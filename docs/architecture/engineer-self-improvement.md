# LifeOS Engineer self-improvement policy

LifeOS Engineer may improve its own user-facing engineering behaviour only through the normal GitHub review, test, verifier, and deployment path.

## Self-modifiable surface

The Engineer may autonomously propose and implement changes to its Open WebUI-facing behaviour, natural-language intent routing, job history and queue summaries, stuck-job detection and alerting logic, read-only observability APIs, tests, documentation, and other non-privileged Engineer worker code.

Every self-improvement must start from a reproducible acceptance-test failure, use a feature branch, preserve an auditable diff, run the relevant automated tests, and be independently verified before deployment. A self-improvement must not declare itself successful merely because it changed code; the original acceptance test must pass against the resulting implementation.

## Protected surface

The Engineer **must not self-modify** the root broker, privileged allow-list or scope policy, independent verifier, job publisher, job runner, secret-handling boundary, destructive-action policy, checksum enforcement, fail-closed queue gates, or the mechanism that decides whether the Engineer's own update is authorised.

Changes to a protected surface require a separately authorised control-plane task and must never be justified solely by a failing Engineer self-test.

## Bounded runtime deployment transaction

An Engineer job may opt in to a post-verification `deploy-engineer-runtime` request. The request sent across the root-broker socket contains exactly the operation name, job ID, and canonical target identity. It cannot name a command, source, destination, service, checksum, or argument. A successful builder run or deployment is not approval.

The protected control plane must first create a root-owned, non-group/world-writable approval record at `/var/lib/lifeos-control/engineer-deploy-approvals/<job-id>.json`. That record binds the job to the exact published `main` commit, both allow-listed source hashes, an independent-verifier PASS evidence ID, and a protected-policy PASS evidence ID. The Engineer cannot create this evidence. Missing, malformed, writable, refused, stale, or mismatched evidence fails closed.

The broker independently requires a clean canonical `/home/joshan/lifeos-platform` checkout whose `HEAD` and local `main` are the approved commit. It rejects symlinked or unexpectedly owned sources and destinations, verifies both source hashes and Python syntax, and can only map:

- `governor/autonomous_agent.py` to `/usr/local/libexec/lifeos-autonomous-agent`
- `governor/engineer_backend.py` to `/usr/local/libexec/lifeos-engineer`

The transaction takes a non-blocking exclusive lock, backs up both installed files, atomically replaces each file, restarts only `lifeos-autonomous-agent.service` and `lifeos-engineer.service`, and waits for the fixed ports 8790 and 8793 health endpoints. Any installation, restart, or health failure restores both backups, restarts both services, and verifies rollback health. A root-owned audit record preserves commit, hashes, backup location, deployment result, and rollback result.

Because the root broker and its operation allow-list are protected surfaces, adding this transaction to the installed broker requires explicit control-plane approval. Repository tests and an independent review must pass before that bounded activation; the Engineer may not install or approve the broker change itself.

## Initial acceptance contracts

1. Asking for all historical jobs returns the job history rather than silently substituting the latest job.
2. Asking what is running, queued, failed/blocked, or complete categorises the current job database accurately.
3. Asking whether a job is stuck uses deterministic runtime evidence such as elapsed time and stage progress rather than an LLM guess.
4. Stuck jobs are detectable independently of an active chat session so a notification path can consume them.
5. Status answers expose enough evidence to explain the current stage, elapsed time, iteration count, and failure/block reason where available.

## Stuck-job principle

A RUNNING job is not stuck merely because it is slow. The detector should compare elapsed time and stage age with recent completed-job history and use a conservative threshold. A job may also be classified as unexpectedly blocked when it remains queued or pending without expected progress and the reason is evidenced by the control plane. False positives should prefer a warning classification over automatic intervention.
