# Personal Information Processing — Paperless-first reset

Status: revised Paperless-first **P0 and P1 accepted**. Earlier custom-first P0–P2
implementation evidence remains historically useful but its gate acceptance is
**superseded/incomplete**. Revised P2 is next; later gates remain blocked.

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

Revised P2 must now evaluate native Paperless rules against a representative real corpus sample in shadow/read-only mode and propose the smallest durable native taxonomy/matcher/workflow configuration. Any future LifeOS component must cite a measured native capability gap after this evaluation. Duplicate policy remains a Paperless configuration decision; LifeOS must not implement parallel deduplication.
