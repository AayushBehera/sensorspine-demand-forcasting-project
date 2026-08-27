"""Redistribution intelligence.

Turns surplus assessments into RANKED, EXPLAINABLE transfer recommendations.

Scoring (all components normalised to 0..1, weights from config):
    need           how badly the destination is short (units at risk vs demand)
    quantity_fit   usable fraction of the source surplus
    urgency        time left in the destination service window + severity
    proximity      decays with distance between locations
    compatibility  same item category / meal period transfer better

Final score = 100 * weighted sum. Every recommendation ships its factor
breakdown and a human-readable reason string so an operator can audit WHY.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from .config import get_thresholds

# Service windows in local hours; used for time-remaining urgency.
SERVICE_WINDOWS = {
    "breakfast": (7.5, 10.0),
    "lunch": (11.5, 14.5),
    "dinner": (17.0, 19.75),
}


def _time_remaining_fraction(meal_period: str, now: datetime) -> float:
    start_h, end_h = SERVICE_WINDOWS.get(meal_period, (11.5, 14.5))
    t = now.hour + now.minute / 60.0
    if t >= end_h:
        return 0.0          # window closed
    if t <= start_h:
        return 1.0
    return (end_h - t) / (end_h - start_h)


def _proximity(distance_km: float | None, max_km: float) -> float:
    if distance_km is None:
        return 0.5          # unknown logistics: neutral, flagged in reason
    return float(max(0.0, 1.0 - distance_km / max_km))


def _compatibility(src_cat: str, src_period: str, dst_cat: str, dst_period: str) -> float:
    same_cat = src_cat == dst_cat
    same_period = src_period == dst_period
    return {(True, True): 1.0, (True, False): 0.7,
            (False, True): 0.45, (False, False): 0.2}[(same_cat, same_period)]


FACTOR_LABELS = {
    "need": "destination shortage risk",
    "quantity_fit": "most of the surplus is usable",
    "urgency": "limited time remaining in service window",
    "proximity": "short transfer distance",
    "compatibility": "compatible item type and meal period",
}


def build_recommendations(assessment: pd.DataFrame,
                          distances: pd.DataFrame | None,
                          thresholds: dict | None = None,
                          now: datetime | None = None) -> list[dict]:
    """Rank feasible source->destination transfers for one service date."""
    th = thresholds or get_thresholds()
    weights = th["weights"]
    min_units = th["min_transfer_units"]
    now = now or datetime.now()
    has_date_col = "date" in assessment.columns
    if has_date_col:
        dates = sorted(assessment["date"].unique())
    else:
        dates = [None]

    dist_lookup: dict[tuple[str, str], float] = {}
    if distances is not None and len(distances):
        for _, r in distances.iterrows():
            dist_lookup[(r["from_location"], r["to_location"])] = float(r["distance_km"])

    recs: list[dict] = []

    def _iso(d):
        return str(pd.Timestamp(d).date()) if d is not None else None

    for date_val in dates:
        frame = assessment[assessment["date"] == date_val] if has_date_col else assessment
        sources = frame[frame["surplus"] > 0]
        dests = frame[(frame["status"].isin(["shortage", "low_surplus", "balanced"]))
                      & (frame["supply"] - frame["predicted_demand"] < 0)]
        # A destination's need must exceed what it already expects to have.
        for _, src in sources.iterrows():
            for _, dst in dests.iterrows():
                if src["location_id"] == dst["location_id"]:
                    continue
                if src["item_id"] != dst["item_id"]:
                    continue
                need = max(0.0, float(dst["predicted_demand"]) - float(dst["supply"]))
                if need <= 0:
                    continue
                qty = min(float(src["surplus"]), need)
                if qty < min_units:
                    continue

                f_need = min(1.0, need / max(float(dst["predicted_demand"]), 1.0))
                f_fit = qty / max(float(src["surplus"]), 1.0)
                frac = (_time_remaining_fraction(str(dst["meal_period"]), now)
                        if (has_date_col and str(date_val) == str(pd.Timestamp(now).date()))
                        or not has_date_col else 1.0)
                severe = f_need >= 0.25
                f_urgency = min(1.0, (1.0 - frac) * 0.6 + (0.4 if severe else 0.0))
                distance = dist_lookup.get((src["location_id"], dst["location_id"]))
                f_prox = _proximity(distance, th["max_distance_km"])
                f_comp = _compatibility(str(src["category"]), str(src["meal_period"]),
                                        str(dst["category"]), str(dst["meal_period"]))

                score = 100.0 * (
                    weights["need"] * f_need
                    + weights["quantity_fit"] * f_fit
                    + weights["urgency"] * f_urgency
                    + weights["proximity"] * f_prox
                    + weights["compatibility"] * f_comp
                )

                contributions = {
                    "need": weights["need"] * f_need,
                    "quantity_fit": weights["quantity_fit"] * f_fit,
                    "urgency": weights["urgency"] * f_urgency,
                    "proximity": weights["proximity"] * f_prox,
                    "compatibility": weights["compatibility"] * f_comp,
                }
                top = sorted(contributions.items(), key=lambda kv: kv[1],
                             reverse=True)[:3]
                reasons = [f"{FACTOR_LABELS[k]} (+{round(v * 100)})" for k, v in top]

                urgency_label = ("High" if f_urgency >= 0.55 or f_need >= 0.5
                                 else "Medium" if score >= 50 else "Low")

                recs.append({
                    **({"date": _iso(date_val)} if has_date_col else {}),
                    "source_location": src["location_id"],
                    "source_item": src["item_id"],
                    "available_surplus": round(float(src["surplus"]), 1),
                    "destination_location": dst["location_id"],
                    "predicted_need": round(need, 1),
                    "transfer_quantity": round(qty, 1),
                    "score": round(score, 1),
                    "urgency": urgency_label,
                    "reason": "; ".join(reasons),
                    "factors": {k: round(v, 3) for k, v in contributions.items()},
                    "distance_km": distance,
                    "status": "pending",
                })

    recs.sort(key=lambda r: r["score"], reverse=True)
    # Greedy allocation: each source's surplus and each destination's need
    # are consumed at most once across accepted recommendations.
    filled_dest: dict[tuple[str, str], float] = {}
    final: list[dict] = []
    for r in recs:
        s_key = (r["source_location"], r["source_item"])
        d_loc_item = (r["destination_location"], r["source_item"])
        used_from_source = sum(
            x["transfer_quantity"] for x in final
            if (x["source_location"], x["source_item"]) == s_key)
        remaining_surplus = r["available_surplus"] - used_from_source
        qty = min(r["transfer_quantity"], remaining_surplus)
        taken = filled_dest.get(d_loc_item, 0.0)
        room = r["predicted_need"] - taken
        qty = min(qty, room)
        if qty < th["min_transfer_units"]:
            continue
        r["transfer_quantity"] = round(qty, 1)
        filled_dest[d_loc_item] = taken + r["transfer_quantity"]
        final.append(r)

    return final
