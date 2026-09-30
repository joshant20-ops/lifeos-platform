class LifeOSPATaskCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
  }

  set hass(hass) { this._hass = hass; this._render(); }
  getCardSize() { return 8; }

  _escape(value) {
    return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
  }

  _datePlusOne() {
    const d = new Date(); d.setDate(d.getDate() + 1);
    return d.toISOString().slice(0, 10);
  }

  _entity() { return this._config.entity || "sensor.lifeos_pa_task_attention"; }

  _render() {
    if (!this.shadowRoot || !this._hass) return;
    const sensor = this._hass.states[this._entity()];
    const attrs = sensor?.attributes || {};
    const items = Array.isArray(attrs.items) ? attrs.items : [];
    const rows = items.map((task) => {
      if (!task || !task.id) return "";
      const id = this._escape(task.id);
      const status = String(task.status || "").toUpperCase();
      const closed = status === "DONE" || status === "DISMISSED";
      const evidence = [];
      for (const ref of (task.source_refs || task.source_message_ids || []).slice(0, 3)) {
        const query = encodeURIComponent("rfc822msgid:" + String(ref).replace(/[<>]/g, ""));
        evidence.push('<a target="_blank" rel="noopener noreferrer" href="https://mail.google.com/mail/u/0/#search/' + query + '">Gmail evidence</a>');
      }
      const paperlessBase = String(this._config.paperless_base_url || (window.location.protocol + "//" + window.location.hostname + ":8010")).replace(/\/+$/, "");
      for (const doc of (task.paperless_evidence || []).slice(0, 5)) {
        if (doc && doc.document_id !== undefined) {
          evidence.push('<a target="_blank" rel="noopener noreferrer" href="' + this._escape(paperlessBase + "/documents/" + encodeURIComponent(doc.document_id)) + '">Paperless #' + this._escape(doc.document_id) + '</a>');
        }
      }
      const notes = (task.user_comments || []).slice(-3).map((comment) =>
        '<div class="note"><strong>Your note</strong> · ' + this._escape(comment.text) + '</div>'
      ).join("");
      const due = task.due_date ? " · due " + this._escape(task.due_date) : "";
      const snooze = task.snoozed_until ? " · snoozed until " + this._escape(task.snoozed_until) : "";
      const buttons = closed
        ? '<button data-action="reopen" data-id="' + id + '">Reopen</button>'
        : '<button data-action="comment" data-id="' + id + '">Add comment</button>' +
          '<button data-action="snooze" data-id="' + id + '">Snooze</button>' +
          '<button data-action="close" data-id="' + id + '">✓ Close</button>' +
          '<button data-action="dismiss" data-id="' + id + '">Dismiss</button>';
      const controls = '<div class="controls">' + buttons +
        '<button data-action="severity" data-id="' + id + '">Severity</button>' +
        '<button data-action="due_date" data-id="' + id + '">Due date</button>' +
        (task.snoozed_until ? '<button data-action="unsnooze" data-id="' + id + '">Unsnooze</button>' : '') +
        '</div>';
      return '<article><div class="title">' + this._escape(task.title || "Untitled obligation") + '</div>' +
        '<div class="meta">' + this._escape(status) + ' · ' + this._escape(task.severity || "normal") + due + snooze + '</div>' +
        (evidence.length ? '<div class="evidence">' + evidence.join(" · ") + '</div>' : '<div class="evidence">No linked evidence reference</div>') +
        notes + controls + '</article>';
    }).join("");

    this.shadowRoot.innerHTML = '<style>' +
      ':host{display:block}ha-card{padding:16px}.summary{color:var(--secondary-text-color);margin:4px 0 12px}' +
      '.list{display:grid;gap:10px}article{border:1px solid var(--divider-color);border-radius:10px;padding:12px}' +
      '.title{font-weight:650}.meta,.evidence,.note{font-size:.85rem;color:var(--secondary-text-color);margin-top:5px}' +
      '.evidence a{color:var(--primary-color)}.controls{display:flex;gap:7px;flex-wrap:wrap;margin-top:10px}' +
      'button{border:1px solid var(--divider-color);background:var(--secondary-background-color);color:var(--primary-text-color);border-radius:8px;padding:7px 10px;cursor:pointer}' +
      'button:disabled{opacity:.5}.empty{color:var(--secondary-text-color)}' +
      '</style><ha-card><h2>' + this._escape(this._config.title || "Personal Attention") + '</h2>' +
      '<div class="summary">' + this._escape(attrs.briefing || "Local PA attention is unavailable.") + '</div>' +
      '<div class="list">' + (rows || '<div class="empty">No obligations in the current task view.</div>') + '</div></ha-card>';

    this.shadowRoot.querySelectorAll("button[data-action]").forEach((button) => {
      button.addEventListener("click", () => this._act(button));
    });
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
  description: "Bounded user-owned obligation controls on the existing PA view",
});
