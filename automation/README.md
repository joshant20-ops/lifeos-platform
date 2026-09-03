# LifeOS GitHub automation

This directory contains the GitHub-driven deployment control plane for the Pi5.

Design principles:

- GitHub `main` is the source of truth.
- A dedicated self-hosted runner performs only unprivileged checkout/orchestration work.
- Privileged host mutations are delegated to the root-owned `lifeos-deploy-gateway` allow-list.
- The gateway accepts a named operation, never arbitrary shell.
- Every operation emits machine-readable `KEY=VALUE` evidence and is captured by GitHub Actions.
- Routine diagnostics, retries and idempotent reconciliation require no interactive `YES` prompts.
- High-risk/destructive operations remain outside the automatic allow-list and must use a separately reviewed path.

Initial automatic operation catalogue:

- `audit-dispatcher-retirement` — read-only retirement audit.
- `retire-engineer-dispatcher` — current gated dispatcher retirement script.

The initial rollout deliberately keeps the existing LifeOS root broker, control-job socket, autonomous agent, Engineer service and Semaphore boundaries unchanged.
