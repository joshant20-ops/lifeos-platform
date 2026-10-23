# Unified LifeOS Roadmap

**Status: ACTIVE — sole roadmap authority**  
**Adopted: 2026-10-07**

This document is the single active roadmap for LifeOS. Earlier Foundation stages, Capability stages, Waves A-D, P0-P10, Governor/OpenHands M0-M7, issue acceptance ladders and subsystem roadmaps are retained only as historical evidence and traceability. They do not independently control programme priority or create new work.

## Mission

LifeOS should reduce the owner's administration and attention burden. Prefer useful behaviour per maintained component over roadmap-stage completion.

## Architecture rule

Every new LifeOS component must do at least one of the following:

1. replace an existing component;
2. connect authoritative systems that cannot adequately communicate natively; or
3. provide a genuinely unique capability with a named maintenance owner.

Otherwise it is not built.

Default order: **existing deployed capability -> native configuration/integration -> mature OTS -> thin replaceable glue -> bespoke code only for a proven gap**.

Use high ceremony for dangerous changes (root, privacy, finance authority, energy actuation, autonomous self-modification). Use proportionate lightweight controls for ordinary UI/configuration changes.

## Authority model

- Home Assistant: household devices, automations, state and presentation.
- Predbat: battery/energy optimisation.
- Enphase: solar/battery hardware integration and telemetry.
- Octopus: tariff authority.
- Paperless: document/evidence authority.
- Email provider: message authority.
- Calendar provider: calendar authority.
- Selected OTS accounting platform: financial-ledger authority.
- OpenHands: software-engineering reasoning/session authority.
- GitHub/lifeos-platform: canonical desired source state and change history.
- Pi5/Governor boundary: privacy, credentials/capabilities, Tower lifecycle, bounded privilege, deployment policy, independent verification and disposition.
- LifeOS product layer: cross-domain intelligence, attention, provenance and coordination. It must not duplicate specialist authorities.

## Phase 0 — Complexity freeze — ACTIVE

Until simplification is complete:

- no new always-on service unless an existing/native/OTS path is proven insufficient;
- no new database, task framework, notification framework, scheduler, deployment mechanism or AI-agent layer;
- no new roadmap hierarchy;
- current defect/capability work may continue through existing architecture;
- PR #1583 remains DEV-only until its existing acceptance criteria pass.

Exit: all new work can identify an existing authoritative owner/path or an explicit justified exception.

## Phase 1 — Simplify the engineering/control plane

Primary owner: #1024, with #418/#935 as acceptance evidence.

Target engineering path:

**User/GitHub -> OpenHands -> repository/tools/tests -> governed deployment**

LifeOS retains only deterministic safety/control responsibilities: privacy/provider policy, credentials, Tower lifecycle, bounded privilege, canonical publication, deployment gating, independent verification, evidence and disposition.

Actions:
- finish #1024;
- remove remaining duplicate planning/edit/test/debug/retry/completion behaviour outside OpenHands;
- use GitHub Actions for CI, systemd for service supervision, HA for device/power actions and Semaphore/Ansible where orchestration is justified;
- prove #935 without issue-specific logic;
- close #418 when the simple end-to-end engineering path is genuinely proven;
- do not extend acceptance ladders merely to test machinery. Reassess #961 against current product value before execution.

Exit: one engineering authority, thin deterministic LifeOS control boundary, live acceptance PASS.

## Phase 2 — Repository, issue and evidence simplification

Unify #883, #1137 and backlog/ledger reconciliation as one simplification programme.

Actions:
- reconcile every open historical Ledger/deployment/discovery/acceptance issue against current runtime and capability ownership;
- close, mark superseded/duplicate, or fold historical implementation steps into their current parent outcome;
- preserve evidence in history/artifacts rather than keeping completed implementation steps open;
- archive/remove one-shot workflows, issue-specific triggers, orphaned scripts and dead compatibility paths after dependency proof;
- consolidate duplicate deployment paths;
- clean merged branches and establish a stable checkpoint;
- make #24 a concise portfolio index pointing to this roadmap rather than a competing roadmap.

Target: open issues represent current outcomes, defects, blockers or explicit human boundaries — not historical implementation chronology.

Exit: roadmap understandable without TASK_LEDGER; active workflow/script/issue surface materially reduced.

## Phase 3 — Simplify the live Homelab

Audit runtime against the authority model above.

Actions:
- complete the full HA estate/runtime audit;
- execute #1071: keep Predbat as optimiser and reduce bespoke energy code to assurance or indispensable thin glue;
- prefer native Octopus/HA/Predbat/Enphase data paths;
- consolidate overlapping Homelab/LifeOS/LifeOS Control presentation where live evidence supports it, while keeping Energy distinct if useful;
- retire stale compatibility services and generated bridges after dependency/rollback proof;
- retire Z97 once its published retirement gates genuinely pass;
- preserve backup/restore, privacy and transactional-root protections.

Exit: one authoritative implementation per capability where practical; live service/component inventory is understandable and justified.

## Phase 4 — Deliver the three user-facing LifeOS products

### 4A — Personal Assistant

One attention model across Email, Calendar, Paperless and household events:

**evidence/events -> matter/obligation -> Needs me / Waiting / Upcoming / Done**

Continue #1498 as the current matter/timeline improvement. Preserve source authority and one reconciler/attention path. No second task database or notification framework.

### 4B — Finance & Assets

Continue #17.

Select/use a mature OTS accounting core. LifeOS adds deterministic ingestion, reconciliation, Paperless evidence, analysis, rental-property workflow, tax preparation and provenance. Do not build a LifeOS accounting engine. Keep authoritative mutations and HMRC submission explicitly gated.

### 4C — Ask LifeOS / Proactive Intelligence

Build on stable Household + PA + Finance sources to answer and surface cross-domain questions, exceptions and opportunities with provenance/confidence. Reuse the same attention and retrieval infrastructure; do not create another AI framework.

Exit: LifeOS provides useful everyday outcomes across attention, money/assets and cross-domain intelligence with minimal maintenance burden.

## Phase 5 — Mature autonomy

Only after Phases 1-4 are boringly reliable.

Actions:
- broaden autonomous repair only through bounded, recoverable controls;
- use #26 transactional rollback/root safety where privileged self-change genuinely warrants it;
- add proactive cross-domain recommendations/actions with clear provenance and approval policy;
- continuously replace custom code with native/OTS capability where equivalence improves.

Exit: routine administration and ordinary repair happen autonomously; dangerous changes remain recoverable, independently verified and auditable.

## Priority order

1. Finish PR #1583 under its existing DEV-only acceptance boundary.
2. Enforce the complexity freeze.
3. Finish #1024; prove #935; close #418 when justified.
4. Reconcile/retire historical issues and ledger work.
5. Complete #883/#1137 repository simplification and stable checkpoint.
6. Audit/simplify live HA/runtime.
7. Execute #1071 energy simplification.
8. Retire Z97 when gates pass.
9. Product delivery: PA (#1498) -> Finance (#17) -> Ask/Proactive Intelligence.
10. Mature autonomy and broader transactional self-maintenance.

## Planning policy

This file controls programme sequencing. Individual issues may contain implementation plans and acceptance criteria, but they are subordinate work packages, not independent roadmaps.

Historical roadmap labels may remain in old issues/docs for traceability. Any document that describes an older roadmap must state that it is retired/superseded and link here.

## Success metric

The primary architectural metric is:

> **Useful behaviour delivered per component that must be maintained.**

LifeOS succeeds when it is boringly reliable infrastructure that saves more time, money and cognitive effort than it consumes.
