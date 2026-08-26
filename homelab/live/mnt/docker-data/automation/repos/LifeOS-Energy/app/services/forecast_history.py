from __future__ import annotations

from contextlib import closing
from datetime import date, datetime, time, timedelta
import json
import time as time_module
from typing import Any
from zoneinfo import ZoneInfo

from app.services.history import connect


MAX_CONTIGUOUS_GAP_SECONDS = 300


def _ensure_tables() -> None:
    with closing(connect()) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS solar_forecasts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_date TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                model TEXT,
                provider TEXT,
                calibration_days INTEGER,
                calibration_factor REAL,
                forecast_kwh REAL NOT NULL,
                slots_json TEXT NOT NULL,
                source TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                UNIQUE(target_date, generated_at)
            )
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_solar_forecasts_target_date
            ON solar_forecasts(target_date)
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_solar_forecasts_generated_at
            ON solar_forecasts(generated_at)
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS solar_forecast_actuals (
                forecast_id INTEGER PRIMARY KEY,
                actual_kwh REAL,
                telemetry_count INTEGER NOT NULL,
                telemetry_coverage_percent REAL NOT NULL,
                forecast_energy_coverage_percent REAL NOT NULL,
                missing_forecast_kwh REAL NOT NULL,
                gap_count INTEGER NOT NULL,
                largest_gap_seconds INTEGER NOT NULL,
                maturity_status TEXT NOT NULL,
                valid INTEGER NOT NULL,
                error_kwh REAL,
                absolute_error_kwh REAL,
                error_percent REAL,
                evaluated_at INTEGER NOT NULL,
                FOREIGN KEY(forecast_id)
                    REFERENCES solar_forecasts(id)
                    ON DELETE CASCADE
            )
            """
        )

        connection.commit()


def record_solar_forecast(
    plan: dict[str, Any],
    slots: list[dict[str, Any]],
    source: str = "plan_generation",
) -> int:
    _ensure_tables()

    forecast = plan.get("forecast") or {}

    target_date = str(plan["target_date"])
    generated_at = str(plan["generated_at"])

    model = (
        forecast.get("solar_model")
        or forecast.get("model")
    )
    provider = (
        forecast.get("solar_provider")
        or forecast.get("provider")
    )

    calibration_days = forecast.get("solar_calibration_days")

    solar_section = forecast.get("solar") or {}
    calibration_factor = solar_section.get("calibration_factor")

    forecast_kwh = float(forecast["solar_kwh"])

    with closing(connect()) as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO solar_forecasts (
                target_date,
                generated_at,
                model,
                provider,
                calibration_days,
                calibration_factor,
                forecast_kwh,
                slots_json,
                source,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                target_date,
                generated_at,
                str(model) if model is not None else None,
                str(provider) if provider is not None else None,
                (
                    int(calibration_days)
                    if calibration_days is not None
                    else None
                ),
                (
                    float(calibration_factor)
                    if calibration_factor is not None
                    else None
                ),
                forecast_kwh,
                json.dumps(slots, separators=(",", ":")),
                source,
                int(time_module.time()),
            ),
        )

        row = connection.execute(
            """
            SELECT id
            FROM solar_forecasts
            WHERE target_date = ?
              AND generated_at = ?
            """,
            (target_date, generated_at),
        ).fetchone()

        connection.commit()

    if row is None:
        raise RuntimeError(
            "Solar forecast was not persisted"
        )

    return int(row["id"])


def _parse_slot_start(
    slot: dict[str, Any],
    slot_index: int,
    target_date: date,
    tz: ZoneInfo,
) -> datetime:
    local_from = slot.get("local_from")

    if local_from:
        parsed = datetime.fromisoformat(str(local_from))

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tz)

        return parsed.astimezone(tz)

    return datetime.combine(
        target_date,
        time.min,
        tzinfo=tz,
    ) + timedelta(minutes=30 * slot_index)


def _parse_slot_end(
    slot: dict[str, Any],
    slot_start: datetime,
    tz: ZoneInfo,
) -> datetime:
    local_to = slot.get("local_to")

    if local_to:
        parsed = datetime.fromisoformat(str(local_to))

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tz)

        return parsed.astimezone(tz)

    return slot_start + timedelta(minutes=30)


def _forecast_energy_between(
    slots: list[dict[str, Any]],
    target_date: date,
    tz: ZoneInfo,
    interval_start: datetime,
    interval_end: datetime,
) -> float:
    total = 0.0

    for index, slot in enumerate(slots):
        solar_kwh = max(
            0.0,
            float(slot.get("solar_kwh") or 0.0),
        )

        if solar_kwh <= 0:
            continue

        slot_start = _parse_slot_start(
            slot,
            index,
            target_date,
            tz,
        )
        slot_end = _parse_slot_end(
            slot,
            slot_start,
            tz,
        )

        overlap_start = max(
            slot_start,
            interval_start,
        )
        overlap_end = min(
            slot_end,
            interval_end,
        )

        overlap_seconds = (
            overlap_end - overlap_start
        ).total_seconds()

        slot_seconds = (
            slot_end - slot_start
        ).total_seconds()

        if overlap_seconds > 0 and slot_seconds > 0:
            total += solar_kwh * (
                overlap_seconds / slot_seconds
            )

    return total


def _evaluate_forecast(
    forecast: dict[str, Any],
    timezone_name: str,
) -> dict[str, Any]:
    tz = ZoneInfo(timezone_name)

    target_date = date.fromisoformat(
        str(forecast["target_date"])
    )

    today = datetime.now(tz).date()

    if target_date >= today:
        return {
            "actual_kwh": None,
            "telemetry_count": 0,
            "telemetry_coverage_percent": 0.0,
            "forecast_energy_coverage_percent": 0.0,
            "missing_forecast_kwh": 0.0,
            "gap_count": 0,
            "largest_gap_seconds": 0,
            "maturity_status": "NOT_MATURE",
            "valid": False,
            "error_kwh": None,
            "absolute_error_kwh": None,
            "error_percent": None,
        }

    day_start = datetime.combine(
        target_date,
        time.min,
        tzinfo=tz,
    )

    next_day = day_start + timedelta(days=1)

    start_ts = int(day_start.timestamp())
    end_ts = int(next_day.timestamp())

    with closing(connect()) as connection:
        rows = connection.execute(
            """
            SELECT
                reading_time,
                production_w
            FROM telemetry
            WHERE reading_time >= ?
              AND reading_time < ?
            ORDER BY reading_time ASC
            """,
            (start_ts, end_ts),
        ).fetchall()

    slots = json.loads(
        str(forecast["slots_json"])
    )

    forecast_kwh = float(
        forecast["forecast_kwh"]
    )

    if not rows:
        return {
            "actual_kwh": None,
            "telemetry_count": 0,
            "telemetry_coverage_percent": 0.0,
            "forecast_energy_coverage_percent": 0.0,
            "missing_forecast_kwh": forecast_kwh,
            "gap_count": 1,
            "largest_gap_seconds": end_ts - start_ts,
            "maturity_status": "NO_TELEMETRY",
            "valid": False,
            "error_kwh": None,
            "absolute_error_kwh": None,
            "error_percent": None,
        }

    actual_kwh = 0.0
    integrated_seconds = 0
    gaps: list[tuple[datetime, datetime]] = []

    first_ts = int(rows[0]["reading_time"])

    if first_ts - start_ts > MAX_CONTIGUOUS_GAP_SECONDS:
        gaps.append(
            (
                day_start,
                datetime.fromtimestamp(first_ts, tz),
            )
        )

    previous_ts: int | None = None
    previous_power: float | None = None

    for row in rows:
        ts = int(row["reading_time"])
        power = max(
            0.0,
            float(row["production_w"] or 0.0),
        )

        if previous_ts is not None and previous_power is not None:
            delta = ts - previous_ts

            if 0 < delta <= MAX_CONTIGUOUS_GAP_SECONDS:
                midpoint_power = (
                    previous_power + power
                ) / 2.0

                actual_kwh += (
                    midpoint_power
                    * delta
                    / 3_600_000
                )

                integrated_seconds += delta

            elif delta > MAX_CONTIGUOUS_GAP_SECONDS:
                gaps.append(
                    (
                        datetime.fromtimestamp(
                            previous_ts,
                            tz,
                        ),
                        datetime.fromtimestamp(
                            ts,
                            tz,
                        ),
                    )
                )

        previous_ts = ts
        previous_power = power

    last_ts = int(rows[-1]["reading_time"])

    if end_ts - last_ts > MAX_CONTIGUOUS_GAP_SECONDS:
        gaps.append(
            (
                datetime.fromtimestamp(last_ts, tz),
                next_day,
            )
        )

    missing_forecast_kwh = sum(
        _forecast_energy_between(
            slots,
            target_date,
            tz,
            gap_start,
            gap_end,
        )
        for gap_start, gap_end in gaps
    )

    day_seconds = end_ts - start_ts

    telemetry_coverage = (
        integrated_seconds / day_seconds * 100.0
        if day_seconds > 0
        else 0.0
    )

    if forecast_kwh > 0:
        forecast_energy_coverage = max(
            0.0,
            min(
                100.0,
                (
                    forecast_kwh
                    - missing_forecast_kwh
                )
                / forecast_kwh
                * 100.0,
            ),
        )
    else:
        forecast_energy_coverage = 100.0

    allowable_missing_kwh = max(
        0.05,
        forecast_kwh * 0.01,
    )

    valid = (
        missing_forecast_kwh
        <= allowable_missing_kwh
    )

    largest_gap_seconds = 0

    if gaps:
        largest_gap_seconds = max(
            int((end - start).total_seconds())
            for start, end in gaps
        )

    if valid:
        error_kwh = forecast_kwh - actual_kwh
        absolute_error_kwh = abs(error_kwh)

        error_percent = (
            error_kwh / actual_kwh * 100.0
            if actual_kwh > 0
            else None
        )

        maturity_status = "VALID"
    else:
        error_kwh = None
        absolute_error_kwh = None
        error_percent = None
        maturity_status = "INCOMPLETE_ACTUAL"

    return {
        "actual_kwh": round(actual_kwh, 4),
        "telemetry_count": len(rows),
        "telemetry_coverage_percent": round(
            telemetry_coverage,
            2,
        ),
        "forecast_energy_coverage_percent": round(
            forecast_energy_coverage,
            2,
        ),
        "missing_forecast_kwh": round(
            missing_forecast_kwh,
            4,
        ),
        "gap_count": len(gaps),
        "largest_gap_seconds": largest_gap_seconds,
        "maturity_status": maturity_status,
        "valid": valid,
        "error_kwh": (
            round(error_kwh, 4)
            if error_kwh is not None
            else None
        ),
        "absolute_error_kwh": (
            round(absolute_error_kwh, 4)
            if absolute_error_kwh is not None
            else None
        ),
        "error_percent": (
            round(error_percent, 2)
            if error_percent is not None
            else None
        ),
    }


def _save_evaluation(
    forecast_id: int,
    result: dict[str, Any],
) -> None:
    with closing(connect()) as connection:
        connection.execute(
            """
            INSERT INTO solar_forecast_actuals (
                forecast_id,
                actual_kwh,
                telemetry_count,
                telemetry_coverage_percent,
                forecast_energy_coverage_percent,
                missing_forecast_kwh,
                gap_count,
                largest_gap_seconds,
                maturity_status,
                valid,
                error_kwh,
                absolute_error_kwh,
                error_percent,
                evaluated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(forecast_id) DO UPDATE SET
                actual_kwh = excluded.actual_kwh,
                telemetry_count = excluded.telemetry_count,
                telemetry_coverage_percent =
                    excluded.telemetry_coverage_percent,
                forecast_energy_coverage_percent =
                    excluded.forecast_energy_coverage_percent,
                missing_forecast_kwh =
                    excluded.missing_forecast_kwh,
                gap_count = excluded.gap_count,
                largest_gap_seconds =
                    excluded.largest_gap_seconds,
                maturity_status =
                    excluded.maturity_status,
                valid = excluded.valid,
                error_kwh = excluded.error_kwh,
                absolute_error_kwh =
                    excluded.absolute_error_kwh,
                error_percent =
                    excluded.error_percent,
                evaluated_at =
                    excluded.evaluated_at
            """,
            (
                forecast_id,
                result["actual_kwh"],
                result["telemetry_count"],
                result["telemetry_coverage_percent"],
                result["forecast_energy_coverage_percent"],
                result["missing_forecast_kwh"],
                result["gap_count"],
                result["largest_gap_seconds"],
                result["maturity_status"],
                1 if result["valid"] else 0,
                result["error_kwh"],
                result["absolute_error_kwh"],
                result["error_percent"],
                int(time_module.time()),
            ),
        )

        connection.commit()


def forecast_error_report(
    timezone_name: str,
    limit: int = 30,
) -> dict[str, Any]:
    _ensure_tables()

    with closing(connect()) as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM solar_forecasts
            ORDER BY
                target_date DESC,
                generated_at ASC
            """
        ).fetchall()

    forecasts = [dict(row) for row in rows]

    evaluated: list[dict[str, Any]] = []

    for forecast in forecasts:
        result = _evaluate_forecast(
            forecast,
            timezone_name,
        )

        _save_evaluation(
            int(forecast["id"]),
            result,
        )

        evaluated.append(
            {
                "forecast_id": int(forecast["id"]),
                "target_date": forecast["target_date"],
                "generated_at": forecast["generated_at"],
                "source": forecast["source"],
                "model": forecast["model"],
                "provider": forecast["provider"],
                "calibration_days": forecast["calibration_days"],
                "forecast_kwh": round(
                    float(forecast["forecast_kwh"]),
                    4,
                ),
                **result,
            }
        )

    # Headline statistics deliberately use the earliest
    # persisted forecast for each target date. This avoids
    # repeated plan generations overweighting one day and
    # prevents later refreshes from benefiting from hindsight.
    selected_by_date: dict[str, dict[str, Any]] = {}

    for sample in sorted(
        evaluated,
        key=lambda row: (
            row["target_date"],
            row["generated_at"],
        ),
    ):
        selected_by_date.setdefault(
            sample["target_date"],
            sample,
        )

    selected = sorted(
        selected_by_date.values(),
        key=lambda row: row["target_date"],
        reverse=True,
    )

    selected = selected[:limit]

    valid_samples = [
        sample
        for sample in selected
        if sample["valid"]
    ]

    invalid_samples = [
        sample
        for sample in selected
        if (
            not sample["valid"]
            and sample["maturity_status"]
            != "NOT_MATURE"
        )
    ]

    not_mature_samples = [
        sample
        for sample in selected
        if sample["maturity_status"]
        == "NOT_MATURE"
    ]

    if valid_samples:
        mae_kwh = sum(
            sample["absolute_error_kwh"]
            for sample in valid_samples
        ) / len(valid_samples)

        bias_kwh = sum(
            sample["error_kwh"]
            for sample in valid_samples
        ) / len(valid_samples)

        percentage_samples = [
            sample["error_percent"]
            for sample in valid_samples
            if sample["error_percent"] is not None
        ]

        mape_percent = (
            sum(abs(value) for value in percentage_samples)
            / len(percentage_samples)
            if percentage_samples
            else None
        )
    else:
        mae_kwh = None
        bias_kwh = None
        mape_percent = None

    return {
        "strategy": "earliest_forecast_per_target_date",
        "forecast_rows_total": len(evaluated),
        "selected_days": len(selected),
        "valid_sample_count": len(valid_samples),
        "invalid_sample_count": len(invalid_samples),
        "not_mature_count": len(not_mature_samples),
        "metrics": {
            "mae_kwh": (
                round(mae_kwh, 4)
                if mae_kwh is not None
                else None
            ),
            "bias_kwh": (
                round(bias_kwh, 4)
                if bias_kwh is not None
                else None
            ),
            "mape_percent": (
                round(mape_percent, 2)
                if mape_percent is not None
                else None
            ),
        },
        "samples": selected,
    }
