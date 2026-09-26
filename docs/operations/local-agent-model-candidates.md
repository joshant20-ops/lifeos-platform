# Local Agent Model Investigation and Decision

Status: complete, 2026-09-26

## Decision

Use `gpt-oss:20b` at 8192 context as the stock Agent Canvas/OpenHands local-agent model. It is the smartest practical model proved on the canonical Tower: repeated Ollama native calls were reliable, a fresh unmodified OpenHands conversation performed real file and terminal actions, and persisted events proved those actions were tools rather than JSON-looking assistant text.

`devstral-small-2:24b` also passed the full gate, but is not the default. It generated at about 2 tokens/s versus GPT-OSS at about 14.2 tokens/s and took about 421 seconds versus 201 seconds for the comparable OpenHands task. No observed task-quality advantage justified more than twice the interactive latency.

The production change is intentionally narrow: only the OpenHands local-AI gateway and persisted Canvas LLM settings move to GPT-OSS. Other Governor, verifier, Home Assistant and fallback routes remain on their existing models. The Pi 5 remains control-plane only; inference stays on Tower. SwitchLLM remains disabled.

## Hardware and method

Canonical source: `docs/operations/available-hardware.md`.

Tower: Intel i5-4690K (4C/4T), 32 GB DDR3-1600, NVIDIA P106-100 6 GB, Ollama 0.33.2. All comparisons used `num_ctx: 8192`. Workflows used the existing Governor lease and Wake-on-LAN lifecycle and stopped at 90 C. Agent acceptance used stock `ghcr.io/openhands/agent-canvas:1.23.0`, a fresh conversation, and no OpenHands application patch or JSON parser shim.

Acceptance required five exact native Ollama tool calls, then exact file creation/readback, a terminal-created second file, verification, normal finish, and persisted file-editor, terminal and finish actions with zero JSON-only `write_file` records.

## Results

| Candidate | Direct native tools | Stock OpenHands | Placement / memory | Performance and thermals | Decision |
|---|---:|---:|---|---|---|
| `gpt-oss:20b` | 5/5 | PASS: 24 events, 9 file actions, 1 terminal action, 2 finish actions, 0 JSON-only | 20.9B MXFP4, 14 GB; 35% GPU / 65% CPU; 5011 MiB VRAM; final 3.8 GiB host RAM used, 27 GiB available, no swap | direct mean 4.83 s; coding 14.21 tok/s; privacy 14.29 tok/s; OpenHands 200.5 s; GPU peak 49 C / 49.39 W. CPU temperature was unavailable in this run because the original sensor probe did not resolve the hwmon symlink. | **Selected** |
| `devstral-small-2:24b` | 5/5 | PASS: 20 events, 7 file actions, 1 terminal action, 1 finish action, 0 JSON-only | 24B Q4_K_M, 16 GB; 26% GPU / 74% CPU; 5029 MiB VRAM; final 4.4 GiB host RAM used, 26 GiB available, no swap | direct mean 24.76 s including cold first call (warm calls about 12.5 s); coding 1.94 tok/s; privacy 2.05 tok/s; OpenHands 420.75 s; CPU peak 77 C; GPU peak 43 C / 59.33 W | Accepted but too slow for default |
| `qwen3:30b-a3b` | One benchmark native call and 6/6 bounded routine cases; not the required repeated gate | Not promoted through the final stock OpenHands gate | Prior MoE investigation only | Unbounded simple code generation ran for minutes. `/no_think` and bounded-output variants were investigated in PRs #1107, #1109, #1113 and #1114. The work was explicitly abandoned before the newer acceptance plan. | Rejected for this route; do not retest without new runtime/model evidence |
| `qwen2.5-coder:7b-instruct` | Ollama works | FAIL | About 5 GB, 100% GPU at 8192 | Both OpenHands native and prompt modes emitted tool-shaped JSON as ordinary assistant text instead of executing tools. SwitchLLM was separately disabled through supported settings. | Retained only as gateway rollback; not an accepted agent |
| `qwen3-coder:30b`, `qwen3:14b` | Not run in the final phase | Not run | Candidate-plan entries only | Once GPT-OSS and Devstral both passed the real gate, another large download/thermal run could not change the evidence-backed default without first showing a likely material quality advantage. | Deferred, not silently treated as failures |

RAM figures are `free -h` host snapshots and therefore do not equal model allocation alone. Both viable models used partial GPU offload without swap pressure. GPT-OSS CPU thermals remain an evidence gap, but the GPU measurement was safe and Devstral's heavier CPU-resident run stayed at 77 C.

## Durable evidence

- Candidate plan: PR #1133.
- GPT-OSS workflow creation: PR #1134. Its initial merged run did appear; the final corrected acceptance is run `36155086170`, job `108137543231`, after PRs #1135, #1138 and #1139.
- Devstral workflow: PR #1140. Run `36253552944`, job `108435966530`, produced exact artifacts and real actions but returned OpenHands `error` after 826.45 seconds. The redacted diagnostic in PR #1235 showed no shim or fake action; corrected run `36255151834`, job `108440412206`, finished successfully with the measurements above.
- GPT-OSS gateway cutover: PR #1236. Initial deploy run `36256245663` found that `systemctl enable --now` did not reload an existing process. PR #1237 changed deployment to an explicit restart; subsequent deployment is the authoritative gateway proof.
- Persisted production settings and fresh gateway-backed OpenHands proof: run `36256533790`, job `108444257428`. Settings survived a full Canvas service restart; the fresh conversation finished in 290.69 seconds with exact artifacts, 36 persisted events, 15 file-editor actions, 1 terminal action, 2 finish actions and 0 JSON-only records. This is the cutover/persistence authority.

## Production route and rollback

The Pi service `lifeos-openhands-local-ai.service` remains the only production OpenHands-to-Tower path. It preserves the existing Tower lease, Wake-on-LAN and release lifecycle. It advertises GPT-OSS as the default and permits only:

- `gpt-oss:20b` — production OpenHands model;
- `qwen2.5-coder:7b-instruct` — explicit rollback target.

Persisted Canvas settings are:

- model `openai/gpt-oss:20b`;
- base URL `http://127.0.0.1:18114/v1` (the Pi lifecycle gateway, not Pi inference);
- native tool calling enabled;
- SwitchLLM disabled;
- security analyzer disabled as already accepted for this local route.

Rollback is a settings-only change back to `openai/qwen2.5-coder:7b-instruct` with native tool calling disabled; the gateway deliberately retains that model. This restores the former runtime without changing any unrelated LifeOS routing, although Qwen remains unsuitable for autonomous OpenHands tool work.

## Re-test policy

Do not repeat these downloads and thermal runs merely because a newer model exists. Reopen selection only when current Ollama support and model evidence indicate a material agent-quality improvement on this exact 32 GB / 6 GB VRAM host, and apply the same repeated-native-call plus persisted-stock-OpenHands gate.
