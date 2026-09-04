# Phase 1 current Engineer activation

The stale `activate-engineer-v1-660a6d4862fa` approval was quarantined during the runtime/Git ownership migration because its approved root-broker bytes no longer matched canonical `main`.

The replacement activation is `scripts/activate-current-engineer-runtime.sh`. It intentionally uses the existing `deploy-engineer-runtime` root-broker operation rather than adding a new privilege path.

Safety gates:
- exact migrated live root-broker SHA-256 is required;
- platform checkout must be clean published `main` (`HEAD == main == origin/main`);
- the three deploy sources must be tracked and compile;
- a fresh root-owned, mode `0600` approval is created for one unique job ID;
- the broker performs the bounded deployment, backup, health verification, rollback and audit;
- the activation validates audit source hashes and live installed hashes;
- read-only jobs/stuck/Open WebUI-compatible acceptance follows;
- malformed broker requests must remain rejected.

Success ends with `NEXT_REQUIRED=phase1_closure_review`.
