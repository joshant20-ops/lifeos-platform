# Unified LifeOS Roadmap

**Active programme authority — reconciled 16 November 2026.**

This file sets programme priorities. Issue #24 is the execution index; individual issues retain acceptance evidence. Former stage/wave/P/M plans are historical, not independent instructions to start work. Current runtime evidence and explicit owner decisions outrank stale plans.

## Direction

Deliver useful household capabilities with minimal maintenance. Organise the programme around **user-facing products and outcomes**, while specialist applications retain their own authority.

### Product map

- **Core / Reliability** — storage, recovery, monitoring, networking and security.
- **Projects & Assistant** — Projects, Attention, email, documents, calendar and Ask LifeOS.
- **Finance** — accounts, transactions, budgets, goals, forecasting and recommendations.
- **Home** — Home Assistant, devices, security and household automation.
- **Energy** — Predbat, Enphase, tariffs, EV integration and economic optimisation.
- **Media** — audiobook/download/library capabilities where selected.
- **Engineering / Platform** — Codex-assisted development, local runtime AI, OpenHands and later adaptive learning.

LifeOS is the **coordination, correlation, intelligence and attention layer**, not a replacement for specialist applications. Home Assistant owns household devices/presentation; Predbat optimisation; Enphase hardware integration; Octopus tariffs; Paperless documents; email/calendar providers their source records; the Finance application its financial ledger; OpenHands engineering execution where accepted. GitHub owns canonical source. The Pi control boundary owns privacy, credentials, bounded privilege, deployment, independent verification and evidence.

### Shared LifeOS concepts

Use a small shared organisational model without creating a universal datastore:

- **Project** — finite outcome with a lifecycle, e.g. buy/collect a vehicle or complete a trip.
- **Area** — ongoing responsibility, e.g. House, Cars, Homelab or Energy.
- **Routine** — recurring obligation, e.g. MOT, insurance renewal or boiler service.
- **Reference** — useful evidence/information with no current obligation.
- **Attention** — common derived output across specialist systems: `ACTION / WAITING / WATCH / INFORMATION / COMPLETE`.

A Project is the user-facing representation of a persistent LifeOS matter. Existing authorities keep their records; LifeOS derives relationships between them. A project may therefore correlate EmailOps evidence, Paperless documents, Finance records, Home Assistant state, calendar events and other authoritative sources without copying their authority.

Use **outcome-first organisation throughout Projects & Attention**, including small and single-source matters. A retailer, lender, payment provider and courier can contribute to one outcome; sender/company is not the organising boundary. Expose a source-backed consolidated timeline wherever accepted evidence allows it. Unconfirmed outcomes and uncertain links remain explicit; do not fabricate goals, historical events or completion to fill gaps. This does not require new Areas/Routines/Reference infrastructure during #1498.

Automatic grouping improvements should reuse accepted reply ancestry and explicit split-parcel/order evidence, with whole-component case/order conflict checks and relationship provenance. Conversation grouping remains a candidate outcome; it does not prove completion. Verify actual consumed group counts and corpus quality, not only synthetic replay or successful deployment.

Reconcile obligation state through one shared source-backed policy across outcomes. Preserve the specific action/issuer/reference scope of each accepted observation, so a later fact can resolve that obligation without closing other steps in the same project. Reuse the existing PA publisher and owner overlay; unresolved evidence remains explicit. Tesla, retailer/courier, household and other cases are acceptance examples, not separate hard-coded programmes.

Every Project should have a clear outcome and close when that outcome is reached. Permanent responsibilities belong under Areas rather than becoming never-ending projects.

### AI boundary

Use cloud development intelligence such as Codex to design, implement, test and debug where authorised, but keep private production LifeOS data local. Production classification, correlation, summarisation and answering remain local-first. Build provider boundaries and accepted test corpora so stronger local AI can replace or improve runtime reasoning without redesigning the product.

Prefer installed functionality, native configuration/integrations, mature open-source software, then thin glue. Add bespoke components only for a demonstrated gap. No general backend, duplicate task database, notification framework or AI-agent layer for hypothetical consumers.

## Verified checkpoint

