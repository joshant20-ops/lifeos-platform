"""Privacy-safe, bounded read-only precondition audit for Paperless."""
from __future__ import annotations

import pathlib
import re
import subprocess

PROJECT = pathlib.Path("/home/joshan/paperless")
COMPOSE = PROJECT / "docker-compose.yml"
DB_VERSION = PROJECT / "data/db/PG_VERSION"
APP_DATA = PROJECT / "data/data"
NAS_PATHS = {
    "PAPERLESS_MEDIA_MOUNT": "/mnt/synology/Joshan/paperless_media",
    "PAPERLESS_EXPORT_MOUNT": "/mnt/synology/Joshan/paperless_export",
    "PAPERLESS_INTAKE_MOUNT": "/mnt/synology/Joshan/Intake",
}
FSTAB = pathlib.Path("/etc/fstab")
MOUNTINFO = pathlib.Path("/proc/self/mountinfo")
FSTAB_MAX_BYTES = 262144
MOUNT_UNIT_TARGETS = {
    "SYNOLOGY": "/mnt/synology",
    "MEDIA": NAS_PATHS["PAPERLESS_MEDIA_MOUNT"],
    "EXPORT": NAS_PATHS["PAPERLESS_EXPORT_MOUNT"],
    "INTAKE": NAS_PATHS["PAPERLESS_INTAKE_MOUNT"],
}
STATES = ("running", "exited", "created", "restarting", "paused", "dead", "removing", "unknown")
HEALTHS = ("healthy", "unhealthy", "starting", "none", "unknown")
MAX_ENV_BYTES = 65536


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
        if path.stat().st_size > MAX_ENV_BYTES:
            return "UNKNOWN"
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


def path_presence(path: str) -> str:
    try:
        target = pathlib.Path(path)
        return "YES" if target.is_dir() and not target.is_symlink() else "NO"
    except OSError:
        return "UNKNOWN"


def mountinfo_state(target: str, path: pathlib.Path | None = None) -> str:
    if target not in MOUNT_UNIT_TARGETS.values():
        return "UNKNOWN"
    path = path or MOUNTINFO
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1048576:
            return "UNKNOWN"
        valid_records = 0
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            fields = line.split()
            if len(fields) < 10 or "-" not in fields[6:]:
                continue
            valid_records += 1
            if fields[4] == target:
                return "MOUNTED"
        return "UNMOUNTED" if valid_records else "UNKNOWN"
    except OSError:
        return "UNKNOWN"


def mount_state_diagnostic(path: str) -> tuple[str, str]:
    # findmnt may return stacked autofs and NFS entries for one target.
    # Inspect target and filesystem only; never expose source/options.
    result = run([
        "findmnt", "--noheadings", "--raw", "--target", path,
        "--output", "TARGET,FSTYPE",
    ])
    if result is None:
        return "UNKNOWN", "COMMAND_UNAVAILABLE"
    if result.returncode != 0:
        return "UNKNOWN", "COMMAND_FAILED"
    lines = [line.split() for line in result.stdout.splitlines() if line.strip()]
    records = [(fields[0], fields[1].lower()) for fields in lines if len(fields) == 2]
    if not records:
        return "UNKNOWN", "EMPTY_OUTPUT"

    requested = path.rstrip("/") or "/"
    synology_root = "/mnt/synology"
    relations: list[tuple[str, str]] = []
    for raw_target, filesystem in records:
        target = raw_target.rstrip("/") or "/"
        if target == "/":
            relation = "HOST_ROOT"
        elif target != synology_root and not target.startswith(synology_root + "/"):
            relation = "OUTSIDE_SYNOLOGY_TREE"
        elif requested == target:
            relation = "EXACT"
        elif requested.startswith(target.rstrip("/") + "/"):
            relation = "ANCESTOR"
        elif target.startswith(requested.rstrip("/") + "/"):
            relation = "DESCENDANT"
        else:
            relation = "NO_ANCESTOR"
        relations.append((relation, filesystem))

    # A stacked autofs entry alone is not proof that the expected NAS filesystem
    # is available. Require an NFS mount at the requested path or an ancestor.
    for relation in ("EXACT", "ANCESTOR"):
        if any(found == relation and filesystem in {"nfs", "nfs4"}
               for found, filesystem in relations):
            return "MOUNTED", relation

    if any(relation in {"EXACT", "ANCESTOR"} for relation, _ in relations):
        return "UNMOUNTED", "NFS_FILESYSTEM_MISSING"
    if any(relation == "DESCENDANT" and filesystem in {"nfs", "nfs4"}
           for relation, filesystem in relations):
        return "UNMOUNTED", "DESCENDANT"
    if any(relation == "HOST_ROOT" for relation, _ in relations):
        return "UNMOUNTED", "HOST_ROOT"
    if any(relation == "OUTSIDE_SYNOLOGY_TREE" for relation, _ in relations):
        return "UNMOUNTED", "OUTSIDE_SYNOLOGY_TREE"
    return "UNMOUNTED", "NO_ANCESTOR"


