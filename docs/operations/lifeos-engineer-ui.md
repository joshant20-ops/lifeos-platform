# LifeOS Engineer UI

The canonical LAN-facing Engineer UI is the existing Open WebUI service on the Pi 5 control host:

- URL: `http://192.168.0.203:8792/`
- Container: `lifeos-engineer-ui`
- Desired state: `ansible/desired/compose/lifeos-engineer-ui/docker-compose.yml`
- Health: `http://192.168.0.203:8792/health`

The Engineer VM at `192.168.0.204` is an execution host. Port 8792 is not assigned to it. Do not publish a second Engineer UI there.

## Ownership

Open WebUI is the single operator-facing LAN UI. The canonical engineering plane is OpenHands. Governor remains the policy, capability, hardware-lifecycle, publication and independent-verification boundary.

The UI must not become a second engineering implementation. Observability should expose OpenHands task/session state through a bounded adapter/API while execution continues through the canonical OpenHands path.

## Network contract

- UI: Pi 5 `:8792`, LAN only.
- Engineer backend compatibility API: Pi 5 `:8793`.
- Governor/OpenHands broker: governed endpoint; credentials remain outside the browser.
- Engineer VM: execution target, not an alternate public UI.
- Tower Ollama: private inference backend; never exposed directly to the UI.

## Operator check

Open `http://192.168.0.203:8792/` from a LAN client. A refusal on `192.168.0.204:8792` is expected because that is not the UI endpoint.

Future OpenHands observability work must reuse this surface rather than install another dashboard.
