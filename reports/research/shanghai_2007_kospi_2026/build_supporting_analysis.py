"""Reproduce supplemental arithmetic and descriptive policy windows offline."""
from __future__ import annotations

import csv
import datetime as dt
import importlib.util
import json
from pathlib import Path

from research_math import implied_pe_change, valuation_return, path_risks

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("price_analytics", ROOT / "prices" / "analytics.py")
PA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PA)

EVENTS = [
    {"id": "CN-STAMP-20070530", "symbol": "SSE_COMPOSITE", "date": "2007-05-30", "category": "과열 억제", "event": "증권거래 인지세 인상 시행", "source": "https://www.mofcom.gov.cn/zcfb/zgdwjjmywg/art/2007/art_99829a5529ff4223a7bf6ca48ffc4b24.html"},
    {"id": "KR-RIA-20260120", "symbol": "KOSPI", "date": "2026-01-20", "category": "국내투자 유도 추진안", "event": "RIA 국내투자 세제지원 추진 발표", "source": "https://www.korea.kr/news/policyNewsView.do?newsId=148958323"},
    {"id": "KR-FUND-20260506", "symbol": "KOSPI", "date": "2026-05-06", "category": "산업자금 및 참여 유도", "event": "국민참여성장펀드 설계 발표", "source": "https://www.fsc.go.kr/no010101/86834?curPage=2"},
    {"id": "KR-FUND-20260529", "symbol": "KOSPI", "date": "2026-05-29", "category": "참여 결과 공표", "event": "1차 국민참여성장펀드 판매 결과 발표", "source": "https://www.fsc.go.kr/po010101/87009"},
    {"id": "KR-RATE-20260716", "symbol": "KOSPI", "date": "2026-07-16", "category": "통화 긴축", "event": "한국은행 기준금리 인상", "source": "https://www.bok.or.kr/portal/singl/baseRate/list.do?dataSeCd=01&menuNo=200643"},
    {"id": "KR-RATE-20260827", "symbol": "KOSPI", "date": "2026-08-27", "category": "통화 긴축", "event": "한국은행 기준금리 인상", "source": "https://www.bok.or.kr/portal/singl/baseRate/list.do?dataSeCd=01&menuNo=200643"},
]


def event_window(rows: list[dict], event_date: str, n: int = 20) -> dict:
    date = dt.date.fromisoformat(event_date)
    event_idx = next((i for i, row in enumerate(rows) if row["date"] >= date), None)
    if event_idx is None or event_idx < n + 1:
        return {"status": "unavailable", "reason": "insufficient pre-event observations"}
    prior, pre_start = rows[event_idx-1], rows[event_idx-n-1]
    result = {"event_session": rows[event_idx]["date"].isoformat(),
              "anchor_close_date": prior["date"].isoformat(),
              "pre_start_date": pre_start["date"].isoformat(),
              "pre_20_return_fraction": prior["close"]/pre_start["close"]-1,
              "post_20_return_fraction": None, "post_end_date": None,
              "individual_flow_change": None,
              "flow_missing_reason": "No comparable public daily investor-flow panel acquired; not inferred from prices or deposits",
              "interpretation": "date-based descriptive window, not an abnormal-return or causal estimate; announcement time unknown"}
    if event_idx+n-1 >= len(rows):
        result.update(status="right_censored", reason="20 post-event sessions not observed by cutoff")
    else:
        end = rows[event_idx+n-1]
        result.update(status="ok", post_end_date=end["date"].isoformat(),
                      post_20_return_fraction=end["close"]/prior["close"]-1)
    return result


