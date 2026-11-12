#!/usr/bin/env python3
"""Read-only local backup-group age and size profile.

Input is the local TSV inventory. No filesystem traversal, deletion or raw paths
in output. Historical age is NEVER interpreted as safe-to-delete evidence.
"""
import argparse
import collections
import datetime as dt
import json
import os
import re
import stat

from scripts.lifeos_storage_retention_inventory import ROOT, MAX_INPUT_BYTES, MAX_LINES, inventory_rows, open_inventory


# These names are emitted by the corresponding scripts in the repository.
# A matching name only suggests which producer to verify on the Pi.
PRODUCER_PATTERN = re.compile(
    r"(pinned-compose|ha-lifeos-dashboard|ha-tower-control|ha-control-bridge|"
    r"ha-dashboard-simplify|autoheal-retire|engineer-ui-adopt|jobs-exporter|"
    r"paste-artifacts|semaphore-reconcile|dispatch-timer-retire|"
    r"engineer-dispatcher-retire|engineer-worker-retire|job-routing|"
    r"stage1-2)-[0-9]{8}-[0-9]{6}"
)

# Keep the private part of a dated group name in memory only. A repeated
# pattern identifies a group of similarly named records, not their owner.
DATED_SUFFIX = re.compile(r"(.+?)[-_.]([0-9]{8})[-_T]([0-9]{6})Z?")


FUNCTIONS = (
    "configuration_rollback",
    "automation_code",
    "database_or_state",
    "logs_or_audit_evidence",
    "archive_contents_uninspected",
    "unknown",
)


def artifact_function(parts):
    """Classify the apparent purpose from fixed metadata hints, without opening files."""
    name = parts[-1].lower()
    for suffix in (".before", ".backup", ".bak", ".old"):
        if name.endswith(suffix):
            name = name[:-len(suffix)]
            break
    if name.endswith((".tar", ".tgz", ".tar.gz", ".zip", ".zst", ".gz")):
        return 4
    if ".storage" in parts[:-1] or name.endswith((".db", ".sqlite", ".sqlite3", ".sql")):
        return 2
    if name.endswith((".log", ".jsonl")) or name in {"run.log", "manifest.json", "evidence.json"}:
        return 3
    if name.endswith((".sh", ".py", ".js", ".ps1")):
        return 1
    if name.endswith((".yaml", ".yml", ".conf", ".service", ".timer", ".ini", ".toml", ".cfg")):
        return 0
    return 5


def functional_totals(groups):
    totals = collections.defaultdict(lambda: {"groups": 0, "files": 0, "bytes": 0})
    components = collections.Counter()
    for record in groups:
        mask = record["function_mask"]
        roles = [label for bit, label in enumerate(FUNCTIONS) if mask & (1 << bit)]
        label = roles[0] if len(roles) == 1 else "mixed"
        bucket = totals[label]
        bucket["groups"] += 1
        bucket["files"] += record["files"]
        bucket["bytes"] += record["bytes"]
        components.update(roles)
    return {"groups_by_apparent_function": dict(sorted(totals.items())),
            "groups_containing_each_component": dict(sorted(components.items()))}


def profile(stream, today, max_lines=MAX_LINES, source_roots=(), local_selection=None):
    groups = {}
    invalid = 0
    flat = {"files": 0, "bytes": 0}
    flat_functions = collections.defaultdict(lambda: {"files": 0, "bytes": 0})
    input_bytes = 0
    count = 0
    for raw in inventory_rows(stream):
        count += 1
        input_bytes += len(raw)
        if count > max_lines or input_bytes > MAX_INPUT_BYTES:
            raise ValueError("inventory_limit_exceeded")
        try:
            size_s, date_s, path = raw.decode("utf-8").rstrip("\n").split("\t", 2)
            size, modified = int(size_s), dt.date.fromisoformat(date_s)
            if size < 0 or modified > today or not path.startswith(ROOT + "backups/"):
                if path.startswith(ROOT + "backups/"):
                    raise ValueError()
                continue
            relative = path[len(ROOT + "backups/"):]
            parts = relative.split("/")
            if any(part in ("", ".", "..") for part in parts):
                raise ValueError()
            key = parts[0]
            if len(key.encode("utf-8")) > 255:
                raise ValueError()
        except (ValueError, TypeError):
            invalid += 1
            continue
        role = artifact_function(parts[1:] or parts)
        if len(parts) == 1:
            flat["files"] += 1
            flat["bytes"] += size
            bucket = flat_functions[FUNCTIONS[role]]
            bucket["files"] += 1
            bucket["bytes"] += size
            continue
        if key not in groups and len(groups) >= 100_000:
            raise ValueError("backup_group_limit_exceeded")
        group = groups.setdefault(key, {"files": 0, "bytes": 0, "latest_modified": modified, "function_mask": 0})
        group["function_mask"] |= 1 << role
        group["files"] += 1
        group["bytes"] += size
        if modified > group["latest_modified"]:
            group["latest_modified"] = modified
    summary = collections.defaultdict(lambda: {"groups": 0, "files": 0, "bytes": 0})
    families = collections.defaultdict(lambda: {"groups": 0, "files": 0, "bytes": 0})
    dated_unknown = collections.defaultdict(lambda: {"groups": 0, "files": 0, "bytes": 0})
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
        dated = DATED_SUFFIX.fullmatch(name) if match is None else None
        if dated:
            cohort = dated_unknown[dated[1]]
            cohort["groups"] += 1
            cohort["files"] += record["files"]
            cohort["bytes"] += record["bytes"]
    repeated = sorted(
        (name for name, item in dated_unknown.items() if item["groups"] > 1),
        key=lambda name: (
            -dated_unknown[name]["bytes"], -dated_unknown[name]["groups"],
            -dated_unknown[name]["files"], name,
        ),
    )
    largest = repeated[:2]
    by_rank = {name: [] for name in largest}
    for name, record in groups.items():
        match = DATED_SUFFIX.fullmatch(name)
        if match and match[1] in by_rank:
            by_rank[match[1]].append(record)
    paired = compare_dates(groups, largest)
    if local_selection is not None:
        local_selection(groups, largest)
    result = {
        "schema_version": 1, "mode": "read_only_dry_run",
        "backup_groups": len(groups), "invalid_rows": invalid,
        "age_bands_by_latest_group_file": dict(sorted(summary.items())),
        "ungrouped_backup_files": flat,
        "ungrouped_files_by_apparent_function": dict(sorted(flat_functions.items())),
        "backup_functions": functional_totals(groups.values()),
        "largest_two_patterns_by_apparent_function": [
            functional_totals(by_rank[name]) for name in largest
        ],
        "repeated_unknown_dated_patterns": len(repeated),
        "largest_unknown_dated_patterns": [dated_unknown[name] for name in repeated[:8]],
        "largest_two_timestamp_overlap": paired,
        "producer_name_hints": dict(sorted(families.items())),
        "deletion_candidates": 0, "eligible_for_deletion_bytes": 0,
        "retention_verdict": "UNDETERMINED_REQUIRES_TERMINAL_AND_HOLD_PROOF",
        "note": "Dates are file modification dates, not verified backup creation or recovery status."
    }

    if source_roots:
        result["installed_producer_source_hints"] = source_hints(repeated[:2], source_roots)
    return result


