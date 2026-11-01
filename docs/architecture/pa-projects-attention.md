# Projects + Attention first slice (#1498)

Authority: `docs/UNIFIED_ROADMAP.md`. This slice is **not accepted** until independent validation, governed Pi deployment, consumed HA runtime evidence and owner acceptance are recorded. Do not close #1498 from this change.

## Reuse and schema gap

`lifeos_tasks_v3`, its accepted matter relationships and timeline, the sole reconciler and `apply_user_state` remain authoritative. The existing HA sensor derives `lifeos_projects_projection_v1` after the user overlay. No database, service, provider, classifier or task publisher is added. Existing source links, Paperless evidence and user actions remain on the matter cards.

Current PA rows lack a consistently declared finite intended outcome. Therefore a derived grouping without an explicit accepted `intended_outcome` is labelled **candidate / outcome not confirmed**. This change does not write an outcome or pretend all responsibilities are finite projects. The documented gap is filled by a bounded `project` annotation on an existing matter entry in the existing user-state overlay. The existing HA action bridge supports naming a finite outcome and explicitly completing/reopening that outcome. No task status, dates, source records or classifier decision changes. The projection always clears old projected annotations before reapplying current owner state. Areas/Routines/Reference infrastructure is deliberately absent.

## Deterministic read contract

Each project exposes a reproducible ID, name, nullable outcome, lifecycle, Attention state, underlying matter IDs, five Attention buckets, next-action/waiting summaries, counts, consolidated timeline, latest recorded update, uncertainties and relationship provenance. No percentages are estimated.

Grouping uses an exact complete accepted reference set, otherwise exact normalized counterparty AND topic only when neither row has a reference, otherwise the accepted matter ID. Order-only references are supplier scoped; labelled case references follow existing reconciler cross-sender semantics. Conflicting, one-sided or overlapping-but-different reference sets stay separate. No transitive fuzzy matching or counterparty-only merge occurs. No semantic inference/provider calls are added; uncertain grouping remains separate.

IDs derive from the deterministic identity key and survive reorder, replay and additional members with the same identity. Candidate IDs can change when accepted reference/topic identity changes. Once an owner confirms an outcome, its existing matter anchor determines the stable project ID, surviving reference/topic changes and added unannotated members. Conflicting owner outcomes are flagged for review rather than silently accepted. If the accepted reconciler later replaces/removes the anchor itself, identity continuity needs review; no alias datastore is added.

Timeline updates consolidate identical accepted title/status/kind with all supporting source IDs, source dates and matter IDs retained. Only events whose exact source ID belongs to the authoritative row are included. Observation time is labelled observation time, never a deadline or claimed source/event time. Consolidation can collapse repeated identical updates; source lists remain navigable on underlying matters. Existing upstream 20-event retention is unchanged; this is not a full email archive.

Effective OPEN => ACTION; WAITING => WAITING; snoozed/unknown => WATCH; suppressed/NONE/dismissed => INFORMATION; DONE => COMPLETE. Dismissal is not successful completion. Confirmation questions remain ACTION questions. Information never changes another obligation's state. A later accepted OPEN state can unblock an action; the project layer cannot do that itself. Age/date alone never completes anything. A known finite outcome closes only after explicit owner outcome confirmation. Completing all currently known items is insufficient. Outcome completion does not close/suppress any obligation; remaining open obligations stay in Attention with an explicit conflict warning. Candidate groups remain candidates even if their items are DONE. Outcome metadata is presentation/owner intent, never a competing obligation authority.

## Ask compatibility and privacy

The projection provides exact project/matter IDs, Attention buckets, accepted upcoming/recent completion IDs, latest recorded updates, timeline source dates and relationship provenance. A future Ask adapter can join those IDs to the existing effective task projection for due semantics and source navigation. It must preserve current unverified-date and uncertainty rules. No full Ask implementation or AI framework is included.

All production projection/source data stays in the existing local HA boundary. Public fixtures contain invented example.test sources only. No private corpus, raw mail, financial ledger or document is needed for CI. EmailOps remains read-only; no mailbox writes, classifier promotion or confirmed-junk activation. Finance, HA, Paperless and EmailOps authority boundaries are unchanged.

