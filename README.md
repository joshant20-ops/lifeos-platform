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
