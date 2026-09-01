# LifeOS repository instructions

These instructions apply throughout this repository.

## Authority and safety

- Treat this repository as the canonical source of truth for LifeOS source,
  policy, tests and documentation.
- Treat Pi5 as the always-on control plane and canonical Git writer.
- Route runtime execution through Watchman. Do not bypass its policy checks.
- Never commit credentials, private keys, tokens, private document contents,
  personal information, private addresses or host-specific secrets.
- Do not invent hardware capabilities. Record unknowns as `TODO` items.

## Change discipline

- Propose changes on a review branch and require independent validation before
  merge. Pi5-owned automation performs publication and runtime execution.
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

## Documentation

Document authority, trust boundaries and rollback expectations. Link to an
accepted decision record when current architecture differs from an older plan.
Clearly label unresolved decisions with `TODO`.
