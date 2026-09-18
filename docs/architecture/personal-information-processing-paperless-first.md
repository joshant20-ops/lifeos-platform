# Personal Information Processing — Paperless-first reset

Status: revised Paperless-first **P0, P1 and P2 accepted**. Earlier custom-first P0–P2
implementation evidence remains historically useful but its gate acceptance is
**superseded/incomplete**. Revised P3 is next; later gates remain blocked.

## Paperless-first invariant

Paperless remains the document authority and normal document-management
system. Do not rebuild its ingestion, original/archive storage, OCR, metadata,
correspondents, document types, tags, storage paths, custom fields, matching,
duplicate review, workflows, full-text search, permissions, bulk editing,
history or normal UI/API management in LifeOS.

Tower Ollama is exception-only. Native Paperless matching and deterministic
rules run first. Local AI may later propose resolution only for a demonstrated
unresolved semantic gap; it cannot replace Paperless classifiers, become an
authority, or mutate metadata directly.

## Native capability established from current documentation

| Need | Native capability | LifeOS decision |
|---|---|---|
| Ingestion and OCR | Consume directory, mail rules and REST upload; OCR and PDF/A/archive generation | Do not rebuild |
| Organisation | Correspondents, types, nested tags, storage paths and custom fields; UI/API/bulk editing | Do not rebuild |
| Classification | Exact/any/all/regex/fuzzy/auto matching over OCR and metadata | Configure and measure before any semantic extension |
| Duplicate handling | Native same-content warnings, duplicate view and optional reject-on-consume | Do not build deletion/deduplication authority |
| Automation | Added/updated/consumption/scheduled workflow triggers and assignment/removal actions | Prefer native workflows |
| Retrieval | Tantivy-backed full-text/API search across OCR and metadata, plus advanced queries | Do not build another document search index |
| Email attachments | Native mail accounts/rules plus accepted Wave B selective disposition | Reconcile; do not add a third importer |

