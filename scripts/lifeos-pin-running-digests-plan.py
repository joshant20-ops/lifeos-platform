#!/usr/bin/env python3
"""Read-only Stage 3 pinning plan from the currently running Docker digests.

This script does NOT modify Compose files or restart containers. It extracts the
current desired image for retained LifeOS services, maps each service to the
running container, resolves the running image RepoDigest, and emits the exact
immutable replacement string proposed for the next gated change.

Policy:
- Pin core retained infrastructure to the exact digest currently running.
- Pin Predbat to its proven running digest without upgrading it.
- Leave LifeOS Energy unchanged (already version-pinned, experimental).
- Leave Autoheal unchanged (pending remove/keep decision).
- Leave qBittorrent unchanged (outside core LifeOS scope).
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "ansible/vars/compose_projects.json"
DESIRED_ROOT = ROOT / "ansible/desired/compose"

PIN_PROJECTS = {
    "adguard",
    "homeassistant",
    "matter-server",
    "mosquitto",
    "npm",
    "paperless",
    "predbat",
    "uptime-kuma",
    "vaultwarden",
    "zwave-js-ui",
}
LEAVE_PROJECTS = {
    "autoheal": "PENDING_REMOVAL_DECISION",
    "lifeos-energy": "ALREADY_VERSION_PINNED_EXPERIMENTAL",
    "qbittorrent": "OUTSIDE_CORE_LIFEOS_SCOPE",
}


def sh(*args: str) -> str:
    p = subprocess.run(args, text=True, capture_output=True)
    if p.returncode:
        raise RuntimeError(f"command failed ({p.returncode}): {' '.join(args)}\n{p.stderr.strip()}")
    return p.stdout.strip()


def load_yaml(path: pathlib.Path):
    try:
        import yaml  # type: ignore
    except ImportError:
        raise SystemExit("PyYAML is required (python3-yaml on Debian).")
    return yaml.safe_load(path.read_text())


def repo_digest_for_container(container: str) -> str:
    image_id = sh("docker", "inspect", "-f", "{{.Image}}", container)
    raw = sh("docker", "image", "inspect", "-f", "{{json .RepoDigests}}", image_id)
    digests = json.loads(raw or "[]")
    if not digests:
        return ""
    running_ref = sh("docker", "inspect", "-f", "{{.Config.Image}}", container)
    base = running_ref.split("@", 1)[0].rsplit(":", 1)[0] if ":" in running_ref.split("/")[-1] else running_ref.split("@", 1)[0]
    for d in digests:
        if d.split("@", 1)[0] == base:
            return d
    return digests[0]


def main() -> int:
    if not MANIFEST.exists():
        raise SystemExit(f"missing manifest: {MANIFEST}")
    manifest = json.loads(MANIFEST.read_text())
    projects = {p["project"]: p for p in manifest.get("compose_projects", [])}

    rows = []
    errors = []
    proposed = 0

    for project, meta in sorted(projects.items()):
        desired_files = meta.get("desired_files") or []
        if not desired_files:
            errors.append(f"{project}: no desired_files")
            continue
        compose = ROOT / "ansible" / desired_files[0]
        if not compose.exists():
            errors.append(f"{project}: missing {compose.relative_to(ROOT)}")
            continue
        data = load_yaml(compose) or {}
        services = data.get("services") or {}
        containers = list(meta.get("containers") or [])

        for service, cfg in services.items():
            if not isinstance(cfg, dict) or not cfg.get("image"):
                continue
            desired = str(cfg["image"])
            container = str(cfg.get("container_name") or "")
            if not container:
                # For compose-generated names, locate by project/service label.
                ids = sh(
                    "docker", "ps", "-a", "-q",
                    "--filter", f"label=com.docker.compose.project={project}",
                    "--filter", f"label=com.docker.compose.service={service}",
                ).splitlines()
                if len(ids) == 1:
                    container = ids[0]
                elif len(containers) == 1:
                    container = containers[0]
            if not container:
                errors.append(f"{project}/{service}: unable to resolve container")
                continue
            try:
                running_state = sh("docker", "inspect", "-f", "{{.State.Status}}", container)
                running_image = sh("docker", "inspect", "-f", "{{.Config.Image}}", container)
                digest = repo_digest_for_container(container)
            except Exception as exc:
                errors.append(f"{project}/{service}: {exc}")
                continue

            if project in PIN_PROJECTS:
                decision = "PIN_RUNNING_DIGEST"
                proposed_image = digest or "NO_DIGEST"
                if digest:
                    proposed += 1
                else:
                    errors.append(f"{project}/{service}: no RepoDigest available")
            else:
                decision = LEAVE_PROJECTS.get(project, "REVIEW")
                proposed_image = desired

            rows.append((
                project, service, container, running_state, desired,
                running_image, digest or "-", decision, proposed_image,
            ))

    headers = (
        "PROJECT", "SERVICE", "CONTAINER", "STATE", "DESIRED_IMAGE",
        "RUNNING_IMAGE", "RUNNING_DIGEST", "DECISION", "PROPOSED_IMAGE",
    )
    widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            widths[i] = min(max(widths[i], len(str(val))), 78)

    def trunc(v: str, w: int) -> str:
        return v if len(v) <= w else v[: max(1, w - 1)] + "…"

    print("  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    print("  ".join("-" * widths[i] for i in range(len(headers))))
    for row in rows:
        print("  ".join(trunc(str(v), widths[i]).ljust(widths[i]) for i, v in enumerate(row)))

    print()
    print("PINNING_PLAN=PASS" if not errors else "PINNING_PLAN=FAIL")
    print(f"SERVICES={len(rows)}")
    print(f"PROPOSED_DIGEST_PINS={proposed}")
    print("MUTATIONS=NONE")
    print("LEAVE_AUTOHEAL=YES")
    print("LEAVE_QBITTORRENT=YES")
    print("LEAVE_LIFEOS_ENERGY=YES")

    if errors:
        print("ERRORS:")
        for e in errors:
            print(f"- {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
