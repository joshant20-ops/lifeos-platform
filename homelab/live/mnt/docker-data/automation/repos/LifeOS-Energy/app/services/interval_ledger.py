from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.services.history import read_history
from app.services.octopus import account_tariffs, tariff_prices


def _sample_value(point: dict[str, Any], key: str) -> float:
    grid_import = max(0.0, float(point.get("grid_import_w") or 0.0))
    battery_charge = max(0.0, -float(point.get("battery_power_w") or 0.0))
    if key == "battery_charge_import_w":
        return min(grid_import, battery_charge)
    if key == "domestic_import_w":
        return max(0.0, grid_import - battery_charge)
    return max(0.0, float(point.get(key) or 0.0))


def _integrate(
    points: list[dict[str, Any]],
    start: float,
    end: float,
    key: str,
) -> float:
    relevant = [
        p for p in points
        if start <= float(p["reading_time"]) <= end
    ]
    if not relevant:
        return 0.0

    before = [p for p in points if float(p["reading_time"]) < start]
    after = [p for p in points if float(p["reading_time"]) > end]
    if before:
        relevant.insert(0, before[-1])
    if after:
        relevant.append(after[0])
    if len(relevant) < 2:
        return 0.0

    wh = 0.0
    for a, b in zip(relevant, relevant[1:]):
        left = max(float(a["reading_time"]), start)
        right = min(float(b["reading_time"]), end)
        dt = max(0.0, right - left)
        average_w = (_sample_value(a, key) + _sample_value(b, key)) / 2.0
        wh += average_w * dt / 3600.0
    return wh / 1000.0


def interval_report(hours: int, timezone_name: str) -> dict[str, Any]:
    tz = ZoneInfo(timezone_name)
    now = datetime.now(tz)
    start = now - timedelta(hours=hours)
    points = read_history(hours + 2)
    tariffs = account_tariffs()

    days = []
    cursor = start.date()
    while cursor <= now.date():
        imp = tariff_prices(
            tariffs["import"]["tariff_code"],
            cursor,
            timezone_name,
        )
        exp = (
            tariff_prices(
                tariffs["export"]["tariff_code"],
                cursor,
                timezone_name,
            )
            if tariffs["export"]
            else None
        )
        days.append((imp, exp))
        cursor += timedelta(days=1)

    export_by_start: dict[str, dict[str, Any]] = {}
    if tariffs["export"]:
        for _, exp in days:
            assert exp is not None
            for slot in exp["slots"]:
                export_by_start[slot["valid_from"]] = slot

    rows = []
    totals = {
        "import_kwh": 0.0,
        "domestic_import_kwh": 0.0,
        "battery_charge_import_kwh": 0.0,
        "export_kwh": 0.0,
        "import_cost_gbp": 0.0,
        "domestic_import_cost_gbp": 0.0,
        "battery_charge_import_cost_gbp": 0.0,
        "export_earnings_gbp": 0.0,
    }

    for imp, _ in days:
        for slot in imp["slots"]:
            a = datetime.fromisoformat(slot["valid_from"]).timestamp()
            b = datetime.fromisoformat(slot["valid_to"]).timestamp()
            if b <= start.timestamp() or a >= now.timestamp():
                continue

            import_kwh = _integrate(points, a, b, "grid_import_w")
            domestic_kwh = _integrate(points, a, b, "domestic_import_w")
            battery_kwh = _integrate(points, a, b, "battery_charge_import_w")
            export_kwh = _integrate(points, a, b, "grid_export_w")

            import_rate = slot.get("rate_p_per_kwh")
            export_slot = export_by_start.get(slot["valid_from"])
            export_rate = (
                export_slot.get("rate_p_per_kwh")
                if export_slot
                else (0.0 if not tariffs["export"] else None)
            )

            import_cost = (
                import_kwh * import_rate / 100.0
                if import_rate is not None else None
            )
            domestic_cost = (
                domestic_kwh * import_rate / 100.0
                if import_rate is not None else None
            )
            battery_cost = (
                battery_kwh * import_rate / 100.0
                if import_rate is not None else None
            )
            export_earnings = (
                export_kwh * export_rate / 100.0
                if export_rate is not None else None
            )

            rows.append({
                "valid_from": slot["valid_from"],
                "valid_to": slot["valid_to"],
                "import_kwh": round(import_kwh, 6),
                "domestic_import_kwh": round(domestic_kwh, 6),
                "battery_charge_import_kwh": round(battery_kwh, 6),
                "export_kwh": round(export_kwh, 6),
                "import_p_per_kwh": import_rate,
                "export_p_per_kwh": export_rate,
                "import_cost_gbp": None if import_cost is None else round(import_cost, 6),
                "domestic_import_cost_gbp": None if domestic_cost is None else round(domestic_cost, 6),
                "battery_charge_import_cost_gbp": None if battery_cost is None else round(battery_cost, 6),
                "export_earnings_gbp": None if export_earnings is None else round(export_earnings, 6),
            })

            totals["import_kwh"] += import_kwh
            totals["domestic_import_kwh"] += domestic_kwh
            totals["battery_charge_import_kwh"] += battery_kwh
            totals["export_kwh"] += export_kwh
            if import_cost is not None:
                totals["import_cost_gbp"] += import_cost
            if domestic_cost is not None:
                totals["domestic_import_cost_gbp"] += domestic_cost
            if battery_cost is not None:
                totals["battery_charge_import_cost_gbp"] += battery_cost
            if export_earnings is not None:
                totals["export_earnings_gbp"] += export_earnings

    for key in list(totals):
        totals[key] = round(totals[key], 6)

    totals["net_electricity_cost_gbp"] = round(
        totals["import_cost_gbp"] - totals["export_earnings_gbp"],
        6,
    )
    totals["net_domestic_electricity_cost_gbp"] = round(
        totals["domestic_import_cost_gbp"] - totals["export_earnings_gbp"],
        6,
    )
    totals["average_import_p_per_kwh"] = (
        round(
            totals["domestic_import_cost_gbp"] * 100
            / totals["domestic_import_kwh"],
            3,
        )
        if totals["domestic_import_kwh"]
        else None
    )
    totals["average_export_p_per_kwh"] = (
        round(
            totals["export_earnings_gbp"] * 100 / totals["export_kwh"],
            3,
        )
        if totals["export_kwh"]
        else None
    )

    return {
        "hours": hours,
        "timezone": timezone_name,
        "interval_minutes": 30,
        "method": "integrated 1-minute telemetry against tariff-native half-hour slots",
        "totals": totals,
        "intervals": rows,
    }