def mount_state(path: str) -> str:
    return mount_state_diagnostic(path)[0]


def fstab_targets(path: pathlib.Path | None = None) -> set[str] | None:
    """Read only canonical mount targets from fstab; never return source/options."""
    path = path or FSTAB
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > FSTAB_MAX_BYTES:
            return None
        raw = path.read_bytes()
        if len(raw) > FSTAB_MAX_BYTES:
            return None
        targets = set()
        for line in raw.decode("utf-8", errors="replace").splitlines():
            fields = line.split("#", 1)[0].split()
            if len(fields) < 2:
                continue
            target = fields[1].replace("\\040", " ").replace("\\011", "\t").replace("\\134", "\\")
            if target in MOUNT_UNIT_TARGETS.values():
                targets.add(target)
        return targets
    except OSError:
        return None


def _enabled_state(result: subprocess.CompletedProcess[str] | None) -> str:
    if result is None:
        return "UNKNOWN"
    value = result.stdout.strip().lower()
    if result.returncode == 0 and value in {"enabled", "enabled-runtime", "generated", "transient", "linked", "linked-runtime", "alias"}:
        return "YES"
    if value in {"disabled", "masked", "static", "indirect", "not-found", "bad"}:
        return "NO"
    return "UNKNOWN"


def _active_state(result: subprocess.CompletedProcess[str] | None) -> str:
    if result is None:
        return "UNKNOWN"
    value = result.stdout.strip().lower()
    if result.returncode == 0 and value == "active":
        return "YES"
    if value in {"inactive", "failed"}:
        return "NO"
    return "UNKNOWN"


def mount_unit_states(target: str) -> tuple[str, str]:
    escaped = run(["systemd-escape", "--path", "--suffix=mount", target], timeout=3)
    if escaped is None or escaped.returncode != 0:
        return "UNKNOWN", "UNKNOWN"
    unit = escaped.stdout.strip()
    # systemd-escape --path emits ASCII alphanumerics plus '.', '_' and '-'
    # for the fixed canonical mount targets audited below. Reject anything
    # outside that safe unit-name alphabet before passing it to systemctl.
    if not re.fullmatch(r"[A-Za-z0-9_.-]+\.mount", unit):
        return "UNKNOWN", "UNKNOWN"
    enabled = run(["systemctl", "is-enabled", unit], timeout=3)
    active = run(["systemctl", "is-active", unit], timeout=3)
    return _enabled_state(enabled), _active_state(active)


def mount_unit_diagnostic(target: str) -> tuple[str, str]:
    escaped = run(["systemd-escape", "--path", "--suffix=mount", target], timeout=3)
    if escaped is None or escaped.returncode != 0:
        return "UNKNOWN", "UNKNOWN"
    unit = escaped.stdout.strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+\.mount", unit):
        return "UNKNOWN", "UNKNOWN"
    sub = run(["systemctl", "show", "--property=SubState", "--value", unit], timeout=3)
    result = run(["systemctl", "show", "--property=Result", "--value", unit], timeout=3)
    if sub is None or sub.returncode != 0:
        substate = "UNKNOWN"
    else:
        raw = sub.stdout.strip().lower()
        substate = {
            "mounted": "MOUNTED",
            "mounting": "TRANSITION",
            "remounting": "TRANSITION",
            "unmounting": "TRANSITION",
            "dead": "UNMOUNTED",
            "failed": "FAILED",
        }.get(raw, "UNKNOWN")
    if result is None or result.returncode != 0:
        unit_result = "UNKNOWN"
    else:
        raw = result.stdout.strip().lower()
        unit_result = "SUCCESS" if raw == "success" else (
            "FAILURE" if raw in {
                "resources", "timeout", "exit-code", "signal", "core-dump",
                "watchdog", "protocol", "start-limit-hit", "dependency",
                "trigger-limit-hit", "oom-kill",
            } else "UNKNOWN"
        )
    return substate, unit_result