## Verification and rollback

The native acceptance also temporarily exercises naming/completing/reopening an outcome through the installed HA bridge, checks unchanged task states and stable project identity, and restores the original overlay using the existing Gate H cleanup. This synthetic temporary annotation is not evidence of a real completed outcome.

Run `python3 -m unittest tests.test_pa_projects tests.test_pa_matter_overview tests.test_pa_source_disposition`, the selected PA pytest suite in LifeOS CI and `node --test tests/personal_admin/pa_task_card.test.cjs`.

After independently validated merge, the existing LifeOS PA Deploy workflow installs the existing sensor/card/package and runs Gate H/I. The read-only acceptance adds actual authenticated HA `projects_view` equality, source coverage, unique membership, information/completion assertions and aggregate multi-source count. These checks emit no private content. A zero multi-source count does not prove the required real project acceptance. Card hash validation and existing override cleanup/zero-error/privacy checks remain required.

Rollback is a reviewed revert through the same PA deploy path; derived data rebuilds on polling. No authoritative task state or user overlay migration needs undoing. Do not use an arbitrary runner shell or bypass the fixed gateway to demonstrate this UI.

Remaining acceptance: actual coherent real multi-source/multi-thread finite project, representative human-labelled corpus quality, lifecycle/completion coverage, review of grouping uncertainty and identity continuity, phone layout, and owner acceptance. These remain #1498 work, not a separate programme. Runtime markers alone do not establish classification quality or user acceptance.


## Owner rejection and legacy-evidence correction (1 November)

Owner phone review rejected the initial view's generic naming, empty historical timeline, unexplained ACTION and repeated empty sections. Passing consumed-runtime equality/aggregate counts did not establish that real project acceptance. Do not treat the earlier implementation checkpoint as user acceptance.

Processed scan IDs are not proof that historical timeline events were ever published. The sole reconciler now backfills metadata-only events for exact already-authoritative source IDs found through the existing bounded, read-only source lookup. It records the verified subject, sender-date provenance and reference IDs; never source bodies, guessed past actions, completion or current state. Unavailable dates remain unknown. Existing lifecycle events win and replay is idempotent. Legacy rows with no history use the same exact-ID lookup for their retained sources; no speculative mailbox/reference search is added.

A positive ordinary order acknowledgement can use the existing informational hold policy only when every source is available and positively non-obligatory. Explicit payment, identity, collection and other requests, mixed/missing evidence and user tracking/closure overrides retain protection. A receipt does not establish delivery or completion. No acknowledgement is automatically converted into WAITING; that requires an independently accepted waiting state.

For Projects identity, verified supplier-scoped order references take precedence over differing generic topics/auxiliary case references. Same-company domain can correlate different named senders only with the exact same verified order set; public mail providers are scoped to the individual address. Existing source/case provenance remains. Unrelated orders never join just on counterparty.

Project detail now explains the next move, names generic order groups using their accepted counterparty, shows only populated sections with a compact empty-section summary, and avoids repeating per-matter empty timelines. Technical candidate/outcome warnings are replaced by a single suggested-grouping explanation. Native acceptance renders the actual HA Projects data with the installed card locally and exposes only aggregate history/order/vehicle-state counters; private identifiers, subjects and message contents must never enter logs. Actual semantic grouping and user/phone acceptance still require local review after deployment.

Order-acknowledgement correction is limited to unsupported OPEN actions. An acknowledgement alone cannot suppress an existing WAITING/DONE state; those states remain authoritative, including when undoing a temporary receipt hold. Native optional-action checks distinguish protected waiting from unsupported open actions.

## Accepted owner relationships and source-scoped waiting

The owner has supplied the missing relationship/current-state decision. The demonstrated schema gap is that the existing overlay can annotate one outcome but cannot link separate accepted matters or scope a waiting decision to reviewed evidence. Extend that same overlay with an anchor link and a source-ID snapshot; do not add a second store or obligation publisher.

