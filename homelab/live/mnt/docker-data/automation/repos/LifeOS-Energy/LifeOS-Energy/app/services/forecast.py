from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
import statistics
import time
from typing import Any
from zoneinfo import ZoneInfo

from app.services.history import connect
from app.services.solar_forecast import weather_adjusted_solar


def _read_history(days: int = 35) -> list[dict[str, Any]]:
    cutoff = int(time.time()) - days * 86400

    with connect() as connection:
        rows = connection.execute(
            """
            SELECT
                reading_time,
                production_w,
                consumption_w
            FROM telemetry
            WHERE reading_time >= ?
            ORDER BY reading_time ASC
            """,
            (cutoff,),
        ).fetchall()

    return [dict(row) for row in rows]


def _default_load(slot: int) -> float:
    hour = slot / 2.0

    if 0 <= hour < 5:
        kw = 0.35
    elif 5 <= hour < 8:
        kw = 0.75
    elif 8 <= hour < 16:
        kw = 0.45
    elif 16 <= hour < 21:
        kw = 1.10
    else:
        kw = 0.50

    return kw * 0.5


def _default_solar(slot: int, solar_capacity_kw: float) -> float:
    from math import exp

    hour = slot / 2.0

    if hour < 5 or hour > 21:
        return 0.0

    centre = 13.0
    width = 3.5

    kw = solar_capacity_kw * exp(
        -((hour - centre) ** 2) / (2 * width**2)
    )

    return kw * 0.5



def build_half_hour_forecast(
    target_date: date,
    timezone_name: str,
    solar_capacity_kw: float,
    config: dict[str, Any],
) -> dict[str, Any]:
    tz = ZoneInfo(timezone_name)
    rows = _read_history(35)

    daily: dict[
        tuple[str, int],
        dict[str, list[float]]
    ] = defaultdict(
        lambda: {
            "production": [],
            "consumption": [],
        }
    )

    for row in rows:
        local = datetime.fromtimestamp(
            int(row["reading_time"]),
            tz=tz,
        )

        slot = local.hour * 2 + local.minute // 30
        key = (local.date().isoformat(), slot)

        daily[key]["production"].append(
            float(row["production_w"] or 0.0)
        )

        daily[key]["consumption"].append(
            float(row["consumption_w"] or 0.0)
        )

    consumption_samples: dict[
        int,
        list[tuple[date, float]]
    ] = defaultdict(list)

    for (day_string, slot), values in daily.items():
        day = date.fromisoformat(day_string)

        if values["consumption"]:
            consumption_samples[slot].append(
                (
                    day,
                    statistics.mean(
                        values["consumption"]
                    ) / 1000 * 0.5,
                )
            )

    target_weekday = target_date.weekday()

    solar = weather_adjusted_solar(
        target_date,
        config,
    )

    solar_by_slot = {
        int(row["slot"]): float(row["solar_kwh"])
        for row in solar["slots"]
    }

    slots = []

    for slot in range(48):
        same_weekday = [
            value
            for sample_date, value
            in consumption_samples.get(slot, [])
            if sample_date.weekday() == target_weekday
            and sample_date < target_date
        ]

        all_history = [
            value
            for sample_date, value
            in consumption_samples.get(slot, [])
            if sample_date < target_date
        ]

        if len(same_weekday) >= 2:
            load_kwh = statistics.median(
                same_weekday
            )
            load_source = "same_weekday_history"
        elif all_history:
            load_kwh = statistics.median(
                all_history
            )
            load_source = "recent_history"
        else:
            load_kwh = _default_load(slot)
            load_source = "fallback"

        slots.append(
            {
                "slot": slot,
                "solar_kwh": round(
                    solar_by_slot.get(slot, 0.0),
                    4,
                ),
                "load_kwh": round(
                    max(0.0, load_kwh),
                    4,
                ),
                "solar_source": solar["model"],
                "load_source": load_source,
            }
        )


    # Add timezone-aware timestamps used to align forecast
    # slots with Octopus half-hour tariff periods.
    from datetime import datetime as _dt, time as _time, timedelta as _td
    from zoneinfo import ZoneInfo as _ZoneInfo

    _tz = _ZoneInfo(timezone_name)
    _day_start = _dt.combine(
        target_date,
        _time.min,
        tzinfo=_tz,
    )

    for _index, _slot in enumerate(slots):
        _slot_start = _day_start + _td(minutes=30 * _index)
        _slot_end = _slot_start + _td(minutes=30)
        _slot["local_from"] = _slot_start.isoformat()
        _slot["local_to"] = _slot_end.isoformat()

    return {
        "target_date": target_date.isoformat(),
        "model": "weather_load_half_hour_v1",
        "history_rows": len(rows),
        "solar": solar,
        "slots": slots,
        "totals": {
            "solar_kwh": round(
                sum(x["solar_kwh"] for x in slots),
                2,
            ),
            "load_kwh": round(
                sum(x["load_kwh"] for x in slots),
                2,
            ),
        },
    }
