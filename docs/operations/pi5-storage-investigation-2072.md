# Pi5 storage investigation — execution gate (#2072)

Status: **PROPOSED / NOT DEPLOYED**. This is not a permission to execute arbitrary shell commands.

## Evidence already established (10 November 2026 GMT)

- HDD ext4 /dev/sda1, approximately 116 GB used and 23 GB available.
- /mnt/docker-data/opt-stacks/mosquitto is approximately 10 GB.
- Canonical Mosquitto configuration includes `log_dest file /mosquitto/log/mosquitto.log` and `persistence_location /mosquitto/data/`.
- /mnt/docker-data/opt-stacks/lifeos-energy 2.1 GB; homeassistant 1.7 GB; adguard 713 MB.
- /mnt/docker-data/automation timed out during size scan.
- /mnt/docker-data/recovery is ~4 GB and contains preservation evidence and an AdGuard backup.
- ext4 reserved blocks are ~7.45 GiB; this is not unexplained file usage.

## Validation before runtime

1. Independently review `governor/read_only_storage_diagnostic.py` and `tests/test_read_only_storage_diagnostic.py`.
2. Run Python unittest in a trusted non-privileged environment. Do not infer a pass from the existence of tests.
3. Confirm `lifeos-pi5` runner status and current Watchman policy, including the specific allowed read-only diagnostic job class.
4. Do not add a generic `sudo`, arbitrary path/command gateway, Docker socket access, or a new privileged entry point.
5. If the existing execution policy does not allow this specific diagnostic, stop at `BLOCKED_USER_ACTION_REQUIRED` or propose a separately reviewed narrow allow-list change; never bypass it.
6. Verify that only sanitized size buckets/statuses can be exported to `lifeos-snapshots`. Raw output and sensitive paths remain local.

## Runtime acceptance (only after gate approval)

- Execute the immutable canonical commit and verify its script SHA-256 via the existing approved Pi control boundary.
- Capture the sanitized report and independently check the actual MQTT log/data sizes locally; report whether the 10 GB comes from log files, persistence, or other files.
- Confirm AdGuard healthy and DNS working before and after. If either check fails, stop and report; **do not restart or repair automatically**.
- Confirm that no files, service state, Docker configuration, firewall, DNS or network settings changed.
- Reconcile filesystem use without double-counting bind mounts, aliases or Docker accounting.
- Do not delete, truncate, rotate or prune any file in this task.

## Known limitations

- The current diagnostic's per-directory `du` calls time out after 12 seconds; `timeout` is a legitimate result, not a zero-byte directory.
- Directory stat may fail when the unprivileged runner cannot access a root-owned bind mount; this must not trigger privilege escalation.
- Immediate MQTT file metadata is not a complete recursive inventory.
- GitHub does not directly access the Pi's live filesystem. A reviewed local execution path is required.

## Gateway finding (10 November 2026 GMT)

The fixed OPS map in `homelab/live/usr/local/sbin/lifeos-deploy-gateway` has no storage-footprint diagnostic. Existing storage migration or verification operations must not be repurposed. A separately reviewed, named, no-argument, read-only operation and authorised update to the installed root-owned gateway are required before Pi execution. Do not introduce arbitrary sudo, command execution, or generic runner privilege. Current state: runtime not verified; no Pi diagnostic execution.
