#!/usr/bin/env bash
set -Eeuo pipefail

readonly TARGET=${LIFEOS_Z97_TARGET:-TowerPC.Tailor}
readonly CONNECT_TIMEOUT=8
readonly JOB_TIMEOUT=600
readonly CANDIDATE=/tmp/lifeos-r580-production-candidate.sh
readonly EVIDENCE=/tmp/lifeos-r580-simulation-evidence.txt

fail() {
  printf 'FAIL=%s\n' "$1" >&2
  printf '%s\n' \
    'ISSUE_VALIDITY=BLOCKED' \
    'LIFEOS_WORK_STATE=BLOCKED' \
    "BARRIER=$1" \
    'NEXT_AUTONOMOUS_ACTION=repair the named diagnostic barrier and rerun this launcher' \
    'DISCOVERED_ISSUES_JSON_B64=none' \
    'RESULT=RETRY' \
    'TESTS=bounded R580 simulation failed' \
    "NEXT_RUNTIME_CHECK=bash governor/runtime_jobs/6e4305a1be02.sh"
  exit 1
}
command -v ssh >/dev/null || fail ssh_missing
command -v base64 >/dev/null || fail base64_missing
command -v timeout >/dev/null || fail timeout_missing

tmp=$(mktemp -d)
trap 'rm -rf -- "$tmp"' EXIT
if ! timeout --signal=TERM --kill-after=15s "${JOB_TIMEOUT}s" \
  ssh -T -o BatchMode=yes -o ConnectTimeout="$CONNECT_TIMEOUT" "$TARGET" 'bash -s' \
  >"$tmp/output" 2>&1 <<'REMOTE'
set -Eeuo pipefail
export LC_ALL=C
fail() { printf 'STAGE=%s FAIL\n' "$1"; exit 1; }
run() { local limit=$1; shift; timeout --signal=TERM --kill-after=10s "$limit" "$@"; }

[[ $(uname -m) == x86_64 ]] || fail host_identity
[[ $(. /etc/os-release; printf %s "$ID:$VERSION_ID") == debian:12 ]] || fail host_identity
kernel=$(uname -r)
[[ "$kernel" == 6.8.12-23-pve ]] || fail kernel_relevance
command -v nvidia-smi >/dev/null || fail nvidia_smi_missing
mapfile -t gpu_rows < <(run 15s nvidia-smi \
  --query-gpu=name,driver_version,memory.total,pci.bus_id \
  --format=csv,noheader,nounits 2>/dev/null)
