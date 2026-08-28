from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
import json
import statistics
import time
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from app.services.history import connect


OPEN_METEO = "https://api.open-meteo.com/v1/forecast"


class SolarForecastError(RuntimeError):
    pass


def _weather(
    latitude: float,
    longitude: float,
    timezone_name: str,
) -> dict[str, Any]:
    params = {
        "latitude": str(latitude),
        "longitude": str(longitude),
        "hourly": "shortwave_radiation",
        "timezone": timezone_name,
        "past_days": "14",
        "forecast_days": "3",
    }

    request = Request(
        OPEN_METEO + "?" + urlencode(params),
        headers={
            "Accept": "application/json",
            "User-Agent": "LifeOS-Energy/0.3",
        },
    )

    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise SolarForecastError(
            f"Open-Meteo request failed: {exc}"
        ) from exc


def _measured_daily_generation(
    timezone_name: str,
    days: int = 14,
) -> dict[date, float]:
    tz = ZoneInfo(timezone_name)
    cutoff = int(time.time()) - (days + 1) * 86400

    with connect() as connection:
        rows = connection.execute(
            """
            SELECT reading_time, production_w
            FROM telemetry
            WHERE reading_time >= ?
            ORDER BY reading_time ASC
            """,
            (cutoff,),
        ).fetchall()

    totals: dict[date, float] = defaultdict(float)

    previous = None

    for row in rows:
        ts = int(row["reading_time"])
        power = float(row["production_w"] or 0.0)

        if previous is not None:
            previous_ts, previous_power = previous

            delta = ts - previous_ts

            # Ignore long telemetry gaps.
            if 0 < delta <= 300:
                midpoint_power = (
                    previous_power + power
                ) / 2.0

                local_day = datetime.fromtimestamp(
                    previous_ts,
                    tz=tz,
                ).date()

                totals[local_day] += (
                    midpoint_power * delta / 3_600_000
                )

        previous = (ts, power)

    return dict(totals)


def weather_adjusted_solar(
    target_date: date,
    config: dict[str, Any],
) -> dict[str, Any]:
    weather_cfg = config["weather"]
    timezone_name = str(config["site"]["timezone"])

    latitude = float(weather_cfg["latitude"])
    longitude = float(weather_cfg["longitude"])

    payload = _weather(
        latitude,
        longitude,
        timezone_name,
    )

    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    radiation = hourly.get("shortwave_radiation") or []

    if len(times) != len(radiation):
        raise SolarForecastError(
            "Open-Meteo returned inconsistent radiation data"
        )

    radiation_by_day: dict[date, float] = defaultdict(float)
    radiation_by_hour: dict[datetime, float] = {}

    for stamp, watts_m2 in zip(times, radiation, strict=True):
        dt = datetime.fromisoformat(stamp)
        value = max(0.0, float(watts_m2 or 0.0))

        radiation_by_hour[dt] = value

        # W/m2 average for one hour -> kWh/m2.
        radiation_by_day[dt.date()] += value / 1000.0

    measured = _measured_daily_generation(
        timezone_name,
        days=14,
    )

    factors = []

    today = datetime.now(
        ZoneInfo(timezone_name)
    ).date()

    for day, generated_kwh in measured.items():
        if day >= today:
            continue

        radiation_kwh_m2 = radiation_by_day.get(day, 0.0)

        if radiation_kwh_m2 > 0.5 and generated_kwh > 0.1:
            factors.append(
                generated_kwh / radiation_kwh_m2
            )

    if not factors:
        raise SolarForecastError(
            "Not enough overlapping Enphase/weather history "
            "to calibrate solar forecast"
        )

    calibration_factor = statistics.median(factors)

    slots = []

    for slot in range(48):
        hour = slot // 2
        minute = 30 if slot % 2 else 0

        dt = datetime.combine(
            target_date,
            datetime.min.time(),
        ).replace(
            hour=hour,
            minute=minute,
        )

        source_hour = dt.replace(minute=0)

        watts_m2 = radiation_by_hour.get(source_hour, 0.0)

        # Split each hourly radiation forecast into two 30m periods.
        radiation_kwh_m2 = watts_m2 / 1000.0 * 0.5

        solar_kwh = radiation_kwh_m2 * calibration_factor

        slots.append(
            {
                "slot": slot,
                "solar_kwh": round(max(0.0, solar_kwh), 4),
            }
        )

    total = sum(slot["solar_kwh"] for slot in slots)

    return {
        "model": "open_meteo_enphase_calibrated_v1",
        "provider": "Open-Meteo",
        "target_date": target_date.isoformat(),
        "calibration_days": len(factors),
        "calibration_factor": round(calibration_factor, 4),
        "solar_kwh": round(total, 2),
        "slots": slots,
    }
