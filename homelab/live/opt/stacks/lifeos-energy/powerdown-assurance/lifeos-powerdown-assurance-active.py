#!/usr/bin/env python3

import json
import math
import os
import sqlite3
import statistics
import time
import urllib.request

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/London")
HA = "http://127.0.0.1:8123"

ROOT = Path("/opt/lifeos-watch/octopus-powerdown-assurance")
STATUS = ROOT / "active-status.json"
STATE = ROOT / "active-state-v48.json"
SAMPLES = ROOT / "grid-samples-v48.json"

DB = "/opt/stacks/homeassistant/config/home-assistant_v2.db"

EVENT = "event.octopus_energy_a_8b23e5b8_octoplus_power_down_events"
BASELINE = "sensor.octopus_energy_electricity_24e8170948_1100019745755_octoplus_power_down_baseline"

IMPORT = "sensor.lifeos_grid_import_power"
ENVOY = "sensor.envoy_122425011227_current_net_power_consumption"

SOC = "sensor.predbat_enphase_5731818_soc_percent"
CAPACITY = "sensor.predbat_enphase_5731818_battery_capacity"
RESERVE_MIN = "sensor.predbat_enphase_5731818_battery_reserve_min"
RESERVE_CONTROL = "number.predbat_enphase_5731818_battery_schedule_reserve"

LOAD = "sensor.predbat_enphase_5731818_load_power"
PV = "sensor.predbat_enphase_5731818_pv_power"
BATTERY = "sensor.predbat_enphase_5731818_battery_power"

SOC_FORECAST = "predbat.soc_kw_best"

GRID_TARGET_W = 0.0

MAX_SOURCE_AGE = 150
MAX_SOURCE_TIMESTAMP_DELTA = 90
MAX_GRID_DIFF_W = 100

# Independent telemetry must agree repeatedly before an active-event
# reserve release is permitted. Once trusted, one transient disagreement
# does not immediately destroy confidence, but two consecutive failures do.
CROSSCHECK_REQUIRED_GOOD_RUNS = 2
CROSSCHECK_MAX_BAD_RUNS = 1

SOC_MARGIN_PERCENT = 2.0
BATTERY_AC_EFFICIENCY = 0.92

READINESS_SAFETY_FACTOR = 1.20
DEFAULT_LOAD_W = 700.0

TOKEN = os.environ.get("HA_TOKEN")
if not TOKEN:
    raise SystemExit("HA_TOKEN missing")

ROOT.mkdir(parents=True, exist_ok=True)

now = datetime.now(TZ)


def atomic(path, data, mode=0o600):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def read_json(path, default):
    try:
        with path.open() as f:
            return json.load(f)
    except Exception:
        return default


def api(path, method="GET", body=None):
    raw = None

    if body is not None:
        raw = json.dumps(body).encode()

    req = urllib.request.Request(
        HA + path,
        method=method,
        data=raw,
        headers={
            "Authorization": "Bearer " + TOKEN,
            "Content-Type": "application/json",
        },
    )

    with urllib.request.urlopen(req, timeout=10) as r:
        data = r.read()

    if not data:
        return None

    return json.loads(data)


def get(entity):
    return api("/api/states/" + entity)


def numeric(entity):
    obj = get(entity)
    try:
        value = float(obj["state"])
    except Exception:
        value = None
    return value, obj


def updated_epoch(obj):
    """Return telemetry report time, falling back for older HA versions."""
    try:
        stamp = obj.get("last_reported") or obj["last_updated"]
        return datetime.fromisoformat(
            stamp.replace("Z", "+00:00")
        ).timestamp()
    except Exception:
        return 0.0


def age(obj):
    stamp = updated_epoch(obj)
    if not stamp:
        return 999999
    return time.time() - stamp


def set_number(entity, value):
    api(
        "/api/services/number/set_value",
        method="POST",
        body={
            "entity_id": entity,
            "value": float(value),
        },
    )


event_obj = get(EVENT)

baseline, baseline_obj = numeric(BASELINE)
grid_import, import_obj = numeric(IMPORT)
envoy_kw, envoy_obj = numeric(ENVOY)