def mount_consistency(mount: str, substate: str) -> str:
    if mount == "MOUNTED" and substate == "MOUNTED":
        return "CONSISTENT"
    if mount == "UNMOUNTED" and substate in {"UNMOUNTED", "FAILED"}:
        return "CONSISTENT"
    if mount == "MOUNTED" and substate in {"UNMOUNTED", "FAILED"}:
        return "INCONSISTENT"
    if mount == "UNMOUNTED" and substate == "MOUNTED":
        return "INCONSISTENT"
    return "UNKNOWN"


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
        "--format", "{{.State}}|{{.Status}}",
    ], timeout=5)
    if result is None or result.returncode != 0:
        return None
    counts = {f"state_{state}": 0 for state in STATES}
    counts.update({f"health_{health}": 0 for health in HEALTHS})
    lines = result.stdout.splitlines()
    if len(lines) > 99:
        return None
    for line in lines:
        state, sep, status = line.partition("|")
        state = state.strip().lower()
        status = status.strip().lower() if sep else ""
        if "(unhealthy)" in status:
            health = "unhealthy"
        elif "(healthy)" in status:
            health = "healthy"
        elif "(health: starting)" in status:
            health = "starting"
        else:
            health = "none"
        counts[f"state_{state if state in STATES[:-1] else 'unknown'}"] += 1
        counts[f"health_{health if health in HEALTHS[:-1] else 'unknown'}"] += 1
    counts["total"] = len(lines)
    return counts


def container_exit_evidence() -> list[tuple[str, str, str, str, str, str, str]] | None:
    """Return fixed, non-sensitive stop metadata for Paperless Compose containers."""
    listing = run([
        "docker", "ps", "--all", "--quiet",
        "--filter", "label=com.docker.compose.project=paperless",
    ], timeout=5)
    if listing is None or listing.returncode != 0:
        return None
    ids = [line.strip() for line in listing.stdout.splitlines() if line.strip()]
    if len(ids) > 10:
        return None
    rows = []
    template = (
        '{{index .Config.Labels "com.docker.compose.service"}}|'
        '{{.State.Status}}|{{.State.ExitCode}}|{{.State.OOMKilled}}|'
        '{{.RestartCount}}|{{if .State.Error}}YES{{else}}NO{{end}}|'
        '{{.HostConfig.RestartPolicy.Name}}'
    )
    for container_id in ids:
        inspected = run(["docker", "inspect", "--format", template, container_id], timeout=5)
        if inspected is None or inspected.returncode != 0:
            return None
        fields = inspected.stdout.strip().split("|")
        if len(fields) != 7:
            return None
        service, state, exit_code, oom, restart_count, error, restart_policy = fields
        if service not in {"db", "redis", "paperless"}:
            return None
        if state not in STATES:
            state = "unknown"
        if not re.fullmatch(r"-?[0-9]+", exit_code):
            exit_code = "UNKNOWN"
        if oom not in {"true", "false"}:
            oom = "unknown"
        if not re.fullmatch(r"[0-9]+", restart_count):
            restart_count = "UNKNOWN"
        if error not in {"YES", "NO"}:
            error = "UNKNOWN"
        if restart_policy not in {"no", "always", "unless-stopped", "on-failure"}:
            restart_policy = "UNKNOWN"
        rows.append((service, state, exit_code, oom.upper(), restart_count, error, restart_policy))
    return rows


def api_http_status() -> str:
    result = run([
        "curl", "--silent", "--output", "/dev/null", "--write-out", "%{http_code}",
        "--connect-timeout", "2", "--max-time", "5", "http://127.0.0.1:8010/api/",
    ], timeout=6)
    if result is None:
        return "000"
    status = result.stdout.strip()
    return status if re.fullmatch(r"[1-5][0-9]{2}", status) else "000"


