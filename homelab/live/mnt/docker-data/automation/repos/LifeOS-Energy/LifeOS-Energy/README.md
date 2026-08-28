# LifeOS Energy

LifeOS Energy is a self-hosted energy monitoring and intelligence service for the LifeOS platform.

It reads live telemetry from a local Enphase Gateway, stores historical readings in SQLite, and provides a browser dashboard and REST API.

## Current capabilities

- Local Enphase Gateway integration using `pyenphase`
- Live solar production telemetry
- Live household consumption telemetry
- Grid import and export telemetry
- Battery state-of-charge and power telemetry
- Persistent SQLite history
- Historical telemetry API
- Responsive browser dashboard
- Docker deployment on the LifeOS Pi5 host
- Health endpoint and container health checks

## Current endpoints

| Endpoint | Purpose |
|---|---|
| `/health` | Application health |
| `/energy` | Energy dashboard |
| `/api/energy/current` | Current Enphase telemetry |
| `/api/energy/history?hours=24` | Historical telemetry |

Default local dashboard:

```text
http://192.168.0.203:8110/energy
