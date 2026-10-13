from __future__ import annotations

import base64
from datetime import date, datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

API_ROOT = "https://api.octopus.energy/v1"
USER_AGENT = "LifeOS-Energy/0.3"

API_KEY_FILE = Path(
    os.getenv(
        "OCTOPUS_API_KEY_FILE",
        "/run/secrets/lifeos-energy/octopus-api-key",
    )
)

ACCOUNT_FILE = Path(
    os.getenv(
        "OCTOPUS_ACCOUNT_FILE",
        "/run/secrets/lifeos-energy/octopus-account",
    )
)


class OctopusError(RuntimeError):
    pass


def _read_secret(path: Path) -> str:
    if not path.is_file():
        raise OctopusError(f"Missing Octopus secret: {path}")

    value = path.read_text(encoding="utf-8").strip()

    if not value:
        raise OctopusError(f"Empty Octopus secret: {path}")

    return value


def _request_json(
    url: str,
    params: dict[str, str] | None = None,
    authenticated: bool = False,
) -> dict[str, Any]:
    if params:
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}{urlencode(params)}"

    headers = {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }

    if authenticated:
        key = _read_secret(API_KEY_FILE)
        token = base64.b64encode(
            f"{key}:".encode("utf-8")
        ).decode("ascii")
        headers["Authorization"] = f"Basic {token}"

    request = Request(url, headers=headers)

    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise OctopusError(
            f"Octopus API request failed: {exc}"
        ) from exc


def _active_agreement(
    meter_point: dict[str, Any],
    now: datetime,
) -> str | None:
    active = []

    for agreement in meter_point.get("agreements", []):
        code = agreement.get("tariff_code")

        if not code:
            continue

        valid_from = agreement.get("valid_from")
        valid_to = agreement.get("valid_to")

        start = (
            datetime.fromisoformat(
                str(valid_from).replace("Z", "+00:00")
            )
            if valid_from
            else datetime.min.replace(tzinfo=timezone.utc)
        )

        end = (
            datetime.fromisoformat(
                str(valid_to).replace("Z", "+00:00")
            )
            if valid_to
            else datetime.max.replace(tzinfo=timezone.utc)
        )

        if start <= now < end:
            active.append((start, str(code)))

    if not active:
        return None

    active.sort(reverse=True)
    return active[0][1]


def account_tariffs() -> dict[str, Any]:
    account = _read_secret(ACCOUNT_FILE)

    payload = _request_json(
        f"{API_ROOT}/accounts/{account}/",
        authenticated=True,
    )

    now = datetime.now(timezone.utc)

    imports = []
    exports = []

    for prop in payload.get("properties", []):
        if prop.get("moved_out_at"):
            continue

        for point in prop.get("electricity_meter_points", []):
            code = _active_agreement(point, now)

            if not code:
                continue

            item = {
                "mpan": point.get("mpan"),
                "tariff_code": code,
                "is_export": bool(point.get("is_export")),
            }

            if point.get("is_export"):
                exports.append(item)
            else:
                imports.append(item)

    if not imports:
        raise OctopusError(
            "No active electricity import tariff found on Octopus account"
        )

    agile = [
        item for item in imports
        if "AGILE" in item["tariff_code"].upper()
    ]

    import_point = agile[0] if agile else imports[0]
    export_point = exports[0] if exports else None

    return {
        "account": account,
        "import": import_point,
        "export": export_point,
    }


def _product_from_tariff(tariff_code: str) -> str:
    prefix = "E-1R-"

    if not tariff_code.startswith(prefix):
        raise OctopusError(
            f"Unsupported electricity tariff code: {tariff_code}"
        )

    body = tariff_code[len(prefix):]

    if "-" not in body:
        raise OctopusError(
            f"Cannot extract product from tariff: {tariff_code}"
        )

    return body.rsplit("-", 1)[0]