| Outcome | Evidence and limits |
|---|---|
| House Status / Doorbell | #1583 accepted Live v35 on 19 Oct; no longer DEV-only. |
| Wake-aware AI endpoint | #1588 complete; Tower lifecycle remains controller-owned. |
| Storage recovery | #1760 complete for selected service set after actual reboot, native application checks and write/readback checks. Fifteen running services, seven legacy services retained stopped. Original SD and recovery copies preserved. |
| Storage reliability, 12 November 2026 GMT | #2072 and #2074 remain open. Mosquitto reopened its live log after rotation. The authorised HDD cleanup released 11,132,416,000 allocated bytes. The Pi then completed all 42 local metadata review batches and reverified the 11,132,338,594-byte encrypted NAS archive. AdGuard configuration recovery and encrypted archive readback passed. The backup pilot restored seven files in isolation, and the Pi profiled 69,063 backup groups with zero deletion eligibility. The daily snapshot now publishes disk and inode reserves, with fresh Pi readback at 10:18 GMT. Allocation coverage remains blocked by mount-root permissions. Current Tier 0 recovery access, MQTT caller attribution and wider lifecycle acceptance remain open. |
| Matter server | Original container and HA integration restored; this does not establish curtain device-level acceptance. |
| Monitoring | Eleven Uptime Kuma monitors accepted, including persisted failure/recovery history. Notifications unconfigured; Predbat's private loopback UI excluded. |
| SMART | #1995 complete: explicit SAT fixes mistaken NVMe autodetection; health reporting passed with zero reallocated/pending/uncorrectable sectors. |
| Personal Assistant | #1498 read-only EmailOps sample and authenticated previews pass; overall capability remains unfinished. |
| Engineering MVP | #935 remains NOT PASS; unchanged fixture/model/hardware boundary applies. |
| Energy | #1071 native-input audit, economic comparison and shadow evaluation remain outstanding. |

Storage terminology correction: the external drive is a WD1600BEVT SATA **HDD**, not an SSD. Historical paths/checkpoint labels may say SSD. Data remains distributed across external HDD, SD and NAS; no claim that all databases moved. Recovery copies are on-device, not proof of an off-device restore. SMART reporting is not a surface scan or future-failure guarantee.

