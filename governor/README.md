# LifeOS Governor

The LifeOS Governor is the lightweight always-on orchestration and policy service for Pi5.

## Placement

- Runs as its own Docker container on `pi5-docker`.
- Does **not** contain a local LLM.
- Does **not** store Codex/OpenAI credentials in the image.
- Does **not** run OpenHands.

## AI policy

1. Cloud/Codex is the primary engineering path while cloud access is healthy.
2. Z97 Ollama is the offline fallback path.
3. The fallback model is expected to be `qwen2.5-coder:7b-instruct` unless explicitly overridden.
4. Provider failure must fail closed: no unapproved host changes are performed merely because the preferred provider is unavailable.
5. The Governor selects and reports a provider; execution remains behind the existing LifeOS gated job/control plane.

## Responsibilities

The Governor owns orchestration, not privileged execution:

- maintain provider health and selection state;
- select cloud primary vs Z97 offline fallback;
- expose health/state for Home Assistant and monitoring;
- provide a stable policy boundary for future job generation/dispatch;
- preserve the GitHub/control-plane audit trail.

Privileged host changes remain the responsibility of the existing gated runner/root broker.

## Runtime configuration

Environment variables:

- `GOVERNOR_PORT` (default `8787`)
- `CLOUD_HEALTH_URL` optional HTTP endpoint used only as a cloud reachability signal
- `OLLAMA_BASE_URL` Z97 Ollama URL, e.g. `http://z97:11434`
- `OLLAMA_MODEL` default `qwen2.5-coder:7b-instruct`
- `PROVIDER_POLICY` must remain `cloud-primary-offline-fallback`

The service never logs secrets and does not require an OpenAI API key for the initial provider-selection/health layer.
