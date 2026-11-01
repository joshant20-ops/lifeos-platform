# Unified LifeOS Roadmap

**Active programme authority — reconciled 1 November 2026.**

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
| Matter server | Original container and HA integration restored; this does not establish curtain device-level acceptance. |
| Monitoring | Eleven Uptime Kuma monitors accepted, including persisted failure/recovery history. Notifications unconfigured; Predbat's private loopback UI excluded. |
| SMART | #1995 complete: explicit SAT fixes mistaken NVMe autodetection; health reporting passed with zero reallocated/pending/uncorrectable sectors. |
| Personal Assistant | #1498 read-only EmailOps sample and authenticated previews pass; overall capability remains unfinished. |
| Engineering MVP | #935 remains NOT PASS; unchanged fixture/model/hardware boundary applies. |
| Energy | #1071 native-input audit, economic comparison and shadow evaluation remain outstanding. |

Storage terminology correction: the external drive is a WD1600BEVT SATA **HDD**, not an SSD. Historical paths/checkpoint labels may say SSD. Data remains distributed across external HDD, SD and NAS; no claim that all databases moved. Recovery copies are on-device, not proof of an off-device restore. SMART reporting is not a surface scan or future-failure guarantee.

Evidence: [storage acceptance](https://github.com/joshant20-ops/lifeos-platform/actions/runs/40425357225), [monitoring acceptance](https://github.com/joshant20-ops/lifeos-platform/actions/runs/40427278190), [SMART repair](https://github.com/joshant20-ops/lifeos-platform/actions/runs/40591258267), [latest audit](https://github.com/joshant20-ops/lifeos-platform/actions/runs/40386695471), [PA served review](https://github.com/joshant20-ops/lifeos-platform/actions/runs/39991994962).

## Current focus — Now / Next / Later

### NOW

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
