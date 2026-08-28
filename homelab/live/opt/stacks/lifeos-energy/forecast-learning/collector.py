#!/usr/bin/env python3

import bisect
import json
import os
import sqlite3
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request

from datetime import datetime, timezone


HA_URL=os.environ.get(
    "HA_URL",
    "http://127.0.0.1:8123"
).rstrip("/")

TOKEN=os.environ["HA_TOKEN"]

DB=os.environ.get(
    "FORECAST_DB",
    "/opt/stacks/lifeos-energy/forecast-learning/forecast_history.sqlite"
)

HORIZON_MIN=int(
    os.environ.get(
        "FORECAST_HORIZON_MINUTES",
        "30"
    )
)

GRID_SECONDS=300
MAX_FORECAST_SECONDS=48*3600
RETENTION_SECONDS=30*86400


FORECAST_ENTITIES={
    "solar_kw":"predbat.pv_power_best",
    "house_kw":"predbat.load_power_best",
    "battery_kwh":"predbat.soc_kw_best",
    "export_cumulative_kwh":"predbat.best_export_energy",
}

ACTUAL_ENTITIES={
    "solar_w":"sensor.predbat_enphase_5731818_pv_power",
    "house_w":"sensor.predbat_enphase_5731818_load_power",
    "battery_kwh":"sensor.predbat_enphase_5731818_soc_kw",
    "grid_w":"sensor.predbat_enphase_5731818_grid_power",
}


def log(msg):
    stamp=datetime.now().astimezone().isoformat(timespec="seconds")
    print(f"[{stamp}] {msg}", flush=True)


def request(path, method="GET", body=None):
    url=HA_URL+path

    data=None

    headers={
        "Authorization":f"Bearer {TOKEN}",
        "Content-Type":"application/json",
    }

    if body is not None:
        data=json.dumps(body).encode()

    req=urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method
    )

    with urllib.request.urlopen(req, timeout=20) as response:
        raw=response.read()

    if not raw:
        return None

    return json.loads(raw)


def state(entity_id):
    return request(f"/api/states/{entity_id}")


def numeric_state(entity_id):
    x=state(entity_id)

    raw=x.get("state")

    if raw in (
        None,
        "unknown",
        "unavailable",
        ""
    ):
        raise RuntimeError(
            f"{entity_id} has invalid state {raw!r}"
        )

    return float(raw)


def parse_timestamp(value):
    # Python handles both:
    #   +01:00
    #   +0100
    dt=datetime.fromisoformat(value)

    if dt.tzinfo is None:
        dt=dt.replace(tzinfo=timezone.utc)

    return int(dt.timestamp())


def get_results(entity_id):
    x=state(entity_id)

    results=x.get("attributes",{}).get("results")

    if not isinstance(results,dict):
        raise RuntimeError(
            f"{entity_id} has no results dictionary"
        )

    points=[]

    for stamp,value in results.items():
        try:
            t=parse_timestamp(stamp)
            v=float(value)
        except Exception:
            continue

        points.append((t,v))

    points.sort()

    if len(points)<2:
        raise RuntimeError(
            f"{entity_id} has insufficient forecast points"
        )

    return points


def interpolate(points, target):
    times=[p[0] for p in points]

    pos=bisect.bisect_left(times,target)

    if pos<len(points) and points[pos][0]==target:
        return points[pos][1]

    if pos==0:
        return points[0][1]

    if pos>=len(points):
        return points[-1][1]

    t0,v0=points[pos-1]
    t1,v1=points[pos]

    if t1==t0:
        return v0

    ratio=(target-t0)/(t1-t0)

    return v0+(v1-v0)*ratio


def derive_export_power(cumulative):
    result=[]

    for i in range(len(cumulative)-1):
        t0,e0=cumulative[i]
        t1,e1=cumulative[i+1]

        seconds=t1-t0

        if seconds<=0:
            continue

        hours=seconds/3600.0

        kw=(e1-e0)/hours

        # Predbat cumulative export should never imply
        # negative export power.
        kw=max(0.0,kw)

        result.append((t0,kw))

    if result:
        result.append(
            (
                cumulative[-1][0],
                result[-1][1]
            )
        )

    return result


