#!/usr/bin/env python3
"""Read-only, fixed-field EmailOps prerequisites. Never read mailbox data/secrets."""
from __future__ import annotations

import os
from pathlib import Path
import platform
import shutil
import subprocess

PROFILE = Path("/home/joshan/.local/share/lifeos/emailops-shadow")


def probe_command(argv):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None


def audit():
    result = {"EMAILOPS_AUDIT_MODE": "READ_ONLY", "EMAILOPS_MAILBOX_WRITES": "DISABLED"}
    result["EMAILOPS_ARCH"] = platform.machine()
    result["EMAILOPS_LIBC"] = "_".join(platform.libc_ver()) or "UNKNOWN"
    for name in ("cargo", "rustc", "pkg-config", "dbus-run-session", "gnome-keyring-daemon", "secret-tool"):
        marker = name.upper().replace("-", "_")
        result["EMAILOPS_" + marker] = "PRESENT" if shutil.which(name) else "ABSENT"
    result["EMAILOPS_PROFILE"] = "PRESENT" if PROFILE.is_dir() else "NOT_INSTALLED"
    result["EMAILOPS_CLI"] = "PRESENT" if (PROFILE / "bin/emailops-cli").is_file() else "NOT_INSTALLED"
    result["EMAILOPS_PRIVATE_PROFILE"] = (
        "PASS" if PROFILE.is_dir() and not (PROFILE.stat().st_mode & 0o077) else "NOT_READY"
    )
    # Listing bus names does not activate/unlock a credential service.
    busctl = shutil.which("busctl")
    bus = probe_command([busctl, "--user", "list", "--no-legend", "--no-pager"]) if busctl else None
    result["EMAILOPS_SECRET_SERVICE"] = (
        "ACTIVE" if bus and bus.returncode == 0 and "org.freedesktop.secrets " in bus.stdout else "NOT_ACTIVE"
    )
    result["EMAILOPS_DISK_FREE_MB"] = str(shutil.disk_usage("/home/joshan").free // (1024 * 1024))
    result["EMAILOPS_AUDIT"] = "PASS"
    return result


def main():
    if platform.node() != "Docker" or platform.machine() not in {"aarch64", "arm64"} or os.geteuid() == 0:
        print("EMAILOPS_AUDIT=BLOCKED_WRONG_RUNTIME")
        return 20
    for key, value in audit().items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