[[ ${#gpu_rows[@]} -eq 1 ]] || fail gpu_count_or_health
IFS=',' read -r gpu driver gpu_memory gpu_bus <<<"${gpu_rows[0]}"
gpu=${gpu## }; driver=${driver## }; gpu_memory=${gpu_memory## }; gpu_bus=${gpu_bus## }
[[ "$driver" == 535.261.03 && "$gpu" == *P106-100* ]] || fail gpu_relevance
[[ "$gpu_memory" =~ ^[0-9]+$ && "$gpu_memory" -ge 5900 && "$gpu_memory" -le 6200 ]] || fail gpu_memory
module_version=$(cat /sys/module/nvidia/version 2>/dev/null || true)
[[ "$module_version" == "$driver" ]] || fail nvidia_userspace_kernel_mismatch
module_vermagic=$(modinfo -F vermagic nvidia 2>/dev/null | head -n1)
module_license=$(modinfo -F license nvidia 2>/dev/null | head -n1)
[[ "$module_vermagic" == "$kernel "* ]] || fail nvidia_module_kernel_mismatch
[[ "$module_license" == *NVIDIA* ]] || fail nvidia_module_not_proprietary
[[ ! -d /sys/module/nouveau ]] || fail nouveau_loaded
nvidia_pci=0
for device in /sys/bus/pci/devices/*; do
  [[ $(cat "$device/vendor" 2>/dev/null || true) == 0x10de ]] || continue
  class=$(cat "$device/class" 2>/dev/null || true)
  [[ "$class" == 0x03* ]] || continue
  [[ -L "$device/driver" && $(basename "$(readlink -f "$device/driver")") == nvidia ]] || fail gpu_not_bound_to_nvidia
  nvidia_pci=$((nvidia_pci + 1))
done
[[ $nvidia_pci -eq 1 ]] || fail gpu_pci_identity
run 15s nvidia-smi -q -d COMPUTE >/dev/null 2>&1 || fail gpu_compute_query
ollama_listen=$(ss -H -ltnp 2>/dev/null | awk '$4 ~ /:11434$/ {print $4}' | paste -sd, -)
[[ "$ollama_listen" != *0.0.0.0:* && "$ollama_listen" != *'[::]:'* && "$ollama_listen" != \*:* ]] || fail ollama_not_localhost
printf 'STAGE=gpu_driver PASS kernel=%s gpu=%s memory_mib=%s pci=%s binding=nvidia module=%s flavor=proprietary nouveau=absent health=responsive ollama=%s\n' \
  "$kernel" "$gpu" "$gpu_memory" "$gpu_bus" "$module_version" "${ollama_listen:-not-listening}"

work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
mkdir -p "$work/etc/apt/sources.list.d" "$work/etc/apt/preferences.d" \
  "$work/var/lib/apt/lists/partial" "$work/var/cache/apt/archives/partial"
cp -a /etc/apt/sources.list "$work/etc/apt/" 2>/dev/null || :
cp -a /etc/apt/sources.list.d/. "$work/etc/apt/sources.list.d/" 2>/dev/null || :
# Avoid Signed-By conflicts with any live CUDA entry; the isolated job defines
# its own NVIDIA source below and never edits the live source files.
if [[ -f "$work/etc/apt/sources.list" ]]; then
  sed -i '\|developer.download.nvidia.com|d' "$work/etc/apt/sources.list"
fi
while IFS= read -r -d '' source_file; do
  grep -q 'developer.download.nvidia.com' "$source_file" && rm -f -- "$source_file"
done < <(find "$work/etc/apt/sources.list.d" -maxdepth 1 -type f -print0)
cat >"$work/etc/apt/sources.list.d/lifeos-r580.list" <<'EOF'
deb [trusted=yes] https://developer.download.nvidia.com/compute/cuda/repos/debian12/x86_64/ /
EOF
cat >"$work/etc/apt/preferences.d/lifeos-r580" <<'EOF'
Package: *
Pin: origin developer.download.nvidia.com
Pin-Priority: 100

Package: *-580 *-580-server
Pin: origin developer.download.nvidia.com
Pin-Priority: 1001

Package: *-590 *-590-server *-595 *-595-server *-600 *-600-server *-610 *-610-server
Pin: origin developer.download.nvidia.com
Pin-Priority: -1
EOF
aptopt=(-o "Dir::Etc=$work/etc/apt" -o "Dir::State::lists=$work/var/lib/apt/lists" \
  -o "Dir::Cache=$work/var/cache/apt" -o Dir::State::status=/var/lib/dpkg/status \
  -o APT::Get::List-Cleanup=0 -o Acquire::Languages=none)
run 180s apt-get "${aptopt[@]}" update >/dev/null || fail repository_metadata
candidate=$(apt-cache "${aptopt[@]}" policy nvidia-driver-580 | awk '/Candidate:/ {print $2; exit}')
[[ -n "$candidate" && "$candidate" != '(none)' && "$candidate" == 580.* ]] || fail r580_candidate
for branch in 590 595 600 610; do
  bad=$(apt-cache "${aptopt[@]}" policy "nvidia-driver-$branch" | awk '/Candidate:/ {print $2; exit}')
  [[ -z "$bad" || "$bad" == '(none)' ]] || fail "branch_${branch}_not_rejected"
done
printf 'STAGE=metadata PASS repo=debian12/x86_64 candidate=%s rejected=R590,R595,R600,R610\n' "$candidate"

sim="$work/simulation.txt"
run 180s apt-get "${aptopt[@]}" -s --no-install-recommends install \
  "nvidia-driver-580=$candidate" >"$sim" 2>&1 || { cat "$sim"; fail dependency_resolution; }
grep -q '^Conf nvidia-driver-580 ' "$sim" || { cat "$sim"; fail r580_not_configured; }
grep -q '^Inst nvidia-dkms-580 ' "$sim" || { cat "$sim"; fail proprietary_r580_dkms_not_selected; }
grep -q '^Inst nvidia-kernel-source-580 ' "$sim" || { cat "$sim"; fail proprietary_r580_source_not_selected; }
if awk '$1=="Inst" && tolower($2) ~ /(nvidia|cuda)/ && tolower($2) ~ /open/ {print}' "$sim" | grep -q .; then
  cat "$sim"; fail open_kernel_module_selected_for_pascal
fi
if grep -Eq '^Inst .*-(590|595|600|610)([^0-9]|$)|\((590|595|600|610)\.' "$sim"; then
  cat "$sim"; fail newer_branch_leak
fi
# Package names are not uniformly branch-suffixed. Audit versions as well so
# unversioned libnvidia/cuda dependencies cannot silently come from R590+.
if awk '$1=="Inst" && tolower($2) ~ /(nvidia|cuda|libnv)/ {
  version=$3; gsub(/[()]/, "", version)
  if (version ~ /(^|[.+~:-])(590|595|600|610)([.+~:-]|$)/) print
}' "$sim" | grep -q .; then
  cat "$sim"; fail newer_branch_version_leak
fi
nvidia_versions=$(awk '$1=="Inst" && tolower($2) ~ /(nvidia|cuda|libnv)/ {
  version=$3; gsub(/[()]/, "", version); print $2"="version
}' "$sim")
[[ -n "$nvidia_versions" ]] || { cat "$sim"; fail missing_nvidia_dependency_graph; }
# Generic support libraries can legitimately use their own 1.x/202x versions.
# Any NVIDIA/CUDA dependency whose version declares a 5xx/6xx driver branch,
# however, must declare 580.
if printf '%s\n' "$nvidia_versions" | awk -F= '
  {
    version=$2; gsub(/[^0-9]+/, " ", version); count=split(version, part, " ")
    for (i=1; i<=count; i++) if (part[i] >= 500 && part[i] <= 699 && part[i] != 580) {print; next}
  }
' | grep -q .; then
  printf '%s\n' "$nvidia_versions"; cat "$sim"; fail incoherent_nvidia_dependency_graph
fi
critical='(^| )(proxmox-ve|proxmox-default-kernel|pve-manager|pve-kernel-[^ ]+|linux-image-[^ ]+|openssh-server|systemd|systemd-sysv|ifupdown2|network-manager|zfsutils-linux|zfs-zed|zfs-dkms|grub[^ ]*|shim[^ ]*|initramfs-tools|apt|dpkg)( |$)'
removals=$(awk '$1=="Remv" {print $2}' "$sim" | paste -sd' ' -)
if printf '%s\n' "$removals" | grep -Eq "$critical"; then cat "$sim"; fail critical_package_removal; fi
installed=$(awk '$1=="Inst" {print $2"="$3}' "$sim" | tr -d '()' | paste -sd' ' -)
[[ -n "$installed" ]] || { cat "$sim"; fail empty_transaction; }
printf 'STAGE=transaction PASS install_count=%s removals=%s\n' \
  "$(awk '$1=="Inst" {n++} END {print n+0}' "$sim")" "${removals:-none}"
printf 'TRANSACTION_PACKAGES=%s\n' "$installed"
printf 'R580_DEPENDENCY_GRAPH=%s\n' "$(printf '%s\n' "$nvidia_versions" | paste -sd' ' -)"

[[ -d "/usr/src/linux-headers-$kernel" ]] || fail matching_headers
command -v dkms >/dev/null || fail dkms_missing
dkms_version=$(dkms --version 2>/dev/null | head -n1)
rollback_kernel=$(find /boot -maxdepth 1 -type f -name 'vmlinuz-*' ! -name "vmlinuz-$kernel" -printf '%f\n' | sort -V | tail -n1)
[[ -n "$rollback_kernel" ]] || fail rollback_kernel_missing
remote_host=$(hostname)
old_packages=$(dpkg-query -W -f='${binary:Package}=${Version}\n' 2>/dev/null | awk 'tolower($0) ~ /(nvidia|cuda)/' | paste -sd' ' -)
[[ -n "$old_packages" ]] || fail rollback_package_inventory_missing
printf 'STAGE=dkms_rollback PASS headers=%s dkms=%s rollback_kernel=%s\n' "$kernel" "$dkms_version" "$rollback_kernel"

# Emit a fully versioned, approval-gated candidate. It is data on stdout; this
# diagnostic never invokes it and never writes apt configuration on the host.
prod="$work/production.sh"
cat >"$prod" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
[[ \${LIFEOS_APPROVE_R580_MIGRATION:-} == YES-I-APPROVE-Z97-R580 ]] || { echo 'REFUSED: explicit approval token absent'; exit 20; }
[[ \$(hostname) == $remote_host && \$(uname -r) == $kernel ]] || { echo 'REFUSED: host/kernel drift'; exit 21; }
[[ \$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -n1) == 535.261.03 ]] || { echo 'REFUSED: driver drift'; exit 22; }
printf '%s\n' '$old_packages' >/root/lifeos-r535-package-inventory.txt
install -d -m 0755 /etc/apt/keyrings
curl -fsSL --max-time 60 https://developer.download.nvidia.com/compute/cuda/repos/debian12/x86_64/3bf863cc.pub | gpg --dearmor --yes -o /etc/apt/keyrings/nvidia-cuda.gpg
printf '%s\n' 'deb [signed-by=/etc/apt/keyrings/nvidia-cuda.gpg] https://developer.download.nvidia.com/compute/cuda/repos/debian12/x86_64/ /' >/etc/apt/sources.list.d/nvidia-cuda-debian12.list
cat >/etc/apt/preferences.d/lifeos-nvidia-r580 <<'PINS'
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
apt-get update
apt-get -s --no-install-recommends install nvidia-driver-580=$candidate | tee /root/lifeos-r580-final-simulation.txt
grep -q '^Inst nvidia-dkms-580 ' /root/lifeos-r580-final-simulation.txt
grep -q '^Inst nvidia-kernel-source-580 ' /root/lifeos-r580-final-simulation.txt
! awk '\$1=="Inst" && tolower(\$2) ~ /(nvidia|cuda)/ && tolower(\$2) ~ /open/ {print}' /root/lifeos-r580-final-simulation.txt | grep -q .
! grep -Eq '^Inst .*-(590|595|600|610)([^0-9]|$)|\((590|595|600|610)\.' /root/lifeos-r580-final-simulation.txt
! awk '\$1=="Remv" {print \$2}' /root/lifeos-r580-final-simulation.txt | grep -Eq '$critical'
apt-get --no-install-recommends install nvidia-driver-580=$candidate
update-initramfs -u -k $kernel
echo 'INSTALL_COMPLETE: reboot required; expected outage 5-15 minutes'
EOF
chmod 0700 "$prod"
printf 'PRODUCTION_SCRIPT_B64=%s\n' "$(base64 -w0 "$prod")"
printf 'ROLLBACK_PLAN=GRUB-select %s; purge only R580 packages, then apt-get install the exact packages in /root/lifeos-r535-package-inventory.txt from configured Debian repositories/cache; do not remove kernel %s\n' "$rollback_kernel" "$kernel"
printf 'R535_ROLLBACK_PACKAGES=%s\n' "$old_packages"
printf 'POST_REBOOT_PLAN=nvidia-smi driver=580.*, dkms status built/installed for %s, Ollama remains loopback-only, CUDA inference smoke test, Proxmox/ZFS/network/SSH health\n' "$kernel"
printf 'STAGE=candidate PASS exact_meta=nvidia-driver-580=%s outage=one_reboot_5_to_15_minutes\n' "$candidate"
REMOTE
then
  cat "$tmp/output" >&2
  fail towerpc_diagnostic_or_simulation
fi

tee "$EVIDENCE" <"$tmp/output" | grep -v '^PRODUCTION_SCRIPT_B64='
payload=$(sed -n 's/^PRODUCTION_SCRIPT_B64=//p' "$tmp/output")
[[ -n "$payload" ]] || fail production_candidate_missing
printf '%s' "$payload" | base64 -d >"$CANDIDATE" || fail production_candidate_decode
chmod 0600 "$CANDIDATE"
bash -n "$CANDIDATE" || fail production_candidate_syntax
printf 'PRODUCTION_CANDIDATE=%s (generated, NOT RUN)\n' "$CANDIDATE"
printf '%s\n' \
  'ISSUE_VALIDITY=VALID' \
  'LIFEOS_WORK_STATE=WAITING_HUMAN' \
  'BARRIER=explicit human approval required before production driver migration' \
  "NEXT_AUTONOMOUS_ACTION=review $EVIDENCE and $CANDIDATE; run the candidate only after explicit approval" \
  'DISCOVERED_ISSUES_JSON_B64=none' \
  'RESULT=PASS' \
  'TESTS=live relevance, isolated repository metadata, pinned dependency simulation, critical-removal guard, DKMS headers, rollback kernel, candidate syntax PASS' \
  'NEXT_RUNTIME_CHECK=explicit approval review of /tmp/lifeos-r580-production-candidate.sh'
