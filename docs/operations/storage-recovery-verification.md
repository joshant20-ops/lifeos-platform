# Interrupted storage recovery verification

Selected 26 October 2026 after router recovery. Parent: #1760; priority follows the owner's explicit instruction, then configure existing Uptime Kuma monitoring. PR #1584 contains the proposed unified roadmap; it is not merged and has stale priorities.

## Preservation boundary

The fixed storage-preserve-sd-source operation runs only as root on Docker after exact root/SSD UUID, Docker-root and live-stack checks. It takes a lock and creates a private mount namespace. A nonrecursive bind of the root filesystem exposes the hidden SD source without unmounting the live SSD stack. Only that private bind is made read-only. The host mount namespace is never changed.

Mutation scope: a root-only recovery directory on the already-mounted SSD, an additive copy and private verification logs/marker; transient /run mountpoint. It never edits source, fstab, services, containers, live stack, keys or the boot configuration. Source filenames/content and rsync diagnostics remain local. Capacity must leave at least 5 GiB beyond the measured source size.

Two rsync checksum/metadata dry runs must return no differences before publication. ACLs, xattrs, hardlinks, numeric ownership and one-filesystem scope are preserved. Partial data is retained on failure; no automatic rollback deletes it. Namespace teardown removes only the temporary mount and empty mountpoint. Existing verified copies are rechecked rather than overwritten. Live mount and Docker root must remain unchanged.

This preserves the hidden source at observation time; it does not prove historical completeness or that old databases are application-consistent. It is not an off-device backup.

## Remaining gates

1. Preserve hidden source and verify it on the actual Pi.
2. Reconcile historical container IDs against retained Docker metadata and current compose services; never blindly start retired containers.
3. Verify HA, MQTT, AdGuard, LifeOS Energy, Paperless, Vaultwarden and prior active services through native APIs; bounded disposable write probes must map to SSD and be removed safely.
4. Verify fstab, mount guards, service dependencies, active writers and backup/restore evidence.
5. Only after these gates, perform a separately reviewed reboot validation with an accessible recovery route. No original activation/rollback/finalize/cleanup operation is selected.
6. Configure the installed Uptime Kuma instance, then prove monitor execution and recovery history.

Do not close #1760 merely because a copy, CI or deploy job passes.
