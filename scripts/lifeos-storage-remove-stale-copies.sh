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

# Prove candidates are neither a configured fstab source/target nor a live mount source/target.
if /usr/bin/grep -n -E -- '(/mnt/docker-data/pre_day7_backup|/mnt/docker-data/host-data/opt-stacks|pre_day7_backup|host-data/opt-stacks)' /etc/fstab 2>/dev/null; then
  fail "candidate_fstab_reference"
fi
while IFS= read -r line; do
  source=${line%% *}
  target=${line#* }
  for p in "${CANDIDATES[@]}"; do
    [[ "$source" == "$p" || "$source" == "$p/"* || "$target" == "$p" || "$target" == "$p/"* ]] && fail "candidate_mount_source_or_target:$line"
  done
done < <(findmnt -rn -o SOURCE,TARGET)

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
    labels=container.get("Config", {}).get("Labels") or {}
    config_files=labels.get("com.docker.compose.project.config_files", "")
    working_dir=labels.get("com.docker.compose.project.working_dir", "")
    for value in [config_files, working_dir]:
        if any(value == p or value.startswith(p + "/") for p in candidates):
            print("ERROR=compose_project_reference:" + value)
            raise SystemExit(4)
print("DOCKER_CANDIDATE_MOUNTS=NONE")
print("DOCKER_COMPOSE_CANDIDATE_PROJECTS=NONE")
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

# Recheck service and source configuration references. Do not scan generated
# automation backups, snapshots, queues, logs, databases, or other runtime data.
# This bounds the scan to text files that can define service paths.
GREP=/usr/bin/grep
FIND=/usr/bin/find
[[ -x "$GREP" && -x "$FIND" ]] || fail "reference_scan_tool_missing"
pattern='(/mnt/docker-data/pre_day7_backup|/mnt/docker-data/host-data/opt-stacks|pre_day7_backup|host-data/opt-stacks)'
HISTORICAL_EVIDENCE=/home/joshan/automation/docker_fleet_auditor/evidence/docker_fleet_evidence_20260602_010106.json
HISTORICAL_EVIDENCE_SHA256=32f07a333acba53c11f85531f031bea9542f18ac4c681034227759679e285190
[[ -f "$HISTORICAL_EVIDENCE" && ! -L "$HISTORICAL_EVIDENCE" ]] || fail "historical_evidence_missing_or_symlink"
actual_evidence_sha=$(sha256sum "$HISTORICAL_EVIDENCE" | awk '{print $1}')
[[ "$actual_evidence_sha" == "$HISTORICAL_EVIDENCE_SHA256" ]] || fail "historical_evidence_hash_mismatch:$actual_evidence_sha"
echo "HISTORICAL_EVIDENCE_SHA256=$actual_evidence_sha"
echo "HISTORICAL_EVIDENCE_CLASS=IMMUTABLE_AUDIT_RECORD"
for root in /etc/fstab /etc/systemd /lib/systemd/system /usr/lib/systemd/system /etc/cron.d /etc/cron.daily /etc/cron.hourly /etc/cron.monthly /etc/cron.weekly /var/spool/cron /etc/docker /etc/containerd /usr/local/sbin /usr/local/bin /opt/stacks /home/joshan/automation /home/joshan/opt /home/joshan/lifeos-platform/homelab/live /home/joshan/lifeos-platform/scripts /home/joshan/lifeos-platform/.github/workflows; do
  [[ -e "$root" ]] || continue
  scan_list=$(mktemp /tmp/lifeos-storage-reference-scan.XXXXXX) || fail "reference_scan_temp_failed:$root"
  trap 'rm -f -- "$scan_list"' EXIT
  if ! "$FIND" -H "$root" \
      -type d \( -name .git -o -name logs -o -name backups -o -name snapshots -o -name queues -o -name data -o -name work -o -name node_modules -o -name .venv -o -name __pycache__ \) -prune -o \
      -type f \( -name '*.sh' -o -name '*.py' -o -name '*.yml' -o -name '*.yaml' -o -name '*.conf' -o -name '*.service' -o -name '*.mount' -o -name '*.timer' -o -name '*.toml' -o -name '*.ini' -o -name '*.env' -o -name '*.md' -o -name '*.json' \) -print0 >"$scan_list"; then
    fail "reference_file_list_failed:$root"
  fi
  while IFS= read -r -d '' file; do
    set +e
    matches=$("$GREP" -n -I -E -- "$pattern" "$file" 2>&1)
    rc=$?
    set -e
    if [[ "$rc" -eq 0 ]]; then
      if [[ "$file" == "$HISTORICAL_EVIDENCE" ]]; then
        echo "HISTORICAL_EVIDENCE_REFERENCES=4"
        echo "HISTORICAL_EVIDENCE_REFERENCE_FILE=$file"
        echo "HISTORICAL_EVIDENCE_REFERENCE_CLASS=IMMUTABLE_HISTORICAL_ONLY"
        continue
      fi
      # The removal/inspection code contains the fixed candidate paths by design;
      # these maintenance scripts are not runtime launch or recovery dependencies.
      case "$file" in
        /home/joshan/lifeos-platform/scripts/lifeos-storage-remove-stale-copies.sh|/home/joshan/lifeos-platform/scripts/lifeos-storage-inspect-backup-evidence.sh)
          echo "MAINTENANCE_CODE_REFERENCE_CLASS=FIXED_GOVERNED_OPERATION"
          continue
          ;;
      esac
      echo "REFERENCE_ROOT=$root"
      echo "REFERENCE_FILE=$file"
      printf '%s\n' "$matches"
      fail "candidate_reference_detected:$root:$file"
    elif [[ "$rc" -ne 1 ]]; then
      fail "reference_scan_failed:$root:$matches"
    fi
  done <"$scan_list"
  rm -f -- "$scan_list"
  trap - EXIT
done
echo "RUNTIME_REFERENCES=NONE"

echo "--- before ---"
df -hT / "$SSD"
echo "DOCKER_SERVICES_BEFORE_BEGIN"
docker ps --format 'table {{.Names}}\t{{.Status}}'
echo "DOCKER_SERVICES_BEFORE_END"
echo "SYSTEMD_FAILED_BEFORE=$(systemctl --failed --no-legend --plain | wc -l)"
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
echo "DOCKER_SERVICES_AFTER_BEGIN"
docker ps --format 'table {{.Names}}\t{{.Status}}'
echo "DOCKER_SERVICES_AFTER_END"
echo "SYSTEMD_FAILED_AFTER=$(systemctl --failed --no-legend --plain | wc -l)"
echo "RESULT=PASS"
