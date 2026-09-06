# System simplification map

Updated 2026-09-06 from canonical configuration and governed live evidence.
Historical files are evidence, not proof of a live consumer. Deletion is permitted
only after the named runtime proof and rollback gate pass.

| Capability | Classification | Authoritative path and live consumers | Simplification / retirement | Risk, rollback and closure proof |
|---|---|---|---|---|
| Home automation and dashboards | KEEP_OTS / KEEP_NATIVE | Home Assistant; household users and automations | Keep HA as UI/state authority; one-shot Tower actions are buttons, not retained toggles; remove only dependency-free compatibility registrations | Snapshot HA config; config check, restart, three-dashboard audit and action semantics must pass |
| Energy optimisation | KEEP_OTS + KEEP_THIN_GLUE | Predbat and Enphase remain specialist control; Octopus tariff source; LifeOS Energy publishes one opportunity contract to HA/common attention | Retire the separate opportunity timer/service and generated JSON bridge; no parallel energy planner or notification framework | Preserve prior unit/config rollback; API, stable/deduplicated IDs, HA entity, attention path and Predbat/Enphase non-mutation proved in runs `34027204105` and `34027701388` |
| Tower power control | KEEP_NATIVE + KEEP_THIN_GLUE | HA momentary buttons -> MQTT -> Pi5 control bridge; Tower user `joshan` executes exact passwordless `/sbin/poweroff`; WOL uses canonical MAC | One governed path for shutdown and WOL; no persistent switch abstraction; retry WOL across NIC transition | Preserve prior bridge/config; exact-command sudo preflight, actual shutdown, bounded wake retries, SSH return, HA health and dashboard regressions |
| Privileged execution | KEEP_THIN_GLUE | Root-broker socket -> protected transaction controller -> independent rollback | Watchman runtime retired; no second policy daemon and no interactive model root | Fail closed; root-owned state, two-hour watchdog, independent evidence, commit and forced rollback proof |
| Engineering orchestration | KEEP_OTS + KEEP_THIN_GLUE | Semaphore/Ansible target with LifeOS policy client and bounded root interfaces | Rundeck shadow retired; custom queue/scheduler remains compatibility-only until Semaphore equivalence gates pass | Preserve historical evidence and old path until equivalence/restart/no-duplicate/rollback tests pass |
| Monitoring and restart | KEEP_OTS | Uptime Kuma, systemd and Docker restart policy | Autoheal/Watchtower absent from active runtime; do not reintroduce overlapping remediation | Live container/unit inventory and health regression |
| Backup and recovery | KEEP_OTS | Restic plus service-native backups and governed restore rehearsals | Keep one declared backup owner per dataset; no deletion based on duplicate filenames alone | Restore rehearsal, integrity proof and recovery-time evidence |
| Personal assistant/action routing | KEEP_NATIVE + KEEP_THIN_GLUE | Common attention/action contract; source systems retain private payloads | Retired PA audit scheduler remains historical; avoid new per-capability notification queues | Schema/privacy regression and end-to-end action provenance |
| Notifications | CONSOLIDATE | Common attention path is authoritative | WhatsApp and Alexa delivery remain explicit human/account integration boundaries (#103/#104), not foundation defects | Test only after user activation; no notification sent during foundation closure |
| AI/provider routing | KEEP_THIN_GLUE | Governor owns privacy/capability/cost policy; OpenHands is provider-neutral tooling; Codex is fallback | No second routing service; free-provider credentials remain an account boundary | Local-only cloud exclusion, health, deployed hash and routing acceptance run `34032103301` |
| Z97 | REVIEW_UNIQUE | Migration-only until dependency inventory is empty | No new authority; retire using `operations/z97-retirement.md` | Reversible power-down window, replacement restore proof and final dependency scan |

## Material reduction already proved

- Retired the live Watchman daemon while preserving the narrower broker/controller/watchdog safety boundary.
- Removed the duplicate Energy Opportunity scheduler and JSON bridge while retaining specialist Predbat/Enphase control.
- Replaced misleading Tower switch semantics with momentary actions and reduced shutdown to one bounded SSH command.
- Kept Autoheal, Watchtower and Rundeck out of the active production estate.

The remaining compatibility and migration artifacts are deliberately classified,
not silently deleted: current runtime reality and dependency proof must precede
removal. WhatsApp/Alexa activation and any user-selected cheap-positive energy
threshold remain outside foundational closure.
