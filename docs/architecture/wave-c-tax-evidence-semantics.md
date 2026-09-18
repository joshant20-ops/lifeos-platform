# Wave C tax evidence semantics

Tax relevance is not tax deductibility.

LifeOS must keep these concepts separate:

1. **tax_related** — correspondence or evidence concerning tax (including HMRC letters, coding notices, calculations, returns and notices). This alone never implies an expense or deduction.
2. **financial_evidence** — a document useful to financial reconciliation. This alone never implies an expense or deduction.
3. **expense_candidate** — positive evidence that money was actually spent. Mentions of tax, VAT, HMRC, an amount, or a financial institution are insufficient.
4. **deductible_expense_candidate** — an expense candidate with positive evidence connecting the expenditure to an allowable work/employment or rental-property purpose. It remains a candidate until reconciled/validated; LifeOS must not automatically claim it.

## Conservative rules

- HMRC correspondence is normally tax-related evidence, not a deductible expense.
- Payslips, P45/P60 documents, tax calculations, coding notices, returns, bank statements, mortgage statements, insurance documents and contracts must not become deductible solely from their document type, financial vocabulary or presence of amounts.
- Keyword matching for `tax`, `VAT`, `HMRC`, `expense`, `invoice`, or similar terms is never sufficient to set deductibility.
- Deductibility requires positive purpose evidence for work/employment or rental property plus evidence of actual expenditure.
- Mixed/private-use, capital-vs-revenue, unclear-purpose, unsupported, or otherwise ambiguous cases are REVIEW/unresolved rather than deductible.
- Paperless remains document/evidence authority. The accounting system remains ledger authority. LifeOS stores classification, references, relationships and reconciliation state rather than inventing ledger facts.
- Real personal/financial document semantics remain local-only; no cloud inference.

## P9 acceptance guard

P9 must prove with synthetic fixtures that an HMRC letter containing tax terms and amounts is `tax_related=true` while `expense_candidate=false` and `deductible_expense_candidate=false`; that an unrelated/private purchase is not deductible; and that a supported work/property expense can only become a deductible *candidate*, never an automatic claim.