The governed deployment applies this one-time confirmation only to the pre-deployment reviewed source set, with fixed selector/count/freshness/date preconditions. The actual identifiers, original overlay backup, membership and waiting snapshot stay local. A durable confirmation reference records provenance and makes the operation idempotent. No new same-company records automatically inherit membership. The source publisher still owns source facts; the owner owns this explicit decision. Unrelated rows/notes/date/priority/closure decisions are preserved.

A later positively informational event preserves waiting. A later request, completion, unknown source or missing lifecycle evidence ends the scoped waiting decision and exposes the authoritative source state; no permanent blanket suppression. Explicit newer owner decisions supersede the scoped confirmation. Removing the confirmation restores the machine backing status, not a persisted projection.


The reviewed deployment hook is deliberately one-time and fixed to the confirmed pre-deployment dataset, not a general supplier grouping rule. It rejects a newer-than-reviewed projection, changed membership/counts, missing sources or a later owner status/project decision before writing anything. The generic writer takes a local source set, records its IDs privately, backs up the complete original overlay in the existing 0700 directory as0600, and atomically commits all annotations with one revision. The opaque confirmation reference makes later deployments no-ops for this decision; it does not reset newer user decisions. Rollback uses the preserved private overlay backup and a reviewed code revert. Never delete that backup as cleanup.

Membership is an explicit anchor link. Only the anchor owns the outcome; child matters carry the link and confirmation provenance. New unrelated same-provider matters are not automatically included. Original source/machine status is retained; scope expiry/removal restores it. Same-second newer owner status actions win through overlay revision ordering. Repeated waiting statements collapse to one project summary with the underlying items and sources available in a disclosure.

## Related financing membership

The owner clarified the financing relationship beyond the original sender-scoped set. Reuse the existing anchor/confirmation schema: a separate, date-bounded membership-only decision links the identified current PCP/identity finance matters to the existing purchase. It does not copy lender ledger data, classify mail, create a financial authority, clear source-review uncertainty, or infer that a finance step is complete/waiting.

Only the current explicitly identified vehicle-finance labels are selected; unrelated lender products and future same-company records are excluded. Original status/waiting decisions, comments, dates and priority stay unchanged. A private pre-change overlay backup, a confirmation reference and per-member annotation fingerprints provide idempotence, rollback and preservation evidence. Provenance distinguishes the original reviewed state decision from the later relationship-only decision. Native validation checks the union of accepted memberships, not a permanently frozen nine-member project.


## Attention presentation grouping correction

Owner phone review showed that the Attention list still rendered one top-level card per underlying item, despite correct shared membership. A repeated project subtitle is not a grouped user experience. Attention now renders exactly one collapsed disclosure per project in its primary Attention category, with action/question/waiting/information counts and a concise summary. All underlying items, existing controls and source links are available inside nested disclosures. Mixed-state projects do not appear repeatedly in several categories. Expansion state survives sensor refreshes.

This is presentation only: no grouping/status/source/user-state migration. Synthetic contracts and native rendering of the actual private HA payload assert one visible parent structure for the confirmed project, all expected child items, default collapse and no duplicate project cards. Hash/served-version checks remain required; browser/phone visual acceptance is still a separate owner check.

## Outcome-first expansion after phone acceptance

The owner accepted the grouped Attention presentation, then clarified that outcome organisation and timelines should apply throughout, including small/single-source matters. Companies are participants, not project boundaries. The original owner-confirmed vehicle/lender membership is evidence for that case, not a global company-name rule. Broader #1498 acceptance remains open.

Schema gap: legacy `case_reference_ids` flatten order/tracking/case labels, so unequal sets cannot safely be used as transitive cross-company edges. The existing sole reconciler now adds `correlation_refs` (typed order/tracking lists) to retained timeline events when their exact sources are available. This is metadata recovered inside the existing local read-only lookup, not new source searching, inference, authority or historical state replay. Long explicitly labelled tracking/consignment/shipment IDs are recognised; bare numbers, URLs and short generic IDs are insufficient. Lifecycle values remain unchanged. Existing private retained-history bounds and specialist source boundaries apply.