soc, soc_obj = numeric(SOC)
capacity, capacity_obj = numeric(CAPACITY)
reserve_min, reserve_min_obj = numeric(RESERVE_MIN)
reserve_now, reserve_obj = numeric(RESERVE_CONTROL)

load_w, load_obj = numeric(LOAD)
pv_w, pv_obj = numeric(PV)
battery_w, battery_obj = numeric(BATTERY)


# -------------------------------------------------------------------
# 1. V51 SYNCHRONOUS GRID CROSS-CHECK
#
# V50 proved LifeOS and Envoy agree when observed on the same controller
# execution, but HA's integration-level last_updated timestamps can be
# phase shifted. Therefore:
#
#   • compare the values read in this execution
#   • independently require both source values to be fresh
#   • retain timestamp delta only as a plausibility guard
#   • build confidence over multiple controller executions
# -------------------------------------------------------------------

cross_state = read_json(
    SAMPLES,
    {
        "good_runs": 0,
        "bad_runs": 0,
        "trusted": False,
        "history": [],
    },
)

lifeos_import_w = (
    max(0.0, grid_import)
    if grid_import is not None
    else None
)

envoy_import_w = (
    max(0.0, envoy_kw * 1000.0)
    if envoy_kw is not None
    else None
)

lifeos_age = age(import_obj)
envoy_age = age(envoy_obj)

lifeos_timestamp = updated_epoch(import_obj)
envoy_timestamp = updated_epoch(envoy_obj)

source_timestamp_delta = None

if lifeos_timestamp and envoy_timestamp:
    source_timestamp_delta = abs(
        lifeos_timestamp - envoy_timestamp
    )

instantaneous_diff_w = None

if (
    lifeos_import_w is not None
    and envoy_import_w is not None
):
    instantaneous_diff_w = abs(
        lifeos_import_w - envoy_import_w
    )

lifeos_fresh = bool(
    lifeos_import_w is not None
    and lifeos_age <= MAX_SOURCE_AGE
)

envoy_fresh = bool(
    envoy_import_w is not None
    and envoy_age <= MAX_SOURCE_AGE
)

timestamp_plausible = bool(
    source_timestamp_delta is not None
    and source_timestamp_delta <= MAX_SOURCE_TIMESTAMP_DELTA
)

instantaneous_agreement = bool(
    instantaneous_diff_w is not None
    and instantaneous_diff_w <= MAX_GRID_DIFF_W
)

current_crosscheck_good = bool(
    lifeos_fresh
    and envoy_fresh
    and timestamp_plausible
    and instantaneous_agreement
)

good_runs = int(cross_state.get("good_runs", 0) or 0)
bad_runs = int(cross_state.get("bad_runs", 0) or 0)
trusted = bool(cross_state.get("trusted", False))

if current_crosscheck_good:
    good_runs += 1
    bad_runs = 0

    if good_runs >= CROSSCHECK_REQUIRED_GOOD_RUNS:
        trusted = True

else:
    bad_runs += 1
    good_runs = 0

    if bad_runs > CROSSCHECK_MAX_BAD_RUNS:
        trusted = False

history = cross_state.get("history", []) or []

history.append({
    "observed_at": now.isoformat(),
    "lifeos_import_w": lifeos_import_w,
    "envoy_import_w": envoy_import_w,
    "lifeos_age_seconds": round(lifeos_age, 1),
    "envoy_age_seconds": round(envoy_age, 1),
    "source_timestamp_delta_seconds": (
        round(source_timestamp_delta, 1)
        if source_timestamp_delta is not None
        else None
    ),
    "difference_w": (
        round(instantaneous_diff_w, 1)
        if instantaneous_diff_w is not None
        else None
    ),
    "current_good": current_crosscheck_good,
    "trusted": trusted,
})

history = history[-40:]

cross_state = {
    "good_runs": good_runs,
    "bad_runs": bad_runs,
    "trusted": trusted,
    "history": history,
}

atomic(
    SAMPLES,
    cross_state,
    0o600,
)

aligned_crosscheck_ok = trusted

