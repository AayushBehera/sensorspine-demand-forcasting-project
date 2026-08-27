/* Number / date / percent formatting. All metric text uses tabular numerals (CSS). */

export function fmt(n, digits = 1) {
  if (n === null || n === undefined || n === "" || Number.isNaN(Number(n))) return "–";
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: digits });
}

export const fmtInt = (n) => fmt(n, 0);

export function signed(n, digits = 1) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return "–";
  const v = Number(n);
  return (v > 0 ? "+" : "") + v.toLocaleString(undefined, { maximumFractionDigits: digits });
}

/** Percent from a 0-1 ratio (API sends ratios like acceptance_rate_pct as % already — use pctRaw for those). */
export function pct(ratio, digits = 1) {
  if (ratio === null || ratio === undefined || Number.isNaN(Number(ratio))) return "–";
  return Number(ratio * 100).toFixed(digits) + "%";
}

export const pctRaw = (v, digits = 1) =>
  (v === null || v === undefined || Number.isNaN(Number(v))) ? "–" : Number(v).toFixed(digits) + "%";

/** "2026-08-14" -> "Aug 14" */
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export function dateMD(d) {
  if (!d) return "";
  const [y, m, day] = String(d).split("-");
  return `${MONTHS[Number(m) - 1] ?? m} ${Number(day)}`;
}
export const dateFull = (d) => d || "";

export function nowClock() {
  return new Date().toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

/** ISO date N days before `end` (both YYYY-MM-DD, UTC-safe). */
export function daysBefore(endIso, days) {
  const d = new Date(endIso + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}
