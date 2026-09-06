from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from app.config import load_config
from app.services.opportunities import current_projection, refresh_opportunities


router = APIRouter(tags=["energy-opportunities"])


@router.get("/api/energy/opportunities/current")
async def energy_opportunities_current() -> dict:
    return current_projection()


@router.post("/api/energy/opportunities/refresh")
async def energy_opportunities_refresh() -> dict:
    try:
        timezone_name = str(load_config()["site"]["timezone"])
        return await asyncio.to_thread(refresh_opportunities, timezone_name)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