best_pair = {
    "lifeos_w": lifeos_import_w,
    "envoy_w": envoy_import_w,
    "timestamp_delta_seconds": (
        source_timestamp_delta
        if source_timestamp_delta is not None
        else None
    ),
    "difference_w": (
        instantaneous_diff_w
        if instantaneous_diff_w is not None
        else None
    ),
    "lifeos_age_seconds": lifeos_age,
    "envoy_age_seconds": envoy_age,
    "current_good": current_crosscheck_good,
    "good_runs": good_runs,
    "bad_runs": bad_runs,
    "trusted": trusted,
}

authoritative_fresh = lifeos_fresh


# -------------------------------------------------------------------
# 2. EVENT DISCOVERY
# -------------------------------------------------------------------

joined = event_obj.get(
    "attributes", {}
).get(
    "joined_events", []
) or []

active = None
future = []

for e in joined:
    try:
        start = datetime.fromisoformat(
            e["start"]
        ).astimezone(TZ)

        end = datetime.fromisoformat(
            e["end"]
        ).astimezone(TZ)

    except Exception:
        continue

    if start <= now < end:
        active = (e, start, end)

    elif start > now:
        future.append((start, end, e))

future.sort(key=lambda x: x[0])

next_event = future[0] if future else None


# -------------------------------------------------------------------
# 3. HISTORICAL LOAD ENERGY ESTIMATE
#
# Ignore forecast solar entirely for readiness.
# Reconstruct same clock-period load for previous 7 days.
# -------------------------------------------------------------------

def integrate_history(entity, start, end):

    con = sqlite3.connect(
        f"file:{DB}?mode=ro",
        uri=True,
    )

    rows = con.execute(
        """
        SELECT s.last_updated_ts, s.state
        FROM states s
        JOIN states_meta sm
          ON sm.metadata_id = s.metadata_id
        WHERE sm.entity_id = ?
          AND s.last_updated_ts >= ?
          AND s.last_updated_ts <= ?
        ORDER BY s.last_updated_ts
        """,
        (
            entity,
            start.timestamp(),
            end.timestamp(),
        ),
    ).fetchall()

    con.close()

    vals = []

    for ts, state in rows:
        try:
            vals.append(
                (
                    float(ts),
                    max(0.0, float(state)),
                )
            )
        except Exception:
            pass

    if len(vals) < 2:
        return None

    energy_wh = 0.0

    for (t1, p1), (t2, p2) in zip(
        vals,
        vals[1:],
    ):
        dt = min(
            max(t2 - t1, 0),
            600,
        )

        energy_wh += (
            (p1 + p2) / 2.0
        ) * dt / 3600.0

    return energy_wh / 1000.0


historical_event_kwh = []

if next_event:
    event_start, event_end, _ = next_event

    for days_back in range(1, 8):
        s = event_start - timedelta(days=days_back)
        e = event_end - timedelta(days=days_back)

        val = integrate_history(
            LOAD,
            s,
            e,
        )

        if val is not None:
            historical_event_kwh.append(val)


def conservative_load_requirement():

    if next_event:
        duration_h = (
            next_event[1] - next_event[0]
        ).total_seconds() / 3600.0
    elif active:
        duration_h = (
            active[2] - active[1]
        ).total_seconds() / 3600.0
    else:
        duration_h = 1.0

    candidates = []

    if historical_event_kwh:
        ordered = sorted(historical_event_kwh)

        index = min(
            len(ordered) - 1,
            math.ceil(
                0.90 * len(ordered)
            ) - 1,
        )

        candidates.append(
            ordered[index]
        )

    if load_w is not None:
        candidates.append(
            load_w / 1000.0
            * duration_h
        )

    candidates.append(
        DEFAULT_LOAD_W / 1000.0
        * duration_h
    )

    base = max(candidates)

    return (
        base
        * READINESS_SAFETY_FACTOR
        / BATTERY_AC_EFFICIENCY
    )


required_battery_kwh = None

if next_event or active:
    required_battery_kwh = (
        conservative_load_requirement()
    )


# -------------------------------------------------------------------
# 4. TRY PREDBAT SOC FORECAST AT EVENT START
# -------------------------------------------------------------------

predicted_soc_kwh = None

