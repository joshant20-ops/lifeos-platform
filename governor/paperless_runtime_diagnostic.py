"""Privacy-safe, bounded read-only precondition audit for Paperless."""
from __future__ import annotations

import json
import pathlib
import subprocess

PROJECT = pathlib.Path("/home/joshan/paperless")
COMPOSE = PROJECT / "docker-compose.yml"
DB_VERSION = PROJECT / "data/db/PG_VERSION"
APP_DATA = PROJECT / "data/data"
NAS_PATHS = {
    "PAPERLESS_MEDIA_MOUNT": "/mnt/synology/Joshan/paperless_media",
    "PAPERLESS_EXPORT_MOUNT": "/mnt/synology/Joshan/paperless_export",
    "PAPERLESS_INTAKE_MOUNT": "/mnt/synology/Intake",
}
STATES = ("running", "exited", "created", "restarting", "paused", "dead", "removing", "unknown")
HEALTHS = ("healthy", "unhealthy", "starting", "none", "unknown")


def run(args: list[str], timeout: int = 4) -> subprocess.CompletedProcess[str] | None:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        if len(result.stdout) > 4096:
            return None
        return result
    except (OSError, subprocess.TimeoutExpired):
        return None


def present(path: pathlib.Path, *, directory: bool = False) -> str:
    try:
        if path.is_symlink():
            return "NO"
        return "YES" if (path.is_dir() if directory else path.is_file()) else "NO"
    except OSError:
        return "UNKNOWN"


def directory_state(path: pathlib.Path) -> str:
    try:
        if path.is_symlink():
            return "SYMLINK"
        if not path.exists():
            return "MISSING"
        if not path.is_dir():
            return "NOT_DIRECTORY"
        return "PRESENT" if next(path.iterdir(), None) is not None else "EMPTY"
    except OSError:
        return "UNKNOWN"


def secret_present(path: pathlib.Path) -> str:
    if present(path) != "YES":
        return "NO"
    try:
        for raw in path.read_text(errors="replace").splitlines():
            line = raw.strip()
            if line.startswith("export "):
                line = line[7:].lstrip()
            key, sep, value = line.partition("=")
            if sep and key.strip() == "PAPERLESS_SECRET_KEY" and value.strip().strip("\"'"):
                return "YES"
    except OSError:
        return "UNKNOWN"
    return "NO"


def mount_state(path: str) -> str:
    result = run(["findmnt", "--noheadings", "--raw", "--target", path, "--output", "TARGET"])
    if result is None:
        return "UNKNOWN"
    if result.returncode != 0:
        return "UNMOUNTED"
    target = result.stdout.strip().rstrip("/") or "/"
    return "MOUNTED" if target == "/mnt/synology" or target.startswith("/mnt/synology/") else "UNMOUNTED"


def resource_state(kind: str, name: str) -> str:
    result = run(["docker", kind, "inspect", name, "--format", "{{.Name}}"])
    if result is None:
        return "UNKNOWN"
    return "PRESENT" if result.returncode == 0 and result.stdout.strip() == name else "MISSING"


def compose_config_state() -> str:
    if present(PROJECT, directory=True) != "YES" or present(COMPOSE) != "YES":
        return "BLOCKED"
    result = run(["docker", "compose", "--project-directory", str(PROJECT), "--project-name", "paperless", "--file", str(COMPOSE), "config", "--quiet"], timeout=8)
    if result is None:
        return "UNKNOWN"
    return "VALID" if result.returncode == 0 else "INVALID"


def container_summary() -> dict[str, int] | None:
    result = run([
        "docker", "ps", "--all", "--filter", "label=com.docker.compose.project=paperless",
        "--format", "{{.State}}|{{.Health}}",
    ], timeout=5)
    if result is None or result.returncode != 0:
        return None
    counts = {f"state_{state}": 0 for state in STATES}
    counts.update({f"health_{health}": 0 for health in HEALTHS})
    lines = result.stdout.splitlines()
    if len(lines) > 99:
        return None
    for line in lines:
        state, sep, health = line.partition("|")
        state = state.strip().lower()
        health = health.strip().lower() if sep and health.strip() else "none"
        counts[f"state_{state if state in STATES[:-1] else 'unknown'}"] += 1
        counts[f"health_{health if health in HEALTHS[:-1] else 'unknown'}"] += 1
    counts["total"] = len(lines)
    return counts


def main() -> int:
    print("PAPERLESS_AUDIT_VERSION=1")
    print("PAPERLESS_AUDIT_MUTATIONS=NONE")
    print("PAPERLESS_PROJECT_DIR=" + present(PROJECT, directory=True))
    print("PAPERLESS_COMPOSE_FILE=" + present(COMPOSE))
    print("PAPERLESS_ENV_FILE=" + present(PROJECT / ".env"))
    print("PAPERLESS_SECRET_KEY_PRESENT=" + secret_present(PROJECT / ".env"))
    print("PAPERLESS_DB_DIR=" + directory_state(PROJECT / "data/db"))
    print("PAPERLESS_DB_PG_VERSION=" + present(DB_VERSION))
    print("PAPERLESS_APP_DATA_DIR=" + directory_state(APP_DATA))
    for label, path in NAS_PATHS.items():
        print(f"{label}=" + mount_state(path))
    print("PAPERLESS_REDIS_VOLUME=" + resource_state("volume", "paperless_redis_data"))
    print("PAPERLESS_REVERSE_PROXY_NETWORK=" + resource_state("network", "reverse_proxy"))
    print("PAPERLESS_COMPOSE_CONFIG=" + compose_config_state())
    counts = container_summary()
    if counts is None:
        print("PAPERLESS_CONTAINER_SUMMARY=UNKNOWN")
        return 0
    print(f"PAPERLESS_CONTAINER_COUNT={counts['total']}")
    for state in STATES:
        print(f"PAPERLESS_CONTAINER_STATE_{state.upper()}={counts[f'state_{state}']}")
    for health in HEALTHS:
        print(f"PAPERLESS_CONTAINER_HEALTH_{health.upper()}={counts[f'health_{health}']}")
    print("PAPERLESS_CONTAINER_SUMMARY=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
