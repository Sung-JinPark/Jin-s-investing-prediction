"""Independent read-only checks of research outputs; writes only this review artifact."""
from __future__ import annotations
import csv
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AS_OF = datetime.fromisoformat("2026-10-12T10:38:50+09:00")


def read_json(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8-sig"))


def main():
    checks = []
    def check(name, value, detail=None):
        checks.append(dict(name=name, pass_=bool(value), detail=detail))
    quant = read_json("quantitative_ml.json")
    evidence = read_json("relative_evidence.json")
    manifest = read_json("price_history_manifest.json")
    panels = {}
    for s in manifest["histories"]:
        raw = (ROOT / s["csv"]).read_bytes()
        rows = list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
        symbol = s["symbol"]
        panels[symbol] = rows
        check(f"{symbol}_manifest_hash_matches", hashlib.sha256(raw).hexdigest() == s["csv_sha256"])
        html = (ROOT / s["source_html"]).read_bytes()
        check(f"{symbol}_raw_html_hash_matches", hashlib.sha256(html).hexdigest() == s["source_sha256"])
        check(f"{symbol}_4723_unique_ordered_sessions", len(rows)==4723 and [r["date"] for r in rows] == sorted({r["date"] for r in rows}))
        check(f"{symbol}_history_ends_at_cutoff_price_day", rows[-1]["date"]=="2026-10-09")
        check(f"{symbol}_values_positive_finite", all(math.isfinite(float(r["adj_close"])) and float(r["adj_close"])>0 for r in rows))
        check(f"{symbol}_actual_missing_available_at_explicit", all(r["available_at"]=="" for r in rows) and s["available_at"] is None)
        check(f"{symbol}_retrieved_after_cutoff_not_PIT_certified", datetime.fromisoformat(s["retrieved_at"])>AS_OF and s["historical_original_vintage_verified"] is False)
    dates = [r["date"] for r in panels["SOXX"]]
    check("all_three_price_panels_synchronized", all([r["date"] for r in panels[t]]==dates for t in panels))
    positions = {d:i for i,d in enumerate(dates)}
    oos = list(csv.DictReader((ROOT / "ml_oos_predictions.csv").read_text(encoding="utf-8-sig").splitlines()))
    for h in [21,57]:
        rows = [r for r in oos if int(r["horizon_sessions"])==h]
        reported = quant["horizons"][str(h)]
        max_target_error = 0
        endpoints_valid = True
        for r in rows:
            t = positions[r["date"]]
            endpoints_valid &= dates[t+h]==r["label_end_date"] and r["label_end_date"] <= "2026-10-09"
            semi0=float(panels["SOXX"][t]["adj_close"]); semi1=float(panels["SOXX"][t+h]["adj_close"])
            soft0=float(panels["IGV"][t]["adj_close"]); soft1=float(panels["IGV"][t+h]["adj_close"])
            independently_computed=math.log(semi1/semi0)-math.log(soft1/soft0)
            max_target_error=max(max_target_error, abs(independently_computed-float(r["target_log_ratio"])))
        check(f"h{h}_target_gross_return_log_ratio", max_target_error<1e-12, max_target_error)
        check(f"h{h}_all_label_endpoints_exact_horizon_mature", endpoints_valid)
        check(f"h{h}_all_labels_match_sign", all(int(r["label"])==int(float(r["target_log_ratio"])>0) for r in rows))
        check(f"h{h}_full_daily_oos_count", len(rows)==4723-h-1386 and len(rows)==reported["daily_origin_count"])
        anchors=rows[::h]
        check(f"h{h}_anchors_do_not_overlap", all(positions[b["date"]]>=positions[a["label_end_date"]] for a,b in zip(anchors,anchors[1:])))
        check(f"h{h}_anchor_count", len(anchors)==reported["nonoverlapping_anchor_count"])
        check(f"h{h}_every_fold_purged", all(f["last_train_label_end"]<f["first_test_origin"] and f["strict_train_label_end_before_test"] for f in reported["folds"]))
        check(f"h{h}_every_fold_train_origin_end_difference", all(positions[f["last_train_label_end"]]-positions[f["last_train_origin"]]==h for f in reported["folds"]))
        for model, column in [("logistic","logistic_probability"),("random_forest","random_forest_probability"),("expanding_class_frequency_baseline","baseline_probability")]:
            brier=sum((float(r[column])-int(r["label"]))**2 for r in rows)/len(rows)
            check(f"h{h}_{model}_brier_recomputed", abs(brier-reported["models"][model]["brier"])<1e-12, brier)
            check(f"h{h}_{model}_fraction_bounds", all(0<=float(r[column])<=1 and math.isfinite(float(r[column])) for r in rows))
        for model, column in [("ridge","ridge_prediction"),("expanding_mean_baseline","baseline_mean")]:
            mae=sum(abs(float(r[column])-float(r["target_log_ratio"])) for r in rows)/len(rows)
            check(f"h{h}_{model}_mae_recomputed", abs(mae-reported["models"][model]["mae"])<1e-12, mae)
        check(f"h{h}_model_failures_are_explicit", all(reported["models"][m]["exploratory_skill_gate"]=="not_demonstrated" for m in ["ridge","logistic","random_forest"]))
        current=reported["current_exploratory_outputs"]
        check(f"h{h}_current_training_labels_precede_origin", current["last_train_label_end"]<current["origin"]=="2026-10-09")
        check(f"h{h}_current_forecast_promotion_disabled", current["prospective_usable"] is False)
    for h in [21,57]:
        observed=quant["descriptive_stats"]["windows"][str(h)]
        for symbol in panels:
            independent=float(panels[symbol][-1]["adj_close"])/float(panels[symbol][-h-1]["adj_close"])-1
            check(f"last{h}_{symbol}_total_return_independent", abs(independent-observed["sectors"][symbol]["adjusted_total_return_fraction"])<1e-12, independent)
    check("strict_PIT_forecast_gate_blocked", quant["prospective_forecast_gate"]=="blocked")
    check("explicit_probability_fraction", quant["canonical_probability_unit"]=="fraction")
    check("date_source_UTC_proxy_not_delivery_claim", all("not an observed vendor arrival timestamp" in s["availability_basis"] for s in evidence["sources"] if s["id"].startswith("REL-") and s["published_at"] and s["id"] not in ["REL-INTC-2026Q2","REL-AMAT-FY26Q3","REL-FED-2026SEP","REL-BLS-2026SEP-JOBS"]))
    for s in evidence["sources"]:
        if s.get("available_at"):
            check(s["id"]+"_availability_bound_within_cutoff", datetime.fromisoformat(s["available_at"].replace("Z","+00:00"))<=AS_OF)
    text=(ROOT / "interpretation.md").read_text(encoding="utf-8")
    check("integrated_conclusion_separates_observation_assumption_failed_model", "실적 가시성은 반도체, 최근 가격은 소프트웨어, 연말 승자는 미검증" in text and "실패한 ML 출력" in text)
    review=dict(
        status="pass_with_research_limitations" if all(c["pass_"] for c in checks) else "fail",
        checked_at=datetime.now().astimezone().isoformat(),
        role="independent_research_integrity_review_not_forecast_accuracy_certification",
        checks=checks, check_count=len(checks), errors=[c for c in checks if not c["pass_"]],
        reviewed_file_sha256={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ["relative_ml.py","quantitative_ml.json","relative_evidence.json","interpretation.md"]},
        static_code_review={
            "target": "Forward log ratio of gross adjusted returns; not arithmetic return-point difference",
            "feature_causality": "Only trailing diff/rolling statistics; no future target in features",
            "purge": "Every training label ends strictly before first test origin; one-session embargo",
            "scaler": "StandardScaler embedded in estimator pipeline fit on x[train] only; RF unscaled",
            "fold_update": "Expanding training refits every63sessions; within-fold test features may include information up to own close",
            "tradeability": "Same-close feature/target is research convention; execution cost and realizable close fill not modeled",
            "nonoverlap": "Every-horizon anchors avoid shared return intervals, not shared regimes or estimation dependence",
            "original_vintage": "Historical actual available_at/adjustment vintages absent; strict prospective gate remains blocked",
            "hyperparameters": "Fixed for this retrospective run, not preregistered before historic outcomes; no tuning on OOS here",
            "bootstrap": "Moving-block CI accounts partly for overlapping labels; regimes/selection/refit dependence remain limits",
            "result": "All tested ML models fail to improve over naive baseline; no current output adopted"
        },
        warnings=[
            "A next-UTC-midnight available_at is an explicit conservative publication-date proxy, not a measured delivery timestamp.",
            "Current adjusted history retrieved after cutoff can support retrospective computations, not certify historic or current live-vintage accuracy.",
            "Raw daily OOS counts are not independent sample counts; even nonoverlapping anchors retain regime dependence.",
            "Block-bootstrap intervals are historical model-comparison uncertainty, not year-end prediction confidence intervals.",
            "Deterministic momentum-sign baseline probabilities0/1 give a numerically epsilon-bounded sklearn log_loss; Brier and direction metrics are the suitable reported comparisons.",
            "Conditional Monte Carlo83.19% reflects supplied priors/ranges/dependence; it does not override failed historical validation.",
            "No executable ML probability is promoted; final conclusion is fundamentals semis / current price software / year-end winner unvalidated."
        ], official_changes=0)
    (ROOT/"research_review.json").write_text(json.dumps(review, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(dict(status=review["status"], checks=len(checks), errors=review["errors"]), ensure_ascii=False))


if __name__=="__main__":
    main()
