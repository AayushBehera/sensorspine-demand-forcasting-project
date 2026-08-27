"""Chat provider abstraction.

The chat engine returns a `{text, blocks}` payload (see app/blocks.py). Two
provider kinds:

* FallbackProvider  — deterministic intent -> tools -> blocks. Works with no
  API key, so the whole chat is usable today.
* HttpLlmProvider   — calls a real LLM with function-calling over the same
  tools. Activates automatically when env vars are set (see get_provider).

Drop-in later: set SENSORSPINE_LLM_PROVIDER=openai (or anthropic) and the
matching key; no code change needed.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from datetime import date

import app.db as db
import app.tools as tools
import app.blocks as B

C = {  # series colors
    "demand": "#3b82f6", "ai": "#a78bfa", "teal": "#14b8a6", "good": "#22c55e",
    "warn": "#f59e0b", "bad": "#ef4444", "hist": "#64748b",
}

# --------------------------------------------------------------------------- #
# shared helpers
# --------------------------------------------------------------------------- #

_LOCATIONS: list[dict] | None = None

def _locations() -> list[dict]:
    global _LOCATIONS
    if _LOCATIONS is None:
        try:
            conn = db.connect(db.DB_PATH)
            _LOCATIONS = [dict(r) for r in conn.execute(
                "SELECT location_id, name FROM locations")]
            conn.close()
        except Exception:
            _LOCATIONS = []
    return _LOCATIONS

def _name(loc_id: str | None) -> str:
    if not loc_id:
        return ""
    for l in _locations():
        if l["location_id"] == loc_id:
            return l["name"]
    return loc_id

def _pick_location(text: str) -> str | None:
    t = text.lower()
    for l in _locations():
        nm = (l["name"] or "").lower()
        if nm and nm in t:
            return l["location_id"]
        if l["location_id"].lower() in t:
            return l["location_id"]
    return None

def _pick_days(text: str, default: int = 30) -> int:
    m = re.search(r"(\d+)\s*(?:day|d)\b", text.lower())
    if m:
        return max(1, min(180, int(m.group(1))))
    for kw, d in (("last 7", 7), ("past week", 7), ("7 day", 7),
                  ("30 day", 30), ("90 day", 90), ("last month", 30),
                  ("quarter", 90), ("year", 180)):
        if kw in text.lower():
            return d
    return default

def _sorted_items(d: dict) -> list[tuple[str, float]]:
    return sorted(((k, float(v)) for k, v in d.items() if v is not None),
                  key=lambda x: x[0])

def _bar_from_mapping(title, mapping, horizontal=True, color=C["teal"], unit=""):
    items = [(str(k), float(v)) for k, v in mapping.items() if v is not None]
    if not items:
        return None
    cats = [k for k, _ in items]
    vals = [round(v, 1) for _, v in items]
    return B.chart(title, "bar", cats,
                   [{"name": title, "data": vals, "color": color}],
                   horizontal=horizontal, unit=unit)


# --------------------------------------------------------------------------- #
# FallbackProvider
# --------------------------------------------------------------------------- #

class FallbackProvider:
    name = "fallback"

    def respond(self, message: str, history: list | None = None) -> dict:
        text = (message or "").lower()
        loc = _pick_location(message)
        days = _pick_days(message)
        want_weather = any(w in text for w in
                           ("weather", "rain", "temperature", "climate", "open-meteo"))

        # weather questions lead with weather (and may overlay demand)
        if any(w in text for w in
               ("weather", "rain", "temperature", "climate", "open-meteo")):
            return self._weather(text, loc, days)

        if any(w in text for w in ("redistribut", "transfer", "move surplus",
                                    "recommend", "reallocate")):
            return self._redistribution(text, loc, want_weather)
        if any(w in text for w in ("surplus", "shortage", "waste", "leftover",
                                    "spoilage")):
            return self._surplus(text, loc, days, want_weather)
        if any(w in text for w in ("map", "campus", "where", "geograph",
                                    "location", "spatial")):
            return self._geographic(loc, want_weather)
        if any(w in text for w in ("food", "nutrition", "category", "ifct",
                                    "hces", "diet", "item")):
            return self._food(loc, want_weather)
        if any(w in text for w in ("model", "accuracy", "mae", "wape",
                                    "performance", "train", "registry",
                                    "baseline")):
            return self._model(loc, want_weather)
        if any(w in text for w in ("row", "record", "explore", "dataset",
                                    "table of data", "raw")):
            return self._records(text, loc, days)
        if any(w in text for w in ("forecast", "predict", "demand", "expected",
                                    "how much", "will we")):
            return self._demand(text, loc, days, want_weather)
        # default: overview
        return self._overview(text, loc, days, want_weather)

    # ----- intent builders --------------------------------------------------

    def _weather(self, text, loc, days):
        wb, wdesc = self._weather_block(loc)
        blocks = list(wb) if wb else []
        summary = wdesc or "Live weather (Open-Meteo)."
        if any(w in text for w in ("demand", "forecast", "affect", "impact", "how")):
            a = tools.run_tool("demand_summary",
                               {"days": days, "location_id": loc})
            dbd = a.get("demand_by_day", {})
            if dbd:
                items = _sorted_items(dbd)
                blocks.append(B.chart("Daily demand (same window)", "line",
                                      [k[5:] for k, _ in items],
                                      [{"name": "Demand", "data": [round(v, 1) for _, v in items],
                                        "color": C["demand"], "area": True}]))
                summary += (" Cross-check demand with the weather trend above — "
                            "rainy days typically shift demand.")
        return B.response(summary, blocks)

    def _weather_block(self, loc):
        w = tools.run_tool("weather_now", {"location_id": loc, "days": 7})
        if w.get("error"):
            return None, f"Live weather is unavailable right now ({w['error']})."
        days = w.get("days", [])
        if not days:
            return None, "No live weather returned."
        dates = [d["date"][5:] for d in days]
        tmax = [d["temp_max"] for d in days]
        tmin = [d["temp_min"] for d in days]
        precip = [d["precip"] or 0 for d in days]
        blk = B.chart("Live weather (Open-Meteo)", "line", dates,
                      [{"name": "Temp max °C", "data": tmax, "color": C["warn"]},
                       {"name": "Temp min °C", "data": tmin, "color": C["demand"]}],
                      unit="°C")
        pblk = B.chart("Daily precipitation", "bar", dates,
                       [{"name": "Precip mm", "data": precip, "color": C["teal"]}],
                       unit="mm")
        last = days[-1]
        desc = (f"Right now at {_name(loc) or 'Bengaluru'}: "
                f"{last['temp_min']}–{last['temp_max']}°C, "
                f"{last['precip'] or 0} mm rain, wind {last['wind']} km/h.")
        return [blk, pblk], desc

    def _demand(self, text, loc, days, want_weather):
        a = tools.run_tool("demand_summary",
                           {"days": days, "location_id": loc})
        blocks = []
        dbd = a.get("demand_by_day", {})
        if dbd:
            items = _sorted_items(dbd)
            blocks.append(B.chart("Daily demand", "line",
                                  [k[5:] for k, _ in items],
                                  [{"name": "Demand (units)", "data": [round(v, 1) for _, v in items],
                                    "color": C["demand"], "area": True}],
                                  unit="units"))
        share = a.get("demand_share_by_location", {})
        b = _bar_from_mapping("Demand share by location", share, color=C["demand"])
        if b:
            blocks.append(b)
        cat = a.get("demand_by_category", {})
        b = _bar_from_mapping("Demand by category", cat, color=C["ai"])
        if b:
            blocks.append(b)
        fm = a.get("feedback_metrics") or {}
        kpis = []
        tot = sum(dbd.values()) if dbd else None
        if tot is not None:
            kpis.append({"label": f"Total demand ({days}d)", "value": f"{round(tot):,} units"})
        if fm.get("mae") is not None:
            kpis.append({"label": "Forecast MAE", "value": f"{fm['mae']:.1f}",
                         "tone": "good" if fm.get("baselines_beaten") else "warn"})
        if fm.get("wape") is not None:
            kpis.append({"label": "WAPE", "value": f"{fm['wape']:.1f}%"})
        if kpis:
            blocks.insert(0, B.kpi(kpis))
        summary = (f"Over the last {days} days"
                   + (f" at {_name(loc)}" if loc else "") +
                   f": total demand ~{round(tot):,} units across "
                   f"{len(share)} locations. "
                   + (f"Model WAPE {fm['wape']:.1f}%." if fm.get('wape') is not None else ""))
        if want_weather:
            wb, wdesc = self._weather_block(loc)
            if wb:
                blocks.extend(wb)
                summary += " " + wdesc
        return B.response(summary, blocks)

    def _surplus(self, text, loc, days, want_weather):
        s = tools.run_tool("surplus", {"days": days, "location_id": loc})
        rows = s.get("rows", [])
        blocks = []
        if not rows:
            return B.response(
                "No surplus assessments in this window yet. Surplus/shortage "
                "assessments are produced by the daily cycle (Model & Feedback "
                "→ Run today's cycle), so they only exist for dates the cycle "
                "has processed.", [B.note("Try a smaller window or run the cycle.")])
        by_date = {}
        by_loc = {}
        mix = {}
        for r in rows:
            d = r.get("service_date")
            by_date[d] = by_date.get(d, 0) + (r.get("expected_surplus") or 0)
            by_loc[r.get("location_id")] = by_loc.get(r.get("location_id"), 0) + (r.get("expected_surplus") or 0)
            st = r.get("status", "unknown")
            mix[st] = mix.get(st, 0) + 1
        items = _sorted_items(by_date)
        blocks.append(B.chart("Net expected surplus over time", "line",
                              [k[5:] for k, _ in items],
                              [{"name": "Net surplus (units)", "data": [round(v, 1) for _, v in items],
                                "color": C["teal"], "area": True}], unit="units"))
        b = _bar_from_mapping("Expected surplus by location", by_loc, color=C["teal"])
        if b:
            blocks.append(b)
        if mix:
            blocks.append(B.chart("Assessment status mix", "donut",
                                  list(mix.keys()),
                                  [{"name": "rows", "data": list(mix.values())}]))
        shortages = mix.get("shortage", 0)
        summary = (f"{len(rows)} surplus assessments; {shortages} flagged as "
                   f"shortage risk" + (f" at {_name(loc)}" if loc else "") + ".")
        if want_weather:
            wb, wdesc = self._weather_block(loc)
            if wb:
                blocks.extend(wb); summary += " " + wdesc
        return B.response(summary, blocks)

    def _redistribution(self, text, loc, want_weather):
        recs = tools.run_tool("redistribution",
                              {"status": None, "location_id": loc})
        rows = recs.get("rows", [])
        blocks = []
        if not rows:
            return B.response(
                "No transfer recommendations recorded yet. Run the daily cycle "
                "to pair surplus with need and generate redistribution plans.",
                [B.note("Model & Feedback → Run today's cycle.")])
        by_status = {}
        pending = [r for r in rows if r.get("status") == "pending"]
        for r in rows:
            by_status[r.get("status", "unknown")] = by_status.get(r.get("status", "unknown"), 0) + 1
        kpis = [
            {"label": "Pending transfers", "value": str(len(pending)), "tone": "warn" if pending else "good"},
            {"label": "Total recommendations", "value": str(len(rows))},
        ]
        if by_status.get("accepted"):
            kpis.append({"label": "Accepted", "value": str(by_status["accepted"]), "tone": "good"})
        blocks.append(B.kpi(kpis))
        top = sorted(pending, key=lambda r: r.get("score", 0), reverse=True)[:12]
        if top:
            cols = [{"key": "dest", "label": "To campus"},
                    {"key": "item", "label": "Item"},
                    {"key": "qty", "label": "Qty"},
                    {"key": "urg", "label": "Urgency"},
                    {"key": "score", "label": "Score"}]
            rws = [{"dest": _name(r.get("destination_location")),
                    "item": r.get("destination_item") or r.get("source_item"),
                    "qty": r.get("transfer_quantity"),
                    "urg": r.get("urgency"), "score": round(r.get("score", 0), 2)}
                   for r in top]
            blocks.append(B.table("Top pending redistribution recommendations", cols, rws))
        summary = (f"{len(pending)} pending transfers out of {len(rows)} "
                   f"recommendations"
                   + (f" for {_name(loc)}" if loc else "") +
                   ". Accept or reject them from the recommendation table.")
        if want_weather:
            wb, wdesc = self._weather_block(loc)
            if wb:
                blocks.extend(wb); summary += " " + wdesc
        return B.response(summary, blocks)

    def _geographic(self, loc, want_weather):
        g = tools.run_tool("geographic", {})
        beng = g.get("bengaluru_map", {})
        pts = beng.get("points", []) if isinstance(beng, dict) else []
        blocks = []
        if pts:
            mp = B.map_block("Bengaluru demand survey points (real lat/lng)",
                             [12.97, 77.59],
                             [{"lat": p.get("lat"), "lng": p.get("lng"),
                               "weight": p.get("weight"),
                               "label": p.get("label")} for p in pts],
                             zoom=10)
            blocks.append(mp)
        camp = g.get("campus_map", {})
        if isinstance(camp, dict) and camp.get("campuses"):
            rows = [{"name": c.get("name"), "loc": c.get("location_id"),
                     "desc": c.get("description")} for c in camp["campuses"]]
            blocks.append(B.table("Campuses",
                                  [{"key": "name", "label": "Campus"},
                                   {"key": "loc", "label": "ID"},
                                   {"key": "desc", "label": "Notes"}], rows))
        summary = ("Geographic view of the Bengaluru operating area: real survey "
                   "demand points and the campus network. (Campus map coordinates "
                   "are representative metro points.)")
        if want_weather:
            wb, wdesc = self._weather_block(loc)
            if wb:
                blocks.extend(wb); summary += " " + wdesc
        return B.response(summary, blocks)

    def _food(self, loc, want_weather):
        c = tools.run_tool("food_context", {})
        blocks = []
        # generic: any mapping value -> bar chart
        for key, val in c.items():
            if key == "_tool":
                continue
            if isinstance(val, dict) and val:
                b = _bar_from_mapping(key.replace("_", " ").title(), val)
                if b:
                    blocks.append(b)
            elif isinstance(val, list) and val and isinstance(val[0], dict):
                # tabular -> first few rows
                cols = [{"key": k, "label": k} for k in val[0].keys()][:6]
                blocks.append(B.table(key.replace("_", " ").title(), cols, val[:25]))
        if not blocks:
            blocks.append(B.note("No India-context data loaded."))
        summary = ("India food context: household consumption shares (HCES), "
                   "IFCT nutrition reference, food inflation and crop context. "
                   "This layer is real reference data; operational records are "
                   "synthetic and flagged as such in the app.")
        return B.response(summary, blocks)

    def _model(self, loc, want_weather):
        a = tools.run_tool("model_perf", {})
        fm = a.get("feedback_metrics") or {}
        blocks = []
        kpis = []
        if fm.get("mae") is not None:
            kpis.append({"label": "MAE", "value": f"{fm['mae']:.2f}",
                         "tone": "good" if fm.get("baselines_beaten") else "warn"})
        if fm.get("wape") is not None:
            kpis.append({"label": "WAPE", "value": f"{fm['wape']:.1f}%"})
        if fm.get("n") is not None:
            kpis.append({"label": "Scored rows", "value": str(fm["n"])})
        if kpis:
            blocks.append(B.kpi(kpis))
        reg = a.get("model_registry") or []
        if reg:
            cols = [{"key": "model_version", "label": "Version"},
                    {"key": "mae", "label": "MAE"},
                    {"key": "wape", "label": "WAPE"},
                    {"key": "notes", "label": "Notes"}]
            blocks.append(B.table("Model registry", cols, reg[:10]))
        summary = ("Model performance: the champion GBM model drives all "
                   "forecasts. " + (f"WAPE {fm['wape']:.1f}%. " if fm.get('wape') is not None else "")
                   + ("It beats the baselines." if fm.get("baselines_beaten") else
                      "It is currently behind the baselines — retraining may help."))
        return B.response(summary, blocks)

    def _records(self, text, loc, days):
        s = tools.run_tool("data_records", {"days": days, "location_id": loc, "page": 1})
        rows = s.get("items", [])
        total = s.get("total", 0)
        blocks = []
        if not rows:
            return B.response("No rows match that query.", [])
        cols = [{"key": "date", "label": "Date"},
                {"key": "location_id", "label": "Location"},
                {"key": "item_id", "label": "Item"},
                {"key": "meal_period", "label": "Meal"},
                {"key": "actual_demand", "label": "Actual"},
                {"key": "planned_production", "label": "Planned"}]
        blocks.append(B.table(f"Data explorer (showing {len(rows)} of {total:,})",
                              cols, rows[:50]))
        return B.response(
            f"Row-level view of the validated dataset — {total:,} rows in window. "
            "Refine with a location, item, category or meal-period in your question.",
            blocks)

    def _overview(self, text, loc, days, want_weather):
        o = tools.run_tool("overview",
                           {"days": days, "location_id": loc})
        blocks = []
        dtd = o.get("daily_total_demand", {})
        if dtd:
            items = _sorted_items(dtd)
            blocks.append(B.chart("Daily total demand", "line",
                                  [k[5:] for k, _ in items],
                                  [{"name": "Demand", "data": [round(v, 1) for _, v in items],
                                    "color": C["demand"], "area": True}], unit="units"))
        byloc = o.get("demand_by_day_location", {})
        if isinstance(byloc, dict) and byloc.get("series"):
            for lid, series in list(byloc["series"].items())[:6]:
                blocks.append(B.chart(f"Demand · {_name(lid)}", "line",
                                      byloc.get("dates", []),
                                      [{"name": _name(lid), "data": [round(x, 1) if x else 0 for x in series],
                                        "color": C["demand"]}], unit="units"))
        cat = o.get("demand_by_category", {})
        b = _bar_from_mapping("Demand by category", cat, color=C["ai"])
        if b:
            blocks.append(b)
        summary = (f"Operational overview for the last {days} days"
                   + (f" at {_name(loc)}" if loc else "") +
                   ". Ask about demand, surplus, redistribution, weather, food "
                   "context, the model, or a specific campus for a deeper view.")
        if want_weather:
            wb, wdesc = self._weather_block(loc)
            if wb:
                blocks.extend(wb); summary += " " + wdesc
        return B.response(summary, blocks)


# --------------------------------------------------------------------------- #
# Real LLM providers (activate when keys are present)
# --------------------------------------------------------------------------- #

SYSTEM_PROMPT = (
    "You are SensorSpine, an operations assistant for campus/hospitality food "
    "services. You answer using the provided backend tools and respond with "
    "BOTH a short natural-language answer AND a structured visualization plan. "
    "Always call the relevant tools first, then reply with JSON of the form "
    '{"text": "...", "blocks": [...]} where each block is one of: '
    '{"type":"text","markdown":"..."}, {"type":"kpi","items":[{"label","value","tone?"}]}, '
    '{"type":"chart","title","chart_type":"line|bar|donut","categories":[...],'
    '"series":[{"name","data":[...],"color?","area?"}]}, '
    '{"type":"table","title?","columns":[{"key","label"}],"rows":[...]}, '
    '{"type":"map","title?","center":[lat,lng],"zoom?","points":[{"lat","lng","weight?","label?"}]}. '
    "Combine live weather with operational data when relevant. Keep text under 60 words."
)

def _tool_schema() -> list[dict]:
    out = []
    for t in tools.TOOLS:
        props = {k: {"type": "string", "description": v}
                 for k, v in t["params"].items()}
        out.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": {"type": "object", "properties": props,
                               "required": []},
            },
        })
    return out

class HttpLlmProvider:
    """OpenAI-compatible chat-completions with function calling. Also supports
    Anthropic via a thin transform. Reads creds from env."""
    def __init__(self, provider: str):
        self.name = provider
        self.mode = provider  # "openai" | "anthropic"

    def _headers(self) -> dict:
        if self.mode == "anthropic":
            return {"x-api-key": os.environ["ANTHROPIC_API_KEY"],
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"}
        key = (os.environ.get("OPENAI_API_KEY") or
               os.environ.get("AZURE_OPENAI_API_KEY"))
        return {"Authorization": f"Bearer {key}",
                "content-type": "application/json"}

    def _url(self) -> str:
        if self.mode == "anthropic":
            return "https://api.anthropic.com/v1/messages"
        if os.environ.get("AZURE_OPENAI_ENDPOINT"):
            return (f"{os.environ['AZURE_OPENAI_ENDPOINT'].rstrip('/')}"
                    f"/openai/deployments/{os.environ.get('AZURE_OPENAI_DEPLOYMENT','gpt-4o')}"
                    "/chat/completions?api-version=2024-02-15-preview")
        return "https://api.openai.com/v1/chat/completions"

    def _model(self) -> str:
        if self.mode == "anthropic":
            return os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-0")
        if os.environ.get("AZURE_OPENAI_DEPLOYMENT"):
            return os.environ["AZURE_OPENAI_DEPLOYMENT"]
        return os.environ.get("OPENAI_MODEL", "gpt-4o")

    def respond(self, message: str, history: list | None = None) -> dict:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for h in (history or [])[-6:]:
            messages.append({"role": h.get("role", "user"),
                             "content": h.get("content", "")})
        messages.append({"role": "user", "content": message})

        # 1) let the model call tools
        req = {"model": self._model(), "messages": messages,
               "tools": _tool_schema(), "tool_choice": "auto"}
        if self.mode == "anthropic":
            req = {"model": self._model(), "system": SYSTEM_PROMPT,
                   "messages": messages[1:], "tools": _anthropic_tools(),
                   "max_tokens": 1500}
        resp = self._post(self._url(), req)
        tool_calls = self._extract_tool_calls(resp)
        if tool_calls:
            for call in tool_calls:
                obs = tools.run_tool(call["name"], call.get("args", {}))
                messages.append({"role": "tool", "name": call["name"],
                                 "content": json.dumps(obs, default=str)})
            # 2) final answer with blocks
            req2 = dict(req)
            req2["messages"] = messages
            req2.pop("tools", None); req2.pop("tool_choice", None)
            if self.mode == "anthropic":
                req2.pop("system", None)
            resp = self._post(self._url(), req2)
        return self._extract_json(resp)

    # --- transport ----------------------------------------------------------
    def _post(self, url, payload) -> dict:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, headers=self._headers(),
                                     method="POST")
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.load(r)

    def _extract_tool_calls(self, resp: dict) -> list[dict]:
        if self.mode == "anthropic":
            out = []
            for b in resp.get("content", []):
                if b.get("type") == "tool_use":
                    out.append({"name": b["name"], "args": b.get("input", {})})
            return out
        msg = resp.get("choices", [{}])[0].get("message", {})
        return [{"name": c["function"]["name"],
                 "args": json.loads(c["function"].get("arguments", "{}"))}
                for c in msg.get("tool_calls", [])]

    def _extract_json(self, resp: dict) -> dict:
        if self.mode == "anthropic":
            txt = "".join(b.get("text", "") for b in resp.get("content", [])
                          if b.get("type") == "text")
        else:
            txt = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
        try:
            return json.loads(txt)
        except Exception:
            return {"text": txt, "blocks": []}


def _anthropic_tools() -> list[dict]:
    out = []
    for t in tools.TOOLS:
        props = {k: {"type": "string", "description": v}
                 for k, v in t["params"].items()}
        out.append({"name": t["name"], "description": t["description"],
                    "input_schema": {"type": "object", "properties": props}})
    return out


def get_provider():
    prov = os.environ.get("SENSORSPINE_LLM_PROVIDER", "").lower()
    if prov == "openai" and os.environ.get("OPENAI_API_KEY"):
        return HttpLlmProvider("openai")
    if prov == "azure" and os.environ.get("AZURE_OPENAI_API_KEY"):
        return HttpLlmProvider("openai")  # openai-compatible
    if prov == "anthropic" and os.environ.get("ANTHROPIC_API_KEY"):
        return HttpLlmProvider("anthropic")
    return FallbackProvider()
