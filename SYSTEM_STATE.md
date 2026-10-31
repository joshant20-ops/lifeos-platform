# LifeOS System State

> Automatically generated from the live Pi 5.
> This file is the first reference for AI/human system context.
> Secrets, credentials, private addresses and runtime databases are intentionally omitted.

## Authority

- Primary host: Raspberry Pi 5 `Docker`
- Repository: `joshant20-ops/lifeos-platform`
- Branch: `main`
- Live source snapshot: `homelab/live/`
- Retired source: `homelab/retired/`
- Managed-file manifest: `homelab/.managed-files.txt`
- Snapshot policy: source/config only; runtime data and secrets excluded

## Host

- Hostname: `Docker`
- Architecture: `aarch64`
- Kernel: `6.18.39+rpt-rpi-2712`
- OS: `Debian GNU/Linux 13 (trixie)`

## Active Docker Services

- `adguardhome` — `aba9e3bf0613`
- `homeassistant` — `372d991e5888`
- `lifeos-agent-canvas` — `ghcr.io/openhands/agent-canvas:1.23.0`
- `lifeos-agent-canvas-tls` — `nginx:1.29-alpine`
- `lifeos-energy` — `d7933b4b7e5d`
- `matter-server` — `ghcr.io/home-assistant-libs/python-matter-server:stable`
- `mosquitto` — `6f8d8a947c50`
- `nginx-proxy-manager` — `52b2c59994f3`
- `paperless-db-1` — `postgres:15`
- `paperless-paperless-1` — `ghcr.io/paperless-ngx/paperless-ngx:latest`
- `paperless-redis-1` — `redis:7`
- `predbat` — `31413752bb3e`
- `uptime-kuma` — `3d632903e6af`
- `vaultwarden` — `efb3cde96201`
- `zwave-js-ui` — `86f418050ce6`

## Key Source Locations

- LifeOS Energy source: `/mnt/docker-data/automation/repos/LifeOS-Energy`
- LifeOS Energy forecast-learning: `/opt/stacks/lifeos-energy/forecast-learning`

## Source Stacks Present

- `adguard`
- `audiobookshelf`
- `homeassistant`
- `lifeos-energy`
- `lifeos-engineer-ui`
- `lifeos-semaphore-shadow`
- `mosquitto`
- `npm`
- `predbat`
- `qbittorrent`
- `qbittorrent_backup_2026-07-01_171445`
- `uptime-kuma`
- `vaultwarden`
- `zwave`
- `zwave-js-ui`

## GitHub Synchronisation

- Nightly schedule: approximately 02:30 Europe/London
- Hard timeout: 15 minutes
- Maximum managed file size: 25 MiB
- No-change runs are journalled without empty commits
- Removed managed source is retained under `homelab/retired/`

## Important Exclusions

- Credentials, secrets and private keys
- Home Assistant `.storage`, databases and generated `www/` output
- Application databases, logs and caches
- Z-Wave downloaded device database/state
- HACS/downloaded third-party integrations
- AdGuard, NPM and qBittorrent runtime state
- Personal Privacy Guardian profiles/data

## Snapshot Coverage
- Managed files: 267

