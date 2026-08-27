/* Fetch wrapper: JSON, error normalization, tiny TTL cache, AbortController pass-through. */

const DEFAULT_TTL = 60_000;
const cache = new Map();

export class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

async function request(path, { method = "GET", body, signal, ttl = DEFAULT_TTL } = {}) {
  const url = path.startsWith("/api") ? path : "/api" + path;
  const key = method + " " + url + (body ? " " + body : "");
  if (method === "GET") {
    const hit = cache.get(key);
    if (hit && Date.now() - hit.t < ttl) return hit.data;
    if (hit) cache.delete(key);
  }
  let res;
  try {
    res = await fetch(url, {
      method,
      signal,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    if (e && e.name === "AbortError") throw e;
    throw new ApiError("Cannot reach backend — is the server running?", 0);
  }
  let data = null;
  try { data = await res.json(); } catch { /* non-JSON body */ }
  if (!res.ok) {
    const d = data && data.detail;
    const msg = typeof d === "object" && d ? (d.detail || d.error || res.statusText)
      : (typeof d === "string" ? d : res.statusText);
    throw new ApiError(String(msg || "Request failed"), res.status);
  }
  if (method === "GET") cache.set(key, { t: Date.now(), data });
  return data;
}

export const api = {
  get: (path, opts) => request(path, opts),
  post: (path, payload, opts) => request(path, { method: "POST", body: payload ?? {}, ...opts }),
};

export function clearApiCache() { cache.clear(); }

/** Build "?a=1&b=x" from an object, skipping null/undefined/"" values. */
export function qs(params) {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params || {})) {
    if (v === null || v === undefined || v === "") continue;
    u.set(k, String(v));
  }
  const s = u.toString();
  return s ? "?" + s : "";
}

/**
 * Page through a paginated endpoint ({items,total,page,page_size}) until
 * `max` rows or the end. Returns {items,total,truncated}.
 */
export async function fetchAll(path, { max = 1000, page_size = 500, signal } = {}) {
  const out = [];
  let total = 0;
  let page = 1;
  for (;;) {
    const sep = path.includes("?") ? "&" : "?";
    const data = await request(path + sep + "page=" + page + "&page_size=" + page_size, { signal });
    total = data.total ?? out.length;
    out.push(...(data.items || []));
    if (out.length >= total || !(data.items || []).length || out.length >= max) break;
    page += 1;
  }
  return { items: out.slice(0, max), total, truncated: total > out.length };
}
