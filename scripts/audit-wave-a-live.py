#!/usr/bin/env python3
"""Read-only live discovery for LifeOS Wave A (PA + Home/Infra + Energy).

Produces only structural/sanitized evidence. It must not mutate Home Assistant,
MQTT, Energy controllers, Docker state, or the repository.
"""
from __future__ import annotations

import json
import subprocess
import urllib.request
from pathlib import Path

OUT = Path.home() / ".local/state/lifeos/wave-a-discovery.json"


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True)


def fail(msg: str) -> None:
    print("WAVE_A_DISCOVERY=FAIL")
    print("DETAIL=" + msg.replace("\n", " | ")[:2000])
    raise SystemExit(1)


ps = run(["docker", "ps", "--format", "{{.Names}}"])
if ps.returncode:
    fail("docker ps failed")
containers = set(ps.stdout.splitlines())


def pick(*names: str) -> str | None:
    return next((name for name in names if name in containers), None)


ha = pick("home-assistant", "homeassistant")
energy = pick("lifeos-energy")
mosquitto = pick("mosquitto")
predbat = pick("predbat")

if not ha:
    fail("Home Assistant container not found")
if not energy:
    fail("lifeos-energy container not found")
if not mosquitto:
    fail("mosquitto container not found")
if not predbat:
    fail("predbat container not found")


def dexec(container: str, *args: str) -> subprocess.CompletedProcess[str]:
    return run(["docker", "exec", container, *args])


# Read only Home Assistant registries. Emit entity/dashboard identifiers only,
# never states, attributes, tokens, secrets, or user content.
entity_code = (
    "import json;"
    "d=json.load(open('/config/.storage/core.entity_registry'));"
    "print('\\n'.join(e.get('entity_id','') for e in d.get('data',{}).get('entities',[])))"
)
er = dexec(ha, "python3", "-c", entity_code)
entities = er.stdout.splitlines() if er.returncode == 0 else []
relevant_entities = sorted(
    e for e in entities
    if any(k in e.lower() for k in ("lifeos", "octopus", "agile", "predbat", "enphase", "energy_opportunity"))
)
notification_entities = sorted(
    e for e in entities
    if e.startswith(("notify.", "media_player.")) or "alexa" in e.lower()
)

dash_code = (
    "import json, pathlib;"
    "p=pathlib.Path('/config/.storage/lovelace_dashboards');"
    "d=json.load(open(p)) if p.exists() else {'data':{'items':[]}};"
    "print('\\n'.join(str(x.get('url_path','')) for x in d.get('data',{}).get('items',[])))"
)
dr = dexec(ha, "python3", "-c", dash_code)
dashboards = sorted(x for x in dr.stdout.splitlines() if x) if dr.returncode == 0 else []
lifeos_dashboards = [x for x in dashboards if "lifeos" in x.lower()]

# Structural source markers only. Paths are useful evidence; file contents are not emitted.
scan = dexec(
    ha,
    "sh",
    "-lc",
    "grep -RilE 'lifeos|energy[_ -]?opportun|negative[_ -]?price|octopus|predbat' "
    "/config/*.yaml /config/packages /config/automations.yaml /config/scripts.yaml 2>/dev/null | sort -u | head -200",
)
ha_source_files = sorted(set(scan.stdout.splitlines())) if scan.returncode in (0, 1) else []

# LifeOS Energy health/status shape. Preserve only HTTP status and JSON key names.
energy_endpoints: dict[str, dict[str, object]] = {}
for path in ("/health", "/api/status"):
    item: dict[str, object] = {}
    try:
        with urllib.request.urlopen("http://127.0.0.1:8110" + path, timeout=5) as resp:
            item["http_status"] = resp.status
            raw = resp.read(8192).decode("utf-8", "replace")
            try:
                parsed = json.loads(raw)
                item["json_keys"] = sorted(parsed.keys()) if isinstance(parsed, dict) else [type(parsed).__name__]
            except json.JSONDecodeError:
                item["body_kind"] = "non_json"
    except Exception as exc:
        item["error_type"] = type(exc).__name__
    energy_endpoints[path] = item

# Detect existing repository primitives that may already provide a common event/action model.
repo = Path("/home/joshan/lifeos-platform")
keywords = ("attention", "event", "action", "opportunity", "personal-assistant", "personal_assistant")
repo_candidates: list[str] = []
for root in (repo / "docs", repo / "governor", repo / "ha", repo / "scripts"):
    if not root.exists():
        continue
    for p in root.rglob("*"):
        if not p.is_file() or p.stat().st_size > 512_000:
            continue
        name = str(p.relative_to(repo)).lower()
        if any(k in name for k in keywords):
            repo_candidates.append(str(p.relative_to(repo)))
repo_candidates = sorted(set(repo_candidates))[:300]

report = {
    "schema_version": 1,
    "wave": "A",
    "mode": "read_only_discovery",
    "containers": {
        "home_assistant": ha,
        "lifeos_energy": energy,
        "mosquitto": mosquitto,
        "predbat": predbat,
    },
    "ha": {
        "relevant_entity_ids": relevant_entities,
        "notification_entity_ids": notification_entities,
        "lifeos_dashboard_paths": lifeos_dashboards,
        "relevant_config_files": ha_source_files,
    },
    "lifeos_energy": {"endpoints": energy_endpoints},
    "repository_candidate_primitives": repo_candidates,
    "secrets_emitted": False,
    "states_emitted": False,
    "mutation_performed": False,
}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

print("WAVE_A_DISCOVERY=PASS")
print("HA_CONTAINER=" + ha)
print("LIFEOS_ENERGY_CONTAINER=" + energy)
print("MOSQUITTO_CONTAINER=" + mosquitto)
print("PREDBAT_CONTAINER=" + predbat)
print("RELEVANT_HA_ENTITIES=" + str(len(relevant_entities)))
print("NOTIFICATION_ENTITIES=" + str(len(notification_entities)))
print("LIFEOS_DASHBOARDS=" + str(len(lifeos_dashboards)))
print("RELEVANT_HA_CONFIG_FILES=" + str(len(ha_source_files)))
print("REPO_CANDIDATE_PRIMITIVES=" + str(len(repo_candidates)))
print("SECRETS_EMITTED=NO")
print("STATES_EMITTED=NO")
print("MUTATION_PERFORMED=NO")
print("REPORT=" + str(OUT))
