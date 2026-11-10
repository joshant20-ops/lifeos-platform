#!/usr/bin/env bash
# Fixed, no-argument, read-only gateway operation. No network or Docker changes.
set -Eeuo pipefail
[[ "$#" -eq 0 ]] || { echo 'STORAGE_AUDIT=REJECTED_ARGUMENTS'; exit 64; }
[[ "${EUID:-$(id -u)}" -eq 0 ]] || { echo 'STORAGE_AUDIT=REQUIRES_GATEWAY'; exit 77; }
REPO=/home/joshan/lifeos-platform
[[ -f "$REPO/governor/read_only_storage_diagnostic.py" && ! -L "$REPO/governor/read_only_storage_diagnostic.py" ]] || {
  echo 'STORAGE_AUDIT=SOURCE_UNAVAILABLE'
  exit 66
}
# The parent gateway already verifies a clean, current origin/main checkout.
# The Python probe only stats metadata and runs fixed bounded 'du' checks.
exec /usr/bin/python3 -B "$REPO/governor/read_only_storage_diagnostic.py" --json
