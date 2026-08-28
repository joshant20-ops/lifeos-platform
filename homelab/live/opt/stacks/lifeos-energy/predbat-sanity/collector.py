#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/London")

BASE = Path("/opt/stacks/lifeos-energy/predbat-sanity")
DATA = BASE / "data"
DAILY_DIR = DATA / "daily"

EXPORT = Path("/opt/stacks/lifeos-energy/predbat-sanity-export")
EXPORT_LATEST = EXPORT / "latest.json"
EXPORT_DAILY = EXPORT / "daily.json"

DB = Path("/opt/stacks/homeassistant/config/home-assistant_v2.db")
APPS = Path("/mnt/docker-data/predbat/config/apps.yaml")

ENTITY_IDS = [
    "predbat.status",
    "predbat.rates",
    "predbat.rates_export",
    "predbat.best_import_energy",
    "predbat.best_import_energy_battery",
    "predbat.best_import_energy_house",
    "predbat.best_export_energy",
    "predbat.best_pv_energy",
    "predbat.best_load_energy",
    "predbat.best_soc_min_kwh",
    "predbat.best_charge_start",
    "predbat.best_charge_end",
    "predbat.best_charge_limit",
    "predbat.best_charge_limit_kw",
    "predbat.best_export_start",
    "predbat.best_export_end",
    "predbat.best_export_limit",
    "predbat.best_export_limit_kw",
    "predbat.battery_cycle_best",
    "predbat.soc_kw_best",
    "predbat.best_battery_hours_left",
    "sensor.predbat_enphase_5731818_soc_percent",
    "sensor.predbat_enphase_5731818_soc_kw",
    "sensor.predbat_enphase_5731818_battery_reserve",
    "sensor.predbat_enphase_5731818_battery_reserve_min",
    "sensor.predbat_enphase_5731818_battery_power",
    "sensor.predbat_enphase_5731818_grid_power",
    "sensor.predbat_enphase_5731818_load_power",
    "sensor.predbat_enphase_5731818_pv_power",
]

FORECAST_IDS = [
    "predbat.soc_kw_best",
    "predbat.grid_power_best",
    "predbat.battery_power_best",
    "predbat.pv_power_best",
    "predbat.rates",
    "predbat.rates_export",
]

def now_local():
    return datetime.now(TZ)

def atomic_json(path: Path, obj, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)

    text = json.dumps(
        obj,
        indent=2,
        sort_keys=True,
        separators=(",", ": "),
    ) + "\n"

    fd, tmpname = tempfile.mkstemp(
        prefix=path.name + ".",
        dir=str(path.parent),
    )

    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())

        os.chmod(tmpname, mode)
        os.replace(tmpname, path)
        os.chmod(path, mode)

    finally:
        try:
            os.unlink(tmpname)
        except FileNotFoundError:
            pass

def scalar(v):
    if v in (None, "", "unknown", "unavailable"):
        return v

    try:
        f = float(v)
        return int(f) if f.is_integer() else round(f, 4)
    except Exception:
        return str(v)

def connect_db():
    con = sqlite3.connect(
        f"file:{DB}?mode=ro",
        uri=True,
        timeout=5,
    )
    con.row_factory = sqlite3.Row
    return con

def latest_states(con):
    marks = ",".join("?" for _ in ENTITY_IDS)

    q = f"""
    SELECT
        sm.entity_id,
        s.state,
        s.last_updated_ts
    FROM states s
    JOIN states_meta sm
      ON sm.metadata_id=s.metadata_id
    JOIN (
        SELECT metadata_id, MAX(state_id) AS max_state_id
        FROM states
        GROUP BY metadata_id
    ) x
      ON x.metadata_id=s.metadata_id
     AND x.max_state_id=s.state_id
    WHERE sm.entity_id IN ({marks})
    """

    out = {}

    for row in con.execute(q, ENTITY_IDS):
        ts = row["last_updated_ts"]

        updated = None
        if ts:
            updated = (
                datetime.fromtimestamp(ts, tz=timezone.utc)
                .astimezone(TZ)
                .isoformat()
            )

        out[row["entity_id"]] = {
            "state": scalar(row["state"]),
            "last_updated": updated,
        }

    return out

