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
- Kernel: `6.18.29+rpt-rpi-2712`
- OS: `Debian GNU/Linux 13 (trixie)`

## Active Docker Services

- `adguardhome` — `adguard/adguardhome:latest`
- `autoheal` — `1c00ddf72362`
- `cadvisor` — `gcr.io/cadvisor/cadvisor:latest`
- `grafana` — `grafana/grafana:latest`
- `homeassistant` — `ghcr.io/home-assistant/home-assistant:stable`
- `lifeos-energy` — `lifeos-energy:0.1.0-dev`
- `lifeos-engineer-ui` — `ghcr.io/open-webui/open-webui:v0.11.1`
- `matter-server` — `ghcr.io/home-assistant-libs/python-matter-server:stable`
- `mosquitto` — `eclipse-mosquitto:latest`
- `nginx-proxy-manager` — `jc21/nginx-proxy-manager:latest`
- `node-exporter` — `quay.io/prometheus/node-exporter:latest`
- `paperless-db-1` — `postgres:15`
- `paperless-paperless-1` — `49eba766581b`
- `paperless-redis-1` — `redis:7`
- `portainer` — `portainer/portainer-ce:latest`
- `predbat` — `nipar44/predbat_addon:latest`
- `privacy-guardian` — `privacy-guardian-privacy-guardian`
- `prometheus` — `prom/prometheus:latest`
- `qbittorrent` — `lscr.io/linuxserver/qbittorrent:latest`
- `uptime-kuma` — `louislam/uptime-kuma:latest`
- `vaultwarden` — `vaultwarden/server:latest`
- `watchtower` — `containrrr/watchtower:latest`
- `zwave-js-ui` — `zwavejs/zwave-js-ui:latest`

## Key Source Locations

- LifeOS Energy source: `/mnt/docker-data/automation/repos/LifeOS-Energy`
- LifeOS Energy forecast-learning: `/opt/stacks/lifeos-energy/forecast-learning`

## Source Stacks Present

- `adguard`
- `autoheal`
- `grafana`
- `homeassistant`
- `lifeos-energy`
- `mosquitto`
- `npm`
- `portainer`
- `predbat`
- `privacy-guardian`
- `prometheus`
- `qbittorrent`
- `qbittorrent_backup_2026-07-01_171445`
- `uptime-kuma`
- `vaultwarden`
- `watchtower`
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
- Managed files: 271

