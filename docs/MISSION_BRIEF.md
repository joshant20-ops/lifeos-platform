# LifeOS / Homelab — Mission Brief

**Status:** Canonical project mission and decision framework  
**Priority:** Governing document for all LifeOS/Homelab work

## 1. Mission

Build a dependable, local-first personal infrastructure platform that quietly operates household systems, personal administration, finance, energy, documents, automation and supporting infrastructure with minimal maintenance burden.

The goal is not to maximise features or build novel software. The goal is the **smallest defensible software estate** that provides required capabilities with strong reliability, security, privacy, recoverability and long-term maintainability.

LifeOS should orchestrate established applications rather than become a giant bespoke application that replaces them.

## 2. Final outcome

The finished platform should:

- Run core household and personal services reliably.
- Detect failures before the user notices them.
- Automatically repair known, pre-authorised failure modes.
- Escalate only when human judgement, a new privilege boundary, destructive action or consequential decision is required.
- Maintain clear audit evidence of changes and outcomes.
- Make infrastructure status understandable through plain language.
- Reduce routine SSH access to exceptional debugging and recovery.
- Preserve service independence so LifeOS failure does not take down unrelated core services.
- Keep personal data local by default.
- Support finance, budgeting and tax preparation without surrendering personal financial data to cloud AI.
- Continuously reduce unnecessary complexity.

Success benchmark:

> The platform can be left alone for long periods, maintains itself, reports only what genuinely requires attention, survives normal failures, preserves evidence of its actions and does not create maintenance burden faster than it removes it.

## 3. Architecture principles

### Capability before software

Define the capability before choosing software. Every application, daemon, container, VM and custom component must have a continuing justification.

### Reuse before addition

For every requirement:

1. Check whether existing installed software already provides it.
2. Check whether configuration or integration can provide it cleanly.
3. Evaluate mature off-the-shelf software only if the existing estate cannot satisfy it.
4. Use small glue only where objectively simpler than another service.
5. Create bespoke applications only exceptionally.

Existing software gets first consideration, not automatic preference. Do not distort an existing application into an unsuitable role merely to avoid adding a justified component.

### OTS before bespoke

Preferred order:

**Existing capability → configuration → integration → established OTS software → small glue → bespoke application**

If a mature maintained product already solves a problem cleanly, rebuilding it is normally an architectural failure.

### Minimise total complexity

Optimise for reliability, maintainability, attack surface, operational burden, backup burden, dependencies, portability, observability, recoverability and lifecycle cost — not merely program count.

## 4. AI and privacy policy

### Personal data stays local

Personal and household data is processed by local systems/local AI by default, including financial transactions, tax records, documents, emails, household activity, Home Assistant data, personal history, addresses, identifying information, credentials and private communications.

Raw personal datasets must not be sent to cloud AI.

### Cloud AI is an exception path

Cloud AI may be used only where local capability is insufficient, there is genuine benefit, and the information sent has been locally minimised and sanitised. Sanitisation must remove unnecessary identifying context, not merely names.

Preferred decision chain:

**Deterministic local software → local AI → local AI + public retrieval → sanitised cloud AI → human**

### Local capability grows

Cloud escalations should be recorded as evidence of local capability gaps. Repeated gaps should drive evaluation of better local models, retrieval, reference data, OTS tools, APIs or configuration.

### Public retrieval is allowed

Local AI may retrieve and reason over public information such as HMRC guidance, tax legislation, regulations, technical documentation, energy tariffs, standards, public APIs and manufacturer information while private data remains local.

## 5. Finance, budgeting and tax

LifeOS must provide a dependable finance capability supporting transaction import, categorisation, reconciliation, budgeting, cash-flow visibility, recurring costs, rental/property finances, evidence linking, tax-year preparation, missing-record detection, forecasting, scenario modelling and Making Tax Digital readiness where applicable.

Target flow:

**transactions → reconciliation → categorisation → evidence → calculations → exceptions → human approval → compliant submission path**

LifeOS may prepare and explain tax information. Consequential tax judgements and submission remain appropriately human-controlled and should be grounded in current authoritative public guidance.

## 6. Service independence

LifeOS orchestrates systems rather than becoming a single point of failure. Failure of Engineer, Governor, conversational UI or another LifeOS component should not unnecessarily stop Home Assistant, MQTT, password management, VPN, ad blocking, finance records, document storage or backups.

## 7. Ownership model

Each capability/data class has one authoritative owner. Git owns desired definitions/versioned configuration; runtime systems own runtime queues/state; audit systems own immutable results; publisher owns staging-to-pending; runner owns execution/results; root broker owns privileged operations; bounded bridges submit only; domain applications own their authoritative domain data.

Git must not overwrite runtime state. Runtime systems must not mutate Git definitions unless explicitly designed and authorised to do so.

## 8. Human control boundaries

