# LifeOS / Homelab — Canonical Mission Brief

**Status:** Active canonical direction  
**Last alignment audit:** 2026-09-05  
**Repository:** `joshant20-ops/lifeos-platform`

This document defines what LifeOS is trying to become and the engineering rules that govern it. It is intentionally more stable than GitHub issues, runtime evidence, or work logs.

For current implementation state, use GitHub issues plus live runtime evidence. **Current reality outranks stale issue text.**

---

## 1. Mission

Build a dependable, local-first, self-hosted personal and household operating platform that reduces administration, coordinates existing systems, surfaces useful decisions and opportunities, and can progressively maintain and improve itself without sacrificing privacy, recoverability, or control.

LifeOS should feel like one coherent system rather than a collection of dashboards and scripts.

The target is not maximum software count or maximum automation. The target is **maximum useful capability with minimum unnecessary complexity**.

---

## 2. Non-negotiable engineering doctrine

### Inspect before changing

For every task:

**Inspect → understand → design → test → protect → mutate → verify → regress → record.**

Never change a working system merely because historical documentation or an old issue says it is broken.

Before mutating anything, establish the current live state and reconcile it against the desired state.

### OTS first

For every capability, use this preference order:

1. existing installed capability;
2. native configuration or integration of that capability;
3. another mature off-the-shelf/open-source product when a real gap remains;
4. thin LifeOS glue/orchestration;
5. bespoke code only for a proven gap.

Every service/program must justify its existence. Prefer consolidation, deletion and replacement of custom code when mature OTS functionality can do the job better.

Do not create a second system of record when a suitable authoritative system already exists.

### Prove completion

A code change, commit, green unit test or successful build is not by itself completion.

Where applicable, completion requires deployment/runtime evidence, focused verification, relevant regression checks and durable evidence.

### Autonomous engineering

Ordinary engineering problems should be diagnosed and repaired autonomously through governed paths. Do not return routine shell commands or normal implementation work to the user merely because the first attempt failed.

Escalate only genuine human boundaries such as credentials/consent, account authorisation, physical access, irreversible/destructive operations, safety-critical validation, or explicit policy/preference decisions.

### No roadmap inflation

The original **12-stage foundation roadmap is complete: 12/12**.

Do not invent Stage 13 or reopen completed foundation stages. New work belongs in the governed capability backlog and portfolio index.

---

## 3. Source-of-truth hierarchy

Use the appropriate authority for each kind of state:

- **GitHub repository** — canonical desired state, source, architecture, history and durable engineering evidence.
- **Pi/runtime systems** — live operational state and runtime evidence.
- **GitHub issues** — backlog, acceptance criteria, decisions and concise progress evidence; issue text can become stale.
- **Home Assistant** — authoritative home/device automation surface where appropriate, not a universal database.
- **Paperless** — authoritative document/evidence store where applicable.
- **Predbat / Enphase / existing energy controllers** — retain their specialist control roles where they already solve the problem well.
- **Accounting/finance core selected for LifeOS Finance** — authoritative financial ledger when implemented; Home Assistant is presentation/orchestration only.

When sources disagree, inspect current runtime evidence before changing the system and then reconcile documentation/issues to reality.

---

## 4. Privacy and AI boundary

Personal, household, document and financial data is **local-first by default**.

Local AI may access private context required to provide useful personal services.

Cloud AI may receive only the minimum sanitised/redacted information genuinely required for an approved task. Private Paperless contents, financial records, secrets and equivalent sensitive material must not be casually copied to cloud AI, GitHub, logs or external services.

Cloud AI may freely use public/non-personal reference information such as technical documentation, UK tax rules, regulations and product documentation.

The architecture should progressively improve local AI capability so fewer tasks require cloud assistance.

AI suggestions must be distinguishable from authoritative facts/records. AI must not silently alter authoritative financial, tax, security or other high-impact records merely because it inferred a change.

