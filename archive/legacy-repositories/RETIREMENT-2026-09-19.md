# Final legacy repository retirement — 2026-09-19

This record closes the legacy repositories left over from the earlier two-repository transition while retaining the accepted three-repository authority model.

## Retained authoritative repositories

- `lifeos-platform` — desired state and sole deployment authority.
- `lifeos-jobs` — sanitised durable engineering audit trail.
- `lifeos-snapshots` — sanitised observed-state evidence.

## Legacy repositories

### LifeOS-Energy
All implementation files on the legacy default branch were compared with `lifeos-platform/energy/`. Every implementation/data-placeholder file is byte-identical. The only differing file is the legacy README, whose purpose is migration/retirement guidance; it is preserved under this archive. No implementation is being discarded.

### lifeos-pi-control
The repository contains only relay policy/ownership documentation, CI metadata, ignore rules, and one old pending diagnostic manifest. The relay documents and pending manifest are preserved under this archive. They are historical evidence only and do not regain runtime or deployment authority.

### lifeos-control
The repository contains only a README declaring the repository retired. That README is preserved under this archive.

## Retirement rule

The three legacy repositories may be deleted only after this migration commit is merged. Their deletion does not change the three-repository authority model. Runtime queues, locks, raw output, secrets and private data remain outside Git as required by the repository model.
