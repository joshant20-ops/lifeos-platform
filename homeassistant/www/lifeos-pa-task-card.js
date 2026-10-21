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

  _startOfWeek(offset = 0) {
    const start = new Date();
    start.setHours(12, 0, 0, 0);
    start.setDate(start.getDate() - ((start.getDay() + 6) % 7) + offset * 7);
    return start;
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

  _dateLabel(date, options) {
    return new Intl.DateTimeFormat(undefined, options).format(date);
  }

  _entity() { return this._config.entity || "sensor.lifeos_pa_task_attention"; }

  _weekStrip(items) {
    const start = this._startOfWeek(this._weekOffset || 0);
    const days = [];
    for (let index = 0; index < 7; index++) {
      const date = new Date(start);
      date.setDate(start.getDate() + index);
      const key = this._dateKey(date);
      const count = items.filter((task) =>
        ["OPEN", "WAITING"].includes(String(task.status || "").toUpperCase()) &&
        !task.snoozed && this._taskDate(task.due_date) === key
      ).length;
      const selected = this._selectedDate === key;
      days.push(
        '<button class="day' + (selected ? " selected" : "") + '" type="button" data-day="' + key +
        '" aria-pressed="' + selected + '" aria-label="' + this._escape(this._dateLabel(date, { weekday: "long", day: "numeric", month: "long" })) +
        ", " + count + (count === 1 ? " task" : " tasks") + '">' +
        '<span class="day-name">' + this._escape(this._dateLabel(date, { weekday: "short" })) + '</span>' +
        '<strong>' + this._escape(this._dateLabel(date, { day: "numeric" })) + '</strong>' +
        '<span class="day-count">' + (count ? count + (count === 1 ? " task" : " tasks") : "—") + '</span>' +
        '</button>'
      );
    }
    const weekLabel = this._dateLabel(start, { day: "numeric", month: "short" }) + " – ";
    const end = new Date(start);
    end.setDate(end.getDate() + 6);
    return '<div class="week-heading"><button class="week-nav" type="button" data-week="-1" aria-label="Previous week">‹</button>' +
      '<strong>' + this._escape(weekLabel + this._dateLabel(end, { day: "numeric", month: "short", year: "numeric" })) + '</strong>' +
      '<button class="week-nav" type="button" data-week="1" aria-label="Next week">›</button></div>' +
      '<div class="week-strip" role="group" aria-label="Tasks due this week">' + days.join("") + '</div>';
  }

  _taskCard(task) {
    const id = this._escape(task.id);
    const status = String(task.status || "OPEN").toUpperCase();
    const severity = String(task.severity || "normal").toLowerCase();
    const due = this._taskDate(task.due_date);
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
      return '<div class="timeline-event"><span>' + this._escape(when || "Earlier") + '</span><strong>' +
        this._escape(event?.title || "Email update") + '</strong>' +
        (event?.event_kind === "information" ? '<em>Information</em>' : "") + '</div>';
    }).join("");
    const latest = timelineEvents[timelineEvents.length - 1];
    const latestPreview = latest
      ? '<div class="activity"><span>Latest update · ' + this._escape(Number(latest.observed_at) > 0 ? new Date(Number(latest.observed_at) * 1000).toLocaleDateString() : "Earlier") +
        '</span><strong>' + this._escape(latest.title || "Email update") + '</strong>' +
        (latest.event_kind === "information" ? '<em>Information only</em>' : "") + '</div>'
      : "";
    const noteMarkup = comments.map((comment) =>
      '<div class="note"><strong>Your note</strong><span>' + this._escape(comment.text || "") + '</span></div>'
    ).join("");
    const supporting = [];
    if (evidence.length) supporting.push('<details><summary>Evidence · ' + evidence.length + '</summary><div class="support-body">' + evidence.join(" · ") + '</div></details>');
    if (timeline) supporting.push('<details><summary>Full timeline · ' + timelineEvents.length + '</summary><div class="support-body timeline">' + timeline + '</div></details>');
    if (noteMarkup) supporting.push('<details><summary>Your notes · ' + (task.user_comment_count || comments.length) + '</summary><div class="support-body">' + noteMarkup + '</div></details>');
    const snooze = task.snoozed_until ? '<span class="tag muted">Snoozed until ' + this._escape(this._formatDate(task.snoozed_until)) + '</span>' : "";
    const dueTag = due ? '<span class="tag ' + (due < this._dateKey(new Date()) ? "overdue" : "") + '">' +
      (due < this._dateKey(new Date()) ? "Overdue · " : "Due · ") + this._escape(this._formatDate(due)) + '</span>' :
      '<span class="tag muted">No due date</span>';
    const statusTag = '<span class="tag status-' + this._escape(status.toLowerCase()) + '">' + this._escape(status === "WAITING" ? "Waiting for reply" : status === "DONE" ? "Completed" : status === "DISMISSED" ? "Dismissed" : "Needs action") + '</span>';
    const buttons = status === "DONE" || status === "DISMISSED"
      ? '<button data-action="reopen" data-id="' + id + '">Reopen</button>'
      : '<button data-action="comment" data-id="' + id + '">Add note</button>' +
        '<button data-action="snooze" data-id="' + id + '">Snooze</button>' +
        '<button data-action="close" data-id="' + id + '">Mark done</button>' +
        '<button data-action="dismiss" data-id="' + id + '">Not a task</button>';
    const controls = '<div class="controls">' + buttons +
      '<button data-action="severity" data-id="' + id + '">Set severity</button>' +
      '<button data-action="due_date" data-id="' + id + '">Set due date</button>' +
      (task.snoozed_until ? '<button data-action="unsnooze" data-id="' + id + '">Unsnooze</button>' : '') +
      '</div>';
    return '<article class="task"><div class="task-top"><h3>' + this._escape(task.title || "Untitled obligation") + '</h3>' +
      '<span class="severity severity-' + this._escape(severity) + '">' + this._escape(severity) + '</span></div>' +
      '<div class="tags">' + statusTag + dueTag + snooze + '</div>' + latestPreview +
      '<div class="source-line">' + sourceRefs.length + (sourceRefs.length === 1 ? " related message" : " related messages") +
      (task.user_comment_count ? " · " + this._escape(task.user_comment_count) + (task.user_comment_count === 1 ? " note" : " notes") : "") +
      '</div>' + supporting.join("") + controls + '</article>';
  }

  _actionSections(items) {
    const groups = [
      ["OPEN", "Needs your action", "Decisions, replies and confirmations that are yours to do."],
      ["WAITING", "Waiting for a reply", "Follow-ups remain visible on the day they are due."],
      ["DONE", "Completed", "Recently completed matters."],
      ["DISMISSED", "Dismissed", "Items you marked as not a task."],
    ];
    const chunks = [];
    for (const [status, title, description] of groups) {
      const matching = items.filter((task) => String(task.status || "").toUpperCase() === status);
      if (!matching.length) continue;
      chunks.push('<section class="group"><div class="group-heading"><h2>' + title + '</h2><span>' +
        matching.length + (matching.length === 1 ? " matter" : " matters") + '</span></div><p>' +
        description + '</p><div class="task-grid">' + matching.map((task) => this._taskCard(task)).join("") + '</div></section>');
    }
    return chunks.join("") || '<div class="empty"><strong>No tasks for this day</strong><span>Choose another date above, or view matters with no due date.</span></div>';
  }

  _render() {
    if (!this.shadowRoot || !this._hass) return;
    const sensor = this._hass.states[this._entity()];
    const attrs = sensor?.attributes || {};
    const items = Array.isArray(attrs.items) ? attrs.items.filter((x) => x && x.id) : [];
    if (!this._selectedDate) this._selectedDate = this._dateKey(new Date());
    const needs = Number(attrs.needs_me || 0);
    const waiting = Number(attrs.waiting_on_others || 0);
    const overdue = Number(attrs.overdue || 0);
    const style = [
      ':host{display:block;color:var(--primary-text-color)}ha-card{padding:16px}',
      '.summary{color:var(--secondary-text-color);margin:4px 0 12px;line-height:1.45}',
      '.count-row{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}',
      '.count{border-radius:9px;padding:9px 12px;background:var(--secondary-background-color);min-width:90px}',
      '.count strong{display:block;font-size:1.15rem;color:var(--primary-text-color)}.count span{font-size:.78rem;color:var(--secondary-text-color)}',
      '.open-link{display:inline-flex;align-items:center;margin-top:4px;color:var(--primary-color);font-weight:600;text-decoration:none}',
      '.page-head{display:flex;justify-content:space-between;gap:14px;align-items:flex-start;margin-bottom:14px}',
      '.page-head h1{font-size:1.45rem;line-height:1.2;margin:2px 0 5px;font-weight:650}',
      '.page-head p,.group>p{color:var(--secondary-text-color);font-size:.88rem;margin:0;line-height:1.4}',
      '.page-kicker{font-size:.72rem;text-transform:uppercase;letter-spacing:.08em;color:var(--primary-color);font-weight:650}',
      '.week-heading{display:flex;align-items:center;justify-content:center;gap:10px;margin:18px 0 9px}',
      '.week-heading strong{font-size:.9rem;font-weight:600}',
      '.week-nav{width:36px;height:36px;border:1px solid var(--divider-color);border-radius:9px;background:var(--card-background-color);color:var(--primary-text-color);font-size:1.25rem}',
      '.week-strip{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:6px;margin-bottom:16px}',
      '.day{min-width:0;min-height:62px;padding:7px 3px;border:1px solid var(--divider-color);border-radius:9px;background:var(--card-background-color);color:var(--primary-text-color);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px}',
      '.day.selected{border-color:var(--primary-color);background:var(--secondary-background-color);box-shadow:inset 0 0 0 1px var(--primary-color)}',
      '.day-name,.day-count{font-size:.67rem;color:var(--secondary-text-color);white-space:nowrap}.day strong{font-size:.95rem;line-height:1.05}.day.selected .day-name,.day.selected .day-count{color:var(--primary-color)}',
      '.no-date-row{display:flex;justify-content:center;margin:0 0 18px}',
      '.no-date{border:0;background:transparent;color:var(--primary-color);font:inherit;font-size:.82rem;text-decoration:underline;text-underline-offset:3px;padding:7px 10px}',
      '.no-date.selected{font-weight:650}',
      '.task-summary{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 14px}',
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
      'details{margin-top:8px;font-size:.78rem}summary{cursor:pointer;color:var(--primary-color);padding:3px 0}.support-body{margin:6px 0 3px;color:var(--secondary-text-color);line-height:1.5;overflow-wrap:anywhere}.support-body a{color:var(--primary-color)}',
      '.timeline-event{padding:5px 0;border-left:1px solid var(--divider-color);padding-left:9px;margin-left:3px;display:flex;flex-direction:column;gap:2px}.timeline-event span{font-size:.68rem}.timeline-event strong{font-size:.78rem;color:var(--primary-text-color);font-weight:500}.timeline-event em{font-size:.68rem;font-style:normal}',
      '.note{margin:6px 0}.note strong{display:block;color:var(--primary-text-color);font-weight:550}.note span{overflow-wrap:anywhere}',
      '.controls{display:flex;gap:6px;flex-wrap:wrap;margin-top:11px}.controls button{min-height:36px;border:1px solid var(--divider-color);background:var(--secondary-background-color);color:var(--primary-text-color);border-radius:8px;padding:6px 9px;font:inherit;font-size:.76rem}',
      '.controls button[data-action="close"]{background:var(--primary-color);border-color:var(--primary-color);color:var(--text-primary-color,#fff);font-weight:600}',
      'button{cursor:pointer}button:focus-visible,a:focus-visible{outline:2px solid var(--primary-color);outline-offset:2px}.empty{border:1px dashed var(--divider-color);border-radius:12px;padding:24px 16px;text-align:center;display:flex;flex-direction:column;gap:5px}.empty span{font-size:.82rem;color:var(--secondary-text-color)}',
      '@media(max-width:500px){ha-card{padding:12px}.page-head h1{font-size:1.25rem}.day{min-height:58px}.day-name,.day-count{font-size:.61rem}.task-grid{grid-template-columns:1fr}.count{flex:1;min-width:80px}}'
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
    const shownItems = items.filter((task) => {
      const due = this._taskDate(task.due_date);
      return this._selectedDate === "no-date" ? !due : due === this._selectedDate;
    });
    const selectedDateLabel = this._selectedDate === "no-date"
      ? "No due date"
      : this._formatDate(this._selectedDate, { weekday: "long", day: "numeric", month: "long" });
    this.shadowRoot.innerHTML = '<style>' + style + '</style><ha-card>' +
      '<div class="page-head"><div><div class="page-kicker">LifeOS · Personal Assistant</div><h1>' +
      this._escape(this._config.title || "Your matters") + '</h1><p>One view for what needs doing, what is waiting, and what happens next.</p></div>' +
      '</div><div class="count-row"><div class="count"><strong>' + needs + '</strong><span>Need your action</span></div>' +
      '<div class="count"><strong>' + waiting + '</strong><span>Waiting for a reply</span></div>' +
      '<div class="count"><strong>' + overdue + '</strong><span>Overdue</span></div></div>' +
      this._weekStrip(items) +
      '<div class="no-date-row"><button class="no-date' + (this._selectedDate === "no-date" ? " selected" : "") +
      '" type="button" data-day="no-date" aria-pressed="' + (this._selectedDate === "no-date") + '">' +
      "Show matters with no due date" + '</button></div>' +
      '<div class="task-summary"><span class="summary-chip">Showing ' + this._escape(selectedDateLabel) + '</span>' +
      '<span class="summary-chip">' + shownItems.length + (shownItems.length === 1 ? " matter" : " matters") + '</span>' +
      (overdue ? '<span class="summary-chip urgent">' + overdue + (overdue === 1 ? " overdue" : " overdue") + '</span>' : "") +
      '</div>' + this._actionSections(shownItems) + '</ha-card>';
    this.shadowRoot.querySelectorAll("button[data-day]").forEach((button) => {
      button.addEventListener("click", () => {
        this._selectedDate = button.dataset.day;
        this._render();
      });
    });
    this.shadowRoot.querySelectorAll("button[data-week]").forEach((button) => {
      button.addEventListener("click", () => {
        this._weekOffset = (this._weekOffset || 0) + Number(button.dataset.week);
        this._selectedDate = this._dateKey(this._startOfWeek(this._weekOffset));
        this._render();
      });
    });
    this.shadowRoot.querySelectorAll("button[data-action]").forEach((button) => {
      button.addEventListener("click", () => this._act(button));
    });
  }

  _datePlusOne() {
    const date = new Date();
    date.setDate(date.getDate() + 1);
    return this._dateKey(date);
  }

  async _act(button) {
    const action = button.dataset.action;
    const taskId = button.dataset.id;
    const task = (this._hass.states[this._entity()]?.attributes?.items || []).find((x) => x.id === taskId);
    if (!task) return;
    const label = task.title || taskId;
    const data = { action, task_id: taskId, note: "", until: "", severity: "", due_date: "" };
    if (action === "comment") {
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
    } else if (!window.confirm(action === "close" ? "Mark " + label + " complete?" :
      action === "dismiss" ? "Dismiss " + label + " as not a task?" :
      action === "reopen" ? "Reopen " + label + "?" : "Unsnooze " + label + "?")) return;

    button.disabled = true;
    try {
      await this._hass.callService("shell_command", "lifeos_pa_user_action", data);
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
  description: "Grouped personal assistant tasks with weekly due-date navigation",
});
