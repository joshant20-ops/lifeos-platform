#!/usr/bin/env bash
set -Eeuo pipefail
# Sanitised observation only: versions/digests/PASS-WATCH-FAIL, never HA values/secrets.
current=$(docker inspect -f '{{.Image}}' predbat)
test -n "$current"
# Candidate discovery remains bounded to the allow-listed Predbat image.
docker pull nipar44/predbat_addon:latest >/dev/null
candidate=$(docker image inspect nipar44/predbat_addon:latest -f '{{.Id}}')
test -n "$candidate"
# The persistent Predbat core version is authoritative. The image can be newer
# while /config/apps/predbat still contains an older running core.
iv=$(docker exec predbat sh -lc "cd /config/apps/predbat && python3 -c 'import predbat; print(predbat.THIS_VERSION)'" 2>/dev/null | tail -1 || true)
cv=$(docker image inspect nipar44/predbat_addon:latest -f '{{index .Config.Labels "org.opencontainers.image.version"}}' 2>/dev/null || true)
iv=${iv#v}; cv=${cv#v}; test -n "$iv"; test -n "$cv"
src="https://github.com/springfall2008/batpred/releases"
python3 - "$iv" "$cv" "$current" "$candidate" "$src" <<'PY'
import json,sys
iv,cv,old,new,src=sys.argv[1:]
def dig(x): return x if x.startswith("sha256:") else "sha256:"+x.removeprefix("sha256:")
pre={k:"PASS" for k in ("installed_candidate_versions","container_health_start_time","git_alignment","systemd_units","ha_api","predbat_status","energy_telemetry","predbat_sanity","power_down_assurance","mqtt","backup","rollback_plan")}
o={"target":"predbat","installed_version":iv,"installed_digest":dig(old),"releases":[{"version":cv,"digest":dig(new),"source":src,"release_notes":""}],"pre_update":pre,"rollback_safe":True}
print("MANAGED_UPDATE_OBSERVATION="+json.dumps(o,separators=(",",":")))
PY
