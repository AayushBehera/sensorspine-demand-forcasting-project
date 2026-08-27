import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    # Hermetic model artifact location so tests never touch data/model.joblib
    from app import service
    old_path = service.MODEL_PATH
    service.MODEL_PATH = tmp_path_factory.mktemp("m") / "model.joblib"
    try:
        from app.main import app
        with TestClient(app) as c:
            yield c
    finally:
        service.MODEL_PATH = old_path


def test_health(client):
    r = client.get("/api/health").json()
    assert {"database", "raw_data", "clean_data", "model"} <= set(r["checks"])


def test_generate_and_validate(client):
    r = client.post("/api/data/generate?seed=5&days=70")
    assert r.status_code == 200
    body = r.json()
    assert body["generated"]["rows"] > 0
    rep = client.post("/api/data/validate").json()
    assert rep["health"]["healthy"] is True


def test_thresholds_validation(client):
    bad = client.put("/api/config/thresholds",
                     json={"thresholds": {"nonsense": 1}})
    assert bad.status_code == 400
    ok = client.put("/api/config/thresholds",
                    json={"thresholds": {"min_transfer_units": 4}})
    assert ok.status_code == 200
    assert ok.json()["thresholds"]["min_transfer_units"] == 4


def test_day_run_requires_model(client):
    # fresh tmp MODEL_PATH does not exist -> must fail cleanly with 409
    if not service_artifact_exists():
        r = client.post("/api/day/run", json={})
        assert r.status_code == 409
        assert r.json()["detail"]["error"] == "model_unavailable"


def service_artifact_exists():
    return False  # tmp artifact deleted between modules by pytest


def test_train_and_full_loop(client):
    tr = client.post("/api/model/train")
    assert tr.status_code == 200, tr.text
    summary = tr.json()
    assert summary["baselines_beaten"] is True
    assert summary["metrics_test"]["candidate_gbm"]["mae"] >= 0

    run = client.post("/api/day/run", json={})
    assert run.status_code == 200, run.text
    payload = run.json()
    assert payload["stored"]["forecasts"] > 0
    assert payload["assessment_summary"]["series_total"] > 0

    recs = client.get("/api/recommendations?limit=10").json()
    assert recs["count"] >= 1
    rid = recs["recommendations"][0]["recommendation_id"]
    dec = client.post(f"/api/recommendations/{rid}/decision",
                      json={"action": "accepted", "units_moved": 3})
    assert dec.status_code == 200
    again = client.post(f"/api/recommendations/{rid}/decision",
                        json={"action": "rejected"})
    assert again.status_code == 404   # already decided

    bt = client.post("/api/backtest/simulate?days=2")
    assert bt.status_code == 200
    sync = client.post("/api/outcomes/sync")
    assert sync.status_code == 200
    fm = sync.json()["feedback_metrics"]
    assert fm["forecasts_evaluated"] > 0
    assert fm["forecast_mae"] is not None


def test_invalid_inputs(client):
    assert client.post("/api/day/run", json={"date": "garbage"}).status_code == 422
    assert client.post("/api/recommendations/999999/decision",
                       json={"action": "accepted"}).status_code == 404
    assert client.post(
        "/api/recommendations/1/decision", json={"action": "maybe"}
    ).status_code == 422
    assert client.post("/api/outcomes/manual", json={
        "service_date": "2026-08-01", "location_id": "LOC-X",
        "item_id": "ITM-Y", "meal_period": "brunch", "actual_demand": 1
    }).status_code == 422


def test_manual_outcome_and_supply_plans(client):
    ok = client.post("/api/outcomes/manual", json={
        "service_date": "2026-07-01", "location_id": "LOC-CAF-M",
        "item_id": "ITM-PASTA", "meal_period": "lunch", "actual_demand": 123})
    assert ok.status_code == 200
    plans = client.post("/api/supply-plans", json=[{
        "service_date": "2099-01-01", "location_id": "LOC-CAF-M",
        "item_id": "ITM-PASTA", "meal_period": "lunch", "supply": 88}])
    assert plans.status_code == 200


# --- additive paginated read endpoints --------------------------------------------