The derived projection can join existing groups through an exact common tracking ID across companies. Order numbers retain supplier scoping. Whole connected components are validated before joining: multiple tracking IDs on one matter, multiple order IDs on a matter, or conflicting order IDs from the same supplier keep the affected groups separate with uncertainty. Explicit owner-linked membership remains pinned rather than silently expanded. Evidence retains the exact originating source and typed references. No semantic/AI matching or provider framework is introduced; missing links remain unresolved.

Every existing matter remains in exactly one outcome group. An exact-ID verified primary source with a saved subject can start an evidence-only timeline even when legacy history is absent. Its saved email date is used only when timezone-aware; missing time stays unknown. This never invents a lifecycle/action/completion event or intended outcome. Repeated source IDs retain every supporting matter relationship. Consolidation distinguishes evidence-only history from accepted lifecycle events and distinguishes time semantics.

Project and Attention disclosures expose timelines with expandable supporting source links using the existing email navigation. Native acceptance checks all eligible retained primary sources appear with provenance, renders timelines from actual HA data, and reports only coverage/count markers. Cross-company group counts may be zero: deployment/coverage is not proof that all real-world relationships have sufficient evidence. Broader correlation, overlapping-action deduplication, unsupported current actions and representative corpus quality remain #1498 work. Rollback is a reviewed code revert; derived groups can be rebuilt, and no user-state migration is performed.

## Later completion evidence and partner order references

Owner review identified split retailer outcomes and stale vehicle steps. Read-only Pi audit found three retailer-related matters: a matching order pair and a partner record with auxiliary references, plus later vehicle finance-approval candidates. Saved header candidates are not proof of identity/signing completion.

Two demonstrated gaps are filled in the existing contracts, not in a second task store: (1) `verified_order_links` records exact source/retailer-origin IDs, supplier and order for an explicit retailer-and-order mention in a partner source; (2) `completion_evidence` records completed step, source/matter ID, source date and accepted relationship. Original status/reason and request chronology remain backing evidence. Private references remain local. Generic source-name spelling tolerance is an audit locator only, never membership evidence.

Partner links require a known single-order source from a named supplier and a current unquoted partner paragraph explicitly containing that supplier and exact order. Multiple source order labels, multiple matching known orders/suppliers, bare company similarity and missing sources are insufficient. Auxiliary historical references remain intact. Projection identity can reuse the originating supplier/order key; owner membership still wins. Recovered links are rebuildable from current exact sources, not permanent company aliases.

Completion advances the sole reconciler's existing machine state, before applying user state. It requires all named obligation steps to have strictly later, timezone-aware explicit completion statements from exact retained sources, connected by the same matter, owner-accepted membership or exact supplier/order/case evidence. A finance approval cannot complete identity or signing; combined requests require every step. Additional identity/signing requests in coarse legacy source messages prevent partial closure. Negative, future, conditional and ordinary quoted text are rejected. No semantic provider or mailbox write is introduced. Current deterministic coverage is identity, signing, finance approval and ordinary delivery; unsupported cases remain unresolved, not guessed. Completing steps never completes the overall project.

Explicit user status overrides are preserved. Source-scoped waiting cannot mask a proven DONE backing state. Completion proof is included in existing source history/provenance and the existing HA item contract. Completed cards label their original briefing as earlier email context, rather than present it as a current instruction. Governed acceptance validates completion source IDs and strict chronology, reports aggregate lifecycle/retailer grouping counts and retains existing Gate H/I, source/override and zero-error checks. Rollback is reviewed code revert plus existing private task recovery copies if an accepted state correction is required; never delete provenance or overlay backups as cleanup.

The first consumed-runtime completion pass found no qualifying closures and left the reported retailer split; this was not product acceptance. Follow-up corrections decode MIME headers before recognising orders/completion, distinguish imperative 'check' from a positively completed 'identity check', and qualify generic application approval with accepted finance context. A single explicitly named retailer/order subject has its own scope even when the body contains a partner reference. Generic sender names can use an accepted counterparty only when its exact name is also a sender-domain label. The tracking ambiguity guard consumes this proven supplier scope rather than re-flagging auxiliary historical references. Added runtime counters report only the reported retailer's evidence shapes and match counts. Broader ambiguous source semantics remain unresolved; never infer identity/signing completion solely from finance approval.
