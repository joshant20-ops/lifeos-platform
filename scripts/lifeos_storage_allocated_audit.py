"""Measure visible allocated blocks with one bounded, read-only traversal."""
import json
import os
from pathlib import Path
import subprocess
import time

from scripts.lifeos_storage_backup_profile import storage_blocks

ROOT = Path("/mnt/docker-data")
KNOWN = frozenset({"automation", "containerd", "opt-stacks", "volumes",
                   "containers", "docker", "recovery", "rollback"})
CONTAINERD = {
    "io.containerd.content.v1.content": "content_store",
    "io.containerd.snapshotter.v1.overlayfs": "overlay_snapshots",
}


def summarize(raw, root, complete, before, after):
    categories = {}
    containerd = {}
    visible = None
    for record in raw.split(b"\0")[:-1]:
        number, path = record.split(b"\t", 1)
        allocated = int(number)
        if allocated < 0:
            raise ValueError("invalid_allocated_count")
        path = Path(os.fsdecode(path))
        if path == root:
            visible = allocated
            continue
        if path.parent.parent == root:
            if path.parent.name == "containerd":
                family = CONTAINERD.get(path.name, "other_entries")
                containerd[family] = containerd.get(family, 0) + allocated
            continue
        if path.parent != root:
            raise ValueError("unexpected_depth")
        category = path.name if path.name in KNOWN else "other_entries"
        categories[category] = categories.get(category, 0) + allocated
    subtotal = sum(categories.values())
    if visible is not None and visible >= subtotal:
        categories["mount_root_and_loose_files"] = visible - subtotal
    else:
        visible = subtotal
        complete = False
    return {
        "allocated_bytes_by_category": dict(sorted(categories.items())),
        "containerd_allocated_bytes_by_family": dict(sorted(containerd.items())),
        "visible_allocated_bytes": visible,
        "scan_complete": complete,
        "filesystem_used_bytes_before": before,
        "filesystem_used_bytes_after": after,
        "used_minus_visible_bytes": after - visible,
    }


def mount_scope_safe(root):
    root_dev = root.stat().st_dev
    if not root.is_mount():
        return False
    # du -x skips different devices. Reject same-device nested mounts since
    # they can expose another view of data already counted by the traversal.
    with open("/proc/self/mountinfo", encoding="utf-8") as stream:
        for line in stream:
            fields = line.split()
            mount = fields[4]
            if mount.startswith(str(root) + "/"):
                major, minor = map(int, fields[2].split(":"))
                if os.makedev(major, minor) == root_dev:
                    return False
    return True


def scan(root, guard=None):
    # stat and statvfs can succeed even when the runner cannot list the mount.
    try:
        with os.scandir(root) as entries:
            next(entries, None)
    except PermissionError:
        return b"", "root_listing_denied"

    deadline = time.monotonic() + 50
    with subprocess.Popen(
        ["/usr/bin/du", "-x", "-B1", "--max-depth=2", "--null", "--", str(root)],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    ) as process:
        try:
            while True:
                if guard is not None:
                    guard(process=process)
                remaining = deadline - time.monotonic()
                try:
                    raw, _ = process.communicate(timeout=max(0, min(2, remaining)))
                except subprocess.TimeoutExpired as error:
                    if remaining <= 2:
                        return error.stdout or b"", "du_timeout"
                else:
                    return raw, "du_failed" if process.returncode else None
        finally:
            if process.poll() is None:
                process.kill()


def main(guard=None):
    try:
        if not mount_scope_safe(ROOT):
            print(json.dumps({"status": "mount_scope_unverified"}))
            return 2
        before = storage_blocks(ROOT)
        if (before["available_bytes"] < max(10 * 2**30, before["capacity_bytes"] // 10)
                or before["available_inodes"] < os.statvfs(ROOT).f_files // 10):
            print(json.dumps({"status": "reserve_too_low"}))
            return 2
        if guard is not None:
            guard()
        raw, failure = scan(ROOT, guard)
        if guard is not None:
            guard()
        after = storage_blocks(ROOT)
        report = summarize(raw, ROOT, failure is None, before["used_bytes"], after["used_bytes"])
        report["scan_status"] = failure or ("complete" if report["scan_complete"] else "incomplete_totals")
        report["filesystem_blocks_after"] = after
        print(json.dumps(report, sort_keys=True))
        return 0 if report["scan_complete"] else 2
    except (OSError, ValueError, IndexError):
        print(json.dumps({"status": "allocated_audit_unavailable"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
