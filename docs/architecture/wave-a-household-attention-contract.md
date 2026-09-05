# Wave A household attention contract

## Purpose

Wave A connects existing household intelligence to one common attention surface without creating another event service, notification service, device controller, or energy controller.

## Authority boundaries

- **Home Assistant** remains authoritative for devices, home automation and household presentation.
- **LifeOS Energy / Octopus / Predbat / Enphase** retain their specialist energy roles.
- `energy/app/opportunities.py` remains the authoritative LifeOS negative-import opportunity model and stable identity/deduplication implementation.
- The **Personal Assistant attention surface** owns presentation of items that need household attention.
- MQTT remains transport where already appropriate; it is not made a second system of record by Wave A.

## Energy Opportunity -> attention projection

`run-energy-opportunity-detection.py` continues to detect and persist current `EnergyOpportunity` records. It remains free of notification and energy-control side effects.

`project-energy-opportunities-to-ha.py` is deliberately thin presentation glue. It converts the current records into one deterministic JSON projection consumed by Home Assistant. It does not detect prices, send messages, or control hardware.

The projection contract is:

- `state`: `attention` when one or more current negative-price windows exist, otherwise `clear`.
- `attention_id`: the first current opportunity's existing `opportunity_id`.
- `opportunity_ids`: stable de-duplicated list of all current opportunity IDs.
- `kind`: `energy_opportunity`.
- `count`, `severity`, `summary`, `start`, `end`, `minimum_price_p_per_kwh`, `source`: presentation/provenance fields.

No generated timestamp is included. Replaying the same input therefore produces byte-identical output and cannot invent a second attention identity.

## Home Assistant integration

Home Assistant reads the local projection through `lifeos_energy_attention_sensor.py` and exposes `LifeOS Energy Opportunity Attention`. The existing `LifeOS Attention Summary` consumes that sensor. There is no parallel notification framework.

The local refresh timer runs the existing detector and the projector as the unprivileged `joshan` account every five minutes. Root is needed only to install/manage the native systemd unit and HA configuration through the governed deployment gateway; the recurring workload itself is not privileged.

## Household delivery

Wave A deliberately stops at the common PA/HA attention surface. WhatsApp and Alexa fan-out are downstream delivery adapters and remain subject to their explicit account/recipient authorization boundaries (#103 and #104). They must consume this common attention/event identity rather than create a second detector.

## Infrastructure coordination

Stage 8 is satisfied by retaining Home Assistant as the authoritative device/automation coordinator and the existing governed action path for privileged host operations. Wave A introduces no second infrastructure manager. Infrastructure defects and simplification work remain tracked independently (notably #122 and #123).

## Closure proof

Wave A closes only after live Pi5 evidence proves: detector health, deterministic replay/dedupe, HA entity registration, common attention integration, enabled local scheduler, Home Assistant/Mosquitto/Predbat/LifeOS Energy health, and a clean canonical repository.
