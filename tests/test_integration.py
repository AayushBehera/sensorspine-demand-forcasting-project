"""Integration test: data -> forecast -> surplus -> recommendation -> DB."""
from app import db, service
from app.features import build_features, temporal_split
from app.forecasting import forecast_future, train_and_evaluate
from app.surplus import assess, estimate_supply, summarize_day
from app.recommend import build_recommendations


def test_end_to_end_pipeline(easy_data, tmp_path, monkeypatch):
    monkeypatch.setattr(service, "MODEL_PATH", tmp_path / "m.joblib")
    db.init_db()
    conn = db.connect()
    try:
        conn.execute("INSERT OR IGNORE INTO locations VALUES('L1','Loc 1','test')")
        conn.execute("INSERT OR IGNORE INTO locations VALUES('L2','Loc 2','test')")
        conn.execute("INSERT OR IGNORE INTO items VALUES('I1','Item 1','hot_meal')")
        conn.commit()
    finally:
        conn.close()

    # features + honest split
    feat = build_features(easy_data)
    tr, va, te = temporal_split(feat)
    assert len(tr) and len(va) and len(te)

    res = train_and_evaluate(tr, va, te)
    assert res["baselines_beaten"]

    # forecast next day from history only
    last = str(easy_data["date"].max().date())
    fc = forecast_future(easy_data, [last], res)
    a = assess(fc, estimate_supply(easy_data))
    s = summarize_day(a)
    assert s["series_total"] == len(fc) > 0

    recs = build_recommendations(a, service.load_distances())
    for r in recs:
        assert r["score"] > 0
        assert r["transfer_quantity"] > 0
        assert r["reason"]

    # persistence round-trip
    conn = db.connect()
    try:
        n = db.save_forecasts(conn, fc, "test-version")
        db.save_assessments(conn, a, "test-version")
        ids = db.save_recommendations(conn, recs, "test-version")
        conn.commit()
        assert n == len(fc) and len(ids) == len(recs)
        stored = conn.execute(
            "SELECT COUNT(*) c FROM forecasts WHERE model_version='test-version'"
        ).fetchone()["c"]
        assert stored == len(fc)
        if ids:
            assert db.decide_recommendation(conn, ids[0], "accepted",
                                            units_moved=1.0)
            conn.commit()
            status = conn.execute(
                "SELECT status FROM recommendations WHERE recommendation_id=?",
                (ids[0],)).fetchone()["status"]
            assert status == "accepted"
    finally:
        conn.close()


def test_outcomes_sync_and_feedback(easy_data):
    db.init_db()
    conn = db.connect()
    try:
        stats = db.sync_outcomes(conn, easy_data)
        conn.commit()
        assert stats["outcome_rows_total"] >= len(easy_data)
        fm = db.feedback_metrics(conn)
        assert fm["forecast_wape_pct"] is None or fm["forecast_wape_pct"] >= 0
    finally:
        conn.close()
