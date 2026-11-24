# LifeOS storage retention — source candidate

No production installation, schedule activation, deletion or merge is authorised
by this document. This is a reviewable policy/core implementation, not a claim
that legacy producers already supply the necessary lifecycle evidence. PR #2148
remains separate and must not be installed or activated as a side effect.

## Policy

`governor/storage-retention-policy.json` contains defaults and per-service/category
overrides. Runtime inventories, roots, approvals and service-specific settings
remain private local configuration, not GitHub data.

| Category | Default | Mandatory hold/acceptance condition |
|---|---|---|
| Automation backup | 30 days after verified completion | Retained verified recovery and independently operating off-host coverage |
| Database backup | 30 operational days | Same recovery rules; live databases and volumes excluded |
| Repair snapshot | 14 days after verified incident closure | Explicit closure evidence, no dependencies and retained recovery |
| Successful job payload | 7 days after verified completion | Terminal, unreferenced and not authoritative control/audit evidence |
| Failed job/diagnostic payload | 30 days after verified terminal completion | Incident and rollback holds cleared; artifact integrity distinct from job success |
| Closed cron log | 14 days | Registered writer, no open handles, verified lifecycle |
| Predbat image | No age rule | Preserve production, rollback and two distinct explicitly approved additional images; all-container and recovery references checked |
| Paperless rehearsal | Only verified temporary artifacts | Existing native rehearsal cleanup adapter; original checkpoint and live data never generic file targets |
| Prometheus | Propose 14 days | Verify actual active flags/data mount first; choose a size cap from measured ingestion, WAL/head overhead and protected reserve |

The defaults do not replace Restic's separate daily/weekly/monthly disaster
recovery tier. A different share on the same appliance is not an independent
failure domain. Off-host point availability and restore verification must be
attested by the existing backup owner; local cleanup cannot silently reduce it.
At least one protected verified recovery point survives every service's cleanup,
even where an override attempts to disable that prerequisite.
Verification alone is not a permanent hold on every historical backup. The native
backup owner maintains a small explicit protected set (current verified baseline,
required rollback and off-host checkpoints). It protects a verified successor
before releasing a predecessor's protection, and clears no incident dependency
implicitly. Other verified expired generations can be eligible.

Existing control records retain their longer minima: ordinary job payload is
distinct from control records (90 days), privileged transaction/root-broker audit
and production acceptance evidence (conservatively one year). Legal, incident,
rollback and sole-evidence holds always win. These records must not be relabelled
as ordinary completed payload to obtain the shorter window.

Backup freshness defaults to a configurable 48-hour alert threshold, separate
from retention duration. Producer admission defaults to a five-minute cooldown
and at most 24 generations per service/day; a measured service-specific daily
byte limit can also be set. Required pre-change backup refusal must stop the
proposed change, not permit changing production without a recovery point.

## Existing mechanisms and gaps

Assessment is against source at `10e8ca441561df9cddf62d256b887402c4bea42a`.
Runtime configurations/schedules have not been read back in this task.

| Existing mechanism | Finding | Proposed handling |
|---|---|---|
| `scripts/lifeos_storage_retention_inventory.py` / backup profile | Bounded cached TSV analysis; dates are modification dates; eligibility explicitly zero | Keep for accounting; do not promote dates to verified completion |
| `governor/backup_duplicate_audit.py` | Bounded hash comparison and private evidence; dependencies remain unverified | Keep dedup evidence separate from deletion authority |
| `lifeos-restic-backup` | Native backup plus 7 daily/4 weekly/6 monthly forget policy; no prune in that script | Preserve independent DR lifecycle and existing credentials; review overlap before changing retention |
| `pi_sd_image_backup.sh` | NAS full-SD stream; count-based newest-four removal using mtime ordering | Legacy safety gap. Do not disable a working recovery producer or change NAS retention here; replacement requires separate review/restore proof |
| Daily observed-state exporter | Existing daily service/timer and snapshot history | Reuse for optional daily read-only assessment and rolling weekly summaries; no new timer/database |
| Governor/Watchman / root broker | Existing execution authority | Supply installed producer locks, health, roots and lifecycle guard adapters; no generic GitHub commands |
| PR #2147 | Unmerged bounded private Predbat investigation | Keep its reference/recovery evidence and exact image identities local |
| PR #2148 | Uninstalled, disabled read-only request route | Independent approval; its counters do not authorise deletion |
| Prometheus | Only retired Compose configuration was found in this inspection; no explicit retention flags there | Active runtime flags, volume ownership, actual growth and alert routing remain unverified; do not modify retired Compose as if it were live |

No backup producer is declared obsolete solely from repeated names, age, duplicate
bytes or an unreferenced Docker volume. No evidence proves that every generation
is needed either. The missing information is authoritative lifecycle/hold proof,
not an assumption that all stored bytes must be retained forever.

