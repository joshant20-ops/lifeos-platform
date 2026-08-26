# LifeOS OTS Migration

## lifeos-system-health

Status: SHADOW RETIRED

Replacement:
- node-exporter — host metrics
- cAdvisor — container metrics
- Prometheus — metric collection/query
- Grafana — visualisation
- Uptime Kuma — availability monitoring

Validation:
- custom timer disabled
- Docker healthy
- Home Assistant healthy
- Prometheus healthy
- no failed systemd units observed during retirement gate

The custom implementation and service definition remain preserved for rollback.

Decision:
Do not restore the custom collector unless an identified LifeOS-specific
capability is demonstrated to require it.
