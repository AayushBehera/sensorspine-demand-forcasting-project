/* Component kit: returns DOM elements built from HTML strings.
   Data honesty helpers live here: skeleton / empty / error states. */

import { fmt } from "./format.js";
import { api } from "./api.js";

/** Accept/dismiss a recommendation; wraps busy state + toast. Returns success. */
export async function submitDecision(id, action, unitsMoved, btn) {
  const units = unitsMoved != null && unitsMoved !== "" ? Number(unitsMoved) : null;
  if (action === "accepted" && (units == null || Number.isNaN(units) || units < 0)) {
    toast("Enter the number of units actually moved", true);
    return false;
  }
  busy(btn, true);
  try {
    await api.post(`/recommendations/${id}/decision`,
      { action, units_moved: action === "accepted" ? units : undefined });
    toast(action === "accepted"
      ? `Recorded: ${fmt(units, 0)} units moved — saved for accuracy evaluation`
      : "Recommendation dismissed");
    return true;
  } catch (e) { toast(e.message || String(e), true); return false; }
  finally { busy(btn, false); }
}

export const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

/* ---------- toast ---------- */
let toastTimer = null;
export function toast(msg, isError = false) {
  let t = document.getElementById("toast");
  if (!t) { t = el('<div id="toast"></div>'); document.body.appendChild(t); }
  t.textContent = String(msg);
  t.className = isError ? "error" : "";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), 4500);
}

export function busy(btn, on, labelBusy) {
  if (!btn) return;
  if (on) { btn.disabled = true; btn.dataset.old = btn.textContent; btn.textContent = labelBusy || "Working…"; }
  else { btn.disabled = false; btn.textContent = btn.dataset.old || "Done"; }
}

export const confirmDialog = (msg) => window.confirm(msg);

/* ---------- semantic labels ---------- */
const STATUS_LABELS = {
  shortage: "Shortage", balanced: "Balanced", low_surplus: "Low surplus",
  high_surplus: "High surplus", unknown_supply: "Supply unknown",
  stable: "Stable", moderate_uncertainty: "Moderate uncertainty",
  high_uncertainty: "High uncertainty",
  pending: "Pending", accepted: "Accepted", rejected: "Rejected",
  confirmed: "Confirmed", estimated: "Estimated",
};
export const labelize = (k) => STATUS_LABELS[k] || String(k ?? "–");

const PILL_TONE = {
  shortage: "red", high_uncertainty: "red", high_surplus: "red",
  balanced: "green", stable: "green", accepted: "green", confirmed: "teal",
  low_surplus: "amber", moderate_uncertainty: "amber", estimated: "amber", pending: "blue",
  unknown_supply: "gray", rejected: "gray",
  high: "red", medium: "amber", low: "gray",
};
export function statusPill(status, extraLabel) {
  const tone = PILL_TONE[String(status ?? "").toLowerCase()] || "gray";
  return `<span class="pill pill-${tone}" title="${esc(labelize(status))}">
    <span aria-hidden="true" style="font-size:8px">&#9679;</span>${esc(extraLabel || labelize(status))}</span>`;
}
export const riskBadge = (status) => statusPill(status);

const PROV_TONE = {
  OFFICIAL: "green", "OFFICIAL-derived": "teal", RESEARCH: "purple",
  COMMUNITY: "blue", SYNTHETIC: "amber", DERIVED: "teal",
};
export function dataSourceBadge(type) {
  const key = String(type || "").toUpperCase();
  const tone = Object.entries(PROV_TONE).find(([k]) => key.startsWith(k))?.[1] || "gray";
  return `<span class="pill pill-${tone}">${esc(type || "UNKNOWN")}</span>`;
}

/* ---------- metric card ---------- */
export function metricCard({ label, value, hint, delta, tone = "", icon }) {
  return el(`<div class="metric-card ${tone ? "tone-" + tone : ""}">
    <span class="metric-label">${icon ? `<span aria-hidden="true">${icon}</span>` : ""}${esc(label)}</span>
    <span class="metric-value">${value}</span>
    ${delta ? `<span class="metric-hint">${esc(delta)}</span>` : hint ? `<span class="metric-hint">${esc(hint)}</span>` : ""}
  </div>`);
}

