# LifeOS AI governor

This is a small provider selector and evidence recorder, not an agent framework. It makes dry-run routing decisions; adapters or a human-controlled runner perform execution. GitHub remains the source-of-truth and audit boundary. Production work reaches the Pi only through the existing controlled `lifeos-pi-control` relay, using an immutable commit and verified artifact. The governor never opens a direct production SSH path.

## Roles and routing

Deterministic tools are the first choice. Normal substantial work routes to an available free cloud worker (Groq, Gemini, OpenRouter, then Cloudflare), followed by deterministic validation and, when meaningful, an independent free-provider review. Corrections are bounded by `max_retries`. Ollama/Qwen is for tiny work, classification, summarisation, and offline fallback—not substantial coding on this four-thread VM.

OpenHands is an optional execution framework which consumes the selected provider settings; it is not the sole intelligence. Codex is the scarce senior engineer/reviewer: normally one consolidated scheduled review per day, with immediate use limited to `HIGH_RISK`, repeated failures, conflicting reviewers, architecture/security decisions, or explicit human instruction. High-risk production changes stay human/senior gated.

The policy is zero-spend. Every cloud provider is marked `free_only`; there is no paid fallback or automatic model upgrade. A missing key reports `CREDENTIAL_REQUIRED`. A recorded `QUOTA_429` starts a cooldown so routing can select the next free provider. The hard retry cap is two.

## Usage

```sh
python3 engineer/ai-governor/governor.py --help
python3 engineer/ai-governor/governor.py health
python3 engineer/ai-governor/governor.py route --task "targeted change" --risk NORMAL
python3 engineer/ai-governor/governor.py route --task "review draft" --risk NORMAL --review-of groq
python3 engineer/ai-governor/governor.py route --task "run tests" --deterministic
python3 engineer/ai-governor/governor.py context path/to/file --max-bytes 32768
python3 engineer/ai-governor/governor.py check-promotion --base-commit "$BASE_COMMIT"
```

`route` is always a dry run and invokes nothing. Before promotion, the runner must show deterministic tests passed, independent review passed when requested, and `check-promotion` confirms `HEAD` still equals the job's base commit. A free-provider draft cannot bypass those gates.

State and machine-readable evidence default to `~/.local/state/lifeos-ai-governor/`, outside Git, with files written mode `0600`. Put real secrets in a separate mode-`0600` environment file; `.env.example` contains names only. Context packets are size-bounded and omit common credential/private-key filenames. Callers must target only necessary files and must not send secrets, private keys, credential stores, `.env` files, or unrelated repository content to cloud providers.

Provider models are configuration, including Cloudflare's free-allocation model. Operators must verify a configured model remains within the provider's free allocation; the governor will never substitute a paid model.

The systemd file is a template only. It is deliberately not installed or enabled.
