# Migration strategy

Migration is evidence-led and fail-closed. Pi5 remains the control plane during
every phase, and no migration step may bypass Watchman.

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
4. Prove Watchman-gated execution against an immutable revision.
5. Prove sanitised job history and observed-state evidence reach their separate
   non-authoritative repositories.
6. Validate affected services and rollback procedures.
7. Reconcile outstanding work and retire legacy systems only after all gates pass.

The detailed repository migration gates in `architecture/REPOSITORY_MODEL.md`
remain normative.

## TODO

- TODO: Record the owner and acceptance evidence for final Z97 retirement.
- TODO: Decide retention periods for migration evidence and preserved rollback
  artifacts.