The user should be as hands-off as practical. Human action is primarily reserved for genuinely new privilege boundaries, destructive/irreversible actions, financial commitments, tax submission, security-sensitive approvals, unavailable secrets, physical hardware work and decisions requiring personal judgement.

## 9. Working relationship

The assistant should perform as much work as possible before asking the user to execute anything:

1. Inspect architecture/history first.
2. Use GitHub/repository state read-only as the primary information source where possible.
3. Build/modify through the repository workflow rather than experimenting on live systems where practical.
4. Test against repository state and known hardware/OS/service capabilities.
5. Validate dependencies, expected state and negative/failure cases.
6. Only then provide a bounded deployment/verification script.
7. Analyse returned evidence and continue from the exact passed/failed stage.

The user's role is primarily to state goals, make consequential decisions, approve new boundaries, run a final bounded command when unavoidable and provide physical access when necessary.

## 10. GitHub-first development

Source changes are made in the canonical repository first where practical. Preserve reviewable diffs and rollback. Avoid live hand-editing. Runtime evidence remains separate from Git-managed definitions. Do not use destructive Git operations merely to make deployment succeed or discard audit/runtime state.

## 11. Deployment-script standard

User-run changes should normally be delivered as **one large gated script** that is self-contained, bounded, minimally interactive, fail-closed, diagnostic, safe against partial completion and repeatable where practical.

Stages should clearly emit `STAGE_X=PASS` or `STAGE_X=FAIL`.

Typical gates:

1. Preflight — target, OS, repo, commit, files, binaries, permissions, disk/hardware/network as relevant.
2. Existing-state validation — desired state, drift, partial deployment, replay/conflicts.
3. Recovery protection — checksums, snapshot/backup, service state, rollback inputs.
4. Mutation — smallest required change only.
5. Direct verification — prove intended outcome, not merely exit code zero.
6. Regression verification — test neighbouring functionality.
7. Final machine-readable summary.

Failure output must include enough non-secret diagnostics for the assistant to identify the next action without asking the user to manually debug.

Change philosophy:

**Inspect → understand → design → test → protect → mutate → verify → regress → record**

Never: **guess → change → see what happens**.

## 12. High-priority capability — Energy Opportunity Alerting

### Objective

Add Energy Opportunity Alerting to the LifeOS energy system. Initial priority:

> **Never miss negative Octopus electricity pricing again.**

LifeOS should detect unusually advantageous Octopus import-price periods shortly after new tariff data becomes available and inform household members without requiring Home Assistant on their phones. The same event source should later support battery optimisation, EV charging and flexible household loads.

### Core behaviour

When Octopus publishes new electricity prices:

1. Reuse existing Octopus/Home Assistant tariff data wherever possible.
2. Detect every half-hour slot where import price is below `0p/kWh`.
3. Combine consecutive negative slots into one opportunity window.
4. Determine start, end, relevant date, duration, minimum price and constituent slots.
5. Detect after tariff publication rather than waiting for the opportunity to begin.
6. Emit only one initial alert per newly discovered opportunity.
7. Persist sufficient state to prevent duplicate alerts after Home Assistant restart, integration reload or tariff refresh.
8. Support multiple distinct negative windows and midnight-spanning windows where source data permits.

### Household notifications

Use two independent paths initially:

**Alexa:** announce the useful window through appropriate existing household Alexa devices, without unnecessary repetition.

**WhatsApp:** notify required household members without requiring Home Assistant on their phones. Prefer a reliable supported mechanism. If official limitations prevent group posting, individual delivery is acceptable. Do not introduce a brittle unofficial WhatsApp Web bot merely to obtain group messaging.

A reminder shortly before an opportunity begins may be considered later, but not until basic alerting is proven reliable.

### Central Energy Opportunity event

Do not design this solely as a notification automation. Create/reuse one authoritative **Energy Opportunity** representation exposing where practical:

- stable/unique event identifier,
- event type/severity,
- start/end timestamps,
- local date,
- duration,
- minimum price,
- constituent price slots,
- source/detection timestamp,
- notification status where appropriate.

Initial condition: `import_price < 0 p/kWh`.

Future consumers may include Alexa, WhatsApp, Predbat, battery control, EV charging, appliance guidance, dashboards and wider LifeOS optimisation. Consumers should not independently reimplement Octopus negative-price detection unless unavoidable.

### Thresholds

Thresholds must be configurable. Initially enable household alerts only for:

**NEGATIVE:** `price < 0p/kWh`

Provision may exist for future thresholds such as **VERY CHEAP:** `price < 5p/kWh`, but do not enable household alerts for them initially. Avoid notification spam.

### Predbat

Predbat remains authoritative for battery optimisation where it already has the necessary information. Do not duplicate its optimisation logic. Energy Opportunity should complement Predbat and provide a common exceptional-pricing event for humans and other systems.

### Reliability