def main() -> None:
    prices = PA.load_prices()
    sensitivity = []
    for eps in (-.4, -.2, 0., .2, .4):
        for pe in (-.4, -.2, 0., .2, .4):
            sensitivity.append({"eps_change_fraction": eps, "pe_change_fraction": pe,
                                "price_return_fraction": valuation_return(eps, pe, unit="fraction"),
                                "role": "illustrative algebra, not estimated scenario, forecast, frequency or probability"})
    threshold = [{"eps_change_fraction": eps,
                  "pe_change_for_20pct_origin_loss_fraction": implied_pe_change(eps, -.2, unit="fraction")}
                 for eps in (-.2, -.1, 0., .1, .2, .4)]
    windows = []
    for event in EVENTS:
        local = prices.get(event["symbol"], [])
        window = {**event, **event_window(local, event["date"])}
        fx_symbol = "CNY_PER_USD" if event["symbol"].startswith("SSE") else "KRW_PER_USD"
        for phase, first_key, last_key in [("pre", "pre_start_date", "anchor_close_date"),
                                           ("post", "anchor_close_date", "post_end_date")]:
            if window.get(first_key) and window.get(last_key):
                selected = PA.select(local, dt.date.fromisoformat(window[first_key]), dt.date.fromisoformat(window[last_key]))
                relative = PA.usd_global_comparison(selected, prices.get(fx_symbol, []), prices.get("MSCI_WORLD", []))
                window[f"{phase}_usd_minus_world_log_return"] = relative.get("usd_minus_world_log_return")
                window[f"{phase}_relative_common_start"] = relative.get("first_common_date")
                window[f"{phase}_relative_common_end"] = relative.get("last_common_date")
            else:
                window[f"{phase}_usd_minus_world_log_return"] = None
                window[f"{phase}_relative_common_start"] = None
                window[f"{phase}_relative_common_end"] = None
        windows.append(window)
    current = PA.select(prices["KOSPI"],dt.date(2025,1,1),dt.date(2026,10,15))
    current_summary = PA.summarize(current)
    origin = current[-1]["close"]
    historical = prices["SSE_COMPOSITE"]
    peak_index = max(range(len(historical)),key=lambda i:historical[i]["close"])
    peak_close = historical[peak_index]["close"]
    threshold_dd = current_summary["latest_drawdown_fraction"]
    crossing_idx = next((i for i in range(peak_index+1,len(historical)) if historical[i]["close"]/peak_close-1 <= threshold_dd), None)
    diagnostic = {"role":"single-case ex-post diagnostic; conditioning on today's observed drawdown, not an independently validated forecast", "matched_drawdown_threshold_fraction":threshold_dd}
    if crossing_idx is not None:
        crossing = historical[crossing_idx]
        diagnostic.update(first_crossing_date=crossing["date"].isoformat(),first_crossing_close=crossing["close"],
                          first_crossing_actual_drawdown_fraction=crossing["close"]/peak_close-1,
                          previous_session_drawdown_fraction=historical[crossing_idx-1]["close"]/peak_close-1,outcomes={})
        for horizon in (126,252):
            future = historical[crossing_idx+1:crossing_idx+horizon+1]
            diagnostic["outcomes"][str(horizon)] = ({"status":"complete",**path_risks(crossing["close"],[r["close"] for r in future],unit="index_points"),"last_date":future[-1]["date"].isoformat()}
                if len(future)==horizon else {"status":"right_censored","observations_available":len(future),"required":horizon,"result":None})
    payload = {"as_of": "2026-10-16T09:00:00+09:00", "unit": "fraction", "probabilities": None,
               "current_origin":{"date":current[-1]["date"].isoformat(),"close":origin,"close_peak":current_summary["peak_close"],
                    "additional_20pct_loss_threshold_points":origin*.8,"return_required_to_recover_peak_fraction":current_summary["peak_close"]/origin-1,
                    "drawdown_from_old_peak_after_additional_20pct_fraction":origin*.8/current_summary["peak_close"]-1},
               "historical_same_drawdown_diagnostic":diagnostic,
               "measured_eps_pe_decomposition": None,
               "decomposition_missing_reason": "No matched constant-definition index EPS and P/E endpoint time series; aggregate profits and differently defined multiples cannot substitute",
               "sensitivity": sensitivity, "loss_threshold": threshold, "policy_windows": windows,
               "sector_return_contribution": None,
               "sector_contribution_missing_reason": "Dated weights are concentration snapshots, not point-in-time daily constituent return contributions"}
    (ROOT / "supporting_analysis.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    for name, rows in [("valuation_sensitivity.csv", sensitivity), ("policy_windows.csv", windows)]:
        with (ROOT / name).open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    print(json.dumps({"sensitivity_cells":len(sensitivity),"policy_windows":len(windows),"official_forecast":False}))


if __name__ == "__main__":
    main()
