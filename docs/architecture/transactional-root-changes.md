# Transactional root changes (increment 1)

Issue #26 remains valid. The bounded root broker has allowlists, approvals and
immediate in-process rollback, but that rollback dies with the broker and does
not provide the required two-hour dead-man guarantee.

This increment adds a minimal protected recovery core for `LOW`/`MEDIUM` risk
atomic file replacement. The root-owned controller creates durable state and a
backup before it arms `lifeos-rollback@<transaction>.timer`; mutation is denied
unless arming succeeds. The persistent systemd timer invokes the separate
rollback executable and does not depend on Governor or Engineer being alive.
Only measured destination hashes and allowlisted service state checks can create
verification evidence. A caller assertion is not accepted as evidence.

The controller allows destinations only below `/usr/local/libexec`; systemd
unit mutation remains denied until prior service state and daemon-reload can be
restored together. Its own module, executables and watchdog units are explicitly
protected. Conflicting destinations use durable exclusive resource locks.
Transaction manifests, backups, evidence, deadline, timer identity and rollback
outcomes live under `/var/lib/lifeos-transactions` and survive reboot.

The Pi5 launcher performs initial install only when the protected files are
absent or byte-identical. A changed recovery core fails closed because its next
upgrade requires an A/B design retaining the known-good copy.

## Trust and remaining scope

Pi5/Watchman remains the runtime authority and canonical Git writer. The model
has no interactive root shell and cannot write the root-owned state directory.
The controller does not yet broaden package, database, container, credential or
network authority. Existing broker deployments have not yet been migrated to
this API; that is the next increment after the runtime canary proves both commit
and forced rollback. Higher-risk operations remain denied rather than silently
receiving insufficient backup depth.

Rollback of this increment is an explicit protected-core A/B operation; ordinary
deployment paths cannot overwrite or remove it.