/* ---------- panel (card w/ states) ---------- */
export function panel({ title, subtitle = "", actions = "" }) {
  const root = el(`<section class="card">
    <div class="card-head">
      <div><div class="card-title">${title}</div>
      ${subtitle ? `<div class="card-subtitle">${subtitle}</div>` : ""}</div>
      <div class="card-actions"></div>
    </div>
    <div class="panel-body"></div>
  </section>`);
  const body = root.querySelector(".panel-body");
  const actionsEl = root.querySelector(".card-actions");
  if (actions) actionsEl.innerHTML = actions;
  return {
    root, body, actionsEl,
    set(node) { body.innerHTML = ""; if (node) body.appendChild(node); },
    setHtml(html) { body.innerHTML = html; },
    loading() {
      body.innerHTML = `<div class="skl-line skeleton" style="width:40%"></div><div class="skl-block skeleton"></div>`;
    },
    error(err, retry) {
      body.innerHTML = "";
      body.appendChild(errorState(
        `Couldn't load this panel`, `${err?.message || err}`,
        retry ? () => { this.loading(); retry(); } : null));
    },
    empty(title_, why) {
      body.innerHTML = "";
      body.appendChild(emptyState(title_, why));
    },
  };
}

/* ---------- states ---------- */
export function skeletonLines(n = 4) {
  const d = el("<div></div>");
  for (let i = 0; i < n; i++) d.appendChild(el(`<div class="skl-line skeleton" style="width:${90 - i * 15}%"></div>`));
  return d;
}

export function emptyState(title, why) {
  return el(`<div class="state" role="status">
    <div class="glyph" aria-hidden="true">i</div>
    <h4>${esc(title)}</h4><p>${why}</p>
  </div>`);
}

export function errorState(title, detail, onRetry) {
  const s = el(`<div class="state err" role="alert">
    <div class="glyph" aria-hidden="true">!</div>
    <h4>${esc(title)}</h4><p>${esc(detail)}</p>
  </div>`);
  if (onRetry) {
    const b = el('<button class="btn sm">Retry</button>');
    b.addEventListener("click", onRetry);
    s.appendChild(b);
  }
  return s;
}

export function offlineFallback(what) {
  return `<div class="state"><div class="glyph" aria-hidden="true">~</div>
    <h4>${esc(what)} unavailable offline</h4>
    <p>The chart library could not be loaded. Check your connection or re-download web/vendor/.</p></div>`;
}

/* ---------- sortable, paginated table ---------- */
/**
 * columns: [{key, label, numeric?, format?(row)=>string, maxWidth?}]
 * Server-side pagination when total/page/onPage provided; client sorting via onSort.
 */
