#!/usr/bin/env python3
"""Guarded, non-recreating recovery of the existing Paperless Compose containers."""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import paperless_runtime_diagnostic as audit

PROJECT = pathlib.Path("/home/joshan/paperless")
COMPOSE = PROJECT / "docker-compose.yml"
EXPECTED_BINDS = {
    "db": {("/home/joshan/paperless/data/db", "/var/lib/postgresql/data")},
    "paperless": {
        ("/home/joshan/paperless/data/data", "/usr/src/paperless/data"),
        ("/mnt/synology/Joshan/paperless_media", "/usr/src/paperless/media"),
        ("/mnt/synology/Joshan/paperless_export", "/usr/src/paperless/export"),
        ("/mnt/synology/Joshan/Intake", "/usr/src/paperless/consume"),
    },
}


def command(args: list[str], timeout: int = 8) -> str | None:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or len(result.stdout) > 8192:
        return None
    return result.stdout.strip()


def compose(*args: str, timeout: int = 8) -> str | None:
    return command([
        "docker", "compose", "--project-directory", str(PROJECT),
        "--project-name", "paperless", "--file", str(COMPOSE), *args,
    ], timeout=timeout)


def inspect_service(service: str) -> dict | None:
    raw_ids = command([
        "docker", "ps", "--all", "--quiet",
        "--filter", "label=com.docker.compose.project=paperless",
    ], timeout=5)
    ids = raw_ids.splitlines() if raw_ids else []
    if not ids or len(ids) > 10:
        return None
    matches = []
    metadata_template = (
        '{{index .Config.Labels "com.docker.compose.project"}}|'
        '{{index .Config.Labels "com.docker.compose.service"}}|'
        '{{.State.Status}}|{{.State.ExitCode}}|{{.State.OOMKilled}}|'
        '{{.RestartCount}}|{{if .State.Error}}YES{{else}}NO{{end}}|'
        '{{.HostConfig.RestartPolicy.Name}}|'
        '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}'
    )
    for container_id in ids:
        metadata = command(["docker", "inspect", "--format", metadata_template, container_id], timeout=5)
        raw_mounts = command([
            "docker", "inspect", "--format",
            '{{range .Mounts}}{{.Type}}|{{.Name}}|{{.Source}}|{{.Destination}};{{end}}',
            container_id,
        ], timeout=5)
        proxy = command([
            "docker", "inspect", "--format",
            '{{if index .NetworkSettings.Networks "reverse_proxy"}}YES{{else}}NO{{end}}',
            container_id,
        ], timeout=5)
        if metadata is None or raw_mounts is None or proxy not in {"YES", "NO"}:
            return None
        fields = metadata.split("|")
        if len(fields) != 9:
            return None
        project, current_service, status, exit_code, oom, restart_count, error, policy, health = fields
        mounts = []
        for entry in raw_mounts.split(";"):
            if not entry:
                continue
            mount_fields = entry.split("|", 3)
            if len(mount_fields) != 4:
                return None
            mount_type, name, source, destination = mount_fields
            mounts.append({
                "Type": mount_type, "Name": name, "Source": source,
                "Destination": destination,
            })
        if project != "paperless" or current_service != service:
            continue
        if status not in audit.STATES:
            status = "unknown"
        try:
            exit_code = int(exit_code)
            restart_count = int(restart_count)
        except ValueError:
            return None
        if oom not in {"true", "false"} or error not in {"YES", "NO"}:
            return None
        if policy not in {"no", "always", "unless-stopped", "on-failure"}:
            return None
        if health not in {"healthy", "unhealthy", "starting", "none"}:
            health = "unknown"
        matches.append({
            "Config": {"Labels": {
                "com.docker.compose.project": project,
                "com.docker.compose.service": current_service,
            }},
            "State": {
                "Status": status, "ExitCode": exit_code,
                "OOMKilled": oom == "true", "Error": "present" if error == "YES" else "",
                "Health": {"Status": health},
            },
            "RestartCount": restart_count,
            "HostConfig": {"RestartPolicy": {"Name": policy}},
            "Mounts": mounts,
            "NetworkSettings": {"Networks": {"reverse_proxy": {}} if proxy == "YES" else {}},
        })
    return matches[0] if len(matches) == 1 else None


