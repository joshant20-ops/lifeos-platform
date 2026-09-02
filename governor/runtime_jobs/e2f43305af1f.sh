#!/usr/bin/env bash
set -Eeuo pipefail

readonly TARGET=${LIFEOS_Z97_TARGET:-TowerPC.Tailor}
readonly SELF=governor/runtime_jobs/e2f43305af1f.sh
readonly OUT=/tmp/lifeos-e2f43305af1f-r580-evidence.txt
readonly CANDIDATE=/tmp/lifeos-e2f43305af1f-r580-approved.sh

finish() {
  local validity=$1 state=$2 barrier=$3 result=$4 tests=$5 next=$6
  printf '%s\n' "ISSUE_VALIDITY=$validity" "LIFEOS_WORK_STATE=$state" \
    "BARRIER=$barrier" "NEXT_AUTONOMOUS_ACTION=$next" \
    'DISCOVERED_ISSUES_JSON_B64=none' "RESULT=$result" "TESTS=$tests" \
    "NEXT_RUNTIME_CHECK=$next"
}
fail() {
  printf 'STAGE=%s FAIL\n' "$1" >&2
  finish BLOCKED BLOCKED "$1" RETRY 'bounded read-only simulation failed' "rerun $SELF through Watchman after resolving $1"
  exit 1
}
for tool in ssh timeout base64 mktemp; do command -v "$tool" >/dev/null || fail "missing_$tool"; done
tmp=$(mktemp -d); trap 'rm -rf -- "$tmp"' EXIT

if ! timeout --signal=TERM --kill-after=15s 720s ssh -T -o BatchMode=yes \
  -o ConnectTimeout=10 -o StrictHostKeyChecking=yes "$TARGET" 'bash -s' \
  >"$tmp/remote" 2>&1 <<'REMOTE'
set -Eeuo pipefail
export LC_ALL=C
stage_fail(){ printf 'STAGE=%s FAIL\n' "$1"; exit 1; }
run(){ local t=$1; shift; timeout --signal=TERM --kill-after=10s "$t" "$@"; }

[[ $(uname -m) == x86_64 ]] || stage_fail host_arch
[[ $(. /etc/os-release; echo "$ID:$VERSION_ID") == debian:12 ]] || stage_fail host_os
kernel=$(uname -r); driver=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1)
gpu=$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)
[[ $gpu == *P106-100* && $driver == 535.* ]] || stage_fail issue_no_longer_matches_host
[[ -d /usr/src/linux-headers-$kernel ]] || stage_fail matching_headers_absent
command -v dkms >/dev/null || stage_fail dkms_absent
[[ $(modinfo -F license nvidia) == *NVIDIA* ]] || stage_fail current_module_not_proprietary
listen=$(ss -H -ltn 2>/dev/null | awk '$4 ~ /:11434$/ {print $4}' | paste -sd, -)
[[ $listen != *0.0.0.0:* && $listen != *'[::]:'* && $listen != \*:* ]] || stage_fail ollama_exposed
rollback=$(find /boot -maxdepth 1 -type f -name 'vmlinuz-*' ! -name "vmlinuz-$kernel" -printf '%f\n' | sort -V | tail -1)
[[ -n $rollback ]] || stage_fail rollback_kernel_absent
printf 'STAGE=relevance PASS gpu=%s driver=%s kernel=%s ollama=%s\n' "$gpu" "$driver" "$kernel" "${listen:-stopped}"

w=$(mktemp -d); trap 'rm -rf -- "$w"' EXIT
mkdir -p "$w/etc/apt/sources.list.d" "$w/etc/apt/preferences.d" "$w/lists/partial" "$w/cache/archives/partial"
cp -a /etc/apt/sources.list "$w/etc/apt/" 2>/dev/null || :
cp -a /etc/apt/sources.list.d/. "$w/etc/apt/sources.list.d/" 2>/dev/null || :
find "$w/etc/apt/sources.list.d" -maxdepth 1 -type f -exec sed -i '\|developer.download.nvidia.com|d' {} +
sed -i '\|developer.download.nvidia.com|d' "$w/etc/apt/sources.list" 2>/dev/null || :
printf '%s\n' 'deb [trusted=yes] https://developer.download.nvidia.com/compute/cuda/repos/debian12/x86_64/ /' >"$w/etc/apt/sources.list.d/r580.list"
cat >"$w/etc/apt/preferences.d/r580" <<'PINS'
Package: *
Pin: origin developer.download.nvidia.com
Pin-Priority: 100