Current upstream references: [basic usage](https://docs.paperless-ngx.com/usage/),
[advanced matching](https://docs.paperless-ngx.com/advanced_usage/),
[REST API](https://docs.paperless-ngx.com/api/) and
[configuration](https://docs.paperless-ngx.com/configuration/).

## Demonstrated gap boundary

No custom classifier is justified merely because current metadata coverage is
low. First configure and evaluate native Paperless matchers/workflows against
synthetic canaries and then production aggregates. The current audit can
demonstrate configuration and outcome gaps but Paperless does not expose
reliable historical assignment provenance for existing metadata; that specific
assignment provenance gap must remain explicit rather than inferred.

Potential LifeOS work is limited to proven cross-system gaps: Gmail disposition
and orchestration, unresolved semantic exceptions after native matching,
cross-domain relationships, Wave C authoritative-ledger-to-Paperless evidence
reconciliation, grouped review exceptions and higher-level intelligence.
Source content stays in Paperless/Gmail; LifeOS retains stable references and
provenance only.

## Revised P0 acceptance

The governed read-only audit must record the running Paperless version/image,
non-secret OCR/consumer configuration, ingestion boundaries, corpus OCR/file
outcomes, metadata/custom-field coverage, matcher/auto configuration, native
mail and workflow configuration, duplicate aggregates and API search route.
It must expose no labels, filenames, OCR, names, IDs or secrets and perform no
production mutation. Only after that evidence passes may revised P1 decide
which native Paperless configuration should be tested before any LifeOS gap
component.

## Revised P0 live evidence and gaps

The governed [native audit run `35183312070`](https://github.com/joshant20-ops/lifeos-platform/actions/runs/35183312070) passed on canonical `95f92bc699b6e2edb58feddc64567c1e9f412aab`. Runtime identity was Paperless-ngx 3.1.2, configured from the mutable `latest` image reference but resolved to immutable image ID `sha256:5ab4f4f9bb099a36bec3e092906ea3e611323c5f18dc5cc38c76a1d540bdca9c`.

The production corpus contained 942 documents: OCR text existed for all 942, originals for all 942 and archive versions for 66. Native metadata currently comprised zero correspondents, five document types, 13 tags, zero storage paths, zero custom fields and zero saved views. Assignment coverage was 0 documents with correspondents, 20 with a type and 85 with tags. All five types and all 13 tags had native matchers configured; 11 tag matchers used Auto. No correspondent or storage-path matchers existed.

Paperless already had six workflows, six triggers and six actions, one mail account and one mail rule. Processed-mail history was zero. The consume mount was present, filesystem polling was 10 seconds, the full-text document API route resolved, and no exact-checksum duplicate group existed. Other audited OCR/consumer settings used current defaults. Paperless cannot reliably expose historical assignment provenance for these existing objects; the audit records that as unavailable rather than inferring it.

This proves the immediate gap is configuration and measured use of native Paperless—not absence of document-processing machinery. Revised P1 must use synthetic canaries to evaluate native matching, workflows, search, mail/API ingestion, duplicate behaviour, rollback and assignment observability before authorising any LifeOS classifier. The mutable `latest` deployment reference is a separate operational reproducibility concern; the audit's immutable image ID preserves current evidence, but changing/pinning deployment is outside read-only P0.

The audit emitted no private fields, configuration secrets, taxonomy labels, filenames, OCR, names or source IDs; it performed no Paperless/Gmail mutation and left canonical clean.

## Revised P1 live acceptance

The governed [native canary run `35185765793`](https://github.com/joshant20-ops/lifeos-platform/actions/runs/35185765793) passed against Paperless-ngx 3.1.2. A unique disposable PDF entered through the authenticated REST ingestion boundary and proved native OCR, correspondent matching, document-type matching, tag matching, workflow-driven custom-field assignment and full-text API search. The canary then submitted the exact file again and measured the configured native duplicate policy as `ALLOW`, which is Paperless's current default rather than a missing LifeOS capability.

The canary used a unique namespace and `try/finally` cleanup. It removed both synthetic documents, both task rows and all temporary taxonomy/workflow objects; the marker search returned to zero and the canonical checkout remained clean. It emitted no private fields or source content, mutated no production document and used neither Tower AI nor a LifeOS classifier.

## Revised P2 — native production shadow

Revised P2 evaluates native Paperless rules against a stable, metadata-stratified
representative real corpus sample. The evaluator invokes Paperless's own matcher
and, where available, its native classifier. It does not copy or reimplement
matching, OCR, classification, duplicate handling, search or workflow logic.

Only sanitised aggregates may leave the local runtime: coverage, unmatched,
ambiguity, conflict, broad-overlap risk, zero-hit rules and candidate counts for
preserving or reviewing the existing correspondent/type/tag/storage-path
configuration. Names, matcher expressions, source IDs, filenames, OCR and all
other private values remain inside Paperless. Existing user-created organisation
is preserved. Real reads are allowed; production metadata writes are prohibited.
The same shadow evaluation must produce an identical logical result when rerun.
For existing taxonomy objects without an effective matcher, P2 may construct an
unsaved case-insensitive literal candidate from the object's existing private
name and evaluate it through Paperless's native matcher. Only candidate counts
and outcome aggregates leave the runtime; no new taxonomy is invented and no
candidate is persisted.

Tower AI is prohibited in P2. A later custom LifeOS component is justified only
when it cites a demonstrated native capability gap from durable P2 evidence.
Low native coverage by itself first calls for bounded Paperless configuration,
not a parallel LifeOS classifier. Exact-duplicate policy remains entirely owned
by Paperless.

### Revised P2 live acceptance

The governed [native production shadow run `35186840593`, attempt 2](https://github.com/joshant20-ops/lifeos-platform/actions/runs/35186840593) passed after an incidental DNS failure on attempt 1. It evaluated 116 stable metadata-stratified documents from the 942-document corpus through Paperless's own matching and classifier logic, without changing documents, metadata or configuration. The identical rerun proof passed.

Current native classification covered 66 sample documents and left 50 unmatched. Unsaved native-rule candidates increased coverage by one document to 67 and left 49 unmatched. Two existing document-type rules and two tag rules were safe enable candidates; three document-type and two tag rules require review. Candidate tag rules overlapped on 53 sample documents, so bulk enabling them without refinement is unsafe. No correspondent or storage-path candidates were justified, all six existing workflows should be preserved, and there were no exact duplicate groups in the current corpus.

No taxonomy labels, filenames, OCR, names, source IDs or other private fields were emitted. Tower AI was not used, proposed production mutations remained none, and the canonical checkout remained clean. Revised P3 may configure only the proven safe native candidates through a reversible canary and limited rollout, and must remeasure overlap before production-wide activation. LifeOS semantic processing remains blocked until a residual native Paperless gap is demonstrated after that configuration work.


## Revised P3 — reversible native configuration canary

Revised P3 remains Paperless-first. It may exercise only the existing native matcher candidates proven safe by P2, must remeasure native coverage and overlap on the same representative sample, and must restore the exact matcher configuration before exit. It must not mutate document metadata, create taxonomy, touch review candidates, or invoke Tower/cloud AI. Production-wide activation requires evidence that a candidate adds useful native coverage without unacceptable ambiguity or overlap.

### Revised P3 live acceptance

The governed native Paperless canary run `35309290110` passed on the self-hosted Pi runner. All 11 focused P2/P3 contract tests passed, the canonical checkout reconciled cleanly, and the canary rediscovered exactly the P2-proven two document-type and two tag candidates against the same 116-document sample.

Native coverage moved from 66 to 67 documents. Document-type overlap remained zero. Tag overlap moved from 52 to 53, confirming the P2 warning that the candidate tag configuration is not suitable for production-wide activation without refinement. The canary restored the exact matcher configuration successfully. It performed no document metadata mutation, created no taxonomy, mutated no review candidates, emitted no private fields and used no Tower AI. The canonical checkout remained clean.

P3 is accepted as a bounded configuration/measurement gate, not as approval to bulk-enable all four candidates. Its evidence demonstrates a substantial residual native Paperless gap: 49 of the 116 representative documents remain outside the native/candidate coverage measured by P2/P3, while the tag candidates introduce additional overlap. P4 may therefore investigate an exception-only semantic layer for the unresolved tail, while continuing to prefer native Paperless for documents it can classify safely. Any production matcher activation must be independently justified by non-regressing overlap evidence.


## Revised P4 — exception-only governed local semantics

P4 adds no replacement document classifier. Paperless remains the first-line authority and the accepted P2 evaluator is reused to identify only the residual native exception set. Real document title/OCR stays local. Semantic interpretation is routed through Governor with `privacy="local-only"` and `force_provider="ollama"`; the bridge independently requires the returned provider to be Ollama. Invalid JSON, missing/unknown schema keys, invalid field types or confidence outside 0..1 fail closed. P4 performs no Paperless writeback.

### Revised P4 live acceptance

The corrected governed native-exception shadow reproduced the accepted P2 baseline on the same representative sample: 116 documents, 66 resolved by native Paperless behavior and 50 selected as unresolved exceptions. It emitted no private content, performed no document mutation and left the canonical checkout clean.

The bounded real semantic canary run `35324638387` then selected three documents only from that native-unresolved set and processed all three successfully through the governed local-only Tower Ollama route. All three returned the strict seven-field structured schema. Sanitised evidence reported `P4_AI_CANARY_SELECTED=3`, `P4_AI_VALID_STRUCTURED=3`, `P4_AI_PRIVACY=LOCAL_ONLY`, `P4_AI_PAPERLESS_WRITEBACK=NONE`, `P4_AI_PRIVATE_CONTENT_EMITTED=NONE`, `RESULT=PASS` and `CANONICAL_CLEAN=PASS`. Paperless Local AI deployment, stable broker contract, contract audit and repository CI also passed for the same revision.

An earlier strict-schema run accepted two of three outputs and rejected one; that failure was retained as evidence that malformed semantic output fails closed. The producer prompt was tightened rather than weakening validation, after which the bounded canary passed three of three. P4 is accepted. P5 may now build a progressive, resumable backlog state machine around Paperless-first native resolution and this exception-only local semantic path; it must not turn Tower Ollama into a default full-corpus processor and must not auto-delete documents.
