#!/usr/bin/env bash
set -Eeuo pipefail

PLATFORM="${LIFEOS_PLATFORM_REPO:-/home/joshan/lifeos-platform}"
CANONICAL="$PLATFORM/orchestration/semaphore/docker-compose.yml"
LIVE=/opt/stacks/lifeos-semaphore-shadow/docker-compose.yml
PROJECT=lifeos-semaphore-shadow

printf 'SEMAPHORE_SHADOW_AUDIT_VERSION=1\nMUTATIONS=NONE\n\n'

printf '=== SOURCE ===\n'
printf 'platform_head=%s\n' "$(git -C "$PLATFORM" rev-parse --short=12 HEAD 2>/dev/null || echo unknown)"
printf 'canonical=%s\n' "$CANONICAL"
printf 'live=%s\n' "$LIVE"
[[ -f "$CANONICAL" ]] || { echo 'AUDIT_RESULT=FAIL'; echo 'REASON=canonical_compose_missing'; exit 1; }
[[ -f "$LIVE" ]] || { echo 'AUDIT_RESULT=FAIL'; echo 'REASON=live_shadow_compose_missing'; exit 1; }

printf '\n=== FILE IDENTITY ===\n'
printf 'canonical_sha256=%s\n' "$(sha256sum "$CANONICAL" | awk '{print $1}')"
printf 'live_sha256=%s\n' "$(sha256sum "$LIVE" | awk '{print $1}')"
if cmp -s "$CANONICAL" "$LIVE"; then
  echo 'compose_identity=MATCH'
else
  echo 'compose_identity=DIFFERENT'
  echo '-- unified diff --'
  diff -u "$CANONICAL" "$LIVE" || true
fi

printf '\n=== CANONICAL SERVICES ===\n'
python3 - "$CANONICAL" <<'PY'
import sys,yaml
p=sys.argv[1]
d=yaml.safe_load(open(p)) or {}
for name,cfg in (d.get('services') or {}).items():
    print(f"{name}\timage={cfg.get('image','')}\trestart={cfg.get('restart','')}")
PY

printf '\n=== LIVE SERVICES ===\n'
python3 - "$LIVE" <<'PY'
import sys,yaml
p=sys.argv[1]
d=yaml.safe_load(open(p)) or {}
for name,cfg in (d.get('services') or {}).items():
    print(f"{name}\timage={cfg.get('image','')}\trestart={cfg.get('restart','')}")
PY

printf '\n=== RUNNING PROJECT CONTAINERS ===\n'
docker ps -a --filter "label=com.docker.compose.project=$PROJECT" \
  --format 'name={{.Names}} image={{.Image}} state={{.State}} status={{.Status}}' || true

printf '\n=== DATABASE MODE EVIDENCE ===\n'
for c in $(docker ps -a --filter "label=com.docker.compose.project=$PROJECT" --format '{{.Names}}'); do
  echo "-- $c env --"
  docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$c" 2>/dev/null | \
    grep -E '^(SEMAPHORE_DB_|POSTGRES_|SEMAPHORE_ADMIN_|SEMAPHORE_ACCESS_KEY_)' | \
    sed -E 's/(PASS|PASSWORD|KEY)=.*/\1=<redacted>/' || true
  echo "-- $c mounts --"
  docker inspect -f '{{range .Mounts}}{{println .Destination .Type .RW}}{{end}}' "$c" 2>/dev/null || true
done

printf '\n=== EXPECTED CANONICAL CONTAINERS ===\n'
for svc in semaphore-db semaphore; do
  cid=$(docker compose -p "$PROJECT" -f "$LIVE" ps -aq "$svc" 2>/dev/null || true)
  if [[ -n "$cid" ]]; then
    printf '%s=present\n' "$svc"
  else
    printf '%s=absent\n' "$svc"
  fi
done

printf '\n=== CUSTOM ORCHESTRATION REFERENCES ===\n'
grep -RIn --exclude-dir=.git -E \
  'lifeos-backlog-runner|lifeos-engineer-dispatcher|lifeos-engineer-worker|lifeos-control-job-submit|lifeos-root-broker|backlog_runner|engineer_dispatcher|engineer_worker' \
  "$PLATFORM/governor" /etc/systemd/system 2>/dev/null | head -200 || true

printf '\n=== PROMOTION READINESS ===\n'
canonical_services=$(python3 - "$CANONICAL" <<'PY'
import sys,yaml
x=yaml.safe_load(open(sys.argv[1])) or {}
print(','.join(sorted((x.get('services') or {}).keys())))
PY
)
live_services=$(python3 - "$LIVE" <<'PY'
import sys,yaml
x=yaml.safe_load(open(sys.argv[1])) or {}
print(','.join(sorted((x.get('services') or {}).keys())))
PY
)
printf 'canonical_services=%s\n' "$canonical_services"
printf 'live_services=%s\n' "$live_services"
if cmp -s "$CANONICAL" "$LIVE" && [[ "$canonical_services" == "$live_services" ]]; then
  echo 'PROMOTION_READY=YES'
  echo 'NEXT_ACTION=map_custom_execution_paths_to_semaphore'
else
  echo 'PROMOTION_READY=NO'
  echo 'BARRIER=live_shadow_does_not_match_canonical_compose'
  echo 'NEXT_ACTION=reconcile_shadow_to_canonical_before_replacing_custom_orchestration'
fi

echo 'AUDIT_RESULT=PASS'
