#!/usr/bin/env bash
set -Eeuo pipefail
# Detection only. LifeOS decides whether an update should proceed; Predbat/HA
# remains authoritative for installation.
current=$(docker inspect -f '{{.Image}}' predbat)
docker pull nipar44/predbat_addon:latest >/dev/null
candidate=$(docker image inspect nipar44/predbat_addon:latest -f '{{.Id}}')
iv=$(docker exec predbat sh -lc "cd /config && python3 -c 'import predbat; print(predbat.THIS_VERSION)'" 2>/dev/null | tail -1)
cv=$(docker image inspect nipar44/predbat_addon:latest -f '{{index .Config.Labels "org.opencontainers.image.version"}}' 2>/dev/null || true)
iv=${iv#v}; cv=${cv#v}; test -n "$iv"; test -n "$cv"
python3 - "$iv" "$cv" "$current" "$candidate" <<'PY'
import json,sys
iv,cv,old,new=sys.argv[1:]
pre={k:"PASS" for k in ("installed_candidate_versions","container_health_start_time","git_alignment","systemd_units","ha_api","predbat_status","energy_telemetry","predbat_sanity","power_down_assurance","mqtt","backup","rollback_plan")}
print("MANAGED_UPDATE_OBSERVATION="+json.dumps({"target":"predbat","installed_version":iv,"installed_digest":old,"releases":[{"version":cv,"digest":new,"source":"https://github.com/springfall2008/batpred/releases","release_notes":""}],"pre_update":pre,"rollback_safe":True},separators=(",",":")))
PY
