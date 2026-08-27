"""Tests for the India data-integration layer: taxonomy, scenarios,
and the context bridge. All offline and deterministic."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_pipeline.taxonomy import (EXCLUDE_CODES, HCES_ITEM_MAP, map_cuisine_token,
                                    map_item, unit_for)


# --- taxonomy -----------------------------------------------------------------

def test_verified_hces_codes_map_to_expected_categories():
    assert map_item("101")[1] == "rice_cereals"       # rice - PDS
    assert map_item("102")[2] == "high"               # rice - other
    assert map_item("140")[1] == "dal_pulses"         # arhar/tur
    assert map_item("195")[1] == "chicken_meat"       # chicken
    assert map_item("280")[1] == "served_processed"   # cooked meals purchased
    assert map_item("256")[0].startswith("dry chillies")


def test_unknown_code_is_flagged_not_fabricated():
    name, cat, conf = map_item("999")
    assert (name, cat, conf) == ("unknown", "other", "low")
    assert "999" not in HCES_ITEM_MAP


def test_subtotals_and_unclear_aggregates_are_excluded():
    for code in ("129", "159", "269", "279", "289"):
        assert code in EXCLUDE_CODES          # group sub-totals
    for code in ("092", "093", "094", "095"):  # ambiguous internal aggregates
        assert code in EXCLUDE_CODES


def test_units_preserve_heterogeneous_measurement():
    assert unit_for("190") == "number"   # eggs
    assert unit_for("160") == "litre"    # milk
    assert unit_for("256") == "gram"     # dry chillies
    assert unit_for("200") == "kg"       # potato


def test_cuisine_keyword_mapping_is_transparent():
    assert map_cuisine_token("Biryani, South Indian") is not None
    assert map_cuisine_token("Continental") is None


# --- scenario layer ------------------------------------------------------------

@pytest.fixture(scope="module")
def scenario_results():
    from data_pipeline.scenarios import run_all
    return run_all()


def test_actionable_scenarios_produce_recommendations(scenario_results):
    for s in ("campus_event", "weather_disruption", "redistribution_opportunity",
              "multiple_candidates"):
        assert scenario_results[s]["recommendations"] >= 1, f"{s} should transfer"
        assert scenario_results[s]["top_score"] > 0


def test_non_actionable_scenarios_stay_quiet(scenario_results):
    for s in ("normal_day", "festival_spike", "shortage_everywhere",
              "overproduction", "no_eligible_destination"):
        assert scenario_results[s]["recommendations"] == 0, \
            f"{s} must not propose transfers"


def test_greedy_allocation_respects_surplus_cap(scenario_results):
    # multiple_candidates: donor surplus 140, needs 70 + 40 -> 110 moved.
    mc = scenario_results["multiple_candidates"]
    assert mc["total_transferable_units"] <= 140
    assert mc["total_transferable_units"] == 110.0


# --- context bridge ---------------------------------------------------------------

def test_context_status_reports_provenance_when_present():
    from app.india_context import context_status
    status = context_status()
    assert set(status) >= {"datasets", "quality_reports"}
    if status["datasets"]:  # populated by data_pipeline.normalize
        names = {d["dataset_name"] for d in status["datasets"]}
        assert "hces2023_24_bengaluru_official" in names


# --- user-collected layers ---------------------------------------------------------

def test_india_facts_surface_from_user_datasets():
    from app.india_context import context_status
    facts = context_status().get("india_facts", {})
    wb = facts.get("waste_benchmark_unep")
    if wb:  # present once data_pipeline.normalize has run
        assert wb["food_service_kg_pc_yr"] == 28.0
        assert wb["confidence"] == "Very Low Confidence"
    inf = facts.get("latest_food_inflation")
    if inf:
        assert -20 <= inf["inflation_pct"] <= 40   # sane inflation band


def test_online_food_survey_normalized():
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent / ("data/processed/restaurant/"
                                                  "online_food_orders_bangalore.csv")
    if not p.exists():
        pytest.skip("normalize not run yet")
    import pandas as pd
    df = pd.read_csv(p)
    assert len(df) == 388
    assert set(df["ordered_online"].unique()) <= {True, False}
    assert df["city"].nunique() == 1


def test_market_arrivals_preserved_as_district_year():
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent / ("data/processed/supply/"
                                                  "market_arrivals_district_year.csv")
    if not p.exists():
        pytest.skip("normalize not run yet")
    import pandas as pd
    df = pd.read_csv(p)
    assert {"district", "year", "arrivals_qty"} <= set(df.columns)
    assert (df["arrivals_qty"] >= 0).all()      # no negatives silently kept
    assert df["unit_confidence"].iloc[0] == "medium"


def test_uncertain_metric_is_flagged_not_interpreted():
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent / ("data/processed/supply/"
                                                  "rs249_as287b_state_year_preserved.csv")
    if not p.exists():
        pytest.skip("normalize not run yet")
    import pandas as pd
    df = pd.read_csv(p)
    assert df["interpretation_uncertain"].all()