def attrs(con, entity_id):
    row = con.execute(
        """
        SELECT sa.shared_attrs
        FROM states s
        JOIN states_meta sm
          ON sm.metadata_id=s.metadata_id
        LEFT JOIN state_attributes sa
          ON sa.attributes_id=s.attributes_id
        WHERE sm.entity_id=?
        ORDER BY s.state_id DESC
        LIMIT 1
        """,
        (entity_id,),
    ).fetchone()

    if not row or not row["shared_attrs"]:
        return {}

    try:
        return json.loads(row["shared_attrs"])
    except Exception:
        return {}

def compact_results(a):
    r = a.get("results")

    if not isinstance(r, dict):
        return []

    out = []

    for t, v in r.items():
        try:
            out.append({
                "time": str(t),
                "value": round(float(v), 4),
            })
        except Exception:
            pass

    out.sort(key=lambda x: x["time"])
    return out[-600:]

def apps_text():
    try:
        return APPS.read_text(errors="replace")
    except PermissionError:
        return subprocess.check_output(
            ["cat", str(APPS)],
            text=True,
            timeout=5,
        )

def config_value(name):
    text = apps_text()

    rx = re.compile(
        rf"^[ \t]*{re.escape(name)}[ \t]*:"
        rf"[ \t]*[\"']?([^\"'#\n]+)",
        re.MULTILINE,
    )

    m = rx.search(text)
    return m.group(1).strip() if m else None

def tariff_horizon(url):
    if not url:
        return {"status": "config_missing"}

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "LifeOS-Predbat-Sanity/1.0"},
        )

        with urllib.request.urlopen(req, timeout=10) as response:
            payload = json.load(response)

        rows = payload.get("results", [])
        if not rows:
            return {"status": "no_results"}

        latest = max(rows, key=lambda r: r.get("valid_from", ""))

        vf = datetime.fromisoformat(
            latest["valid_from"].replace("Z", "+00:00")
        ).astimezone(TZ)

        vt = datetime.fromisoformat(
            latest["valid_to"].replace("Z", "+00:00")
        ).astimezone(TZ)

        return {
            "status": "live_api_ok",
            "published_slot_count": len(rows),
            "latest_local_from": vf.isoformat(),
            "latest_local_to": vt.isoformat(),
            "latest_rate_p_per_kwh": round(
                float(latest["value_inc_vat"]), 4
            ),
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e)[:200],
        }

def parse_time(t):
    try:
        return datetime.fromisoformat(
            t.replace("Z", "+00:00")
        ).astimezone(TZ)
    except Exception:
        return None

def forecast_summary(forecast, tariff):
    soc = forecast.get("predbat.soc_kw_best", [])
    grid = forecast.get("predbat.grid_power_best", [])

    out = {
        "soc_points": len(soc),
        "grid_points": len(grid),
    }

    if soc:
        mn = min(soc, key=lambda x: x["value"])
        mx = max(soc, key=lambda x: x["value"])

        out.update({
            "soc_min_kwh": mn["value"],
            "soc_min_time": mn["time"],
            "soc_max_kwh": mx["value"],
            "soc_max_time": mx["time"],
        })

    horizon_text = tariff["import"].get("latest_local_to")
    horizon = (
        datetime.fromisoformat(horizon_text)
        if horizon_text
        else None
    )

    provisional = 0

    if horizon:
        for point in grid:
            pt = parse_time(point["time"])
            if pt and pt > horizon and point["value"] > 2.0:
                provisional += 1

    out["high_import_points_beyond_live_tariff_horizon"] = provisional

    return out

def anomaly_flags(snapshot):
    flags = []

    fs = snapshot["forecast_summary"]

    if fs.get("high_import_points_beyond_live_tariff_horizon", 0) > 0:
        flags.append("high_grid_charge_planned_on_provisional_tariff")

    if snapshot["tariff"]["import"].get("status") != "live_api_ok":
        flags.append("import_tariff_source_unhealthy")

    if snapshot["tariff"]["export"].get("status") != "live_api_ok":
        flags.append("export_tariff_source_unhealthy")

    return flags

