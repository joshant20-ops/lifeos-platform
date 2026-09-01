# LifeOS Engineer GitHub Run Records

This file defines the standing output contract for LifeOS Engineer jobs.

## Purpose

Every Engineer/control-loop run should leave a sanitised, GitHub-readable record so the cloud control/round-up chat can inspect progress without requiring terminal output to be pasted manually.

## Canonical location

Write one record per job under:

`docs/operations/engineer-runs/<job-id>.md`

Also maintain:

`docs/operations/engineer-runs/latest.md`

`latest.md` should contain the same sanitised summary/evidence as the most recent completed or materially updated job, plus the job ID and timestamp.

## Required record content

Each record should include, where applicable:

- job ID
- UTC/BST timestamp
- status and stage
- elapsed time
- iteration count
- request summary
- important implementation changes
- files/commits/branches/PRs affected
- tests and CI results
- runtime result and verifier result
- current blocker, if any
- exact next safe action
- whether human action is required
- service health evidence
- relevant queue/publisher/runner/root-broker state
- live acceptance results

Prefer concise structured text over raw multi-megabyte logs. Include the decisive error/output excerpts needed to diagnose failures.

## Redaction rules

Redact before writing or committing. Never commit raw:

- passwords
- API keys
- bearer tokens
- OAuth/session tokens
- cookies
- private SSH keys or key material
- access tokens embedded in URLs
- Authorization headers
- secret environment variables
- secret-file contents
- recovery codes or credentials

Use `[REDACTED]` in place of removed values.

Paths, service/unit names, job IDs, commit SHAs, checksums, local hostnames, local IP addresses, ports, non-secret usernames, repository names and ordinary diagnostic metadata may remain when needed for engineering diagnosis.

Do not copy entire environment dumps. If a command could expose secrets, sanitise its output before recording it.

## Safety boundary

Publishing a run record is observability only. It must not bypass or weaken the existing verifier, publisher, runner, root-broker, checksum, allow-list, approval, backup, privacy, secret or fail-closed controls.

A failed record publication must not turn an otherwise failed engineering job into PASS. Record publication should itself fail closed with a clear diagnostic, while preserving the underlying job result.

## Standing instruction

Future LifeOS Engineer jobs should update the GitHub run record automatically whenever a job:

- completes,
- becomes BLOCKED/HUMAN_ACTION_REQUIRED,
- becomes genuinely stuck,
- changes stage materially after an extended run,
- or produces decisive new evidence that changes the next action.

The cloud control chat may use these files as the primary source for checking Engineer progress and job outcomes.
