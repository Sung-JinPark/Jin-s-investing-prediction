"""Independent checks scoped to the separate timing research directory."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pandas as pd
import xlrd

ROOT = Path(__file__).resolve().parent
STUDY = ROOT.parent
REPO = STUDY.parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def invalid_constant(value):
    raise ValueError(f"Non-finite JSON number: {value}")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=invalid_constant)


def main():
    checks, errors = [], []

    def record(name, passed, **details):
        checks.append({"check": name, "passed": bool(passed), **details})
        if not passed:
            errors.append(name)

    for name, base, snapshot in [
        ("previous_studies_unchanged", STUDY, ROOT / "original_study_before.json"),
        ("protected_existing_system_unchanged", REPO, STUDY / "protected_before.json"),
    ]:
        hashes = read(snapshot)["sha256"]
        changed = [p for p, digest in hashes.items()
                   if not (base/p).is_file() or sha(base/p) != digest]
        record(name, not changed, checked_files=len(hashes), changed=changed)

    verified, mismatches, attempts = 0, [], 0
    for part in ("china_earnings", "china_liquidity", "korea", "context"):
        for source in read(ROOT/part/"source_manifest.json")["sources"]:
            attempts += 1
            pairs = [(key, digest) for key, digest in [
                ("local_path", "sha256"), ("archive_relative_path", "sha256"),
                ("extracted_text_path", "extracted_text_sha256"), ("html_path", "html_sha256")
            ] if source.get(key) and source.get(digest)]
            for key, digest in pairs:
                path = (ROOT/part/source[key]).resolve()
                if not path.is_relative_to(STUDY) or not path.is_file() or sha(path) != source[digest]:
                    mismatches.append(f"{part}/{source['source_id']}/{key}")
                else:
                    verified += 1
    record("source_response_and_extraction_hashes", not mismatches, source_records=attempts,
           hashes_verified=verified, mismatches=mismatches,
           note="Includes retained unusable/redirect responses, whose bytes do not establish factual validity.")

    json_files = list(ROOT.rglob("*.json"))
    bad_json = []
    for path in json_files:
        try:
            read(path)
        except (ValueError, UnicodeError) as error:
            bad_json.append({"path": path.relative_to(ROOT).as_posix(), "error": str(error)})
    record("finite_valid_json", not bad_json, checked_files=len(json_files), errors=bad_json)

    prices = pd.read_csv(STUDY/"prices/prices.csv", parse_dates=["date"])
    chronology = read(ROOT/"price_chronology.json")
    record("frozen_price_source", chronology["source_sha256"] == sha(STUDY/"prices/prices.csv")
           and prices.date.max() <= pd.Timestamp("2026-10-15")
           and not prices.duplicated(["symbol", "date"]).any())
    failures = []
    for row in chronology["rows"]:
        series = prices.loc[prices.symbol.eq(row["symbol"])].sort_values("date").reset_index(drop=True)
        index = series.index[series.date.eq(pd.Timestamp(row["date"]))]
        peak_index = series.index[series.date.eq(pd.Timestamp(row["peak_reference_date"]))]
        if len(index) != 1 or len(peak_index) != 1:
            failures.append(row["date"])
            continue
        close = float(series.loc[index[0], "close"])
        peak = float(series.loc[peak_index[0], "close"])
        correct = (abs(close-row["close_index_points"]) < 1e-10
                   and abs(close/peak-1-row["return_from_observed_peak_fraction"]) < 1e-12
                   and index[0]-peak_index[0] == row["actual_return_intervals_from_peak"]
                   and row["peak_reference_is_future_to_observation"] == (index[0] < peak_index[0]))
        if not correct:
            failures.append(f"{row['symbol']}/{row['date']}")
    record("independent_pandas_price_and_session_arithmetic", not failures,
           observations=len(chronology["rows"]), failures=failures)
    record("no_invented_holiday_close", not any(row["date"] == "2007-12-31" for row in chronology["rows"])
           and any(row["date"] == "2007-12-28" for row in chronology["rows"]))

    monthly = pd.read_csv(ROOT/"china_liquidity/monthly_market_activity.csv")
    manifests = {r["source_id"]: r for r in read(ROOT/"china_liquidity/source_manifest.json")["sources"]}
    monthly_errors, reported_discrepancies = [], []
    for row in monthly.to_dict("records"):
        source = manifests[row["source_id"]]
        book = xlrd.open_workbook(str(ROOT/"china_liquidity"/source["local_path"]))
        trade = book.sheet_by_name("交易")
        month = int(row["period"][-2:])
        sheet_row = month+4  # January is physical row 6; independent direct-cell read.
        days, total, average = [float(trade.cell_value(sheet_row, col)) for col in (1, 2, 4)]
        actual_days = int(prices.loc[prices.symbol.eq("SSE_COMPOSITE")
                          & prices.date.dt.strftime("%Y-%m").eq(row["period"])].shape[0])
        delta = average-total/days
        if not (days == row["trading_days_official"] == actual_days
                and abs(total-row["stock_turnover_CNY_100million"]) < 1e-9
                and abs(average-row["daily_average_turnover_CNY_100million"]) < 1e-9
                and abs(delta-row["daily_average_published_minus_recomputed_CNY_100million"]) < 1e-10):
            monthly_errors.append(row["period"])
        if abs(delta) > 0.005:
            reported_discrepancies.append({"period": row["period"], "published_minus_recomputed": delta,
                                          "unit": "CNY 100 million per trading day"})
    record("independent_XLS_cells_and_actual_trading_days", not monthly_errors,
           observations=len(monthly), failures=monthly_errors,
           original_arithmetic_discrepancies_preserved=reported_discrepancies)

    record("unit_arithmetic_in_report", abs((3.5/7.3-1)*100+52.05479452054794) < 1e-10
           and abs((56/63.2-1)*100+11.39240506329114) < 1e-10
           and abs((25.3-31.6)+6.3) < 1e-12,
           meanings=["Conditional crash-day net-buy change is not monthly retail net selling",
                     "Outstanding loan change is not a forced-sale amount",
                     "CICC growth forecast -6.3 percentage points is not EPS level -6.3 percent"])
    validations = {part: read(ROOT/part/"validation.json")["status"]
                   for part in ("china_earnings", "china_liquidity", "korea")}
    record("component_provenance_validations", all(v == "passed" for v in validations.values()), results=validations)

    report = (ROOT/"report.md").read_text(encoding="utf-8")
    resolved = {
        "actual_decline_narrowed_to_later_annual_results": "나중에 확정된 연간 순이익 감소" in report and "2009년 5월 19일 사후 확인" in report,
        "forecast_chart_two_year_growth_series": "2007년·2008년 순이익 예상 증가율의 두 선" in report,
        "effective_stock_not_A_only_accounts": "유효 주식 계좌" in report and "유효 A주 계좌" not in report,
        "turnover_not_flow_direction": "참여 활동이 일방적으로 줄지는 않음" in report,
        "crash_day_sample_narrowing": "급락일의 개인 매수 완충 약화" in report,
        "BOK_undated_outlook_qualified": "정확한 관측일·데이터 제공자·구성기업·전망연도" in report,
        "security_collateral_label": "증권담보대출" in report,
    }
    reviews = {}
    for part in ("china_earnings", "china_liquidity", "korea"):
        file = ROOT/part/"independent_review.json"
        value = read(file)
        reviews[part] = {"sha256": sha(file), "status": value.get("status", value.get("verdict")),
                         "blocking_findings": value.get("blocking_findings", [])}
    record("independent_reviews_and_wording_resolutions", all(resolved.values())
           and all(not r["blocking_findings"] for r in reviews.values()),
           reviews=reviews, resolved_wording=resolved,
           note="Reviews are independent agent cross-checks, not external audit or causal identification.")
    record("offline_browser_layout", read(ROOT/"visual_qa.json")["passed"], widths=[1440, 768, 390])
    result = {
        "status": "passed" if not errors else "failed", "errors": errors, "checks": checks,
        "validated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_as_of": "2026-10-16T09:00:00+09:00", "price_cutoff": "2026-10-15",
        "missing_data_not_inferred": ["Common-provider fixed-year EPS revision levels and first cut date",
                                      "Retail daily net-flow turning date in China", "Current Korean forced-sale acceleration"],
        "source_issues_retained": ["Some original daily averages do not equal turnover divided by days within rounding",
                                   "Original historical collection vintages not fully authenticated",
                                   "IMF retrieval failed; BIS old PDF URL redirects to HTML index; neither substituted for article PDF"],
        "code_changes": "Research-only source receipt, rendering and validation scripts; no production code changes",
        "production_suite": "Not run: production files and model behavior unchanged",
        "official_mutations": False, "probability_outputs": [],
        "report_sha256": {name: sha(ROOT/name) for name in ("report.md", "report.html")},
    }
    (ROOT/"validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "checks": len(checks), "hashes": verified,
                      "errors": errors}, ensure_ascii=False))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
