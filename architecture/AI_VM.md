# LifeOS AI VM

## Role

The former Engineer VM is retained and repurposed as the LifeOS **AI VM**.

It is not the primary Governor or control plane. Pi5 remains the always-on Governor/control node.

The AI VM provides local/private AI capabilities that remain available when cloud AI services are unavailable and provides an isolation boundary for sensitive document and data processing.

## Responsibilities

- Host Ollama and approved local models.
- Provide an offline AI fallback for LifeOS when cloud AI/Codex is unavailable.
- Process private documents and sensitive personal data locally.
- Provide local embeddings, classification, summarisation and extraction services for document workflows.
- Act as an optional heavy-compute AI worker for the Pi5 Governor.
- Keep private source documents and derived indexes off cloud AI paths unless explicitly allowed by policy.

## AI routing policy

1. Normal engineering/orchestration work: cloud/Codex first.
2. Private-data tasks: AI VM local models first by default.
3. Cloud outage/unavailable primary AI: AI VM Ollama fallback.
4. If both cloud AI and AI VM are unavailable, Governor fails closed for AI-dependent actions.

## Current local model

- Ollama
- qwen2.5-coder:7b-instruct

Additional models may be added later for document understanding, embeddings or vision, provided they are justified by a defined workload.

## Privacy boundary

Sensitive documents and private datasets should be processed locally on the AI VM. The Governor may send task metadata and references, but should not forward private document contents to cloud AI unless an explicit policy permits it.

Document workflows should separate:

- raw/private source files
- extracted text
- embeddings/vector indexes
- generated summaries/metadata
- cloud-safe/redacted derivatives

## Relationship to Pi5 Governor

Pi5 hosts the always-on LifeOS Governor container. The Governor owns orchestration, health, routing and policy. The AI VM owns local model execution and private-data AI workloads.

The Governor should treat the AI VM as a remote provider/worker and should not require Ollama or large models inside the Pi5 Governor container.

## Naming

Logical service name: `ai-vm`

The underlying Proxmox VM and Linux hostname may continue to use the historical `Engineer` name until a controlled rename is performed. Renaming should be treated as a separate migration because hostnames can be referenced by SSH configuration, monitoring, scripts, DNS and automation.