if next_event:
    try:
        obj = get(SOC_FORECAST)
        results = obj.get(
            "attributes", {}
        ).get(
            "results", {}
        )

        points = []

        if isinstance(results, dict):
            iterator = results.items()
        elif isinstance(results, list):
            iterator = results
        else:
            iterator = []

        for item in iterator:
            try:
                if isinstance(item, tuple):
                    stamp, value = item

                elif isinstance(item, list) and len(item) >= 2:
                    stamp, value = item[0], item[1]

                elif isinstance(item, dict):
                    stamp = (
                        item.get("time")
                        or item.get("timestamp")
                        or item.get("datetime")
                    )
                    value = (
                        item.get("value")
                        or item.get("state")
                        or item.get("soc")
                    )

                else:
                    continue

                dt = datetime.fromisoformat(
                    str(stamp).replace(
                        "Z",
                        "+00:00",
                    )
                ).astimezone(TZ)

                points.append(
                    (
                        abs(
                            (
                                dt
                                - next_event[0]
                            ).total_seconds()
                        ),
                        float(value),
                    )
                )

            except Exception:
                continue

        if points:
            points.sort(
                key=lambda x: x[0]
            )

            if points[0][0] <= 1800:
                predicted_soc_kwh = points[0][1]

    except Exception:
        pass


# -------------------------------------------------------------------
# 5. READINESS
# -------------------------------------------------------------------

current_soc_kwh = None

if (
    soc is not None
    and capacity is not None
):
    current_soc_kwh = (
        soc / 100.0
        * capacity
    )

reserve_floor_percent = None

if reserve_min is not None:
    reserve_floor_percent = (
        reserve_min
        + SOC_MARGIN_PERCENT
    )

available_source_soc_kwh = (
    predicted_soc_kwh
    if predicted_soc_kwh is not None
    else current_soc_kwh
)

usable_at_event_kwh = None

if (
    available_source_soc_kwh is not None
    and capacity is not None
    and reserve_floor_percent is not None
):
    reserve_kwh = (
        reserve_floor_percent
        / 100.0
        * capacity
    )

    usable_at_event_kwh = max(
        available_source_soc_kwh
        - reserve_kwh,
        0.0,
    ) * BATTERY_AC_EFFICIENCY


readiness = "NO_EVENT"

if next_event:
    if (
        required_battery_kwh is not None
        and usable_at_event_kwh is not None
    ):
        readiness = (
            "READY"
            if usable_at_event_kwh
            >= required_battery_kwh
            else "NOT_READY"
        )
    else:
        readiness = "UNKNOWN"


# -------------------------------------------------------------------
# 6. EVENT ENERGY INTEGRATION + RESERVE OWNERSHIP
# -------------------------------------------------------------------

internal = read_json(
    STATE,
    {},
)

previous_event_id = internal.get(
    "event_id"
)

integrated = float(
    internal.get(
        "event_import_kwh",
        0.0,
    )
)

last_epoch = internal.get(
    "last_epoch"
)

last_import = internal.get(
    "last_import_w"
)

saved_reserve = internal.get(
    "saved_reserve_percent"
)

owns_reserve = bool(
    internal.get(
        "owns_reserve",
        False,
    )
)

event_id = (
    active[0].get("id")
    if active
    else None
)

write_performed = False
action = "NO_WRITE_OUTSIDE_EVENT"
blocked_reason = None
restored = False


if active:

    if previous_event_id != event_id:
        integrated = 0.0
        last_epoch = None
        last_import = None

        saved_reserve = reserve_now
        owns_reserve = False

    epoch = time.time()

    if (
        last_epoch is not None
        and last_import is not None
        and grid_import is not None
    ):
        dt = min(
            max(
                epoch
                - float(last_epoch),
                0.0,
            ),
            90.0,
        )

        avg = (
            max(float(last_import), 0.0)
            + max(grid_import, 0.0)
        ) / 2.0

        integrated += (
            avg
            * dt
            / 3600000.0
        )

    safe_soc = bool(
        soc is not None
        and reserve_floor_percent is not None
        and soc > reserve_floor_percent
    )

    if not authoritative_fresh:
        action = "BLOCKED"
        blocked_reason = "authoritative_grid_stale"

    elif not aligned_crosscheck_ok:
        action = "BLOCKED"
        blocked_reason = "independent_grid_crosscheck_not_trusted"

    elif not safe_soc:
        action = "BLOCKED"
        blocked_reason = "battery_soc_low"

    elif (
        reserve_min is None
        or reserve_now is None
    ):
        action = "BLOCKED"
        blocked_reason = "reserve_interface_unavailable"

    else:
        # Only release reserve.
        # Do not command discharge rate.
        if abs(
            reserve_now
            - reserve_min
        ) > 0.1:
            set_number(
                RESERVE_CONTROL,
                reserve_min,
            )

            write_performed = True

        owns_reserve = True
        action = "ACTIVE_EVENT_RESERVE_RELEASE"

    internal = {
        "event_id": event_id,
        "last_epoch": epoch,
        "last_import_w": grid_import,
        "event_import_kwh": integrated,
        "saved_reserve_percent": saved_reserve,
        "owns_reserve": owns_reserve,
    }


