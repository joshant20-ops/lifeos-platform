# LifeOS engineering interfaces

## Canonical state

OpenHands is the engineering plane. Governor is the thin control plane for policy, privacy, hardware lifecycle, bounded publication and independent deterministic verification. LifeOS must not duplicate OpenHands planning, tool loops or completion semantics.

The native OpenHands UI is exposed on the Engineer VM at `http://192.168.0.204:3000/`. It is the operator surface for OpenHands itself; it must use the same governed model boundary as headless engineering rather than direct browser credentials or a second model authority.

Headless governed jobs execute on Engineer VM `192.168.0.204` through `governor/scripts/lifeos-openhands-sdk-runner.py`, using OpenHands' native CLI agent preset and native conversation completion.

## Legacy retirement boundary

The service at `http://192.168.0.203:8792/` is Open WebUI, not OpenHands. Its `governor/engineer_backend.py` compatibility API on Pi 5 `:8793` is legacy and must not be treated as an engineering implementation or canonical UI. Retire that pair once its remaining operator-only status/history functions are either available through the native OpenHands/Governor surfaces or proven unnecessary. Do not route new engineering work through it.

## Endpoints

- Native OpenHands UI: `http://192.168.0.204:3000/`
- Engineer/OpenHands execution VM: `192.168.0.204`
- Governor control/broker boundary: Pi 5 `:8790`
- Legacy Open WebUI: `http://192.168.0.203:8792/`
- Legacy compatibility backend: Pi 5 `:8793`

## Invariants

- Private/local-only engineering remains on Tower Ollama through the Governor broker; no cloud fallback.
- OpenHands owns engineering planning, repository inspection, edits, tests, repair and completion.
- Governor never manufactures pseudo-turns or interprets OpenHands internal action counts as completion.
- Governor independently verifies the resulting canonical state before PASS/publication.
- The browser UI must not require users to paste model credentials that bypass Governor.
