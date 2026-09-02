# OTS Engineer orchestration

## Decision and current state

Semaphore UI is the target orchestration and audit service. The 2026-09-02 architecture update supersedes Rundeck after its official image proved amd64-only on the ARM64 Pi5; production emulation is prohibited. A pinned Semaphore shadow definition exists under `orchestration/semaphore`. Runtime acceptance is pending and the working compatibility path remains unchanged.

The current path is Engineer -> autonomous agent -> custom builder/publication/runtime loop -> LifeOS submission bridge/root broker -> services. Git-owned staging, pending, archive, results, and runtime scripts currently carry both source and transient execution state.

The target path is Engineer -> canonical `lifeos-platform` source -> bounded LifeOS policy/client -> Semaphore -> version-controlled Ansible -> #26 transaction controller -> bounded submission bridge/root broker -> Pi5, Docker, and Home Assistant. Semaphore receives no generic sudo, arbitrary root shell, caller-selected root path, or wildcard service authority.

## Ownership

| Component | Ownership |
| --- | --- |
| GitHub | Canonical definitions, source, history, and redacted final evidence |
| Engineer | Request understanding, edits, builds, tests, and execution requests |
| Semaphore UI | Scheduling, queueing, retries, task state, logs, history, and operator UI |
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
| #26 protected transaction controller and watchdog | KEEP | Independent safety boundary for every privileged mutation |
| Existing Ansible baseline | KEEP | Seed for the version-controlled execution catalogue |
| Failed Rundeck shadow | RETIRE_AFTER_SHADOW | Preserve generic evidence/contracts, keep stopped, and remove only after Semaphore equivalence |
| Semaphore shadow | KEEP | Selected native-ARM64 OTS execution plane; remains non-production until accepted |
| Filesystem queue promotion | RETIRE_AFTER_SHADOW | Semaphore will own queueing |
| Custom retry scheduler | RETIRE_AFTER_SHADOW | Semaphore will own retries/history |
| Custom execution state and UI | RETIRE_AFTER_SHADOW | Semaphore will own state, logs, and UI |
| Git/runtime queue synchronisation | RETIRE_AFTER_SHADOW | Runtime state must not be source |
| Existing runner/publisher | TEMPORARY_COMPATIBILITY | Rollback and equivalence reference |

## Migration stages

1. Enforce artifact publication and builder-routing invariants in the compatibility path.
2. Runtime-validate the LAN-only Semaphore shadow deployment in `orchestration/semaphore`, including native ARM64 resolution, persistence, external secrets, health, restart policy, limits, and backup/restore.
3. Add an unprivileged Ansible control project. Privileged playbooks submit fixed LifeOS operations to the existing bridge; they never invoke arbitrary privileged shell.
4. Shadow harmless health, identity/status, timeout, malformed-input, retry, concurrency, audit, failure, privilege, and restart/recovery scenarios through both paths.
5. Require equivalent decisions, complete audit evidence, fail-closed behavior, and no privilege expansion for a defined observation window.
6. Disable custom scheduling/state components individually. Preserve their code and historical evidence for rollback until the post-cutover window closes.

## Security and rollback

Semaphore binds only to an explicit LAN address and reads credentials from root-owned files outside Git. Its execution identity is unprivileged. Read-only checks use ordinary Ansible modules; mutations call allow-listed LifeOS interfaces and must enter the #26 transaction controller before mutation. Inventory variables may identify services but cannot select root paths or commands.

Rollback stops new Semaphore submissions, drains or marks active tasks, and keeps or re-enables the compatibility scheduler at its last recorded FIFO position while verifying that no operation is duplicated. The accepted activation `activate-engineer-v1-660a6d4862fa` is preserved and must be resumed exactly once; its assured broker SHA256 remains `a15e9c2b0f2ed31600d936eaa1b64d61fc094779a49542267b73c78cfa701417`.

## Shadow acceptance criteria

Shadow mode must demonstrate equivalent health results and deterministic job identity/status; bounded timeout and retry behavior; malformed request rejection; safe concurrency; complete redacted audit records; faithful failure propagation; no privilege escalation; and restart recovery without duplicate execution. No destructive cutover is permitted before all criteria pass and rollback has been rehearsed.