Package: *-580 *-580-server
Pin: origin developer.download.nvidia.com
Pin-Priority: 1001

Package: *-590 *-590-server *-595 *-595-server *-600 *-600-server *-610 *-610-server
Pin: origin developer.download.nvidia.com
Pin-Priority: -1
PINS
o=(-o "Dir::Etc=$w/etc/apt" -o "Dir::State::lists=$w/lists" -o "Dir::Cache=$w/cache" \
   -o Dir::State::status=/var/lib/dpkg/status -o Acquire::Languages=none -o APT::Get::List-Cleanup=0)
run 240s apt-get "${o[@]}" update >/dev/null || stage_fail repository_metadata
version=$(apt-cache "${o[@]}" policy nvidia-driver-580 | awk '/Candidate:/ {print $2;exit}')
[[ $version == 580.* ]] || stage_fail no_r580_candidate
# NVIDIA's Debian packages and Debian's native R535 packages use different
# package-family names.  Model the migration as one atomic remove/install
# request; asking APT to install the meta-package alone was the V39/V40-style
# incoherent simulation which this job replaces.
mapfile -t old_names < <(dpkg-query -W -f='${binary:Package}\t${Version}\n' 2>/dev/null |
  awk 'tolower($0) ~ /(nvidia|cuda)/ {sub(/:amd64$/, "", $1); print $1}' | sort -u)
