# Managed Home Assistant and Predbat updates

This is the first, shadow-mode implementation of issue #5. Pi5 remains the
controller, runtime executor, and canonical Git writer. Engineer may prepare a
sanitised review packet, but it has no deployment, SSH, Docker, HA API, battery
control, or publication authority.

The workflow is strictly `detect -> review -> test -> deploy one -> regress ->
accept/rollback -> evidence`. `engineer/managed_updates.json` is the explicit
allow-list. Only Predbat Core and Home Assistant Core are present. Stable
releases are deterministically coalesced to the greatest semantic version;
prereleases are ignored. Both managed Compose services explicitly opt out of
Watchtower.

Run the shadow planner with a sanitised observation:

```text
python3 engineer/managed_updates.py --observation observation.json --output packet.json
```

The observation must contain every named pre-update check. A regression result
must contain every contract check and use only PASS/WATCH/FAIL. Missing or
ambiguous evidence fails closed. Installed and candidate images must have valid
`sha256:` digests; a mutable tag alone is rejected. Risk terms, Home Assistant major changes,
WATCH, and unproven rollback all escalate. `automatic_deploy_allowed` and
`control_writes_permitted` remain false in every packet.

Rollback currently means a deterministic decision proven by tests, not live
rollback authority. Before enabling deployment, an accepted architecture
decision and independent review must define a Pi5-owned bounded transaction:
pinned before/after image digests, configuration/state backup, HA config check,
one-component restart, the complete regression contract, digest-pinned restore,
and a second regression proving the old baseline. Raw HA states, secrets, and
private telemetry must remain local; repository evidence contains only status,
versions, hashes, timestamps, and source URLs.

Rollback is to the recorded pre-update digest/config backup. If either is
missing or restoration cannot be proven, stop and escalate. No direct Pi
deployment is authorized by this shadow milestone.
