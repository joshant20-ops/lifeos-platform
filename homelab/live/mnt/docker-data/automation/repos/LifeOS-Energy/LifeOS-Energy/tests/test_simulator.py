from app.services.simulator import run_daily_simulation


CONFIG = {
    "energy": {
        "solar_capacity_kw": 4.4,
        "battery_capacity_kwh": 10.0,
        "battery_minimum_percent": 10,
        "battery_maximum_percent": 95,
    }
}


def test_simulator_returns_24_points() -> None:
    result = run_daily_simulation(CONFIG)

    assert len(result["points"]) == 24


def test_simulator_energy_values_are_non_negative() -> None:
    result = run_daily_simulation(CONFIG)
    totals = result["totals"]

    assert totals["solar_generation_kwh"] >= 0
    assert totals["household_load_kwh"] > 0
    assert totals["grid_import_kwh"] >= 0
    assert totals["grid_export_kwh"] >= 0


def test_battery_stays_within_configured_limits() -> None:
    result = run_daily_simulation(CONFIG)

    for point in result["points"]:
        assert point["battery_soc_percent"] >= 10
        assert point["battery_soc_percent"] <= 95
