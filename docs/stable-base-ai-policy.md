# Stable-base AI policy

During the stable-base phase LifeOS deliberately enables only two AI inference paths.

- Personal/private (`local-only`) work: Tower Ollama only. It fails closed and must never fall through to Codex or another cloud provider.
- Normal/sanitized/non-personal engineering: Codex. The Tower Ollama provider is marked `private_only` and is not eligible for normal routing.

Deterministic tooling remains available and is not an AI provider. Gemini, Groq, OpenRouter and Cloudflare remain disabled for this phase. The provider-router architecture is retained so additional providers can be re-enabled later by an explicit policy change and regression tests.
