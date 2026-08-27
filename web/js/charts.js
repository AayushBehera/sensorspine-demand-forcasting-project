/* ECharts helpers: shared theme, init/dispose tracking, common option builders.
   echarts.min.js is vendored UMD loaded via <script> -> window.echarts. */

export const C = {
  demand: "#3b82f6", ai: "#a78bfa", teal: "#14b8a6", good: "#22c55e",
  warn: "#f59e0b", bad: "#ef4444", hist: "#64748b",
  series: ["#3b82f6", "#14b8a6", "#a78bfa", "#f59e0b", "#ef4444", "#22c55e",
           "#38bdf8", "#e879f9", "#84cc16", "#fb923c"],
};

const instances = new Set();
let themeDone = false;

// Shared observer: resize any chart whose container box changes (responsive
// reflow, sidebar toggle, nested layout). Falls back to window resize only.
const chartRO = (typeof ResizeObserver !== "undefined")
  ? new ResizeObserver(() => { for (const i of instances) { try { i.resize(); } catch {} } })
  : null;
window.addEventListener("resize", () => { for (const i of instances) { try { i.resize(); } catch {} } });

function ensureTheme() {
  if (themeDone || !window.echarts) return;
  const axis = { axisLine: { lineStyle: { color: "#3d4f74" } }, axisTick: { show: false } };
  window.echarts.registerTheme("spine", {
    backgroundColor: "transparent",
    color: C.series,
    textStyle: { fontFamily: 'ui-sans-serif, system-ui, "Segoe UI", Roboto, sans-serif' },
    title: { textStyle: { color: "#e6edf7" } },
    legend: { textStyle: { color: "#8fa3bf" }, inactiveColor: "#44536f" },
    tooltip: {
      backgroundColor: "rgba(13,20,35,.96)", borderColor: "#2e3f63",
      textStyle: { color: "#e6edf7", fontSize: 12 },
      extraCssText: "font-variant-numeric: tabular-nums;",
    },
    categoryAxis: { ...axis, axisLabel: { color: "#8fa3bf" }, splitLine: { show: false } },
    valueAxis: { ...axis, axisLabel: { color: "#8fa3bf" }, splitLine: { lineStyle: { color: "#1c2a47" } } },
  });
  themeDone = true;
}

export function chartReady() { return typeof window.echarts !== "undefined"; }

export function mount(el, option) {
  if (!el) return null;
  el.innerHTML = "";
  if (!chartReady()) {
    el.innerHTML = `<div class="state"><div class="glyph">~</div><h4>Charts unavailable offline</h4>
      <p>echarts.min.js failed to load from web/vendor/. Re-download it or check the network tab.</p></div>`;
    return null;
  }
  ensureTheme();
  const inst = window.echarts.init(el, "spine");
  inst.setOption(option);
  instances.add(inst);
  if (chartRO) { try { chartRO.observe(el); } catch {} }
  return inst;
}

export function disposeAll() {
  for (const inst of instances) { try { inst.dispose(); } catch { /* already gone */ } }
  instances.clear();
}

window.addEventListener("resize", () => { for (const i of instances) { try { i.resize(); } catch {} } });


const baseGrid = { left: 46, right: 18, top: 30, bottom: 42, containLabel: true };

/** Multi-series line/area. series: [{name, data, color?, dashed?, area?}] */
export function lineOption(dates, seriesArr, { unit = "", stacked = false } = {}) {
  return {
    animation: false,
    tooltip: { trigger: "axis", valueFormatter: (v) => v == null ? "–" : v + " " + unit },
    legend: { type: "scroll", bottom: 0 },
    grid: baseGrid,
    xAxis: { type: "category", boundaryGap: false, data: dates, axisLabel: { hideOverlap: true } },
    yAxis: { type: "value", name: unit || null },
    series: seriesArr.map((s) => ({
      name: s.name, type: "line", showSymbol: dates.length < 40,
      data: s.data,
      stack: stacked ? "total" : undefined,
      areaStyle: s.area ? { opacity: 0.12 } : undefined,
      lineStyle: { width: 2, type: s.dashed ? "dashed" : "solid", color: s.color },
      itemStyle: { color: s.color },
      emphasis: { focus: "series" },
    })),
  };
}

/**
 * Actual vs forecast with q10–q90 band.
 * actual/pred/low/high are arrays aligned to dates (null gaps allowed).
 */
export function forecastBandOption(dates, { actual, pred, low, high }, { unit = "units" } = {}) {
  const bandBase = low.map((v) => (v == null ? "-" : v));
  const bandSpan = high.map((v, i) => (v == null || low[i] == null ? "-" : +(v - low[i]).toFixed(2)));
  return {
    animation: false,
    tooltip: { trigger: "axis", valueFormatter: (v) => v === "-" ? "–" : v + " " + unit },
    legend: { bottom: 0 },
    grid: baseGrid,
    xAxis: { type: "category", boundaryGap: false, data: dates, axisLabel: { hideOverlap: true } },
    yAxis: { type: "value", name: unit },
    series: [
      { name: "90% interval", type: "line", data: bandBase, stack: "band", step: false,
        lineStyle: { opacity: 0 }, symbol: "none", tooltip: { show: false }, silent: true },
      { name: "Forecast interval (q10–q90)", type: "line", data: bandSpan, stack: "band",
        lineStyle: { opacity: 0 }, symbol: "none", silent: true,
        areaStyle: { color: C.ai, opacity: 0.18 } },
      { name: "Actual", type: "line", data: actual, showSymbol: dates.length < 40,
        lineStyle: { width: 2.4, color: C.demand }, itemStyle: { color: C.demand } },
      { name: "Forecast", type: "line", data: pred, showSymbol: false,
        lineStyle: { width: 2, type: "dashed", color: C.ai }, itemStyle: { color: C.ai } },
    ],
  };
}

