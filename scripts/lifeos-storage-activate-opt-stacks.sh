#!/usr/bin/env bash
# Final writer-stop, sync, bind-mount cutover and live validation for /opt/stacks.
# All paths are fixed; the source is retained on SD for the reboot/rollback gate.
set -Eeuo pipefail

SSD=/mnt/docker-data
SOURCE=/opt/stacks
DEST=/mnt/docker-data/opt-stacks
ROLLBACK=/opt/stacks.sd-rollback-20261017
EXPECTED_UUID=a53fd6a0-c498-4b76-a496-0e5d9233447f
STATE=/var/lib/lifeos-storage-migration
FSTAB=/etc/fstab
DROPIN=/etc/systemd/system/docker.service.d/20-lifeos-storage.conf
GUARD=/usr/local/sbin/lifeos-require-opt-stacks-ssd
rollback_needed=0
original_containers=()

fail(){ echo "RESULT=FAIL"; echo "ERROR=$*"; return 1; }
rollback_cutover(){
  trap - ERR
  set +e
  echo "AUTOMATIC_ROLLBACK=START"
  systemctl stop docker.service
  if mountpoint -q "$SOURCE"; then umount "$SOURCE"; fi
  if [[ -f "$STATE/fstab.before" ]]; then cp -a "$STATE/fstab.before" "$FSTAB"; fi
  if [[ -f "$STATE/docker-dropin.before" ]]; then
    install -D -o root -g root -m 0644 "$STATE/docker-dropin.before" "$DROPIN"
  else
    rm -f "$DROPIN"
  fi
  if [[ -f "$STATE/guard.before" ]]; then
    install -D -o root -g root -m 0755 "$STATE/guard.before" "$GUARD"
  else
    rm -f "$GUARD"
  fi
  systemctl daemon-reload
  if [[ -d "$ROLLBACK" && ! -e "$SOURCE" ]]; then mv -- "$ROLLBACK" "$SOURCE"; fi
  if [[ -d "$SOURCE" ]]; then chmod 0755 "$SOURCE"; fi
  if [[ "$(findmnt -n -o UUID -T "$SSD" 2>/dev/null || true)" == "$EXPECTED_UUID" ]]; then
    systemctl start docker.service
    for id in "${original_containers[@]}"; do docker start "$id" >/dev/null 2>&1 || true; done
    echo "AUTOMATIC_ROLLBACK_DOCKER=STARTED"
  else
    echo "AUTOMATIC_ROLLBACK_DOCKER=SSD_UNAVAILABLE"
  fi
  echo "AUTOMATIC_ROLLBACK=FINISHED"
}
on_error(){
  rc=$?
  line=${1:-unknown}
  trap - ERR
  echo "FAIL_LINE=$line"
  if (( rollback_needed )); then rollback_cutover; fi
  echo "RESULT=FAIL"
  exit "$rc"
}
trap 'on_error "$LINENO"' ERR

echo "UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "OPERATION=storage-activate-opt-stacks"

[[ "$(findmnt -n -o UUID -T "$SSD" 2>/dev/null || true)" == "$EXPECTED_UUID" ]] || fail "ssd_uuid_mismatch"
[[ "$(findmnt -n -o TARGET -T "$SSD" 2>/dev/null || true)" == "$SSD" ]] || fail "ssd_mountpoint_not_exact"
[[ "$(docker info --format '{{.DockerRootDir}}')" == "$SSD" ]] || fail "docker_root_changed"
[[ -d "$SOURCE" && ! -L "$SOURCE" ]] || fail "source_missing_or_symlink"
[[ -d "$DEST" && ! -L "$DEST" ]] || fail "stage_destination_missing"
[[ ! -e "$ROLLBACK" && ! -L "$ROLLBACK" ]] || fail "rollback_path_already_exists"
STAGE_MARKER=/mnt/docker-data/.lifeos-opt-stacks-stage
PARTIAL_MARKER=/mnt/docker-data/.lifeos-opt-stacks-stage.partial
[[ -f "$STAGE_MARKER" && ! -L "$STAGE_MARKER" ]] || fail "stage_marker_missing"
grep -Fxq "SOURCE=$SOURCE" "$STAGE_MARKER" || fail "stage_marker_source_mismatch"
grep -Fxq "EXPECTED_UUID=$EXPECTED_UUID" "$STAGE_MARKER" || fail "stage_marker_uuid_mismatch"
grep -Fxq "STAGE_STATUS=COMPLETE" "$STAGE_MARKER" || fail "stage_marker_not_complete"
[[ ! -e "$PARTIAL_MARKER" && ! -L "$PARTIAL_MARKER" ]] || fail "stage_in_progress_marker_present"
[[ "$(stat -c '%d' "$DEST")" == "$(stat -c '%d' "$SSD")" ]] || fail "stage_not_on_ssd"
[[ "$(findmnt -n -o TARGET -T "$SOURCE")" == "/" ]] || fail "source_no_longer_on_root"

