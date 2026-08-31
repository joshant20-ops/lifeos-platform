# LifeOS AI VM

Role: private/local AI execution, heavy document processing, embeddings, offline fallback, and sensitive-data workloads.

Control plane remains on Pi5 in `lifeos-governor`.

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
