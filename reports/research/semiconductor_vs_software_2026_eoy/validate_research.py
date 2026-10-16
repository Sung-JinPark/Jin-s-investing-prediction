"""Independent read-only audit from preserved CSV/JSON (no model refitting)."""
from __future__ import annotations
import csv
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OLD = ROOT.parent / "sector_outlook_2026_eoy"
REPO = ROOT.parents[2]


def read(p):
    return json.loads(Path(p).read_text(encoding="utf-8-sig"))


def run():
    a, q = read(ROOT / "analytical_results.json"), read(ROOT / "quantitative_ml.json")
    checks = []
    def check(name, condition, detail=None):
        checks.append({"name": name, "pass": bool(condition), "detail": detail})
    prices = {}
    for s in ("SOXX", "IGV", "SPY"):
        rows = list(csv.DictReader((ROOT / "price_inputs" / f"{s}_adjusted_history.csv").open(encoding="utf-8-sig", newline="")))
        prices[s] = {x["date"]: float(x["adj_close"]) for x in rows}
        dates = list(prices[s])
        check(f"{s}_unique_chronological", len(dates) == len(rows) and dates == sorted(dates))
        check(f"{s}_no_future_session", dates[-1] == "2026-10-09")
        check(f"{s}_positive_finite", all(math.isfinite(v) and v > 0 for v in prices[s].values()))
    dates = list(prices["SOXX"])
    check("synchronized_three_series", all(list(p) == dates for p in prices.values()))
    oos = list(csv.DictReader((ROOT / "ml_oos_predictions.csv").open(encoding="utf-8-sig", newline="")))
    baselines = {}
    index = {d: i for i, d in enumerate(dates)}
    for hkey, model in q["horizons"].items():
        h = int(hkey)
        rows = [x for x in oos if int(x["horizon_sessions"]) == h]
        errors, deltas = [], []
        for r in rows:
            d, end = r["date"], r["label_end_date"]
            expected = math.log(prices["SOXX"][end] / prices["SOXX"][d]) - math.log(prices["IGV"][end] / prices["IGV"][d])
            errors.append(abs(expected - float(r["target_log_ratio"])))
            deltas.append(index[end] - index[d])
        check(f"h{h}_label_recomputed_independently", max(errors) < 1e-12, max(errors))
        check(f"h{h}_all_label_horizons", set(deltas) == {h})
        check(f"h{h}_oos_count", len(rows) == model["daily_origin_count"])
        check(f"h{h}_nonoverlapping_anchor_count", len(rows[::h]) == model["nonoverlapping_anchor_count"])
        check(f"h{h}_purged_folds", all(f["last_train_label_end"] < f["first_test_origin"] for f in model["folds"]))
        check(f"h{h}_latest_training_label_known", model["current_exploratory_outputs"]["last_train_label_end"] < q["price_as_of"])
        check(f"h{h}_current_outputs_not_promoted", model["current_exploratory_outputs"]["prospective_usable"] is False)
        labels = [int(r["label"]) for r in rows]
        check(f"h{h}_all_labels_correct", all(int(float(r["target_log_ratio"]) > 0) == int(r["label"]) for r in rows))
        for name, col in (("logistic", "logistic_probability"), ("random_forest", "random_forest_probability"),
                          ("expanding_class_frequency_baseline", "baseline_probability")):
            p = [float(r[col]) for r in rows]
            brier = sum((v - label) ** 2 for v, label in zip(p, labels)) / len(rows)
            check(f"h{h}_{name}_brier_independent", abs(brier - model["models"][name]["brier"]) < 1e-12)
            check(f"h{h}_{name}_fraction_bounds", all(math.isfinite(v) and 0 <= v <= 1 for v in p))
        for name, col in (("ridge", "ridge_prediction"), ("expanding_mean_baseline", "baseline_mean")):
            mae = sum(abs(float(r[col]) - float(r["target_log_ratio"])) for r in rows) / len(rows)
            check(f"h{h}_{name}_mae_independent", abs(mae - model["models"][name]["mae"]) < 1e-12)
        baselines[hkey] = {"role": "additional_naive_baselines_not_new_forecasts", "constant_half_probability_brier": .25,
                           "zero_relative_log_forecast_mae": sum(abs(float(r["target_log_ratio"])) for r in rows) / len(rows),
                           "oos_rows": len(rows), "probability_unit": "fraction", "mae_unit": "log_gross_return_ratio"}
    check("remaining_sessions_57", q["remaining_sessions"] == a["calendar"]["remaining_us_sessions"] == 57)
    check("no_calibrated_winner_claim", a["summary"]["calibrated_winner_probability"] is None)
    check("strict_PIT_gate_blocked", q["prospective_forecast_gate"] == "blocked")
    check("no_official_model_write", q["official_model_changes"] == 0 and a["official_forecast"] is False)
    baseline = read(OLD / "internal_audit.json")
    protected = baseline["source_integrity"]["sha256_before"]
    changed = [name for name, digest in protected.items() if not (REPO / name).is_file()
               or hashlib.sha256((REPO / name).read_bytes()).hexdigest() != digest]
    check("protected_originals_unchanged", not changed, {"count": len(protected), "changed": changed})
    check("previous_study_inputs_unchanged", all(hashlib.sha256((OLD / name).read_bytes()).hexdigest() == digest
                                               for name, digest in a["validation"]["source_hashes"].items()))
    result = {"as_of": a["as_of"], "kind": "independent_integrity_arithmetic_checks_not_forecast_accuracy_certification",
              "status": "pass" if all(c["pass"] for c in checks) else "fail", "check_count": len(checks),
              "checks": checks, "supplemental_baselines": baselines,
              "errors": [c for c in checks if not c["pass"]],
              "warnings": ["Original historical publication/adjustment vintages remain unavailable.",
                           "Overlapping daily labels are not independent samples; nonoverlapping anchors also may share regime dependence.",
                           "Inference methods and hyperparameters were not preregistered before historical outcomes.",
                           "No tested model beat its predeclared baseline; current exploratory outputs are not adopted."]}
    (ROOT / "independent_qa.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"status": result["status"], "checks": len(checks), "errors": result["errors"], "supplemental_baselines": baselines}, ensure_ascii=False))
    if result["errors"]:
        raise AssertionError("Research integrity validation failed")


if __name__ == "__main__":
    run()
