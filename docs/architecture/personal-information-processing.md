# Personal Information Processing

Status: gated implementation; **P0 accepted**. P1 is the next gate; P2 through
P10 remain blocked until their preceding acceptance gate has durable evidence.

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

P0 passed in the governed workflow run
[`35141879710`](https://github.com/joshant20-ops/lifeos-platform/actions/runs/35141879710)
on canonical `d1f2fcee7e2c82f03209617277f63538dee02345`. The sanitized
baseline was:

- 942 documents; all 942 had OCR; OCR lengths were 1 short, 896 medium and 45
  long;
- zero correspondents defined, so 942 documents lacked a correspondent;
- five document types were defined and 922 documents lacked a document type;
- 13 tags were defined and 857 documents were untagged;
- zero exact-checksum duplicate groups and eight probable same-title groups;
- 219 documents matched the deliberately broad, deterministic
  finance/property candidate vocabulary;
- one native Paperless mail account and one native mail rule existed;
- document-year counts covered 2014–2026 and reconciled exactly to the 942
  document total.

The same run recorded `PAPERLESS_METADATA_STABLE=PASS`,
`PAPERLESS_MUTATION=NONE`, `PRIVATE_FIELDS_EMITTED=NONE`,
`PRIVACY_LOCAL_ONLY=PASS`, `CANONICAL_CLEAN=PASS` and `RESULT=PASS`. No Gmail
messages were read or processed. These figures are discovery candidates, not
document classifications or permission to mutate metadata.

P1 may now define the versioned schema and taxonomy using synthetic fixtures.
No P0 code permits real Gmail processing or Paperless metadata writes.

## P1 processing contract

P1 defines schema version 1 in
`governor/contracts/personal-information-processing.schema.json` and taxonomy
`pip-taxonomy-v1`. This gate uses synthetic fixtures only and permits no production Paperless or Gmail mutation.

The deliberately small domains are Finance, Property, Employment, Vehicles,
Household, Personal Administration and Unknown. Information types describe
durable functional kinds rather than provider-specific tags. Existing
user-created Paperless correspondents, document types and tags are preserved;
the contract explicitly forbids automatic replacement of that organisation.

Processing records retain stable authoritative references, never source
content. They carry an explicit processing state, method, confidence band and
score, controlled reason codes, dates/periods, entity and source-object
relationships, processor/rule versions, provenance, an exception state and a
fail-closed mutation control. `unknown` and `review` are valid outcomes;
coverage is never improved by inventing a classification.

Confidence policy is versioned with the taxonomy. High begins at 0.90 and may
only become eligible for a later deterministic P4 action policy; it is not
mutation permission. Medium begins at 0.65 and requires review or independent
corroboration. Low and unknown remain unresolved/review. Local AI is encoded
only as `local-ai-proposal`; deterministic validation and later gate policy
remain authoritative.
