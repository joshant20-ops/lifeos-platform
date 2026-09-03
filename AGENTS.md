# LifeOS repository instructions

These instructions apply throughout this repository.

## Authority and safety

- Treat this repository as the canonical source of truth for LifeOS source,
  policy, tests and documentation.
- Treat Pi5 as the always-on control plane and canonical runtime target.
- Route runtime execution through Watchman and the reviewed LifeOS control
  boundaries. Do not bypass policy checks.
- Never commit credentials, private keys, tokens, private document contents,
  personal information, private addresses or host-specific secrets.
- Do not invent hardware capabilities. Record unknowns as `TODO` items.

## GitHub and Codex operating model

- GitHub is the canonical source of truth. The Pi runtime is a deployment target,
  not a place for unreviewed source edits.
- The dedicated self-hosted GitHub Actions runner is `lifeos-pi5` and runs as the
  unprivileged `joshan` account.
- Never grant the Actions runner general passwordless sudo, a root shell, or
  arbitrary command execution.
- `/usr/local/sbin/lifeos-deploy-gateway` must remain a fixed named allow-list.
  Do not accept arbitrary paths, shell fragments, user-supplied script names or
  environment-controlled executables.
- New privileged gateway operations require an explicit allow-list entry, narrow
  mutation scope, deterministic preconditions, rollback behaviour, post-change
  invariants, and a separately reviewed update of the installed root-owned
  gateway.
- Keep `lifeos-root-broker.socket` as the permanent privileged host boundary
  unless a separately accepted architecture decision replaces it.
- Keep `lifeos-control-job-submit.socket`, `lifeos-autonomous-agent.service`,
  `lifeos-engineer.service`, and the HA issue queue bridge protected unless a
  task explicitly proves a safe replacement.
- Do not reintroduce the retired Engineer worker/dispatcher timers or files as a
  shortcut.
- Do not delete recovery backups, legacy data volumes, or migration evidence
  merely to make a validation pass.

## Change discipline

- Propose substantial changes on a review branch and require independent
  validation before merge. Pi5-owned automation performs runtime execution.
- Inspect current repository state and relevant architecture decisions first.
- Prefer maintained open-source components over bespoke services when they meet
  the requirement.
- Keep Engineer, Auditor and Personal Assistant concerns separate. A worker must
  not import another worker's implementation or depend on its runtime process.
- Exchange work only through versioned files, explicit queues and repository
  state, using schemas that can be validated independently.
- Keep private-data processing on an approved local boundary. Cloud builders
  must operate only on cloud-safe repository content.
- Add tests or validation proportional to the change. Do not allow unrelated
  pre-existing failures to conceal the scoped result.
- Prefer read-only or shadow proofs before authoritative runtime mutation.
- For runtime-changing work, commit code first, execute through the reviewed
  runner/gateway/control plane, and capture machine-readable terminal evidence.
- Do not mark runtime-changing work complete until the required Pi verification
  has returned terminal evidence.

## Automated execution requirements

- `.github/workflows/lifeos-pi-auto-smoke.yml` is the recurring Pi automation
  health gate. It validates checkout identity, retired dispatcher state,
  Semaphore, protected LifeOS services, queue state and the GitHub runner.
- Automation health evidence is recorded in GitHub issue #29 and as workflow
  artifacts.
- A failing health gate must surface evidence and preserve safety boundaries;
  it must not attempt unrestricted self-repair.
- Avoid interactive confirmation prompts in fully automated paths. Safety must
  come from fixed preconditions, allow-lists, bounded mutation scope, rollback
  and post-change verification rather than repeated `YES` prompts.
- Shell automation should use `set -Eeuo pipefail` unless a documented reason
  requires otherwise.
- When root invokes Git against `/home/joshan/lifeos-platform`, run Git as
  `joshan` so repository ownership is preserved.
- Emit concise `KEY=VALUE` terminal markers for machine-readable evidence.
- Make deployment scripts idempotent or safely resumable where practical.

## Documentation

Document authority, trust boundaries and rollback expectations. Link to an
accepted decision record when current architecture differs from an older plan.
Clearly label unresolved decisions with `TODO`.