## Inventory and producer integration

`governor/contracts/storage-retention-inventory.schema.json` defines the private
normalised input. Each generation records service, stable generation ID, root ID,
category, producer evidence ID, verified creation/completion times, state, sizes,
verification, active/open references, dependencies, holds, recovery requirements
and an exact file/identity list or full Docker config image ID. Repair closure is
independently attested. Registry data includes protected recovery points, off-host
failure separation and protected full image IDs, never inferred from filenames.

Registered adapters must derive these fields from existing native producer/job
records. Do not manufacture `timestamp_verified`, `references_verified`, `complete`
or closure proof for the old TSV. Legacy unverified data remains HOLD. The
observed timestamp covers fresh active-job/reference checks, not a rewritten file
mtime. Unknown, incomplete, stale, inaccessible and future-dated records fail
closed. At most 10,000 records/16 MiB are accepted per bounded assessment; use
existing Governor checkpoints for complete per-service cohorts rather than a
second queue, giant temporary inventory or repeated full-disk scan. Recovery
registry/reference coverage must remain complete for each assessed cohort.

Existing backup creators call `producer_admission()` before writing, under their
existing producer lock, and monitor actual allocation against the admitted upper
bound. The hook is not yet inserted into unknown/legacy producers. A required
backup that exceeds its bound must stop nonessential upstream changes. Retry
reuse requires the same job and unchanged source epoch, with a completed verified
generation; active/unknown attempts block a new overlapping generation. No new
backup application, scheduler, task database or automatic deletion is introduced.

## Daily assessment, weekly summaries and monitoring

The existing observed-state exporter now has an optional `daily()` hook. It is
NOT_CONFIGURED without private `LIFEOS_RETENTION_CONFIG`. Enabling this read-only
hook requires owner-approved deployment/configuration; no timer is added.

Private configuration contains `assessment_enabled`, `inventory`, `policy`,
`storage_root` and optional `history_root` pointing at existing daily snapshot
history. The assessment returns counters, fixed categories/hold codes and no
generation IDs/paths. The rolling seven-day view reads at most seven previous
snapshot files, capped at 4,000 directory entries; it reports growth, expired
generations and potential allocated capacity. No weekly task is scheduled.

The `metrics()` projection supplies fixed numeric textfile counters to the existing
metrics publisher, including backup failure/freshness, retention backlog, reserve
and real assessment timestamp. `monitoring/retention-alerts.yml` contains proposed
rules for the existing Prometheus/Alertmanager/Attention route; loading the rules,
textfile wiring and notification acceptance require separate approval. No live
alert receiver or rule group was changed. Stable Attention identities deduplicate
unchanged conditions; no new messaging service or notifications are sent here.

## Manifests and disabled executor

The read-only CLI is:

```text
python3 -m governor.storage_retention PRIVATE_INVENTORY --policy PRIVATE_POLICY --manifest NEW_PRIVATE_MANIFEST
```

It never executes cleanup. A manifest is a new mode-0600 file and contains exact
generation/file identities, policy/inventory SHA256 and a short expiry window.
Existing files are not overwritten. The planner defaults to at most five
generations/one GiB per manifest; a service may require a smaller reviewed batch.
Each manifest has one registered root and at most 256 individual operations.
Larger individual generations require review, not automatic splitting by age.
Batch limits are atomic-operation limits, not a five-generation daily cleanup
quota. Any future approved maintenance coordinator must resnapshot and generate
fresh approved batches under its existing resource/time budget; this PR does not
mint automatic approvals or add a cleanup scheduling loop.
Potential allocated bytes are not guaranteed physical recovery; filesystem free
space remains authoritative, especially for hardlinks, shared layers and ongoing
writers. No synthetic test result is reported as Pi space recovery.

`execute()` is an internal installed-Governor adapter API with no deletion CLI or
new gateway endpoint. It is disabled in shipped policy and requires root, a
root-owned private approval naming the exact canonical manifest hash, unexpired
approval/manifest, unchanged policy and inventory, and the approved root map.
Approval of the previous one-off cutoff does not enable scheduled deletion or
broader categories. No commands, executables or callbacks are read from GitHub or
manifest data. Guards are installed reviewed code, not user-supplied Python.

The required guard contract is deliberately not replaced by permissive stubs:

- `exclusive()` holds the existing global/producer maintenance leases for the
  entire operation, including compression. All other mutations must respect them.
- `approved_roots()` supplies the root-owned registry of narrowly managed backup,
  payload and closed-log roots. Never register live data, database volumes,
  application configuration, off-host repositories or broad filesystem roots.
  Reject nested mounts, including same-device bind mounts, and uncoordinated
  writable roots; a matching filesystem device alone does not prove isolation.
