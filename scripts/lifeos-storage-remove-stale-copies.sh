#!/usr/bin/env bash
# Remove only the two SSD copies proven inactive by the 2026-10-16 read-only audit.
# This script is intentionally fixed-path and refuses to proceed if mount/runtime
# evidence differs from the audited state.
set -Eeuo pipefail

SSD=/mnt/docker-data
EXPECTED_UUID=a53fd6a0-c498-4b76-a496-0e5d9233447f
CANDIDATES=(
  /mnt/docker-data/pre_day7_backup
  /mnt/docker-data/host-data/opt-stacks
)

fail() { echo "RESULT=FAIL"; echo "ERROR=$*"; exit 1; }
require() { "$@" || fail "preflight_failed:$*"; }

echo "UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "OPERATION=remove-two-proven-stale-ssd-copies"

mounted_uuid=$(findmnt -n -o UUID -T "$SSD" 2>/dev/null || true)
mounted_target=$(findmnt -n -o TARGET -T "$SSD" 2>/dev/null || true)
[[ "$mounted_uuid" == "$EXPECTED_UUID" ]] || fail "ssd_uuid_mismatch:$mounted_uuid"
[[ "$mounted_target" == "$SSD" ]] || fail "ssd_mountpoint_not_exact:$mounted_target"

docker_root=$(docker info --format '{{.DockerRootDir}}' 2>/dev/null || true)
[[ "$docker_root" == "$SSD" ]] || fail "docker_root_changed:$docker_root"

ssd_dev=$(stat -c '%d' "$SSD") || fail "ssd_stat_failed"
for p in "${CANDIDATES[@]}"; do
  [[ "$p" == "$SSD/"* ]] || fail "unsafe_candidate_path:$p"
  [[ -d "$p" && ! -L "$p" ]] || fail "candidate_missing_or_symlink:$p"
  [[ "$(stat -c '%d' "$p")" == "$ssd_dev" ]] || fail "candidate_not_on_ssd:$p"
  nested=$(findmnt -rn -o TARGET | awk -v p="$p" '$0 == p || index($0,p"/") == 1')
  [[ -z "$nested" ]] || fail "candidate_mount_detected:$p:$nested"
done

# Check every Docker mount source, including stopped containers.
container_ids=$(docker ps -aq)
if [[ -n "$container_ids" ]]; then
  if ! docker inspect $container_ids | python3 -c '
import json, sys
candidates=sys.argv[1:]
try:
    containers=json.load(sys.stdin)
except Exception:
    print("ERROR=docker_inspect_unreadable")
    raise SystemExit(2)
for container in containers:
    for mount in container.get("Mounts", []):
        source=mount.get("Source", "")
        if any(source == p or source.startswith(p + "/") for p in candidates):
            print("ERROR=container_mount_reference:" + source)
            raise SystemExit(3)
print("DOCKER_CANDIDATE_MOUNTS=NONE")
' "${CANDIDATES[@]}"; then
    fail "docker_mount_check_failed"
  fi
else
  echo "DOCKER_CANDIDATE_MOUNTS=NONE"
fi

if python3 - "${CANDIDATES[@]}" <<'PY'
import glob, os, sys
targets=[os.path.realpath(p) for p in sys.argv[1:]]
found=[]
for proc in glob.glob('/proc/[0-9]*'):
    try:
        pid=proc.rsplit('/',1)[-1]
        name=open(proc+'/comm', encoding='utf-8', errors='replace').read().strip()
        fds=glob.glob(proc+'/fd/*')
    except OSError:
        continue
    for fd in fds:
        try: link=os.readlink(fd)
        except OSError: continue
        if any(link == p or link.startswith(p+'/') for p in targets):
            found.append((pid,name,link))
            if len(found) >= 100: break
    if len(found) >= 100: break
for pid,name,path in found: print(f'OPEN_FD pid={pid} comm={name} path={path}')
print(f'OPEN_FD_MATCH_COUNT={len(found)}')
raise SystemExit(1 if found else 0)
PY
then
  :
else
  fail "candidate_open_file_detected"
fi

# Recheck host service, Docker, containerd, compose, and automation references.
# Use Debian's standard grep without following broken unit symlinks. Scan both
# systemd unit target directories as well as /etc's drop-ins and references.
GREP=/usr/bin/grep
[[ -x "$GREP" ]] || fail "reference_scan_tool_missing:$GREP"
for root in /etc/systemd /lib/systemd/system /usr/lib/systemd/system /etc/docker /etc/containerd /opt/stacks /home/joshan/automation /home/joshan/opt; do
  [[ -e "$root" ]] || continue
  set +e
  matches=$("$GREP" -r -n -I -E --exclude-dir=.git --exclude-dir=logs --exclude='*.log' \
      '(/mnt/docker-data/pre_day7_backup|/mnt/docker-data/host-data/opt-stacks|pre_day7_backup|host-data/opt-stacks)' "$root" 2>&1)
  rc=$?
  set -e
  if [[ "$rc" -eq 0 ]]; then
    printf '%s\\n' "$matches"
    fail "candidate_reference_detected:$root"
  elif [[ "$rc" -ne 1 ]]; then
    fail "reference_scan_failed:$root:$matches"
  fi
done
echo "RUNTIME_REFERENCES=NONE"

echo "--- before ---"
df -hT / "$SSD"
for p in "${CANDIDATES[@]}"; do
  du -sx --block-size=1 "$p"
done

# Remove only the preflighted directory entries; never touch Docker's current
# root, volumes, or any other path.
for p in "${CANDIDATES[@]}"; do
  rm -rf --one-file-system -- "$p"
  [[ ! -e "$p" && ! -L "$p" ]] || fail "candidate_remains:$p"
  echo "REMOVED=$p"
done

echo "--- after ---"
df -hT / "$SSD"
echo "RESULT=PASS"
