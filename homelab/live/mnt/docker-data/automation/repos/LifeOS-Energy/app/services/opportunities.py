from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from app.services.octopus import OctopusError, account_tariffs, tariff_prices


LOGGER = logging.getLogger("lifeos-energy")
STATE_DIR = Path(os.getenv("ENERGY_OPPORTUNITY_STATE_DIR", "/data"))
CURRENT_PATH = STATE_DIR / "current-energy-opportunities.json"
LEDGER_PATH = STATE_DIR / "energy-opportunities.json"
REFRESH_SECONDS = int(os.getenv("ENERGY_OPPORTUNITY_REFRESH_SECONDS", "300"))
SOURCE = "lifeos_energy_octopus_api"

_task: asyncio.Task[None] | None = None
_stop_event: asyncio.Event | None = None
_last_error: str | None = None


@dataclass(frozen=True)
class RateSlot:
    start: datetime
    end: datetime
    price_p_per_kwh: float


@dataclass(frozen=True)
class EnergyOpportunity:
    opportunity_id: str
    type: str
    severity: str
    start: str
    end: str
    local_date: str
    duration_minutes: int
    minimum_price_p_per_kwh: float
    slots: tuple[dict[str, object], ...]
    detected_at: str
    source: str


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timezone-aware datetime required")
    return value.isoformat()


