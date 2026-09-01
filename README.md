# lifeos-platform

Canonical source of truth for LifeOS.

All authoritative implementation belongs here: Homelab infrastructure, Home Assistant deployment, energy/Predbat/Octopus integration, forecast learning, financial accounting, tests, assurance tooling, documentation and deployment logic.

The companion `lifeos-pi-control` repository is transport only. It carries execution manifests, thin wrappers, Pi results and runner state. It must not become a second authoritative implementation repository.

## Repository contract

- Source changes are made here first.
- Executable relay jobs must identify an immutable `lifeos-platform` commit SHA.
- The Pi reports execution evidence through `lifeos-pi-control`.
- Feedback is used to make the next canonical change here.
- Legacy repositories are retained only during gated migration and are retired after the Pi proves the two-repository path.

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
