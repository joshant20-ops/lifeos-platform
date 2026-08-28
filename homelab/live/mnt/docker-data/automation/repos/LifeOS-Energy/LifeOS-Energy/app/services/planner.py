from __future__ import annotations

from app.services.forecast_history import record_solar_forecast

from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.services.forecast import build_half_hour_forecast
from app.services.octopus import tomorrow_prices


PLAN_PATH = Path(
    os.getenv(
        "ENERGY_TOMORROW_PLAN",
        "/data/tomorrow-plan.json",
    )
)


def _states(minimum: float, maximum: float, step: float) -> list[float]:
    count = int(round((maximum - minimum) / step))
    return [
        round(minimum + i * step, 3)
        for i in range(count + 1)
    ]


def _optimise(
    price_slots: list[dict[str, Any]],
    forecast_slots: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    energy = config["energy"]
    planner = config["planner"]

    capacity = float(energy["battery_capacity_kwh"])
    min_soc = float(energy["battery_minimum_percent"])
    max_soc = float(energy["battery_maximum_percent"])
    start_soc = float(planner["planning_start_soc_percent"])

    min_kwh = capacity * min_soc / 100
    max_kwh = capacity * max_soc / 100
    start_kwh = capacity * start_soc / 100

    charge_kw = float(planner["maximum_charge_kw"])
    discharge_kw = float(planner["maximum_discharge_kw"])
    charge_eff = float(planner["charge_efficiency"])
    discharge_eff = float(planner["discharge_efficiency"])
    state_step = float(planner["state_step_kwh"])

    states = _states(min_kwh, max_kwh, state_step)

    start_state = min(
        states,
        key=lambda value: abs(value - start_kwh),
    )

    infinity = float("inf")
    cost = {state: infinity for state in states}
    cost[start_state] = 0.0

    parents: list[dict[float, tuple[float, dict[str, Any]]]] = []

    # Match forecast and tariff data by actual half-hour timestamp,
    # not sequential slot number. This remains correct when one or
    # more tariff periods are temporarily unavailable.
    forecast_by_time = {
        str(row.get("local_from")): row
        for row in forecast_slots
        if row.get("local_from")
    }

    for price in price_slots:
        local_from = str(price.get("local_from") or "")
        forecast = forecast_by_time.get(local_from)

        if forecast is None:
            raise RuntimeError(
                "No forecast data for tariff period "
                f"{local_from or price.get('valid_from')}"
            )

        solar = float(forecast["solar_kwh"])
        load = float(forecast["load_kwh"])
        import_rate = float(price["import_p_per_kwh"])
        export_rate = float(price["export_p_per_kwh"])

        next_cost = {state: infinity for state in states}
        parent: dict[float, tuple[float, dict[str, Any]]] = {}

        for previous in states:
            previous_cost = cost[previous]

            if previous_cost == infinity:
                continue

            for following in states:
                delta = following - previous

                if delta >= 0:
                    battery_charge_ac = delta / charge_eff
                    battery_discharge_ac = 0.0

                    if battery_charge_ac > charge_kw * 0.5 + 1e-9:
                        continue
                else:
                    battery_charge_ac = 0.0
                    battery_discharge_ac = (-delta) * discharge_eff

                    if battery_discharge_ac > discharge_kw * 0.5 + 1e-9:
                        continue

                grid_kwh = (
                    load
                    - solar
                    + battery_charge_ac
                    - battery_discharge_ac
                )

                import_kwh = max(0.0, grid_kwh)
                export_kwh = max(0.0, -grid_kwh)

                slot_cost = (
                    import_kwh * import_rate
                    - export_kwh * export_rate
                )

                candidate = previous_cost + slot_cost

                if candidate >= next_cost[following]:
                    continue

                if delta > 0.05:
                    if solar > load and import_kwh < 0.05:
                        action = "SOLAR_CHARGE"
                    elif import_kwh > 0.05:
                        action = "GRID_CHARGE"
                    else:
                        action = "CHARGE"
                elif delta < -0.05:
                    if export_kwh > 0.05:
                        action = "EXPORT_DISCHARGE"
                    else:
                        action = "BATTERY_SUPPORT"
                else:
                    if export_kwh > 0.05:
                        action = "EXPORT"
                    elif import_kwh > 0.05:
                        action = "GRID_IMPORT"
                    else:
                        action = "HOLD"

                next_cost[following] = candidate

                parent[following] = (
                    previous,
                    {
                        "action": action,
                        "solar_kwh": round(solar, 3),
                        "load_kwh": round(load, 3),
                        "battery_start_kwh": round(previous, 2),
                        "battery_end_kwh": round(following, 2),
                        "battery_start_soc_percent": round(
                            previous / capacity * 100,
                            1,
                        ),
                        "battery_end_soc_percent": round(
                            following / capacity * 100,
                            1,
                        ),
                        "grid_import_kwh": round(import_kwh, 3),
                        "grid_export_kwh": round(export_kwh, 3),
                        "import_p_per_kwh": round(import_rate, 3),
                        "export_p_per_kwh": round(export_rate, 3),
                        "slot_net_cost_pence": round(slot_cost, 3),
                    },
                )

        parents.append(parent)
        cost = next_cost

    end_state = min(cost, key=cost.get)
    total_cost_pence = cost[end_state]

    reversed_plan = []
    current = end_state

    for index in range(len(price_slots) - 1, -1, -1):
        previous, detail = parents[index][current]

        detail["valid_from"] = price_slots[index]["valid_from"]
        detail["valid_to"] = price_slots[index]["valid_to"]
        detail["local_from"] = price_slots[index]["local_from"]
        detail["local_to"] = price_slots[index]["local_to"]

        reversed_plan.append(detail)
        current = previous

    slots = list(reversed(reversed_plan))

    return {
        "model": "battery_dp_v1",
        "starting_soc_percent": start_soc,
        "minimum_soc_percent": min_soc,
        "maximum_soc_percent": max_soc,
        "ending_soc_percent": round(end_state / capacity * 100, 1),
        "totals": {
            "solar_kwh": round(
                sum(item["solar_kwh"] for item in slots),
                2,
            ),
            "load_kwh": round(
                sum(item["load_kwh"] for item in slots),
                2,
            ),
            "grid_import_kwh": round(
                sum(item["grid_import_kwh"] for item in slots),
                2,
            ),
            "grid_export_kwh": round(
                sum(item["grid_export_kwh"] for item in slots),
                2,
            ),
            "net_energy_cost_pence": round(total_cost_pence, 2),
            "net_energy_cost_gbp": round(total_cost_pence / 100, 2),
        },
        "slots": slots,
    }


def generate_plan(
    config: dict[str, Any],
    target_date: date | None = None,
) -> dict[str, Any]:
    timezone_name = str(config["site"]["timezone"])
    tz = ZoneInfo(timezone_name)

    if target_date is None:
        target_date = datetime.now(tz).date() + timedelta(days=1)

    price_data = tomorrow_prices(
        target_date,
        timezone_name,
    )

    forecast = build_half_hour_forecast(
        target_date,
        timezone_name,
        float(config["energy"]["solar_capacity_kw"]),
        config,
    )

    # Build the same 23:00 -> 23:00 horizon as the Agile
    # tariff window. Two slots come from the previous local
    # day (23:00 and 23:30), followed by the first 46 slots
    # of the target date.
    previous_forecast = build_half_hour_forecast(
        target_date - timedelta(days=1),
        timezone_name,
        float(config["energy"]["solar_capacity_kw"]),
        config,
    )

    previous_slots = previous_forecast["slots"]
    target_slots = forecast["slots"]

    horizon_slots = (
        previous_slots[-2:]
        + target_slots[:46]
    )

    # Re-number slots for the optimisation horizon while
    # preserving their real local timestamps.
    for slot_number, slot in enumerate(horizon_slots):
        slot["slot"] = slot_number

    forecast["slots"] = horizon_slots

    forecast["totals"] = dict(
        forecast.get("totals") or {}
    )

    forecast["totals"]["solar_kwh"] = round(
        sum(
            float(slot.get("solar_kwh") or 0.0)
            for slot in horizon_slots
        ),
        4,
    )

    forecast["totals"]["load_kwh"] = round(
        sum(
            float(slot.get("load_kwh") or 0.0)
            for slot in horizon_slots
        ),
        4,
    )

    forecast_by_time = {
        slot.get("local_from"): slot
        for slot in forecast["slots"]
    }

    usable_forecast_slots = [
        forecast_by_time[price.get("local_from")]
        for price in price_data["slots"]
        if (
            price.get("import_p_per_kwh") is not None
            and price.get("local_from") in forecast_by_time
        )
    ]

    optimisation = _optimise(
        price_data["slots"],
        usable_forecast_slots,
        config,
    )

    previous_plan = read_latest_plan()

    expected_slots = int(
        price_data.get(
            "expected_slot_count",
            len(price_data["slots"]),
        )
    )
    available_slots = int(
        price_data.get(
            "slot_count",
            len(price_data["slots"]),
        )
    )

    coverage_percent = round(
        (
            available_slots / expected_slots * 100.0
            if expected_slots
            else 0.0
        ),
        1,
    )

    plan = {
        "generated_at": datetime.now(tz).isoformat(),
        "target_date": target_date.isoformat(),
        "status": (
            "READY"
            if available_slots == expected_slots
            else "PARTIAL"
        ),
        "coverage_percent": coverage_percent,
        "available_slot_count": available_slots,
        "expected_slot_count": expected_slots,
        "plan_revision": (
            int((previous_plan or {}).get("plan_revision", 0)) + 1
        ),
        "previous_generated_at": (
            (previous_plan or {}).get("generated_at")
        ),
        "tariff": {
            "provider": "Octopus Energy",
            "import_product_code": price_data["import_product_code"],
            "import_tariff_code": price_data["import_tariff_code"],
            "export_product_code": price_data["export_product_code"],
            "export_tariff_code": price_data["export_tariff_code"],
            "export_active": price_data["export_active"],
            "source": "octopus_account_api",
        },
        "forecast": {
            "model": forecast["model"],
            "history_rows": forecast["history_rows"],
            "solar_kwh": forecast["totals"]["solar_kwh"],
            "load_kwh": forecast["totals"]["load_kwh"],
            "solar_model": forecast["solar"]["model"],
            "solar_provider": forecast["solar"]["provider"],
            "solar_calibration_days": forecast["solar"]["calibration_days"],
        },
        "optimisation": optimisation,
    }

    record_solar_forecast(
        plan,
        forecast["slots"],
    )

    PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)

    if PLAN_PATH.is_file():
        previous_path = PLAN_PATH.with_name(
            "previous-plan.json"
        )
        previous_path.write_text(
            PLAN_PATH.read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    temporary = PLAN_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(plan, indent=2),
        encoding="utf-8",
    )
    temporary.replace(PLAN_PATH)

    return plan


def read_latest_plan() -> dict[str, Any] | None:
    if not PLAN_PATH.is_file():
        return None

    return json.loads(
        PLAN_PATH.read_text(encoding="utf-8")
    )