def group_negative_import_slots(
    slots: Iterable[RateSlot], *, detected_at: datetime, source: str = SOURCE
) -> list[EnergyOpportunity]:
    ordered = sorted(
        (slot for slot in slots if slot.price_p_per_kwh < 0),
        key=lambda slot: slot.start,
    )
    groups: list[list[RateSlot]] = []
    for slot in ordered:
        if groups and groups[-1][-1].end == slot.start:
            groups[-1].append(slot)
        else:
            groups.append([slot])

    opportunities = []
    for group in groups:
        start, end = group[0].start, group[-1].end
        identity = "|".join(
            f"{_iso(slot.start)}|{_iso(slot.end)}|{slot.price_p_per_kwh:.6f}"
            for slot in group
        )
        opportunity_id = "negative-import-" + hashlib.sha256(
            identity.encode("utf-8")
        ).hexdigest()[:20]
        opportunities.append(
            EnergyOpportunity(
                opportunity_id=opportunity_id,
                type="negative_import_price",
                severity="opportunity",
                start=_iso(start),
                end=_iso(end),
                local_date=start.date().isoformat(),
                duration_minutes=int((end - start).total_seconds() // 60),
                minimum_price_p_per_kwh=min(
                    slot.price_p_per_kwh for slot in group
                ),
                slots=tuple(
                    {
                        "start": _iso(slot.start),
                        "end": _iso(slot.end),
                        "price_p_per_kwh": slot.price_p_per_kwh,
                    }
                    for slot in group
                ),
                detected_at=_iso(detected_at),
                source=source,
            )
        )
    return opportunities


def build_projection(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {
        str(record["opportunity_id"]): record
        for record in records
        if isinstance(record, dict) and record.get("opportunity_id")
    }
    valid = list(by_id.values())
    valid.sort(
        key=lambda record: (
            str(record.get("start", "")),
            str(record.get("opportunity_id", "")),
        )
    )
    ids = [str(record["opportunity_id"]) for record in valid]
    if not valid:
        return {
            "state": "clear",
            "count": 0,
            "attention_id": "",
            "opportunity_ids": [],
            "kind": "energy_opportunity",
            "severity": "info",
            "summary": "No negative-price energy opportunity",
            "opportunities": [],
        }

    first = valid[0]
    minimums = [
        float(record["minimum_price_p_per_kwh"])
        for record in valid
        if record.get("minimum_price_p_per_kwh") is not None
    ]
    minimum = min(minimums) if minimums else None
    summary = f"Negative-price electricity opportunity: {len(valid)} period"
    if len(valid) != 1:
        summary += "s"
    if minimum is not None:
        summary += f", minimum {minimum:g} p/kWh"
    return {
        "state": "attention",
        "count": len(valid),
        "attention_id": str(first["opportunity_id"]),
        "opportunity_ids": ids,
        "kind": "energy_opportunity",
        "severity": str(first.get("severity") or "opportunity"),
        "summary": summary,
        "start": str(first.get("start", "")),
        "end": str(first.get("end", "")),
        "minimum_price_p_per_kwh": minimum,
        "source": str(first.get("source") or ""),
        "opportunities": valid,
    }


def _atomic_write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    fd, name = tempfile.mkstemp(
        prefix=path.name + ".", dir=str(path.parent), text=True
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def _load_json(path: Path, default: object) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _price_slots(timezone_name: str) -> list[RateSlot]:
    tz = ZoneInfo(timezone_name)
    today = datetime.now(tz).date()
    tariff = account_tariffs()["import"]["tariff_code"]
    by_start: dict[str, RateSlot] = {}
    for target in (today, today + timedelta(days=1)):
        try:
            prices = tariff_prices(tariff, target, timezone_name)
        except OctopusError:
            if target == today:
                raise
            LOGGER.info("tomorrow_opportunity_prices_not_published target=%s", target)
            continue
        for raw in prices["slots"]:
            rate = raw.get("rate_p_per_kwh")
            if rate is None or not raw.get("price_available", True):
                continue
            start = datetime.fromisoformat(str(raw["valid_from"]))
            end = datetime.fromisoformat(str(raw["valid_to"]))
            by_start[_iso(start)] = RateSlot(start, end, float(rate))
    return list(by_start.values())


def refresh_opportunities(timezone_name: str) -> dict[str, Any]:
    global _last_error
    now = datetime.now(ZoneInfo(timezone_name))
    opportunities = group_negative_import_slots(
        (
            slot
            for slot in _price_slots(timezone_name)
            if slot.end > now.astimezone(slot.end.tzinfo)
        ),
        detected_at=now,
    )
    records = [asdict(item) for item in opportunities]
    ledger = _load_json(LEDGER_PATH, {})
    if not isinstance(ledger, dict):
        ledger = {}
    for record in records:
        opportunity_id = str(record["opportunity_id"])
        previous = ledger.get(opportunity_id)
        first_detected = (
            previous.get("first_detected_at")
            if isinstance(previous, dict)
            else record["detected_at"]
        )
        ledger[opportunity_id] = {
            **record,
            "first_detected_at": first_detected,
            "last_detected_at": record["detected_at"],
        }
    _atomic_write(CURRENT_PATH, records)
    _atomic_write(LEDGER_PATH, ledger)
    _last_error = None
    return build_projection(records)


def current_projection() -> dict[str, Any]:
    records = _load_json(CURRENT_PATH, [])
    if not isinstance(records, list):
        records = []
    projection = build_projection(records)
    projection["available"] = _last_error is None
    if _last_error:
        projection["state"] = "unavailable"
        projection["error"] = _last_error
    return projection


async def opportunity_loop(
    timezone_name: str, stop_event: asyncio.Event
) -> None:
    global _last_error
    while not stop_event.is_set():
        try:
            projection = await asyncio.to_thread(
                refresh_opportunities, timezone_name
            )
            LOGGER.info(
                "energy_opportunities_refreshed count=%s attention_id=%s",
                projection["count"],
                projection["attention_id"] or "none",
            )
        except Exception as exc:
            _last_error = f"{type(exc).__name__}: {exc}"
            LOGGER.warning("energy_opportunities_unavailable error=%s", exc)
        try:
            await asyncio.wait_for(
                stop_event.wait(), timeout=max(30, REFRESH_SECONDS)
            )
        except TimeoutError:
            continue


async def start_opportunity_scheduler(timezone_name: str) -> None:
    global _task, _stop_event
    if _task is not None and not _task.done():
        return
    _stop_event = asyncio.Event()
    _task = asyncio.create_task(
        opportunity_loop(timezone_name, _stop_event),
        name="lifeos-energy-opportunities",
    )


async def stop_opportunity_scheduler() -> None:
    global _task, _stop_event
    if _stop_event is not None:
        _stop_event.set()
    if _task is not None:
        try:
            await asyncio.wait_for(_task, timeout=10)
        except TimeoutError:
            _task.cancel()
    _task = None
    _stop_event = None
