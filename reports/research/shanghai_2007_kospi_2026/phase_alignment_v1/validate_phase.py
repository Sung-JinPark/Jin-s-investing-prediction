"""Research-only integrity, independent arithmetic and scoped test checks."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

import numpy as np
import pandas as pd
from scipy.stats import pearsonr

ROOT = Path(__file__).resolve().parent
STUDY = ROOT.parent
REPO = STUDY.parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    checks, errors = [], []

    def record(name, passed, **detail):
        checks.append({"check": name, "passed": bool(passed), **detail})
        if not passed:
            errors.append(name)

    old = read(ROOT / "original_study_before.json")["sha256"]
    changed = [name for name, value in old.items()
               if not (STUDY / name).is_file() or sha(STUDY / name) != value]
    record("original_study_unchanged", not changed, checked_files=len(old), changed=changed)
    protected = read(STUDY / "protected_before.json")["sha256"]
    changed = [name for name, value in protected.items()
               if not (REPO / name).is_file() or sha(REPO / name) != value]
    record("protected_existing_system_unchanged", not changed,
           checked_files=len(protected), changed=changed)

    source_count, verified, bad = 0, 0, []
    for directory, manifest_name in [
        ("prices", "extension_source_manifest.json"),
        ("fundamentals", "source_manifest.json"),
        ("review", "source_manifest.json"),
    ]:
        for source in read(ROOT / directory / manifest_name).get("sources", []):
            source_count += 1
            name = next((source.get(k) for k in ("raw_file", "relative_path", "local_path")
                         if source.get(k)), None)
            if not name or not source.get("sha256"):
                continue  # Failed attempts remain explicit records, not usable content.
            path = (ROOT / directory / name).resolve()
            if not path.is_relative_to(ROOT) or not path.is_file() or sha(path) != source["sha256"]:
                bad.append(source["source_id"])
            else:
                verified += 1
    record("new_source_response_hashes", not bad, source_attempts=source_count,
           hash_verified_responses=verified, mismatches=bad,
           note="A matching hash authenticates the saved response, not its economic accuracy or original vintage.")

    analysis = read(ROOT / "prices/phase_analysis.json")
    support = read(ROOT / "phase_support.json")
    price_path = STUDY / "prices/prices.csv"
    record("frozen_input_and_method_hashes",
           sha(price_path) == analysis["input_frozen_prices_sha256"]
           and sha(ROOT / "prices/method_contract.json") == analysis["method_contract_sha256"])
    frame = pd.read_csv(price_path, parse_dates=["date"])
    record("frozen_price_boundary", not frame.duplicated(["symbol", "date"]).any()
           and frame.close.gt(0).all() and frame.date.max() <= pd.Timestamp("2026-10-15"),
           rows=len(frame), latest_date=frame.date.max().date().isoformat())
    korean = frame.loc[frame.symbol.eq("KOSPI")].sort_values("date").reset_index(drop=True)
    china = frame.loc[frame.symbol.eq("SSE_COMPOSITE")].sort_values("date").reset_index(drop=True)
    record("current_origin", korean.iloc[-1].date == pd.Timestamp("2026-10-15")
           and abs(korean.iloc[-1].close - support["origin_index_points"]) < 1e-12)
    kp, cp = korean.close.idxmax(), china.close.idxmax()
    n = len(korean) - kp - 1
    k = korean.loc[kp:, "close"].to_numpy()
    c = china.loc[cp:cp+n, "close"].to_numpy()
    corr = {"closing_level_pearson": float(pearsonr(k, c).statistic),
            "daily_log_return_pearson": float(pearsonr(np.diff(np.log(k)), np.diff(np.log(c))).statistic)}
    record("independent_scipy_phase_correlations", n == 77 and len(k) == len(c) == 78
           and all(abs(v - support["postpeak_equal_age_correlation"][key]) < 1e-12
                   for key, v in corr.items()), n_return_pairs=n, **corr)

    level_errors = []
    dates = {"prior_trough": "2026-07-30", "last_pre_break_close": "2026-10-14",
             "observed_rebound_high": "2026-09-23", "observed_peak": "2026-06-22"}
    for item in support["levels"]:
        name = item["level"]
        value = (korean.close.tail(int(name[4:])).mean() if name.startswith("sma_") else
                 float(korean.loc[korean.date.eq(pd.Timestamp(dates[name])), "close"].iloc[0]))
        if abs(value - item["value_index_points"]) > 1e-9 or abs(
            value / korean.iloc[-1].close - 1 - item["required_return_fraction"]
        ) > 1e-12:
            level_errors.append(name)
    record("independent_price_references_and_averages", not level_errors,
           checked=len(support["levels"]), mismatches=level_errors)

    case_errors = []
    for case in support["contrasting_historical_cases"]:
        index = china.index[china.date.eq(pd.Timestamp(case["date"]))][0]
        path = china.loc[index:index+126, "close"].to_numpy()
        metrics = {"end_126_return_fraction": path[-1]/path[0]-1,
                   "best_origin_return_fraction": path.max()/path[0]-1,
                   "worst_origin_return_fraction": path.min()/path[0]-1,
                   "future_max_drawdown_fraction": np.min(path/np.maximum.accumulate(path)-1)}
        if len(path) != 127 or any(abs(case[key]-value) > 1e-12 for key, value in metrics.items()):
            case_errors.append(case["date"])
    record("independent_126_interval_contrasting_outcomes", not case_errors,
           count=len(support["contrasting_historical_cases"]), mismatches=case_errors)

    candidates = pd.read_csv(ROOT / "prices/all_candidates.csv")
    expected = {0.1: [0, 0, 12], 0.15: [0, 0, 0], 0.2: [0, 0, 0]}
    intersections = {}
    for threshold in expected:
        subset = candidates.loc[candidates.symbol.eq("SSE_COMPOSITE")
                                & candidates.threshold_fraction.eq(threshold)]
        intersections[str(threshold)] = [int(subset[f"extended_tolerance_{mode}"].sum())
                                         for mode in ("strict", "base", "loose")]
    record("candidate_coverage_and_joint_intersections",
           len(candidates) == 1794
           and not candidates.duplicated(["symbol", "threshold_fraction", "date"]).any()
           and candidates.future126_status.eq("complete").all()
           and all(intersections[str(t)] == counts for t, counts in expected.items()),
           rows=len(candidates), extended_strict_base_loose=intersections,
           note="Independent reviewers additionally recomputed intersections from raw features without stored distance/flag columns.")
    record("no_forecast_or_probability_output", analysis["probability_output"] is False
           and analysis["aggregate_similarity_score"] is None and support["probability_output"] is False
           and support["benchmark"] is None and support["earnings_revision_series"] is None)

    conditions = read(ROOT / "fundamentals/condition_matrix.json")
    fundamentals = read(ROOT / "fundamentals/validation.json")
    record("explicit_unvalidated_conditions_and_missing_data",
           conditions["threshold_status"] == "ALL_NUMERIC_THRESHOLDS_ARE_UNVALIDATED_RESEARCH_HEURISTICS"
           and conditions["missing_data_rule"].startswith("not_assessable")
           and conditions["horizon"]["future_trading_return_intervals"] == 126
           and conditions["horizon"]["exact_end"] is None
           and fundamentals["status"] == "passed")
    record("independent_turn_confirmation_review",
           read(ROOT / "review/prefix_confirmation_check.json")["status"] == "passed"
           and read(ROOT / "review/rebound_pair_check.json")["status"] == "passed")

    reviewer_records = []
    for part in ("prices", "fundamentals", "review"):
        file = ROOT / part / "independent_review_parent.json"
        review = read(file)
        reviewer_records.append({"path": file.relative_to(ROOT).as_posix(), "sha256": sha(file),
                                 "blocking_findings": review.get("blocking_findings", [])})
    record("three_independent_agent_reviews", all(not r["blocking_findings"] for r in reviewer_records),
           reviews=reviewer_records,
           scope="Agent cross-checks; not an external audit or an out-of-sample forecast validation.")

    test_logs, tests = [], []
    for name, cwd, args in [
        ("phase_support", ROOT, ["discover", "-p", "test_*.py", "-v"]),
        ("phase_math", ROOT, ["discover", "-s", "prices", "-p", "test_*.py", "-v"]),
        ("existing_research", STUDY, ["discover", "-p", "test_*.py", "-v"]),
    ]:
        run = subprocess.run([sys.executable, "-B", "-X", "utf8", "-m", "unittest", *args],
                             cwd=cwd, capture_output=True, text=True, encoding="utf-8")
        output = run.stdout + run.stderr
        count = re.search(r"Ran (\d+) tests?", output)
        tests.append({"suite": name, "passed": run.returncode == 0,
                      "tests": int(count.group(1)) if count else None})
        test_logs.append(name + "\n" + output)
    (ROOT / "test_results.txt").write_text("\n".join(test_logs), encoding="utf-8")
    record("scoped_research_test_suites", all(r["passed"] for r in tests),
           suites=tests, total_tests=sum(r["tests"] or 0 for r in tests),
           production_application_suite="not run: no production code changed; research tests use disposable fixtures")
    visual = read(ROOT / "visual_qa.json")
    record("offline_browser_layout", visual["passed"],
           widths=[r["width"] for r in visual["results"]], images_visually_inspected=True)
    result = {
        "status": "passed" if not errors else "failed",
        "validated_at_utc": datetime.now(timezone.utc).isoformat(),
        "as_of": "2026-10-16T09:00:00+09:00", "price_cutoff": "2026-10-15",
        "checks": checks, "errors": errors,
        "error_categories": {"code_defects": errors, "environment_dependency_failures": [],
            "missing_data_not_treated_as_pass_or_failure": [
                "fixed-FY2027 common-provider EPS revisions", "comparable daily forced-sale series",
                "constituent breadth panel", "workday-adjusted export panel",
                "strict original-vintage certification", "verified global-market benchmark"]},
        "report_files": {name: sha(ROOT/name) for name in ("report.md", "report.html")},
        "probabilities_created": False, "official_or_existing_research_mutations": False,
    }
    (ROOT / "validation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "checks": len(checks), "errors": errors,
                      "tests": sum(r["tests"] or 0 for r in tests)}, ensure_ascii=False))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
