# LifeOS engineering role boundaries

- **Deterministic tools** are the first choice for tests, linting, Git checks, health gates, and any task that does not need an LLM.
- **Free cloud models** are normal substantial engineering workers and independent reviewers. They remain zero-spend, receive compact targeted context, and cannot promote work without deterministic evidence.
- **OpenHands** is an optional agent/execution framework that uses governor-selected local or cloud intelligence. It is not the sole intelligence or an authority boundary.
- **Ollama/Qwen** handles tiny jobs, classification, summarisation, and offline fallback. It is not preferred for substantial coding on the four-thread Engineer VM.
- **Codex** is the scarce senior engineer/reviewer. Use one consolidated scheduled review per day in normal operation; escalate immediately only for high risk, repeated failure, conflicting reviewers, architecture/security decisions, or explicit human direction.
- **GitHub (`lifeos-platform`)** is the authoritative source and change/audit boundary. Promotion must detect concurrent movement of `main` and retain machine-readable evidence.
- **The Pi** is a controlled execution target, not an AI scratchpad. All execution continues through the existing `lifeos-pi-control` relay with immutable source identity; the governor does not create a direct SSH mutation route.

High-risk production changes remain human/senior gated. Secrets and runtime credentials stay outside Git.
