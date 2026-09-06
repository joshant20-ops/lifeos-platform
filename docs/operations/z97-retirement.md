# Z97 retirement checklist

Z97 is migration-only. It may be retired only when every item below has an owner,
timestamp and immutable live-evidence reference. Any failed gate leaves Z97 in
place without granting it new authority.

- [ ] Inventory services, timers, containers, storage, scheduled jobs and inbound/outbound dependencies.
- [ ] Prove no canonical repository, unique secret, private source, backup key or only recovery copy exists solely on Z97.
- [ ] Migrate each live consumer to its named authoritative path and observe it through an agreed stability window.
- [ ] Prove restore and rollback from the replacement path without Z97 participating.
- [ ] Remove Z97 from DNS, monitoring, backup, orchestration and Home Assistant references, then rerun dependency discovery.
- [ ] Capture final clean dependency scan, affected capability regressions and owner approval.
- [ ] Power down for a reversible observation window before storage wipe or disposal.
- [ ] Record final retirement date and disposition; treat any destructive wipe as a separately approved operation.

Current status: **NOT READY FOR RETIREMENT** until the unchecked live gates above
are evidenced. This checklist resolves the roadmap policy gap without inventing
proof or prematurely deleting a recovery dependency.
