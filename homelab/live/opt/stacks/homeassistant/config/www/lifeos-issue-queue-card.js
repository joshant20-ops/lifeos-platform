class LifeOSIssueQueueCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() { return 6; }

  _queueState() {
    if (!this._hass) return null;
    const configured = this._config.entity;
    if (configured && this._hass.states[configured]) return this._hass.states[configured];
    return Object.values(this._hass.states).find((s) =>
      s.attributes && Array.isArray(s.attributes.issues) &&
      (s.attributes.friendly_name === "LifeOS Open Jobs" || s.entity_id.includes("lifeos_open_jobs"))
    ) || null;
  }

  _switchEntity(number) {
    const exact = `switch.lifeos_issue_queue_${number}_high_priority`;
    if (this._hass.states[exact]) return exact;
    const suffix = `${number}_high_priority`;
    const found = Object.keys(this._hass.states).find((id) =>
      id.startsWith("switch.") && id.includes("lifeos_issue_queue") && id.endsWith(suffix)
    );
    return found || null;
  }

  _escape(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  _render() {
    if (!this.shadowRoot || !this._hass) return;
    const state = this._queueState();
    const issues = state?.attributes?.issues || [];
    const highCount = state?.attributes?.high_priority_count || 0;

    const rows = issues.map((issue) => {
      const number = Number(issue.number);
      const switchId = this._switchEntity(number);
      const switchState = switchId ? this._hass.states[switchId]?.state : null;
      const checked = switchState === "on" || issue.high_priority === true;
      const disabled = !switchId;
      const detail = issue.detail ? `<div class="detail">${this._escape(issue.detail)}</div>` : "";
      const statusClass = String(issue.status || "ready").toLowerCase().replace(/[^a-z0-9_-]/g, "-");
      return `
        <div class="row ${checked ? "manual-high" : ""}">
          <label class="check" title="Manually place this issue in the high-priority pool">
            <input type="checkbox" data-issue="${number}" data-switch="${this._escape(switchId || "")}" ${checked ? "checked" : ""} ${disabled ? "disabled" : ""}>
            <span>High</span>
          </label>
          <div class="priority">P${this._escape(issue.priority)}</div>
          <div class="body">
            <div class="titleline">
              <a href="${this._escape(issue.url)}" target="_blank" rel="noopener noreferrer">#${number} ${this._escape(issue.title)}</a>
              <span class="status ${statusClass}">${this._escape(issue.status)}</span>
            </div>
            <div class="meta">${this._escape(issue.stage || "")}</div>
            ${detail}
          </div>
        </div>`;
    }).join("");

    this.shadowRoot.innerHTML = `
      <style>
        :host { display:block; }
        ha-card { padding: 16px; }
        .header { display:flex; align-items:baseline; justify-content:space-between; gap:12px; margin-bottom:12px; }
        .header h2 { margin:0; font-size:1.25rem; }
        .summary { color:var(--secondary-text-color); font-size:.9rem; }
        .list { display:flex; flex-direction:column; gap:8px; }
        .row { display:grid; grid-template-columns:76px 42px minmax(0,1fr); gap:10px; align-items:start; padding:10px; border:1px solid var(--divider-color); border-radius:10px; }
        .row.manual-high { border-color:var(--warning-color, #ff9800); }
        .check { display:flex; align-items:center; gap:5px; font-size:.85rem; cursor:pointer; user-select:none; }
        .check input { width:18px; height:18px; cursor:pointer; }
        .priority { font-weight:700; text-align:center; padding:3px 6px; border-radius:8px; background:var(--secondary-background-color); }
        .body { min-width:0; }
        .titleline { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
        a { color:var(--primary-text-color); font-weight:600; text-decoration:none; }
        a:hover { text-decoration:underline; }
        .status { font-size:.72rem; font-weight:700; padding:2px 7px; border-radius:999px; background:var(--secondary-background-color); }
        .status.running { background:rgba(3,169,244,.18); }
        .status.blocked, .status.cooldown { background:rgba(255,152,0,.18); }
        .status.ready { background:rgba(76,175,80,.18); }
        .meta, .detail { color:var(--secondary-text-color); font-size:.82rem; margin-top:3px; }
        .detail { white-space:normal; overflow-wrap:anywhere; }
        .empty { color:var(--secondary-text-color); padding:10px 0; }
        @media (max-width: 650px) {
          .row { grid-template-columns:68px 38px minmax(0,1fr); gap:6px; padding:8px; }
          .detail { display:none; }
        }
      </style>
      <ha-card>
        <div class="header">
          <h2>${this._escape(this._config.title || "Open Jobs")}</h2>
          <div class="summary">${issues.length} open · ${highCount} manually high priority</div>
        </div>
        <div class="list">${rows || '<div class="empty">No open LifeOS jobs.</div>'}</div>
      </ha-card>`;

    this.shadowRoot.querySelectorAll('input[type="checkbox"][data-switch]').forEach((input) => {
      input.addEventListener("change", async (event) => {
        const entityId = event.target.dataset.switch;
        if (!entityId) return;
        event.target.disabled = true;
        try {
          await this._hass.callService("switch", event.target.checked ? "turn_on" : "turn_off", { entity_id: entityId });
        } finally {
          setTimeout(() => { event.target.disabled = false; }, 700);
        }
      });
    });
  }
}

customElements.define("lifeos-issue-queue-card", LifeOSIssueQueueCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "lifeos-issue-queue-card",
  name: "LifeOS Issue Queue",
  description: "Live LifeOS GitHub issue queue with manual high-priority overrides",
});
