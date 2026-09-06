# Wave A household attention contract

## Purpose

Wave A connects existing household intelligence to one common attention surface without creating another event service, notification service, device controller, or energy controller.

## Authority boundaries

- **Home Assistant** remains authoritative for devices, home automation and household presentation.
- **LifeOS Energy / Octopus / Predbat / Enphase** retain their specialist energy roles.
- LifeOS Energy remains the authoritative negative-import opportunity model and stable identity/deduplication implementation.
- The **Personal Assistant attention surface** owns presentation of items that need household attention.
- MQTT remains transport where already appropriate; it is not made a second system of record by Wave A.

## Energy Opportunity -> attention projection

The existing LifeOS Energy process now detects and persists current `EnergyOpportunity` records using its supported Octopus client and persistent `/data` volume. It exposes the deterministic projection at `/api/energy/opportunities/current`. It remains free of notification and energy-control side effects.

The projection contract is:

- `state`: `attention` when one or more current negative-price windows exist, otherwise `clear`.
- `attention_id`: the first current opportunity's existing `opportunity_id`.
- `opportunity_ids`: stable de-duplicated list of all current opportunity IDs.
- `kind`: `energy_opportunity`.
- `count`, `severity`, `summary`, `start`, `end`, `minimum_price_p_per_kwh`, `source`: presentation/provenance fields.

No generated timestamp is included. Replaying the same input therefore produces byte-identical output and cannot invent a second attention identity.

## Home Assistant integration

Home Assistant preserves the stable `sensor.lifeos_energy_opportunity_attention` entity. Its small compatibility adapter reads the LifeOS Energy API directly; it no longer reads a generated JSON interchange file. The existing `LifeOS Attention Summary` consumes that sensor. There is no parallel notification framework.

LifeOS Energy refreshes opportunities inside its existing application scheduler every five minutes. The separate detector/projector systemd service and timer are retired.

## Household delivery

Wave A deliberately stops at the common PA/HA attention surface. WhatsApp and Alexa fan-out are downstream delivery adapters and remain subject to their explicit account/recipient authorization boundaries (#103 and #104). They must consume this common attention/event identity rather than create a second detector.

## Infrastructure coordination

Stage 8 is satisfied by retaining Home Assistant as the authoritative device/automation coordinator and the existing governed action path for privileged host operations. Wave A introduces no second infrastructure manager. Infrastructure defects and simplification work remain tracked independently (notably #122 and #123).

## Closure proof

The household Energy integration remains accepted only while live Pi5 evidence proves: specialist API health, deterministic replay/dedupe, HA entity registration, common attention integration, internal scheduler operation, retirement of the legacy JSON/timer bridge, Home Assistant/Mosquitto/Predbat/LifeOS Energy health, and a clean canonical repository.
