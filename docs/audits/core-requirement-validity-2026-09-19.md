# Core-requirement validity audit — 2026-09-19

This document asks a different question from implementation acceptance:

> **Why did this work item exist, and is that underlying reason still required by the current LifeOS architecture/runtime?**

Current architecture and live runtime outrank historical implementation instructions.

## Current active issues

| Issue | Core reason | Still required? | Current disposition |
|---|---|---|---|
| #7 | Local private AI still depends on the Tower GPU. | **REQUIRED** | Local private AI still depends on the Tower GPU. The exact R580 migration method is historical, but reliable GPU-backed local inference remains a current requirement; retain under current Tower GPU/runtime acceptance rather than blindly performing the old package plan. |
| #14 | Privacy routing remains a hard current invariant. | **REQUIRED** | Privacy routing remains a hard current invariant. Current AI-routing/privacy workflows exist; fresh E2E proof remains relevant. |
| #15 | A user-facing Personal Assistant surface remains part of the current architecture; HA is live and PA services are deployed, but current acceptance is incomplete. | **REQUIRED** | A user-facing Personal Assistant surface remains part of the current architecture; HA is live and PA services are deployed, but current acceptance is incomplete. |
| #16 | User-facing autonomous job submission/progress remains a current capability requirement; Governor/Engineer services are live. | **REQUIRED** | User-facing autonomous job submission/progress remains a current capability requirement; Governor/Engineer services are live. |
| #17 | Finance & Assets is current Wave C work; current finance architecture/contracts exist. | **REQUIRED** | Finance & Assets is current Wave C work; current finance architecture/contracts exist. |
| #18 | Physical Zemismart curtain remains a current HA/Matter device requirement; Matter server is live. | **REQUIRED** | Physical Zemismart curtain remains a current HA/Matter device requirement; Matter server is live. Stability must be verified, not assumed. |
| #24 | This is the current central capability/backlog index and remains the portfolio owner. | **REQUIRED** | This is the current central capability/backlog index and remains the portfolio owner. |
| #103 | Household WhatsApp delivery is still desired but requires provider/recipient authorisation. | **REQUIRED_HUMAN_BOUNDARY** | Household WhatsApp delivery is still desired but requires provider/recipient authorisation. |
| #104 | Alexa delivery remains desired but requires an authorised HA/Alexa notification surface. | **REQUIRED_HUMAN_BOUNDARY** | Alexa delivery remains desired but requires an authorised HA/Alexa notification surface. |
| #105 | Cheap-positive-price threshold is still a user policy choice; no technical default should be invented. | **REQUIRED_HUMAN_BOUNDARY** | Cheap-positive-price threshold is still a user policy choice; no technical default should be invented. |
| #164 | Calendar/Email/Paperless personal administration remains current; Paperless and PA containers/workflows are live, but the mission audit previously reported scripted execution incomplete. | **REQUIRED** | Calendar/Email/Paperless personal administration remains current; Paperless and PA containers/workflows are live, but the mission audit previously reported scripted execution incomplete. |
| #200 | The historical failed run is not itself important, but automation health is currently still failing (LifeOS CI failures and failed live units), so the core reason remains valid and should be consolidated into current health/convergence work. | **REQUIRED_AS_CURRENT_DEFECT** | The historical failed run is not itself important, but automation health is currently still failing (LifeOS CI failures and failed live units), so the core reason remains valid and should be consolidated into current health/convergence work. |
| #230 | The original thermal incident is historical, but safe sustained 8K local inference remains required. | **REQUIRED_AS_SAFETY_INVARIANT** | The original thermal incident is historical, but safe sustained 8K local inference remains required. Current Tower thermal acceptance was not re-proven in today's audit. |

## Historical numbered implementation work
Historical PRs and closed issues are implementation/evidence steps, not 300+ independent product requirements. They must be mapped to the current capability that owns their underlying reason. A historical implementation instruction is **not** retained merely because it once existed.

Current owner families:
- **Repository/governance/execution authority** → three-repository authority + governed Pi5 execution.
- **Autonomous engineering** → Governor/Engineer + deterministic contracts + current AI routing.
- **Local/private AI** → Tower lifecycle + local-only routing + GPU/thermal safety.
- **Home Assistant/UI/device control** → HA as device authority + current LifeOS dashboard/control surfaces.
- **Energy** → Predbat/HA/Octopus specialist ownership + LifeOS opportunity/intelligence glue.
- **Personal administration** → Calendar/Email/Paperless OTS-first, Paperless authoritative for documents.
- **Finance/assets** → Wave C read-only/accounting architecture.
- **Operations/recovery** → systemd/Docker/Restic/Uptime Kuma + governed transactional mutation.
- **Historical triggers/retries/migrations** → not requirements; archive when their underlying capability is owned by a current family and the trigger itself has no continuing purpose.

## Live contradiction discovered
The accepted three-repository authority says the old `lifeos-pi-control` repository/relay is retired, but the live Pi still has scheduled `lifeos-pi-control.service` and `lifeos-job-publisher.service` units whose WorkingDirectory is `/home/joshan/lifeos-pi-control`; both are currently failed. This is stale runtime residue and must be reconciled rather than treating old relay-era tasks as still-required architecture.

## Evidence
- Requirement-validity live run: 35445247231
- Current canonical commit audited: `b083d7b65932c2942d1299f2ca1a332b8be857ae`
- Current authority documents present: three-repository authority, system simplification map, Governor AI routing, Paperless-first processing, Finance Wave C.
- Current runtime: Governor/Engineer/Tower control active; HA/Paperless/Predbat/Matter/Energy containers live.
