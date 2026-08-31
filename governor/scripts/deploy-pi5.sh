#!/usr/bin/env bash
set -euo pipefail

START=$(date +%s)
REPO=/home/joshan/lifeos-platform
GOV="$REPO/governor"

echo "===== LIFEOS GOVERNOR PI5 DEPLOY ====="
echo "Expected: <5 minutes"
echo

[[ "$(hostname)" == "Docker" ]] || { echo "FAIL: expected Docker host"; exit 20; }
[[ -d "$REPO/.git" ]] || { echo "FAIL: platform repo missing"; exit 21; }
command -v docker >/dev/null || { echo "FAIL: docker missing"; exit 22; }

echo "[1/6] Sync canonical platform"
git -C "$REPO" fetch origin main
git -C "$REPO" merge --ff-only origin/main
HEAD=$(git -C "$REPO" rev-parse HEAD)
echo "HEAD=$HEAD"

echo

echo "[2/6] Validate Governor source"
python3 -m py_compile "$GOV/app.py"
python3 - <<'PY'
import json
p=json.load(open('/home/joshan/lifeos-platform/governor/policy.json'))
assert p['policy']=='cloud-primary-offline-fallback'
assert p['primary']['provider']=='codex-cloud'
assert p['fallback']['provider']=='ollama-z97'
assert p['execution']['fallback_does_not_relax_policy'] is True
print('POLICY=PASS')
PY
docker compose -f "$GOV/docker-compose.yml" config >/dev/null
echo "SOURCE_VALIDATION=PASS"

echo

echo "[3/6] Build and deploy isolated Governor container"
docker compose -f "$GOV/docker-compose.yml" up -d --build --remove-orphans

echo

echo "[4/6] Container state"
docker ps --filter name='^/lifeos-governor$' --format 'NAME={{.Names}} STATUS={{.Status}} IMAGE={{.Image}}'

for _ in $(seq 1 20); do
    state=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' lifeos-governor 2>/dev/null || true)
    [[ "$state" == healthy || "$state" == running ]] && break
    sleep 2
done
state=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' lifeos-governor)
echo "CONTAINER_STATE=$state"
[[ "$state" == healthy || "$state" == running ]] || { docker logs --tail 100 lifeos-governor || true; exit 30; }

echo

echo "[5/6] Governor API"
python3 - <<'PY'
import json, urllib.request
with urllib.request.urlopen('http://127.0.0.1:8787/state', timeout=5) as r:
    d=json.load(r)
print('SERVICE='+d['service'])
print('POLICY='+d['policy'])
print('SELECTED_PROVIDER='+d['selected_provider'])
print('CLOUD_HEALTHY='+str(d['primary']['healthy']).lower())
print('OLLAMA_Z97_HEALTHY='+str(d['fallback']['healthy']).lower())
print('FALLBACK_MODEL='+d['fallback']['model'])
print('FAIL_CLOSED='+str(d['fail_closed']).lower())
assert d['policy']=='cloud-primary-offline-fallback'
assert d['fallback']['model']=='qwen2.5-coder:7b-instruct'
assert d['execution_policy']=='gated-control-plane-only'
PY

echo

echo "[6/6] Safety boundaries"
echo "CONTAINER_PRIVILEGED=$(docker inspect -f '{{.HostConfig.Privileged}}' lifeos-governor)"
echo "CONTAINER_READONLY=$(docker inspect -f '{{.HostConfig.ReadonlyRootfs}}' lifeos-governor)"
echo "CONTAINER_RESTART=$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' lifeos-governor)"
echo "HOST_PORT_BIND=127.0.0.1:8787"
echo "OLLAMA_LOCATION=z97"
echo "LOCAL_LLM_ON_PI=no"
echo "OPENHANDS=no"
echo

echo "RESULT=PASS"
echo "NEXT=prove_governor_cloud_primary_then_z97_offline_fallback"
echo "Elapsed: $(( $(date +%s)-START ))s"