/** Vertical bars. entries: [{name, value}] or [label, value] pairs; supports multi series via seriesOf. */
export function barsOption(categories, values, { unit = "", color = C.demand, horizontal = false, name = "" } = {}) {
  const catAxis = { type: horizontal ? "value" : "category", data: categories,
    axisLabel: { hideOverlap: true, width: horizontal ? 150 : undefined, overflow: horizontal ? "truncate" : undefined } };
  const valAxis = { type: horizontal ? "category" : "value", name: unit || null };
  return {
    animation: false,
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: (v) => v + " " + unit },
    grid: { ...baseGrid, left: horizontal ? 10 : 46 },
    xAxis: horizontal ? valAxis : catAxis,
    yAxis: horizontal ? catAxis : valAxis,
    series: [{ name, type: "bar", data: values, barMaxWidth: 34, itemStyle: { color, borderRadius: [3, 3, 0, 0] } }],
  };
}

/** Donut with labels + legend. entries: [[label, value]] */
export function donutOption(entries, { unit = "" } = {}) {
  return {
    animation: false,
    tooltip: { trigger: "item", formatter: (p) => `${p.name}<br><b>${p.value}</b> ${unit} (${p.percent}%)` },
    legend: { orient: "vertical", right: 4, top: "middle", type: "scroll" },
    series: [{
      type: "pie", radius: ["48%", "72%"], center: ["38%", "50%"],
      avoidLabelOverlap: true, label: { show: false },
      data: entries.map(([name, value]) => ({ name, value })),
    }],
  };
}

/** Stacked bars by status. categories + [{name,data,color}] */
export function stackedBarOption(categories, seriesArr, { unit = "" } = {}) {
  return {
    animation: false,
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    legend: { bottom: 0 },
    grid: baseGrid,
    xAxis: { type: "category", data: categories, axisLabel: { hideOverlap: true } },
    yAxis: { type: "value", name: unit },
    series: seriesArr.map((s) => ({
      name: s.name, type: "bar", stack: "s", data: s.data, barMaxWidth: 40,
      itemStyle: { color: s.color },
    })),
  };
}

/** Heatmap. data: [[xIdx,yIdx,value]] */
export function heatOption(xLabels, yLabels, data, { unit = "" } = {}) {
  const vals = data.map((d) => d[2]);
  const min = vals.length ? Math.min(...vals) : 0;
  const max = vals.length ? Math.max(...vals) : 1;
  return {
    animation: false,
    tooltip: { position: "top",
      formatter: (p) => `${xLabels[p.value[0]]}, ${yLabels[p.value[1]]}<br><b>${p.value[2]}</b> ${unit}` },
    grid: { ...baseGrid, left: 90 },
    xAxis: { type: "category", data: xLabels, splitArea: { show: true } },
    yAxis: { type: "category", data: yLabels, splitArea: { show: true } },
    visualMap: {
      min, max: max > min ? max : min + 1,
      calculable: false, orient: "horizontal", left: "center", bottom: 0,
      inRange: { color: ["#1d4ed8", "#7dd3fc", "#fbbf24", "#ef4444"] },
      textStyle: { color: "#8fa3bf" },
    },
    series: [{ type: "heatmap", data, label: { show: data.length <= 200, color: "#dbe4f5", fontSize: 9 } }],
  };
}

/** Force-ish graph used for transfer flows; pass layout:"none" + node x/y for schematics. */
export function graphOption(nodes, links, { captions = false, layout = "force" } = {}) {
  return {
    animation: false,
    tooltip: { formatter: (p) => p.dataType === "edge"
      ? `${p.data.source} → ${p.data.target}${p.data.tip ? "<br>" + p.data.tip : ""}`
      : `${p.name}${p.data.tip ? "<br>" + p.data.tip : ""}` },
    series: [{
      type: "graph", layout,
      force: layout === "force" ? { repulsion: 320, edgeLength: 110, gravity: 0.12 } : undefined,
      roam: true,
      label: { show: true, color: "#cbd5ea", fontSize: 11, position: "bottom" },
      edgeLabel: { show: !!captions, fontSize: 10, color: "#8fa3bf", formatter: (p) => p.data.km != null ? p.data.km + " km" : "" },
      lineStyle: { curveness: 0.15, opacity: 0.85 },
      emphasis: { focus: "adjacency" },
      data: nodes, links,
    }],
  };
}

/** Scatter with reference diagonal (pred vs actual). */
export function scatterOption(points, { unit = "units" } = {}) {
  const finite = points.filter((p) => Number.isFinite(p[0]) && Number.isFinite(p[1]));
  const maxV = Math.max(1, ...finite.flatMap((p) => [p[0], p[1]]));
  return {
    animation: false,
    tooltip: { formatter: (p) => p.seriesType === "scatter"
      ? `${p.data[2] || "pair"}<br>Predicted ${fmtN(p.value[0])} · Actual ${fmtN(p.value[1])}` : "" },
    grid: baseGrid,
    xAxis: { type: "value", name: "Predicted (" + unit + ")", min: 0, max: maxV },
    yAxis: { type: "value", name: "Actual (" + unit + ")", min: 0, max: maxV },
    series: [
      { type: "line", silent: true, tooltip: { show: false }, lineStyle: { type: "dashed", color: C.hist },
        data: [[0, 0], [maxV, maxV]] },
      { type: "scatter", symbolSize: 7, itemStyle: { color: C.demand, opacity: 0.65 }, data: finite },
    ],
  };
}

const fmtN = (v) => Number(v).toLocaleString(undefined, { maximumFractionDigits: 1 });
