#!/usr/bin/env python3
import json, re, subprocess

SECRET = re.compile(r"(?i)(token|password|secret|api[_-]?key|authorization)\s*[:=]\s*[^\s,}]+")
IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
URL_CREDS = re.compile(r"(?i)(https?://)([^/@\s:]+):([^/@\s]+)@")

def run(*args, check=True):
    p = subprocess.run(args, text=True, capture_output=True)
    if check and p.returncode:
        raise RuntimeError(f"command failed rc={p.returncode}: {' '.join(args)}\n{p.stderr}")
    return p.stdout

def redact(s):
    s = SECRET.sub(lambda m: m.group(1)+"=<redacted>", s)
    s = URL_CREDS.sub(r"\1<redacted>@", s)
    s = IP.sub("<ip>", s)
    return s

containers = run("docker","ps","--format","{{.Names}}").splitlines()
ha = next((x for x in containers if x in ("homeassistant","home-assistant")), None)
if not ha:
    raise SystemExit("HA_CONTAINER=NOT_FOUND")

# Find YAML references without exposing credentials or addresses.
yaml_out = run("docker","exec",ha,"sh","-lc",
    "find /config -maxdepth 3 -type f \\( -name '*.yaml' -o -name '*.yml' \\) -print0 | "
    "xargs -0 grep -nHiE 'shut[[:space:]]*down[[:space:]]*tower|shutdown[[:space:]]*tower|tower|z97|poweroff|shutdown|lifeos[-_]?wol|power[-_]?down' || true")
yaml_lines = [redact(x)[:500] for x in yaml_out.splitlines()]

# Read HA entity registry structurally. Do not emit states or private values.
registry_py = r'''import json
p='/config/.storage/core.entity_registry'
d=json.load(open(p))
for e in d.get('data',{}).get('entities',[]):
    blob=' '.join(str(e.get(k,'')) for k in ('entity_id','name','original_name','unique_id','platform'))
    if any(x in blob.lower() for x in ('tower','shutdown','shut down','z97')):
        print(json.dumps({k:e.get(k) for k in ('entity_id','name','original_name','unique_id','platform','device_id','config_entry_id')}, sort_keys=True))
'''
registry_out = run("docker","exec",ha,"python3","-c",registry_py)
registry = []
for line in registry_out.splitlines():
    try: registry.append(json.loads(line))
    except Exception: pass

# Determine dashboard references to the matching entity IDs, but emit only file/path + entity IDs.
entity_ids = [e.get('entity_id') for e in registry if e.get('entity_id')]
dash_refs=[]
for eid in entity_ids:
    out=run("docker","exec",ha,"sh","-lc",f"grep -RIl --exclude='*.log' --exclude='*.db*' {eid!r} /config/.storage /config/www /config/*.yaml /config/packages 2>/dev/null || true")
    for path in out.splitlines(): dash_refs.append({'entity_id':eid,'path':path})

# Systemd structural evidence for the dedicated tower-control service.
unit = run("systemctl","show","lifeos-tower-control.service","--no-pager",
           "-p","LoadState","-p","ActiveState","-p","SubState","-p","FragmentPath","-p","ExecStart", check=False)
unit = redact(unit)
cat = run("systemctl","cat","lifeos-tower-control.service","--no-pager", check=False)
cat_lines=[]
for x in cat.splitlines():
    if x.startswith(('ExecStart=','Description=','User=','Group=','After=','Requires=','Wants=')):
        cat_lines.append(redact(x))

print("TOWER_SHUTDOWN_AUDIT_V2=PASS")
print(f"HA_CONTAINER={ha}")
print(f"YAML_MATCH_COUNT={len(yaml_lines)}")
print("ENTITY_REGISTRY_BEGIN")
for e in registry: print(json.dumps(e, sort_keys=True))
print("ENTITY_REGISTRY_END")
print("DASHBOARD_REFERENCES_BEGIN")
for r in dash_refs: print(json.dumps(r, sort_keys=True))
print("DASHBOARD_REFERENCES_END")
print("TOWER_CONTROL_UNIT_BEGIN")
print(unit.strip())
for x in cat_lines: print(x)
print("TOWER_CONTROL_UNIT_END")
print("POWERDOWN_PACKAGE_MATCHES_BEGIN")
for x in yaml_lines:
    if 'lifeos_powerdown.yaml' in x or 'tower' in x.lower() or 'shutdown' in x.lower(): print(x)
print("POWERDOWN_PACKAGE_MATCHES_END")
print("STATES_EMITTED=NO")
print("SECRETS_REDACTED=YES")
print("MUTATION_PERFORMED=NO")
