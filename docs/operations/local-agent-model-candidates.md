# Local Agent Model Candidate Audit

Date: 2026-09-25

## Hardware envelope

Canonical source: `docs/operations/available-hardware.md`.

Tower: i5-4690K 4C/4T, 32 GB DDR3-1600, NVIDIA P106-100 6 GB, Ollama 0.33.2. Current Qwen2.5-Coder 7B uses about 5 GB and is verified 100% GPU at 8192 context.

## Acceptance gate

A replacement must work through stock Agent Canvas/OpenHands without a LifeOS parser or application patch. It must reliably invoke real file and terminal tools rather than printing JSON that resembles tool calls. Evaluate repeated create/read/verify file operations, terminal execution, persistence, latency, RAM/VRAM placement, sustained thermals and power.

## Candidates

1. `gpt-oss:20b` — 14 GB Ollama package, 20.9B parameters, 128K advertised context, explicit function-calling/agentic support. Primary general-agent candidate.
2. `devstral:24b` — 14 GB Q4 package, 24B, 128K advertised context. Built with All Hands AI specifically for software-engineering agents and evaluated with the OpenHands scaffold. Primary Engineer candidate.
3. `qwen3-coder:30b` — 19 GB Q4_K_M, 30.5B MoE / ~3.3B active, 256K advertised context, explicit tools support. High-intelligence sparse candidate, but expected to depend heavily on system RAM with only 6 GB VRAM.
4. `qwen3:14b` — 9.3 GB package, explicit tools support. Lower-memory fallback candidate.

## Test policy

- Keep context at 8192 initially for a fair comparison and to limit KV-cache pressure.
- Do not replace the current production model until a candidate passes functional acceptance.
- Do not modify OpenHands application code to accommodate a model.
- Test native tool calling first where the model/runtime explicitly supports it.
- Record Ollama placement, load size, prompt/eval throughput, RAM, VRAM, CPU/GPU utilisation and thermals.
- Stop a candidate if memory pressure threatens host stability or tool calls are not real structured calls.
- Prefer job-level model routing if different models clearly win Governor/general-agent and Engineer/coding-agent roles.
