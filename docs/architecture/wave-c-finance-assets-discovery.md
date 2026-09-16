# Wave C Finance & Assets discovery

Status: discovery contract only. No live financial adapter, account connection,
ledger write or tax submission is authorised by this decision.

## Evidence and decision

The LifeOS mission brief requires a mature off-the-shelf accounting and Making
Tax Digital (MTD) product to remain the authoritative ledger. LifeOS supplies
integration, provenance, evidence links, reconciliation proposals and review
workflows; it does not implement an accounting engine. The existing
`finance-assets` Governor domain is `local-only`, disables cloud fallback and
fails closed.

Repository discovery found reusable Paperless REST/evidence interfaces, the
Wave B event/obligation/action/evidence model, governed deployment boundaries
and existing energy sources. It did not find a proven Finance & Assets ledger
or ingestion implementation. Historical Governor job records are not proof of
one.

Select the OTS core only after a bounded, synthetic-data evaluation. Evaluate
FreeAgent, Xero, QuickBooks Online and Sage against the current HMRC-recognised
software finder, API entitlement, UK property-income/MTD coverage, bank feeds,
exports, audit history and cost. Evaluate a landlord-specific product only if a
documented property workflow gap remains. This shortlist is not a product
selection or permission to purchase.

Use the selected ledger's native bank feeds first. If they are inadequate,
evaluate a regulated read-only Open Banking provider separately. Account
consent, paid subscriptions and production HMRC authority are human/account
boundaries. LifeOS must not build a direct HMRC submission client merely to
avoid them.

Public references used for the discovery decision:

- HMRC compatible-software guidance:
  <https://www.gov.uk/guidance/choose-the-right-software-for-making-tax-digital-for-income-tax>
- HMRC Developer Hub: <https://developer.service.hmrc.gov.uk/api-documentation>
- TrueLayer Data API overview (only if a native-feed gap is proven):
  <https://docs.truelayer.com/docs/data-api-basics>
- DVLA available APIs:
  <https://developer-portal.driver-vehicle-licensing.api.gov.uk/availableapis.html>

## Source authority

| Concern | Authority | LifeOS responsibility |
|---|---|---|
| Booked transactions, balances, ledgers and MTD state | Selected OTS accounting/MTD product | Read references, reconcile and present review work |
| Raw bank observations | Bank or approved Open Banking provider | Read-only cursor and immutable source reference |
| Receipt, invoice and tax evidence | Paperless | Store exact document ID and checksum link; never duplicate content |
| Desired adapters, schemas and policy | GitHub | Canonical reviewed source and history |
| Runtime cursor/cache | Local operational state | Recoverable, non-authoritative read model |
| Vehicle statutory facts | DVLA/MOT interfaces | Read-only facts where authorised |
| Energy measurements and tariffs | Existing Enphase/Octopus/Predbat sources | Derive traceable EV-cost inputs; ledger remains financial authority |
| Attention and presentation | PA and Home Assistant | Surface decisions; never act as ledger or document store |

Property and future business activity use distinct entity/property dimensions
inside the selected ledger. A property-management system is added only for a
proven tenancy or maintenance gap. Vehicle costs, mileage, insurance,
maintenance and EV charging use the same ledger/provenance model; travel
planning remains out of scope.

## Read-model contract

`governor/contracts/finance-assets-read-model.schema.json` describes the only
repository-approved Wave C data shape at this stage. It is a local,
references-only projection, not a journal. Amounts use signed minor units plus
ISO currency. Material values retain source identity, observation time,
canonical revision and reconciliation state. Evidence links use a Paperless ID
and checksum, never document text or a host URL.

The deterministic import fingerprint is SHA-256 over the UTF-8 string:

`source_system|source_record_id|booked_on|currency|amount_minor`

Re-reading the same source fingerprint is idempotent. Conflicting observations
with the same source identity stop for review. Reconciliation requires exact
currency and amount agreement; classification confidence cannot override
deterministic checks. Local AI may propose a category but cannot perform an
authoritative write.

UK tax-year labels use `YYYY-YY`, beginning on 6 April. For example, 5 April
2026 is `2025-26` and 6 April 2026 is `2026-27`. The OTS product remains
authoritative for actual tax treatment.

## Privacy and mutation gates

All bank, transaction, balance, tax, tenancy, property, receipt, invoice,
vehicle-ownership and mileage data is `local-only`. Codex/cloud workers may use
this architecture, schema and synthetic fixtures only. Raw provider payloads,
descriptions, account identifiers, credentials and document bodies are not
GitHub or control-record fields. A public reference question must be separated
from private context before web/cloud use.

This discovery contract hard-codes read-only mode and forbids authoritative
writes or submissions. Later mutation support requires a separate reviewed
contract with deterministic policy, scoped approval, transaction/rollback
evidence and human confirmation for uncertain ledger classifications or any
HMRC submission. Home Assistant cannot grant that approval.

## Backup and recovery gates

Current Pi restic coverage includes `/opt/stacks`, but Paperless media and
exports are Synology mounts outside that path. Before Wave C acceptance:

1. prove application-consistent export or database dump and restore for the OTS
   ledger rather than relying on a live database-volume copy;
2. prove independent snapshot/backup and restore for Paperless media/export;
3. restore a synthetic transaction, its exact Paperless evidence link and its
   reconciliation record without production overwrite;
4. document RPO, RTO, retention and credential recovery without logging secrets.

## Delivery stages and acceptance

1. **Discovery/selection:** synthetic API evaluation and explicit product
   decision; no purchase or account authorisation inferred.
2. **Contracts:** deterministic schemas, synthetic fixtures and privacy,
   idempotency, UK-tax-year, reconciliation and mutation-gate tests.
3. **Read-only adapters:** least-privilege scopes, local cursors, outage
   fail-closed behaviour and redacted evidence.
4. **Reconciliation/evidence:** exact ledger-to-Paperless links and deterministic
   matching, with uncertain results queued for review.
5. **Local intelligence:** Tower-only classification proposals; no AI write.
6. **Controlled ledger mutation:** separately reviewed and approved transaction
   path after the autonomous-engineering safety gate.
7. **HMRC submission:** separately authorised human-reviewed action using the
   chosen OTS core.

Wave C discovery passes when stages 1 and 2 identify the product decision gate
and the synthetic contract tests pass. It does not imply live ingestion, an
authoritative classification, an accounting entry or an HMRC submission.
