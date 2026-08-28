from app.services.pricing import calculate_daily_cost


SIMULATION = {
    "points": [
        {
            "hour": 0,
            "grid_import_kw": 2.0,
            "grid_export_kw": 0.0,
        },
        {
            "hour": 1,
            "grid_import_kw": 0.0,
            "grid_export_kw": 1.5,
        },
    ]
}

TARIFF = {
    "name": "Test Tariff",
    "provider": "test",
    "import_unit_rate_p_per_kwh": 25.0,
    "export_unit_rate_p_per_kwh": 10.0,
    "standing_charge_p_per_day": 50.0,
}


def test_daily_cost_calculation() -> None:
    result = calculate_daily_cost(
        SIMULATION,
        TARIFF,
    )

    totals = result["totals"]

    assert totals["import_cost_pence"] == 50.0
    assert totals["export_income_pence"] == 15.0
    assert totals["net_energy_cost_pence"] == 35.0
    assert totals["standing_charge_pence"] == 50.0
    assert totals["net_daily_cost_pence"] == 85.0
    assert totals["net_daily_cost_gbp"] == 0.85


def test_pricing_returns_one_point_per_interval() -> None:
    result = calculate_daily_cost(
        SIMULATION,
        TARIFF,
    )

    assert len(result["points"]) == 2


def test_export_can_create_negative_energy_cost() -> None:
    simulation = {
        "points": [
            {
                "hour": 0,
                "grid_import_kw": 0.0,
                "grid_export_kw": 10.0,
            }
        ]
    }

    result = calculate_daily_cost(
        simulation,
        TARIFF,
    )

    assert (
        result["totals"]["net_energy_cost_pence"]
        == -100.0
    )