def _ensure_seeded(client):
    """Daily-loop artifacts for the read-endpoint tests below.

    Normally test_train_and_full_loop leaves these behind, but that test's
    baselines_beaten assertion is environment-sensitive; seed independently
    (idempotently) so read endpoints are verifiable either way."""
    h = client.get("/api/health").json()["checks"]
    if not h["clean_data"]:
        assert client.post("/api/data/generate?seed=5&days=70").status_code == 200
    if not h["model"]:
        assert client.post("/api/model/train").status_code == 200
    if client.get("/api/forecasts?page_size=1").json()["total"] == 0:
        r = client.post("/api/day/run", json={})
        assert r.status_code == 200, r.text
        recs = client.get("/api/recommendations?limit=1").json()
        if recs["count"]:
            rid = recs["recommendations"][0]["recommendation_id"]
            assert client.post(f"/api/recommendations/{rid}/decision", json={
                "action": "accepted", "units_moved": 3}).status_code == 200
    if client.get("/api/outcomes?page_size=1").json()["total"] == 0:
        assert client.post("/api/backtest/simulate?days=2").status_code == 200
        assert client.post("/api/outcomes/sync").status_code == 200


def _assert_envelope(body):
    assert {"items", "total", "page", "page_size"} <= set(body)
    assert isinstance(body["total"], int) and body["page"] >= 1