def safe_preflight() -> bool:
    required = ["/mnt/synology", *audit.NAS_PATHS.values()]
    if any(audit.mount_state(path) != "MOUNTED" for path in required):
        print("PAPERLESS_RESTORE_BLOCKED=MOUNT_PRECONDITION")
        return False
    if any(audit.path_presence(path) != "YES" for path in required[1:]):
        print("PAPERLESS_RESTORE_BLOCKED=EXPECTED_PATH_MISSING")
        return False
    if audit._active_state(audit.run(["systemctl", "is-active", "docker.service"])) != "YES":
        print("PAPERLESS_RESTORE_BLOCKED=DOCKER_INACTIVE")
        return False
    if audit._active_state(audit.run(["systemctl", "is-active", "containerd.service"])) != "YES":
        print("PAPERLESS_RESTORE_BLOCKED=CONTAINERD_INACTIVE")
        return False
    if audit.compose_config_state() != "VALID":
        print("PAPERLESS_RESTORE_BLOCKED=COMPOSE_INVALID")
        return False
    if audit.present(audit.DB_VERSION) != "YES":
        print("PAPERLESS_RESTORE_BLOCKED=DATABASE_MARKER_MISSING")
        return False
    if audit.resource_state("volume", "paperless_redis_data") != "PRESENT":
        print("PAPERLESS_RESTORE_BLOCKED=REDIS_VOLUME_MISSING")
        return False
    if audit.resource_state("network", "reverse_proxy") != "PRESENT":
        print("PAPERLESS_RESTORE_BLOCKED=REVERSE_PROXY_NETWORK_MISSING")
        return False

    for service in ("db", "redis", "paperless"):
        value = inspect_service(service)
        if value is None:
            print("PAPERLESS_RESTORE_BLOCKED=CONTAINER_SET_MISMATCH")
            return False
        state = value.get("State", {})
        policy = value.get("HostConfig", {}).get("RestartPolicy", {}).get("Name")
        if state.get("Status") != "exited" or policy != "unless-stopped":
            print("PAPERLESS_RESTORE_BLOCKED=CONTAINER_STATE_UNEXPECTED")
            return False
        if state.get("OOMKilled") or state.get("Error"):
            print("PAPERLESS_RESTORE_BLOCKED=CONTAINER_FAILURE_FLAG")
            return False
        if service in EXPECTED_BINDS:
            bindings = {
                (mount.get("Source"), mount.get("Destination"))
                for mount in value.get("Mounts", [])
                if mount.get("Type") == "bind"
            }
            if not EXPECTED_BINDS[service].issubset(bindings):
                print("PAPERLESS_RESTORE_BLOCKED=EXPECTED_BIND_MOUNT_MISMATCH")
                return False
        if service == "redis":
            volumes = {
                (mount.get("Name"), mount.get("Destination"))
                for mount in value.get("Mounts", [])
                if mount.get("Type") == "volume"
            }
            if ("paperless_redis_data", "/data") not in volumes:
                print("PAPERLESS_RESTORE_BLOCKED=REDIS_VOLUME_BINDING_MISMATCH")
                return False
        if service == "paperless" and "reverse_proxy" not in value.get("NetworkSettings", {}).get("Networks", {}):
            print("PAPERLESS_RESTORE_BLOCKED=REVERSE_PROXY_NETWORK_BINDING_MISMATCH")
            return False
    summary = audit.container_summary()
    if summary is None or summary.get("total") != 3 or summary.get("state_exited") != 3:
        print("PAPERLESS_RESTORE_BLOCKED=CONTAINER_SET_MISMATCH")
        return False
    print("PAPERLESS_RESTORE_PREFLIGHT=PASS")
    return True


def wait_health(service: str, timeout: int = 180) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = inspect_service(service)
        if value is None:
            time.sleep(3)
            continue
        state = value.get("State", {})
        if state.get("Status") != "running":
            time.sleep(3)
            continue
        health = state.get("Health", {}).get("Status", "none")
        if health == "healthy":
            return True
        time.sleep(3)
    return False


def main() -> int:
    if not safe_preflight():
        return 2
    if compose("start", "db", "redis", timeout=30) is None:
        print("PAPERLESS_RESTORE_FAILED=DEPENDENCY_START")
        return 1
    print("PAPERLESS_DEPENDENCIES_STARTED=YES")
    for service in ("db", "redis"):
        if not wait_health(service):
            print(f"PAPERLESS_RESTORE_FAILED={service.upper()}_HEALTH_TIMEOUT")
            return 1
    print("PAPERLESS_DEPENDENCIES_HEALTHY=YES")
    if compose("start", "paperless", timeout=30) is None:
        print("PAPERLESS_RESTORE_FAILED=APPLICATION_START")
        return 1
    print("PAPERLESS_APPLICATION_STARTED=YES")
    deadline = time.monotonic() + 180
    status = "000"
    while time.monotonic() < deadline:
        status = audit.api_http_status()
        if status != "000":
            print("PAPERLESS_API_HTTP_STATUS=" + status)
            print("PAPERLESS_RESTORE_RESULT=STARTED_API_REACHABLE")
            return 0
        time.sleep(5)
    print("PAPERLESS_API_HTTP_STATUS=000")
    print("PAPERLESS_RESTORE_FAILED=API_TIMEOUT")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
