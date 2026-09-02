# Semaphore shadow execution plane

This is the bounded M2 shadow deployment for issue #23. The 2026-09-02
architecture update supersedes the failed amd64-only Rundeck experiment.
Semaphore UI `v2.18.29` is pinned; the Pi5 launcher additionally rejects any
resolved image whose architecture is not `arm64`. No emulation is accepted.

The stack is shadow-only. It does not disable or modify the backlog runner,
Watchman, root broker, or transaction controller. Semaphore has no Docker
socket, host root, transaction-state mount, sudo capability, or arbitrary shell
template. The database has no published port and the UI must bind to one
explicit LAN address, never `0.0.0.0`.

## Secrets and initial deployment

On a first deployment, the Watchman launcher detects the Pi5's private IPv4
source address and creates `/etc/lifeos/semaphore.env` mode `0600`, plus a
root-owned secret directory mode `0700`. It generates four regular files mode
`0600`: `db_password`, `admin_user`, `admin_password`, and
`access_key_encryption`. The encryption file contains a stable base64-encoded
32-byte key. Existing configuration is never overwritten and unsafe ownership,
permissions, symlinks, non-private binding, or a custom missing secrets path
fail closed. These values stay outside Git and must not be printed in runtime
evidence. Changing or losing the encryption key makes stored credentials
unusable. `runtime.env.example` documents the non-secret settings for a
deliberate pre-provisioned configuration.

Only the reviewed launcher
`governor/runtime_jobs/c3751aaff97b.sh` may inspect or start this shadow on Pi5.
It validates secret metadata, host/image architecture, LAN binding, health,
mount and capability boundaries, and confirms the compatibility services were
not disturbed.

## Backup, restore, and rollback

Before upgrades, stop new shadow submissions and let active tasks drain. From
the approved local boundary, take a PostgreSQL custom-format dump and archives
of `semaphore-config`, `semaphore-data`, and `semaphore-work`; back up the four
secret files separately with root-only permissions. Store neither contents nor
private task output in Git. Record only image digests, checksums, and redacted
PASS evidence.

Restore the secret files first, then empty volumes with the same pinned images,
restore PostgreSQL, start Semaphore, and prove login, project/template inventory
and one read-only task. An upgrade rollback restores the matched pre-upgrade
database, volumes, secrets, and image pin. Shadow rollback is simply to stop the
Semaphore project while leaving named volumes intact; the unchanged compatibility
path continues from its existing checkpoint. Rundeck remains stopped and its
historical evidence is retained until migration closure.

## Acceptance boundary

Passing the launcher proves only the persistent, native-ARM64, LAN-bounded
shadow foundation. It does not prove task catalogue equivalence or authorize
cutover. M3 must add version-controlled allow-listed Ansible templates. M4 must
route every mutation through the #26 begin/backup/watchdog/apply/verify/protected
GOOD/commit sequence, with immediate or watchdog rollback otherwise.
