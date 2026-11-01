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
