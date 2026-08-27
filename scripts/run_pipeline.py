"""One-command pipeline bootstrap: fresh environment -> working system.

    python scripts/run_pipeline.py [--seed 42] [--days 180] [--skip-backtest]

Generates the operational dataset (clearly labelled as synthetic until live
feeds are connected), validates it, trains models with a time-aware split,
runs the Forecast-to-Action loop for the next service day, replays a 14-day
walk-forward backtest, records outcomes, and prints the evaluation summary.

This is the canonical entrypoint for both first-time provisioning and
repeatable rebuilds; scripts/run_demo.py remains as a compatibility alias.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, service  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Sensorspine pipeline bootstrap")
    ap.add_argument("--seed", type=int,
                    default=int(__import__("os").environ.get("FSDB_DATA_SEED", "42")))
    ap.add_argument("--days", type=int,
                    default=int(__import__("os").environ.get("FSDB_DATA_DAYS", "180")))
    ap.add_argument("--skip-backtest", action="store_true",
                    help="provision only; skip forecast-to-action + backtest stages")
    args = ap.parse_args()

    db.init_db()
    conn = db.connect()
    try:
        db.upsert_reference(conn, service.LOCATIONS_REF, service.ITEMS_REF)
        conn.commit()
    finally:
        conn.close()

    print("[1/6] generating operational dataset ...")
    print("   ", service.regenerate_data(seed=args.seed, days=args.days))
    print("[2/6] validating ...")
    report = service.run_validation()
    print(f"    rows {report['rows_in']} -> {report['rows_out']} | "
          f"health: {report['health']['healthy']}")
    if not service.load_artifact():
        print("[3/6] training (baselines vs GBM & ridge candidates) ...")
        summary = service.train_pipeline(seed=args.seed)
        best = min(summary["metrics_test"].items(), key=lambda kv: kv[1]["mae"])
        print(f"    winner on unseen test window: {best[0]} "
              f"(MAE {best[1]['mae']:.2f}, WAPE {best[1]['wape_pct']:.1f}%)")
        print(f"    selected strategy: {summary['selected_strategy']} | "
              f"baselines beaten: {summary['baselines_beaten']}")
    else:
        print("[3/6] model artifact found - skipping training")
    if args.skip_backtest:
        print("[6/6] done (--skip-backtest).")
        return
    print("[4/6] running forecast-to-action for next service day ...")
    run = service.run_day(service.next_service_dates(1))
    s = run["assessment_summary"]
    print(f"    expected demand {s['total_predicted_demand']:.0f} units | "
          f"expected surplus {s['total_expected_surplus']:.0f} | "
          f"shortage risk {s['at_risk_units']:.0f} units")
    print(f"    recommendations generated: {len(run['recommendations'])}")
    top = run["recommendations"][0] if run["recommendations"] else None
    if top:
        print(f"    TOP: move {top['transfer_quantity']:.0f} units of "
              f"{top['source_item']} {top['source_location']} -> "
              f"{top['destination_location']} (score {top['score']})")
        print(f"         why: {top['reason']}")
    print("[5/6] walk-forward backtest (last 14 days) ...")
    bt = service.simulate_backtest(14)
    fm = bt["feedback_metrics"]
    print(f"    evaluated forecasts vs actuals: {fm['forecasts_evaluated']}")
    print(f"    MAE {fm['forecast_mae']} | WAPE {fm['forecast_wape_pct']}% | "
          f"bias {fm['forecast_bias']}")
    print("[6/6] done.")
    print("\nStart the server:  uvicorn app.main:app --port 8000"
          "  then open http://127.0.0.1:8000"
          "  (set FSDB_API_KEY before exposing beyond localhost)")


if __name__ == "__main__":
    main()
