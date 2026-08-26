from pathlib import Path
import os
from typing import Any

import yaml


def _resolve_config_path() -> Path:
    configured = os.environ.get("LIFEOS_CONFIG")

    if configured:
        return Path(configured)

    container_path = Path("/app/config/config.yaml")

    if container_path.is_file():
        return container_path

    return (
        Path(__file__).resolve().parent.parent
        / "config"
        / "config.yaml"
    )


def _require_number(
    mapping: dict[str, Any],
    key: str,
    minimum: float | None = None,
) -> float:
    if key not in mapping:
        raise RuntimeError(f"Missing configuration value: {key}")

    try:
        value = float(mapping[key])
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"Configuration value must be numeric: {key}"
        ) from exc

    if minimum is not None and value < minimum:
        raise RuntimeError(
            f"Configuration value {key} must be >= {minimum}"
        )

    return value


def load_config() -> dict[str, Any]:
    path = _resolve_config_path()

    if not path.is_file():
        raise RuntimeError(f"Configuration not found: {path}")

    config = yaml.safe_load(
        path.read_text(encoding="utf-8")
    ) or {}

    required_sections = {
        "application",
        "site",
        "energy",
        "tariff",
        "planner",
        "weather",
        "logging",
    }

    missing = sorted(required_sections - set(config))

    if missing:
        raise RuntimeError(
            "Missing configuration sections: "
            + ", ".join(missing)
        )

    energy = config["energy"]
    planner = config["planner"]
    weather = config["weather"]

    capacity = _require_number(
        energy,
        "battery_capacity_kwh",
        minimum=0.1,
    )

    minimum = _require_number(
        energy,
        "battery_minimum_percent",
        minimum=0,
    )

    maximum = _require_number(
        energy,
        "battery_maximum_percent",
        minimum=0,
    )

    start = _require_number(
        planner,
        "planning_start_soc_percent",
        minimum=0,
    )

    if not 0 <= minimum < maximum <= 100:
        raise RuntimeError("Invalid battery operating limits")

    if not minimum <= start <= maximum:
        raise RuntimeError(
            "planning_start_soc_percent must be inside battery limits"
        )

    _require_number(
        energy,
        "solar_capacity_kw",
        minimum=0,
    )

    _require_number(
        planner,
        "maximum_charge_kw",
        minimum=0.1,
    )

    _require_number(
        planner,
        "maximum_discharge_kw",
        minimum=0.1,
    )

    charge_efficiency = _require_number(
        planner,
        "charge_efficiency",
        minimum=0.01,
    )

    discharge_efficiency = _require_number(
        planner,
        "discharge_efficiency",
        minimum=0.01,
    )

    if charge_efficiency > 1 or discharge_efficiency > 1:
        raise RuntimeError(
            "Battery efficiencies must be <= 1"
        )

    latitude = float(weather["latitude"])
    longitude = float(weather["longitude"])

    if not -90 <= latitude <= 90:
        raise RuntimeError("Invalid weather latitude")

    if not -180 <= longitude <= 180:
        raise RuntimeError("Invalid weather longitude")

    if capacity <= 0:
        raise RuntimeError("Battery capacity must be positive")

    return config
