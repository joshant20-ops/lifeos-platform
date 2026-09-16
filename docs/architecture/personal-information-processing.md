# Personal Information Processing

Status: gated implementation; **P0 discovery only**. P1 through P10 remain
blocked until their preceding acceptance gate has durable evidence.

## Authority and privacy

Gmail remains authoritative for email. Paperless remains authoritative for
documents and evidence. The selected Wave C accounting product remains
authoritative for accounting records; in short, the accounting product remains authoritative. LifeOS stores processing state, stable
source references, provenance, relationships and derived intelligence; it does
not create a second content archive or accounting ledger.

Real email and document content is `local-only`. Deterministic code processes
it first. Where semantics are genuinely required, Governor routes private work
to Tower Ollama and fails closed if that boundary is unavailable. Tower/local
AI is a bounded processor inside the permanent system: it does not design the architecture,
become a source of truth, or directly own policy or writes. It
may return a schema-constrained proposal; deterministic validation and policy
must authorize any future action. AI must not perform authoritative mutations.
Pi-local Ollama remains absent and private work has no cloud fallback.

Codex and GitHub may receive source code, schemas, synthetic fixtures and
sanitized aggregate evidence only. Titles, filenames, OCR, correspondents,
senders, addresses, account details and document identifiers are excluded from
cloud-visible evidence.

## P0 architecture discovery

The repository already contains capabilities that must be reused rather than
duplicated:

- Wave B's `lifeos_email_paperless_selective.py` is the accepted selective
  Gmail/IMAP → local triage → deterministic policy → Paperless API boundary.
  P6/P7 will extend that path, not create a second Gmail integration.
- `lifeos_paperless_local_ai.py` proves a read-only Paperless → governed local
  AI boundary, while `lifeos_paperless_junk_audit.py` is a historical bounded
  audit. Neither is yet the permanent P1–P10 processor contract.
- Paperless native mail workflows exist, alongside retirement evidence for
  duplicate legacy email importers. They must be reconciled with the accepted
  Wave B path before continuous P7 operation.
- Governor supplies privacy classification, Tower wake/readiness/lease/release,
  fail-closed local inference and durable job evidence. Those mechanisms are
  reused; the information processor does not create another orchestrator.
- Existing control-plane queues are engineering/control queues. P1 must define
  a versioned personal-information processing/checkpoint contract before
  production rollout; source payloads remain in Gmail/Paperless.
- The Wave B event/obligation/action/evidence contract and Wave C
  `finance-assets-read-model` provide downstream reference shapes. Extracted
  document facts are evidence candidates, never accounting truth.

## P0 live baseline contract

`scripts/lifeos-pip-p0-paperless-inventory.sh` queries the live Paperless
application read-only and emits aggregate counts only. It covers corpus size,
taxonomy assignment gaps, OCR coverage/size bands, year distribution, exact
checksum duplicate groups, probable same-title groups, likely
finance/property coverage, and native mail configuration counts. It never
prints a source ID, checksum, title, filename, OCR fragment, taxonomy label or
person/organisation name.

The audit compares a fingerprint of authoritative document IDs, metadata
references, checksums and modification values before and after collection. A
concurrent metadata change makes the run retry rather than accepting an
unstable baseline. The workflow also proves the canonical checkout stays
clean. This is evidence that the audit performed no production mutation; it is
not a lock over Paperless and it grants no later mutation authority.

## Gate state

P0 passes only after the governed live workflow reports `RESULT=PASS`, the
sanitized aggregate baseline is recorded, the repository architecture review
above is current, and production mutation remains `NONE`. P1 may then define
the versioned schema and taxonomy using synthetic fixtures. No P0 code permits
real Gmail processing or Paperless metadata writes.
