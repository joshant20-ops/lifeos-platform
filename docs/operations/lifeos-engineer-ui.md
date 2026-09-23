# LifeOS engineering interfaces

## Current state

The service at `http://192.168.0.203:8792/` is **Open WebUI**, not OpenHands. It is the legacy LifeOS Engineer chat surface backed by `governor/engineer_backend.py` on port 8793.

The canonical OpenHands engineering runtime executes headlessly on Engineer VM `192.168.0.204` through `governor/scripts/lifeos-openhands-sdk-runner.py`.

There is currently no native OpenHands web UI deployed on the LAN. Do not label Open WebUI as OpenHands and do not advertise `192.168.0.204:8792` as an OpenHands endpoint.

## Migration target

- OpenHands remains the canonical engineering plane.
- Governor remains the policy, privacy, hardware-lifecycle, publication and independent-verification control plane.
- A native OpenHands UI may be exposed on the LAN only when it is connected to the canonical engineering runtime/session contract rather than creating a second independent engineering authority.
- The legacy Open WebUI + `engineer_backend.py` pair may be retired only after its distinct operator functions have either moved to the OpenHands surface or been proven unnecessary.

## Existing endpoints

- Legacy Open WebUI: `http://192.168.0.203:8792/`
- Legacy compatibility backend: Pi 5 `:8793`
- Engineer/OpenHands execution VM: `192.168.0.204`
- Governor control/broker boundary: Pi 5 `:8790`
