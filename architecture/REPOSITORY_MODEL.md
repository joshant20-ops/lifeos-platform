# LifeOS repository authority model

## Current model

LifeOS uses three repositories with distinct authority:

1. `lifeos-platform` is the sole desired-state and deployment authority.
2. `lifeos-jobs` is a sanitised, durable engineering audit trail.
3. `lifeos-snapshots` is sanitised observed-state evidence.

The complete data contract, visibility rules and trust flow are normative in
[`docs/architecture/three-repo-model.md`](../docs/architecture/three-repo-model.md).
The accepted transition from the older relay design is recorded in
[`architecture/decisions/three-repository-authority.md`](decisions/three-repository-authority.md).

Pi5 remains the always-on control plane and canonical Git writer. Live queues,
locks, rapidly changing job state and raw runtime output stay local. Repository
exports are deliberately sanitised; none of the three repositories is a place
for credentials, private documents, personal data, Home Assistant history or
arbitrary logs.

## Execution identity

Every runtime execution request must identify:

- canonical repository: `joshant20-ops/lifeos-platform`
- immutable source commit SHA
- canonical script path
- canonical script SHA-256
- target host
- job class
- timeout

A thin, Pi5-owned execution wrapper may verify and execute canonical content,
but must not contain a divergent copy of business logic. Watchman remains the
runtime policy gate.

## Feedback loop

1. An engineering actor proposes a change to `lifeos-platform`.
2. Independent validation records evidence for the immutable revision.
3. Pi5 publishes accepted canonical changes and controls runtime execution.
4. Watchman permits or rejects the requested runtime action.
5. Pi5 exports only sanitised job history to `lifeos-jobs` and sanitised
   observed-state evidence to `lifeos-snapshots`.
6. Evidence informs the next proposed canonical change; it never becomes
   deployment authority itself.

## Migration gates

Legacy repositories or relays are not retired until all applicable gates pass:

1. Inventory their authoritative, generated, private and retired content.
2. Import only authoritative, cloud-safe source and documentation.
3. Confirm Pi5 has a clean, current canonical checkout.
4. Prove Watchman-gated execution against immutable `lifeos-platform` content.
5. Prove sanitised job and observed-state exports reach their repositories.
6. Validate affected services and rollback expectations.
7. Reconcile outstanding work before retiring a legacy path.

Migration fails closed at the first failed gate. Runtime paths may remain in
place during migration, but they do not gain source or deployment authority.