---

## 5. Privilege, self-modification and safety

LifeOS may progressively gain broad administrative capability, including root-level maintenance, but **never through an unrestricted interactive root shell for the model**.

Privileged operations must pass through the governed root gateway / Watchman / transaction-control boundary.

Unknown privilege requests fail closed.

Privileged or self-modifying changes must become transactional where required by risk: establish recovery state first, arm independent rollback protection, apply the bounded change, verify independently, and commit only after measurable evidence.

The protected recovery mechanism must remain outside the ordinary AI self-modification path.

The default maximum unconfirmed rollback window for transactional root changes is **2 hours**, subject to the policy defined by the transactional-root capability.

Do not bypass safety controls merely to make automation appear unblocked.

---

## 6. Core platform roles

### LifeOS Engineer

The specialist engineering agent/control plane. Responsible for inspection, architecture, code, infrastructure, Home Assistant engineering, Git, tests, deployment, verification, recovery and governed autonomous repair.

### LifeOS Personal Assistant

The everyday user-facing assistant. Responsible for useful household/personal interaction, attention management, reminders, summaries, decisions and cross-domain coordination.

The PA does not become an unrestricted engineering agent. Engineering/build work is handed to LifeOS Engineer through the governed workflow.

### Pi5 control plane

The Pi5 remains the central orchestration/control point unless a later evidence-backed architecture change proves a better design.

### Specialist systems

LifeOS coordinates mature specialist products rather than replacing them without reason. Home Assistant, Paperless, MQTT, energy controllers, accounting systems, backup tooling and other retained services should keep clearly defined responsibilities.

---

## 7. Capability direction

The capability backlog is managed in the central portfolio/index issue rather than as additional foundation stages. Strategic capability areas include:

- production operations, monitoring, backup/recovery and service health;
- OTS rationalisation and retirement of obsolete custom code;
- unified Personal Assistant inbox and conversational job management;
- calendar, scheduling, email and document workflows;
- Home Assistant / infrastructure / smart-home coordination;
- energy optimisation and opportunity alerting;
- finance, rental-property accounting, budgeting, tax preparation and MTD support;
- vehicles, EV and travel context;
- knowledge, provenance and Ask LifeOS;
- proactive cross-domain assistance;
- mature governed self-maintenance.

The portfolio index may reprioritise these streams without changing this mission.

---

## 8. Energy mission

Energy is a high-priority LifeOS capability.

LifeOS should coordinate existing Octopus, Home Assistant, Predbat, Enphase and future storage/EV/heat-pump capabilities rather than duplicating their specialist control engines.

A specific high-priority objective is **Energy Opportunity Alerting**: do not miss economically valuable electricity periods, especially negative Octopus import pricing.

The reusable LifeOS energy-opportunity model should, where data supports it:

- detect and group relevant half-hour price periods;
- represent start/end, duration, slots, minimum/representative price, opportunity type and stable unique identity;
- persist deduplication across Home Assistant restarts and refreshed tariff data;
- notify the household through authorised channels such as Alexa and/or messaging;
- distinguish technical detection from user-defined notification policy;
- allow future positive-cheap-power thresholds only after the household policy is explicitly chosen;
- provide opportunity context to energy controllers without overriding them blindly.

Credentials, recipient consent and household notification preferences remain genuine human boundaries.

---

## 9. Finance mission

LifeOS Finance should combine useful personal money management with rigorous bookkeeping/tax preparation while keeping private financial data local by default.

Prefer a mature OTS accounting/ledger core. LifeOS should provide orchestration, integrations, provenance, automation, review workflows and useful explanations rather than inventing an accounting engine.

Target capabilities include:

- personal budgeting and cash-flow understanding;
- bank/card transaction ingestion and reconciliation;
- recurring-payment and anomaly visibility;
- separate personal, rental-property and future business entities/ledgers;
- Paperless-linked receipt/invoice evidence rather than a duplicate document store;
- rental income/expense accounting and evidence matching;
- UK tax-year-aware categorisation and reproducible tax packs;
- accountant exports and future Making Tax Digital support where applicable;
- provenance from every material figure back to source transactions/documents;
- explicit human review before authoritative uncertain classifications or HMRC submission.

The desired end state is that quarterly/annual tax work is largely a by-product of continuously maintained records, with LifeOS surfacing missing evidence or decisions rather than requiring a year-end reconstruction exercise.

---

## 10. Reliability and recovery standard

Core services deserve stricter reliability standards than optional features.

For retained infrastructure, aim for:

- known ownership and purpose;
- health monitoring;
- tested backup where state matters;
- reproducible restore/recovery path;
- bounded failure handling;
- observable state and useful evidence;
- least privilege;
- dependency awareness;
- graceful degradation where practical.

A backup that has never been restore-tested is not sufficient evidence of recoverability.

Autonomous repair must be bounded. Repeated failure must stop safely rather than loop forever.

---

## 11. User experience doctrine

LifeOS should reduce attention demand, not create another stream of telemetry.

Prefer:

- exceptions, opportunities and decisions over raw status;
- concise explanations with drill-down available;
- one coherent interaction surface where practical;
- proactive alerts only when useful/actionable;
- automation that handles routine work silently and records what it did;
- explicit approval only where approval genuinely adds safety, consent or policy value.

The system should be cold, dependable infrastructure first. Personality or novelty must never compromise clarity, reliability or efficiency.

---

## 12. Evidence and issue hygiene

Historical issues are hypotheses/records, not commands to mutate the present system.

Before acting on an old issue:

1. inspect current implementation and runtime state;
2. determine whether the defect/capability gap still exists;
3. close or update stale work rather than recreating it;
4. make the smallest justified change if a current gap remains;
5. attach concise proof and keep large raw logs in appropriate evidence artifacts.

Temporary verification triggers should be closed after their purpose is satisfied.

Human-boundary issues may remain open without blocking unrelated autonomous engineering.

---

## 13. Current programme state

As of the 2026-09-05 alignment audit:

- Foundation roadmap: **12/12 COMPLETE**.
- New work is capability/backlog work, not new foundation stages.
- Transactional root self-modification remains active work; the previous `must_run_as_root_via_Watchman` blocker has been repaired and live-proven, but the broader capability must satisfy its own acceptance criteria before closure.
- Historical GPU migration assumptions must not trigger package/driver changes without fresh read-only verification of the actual current GPU/driver/inference state.
- Privacy-classifier and Zemismart curtain work must establish current runtime state before mutation.
- Household WhatsApp/Alexa delivery and positive cheap-power thresholds remain human/account/policy boundaries where authorisation or preference is genuinely required.

This section is a snapshot only. GitHub issues and live evidence are authoritative for newer status.

---

## 14. Definition of success

LifeOS succeeds when it is a boringly reliable personal infrastructure layer that:

- protects private data by default;
- reuses mature systems rather than endlessly adding software;
- automates routine administration;
- surfaces the few things that genuinely need human attention;
- can diagnose and repair ordinary failures autonomously;
- can modify itself only through recoverable, governed mechanisms;
- preserves provenance and auditability;
- improves local capability over time;
- remains understandable and recoverable by its owner;
- measurably saves time, money or cognitive effort without creating equivalent maintenance burden.

**The governing question for every proposed component or change is: does this make LifeOS more useful, reliable, private or maintainable than the system we already have — and can we prove it?**

---

## Work log — 2026-09-05 — capability roadmap regrouping

### Decision

Following completion of the foundation and capability Stages 1–3, the remaining numbered capability stages should be delivered as **integrated capability waves** where they share data models, integrations and user-facing workflows. The original stage numbers remain for traceability; the wave model controls delivery sequencing and prevents duplicate subsystems.

