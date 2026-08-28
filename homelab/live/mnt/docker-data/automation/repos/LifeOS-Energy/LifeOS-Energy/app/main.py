from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import load_config
from app.logging_setup import configure_logging
from app.routers.enphase import router as enphase_router
from app.routers.energy import router as energy_router
from app.routers.home_assistant import router as home_assistant_router
from app.services.history import (
    start_history_collector,
    stop_history_collector,
)
from app.services.scheduler import (
    start_planner_scheduler,
    stop_planner_scheduler,
)

CONFIG = load_config()
LOGGER = configure_logging(CONFIG)

APP = CONFIG["application"]
SITE = CONFIG["site"]
ENERGY = CONFIG["energy"]
PLANNER = CONFIG["planner"]
WEATHER = CONFIG["weather"]

STARTED = monotonic()
STARTED_AT = datetime.now(timezone.utc)

ROOT = Path(__file__).resolve().parent.parent

app = FastAPI(
    title=APP["name"],
    version=APP["version"],
)

app.include_router(enphase_router)
app.include_router(energy_router)
app.include_router(home_assistant_router)

app.mount(
    "/static",
    StaticFiles(directory=str(ROOT / "static")),
    name="static",
)

templates = Jinja2Templates(
    directory=str(ROOT / "templates"),
)


@app.on_event("startup")
async def startup() -> None:
    LOGGER.info(
        "application_started name=%s version=%s",
        APP["name"],
        APP["version"],
    )

    await start_history_collector()
    await start_planner_scheduler(CONFIG)


@app.on_event("shutdown")
async def shutdown() -> None:
    await stop_planner_scheduler()
    await stop_history_collector()


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "application": APP,
            "site": SITE,
            "energy": ENERGY,
            "planner": PLANNER,
            "weather": WEATHER,
        },
    )


@app.get("/health")
async def health() -> dict:
    return {
        "status": "healthy",
        "application": APP["name"],
        "version": APP["version"],
        "uptime_seconds": round(
            monotonic() - STARTED,
            1,
        ),
    }


@app.get("/api/status")
async def status() -> dict:
    return {
        "application": APP,
        "site": SITE,
        "energy": ENERGY,
        "planner": PLANNER,
        "weather": {
            "provider": WEATHER["provider"],
            "configured": True,
        },
        "started_at": STARTED_AT.isoformat(),
        "uptime_seconds": round(
            monotonic() - STARTED,
            1,
        ),
        "modules": {
            "enphase_live": "ready",
            "history": "ready",
            "octopus_account_tariffs": "ready",
            "weather_solar": "ready",
            "optimiser": "ready",
            "daily_2000_scheduler": "ready",
        },
    }


@app.get("/api/simulation")
async def legacy_simulation() -> dict:
    return {
        "deprecated": True,
        "message": "Use /api/plan/latest.",
    }


@app.get("/api/cost")
async def legacy_cost() -> dict:
    return {
        "deprecated": True,
        "message": "Use /api/plan/latest.",
    }

@app.get("/api/energy/powerdown")
async def energy_powerdown() -> dict:
    """Return the current Octopus Power Down watcher decision.

    This endpoint is deliberately read-only.  LifeOS Energy consumes
    watcher output but does not control or modify the watcher.
    """
    import json

    decision_path = Path("/run/lifeos-powerdown/decision.json")

    unavailable = {
        "available": False,
        "decision": "UNAVAILABLE",
        "reason": "Power Down status is currently unavailable.",
        "decision_at": None,
        "watcher": {},
    }

    try:
        raw = decision_path.read_text()
        payload = json.loads(raw)
    except (OSError, ValueError, TypeError):
        return unavailable

    if not isinstance(payload, dict):
        return unavailable

    decision = payload.get("decision")
    reason = payload.get("reason")

    if not isinstance(decision, str) or not isinstance(reason, str):
        return unavailable

    watcher = payload.get("watcher")
    if not isinstance(watcher, dict):
        watcher = {}

    return {
        "available": True,
        "decision": decision,
        "reason": reason,
        "decision_at": payload.get("decision_at"),
        "watcher": {
            "checked_at": watcher.get("checked_at"),
            "future_or_current_joined": watcher.get(
                "future_or_current_joined"
            ),
            "baseline_state": watcher.get("baseline_state"),
            "baseline_numeric": watcher.get("baseline_numeric"),
        },
    }

