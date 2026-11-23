#!/usr/bin/env bash
# Owner-only, approval-gated setup. Never invoked by the audit workflow.
set -Eeuo pipefail
[[ $EUID -eq 0 && $# -eq 3 ]] || { echo 'USAGE: sudo bash install.sh APPROVED_COMMIT PRIVATE_CONFIG RUNNER_ACCOUNT'; exit 64; }
approved=$1
private_config=$2
runner=$3
[[ $approved =~ ^[0-9a-f]{40}$ && $runner =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] || exit 64
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd -P)
owner=$(stat -c %U "$repo/.git")
[[ $owner != root && $(id -u "$runner") -ne 0 ]] || exit 65
git_owner() { runuser -u "$owner" -- /usr/bin/git -C "$repo" "$@"; }
[[ $(git_owner rev-parse HEAD) == "$approved" ]] || { echo SOURCE_REVISION_MISMATCH; exit 65; }
[[ -z $(git_owner status --porcelain --untracked-files=no) ]] || { echo SOURCE_NOT_CLEAN; exit 65; }
# A pre-existing broad Docker/shell boundary is not silently accepted.
if runuser -u "$runner" -- /usr/bin/test -w /run/docker.sock; then
  echo RUNNER_HAS_UNRESTRICTED_DOCKER_ACCESS_REQUIRES_SEPARATE_ISOLATION; exit 65
fi
for command in /bin/sh /usr/bin/python3 /usr/bin/docker; do
  if sudo -n -l -U "$runner" -- "$command" >/dev/null 2>&1; then
    echo RUNNER_HAS_BROAD_PRIVILEGE_REQUIRES_SEPARATE_ISOLATION; exit 65
  fi
done
[[ -f /usr/local/sbin/lifeos-deploy-gateway && ! -L /usr/local/sbin/lifeos-deploy-gateway ]] || exit 65
sudo -n -l -U "$runner" -- /usr/local/sbin/lifeos-deploy-gateway storage-audit-summary >/dev/null 2>&1 || { echo RUNNER_NOT_AUTHORISED_FIXED_GATEWAY; exit 65; }
[[ $(stat -c %u /usr/local/sbin/lifeos-deploy-gateway) -eq 0 ]] || exit 65
[[ $(sha256sum /usr/local/sbin/lifeos-deploy-gateway | cut -d' ' -f1) == dc004f5f35f56e22abb0d8fc8484f78958722b009cb96a900447cf39531fe859 ]] || { echo INSTALLED_GATEWAY_BASELINE_MISMATCH_REQUIRES_REVIEW; exit 65; }
[[ ! -e /etc/lifeos-storage-audit.json && ! -e /usr/local/lib/lifeos-storage-audit ]] || { echo EXISTING_INSTALLATION_REQUIRES_REVIEW; exit 65; }
[[ $private_config == /* && -f $private_config && ! -L $private_config && $private_config != "$repo/"* ]] || exit 65
umask 077
state=/var/lib/lifeos-storage-audit
install -d -o root -g root -m 0700 "$state"
stage=$(mktemp -d "$state/setup-XXXXXXXX")
files=(scripts/audits/storage/worker.py scripts/audits/storage/lifeos-storage-audit.service scripts/lifeos_storage_retention_inventory.py scripts/lifeos_storage_backup_profile.py homelab/live/usr/local/sbin/lifeos-deploy-gateway)
for relative in "${files[@]}"; do
  mkdir -p -- "$stage/$(dirname -- "$relative")"
  git_owner show "$approved:$relative" > "$stage/$relative"
done
python3 -I - "$stage/scripts/audits/storage/worker.py" "$private_config" <<'PY'
import importlib.util, os, sys
spec=importlib.util.spec_from_file_location('checked',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
m.configuration(sys.argv[2])
PY
# Preserve old installed boundary before any replacement; no sudoers edits.
cp -p -- /usr/local/sbin/lifeos-deploy-gateway "$stage/gateway.before"
lib=/usr/local/lib/lifeos-storage-audit
install -d -o root -g root -m 0755 "$lib/scripts"
printf '' > "$lib/scripts/__init__.py"
install -o root -g root -m 0644 "$stage/scripts/audits/storage/worker.py" "$lib/worker.py"
for name in lifeos_storage_retention_inventory.py lifeos_storage_backup_profile.py; do
  install -o root -g root -m 0644 "$stage/scripts/$name" "$lib/scripts/$name"
done
install -o root -g root -m 0600 "$private_config" /etc/lifeos-storage-audit.json
install -o root -g root -m 0644 "$stage/scripts/audits/storage/lifeos-storage-audit.service" /etc/systemd/system/lifeos-storage-audit.service
systemd-analyze verify /etc/systemd/system/lifeos-storage-audit.service
install -o root -g root -m 0755 "$stage/homelab/live/usr/local/sbin/lifeos-deploy-gateway" /usr/local/sbin/lifeos-deploy-gateway
systemctl daemon-reload
# No timer, runner registration, service start, sudoers change or GitHub activation.
echo STORAGE_AUDIT_INSTALLED_NOT_EXECUTED
echo GITHUB_ACTIVATION_REQUIRES_OWNER_APPROVAL_AND_BOUNDARY_ACCEPTANCE
