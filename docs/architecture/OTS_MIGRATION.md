# LifeOS OTS Migration

## Engineer control plane

Status: DESIGN DECIDED; COMPATIBILITY SAFETY WORK IN PROGRESS

Target: Ansible Semaphore and version-controlled Ansible automation, with the LifeOS policy/client and existing submission bridge/root broker retained as the privileged boundary.

The ownership model, component disposition, shadow gates, and rollback plan are defined in [ots-engineer-orchestration.md](ots-engineer-orchestration.md). No destructive cutover is authorised until shadow equivalence passes. Git-owned runtime queue directories remain temporary compatibility state, not the target design.

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