export function dataTable({ columns, rows, sortKey, sortDir, onSort, page, pageSize, total, onPage, emptyMsg }) {
  const wrap = el(`<div><div class="table-wrap"><table class="dt"><thead></thead><tbody></tbody></table></div></div>`);
  const thead = wrap.querySelector("thead");
  const tbody = wrap.querySelector("tbody");
  thead.innerHTML = "<tr>" + columns.map((c) =>
    `<th class="${c.numeric ? "numeric" : ""} ${onSort ? "sortable" : ""}" data-key="${esc(c.key)}"
       ${c.maxWidth ? `style="max-width:${c.maxWidth}"` : ""}
       aria-sort="${sortKey === c.key ? (sortDir === "desc" ? "descending" : "ascending") : "none"}"
       ${onSort ? `title="Sort by ${esc(c.label)}"` : ""}>${esc(c.label)}${sortKey === c.key ? (sortDir === "desc" ? " ▾" : " ▴") : ""}</th>`).join("") + "</tr>";
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="${columns.length}">${esc(emptyMsg || "No rows")}</td></tr>`;
  } else {
    tbody.innerHTML = rows.map((r) => "<tr>" + columns.map((c) => {
      const raw = typeof c.format === "function" ? c.format(r) : r[c.key];
      return `<td class="${c.numeric ? "numeric" : ""}">${raw == null ? "–" : raw}</td>`;
    }).join("") + "</tr>").join("");
  }
  if (onSort) thead.querySelectorAll("th.sortable").forEach((th) =>
    th.addEventListener("click", () => onSort(th.dataset.key)));
  if (total != null && onPage) {
    const n = rows.length;
    const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
    const to = (page - 1) * pageSize + n;
    const pages = Math.max(1, Math.ceil(total / pageSize));
    const foot = el(`<div class="table-foot">
      <span>Showing ${from}–${to} of ${fmt(total)} · page ${page}/${pages}</span>
      <span class="row" style="gap:6px">
        <button class="btn sm" data-pg="prev" ${page <= 1 ? "disabled" : ""}>Prev</button>
        <button class="btn sm" data-pg="next" ${page >= pages ? "disabled" : ""}>Next</button>
      </span></div>`);
    foot.querySelectorAll("[data-pg]").forEach((b) =>
      b.addEventListener("click", () => onPage(b.dataset.pg === "prev" ? page - 1 : page + 1)));
    wrap.appendChild(foot);
  }
  return wrap;
}

/* ---------- recommendation card ---------- */
const FACTOR_LABELS = [
  ["need", "Need"], ["quantity_fit", "Quantity fit"], ["urgency", "Urgency"],
  ["proximity", "Proximity"], ["compatibility", "Compatibility"],
];

export function recCard(r, names, { onDecision } = {}) {
  const f = r.factors || {};
  const card = el(`<article class="rec-card" data-id="${r.recommendation_id ?? ""}">
    <div class="row spread">
      <span class="rec-route">${esc(names.loc(r.source_location))}
        <span aria-hidden="true" style="color:var(--teal)">→</span>
        ${esc(names.loc(r.destination_location))}
        ${statusPill(r.status)}${statusPill(r.urgency)}
      </span>
      <span class="rec-score num">${fmt(r.score, 0)}<small class="muted" style="font-size:12px">/100</small></span>
    </div>
    <div class="rec-meta">
      <span>Move <b class="num">${fmt(r.transfer_quantity, 0)} units</b></span>
      <span>Item <b>${esc(names.item(r.source_item))}</b></span>
      <span>Date <b>${esc(r.service_date)}</b></span>
      <span>Surplus at source <b class="num">${fmt(r.available_surplus, 0)}</b></span>
      <span>Predicted need <b class="num">${fmt(r.predicted_need, 0)}</b></span>
      ${r.distance_km != null ? `<span>Distance <b class="num">${fmt(r.distance_km)} km</b></span>` : ""}
    </div>
    <p class="rec-reason"><b>Why:</b> ${esc(r.reason)}</p>
    <div class="factor-bars">
      ${FACTOR_LABELS.map(([k, lab]) => {
        const v = Math.max(0, Math.min(1, Number(f[k] ?? 0)));
        return `<div class="factor">${lab}<span class="num" style="float:right">${Math.round(v * 100)}%</span>
          <div class="factor-bar"><div class="factor-fill" style="width:${Math.round(v * 100)}%"></div></div></div>`;
      }).join("")}
    </div>
    <div class="row rec-actions" style="margin-top:10px"></div>
  </article>`);

  const acts = card.querySelector(".rec-actions");
  if (onDecision && r.status === "pending" && r.recommendation_id != null) {
    const input = el(`<label class="fld small">Units moved
      <input type="number" min="0" step="1" value="${Math.round(r.transfer_quantity)}"
             style="width:90px;background:var(--surface);border:1px solid var(--hairline-strong);border-radius:6px;padding:5px 8px;color:var(--text)">
    </label>`);
    const ok = el('<button class="btn primary sm">Confirm transfer done</button>');
    const no = el('<button class="btn sm danger">Dismiss</button>');
    ok.addEventListener("click", () => onDecision(r.recommendation_id, "accepted", input.querySelector("input").value, ok));
    no.addEventListener("click", () => onDecision(r.recommendation_id, "rejected", null, no));
    acts.append(input, ok, no);
  }
  return card;
}
