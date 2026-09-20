# Workflow governance

LifeOS workflows are an operational API. Keep the active surface small and intentional.

## Classes
- **ci** — deterministic tests/contracts. Prefer one workflow per domain suite.
- **deploy** — deploy desired state. Deployment and acceptance may share one workflow when tightly coupled.
- **health** — recurring/live verification of an already deployed capability.
- **control** — operator entry points such as Mission Control.
- **maintenance** — scheduled upkeep.
- **recovery** — restore/reconciliation paths that remain genuinely reusable.
- **temporary** — migration, investigation, incident or milestone workflow. Must have a removal condition.

## Rules
1. Search `.github/workflows` and this registry before adding a workflow.
2. Extend an existing workflow when the trigger, runner and responsibility substantially overlap.
3. Put repeated implementation in `.github/actions`, scripts, or a reusable `workflow_call`; wrappers should stay thin.
4. A temporary workflow must state its issue/milestone and removal condition in the registry.
5. Completed temporary workflows leave `.github/workflows`. Historical copies belong in `archive/workflows`; Git history is authoritative.
6. CI/contract coverage must be transferred before archiving a milestone workflow.
7. No workflow may be hard-coded to a closed issue.
8. Each active workflow has one primary class and one domain owner.
9. Quarterly, and after each Wave closes, audit the registry for duplicates and expired temporary workflows.

## Target active structure
Prefer these durable families:
- platform CI + contracts
- governed AI routing/deployment
- Pi deployment + health
- Tower lifecycle + health
- Home Assistant / energy deployment + health
- Personal Administration mission control
- Paperless exception-semantic integration
- backup / restore / snapshot
- Wave-specific contracts only while that Wave is active

## Archive policy
Files in `archive/workflows` are evidence only and are intentionally outside GitHub Actions' executable workflow directory.
