# OTS-first architecture reduction audit

## Decision rule
LifeOS should orchestrate and govern mature tools, not reimplement their native domain. Custom code remains only for LifeOS-specific policy, privacy, capability boundaries, hardware lifecycle, deterministic acceptance, evidence publication, and cross-system integration.

## Keep as LifeOS control plane
- `governor/ai_broker.py`: privacy/routing boundary and Tower lease/wake integration.
- `governor/autonomous_agent.py`: reduce to intake, builder selection, publication, independent deterministic acceptance, disposition and bounded privileged deployment.
- `governor/job_records.py`, `target_identity.py`: provenance and target identity.
- Root/control bridges and deployment allowlists: retain privilege separation.
- Mission Control: retain as GitHub entrypoint/evidence transport, not an engineering agent.

## Delegate to OpenHands
OpenHands owns the complete repository engineering plane:
- repository discovery and diagnosis;
- planning and task decomposition;
- editing;
- choosing/running focused tests;
- debugging and retrying;
- interpreting prior acceptance feedback inside the same engineering objective;
- deciding when it has produced a change or deterministic no-change evidence.

LifeOS must not infer engineering progress from tool/action counts or reproduce an agent planning loop.

### Consolidation candidates
- `governor/scripts/lifeos-openhands-sdk-runner.py`: keep only a thin OpenHands launch/session adapter plus bounded evidence contract.
- `governor/scripts/lifeos-local-builder`: reduce to privacy-safe snapshot transfer, OpenHands launch and artifact return.
- `governor/scripts/lifeos-remote-agent-builder`: reduce to generic workspace/artifact boundary; remove OpenHands-specific pseudo-agent policy now owned by OpenHands.
- `engineer/openhands_worker.py`: overlaps the newer Governor-broker/OpenHands path; migrate any still-needed dry-run/broker assertions into the canonical adapter, then retire it.
- `engineer/cleanup_audit.py` and `engineer/review_packet.py`: repository/audit reasoning belongs to OpenHands unless a deterministic machine-readable check consumes these outputs.

## Delegate to existing OTS systems
- GitHub Actions: CI execution, test status and workflow scheduling. Governor consumes results rather than recreating CI.
- systemd: service startup/restart/dependencies and process supervision. Python retains semantic health only where systemd cannot express it.
- Home Assistant: device state, automations and Tower power actuation. Governor requests bounded outcomes.
- Ollama: model process/load/keep-alive. Governor performs readiness and lease policy, not model supervision.
- Paperless-ngx: document storage/OCR/index/search/metadata.
- Predbat: battery forecast/optimisation; LifeOS supplies policy/objectives and consumes decisions.

## Review / likely retire after dependency proof
- `engineer/provider_router.py`: routing authority now belongs at the Pi Governor broker. Keep only if a non-duplicated policy consumer remains.
- `governor/engineer_backend.py`: contains a second engineering-manager/model interaction surface. Review callers; collapse into Mission/Governor + OpenHands if no distinct UI requirement remains.
- `governor/scripts/lifeos-cloud-builder`: cloud engineering should use the same OpenHands-first engineering contract where possible, with Governor selecting an approved provider/capability instead of maintaining a parallel prompt/orchestration implementation.
- legacy bespoke retry/iteration code in `autonomous_agent.py`: retain bounded acceptance retries only as an outer verifier loop; do not treat each retry as a fresh engineering strategy.

## Keep outside OpenHands
These must remain independently controlled:
- privacy classification and provider authorization;
- secrets/capability issuance;
- Tower wake/lease/shutdown;
- canonical Git publication boundary;
- privileged/root operations;
- deterministic canonical assertions;
- final acceptance/disposition and durable evidence archive.

OpenHands must never be the sole verifier of its own work.

## Immediate cleanup
Temporary diagnostic workflows are not architecture:
- `.github/workflows/lifeos-broker-502-diagnostic.yml`
- `.github/workflows/lifeos-level2-premature-diagnostic.yml`
- `.github/workflows/lifeos-level3-diagnostic.yml`

Remove them once their evidence is preserved in issues/job records. Do not remove active deployment or acceptance workflows.

## Migration order
1. Make the canonical local engineering route OpenHands-owned and get CI + Level 2 green.
2. Collapse duplicate OpenHands adapters/builders behind one adapter.
3. Move cloud/sanitised engineering onto the same adapter contract, changing only Governor-selected model/provider capability.
4. Remove Engineer-side duplicate provider routing after call-site proof.
5. Reduce Governor acceptance retries to an outer independent verifier feedback loop into the same OpenHands objective/session mechanism.
6. Remove temporary diagnostics and obsolete compatibility code.
7. Re-run Level 2 unchanged.
8. Only then resume Level 3.

## Acceptance criteria
- no action-count/progress heuristics in LifeOS;
- one canonical OpenHands engineering adapter;
- no duplicate provider-routing authority;
- Governor cannot self-approve OpenHands output;
- local-only inference remains Tower-only;
- Tower lifecycle remains automatic;
- deterministic canonical verification remains independent;
- CI green;
- unchanged Level 2 #935 genuinely passes before Level 3 resumes.
