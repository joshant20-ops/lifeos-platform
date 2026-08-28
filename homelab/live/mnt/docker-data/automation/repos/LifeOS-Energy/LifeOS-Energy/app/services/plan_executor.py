from __future__ import annotations

from datetime import datetime
from typing import Any

CONTROL_MAP = {
    "HOLD": "hold",
    "SOLAR_CHARGE": "hold",
    "GRID_IMPORT": "hold",
    "BATTERY_SUPPORT": "battery_support",
    "GRID_CHARGE": "grid_charge",
    "EXPORT": "export",
    "EXPORT_DISCHARGE": "export_discharge",
}

def current_plan_action(plan: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now().astimezone()
    slots = plan.get("optimisation", {}).get("slots", [])

    for slot in slots:
        try:
            start = datetime.fromisoformat(slot["valid_from"])
            end = datetime.fromisoformat(slot["valid_to"])

            if start <= now < end:
                action = str(slot.get("action", "HOLD")).upper()
                return {
                    "status": "DRY_RUN",
                    "write_enabled": False,
                    "time": now.isoformat(),
                    "plan_action": action,
                    "control_action": CONTROL_MAP.get(action, "hold"),
                    "window": f'{slot.get("local_from")} -> {slot.get("local_to")}',
                    "target_soc_percent": slot.get("battery_end_soc_percent"),
                    "slot": slot,
                    "source": "lifeos_plan",
                }
        except (KeyError, TypeError, ValueError):
            continue

    return {
        "status": "NO_ACTIVE_SLOT",
        "write_enabled": False,
        "time": now.isoformat(),
        "plan_action": None,
        "control_action": "hold",
        "window": None,
        "source": "lifeos_plan",
    }
