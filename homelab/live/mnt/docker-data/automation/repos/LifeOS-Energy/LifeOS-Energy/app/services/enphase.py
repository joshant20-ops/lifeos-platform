
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pyenphase import Envoy


class EnphaseError(RuntimeError):
    """Base error for the LifeOS Enphase provider."""


class EnphaseAuthenticationError(EnphaseError):
    """The Gateway token is missing or was rejected."""


class EnphaseUnavailableError(EnphaseError):
    """The Gateway could not provide telemetry."""


@dataclass(frozen=True)
class EnphaseSettings:
    gateway: str
    token_file: Path
    timeout_seconds: float
    stale_seconds: int

    @classmethod
    def from_environment(cls) -> "EnphaseSettings":
        return cls(
            gateway=os.getenv(
                "ENPHASE_GATEWAY",
                "192.168.0.18",
            ).strip(),
            token_file=Path(
                os.getenv(
                    "ENPHASE_TOKEN_FILE",
                    "/run/secrets/enphase-token",
                )
            ),
            timeout_seconds=float(
                os.getenv(
                    "ENPHASE_TIMEOUT_SECONDS",
                    "15",
                )
            ),
            stale_seconds=int(
                os.getenv(
                    "ENPHASE_STALE_SECONDS",
                    "60",
                )
            ),
        )


def number_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        return float(value)

    return None


def model_number(
    model: Any,
    attribute: str,
) -> float | None:
    if model is None:
        return None

    return number_or_none(
        getattr(model, attribute, None)
    )


def normalise_battery(
    data: Any,
) -> dict[str, Any]:
    aggregate = getattr(
        data,
        "encharge_aggregate",
        None,
    )

    if aggregate is None:
        aggregate = getattr(
            data,
            "battery_aggregate",
            None,
        )

    soc_percent = None

    for attribute in (
        "state_of_charge",
        "soc",
        "percent_full",
    ):
        soc_percent = model_number(
            aggregate,
            attribute,
        )

        if soc_percent is not None:
            break

    if (
        soc_percent is not None
        and 0 <= soc_percent <= 1
    ):
        soc_percent *= 100

    power_items = getattr(
        data,
        "encharge_power",
        None,
    )

    power_w: float | None = None
    device_count = 0

    if isinstance(power_items, dict):
        values: list[float] = []

        for battery in power_items.values():
            real_power_mw = model_number(
                battery,
                "real_power_mw",
            )

            if real_power_mw is None:
                continue

            values.append(
                real_power_mw / 1000.0
            )

        if values:
            power_w = sum(values)
            device_count = len(values)

    if power_w is None:
        storage = getattr(
            data,
            "ctmeter_storage",
            None,
        )

        power_w = model_number(
            storage,
            "active_power",
        )

        if power_w is None:
            power_w = model_number(
                storage,
                "watts_now",
            )

    return {
        "soc_percent": (
            round(soc_percent, 2)
            if soc_percent is not None
            else None
        ),
        "power_w": (
            round(power_w, 3)
            if power_w is not None
            else None
        ),
        "device_count": device_count,
    }


