#!/usr/bin/env bash
set -Eeuo pipefail

# Wave C read-only capability inventory. Output is deliberately limited to
# interface availability; it never prints credential values, source records,
# filenames, account identifiers, balances, document metadata or counts.

REPO=${LIFEOS_PLATFORM_REPO:-/home/joshan/lifeos-platform}
cd "$REPO"

test -z "$(git status --porcelain --untracked-files=all)"
test "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)"
echo 'CANONICAL_CHECKOUT=PASS'

secret_names=$(sudo -n find /etc/lifeos/secrets -maxdepth 1 -type f -printf '%f\n' 2>/dev/null || true)
container_names=$(docker ps --format '{{.Names}}' 2>/dev/null || true)
container_images=$(docker ps --format '{{.Image}}' 2>/dev/null || true)
unit_names=$(systemctl list-unit-files --no-legend --no-pager 2>/dev/null | awk '{print $1}' || true)

probe_provider() {
  local label=$1 pattern=$2
  if grep -Eiq "$pattern" <<<"$secret_names" ||
     grep -Eiq "$pattern" <<<"$container_names" ||
     grep -Eiq "$pattern" <<<"$container_images" ||
     grep -Eiq "$pattern" <<<"$unit_names"; then
    printf '%s=AVAILABLE\n' "$label"
  else
    printf '%s=ABSENT\n' "$label"
  fi
}

probe_provider 'ACCOUNTING_FREEAGENT' 'freeagent'
probe_provider 'ACCOUNTING_XERO' '(^|[-_.])xero([-_.]|$)'
probe_provider 'ACCOUNTING_QUICKBOOKS' 'quickbooks|(^|[-_.])qbo([-_.]|$)'
probe_provider 'ACCOUNTING_SAGE' '(^|[-_.])sage([-_.]|$)'
probe_provider 'OPEN_BANKING_TRUELAYER' 'truelayer'
probe_provider 'OPEN_BANKING_GOCARDLESS' 'gocardless|bank-account-data'
probe_provider 'BANK_MONZO' '(^|[-_.])monzo([-_.]|$)'
probe_provider 'BANK_STARLING' 'starling'
probe_provider 'HMRC_INTERFACE' '(^|[-_.])hmrc([-_.]|$)'

if grep -qx 'paperless-paperless-1' <<<"$container_names" &&
   docker inspect -f '{{.State.Running}}' paperless-paperless-1 2>/dev/null | grep -qx true; then
  echo 'PAPERLESS_RUNTIME=AVAILABLE'
else
  echo 'PAPERLESS_RUNTIME=ABSENT'
fi

if sudo -n test -s /etc/lifeos/secrets/paperless-api-token 2>/dev/null; then
  echo 'PAPERLESS_READ_CREDENTIAL=AVAILABLE'
else
  echo 'PAPERLESS_READ_CREDENTIAL=ABSENT'
fi

if docker exec paperless-paperless-1 python manage.py shell -c \
  "from documents.models import Document; Document.objects.order_by('id').values_list('id', flat=True).first(); print('PAPERLESS_READ_BOUNDARY=PASS')" \
  2>/dev/null | grep -qx 'PAPERLESS_READ_BOUNDARY=PASS'; then
  echo 'PAPERLESS_READ_BOUNDARY=PASS'
else
  echo 'PAPERLESS_READ_BOUNDARY=UNAVAILABLE'
fi

candidate=ABSENT
for root in /mnt/synology/Joshan /opt/stacks /home/joshan; do
  if sudo -n test -d "$root" 2>/dev/null &&
     sudo -n find "$root" -xdev -type f \
       \( -iname '*.ofx' -o -iname '*.qif' -o -iname '*.qfx' \) \
       -print -quit 2>/dev/null | grep -q .; then
    candidate=AVAILABLE_UNPROVEN
    break
  fi
done
printf 'FINANCIAL_IMPORT_FORMAT_CANDIDATE=%s\n' "$candidate"

echo 'MUTATION_GATE=READ_ONLY'
echo 'LEDGER_WRITES=BLOCKED'
echo 'BANK_WRITES=BLOCKED'
echo 'HMRC_SUBMISSIONS=BLOCKED'
echo 'WAVE_C_RUNTIME_INVENTORY=PASS'
