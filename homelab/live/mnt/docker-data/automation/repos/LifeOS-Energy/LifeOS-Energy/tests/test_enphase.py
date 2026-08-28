
from __future__ import annotations

from dataclasses import dataclass

from app.services.enphase import (
    normalise_battery,
    normalise_envoy_data,
)


@dataclass
class PowerModel:
    watts_now: float
    watt_hours_lifetime: float
    watt_hours_today: float


@dataclass
class BatteryAggregate:
    state_of_charge: float


@dataclass
class BatteryPower:
    real_power_mw: int


@dataclass
class FakeEnvoyData:
    system_production: PowerModel
    system_consumption: PowerModel
    system_net_consumption: PowerModel
    encharge_aggregate: BatteryAggregate
    encharge_power: dict[str, BatteryPower]
    battery_aggregate: object | None = None
    ctmeter_storage: object | None = None


def build_data(
    *,
    production_w: float = 300,
    consumption_w: float = 820,
    grid_w: float = 520,
) -> FakeEnvoyData:
    return FakeEnvoyData(
        system_production=PowerModel(
            watts_now=production_w,
            watt_hours_lifetime=5_050_000,
            watt_hours_today=12_500,
        ),
        system_consumption=PowerModel(
            watts_now=consumption_w,
            watt_hours_lifetime=8_000_000,
            watt_hours_today=9_000,
        ),
        system_net_consumption=PowerModel(
            watts_now=grid_w,
            watt_hours_lifetime=3_000_000,
            watt_hours_today=1_500,
        ),
        encharge_aggregate=BatteryAggregate(
            state_of_charge=49,
        ),
        encharge_power={
            "battery-a": BatteryPower(
                real_power_mw=-850_000,
            ),
            "battery-b": BatteryPower(
                real_power_mw=-150_000,
            ),
        },
    )


def test_live_contract() -> None:
    result = normalise_envoy_data(
        build_data(),
        gateway="192.168.0.18",
        retrieved_at=1_785_265_306,
    )

    assert result["production_w"] == 300.0
    assert result["consumption_w"] == 820.0
    assert result["grid_w"] == 520.0
    assert result["grid_import_w"] == 520.0
    assert result["grid_export_w"] == 0.0
    assert result["battery"]["soc_percent"] == 49.0
    assert result["battery"]["power_w"] == -1000.0
    assert result["battery"]["device_count"] == 2
    assert result["provider"] == "pyenphase"
    assert result["source"] == "pyenphase_local"


def test_grid_export() -> None:
    result = normalise_envoy_data(
        build_data(
            production_w=4000,
            consumption_w=1000,
            grid_w=-3000,
        ),
        gateway="192.168.0.18",
        retrieved_at=1,
    )

    assert result["grid_import_w"] == 0.0
    assert result["grid_export_w"] == 3000.0


def test_soc_fraction_is_converted() -> None:
    data = build_data()
    data.encharge_aggregate.state_of_charge = 0.72

    result = normalise_battery(data)

    assert result["soc_percent"] == 72.0


def test_missing_battery_is_safe() -> None:
    data = build_data()
    data.encharge_aggregate = None
    data.encharge_power = {}

    result = normalise_battery(data)

    assert result["soc_percent"] is None
    assert result["power_w"] is None
    assert result["device_count"] == 0
