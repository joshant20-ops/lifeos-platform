
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.services.enphase import (
    EnphaseAuthenticationError,
    EnphaseClient,
    EnphaseUnavailableError,
)


router = APIRouter(
    prefix="/api/enphase",
    tags=["enphase"],
)

client = EnphaseClient()


@router.get("/status")
async def enphase_status() -> dict:
    return await client.status()


@router.get("/live")
async def enphase_live() -> dict:
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
