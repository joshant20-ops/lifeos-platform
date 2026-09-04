#!/usr/bin/env bash
set -Eeuo pipefail

readonly PLATFORM=/home/joshan/lifeos-platform
readonly AUDIT=/var/lib/lifeos-control/engineer-deploy-audit/engineer-current-20260904-v3.json

stage(){ printf '\n===== STAGE %s — %s =====\n' "$1" "$2"; }
pass(){ printf 'STAGE_%s=PASS\n' "$1"; }
sha(){ sha256sum "$1" | awk '{print $1}'; }

[[ $(id -u) -eq 0 ]] || { echo 'FINAL_STATUS=FAIL'; echo 'FAIL_REASON=must_run_as_root'; exit 1; }

stage 1 'READ-ONLY STATE AND DEPLOYMENT EVIDENCE'
HEAD="$(git -C "$PLATFORM" rev-parse HEAD 2>/dev/null || true)"
printf 'SOURCE_COMMIT=%s\n' "$HEAD"
printf 'GIT_STATUS=%q\n' "$(git -C "$PLATFORM" status --porcelain --untracked-files=no 2>/dev/null || true)"
for p in /usr/local/libexec/lifeos-autonomous-agent /usr/local/libexec/target_identity.py /usr/local/libexec/lifeos-engineer; do
  if [[ -e "$p" ]]; then
    printf 'LIVE_FILE=%s UID=%s GID=%s MODE=%s SHA256=%s\n' "$p" "$(stat -c %u "$p")" "$(stat -c %g "$p")" "$(stat -c %a "$p")" "$(sha "$p")"
  else
    printf 'LIVE_FILE=%s STATE=missing\n' "$p"
  fi
done
python3 - "$AUDIT" <<'PY'
import json, pathlib, sys
p=pathlib.Path(sys.argv[1])
if not p.exists():
    print('DEPLOY_AUDIT=missing')
else:
    d=json.loads(p.read_text())
    for k in ('status','deployment_result','rollback_result','failure','source_commit','target','backup_location','finished_at'):
        print(f'AUDIT_{k.upper()}={d.get(k)}')
PY
python3 - <<'PY'
from pathlib import Path
p=Path('/usr/local/libexec/lifeos-engineer')
try:
    compile(p.read_text(), str(p), 'exec')
    print('ENGINEER_PYTHON_COMPILE=PASS')
except Exception as exc:
    print('ENGINEER_PYTHON_COMPILE=FAIL:'+type(exc).__name__+':'+str(exc)[:300])
PY
pass 1

stage 2 'SYSTEMD AND LISTENER STATE'
for unit in lifeos-autonomous-agent.service lifeos-engineer.service; do
  echo "UNIT=$unit"
  systemctl show "$unit" --no-pager \
    --property=LoadState,ActiveState,SubState,Result,ExecMainCode,ExecMainStatus,MainPID,NRestarts,FragmentPath,User,Group,ExecStart 2>&1 || true
done
printf '%s\n' '--- LISTENERS 8790/8793 ---'
ss -ltnp 2>&1 | awk 'NR==1 || /:8790[[:space:]]/ || /:8793[[:space:]]/' || true
pass 2

stage 3 'SEPARATE HTTP AND DEPENDENCY HEALTH'
python3 - <<'PY'
import json, urllib.error, urllib.request
checks=(
 ('AGENT_HEALTH','http://127.0.0.1:8790/health'),
 ('ENGINEER_HEALTH','http://127.0.0.1:8793/health'),
 ('ENGINEER_MODELS','http://127.0.0.1:8793/v1/models'),
 ('OLLAMA_TAGS','http://192.168.0.201:11434/api/tags'),
)
for name,url in checks:
    try:
        with urllib.request.urlopen(url,timeout=6) as r:
            body=r.read(2048).decode('utf-8','replace').replace('\n',' ')[:1800]
            print(f'{name}=HTTP_{r.status} BODY={body}')
    except urllib.error.HTTPError as e:
        body=e.read(2048).decode('utf-8','replace').replace('\n',' ')[:1800]
        print(f'{name}=HTTP_{e.code} BODY={body}')
    except Exception as e:
        print(f'{name}=ERROR_{type(e).__name__} DETAIL={str(e)[:500]}')
PY
pass 3

stage 4 'BOUNDED STARTUP/FAILURE LOGS'
for unit in lifeos-autonomous-agent.service lifeos-engineer.service; do
  echo "--- JOURNAL=$unit ---"
  journalctl -u "$unit" -b -n 50 --no-pager --output=short-iso 2>&1 \
    | grep -E 'Started|Starting|Stopped|Stopping|Failed|failed|error|Error|ERROR|Traceback|listening|exited|status=|Address already in use|Permission denied|No such file|engineer .* (GET|POST)' \
    | tail -n 50 || true
done
pass 4

echo 'FINAL_STATUS=PASS'
echo 'MUTATION_PERFORMED=NO'
echo 'NEXT_REQUIRED=repair_engineer_8793_from_live_evidence'
