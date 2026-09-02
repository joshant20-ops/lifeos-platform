#!/usr/bin/env bash
set -Eeuo pipefail

readonly TARGET=${LIFEOS_Z97_TARGET:-TowerPC.Tailor}
readonly SELF=governor/runtime_jobs/a56ef2e00b48.sh
readonly EVIDENCE=/tmp/lifeos-a56ef2e00b48-r580-evidence.txt
readonly CANDIDATE=/tmp/lifeos-a56ef2e00b48-r580-production.sh

finish() {
  printf '%s\n' \
    "ISSUE_VALIDITY=$1" "LIFEOS_WORK_STATE=$2" "BARRIER=$3" \
    "NEXT_AUTONOMOUS_ACTION=$4" 'DISCOVERED_ISSUES_JSON_B64=none' \
    "RESULT=$5" "TESTS=$6" "NEXT_RUNTIME_CHECK=$7"
}
fail() {
  local barrier=$1
  printf 'STAGE=%s FAIL\n' "$barrier" >&2
  finish BLOCKED BLOCKED "$barrier" \
    "repair the named read-only diagnostic barrier and rerun $SELF through Watchman" \
    RETRY 'bounded R580 proof did not complete; full remote diagnostics printed above' \
    "bash $SELF"
  exit 1
}
for tool in ssh timeout base64 mktemp; do
  command -v "$tool" >/dev/null || fail "pi5_missing_$tool"
done

tmp=$(mktemp -d)
trap 'rm -rf -- "$tmp"' EXIT
set +e
timeout --signal=TERM --kill-after=15s 900s ssh -T -o BatchMode=yes \
  -o ConnectTimeout=10 -o StrictHostKeyChecking=yes "$TARGET" 'bash -s' \
  >"$tmp/remote" 2>&1 <<'REMOTE'
set -Eeuo pipefail
export LC_ALL=C
stage=initialization
trap 'rc=$?; printf "STAGE=%s FAIL rc=%s line=%s command=%q\n" "$stage" "$rc" "$LINENO" "$BASH_COMMAND" >&2; exit "$rc"' ERR
run() { local duration=$1; shift; timeout --signal=TERM --kill-after=10s "$duration" "$@"; }

stage=relevance
[[ $(uname -m) == x86_64 ]]
[[ $(. /etc/os-release; printf '%s' "$ID:$VERSION_ID") == debian:12 ]]
kernel=$(uname -r)
driver=$(run 15s nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1)
gpu=$(run 15s nvidia-smi --query-gpu=name --format=csv,noheader | head -1)
[[ $gpu == *P106-100* && $driver == 535.* ]]
[[ -d /usr/src/linux-headers-$kernel ]]
command -v dkms >/dev/null
[[ $(modinfo -F vermagic nvidia | head -1) == "$kernel "* ]]
[[ $(modinfo -F license nvidia | head -1) == *NVIDIA* ]]
listen=$(ss -H -ltn 2>/dev/null | awk '$4 ~ /:11434$/ {print $4}' | paste -sd, -)
[[ $listen != *0.0.0.0:* && $listen != *'[::]:'* && $listen != \*:* ]]
rollback=$(find /boot -maxdepth 1 -type f -name 'vmlinuz-*' ! -name "vmlinuz-$kernel" -printf '%f\n' | sort -V | tail -1)
[[ -n $rollback ]]
printf 'STAGE=relevance PASS gpu=%s driver=%s kernel=%s headers=present module=proprietary ollama=%s rollback=%s\n' \
  "$gpu" "$driver" "$kernel" "${listen:-stopped}" "$rollback"

stage=repository_metadata
w=$(mktemp -d)
trap 'rm -rf -- "$w"' EXIT
mkdir -p "$w/etc/apt/sources.list.d" "$w/etc/apt/preferences.d" \
  "$w/state/lists/partial" "$w/cache/archives/partial" "$w/log"
# Snapshot package state as ordinary files in the disposable tree.  Pointing a
# non-root APT process at the live dpkg state still lets APT probe locks and
# auxiliary state below read-only /var/lib paths on some hosts/Watchman units.
# The copies preserve the exact installed and auto/manual package state needed
# for a faithful simulation without giving the diagnostic a writable host path.
cp -- /var/lib/dpkg/status "$w/state/status"
if [[ -r /var/lib/apt/extended_states ]]; then
  cp -- /var/lib/apt/extended_states "$w/state/extended_states"
else
  : >"$w/state/extended_states"
fi
# Seed the disposable lists with the host's current Debian/Proxmox metadata,
# but do not update those sources. Copy only readable, top-level index files:
# an unprivileged diagnostic cannot traverse apt's protected partial directory
# or preserve root ownership with `cp -a`.
find /var/lib/apt/lists -maxdepth 1 -type f -readable \
  -exec cp -- {} "$w/state/lists/" \;
