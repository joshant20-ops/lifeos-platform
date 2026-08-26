from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from app.config import load_config
from app.services.enphase import (
    EnphaseAuthenticationError,
    EnphaseClient,
    EnphaseUnavailableError,
)
from app.services.history import history_summary
from app.services.forecast_history import forecast_error_report
from app.services.planner import generate_plan, read_latest_plan
from app.services.octopus import account_tariffs
from app.services.solar_forecast import weather_adjusted_solar
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


router = APIRouter(tags=["energy"])
client = EnphaseClient()
TEMPLATE = Path("/app/templates/energy.html")


@router.get("/energy", response_class=HTMLResponse)
async def energy_dashboard() -> HTMLResponse:
    if not TEMPLATE.is_file():
        raise HTTPException(
            status_code=500,
            detail="Energy dashboard template is missing",
        )

    return HTMLResponse(
        TEMPLATE.read_text(encoding="utf-8")
    )


@router.get("/api/energy/current")
async def current_energy() -> dict:
    try:
        return await client.live()

    except EnphaseAuthenticationError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "state": "AUTH_ERROR",
                "message": str(exc),
            },
        ) from exc

    except EnphaseUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "state": "OFFLINE",
                "message": str(exc),
            },
        ) from exc


@router.get("/api/energy/history")
async def energy_history(
    hours: int = Query(default=24, ge=1, le=840),
) -> dict:
    return await asyncio.to_thread(
        history_summary,
        hours,
    )


@router.get("/api/plan/latest")
async def latest_plan() -> dict:
    plan = await asyncio.to_thread(read_latest_plan)

    if plan is None:
        return {
            "status": "NOT_GENERATED",
            "message": "No tomorrow plan has been generated yet",
        }

    return plan


@router.get("/api/plan/tomorrow")
async def tomorrow_plan() -> dict:
    plan = await asyncio.to_thread(read_latest_plan)

    if plan is None:
        raise HTTPException(
            status_code=404,
            detail="Tomorrow plan has not been generated",
        )

    return plan


@router.post("/api/plan/generate")
async def generate_tomorrow_plan() -> dict:
    try:
        config = load_config()
        return await asyncio.to_thread(
            generate_plan,
            config,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc



@router.get("/api/forecast/errors")
async def forecast_errors(
    limit: int = Query(default=30, ge=1, le=365),
) -> dict:
    config = load_config()
    timezone_name = str(config["site"]["timezone"])

    return await asyncio.to_thread(
        forecast_error_report,
        timezone_name,
        limit,
    )


@router.get("/api/sources/status")
async def sources_status() -> dict:
    config = load_config()
    timezone_name = str(config["site"]["timezone"])
    tz = ZoneInfo(timezone_name)

    tomorrow = datetime.now(tz).date() + timedelta(days=1)

    tariffs = await asyncio.to_thread(account_tariffs)

    solar = await asyncio.to_thread(
        weather_adjusted_solar,
        tomorrow,
        config,
    )

    return {
        "octopus": {
            "import_tariff": tariffs["import"]["tariff_code"],
            "export_tariff": (
                tariffs["export"]["tariff_code"]
                if tariffs["export"]
                else None
            ),
            "export_active": tariffs["export"] is not None,
        },
        "solar": {
            "target_date": tomorrow.isoformat(),
            "provider": solar["provider"],
            "model": solar["model"],
            "forecast_kwh": solar["solar_kwh"],
            "calibration_days": solar["calibration_days"],
        },
    }

@router.get("/api/control/status")
async def control_status() -> dict:
    from app.services.plan_executor import current_plan_action

    plan = await asyncio.to_thread(read_latest_plan)

    if plan is None:
        return {
            "status": "NO_PLAN",
            "write_enabled": False,
        }

    config = load_config()

    return current_plan_action(plan)