def normalise_envoy_data(
    data: Any,
    *,
    gateway: str,
    retrieved_at: int,
) -> dict[str, Any]:

    production = getattr(
        data,
        "system_production",
        None,
    )

    consumption = getattr(
        data,
        "system_consumption",
        None,
    )

    net_consumption = getattr(
        data,
        "system_net_consumption",
        None,
    )

    production_w = (
        model_number(
            production,
            "watts_now",
        )
        or 0.0
    )

    reported_consumption_w = model_number(
        consumption,
        "watts_now",
    )

    grid_w = model_number(
        net_consumption,
        "watts_now",
    )

    #
    # LIFEOS_ENPHASE_CONSUMPTION_BALANCE_FIX_V4
    #
    # Grid convention used by LifeOS:
    #
    #   positive = grid import
    #   negative = grid export
    #
    # Prefer the Envoy net-consumption meter for grid flow.
    #

    if (
        grid_w is None
        and reported_consumption_w is not None
    ):
        grid_w = (
            reported_consumption_w
            - production_w
        )

    grid_import_w = max(
        float(grid_w or 0.0),
        0.0,
    )

    grid_export_w = max(
        -float(grid_w or 0.0),
        0.0,
    )

    battery = normalise_battery(data)

    battery_power_w = float(
        battery.get("power_w")
        or 0.0
    )

    #
    # Observed Enphase convention on this installation:
    #
    #   positive battery power = battery discharge
    #   negative battery power = battery charge
    #

    battery_discharge_w = max(
        battery_power_w,
        0.0,
    )

    battery_charge_w = max(
        -battery_power_w,
        0.0,
    )

    #
    # Physical power balance:
    #
    # house =
    #     solar
    #   + grid import
    #   + battery discharge
    #   - grid export
    #   - battery charge
    #

    derived_consumption_w = (
        production_w
        + grid_import_w
        + battery_discharge_w
        - grid_export_w
        - battery_charge_w
    )

    derived_consumption_w = max(
        derived_consumption_w,
        0.0,
    )

    #
    # Use the Envoy-reported consumption when it is sane.
    #
    # During battery export some Envoy/pyenphase combinations
    # expose net consumption in system_consumption, resulting
    # in impossible negative house-load values.
    #
    # In that case use the physical power balance instead.
    #

    if (
        reported_consumption_w is None
        or reported_consumption_w < 0
    ):
        consumption_w = derived_consumption_w
        consumption_source = "derived_power_balance"

    else:
        consumption_w = float(
            reported_consumption_w
        )
        consumption_source = "envoy_system_consumption"

    return {
        "production_w": round(
            production_w,
            3,
        ),

        "consumption_w": round(
            consumption_w,
            3,
        ),

        "consumption_reported_w": (
            round(
                reported_consumption_w,
                3,
            )
            if reported_consumption_w is not None
            else None
        ),

        "consumption_derived_w": round(
            derived_consumption_w,
            3,
        ),

        "consumption_source": (
            consumption_source
        ),

        "grid_w": (
            round(
                grid_w,
                3,
            )
            if grid_w is not None
            else None
        ),

        "grid_import_w": round(
            grid_import_w,
            3,
        ),

        "grid_export_w": round(
            grid_export_w,
            3,
        ),

        "reading_time": retrieved_at,

        "production_lifetime_wh": model_number(
            production,
            "watt_hours_lifetime",
        ),

        "consumption_lifetime_wh": model_number(
            consumption,
            "watt_hours_lifetime",
        ),

        "production_today_wh": model_number(
            production,
            "watt_hours_today",
        ),

        "consumption_today_wh": model_number(
            consumption,
            "watt_hours_today",
        ),

        "battery": battery,

        "gateway": gateway,

        "retrieved_at": retrieved_at,

        "source": "pyenphase_local",

        "provider": "pyenphase",

        "age_seconds": 0,

        "state": "LIVE",
    }

class EnphaseClient:
    def __init__(
        self,
        settings: EnphaseSettings | None = None,
        cache_seconds: float = 5.0,
    ) -> None:
        self.settings = (
            settings
            if settings is not None
            else EnphaseSettings.from_environment()
        )

        self.cache_seconds = cache_seconds
        self._cache_at = 0.0
        self._cache_value: dict[str, Any] | None = None
        self._lock = asyncio.Lock()

    def read_token(self) -> str:
        try:
            token = self.settings.token_file.read_text(
                encoding="utf-8"
            ).strip()
        except OSError as exc:
            raise EnphaseAuthenticationError(
                "Enphase token file is unavailable"
            ) from exc

        if len(token) < 40:
            raise EnphaseAuthenticationError(
                "Enphase token is empty or invalid"
            )

        return token

    async def collect(self) -> Any:
        token = self.read_token()

        envoy = Envoy(
            self.settings.gateway,
            timeout=self.settings.timeout_seconds,
        )

        try:
            await envoy.setup()
            await envoy.authenticate(token=token)
            return await envoy.update()

        except EnphaseAuthenticationError:
            raise

        except Exception as exc:
            name = type(exc).__name__.lower()
            message = str(exc).lower()

            if (
                "auth" in name
                or "token" in message
                or "401" in message
                or "403" in message
            ):
                raise EnphaseAuthenticationError(
                    "Gateway authentication failed"
                ) from exc

            raise EnphaseUnavailableError(
                "Gateway telemetry request failed: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        finally:
            await envoy.close()

    async def live(
        self,
        force: bool = False,
    ) -> dict[str, Any]:
        now = time.monotonic()

        if (
            not force
            and self._cache_value is not None
            and now - self._cache_at
            < self.cache_seconds
        ):
            return dict(self._cache_value)

        async with self._lock:
            now = time.monotonic()

            if (
                not force
                and self._cache_value is not None
                and now - self._cache_at
                < self.cache_seconds
            ):
                return dict(self._cache_value)

            data = await self.collect()
            retrieved_at = int(time.time())

            telemetry = normalise_envoy_data(
                data,
                gateway=self.settings.gateway,
                retrieved_at=retrieved_at,
            )

            self._cache_value = dict(telemetry)
            self._cache_at = time.monotonic()

            return telemetry

    async def status(self) -> dict[str, Any]:
        try:
            live = await self.live()

        except EnphaseAuthenticationError as exc:
            return {
                "state": "AUTH_ERROR",
                "available": False,
                "gateway": self.settings.gateway,
                "provider": "pyenphase",
                "detail": str(exc),
            }

        except EnphaseUnavailableError as exc:
            return {
                "state": "OFFLINE",
                "available": False,
                "gateway": self.settings.gateway,
                "provider": "pyenphase",
                "detail": str(exc),
            }

        return {
            "state": live["state"],
            "available": True,
            "gateway": self.settings.gateway,
            "provider": "pyenphase",
            "age_seconds": live["age_seconds"],
            "reading_time": live["reading_time"],
            "source": live["source"],
        }
