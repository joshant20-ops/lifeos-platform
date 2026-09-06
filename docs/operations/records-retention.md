# Control-plane records and retention

All durable control records carry `schema_version`, a stable record identifier,
UTC `created_at`, producer, immutable canonical revision where applicable, state,
and a redacted evidence/result object. Producers reject unknown major schema
versions. Optional additive fields are permitted; required fields are not silently
reinterpreted.

| Record | Canonical shape | Minimum retention | Disposal rule |
|---|---|---:|---|
| Engineering proposal/job | `governor/contracts/engineering-work.schema.json` plus immutable source revision | 90 days after terminal state | Retain longer while referenced by an open issue or rollback artifact |
| Privileged transaction | root-owned manifest, backup, verification and rollback result under `/var/lib/lifeos-transactions/<id>` | 90 days after commit; 1 year after rollback/failure | Never purge an active/non-terminal transaction; preserve any record referenced by incident evidence |
| Root-broker audit | create-only request/result record with operation, revision, outcome and redacted diagnostics | 1 year | No secret values; failed and denied requests have the same retention as successful requests |
| Assistant/action queue | versioned item ID, provenance, privacy class, state and disposition | 90 days after terminal state | Personal source payloads remain in their approved source system; queue records retain references and redacted summaries only |
| CI/deployment evidence | GitHub run or durable local proof tied to revision | 1 year for production mutation; 30 days for discovery-only artifacts | Issue/decision closure must retain a stable evidence reference |

Retention is a minimum, not an instruction to delete. A governed maintenance job
must first prove the record is terminal, outside every legal/incident/rollback
hold and not the only surviving acceptance evidence. Deletion itself is audited.
Secrets, credentials and raw private documents are never control-record fields.