### Wave A — Household Intelligence — NEXT

Combines **Stage 4 Personal Assistant + Stage 8 Infrastructure/Smart Home + Stage 9 Energy**.

Target outcome: establish the first complete LifeOS operational loop:

**observe → understand → decide → surface/approve when needed → act through the authoritative specialist system → verify → record.**

Responsibilities remain separated:

- Stage 4 / PA owns attention, conversation, decisions, approvals, explanations and household-facing delivery.
- Stage 8 owns higher-level infrastructure/home coordination while Home Assistant remains the authoritative device automation platform.
- Stage 9 owns energy opportunity/intelligence events while Predbat, Enphase, Octopus and Home Assistant retain their specialist control roles.
- Stage 9 must not create a separate notification framework; energy events are presented through the common PA attention/delivery model.
- Stage 4 must not absorb smart-home or energy control logic into a monolith.
- Pull forward only the EV/energy interface from Stage 11 when required; do not build the full vehicle/travel capability prematurely.

This wave should prove the reusable event/action/decision model with high-value household cases such as negative/cheap electricity opportunities, infrastructure exceptions and verified household actions.

### Wave B — Personal Administration

Combines **Stage 5 Calendar + Stage 6 Email + Stage 7 Documents/Paperless**.

Build a shared **event / obligation / action / evidence** model rather than separate reminder/deadline systems for each source.

Examples include email creating an actionable obligation, Paperless retaining authoritative supporting evidence, Calendar representing time commitments/deadlines, and the PA presenting only the resulting decision/action that needs attention.

### Wave C — Finance & Assets

Combines **Stage 10 Finance/Rental/MTD + the vehicle ownership/EV economics portion of Stage 11**.

Finance should consume the document/email/calendar capabilities from Wave B rather than duplicating them. Vehicle costs, mileage, charging/fuel, insurance and maintenance should feed the same financial/provenance model where appropriate. Rental-property accounting remains part of the finance stream. Full travel planning remains separate/continuous rather than blocking this wave.

A mature OTS accounting/MTD core remains mandatory unless a proven gap justifies otherwise; LifeOS provides orchestration, evidence linking, provenance, review and user experience rather than replacing the ledger.

### Wave D — Intelligence & Autonomy

Combines **Stage 12 Knowledge/Provenance/Ask LifeOS + Stage 13 Proactive Cross-Domain Assistant + Stage 14 Mature Governed Self-Maintenance**.

Treat these as progressive maturity of one intelligence architecture:

1. **Ask:** what does LifeOS know, with source/confidence provenance?
2. **Anticipate:** what does the user need to know or decide without asking?
3. **Act/improve safely:** what can LifeOS repair or improve autonomously through governed, recoverable mechanisms?

They must share provenance, confidence, policy, audit and reasoning infrastructure rather than creating separate AI frameworks. Existing #26 transactional-root/governance work continues in parallel now; Wave D is the mature system-wide use of those safety foundations, not a reason to defer them.

### Continuous / cross-wave work

- Genuine maintenance, security, restore/recovery and governance defects continue independently and do not wait for a capability wave.
- Stage 11 travel capability can be added when useful without blocking Finance & Assets.
- OTS rationalisation remains a permanent engineering doctrine after Stage 1 completion: periodically re-evaluate retained custom code and services as mature native/OTS alternatives improve.
- Human/account/policy boundaries such as WhatsApp/Alexa authorisation and positive cheap-energy thresholds remain explicit boundaries rather than fabricated defaults.

### Delivery order

**Foundation + capability Stages 1–3 COMPLETE → Wave A Household Intelligence → Wave B Personal Administration → Wave C Finance & Assets → Wave D Intelligence & Autonomy.**

Each wave should leave behind reusable capability for the next rather than implementing parallel point solutions. The objective is four progressively more capable versions of one LifeOS, not eleven loosely connected feature projects.
