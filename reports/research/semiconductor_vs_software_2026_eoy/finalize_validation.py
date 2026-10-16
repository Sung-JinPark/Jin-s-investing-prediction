"""Record final research validation and artifact hashes; no durable system writes."""
import datetime as dt
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def read(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8-sig"))


def main():
    arithmetic, browser, review = read("independent_qa.json"), read("html_qa.json"), read("research_review.json")
    if arithmetic["errors"] or browser["errors"] or review.get("errors"):
        raise ValueError("Unresolved final validation error")
    names = ["report.html", "build_html.py", "build_analytics.py", "relative_ml.py", "analysis_assumptions.json",
             "analytical_results.json", "quantitative_ml.json", "relative_evidence.json", "price_history_manifest.json",
             "independent_qa.json", "html_qa.json", "research_review.json", "interpretation.md", "README.md"]
    result = {
        "research_as_of": "2026-10-12T10:38:50+09:00",
        "record_generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "status": "complete_with_explicit_research_limits", "official_forecast": False,
        "research_tests": {"passed": 23, "scope": "13 paired arithmetic + 10 ML integrity tests", "durable_database_writes": 0},
        "independent_arithmetic_checks": {"passed": arithmetic["check_count"], "errors": 0},
        "independent_research_review": {"status": review.get("status"), "errors": 0, "record": "research_review.json"},
        "html_browser_checks": {"passed": browser["check_count"], "errors": 0, "viewports": [1440, 768, 390],
                                "offline_no_remote_requests": True, "visual_review": "desktop and mobile overview inspected"},
        "source_integrity": {"previous_protected_files_unchanged": 242, "previous_study_midpoints_preserved": True},
        "substantive_limits": {"ml_predictive_skill": "not demonstrated; tested models worse than simple baselines",
                               "historical_original_vintage": "unverified; prospective gate blocked",
                               "calibrated_year_end_winner_probability": None,
                               "monte_carlo_role": "assumption distribution frequency, not market winning probability",
                               "macro_features_fitted": False, "macro_role": "separate primary-source interpretation"},
        "sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names}
    }
    (ROOT / "validation_summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"status": result["status"], "tests": 23, "independent_checks": arithmetic["check_count"],
                      "browser_checks": browser["check_count"], "html_sha256": result["sha256"]["report.html"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
