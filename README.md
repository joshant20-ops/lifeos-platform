# lifeos-platform

Canonical source of truth for LifeOS.

All authoritative implementation belongs here: Homelab infrastructure, Home Assistant deployment, energy/Predbat/Octopus integration, forecast learning, financial accounting, tests, assurance tooling, documentation and deployment logic.

Sanitised engineering history and observed-state evidence live in separate
non-authoritative repositories. Live execution state and raw output remain local
to the Pi5 control plane.

## Repository contract

- Source changes are made here first.
- Executable relay jobs must identify an immutable `lifeos-platform` commit SHA.
- Pi5 exports sanitised history to `lifeos-jobs` and sanitised observations to
  `lifeos-snapshots`.
- Feedback is used to make the next canonical change here.
- Legacy repositories are retained only during gated migration and are retired
  after Pi5 proves the three-repository authority split.

See `architecture/REPOSITORY_MODEL.md` for the migration and trust model.

## Governance

The Pi5 Governor is the always-on control plane and Watchman is the sole gate for
runtime execution. Changes are proposed and reviewed through repository state;
workers exchange files and queue records rather than importing or calling one
another directly.

Start with:

- `docs/architecture_overview.md` for system boundaries and authority.
- `governance/communication.md` for worker communication rules.
- `docs/roadmap.md` and `docs/migration_strategy.md` for planned work and gates.
- `AGENTS.md` for repository-wide contributor instructions.

The repository contains existing runtime and deployment assets. Foundation-only
changes must not introduce new deployment code or Dockerfiles.
