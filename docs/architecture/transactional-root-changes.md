# Transactional root changes

The first production increment of issue #26 is complete. The bounded root broker
retains allowlists and approvals; privileged file replacement is protected by a
separate durable controller and two-hour dead-man watchdog.

This increment adds a minimal protected recovery core for `LOW`/`MEDIUM` risk
atomic file replacement. The root-owned controller creates durable state and a
backup before it arms `lifeos-rollback@<transaction>.timer`; mutation is denied
unless arming succeeds. The systemd timer invokes the separate rollback
executable every minute, including after boot, and checks the durable wall-clock
deadline. This avoids extending probation after reboot, and does not depend on
Governor or Engineer being alive.
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

## Production proof

The Governor provider-aware builder is an existing privileged deployment now
routed through `begin -> apply -> verify -> commit`. Its canonical hash and the
active Governor service are measured by the protected controller before commit.
Live transaction `governor-ai-routing-34032013540` committed successfully with
the watchdog armed before mutation. The harmless canary also proved the forced
rollback path end-to-end. This satisfies the required incremental deployment
approach without widening the controller into a generic root shell.

Transaction state is a root-owned durable audit surface. Human-facing progress
systems may render its state, component, risk, deadline, evidence and rollback
result, but they do not author commit evidence.

## Trust and bounded scope

Pi5/Watchman remains the runtime authority and canonical Git writer. The model
has no interactive root shell and cannot write the root-owned state directory.
The controller does not broaden package, database, container, credential,
systemd-unit or network authority. Those operation types are deliberately denied
until each has an operation-specific recovery design, independent verification,
bounded retry policy and live rollback proof. This is fail-closed scope, not an
unfinished generic authority promise.

Changing the protected recovery core requires an explicit A/B operation retaining
the known-good path. Ordinary deployment paths cannot overwrite or remove it.
