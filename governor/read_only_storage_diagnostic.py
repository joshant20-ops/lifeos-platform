#!/usr/bin/env python3
"""Read-only, bounded Pi5 storage diagnostic. Never prints filenames or file contents.

Execution must be authorised through the existing Pi5 Governor/Watchman boundary.
This script does not install a runner, elevate privileges, or publish raw output.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path("/mnt/docker-data")
CATEGORIES = {
    "mqtt_logs": ROOT / "opt-stacks/mosquitto/log",
    "mqtt_persistence": ROOT / "opt-stacks/mosquitto/data",
    "mqtt_configuration": ROOT / "opt-stacks/mosquitto/config",
}
TIMEOUT_SECONDS = 12


def size_bucket(n: int) -> str:
    """Coarse magnitude only; never reveal exact private-data sizes."""
    if n < 1024 * 1024:
        return "under_1MiB"
    if n < 1024**3:
        return "1MiB_to_1GiB"
    if n < 5 * 1024**3:
        return "1GiB_to_5GiB"
    if n < 10 * 1024**3:
        return "5GiB_to_10GiB"
    return "10GiB_or_more"


def bounded_du(path: Path) -> dict:
    if not path.is_dir() or path.is_symlink():
        return {"status": "unavailable"}
    try:
        result = subprocess.run(
            ["du", "-sx", "--block-size=1", "--", str(path)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            timeout=TIMEOUT_SECONDS, check=False,
        )
    except subprocess.TimeoutExpired:
        return {"status": "timeout"}
    except OSError:
        return {"status": "error"}
    if result.returncode != 0:
        return {"status": "error"}
    try:
        n = int(result.stdout.split(None, 1)[0])
    except (ValueError, IndexError):
        return {"status": "error"}
    return {"status": "ok", "size_bucket": size_bucket(n)}


def mqtt_top_level() -> dict:
    """Only stat immediate files; do not recurse, print names, or read contents."""
    result = {}
    for label in ("log", "data"):
        path = ROOT / "opt-stacks/mosquitto" / label
        try:
            count = 0
            largest = 0
            with os.scandir(path) as entries:
                deadline = time.monotonic() + 2
                for index, entry in enumerate(entries):
                    if index >= 4096 or time.monotonic() > deadline:
                        raise TimeoutError
                    if entry.is_file(follow_symlinks=False):
                        count += 1
                        largest = max(largest, entry.stat(follow_symlinks=False).st_size)
            result[label] = {
                "status": "ok",
                "file_count_bucket": "0" if count == 0 else "1-10" if count <= 10 else "11-100" if count <= 100 else "over_100",
                "largest_file_bucket": size_bucket(largest),
            }
        except TimeoutError:
            result[label] = {"status": "limit"}
        except OSError:
            result[label] = {"status": "unavailable"}
    return result


def filesystem() -> dict:
    stats = os.statvfs(ROOT)
    return {
        "used_bucket": size_bucket((stats.f_blocks - stats.f_bfree) * stats.f_frsize),
        "available_bucket": size_bucket(stats.f_bavail * stats.f_frsize),
        "reserved_or_unavailable_bucket": size_bucket(max(0, stats.f_bfree - stats.f_bavail) * stats.f_frsize),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print sanitised JSON")
    args = parser.parse_args()
    if not ROOT.is_dir():
        print("STORAGE_AUDIT=UNAVAILABLE")
        return 2
    try:
        stats = filesystem()
    except OSError:
        print("STORAGE_AUDIT=FILESYSTEM_UNAVAILABLE")
        return 2
    report = {
        "schema_version": 1,
        "mode": "read_only",
        "filesystem": stats,
        "directories": {name: bounded_du(path) for name, path in CATEGORIES.items()},
        "mqtt_immediate_files": mqtt_top_level(),
        "note": "Directory sizes are coarse; Docker accounting and bind mounts must not be added blindly.",
    }
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print("STORAGE_AUDIT=READ_ONLY")
        for name, row in report["directories"].items():
            print(f"STORAGE_{name.upper()}={row['status']}:{row.get('size_bucket', 'unknown')}")
        for name, row in report["mqtt_immediate_files"].items():
            print(f"MQTT_{name.upper()}_LARGEST={row.get('largest_file_bucket', 'unknown')}")
    return 0 if all(row["status"] == "ok" for section in ("directories", "mqtt_immediate_files")
                    for row in report[section].values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
