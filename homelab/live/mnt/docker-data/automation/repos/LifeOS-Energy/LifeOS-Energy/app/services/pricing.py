from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class CostPoint:
    hour: int
    grid_import_kwh: float
    grid_export_kwh: float
    import_cost_pence: float
    export_income_pence: float
    net_energy_cost_pence: float


def calculate_daily_cost(
    simulation: dict[str, Any],
    tariff: dict[str, Any],
) -> dict[str, Any]:
    import_rate = float(
        tariff["import_unit_rate_p_per_kwh"]
    )

    export_rate = float(
        tariff["export_unit_rate_p_per_kwh"]
    )

    standing_charge = float(
        tariff["standing_charge_p_per_day"]
    )

    cost_points: list[CostPoint] = []

    total_import_cost = 0.0
    total_export_income = 0.0

    for point in simulation["points"]:
        import_kwh = float(point["grid_import_kw"])
        export_kwh = float(point["grid_export_kw"])

        import_cost = import_kwh * import_rate
        export_income = export_kwh * export_rate
        net_energy_cost = import_cost - export_income

        total_import_cost += import_cost
        total_export_income += export_income

        cost_points.append(
            CostPoint(
                hour=int(point["hour"]),
                grid_import_kwh=round(import_kwh, 3),
                grid_export_kwh=round(export_kwh, 3),
                import_cost_pence=round(import_cost, 3),
                export_income_pence=round(export_income, 3),
                net_energy_cost_pence=round(
                    net_energy_cost,
                    3,
                ),
            )
        )

    net_energy_cost = (
        total_import_cost - total_export_income
    )

    net_daily_cost = net_energy_cost + standing_charge

    return {
        "model": "fixed_tariff_v1",
        "tariff": {
            "name": str(tariff["name"]),
            "provider": str(tariff["provider"]),
            "import_unit_rate_p_per_kwh": import_rate,
            "export_unit_rate_p_per_kwh": export_rate,
            "standing_charge_p_per_day": standing_charge,
        },
        "totals": {
            "import_cost_pence": round(
                total_import_cost,
                2,
            ),
            "export_income_pence": round(
                total_export_income,
                2,
            ),
            "net_energy_cost_pence": round(
                net_energy_cost,
                2,
            ),
            "standing_charge_pence": round(
                standing_charge,
                2,
            ),
            "net_daily_cost_pence": round(
                net_daily_cost,
                2,
            ),
            "import_cost_gbp": round(
                total_import_cost / 100,
                2,
            ),
            "export_income_gbp": round(
                total_export_income / 100,
                2,
            ),
            "net_daily_cost_gbp": round(
                net_daily_cost / 100,
                2,
            ),
        },
        "points": [
            asdict(point)
            for point in cost_points
        ],
    }