[[ ${#old_names[@]} -gt 0 ]] || stage_fail r535_package_family_empty
remove_args=(); for package in "${old_names[@]}"; do remove_args+=("$package-"); done
sim="$w/sim"
run 240s apt-get "${o[@]}" -s --no-install-recommends install \
  "${remove_args[@]}" "nvidia-driver-580=$version" >"$sim" 2>&1 || {
    cat "$sim"; stage_fail dependency_resolution;
  }
grep -q '^Inst nvidia-dkms-580 ' "$sim" || { cat "$sim"; stage_fail proprietary_dkms_missing; }
grep -q '^Inst nvidia-kernel-source-580 ' "$sim" || { cat "$sim"; stage_fail proprietary_source_missing; }
inst=$(awk '$1=="Inst" {v=$3;gsub(/[()]/,"",v);print $2"="v}' "$sim")
nv=$(printf '%s\n' "$inst" | grep -Ei '(^|=).*(nvidia|cuda|libnv)' || true)
[[ -n $nv ]] || { cat "$sim"; stage_fail dependency_graph_empty; }
if printf '%s\n' "$nv" | grep -Ei '(^|[-=.+~:])(59[0-9]|6[0-9][0-9])([-.+~:]|$)'; then cat "$sim"; stage_fail r590_plus_leak; fi
if awk '$1=="Inst" && tolower($2) ~ /(nvidia|cuda)/ && tolower($2) ~ /open/' "$sim" | grep -q .; then cat "$sim"; stage_fail open_module_leak; fi
rem=$(awk '$1=="Remv" {print $2}' "$sim")
critical='^(proxmox|pve-|linux-image|openssh-server$|systemd|ifupdown2$|network-manager$|zfs|grub|shim|initramfs-tools$|apt$|dpkg$)'
if printf '%s\n' "$rem" | grep -Eq "$critical"; then cat "$sim"; stage_fail critical_removal; fi
for package in "${old_names[@]}"; do
  printf '%s\n' "$rem" | grep -Fqx "$package" || { cat "$sim"; stage_fail "r535_removal_missing_$package"; }
done
printf 'STAGE=metadata PASS candidate=%s rejected=R590+ source=NVIDIA_debian12\n' "$version"
printf 'STAGE=transaction PASS installs=%s removals=%s open_modules=none newer_branch=none\n' "$(printf '%s\n' "$inst" | wc -l)" "$(printf '%s\n' "$rem" | paste -sd, - | sed 's/^$/none/')"
printf 'R580_DEPENDENCY_GRAPH=%s\n' "$(printf '%s\n' "$nv" | paste -sd' ' -)"
old=$(dpkg-query -W -f='${binary:Package}=${Version}\n' | grep -Ei 'nvidia|cuda' | paste -sd' ' -)
[[ -n $old ]] || stage_fail rollback_inventory_empty
printf 'STAGE=rollback PASS headers=%s dkms=%s rollback_kernel=%s\n' "$kernel" "$(dkms --version | head -1)" "$rollback"

# This artifact is emitted only; the diagnostic does not execute it.
cat >"$w/candidate" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
[[ \${LIFEOS_APPROVE_R580_MIGRATION:-} == YES-I-APPROVE-Z97-R580 ]] || { echo 'REFUSED approval absent'; exit 20; }
[[ \$(uname -r) == '$kernel' ]] || { echo 'REFUSED kernel drift'; exit 21; }
[[ \$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1) == '$driver' ]] || { echo 'REFUSED driver drift'; exit 22; }
printf '%s\n' '$old' >/root/lifeos-r535-package-inventory.txt
install -d -m0700 /root/lifeos-r580-source-backup
cp -a /etc/apt/sources.list /etc/apt/sources.list.d /etc/apt/preferences.d /root/lifeos-r580-source-backup/
install -d -m0755 /etc/apt/keyrings
curl -fsSL --max-time 60 https://developer.download.nvidia.com/compute/cuda/repos/debian12/x86_64/3bf863cc.pub | gpg --dearmor --yes -o /etc/apt/keyrings/nvidia-cuda.gpg
# Normalize pre-existing NVIDIA entries to prevent duplicate-URI/Signed-By
# conflicts.  The complete original APT configuration is backed up above.
sed -i '\|developer.download.nvidia.com/compute/cuda/repos/debian12/x86_64|d' /etc/apt/sources.list 2>/dev/null || :
find /etc/apt/sources.list.d -maxdepth 1 -type f ! -name lifeos-r580.list -exec sed -i '\|developer.download.nvidia.com/compute/cuda/repos/debian12/x86_64|d' {} +
printf '%s\n' 'deb [signed-by=/etc/apt/keyrings/nvidia-cuda.gpg] https://developer.download.nvidia.com/compute/cuda/repos/debian12/x86_64/ /' >/etc/apt/sources.list.d/lifeos-r580.list
cat >/etc/apt/preferences.d/lifeos-r580 <<'PINS'
$(cat "$w/etc/apt/preferences.d/r580")
PINS
apt-get update
apt-get -s --no-install-recommends install ${remove_args[*]} 'nvidia-driver-580=$version' | tee /root/lifeos-r580-final-simulation.txt
grep -q '^Inst nvidia-dkms-580 ' /root/lifeos-r580-final-simulation.txt
! grep -Eiq '^Inst .*([-=(]59[0-9]|[-=(]6[0-9][0-9])' /root/lifeos-r580-final-simulation.txt
! awk '\$1=="Remv" {print \$2}' /root/lifeos-r580-final-simulation.txt | grep -Eq '$critical'
apt-get --no-install-recommends install ${remove_args[*]} 'nvidia-driver-580=$version'
update-initramfs -u -k '$kernel'
echo 'INSTALL_COMPLETE reboot required; expected outage 5-15 minutes'
EOF
printf 'PRODUCTION_SCRIPT_B64=%s\n' "$(base64 -w0 "$w/candidate")"
printf 'ROLLBACK_PLAN=GRUB boot %s; restore APT configuration from /root/lifeos-r580-source-backup; remove only installed R580 transaction packages; reinstall inventory /root/lifeos-r535-package-inventory.txt; retain %s\n' "$rollback" "$kernel"
printf 'POST_REBOOT_PLAN=nvidia-smi=580.*, DKMS installed for %s, Ollama loopback-only, CUDA inference smoke, Proxmox/ZFS/network/SSH health\n' "$kernel"
printf 'STAGE=candidate PASS outage=one_reboot_5_to_15_minutes production_change=NOT_RUN\n'
REMOTE
then
  cat "$tmp/remote" >&2
  fail towerpc_read_only_simulation
fi

tee "$OUT" <"$tmp/remote" | grep -v '^PRODUCTION_SCRIPT_B64='
payload=$(sed -n 's/^PRODUCTION_SCRIPT_B64=//p' "$tmp/remote")
[[ -n $payload ]] || fail candidate_missing
printf '%s' "$payload" | base64 -d >"$CANDIDATE" || fail candidate_decode
chmod 0600 "$CANDIDATE"; bash -n "$CANDIDATE" || fail candidate_syntax
printf 'PRODUCTION_CANDIDATE=%s NOT_RUN\n' "$CANDIDATE"
finish VALID WAITING_HUMAN 'explicit human approval required before production driver migration' PASS \
  'relevance, metadata, coherent proprietary R580 simulation, R590+ rejection, critical-removal audit, DKMS/rollback and candidate syntax PASS' \
  "review $OUT and $CANDIDATE; execute only after explicit approval"
