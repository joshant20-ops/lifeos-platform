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
are visible in Reference without completion/reopen/Junk controls. Review and note
remain available. A quote cannot establish an existing policy renewal date.
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
