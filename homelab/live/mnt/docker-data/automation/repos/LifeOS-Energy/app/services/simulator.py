from dataclasses import asdict, dataclass
from math import exp
from typing import Any


@dataclass(frozen=True)
class SimulationPoint:
    hour: int
    solar_kw: float
    load_kw: float
    battery_kw: float
    battery_soc_percent: float
    grid_import_kw: float
    grid_export_kw: float


def _solar_profile(hour: int, peak_kw: float) -> float:
    if hour < 5 or hour > 20:
        return 0.0

    centre = 13.0
    width = 3.6
    value = peak_kw * exp(-((hour - centre) ** 2) / (2 * width**2))

    return round(value, 3)


def _load_profile(hour: int) -> float:
    base_load = 0.32

    morning_peak = 1.2 * exp(-((hour - 7.5) ** 2) / (2 * 1.3**2))
    evening_peak = 1.8 * exp(-((hour - 18.5) ** 2) / (2 * 1.8**2))
    overnight_load = 0.10 if hour <= 5 else 0.0

    return round(base_load + morning_peak + evening_peak + overnight_load, 3)


def run_daily_simulation(config: dict[str, Any]) -> dict[str, Any]:
    energy = config["energy"]

    solar_capacity_kw = float(energy["solar_capacity_kw"])
    battery_capacity_kwh = float(energy["battery_capacity_kwh"])
    battery_minimum_percent = float(
        energy["battery_minimum_percent"]
    )
    battery_maximum_percent = float(
        energy["battery_maximum_percent"]
    )

    minimum_kwh = battery_capacity_kwh * battery_minimum_percent / 100
    maximum_kwh = battery_capacity_kwh * battery_maximum_percent / 100

    initial_soc_percent = 50.0
    battery_energy_kwh = battery_capacity_kwh * initial_soc_percent / 100

    maximum_charge_kw = min(3.68, battery_capacity_kwh)
    maximum_discharge_kw = min(3.68, battery_capacity_kwh)

    points: list[SimulationPoint] = []

    total_solar_kwh = 0.0
    total_load_kwh = 0.0
    total_import_kwh = 0.0
    total_export_kwh = 0.0
    total_battery_charge_kwh = 0.0
    total_battery_discharge_kwh = 0.0

    for hour in range(24):
        solar_kw = _solar_profile(hour, solar_capacity_kw)
        load_kw = _load_profile(hour)

        available_surplus_kw = max(0.0, solar_kw - load_kw)
        energy_deficit_kw = max(0.0, load_kw - solar_kw)

        battery_kw = 0.0
        grid_import_kw = 0.0
        grid_export_kw = 0.0

        if available_surplus_kw > 0:
            remaining_capacity_kwh = maximum_kwh - battery_energy_kwh

            charge_kw = min(
                available_surplus_kw,
                maximum_charge_kw,
                max(0.0, remaining_capacity_kwh),
            )

            battery_energy_kwh += charge_kw
            battery_kw = charge_kw
            grid_export_kw = available_surplus_kw - charge_kw

            total_battery_charge_kwh += charge_kw

        elif energy_deficit_kw > 0:
            available_battery_kwh = battery_energy_kwh - minimum_kwh

            discharge_kw = min(
                energy_deficit_kw,
                maximum_discharge_kw,
                max(0.0, available_battery_kwh),
            )

            battery_energy_kwh -= discharge_kw
            battery_kw = -discharge_kw
            grid_import_kw = energy_deficit_kw - discharge_kw

            total_battery_discharge_kwh += discharge_kw

        battery_energy_kwh = min(
            maximum_kwh,
            max(minimum_kwh, battery_energy_kwh),
        )

        battery_soc_percent = (
            battery_energy_kwh / battery_capacity_kwh * 100
        )

        total_solar_kwh += solar_kw
        total_load_kwh += load_kw
        total_import_kwh += grid_import_kw
        total_export_kwh += grid_export_kw

        points.append(
            SimulationPoint(
                hour=hour,
                solar_kw=round(solar_kw, 3),
                load_kw=round(load_kw, 3),
                battery_kw=round(battery_kw, 3),
                battery_soc_percent=round(battery_soc_percent, 1),
                grid_import_kw=round(grid_import_kw, 3),
                grid_export_kw=round(grid_export_kw, 3),
            )
        )

    self_consumed_kwh = total_solar_kwh - total_export_kwh

    self_consumption_percent = (
        self_consumed_kwh / total_solar_kwh * 100
        if total_solar_kwh > 0
        else 0.0
    )

    grid_independence_percent = (
        (total_load_kwh - total_import_kwh) / total_load_kwh * 100
        if total_load_kwh > 0
        else 0.0
    )

    return {
        "model": "deterministic_v1",
        "interval_minutes": 60,
        "initial_battery_soc_percent": initial_soc_percent,
        "final_battery_soc_percent": round(
            battery_energy_kwh / battery_capacity_kwh * 100,
            1,
        ),
        "totals": {
            "solar_generation_kwh": round(total_solar_kwh, 2),
            "household_load_kwh": round(total_load_kwh, 2),
            "grid_import_kwh": round(total_import_kwh, 2),
            "grid_export_kwh": round(total_export_kwh, 2),
            "battery_charge_kwh": round(
                total_battery_charge_kwh,
                2,
            ),
            "battery_discharge_kwh": round(
                total_battery_discharge_kwh,
                2,
            ),
            "self_consumption_percent": round(
                self_consumption_percent,
                1,
            ),
            "grid_independence_percent": round(
                grid_independence_percent,
                1,
            ),
        },
        "points": [asdict(point) for point in points],
    }
