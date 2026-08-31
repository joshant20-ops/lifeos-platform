# LifeOS AI governor

This is a small provider selector, queue boundary and evidence recorder, not a second agent framework. GitHub remains the source-of-truth and audit boundary. Production work reaches the Pi only through the existing controlled `lifeos-pi-control` relay, using an immutable commit and verified artifact. The governor never opens a direct production SSH path.

## Roles and routing

Deterministic tools are the first choice. Normal substantial work routes to an available free cloud worker (Groq, Gemini, OpenRouter, then Cloudflare), followed by deterministic validation and, when meaningful, an independent free-provider review. Corrections are bounded by `max_retries`. Ollama/Qwen is for tiny work, classification, summarisation, and offline fallback—not substantial coding on this four-thread VM.

OpenHands is the engineering execution framework for queued implementation work; it consumes the provider selected by the governor. Codex is the scarce senior engineer/reviewer: normally one consolidated scheduled review per day, with immediate use limited to `HIGH_RISK`, repeated failures, conflicting reviewers, architecture/security decisions, or explicit human instruction. High-risk production changes stay human/senior gated.

The policy is zero-spend. Every normal cloud provider is marked `free_only`; there is no paid fallback or automatic model upgrade. A missing key reports `CREDENTIAL_REQUIRED`. A recorded `QUOTA_429` starts a cooldown so routing can select the next free provider. The hard retry cap is two.

## Automatic GitHub job intake

`github_issue_intake.py` polls the configured LifeOS repository and feeds the governor's single local queue. It does not create a second queue or a second GitHub publisher. Pull requests and untrusted issue authors are ignored.

An issue becomes eligible only when **both** of these are true:

1. its author is in `LIFEOS_GITHUB_ALLOWED_AUTHORS`; and
2. it contains `<!-- lifeos-engineer:ready -->` or has the configured `lifeos-engineer-ready` label.

Optional trusted issue metadata can set `<!-- lifeos-risk:HIGH_RISK -->`, `<!-- lifeos-context:path/to/file -->`, or `<!-- lifeos-accept:deterministic command -->`. The stable job ID is derived from repository + issue number. Queue creation uses `O_EXCL`, so repeated polling is idempotent and two intake attempts cannot create duplicate pending jobs.

Queued JSON lives below `LIFEOS_GOVERNOR_STATE_DIR/queue/`. `queue_worker.py` claims a pending file with an atomic rename, applies the normal governor risk/provider decision, and—only when run with `--execute`—creates an isolated Engineer git worktree and invokes the existing OpenHands adapter. It never deploys to the Pi, merges, or pushes. A successful implementation must pass its deterministic acceptance commands and `git diff --check`, then stops at `awaiting_review`. `HIGH_RISK` and `SENIOR_REVIEW` jobs are moved to `blocked` by the governor instead of being given to OpenHands.

This gives the intended flow:

```text
trusted GitHub issue marked ready
        ↓
github_issue_intake.py
        ↓
single governor pending queue
        ↓
risk/provider governor
        ↓
OpenHands isolated worktree
        ↓
deterministic acceptance
        ↓
awaiting_review
        ↓
existing review / promotion / Pi-control gates
```

The systemd intake and queue-worker files are templates. Validate token scope, checkout/state paths, ownership, dry-run intake and route-only worker behaviour before enabling them. The templates poll every five minutes; systemd prevents overlapping executions of the same oneshot service.

## Usage

```sh
python3 engineer/ai-governor/governor.py --help
python3 engineer/ai-governor/governor.py health
python3 engineer/ai-governor/governor.py route --task "targeted change" --risk NORMAL
python3 engineer/ai-governor/governor.py route --task "review draft" --risk NORMAL --review-of groq
python3 engineer/ai-governor/governor.py route --task "run tests" --deterministic
python3 engineer/ai-governor/governor.py context path/to/file --max-bytes 32768
python3 engineer/ai-governor/governor.py check-promotion --base-commit "$BASE_COMMIT"

# GitHub queue dry-run: reads eligible issues but writes no queue file.
python3 engineer/ai-governor/github_issue_intake.py --dry-run

# Normal intake: idempotently creates pending jobs.
python3 engineer/ai-governor/github_issue_intake.py

# Route one queued job without invoking OpenHands.
python3 engineer/ai-governor/queue_worker.py

# Production Engineer worker mode after independent validation.
python3 engineer/ai-governor/queue_worker.py --execute
```

`route` is always a dry run and invokes nothing. Before promotion, the runner must show deterministic tests passed, independent review passed when requested, and `check-promotion` confirms the promotion target still equals the job's base commit. A free-provider draft cannot bypass those gates.

State and machine-readable evidence default to `~/.local/state/lifeos-ai-governor/`, outside Git, with files written mode `0600`. Put real secrets in a separate mode-`0600` environment file; `.env.example` contains names only. Context packets are size-bounded and omit common credential/private-key filenames. Callers must target only necessary files and must not send secrets, private keys, credential stores, `.env` files, or unrelated repository content to cloud providers.

Provider models are configuration, including Cloudflare's free-allocation model. Operators must verify a configured model remains within the provider's free allocation; the governor will never substitute a paid model.

All systemd files in this directory are templates only. They are deliberately not installed or enabled by repository changes alone.
