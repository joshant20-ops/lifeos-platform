#!/usr/bin/env python3
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DESIRED = ROOT / "ansible" / "desired" / "compose"


def run(*args):
    p = subprocess.run(args, text=True, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(args)}\n{p.stderr.strip()}")
    return p.stdout.strip()


def desired_services():
    rows = []
    try:
        import yaml
    except Exception:
        raise SystemExit("PyYAML is required: python3 -m pip install --user PyYAML")

    for f in sorted(list(DESIRED.rglob("*.yml")) + list(DESIRED.rglob("*.yaml"))):
        data = yaml.safe_load(f.read_text()) or {}
        project = f.parent.name
        for service, cfg in (data.get("services") or {}).items():
            cfg = cfg or {}
            rows.append({
                "project": project,
                "service": service,
                "desired_image": cfg.get("image"),
                "build": cfg.get("build"),
                "file": str(f.relative_to(ROOT)),
            })
    return rows


def inspect_container(name):
    p = subprocess.run(["docker", "inspect", name], text=True, capture_output=True)
    if p.returncode != 0:
        return None
    data = json.loads(p.stdout)[0]
    image_id = data.get("Image", "")
    config_image = (data.get("Config") or {}).get("Image", "")

    repo_digests = []
    if image_id:
        q = subprocess.run(
            ["docker", "image", "inspect", image_id, "--format", "{{json .RepoDigests}}"],
            text=True, capture_output=True,
        )
        if q.returncode == 0 and q.stdout.strip():
            try:
                repo_digests = json.loads(q.stdout.strip()) or []
            except Exception:
                repo_digests = []

    return {
        "container": name,
        "running_image": config_image,
        "image_id": image_id,
        "repo_digests": repo_digests,
        "state": (data.get("State") or {}).get("Status", "unknown"),
    }


def choose_digest(desired, running, digests):
    if not digests:
        return ""
    base = (desired or running or "").split("@")[0]
    base_no_tag = base
    if ":" in base.rsplit("/", 1)[-1]:
        base_no_tag = base.rsplit(":", 1)[0]
    for d in digests:
        if d.startswith(base_no_tag + "@"):
            return d
    return digests[0]


rows = desired_services()
container_names = set(run("docker", "ps", "-a", "--format", "{{.Names}}").splitlines())

print("PROJECT\tSERVICE\tCONTAINER\tSTATE\tDESIRED_IMAGE\tRUNNING_IMAGE\tIMAGE_ID\tREPO_DIGEST\tSTATUS")
counts = {"MATCH": 0, "DRIFT": 0, "NO_CONTAINER": 0, "LOCAL_BUILD": 0, "NO_DIGEST": 0}

for row in rows:
    service = row["service"]
    # Current LifeOS compose files use explicit container_name almost everywhere.
    # Prefer exact service name, then project name, then project-service compose default style.
    candidates = [service, row["project"], f"{row['project']}-{service}-1"]
    container = next((c for c in candidates if c in container_names), None)

    if row["build"] and not row["desired_image"]:
        status = "LOCAL_BUILD"
        counts[status] += 1
        print("\t".join([row["project"], service, "-", "-", "<build>", "-", "-", "-", status]))
        continue

    if not container:
        status = "NO_CONTAINER"
        counts[status] += 1
        print("\t".join([row["project"], service, "-", "absent", str(row["desired_image"] or ""), "-", "-", "-", status]))
        continue

    info = inspect_container(container)
    desired = row["desired_image"] or ""
    running = info["running_image"] or ""
    digest = choose_digest(desired, running, info["repo_digests"])

    if not digest:
        status = "NO_DIGEST"
    elif desired == running:
        status = "MATCH"
    else:
        status = "DRIFT"
    counts[status] += 1

    print("\t".join([
        row["project"], service, container, info["state"], desired, running,
        info["image_id"][:19], digest, status,
    ]))

print()
print("RUNNING_IMAGE_DIGEST_AUDIT=PASS")
for k in ("MATCH", "DRIFT", "NO_CONTAINER", "LOCAL_BUILD", "NO_DIGEST"):
    print(f"{k}={counts[k]}")
print("MUTATIONS=NONE")