: >"$w/etc/apt/sources.list"
printf '%s\n' 'deb [trusted=yes] https://developer.download.nvidia.com/compute/cuda/repos/debian12/x86_64/ /' >"$w/etc/apt/sources.list.d/lifeos-r580.list"
cat >"$w/etc/apt/preferences.d/lifeos-r580" <<'PINS'
Package: nvidia-* libnvidia-* cuda-* libcuda* xserver-xorg-video-nvidia*
Pin: origin developer.download.nvidia.com
Pin-Priority: 100

Package: *-580 *-580-server
Pin: version 580*
Pin-Priority: 1001

Package: nvidia-* libnvidia-* cuda-* libcuda* xserver-xorg-video-nvidia*
Pin: version 59[05]*
Pin-Priority: -1

Package: nvidia-* libnvidia-* cuda-* libcuda* xserver-xorg-video-nvidia*
Pin: version 6*
Pin-Priority: -1
PINS
o=(-o "Dir::Etc=$w/etc/apt" -o "Dir::State=$w/state" \
   -o "Dir::State::status=$w/state/status" -o "Dir::State::extended_states=$w/state/extended_states" \
   -o "Dir::State::lists=$w/state/lists" -o "Dir::Cache=$w/cache" -o "Dir::Log=$w/log" \
   -o Acquire::Languages=none \
   -o APT::Get::List-Cleanup=0 -o Debug::NoLocking=1 \
   -o "APT::Sandbox::User=$(id -un)")
run 300s apt-get "${o[@]}" update >/dev/null
version=$(apt-cache "${o[@]}" policy nvidia-driver-580 | awk '/Candidate:/ {print $2;exit}')
[[ $version == 580.* ]]
for branch in 590 595 600 610; do
  rejected=$(apt-cache "${o[@]}" policy "nvidia-driver-$branch" | awk '/Candidate:/ {print $2;exit}')
  [[ -z $rejected || $rejected == '(none)' ]]
done
printf 'STAGE=metadata PASS source=NVIDIA_debian12 candidate=%s rejected=R590,R595,R600,R610\n' "$version"

stage=dependency_simulation
mapfile -t old_names < <(dpkg-query -W -f='${binary:Package}\t${Version}\n' 2>/dev/null |
  awk 'tolower($0) ~ /(nvidia|cuda)/ {sub(/:amd64$/, "", $1); print $1}' | sort -u)
