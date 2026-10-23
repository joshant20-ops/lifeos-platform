#!/usr/bin/env bash
# Fixed read-only audit of Pi storage topology, migration state, and runtime.
# Every probe is bounded/best-effort so an inactive Docker daemon cannot hide
# later safety evidence. No command in this script mutates host state.
set -u -o pipefail

SSD=/mnt/docker-data
STACK=/opt/stacks
SSD_STACK=/mnt/docker-data/opt-stacks
ROLLBACK=/opt/stacks.sd-rollback-20261017
ROLLBACK_ARCHIVE=/mnt/docker-data/rollback/opt-stacks-pre-migration
STAGE_MARKER=/mnt/docker-data/.lifeos-opt-stacks-stage
PARTIAL_MARKER=/mnt/docker-data/.lifeos-opt-stacks-stage.partial
MIGRATION_STATE=/var/lib/lifeos-storage-migration
EXPECTED_UUID=a53fd6a0-c498-4b76-a496-0e5d9233447f
DOCKER_READY=NO

section() { printf '\n--- %s ---\n' "$1"; }
probe_state() {
  local unit="$1" active enabled
  active=$(systemctl is-active "$unit" 2>/dev/null || true)
  enabled=$(systemctl is-enabled "$unit" 2>/dev/null || true)
  printf 'UNIT_%s_ACTIVE=%s\n' "${unit//[^A-Za-z0-9]/_}" "${active:-unknown}"
  printf 'UNIT_%s_ENABLED=%s\n' "${unit//[^A-Za-z0-9]/_}" "${enabled:-unknown}"
}
path_state() {
  local label="$1" path="$2"
  if [[ -e "$path" ]]; then
    printf '%s=PRESENT\n' "$label"
    timeout 20 du -sx --block-size=1 "$path" 2>/dev/null | awk -v k="$label" '{print k "_BYTES=" $1}' || printf '%s_BYTES=UNKNOWN\n' "$label"
    stat -c "${label}_MODE=%a ${label}_OWNER=%U:%G ${label}_MTIME=%y" "$path" 2>/dev/null || true
  else
    printf '%s=ABSENT\n' "$label"
  fi
}

printf 'UTC=%s\nOPERATION=storage-audit-pi-state\nEXPECTED_SSD_UUID=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$EXPECTED_UUID"

section 'filesystem and UUIDs'
for path in / "$SSD" "$STACK" "$SSD_STACK" "$ROLLBACK"; do
  findmnt -n -o TARGET,SOURCE,FSTYPE,UUID,OPTIONS -T "$path" 2>/dev/null || printf 'FINDMNT_%s=UNAVAILABLE\n' "${path//\//_}"
done
df -hT / "$SSD" "$STACK" 2>&1 || true
lsblk -o NAME,TYPE,FSTYPE,UUID,MOUNTPOINTS 2>/dev/null || true

section 'fstab migration entries (credentials redacted)'
python3 - <<'PY'
from pathlib import Path
wanted = {"/mnt/docker-data", "/mnt/docker-data/opt-stacks", "/opt/stacks"}
try:
    lines = Path('/etc/fstab').read_text(errors='replace').splitlines()
except OSError:
    print('FSTAB_READ=UNAVAILABLE')
else:
    count = 0
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        cols = line.split()
        if len(cols) < 4 or cols[1].replace('\\040', ' ') not in wanted:
            continue
        opts = []
        for item in cols[3].split(','):
            key, sep, value = item.partition('=')
            opts.append(key + ('=<redacted>' if sep and key.lower() in {'password','passwd','credentials','username','user'} else (sep + value if sep else '')))
        print('FSTAB=' + ' '.join((cols[0], cols[1], cols[2], ','.join(opts))))
        count += 1
    print(f'FSTAB_MIGRATION_ENTRY_COUNT={count}')
PY

