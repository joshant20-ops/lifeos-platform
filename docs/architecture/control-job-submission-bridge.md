# Control-job submission trust boundary

The Engineer remains unable to write `/home/joshan/lifeos-pi-control`. A local Unix socket exposes one operation, `submit-control-job`, accepting only manifest JSON and exact script bytes. The socket authenticates the kernel-supplied peer UID against a root-owned configuration value and rejects all other peers.

The bridge independently validates the publisher's schema and policy subset, rejects unknown fields, derives `<scope-root>/<job_id>.sh`, and never accepts a destination, command, arguments, Git input, service name, or mode/ownership input. Its fixed scope mapping is:

| Scope | Derived root |
|---|---|
| `diagnostic` | `jobs/scripts/` |
| `control-state` | `jobs/change-scripts/` |
| `root-broker` | `jobs/root-scripts/` |

An exclusive lock serializes submissions. Create-if-absent opens, symlink/root checks, conflict checks across staging/pending/archive/results, and a checksum of the final staged inode prevent overwrite, replay, and path escape. The script is created first and the manifest last, so a failure cannot publish a partial job. The publisher remains the only component that promotes staging to pending and performs Git operations; FIFO, runner, and root-broker authority are unchanged.

Acceptance and rejection records are emitted as structured journal events with job ID, target, type/scope, checksum, peer UID, `created_by`, timestamp, and reason. The service account has no login and systemd makes the host read-only except for the four exact create roots and its runtime lock directory. It cannot write pending, archive, results, binaries, secrets, or unrelated platform paths.

Activation is intentionally a human-controlled privilege change: create the dedicated service account and socket group, grant that account write/search access only to the four directories (prefer named ACLs), write the Engineer UID to `/etc/lifeos-control/control-job-submit.conf`, install the unit/helper, and enable the socket. The runtime launcher performs these bounded steps and verifies denial and acceptance behavior before continuing the previously approved job through the normal queue.
