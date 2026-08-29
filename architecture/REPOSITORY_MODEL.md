# LifeOS two-repository model

## End state

LifeOS uses exactly two active GitHub repositories.

### 1. `lifeos-platform` — source of truth

Authoritative implementation and documentation live here. This includes Homelab infrastructure, Home Assistant, LifeOS Energy, Predbat/Octopus integration, learning and financial tooling, deployment scripts, tests and assurance code.

### 2. `lifeos-pi-control` — execution relay

This private repository is the middleman between ChatGPT/GitHub and the Raspberry Pi. It contains only control-plane material: pending manifests, thin execution wrappers, completed manifests, structured results, captured output and runner state.

The relay must never become an independent implementation source.

## Execution identity

Every post-migration execution request must identify:

- canonical repository: `joshant20-ops/lifeos-platform`
- immutable source commit SHA
- canonical script path
- canonical script SHA-256
- target host
- job class
- timeout

A thin relay wrapper may fetch/verify/execute canonical content, but must not contain a divergent copy of business logic.

## Feedback loop

1. ChatGPT changes `lifeos-platform`.
2. The resulting immutable commit SHA is captured.
3. `lifeos-pi-control` queues a job referring to that SHA/path/hash.
4. The Pi verifies and executes the requested canonical artifact.
5. The Pi writes structured evidence to `lifeos-pi-control`.
6. ChatGPT reads the evidence and makes the next canonical source change.

## Migration gates

Legacy repositories are not deleted or archived until all gates pass:

1. Inventory legacy repository contents and outstanding work.
2. Import authoritative `LifeOS-Energy` content into `lifeos-platform/energy/` without losing the queued financial-history/export-accounting job.
3. Confirm the Pi has a clean/current checkout of both active repositories.
4. Prove a relay job can reference and execute an immutable `lifeos-platform` artifact.
5. Prove result feedback returns to `lifeos-pi-control`.
6. Prove Home Assistant, Predbat, LifeOS Energy, forecast recording and shadow learning remain healthy.
7. Reconcile all outstanding work as DONE / RUNNING / QUEUED / NOT_YET_QUEUED / BLOCKED.
8. Only then retire `LifeOS-Energy` and the unused `lifeos-control` repository.

## Fail-closed principle

Migration stops at the first failed gate. No legacy repository is retired on partial success. Runtime service paths may remain unchanged while source ownership moves to `lifeos-platform`; source consolidation must not require an unnecessary production-path migration.
