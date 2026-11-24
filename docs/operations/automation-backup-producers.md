# Automation backup producer integration

Status: source candidate in PR #2149; no live deployment, inventory, deletion or
reclaimed capacity. Scope is the existing retention implementation, not another
backup service, scheduler or remote-command interface.

## Repository-confirmed producers

| Canonical script | Generation family | Payload and recovery dependency |
| --- | --- | --- |
| `lifeos-sync-pinned-compose.sh` | `pinned-compose-*` | Per-project live Compose `.before` files, container/digest audit; multi-service rollback dependency |
| `lifeos-ha-dashboard-audit-simplify.sh` | `ha-dashboard-simplify-*` | Home Assistant dashboard `.before` files; dashboard rollback |
| `lifeos-adapt-ha-lifeos-dashboard.sh` | `ha-lifeos-dashboard-*` | Dashboard `.before` and `.absent` markers; restoration and absence semantics |
| `lifeos-adapt-ha-tower-control.sh` | `ha-tower-control-*` | Existing control dashboard `.before`; dashboard rollback |
| `lifeos-deploy-ha-control-bridge-impl.sh` | `ha-control-bridge-*` | Bridge, controller, unit/config and prior-active markers; also calls dashboard producers |

These are source discoveries, **not proof these are the current installed
producers or dominant historical cohorts**. Other prefixes in the profiling
script are hints only; their original producer must be recovered from installed
scripts, job records or archived canonical revisions. Flat reconciler backups
under a different configured root are not automatically in scope.

## Why previous accounting cannot authorise deletion

The old scripts name directories with local `date`, copy rollback material and
print `PASS`/`BACKUP` strings. They do not persist a timezone-aware generation
completion receipt, active lease, restore result, retained recovery relationship
or closure of dependent transactions. `PASS` means the engineering script
succeeded; it does not establish restore verification. The historical aggregate
file counts and logical sizes cannot supply those missing facts.

The user-approved cutoff is **2026-10-24T00:00:00Z**, strictly earlier than it.
Neither a directory name nor its modification date may establish that boundary.
An exact generation reference in an authoritative producer/job record with
verified timezone-aware start/completion evidence can establish age. A timestamp
interval is usable only if its latest possible completion precedes the cutoff.
Any additional control-record retention minimum or recovery hold still applies.

## Narrow integration

Each of the five existing scripts calls `backup_producer_metadata.py begin` after
creating its backup directory, then an EXIT hook records completion/failure after
the existing ERR rollback handler. The native producer actions are unchanged.
Metadata failure warns and leaves a retention hold; it must not itself trigger
service rollback. SIGKILL/power loss leaves an active or incomplete receipt.
Exclusive receipt creation preserves collision evidence. Do not overwrite old
receipts to retry a generation; use a new generation identifier.

Receipts are private mode 0600 and contain UTC timestamps, source hash, exact
generation identity, service and unresolved recovery dependency. Completion is
not recovery acceptance. `retention_generation()` translates receipt/file stats
to the **existing** PR #2149 inventory fields. Unattested timestamps, references,
off-host coverage and recovery quality remain false/unknown; no receipt can
promote its own verification flags. Rollback bundles conservatively retain the
privileged-transaction class until their actual records/payload split is verified.

`discover` never invokes `begin`, `finish`, Docker, subprocesses or service APIs.
It reads names, bounded receipts and file stats; emits only aggregate counters
to stdout. Optional private report preserves exact generation names and measured
file sizes plus held normalized receipt records, locally. It does not read
document or backup payload contents, derive dates, approve manifests or delete.
It refuses symlink/mount traversal and holds hardlinks, special files, permission
failures and oversized trees. Bounds: 100,000 root entries, 2,048 descendants per
generation, 10,000 normalized receipt generations. Reaching bounds is incomplete
coverage, never deletion clearance. Allocated file bytes exclude directory
overhead and are not guaranteed filesystem recovery.

## Live evidence boundary and next step

The previously verified self-hosted runner does not by itself authorise arbitrary
audit scripts or new privileged operations. No verified existing operation reads
this producer evidence. PR #2148 is uninstalled and must not be activated here.
Do not modify the gateway or dispatch a generic shell job to bypass that boundary.

The owner may run the pinned `discover` command supplied in the PR conversation
on the Pi using existing local access. It downloads only this public committed
module into a private temporary directory, runs at low CPU/I/O priority with a
five-minute timeout, and writes the optional private result outside the backup
root. No Android processing or software installation is needed. Existing tools
required: `gh`, Python 3, `timeout`, `nice`, `ionice`; read permission for backups.
Do not grant the runner sudo or change permissions if collection is refused.
Private report paths and contents must not be uploaded. Only stdout is sanitised.

Then correlate private generation IDs with installed producer source hashes,
terminal job/transaction records, live leases and verified retained/off-host
recovery points. Register that reviewed witness adapter in existing Governor
controls, not a JSON command executor. Only then can `storage_retention.assess`
produce a deletion-ready bounded manifest. Existing owner age approval remains
valid; it cannot substitute for missing lifecycle evidence or widen execution
authority. No verified live eligible count or protected count is currently known.

Rollback before deployment is a revert of this source commit. These hooks have
not been installed or executed against production. Source tests cover receipts,
failure/ERR/EXIT interactions, bounds, privacy and conservative decisions; they
are not runtime or recovery acceptance.
