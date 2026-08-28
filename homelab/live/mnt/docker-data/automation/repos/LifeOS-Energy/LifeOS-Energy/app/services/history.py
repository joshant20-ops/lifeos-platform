
from __future__ import annotations

import asyncio
import os
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from app.services.enphase import (
    EnphaseAuthenticationError,
    EnphaseClient,
    EnphaseUnavailableError,
)


DATABASE_PATH = Path(
    os.getenv(
        "ENERGY_HISTORY_DATABASE",
        "/data/lifeos-energy-history.sqlite3",
    )
)

COLLECTION_INTERVAL_SECONDS = max(
    30,
    int(os.getenv("ENERGY_COLLECTION_INTERVAL_SECONDS", "60")),
)

_client = EnphaseClient()
_collector_task: asyncio.Task[None] | None = None
_stop_event: asyncio.Event | None = None


def connect() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(
        DATABASE_PATH,
        timeout=10,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    return connection


def initialise_database() -> None:
    with closing(connect()) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS telemetry (
                reading_time INTEGER PRIMARY KEY,
                production_w REAL NOT NULL,
                consumption_w REAL,
                grid_w REAL,
                grid_import_w REAL NOT NULL,
                grid_export_w REAL NOT NULL,
                battery_soc_percent REAL,
                battery_power_w REAL,
                source TEXT NOT NULL,
                provider TEXT NOT NULL,
                recorded_at INTEGER NOT NULL
            )
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_telemetry_recorded_at
            ON telemetry(recorded_at)
            """
        )

        connection.commit()


def insert_telemetry(telemetry: dict[str, Any]) -> None:
    battery = telemetry.get("battery") or {}

    with closing(connect()) as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO telemetry (
                reading_time,
                production_w,
                consumption_w,
                grid_w,
                grid_import_w,
                grid_export_w,
                battery_soc_percent,
                battery_power_w,
                source,
                provider,
                recorded_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(telemetry["reading_time"]),
                float(telemetry["production_w"]),
                telemetry.get("consumption_w"),
                telemetry.get("grid_w"),
                float(telemetry["grid_import_w"]),
                float(telemetry["grid_export_w"]),
                battery.get("soc_percent"),
                battery.get("power_w"),
                str(telemetry["source"]),
                str(telemetry["provider"]),
                int(time.time()),
            ),
        )
        connection.commit()


def read_history(hours: int) -> list[dict[str, Any]]:
    cutoff = int(time.time()) - hours * 3600

    with closing(connect()) as connection:
        rows = connection.execute(
            """
            SELECT
                reading_time,
                production_w,
                consumption_w,
                grid_w,
                grid_import_w,
                grid_export_w,
                battery_soc_percent,
                battery_power_w,
                source,
                provider
            FROM telemetry
            WHERE reading_time >= ?
            ORDER BY reading_time ASC
            """,
            (cutoff,),
        ).fetchall()

    return [dict(row) for row in rows]


def history_summary(hours: int) -> dict[str, Any]:
    points = read_history(hours)

    if not points:
        return {
            "hours": hours,
            "count": 0,
            "first_reading_time": None,
            "last_reading_time": None,
            "points": [],
        }

    return {
        "hours": hours,
        "count": len(points),
        "first_reading_time": points[0]["reading_time"],
        "last_reading_time": points[-1]["reading_time"],
        "points": points,
    }


async def collect_once() -> dict[str, Any]:
    telemetry = await _client.live(force=True)
    await asyncio.to_thread(insert_telemetry, telemetry)
    return telemetry


async def collector_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await collect_once()
        except (
            EnphaseAuthenticationError,
            EnphaseUnavailableError,
        ):
            pass
        except Exception:
            pass

        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=COLLECTION_INTERVAL_SECONDS,
            )
        except TimeoutError:
            continue


async def start_history_collector() -> None:
    global _collector_task, _stop_event

    initialise_database()

    if _collector_task is not None and not _collector_task.done():
        return

    _stop_event = asyncio.Event()
    _collector_task = asyncio.create_task(
        collector_loop(_stop_event),
        name="lifeos-energy-history-collector",
    )


async def stop_history_collector() -> None:
    global _collector_task, _stop_event

    if _stop_event is not None:
        _stop_event.set()

    if _collector_task is not None:
        try:
            await asyncio.wait_for(_collector_task, timeout=10)
        except TimeoutError:
            _collector_task.cancel()

    _collector_task = None
    _stop_event = None
