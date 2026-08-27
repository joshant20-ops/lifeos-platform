# Octopus Power Down OTS Migration

Date: 2026-08-27T12:17:03+01:00

## Decision

Custom `octopus-powerdown-watch.timer` retired.

Power Down session discovery is now owned by the installed
BottlecapDave Octopus Energy Home Assistant integration.

Native authoritative entities:

- event: discovered from Home Assistant Octopus Energy integration
- calendar: discovered from Home Assistant Octopus Energy integration

The legacy service and timer definitions remain on the host for rollback.

## Architecture

Octopus Energy API
→ Home Assistant Octopus Energy integration
→ native Power Down event/calendar
→ Home Assistant automations / LifeOS consumers as required

No duplicate custom polling service is required.
