# LifeOS engineering interfaces

## Canonical state

OpenHands Agent Canvas now runs on the always-on Pi 5 control host (`Docker`, `192.168.0.203`). The accepted operator surface is `https://192.168.0.203:8443/canvas/`, using stock `ghcr.io/openhands/agent-canvas:1.23.0` with persistent state.

Engineer VM `192.168.0.204` is no longer an OpenHands host. Its OpenHands services and runtime containers were retired after the Pi 5 functional and persistence acceptance passed.

## Endpoints

- OpenHands Agent Canvas: `https://192.168.0.203:8443/canvas/`
- OpenHands execution/control host: Pi 5 `192.168.0.203`
- Tower local-AI host: `192.168.0.201`
- Engineer VM: `192.168.0.204` (retained for other engineering workloads; not OpenHands)

## Invariants

- Pi 5 hosts the OpenHands control plane but does not run private/local LLM inference.
- Private/local-only AI runs on Tower and must not silently fall back to cloud.
- OpenHands owns agent execution/planning/tool loops.
- Model routing and Tower lifecycle are separate deterministic controls and must remain enforceable during Governor retirement.
- OpenHands persisted state must survive service/container restart and deployment.
