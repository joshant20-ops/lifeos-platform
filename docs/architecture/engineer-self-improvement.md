# LifeOS Engineer self-improvement policy

LifeOS Engineer may improve its own user-facing engineering behaviour only through the normal GitHub review, test, verifier, and deployment path.

## Self-modifiable surface

The Engineer may autonomously propose and implement changes to its Open WebUI-facing behaviour, natural-language intent routing, job history and queue summaries, stuck-job detection and alerting logic, read-only observability APIs, tests, documentation, and other non-privileged Engineer worker code.

Every self-improvement must start from a reproducible acceptance-test failure, use a feature branch, preserve an auditable diff, run the relevant automated tests, and be independently verified before deployment. A self-improvement must not declare itself successful merely because it changed code; the original acceptance test must pass against the resulting implementation.

## Protected surface

The Engineer **must not self-modify** the root broker, privileged allow-list or scope policy, independent verifier, job publisher, job runner, secret-handling boundary, destructive-action policy, checksum enforcement, fail-closed queue gates, or the mechanism that decides whether the Engineer's own update is authorised.

Changes to a protected surface require a separately authorised control-plane task and must never be justified solely by a failing Engineer self-test.

## Initial acceptance contracts

1. Asking for all historical jobs returns the job history rather than silently substituting the latest job.
2. Asking what is running, queued, failed/blocked, or complete categorises the current job database accurately.
3. Asking whether a job is stuck uses deterministic runtime evidence such as elapsed time and stage progress rather than an LLM guess.
4. Stuck jobs are detectable independently of an active chat session so a notification path can consume them.
5. Status answers expose enough evidence to explain the current stage, elapsed time, iteration count, and failure/block reason where available.

## Stuck-job principle

A RUNNING job is not stuck merely because it is slow. The detector should compare elapsed time and stage age with recent completed-job history and use a conservative threshold. A job may also be classified as unexpectedly blocked when it remains queued or pending without expected progress and the reason is evidenced by the control plane. False positives should prefer a warning classification over automatic intervention.
