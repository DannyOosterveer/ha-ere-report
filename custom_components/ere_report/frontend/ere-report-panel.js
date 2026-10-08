// Sidebar panel: list ERE reports, download them and create new ones.

const STRINGS = {
  nl: {
    title: "ERE-rapporten",
    create: "Rapport maken",
    creating: "Bezig…",
    quarter: "Kwartaal",
    running: "loopt nog",
    created: "Rapport {period} gemaakt: {kwh} kWh, {sessions} sessies.",
    failed: "Mislukt: {error}",
    reports: "Rapporten",
    period: "Periode",
    charger: "Laadpunt",
    generated: "Aangemaakt",
    sessions: "Sessies",
    files: "Bestanden",
    provisional: "voorlopig",
    none: "Nog geen rapporten. Kies een kwartaal en klik op Rapport maken.",
    noChargers: "Nog geen laadpunt ingesteld. Voeg de integratie ERE Charging Report toe.",
    loadError: "Kon de rapporten niet laden: {error}",
    lastReport: "Laatste rapport: {period}, {when}",
    delete: "Verwijderen",
    confirmDelete:
      "Rapport {period} van {charger} verwijderen? Het xlsx- en csv-bestand worden definitief verwijderd.",
    deleteFailed: "Verwijderen mislukt: {error}",
  },
  en: {
    title: "ERE reports",
    create: "Create report",
    creating: "Working…",
    quarter: "Quarter",
    running: "in progress",
    created: "Created the {period} report: {kwh} kWh, {sessions} sessions.",
    failed: "Failed: {error}",
    reports: "Reports",
    period: "Period",
    charger: "Charge point",
    generated: "Created",
    sessions: "Sessions",
    files: "Files",
    provisional: "provisional",
    none: "No reports yet. Pick a quarter and click Create report.",
    noChargers: "No charge point set up yet. Add the ERE Charging Report integration.",
    loadError: "Could not load the reports: {error}",
    lastReport: "Last report: {period}, {when}",
    delete: "Delete",
    confirmDelete:
      "Delete the {period} report for {charger}? The xlsx and csv files are deleted permanently.",
    deleteFailed: "Could not delete: {error}",
  },
};

const escapeHtml = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]
  );

const format = (template, values) =>
  template.replace(/\{(\w+)\}/g, (_, key) => values[key] ?? "");

class EreReportPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._data = null;
    this._loadError = null;
    this._status = {};
    this.shadowRoot.addEventListener("click", (ev) => this._onClick(ev));
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) {
      this._render();
      this._load();
    }
    this._syncMenuButton();
  }

  set narrow(narrow) {
    this._narrow = narrow;
    this._syncMenuButton();
  }

  get _lang() {
    return (this._hass?.language || "en").startsWith("nl") ? "nl" : "en";
  }

  get _t() {
    return STRINGS[this._lang];
  }

  _number(value, digits = 2) {
    if (value === null || value === undefined) return "–";
    return Number(value).toLocaleString(this._lang, {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  }

  _date(iso) {
    return new Date(iso).toLocaleString(this._lang, {
      dateStyle: "medium",
      timeStyle: "short",
    });
  }

  _quarters() {
    // The current quarter plus the eight before it, newest first.
    const now = new Date();
    let year = now.getFullYear();
    let quarter = Math.floor(now.getMonth() / 3) + 1;
    const list = [];
    for (let i = 0; i < 9; i++) {
      list.push({ year, quarter, running: i === 0 });
      quarter -= 1;
      if (quarter === 0) {
        quarter = 4;
        year -= 1;
      }
    }
    return list;
  }

  async _load() {
    try {
      this._data = await this._hass.callWS({ type: "ere_report/reports" });
      this._loadError = null;
    } catch (err) {
      this._loadError = err.message || String(err);
    }
    this._render();
  }

  async _generate(entryId) {
    const select = this.shadowRoot.querySelector(`select[data-entry="${entryId}"]`);
    const [year, quarter] = select.value.split("-").map(Number);
    this._status[entryId] = { busy: true };
    this._render();
    try {
      const result = await this._hass.callWS({
        type: "call_service",
        domain: "ere_report",
        service: "generate_report",
        service_data: { config_entry_id: entryId, year, quarter },
        return_response: true,
      });
      const r = result.response;
      this._status[entryId] = {
        ok: format(this._t.created, {
          period: `Q${r.quarter} ${r.year}`,
          kwh: this._number(r.total_kwh),
          sessions: r.sessions,
        }),
        notes: r.notes || [],
        selected: select.value,
      };
    } catch (err) {
      this._status[entryId] = {
        error: format(this._t.failed, { error: err.message || String(err) }),
        selected: select.value,
      };
    }
    await this._load();
  }

  async _download(name) {
    const { path } = await this._hass.callWS({
      type: "auth/sign_path",
      path: `/api/ere_report/${name}`,
      expires: 60,
    });
    const link = document.createElement("a");
    link.href = this._hass.hassUrl(path);
    link.download = name;
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  async _delete(stem) {
    const report = this._data.reports.find((r) => r.stem === stem);
    const question = format(this._t.confirmDelete, {
      period: `Q${report.quarter} ${report.year}`,
      charger: report.charger,
    });
    if (!window.confirm(question)) return;
    try {
      await this._hass.callWS({ type: "ere_report/delete", stem });
      this._deleteError = null;
    } catch (err) {
      this._deleteError = format(this._t.deleteFailed, { error: err.message || String(err) });
    }
    await this._load();
  }

  _onClick(ev) {
    const target = ev.target.closest("[data-action]");
    if (!target) return;
    if (target.dataset.action === "generate") this._generate(target.dataset.entry);
    if (target.dataset.action === "download") this._download(target.dataset.file);
    if (target.dataset.action === "delete") this._delete(target.dataset.stem);
  }

  _syncMenuButton() {
    const button = this.shadowRoot.querySelector("ha-menu-button");
    if (button && this._hass) {
      button.hass = this._hass;
      button.narrow = this._narrow;
    }
  }

  _renderCharger(charger) {
    const t = this._t;
    const status = this._status[charger.entry_id] || {};
    const last = (this._data.reports || []).find((r) => r.entry_id === charger.entry_id);
    const lastLine = last
      ? `<p class="secondary">${escapeHtml(
          format(t.lastReport, {
            period: `Q${last.quarter} ${last.year}`,
            when: this._date(last.generated),
          })
        )}</p>`
      : "";
    const previous = this._quarters()[1];
    const selected = status.selected || `${previous.year}-${previous.quarter}`;
    const options = this._quarters()
      .map((q) => {
        const value = `${q.year}-${q.quarter}`;
        const label = `Q${q.quarter} ${q.year}${q.running ? ` (${t.running})` : ""}`;
        return `<option value="${value}" ${value === selected ? "selected" : ""}>${escapeHtml(label)}</option>`;
      })
      .join("");
    let result = "";
    if (status.ok) {
      const notes = status.notes.length
        ? `<ul>${status.notes.map((n) => `<li>${escapeHtml(n)}</li>`).join("")}</ul>`
        : "";
      result = `<div class="result ok">${escapeHtml(status.ok)}${notes}</div>`;
    } else if (status.error) {
      result = `<div class="result error">${escapeHtml(status.error)}</div>`;
    }
    return `
      <ha-card>
        <div class="card-content">
          <h2>${escapeHtml(charger.title)}</h2>
          ${lastLine}
          <div class="row">
            <label>${t.quarter}
              <select data-entry="${escapeHtml(charger.entry_id)}" ${status.busy ? "disabled" : ""}>${options}</select>
            </label>
            <button class="primary" data-action="generate" data-entry="${escapeHtml(charger.entry_id)}" ${status.busy ? "disabled" : ""}>
              ${status.busy ? t.creating : t.create}
            </button>
          </div>
          ${result}
        </div>
      </ha-card>`;
  }

  _renderReports() {
    const t = this._t;
    const reports = this._data.reports || [];
    if (!reports.length) {
      return `<ha-card><div class="card-content"><p class="secondary">${t.none}</p></div></ha-card>`;
    }
    const rows = reports
      .map((r) => {
        const provisional = r.complete === false ? ` <span class="tag">${t.provisional}</span>` : "";
        const buttons = r.files
          .map(
            (ext) =>
              `<button data-action="download" data-file="${escapeHtml(`${r.stem}.${ext}`)}">${ext}</button>`
          )
          .join(" ");
        const remove = `<button class="delete" data-action="delete" data-stem="${escapeHtml(r.stem)}" title="${t.delete}" aria-label="${t.delete}">${t.delete}</button>`;
        return `
          <tr>
            <td class="period">Q${r.quarter} ${r.year}${provisional}</td>
            <td>${escapeHtml(r.charger)}</td>
            <td>${escapeHtml(this._date(r.generated))}</td>
            <td class="num" data-label="kWh">${this._number(r.total_kwh)}</td>
            <td class="num" data-label="${escapeHtml(t.sessions)}">${r.sessions ?? "–"}</td>
            <td class="files">${buttons} ${remove}</td>
          </tr>`;
      })
      .join("");
    return `
      <ha-card>
        <div class="card-content">
          <h2>${t.reports}</h2>
          ${this._deleteError ? `<div class="result error">${escapeHtml(this._deleteError)}</div>` : ""}
          <div class="table">
            <table>
              <thead>
                <tr>
                  <th>${t.period}</th><th>${t.charger}</th><th>${t.generated}</th>
                  <th class="num">kWh</th><th class="num">${t.sessions}</th><th>${t.files}</th>
                </tr>
              </thead>
              <tbody>${rows}</tbody>
            </table>
          </div>
        </div>
      </ha-card>`;
  }

  _render() {
    const t = this._t;
    let body;
    if (this._loadError) {
      body = `<ha-card><div class="card-content result error">${escapeHtml(
        format(t.loadError, { error: this._loadError })
      )}</div></ha-card>`;
    } else if (!this._data) {
      body = "";
    } else if (!this._data.chargers.length) {
      body = `<ha-card><div class="card-content"><p class="secondary">${t.noChargers}</p></div></ha-card>`;
    } else {
      body = this._data.chargers.map((c) => this._renderCharger(c)).join("") + this._renderReports();
    }
    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; min-height: 100vh; background: var(--primary-background-color); color: var(--primary-text-color); }
        header { display: flex; align-items: center; gap: 8px; height: 56px; padding: 0 12px;
          background: var(--app-header-background-color, var(--primary-color));
          color: var(--app-header-text-color, var(--text-primary-color)); }
        header h1 { font-size: 20px; font-weight: 400; margin: 0; }
        main { max-width: 960px; margin: 0 auto; padding: 16px; display: grid; gap: 16px; }
        h2 { font-size: 18px; font-weight: 500; margin: 0 0 4px; }
        .secondary { color: var(--secondary-text-color); margin: 0 0 12px; }
        .row { display: flex; flex-wrap: wrap; align-items: end; gap: 12px; }
        label { display: grid; gap: 4px; font-size: 14px; color: var(--secondary-text-color); }
        select, button { font: inherit; border-radius: 8px; padding: 8px 12px;
          border: 1px solid var(--divider-color); background: var(--card-background-color); color: var(--primary-text-color); }
        button { cursor: pointer; }
        button.primary { background: var(--primary-color); color: var(--text-primary-color); border-color: var(--primary-color); }
        button:disabled { opacity: 0.6; cursor: default; }
        .result { margin-top: 12px; padding: 12px; border-radius: 8px; }
        .result.ok { background: rgba(var(--rgb-success-color, 67, 160, 71), 0.12); }
        .result.error { background: rgba(var(--rgb-error-color, 219, 68, 55), 0.12); color: var(--error-color); }
        .result ul { margin: 8px 0 0; padding-left: 20px; color: var(--secondary-text-color); }
        .table { overflow-x: auto; }
        table { width: 100%; border-collapse: collapse; font-size: 14px; }
        th, td { text-align: left; padding: 8px; border-bottom: 1px solid var(--divider-color); white-space: nowrap; }
        th { color: var(--secondary-text-color); font-weight: 500; }
        .num { text-align: right; }
        .files button { padding: 4px 10px; }
        .files button.delete { color: var(--error-color); border-color: transparent; background: none; }
        .tag { font-size: 12px; color: var(--secondary-text-color); }
        @media (max-width: 600px) {
          main { padding: 8px; gap: 8px; }
          thead { display: none; }
          tr { display: grid; grid-template-columns: 1fr auto; padding: 8px 0; border-bottom: 1px solid var(--divider-color); }
          td { border: none; padding: 2px 4px; white-space: normal; }
          td.period { font-weight: 500; }
          td.num { text-align: left; color: var(--secondary-text-color); }
          td.num::before { content: attr(data-label) ": "; }
          td.files { grid-column: 2; grid-row: 1 / span 5; align-self: center; display: grid; gap: 6px; }
        }
      </style>
      <header>
        <ha-menu-button></ha-menu-button>
        <h1>${t.title}</h1>
      </header>
      <main>${body}</main>`;
    this._syncMenuButton();
  }
}

// The module can load twice, e.g. after an update changes its URL.
if (!customElements.get("ere-report-panel")) {
  customElements.define("ere-report-panel", EreReportPanel);
}
