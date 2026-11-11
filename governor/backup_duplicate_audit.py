"""Find exact duplicate content in a bounded sample of the two largest families."""
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

from governor.backup_pair_archive_pilot import (
    DATED_SUFFIX, INVENTORY, MAX_FILES, MAX_SOURCE, ROOT, PilotStopped, build_archive,
)
from governor.mqtt_retained_rotation import write_record
from governor.storage_tier0 import enough_space
from scripts.lifeos_storage_backup_profile import profile
from scripts.lifeos_storage_retention_inventory import open_inventory

SCAN_LIMIT = 256 * 1024**2
GROUP_LIMIT = 128
AUDIT = Path("/var/lib/lifeos-storage-audit")


def select_sample(groups, ranks):
    buckets = defaultdict(list)
    for name, record in groups.items():
        match = DATED_SUFFIX.fullmatch(name)
        if (match and match[1] in ranks and 0 < record["bytes"] <= MAX_SOURCE
                and 0 < record["files"] <= MAX_FILES):
            stamp = match[2] + match[3]
            buckets[(ranks.index(match[1]), record["bytes"], record["files"])].append(
                (stamp, name, record)
            )
    # Prioritise large equal-size cohorts while retaining older and newer samples.
    sample = []
    remaining = SCAN_LIMIT
    for key in sorted(buckets, key=lambda key: (-key[1], key[0], key[2])):
        bucket = sorted(buckets[key])
        if len(bucket) < 2 or remaining < 2 * key[1] or len(sample) > GROUP_LIMIT - 2:
            continue
        for stamp, name, record in (bucket[0], bucket[-1]):
            sample.append((key[0], stamp, name, record))
            remaining -= key[1]
    return sample


def compare(records):
    groups = defaultdict(list)
    files = defaultdict(list)
    for rank, stamp, name, entries in records:
        signature = []
        for entry in entries:
            relative = entry["archive_path"].split("/", 1)[1]
            key = (relative, entry["mode"], entry["bytes"], entry["sha256"])
            signature.append(key)
            files[(rank, *key)].append((stamp, name, entry))
        digest = hashlib.sha256(json.dumps(sorted(signature)).encode()).hexdigest()
        groups[(rank, digest)].append((stamp, name, entries))

    candidates = []
    allocated = 0
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort(reverse=True)
        for stamp, name, entries in members[1:]:
            amount = sum(entry["allocated_bytes"] for entry in entries)
            allocated += amount
            candidates.append({"original_group": name, "timestamp": stamp,
                               "identical_group": members[0][1], "files": entries,
                               "allocated_bytes": amount,
                               "dependency_and_hold_status": "unverified"})
    repeated = sum(len(members) - 1 for members in files.values())
    return candidates, allocated, repeated


def run():
    if os.geteuid() != 0 or not enough_space():
        raise PilotStopped("fixed_gateway_or_storage_reserve_unverified")
    space = os.statvfs("/dev/shm")
    if space.f_bavail * space.f_frsize < 128 * 1024**2:
        raise PilotStopped("ram_reserve_unverified")
    selection = []
    today = datetime.now(timezone.utc).date()
    with open_inventory(INVENTORY) as stream:
        profile(stream, today, local_selection=lambda groups, ranks:
                selection.extend(select_sample(groups, ranks)))
    records = []
    skipped = 0
    source_bytes = 0
    for rank, stamp, name, expected in selection:
        if not enough_space():
            raise PilotStopped("critical_storage_reserve")
        try:
            with tempfile.TemporaryFile(dir="/dev/shm") as archive:
                manifest, _, size = build_archive(ROOT, stamp, [(name, expected)], archive)
        except (OSError, PilotStopped, ValueError):
            skipped += 1
            continue
        source_bytes += size
        records.append((rank, stamp, name, manifest["groups"][0]["files"]))

    candidates, allocated, repeated = compare(records)
    AUDIT.mkdir(mode=0o700, exist_ok=True)
    info = AUDIT.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise PilotStopped("audit_directory_unverified")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    write_record(AUDIT / f"duplicate-evidence-{stamp}.json", {
        "scope": "bounded_sample_of_two_largest_patterns",
        "candidates": candidates, "deletion_authorised": False,
    })
    return {"status": "backup_duplicates_measured", "groups_compared": len(records),
            "groups_skipped": skipped, "source_bytes_compared": source_bytes,
            "exact_duplicate_groups": len(candidates), "repeated_files": repeated,
            "duplicate_group_allocated_bytes": allocated, "eligible_for_deletion_bytes": 0}


def main():
    try:
        report = run()
    except PilotStopped as error:
        report = {"status": str(error)}
    except (OSError, ValueError, KeyError, IndexError) as error:
        report = {"status": "duplicate_audit_unverified", "error_type": type(error).__name__}
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "backup_duplicates_measured" else 2
