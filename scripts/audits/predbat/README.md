# Bounded read-only Predbat recovery follow-up

This is the previously validated one-shot audit, parameterised for publication.
It reuses an existing private collector JSON; it does not repeat a full disk scan.
Run on the target through existing owner SSH. No Android Python, evidence download
or new gateway is required. No merge, deployment or production execution is
implied by this source change.

## Parameters

Set these privately on the target, never in this repository:

| Parameter | Meaning |
|---|---|
| `PREDBAT_STORAGE_ROOT` | Required absolute mount path for capacity/inode measurement |
| `PREDBAT_TRANSACTION_ROOT` | Required absolute transaction-record directory; it must also be inside the original report's reference roots to be read |
| `PREDBAT_AUDIT_INPUT` | Existing local collector JSON, or pass its path as the positional argument |
| `PREDBAT_EVIDENCE_ROOT` | Absolute output parent; defaults to `$HOME/predbat-audit-evidence` |
| `PREDBAT_FOCUS_IMAGE_ID` | Optional 12-character lowercase config-image prefix for focused reinspection |
| `PREDBAT_METADATA_DIRS` | Optional JSON list of up to eight absolute paths for directory metadata only |

The ordinary SSH target is configured by the caller (for example `PI_SSH_TARGET`);
the script contains no remote account, address, SCP command or interpolated remote
shell. Paths are data passed through quoted arguments or Python filesystem APIs.
No `eval`, shell subprocess execution, privilege escalation or credentials exist.

Image identities are read from the private report: four `KEEP` rows and twenty
`HOLD` rows are required, with unique validated config IDs. This is an audit input
shape, not deletion authority. Keep protected roles correct in the original local
report. Growth baselines come from its existing `growth` records, not hardcoded
measurements. Missing baselines remain unknown. Build dates do not prove pull
dates, and bounded Docker event history cannot prove historical absence.

## Execution

Inside the existing SSH session, configure the required paths privately and run:

```bash
bash scripts/audits/predbat/Predbat_Followup_ReadOnly_2026-11-23.sh --on-pi "$PREDBAT_AUDIT_INPUT"
```

The script can also be streamed from the repository's contents API at an exact
reviewed commit using an already authenticated `gh` on the Pi. Do not check out,
merge or overwrite the production checkout just to run this audit. The final PR
handoff supplies the pinned command. Do not disable TLS or expose SSH publicly.

The new evidence directory has a random job name and restrictive permissions.
Input is copied into that new directory only; private records, source and raw
results remain on the target. A detached job survives disconnects; inspect its
`summary.json` or `run.log` after reconnecting. Nothing publishes evidence to
GitHub or calls a model/external document-processing service. Treat even the
summary as private operational data; share only intentionally sanitised findings.
Never commit input JSON, generated evidence, environment files or SSH material.

## Safety and limits

Read-only means **production state is read-only**; new private evidence files are
created. Docker operations are inspect, list and bounded image events only. No
pulls, execs, restart/recreate, prune, removal, volume mutation or configuration
changes occur. Application databases, documents, backups and queues are never
modified. No permissions or protected storage reserve are changed.

The existing controls remain: 16 MiB input limit; 1 MiB text-file limit; 400-file,
24 MiB and 110-second targeted review budgets; at most eight archive attempts;
eight-second archive/du limits; low CPU and available idle I/O priority; 384 MiB
virtual-memory cap and 180-second outer timeout. No archive extraction to disk.
Symlinks/nonregular files are refused, and ambiguous or inaccessible evidence
remains unresolved. Backups/queues receive metadata inspection only. At most
three prior growth roots are remeasured; normal writes can affect net free space.

The original collector's substring matching, omitted file types, symlink-directory
coverage and shared time budget limit negative conclusions. This follow-up uses
whole config-ID tokens and version boundaries, rereads relevant records and
triages skipped files. Classifications such as deployment/recovery record are
review leads, not automatic proof of dependency. Opaque archives, unknown paths
and exhausted budgets are explicit gaps. The deletion allowlist is always empty
and the decision remains NO-GO pending recovery review. It never authorises
cleanup even if no references are found.

## Validation and provenance

`followup.py` is the testable copy of the embedded Python. A test requires exact
identity between these two copies. The implementation was adapted directly from
the existing session artifact, not reconstructed from a summary. Publication
changes remove remote-transfer orchestration and private literals, derive roles
and baselines from private evidence, and parameterise runtime paths. The original
22 tests retain their behaviours with synthetic identities and fixture counts;
12 added checks cover parameters, privacy, source identity and shell safety.

```bash
python3 -m unittest discover -s scripts/audits/predbat -p 'test_*.py' -v
bash -n scripts/audits/predbat/Predbat_Followup_ReadOnly_2026-11-23.sh
```

Tests use synthetic files, mock commands and temporary directories. They perform
no production execution and establish no deletion clearance. Independent review
is required before merge. This PR does not add a scheduler, service, privileged
gateway operation, infrastructure configuration or automatic deployment.
