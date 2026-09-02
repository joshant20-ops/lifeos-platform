# Rundeck Community shadow plane

This is the bounded M2 shadow deployment for issue #23. It is not authorised
to replace the production Watchman/backlog path. The image is explicitly pinned
to Rundeck Community `5.13.0`; changing that pin requires release-note review,
a backup, and the shadow acceptance suite.

## Boundary and secrets

Pi5 remains the runtime authority and canonical Git writer. Set
`LIFEOS_RUNDECK_BIND_IP` to a specific Pi5 LAN address; Compose deliberately
fails if it is absent and never publishes on `0.0.0.0`. The database is on an
internal Docker network and has no host port. No Docker socket, host root,
SSH key, transaction state, or root capability is mounted into Rundeck.

Create `/etc/lifeos/rundeck.env` from `runtime.env.example`, replace all sample
values, and make it root-owned mode `0600`. The populated file stays outside
Git. Start or inspect the shadow stack only through a reviewed Pi5/Watchman
runtime job, using:

```text
docker compose --env-file /etc/lifeos/rundeck.env \
  -f orchestration/rundeck/docker-compose.yml up -d
```

Rundeck initially has no privileged project or arbitrary-command job. A later
milestone may import only version-controlled, allow-listed job definitions that
invoke the LifeOS policy adapter. Rundeck itself must never receive unrestricted
sudo or arbitrary root shell access.

## Backup, restore, and rollback

Before an upgrade or configuration change, stop new submissions and wait for
shadow executions to finish. Through a bounded Watchman job, create a
root-readable PostgreSQL custom-format dump and archive the `rundeck-data`
volume into Pi5's approved local backup boundary. Do not put either artifact in
Git or job logs. Record image tags, archive checksums, and redacted success in
the local evidence store.

Restore into newly created empty volumes using the same pinned images: restore
the data-volume archive, start PostgreSQL, restore the database dump with
`pg_restore`, then start Rundeck. Verify the container health checks, login,
project/job inventory, and a read-only shadow run before allowing submissions.

Rollback is to stop the shadow stack and resume the unchanged compatibility
path at its recorded checkpoint. Never use a database from a newer Rundeck
release with an older image unless Rundeck's release documentation explicitly
supports it; restore the pre-upgrade pair instead. Named volumes are retained
by normal `docker compose down` and must not be deleted during rollback.

## Runtime acceptance (not performed by cloud builders)

The Pi5 verifier must confirm the resolved image digest, image architecture,
LAN-only listening socket, healthy containers after reboot, persistent job
history, successful backup/restore rehearsal, and absence of host/Docker/root
mounts. Until that evidence exists this deployment remains shadow-only.
