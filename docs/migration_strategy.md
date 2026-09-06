# Migration strategy

Migration is evidence-led and fail-closed. Pi5 remains the control plane during
every phase, and no migration step may bypass the root broker and protected
transaction boundary.

## Principles

- Inventory before moving or retiring anything.
- Move authority into `lifeos-platform`; do not create competing source copies.
- Keep transport wrappers thin and identify immutable canonical revisions.
- Validate health and rollback at each boundary before advancing.
- Preserve legacy state until replacement behavior and returned evidence are
  proven.
- Keep secrets, personal information and private documents outside repository
  history and cloud workflows.

## Sequence

1. Classify legacy content as authoritative, generated, private or retired.
2. Import only authoritative, cloud-safe source and documentation.
3. Validate the canonical checkout and control relay on Pi5.
4. Prove root-broker-gated execution against an immutable revision.
5. Prove sanitised job history and observed-state evidence reach their separate
   non-authoritative repositories.
6. Validate affected services and rollback procedures.
7. Reconcile outstanding work and retire legacy systems only after all gates pass.

The detailed repository migration gates in `architecture/REPOSITORY_MODEL.md`
remain normative.

## Governed closure

- Z97 ownership and final acceptance evidence are required by
  `operations/z97-retirement.md`.
- Migration evidence and rollback artifacts follow
  `operations/records-retention.md`; a capability-specific policy may retain them
  longer but never silently shorten the stated recovery window.
