# Roadmap

## Current priorities

1. Keep `lifeos-platform` authoritative and maintain immutable source identity in
   every runtime request.
2. Complete the gated move to the two-repository model described in
   `architecture/REPOSITORY_MODEL.md`.
3. Preserve Watchman as the only execution gate and retain auditable result
   evidence.
4. Prefer established open-source capabilities; add custom components only when
   a documented gap and maintenance owner exist.
5. Retire migration-only systems after health, rollback and evidence gates pass.

## Governance outcomes

- Proposals, validation and personal-assistant work remain separately attributable.
- Worker communication remains file-, queue- or repository-based with explicit
  schemas and no direct runtime coupling.
- Sensitive processing remains within approved local privacy boundaries.
- Documentation and decision records stay aligned with deployed authority.

## TODO

- TODO: Choose and document stable schemas and retention rules for proposal,
  audit and assistant queue records.
- TODO: Define service-level objectives for Governor and Watchman availability.
- TODO: Publish the Z97 retirement checklist after migration inventory is
  reconciled.
