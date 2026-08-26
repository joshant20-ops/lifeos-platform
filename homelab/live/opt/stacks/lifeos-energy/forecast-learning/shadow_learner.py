#!/usr/bin/env python3

import json
import math
import os
import sqlite3
import statistics
import sys
import urllib.error
import urllib.request

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


DB_PATH=Path(
    os.environ.get(
        "FORECAST_DB",
        "/opt/stacks/lifeos-energy/forecast-learning/"
        "forecast_history.sqlite"
    )
)

REPORT_PATH=Path(
    os.environ.get(
        "SHADOW_REPORT",
        "/opt/stacks/lifeos-energy/forecast-learning/"
        "shadow_learning_report.json"
    )
)

HORIZON=30
LOCAL_TZ=ZoneInfo("Europe/London")

# Minimum number of PRIOR observations before scoring begins.
MIN_TRAINING_SAMPLES=24

# Maximum recent history used for the broad correction.
# 7 days at approximately five-minute intervals.
GLOBAL_WINDOW=2016

# Local-hour data window.
HOUR_WINDOW=336

# Bayesian-style shrinkage:
# sparse hour-specific learning is blended toward broad behaviour.
HOUR_SHRINKAGE=18

# Hard safety bounds on any learned additive correction.
# These are deliberately conservative because this is shadow mode.
CORRECTION_LIMITS={
    "solar_kw": 1.00,
    "house_kw": 1.00,
    "battery_kwh": 0.50,
    "export_kw": 1.50,
}

METRICS={
    "solar_kw":{
        "forecast":"solar_forecast_kw",
        "actual":"solar_actual_kw",
        "error":"solar_error_kw",
        "unit":"kW",
    },
    "house_kw":{
        "forecast":"house_forecast_kw",
        "actual":"house_actual_kw",
        "error":"house_error_kw",
        "unit":"kW",
    },
    "battery_kwh":{
        "forecast":"battery_forecast_kwh",
        "actual":"battery_actual_kwh",
        "error":"battery_error_kwh",
        "unit":"kWh",
    },
    "export_kw":{
        "forecast":"export_forecast_kw",
        "actual":"export_actual_kw",
        "error":"export_error_kw",
        "unit":"kW",
    },
}


def log(msg):
    print(
        f"[{datetime.now(LOCAL_TZ).isoformat(timespec='seconds')}] "
        f"{msg}",
        flush=True,
    )


def mean(values):
    if not values:
        return 0.0
    return sum(values)/len(values)


def mae(values):
    if not values:
        return None
    return sum(abs(v) for v in values)/len(values)


def rmse(values):
    if not values:
        return None
    return math.sqrt(
        sum(v*v for v in values)/len(values)
    )


def clamp(value, lower, upper):
    return max(lower,min(upper,value))


def local_hour(timestamp):
    return datetime.fromtimestamp(
        timestamp,
        LOCAL_TZ
    ).hour