def _empty_last_page(client, url, total, page_size):
    last = -(-total // page_size) + 1
    return client.get(f"{url}{'&' if '?' in url else '?'}"
                      f"page={last}&page_size={page_size}").json()["items"]


def test_forecasts_endpoint(client):
    _ensure_seeded(client)
    r = client.get("/api/forecasts?page_size=50")
    assert r.status_code == 200
    body = r.json()
    _assert_envelope(body)
    assert body["total"] > 0 and len(body["items"]) == 50
    dates = [i["service_date"] for i in body["items"]]
    assert dates == sorted(dates, reverse=True)

    loc = body["items"][0]["location_id"]
    filt = client.get(f"/api/forecasts?location_id={loc}&page_size=1000").json()
    assert 0 < filt["total"] < body["total"]
    assert all(i["location_id"] == loc for i in filt["items"])

    none = client.get("/api/forecasts?location_id=NOPE").json()
    _assert_envelope(none)
    assert none["total"] == 0 and none["items"] == []
    assert client.get("/api/forecasts?page=0").status_code == 422
    assert client.get("/api/forecasts?page_size=1001").status_code == 422
    assert client.get("/api/forecasts?start=bad-date").status_code == 422
    assert _empty_last_page(client, "/api/forecasts?page_size=7",
                            body["total"], 7) == []


def test_surplus_history_endpoint(client):
    _ensure_seeded(client)
    body = client.get("/api/surplus/history?page_size=10").json()
    _assert_envelope(body)
    assert body["total"] > 0 and len(body["items"]) == 10

    st = body["items"][0]["status"]
    if st:
        filt = client.get(f"/api/surplus/history?status={st}&page_size=1000").json()
        assert 0 < filt["total"] <= body["total"]
        assert all(i["status"] == st for i in filt["items"])
    none = client.get("/api/surplus/history?status=nope").json()
    assert none["total"] == 0 and none["items"] == []
    assert _empty_last_page(client, "/api/surplus/history?page_size=5",
                            body["total"], 5) == []


def test_outcomes_endpoint(client):
    _ensure_seeded(client)
    body = client.get("/api/outcomes?page_size=25").json()
    _assert_envelope(body)
    assert body["total"] > 0

    d0 = body["items"][0]["service_date"]
    rng = client.get(f"/api/outcomes?start={d0}&end={d0}&page_size=1000").json()
    assert rng["total"] >= 1 and rng["total"] <= body["total"]
    assert all(i["service_date"] == d0 for i in rng["items"])

    man = client.get("/api/outcomes?source=manual&page_size=1000").json()
    assert man["total"] >= 1
    assert all(i["source"] == "manual" for i in man["items"])

    loc = body["items"][0]["location_id"]
    flt = client.get(f"/api/outcomes?location_id={loc}&page_size=1000").json()
    assert 0 < flt["total"] <= body["total"]
    assert all(i["location_id"] == loc for i in flt["items"])
    assert _empty_last_page(client, "/api/outcomes?page_size=9",
                            body["total"], 9) == []


def test_supply_plans_get_endpoint(client):
    # depends on plan posted by test_manual_outcome_and_supply_plans above
    body = client.get("/api/supply-plans?start=2099-01-01&end=2099-01-01").json()
    _assert_envelope(body)
    assert body["total"] == 1
    item = body["items"][0]
    assert item["location_id"] == "LOC-CAF-M" and item["supply"] == 88
    assert client.get("/api/supply-plans?location_id=NOPE").json()[
        "items"] == []
    assert client.get("/api/supply-plans?page=2&page_size=1").json()[
        "items"] == []


def test_data_records_endpoint(client):
    _ensure_seeded(client)
    r = client.get("/api/data/records?page_size=30")
    assert r.status_code == 200
    body = r.json()
    _assert_envelope(body)
    assert body["count"] == body["total"]
    assert body["total"] > 0 and len(body["items"]) == 30
    dates = [i["date"] for i in body["items"]]
    assert dates == sorted(dates, reverse=True)

    cat = body["items"][0]["category"]
    filt = client.get(f"/api/data/records?category={cat}&page_size=1000").json()
    assert 0 < filt["total"] < body["total"]

    srch = client.get("/api/data/records?search=caf&page_size=1000").json()
    assert 0 < srch["total"] < body["total"]
    assert all("caf" in str(i["location_id"]).casefold()
               or "caf" in str(i["item_id"]).casefold()
               or "caf" in str(i["category"]).casefold()
               for i in srch["items"])

    assert client.get("/api/data/records?search=zzznope").json()[
        "items"] == []
    assert client.get("/api/data/records?page=-1").status_code == 422


def test_analytics_filters(client):
    _ensure_seeded(client)
    base = client.get("/api/analytics").json()
    filt = client.get("/api/analytics?location_id=LOC-CAF-M").json()
    assert sum(base["demand_by_day"].values()) >= sum(
        filt["demand_by_day"].values())
    # feedback/model registry are DB-derived and must be unaffected
    assert filt["feedback_metrics"] == base["feedback_metrics"]
    assert len(filt["model_registry"]) == len(base["model_registry"])
    sample = [h for h in filt["forecast_vs_actual_sample"]]
    assert all(h["l"] == "LOC-CAF-M" for h in sample)

    mp = client.get("/api/analytics?meal_period=lunch").json()
    assert sum(mp["demand_by_day"].values()) < sum(
        base["demand_by_day"].values())

    again = client.get("/api/analytics").json()
    assert again == base


def test_dashboard_overview_filters(client):
    _ensure_seeded(client)
    base = client.get("/api/dashboard/overview").json()
    r = client.get("/api/dashboard/overview?location_id=LOC-CAF-M")
    assert r.status_code == 200
    filt = r.json()
    o, fo = base["overview"], filt["overview"]
    assert 0 < fo["window"]["rows"] < o["window"]["rows"]
    assert set(o["demand_by_meal"]) == set(fo["demand_by_meal"])
    # map/context payloads stay global
    assert len(base["campus_map"]["nodes"]) == len(filt["campus_map"]["nodes"])
    assert list(base["india_context"]) == list(filt["india_context"])
    # defaults preserve current output exactly
    assert client.get("/api/dashboard/overview").json() == base


def test_chat_units_redistributed_bugfix(client):
    _ensure_seeded(client)
    # The chat must answer redistribution questions from the real recommendations
    # table (no fabricated columns) and return the new {text, blocks, engine} shape.
    r = client.post("/api/chat", json={
        "message": "show pending redistribution recommendations"})
    assert r.status_code == 200
    body = r.json()
    assert "text" in body and isinstance(body.get("blocks"), list)
    assert body.get("engine")
    tbl = next((b for b in body["blocks"] if b["type"] == "table"), None)
    assert tbl and tbl["rows"], "redistribution should render a real table"