def compact_record(snapshot):
    wanted = [
        "predbat.status",
        "predbat.rates",
        "predbat.rates_export",
        "predbat.best_import_energy",
        "predbat.best_import_energy_battery",
        "predbat.best_export_energy",
        "predbat.best_pv_energy",
        "predbat.best_load_energy",
        "predbat.best_soc_min_kwh",
        "predbat.best_charge_start",
        "predbat.best_charge_end",
        "predbat.best_charge_limit",
        "predbat.best_export_start",
        "predbat.best_export_end",
        "predbat.battery_cycle_best",
        "sensor.predbat_enphase_5731818_soc_percent",
        "sensor.predbat_enphase_5731818_battery_reserve",
        "sensor.predbat_enphase_5731818_grid_power",
        "sensor.predbat_enphase_5731818_battery_power",
        "sensor.predbat_enphase_5731818_load_power",
        "sensor.predbat_enphase_5731818_pv_power",
    ]

    return {
        "generated_at": snapshot["generated_at"],
        "states": {
            e: snapshot["entities"][e]["state"]
            for e in wanted
            if e in snapshot["entities"]
        },
        "tariff_horizon": {
            "import": snapshot["tariff"]["import"].get("latest_local_to"),
            "export": snapshot["tariff"]["export"].get("latest_local_to"),
        },
        "forecast_summary": snapshot["forecast_summary"],
        "anomaly_flags": snapshot["anomaly_flags"],
    }

def main():
    DATA.mkdir(parents=True, exist_ok=True)
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    EXPORT.mkdir(parents=True, exist_ok=True)

    with connect_db() as con:
        states = latest_states(con)

        forecast = {
            e: compact_results(attrs(con, e))
            for e in FORECAST_IDS
        }

    tariff = {
        "import": tariff_horizon(config_value("rates_import_octopus_url")),
        "export": tariff_horizon(config_value("rates_export_octopus_url")),
    }

    snapshot = {
        "schema": "lifeos.predbat_sanity.v1",
        "generated_at": now_local().isoformat(),
        "entities_expected": len(ENTITY_IDS),
        "entities_present": len(states),
        "entities_missing": [
            e for e in ENTITY_IDS if e not in states
        ],
        "entities": states,
        "tariff": tariff,
        "forecast": forecast,
    }

    snapshot["forecast_summary"] = forecast_summary(
        forecast,
        tariff,
    )

    snapshot["anomaly_flags"] = anomaly_flags(snapshot)

    local_latest = DATA / "latest.json"
    atomic_json(local_latest, snapshot, 0o600)

    dayfile = DAILY_DIR / f"{now_local().date().isoformat()}.json"

    try:
        history = json.loads(dayfile.read_text())
        if not isinstance(history, list):
            history = []
    except Exception:
        history = []

    history.append(compact_record(snapshot))
    history = history[-60:]

    atomic_json(dayfile, history, 0o600)

    # Sanitised publication copies:
    # root-owned but world-readable, no credentials/secrets.
    atomic_json(EXPORT_LATEST, snapshot, 0o644)
    atomic_json(EXPORT_DAILY, history, 0o644)

    print("COLLECTOR_STATUS=PASS")
    print(f"GENERATED_AT={snapshot['generated_at']}")
    print(f"ENTITY_PRESENT_COUNT={snapshot['entities_present']}")
    print(f"ENTITY_MISSING_COUNT={len(snapshot['entities_missing'])}")
    print("IMPORT_TARIFF_STATUS=" + tariff["import"].get("status", "unknown"))
    print("EXPORT_TARIFF_STATUS=" + tariff["export"].get("status", "unknown"))
    print(
        "ANOMALY_FLAGS="
        + (
            ",".join(snapshot["anomaly_flags"])
            if snapshot["anomaly_flags"]
            else "none"
        )
    )

if __name__ == "__main__":
    main()
