#!/usr/bin/env python3

import json
import os
import sys
import time
import urllib.error
import urllib.request


HA_URL=os.environ.get(
    "HA_URL",
    "http://127.0.0.1:8123"
).rstrip("/")

TOKEN=os.environ.get("HA_TOKEN","").strip()

TIMEOUT_SECONDS=int(
    os.environ.get(
        "HA_READY_TIMEOUT",
        "300"
    )
)

POLL_SECONDS=int(
    os.environ.get(
        "HA_READY_POLL",
        "5"
    )
)


REQUIRED = {
    # Predbat forecasts
    "predbat.pv_power_best":
        "Predbat solar forecast",

    "predbat.load_power_best":
        "Predbat house forecast",

    "predbat.soc_kw_best":
        "Predbat battery forecast",

    "predbat.best_export_energy":
        "Predbat export forecast",

    # Enphase actuals
    "sensor.predbat_enphase_5731818_pv_power":
        "Enphase actual solar",

    "sensor.predbat_enphase_5731818_load_power":
        "Enphase actual house load",

    "sensor.predbat_enphase_5731818_soc_kw":
        "Enphase actual battery",

    "sensor.predbat_enphase_5731818_grid_power":
        "Enphase actual grid",
}


if not TOKEN:
    print(
        "ERROR: HA_TOKEN is not set",
        flush=True
    )
    raise SystemExit(2)


headers={
    "Authorization":f"Bearer {TOKEN}",
    "Accept":"application/json",
}


def get_state(entity_id):
    req=urllib.request.Request(
        f"{HA_URL}/api/states/{entity_id}",
        headers=headers,
        method="GET",
    )

    try:
        with urllib.request.urlopen(
            req,
            timeout=10
        ) as response:

            payload=json.loads(
                response.read()
            )

            return (
                response.status,
                payload.get("state"),
                payload.get("attributes",{})
            )

    except urllib.error.HTTPError as exc:
        return (
            exc.code,
            None,
            {}
        )

    except Exception:
        return (
            0,
            None,
            {}
        )


def usable(entity_id,state,attrs):
    if state in (
        None,
        "",
        "unknown",
        "unavailable"
    ):
        return False

    # Forecast entities must also contain their
    # timestamped result series.
    if entity_id.startswith("predbat."):
        results=attrs.get("results")

        if not isinstance(results,dict):
            return False

        if not results:
            return False

    return True


started=time.monotonic()
attempt=0

print(
    "Waiting for Home Assistant energy stack...",
    flush=True
)

while True:

    attempt += 1

    ready=[]
    waiting=[]

    for entity_id,label in REQUIRED.items():

        code,state,attrs=get_state(
            entity_id
        )

        if (
            code == 200
            and usable(
                entity_id,
                state,
                attrs
            )
        ):
            ready.append(entity_id)

        else:
            reason=f"HTTP {code}"

            if code == 200:
                reason=f"state={state!r}"

                if entity_id.startswith(
                    "predbat."
                ):
                    results=attrs.get(
                        "results"
                    )

                    if not isinstance(
                        results,
                        dict
                    ) or not results:
                        reason += (
                            ", no forecast "
                            "results yet"
                        )

            waiting.append(
                (
                    entity_id,
                    label,
                    reason
                )
            )

    elapsed=int(
        time.monotonic()-started
    )

    print(
        f"Readiness check {attempt:02d}: "
        f"{len(ready)}/{len(REQUIRED)} ready "
        f"after {elapsed}s",
        flush=True
    )

    if not waiting:
        print(
            "All required Predbat and "
            "Enphase entities are ready.",
            flush=True
        )
        raise SystemExit(0)

    for entity_id,label,reason in waiting:
        print(
            f"  WAIT {entity_id} "
            f"({label}) -> {reason}",
            flush=True
        )

    if elapsed >= TIMEOUT_SECONDS:
        print(
            "",
            flush=True
        )
        print(
            f"ERROR: energy stack did not "
            f"become ready within "
            f"{TIMEOUT_SECONDS}s",
            flush=True
        )
        raise SystemExit(1)

    time.sleep(POLL_SECONDS)
