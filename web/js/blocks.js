/* Render the chat {text, blocks} contract into DOM.
   Block types: text, kpi, chart, table, map, note.
   Reuses app/charts.js (ECharts) and Leaflet (global L). */
import { mount, C } from "./charts.js";
import { esc } from "./ui.js";

const TONE = { good: "good", warn: "warn", bad: "bad" };

export function renderBlocks(blocks) {
  const wrap = document.createElement("div");
  wrap.className = "blocks";
  for (const b of blocks || []) {
    try {
      const node = renderOne(b);
      if (node) wrap.appendChild(node);
    } catch (e) {
      wrap.appendChild(note("⚠️ Could not render a block: " + e.message));
    }
  }
  return wrap;
}

function renderOne(b) {
  switch (b.type) {
    case "text": return textBlock(b.markdown || "");
    case "note": return note(b.text || "");
    case "kpi": return kpiBlock(b.items || []);
    case "chart": return chartBlock(b);
    case "table": return tableBlock(b);
    case "map": return mapBlock(b);
    default: return note("Unknown block: " + b.type);
  }
}

/* --- text (minimal markdown) --- */
function textBlock(md) {
  const d = document.createElement("div");
  d.className = "msg-text";
  d.innerHTML = miniMarkdown(md);
  return d;
}
function miniMarkdown(s) {
  const esc = (x) => x.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  return esc(String(s))
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/\n/g, "<br>");
}

/* --- note --- */
function note(text) {
  const d = document.createElement("div");
  d.className = "block-note";
  d.textContent = text;
  return d;
}

/* --- kpi --- */
function kpiBlock(items) {
  const grid = document.createElement("div");
  grid.className = "kpi-grid";
  for (const it of items) {
    const card = document.createElement("div");
    card.className = "kpi-card " + (TONE[it.tone] || "");
    card.innerHTML =
      `<div class="k-label">${esc(it.label || "")}</div>` +
      `<div class="k-value">${esc(it.value ?? "")}</div>`;
    grid.appendChild(card);
  }
  return grid;
}

/* --- chart --- */
function chartBlock(b) {
  const wrap = document.createElement("div");
  if (b.title) {
    const t = document.createElement("div");
    t.className = "block-title";
    t.textContent = b.title;
    wrap.appendChild(t);
  }
  const box = document.createElement("div");
  box.className = "chart-box" + (b.chart_type === "line" ? " tall" : "");
  wrap.appendChild(box);
  const opt = chartOption(b);
  // mount after layout so ECharts reads a real width
  requestAnimationFrame(() => mount(box, opt));
  return wrap;
}

function chartOption(b) {
  if (b.chart_type === "donut") {
    const data = (b.series?.[0]?.data || []).map((v, i) => ({
      name: b.categories?.[i] || ("#" + (i + 1)), value: v,
    }));
    return {
      tooltip: { trigger: "item" },
      legend: { bottom: 0, textStyle: { color: "#8fa3bf" } },
      series: [{ type: "pie", radius: ["38%", "70%"],
                 data, label: { color: "#e6edf7" },
                 itemStyle: { borderColor: "transparent" } }],
    };
  }
  const isBar = b.chart_type === "bar";
  const isH = !!b.horizontal;
  const catAxis = { type: "category", data: b.categories || [],
                    axisLabel: { color: "#8fa3bf" }, axisLine: { lineStyle: { color: "#3d4f74" } } };
  const valAxis = { type: "value", axisLabel: { color: "#8fa3bf" },
                    name: b.unit || "", axisLine: { lineStyle: { color: "#3d4f74" } },
                    splitLine: { lineStyle: { color: "#1c2a47" } } };
  const series = (b.series || []).map((s) => ({
    name: s.name, type: isBar ? "bar" : "line",
    data: s.data, smooth: !isBar, symbol: "none",
    ...(s.area ? { areaStyle: { opacity: 0.15 } } : {}),
    ...(s.color ? { itemStyle: { color: s.color }, lineStyle: { color: s.color, width: 2 } } : {}),
    ...(s.dashed ? { lineStyle: { type: "dashed" } } : {}),
  }));
  return {
    tooltip: { trigger: "axis",
               valueFormatter: (v) => (v == null ? "" : v) + (b.unit ? " " + b.unit : "") },
    legend: { bottom: 0, textStyle: { color: "#8fa3bf" } },
    grid: { left: 48, right: 18, top: 28, bottom: 46, containLabel: true },
    xAxis: isBar && isH ? valAxis : catAxis,
    yAxis: isBar && isH ? catAxis : valAxis,
    series,
  };
}

/* --- table --- */
function tableBlock(b) {
  const wrap = document.createElement("div");
  if (b.title) {
    const t = document.createElement("div");
    t.className = "block-title";
    t.textContent = b.title;
    wrap.appendChild(t);
  }
  const sc = document.createElement("div");
  sc.className = "dt-wrap";
  const table = document.createElement("table");
  table.className = "dt";
  const cols = b.columns || [];
  table.innerHTML =
    "<thead><tr>" + cols.map((c) => `<th>${esc(c.label)}</th>`).join("") + "</tr></thead>";
  const tb = document.createElement("tbody");
  for (const row of b.rows || []) {
    const tr = document.createElement("tr");
    tr.innerHTML = cols.map((c) => `<td>${esc(row[c.key] ?? "")}</td>`).join("");
    tb.appendChild(tr);
  }
  table.appendChild(tb);
  sc.appendChild(table);
  wrap.appendChild(sc);
  return wrap;
}

/* --- map --- */
function mapBlock(b) {
  const wrap = document.createElement("div");
  if (b.title) {
    const t = document.createElement("div");
    t.className = "block-title";
    t.textContent = b.title;
    wrap.appendChild(t);
  }
  const box = document.createElement("div");
  box.className = "map-box";
  wrap.appendChild(box);
  if (typeof L === "undefined") {
    box.textContent = "Map library unavailable.";
    return wrap;
  }
  const center = b.center || [12.97, 77.59];
  requestAnimationFrame(() => {
    const map = L.map(box).setView(center, b.zoom || 11);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
      { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(map);
    const maxW = Math.max(1, ...(b.points || []).map((p) => p.weight || 0));
    for (const p of b.points || []) {
      const r = 5 + 16 * ((p.weight || 0) / maxW);
      const color = p.color || C.teal;
      L.circleMarker([p.lat, p.lng], { radius: r, color, weight: 1,
        fillColor: color, fillOpacity: 0.5 })
        .addTo(map).bindPopup(p.label || "");
    }
    setTimeout(() => map.invalidateSize(), 200);
  });
  return wrap;
}