section 'docker and containerd unit state/dependencies'
probe_state docker.service
probe_state containerd.service
systemctl show docker.service containerd.service -p Id -p ActiveState -p SubState -p Requires -p Wants -p After -p BindsTo -p FragmentPath 2>/dev/null | sed -E 's#(/[^ ]*(docker|containerd)[^ ]*)#<path-redacted>#g' || true
for dropin in /etc/systemd/system/docker.service.d/*.conf; do
  [[ -f "$dropin" ]] || continue
  printf 'DOCKER_DROPIN_PRESENT=%s\n' "$(basename "$dropin")"
  sha256sum "$dropin" | awk '{print "DOCKER_DROPIN_SHA256=" $1}'
  grep -E '^(RequiresMountsFor|BindsTo|After|Requires|ExecStartPre)=' "$dropin" 2>/dev/null | sed -E 's#(ExecStartPre=).*#\1<present>#' || true
done
guard=/usr/local/sbin/lifeos-require-opt-stacks-ssd
if [[ -f "$guard" && ! -L "$guard" ]]; then
  echo 'SSD_GUARD=PRESENT'
  sha256sum "$guard" | awk '{print "SSD_GUARD_SHA256=" $1}'
  for token in "$EXPECTED_UUID" '/opt/stacks' '/mnt/docker-data/opt-stacks'; do
    if grep -Fq -- "$token" "$guard"; then printf 'SSD_GUARD_HAS_EXPECTED_TOKEN=YES\n'; else printf 'SSD_GUARD_HAS_EXPECTED_TOKEN=NO\n'; fi
  done
else
  echo 'SSD_GUARD=ABSENT_OR_UNSAFE'
fi

section 'docker runtime (non-fatal if unavailable)'
if root=$(docker info --format '{{.DockerRootDir}}' 2>/dev/null); then
  DOCKER_READY=YES
  printf 'DOCKER_STATE=AVAILABLE\nDOCKER_ROOT=%s\n' "${root:-UNKNOWN}"
  docker ps --format 'RUNNING_CONTAINER={{.Names}} STATUS={{.Status}}' 2>/dev/null || echo 'DOCKER_PS_RUNNING=UNAVAILABLE'
  docker ps -a --format 'ALL_CONTAINER={{.Names}} STATUS={{.Status}}' 2>/dev/null || echo 'DOCKER_PS_ALL=UNAVAILABLE'
  docker compose ls --all --format json 2>/dev/null | python3 -c '
import json,sys
try: rows=json.load(sys.stdin)
except Exception: print("COMPOSE_PROJECTS=UNAVAILABLE"); raise SystemExit
for row in rows:
 print("COMPOSE_PROJECT=" + json.dumps({k:row.get(k) for k in ("Name","Status","ConfigFiles")},sort_keys=True))
' || true
  ids=$(docker ps -aq 2>/dev/null || true)
  if [[ -n "$ids" ]]; then
    docker inspect $ids 2>/dev/null | python3 -c '
import json,sys
try: rows=json.load(sys.stdin)
except Exception: print("DOCKER_INSPECT=UNAVAILABLE"); raise SystemExit
for c in rows:
 s=c.get("State") or {}; labels=(c.get("Config") or {}).get("Labels") or {}
 n=(c.get("Name") or "").lstrip("/")
 h=((s.get("Health") or {}).get("Status") or "no-healthcheck")
 print("CONTAINER=" + json.dumps({"name":n,"state":s.get("Status"),"health":h,"compose_project":labels.get("com.docker.compose.project"),"compose_workdir":labels.get("com.docker.compose.project.working_dir"),"compose_files":labels.get("com.docker.compose.project.config_files")},sort_keys=True))
 for m in c.get("Mounts",[]):
  print("CONTAINER_MOUNT=" + json.dumps({k:m.get(k) for k in ("Type","Source","Destination","RW")},sort_keys=True))
' || echo 'DOCKER_INSPECT=UNAVAILABLE'
  else
    echo 'CONTAINER_COUNT=0'
  fi
else
  echo 'DOCKER_STATE=UNAVAILABLE'
  echo 'DOCKER_ROOT=UNAVAILABLE'
  echo 'CONTAINER_INVENTORY=UNAVAILABLE_DAEMON_STOPPED'
  echo 'COMPOSE_PROJECT_INVENTORY=UNAVAILABLE_DAEMON_STOPPED'
fi
section 'migration paths and rollback state'
path_state ACTIVE_STACK "$STACK"
path_state SSD_STACK "$SSD_STACK"
path_state SD_ROLLBACK "$ROLLBACK"
path_state SSD_ROLLBACK_ARCHIVE "$ROLLBACK_ARCHIVE"
path_state MIGRATION_STATE "$MIGRATION_STATE"
if [[ -d "$MIGRATION_STATE" ]]; then
  find "$MIGRATION_STATE" -maxdepth 2 -type f -printf 'MIGRATION_STATE_FILE=%P bytes=%s mtime=%TY-%Tm-%TdT%TH:%TM:%TS\n' 2>/dev/null | sort || true
fi
if [[ -d "$ROLLBACK" ]]; then
  find "$ROLLBACK" -mindepth 1 -maxdepth 1 -printf 'ROLLBACK_TOP_LEVEL=%f type=%y\n' 2>/dev/null | sort || true
fi
for marker in "$STAGE_MARKER" "$PARTIAL_MARKER" "$MIGRATION_STATE/active-manifest" "$MIGRATION_STATE/boot-validation.pass"; do
  if [[ -f "$marker" && ! -L "$marker" ]]; then printf 'MIGRATION_MARKER=%s PRESENT bytes=%s\n' "${marker##*/}" "$(stat -c %s "$marker" 2>/dev/null || echo UNKNOWN)"; else printf 'MIGRATION_MARKER=%s ABSENT\n' "${marker##*/}"; fi
done
if [[ -f "$MIGRATION_STATE/active-containers.before" && "$DOCKER_READY" == YES ]]; then
  while IFS= read -r id; do
    [[ -n "$id" ]] || continue
    detail=$(docker inspect --format '{{.Name}} {{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' "$id" 2>/dev/null || true)
    if [[ -n "$detail" ]]; then printf 'PRE_CUTOVER_CONTAINER=%s\n' "${detail#/}"; else echo 'PRE_CUTOVER_CONTAINER=NOT_FOUND'; fi
  done < "$MIGRATION_STATE/active-containers.before"
else
  echo 'PRE_CUTOVER_CONTAINER_BASELINE=UNAVAILABLE'
fi


section 'read-only SD underlay metadata (live filesystem; not backup acceptance)'
python3 - <<'PY'
import re, shutil, subprocess
tool = shutil.which('debugfs')
try:
    fields = subprocess.check_output(
        ['findmnt', '-n', '-o', 'SOURCE,UUID,FSTYPE', '-T', '/'],
        text=True, timeout=5).split()
except (OSError, subprocess.SubprocessError):
    fields = []
if (not tool or len(fields) != 3 or fields[0] != '/dev/mmcblk0p2'
        or fields[1] != 'e20b40e9-a03b-4e15-b170-f527cf96d5e5' or fields[2] != 'ext4'):
    print('SD_UNDERLAY_PROBE=UNAVAILABLE_OR_UNEXPECTED_ROOT')
else:
    # debugfs defaults to read-only. Never use -w or read file contents.
    # The live filesystem can change during this metadata-only observation.
    for label, path in (
        ('SOURCE', '/opt/stacks'),
        ('SOURCE_HA_MANIFEST', '/opt/stacks/homeassistant/docker-compose.yml'),
        ('ROLLBACK', '/opt/stacks.sd-rollback-20261017'),
    ):
        try:
            result = subprocess.run([tool, '-R', 'stat ' + path, fields[0]],
                capture_output=True, text=True, timeout=10, check=False)
            match = re.search(r'Inode:\s*(\d+)\s+Type:\s*(directory|regular)', result.stdout)
            if match and result.returncode == 0:
                print('SD_UNDERLAY_' + label + '=PRESENT_' + match.group(2).upper())
            elif 'File not found' in result.stderr:
                print('SD_UNDERLAY_' + label + '=NOT_FOUND')
            else:
                print('SD_UNDERLAY_' + label + '=UNKNOWN')
        except (OSError, subprocess.SubprocessError):
            print('SD_UNDERLAY_' + label + '=UNKNOWN')
    print('SD_UNDERLAY_PROBE=READ_ONLY_METADATA_NOT_RECOVERY_PROOF')
PY

section 'process references to active, staged, or rollback stack paths'
python3 - <<'PY'
import os
needles = (b'/opt/stacks', b'/mnt/docker-data/opt-stacks')
count = 0
for entry in os.scandir('/proc'):
    if not entry.name.isdigit(): continue
    pid = entry.name
    try:
        comm = open(f'/proc/{pid}/comm', 'rb').read(128).strip().decode(errors='replace')
    except OSError: comm = 'unknown'
    refs = []
    for label, path in [('cwd', f'/proc/{pid}/cwd'), ('root', f'/proc/{pid}/root')]:
        try:
            target = os.readlink(path)
            if any(n.decode() in target for n in needles): refs.append(label)
        except OSError: pass
    try:
        for fd in os.scandir(f'/proc/{pid}/fd'):
            try:
                target = os.readlink(fd.path)
                if any(n.decode() in target for n in needles): refs.append('fd'); break
            except OSError: pass
    except OSError: pass
    if refs:
        print(f'PROCESS_PATH_REFERENCE=pid:{pid} comm:{comm} via:{",".join(sorted(set(refs)))}')
        count += 1
print(f'PROCESS_PATH_REFERENCE_COUNT={count}')
PY

section 'running services, failed services, timers, runner'
systemctl --failed --no-legend --plain 2>/dev/null | sed -E 's#(/[^ ]+)#<path-redacted>#g' || true
systemctl list-units --type=service --state=running --no-legend --plain 2>/dev/null | awk '{print "RUNNING_SERVICE=" $1 " " $3 " " $4}' || true
systemctl list-timers --all --no-legend --plain 2>/dev/null | awk '{print "TIMER=" $1 " " $2 " " $3 " " $4 " " $5 " " $6}' || true
systemctl list-units --all --type=service --no-legend --plain 2>/dev/null | grep -Ei 'actions\.runner|runner' | awk '{print "RUNNER_UNIT=" $1 " " $3 " " $4}' || true

section 'canonical stack manifests and storage footprint'
find "$STACK" -maxdepth 4 -type f \( -name docker-compose.yml -o -name compose.yml \) -print 2>/dev/null | sort | sed 's#^#ACTIVE_STACK_MANIFEST=#' || true
for p in /home/joshan /home/joshan/lifeos-platform /opt/actions-runner-lifeos /opt/actions-runner-lifeos/_work /var/mail/joshan /var/swap; do
  [[ -e "$p" ]] || continue
  printf 'FOOTPRINT_PATH=%s ' "$p"
  findmnt -n -o SOURCE,UUID,TARGET -T "$p" 2>/dev/null | tr '\n' ' '
  timeout 20 du -sx --block-size=1 "$p" 2>/dev/null | awk '{print "bytes=" $1}' || echo 'bytes=UNKNOWN'
done
if command -v swapon >/dev/null 2>&1; then swapon --show --bytes 2>/dev/null || true; fi
if [[ -f /var/mail/joshan ]]; then
  printf 'MAIL_SPOOL_BYTES=%s\n' "$(stat -c %s /var/mail/joshan 2>/dev/null || echo UNKNOWN)"
  printf 'MAIL_SPOOL_MTIME=%s\n' "$(stat -c %y /var/mail/joshan 2>/dev/null || echo UNKNOWN)"
  printf 'MAIL_SPOOL_MESSAGE_COUNT=%s\n' "$(grep -c '^From ' /var/mail/joshan 2>/dev/null || true)"
fi

echo 'AUDIT_MUTATIONS=NONE'
echo 'RESULT=PASS'
