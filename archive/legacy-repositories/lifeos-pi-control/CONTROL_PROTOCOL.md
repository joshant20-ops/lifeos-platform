# LifeOS Pi Control Protocol

This private repository is the control channel between ChatGPT/GitHub and the LifeOS Raspberry Pi 5.

## Repository roles

- `joshant20-ops/lifeos-platform` is the single canonical source of truth.
- `joshant20-ops/lifeos-pi-control` is execution transport, results and runner state only.
- Relay jobs must not become a divergent copy of LifeOS implementation code.

## Trust model

The Pi MUST NOT execute arbitrary repository content. A job is executable only when all applicable checks pass:

1. Repositories are fetched from configured GitHub remotes.
2. Local branches update by fast-forward only.
3. The manifest is valid JSON and targets the configured Pi.
4. `job_type` is an allowed class.
5. Bootstrap/legacy jobs reference a script under the approved relay script path.
6. Post-migration jobs identify an immutable `lifeos-platform` source commit, canonical script path and SHA-256.
7. The canonical source commit exists locally after fetch and exactly matches the manifest.
8. The canonical script SHA-256 exactly matches the manifest before execution.
9. Gitleaks reports no secret in the manifest, wrapper or canonical script.
10. The job ID has never previously completed.
11. Only one runner instance holds the execution lock.
12. Execution is constrained by the manifest timeout.

## Job classes

- `diagnostic`: read-only inspection. May run unattended.
- `change`: may alter the host/repositories only when the runner's gated change authority is enabled.

## Repository layout

- `jobs/pending/` job manifests awaiting execution.
- `jobs/scripts/` legacy/bootstrap scripts or thin wrappers only.
- `jobs/archive/` completed manifests written by the Pi.
- `results/` structured execution results and captured output written by the Pi.
- `state/` runner health/status written by the Pi.

## Manifest v1 — bootstrap/legacy

```json
{
  "schema_version": 1,
  "job_id": "unique-id",
  "target": "pi5",
  "job_type": "diagnostic",
  "script": "jobs/scripts/example.sh",
  "script_sha256": "64 lowercase hexadecimal characters",
  "timeout_seconds": 120,
  "created_by": "chatgpt",
  "description": "Human readable purpose"
}
```

## Manifest v2 — canonical platform execution

Target end-state contract:

```json
{
  "schema_version": 2,
  "job_id": "unique-id",
  "target": "pi5-docker",
  "job_type": "change",
  "source_repo": "joshant20-ops/lifeos-platform",
  "source_commit": "40 hexadecimal commit SHA",
  "source_script": "energy/scripts/example.sh",
  "source_sha256": "64 lowercase hexadecimal characters",
  "timeout_seconds": 300,
  "created_by": "chatgpt",
  "description": "Human readable purpose"
}
```

The runner must refuse v2 execution if `source_repo` is not the configured canonical repository or if the source commit/path/hash cannot be proven exactly.

## Result contract

For every claimed job, the Pi records at least:

- job ID
- relay manifest Git commit SHA
- canonical source repository/commit/path when applicable
- canonical script SHA-256
- start/end timestamps
- elapsed seconds
- exit code
- classification (`PASS`, `FAIL`, `TIMEOUT`, `REJECTED`)
- host identity
- captured stdout/stderr

Raw output remains in this PRIVATE repository.

## Execution policy

A failure does not cause the next job to run automatically during the same invocation. The runner processes at most one pending job per invocation. This preserves the LifeOS pause/fix/resume workflow.

Migration/bootstrap jobs may use manifest v1 only to establish and prove the v2 path. After v2 is proven, new implementation jobs should use canonical `lifeos-platform` artifacts rather than implementation payloads stored in this relay repository.
