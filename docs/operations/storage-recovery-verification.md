# Interrupted storage recovery verification

Selected 26 October 2026 after router recovery. Parent: #1760; priority follows the owner's explicit instruction, then configure existing Uptime Kuma monitoring. PR #1584 contains the proposed unified roadmap; it is not merged and has stale priorities.

## Preservation boundary

The fixed storage-preserve-sd-source operation runs only as root on Docker after exact root/SSD UUID, Docker-root and live-stack checks. It takes a lock and creates a private mount namespace. A nonrecursive bind of the root filesystem exposes the hidden SD source without unmounting the live SSD stack. Only that private bind is made read-only. The host mount namespace is never changed.

Mutation scope: a root-only recovery directory on the already-mounted SSD, an additive copy and private verification logs/marker; transient /run mountpoint. It never edits source, fstab, services, containers, live stack, keys or the boot configuration. Source filenames/content and rsync diagnostics remain local. Capacity must leave at least 5 GiB beyond the measured source size.

Two rsync checksum/metadata dry runs must return no differences before publication. ACLs, xattrs, hardlinks, numeric ownership and one-filesystem scope are preserved. Partial data is retained on failure; no automatic rollback deletes it. Namespace teardown removes only the temporary mount and empty mountpoint. Existing verified copies are rechecked rather than overwritten. Live mount and Docker root must remain unchanged.

This preserves the hidden source at observation time; it does not prove historical completeness or that old databases are application-consistent. It is not an off-device backup.

## Verification sequence

1. Preserve hidden source and verify it on the actual Pi.
2. Reconcile historical container IDs against retained Docker metadata and current compose services; never blindly start retired containers.
3. Verify HA, MQTT, AdGuard, LifeOS Energy, Paperless, Vaultwarden and prior active services through native APIs; bounded disposable write probes must map to SSD and be removed safely.
4. Verify fstab, mount guards, service dependencies, active writers and backup/restore evidence.
5. Only after these gates, perform a separately reviewed reboot validation with an accessible recovery route. No original activation/rollback/finalize/cleanup operation is selected.
6. Configure the installed Uptime Kuma instance, then prove monitor execution and recovery history.

Do not close #1760 merely because a copy, CI or deploy job passes.

## Verified checkpoint — 27 October 2026

Recovery #1760 is complete for the selected current service set. The original SD source and the on-device recovery copy are retained; no cleanup, repeat cutover, rollback or finalize operation was run.

| Evidence | Verified outcome |
| --- | --- |
| [Preservation40380647513](https://github.com/joshant20-ops/lifeos-platform/actions/runs/40380647513), job121775610869 | Read-only private source view; two checksum/metadata passes; live mount unchanged |
| [Runtime40385302166](https://github.com/joshant20-ops/lifeos-platform/actions/runs/40385302166), job121793456287 | Six SSD-backed container write/readback/cleanup probes and native application reads |
| [Matter40424075371](https://github.com/joshant20-ops/lifeos-platform/actions/runs/40424075371), job121925373963 | Private fabric backup/compare, original recorded container resumed, HA integration loaded |
| [Controlled reboot40425213177](https://github.com/joshant20-ops/lifeos-platform/actions/runs/40425213177) | One real new boot at 27 Oct 00:16:49 GMT |
| [Post-boot40425357225](https://github.com/joshant20-ops/lifeos-platform/actions/runs/40425357225), job121935674776, a50177e9 | SSD mounts and fresh native app/write checks; thirteen stable core IDs; Canvas native lifecycle/persistence; fifteen running services and seven legacy services still stopped |

Canvas is already supervised by enabled user systemd units installed by the canonical OpenHands Native UI workflow. Their ExecStartPre deliberately recreates the two containers, so their IDs are not durable identity. Verify the existing units, fixed images, network, exact persistent/read-only mounts, backend, HTTPS UI and checkout instead of adding a competing Docker restart owner.

The first cold HA startup needed longer than the initial gate allowed. It reached RUNNING, healthy HTTP200 and loaded Matter/Z-Wave/MQTT without restart or repair. The readiness gate now permits up to fifteen minutes. No second reboot was performed.

Eight historical pre-cutover IDs have no retained identity metadata. This remains a traceability limitation; no complete historical reconstruction is claimed. The optional service-set question was unanswered, so the recovery baseline preserved the working current services plus the demonstrated Matter dependency. Vikunja+DB, Radicale, Semaphore shadow+DB, old Engineer UI and qBittorrent remain stopped.

Docker/live stacks and the six selected write targets are SSD-backed. Canvas working data, Matter fabric and Paperless application/database data remain on their existing SD locations; Paperless media/intake/export remain on NAS. No silent expansion of migration scope occurred. The preservation copy is on-device and is not an independently verified off-device disaster-recovery backup.

## Existing monitoring configured

[Native Kuma acceptance40427278190](https://github.com/joshant20-ops/lifeos-platform/actions/runs/40427278190), job121940885075 on 5f52b416, passed eleven healthy monitors with at least two live UP samples each and persisted controlled DOWN-to-UP history. The temporary diagnostic was removed.

Coverage: router; WAN connectivity without DNS; public and local DNS through AdGuard; Home Assistant; AdGuard admin; MQTT and Matter listeners; Energy API; Paperless; Vaultwarden. Predbat's web UI is deliberately loopback-only and is excluded from Kuma coverage; its existing local health/HA assurance remains separate. No optimiser or listener exposure changed.

[Independent read-only audit40386695471](https://github.com/joshant20-ops/lifeos-platform/actions/runs/40386695471), job121941855688 at 00:51 GMT, confirms native metrics eleven UP/zero DOWN, HA RUNNING, loaded Matter/Z-Wave/MQTT and passing local/public DNS over loopback and LAN.

Kuma uses the existing port3002 dashboard. Admin username is joshan; its generated credential is stored only on Pi at /etc/lifeos/secrets/uptime-kuma/admin.json with root-only permissions. Retrieve locally through the owner's SSH/sudo access when needed; never publish that file or its contents in issue/workflow output. Notifications are not configured.

The remaining SMART daemon failure, two invalid OpenHands workflows and stale unmerged roadmap #1584 are separate outstanding work. This record does not mark those accepted.
