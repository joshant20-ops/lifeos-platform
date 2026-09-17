# Personal Information Processing — Paperless-first reset

Status: revised P0 discovery. Earlier P0–P2 evidence remains historically
useful but its acceptance is **superseded/incomplete** because native
Paperless-ngx capability was not proven first. Revised P1 and later gates remain
blocked until the governed native audit passes.

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