def connect():
    db=sqlite3.connect(DB)

    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")

    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS forecast_snapshots (
            issued_at INTEGER NOT NULL,
            target_at INTEGER NOT NULL,
            metric TEXT NOT NULL,
            value REAL NOT NULL,
            PRIMARY KEY (
                issued_at,
                target_at,
                metric
            )
        );

        CREATE INDEX IF NOT EXISTS
        idx_forecast_lookup
        ON forecast_snapshots (
            metric,
            target_at,
            issued_at
        );

        CREATE TABLE IF NOT EXISTS actual_samples (
            target_at INTEGER PRIMARY KEY,
            solar_kw REAL,
            house_kw REAL,
            battery_kwh REAL,
            export_kw REAL
        );

        CREATE TABLE IF NOT EXISTS forecast_errors (
            target_at INTEGER NOT NULL,
            horizon_minutes INTEGER NOT NULL,

            solar_forecast_kw REAL,
            solar_actual_kw REAL,
            solar_error_kw REAL,

            house_forecast_kw REAL,
            house_actual_kw REAL,
            house_error_kw REAL,

            battery_forecast_kwh REAL,
            battery_actual_kwh REAL,
            battery_error_kwh REAL,

            export_forecast_kw REAL,
            export_actual_kw REAL,
            export_error_kw REAL,

            PRIMARY KEY (
                target_at,
                horizon_minutes
            )
        );
        """
    )

    return db


def save_forecasts(db,issued_at):
    log("Downloading Predbat forecast series")

    solar=get_results(
        FORECAST_ENTITIES["solar_kw"]
    )

    house=get_results(
        FORECAST_ENTITIES["house_kw"]
    )

    battery=get_results(
        FORECAST_ENTITIES["battery_kwh"]
    )

    export_cumulative=get_results(
        FORECAST_ENTITIES["export_cumulative_kwh"]
    )

    export_power=derive_export_power(
        export_cumulative
    )

    series={
        "solar_kw":solar,
        "house_kw":house,
        "battery_kwh":battery,
        "export_kw":export_power,
    }

    first_target=(
        (issued_at+GRID_SECONDS-1)
        // GRID_SECONDS
        * GRID_SECONDS
    )

    final_target=issued_at+MAX_FORECAST_SECONDS

    inserted=0

    for target in range(
        first_target,
        final_target+1,
        GRID_SECONDS
    ):
        for metric,points in series.items():
            if (
                not points
                or target<points[0][0]
                or target>points[-1][0]
            ):
                continue

            value=interpolate(points,target)

            db.execute(
                """
                INSERT OR REPLACE INTO forecast_snapshots
                (
                    issued_at,
                    target_at,
                    metric,
                    value
                )
                VALUES (?,?,?,?)
                """,
                (
                    issued_at,
                    target,
                    metric,
                    value
                )
            )

            inserted+=1

    db.commit()

    log(
        f"Stored {inserted} timestamped forecast values"
    )

    return inserted


def save_actual(db,target_at):
    solar_kw=max(
        0.0,
        numeric_state(
            ACTUAL_ENTITIES["solar_w"]
        )/1000.0
    )

    house_kw=max(
        0.0,
        numeric_state(
            ACTUAL_ENTITIES["house_w"]
        )/1000.0
    )

    battery_kwh=max(
        0.0,
        numeric_state(
            ACTUAL_ENTITIES["battery_kwh"]
        )
    )

    grid_kw=(
        numeric_state(
            ACTUAL_ENTITIES["grid_w"]
        )/1000.0
    )

    # Enphase convention:
    # negative grid power = export.
    export_kw=max(
        0.0,
        -grid_kw
    )

    values={
        "solar_kw":solar_kw,
        "house_kw":house_kw,
        "battery_kwh":battery_kwh,
        "export_kw":export_kw,
    }

    db.execute(
        """
        INSERT OR REPLACE INTO actual_samples
        (
            target_at,
            solar_kw,
            house_kw,
            battery_kwh,
            export_kw
        )
        VALUES (?,?,?,?,?)
        """,
        (
            target_at,
            solar_kw,
            house_kw,
            battery_kwh,
            export_kw
        )
    )

    db.commit()

    log(
        "Actual: "
        f"solar={solar_kw:.3f}kW "
        f"house={house_kw:.3f}kW "
        f"battery={battery_kwh:.3f}kWh "
        f"export={export_kw:.3f}kW"
    )

    return values


def find_locked_forecast(
    db,
    metric,
    target_at
):
    desired=(
        target_at
        - HORIZON_MIN*60
    )

    tolerance=5*60

    row=db.execute(
        """
        SELECT
            issued_at,
            value
        FROM forecast_snapshots
        WHERE metric=?
          AND target_at=?
          AND issued_at BETWEEN ? AND ?
        ORDER BY ABS(issued_at-?)
        LIMIT 1
        """,
        (
            metric,
            target_at,
            desired-tolerance,
            desired+tolerance,
            desired
        )
    ).fetchone()

    if row is None:
        return None

    return {
        "issued_at":row[0],
        "value":row[1]
    }


def calculate_errors(
    db,
    target_at,
    actual
):
    forecast={}

    for metric in (
        "solar_kw",
        "house_kw",
        "battery_kwh",
        "export_kw"
    ):
        found=find_locked_forecast(
            db,
            metric,
            target_at
        )

        if found is None:
            log(
                f"No locked {HORIZON_MIN}-minute "
                f"forecast yet for {metric}"
            )

            return None

        forecast[metric]=found["value"]

    errors={
        metric:
            actual[metric]-forecast[metric]
        for metric in forecast
    }

    db.execute(
        """
        INSERT OR REPLACE INTO forecast_errors
        (
            target_at,
            horizon_minutes,

            solar_forecast_kw,
            solar_actual_kw,
            solar_error_kw,

            house_forecast_kw,
            house_actual_kw,
            house_error_kw,

            battery_forecast_kwh,
            battery_actual_kwh,
            battery_error_kwh,

            export_forecast_kw,
            export_actual_kw,
            export_error_kw
        )
        VALUES (
            ?,?,
            ?,?,?,
            ?,?,?,
            ?,?,?,
            ?,?,?
        )
        """,
        (
            target_at,
            HORIZON_MIN,

            forecast["solar_kw"],
            actual["solar_kw"],
            errors["solar_kw"],

            forecast["house_kw"],
            actual["house_kw"],
            errors["house_kw"],

            forecast["battery_kwh"],
            actual["battery_kwh"],
            errors["battery_kwh"],

            forecast["export_kw"],
            actual["export_kw"],
            errors["export_kw"],
        )
    )

    db.commit()

    log(
        "Forecast errors: "
        f"solar={errors['solar_kw']:+.3f}kW "
        f"house={errors['house_kw']:+.3f}kW "
        f"battery={errors['battery_kwh']:+.3f}kWh "
        f"export={errors['export_kw']:+.3f}kW"
    )

    return {
        "forecast":forecast,
        "errors":errors
    }



# LIFEOS_MQTT_TRANSPORT_V1
MQTT_HOST=os.environ.get("MQTT_HOST","127.0.0.1")
MQTT_PORT=int(os.environ.get("MQTT_PORT","1883"))
MQTT_STATE_TOPIC="lifeos/energy/forecast/state"
MQTT_DISCOVERY_PREFIX="homeassistant"

MQTT_STATE={
    "forecast_horizon_minutes":HORIZON_MIN,
    "errors":{},
    "recorder":{},
}

def mqtt_publish(topic,payload,retain=True):
    if not isinstance(payload,str):
        payload=json.dumps(payload,separators=(",",":"))

    cmd=[
        "mosquitto_pub",
        "-h",MQTT_HOST,
        "-p",str(MQTT_PORT),
        "-t",topic,
        "-m",payload,
    ]

    if retain:
        cmd.append("-r")

    result=subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=10,
    )

    if result.returncode != 0:
        raise RuntimeError(
            result.stderr[-500:]
            or f"MQTT publish failed for {topic}"
        )

def mqtt_discovery(
    object_id,
    name,
    value_template,
    unit=None,
    device_class=None,
):
    config={
        "name":name,
        "unique_id":f"lifeos_{object_id}_mqtt_v1",
        "state_topic":MQTT_STATE_TOPIC,
        "value_template":value_template,
        "availability_topic":"lifeos/status",
        "payload_available":"online",
        "payload_not_available":"offline",
        "device":{
            "identifiers":["lifeos_energy_learning"],
            "name":"LifeOS Energy Learning",
            "manufacturer":"LifeOS",
        },
    }

    if unit:
        config["unit_of_measurement"]=unit
        config["state_class"]="measurement"

    if device_class:
        config["device_class"]=device_class

    mqtt_publish(
        f"{MQTT_DISCOVERY_PREFIX}/sensor/"
        f"lifeos_{object_id}_mqtt_v1/config",
        config,
        True,
    )

def publish_mqtt_discovery():
    mqtt_discovery(
        "forecast_error_solar_30m",
        "LifeOS Forecast Error Solar 30m MQTT",
        "{{ value_json.errors.solar.state }}",
        "kW",
        "power",
    )

    mqtt_discovery(
        "forecast_error_house_30m",
        "LifeOS Forecast Error House 30m MQTT",
        "{{ value_json.errors.house.state }}",
        "kW",
        "power",
    )

    mqtt_discovery(
        "forecast_error_battery_30m",
        "LifeOS Forecast Error Battery 30m MQTT",
        "{{ value_json.errors.battery.state }}",
        "kWh",
        "energy",
    )

    mqtt_discovery(
        "forecast_error_export_30m",
        "LifeOS Forecast Error Export 30m MQTT",
        "{{ value_json.errors.export.state }}",
        "kW",
        "power",
    )

    mqtt_discovery(
        "forecast_recorder",
        "LifeOS Forecast Recorder MQTT",
        "{{ value_json.get('recorder', {}).get('state', 'unknown') }}",
    )

def publish_mqtt_state():
    MQTT_STATE["generated_at"] = (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
    )

    mqtt_publish(
        "lifeos/status",
        "online",
        True,
    )

    publish_mqtt_discovery()

    mqtt_publish(
        MQTT_STATE_TOPIC,
        MQTT_STATE,
        True,
    )




def publish_errors(result,target_at):
    iso=datetime.fromtimestamp(
        target_at,
        timezone.utc
    ).isoformat()

    if result is None:
        for key in (
            "solar",
            "house",
            "battery",
            "export",
        ):
            MQTT_STATE["errors"][key]={
                "state":"unavailable",
                "status":"collecting_baseline",
                "target_timestamp":iso,
            }

        publish_mqtt_state()
        return

    errors=result["errors"]
    forecast=result["forecast"]

    mapping={
        "solar":("solar_kw","kW"),
        "house":("house_kw","kW"),
        "battery":("battery_kwh","kWh"),
        "export":("export_kw","kW"),
    }

    for key,(metric,unit) in mapping.items():
        MQTT_STATE["errors"][key]={
            "state":round(float(errors[metric]),4),
            "status":"ready",
            "unit":unit,
            "target_timestamp":iso,
            "locked_forecast":round(
                float(forecast[metric]),
                4,
            ),
            "calculation":"actual - forecast",
        }

    publish_mqtt_state()




def publish_health(db):
    forecast_count=db.execute(
        "SELECT COUNT(*) FROM forecast_snapshots"
    ).fetchone()[0]

    actual_count=db.execute(
        "SELECT COUNT(*) FROM actual_samples"
    ).fetchone()[0]

    error_count=db.execute(
        """
        SELECT COUNT(*)
        FROM forecast_errors
        WHERE horizon_minutes=?
        """,
        (HORIZON_MIN,)
    ).fetchone()[0]

    MQTT_STATE["recorder"]={
        "state":"running",
        "forecast_snapshots":forecast_count,
        "actual_samples":actual_count,
        "error_samples":error_count,
        "forecast_horizon_minutes":HORIZON_MIN,
        "database":DB,
    }

    publish_mqtt_state()

    log(
        "Database: "
        f"{forecast_count} forecast rows, "
        f"{actual_count} actual rows, "
        f"{error_count} error rows"
    )



def prune(db,now):
    cutoff=now-RETENTION_SECONDS

    db.execute(
        "DELETE FROM forecast_snapshots WHERE target_at<?",
        (cutoff,)
    )

    db.execute(
        "DELETE FROM actual_samples WHERE target_at<?",
        (cutoff,)
    )

    db.execute(
        "DELETE FROM forecast_errors WHERE target_at<?",
        (cutoff,)
    )

    db.commit()


def main():
    now=int(time.time())

    issued_at=(
        now
        // GRID_SECONDS
        * GRID_SECONDS
    )

    target_at=issued_at

    os.makedirs(
        os.path.dirname(DB),
        exist_ok=True
    )

    db=connect()

    log(
        f"Forecast collector started; "
        f"horizon={HORIZON_MIN} minutes"
    )

    save_forecasts(
        db,
        issued_at
    )

    actual=save_actual(
        db,
        target_at
    )

    result=calculate_errors(
        db,
        target_at,
        actual
    )

    publish_errors(
        result,
        target_at
    )

    prune(db,now)

    publish_health(db)

    db.close()

    log("Collector completed successfully")


if __name__=="__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