def source_hints(names, roots):
    needles = [re.compile(rb"(?<![a-zA-Z0-9_])" + re.escape(name.encode()) + rb"[-_.]")
               for name in names]
    matches = [0] * len(names)
    shared = scanned = skipped = 0
    remaining = 12 * 1024 * 1024
    for root in roots:
        try:
            with os.scandir(root) as entries:
                for index, entry in enumerate(entries):
                    if index >= 512:
                        skipped += 1
                        break
                    if not entry.name.endswith((".py", ".sh")):
                        continue
                    try:
                        if not entry.is_file(follow_symlinks=False):
                            skipped += 1
                            continue
                        fd = os.open(entry.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                        with os.fdopen(fd, "rb") as stream:
                            info = os.fstat(stream.fileno())
                            if not stat.S_ISREG(info.st_mode) or info.st_size > 262144:
                                skipped += 1
                                continue
                            if remaining <= 0:
                                skipped += 1
                                break
                            data = stream.read(min(remaining, 262145))
                            remaining -= len(data)
                            if len(data) < info.st_size:
                                skipped += 1
                                continue
                    except OSError:
                        skipped += 1
                        continue
                    if len(data) > 262144:
                        skipped += 1
                        continue
                    scanned += 1
                    found = [bool(needle.search(data)) for needle in needles]
                    for rank, hit in enumerate(found):
                        matches[rank] += hit
                    if len(found) == 2 and all(found):
                        shared += 1
        except OSError:
            skipped += 1
    return {"sources_read": scanned, "skipped_or_limited": skipped,
            "sources_matching_by_rank": matches, "sources_matching_both": shared}


def compare_dates(groups, names):
    if len(names) < 2:
        return None
    timestamps = {name: set() for name in names}
    for group in groups:
        match = DATED_SUFFIX.fullmatch(group)
        if match and match[1] in timestamps:
            timestamps[match[1]].add(match[2] + match[3])
    left, right = (timestamps[name] for name in names)
    return {
        "distinct_timestamps_by_rank": [len(left), len(right)],
        "shared_timestamps": len(left & right),
    }


def storage_blocks(path):
    fs = os.statvfs(path)
    return {
        "capacity_bytes": fs.f_blocks * fs.f_frsize,
        "used_bytes": (fs.f_blocks - fs.f_bfree) * fs.f_frsize,
        "reserved_free_bytes": (fs.f_bfree - fs.f_bavail) * fs.f_frsize,
        "available_bytes": fs.f_bavail * fs.f_frsize,
        "available_inodes": fs.f_favail,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("inventory", help="Local inventory TSV; do not publish")
    parser.add_argument("--today", type=dt.date.fromisoformat, default=dt.datetime.now(dt.timezone.utc).date())
    parser.add_argument("--storage-blocks", action="store_true",
                        help="Include aggregate block counts for the Docker data filesystem")
    parser.add_argument("--installed-source-hints", action="store_true",
                        help="Count matching literals in fixed local producer script directories")
    args = parser.parse_args()
    try:
        with open_inventory(args.inventory) as stream:
            roots = ("/mnt/docker-data/automation", "/mnt/docker-data/automation/scripts")
            report = profile(stream, args.today,
                             source_roots=roots if args.installed_source_hints else ())
        if args.storage_blocks:
            report["docker_data_filesystem"] = storage_blocks("/mnt/docker-data")
        print(json.dumps(report, sort_keys=True))
    except (OSError, ValueError):
        print(json.dumps({"status": "inventory_unavailable_or_out_of_bounds"}))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