mkdir -p -m 0700 "$STATE"
[[ ! -e "$STATE/fstab.before" ]] || fail "migration_state_exists"
cp -a "$FSTAB" "$STATE/fstab.before"
if [[ -e "$DROPIN" ]]; then cp -a "$DROPIN" "$STATE/docker-dropin.before"; fi
if [[ -e "$GUARD" ]]; then cp -a "$GUARD" "$STATE/guard.before"; fi

echo "--- before ---"
df -hT / "$SSD"
du -sx --block-size=1 "$SOURCE" "$DEST"
docker ps --format 'CONTAINER={{.Names}} STATUS={{.Status}}'
systemctl --failed --no-legend --plain

mapfile -t original_containers < <(docker ps -q)
printf '%s\n' "${original_containers[@]}" >"$STATE/active-containers.before"
rollback_needed=1

echo "STOPPING_ALL_DOCKER_CONTAINERS=${#original_containers[@]}"
if (( ${#original_containers[@]} )); then
  docker stop --time 90 "${original_containers[@]}"
fi

# Stop any active host service whose configured command or working directory
# names the source. Do not print unit command/environment contents.
: >"$STATE/active-host-units.before"
while read -r unit _; do
  [[ -n "$unit" && "$unit" != docker.service ]] || continue
  props=$(systemctl show "$unit" -p ExecStart -p WorkingDirectory -p EnvironmentFiles --value 2>/dev/null || true)
  if [[ "$props" == *"$SOURCE"* ]]; then
    echo "STOP_HOST_SERVICE=$unit"
    echo "$unit" >>"$STATE/active-host-units.before"
    systemctl stop "$unit"
  fi
done < <(systemctl list-units --type=service --state=running --no-legend --plain)

# Prove no process still has a source file open or has its cwd/root there.
python3 - "$SOURCE" <<'PY'
import glob, os, sys
root=os.path.realpath(sys.argv[1])
found=[]
for proc in glob.glob('/proc/[0-9]*'):
    pid=proc.rsplit('/',1)[-1]
    try:
        name=open(proc+'/comm',encoding='utf-8',errors='replace').read().strip()
    except OSError:
        continue
    for entry in ('cwd','root'):
        try: path=os.path.realpath(os.readlink(proc+'/'+entry))
        except OSError: continue
        if path == root or path.startswith(root+'/'):
            found.append((pid,name,entry,path))
    for fd in glob.glob(proc+'/fd/*'):
        try: path=os.path.realpath(os.readlink(fd))
        except OSError: continue
        if path == root or path.startswith(root+'/'):
            found.append((pid,name,'fd',path))
            break
for pid,name,kind,path in found[:50]:
    print(f'ACTIVE_SOURCE_REFERENCE pid={pid} comm={name} kind={kind} path={path}')
print(f'ACTIVE_SOURCE_REFERENCE_COUNT={len(found)}')
raise SystemExit(1 if found else 0)
PY

echo "WRITERS_STOPPED=PASS"
rsync -aHAXx --numeric-ids --delete --info=stats2 "$SOURCE/" "$DEST/"
set +e
delta=$(rsync -aHAXxnc --numeric-ids --delete --dry-run --itemize-changes "$SOURCE/" "$DEST/" 2>&1)
delta_rc=$?
set -e
[[ "$delta_rc" -eq 0 ]] || fail "final_checksum_scan_failed:$delta_rc"
[[ -z "$delta" ]] || { printf '%s\n' "$delta" | head -100; fail "source_destination_checksum_mismatch"; }
echo "FINAL_RSYNC_CHECKSUM=PASS"

# Keep the old source in place on the SD until the reboot and boot-ordering gate passes.
mv -- "$SOURCE" "$ROLLBACK"
install -d -o root -g root -m 0555 "$SOURCE"

python3 - "$FSTAB" "$SSD" "$DEST" "$SOURCE" <<'PY'
from pathlib import Path
import sys
path=Path(sys.argv[1]); ssd=sys.argv[2]; dest=sys.argv[3]; target=sys.argv[4]
lines=path.read_text().splitlines()
out=[]
ssd_found=False
for raw in lines:
    stripped=raw.strip()
    if not stripped or stripped.startswith('#'):
        out.append(raw); continue
    cols=stripped.split()
    if len(cols) >= 4 and cols[1] == ssd:
        options=cols[3].split(',')
        if 'nofail' not in options:
            raise SystemExit('SSD fstab entry lost nofail; refusing')
        if not any(o.startswith('x-systemd.device-timeout=') for o in options):
            options.append('x-systemd.device-timeout=10s')
        cols[3]=','.join(options)
        out.append(' '.join(cols))
        ssd_found=True
        continue
    if len(cols) >= 2 and cols[1] == target:
        raise SystemExit('existing /opt/stacks fstab target found; refusing')
    out.append(raw)
if not ssd_found:
    raise SystemExit('SSD fstab source entry missing')
out += [
    '# LIFEOS-SSD-OPT-STACKS-BIND',
    f'{dest} {target} none bind,nofail,x-systemd.requires={ssd} 0 0',
]
path.write_text('\n'.join(out)+'\n')
PY

cat >"$GUARD" <<'SH'
#!/usr/bin/env bash
set -Eeuo pipefail
EXPECTED_UUID=a53fd6a0-c498-4b76-a496-0e5d9233447f
TARGET=/opt/stacks
SSD=/mnt/docker-data
mountpoint -q "$TARGET"
target=$(findmnt -n -o TARGET -T "$TARGET")
uuid=$(findmnt -n -o UUID -T "$TARGET")
ssd_uuid=$(findmnt -n -o UUID -T "$SSD")
[[ "$target" == "$TARGET" && "$uuid" == "$EXPECTED_UUID" && "$ssd_uuid" == "$EXPECTED_UUID" ]]
SH
chown root:root "$GUARD"
chmod 0755 "$GUARD"

ssd_unit=$(systemd-escape --path --suffix=mount "$SSD")
stacks_unit=$(systemd-escape --path --suffix=mount "$SOURCE")
install -d -o root -g root -m 0755 "$(dirname "$DROPIN")"
cat >"$DROPIN" <<EOF
[Unit]
RequiresMountsFor=$SSD/opt-stacks $SOURCE
BindsTo=$ssd_unit $stacks_unit
After=$ssd_unit $stacks_unit

[Service]
ExecStartPre=$GUARD
EOF
chown root:root "$DROPIN"
chmod 0644 "$DROPIN"

systemctl daemon-reload
systemctl start "$stacks_unit"
"$GUARD"
echo "STACKS_MOUNT_UNIT=$stacks_unit"
echo "SSD_MOUNT_UNIT=$ssd_unit"
echo "STACKS_UUID=$(findmnt -n -o UUID -T "$SOURCE")"
echo "STACKS_TARGET=$(findmnt -n -o TARGET -T "$SOURCE")"
grep -qF "$stacks_unit" < <(systemctl show docker.service -p Requires -p BindsTo -p After --value) || fail "docker_missing_stacks_mount_dependency"
grep -qF "$ssd_unit" < <(systemctl show docker.service -p Requires -p BindsTo -p After --value) || fail "docker_missing_ssd_mount_dependency"
systemd-analyze verify docker.service "$stacks_unit" "$ssd_unit"

systemctl restart docker.service
if (( ${#original_containers[@]} )); then
  docker start "${original_containers[@]}"
fi
for container in homeassistant mosquitto adguardhome; do
  for _ in $(seq 1 120); do
    state=$(docker inspect --format '{{.State.Status}}' "$container" 2>/dev/null || true)
    health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container" 2>/dev/null || true)
    [[ "$state" == running && "$health" == healthy ]] && break
    sleep 2
  done
  [[ "$state" == running && "$health" == healthy ]] || fail "required_container_unhealthy:$container:$state:$health"
  echo "SERVICE_HEALTH=$container:$health"
done

# Prove an application container can write to its persistent config bind and
# that the resulting file's device is the SSD device.
docker exec homeassistant sh -ec 'printf storage-test > /config/.lifeos-ssd-write-test'
test_path="$SOURCE/homeassistant/config/.lifeos-ssd-write-test"
[[ "$(stat -c '%d' "$test_path")" == "$(stat -c '%d' "$SSD")" ]] || fail "application_write_not_on_ssd"
rm -f -- "$test_path"
echo "APPLICATION_WRITE=PASS device=$(stat -c '%d' "$SSD")"

systemctl is-active --quiet docker.service
"$GUARD"
echo "DOCKER_ROOT=$(docker info --format '{{.DockerRootDir}}')"
echo "--- after ---"
df -hT / "$SSD"
du -sx --block-size=1 "$SOURCE" "$ROLLBACK"
docker ps --format 'CONTAINER={{.Names}} STATUS={{.Status}}'
systemctl --failed --no-legend --plain

printf 'UUID=%s\nSOURCE=%s\nDEST=%s\nCUTOVER_UTC=%s\n' "$EXPECTED_UUID" "$SOURCE" "$DEST" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"$STATE/active-manifest"
chmod 0600 "$STATE/active-manifest"
rollback_needed=0
trap - ERR
echo "ROLLBACK_SOURCE_RETAINED=$ROLLBACK"
echo "REBOOT_ORDERING_VALIDATION=PENDING"
echo "RESULT=PASS"
