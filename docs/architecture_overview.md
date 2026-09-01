# Architecture overview

## Authority

`lifeos-platform` is the canonical source of truth for LifeOS implementation,
policy, tests and documentation. The companion control repository is a transport
and evidence channel, not an alternative implementation source. The detailed
repository contract is in `architecture/REPOSITORY_MODEL.md`.

Pi5 is the permanent, always-on Governor and control plane. It owns canonical Git
publication and coordinates work. Watchman is the sole runtime execution
gatekeeper: proposals do not become runtime actions without its policy decision.

## Compute roles

- **Pi5 Governor:** orchestration, policy, health, queues and execution gating.
- **AI VM:** optional local/private AI and heavy-compute provider. Its underlying
  machine may retain a historical name during controlled migration.
- **Z97:** migration-only legacy capacity, to be retired after migration gates
  pass.

No hardware specifications are assumed here. See `architecture/AI_VM.md` for the
current AI routing and privacy boundary.

## Worker boundaries

Engineer, Auditor and Personal Assistant are separate concerns whenever those
capabilities are active. They must not directly import one another, call one
another's runtime, or share private in-process state. Communication is limited to
files, queues and repository state as defined in `governance/communication.md`.

The historical dedicated Engineer worker and PA audit scheduler are currently
shadow-retired; their decisions are recorded in
`architecture/decisions/engineer-worker-retirement.md` and
`architecture/decisions/pa-audit-retirement.md`. Their retirement does not merge
their responsibilities or relax the separation rule.

## Trust flow

1. An engineering actor writes a proposal as reviewable repository state.
2. Independent validation records evidence without mutating the proposal.
3. Pi5 accepts an immutable revision through the control channel.
4. Watchman evaluates policy and either rejects the request or permits execution.
5. Runtime evidence returns through files or queue state for later review.

## Unresolved decisions

- TODO: Define objective criteria for restoring a dedicated Engineer or Auditor
  worker if an established component cannot meet a future workload.
- TODO: Record the final Z97 retirement evidence and date after every migration
  gate passes.
