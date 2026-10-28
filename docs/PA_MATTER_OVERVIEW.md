# PA daily overview and source-backed decisions

The PA page opens a concise daily list, then opens one selected matter on demand.
Today includes undated and due/overdue actions and questions; Upcoming shows
future dated work; Waiting keeps source-derived waiting matters separate;
Reference shows retained quote-only information. Reference rows are published in
`reference_items`, never the legacy actionable `items` channel, so an old cached
card cannot present them as tasks during rollout. All matters includes closed
and snoozed rows. The existing bounded sensor projection is retained; if there
are more than 100 matters, the page states how many are shown. No second task
manager, source store or classifier service is introduced.

Question, action, waiting, information and closed are presentation types. Source
status, source evidence and persistent user annotations retain their authority.
Missing deadlines, device details, location and sign-in time are explicit unknowns.
An email timestamp is labelled as an alert-email time, never a sign-in time.
Source email and verified Paperless links remain available alongside history.

## OpenAI sign-in confirmation

Only an exact source email with an OpenAI sender domain and explicit sign-in
wording can create the specialised question. Sender naming is not authentication:
the card says the email reports an event and links to the original email. OTPs,
password resets and generic security advice do not qualify. Conditional no-action
wording cannot delete a recognised sign-in alert. New recognised sign-in messages
use a deterministic source guard, not an additional model/promotion path.

Each decision is keyed by SHA-256 of its exact Message-ID inside the existing
user-owned overlay. The HA bridge accepts only a current event ID for that matter.
Yes acknowledges that event; a matter closes automatically only when every
source is a recognised event and every event is acknowledged. A later or unrelated
source remains open. No keeps security follow-up open; Not sure keeps review open.
A new answer supersedes an earlier whole-matter status override; a later explicit
close/reopen remains user-owned. No answer authorises/blocks a provider login,
changes credentials, sends mail, or invokes a mailbox write. Official security
help uses a fixed OpenAI URL, never an untrusted URL from an email.

## Retained information

Quote-only rows keep provenance and notes, stay outside attention counts, and
are visible in Reference without completion/Junk controls. Review and note remain available. **Track this**
uses the existing explicit user reopen action to accept a personal follow-up; it
does not turn the source email into proof of an obligation. A quote cannot establish an existing policy renewal date.
Information and obligation buckets are disjoint, including legacy duplicate rows.

## Validation and rollback

Synthetic tests cover event-scoped replay/new events, unrelated-source protection,
prior closure, invalid event IDs and source recognition. Node contracts cover
navigation, contextual controls, escaping and dispatched answer payloads.
The existing governed PA deployment verifies the served card bytes and access
checks. Gate H verifies live projection uniqueness, source parity, question counts
and informational exclusion using fixed public counters only. Actual phone visual
acceptance remains a separate check; synthetic rendering is not that evidence.

Rollback is a reviewed revert and redeployment through the existing fixed gateway.
Do not delete original task data, source emails, documents, notes or decision
history. Unknown overlay fields are retained, so rollback need not erase decisions.
Finance remains excluded. EmailOps stays shadow-only with lifecycle UNKNOWN.


## Source quality correction

The native source guard applies to both future extraction and existing saved
rows. Promotional offers, routine delivery status and explicit optional bulk
invitations cannot establish a user commitment or a personal due date. Titles
are used only to select extra exact-source lookups; they never authorise a hold.
All saved source messages must be retrieved and positively non-obligatory before
creating a hold. Mixed, unknown or mandatory evidence remains active. Temporary
lookup failure does not undo an existing hold; a retrieved contradictory source
does. No date alone closes a genuine obligation or proves completion.

Mandatory response, invoice/payment, actual policy, accepted application,
appointment, delivery exception and equipment return signals outrank campaign
footers. Existing user active-status, date or priority decisions are preserved. User-closed
and dismissed matters retain their closed view through source replay.
Information keeps its original source IDs, history and notes, carries an explicit
reason and stays out of the legacy action channel. A user can choose Track this
as a personal commitment through the existing overlay; no new task store or
mailbox write is introduced. The existing pinned EmailOps shadow classifier is
not promoted and local models are unchanged.