[[ ${#old_names[@]} -gt 0 ]]
remove_args=()
for package in "${old_names[@]}"; do remove_args+=("$package-"); done
sim="$w/simulation.txt"
if ! run 300s apt-get "${o[@]}" -s --no-install-recommends install \
  "${remove_args[@]}" "nvidia-driver-580=$version" >"$sim" 2>&1; then
  cat "$sim" >&2
  false
fi
cat "$sim" >"$w/simulation.audit"
grep -q '^Inst nvidia-dkms-580 ' "$sim"
grep -q '^Inst nvidia-kernel-source-580 ' "$sim"
! awk '$1=="Inst" && tolower($2) ~ /(nvidia|cuda)/ && tolower($2) ~ /open/' "$sim" | grep -q .
inst=$(awk '$1=="Inst" {v=$3;gsub(/[()]/,"",v);print $2"="v}' "$sim")
nv=$(printf '%s\n' "$inst" | grep -Ei '(nvidia|cuda|libnv)' || true)
[[ -n $nv ]]
# Audit package names and all version tokens, including unversioned package names.
! printf '%s\n' "$nv" | grep -Ei '(^|[-=.+~:])(59[0-9]|6[0-9][0-9])([-.+~:]|$)'
rem=$(awk '$1=="Remv" {print $2}' "$sim")
critical='^(proxmox|pve-|linux-(image|headers)-|openssh-(server|client)$|systemd|ifupdown|ifupdown2$|network-manager$|zfs|grub|shim|initramfs-tools$|apt$|dpkg$)'
! printf '%s\n' "$rem" | grep -Eq "$critical"
for package in "${old_names[@]}"; do printf '%s\n' "$rem" | grep -Fqx "$package"; done
printf 'STAGE=transaction PASS installs=%s removals=%s critical_removals=none open_modules=none R590_plus=none\n' \
  "$(printf '%s\n' "$inst" | wc -l)" "$(printf '%s\n' "$rem" | wc -l)"
printf 'R580_DEPENDENCY_GRAPH=%s\n' "$(printf '%s\n' "$nv" | paste -sd' ' -)"
printf 'TRANSACTION_INSTALL=%s\n' "$(printf '%s\n' "$inst" | paste -sd' ' -)"
printf 'TRANSACTION_REMOVE=%s\n' "$(printf '%s\n' "$rem" | paste -sd' ' -)"

stage=rollback_candidate
old=$(dpkg-query -W -f='${binary:Package}=${Version}\n' | grep -Ei 'nvidia|cuda' | paste -sd' ' -)
[[ -n $old ]]
dkms_version=$(dkms --version | head -1)
printf 'STAGE=dkms_rollback PASS headers=%s dkms=%s preserved_kernel=%s rollback_kernel=%s\n' \
  "$kernel" "$dkms_version" "$kernel" "$rollback"
cat >"$w/candidate" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
[[ \${LIFEOS_APPROVE_R580_MIGRATION:-} == YES-I-APPROVE-Z97-R580 ]] || { echo 'REFUSED: explicit approval absent'; exit 20; }
[[ \$(uname -r) == '$kernel' ]] || { echo 'REFUSED: kernel drift'; exit 21; }
[[ \$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1) == '$driver' ]] || { echo 'REFUSED: driver drift'; exit 22; }
[[ -d '/usr/src/linux-headers-$kernel' ]] || { echo 'REFUSED: headers absent'; exit 23; }
printf '%s\n' '$old' >/root/lifeos-r535-package-inventory.txt
install -d -m0700 /root/lifeos-r580-source-backup
cp -a /etc/apt/sources.list /etc/apt/sources.list.d /etc/apt/preferences.d /root/lifeos-r580-source-backup/
install -d -m0755 /etc/apt/keyrings
curl -fsSL --max-time 60 https://developer.download.nvidia.com/compute/cuda/repos/debian12/x86_64/3bf863cc.pub | gpg --dearmor --yes -o /etc/apt/keyrings/nvidia-cuda.gpg
sed -i '\|developer.download.nvidia.com/compute/cuda/repos/debian12/x86_64|d' /etc/apt/sources.list 2>/dev/null || :
find /etc/apt/sources.list.d -maxdepth 1 -type f ! -name lifeos-r580.list -exec sed -i '\|developer.download.nvidia.com/compute/cuda/repos/debian12/x86_64|d' {} +
printf '%s\n' 'deb [signed-by=/etc/apt/keyrings/nvidia-cuda.gpg] https://developer.download.nvidia.com/compute/cuda/repos/debian12/x86_64/ /' >/etc/apt/sources.list.d/lifeos-r580.list
cat >/etc/apt/preferences.d/lifeos-r580 <<'PINS'
$(cat "$w/etc/apt/preferences.d/lifeos-r580")
PINS
apt-get update
apt-get -s --no-install-recommends install ${remove_args[*]} 'nvidia-driver-580=$version' | tee /root/lifeos-r580-final-simulation.txt
grep -q '^Inst nvidia-dkms-580 ' /root/lifeos-r580-final-simulation.txt
grep -q '^Inst nvidia-kernel-source-580 ' /root/lifeos-r580-final-simulation.txt
! grep -Eiq '^Inst .*([-=(]59[0-9]|[-=(]6[0-9][0-9])' /root/lifeos-r580-final-simulation.txt
! awk '\$1=="Remv" {print \$2}' /root/lifeos-r580-final-simulation.txt | grep -Eq '$critical'
apt-get --no-install-recommends install ${remove_args[*]} 'nvidia-driver-580=$version'
update-initramfs -u -k '$kernel'
echo 'INSTALL_COMPLETE: reboot required; expected outage 5-15 minutes'
EOF
bash -n "$w/candidate"
printf 'PRODUCTION_SCRIPT_B64=%s\n' "$(base64 -w0 "$w/candidate")"
printf 'ROLLBACK_PLAN=Before reboot, restore APT files from /root/lifeos-r580-source-backup and reinstall /root/lifeos-r535-package-inventory.txt if R580 install fails. After reboot failure, GRUB-select %s; retain current kernel %s; purge only transaction R580 packages and restore the saved R535 inventory.\n' "$rollback" "$kernel"
printf 'POST_REBOOT_PLAN=nvidia-smi reports 580.* and P106-100; DKMS installed for %s; Ollama remains loopback-only; CUDA inference smoke passes; Proxmox, ZFS, networking and SSH healthy\n' "$kernel"
printf 'STAGE=candidate PASS exact_version=%s production_change=NOT_RUN outage=one_reboot_5_to_15_minutes\n' "$version"
REMOTE
rc=$?
set -e
grep -v '^PRODUCTION_SCRIPT_B64=' "$tmp/remote" || :
[[ $rc -eq 0 ]] || fail "towerpc_remote_rc_$rc"

cp "$tmp/remote" "$EVIDENCE"
payload=$(sed -n 's/^PRODUCTION_SCRIPT_B64=//p' "$tmp/remote")
[[ -n $payload ]] || fail production_candidate_missing
printf '%s' "$payload" | base64 -d >"$CANDIDATE" || fail production_candidate_decode
chmod 0600 "$CANDIDATE"
bash -n "$CANDIDATE" || fail production_candidate_syntax
printf 'PRODUCTION_CANDIDATE=%s generated_NOT_RUN\n' "$CANDIDATE"
finish VALID WAITING_HUMAN 'explicit human approval required before production driver migration' \
  "review $EVIDENCE and $CANDIDATE; production execution requires the approval token" \
  PASS 'live relevance, R580 metadata/closure, atomic R535 removal simulation, R590+ and critical-removal guards, DKMS/rollback, candidate syntax PASS' \
  'none until explicit human approval'