else:

    # Restore only if:
    #   V48 previously took ownership,
    #   a previous reserve is known,
    #   current reserve is still approximately the minimum.
    #
    # If Predbat has already changed it, do NOT fight Predbat.
    if (
        owns_reserve
        and saved_reserve is not None
        and reserve_now is not None
        and reserve_min is not None
        and abs(
            reserve_now
            - reserve_min
        ) <= 0.5
    ):
        set_number(
            RESERVE_CONTROL,
            saved_reserve,
        )

        write_performed = True
        restored = True
        action = "POST_EVENT_RESERVE_RESTORE"

    internal = {
        "event_id": None,
        "last_epoch": None,
        "last_import_w": None,
        "event_import_kwh": 0.0,
        "saved_reserve_percent": None,
        "owns_reserve": False,
    }


atomic(
    STATE,
    internal,
    0o600,
)


# -------------------------------------------------------------------
# 7. STATUS
# -------------------------------------------------------------------

conservative_target = (
    baseline * 0.5
    if baseline is not None
    else None
)

remaining_budget = (
    max(
        conservative_target
        - integrated,
        0.0,
    )
    if conservative_target is not None
    else None
)

flags = []

if not authoritative_fresh:
    flags.append(
        "authoritative_grid_stale"
    )

if not aligned_crosscheck_ok:
    flags.append(
        "aligned_crosscheck_unavailable"
    )

if readiness == "NOT_READY":
    flags.append(
        "future_powerdown_battery_not_ready"
    )

if (
    active
    and grid_import is not None
    and grid_import > 100
):
    flags.append(
        "active_event_import_above_100w"
    )

if (
    active
    and conservative_target is not None
    and integrated >= conservative_target
):
    flags.append(
        "conservative_import_budget_exceeded"
    )


