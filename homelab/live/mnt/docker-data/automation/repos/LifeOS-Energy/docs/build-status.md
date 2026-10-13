# LifeOS Energy Build Status

## Branches

- `main`: stable foundation
- `develop`: active validated development

## Completed milestones

- Commit 01: FastAPI foundation
- Commit 02: configuration and persistent logging
- Commit 03: structured live dashboard
- Commit 04: deterministic energy simulation
- Commit 05: fixed tariff and daily cost engine

## Current APIs

- `/health`
- `/api/status`
- `/api/simulation`
- `/api/cost`

## Current pricing model

The application currently uses a configurable fixed tariff with:

- Import unit rate in pence per kWh
- Export unit rate in pence per kWh
- Standing charge in pence per day

## Next milestone

Commit 06 will introduce battery strategy comparison and optimisation.


## Commit 06 — Enphase live telemetry

Status: implemented

Features:

- Local IQ Gateway read-only connector
- Bearer-token authentication
- Protected token mounted outside Git
- Live solar-production telemetry
- Live household-consumption telemetry
- Grid import and export telemetry
- Battery telemetry extraction
- `/api/enphase/status`
- `/api/enphase/live`
- `LIVE`, `STALE`, `AUTH_ERROR`, and `OFFLINE` states
- No Enphase control or configuration operations

Gateway:

- Address: `192.168.0.18`
- Transport: local HTTPS
- Polling: request-driven with a short in-process cache
- Local self-signed certificate verification disabled

Security:

- Token is not stored in Git
- Host token permissions are `600`
- Container token mount is read-only
- API output does not expose credentials


## Commit 06.5 — pyenphase provider migration

Status: implemented

Changes:

- Replaced the custom Gateway HTTP implementation with `pyenphase`
- Preserved `/api/enphase/status`
- Preserved `/api/enphase/live`
- Preserved the existing LifeOS telemetry contract
- Added typed extraction from `EnvoyData`
- Added Encharge aggregate state-of-charge extraction
- Added Encharge battery power aggregation
- Retained short-lived in-process caching
- Retained external read-only token storage
- Removed the temporary compatibility probe

Provider responsibilities:

- `pyenphase` handles Gateway communication, authentication and firmware-specific datasets
- LifeOS handles API contracts, state reporting, caching, tariffs, history and optimisation

Safety:

- Only `setup`, `authenticate`, `update` and `close` are used
- No storage-mode, reserve, grid, relay or battery-control method is called
- Enphase credentials remain outside the repository

## Commit 07 — Live dashboard and telemetry history

Status: implemented

Features:

- Live dashboard at `/energy`
- Five-second browser telemetry refresh
- One-minute server-side history collection
- SQLite telemetry persistence
- Twenty-four-hour history API
- Solar, household, grid and battery visualisation
- Source and freshness indicators
- Read-only Enphase operation
- Open-source dependency governance ADR

Runtime data:

- Database: `/data/lifeos-energy-history.sqlite3`
- Runtime database is excluded from Git
- Enphase tokens remain outside the repository

API:

- `GET /api/energy/current`
- `GET /api/energy/history?hours=24`
- `GET /energy`


## House Status DEV historical energy

The development dashboard reads its historical electricity source from the
LifeOS Energy API. Enphase Envoy telemetry is collected locally and compacted
in the existing SQLite cache: recent raw readings remain available for the
existing 35-day interval-report contract, and older readings are retained as
half-hour kWh rollups. The compact rollups are the minimum data needed to
recalculate time-of-use costs; Home Assistant Recorder is not used as a second
long-term energy database.

Octopus supplies tariff-native half-hour import prices. LifeOS joins those
prices to Enphase energy at read time and calculates domestic import cost from
grid import excluding battery charging. API timestamps include UTC and
Europe/London local boundaries so repeated/missing DST hours remain distinct.

API:

- \`GET /api/energy/rollups?start=<epoch>&end=<epoch>&granularity=30m\`
- Response includes Enphase kWh, Octopus p/kWh, domestic import cost, UTC/local
  slot boundaries, source coverage, and missing-price indicators.
- Missing telemetry or Octopus prices remain explicit; unavailable prices are
  not treated as zero cost.

House Status DEV aggregates half-hour data by selected period: Day retains
intraday slots, Week groups by local day, Month by Monday-starting week, and
Year by calendar month. Period summaries use the selected dates and sum cost.
Only the DEV asset bundle is deployed by its dashboard workflow; production
House Status remains behind its separate manual release workflow.

Acceptance status: pending live DEV deployment and Enphase/Octopus comparison.
