# Mosquitto retained rotation safety groundwork

Programme: #2074. Retention authority: [records-retention.md](records-retention.md).

This change supplies tested primitives, not a deployed maintenance operation.
There is no CLI, scheduler, privileged gateway entry, or production execution
workflow. Synthetic tests use isolated temporary directories and fabricated
health results. They require no private production data.

The rotation primitive renames a single regular, singly linked log without
replacement, writes durable local journal records, and invokes trusted caller
adapters for writer identity, health, reopen and continuity verification. It
retains all historical bytes and reports zero reclaimed space. It never deletes,
truncates, compresses or copies logs. An interrupted reopen restores the original
name only when the original writer is still proven and the name remains absent.
When a new log exists, both files remain intact for investigation.

The health gate rejects absent, failed, stale or excessively slow evidence.
A failure stays latched for that maintenance session even if a later sample
passes. Probe implementations must bound their own I/O timeouts. The gate cannot
interrupt a blocking operation already in progress; production adapters must
use bounded operations and check health before and after every operation.

## Remaining production prerequisites

- A separately reviewed fixed adapter must verify the exact pinned broker,
  mount, process start identity, descriptor ownership, log directory ownership
  and new/retained descriptor invariants. No caller-controlled paths or commands.
- A protected exclusive maintenance lock and unresolved-journal check must
  prevent concurrent or repeated unverified rotation.
- Fresh local DNS UDP/TCP, direct-IP TLS, AdGuard health, GitHub, capacity,
  management-path and post-operation MQTT continuity checks are required.
- Local monitoring and recovery must work without internet. A successful LAN or
  console recovery login is not yet evidenced; a previous SSH attempt failed
  public-key authentication. GitHub access does not replace local recovery.
- Verify failure handling against the pinned disposable broker on ARM64 before
  any reviewed gateway installation or live rotation.
- Existing encrypted NAS archive readback succeeded in run 42907185330. This
  verifies historical recovery files, not a restored running AdGuard instance;
  routine latest-snapshot work-data coverage remains unresolved.

Owner approval covers retain-and-reopen rotation. It does not authorise deleting
the retained log or altering AdGuard/network configuration. The production adapter
must enforce all prerequisites rather than treating approval as runtime evidence.