status = {
    "schema": "lifeos.powerdown_assurance.v51",

    "generated_at": now.isoformat(),

    "mode": "ARMED_ACTIVE_EVENT_ONLY",

    "policy": {
        "grid_import_target_w": GRID_TARGET_W,
        "artificial_baseline_inflation": False,
        "forced_precharge_enabled": False,
        "solar_credit_in_readiness": False,
    },

    "event": {
        "active": bool(active),

        "id": event_id,

        "start": (
            active[1].isoformat()
            if active else None
        ),

        "end": (
            active[2].isoformat()
            if active else None
        ),

        "next_event": (
            {
                "id": next_event[2].get("id"),
                "start": next_event[0].isoformat(),
                "end": next_event[1].isoformat(),
            }
            if next_event
            else None
        ),
    },

    "readiness": {
        "state": readiness,

        "historical_event_samples":
            len(historical_event_kwh),

        "historical_event_energy_kwh":
            [
                round(x, 3)
                for x in historical_event_kwh
            ],

        "required_battery_energy_kwh":
            (
                round(
                    required_battery_kwh,
                    3,
                )
                if required_battery_kwh
                is not None
                else None
            ),

        "predicted_soc_at_event_kwh":
            predicted_soc_kwh,

        "current_soc_kwh":
            current_soc_kwh,

        "usable_energy_at_event_kwh":
            (
                round(
                    usable_at_event_kwh,
                    3,
                )
                if usable_at_event_kwh
                is not None
                else None
            ),
    },

    "baseline": {
        "native_kwh": baseline,

        "conservative_target_kwh":
            conservative_target,
    },

    "event_energy": {
        "integrated_import_kwh":
            round(
                integrated,
                6,
            ),

        "remaining_conservative_budget_kwh":
            (
                round(
                    remaining_budget,
                    6,
                )
                if remaining_budget
                is not None
                else None
            ),
    },

    "telemetry": {
        "lifeos_grid_import_w":
            grid_import,

        "lifeos_age_seconds":
            round(
                age(import_obj),
                1,
            ),

        "current_envoy_import_w":
            (
                max(
                    0.0,
                    envoy_kw * 1000.0,
                )
                if envoy_kw is not None
                else None
            ),

        "crosscheck":
            best_pair,

        "crosscheck_pass":
            aligned_crosscheck_ok,

        # Compatibility keys retained temporarily for existing
        # dashboards/readers.
        "aligned_crosscheck":
            best_pair,

        "aligned_crosscheck_pass":
            aligned_crosscheck_ok,

        "load_w": load_w,
        "pv_w": pv_w,
        "battery_w": battery_w,
        "battery_soc_percent": soc,
        "battery_capacity_kwh": capacity,
    },

    "reserve": {
        "current_percent":
            reserve_now,

        "native_min_percent":
            reserve_min,

        "saved_pre_event_percent":
            saved_reserve,

        "controller_owns_reserve":
            owns_reserve,

        "restored_this_run":
            restored,
    },

    "control": {
        "action": action,

        "write_performed":
            write_performed,

        "blocked_reason":
            blocked_reason,
    },

    "anomaly_flags": flags,
}

atomic(
    STATUS,
    status,
    0o644,
)


print("CONTROLLER_STATUS=PASS")
print("SCHEMA=lifeos.powerdown_assurance.v51")
print("POWERDOWN_ACTIVE="+("yes" if active else "no"))

if next_event:
    print("NEXT_POWERDOWN_START="+next_event[0].isoformat())
    print("NEXT_POWERDOWN_END="+next_event[1].isoformat())
else:
    print("NEXT_POWERDOWN=none")

print("READINESS="+readiness)

print(
    "REQUIRED_BATTERY_KWH="
    +str(
        round(
            required_battery_kwh,
            3,
        )
        if required_battery_kwh is not None
        else None
    )
)

print(
    "USABLE_AT_EVENT_KWH="
    +str(
        round(
            usable_at_event_kwh,
            3,
        )
        if usable_at_event_kwh is not None
        else None
    )
)

print(
    "PREDICTED_SOC_AT_EVENT_KWH="
    +str(predicted_soc_kwh)
)

print(
    "GRID_CROSSCHECK_TRUST="
    +("PASS" if aligned_crosscheck_ok else "HOLD")
)

print(
    "GRID_CROSSCHECK_CURRENT="
    +("PASS" if current_crosscheck_good else "FAIL")
)

print("GRID_CROSSCHECK_GOOD_RUNS="+str(good_runs))
print("GRID_CROSSCHECK_BAD_RUNS="+str(bad_runs))

if best_pair:
    print(
        "GRID_CROSSCHECK_DIFF_W="
        +str(
            round(
                best_pair["difference_w"],
                1,
            )
        )
    )

    print(
        "GRID_SOURCE_TIMESTAMP_DELTA_S="
        +str(
            round(
                best_pair["timestamp_delta_seconds"],
                1,
            )
        )
    )
else:
    print("GRID_CROSSCHECK_PAIR=none")

print("GRID_IMPORT_W="+str(grid_import))
print("BATTERY_SOC_PERCENT="+str(soc))
print("RESERVE_NOW_PERCENT="+str(reserve_now))
print("RESERVE_MIN_PERCENT="+str(reserve_min))
print("ACTION="+action)
print("WRITE_PERFORMED="+("yes" if write_performed else "no"))
print("RESERVE_RESTORED="+("yes" if restored else "no"))
print("EVENT_IMPORT_KWH="+f"{integrated:.6f}")

print(
    "ANOMALY_FLAGS="
    +(
        ",".join(flags)
        if flags
        else "none"
    )
)

print("STATUS="+str(STATUS))
