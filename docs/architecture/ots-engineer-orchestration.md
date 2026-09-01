# OTS Engineer orchestration

## Decision and current state

Ansible Semaphore is the target orchestration and audit service. The repository snapshot does not contain Semaphore, AWX, Rundeck, or Woodpecker deployment definitions, so no existing locally hosted equivalent is established here. This decision does not claim that a live-host inventory has run.

The current path is Engineer -> autonomous agent -> custom builder/publication/runtime loop -> LifeOS submission bridge/root broker -> services. Git-owned staging, pending, archive, results, and runtime scripts currently carry both source and transient execution state.

The target path is Engineer -> canonical `lifeos-platform` source -> bounded LifeOS policy/client -> Semaphore -> version-controlled Ansible -> bounded submission bridge/root broker -> Pi5, Docker, and Home Assistant. Semaphore receives no generic sudo, arbitrary root shell, caller-selected root path, or wildcard service authority.

## Ownership

| Component | Ownership |
| --- | --- |
| GitHub | Canonical definitions, source, history, and redacted final evidence |
| Engineer | Request understanding, edits, builds, tests, and execution requests |
| Semaphore | Scheduling, queueing, retries, task state, logs, history, and operator UI |
| Ansible | Deterministic, version-controlled automation |
| LifeOS policy/client | Allow/deny decisions and constrained request construction |
| Submission bridge/root broker | Final narrow privileged boundary |
| Local runtime | Actual Pi5, Docker, and Home Assistant state |

Runtime staging, pending, archive, results, locks, generated launchers, and transient status must move outside Git. Historical evidence remains read-only during migration.

## Component disposition

| Existing component | Disposition | Rationale |
| --- | --- | --- |
| Request understanding and privacy classification | KEEP | LifeOS-specific intent and data boundary |
| Policy and approval semantics | KEEP | Security decision point |
| Submission bridge and root broker | KEEP | Narrow privileged boundary |
| Service-specific integration logic | KEEP | Retain where no mature module exists |
| Filesystem queue promotion | RETIRE AFTER SHADOW | Semaphore owns queueing |
| Custom retry scheduler | RETIRE AFTER SHADOW | Semaphore owns retries/history |
| Custom execution state and UI | RETIRE AFTER SHADOW | Semaphore owns state, logs, and UI |
| Git/runtime queue synchronisation | RETIRE AFTER SHADOW | Runtime state must not be source |
| Existing runner/publisher | TEMPORARY COMPATIBILITY | Rollback and equivalence reference |

## Migration stages

1. Enforce artifact publication and builder-routing invariants in the compatibility path.
2. Add a LAN-only Semaphore deployment with persistent storage, secrets supplied outside Git, health checks, restart policy, resource limits, and backup/restore procedures.
3. Add an unprivileged Ansible control project. Privileged playbooks submit fixed LifeOS operations to the existing bridge; they never invoke arbitrary privileged shell.
4. Shadow harmless health, identity/status, timeout, malformed-input, retry, concurrency, audit, failure, privilege, and restart/recovery scenarios through both paths.
5. Require equivalent decisions, complete audit evidence, fail-closed behavior, and no privilege expansion for a defined observation window.
6. Disable custom scheduling/state components individually. Preserve their code and historical evidence for rollback until the post-cutover window closes.

## Security and rollback

Semaphore binds only to an explicit LAN address and uses credentials injected at deployment time. Its execution identity is unprivileged. Read-only checks use ordinary Ansible modules; mutations call allow-listed LifeOS interfaces. Inventory variables may identify services but cannot select root paths or commands.

Rollback stops new Semaphore submissions, drains or marks its active tasks, re-enables the compatibility scheduler at the last recorded FIFO position, and verifies that no operation is duplicated. The accepted activation `activate-engineer-v1-660a6d4862fa` is preserved and must be resumed exactly once; its assured broker SHA256 remains `a15e9c2b0f2ed31600d936eaa1b64d61fc094779a49542267b73c78cfa701417`.

## Shadow acceptance criteria

Shadow mode must demonstrate equivalent health results and deterministic job identity/status; bounded timeout and retry behavior; malformed request rejection; safe concurrency; complete redacted audit records; faithful failure propagation; no privilege escalation; and restart recovery without duplicate execution. No destructive cutover is permitted before all criteria pass and rollback has been rehearsed.