Handle Home Assistant restart, integration reload, duplicate/late tariff updates, multiple separate negative periods, consecutive slots, midnight crossing where available, unavailable data and detectable notification failures. Restart/refresh must not repeatedly announce previously known opportunities.

### First implementation gate

Before implementation, audit and report:

1. Where Octopus Agile data currently enters the system.
2. Which entities/API expose future half-hour prices.
3. Whether existing Home Assistant functionality can detect/group negative periods without another service.
4. Existing Alexa integration and announcement mechanism.
5. Best supported WhatsApp delivery route.
6. Whether any new dependency is actually required.
7. Proposed Energy Opportunity representation and authoritative owner.
8. Proposed persistence/deduplication mechanism.
9. How downstream consumers subscribe/retrieve events.

Then recommend the smallest reliable implementation and build/test it through the established GitHub workflow before live deployment.

### Success criteria

**Octopus publishes a negative-price period → LifeOS detects it shortly after publication → one persistent Energy Opportunity is created → Alexa announces it → required household members receive WhatsApp notification without Home Assistant → tariff refreshes/restarts do not cause spam.**

Guiding principle:

> The household should not have to watch electricity prices. LifeOS watches them, identifies genuinely useful opportunities, tells humans only when their action is worthwhile, and allows automated systems to exploit them wherever practical.

## 13. Roadmap

### Phase 1 — Control plane and safe autonomy

Prove Governor/Engineer, bounded submission, publisher/FIFO/runner, root broker, replay/checksum protection, audit evidence, privilege boundaries, Git/runtime separation and safe self-deployment.

**Current status: near completion; close remaining protected activation/control-state work.**

### Phase 2A — Estate and OTS rationalisation

Inventory every service/capability and classify it `KEEP`, `CONSOLIDATE`, `REPLACE`, `REMOVE` or `INVESTIGATE`. Every running component must be justified. Establish authoritative capability ownership and remove obsolete/duplicate bespoke systems.

### Phase 2B — High-priority Energy Opportunity Alerting

Perform the capability audit above, then implement the smallest reliable negative-price event/notification system using existing capabilities first. This is an early real-world proof of the LifeOS architecture.

### Phase 2C — Backlog hygiene and wider rationalisation

Remove obsolete, duplicate, superseded and low-value work; document genuine capability gaps.

### Phase 3 — Production operations

Implement health/dependency/storage/backup monitoring, restore verification, failure classification, known-fault remediation, drift detection, bounded rollback, operational visibility and escalation.

### Phase 4 — Local data and knowledge layer

Provide local retrieval/search, document indexing, controlled cross-service context, local AI access to authorised personal data, provenance and public-information retrieval.

### Phase 5 — Finance, budgeting and tax

Deliver the finance capability described above using existing/OTS software first and keeping personal financial data local.

### Phase 6 — LifeOS orchestration

Join independent authoritative systems into useful workflows through supported interfaces without absorbing their ownership.

### Phase 7 — Autonomous maintenance

Detect drift/failures, diagnose, test, execute bounded approved repairs, verify, roll back and preserve evidence; escalate only when required.

### Phase 8 — Continuous simplification

Continuously identify unused services, duplicate capabilities, obsolete custom code, repeated cloud-AI gaps, recurring manual work and weak recovery paths. Success is partly measured by what can safely be removed.

## 14. New-feature gate

Before implementing a feature, answer:

1. What required capability does it provide?
2. Is it actually needed?
3. Can an existing program already do it?
4. Can configuration solve it?
5. Can an existing integration solve it?
6. Is there a mature OTS product that solves it better?
7. What maintenance burden is introduced?
8. What security/privacy exposure is introduced?
9. What must be backed up?
10. What happens when it fails?
11. Can it be removed cleanly?
12. Does it reduce or increase total system complexity?

If the justification is not convincing, do not implement it.

## 15. Assistant behaviour contract

For all LifeOS work:

- Prefer evidence over assumptions.
- Prefer read-only inspection before mutation.
- Prefer GitHub/repository analysis before live-system changes.
- Do not make the user manually debug what can be diagnosed automatically.
- Prefer one gated script over long sequences of unguarded commands.
- Do not ask the user to perform speculative mutations merely to gather information.
- Test as far as practical before presenting deployment code.
- Preserve recovery and audit evidence.
- Stop at genuinely consequential boundaries.
- Challenge requirements that increase complexity, fragility or privacy risk.
- Do not agree merely for convenience.
- Keep work aligned to this mission rather than accumulating side projects.

## 16. Paste-back instruction

At the start of any LifeOS/Homelab conversation, the user can say:

> **Read the canonical LifeOS mission brief from `joshant20-ops/lifeos-platform` at `docs/MISSION_BRIEF.md`, treat it as the governing requirements for this work, check the current roadmap/state in GitHub, and continue from the appropriate phase. Do not rely on an older pasted copy if GitHub is available.**

That repository document is authoritative over abbreviated copies in chat.