Evidence: [storage acceptance](https://github.com/joshant20-ops/lifeos-platform/actions/runs/40425357225), [monitoring acceptance](https://github.com/joshant20-ops/lifeos-platform/actions/runs/40427278190), [SMART repair](https://github.com/joshant20-ops/lifeos-platform/actions/runs/40591258267), [latest audit](https://github.com/joshant20-ops/lifeos-platform/actions/runs/40386695471), [PA served review](https://github.com/joshant20-ops/lifeos-platform/actions/runs/39991994962).

The November storage evidence is recorded in the [Pi inventory run](https://github.com/joshant20-ops/lifeos-platform/actions/runs/43193896401), [authorised MQTT release](https://github.com/joshant20-ops/lifeos-platform/actions/runs/43060646029), [full local archive review](https://github.com/joshant20-ops/lifeos-platform/actions/runs/43194508746) and [snapshot deployment](https://github.com/joshant20-ops/lifeos-platform/actions/runs/43199132248).

## Active standalone Paperless delivery — master milestones (16 November 2026)

This is the sole active detailed Paperless checklist within the programme roadmap; M identifiers are tracking identifiers, not separate projects. #2122 owns processing/intelligence acceptance, #652 owns historical backlog evidence, #2072/#2074 own shared storage reliability. Supersedes earlier chat checklists; preserve historical issues and evidence. The later owner-selected intake work supersedes the earlier intake deferral, but not quality/security acceptance. #2123 engineering recovery is a separate deferred lane unless a demonstrated Paperless dependency blocks delivery; do not require OpenHands acceptance to use independently proven local inference.

Owner-reported CLI checkpoint (not independently reproduced by GitHub): 1,490 Gmail All Mail records labelled Imported, zero unlabelled; 2,772 accessible original paths; 876 legacy extracts confirmed; 11 historical failed tasks investigated. Label coverage is not proof of message/attachment completeness. Filename matches plus prior pilot evidence account for five failures; two synthetic failures, two likely inline icons and two older Word files remain to reconcile. No private identities, text or filenames belong in repository evidence. Counts are point-in-time.

| ID | Function / immediate state | Acceptance owner |
|---|---|---|
| M01 | Resource monitoring — functional | #2072 / #2074 |
| M02 | Adaptive worker governor — partial | #2122, shared reliability |
| M03 | Local AI gateway — partial, new changes pending live acceptance | #2122; historical #1588 |
| M04 | Format conversion — functional | #2122 |
| M05 | Historical Gmail label coverage — functional | #652 / #2122 |
| M06 | Independent adaptive loader — partial | #2122 |
| M07 | Original path availability audit — functional | #652 |
| M08 | Failure recovery — partial | #2122 / #652 |
| M09 | Legacy retirement — partial | #2122; preserve #1498 dependencies |
| M10 | Deduplication — outstanding | #652 |
| M11 | IQ semantic search — partial | #2122 |
| M12 | Intelligent classification — partial | #2122 |
| M13 | Persistent source-backed knowledge — outstanding | #2122 |
| M14 | Autonomous operation / production sign-off — outstanding | #2122; #2074 for storage |

Functional milestones above are not production sign-off. Baseline: 4 functional, 7 partial, 3 outstanding. Do not count overlapping historical ledger or deploy tickets as additional requirements.

### Owner priority clarification — 18 November 2026

**Full development remains authorised.** The 17 November simplification/architecture freeze means *no speculative new shared frameworks or unnecessary production changes*, not a blanket halt on existing approved product development. Paperless is the immediate delivery priority and should reach correct, reliable everyday operation as soon as practicable. Finance, Projects & Assistant, and other owner-selected capabilities may advance in parallel when isolated from Paperless's critical path and resource budget; serialize changes touching shared Pi resources, credentials, network or storage.

**Paperless evidence window:** after correcting immediate defects and demonstrating isolated recovery, run an observed multi-day acceptance period (duration evidence-driven, not an automatic fixed delay). During observation continue useful engineering: verify incoming mail and attachments, queue/worker behaviour, searchable originals, IQ indexing/classification with measured quality, backup freshness, alerts and restart/failure handling. Investigate failures promptly; do not mark production PASS merely because time elapsed. Do not postpone urgent safe fixes to wait out the window. Avoid unnecessary downtime and preserve AdGuard/Predbat/Home Assistant.

**Recovery evidence — 18 November 2026:** [Pi run 44321972100, attempt 2](https://github.com/joshant20-ops/lifeos-platform/actions/runs/44321972100) restored PostgreSQL (74 tables, 327 indexes, 304 constraints), checked all 2,772 original files with zero missing/checksum mismatches, passed both extracted IQ SQLite integrity checks and native Chroma queries (2 collections, 10,671 embeddings, 2 query tests). The run failed during temporary IQ cleanup; #2131 implements a scoped cleanup correction; live cleanup acceptance remains pending. [Earlier run 44323674044](https://github.com/joshant20-ops/lifeos-platform/actions/runs/44323674044) stopped on TIER0_HEALTH_UNAVAILABLE after five archive hashes. Subsequent diagnostic [Pi run44375658081](https://github.com/joshant20-ops/lifeos-platform/actions/runs/44375658081) identified storage_reserve as the sole failed check; network/AdGuard checks passed. Available15,252,385,792bytes was below required15,639,126,835bytes. #2134 added scoped cleanup of verified disposable restores after rehashing the original checkpoint. [Pi run44379203633](https://github.com/joshant20-ops/lifeos-platform/actions/runs/44379203633) reverified five hashes and healthy cleanup checks but refused a read-only ancestor bind reference. No cleanup or restored reserve is yet accepted. Diagnose/correct this boundary through independent review and rerun the governed workflow; full Tier0 reserve gate remains mandatory before new staging. Historical-email recovery (408 extracted files, no direct EML suffixes), application startup, IQ component compatibility and encrypted off-device copies remain open. Preserve the checkpoint.

**Recovery acceptance — 18 November19:24GMT:** [Actual Pi run44379752567](https://github.com/joshant20-ops/lifeos-platform/actions/runs/44379752567) passed DATA_RESTORE_PASS and full Tier0 health. Reverified all five checkpoint archives; removed2verified disposable rehearsal stages, increasing available space15,240,806,400→17,229,164,544bytes before new testing. Restored PostgreSQL, matched all2772original checksums, passed both extracted SQLite integrity checks and nativeChroma2collections/10671embeddings/2queries. IQtemporarycleanup and PostgreSQLstop PASS; successful run staging/container cleanup PASS. Original checkpoint and root reports preserved. Full application restoration, historical408file recovery, IQapplication compatibility and encrypted automated off-device backup coverage remain outstanding. Normal ingestion untouched; classification accuracy remains a separate gate. Next use the same governed rehearsal for native app startup, access-control, listing, original retrieval and disposable native-index/search tests; never connect it to live ingestion or integrations.


**IQ scheduler Stage 1 — 19 November 2026:** Owner requested source finalisation only; no deployment or automation activation. Candidate branch `fix/paperless-iq-bounded-classification-stage1` adds finite runs, pending review backpressure, atomic automatic deduplication, failure backoff, resource gates and suggestion-only callbacks. Tests and review evidence accompany the branch; [deployment/rollback procedure](../patches/paperless-iq/DEPLOYMENT.md) records remaining runtime preflights. M12 stays partial: no live automatic classification or tagging accuracy acceptance is claimed. Preserve the existing pending suggestions and `auto_apply=False`. Stop after Stage 1 pending a separate owner instruction.

### Engineering simplification and acceptance gate — 17 November 2026

Owner-directed implementation policy following the viability audit:

- **Stop expanding the LifeOS architecture** until the existing standalone services are proven recoverable, reliable and useful. This does not cancel previously approved independent Finance work; it prevents speculative cross-service frameworks and new runtime dependencies.
- **Paperless first:** preserve the current working stack and complete isolated recovery, backup encryption/off-device failure separation, capacity safeguards, Gmail integrity, loader/governor reliability, IQ acceptance and production sign-off. Keep the 14 existing milestones and issue ownership authoritative; do not create a second roadmap.
- **Simplify with evidence:** inventory each custom Paperless helper, its native/OTS alternative, measured benefit, dependencies, failure modes, and retirement/rollback plan. Retain only components with a demonstrated need; do not remove a live helper merely because it is custom.
- **Autonomy boundary:** allow unattended observation, isolated tests and explicitly bounded/reversible operations with durable logs. Require risk-appropriate authorization, rollback and runtime verification for production mutations. Never let an agent self-authorize destructive cleanup, privilege expansion, unbounded deployment or protected-service disruption.
- **Acceptance over activity:** passing source tests or creating a GitHub commit is not deployed production acceptance. Measure document integrity, search/classification quality, restoration, resource impact, alerts and sustained unattended processing with explicit denominators and evidence.
- **Safety:** AdGuard Tier 0, Predbat and Home Assistant are protected. No uncontrolled reboot, Docker prune, destructive deduplication, or exposure of private data. Keep rollback evidence and prevent retired deployments from reappearing.
- **Recovery checkpoint (owner CLI, 16 Nov):** `/mnt/docker-data/paperless-recovery/20261116-164147-XuCaRz` contains `paperless.dump`, `media.tar`, `configuration.tar`, `historical-email.tar`, `paperless-iq.tar` and `SHA256SUMS`; five checksum checks passed, total 825 MB. Live IQ SQLite integrity checks passed and IQ restarted; protected services remained running. **No isolated restore yet; unencrypted and co-located with Pi; database/media snapshots not simultaneous.** Never report this as production recovery proof or delete it before a separate verified copy.
- **Next executable gate:** inspect storage/mounts, stage the existing recovery set read-only, validate extracted IQ SQLite and media references, restore PostgreSQL into an isolated instance, record findings; then harden Restic with encryption and separate failure boundary. Do not modify live data during rehearsal.

### Latest M08 evidence — owner-reported 16 November 2026

- All 1,534 archived EML files parsed successfully; zero read errors in this audit.
- Both failed image filenames occur in three archived emails each; original payloads are present, but exact failed-task identity and inline disposition still require verification.
- Flight attachment filenames occur inside the known recovered email; exact byte comparison against separately archived originals remains pending.
- Neither outstanding older Word filename was found in archived EML; source recovery remains unresolved. Do not claim recovery or delete failure evidence.
- Next: compare attachment hashes locally, then reconcile legacy wrappers. No private filenames, message contents or hashes exported.

### Milestone acceptance checklist

- [x] M01: Prometheus/Node Exporter and HA CPU, RAM, temperature, SD/HDD/NAS sensors; Grafana removed; live samples observed.
- [x] M02: separate PI worker control and loader; target CPU 75%; grow/shrink and zero/recovery exercised; protect critical services.
- [ ] M02: resolve busy-worker shrink/recycling limitations; failure/restart safeguards; persist resource priorities and validate sustained load.
- [x] M03: existing wake-aware Ollama gateway; embedding endpoint/model; MQTT5 expiry and renewal implemented in source; regression tests reported passing.
- [ ] M03: safely deploy pending gateway fixes; reconcile obsolete retained leases without broker restart; prove long inference protection, expiry and live acceptance.
- [x] M04: Tika/Gotenberg, EML and Office conversion enabled; searchable email test and original attachment retention demonstrated in pilot.
- [x] M05: native mail rule, original EML and true attachments, no historical age limit, Imported label coverage; tested read-state preservation.
- [x] M06: independent loader, actual worker count, measured average, ceil(180/average seconds × workers), nominal 30-second schedule, singleton lock and CLI start/stop.
- [ ] M06: independent 30-second active queue observation, five-minute idle Gmail polling with automatic active resumption, new-mail acceptance; native rule remains disabled while loader owns ingestion.
- [x] M07: original path availability audit at baseline; corpus inventory and legacy wrapper count.
- [x] M08: investigate all eleven failure causes, correct pilot permission issue and identify five recovered candidates.
- [ ] M08: verify recovered bytes, inline image retention and older Word source availability; safe retry/quarantine, failure notification and escalation; verify message/attachment completeness independently of label.
- [x] M09: old archive timer disabled; legacy EmailOps deployment retired in source; conflicting native assignment/matching disabled.
- [ ] M09: live retirement and trigger/reference audit; retain legacy important-information pipeline until proven replacement; prevent redeployment and preserve rollback/evidence.
- [ ] M10: match all 876 wrappers to EML using identity/content evidence; report ambiguous/unmatched; preserve metadata/links; prove backup/restore; owner approval before destructive removal; reconcile IQ.
- [x] M11: IQ connected with local reasoning and embeddings, semantic index and live reindex webhook, progressing index.
- [ ] M11: complete retained corpus index, stale/missing entries audit, representative semantic search/discovery, restart/index recovery and access controls.
- [x] M12: naming/type/correspondent/tag policies and review prompts; pilot proposals; autoapply disabled.
- [ ] M12: stale pilot reconciliation; independent stratified reference sample (~100), OCR/text quality, type/correspondent/date/amount/reference accuracy, search recall and duplicate precision; report denominators/abstentions; set safe autoapproval gates, classify backlog and newly arriving documents, avoid metadata proliferation. Preserve #2122 proposed thresholds (processing ≥99%, type/correspondent ≥95%, financial ≥99%, date ≥98%, originals 100%, cloud disclosure zero); do not claim population accuracy from sample.
- [ ] M13: evaluate native IQ Memories/Discovery first; persistent source-linked facts, confidence, conflicts/supersession, expiry, deduplication, review/correction, incremental updates and restart proof; retire legacy only after equivalent outcome accepted.
- [ ] M14: NAS/manual intake and export freshness, mobile usability, archive/original integrity, backup/isolated off-device restore, capacity safeguards, converter isolation positive/negative tests, monitoring/alerts, restart/recovery and end-to-end standalone acceptance; canonical runtime/config and controlled boot persistence; safe synthetic cleanup; operational documentation and acceptance evidence.

Execution: M08 → M10 → M06 → M02 → M03 → M11 → M12 → M13 → M09 → M14; prioritize actual safety incidents and prerequisites, allow already-running safe background processing. AdGuard Tier 0 and Predbat untouched; no uncontrolled reboot, prune or destructive changes. Local-only private processing, native/OTS first, sole owner per capability, detached long jobs, serialized production changes. GitHub code/aggregate evidence only. Production completion requires consumed runtime, relevant regression/failure tests, rollback, durable config and evidence, retirement where applicable.

Historical deployment tickets and ledger entries remain evidence/demand-led until individually proven obsolete or duplicate. Wider active/deferred portfolio remains below; standalone Paperless is the selected delivery focus, not a new parallel roadmap.

## Current focus — Now / Next / Later

### NOW

**Owner-selected priority — 14 November 2026: standalone Paperless optimisation.** Temporarily deprioritise broader LifeOS integration. Preserve existing integrations, but require no new LifeOS runtime dependency. Native Paperless capabilities first; private document processing stays local. The fresh read-only [runtime audit](https://github.com/joshant20-ops/lifeos-platform/actions/runs/43629088828) verified three healthy containers, consistent NAS mounts, authenticated document listing and media retrieval. [15 November native audit](https://github.com/joshant20-ops/lifeos-platform/actions/runs/43726512687) verified running 3.1.2 and 942 documents, with 922 missing type, 857 untagged and no additions in 30 days. One enabled mail rule had zero recorded processed messages. Native task history, NAS intake and export freshness need further evidence. Backlog quality, isolated restoration, AI, mobile usability and automatic maintenance remain open. Historical P0–P10 acceptance remains historical; it does not establish this expanded standalone scope. #652 retains backlog acceptance. Storage protection and AdGuard remain mandatory constraints.

1. **Projects & Assistant — #1498.** Finish the existing PA/matter capability as a Projects + Attention experience. Keep the sole reconciler/task projection authoritative during #1498. Add derived project grouping/timeline/status rather than a second task manager/database. Complete representative classification quality, real multi-message/multi-thread grouping, lifecycle/completion, user overrides and phone/user acceptance. Initial project states: `ACTION / WAITING / WATCH / INFORMATION / COMPLETE`.
2. **Finance — #17, resumed by owner.** Finance is active again. Continue the self-hosted finance product already under development: authoritative accounting model, transactions, budgets with carry-forward, goals, forecasting and recommendations. Keep financial data local; distinguish calculated facts from suggestions; integrate with LifeOS Attention later rather than requiring the user to constantly inspect a finance dashboard.
3. **Runtime simplification / reliability cleanup.** Finish already-selected retirement/cleanup work only where it removes a proven duplicate/stale runtime dependency. Preserve rollback/data and require live acceptance; do not let historical cleanup displace user-facing delivery.

### NEXT

4. **Ask LifeOS / Proactive Intelligence.** Query Projects, Attention and accepted specialist sources with provenance/confidence. Target questions include: “what needs me?”, “what am I waiting for?”, “what changed?”, “what is due soon?”, “what evidence do I have for X?” and project-specific status questions. Reuse accepted authorities/read adapters; no universal datastore first.
5. **Energy — #1071.** Audit deployed native inputs and authority boundaries, quantify historical/replay economics and prove any proposed native-setting improvement before changing live control. Predbat remains optimiser; no duplicate controller.

### LATER / EVIDENCE-DRIVEN

6. **Adaptive capability learning — #1772.** Address demonstrated workload failures with existing tools/configuration first. Model/hardware expansion requires accepted evidence and its existing approval boundary.
7. **Broader engineering autonomy.** Engineering MVP #935 remains a separate R&D acceptance lane and is NOT PASS at Level 2. It does not block Projects, Finance, Ask LifeOS or Energy. Do not advance Levels 3/4 merely because infrastructure exists.

Serialize production changes when work touches shared components. Independent discovery/development may run in isolated lanes.

## Reliability and maintenance backlog

- Repair the two invalid OpenHands workflow definitions; scoped LifeOS CI success does not mean all workflows are green.
- Monitoring notification delivery remains unconfigured and needs a selected delivery destination before activation.
- Off-device restore assurance remains outstanding; do not delete recovery copies or repeat storage cutover/finalization as routine cleanup.
- Treat #883/#1137/#1024 and historical ledger cleanup as demand-led maintenance: act when they block a capability, remove meaningful burden or fix a demonstrated defect. Preserve evidence and prove dependencies before retiring code/services.
- Z97 retirement, broader autonomy, hardware expansion, new dashboards and curtain device acceptance remain deferred unless explicitly selected and their gates pass.

## Finance — active again

The 27 October 2026 deferral is historical. The owner subsequently resumed Finance and active development has started. #17 is therefore part of the current programme again.

Current product direction is a secure self-hosted finance application with separate real-account and virtual-category accounting, immutable dated events, continuous category carry-forward, configurable budgets, multiple goals, forecasting and recommendations. Existing prototype/accounting work must be treated as implementation progress, not production acceptance until its current repository/runtime evidence is reconciled.

Finance remains a specialist authority. LifeOS should consume useful derived finance Attention — for example a goal projected to miss its target or a material budget exception — rather than duplicate the ledger.

## Programme outcome and measurement

Measure success by **administration and attention removed from the owner**, not by code volume or number of services. Useful future measures include obligations identified, items safely treated as waiting/information, false alerts, missed obligations, decisions requested, automated handling and estimated administration avoided.

## Completion and safety

CI/merge/deployment alone is not completion. Require actual consumed-runtime acceptance, relevant regression checks, preserved recovery/rollback and durable evidence. Prefer read-only/shadow proofs first. Preserve private data locally. Do not reboot, remove recovery data, alter energy control, change approved AI models/hardware or introduce a new authority merely to make an acceptance gate pass.

Success is useful behaviour delivered per component maintained, with less household administration and attention.

