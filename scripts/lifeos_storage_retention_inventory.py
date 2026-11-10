#!/usr/bin/env python3
"""Read-only, bounded analysis of a LOCAL LifeOS storage inventory.

Consumes the TSV created by find(1): bytes, YYYY-MM-DD, absolute path.
Never opens any referenced file, traverses the filesystem, or deletes anything.
Output contains only predefined aggregate categories; no filenames or paths.
"""
import argparse
import collections
import datetime as dt
import json
from pathlib import Path

ROOT = "/mnt/docker-data/automation/"
CATEGORIES = ("backups", "repair_lifecycle", "queues", "logs", "lifeos_state", "engineer_packets")
MAX_LINES = 3_000_000
MAX_INPUT_BYTES = 600 * 1024 * 1024
MAX_LINE_BYTES = 4096


def classify(relative):
    parts = relative.split("/")
    top = parts[0]
    if top not in CATEGORIES:
        return "other"
    if top == "queues":
        child = parts[1] if len(parts) > 1 else ""
        return "queues/" + child if child in ("closed_loop", "auditor", "engineer", "watchman") else "queues/other"
    if top == "logs":
        return "logs/cron" if len(parts) > 1 and parts[1] == "cron" else "logs/other"
    if top == "repair_lifecycle":
        return "repair_lifecycle/snapshots" if len(parts) > 1 and parts[1] == "snapshots" else "repair_lifecycle/other"
    return top


def summarise(stream, today, max_lines=MAX_LINES):
    groups = collections.defaultdict(lambda: {"files": 0, "bytes": 0, "older_than_90d_files": 0, "older_than_90d_bytes": 0})
    errors = 0
    read_bytes = 0
    lines = 0
    for raw in stream:
        lines += 1
        read_bytes += len(raw)
        if lines > max_lines or read_bytes > MAX_INPUT_BYTES:
            raise ValueError("inventory_limit_exceeded")
        if len(raw) > MAX_LINE_BYTES:
            errors += 1
            continue
        try:
            size_str, date_str, path = raw.decode("utf-8", "replace").rstrip("\n").split("\t", 2)
            size = int(size_str)
            date = dt.date.fromisoformat(date_str)
            if size < 0 or not path.startswith(ROOT) or ".." in Path(path).parts or date > today:
                raise ValueError()
            category = classify(path[len(ROOT):])
        except (ValueError, TypeError):
            errors += 1
            continue
        record = groups[category]
        record["files"] += 1
        record["bytes"] += size
        if (today - date).days > 90:
            record["older_than_90d_files"] += 1
            record["older_than_90d_bytes"] += size
    return {"schema_version": 1, "mode": "read_only_dry_run", "lines": lines, "invalid_rows": errors,
            "categories": dict(sorted(groups.items())),
            "eligible_for_deletion_bytes": 0,
            "retention_verdict": "UNDETERMINED_REQUIRES_TERMINAL_AND_HOLD_PROOF"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("inventory", help="Local inventory TSV; never upload to GitHub")
    parser.add_argument("--today", type=dt.date.fromisoformat, default=dt.datetime.now(dt.timezone.utc).date())
    args = parser.parse_args()
    with open(args.inventory, "rb") as f:
        report = summarise(f, args.today)
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
