# Workflow archive audit — 2026-09-19

This file records one-off GitHub Actions entry points removed from the active workflow surface after their migration/diagnostic/retirement acceptance purpose was superseded by the current canonical architecture. Git history remains the archive and preserves the exact workflow implementation and run references.

Removed active entry points:
- `lifeos-email-duplicate-retire.yml`
- `lifeos-email-legacy-retire.yml`
- `lifeos-pi5-ai-broker-migrate.yml`
- `lifeos-pi5-cloud-provider-diagnostic.yml`
- `lifeos-pi5-provider-targeted-probe.yml`
- `lifeos-retire-engineer-cloud-secrets.yml`
- `lifeos-tower-thermal-context-ab.yml`

Rationale:
- email duplicate/legacy retirement: one-time retirement actions; current Paperless-first mail architecture owns ongoing operation.
- Pi5 AI broker migration and provider diagnostics/probes: migration/diagnostic scaffolding superseded by the stable-base broker/provider contracts and current Governor routing.
- Engineer cloud-secret retirement: one-time privacy hardening action; current local-only private-domain policy is the maintained control.
- Tower thermal 8192 acceptance: completed acceptance experiment; 8192 is now canonical and ongoing lifecycle/control workflows cover operation.

Not removed in this batch: permanent CI, stable-base contracts, Mission Control, managed updates, deployment/lifecycle workflows, or ambiguous stage/PIP workflows that still need item-specific supersession proof.