# Runtime ownership

`lifeos-pi-control` is the controlled execution transport and runtime evidence boundary. `joshant20-ops/lifeos-platform` is the single canonical source for executable control-plane definitions, including the publisher, runner and root broker. This repository must not retain duplicate executable source copies.

## Git-owned paths

Only transport policy/metadata belongs in this repository's Git history, principally:

- `.github/`
- `.gitignore`
- `CONTROL_PROTOCOL.md`
- `README.md`
- `RUNTIME_OWNERSHIP.md`

Executable desired state is owned by `lifeos-platform` and deployed from an immutable canonical commit.

## Runtime-owned paths

The following paths are deliberately ignored and must never be committed:

- `jobs/staging/`
- `jobs/staged/` (legacy spelling retained only for migration protection)
- `jobs/pending/`
- `jobs/archive/`
- `jobs/scripts/`
- `jobs/change-scripts/`
- `jobs/root-scripts/`
- `results/`
- `state/`

These directories may contain accepted work, immutable script artifacts, job manifests, logs, results, replay state, locks and other operational evidence. Git updates must not overwrite or delete their live contents.

## Migration rule

Removing a runtime-owned path from Git means removing it from the repository index/history tip, not deleting the live runtime file. A live migration must preserve the filesystem contents first, update the checkout to the new Git tip without allowing checkout deletion to destroy those contents, and verify the preserved files before returning the control plane to service.

The historical `activate-engineer-v1-660a6d4862fa` job is preserved as evidence but must not be executed after its assured root-broker bytes have become stale relative to canonical `lifeos-platform`. A gated migration quarantines that manifest and uses fresh live evidence to build any successor activation.

## CI invariants

CI fails if:

1. any runtime-owned path becomes tracked again; or
2. duplicate executable control sources are reintroduced under `publisher/`, `runner/` or `broker/`.

This prevents runtime/Git ownership collisions and prevents a stale relay copy from competing with the canonical platform source.
