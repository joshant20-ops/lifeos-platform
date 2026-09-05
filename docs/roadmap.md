# Roadmap

## Current priorities

1. Keep `lifeos-platform` authoritative and maintain immutable source identity in every runtime request.
2. Preserve Watchman as the only privileged execution gate and retain auditable result evidence.
3. Continue user-facing capability delivery on top of the completed foundation and completed OTS/operations baselines.
4. Prefer established open-source capabilities; add custom components only when a documented gap and maintenance owner exist.
5. Retire migration-only systems after health, rollback and evidence gates pass.

## Capability status

- Foundation roadmap: **12/12 COMPLETE**.
- Capability Stage 1 — OTS rationalisation/custom-code purge: **COMPLETE 2026-09-05**. Live closure run `33965885337` on `lifeos-pi5` passed the active-runtime gate: 17 active containers were inventoried; no active Autoheal, Watchtower or Rundeck was present; Home Assistant, Mosquitto and Uptime Kuma were live. Historical proof/migration files remain as evidence and are not treated as active services.
- Capability Stage 2 — backlog/issue hygiene: **COMPLETE 2026-09-04**.
- Capability Stage 3 — production operations OTS audit: **COMPLETE 2026-09-05**. Durable restore rehearsal continues independently under issue #106 and does not reopen the base operations audit.
- Capability Stages 4–14: capability delivery roadmap; several already have partial implementations or dedicated issues.

## Governance outcomes

- Proposals, validation and personal-assistant work remain separately attributable.
- Worker communication remains file-, queue- or repository-based with explicit schemas and no direct runtime coupling.
- Sensitive processing remains within approved local privacy boundaries.
- Documentation and decision records stay aligned with deployed authority.
- OTS rationalisation is now a standing maintenance policy rather than a perpetually open migration stage.

## TODO

- Choose and document stable schemas and retention rules for proposal, audit and assistant queue records.
- Define service-level objectives for Governor and Watchman availability.
- Publish the Z97 retirement checklist after migration inventory is reconciled.
