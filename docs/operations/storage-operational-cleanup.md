# Operational PA backup cleanup and consolidated retention

Owner policy: 24 November 2026. This supersedes disproportionate interpretation
of the earlier source-candidate gates, not the protected execution boundary.

## Immediate operation

scripts/lifeos_pa_backup_cleanup.py is a one-off operator procedure for only
pa_ha_dashboard_* and pa_escalation_v1_* under the owner-specified registered
automation/backups root. It is not another general retention framework and has
no service, timer, queue, remote command listener or installation action.

Use the immutable owner procedure in PR #2149. The approved cutoff remains
2026-10-24T00:00:00Z. It uses ext4 birth timestamps, unchanged inode ctimes and
the canonical producer's exact flat file layouts; legacy receipts are not
required and copied mtimes are never used as proof of creation.

The operation:
1. Checks current containers, AdGuard DNS over UDP/TCP, DNS-independent GitHub
   TLS, SSH recovery, memory and temperature. It changes no service.
2. Reads bounded current operational records, container configuration/mounts,
   kernel mount records, fstab and active process file/mapping references.
   It does not search historical archives or private document collections.
3. Preserves designated --protect generations and explicit references. It
   actually restores the newest two usable generations of each family into
   private isolated staging and verifies identical bytes, JSON, Python syntax
   and YAML using safe_load inside the existing HA Python environment.
   This is file-level recovery evidence, NOT a full HA disaster-recovery test.
4. Skips individual incomplete, changed, recent, symlink, hardlink, oversized,
   cross-device, active or otherwise uncertain generations. A family without
   two successful recovery copies is held independently of the other family.
5. Writes the exact private manifest before removal. Removes only listed flat
   regular files using directory FDs; no recursive rm, find-delete, prune or
   Docker storage-internal mutation. A durable intent precedes each generation.
6. Rechecks service identities, recovery copies and active references between
   batches; stops on availability/health or execution-permission failure.
   It stops at 30% available capacity, end of eligible scope, or 20 minutes.
7. Records every removal and real before/after available bytes, including a
   negative net delta if concurrent writes exceed recovery. Private details
   stay on the Pi. Retained copies are hash-checked after cleanup.

The operator needs existing owner-authorised privileged access to read current
process/transaction references and remove root-owned backup files. No passwordless
sudo grant, gateway install or runner privilege change is provided. Inaccessible
records with unknown scope are not silently declared clear: that execution-access
failure still stops the operation. Known candidate-specific uncertainty is a skip.

The audit directory must be NEW, canonical and outside the backup root. It needs
256 MiB free space on its filesystem; recovery staging is small and the private
manifest/journal persist there. Do not reuse an interrupted directory or blindly
replay its manifest. An interrupted, partially removed generation loses the known
complete shape and will be held on a subsequent fresh run; review its durable
journal rather than infer success.

No full service restore, production metadata writes, original documents, Restic
forget/prune or Paperless checkpoints are part of this operation. Existing broader
recovery points are outside the two exact family allowlists. If the owner has
additional designated points inside these two families, supply their exact
generation identifiers through repeated --protect arguments.

Based on the owner's live evidence, the two age-qualified families total
28,692,869,120 allocated file bytes. This is NOT a measured reclamation result.
At the last reported available capacity, roughly 31.40 GB is needed to reach
30% free, so these families alone cannot achieve that target. Directory overhead,
open/deferred blocks, protected copies and concurrent writes change the result.

## Governance consolidation

Keep: registered roots/artifacts, actual age/lifecycle evidence, no active writes,
retained recovery/rollback and designated holds, least privilege, resource limits,
bounded manifests/journals, measured capacity and protected-service checks.

Remove from routine expiry:
- Invented receipt formats as a prerequisite for legacy data when existing
  trustworthy timestamps and producer/file layouts suffice.
- A complete-disk or exhaustive historical-reference audit for every batch.
- Holding an individually cleared candidate solely because other inventory
  records are unknown. The existing assessor now evaluates each record's
  references and recovery proof independently; an incomplete index stays labelled.
- Requiring a full service boot/restore when verifying ordinary copied config
  recovery files. Match verification scope to backup scope; do not call syntax
  or byte checks proof of full service recoverability.
- Off-host proof as a blanket condition for every redundant local automation
  copy. Explicit required off-host coverage remains protected, and Restic is
  untouched.
- A new OWNER approval for each routine expiry after one narrow root-owned
  policy has been accepted. A machine-generated exact manifest remains an
  audit/precondition record, not another human approval gate.

Do not reinterpret bulk PA backups as privileged transaction/audit records just
because an engineering script produced them. Preserve actual control records
under docs/operations/records-retention.md: their 90-day/one-year minima and
incident holds are separate from the bulk payload policy.

## Single permanent-automation approval package (NOT enabled)

Reuse the existing daily exporter, Governor/Watchman maintenance authority,
root broker, Attention and metrics. No competing scheduler/database/gateway.

The owner approval covers one versioned policy, registered roots/families,
two verified retained generations where available, designated rollback points,
resource/batch limits, health guard and automatic expiry within that scope.
The existing root authority may generate exact per-batch manifest approvals
under that accepted policy; GitHub never supplies arbitrary shell commands.

Initially enable destructive expiry only for the two PA families accepted by
live cleanup. All other families remain assessment-only until their native
lifecycle evidence is adequate; unknown individuals are skipped.

Defaults: automation/database backups 30 days; closed repair snapshots 14 days;
successful payloads 7 days; failed payloads 30 days; closed logs 14 days with
bounded native rotation/compression; verified temporary restores 48 hours;
abandoned temporary artifacts 7 days after active-use/recovery checks. Retain
active images, designated rollback and two appropriate approved versions.
Prometheus 14 days is a proposal pending active configuration and monitoring
requirements. Preserve all existing Restic repositories pending separate review.

Before activation, one consolidated approval must cover the reviewed installation
of the narrow broker adapter, read-only exporter/monitoring wiring and policy
automation. This document does not install or activate PR #2148, grant runner
sudo, merge PRs, or enable unattended deletion. The immediate manual owner cleanup
already has the separate 30-day authorisation and does not wait for that package.

Operational acceptance still needs terminal Pi cleanup evidence, surviving file
recovery checks, protected-service health, and a bounded unattended rehearsal.
CI and this documentation are not production completion.
