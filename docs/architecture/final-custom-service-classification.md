# Final Custom Service Classification

Updated: 2026-08-28T01:16:09+01:00

## lifeos-predbat-sanity

**KEEP / SIMPLIFY**

Independent read-only validation remains useful.

It checks Predbat/HA entity availability, tariff API health,
live tariff publication horizon, forecast state, and anomalous
planned imports beyond the known tariff horizon.

Architecture:

Predbat + HA recorder + tariff API
→ Predbat Sanity
→ durable JSON
→ retained MQTT `lifeos/energy/predbat_sanity/state`
→ compact Home Assistant MQTT status entity

The complete diagnostic snapshot is deliberately NOT copied into
Home Assistant state attributes because it exceeds HA recorder's
attribute-size boundary.

No Predbat, battery, planner, or Home Assistant control is performed.

## lifeos-ask-process

**KEEP**

Ask is an on-demand workflow, not a periodic scheduler.

The active submit path explicitly starts
`lifeos-ask-process.service`, and the host worker references the
canonical `lifeos_ask_processor.py`.

The lack of periodic systemd starts therefore does not demonstrate
that the workflow is obsolete.

Any future simplification should preserve its semantic/Paperless
query capability while reducing transport/orchestration glue.