def create_schema(db):
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS shadow_predictions (
            target_at INTEGER NOT NULL,
            horizon_minutes INTEGER NOT NULL,
            metric TEXT NOT NULL,

            raw_forecast REAL NOT NULL,
            learned_correction REAL NOT NULL,
            corrected_forecast REAL NOT NULL,
            actual REAL NOT NULL,

            raw_error REAL NOT NULL,
            corrected_error REAL NOT NULL,

            training_samples INTEGER NOT NULL,
            local_training_samples INTEGER NOT NULL,
            method TEXT NOT NULL,

            PRIMARY KEY (
                target_at,
                horizon_minutes,
                metric
            )
        );

        CREATE INDEX IF NOT EXISTS idx_shadow_metric_time
        ON shadow_predictions (
            metric,
            target_at
        );

        CREATE TABLE IF NOT EXISTS shadow_learning_runs (
            run_at INTEGER PRIMARY KEY,
            source_error_rows INTEGER NOT NULL,
            scored_predictions INTEGER NOT NULL,
            mode TEXT NOT NULL,
            report_json TEXT NOT NULL
        );
        """
    )
    db.commit()


def fetch_error_rows(db):
    cols=[
        "target_at",
        "solar_forecast_kw",
        "solar_actual_kw",
        "solar_error_kw",
        "house_forecast_kw",
        "house_actual_kw",
        "house_error_kw",
        "battery_forecast_kwh",
        "battery_actual_kwh",
        "battery_error_kwh",
        "export_forecast_kw",
        "export_actual_kw",
        "export_error_kw",
    ]

    sql=f"""
        SELECT {",".join(cols)}
        FROM forecast_errors
        WHERE horizon_minutes=?
        ORDER BY target_at
    """

    cur=db.execute(sql,(HORIZON,))
    result=[]

    for row in cur:
        result.append(dict(zip(cols,row)))

    return result


def calculate_correction(
    history,
    timestamp,
    metric,
):
    """
    IMPORTANT:
    history contains ONLY samples earlier than timestamp.

    This means historical evaluation is walk-forward and does
    not train on the value it is attempting to predict.
    """

    prior=history[metric]

    if len(prior) < MIN_TRAINING_SAMPLES:
        return None

    broad=prior[-GLOBAL_WINDOW:]
    broad_errors=[
        item["error"]
        for item in broad
    ]

    broad_bias=mean(broad_errors)

    hour=local_hour(timestamp)

    # ±1 local-clock-hour allows useful time-of-day learning
    # while still keeping bins populated.
    local=[
        item
        for item in prior[-HOUR_WINDOW:]
        if min(
            (item["hour"]-hour) % 24,
            (hour-item["hour"]) % 24,
        ) <= 1
    ]

    local_errors=[
        item["error"]
        for item in local
    ]

    local_bias=(
        mean(local_errors)
        if local_errors
        else broad_bias
    )

    weight=(
        len(local_errors)
        /
        (len(local_errors)+HOUR_SHRINKAGE)
    )

    blended=(
        weight*local_bias
        +
        (1-weight)*broad_bias
    )

    limit=CORRECTION_LIMITS[metric]
    correction=clamp(
        blended,
        -limit,
        limit,
    )

    return {
        "correction":correction,
        "global_bias":broad_bias,
        "local_bias":local_bias,
        "training_samples":len(prior),
        "local_training_samples":len(local_errors),
        "method":"walk_forward_hour_bias_v1",
    }


def physically_bound(metric,value):
    # These four quantities cannot physically be negative.
    return max(0.0,value)


def rebuild_shadow_predictions(db,rows):
    history=defaultdict(list)

    db.execute(
        "DELETE FROM shadow_predictions"
    )

    scored=0

    for row in rows:
        timestamp=int(row["target_at"])
        hour=local_hour(timestamp)

        # Calculate prediction BEFORE adding this target to history.
        for metric,spec in METRICS.items():
            raw=row[spec["forecast"]]
            actual=row[spec["actual"]]
            original_error=row[spec["error"]]

            if (
                raw is None
                or actual is None
                or original_error is None
            ):
                continue

            model=calculate_correction(
                history,
                timestamp,
                metric,
            )

            if model is None:
                continue

            correction=model["correction"]

            corrected=physically_bound(
                metric,
                float(raw)+correction,
            )

            raw_error=float(actual)-float(raw)
            corrected_error=float(actual)-corrected

            db.execute(
                """
                INSERT OR REPLACE INTO shadow_predictions
                (
                    target_at,
                    horizon_minutes,
                    metric,
                    raw_forecast,
                    learned_correction,
                    corrected_forecast,
                    actual,
                    raw_error,
                    corrected_error,
                    training_samples,
                    local_training_samples,
                    method
                )
                VALUES (
                    ?,?,?,?,?,?,?,?,?,?,?,?
                )
                """,
                (
                    timestamp,
                    HORIZON,
                    metric,
                    float(raw),
                    correction,
                    corrected,
                    float(actual),
                    raw_error,
                    corrected_error,
                    model["training_samples"],
                    model["local_training_samples"],
                    model["method"],
                )
            )

            scored+=1

        # Only AFTER predictions were produced do actual errors
        # enter the model's training history.
        for metric,spec in METRICS.items():
            error=row[spec["error"]]

            if error is None:
                continue

            history[metric].append(
                {
                    "target_at":timestamp,
                    "hour":hour,
                    "error":float(error),
                }
            )

    db.commit()

    return scored


def metric_report(db,metric):
    rows=db.execute(
        """
        SELECT
            raw_error,
            corrected_error,
            learned_correction,
            training_samples,
            local_training_samples
        FROM shadow_predictions
        WHERE horizon_minutes=?
          AND metric=?
        ORDER BY target_at
        """,
        (
            HORIZON,
            metric,
        )
    ).fetchall()

    if not rows:
        return {
            "samples":0,
            "raw_mae":None,
            "shadow_mae":None,
            "improvement_percent":None,
            "raw_rmse":None,
            "shadow_rmse":None,
            "latest_correction":None,
        }

    raw=[r[0] for r in rows]
    shadow=[r[1] for r in rows]

    raw_mae=mae(raw)
    shadow_mae=mae(shadow)

    improvement=(
        100.0*(raw_mae-shadow_mae)/raw_mae
        if raw_mae and raw_mae > 0
        else 0.0
    )

    return {
        "samples":len(rows),
        "raw_mae":round(raw_mae,6),
        "shadow_mae":round(shadow_mae,6),
        "improvement_percent":round(improvement,2),
        "raw_rmse":round(rmse(raw),6),
        "shadow_rmse":round(rmse(shadow),6),
        "latest_correction":round(rows[-1][2],6),
        "latest_training_samples":rows[-1][3],
        "latest_local_training_samples":rows[-1][4],
    }


def determine_state(metrics,coverage_hours):
    scored=[
        value
        for value in metrics.values()
        if value["samples"] > 0
    ]

    if not scored:
        return "COLLECTING_BASELINE"

    # This is intentionally NOT an activation rule.
    # It is informational only.
    if coverage_hours < 48:
        return "SHADOW_EARLY"

    if coverage_hours < 168:
        return "SHADOW_LEARNING"

    return "SHADOW_EVALUATION"


def make_report(db,source_rows,scored):
    times=db.execute(
        """
        SELECT
            MIN(target_at),
            MAX(target_at)
        FROM forecast_errors
        WHERE horizon_minutes=?
        """,
        (HORIZON,)
    ).fetchone()

    if (
        times
        and times[0] is not None
        and times[1] is not None
    ):
        coverage_hours=(
            times[1]-times[0]
        )/3600
    else:
        coverage_hours=0

    metrics={
        metric:metric_report(db,metric)
        for metric in METRICS
    }

    state=determine_state(
        metrics,
        coverage_hours,
    )

    return {
        "mode":"shadow_only",
        "control_enabled":False,
        "predbat_write_enabled":False,
        "planner_influence_enabled":False,
        "horizon_minutes":HORIZON,
        "source_error_rows":source_rows,
        "shadow_predictions":scored,
        "coverage_hours":round(
            coverage_hours,
            2
        ),
        "status":state,
        "model":"walk_forward_hour_bias_v1",
        "metrics":metrics,
        "safety":{
            "walk_forward_only":True,
            "future_information_used":False,
            "bounded_correction":True,
            "nonnegative_output":True,
            "predbat_control":False,
            "battery_control":False,
            "planner_control":False,
        },
        "generated_at":datetime.now(
            LOCAL_TZ
        ).isoformat(timespec="seconds"),
    }


def atomic_json(path,data):
    temp=path.with_suffix(
        path.suffix+".tmp"
    )

    temp.write_text(
        json.dumps(
            data,
            indent=2,
            sort_keys=True,
        )+"\n"
    )

    temp.replace(path)


def ha_request(path,payload=None):
    base=os.environ.get(
        "HA_URL",
        "http://127.0.0.1:8123"
    ).rstrip("/")

    token=os.environ.get("HA_TOKEN")

    if not token:
        raise RuntimeError(
            "HA_TOKEN not available"
        )

    body=None

    headers={
        "Authorization":f"Bearer {token}",
        "Content-Type":"application/json",
    }

    if payload is not None:
        body=json.dumps(payload).encode()

    req=urllib.request.Request(
        base+path,
        data=body,
        headers=headers,
        method="POST" if payload is not None else "GET",
    )

    with urllib.request.urlopen(
        req,
        timeout=10
    ) as response:
        raw=response.read()

    if not raw:
        return None

    return json.loads(raw)


def publish_sensor(entity_id,state,attributes):
    ha_request(
        f"/api/states/{entity_id}",
        {
            "state":str(state),
            "attributes":attributes,
        }
    )


def publish_home_assistant(report):
    publish_sensor(
        "sensor.lifeos_shadow_learning_status",
        report["status"],
        {
            "friendly_name":
                "LifeOS Energy Shadow Learning Status",
            "mode":"shadow_only",
            "control_enabled":False,
            "forecast_horizon_minutes":
                report["horizon_minutes"],
            "source_error_rows":
                report["source_error_rows"],
            "coverage_hours":
                report["coverage_hours"],
            "model":
                report["model"],
            "generated_at":
                report["generated_at"],
        }
    )

    names={
        "solar_kw":"Solar",
        "house_kw":"House",
        "battery_kwh":"Battery",
        "export_kw":"Export",
    }

    entity_ids={
        "solar_kw":
            "sensor.lifeos_shadow_solar_improvement",
        "house_kw":
            "sensor.lifeos_shadow_house_improvement",
        "battery_kwh":
            "sensor.lifeos_shadow_battery_improvement",
        "export_kw":
            "sensor.lifeos_shadow_export_improvement",
    }

    for metric,name in names.items():
        result=report["metrics"][metric]

        improvement=(
            result["improvement_percent"]
            if result["improvement_percent"] is not None
            else 0
        )

        publish_sensor(
            entity_ids[metric],
            improvement,
            {
                "friendly_name":
                    f"LifeOS {name} Shadow Improvement",
                "unit_of_measurement":"%",
                "state_class":"measurement",
                "samples":
                    result["samples"],
                "raw_mae":
                    result["raw_mae"],
                "shadow_mae":
                    result["shadow_mae"],
                "raw_rmse":
                    result["raw_rmse"],
                "shadow_rmse":
                    result["shadow_rmse"],
                "latest_correction":
                    result["latest_correction"],
                "mode":"shadow_only",
            }
        )


def save_run(db,report):
    run_at=int(
        datetime.now().timestamp()
    )

    db.execute(
        """
        INSERT OR REPLACE INTO shadow_learning_runs
        (
            run_at,
            source_error_rows,
            scored_predictions,
            mode,
            report_json
        )
        VALUES (?,?,?,?,?)
        """,
        (
            run_at,
            report["source_error_rows"],
            report["shadow_predictions"],
            "shadow_only",
            json.dumps(report),
        )
    )

    db.commit()


def main():
    log("Shadow learner starting")

    db=sqlite3.connect(
        DB_PATH,
        timeout=30
    )

    db.execute(
        "PRAGMA busy_timeout=30000"
    )

    create_schema(db)

    rows=fetch_error_rows(db)

    log(
        f"Loaded {len(rows)} genuine "
        f"{HORIZON}-minute error records"
    )

    scored=rebuild_shadow_predictions(
        db,
        rows,
    )

    report=make_report(
        db,
        len(rows),
        scored,
    )

    atomic_json(
        REPORT_PATH,
        report,
    )

    save_run(
        db,
        report,
    )

    db.close()

    log(
        f"Generated {scored} walk-forward "
        f"shadow predictions"
    )

    for metric,result in report["metrics"].items():
        if result["samples"]:
            log(
                f"{metric}: "
                f"N={result['samples']} "
                f"raw MAE={result['raw_mae']:.4f} "
                f"shadow MAE={result['shadow_mae']:.4f} "
                f"improvement="
                f"{result['improvement_percent']:+.2f}%"
            )

    try:
        publish_home_assistant(
            report
        )
        log(
            "Published informational "
            "Home Assistant sensors"
        )
    except Exception as exc:
        # Do not destroy a valid learning run merely because
        # the HA frontend is temporarily unavailable.
        log(
            "WARNING: Home Assistant sensor "
            f"publishing failed: {exc}"
        )

    log(
        "Mode remains SHADOW ONLY; "
        "no control outputs exist"
    )

    log(
        "Shadow learner completed successfully"
    )


if __name__ == "__main__":
    main()