def published_state() -> str:
    result = run(["docker", "ps", "--all", "--filter", "publish=8010", "--quiet"], timeout=5)
    if result is None or result.returncode != 0:
        return "UNKNOWN"
    count = len(result.stdout.splitlines())
    return "NO" if count == 0 else ("YES" if count == 1 else "MULTIPLE")


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
    defined_mounts = fstab_targets()
    for label, target in MOUNT_UNIT_TARGETS.items():
        fstab_status = "UNKNOWN" if defined_mounts is None else ("YES" if target in defined_mounts else "NO")
        print(f"PAPERLESS_FSTAB_{label}={fstab_status}")
        enabled, active = mount_unit_states(target)
        print(f"PAPERLESS_MOUNT_UNIT_{label}_ENABLED={enabled}")
        print(f"PAPERLESS_MOUNT_UNIT_{label}_ACTIVE={active}")
    print("PAPERLESS_SYNOLOGY_PATH_EXISTS=" + path_presence("/mnt/synology"))
    root_mount_state, root_findmnt_relation = mount_state_diagnostic("/mnt/synology")
    print("PAPERLESS_SYNOLOGY_MOUNT=" + root_mount_state)
    print("PAPERLESS_SYNOLOGY_FINDMNT_RELATION=" + root_findmnt_relation)
    root_mountinfo_state = mountinfo_state("/mnt/synology")
    print("PAPERLESS_SYNOLOGY_PROC_MOUNTINFO=" + root_mountinfo_state)
    mount_substate, mount_result = mount_unit_diagnostic("/mnt/synology")
    print("PAPERLESS_SYNOLOGY_UNIT_SUBSTATE=" + mount_substate)
    print("PAPERLESS_SYNOLOGY_UNIT_RESULT=" + mount_result)
    print("PAPERLESS_SYNOLOGY_MOUNT_CONSISTENCY=" + mount_consistency(root_mount_state, mount_substate))
    if root_mountinfo_state == "UNKNOWN":
        kernel_mount_state = "UNKNOWN"
    elif root_mountinfo_state == root_mount_state:
        kernel_mount_state = "CONSISTENT"
    else:
        kernel_mount_state = "INCONSISTENT"
    print("PAPERLESS_SYNOLOGY_KERNEL_MOUNT_CONSISTENCY=" + kernel_mount_state)
    for label, path in NAS_PATHS.items():
        print(label.replace("_MOUNT", "_PATH_EXISTS") + "=" + path_presence(path))
        child_mount_state, child_findmnt_relation = mount_state_diagnostic(path)
        print(f"{label}=" + child_mount_state)
        print(label.replace("_MOUNT", "") + "_FINDMNT_RELATION=" + child_findmnt_relation)
    print("PAPERLESS_DOCKER_SERVICE_ACTIVE=" + _active_state(run(["systemctl", "is-active", "docker.service"], timeout=3)))
    print("PAPERLESS_CONTAINERD_SERVICE_ACTIVE=" + _active_state(run(["systemctl", "is-active", "containerd.service"], timeout=3)))
    print("PAPERLESS_RECONCILER_SERVICE_ACTIVE=" + _active_state(run(["systemctl", "is-active", "lifeos-task-reconciler.service"], timeout=3)))
    print("PAPERLESS_ASSISTANT_SERVICE_ACTIVE=" + _active_state(run(["systemctl", "is-active", "lifeos-assistant.service"], timeout=3)))
    print("PAPERLESS_REDIS_VOLUME=" + resource_state("volume", "paperless_redis_data"))
    print("PAPERLESS_REVERSE_PROXY_NETWORK=" + resource_state("network", "reverse_proxy"))
    print("PAPERLESS_COMPOSE_CONFIG=" + compose_config_state())
    http_status = api_http_status()
    print("PAPERLESS_8010_PUBLISHED=" + published_state())
    print("PAPERLESS_API_HTTP_STATUS=" + http_status)
    print("PAPERLESS_API_REACHABILITY=" + ("REACHABLE" if http_status != "000" else "UNREACHABLE"))
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
    exit_evidence = container_exit_evidence()
    if exit_evidence is None:
        print("PAPERLESS_CONTAINER_EXIT_EVIDENCE=UNKNOWN")
    else:
        print("PAPERLESS_CONTAINER_EXIT_EVIDENCE=AVAILABLE")
        for service, state, exit_code, oom, restart_count, error, restart_policy in sorted(exit_evidence):
            prefix = "PAPERLESS_CONTAINER_" + service.upper()
            print(f"{prefix}_STATE={state.upper()}")
            print(f"{prefix}_EXIT_CODE={exit_code}")
            print(f"{prefix}_OOM_KILLED={oom}")
            print(f"{prefix}_RESTART_COUNT={restart_count}")
            print(f"{prefix}_DOCKER_ERROR_PRESENT={error}")
            print(f"{prefix}_RESTART_POLICY={restart_policy.upper().replace('-', '_')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