def tariff_prices(
    tariff_code: str,
    target_date: date,
    timezone_name: str,
) -> dict[str, Any]:
    tz = ZoneInfo(timezone_name)

    local_start = datetime.combine(
        target_date,
        time.min,
        tzinfo=tz,
    )

    local_end = local_start + timedelta(days=1)

    utc_start = local_start.astimezone(timezone.utc)
    utc_end = local_end.astimezone(timezone.utc)

    product = _product_from_tariff(tariff_code)

    endpoint = (
        f"{API_ROOT}/products/{product}/"
        f"electricity-tariffs/{tariff_code}/"
        "standard-unit-rates/"
    )

    payload = _request_json(
        endpoint,
        {
            "period_from": utc_start.isoformat().replace("+00:00", "Z"),
            "period_to": utc_end.isoformat().replace("+00:00", "Z"),
            "page_size": "1500",
        },
    )

    rows = payload.get("results", [])

    parsed = []

    for row in rows:
        valid_from = datetime.fromisoformat(
            row["valid_from"].replace("Z", "+00:00")
        )

        valid_to = (
            datetime.fromisoformat(
                row["valid_to"].replace("Z", "+00:00")
            )
            if row.get("valid_to")
            else datetime.max.replace(tzinfo=timezone.utc)
        )

        parsed.append(
            {
                "from": valid_from,
                "to": valid_to,
                "rate": float(row["value_inc_vat"]),
            }
        )

    expected_slots = int(
        (utc_end - utc_start).total_seconds() // 1800
    )

    slots = []

    cursor = utc_start

    for slot_index in range(expected_slots):
        match = None

        for row in parsed:
            if row["from"] <= cursor < row["to"]:
                match = row
                break

        if match is None:
            local_from = cursor.astimezone(tz)
            local_to = (
                cursor + timedelta(minutes=30)
            ).astimezone(tz)

            slots.append(
                {
                    "slot": slot_index,
                    "valid_from": cursor.isoformat(),
                    "valid_to": (
                        cursor + timedelta(minutes=30)
                    ).isoformat(),
                    "local_from": local_from.isoformat(),
                    "local_to": local_to.isoformat(),
                    "rate_p_per_kwh": None,
                    "price_available": False,
                }
            )

            cursor += timedelta(minutes=30)
            continue

        local_from = cursor.astimezone(tz)
        local_to = (cursor + timedelta(minutes=30)).astimezone(tz)

        slots.append(
            {
                "slot": slot_index,
                "valid_from": cursor.isoformat(),
                "valid_to": (
                    cursor + timedelta(minutes=30)
                ).isoformat(),
                "local_from": local_from.isoformat(),
                "local_to": local_to.isoformat(),
                "rate_p_per_kwh": match["rate"],
                "price_available": True,
            }
        )

        cursor += timedelta(minutes=30)

    available_slots = sum(
        1 for slot in slots
        if slot.get("price_available", True)
        and slot.get("rate_p_per_kwh") is not None
    )

    coverage_percent = (
        (available_slots / expected_slots) * 100.0
        if expected_slots
        else 0.0
    )

    if coverage_percent < 90.0:
        raise OctopusError(
            f"Incomplete tariff prices for {tariff_code}: "
            f"{available_slots}/{expected_slots} slots "
            f"({coverage_percent:.1f}%) available; minimum is 90%"
        )

    return {
        "tariff_code": tariff_code,
        "product_code": product,
        "target_date": target_date.isoformat(),
        "slot_count": len(slots),
        "available_slot_count": available_slots,
        "expected_slot_count": expected_slots,
        "coverage_percent": round(coverage_percent, 1),
        "complete": available_slots == expected_slots,
        "slots": slots,
    }


def tomorrow_prices(
    target_date: date,
    timezone_name: str,
) -> dict[str, Any]:
    """
    Return the tariff-native Agile planning horizon:

        23:00 on target_date - 1 day
        through
        23:00 on target_date

    This gives 48 half-hour periods matching the block of
    next-day Agile prices published together by Octopus.
    """

    tariffs = account_tariffs()
    tz = ZoneInfo(timezone_name)

    previous_date = target_date - timedelta(days=1)

    window_start = datetime.combine(
        previous_date,
        time(hour=23),
        tzinfo=tz,
    )

    window_end = datetime.combine(
        target_date,
        time(hour=23),
        tzinfo=tz,
    )

    import_previous = tariff_prices(
        tariffs["import"]["tariff_code"],
        previous_date,
        timezone_name,
    )

    import_target = tariff_prices(
        tariffs["import"]["tariff_code"],
        target_date,
        timezone_name,
    )

    import_slots = (
        import_previous["slots"]
        + import_target["slots"]
    )

    import_by_time = {
        str(slot["local_from"]): slot
        for slot in import_slots
    }

    export_point = tariffs["export"]

    if export_point:
        export_previous = tariff_prices(
            export_point["tariff_code"],
            previous_date,
            timezone_name,
        )

        export_target = tariff_prices(
            export_point["tariff_code"],
            target_date,
            timezone_name,
        )

        export_slots = (
            export_previous["slots"]
            + export_target["slots"]
        )

        export_by_time = {
            str(slot["local_from"]): slot
            for slot in export_slots
        }

        export_tariff_code = export_target["tariff_code"]
        export_product_code = export_target["product_code"]

    else:
        export_by_time = {}
        export_tariff_code = None
        export_product_code = None

    combined = []

    cursor = window_start

    for slot_index in range(48):
        stamp = cursor.isoformat()

        imp = import_by_time.get(stamp)
        exp = export_by_time.get(stamp)

        valid_from = cursor.astimezone(
            timezone.utc
        )

        valid_to = (
            cursor + timedelta(minutes=30)
        ).astimezone(timezone.utc)

        combined.append(
            {
                "slot": slot_index,
                "valid_from": valid_from.isoformat(),
                "valid_to": valid_to.isoformat(),
                "local_from": cursor.isoformat(),
                "local_to": (
                    cursor + timedelta(minutes=30)
                ).isoformat(),
                "import_p_per_kwh": (
                    imp.get("rate_p_per_kwh")
                    if imp
                    else None
                ),
                "export_p_per_kwh": (
                    exp.get("rate_p_per_kwh")
                    if exp
                    else 0.0
                ),
            }
        )

        cursor += timedelta(minutes=30)

    available_slots = sum(
        1
        for slot in combined
        if slot["import_p_per_kwh"] is not None
        and (
            not export_point
            or slot["export_p_per_kwh"] is not None
        )
    )

    return {
        "import_tariff_code": import_target["tariff_code"],
        "import_product_code": import_target["product_code"],
        "export_tariff_code": export_tariff_code,
        "export_product_code": export_product_code,
        "export_active": export_point is not None,
        "slot_count": available_slots,
        "expected_slot_count": 48,
        "coverage_percent": round(
            available_slots / 48 * 100.0,
            1,
        ),
        "complete": available_slots == 48,
        "planning_window_start": window_start.isoformat(),
        "planning_window_end": window_end.isoformat(),
        "slots": combined,
    }
