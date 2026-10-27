# Unified LifeOS Roadmap

**Active programme authority — reconciled and adopted 27 October 2026.**

This file sets programme priorities. Issue #24 is the execution index; individual issues retain acceptance evidence. Former stage/wave/P/M plans are historical, not independent instructions to start work. Current runtime evidence and explicit owner decisions outrank stale plans.

## Direction

Deliver useful household capabilities with minimal maintenance. Prefer installed functionality, native configuration/integrations, mature open-source software, then thin glue. Add bespoke components only for a demonstrated gap. No general backend, task database, notification framework or AI-agent layer for hypothetical consumers.

Home Assistant owns household devices/presentation; Predbat optimisation; Enphase hardware integration; Octopus tariffs; Paperless documents; email/calendar providers their source records; OpenHands engineering reasoning. GitHub owns canonical source. The Pi control boundary owns privacy, credentials, bounded privilege, deployment, independent verification and evidence. Preserve the root broker and protected services.

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

## Delivery order

1. **Personal Assistant usability — #1498 (next main delivery).** Prove classification quality on a broader corpus, related multi-message/multi-thread matter grouping, genuine obligations, deduplication, completion/lifecycle handling, preserved user overrides and user acceptance. Reuse the sole reconciler/task projection. Existing previews are read-only; mailbox writes, classifier promotion and confirmed-junk activation remain held.
2. **Ask LifeOS / Proactive Intelligence.** Answer and surface useful questions from accepted household and PA sources with provenance and confidence. Use existing authorities and thin read adapters. Finance is not a prerequisite or input integration to build.
3. **Energy — #1071.** Audit deployed native inputs and authority boundaries, quantify historical/replay economics and prove any proposed native-setting improvement before changing live control. Predbat remains optimiser; no duplicate controller.
4. **Adaptive capability learning — #1772.** Address demonstrated workload failures with existing tools/configuration first. Model/hardware expansion requires accepted evidence and its existing approval boundary.

Engineering MVP #935 is a separate bounded acceptance task, not a gate requiring all infrastructure programmes to finish before PA. Prove the unchanged Level 2 fixture without supplying OpenHands the solution or changing model/hardware. Repair only generic pipeline defects; stop when #935 passes. Keep #418 open until its selected criteria pass; do not automatically advance Levels 3/4 or broad #1024 M3–M7.

Serialize production changes; inspect other active work before touching shared files. Independent discovery does not authorize competing production owners.

## Reliability and maintenance backlog

- Repair the two invalid OpenHands workflow definitions; scoped LifeOS CI success does not mean all workflows are green.
- Monitoring notification delivery remains unconfigured and needs a selected delivery destination before activation.
- Off-device restore assurance remains outstanding; do not delete recovery copies or repeat storage cutover/finalization as routine cleanup.
- Treat #883/#1137/#1024 and historical ledger cleanup as demand-led maintenance: act when they block a capability, remove meaningful burden or fix a demonstrated defect. Preserve evidence and prove dependencies before retiring code/services.
- Z97 retirement, broader autonomy, hardware expansion, new dashboards and curtain device acceptance remain deferred unless explicitly selected and their gates pass.

## Finance — deferred by owner

On 27 October 2026 the owner removed Finance & Assets from the plan: “Dont want it. Maybe later.” #17 is closed as not planned, with its original proposal retained as history. There is no finance phase, accounting-core selection, bank integration, tax/MTD delivery, dependency or scheduled commitment. Resume only after an explicit future owner request. Privacy protections for any existing financial information remain in force.

## Completion and safety

CI/merge/deployment alone is not completion. Require actual consumed-runtime acceptance, relevant regression checks, preserved recovery/rollback and durable evidence. Prefer read-only/shadow proofs first. Preserve private data locally. Do not reboot, remove recovery data, alter energy control, change approved AI models/hardware or introduce a new authority merely to make an acceptance gate pass.

Success is useful behaviour delivered per component maintained, with less household administration and attention.