- `inventory()` reattests producer terminal state, closure, open issue/rollback
  dependencies, image holds, all running/stopped container references, recovery
  and off-host availability. Missing permission/coverage is failure, not absence.
- `health()` and `revalidate()` enforce current Tier 0 UDP/TCP DNS, direct internet,
  protected services, storage/inode reserves, resource limits and retained recovery
  coverage before and between actions; missing checks refuse execution.
- `file_idle()` proves no open file descriptors or writer references under the
  held lease. `capacity()` reads actual available bytes on the target filesystem.
- The rotation adapter additionally supplies registered writer/reopen proof,
  closed current/archive handles, compression upper bound and the protected reserve.

These root-owned adapters and their live acceptance are **remaining integration
gates**, not claims implemented by a mocked unit test. Existing Tier 0 helpers
and producer/controller records should implement them during separately approved
deployment; an arbitrary diagnostic script is not a substitute.

File deletion is limited to exact regular files, same device, no symlinks or
hardlinks, matching device/inode/size/mtime/ctime/allocation, below the approved
generation and registered root. There is no recursive removal, glob, find-delete
or deletion of unknown files/empty-directory sweep. Per-file intents are fsynced
before removal, results afterwards. A completed manifest is idempotent; an
interrupted intent requires explicit reconciliation and never blindly replays.
The exact approved manifest is fsynced and retained beside the private journal
under the existing storage audit state area. Journals are bounded per manifest,
not one indefinitely appended global file. These mutation records inherit the
longer control-record minimum. Directory-descriptor traversal prevents symlink
escapes; the final stat/unlink pair additionally depends on the full producer
lease excluding every writer/administrator. There is no atomic conditional-unlink
promise against a writer that ignores that lease; such roots remain HOLD.
The existing coordinator must consume completion evidence to reconcile its own
authoritative producer record to purged; it must not regenerate candidates from
an unchanged old registry. Interrupted intents are not completed purge evidence.

The native Docker adapter pins the local Unix socket, accepts only fixed inspect,
all-container list/reference, exact-ID remove and verification operations. It
rechecks all four retained IDs and all container states. No force, prune, remote
Docker context or internal storage manipulation is used. Docker rejects conflicts;
failure stops and preserves the audit. Paperless remains HOLD until its existing
verified native rehearsal cleanup adapter is selected; generic file deletion is
intentionally refused for that category.

## Native log rotation

`rotate_log()` uses native logrotate under the existing coordinated Governor task,
not a second schedule. It remains separately disabled. Generated configuration
is stored only in the private audit state, **not** `/etc/logrotate.d`, so a global
logrotate timer cannot run it outside the producer lease. Rotation is daily,
compression uses delaycompress/gzip, no copytruncate, force or service restart.
Native state makes repeat daily calls safe. Open or unregistered writers defer.
Compression input is bounded to 64 MiB/run and must leave twice its upper bound
above the protected reserve; no large temporary copies are created by this code.
Oversized historical logs require a separately reviewed bounded approach.

Native logrotate uses `rotate -1` without maxage: it never expires archives behind
the manifest executor. The 14-day policy removes only explicitly inventoried,
closed, approved archives. This separates rotation/compression from deletion.
The local logrotate installation/version, writer reopen behaviour and permissions
must be verified before enabling this adapter. Native rotation was mocked in
tests; no production or real native logrotate run is claimed.

## Recovery, risks and owner approvals

Code/policy rollback is a reviewed revert before deployment. Deleted local bytes
cannot be undeleted by this tool; rollback is possible only through preserved
verified recovery points and the existing restore procedure. There is no automatic
production restore/restart. Journals, incident evidence and interrupted-generation
state must remain for reconciliation. Deleting files does not prove block release.

Approval gates, in order:

1. Independent review of this source/policy and service-specific exceptions.
2. Register/verify producer metadata, root/lease/health/recovery adapters; reconcile
   old data without using mtime or filenames as completion proof.
3. Approve deployment of the **read-only** daily hook and existing metrics/Attention
   wiring. PR #2148 needs its own separate approval if used as a transport.
4. Verify active Prometheus flags/mounts and resource use, then approve its time
   and measured size cap. Do not edit retired Compose or prune volumes.
5. Approve native rotation/compression only after closed-writer and reserve proof.
6. Approve enabling the restricted executor separately, then approve each exact
   current manifest (or a separately reviewed narrow automatic-approval policy).
   No implicit permission for blanket cleanup, off-host forgetting or other roots.
7. Observe a small live batch and verify actual free bytes, inode reserve, retained
   recovery, unchanged protected services and DNS before broader unattended use.

Remaining blockers are explicit: live metadata/access, installed guard adapters,
native-tool acceptance and owner deployment/destructive-automation approvals.
Until those pass, this is a tested source candidate, not an operational retention
system. Nothing in this PR installs/activates PR #2148 or removes production data.
