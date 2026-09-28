# LifeOS Finance deterministic workflows

Issue #17 extends the existing FreeAgent-selected, local-only read model without creating a second ledger.

Implemented here:
- deterministic/user-reviewed classification state separate from authoritative ledger data;
- local co-pilot facts for income, expenditure, net cash flow, category totals, recurring candidates, unresolved classifications and missing evidence;
- AI classifications remain proposals until explicitly reviewed and never write the ledger;
- versioned UK rental mapping for tax year 2025-26 using HMRC SA105 2026;
- draft rental tax pack with unresolved/missing-evidence queues and Paperless provenance references;
- deterministic accountant CSV export.

Tax mapping is deliberately fail-closed. The 2025-26 rules map only explicit supported categories to SA105 boxes 20, 24-29, 36 and 44. Residential finance costs are reported separately at box 44 and are not deducted by this module when computing the pre-finance-cost property result. Unsupported categories/tax years remain unresolved. No deductibility inference or HMRC submission path exists.

Authoritative references:
- https://www.gov.uk/government/publications/self-assessment-uk-property-sa105
- https://www.gov.uk/hmrc-internal-manuals/property-income-manual/pim2054
- https://www.gov.uk/hmrc-internal-manuals/property-income-manual/pim2120

Production financial data remains local-only. GitHub/CI tests use synthetic records only.
