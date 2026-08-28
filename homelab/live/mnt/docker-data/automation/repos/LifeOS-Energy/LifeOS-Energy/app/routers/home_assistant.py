from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter

from app.services.planner import read_latest_plan


router = APIRouter(tags=["home-assistant"])

TIMEZONE = ZoneInfo("Europe/London")


def _group_actions(slots: list[dict]) -> list[str]:
    if not slots:
        return []

    groups = []
    current = [slots[0]]

    for slot in slots[1:]:
        if slot.get("action") == current[-1].get("action"):
            current.append(slot)
        else:
            groups.append(current)
            current = [slot]

    groups.append(current)

    output = []

    for group in groups:
        first = group[0]
        last = group[-1]

        start = str(first.get("local_from", ""))[11:16]
        end = str(last.get("local_to", ""))[11:16]
        action = str(first.get("action", "UNKNOWN"))

        start_soc = first.get("battery_start_soc_percent")
        end_soc = last.get("battery_end_soc_percent")

        output.append(
            f"{start}-{end} {action} "
            f"(SOC {start_soc}% -> {end_soc}%)"
        )

    return output


def _not_ready(reason: str) -> dict:
    return {
        "status": "NOT_READY",
        "reason": reason,
        "target_date": None,
        "generated_at": None,
        "solar_kwh": None,
        "load_kwh": None,
        "grid_import_kwh": None,
        "grid_export_kwh": None,
        "net_energy_cost_gbp": None,
        "starting_soc_percent": None,
        "ending_soc_percent": None,
        "import_tariff": None,
        "export_tariff": None,
        "slot_count": 0,
        "action_summary": [],
    }


def _plan_is_complete(plan: dict) -> tuple[bool, str]:
    if not plan or plan.get("status") not in {
        "READY",
        "PARTIAL",
    }:
        return False, "no_ready_plan"

    target_text = plan.get("target_date")

    if not target_text:
        return False, "missing_target_date"

    try:
        target = date.fromisoformat(target_text)
    except ValueError:
        return False, "invalid_target_date"

    optimisation = plan.get("optimisation") or {}
    slots = optimisation.get("slots") or []

    if not slots:
        return False, "no_slots"

    tariff = plan.get("tariff") or {}

    import_tariff = (
        tariff.get("import_tariff_code")
        or tariff.get("tariff_code")
    )

    # Export may legitimately be absent from older stored plans.
    export_tariff = (
        tariff.get("export_tariff_code")
        or tariff.get("export_source")
    )

    if not import_tariff:
        return False, "missing_import_tariff"

    if not export_tariff:
        return False, "missing_export_tariff"

    expected_start = datetime.combine(
        target,
        datetime.min.time(),
        tzinfo=TIMEZONE,
    )

    expected_end = expected_start + timedelta(days=1)

    expected_slots = int(
        (
            expected_end.astimezone(ZoneInfo("UTC"))
            - expected_start.astimezone(ZoneInfo("UTC"))
        ).total_seconds()
        // 1800
    )

    coverage = (
        float(plan.get("coverage_percent", 0))
        if plan.get("coverage_percent") is not None
        else 0.0
    )

    if not coverage:
        coverage = len(slots) / expected_slots * 100.0

    if coverage < 90.0:
        return False, (
            f"insufficient_coverage_{coverage:.1f}_percent"
        )

    if len(slots) < int(expected_slots * 0.90):
        return False, (
            f"incomplete_slots_{len(slots)}_of_{expected_slots}"
        )

    return True, (
        "ready"
        if coverage >= 100.0
        else f"partial_{coverage:.1f}_percent"
    )


@router.get("/api/ha/plan")
async def home_assistant_plan() -> dict:
    plan = read_latest_plan()

    valid, reason = _plan_is_complete(plan)

    if not valid:
        return _not_ready(reason)

    optimisation = plan["optimisation"]
    totals = optimisation.get("totals") or {}
    forecast = plan.get("forecast") or {}
    tariff = plan.get("tariff") or {}
    slots = optimisation["slots"]

    target = date.fromisoformat(plan["target_date"])

    expected_start = datetime.combine(
        target,
        datetime.min.time(),
        tzinfo=TIMEZONE,
    )
    expected_end = expected_start + timedelta(days=1)

    calendar_expected_slots = int(
        (
            expected_end.astimezone(ZoneInfo("UTC"))
            - expected_start.astimezone(ZoneInfo("UTC"))
        ).total_seconds()
        // 1800
    )

    available_slot_count = int(
        plan.get("available_slot_count")
        or len(slots)
    )

    expected_slot_count = int(
        plan.get("expected_slot_count")
        or calendar_expected_slots
    )

    coverage_percent = float(
        plan.get("coverage_percent")
        or (
            available_slot_count
            / expected_slot_count
            * 100.0
        )
    )

    coverage_percent = round(coverage_percent, 1)

    return {
        "status": (
            "READY"
            if coverage_percent >= 100.0
            else "PARTIAL"
        ),
        "reason": reason,
        "coverage_percent": coverage_percent,
        "available_slot_count": available_slot_count,
        "expected_slot_count": expected_slot_count,
        "plan_revision": plan.get("plan_revision", 1),
        "previous_generated_at": plan.get(
            "previous_generated_at"
        ),
        "target_date": plan.get("target_date"),
        "generated_at": plan.get("generated_at"),
        "solar_kwh": forecast.get("solar_kwh"),
        "load_kwh": forecast.get("load_kwh"),
        "grid_import_kwh": totals.get("grid_import_kwh"),
        "grid_export_kwh": totals.get("grid_export_kwh"),
        "net_energy_cost_gbp": totals.get(
            "net_energy_cost_gbp"
        ),
        "starting_soc_percent": optimisation.get(
            "starting_soc_percent"
        ),
        "ending_soc_percent": optimisation.get(
            "ending_soc_percent"
        ),
        "import_tariff": (
            tariff.get("import_tariff_code")
            or tariff.get("tariff_code")
        ),
        "export_tariff": (
            tariff.get("export_tariff_code")
            or tariff.get("export_source")
        ),
        "slot_count": len(slots),
        "action_summary": _group_actions(slots),
    }
