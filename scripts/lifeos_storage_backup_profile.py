#!/usr/bin/env python3
"""Read-only local backup-group age and size profile.

Input is the local TSV inventory. No filesystem traversal, deletion or raw paths
in output. Historical age is NEVER interpreted as safe-to-delete evidence.
"""
import argparse
import collections
import datetime as dt
import json
import re

from scripts.lifeos_storage_retention_inventory import ROOT, MAX_INPUT_BYTES, MAX_LINE_BYTES, MAX_LINES, inventory_rows, open_inventory


# These names are emitted by the corresponding scripts in the repository.
# A matching name only suggests which producer to verify on the Pi.
PRODUCER_PATTERN = re.compile(
    r"(pinned-compose|ha-lifeos-dashboard|ha-tower-control|ha-control-bridge|"
    r"ha-dashboard-simplify)-[0-9]{8}-[0-9]{6}"
)


def profile(stream, today, max_lines=MAX_LINES):
    groups = {}
    invalid = 0
    input_bytes = 0
    count = 0
    for raw in inventory_rows(stream):
        count += 1
        input_bytes += len(raw)
        if count > max_lines or input_bytes > MAX_INPUT_BYTES:
            raise ValueError("inventory_limit_exceeded")
        if len(raw) > MAX_LINE_BYTES:
            invalid += 1
            continue
        try:
            size_s, date_s, path = raw.decode("utf-8").rstrip("\n").split("\t", 2)
            size, modified = int(size_s), dt.date.fromisoformat(date_s)
            if size < 0 or modified > today or not path.startswith(ROOT + "backups/"):
                if path.startswith(ROOT + "backups/"):
                    raise ValueError()
                continue
            relative = path[len(ROOT + "backups/"):]
            parts = relative.split("/")
            if len(parts) < 2 or not parts[0] or any(part in ("", ".", "..") for part in parts):
                raise ValueError()
            key = parts[0]
            if len(key.encode("utf-8")) > 255:
                raise ValueError()
        except (ValueError, TypeError):
            invalid += 1
            continue
        if key not in groups and len(groups) >= 100_000:
            raise ValueError("backup_group_limit_exceeded")
        group = groups.setdefault(key, {"files": 0, "bytes": 0, "latest_modified": modified})
        group["files"] += 1
        group["bytes"] += size
        if modified > group["latest_modified"]:
            group["latest_modified"] = modified
    summary = collections.defaultdict(lambda: {"groups": 0, "files": 0, "bytes": 0})
    families = collections.defaultdict(lambda: {"groups": 0, "files": 0, "bytes": 0})
    for name, record in groups.items():
        age = (today - record["latest_modified"]).days
        age_band = "0-30d" if age <= 30 else "31-90d" if age <= 90 else "91-180d" if age <= 180 else "181d+"
        bucket = summary[age_band]
        bucket["groups"] += 1
        bucket["files"] += record["files"]
        bucket["bytes"] += record["bytes"]
        match = PRODUCER_PATTERN.fullmatch(name)
        family = families[match[1] if match else "unknown"]
        family["groups"] += 1
        family["files"] += record["files"]
        family["bytes"] += record["bytes"]
    return {
        "schema_version": 1, "mode": "read_only_dry_run",
        "backup_groups": len(groups), "invalid_rows": invalid,
        "age_bands_by_latest_group_file": dict(sorted(summary.items())),
        "producer_name_hints": dict(sorted(families.items())),
        "deletion_candidates": 0, "eligible_for_deletion_bytes": 0,
        "retention_verdict": "UNDETERMINED_REQUIRES_TERMINAL_AND_HOLD_PROOF",
        "note": "Dates are file modification dates, not verified backup creation or recovery status."
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("inventory", help="Local inventory TSV; do not publish")
    parser.add_argument("--today", type=dt.date.fromisoformat, default=dt.datetime.now(dt.timezone.utc).date())
    args = parser.parse_args()
    try:
        with open_inventory(args.inventory) as stream:
            report = profile(stream, args.today)
        print(json.dumps(report, sort_keys=True))
    except (OSError, ValueError):
        print(json.dumps({"status": "inventory_unavailable_or_out_of_bounds"}))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