Native acceptance reports fixed per-kind held counts and verifies zero known
optional-source rows remain actionable without a user decision. This is a
bounded source correction, not representative-corpus or general classification
acceptance. Missing or ambiguous sources stay unresolved for later review.


Exact saved-source lookups start in Inbox on a fresh owned IMAP session. If
source IDs remain missing, that owned session checks the fixed Gmail All Mail
names read-only, searching only missing exact IDs (with bounded existing date
fallback). A caller-owned selected session is never reselected or closed. Every
retrieved RFC822 Message-ID must match before the source is accepted. This does
not scan arbitrary mailboxes or change flags, labels, read state or contents.
Only aggregate recovered/missing-source and disposition-reason counts are logged.


## Unconfirmed commitments and unavailable sources

A source-verified application-related candidate that is still unclassified by
these guards is presented as a question, unless mandatory, accepted-commitment
or transactional uncertainty signals require preserving it as an action. Missing
source messages are explicitly flagged for review. No row is completed, deleted
or dismissed by either flag. The original title, sources, notes and extracted
date remain available; an optional commitment's extracted date does not enter
obligation overdue counts before the user accepts it. Unknown extracted dates
are labelled rather than asserted as personal deadlines.

Yes, track this and No, not something I need to do use existing reopen/dismiss
user overlay actions. The explicit user answer survives source replay. This
creates a small user decision, not a fabricated commitment or assumed completion.
The current source and commitment uncertainty are visible in the real HA entity
and covered by native question-count and source-parity acceptance.


During a mixed-version rollout, the sensor prefixes unconfirmed rows with
Confirm whether to track / Review source for and excludes their extracted dates
from the legacy deadline field. New clients receive separate original-title and
extracted-date context. Old cached clients therefore cannot falsely present an
unconfirmed application as a plain overdue personal obligation. Source records
and saved user decisions are retained without changing their original dates.


Tracking acceptance and date verification are separate. Yes clears the tracking
question, while an unverified extracted date remains context until an explicit
user due-date override or a verified policy date replaces it. Shared attention
projection semantics are used for structured assistant matches, including targeted
queries; empty due lists never fall back to raw uncertain dates. Reviewing an
unavailable source needs the user even if the underlying process is waiting on
another party; the original source status remains in canonical state.


Owner date/priority projections retain independent machine-base values, including
whether the base date was unverified. Bounded source replay restores those base
values before fresh source reconciliation and reapplies current owner decisions
afterwards. This prevents an acceptance test's temporary override becoming source
state after its overlay is restored. Native acceptance checks restored projected
values against the unchanged source record. Historical dates with no independent
proof remain labelled Saved date / unverified; this does not claim recovery of
previously overwritten source values or invent old dates from message age.


Optional feedback and meal/order change windows are source-only informational
updates, not personal obligations. A survey needs positive optional or customer
feedback context; clinical, licence, identity and other concrete duties remain
protected. A separate request in the same message outranks optional content.
Unclassified feedback/change candidates ask about tracking instead of silently
assuming commitment. Missing or mixed source evidence cannot create a hold.

A past scheduled-event candidate asks whether follow-up is still needed only
when all retrieved sources are event notices without a concrete response or
deadline. This is neither completion nor cancellation. The saved date remains
unverified context, separate from obligation overdue counts; independently
verified or owner-set deadlines and explicit owner decisions retain precedence.
Native acceptance checks the actual HA entity, question labels, separate saved
dates, aggregate feedback/change dispositions and elapsed-event question count.
An already loaded older HA custom element still requires a full client reload;
server deployment cannot replace JavaScript already executing on a phone.

## Past event dates and source requests

An old saved date is not automatically treated as a response deadline for a
hearing or appointment. The source must identify a scheduled event and repeat
the same date; every exact source must be available; and there must not be a
separate explicit response deadline. Otherwise, the existing actionable matter
and deadline remain visible. When the date matches an event and follow-up remains
uncertain, the dashboard asks the user to review status, retains source-action
signals and existing high priority, labels the date unverified, and never marks
the matter complete. A user-set or independently verified policy date remains
authoritative. The read-only Pi audit reports aggregate counts for these cases;
it does not emit source text, titles, IDs or secrets.
