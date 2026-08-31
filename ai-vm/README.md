# LifeOS AI VM

Role: private/local AI execution, heavy document processing, embeddings, offline fallback, and sensitive-data workloads.

Control plane remains on Pi5 in `lifeos-governor`, but Pi5 is not a transport/proxy hop for AI VM jobs.

## Control and transport model

- GitHub is the shared source of truth and job/result transport.
- AI VM pulls its own `ai-vm`-targeted jobs and immutable artifacts directly from GitHub.
- AI VM publishes its own results directly back to GitHub.
- Pi5 Governor reads shared state from GitHub and coordinates policy, priorities, and scheduling.
- Pi5 must not relay scripts/files to AI VM as part of normal execution.
- Multi-node runners ignore jobs for other targets, so `pi5-docker` and `ai-vm` can safely share one relay repository.

## Provider policy

1. Cloud/Codex is primary for normal non-sensitive engineering/AI work.
2. Private document/data processing stays local on AI VM by default.
3. Ollama on AI VM is the offline fallback when cloud providers are unavailable.
4. AI VM must not become a second Governor/control plane.
5. AI-dependent work fails closed when no approved provider is available.

## Planned workloads

- Ollama local inference
- Paperless heavy task worker / OCR where supported by current deployment
- embeddings / local RAG
- private document classification and summarisation
- offline LifeOS AI fallback

Actual Paperless topology is discovered before any migration. No assumptions are made about storage, broker, database, or current host placement.
