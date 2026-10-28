class LifeOSPATaskCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
  }

  set hass(hass) { this._hass = hass; this._render(); }
  getCardSize() { return this._config.compact ? 2 : 10; }

  _escape(value) {
    return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
  }

  _dateKey(date) {
    return date.getFullYear() + "-" +
      String(date.getMonth() + 1).padStart(2, "0") + "-" +
      String(date.getDate()).padStart(2, "0");
  }

  _taskDate(value) {
    return /^\d{4}-\d{2}-\d{2}$/.test(String(value || "")) ? String(value) : "";
  }

  _formatDate(value, options = { day: "numeric", month: "short" }) {
    const key = this._taskDate(value);
    if (!key) return "No due date";
    const parts = key.split("-").map(Number);
    return new Intl.DateTimeFormat(undefined, options).format(new Date(parts[0], parts[1] - 1, parts[2], 12));
  }

  _entity() { return this._config.entity || "sensor.lifeos_pa_task_attention"; }

  _items(attrs = this._hass?.states[this._entity()]?.attributes || {}) {
    const rows = [...(Array.isArray(attrs.items) ? attrs.items : []), ...(Array.isArray(attrs.reference_items) ? attrs.reference_items : [])];
    const seen = new Set();
    return rows.filter(row => row && row.id && !seen.has(row.id) && seen.add(row.id));
  }

  _kind(task) {
    if (task.obligation_suppressed) return "information";
    if (["DONE", "DISMISSED"].includes(String(task.status).toUpperCase())) return "closed";
    if (["optional_commitment","source_unavailable"].includes(task.confirmation_required)) return "question";
    if ((task.sign_in_events || []).some(e => e.answer !== "yes")) return task.sign_in_events.some(e => e.answer === "no") ? "action" : "question";
    return String(task.status).toUpperCase() === "WAITING" ? "waiting" : "action";
  }

  _referenceInfo(task) {
    const kinds = {
      quote_only_no_verified_policy: ["Insurance quotes received", "Renewal date: not confirmed", "Quote emails do not establish the renewal date of your current policy. No renewal action is required from these quotes alone."],
      marketing_offer: ["Promotional offer received", "Optional offer", "An offer or discount is optional. Its expiry date is not a personal deadline."],
      routine_delivery: ["Delivery status update", "Information only", "Routine tracking is information. No required follow-up was found in these source messages."],
      optional_opportunity: ["Optional opportunity", "No commitment recorded", "An invitation to apply is optional. These source messages do not show that you accepted or applied."],
    };
    return kinds[task.obligation_suppressed] || ["Information update", "Information only", "Source updates are retained for reference."];
  }

  _title(task) {
    if (task.obligation_suppressed) return this._referenceInfo(task)[0];
    if (this._kind(task) === "question" && task.confirmation_required)
      return task.confirmation_required === "source_unavailable" ? "Does this still need tracking?" : "Do you want to pursue this?";
    if ((task.sign_in_events || []).some(e => e.answer !== "yes") && this._kind(task) !== "closed")
      return this._kind(task) === "question" ? "Was this OpenAI sign-in you?" : "Secure your OpenAI account";
    return task.title || "Untitled matter";
  }

  _commitmentMarkup(task) {
    if (!["optional_commitment","source_unavailable"].includes(task.confirmation_required) || this._kind(task) === "closed") return "";
    const id=this._escape(task.id), missing=task.confirmation_required === "source_unavailable";
    const source=(task.source_message_ids || [])[0];
    const query=encodeURIComponent("rfc822msgid:"+String(source || "").replace(/[<>]/g,""));
    return '<section class="decision"><h4>' + (missing ? 'Do you still need to track this?' : 'Do you want to take this on?') + '</h4><p><strong>' + this._escape(task.original_title || task.title || 'Source matter') + '</strong></p><p>' +
      (missing ? (task.date_verified ? 'LifeOS could not retrieve every original email. Independently verified date evidence is retained; review the source status.' : 'LifeOS could not retrieve every original source message. The status and extracted date need checking.') : 'LifeOS has not established that this is a personal commitment. An invitation or application deadline alone is not enough.') +
      '</p><div class="decision-buttons"><button data-action="reopen" data-id="' + id + '">Yes, track this</button><button data-action="dismiss" data-id="' + id + '">No, not something I need to do</button></div>' +
      (source ? '<a target="_blank" rel="noopener noreferrer" href="https://mail.google.com/mail/u/0/#search/' + query + '">View original source email ↗</a>' : '') + '</section>';
  }

  _confirmationMarkup(task) {
    return (task.sign_in_events || []).map((event, index) => {
      const id = this._escape(task.id), eventId = this._escape(event.id);
      const emailTime = event.email_received_at ? new Date(event.email_received_at * 1000).toLocaleString() : "Not available";
      const query = encodeURIComponent("rfc822msgid:" + String(event.source_message_id).replace(/[<>]/g, ""));
      const choice = {yes: "Confirmed by you", no: "You did not recognise this sign-in", unsure: "Awaiting your review"}[event.answer] || "Awaiting your confirmation";
      return '<section class="decision"><h4>Sign-in alert ' + (index + 1) + '</h4><p>An email reports a sign-in. ' + this._escape(choice) + '.</p>' +
        '<dl><dt>Alert email received</dt><dd>' + this._escape(emailTime) + '</dd><dt>Sign-in time</dt><dd>Not provided in this view</dd><dt>Device / location</dt><dd>Check the original alert</dd></dl>' +
        '<a target="_blank" rel="noopener noreferrer" href="https://mail.google.com/mail/u/0/#search/' + query + '">View this alert email ↗</a>' +
        '<div class="decision-buttons">' + [["yes", "Yes, that was me"], ["no", "No, help secure my account"], ["unsure", "Not sure — review activity"]].map(([value, label]) =>
          '<button type="button" data-action="signin_' + value + '" data-id="' + id + '" data-event="' + eventId + '" aria-pressed="' + (event.answer === value) + '">' + label + '</button>').join("") + '</div>' +
        '<p class="decision-note">Your answer updates only this alert in LifeOS. It does not approve or block a login.</p>' +
        (event.answer === "no" || event.answer === "unsure" ? '<a target="_blank" rel="noopener noreferrer" href="https://help.openai.com/en/articles/8304786-keeping-your-openai-account-secure">Review OpenAI’s account security steps ↗</a>' : '') + '</section>';
    }).join("");
  }

  _overviewMarkup(items) {
    const tab = this._overviewTab || "today", today = this._dateKey(new Date());
    const active = task => !task.snoozed && !["closed", "information"].includes(this._kind(task));
    const shown = items.filter(task => {
      const kind = this._kind(task), due = this._taskDate(task.due_date);
      if (tab === "today") return active(task) && kind !== "waiting" && (!due || due <= today);
      if (tab === "upcoming") return active(task) && kind !== "waiting" && due > today;
      if (tab === "waiting") return active(task) && kind === "waiting";
      if (tab === "reference") return kind === "information";
      return true;
    });
    const labels = {question:"Confirmation",action:"Next action",waiting:"Waiting",information:"Information only",closed:"Closed"};
    const selected = shown.find(task => task.id === this._selectedMatterId);
    const tabs = [["today","Today"],["upcoming","Upcoming"],["waiting","Waiting"],["reference","Reference"],["all","All matters"]].map(([key,label]) =>
      '<button type="button" data-tab="' + key + '" aria-pressed="' + (tab === key) + '">' + label + '</button>').join("");
    const tiles = shown.map(task => {
      const kind = this._kind(task), due = this._taskDate(task.due_date);
      return '<button type="button" class="overview-tile kind-' + kind + '" data-matter="' + this._escape(task.id) + '"><span class="eyebrow">' + labels[kind] + (task.snoozed ? ' · Snoozed' : '') +
        '</span><strong>' + this._escape(this._title(task)) + '</strong>' + (task.confirmation_required ? '<span>' + this._escape(task.original_title || task.title || 'Source matter') + '</span>' : '') + '<span>' +
        this._escape(kind === "information" ? "No action required · Sources retained" : kind === "waiting" ? "Awaiting progress or a reply" : kind === "closed" ? task.status === "DONE" ? "Completed" : "Dismissed" : task.confirmation_required ? (task.confirmation_required === "source_unavailable" ? "Source needs review" : "Personal commitment unconfirmed") : due ? (due < today ? "Overdue · " : "Due · ") + this._formatDate(due) : "No confirmed deadline") +
        '</span><span class="tile-link">' + (kind === "question" ? (task.confirmation_required ? "Answer question" : "Review sign-in") : "Open matter") + ' →</span></button>';
    }).join("");
    return '<nav class="overview-tabs" aria-label="Matter views">' + tabs + '</nav>' +
      (selected ? '<button type="button" class="back-matters" data-back-matters>← Back to ' + this._escape(tab === "all" ? "all matters" : tab) + '</button>' + this._taskCard(selected, true) :
        '<section class="overview-list" aria-label="' + this._escape(tab) + '">' + (tiles || '<div class="empty"><strong>No items in this view</strong><span>Other matters are available in the tabs above.</span></div>') + '</section>');
  }

  _taskCard(task, featured = false) {
    const kind = this._kind(task);
    const id = this._escape(task.id);
    const status = String(task.status || "OPEN").toUpperCase();
    const severity = String(task.severity || "normal").toLowerCase();
    const due = this._taskDate((task.confirmation_required || task.date_confirmation_required) ? task.extracted_date || task.due_date : task.due_date);
    const timelineEvents = (Array.isArray(task.timeline_events) ? task.timeline_events : []).slice(-20);
    const comments = Array.isArray(task.user_comments) ? task.user_comments.slice(-10) : [];
    const sourceRefs = Array.isArray(task.source_message_ids) ? task.source_message_ids : [];
    const evidence = [];
    for (const ref of sourceRefs.slice(0, 3)) {
      const query = encodeURIComponent("rfc822msgid:" + String(ref).replace(/[<>]/g, ""));
      evidence.push('<a target="_blank" rel="noopener noreferrer" href="https://mail.google.com/mail/u/0/#search/' + query + '">Open source email</a>');
    }
    const paperlessBase = String(this._config.paperless_base_url || (window.location.protocol + "//" + window.location.hostname + ":8010")).replace(/\/+$/, "");
    for (const doc of (Array.isArray(task.paperless_evidence) ? task.paperless_evidence : []).slice(0, 5)) {
      if (doc && doc.document_id !== undefined) {
        evidence.push('<a target="_blank" rel="noopener noreferrer" href="' + this._escape(paperlessBase + "/documents/" + encodeURIComponent(doc.document_id)) + '">Open Paperless document</a>');
      }
    }
    const timeline = timelineEvents.map((event) => {
      const when = Number(event?.observed_at) > 0
        ? new Date(Number(event.observed_at) * 1000).toLocaleString()
        : "";
      const eventStatus = String(event?.status || "").toUpperCase();
      return '<div class="timeline-event"><span class="event-dot"></span><div class="event-copy"><time>' +
        this._escape(when || "Earlier") + '</time><strong>' +
        this._escape(event?.title || "Email update") + '</strong>' +
        (event?.event_kind === "information" ? '<em>Information update</em>' : "") +
        (eventStatus && eventStatus !== "NONE" ? '<span class="event-status">' + this._escape(kind === "information" ? "Previous extraction · now information" : task.confirmation_required ? "Previous extraction · awaiting confirmation" : eventStatus === "WAITING" ? "Waiting for reply" : eventStatus === "DONE" ? "Completed" : "Action needed") + '</span>' : "") +
        '</div></div>';
    }).join("");
    const latest = timelineEvents[timelineEvents.length - 1];
    const latestPreview = latest
      ? '<div class="activity"><span>Latest update · ' + this._escape(Number(latest.observed_at) > 0 ? new Date(Number(latest.observed_at) * 1000).toLocaleDateString() : "Earlier") +
        '</span><strong>' + this._escape(latest.title || "Email update") + '</strong>' +
        (latest.event_kind === "information" ? '<em>Information only</em>' : "") + '</div>'
      : "";
    const trailMarkup = featured
      ? '<section class="trail"><div class="trail-heading"><div><span class="eyebrow">The story so far</span><h4>Updates</h4></div><span class="trail-count">' + timelineEvents.length + (timelineEvents.length === 1 ? " update" : " updates") + '</span></div>' +
        (timeline ? '<div class="timeline">' + timeline + '</div>' : '<div class="trail-empty">No message updates have been recorded for this matter yet.</div>') + '</section>'
      : "";
    const noteMarkup = comments.map((comment) =>
      '<div class="note"><strong>Your note</strong><span>' + this._escape(comment.text || "") + '</span></div>'
    ).join("");
    const junkNotice = this._junkFailedTaskIds?.has(String(task.id))
      ? '<div class="junk-notice failed" role="alert">Junk action needs review. Check Gmail Spam and Paperless before retrying.</div>'
      : this._junkPendingTaskIds?.has(String(task.id))
        ? '<div class="junk-notice pending" role="status">Junk action is being processed.</div>'
        : "";
    const supporting = [];
    if (evidence.length) supporting.push('<details><summary>Source messages and documents · ' + evidence.length + '</summary><div class="support-body">' + evidence.join(" · ") + '</div></details>');
    if (timeline && !featured) supporting.push('<details><summary>Full timeline · ' + timelineEvents.length + '</summary><div class="support-body timeline">' + timeline + '</div></details>');
    if (noteMarkup) supporting.push('<details><summary>Your notes · ' + (task.user_comment_count || comments.length) + '</summary><div class="support-body">' + noteMarkup + '</div></details>');
    const snooze = task.snoozed_until ? '<span class="tag muted">Snoozed until ' + this._escape(this._formatDate(task.snoozed_until)) + '</span>' : "";
    const dueTag = task.confirmation_required && task.date_verified ? '<span class="tag">Verified deadline · ' + this._escape(this._formatDate(due)) + '</span>' : task.confirmation_required || task.date_confirmation_required ? '<span class="tag muted">' + (due ? 'Saved date · unverified · ' + this._escape(this._formatDate(due)) : 'No confirmed deadline') + '</span>' : kind === "information" ? '<span class="tag muted">' + this._escape(this._referenceInfo(task)[1]) + '</span>' : due ? '<span class="tag ' + (due < this._dateKey(new Date()) ? "overdue" : "") + '">' +
      (due < this._dateKey(new Date()) ? "Overdue · " : "Due · ") + this._escape(this._formatDate(due)) + '</span>' :
      '<span class="tag muted">No due date</span>';
    const statusTag = '<span class="tag status-' + this._escape(status.toLowerCase()) + '">' + this._escape(kind === "information" ? "Information only" : kind === "question" ? "Awaiting confirmation" : status === "WAITING" ? "Waiting for reply" : status === "DONE" ? "Completed" : status === "DISMISSED" ? "Dismissed" : "Needs action") + '</span>';
    const closed = status === "DONE" || status === "DISMISSED";
    const reviewLabel = task.emailops_shadow_available ? "Review · EmailOps" : "Review";
    const primaryActions = kind === "information"
      ? '<button data-action="reopen" data-id="' + id + '">Track this</button><button data-action="review" data-id="' + id + '">' + reviewLabel + '</button><button data-action="comment" data-id="' + id + '">Add note</button>'
      : task.confirmation_required && !closed
      ? '<button data-action="comment" data-id="' + id + '">Add note</button>'
      : (task.sign_in_events || []).some(e => e.answer !== "yes") && !closed
      ? '<button data-action="review" data-id="' + id + '">' + reviewLabel + '</button><button data-action="comment" data-id="' + id + '">Add note</button>'
      : closed
      ? '<button class="primary" data-action="reopen" data-id="' + id + '">Reopen</button><button data-action="review" data-id="' + id + '">' + reviewLabel + '</button>'
      : '<button class="primary" data-action="close" data-id="' + id + '">Mark done</button>' +
        '<button data-action="review" data-id="' + id + '">' + reviewLabel + '</button>' +
        '<button data-action="comment" data-id="' + id + '">Add note</button>' +
        '<button data-action="snooze" data-id="' + id + '">Snooze</button>' +
        '<button data-action="due_date" data-id="' + id + '">Set due date</button>' +
        '<button data-action="junk" data-id="' + id + '">Junk</button>';
    const secondaryActions = kind === "information" ? "" :
      '<button data-action="severity" data-id="' + id + '">Set severity</button>' +
      (!closed ? '<button data-action="dismiss" data-id="' + id + '">Not a task</button>' : '<button data-action="due_date" data-id="' + id + '">Set due date</button>') +
      (task.snoozed_until ? '<button data-action="unsnooze" data-id="' + id + '">Unsnooze</button>' : '');
    const controls = '<div class="controls"><div class="primary-controls">' + primaryActions + '</div>' +
      (secondaryActions ? '<details class="more-actions"><summary>More actions</summary><div class="secondary-controls">' + secondaryActions + '</div></details>' : '') +
      '</div>';
    return '<article class="task' + (featured ? ' featured' : '') + '"><div class="task-top"><div><span class="eyebrow">' +
      (kind === "information" ? "Information only" : kind === "question" ? "A quick decision" : status === "WAITING" ? "Waiting on someone else" : status === "DONE" ? "Completed matter" : status === "DISMISSED" ? "Dismissed item" : "Your next step") +
      '</span><h3>' + this._escape(this._title(task)) + '</h3></div><span class="severity severity-' + this._escape(kind === "question" && task.severity_source !== "user" ? "normal" : severity) + '">' +
      this._escape(kind === 'question' ? 'Confirm' : kind === 'information' ? 'Reference' : severity) + '</span></div>' +
      '<div class="tags">' + statusTag + dueTag + snooze + '</div>' + (featured ? "" : latestPreview) +
      '<div class="source-line">' + sourceRefs.length + (sourceRefs.length === 1 ? " related message" : " related messages") +
      (task.user_comment_count ? " · " + this._escape(task.user_comment_count) + (task.user_comment_count === 1 ? " note" : " notes") : "") +
      '</div>' + (kind === 'information' ? '<p class="matter-explanation">' + this._escape(this._referenceInfo(task)[2]) + '</p>' : '') + this._commitmentMarkup(task) + this._confirmationMarkup(task) + junkNotice + trailMarkup + supporting.join("") + controls + '</article>';
  }

  _render() {
    if (!this.shadowRoot || !this._hass) return;
    // Sensor polling calls set hass repeatedly. Replacing shadowRoot.innerHTML
    // while a native dialog is open disconnects it and closes the review.
    if (this._activeReviewDialog?.open) return;
    const sensor = this._hass.states[this._entity()];
    const attrs = sensor?.attributes || {};
    this._junkPendingTaskIds = new Set(Array.isArray(attrs.junk_action_pending_task_ids) ? attrs.junk_action_pending_task_ids.map(String) : []);
    this._junkFailedTaskIds = new Set(Array.isArray(attrs.junk_action_failed_task_ids) ? attrs.junk_action_failed_task_ids.map(String) : []);
    this._reviewPendingTaskIds = new Set(Array.isArray(attrs.review_pending_task_ids) ? attrs.review_pending_task_ids.map(String) : []);
    this._reviewFailedTaskIds = new Set(Array.isArray(attrs.review_failed_task_ids) ? attrs.review_failed_task_ids.map(String) : []);
    const items = this._items(attrs);
    const needs = Number(attrs.needs_me || 0);
    const waiting = Number(attrs.waiting_on_others || 0);
    const overdue = Number(attrs.overdue || 0);
    const style = [
      ':host{display:block;color:var(--primary-text-color)}ha-card{padding:16px}',
      '.summary{color:var(--secondary-text-color);margin:4px 0 12px;line-height:1.45}',
      '.count-row{display:flex;gap:7px;flex-wrap:wrap;margin:4px 0 0}',
      '.page-head>.page-copy{min-width:0}.page-head>.count-row{justify-content:flex-end;flex:0 0 auto}',
      '.count{border:1px solid var(--divider-color);border-radius:9px;padding:7px 10px;background:var(--secondary-background-color);min-width:76px;text-align:left;color:var(--primary-text-color);font:inherit;cursor:pointer}.count[aria-pressed="true"]{border-color:var(--primary-color);box-shadow:inset 0 0 0 1px var(--primary-color)}.count:hover{background:var(--card-background-color)}',
      '.count strong{display:block;font-size:1.15rem;color:var(--primary-text-color)}.count span{font-size:.78rem;color:var(--secondary-text-color)}',
      '.open-link{display:inline-flex;align-items:center;margin-top:4px;color:var(--primary-color);font-weight:600;text-decoration:none}',
      '.page-head{display:flex;justify-content:space-between;gap:14px;align-items:flex-start;margin-bottom:14px}',
      '.page-head h1{font-size:1.45rem;line-height:1.2;margin:2px 0 5px;font-weight:650}',
      '.page-head p,.group>p{color:var(--secondary-text-color);font-size:.88rem;margin:0;line-height:1.4}',
      '.page-kicker{font-size:.72rem;text-transform:uppercase;letter-spacing:.08em;color:var(--primary-color);font-weight:650}',
      '.week-heading{display:flex;align-items:center;justify-content:center;gap:10px;margin:18px 0 9px}',
      '.week-heading strong{font-size:.9rem;font-weight:600}',
      '.week-nav{width:36px;height:36px;border:1px solid var(--divider-color);border-radius:9px;background:var(--card-background-color);color:var(--primary-text-color);font-size:1.25rem}',
      '.week-strip{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:3px;margin-bottom:10px;padding:5px;border:1px solid var(--divider-color);border-radius:12px;background:var(--secondary-background-color)}',
      '.day{min-width:0;min-height:66px;padding:7px 3px;border:1px solid transparent;border-radius:9px;background:transparent;color:var(--primary-text-color);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px}',
      '.day:hover{background:var(--card-background-color)}',
      '.day.selected{border-color:var(--primary-color);background:var(--card-background-color);box-shadow:inset 0 0 0 1px var(--primary-color)}',
      '.day-name,.day-count{font-size:.67rem;color:var(--secondary-text-color);white-space:nowrap}.day strong{font-size:.95rem;line-height:1.05}.day.selected .day-name,.day.selected .day-count{color:var(--primary-color)}',
      '.no-date-row{display:flex;justify-content:center;margin:0 0 18px}',
      '.no-date{border:0;background:transparent;color:var(--primary-color);font:inherit;font-size:.82rem;text-decoration:underline;text-underline-offset:3px;padding:7px 10px}',
      '.no-date.selected{font-weight:650}',
      '.task-summary{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 14px}.clear-filter{margin:12px 0 4px;padding:8px 12px;border:1px solid var(--divider-color);border-radius:8px;background:var(--secondary-background-color);color:var(--primary-text-color);font:inherit;cursor:pointer}',
      '.summary-chip{border-radius:20px;background:var(--secondary-background-color);padding:6px 10px;font-size:.77rem;color:var(--secondary-text-color)}',
      '.summary-chip.urgent{color:var(--error-color,var(--primary-text-color));font-weight:600}',
      '.group{margin:17px 0 20px}.group-heading{display:flex;gap:9px;align-items:baseline}.group-heading h2{font-size:1.02rem;margin:0;font-weight:650}.group-heading span{font-size:.75rem;color:var(--secondary-text-color)}',
      '.group>p{font-size:.78rem;margin:4px 0 9px}.task-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr));gap:10px}',
      '.task{border:1px solid var(--divider-color);border-radius:12px;padding:13px;background:var(--card-background-color);min-width:0}',
      '.task-top{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}.task h3{font-size:.98rem;line-height:1.3;margin:0;font-weight:650;overflow-wrap:anywhere}',
      '.severity{font-size:.72rem;text-transform:capitalize;color:var(--secondary-text-color);white-space:nowrap}',
      '.severity-high{color:var(--error-color,var(--primary-text-color));font-weight:650}.severity-normal{color:var(--secondary-text-color)}',
      '.tags{display:flex;gap:6px;flex-wrap:wrap;margin-top:9px}.tag{border-radius:16px;padding:4px 8px;background:var(--secondary-background-color);font-size:.72rem;color:var(--primary-text-color)}',
      '.tag.overdue{color:var(--error-color,var(--primary-text-color));font-weight:650}.tag.muted{color:var(--secondary-text-color)}',
      '.status-waiting{color:var(--primary-color);font-weight:600}.status-done{color:var(--success-color,var(--primary-text-color))}',
      '.activity{border-left:2px solid var(--primary-color);margin-top:11px;padding:1px 0 1px 9px;display:flex;flex-direction:column;gap:3px;min-width:0}',
      '.activity span{font-size:.68rem;color:var(--secondary-text-color)}.activity strong{font-size:.82rem;font-weight:550;overflow-wrap:anywhere}.activity em{font-style:normal;font-size:.68rem;color:var(--secondary-text-color)}',
      '.source-line{font-size:.72rem;color:var(--secondary-text-color);margin-top:10px}',
      '.junk-notice{margin-top:10px;padding:9px 10px;border-radius:8px;font-size:.76rem;line-height:1.4;background:var(--secondary-background-color)}.junk-notice.failed{color:var(--error-color,var(--primary-text-color));border:1px solid var(--error-color,var(--divider-color))}.junk-notice.pending{color:var(--primary-color)}',
      'details{margin-top:8px;font-size:.78rem}summary{cursor:pointer;color:var(--primary-color);padding:3px 0}.support-body{margin:6px 0 3px;color:var(--secondary-text-color);line-height:1.5;overflow-wrap:anywhere}.support-body a{color:var(--primary-color)}',
      '.timeline-event{padding:5px 0;border-left:1px solid var(--divider-color);padding-left:9px;margin-left:3px;display:flex;flex-direction:column;gap:2px}.timeline-event span{font-size:.68rem}.timeline-event strong{font-size:.78rem;color:var(--primary-text-color);font-weight:500}.timeline-event em{font-size:.68rem;font-style:normal}',
      '.note{margin:6px 0}.note strong{display:block;color:var(--primary-text-color);font-weight:550}.note span{overflow-wrap:anywhere}',
      '.controls{margin-top:15px;padding-top:13px;border-top:1px solid var(--divider-color)}.primary-controls,.secondary-controls{display:flex;gap:7px;flex-wrap:wrap}.controls button{min-height:38px;border:1px solid var(--divider-color);background:var(--secondary-background-color);color:var(--primary-text-color);border-radius:8px;padding:7px 11px;font:inherit;font-size:.78rem}.controls button[data-action="close"],.controls button.primary{background:var(--primary-color);border-color:var(--primary-color);color:var(--text-primary-color,#fff);font-weight:600}.more-actions{margin-top:8px}.more-actions summary{font-size:.75rem}.secondary-controls{padding:7px 0 2px}',

      'button{cursor:pointer}button:focus-visible,a:focus-visible{outline:2px solid var(--primary-color);outline-offset:2px}.empty{border:1px dashed var(--divider-color);border-radius:12px;padding:24px 16px;text-align:center;display:flex;flex-direction:column;gap:5px}.empty span{font-size:.82rem;color:var(--secondary-text-color)}',
      '@media(max-width:500px){ha-card{padding:12px}.page-head h1{font-size:1.25rem}.day{min-height:58px}.day-name,.day-count{font-size:.61rem}.task-grid{grid-template-columns:1fr}.count{flex:1;min-width:80px}}'

,
      '.matter-layout{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(240px,.85fr);gap:16px;align-items:start;margin-top:10px}',
      '.matter-main,.matter-rail{min-width:0}.matter-main .task{border-color:color-mix(in srgb,var(--primary-color) 38%,var(--divider-color));box-shadow:0 8px 24px rgba(0,0,0,.07)}',
      '.focus-label{display:flex;align-items:center;gap:8px;font-size:.73rem;text-transform:uppercase;letter-spacing:.09em;color:var(--primary-color);font-weight:700;margin:0 0 9px 3px}.focus-mark{width:8px;height:8px;border-radius:50%;background:var(--primary-color);box-shadow:0 0 0 4px color-mix(in srgb,var(--primary-color) 15%,transparent)}',
      '.matter-rail{border:1px solid var(--divider-color);border-radius:14px;background:var(--secondary-background-color);padding:14px}.rail-heading{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:10px}.rail-heading h2{font-size:1.02rem;margin:3px 0 0}.rail-count,.trail-count{font-size:.72rem;color:var(--secondary-text-color);white-space:nowrap}',
      '.eyebrow{display:block;font-size:.68rem;text-transform:uppercase;letter-spacing:.08em;color:var(--secondary-text-color);font-weight:650;margin-bottom:5px}.task.featured{padding:19px;border-radius:14px}.task.featured h3{font-size:1.35rem;line-height:1.2;letter-spacing:-.025em}.task.featured .tags{margin-top:13px}.task.featured .severity{border:1px solid var(--divider-color);border-radius:20px;padding:4px 9px;background:var(--secondary-background-color)}',
      '.matter-link{display:block;width:100%;text-align:left;padding:11px 10px;margin:7px 0;border:1px solid var(--divider-color);border-radius:10px;background:var(--card-background-color);color:var(--primary-text-color);cursor:pointer}.matter-link.selected{border-color:var(--primary-color);box-shadow:inset 3px 0 0 var(--primary-color)}.matter-link strong{display:block;font-size:.84rem;line-height:1.32;margin:5px 0;overflow-wrap:anywhere}.matter-link-top{display:flex;justify-content:space-between;gap:6px;align-items:center}.matter-status,.matter-date{font-size:.66rem;color:var(--secondary-text-color)}.status-waiting{color:var(--primary-color);font-weight:600}.matter-latest{display:block;font-size:.72rem;color:var(--secondary-text-color);line-height:1.35;margin-top:3px}.matter-messages{display:block;font-size:.67rem;color:var(--secondary-text-color);margin-top:7px}',
      '.trail{margin:18px 0 12px;padding:15px 0 0;border-top:1px solid var(--divider-color)}.trail-heading{display:flex;align-items:flex-end;justify-content:space-between;gap:10px;margin-bottom:13px}.trail-heading h4{font-size:1rem;margin:1px 0 0}.trail-heading .eyebrow{color:var(--primary-color)}.timeline{position:relative;padding:0 0 6px 5px}.timeline:before{content:"";position:absolute;top:7px;bottom:17px;left:9px;width:1px;background:var(--divider-color)}.timeline-event{position:relative;display:flex;gap:11px;padding:0 0 15px;min-width:0}.event-dot{position:relative;z-index:1;flex:0 0 9px;width:9px;height:9px;margin-top:5px;border:2px solid var(--primary-color);border-radius:50%;background:var(--card-background-color)}.timeline-event:last-child .event-dot{background:var(--primary-color)}.event-copy{display:grid;gap:3px;min-width:0}.event-copy time{font-size:.72rem;color:var(--secondary-text-color)}.event-copy strong{font-size:.9rem;line-height:1.35;font-weight:550;overflow-wrap:anywhere}.event-copy em,.event-status{font-style:normal;font-size:.72rem;color:var(--secondary-text-color)}.trail-empty{font-size:.82rem;color:var(--secondary-text-color);padding:4px 0 13px}',
      '.resolved{margin-top:12px;border-top:1px solid var(--divider-color);padding-top:10px}.resolved summary{font-size:.76rem}.resolved-items{max-height:300px;overflow:auto}.rail-empty{padding:12px 8px;color:var(--secondary-text-color);font-size:.79rem;line-height:1.4}',
      '@media(max-width:760px){.page-head{display:block}.page-head>.count-row{justify-content:flex-start;margin-top:12px}.matter-layout{grid-template-columns:1fr}.matter-rail{order:2}.matter-main{order:1}}',
      '.daily-counts{border:1px solid var(--divider-color);border-radius:12px;padding:14px;font-size:.95rem;background:var(--secondary-background-color)}.freshness{color:var(--secondary-text-color);font-size:.72rem}.overview-tabs{display:flex;flex-wrap:wrap;gap:5px;margin:16px 0}.overview-tabs button,.back-matters{font:inherit;min-height:44px;padding:8px 12px;border:1px solid var(--divider-color);border-radius:9px;background:var(--card-background-color);color:var(--primary-text-color)}.overview-tabs button[aria-pressed="true"]{border-color:var(--primary-color);color:var(--primary-color)}.overview-list{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:12px}.overview-tile{font:inherit;text-align:left;background:var(--card-background-color);color:var(--primary-text-color);border:1px solid var(--divider-color);border-left:4px solid var(--primary-color);border-radius:12px;padding:16px;display:grid;gap:8px;min-width:0}.overview-tile strong{font-size:1.04rem;overflow-wrap:anywhere}.overview-tile>span:not(.eyebrow){font-size:.8rem;color:var(--secondary-text-color)}.overview-tile .tile-link{color:var(--primary-color)!important}.kind-question{border-left-color:#e6ad35}.kind-question .eyebrow{color:#e6ad35}.kind-information,.kind-waiting,.kind-closed{border-left-color:var(--secondary-text-color)}.back-matters{margin-bottom:14px}.decision{margin:18px 0;padding:15px;border:1px solid var(--divider-color);border-radius:12px;background:var(--secondary-background-color)}.decision h4{margin:0 0 8px}.decision p,.matter-explanation{font-size:.87rem;line-height:1.5}.decision dl{font-size:.8rem;display:grid;grid-template-columns:1fr 1.3fr;gap:10px;margin:16px 0}.decision dd{margin:0}.decision dt,.decision-note{color:var(--secondary-text-color)}.decision a{color:var(--primary-color);font-size:.82rem}.decision-buttons{display:grid;gap:10px;margin-top:16px}.decision-buttons button{min-height:48px;font:inherit;border:1px solid var(--divider-color);border-radius:9px;background:var(--card-background-color);color:var(--primary-text-color);padding:10px}.decision-buttons button[aria-pressed="true"]{outline:2px solid var(--primary-color)}.decision-buttons button[data-action="signin_yes"]{background:var(--primary-color);color:var(--text-primary-color,#fff)}.decision-buttons button[data-action="signin_no"]{border-color:#e6ad35;color:#e6ad35}.controls button{min-height:44px}',
    ].join("");
    if (this._config.compact) {
      this.shadowRoot.innerHTML = '<style>' + style + '</style><ha-card><h2>' +
        this._escape(this._config.title || "Personal Attention") + '</h2><div class="summary">' +
        this._escape(attrs.briefing || "Local PA attention is unavailable.") + '</div><div class="count-row">' +
        '<div class="count"><strong>' + needs + '</strong><span>Need you</span></div>' +
        '<div class="count"><strong>' + waiting + '</strong><span>Waiting</span></div>' +
        '<div class="count"><strong>' + overdue + '</strong><span>Overdue</span></div></div>' +
        '<a class="open-link" href="/lifeos/personal-assistant">Open Personal Assistant →</a></ha-card>';
      return;
    }
    const questions = items.filter(task => this._kind(task) === "question" && !task.snoozed).length;
    const actions = items.filter(task => this._kind(task) === "action" && !task.snoozed).length;
    const waitingCount = items.filter(task => this._kind(task) === "waiting" && !task.snoozed).length;
    const unavailable = !sensor || ["unavailable","unknown"].includes(sensor.state);
    this.shadowRoot.innerHTML = '<style>' + style + '</style><ha-card><div class="page-head"><div class="page-copy"><div class="page-kicker">LifeOS · Personal Assistant</div>' +
      '<h1>Your day</h1><p>Here’s what needs your attention.</p></div></div>' +
      (unavailable ? '<div class="empty" role="alert"><strong>PA information is unavailable</strong><span>Current matters could not be checked. This does not mean there is nothing to do.</span></div>' :
        '<div class="daily-counts">' + questions + (questions === 1 ? ' question · ' : ' questions · ') + actions + (actions === 1 ? ' action · ' : ' actions · ') + waitingCount + ' waiting</div>' +
        '<p class="freshness">Updated ' + this._escape(attrs.generated_time ? new Date(attrs.generated_time * 1000).toLocaleString() : "time unavailable") + '</p>' + (Number(attrs.total_matters) > items.length ? '<p class="freshness">Showing ' + items.length + ' of ' + Number(attrs.total_matters) + ' matters, in attention order.</p>' : '') + this._overviewMarkup(items)) + '</ha-card>';
    this.shadowRoot.querySelectorAll("button[data-tab]").forEach(button => button.addEventListener("click", () => {
      this._overviewTab = button.dataset.tab; this._selectedMatterId = null; this._render();
    }));
    this.shadowRoot.querySelector("button[data-back-matters]")?.addEventListener("click", () => { this._selectedMatterId = null; this._render(); });
    const samplesButton = document.createElement("button");
    samplesButton.type = "button";
    samplesButton.textContent = "Review email suggestions";
    samplesButton.className = "count";
    samplesButton.addEventListener("click", () => this._showEmailSamples());
    (this.shadowRoot.querySelector(".page-copy") || this.shadowRoot.querySelector("ha-card"))?.append(samplesButton);
    this.shadowRoot.querySelectorAll("button[data-matter]").forEach((button) => {
      button.addEventListener("click", () => {
        this._selectedMatterId = button.dataset.matter;
        this._render();
      });
    });
    this.shadowRoot.querySelectorAll("button[data-action]").forEach((button) => {
      button.addEventListener("click", () => this._act(button));
    });
  }

  async _chooseJunkDocuments(task) {
    const refs = Array.isArray(task.source_message_ids) ? task.source_message_ids : [];
    const documents = (Array.isArray(task.paperless_evidence) ? task.paperless_evidence : [])
      .filter((doc) => doc && /^\d+$/.test(String(doc.document_id || "")));
    if (!refs.length) {
      window.alert("Junk needs at least one linked email.");
      return null;
    }
    const paperlessBase = String(this._config.paperless_base_url || (window.location.protocol + "//" + window.location.hostname + ":8010")).replace(/\/+$/, "");
    const dialog = document.createElement("dialog");
    dialog.setAttribute("aria-labelledby", "junk-title");
    dialog.innerHTML = '<style>' +
      'dialog{max-width:min(520px,calc(100vw - 32px));max-height:80vh;overflow:auto;border:1px solid var(--divider-color);border-radius:14px;background:var(--card-background-color);color:var(--primary-text-color);padding:20px;box-shadow:0 16px 48px rgba(0,0,0,.4)}' +
      'dialog::backdrop{background:rgba(0,0,0,.62)}.junk-title{font-size:1.15rem;margin:0 0 10px}.junk-copy{font-size:.86rem;line-height:1.45;color:var(--secondary-text-color)}' +
      '.junk-docs{display:grid;gap:8px;margin:14px 0}.junk-doc{display:flex;gap:10px;align-items:flex-start;padding:10px;border:1px solid var(--divider-color);border-radius:9px}' +
      '.junk-doc strong{display:block;overflow-wrap:anywhere}.junk-doc small{display:block;color:var(--secondary-text-color)}.junk-doc a{display:inline-block;margin-top:5px;color:var(--primary-color);font-size:.82rem;font-weight:600}.junk-warning{font-size:.77rem;color:var(--error-color,var(--secondary-text-color))}' +
      '.junk-buttons{display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap;margin-top:16px}.junk-buttons button{padding:9px 12px;border-radius:8px;border:1px solid var(--divider-color);background:var(--secondary-background-color);color:var(--primary-text-color);font:inherit}' +
      '.junk-buttons .danger{background:var(--error-color,#b3261e);color:#fff}.junk-error{min-height:1.2em;color:var(--error-color,#b3261e);font-size:.8rem}' +
      '</style><h2 class="junk-title" id="junk-title">Move this matter to Junk?</h2>' +
      '<p class="junk-copy">This will move all ' + refs.length + (refs.length === 1 ? ' related email' : ' related emails') +
      ' to Gmail Spam and dismiss the matter. Choose any linked Paperless documents to delete too. Leave them unchecked to keep them. “View in Paperless” opens a document in a new tab; this selection stays open.</p>' +
      '<div class="junk-docs">' + (documents.length ? documents.map((doc, index) =>
        '<label class="junk-doc"><input type="checkbox" data-paperless-id="' + this._escape(doc.document_id) + '">' +
        '<span><strong>' + this._escape(doc.title || ("Paperless document " + (index + 1))) + '</strong>' +
        '<small>Document ID ' + this._escape(doc.document_id) + '</small>' +
        '<a target="_blank" rel="noopener noreferrer" href="' + this._escape(paperlessBase + "/documents/" + encodeURIComponent(doc.document_id)) + '">View in Paperless</a></span></label>'
      ).join("") : '<p class="junk-copy">No linked Paperless documents were found for this matter.</p>') +
      '</div><p class="junk-warning">Only checked documents will be deleted from Paperless. This may also remove their versions.</p>' +
      '<div class="junk-error" aria-live="polite"></div><div class="junk-buttons">' +
      '<button type="button" data-junk-cancel>Cancel</button><button type="button" class="danger" data-junk-submit>Junk emails and delete selected documents</button></div>';
    this.shadowRoot.append(dialog);
    return new Promise((resolve) => {
      let settled = false;
      const finish = (value) => {
        if (settled) return;
        settled = true;
        resolve(value);
      };
      dialog.addEventListener("close", () => {
        dialog.remove();
        finish(null);
      });
      dialog.querySelector("[data-junk-cancel]").addEventListener("click", () => dialog.close());
      dialog.querySelector("[data-junk-submit]").addEventListener("click", () => {
        const selected = Array.from(dialog.querySelectorAll("[data-paperless-id]:checked"))
          .map((input) => input.dataset.paperlessId);
        finish(selected);
        dialog.close();
      });
      dialog.showModal();
    });
  }

  _datePlusOne() {
    const date = new Date();
    date.setDate(date.getDate() + 1);
    return this._dateKey(date);
  }

  _reviewDialogMarkup(task, busyText = "", previews = []) {
    const docs = (Array.isArray(task.paperless_evidence) ? task.paperless_evidence : [])
      .filter((doc) => doc && /^\d+$/.test(String(doc.document_id || ""))).slice(0, 10);
    const paperlessBase = String(this._config.paperless_base_url || (window.location.protocol + "//" + window.location.hostname + ":8010")).replace(/\/+$/, "");
    const review = task.ai_review && typeof task.ai_review === "object" ? task.ai_review : null;
    const emailops = this._emailopsReports?.get(String(task.id));
    const emailopsMarkup = emailops ? '<section class="review-analysis"><h3>EmailOps preview</h3>' +
      '<p class="review-muted">Comparison only. Your task has not been changed.</p><p>' + this._escape(emailops.summary || "") + '</p>' +
      ((emailops.proposals || []).length ? '<h4>Suggested tasks</h4><ul>' + emailops.proposals.map((item) =>
        '<li>' + this._escape(item.title) + (item.due_date ? ' · ' + this._escape(item.due_date) : '') + '</li>').join("") + '</ul>' :
        '<p>No action suggested for this email.</p>') + '</section>' : '';
    const sourceMessageIds = Array.from(new Set([
      ...(Array.isArray(task.source_message_ids) ? task.source_message_ids : []),
      task.email_message_id,
      ...(Array.isArray(task.timeline_events) ? task.timeline_events.map((event) => event?.message_id) : []),
    ].map((value) => String(value || "").trim()).filter((value) =>
      value.length <= 300 && /^<[^<>\s]+@[^<>\s]+>$/.test(value)
    )));
    const sourceEmails = sourceMessageIds.map((messageId, index) => {
      const event = (Array.isArray(task.timeline_events) ? task.timeline_events : [])
        .find((item) => String(item?.message_id || "").trim() === messageId);
      const query = encodeURIComponent("in:anywhere rfc822msgid:" + messageId.slice(1, -1));
      return '<li><a target="_blank" rel="noopener noreferrer" href="https://mail.google.com/mail/u/0/#search/' +
        query + '">' + this._escape(event?.title || ("Source email " + (index + 1))) + '</a></li>';
    }).join("");
    const sourceMarkup = sourceEmails
      ? '<section class="review-sources"><h3>Source emails</h3><ul>' + sourceEmails + '</ul></section>'
      : '<p class="review-muted">No valid source email is attached. This item should not be actionable.</p>';
    const reviewPending = this._reviewPendingTaskIds?.has(String(task.id)) || false;
    const previewById = new Map((Array.isArray(previews) ? previews : []).map((item) => [String(item.document_id), item]));
    const documents = docs.length ? docs.map((doc, index) => {
      const url = this._escape(paperlessBase + "/documents/" + encodeURIComponent(doc.document_id));
      const preview = previewById.get(String(doc.document_id));
      return '<section class="review-doc"><div class="review-doc-head"><strong>' + this._escape(doc.title || ("Document " + (index + 1))) +
        '</strong><a target="_blank" rel="noopener noreferrer" href="' + url + '">Open in Paperless</a></div>' +
        (preview && preview.ocr_text ? '<pre class="review-doc-text">' + this._escape(preview.ocr_text) + '</pre>' :
          '<p class="review-muted review-doc-unavailable">' + this._escape(busyText || "Document text preview is unavailable. Open it in Paperless to view the original.") + '</p>') + '</section>';
    }).join("") : '<p class="review-muted">No linked Paperless documents were found for this task.</p>';
    const result = review
      ? '<section class="review-analysis"><h3>AI analysis</h3><p>' + this._escape(review.analysis || "No analysis was returned.") + '</p>' +
        '<h4>Recommended actions</h4>' + ((Array.isArray(review.recommended_actions) && review.recommended_actions.length)
          ? '<ol>' + review.recommended_actions.map((item) => '<li>' + this._escape(item) + '</li>').join("") + '</ol>'
          : '<p class="review-muted">No specific actions suggested.</p>') +
        '<p class="review-confidence">Confidence: ' + this._escape(review.confidence || "unknown") + '</p>' +
        ((review.response_body || review.response_subject) ? '<h4>Suggested response</h4>' +
          (review.response_subject ? '<label>Subject<input readonly value="' + this._escape(review.response_subject) + '"></label>' : '') +
          '<label>Draft<textarea readonly rows="6">' + this._escape(review.response_body || "") + '</textarea></label>' +
          (review.response_body ? '<button type="button" data-review-copy>Copy response</button>' : '') : '') +
        '<p class="review-muted">Draft only. It has not been sent.</p></section>'
      : '<section class="review-analysis"><h3>AI analysis</h3><p class="review-muted">' + this._escape(busyText || "No analysis yet. Generate a local review when you are ready.") + '</p></section>';
    return '<style>' +
      'dialog{width:min(980px,calc(100vw - 28px));max-width:980px;max-height:92vh;overflow:auto;border:1px solid var(--divider-color);border-radius:14px;background:var(--card-background-color);color:var(--primary-text-color);padding:20px;box-shadow:0 16px 48px rgba(0,0,0,.4)}dialog::backdrop{background:rgba(0,0,0,.68)}' +
      '.review-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.review-head h2{margin:0}.review-muted,.review-confidence{color:var(--secondary-text-color);font-size:.9rem}.review-docs{display:grid;gap:16px;margin:18px 0}.review-doc{border:1px solid var(--divider-color);border-radius:10px;overflow:hidden}.review-doc-head{display:flex;justify-content:space-between;gap:12px;padding:10px 12px}.review-doc-head strong{overflow-wrap:anywhere}.review-doc a{color:var(--primary-color);white-space:nowrap}.review-doc-text{white-space:pre-wrap;overflow-wrap:anywhere;max-height:52vh;overflow:auto;margin:0;padding:16px;border-top:1px solid var(--divider-color);font:inherit;line-height:1.5;color:var(--primary-text-color)}.review-doc-unavailable{padding:4px 12px 12px}.review-analysis{border:1px solid var(--divider-color);border-radius:10px;padding:16px;margin-top:20px}.review-analysis h3{margin:0 0 10px}.review-analysis h4{margin-bottom:6px}.review-analysis li{margin:7px 0}.review-analysis label{display:block;font-size:.85rem;color:var(--secondary-text-color);margin:10px 0}.review-analysis input,.review-analysis textarea{display:block;width:100%;box-sizing:border-box;margin-top:5px;padding:10px;border:1px solid var(--divider-color);border-radius:8px;background:var(--secondary-background-color);color:var(--primary-text-color);font:inherit}.review-actions{display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap;margin-top:16px}.review-actions button,.review-analysis button{padding:9px 12px;border-radius:8px;border:1px solid var(--divider-color);background:var(--secondary-background-color);color:var(--primary-text-color);font:inherit}.review-actions .primary{background:var(--primary-color);color:var(--text-primary-color,#fff)}' +
      '</style><div class="review-head"><div><p class="eyebrow">TASK REVIEW</p><h2 id="review-title">' + this._escape(task.title || "Untitled task") + '</h2></div><button type="button" data-review-close aria-label="Close">Close</button></div>' +
      '<p class="review-muted">Review the source email and any verified Paperless documents, then check the local AI suggestions below.</p>' + sourceMarkup + '<div class="review-docs">' + documents + '</div>' + emailopsMarkup + result +
      '<div class="review-actions"><span class="review-muted" aria-live="polite">' + this._escape(busyText) + '</span>' +
      '<button type="button" data-review-refresh' + (reviewPending ? ' disabled' : '') + '>' + (reviewPending ? 'Analysis running…' : (review ? 'Refresh analysis' : 'Analyze task')) + '</button><button type="button" data-review-close>Close</button></div>';
  }

  _bindReviewDialog(dialog, taskId) {
    dialog.querySelectorAll("[data-review-close]").forEach((button) => button.addEventListener("click", () => dialog.close()));
    const refresh = dialog.querySelector("[data-review-refresh]");
    if (refresh) refresh.addEventListener("click", () => this._requestTaskReview(dialog, taskId));
    const copy = dialog.querySelector("[data-review-copy]");
    if (copy) copy.addEventListener("click", async () => {
      const body = dialog.querySelector(".review-analysis textarea")?.value || "";
      try { await navigator.clipboard.writeText(body); copy.textContent = "Copied"; }
      catch (_) { window.alert("Could not copy the response. You can select the draft text and copy it manually."); }
    });
  }

  async _requestTaskReview(dialog, taskId) {
    const task = this._items().find((x) => x.id === taskId);
    if (!task) return;
    const alreadyPending = this._reviewPendingTaskIds.has(String(taskId));
    const refresh = dialog.querySelector("[data-review-refresh]");
    const priorGeneratedAt = Number(task.ai_review?.generated_at || 0);
    if (refresh) refresh.disabled = true;
    try {
      if (!alreadyPending) {
        await this._hass.callService("shell_command", "lifeos_pa_user_action", {
          action: "review", task_id: taskId, note: "", until: "", severity: "", due_date: "", paperless_ids: "",
        });
      }
      this._reviewPendingTaskIds.add(String(taskId));
      dialog._reviewBusyText = "Preparing private document text and local analysis…";
      dialog.innerHTML = this._reviewDialogMarkup(task, dialog._reviewBusyText, dialog._reviewPreviews || []);
      this._bindReviewDialog(dialog, taskId);
      let attempts = 0;
      const poll = async () => {
        if (!dialog.open) return;
        if (attempts++ >= 60) {
          this._reviewPendingTaskIds.delete(String(taskId));
          dialog._reviewBusyText = "Local analysis has not finished after 10 minutes. It may still be queued; close and reopen this task to check or retry.";
          const latest = this._items().find((x) => x.id === taskId) || task;
          dialog.innerHTML = this._reviewDialogMarkup(latest, dialog._reviewBusyText, dialog._reviewPreviews || []);
          this._bindReviewDialog(dialog, taskId);
          return;
        }
        await this._hass.callService("homeassistant", "update_entity", { entity_id: this._entity() }).catch(() => {});
        await this._loadReviewPreviews(dialog, taskId);
        await new Promise((resolve) => window.setTimeout(resolve, 10000));
        const latest = this._items().find((x) => x.id === taskId);
        if (!latest) return;
        if (latest.ai_review && Number(latest.ai_review.generated_at || 0) > priorGeneratedAt) {
          this._reviewPendingTaskIds.delete(String(taskId));
          dialog._reviewBusyText = "";
          dialog.innerHTML = this._reviewDialogMarkup(latest, "", dialog._reviewPreviews || []);
          this._bindReviewDialog(dialog, taskId);
          return;
        }
        const latestAttrs = this._hass.states[this._entity()]?.attributes || {};
        const pendingIds = new Set((latestAttrs.review_pending_task_ids || []).map(String));
        const failedIds = new Set((latestAttrs.review_failed_task_ids || []).map(String));
        if (pendingIds.has(String(taskId))) this._reviewPendingTaskIds.add(String(taskId));
        else this._reviewPendingTaskIds.delete(String(taskId));
        if (failedIds.has(String(taskId)) && !pendingIds.has(String(taskId))) {
          this._reviewPendingTaskIds.delete(String(taskId));
          dialog._reviewBusyText = "Local analysis failed. The document text remains available below; you can retry the analysis.";
          dialog.innerHTML = this._reviewDialogMarkup(latest, dialog._reviewBusyText, dialog._reviewPreviews || []);
          this._bindReviewDialog(dialog, taskId);
          return;
        }
        dialog._reviewBusyText = "Analysis is still running locally…";
        const status = dialog.querySelector("[aria-live]");
        if (status) status.textContent = dialog._reviewBusyText;
        poll();
      };
      poll();
    } catch (_) {
      window.alert("LifeOS could not queue the local task analysis.");
      if (refresh) refresh.disabled = false;
    }
  }

  _showTaskReview(task) {
    const dialog = document.createElement("dialog");
    dialog.setAttribute("aria-labelledby", "review-title");
    dialog._reviewBusyText = "Loading the private document text preview…";
    dialog.innerHTML = this._reviewDialogMarkup(task, dialog._reviewBusyText);
    this.shadowRoot.append(dialog);
    this._activeReviewDialog = dialog;
    dialog.addEventListener("close", () => {
      this._hass.callApi("DELETE", "lifeos_pa_review/" + encodeURIComponent(String(task.id))).catch(() => {});
      dialog.remove();
      this._activeReviewDialog = null;
      this._render();
    });
    this._bindReviewDialog(dialog, String(task.id));
    dialog.showModal();
    this._loadEmailOpsShadow(dialog, String(task.id));
    this._loadReviewPreviews(dialog, String(task.id)).then((loaded) => {
      if (!dialog.open) return;
      if (!loaded || !task.ai_review) this._requestTaskReview(dialog, String(task.id));
    });
  }

  async _loadReviewPreviews(dialog, taskId) {
    try {
      const payload = await this._hass.callApi("GET", "lifeos_pa_review/" + encodeURIComponent(taskId));
      if (!dialog.open || payload?.schema !== "lifeos_pa_task_previews_v1" || payload.task_id !== taskId || !Array.isArray(payload.documents)) return false;
      if (JSON.stringify(payload.documents) === JSON.stringify(dialog._reviewPreviews || null)) return true;
      dialog._reviewPreviews = payload.documents;
      const latest = this._items().find((x) => x.id === taskId);
      if (latest) {
        dialog.innerHTML = this._reviewDialogMarkup(latest, dialog._reviewBusyText || "", dialog._reviewPreviews);
        this._bindReviewDialog(dialog, taskId);
      }
      return true;
    } catch (_) {
      return false;
    }
  }

  async _loadEmailOpsShadow(dialog, taskId) {
    try {
      const payload = await this._hass.callApi("GET", "lifeos_emailops_shadow/" + encodeURIComponent(taskId));
      if (!dialog.open || payload?.schema !== "lifeos_emailops_shadow_task_v1" || payload.task_id !== taskId || payload.mode !== "shadow") return;
      if (!this._emailopsReports) this._emailopsReports = new Map();
      this._emailopsReports.set(taskId, payload);
      const task = this._items().find((x) => x.id === taskId);
      if (task) {
        dialog.innerHTML = this._reviewDialogMarkup(task, dialog._reviewBusyText || "", dialog._reviewPreviews || []);
        this._bindReviewDialog(dialog, taskId);
      }
    } catch (_) { /* A task without a shadow sample keeps its normal review. */ }
  }


  async _showEmailSamples() {
    const dialog = document.createElement("dialog");
    dialog.setAttribute("aria-label", "Email suggestion review");
    dialog.innerHTML = '<p>Loading private samples…</p><button type="button">Close</button>';
    dialog.querySelector("button").onclick = () => dialog.close();
    this.shadowRoot.append(dialog);
    this._activeReviewDialog = dialog;
    dialog.addEventListener("close", () => { dialog.remove(); this._activeReviewDialog = null; this._render(); });
    dialog.showModal();
    try {
      const payload = await this._hass.callApi("GET", "lifeos_emailops_samples");
      if (!dialog.open) return;
      if (payload?.schema !== "lifeos_emailops_samples_v1" || !Array.isArray(payload.samples)) throw new Error();
      dialog.innerHTML = '<h2>Email suggestion review</h2><p>Comparison only. No task or mailbox changes.</p><p>Sampled ' +
        this._escape(new Date(payload.generated_at * 1000).toLocaleString()) + '</p>' +
        payload.samples.map((sample, i) => {
          const query = encodeURIComponent("rfc822msgid:" + String(sample.source_message_id).replace(/[<>]/g, ""));
          return '<section><h3>Sample ' + (i + 1) + (sample.matched ? ' · Existing task source' : ' · Not linked to a task') +
            '</h3><a target="_blank" rel="noopener noreferrer" href="https://mail.google.com/mail/u/0/#search/' + query +
            '">Open source email</a><p>' + this._escape(sample.summary || "No summary provided.") +
            '</p><h4>Suggested obligations</h4>' + (sample.proposals.length ? '<ul>' + sample.proposals.map(p =>
              '<li>' + this._escape(p.title) + (p.due_date ? ' · ' + this._escape(p.due_date) : '') + '</li>').join('') +
              '</ul>' : '<p>No obligation suggested.</p>') + '<p>Completion not assessed.</p></section>';
        }).join('') + '<button type="button" data-samples-close>Close</button>';
      dialog.querySelector("[data-samples-close]").onclick = () => dialog.close();
    } catch (_) {
      if (dialog.open) dialog.querySelector("p").textContent = "No current sample is available. Existing tasks are unchanged.";
    }
  }

  async _act(button) {
    let action = button.dataset.action;
    const taskId = button.dataset.id;
    const task = this._items().find((x) => x.id === taskId);
    if (!task) return;
    const label = task.title || taskId;
    const data = { action, task_id: taskId, note: "", until: "", severity: "", due_date: "" };
    if (action.startsWith("signin_")) {
      data.note = button.dataset.event || "";
      if (!/^[a-f0-9]{64}$/.test(data.note)) return;
    } else if (["reopen","dismiss"].includes(action) && task.confirmation_required) {
      // The labelled answer is the explicit user decision; no whole-source inference.
    } else if (action === "review") {
      this._showTaskReview(task);
      return;
    } else if (action === "junk") {
      const selected = await this._chooseJunkDocuments(task);
      if (!selected) return;
      data.paperless_ids = selected.join(",");
    } else if (action === "comment") {
      data.note = window.prompt("Add a note to " + label + ":") || "";
      if (!data.note.trim()) return;
      if (!window.confirm("Add this user note to the obligation?")) return;
    } else if (action === "snooze") {
      data.until = window.prompt("Snooze until (YYYY-MM-DD):", this._datePlusOne()) || "";
      if (!/^\d{4}-\d{2}-\d{2}$/.test(data.until)) return;
      if (!window.confirm("Snooze " + label + " until " + data.until + "?")) return;
    } else if (action === "severity") {
      data.severity = window.prompt("Set severity: low, normal, or high:", task.severity || "normal") || "";
      if (!["low", "normal", "high"].includes(data.severity.toLowerCase())) return;
      data.severity = data.severity.toLowerCase();
      if (!window.confirm("Override severity for " + label + " to " + data.severity + "?")) return;
    } else if (action === "due_date") {
      data.due_date = window.prompt("Set due date (YYYY-MM-DD):", task.due_date || "") || "";
      if (!/^\d{4}-\d{2}-\d{2}$/.test(data.due_date)) return;
      if (!window.confirm("Override due date for " + label + " to " + data.due_date + "?")) return;
    } else if (action !== "junk" && !window.confirm(action === "close" ? "Mark " + label + " complete?" :
      action === "dismiss" ? "Dismiss " + label + " as not a task?" :
      action === "reopen" ? (task.obligation_suppressed ? "Track this as your own task?" : "Reopen " + label + "?") : "Unsnooze " + label + "?")) return;

    button.disabled = true;
    try {
      await this._hass.callService("shell_command", "lifeos_pa_user_action", data);
      if (action === "junk") {
        window.alert("Junk request queued. The matter will close after the email and selected Paperless documents are verified.");
      }
      await this._hass.callService("homeassistant", "update_entity", { entity_id: this._entity() });
    } catch (error) {
      window.alert("LifeOS could not verify this action. The task view has not been confirmed updated.");
    } finally {
      button.disabled = false;
    }
  }
}

customElements.define("lifeos-pa-task-card", LifeOSPATaskCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "lifeos-pa-task-card",
  name: "LifeOS PA Tasks",
  description: "Source-backed matters, questions and daily actions",
});
