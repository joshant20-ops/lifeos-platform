# Roadmap

## Current priorities

1. Keep `lifeos-platform` authoritative and maintain immutable source identity in every runtime request.
2. Preserve the root broker plus protected transaction controller as the only privileged execution gate and retain auditable result evidence.
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

## Foundational corrections

- Record schemas and retention: **DEFINED** in `operations/records-retention.md`.
- Governor and privileged-boundary SLOs: **DEFINED** in `operations/control-plane-slos.md`.
- Z97 retirement checklist: **PUBLISHED** in `operations/z97-retirement.md`; retirement remains gated on live dependency evidence.
- System simplification map: **RECORDED** in `architecture/system-simplification-map.md`.
- Transactional-root first production increment: **COMPLETE**; broader operation types remain fail-closed until separately designed and proven.


## Queued maintenance — Predbat v9

- **Predbat v8.55.0 → v9.0.3 controlled upgrade** — queued for the governed runner after the current interactive build work. Treat this as a safety-sensitive energy-control upgrade, not an unattended blind update.
- Preflight: capture installed version, current Predbat status/mode, `apps.yaml` and relevant HA entity/config state; confirm a rollback path to v8.55.0; inspect current inverter/component configuration and verify no deprecated AppDaemon migration is being mixed into this change.
- Compatibility review: v9.0.0's major refactor is specifically GivTCP REST; this installation uses Enphase, so that headline refactor is not directly applicable. Octopus fixes in v9.0.x are relevant and should be retained. New `manual_soc_max` is optional and must not be enabled merely by upgrading.
- Execute: take/verify HA backup or equivalent rollback evidence, upgrade Predbat to v9.0.3 using its supported HA update mechanism, then wait for clean startup.
- Acceptance: prove Predbat reports v9.0.3 with no error status; tariff/Octopus inputs, PV/load/grid/battery sensors and plan populate; compare pre/post plan for unexplained material changes; verify existing battery control mode and limits are preserved; perform a bounded observation before allowing normal autonomous control. If validation fails, roll back to v8.55.0 and record aggregate diagnostics only.
- Do not expose secrets from `apps.yaml` or HA tokens in CI/log evidence.

- **Governor/HA Current AI workflow stale-state repair** — queued for governed runner. Reconcile historical Issue #7 / job `0bb4e8f8be4a` against current accepted GPU state; do not revive or execute the obsolete R580 migration. Clear/terminalise stale runtime state using the existing governed mechanism, then repair the producer/dashboard contract so terminal, superseded, or stale jobs cannot remain presented as the current workflow. Acceptance: dashboard no longer presents Issue #7 as active; current-workflow card shows only genuinely active work (or an explicit idle state); regression test covers blocked-terminal/stale/superseded records; no NVIDIA/driver/package/reboot mutation; preserve audit history rather than deleting evidence.

- **Full Home Assistant estate audit** — queued for governed runner, audit-first and read-only before repair. Scope the entire live HA program, not only LifeOS-owned cards: configuration/packages, integrations/devices/entities/helpers, dashboards/views/cards/resources, automations, scripts/scenes, templates, blueprints, AppDaemon/add-ons where present, MQTT discovery/retained state, Predbat/Octopus/Enphase energy paths, Alexa/notification paths, Matter devices, LifeOS/Governor/Tower entities, history/recorder behaviour, backups/update health, and all repo-managed HA deployment/adaptation scripts. Inventory live state versus GitHub desired state and identify configuration errors, unavailable/orphaned/duplicate entities, stale historical workflow state, broken dashboard references, disabled/dead automations, overlapping logic, unsafe actions, secrets leakage, hard-coded entity IDs/hosts, race/restart/idempotency problems, noisy loops, obsolete custom code, and functions already provided adequately by HA/OTS integrations. Preserve existing accepted Wave A capabilities and do not rebuild working OTS functionality. Produce a sanitised findings/evidence report ranked by severity and ownership, with exact proposed repairs and rollback. After the read-only audit, automatically repair normal user-owned/configuration defects through the governed Git/deploy path, validate HA configuration before restart/reload, verify affected dashboards/automations live, run regression/acceptance checks, and record remaining genuine human/credential/hardware boundaries. Never print secrets/tokens/private payloads. Do not update Predbat as part of the audit; its separately queued controlled v9.0.3 upgrade remains its own gated maintenance item.
