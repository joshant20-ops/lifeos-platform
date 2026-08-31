# LifeOS three-repository authority model

## Purpose

LifeOS separates **desired state**, **engineering history**, and **observed live state** so that backups or runtime observations can never become deployment authority by accident.

## Repositories

### `lifeos-platform` — desired state

This repository is the only canonical source of what LifeOS **should be**.

It owns:
- application and service code
- deployment logic
- systemd/container definitions
- Home Assistant configuration templates and integration code
- policies and tests
- control-plane source code

Only commits to `lifeos-platform` may define deployable desired state.

### `lifeos-jobs` — durable engineering audit trail

This repository records what engineering work was requested and how it concluded.

It may contain:
- job ID and request
- privacy classification
- created/started/completed timestamps
- final status and stage
- iteration count
- verifier verdict/reason
- failure signature and repeated-failure count
- resulting platform commit references

It must **not** contain raw runtime evidence, secrets, credentials, private documents, Home Assistant history, email/document contents, or cloud-inappropriate personal data.

The live queue remains local under `/var/lib/lifeos-agent`. Git is not used for locks, heartbeats, or rapidly changing RUNNING state.

### `lifeos-snapshots` — sanitised observed state

This private repository records what the running system **actually looks like** at a point in time.

It may contain:
- host/service health state
- installed binary/config hashes
- repository HEADs
- container image names/tags and health state
- drift comparisons against desired state
- timestamps and host role identifiers

It must not contain secrets, environment variable values, private document data, credentials, tokens, raw Home Assistant history, or arbitrary logs.

## Authority rules

1. `lifeos-platform` is the only deployment authority.
2. `lifeos-jobs` is append-only engineering history from the deployment system's point of view.
3. `lifeos-snapshots` is evidence only.
4. Snapshot data may report drift but must never overwrite, restore, seed, or otherwise mutate `lifeos-platform`.
5. A mismatch between desired and observed state produces a drift report or engineering job; it does not copy the observed file into desired state.
6. Control-plane binaries that require root installation use explicit host-authorised bootstrap. Observed live copies are never promoted back into Git automatically.
7. Live runtime job state remains local and is exported to `lifeos-jobs` only as a sanitised durable record.

## Data flow

```text
lifeos-platform (desired)
        |
        v
Pi5 controller -> Engineer/Codex -> Pi5 runtime -> local verifier
        |                                  |
        |                                  v
        +---- sanitised job record ----> lifeos-jobs
                                           
Running hosts ---------------- sanitised state ----> lifeos-snapshots
        ^
        |
        +---- compare only; never restore desired state ---- lifeos-platform
```

## Repository visibility

- `lifeos-platform`: retain current visibility/access policy.
- `lifeos-jobs`: private recommended.
- `lifeos-snapshots`: private required.

## Migration rule

The split is introduced without moving deployable source out of `lifeos-platform`. Existing automation continues to run while job-history and observed-state exporters are enabled. Only after the exporters are proven should legacy snapshot/protection mechanisms that can write toward desired state be removed.
