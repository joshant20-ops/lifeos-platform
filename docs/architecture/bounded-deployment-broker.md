# Bounded deployment broker

LifeOS uses the local Unix socket `/run/lifeos-root-broker.sock` as its reusable
privilege boundary. The Engineer publishes reviewed source through the canonical
Pi5 Git workflow. The Governor accepts only an exact `DEPLOYMENT_OPERATION`
intent, maps it through a constant allowlist, and sends only `operation`,
`job_id`, and `target` to the broker. The broker then independently requires a
fresh root-owned approval containing verifier, policy, commit, publication, and
exact source-hash evidence.

Supported deployment transactions are `deploy-engineer-runtime`,
`deploy-autonomous-agent`, and `deploy-backlog-runner`. Each has a compiled
source/destination/unit/health manifest. The backlog transaction installs the
canonical worker and fixed units but requires its timer to remain inactive;
enabling it is deliberately outside this deployment milestone until post-deploy
behavior is verified. `restart-approved-unit` remains a separate constant unit
allowlist. Systemd daemon reload is internal to a transaction that installs a
mapped unit and is not exposed as a caller-selectable operation.

## Threat model and rejected authority

The broker is local Unix-socket only and is not a shell or sudo replacement. It
rejects unknown operations, malformed or extra fields, arbitrary commands,
arguments, environment, paths, destinations, hashes, and non-allowlisted units.
Canonical sources must be tracked regular non-symlink files contained in the
repository, owned safely, byte-identical to an approved SHA256, and from a clean
HEAD equal to `main` and `origin/main`. Source bytes are pinned through an
`O_NOFOLLOW` descriptor before installation to close the hash/install race.

Every transaction is serialized and job IDs are replay-protected by immutable
audit creation. Existing files are backed up before atomic replacement. A
restart, health, timer-state, or reload failure restores prior files, reloads
systemd when relevant, rechecks service health, and records distinct deployment
and rollback results.

## Adding a service

Normal jobs need no new sudo launcher once an operation is live: they emit an
exact allowed intent, the Pi5 publishes it, the independent approval is created,
and the Governor invokes the broker. Adding a future service requires editing
the broker's fixed manifest, committing its canonical unit files, adding
adversarial and rollback tests, and bootstrapping the broker change. That is a
privilege-boundary review because it expands which root-owned bytes or services
automation may replace or restart. Recovery uses the transaction audit and
root-owned backup; a failed automatic rollback must remain fail-closed for an
operator review.
