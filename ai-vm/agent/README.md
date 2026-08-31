# LifeOS AI VM Autonomous Agent

Purpose: provide a persistent local AI worker that can be given a goal once and continue until it reaches a verified completion state or a real authority/safety boundary.

## Runtime loop

1. Accept a goal from a local/GitHub-backed goal inbox.
2. Ask the local Ollama model for a structured plan.
3. Execute only policy-allowed local actions.
4. Verify observable results.
5. Feed evidence back into the model and refine/retry as needed.
6. Checkpoint after every iteration.
7. Resume unfinished goals after restart.
8. Mark complete only when verification passes.

This is intentionally different from the diagnostic GitHub runner. The runner transports bounded jobs; the agent owns longer-running goal completion.

## Provider policy

- Private/offline tasks: local Ollama on the AI VM.
- Normal cloud engineering can still be routed by the Pi5 Governor to Codex/cloud AI when available.
- The local agent does not send private source material to cloud providers by default.

## Authority

The agent runs as the unprivileged `joshan` user. Root/system mutation requires a separately approved broker operation. Paperless writeback remains disabled until a dedicated test and policy gate are added.

## Completion semantics

A goal is not complete because the model says it is complete. The agent must collect local verification evidence and persist it with the goal state.
