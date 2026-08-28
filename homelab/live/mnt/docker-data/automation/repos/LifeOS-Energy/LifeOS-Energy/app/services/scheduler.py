from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
from typing import Any
from zoneinfo import ZoneInfo

from app.services.planner import generate_plan, read_latest_plan


LOGGER = logging.getLogger("lifeos-energy")

_task: asyncio.Task[None] | None = None
_stop_event: asyncio.Event | None = None

RETRY_SECONDS = 600


async def _generate(
    config: dict[str, Any],
) -> bool:
    try:
        plan = await asyncio.to_thread(
            generate_plan,
            config,
        )

        if plan.get("status") == "READY":
            LOGGER.info(
                "tomorrow_plan_ready target=%s cost_gbp=%s",
                plan["target_date"],
                plan["optimisation"]["totals"][
                    "net_energy_cost_gbp"
                ],
            )

            return True

        LOGGER.info(
            "tomorrow_plan_partial target=%s coverage_percent=%s "
            "available_slots=%s expected_slots=%s",
            plan["target_date"],
            plan.get("coverage_percent"),
            plan.get("available_slot_count"),
            plan.get("expected_slot_count"),
        )

        return False

    except Exception as exc:
        LOGGER.warning(
            "tomorrow_plan_not_ready error=%s",
            exc,
        )

        return False


async def scheduler_loop(
    config: dict[str, Any],
    stop_event: asyncio.Event,
) -> None:
    planner = config["planner"]

    timezone_name = str(
        config["site"]["timezone"]
    )

    tz = ZoneInfo(timezone_name)

    run_hour = int(
        planner["daily_run_hour"]
    )

    run_minute = int(
        planner["daily_run_minute"]
    )

    while not stop_event.is_set():

        now = datetime.now(tz)

        today_run = now.replace(
            hour=run_hour,
            minute=run_minute,
            second=0,
            microsecond=0,
        )

        expected_target = (
            now.date() + timedelta(days=1)
        ).isoformat()

        latest = await asyncio.to_thread(
            read_latest_plan
        )

        latest_target = (
            latest.get("target_date")
            if latest
            else None
        )

        #
        # Before 20:00:
        # sleep until the planning window opens.
        #
        if now < today_run:

            seconds = max(
                1.0,
                (today_run - now).total_seconds(),
            )

            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=seconds,
                )
                continue

            except TimeoutError:
                continue

        #
        # After 20:00:
        # if tomorrow's valid plan already exists,
        # wait until tomorrow's planning window.
        #
        if (
            latest_target == expected_target
            and (latest or {}).get("status") == "READY"
        ):

            tomorrow_run = (
                today_run + timedelta(days=1)
            )

            seconds = max(
                1.0,
                (
                    tomorrow_run
                    - datetime.now(tz)
                ).total_seconds(),
            )

            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=seconds,
                )
                continue

            except TimeoutError:
                continue

        #
        # Tomorrow's plan does not exist.
        # Try now.
        #
        success = await _generate(config)

        if success:
            continue

        #
        # Octopus prices may still be incomplete.
        # Retry every 10 minutes.
        #
        LOGGER.info(
            "tomorrow_plan_retry_in_seconds=%s",
            RETRY_SECONDS,
        )

        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=RETRY_SECONDS,
            )

        except TimeoutError:
            continue


async def start_planner_scheduler(
    config: dict[str, Any],
) -> None:
    global _task, _stop_event

    if (
        _task is not None
        and not _task.done()
    ):
        return

    _stop_event = asyncio.Event()

    _task = asyncio.create_task(
        scheduler_loop(
            config,
            _stop_event,
        ),
        name="lifeos-energy-daily-planner",
    )


async def stop_planner_scheduler() -> None:
    global _task, _stop_event

    if _stop_event is not None:
        _stop_event.set()

    if _task is not None:
        try:
            await asyncio.wait_for(
                _task,
                timeout=10,
            )

        except TimeoutError:
            _task.cancel()

    _task = None
    _stop_event = None
