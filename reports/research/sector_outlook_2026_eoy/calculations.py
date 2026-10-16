"""Reproduce research tables and hypothetical scenario arithmetic offline.

This is not a fitted forecast model. All prospective drivers are declared
analyst assumptions. Existing official model/ledger/snapshot files are read
only and are never promoted, synchronized, or rebuilt by this script.
"""
from collections import Counter
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
import argparse
import csv
import json
import math

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
OUTPUT = ROOT
STATES = ("bull", "base", "bear")

def load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))

def number(value, name):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError(f"{name}: expected an explicit finite number, got {value!r}")
    return float(value)

def validate_weights(weights, unit):
    if unit != "fraction":
        raise ValueError("weights require explicit fraction unit metadata")
    if set(weights) != set(STATES):
        raise ValueError("weights must explicitly cover bull/base/bear")
    values = [number(weights[s], s) for s in STATES]
    if any(v < 0 or v > 1 for v in values):
        raise ValueError("weight outside [0,1]; no clipping is permitted")
    if not math.isclose(sum(values), 1, abs_tol=1e-12, rel_tol=0):
        raise ValueError("weights must sum to one; no normalization is permitted")

def check_available(available_at, as_of):
    if available_at is None:
        return "publication_time_unverified_reference_only"
    available, cutoff = datetime.fromisoformat(available_at.replace("Z", "+00:00")), datetime.fromisoformat(as_of)
    if available.tzinfo is None or cutoff.tzinfo is None:
        raise ValueError("availability and cutoff require explicit timezones")
    if available > cutoff:
        raise ValueError(f"future availability {available_at} after cutoff {as_of}")
    return "dated_release_precedes_cutoff"

def scenario_return(g, m, dividend, expense):
    g, m, dividend, expense = [number(v, n) for v, n in zip(
        (g, m, dividend, expense), ("earnings change", "multiple change", "dividend", "expense"))]
    if g <= -1 or m <= -1 or dividend < 0 or expense < 0:
        raise ValueError("invalid economic factor or cash/expense assumption")
    price_return = (1 + g) * (1 + m) - 1 - expense
    if price_return < -1:
        raise ValueError("assumed expenses exceed hypothetical fund value; no clipping")
    return price_return + dividend

def weighted_return(returns, weights):
    validate_weights(weights, "fraction")
    if set(returns) != set(STATES):
        raise ValueError("return cases do not match weight cases")
    return sum(number(returns[s], s) * weights[s] for s in STATES)

def fx_return(local_return, fx_change):
    r, f = number(local_return, "local return"), number(fx_change, "FX change")
    if r < -1 or f <= -1:
        raise ValueError("invalid return/FX factor")
    return (1 + r) * (1 + f) - 1

def split_economic_return(before_price, after_price, shares_per_old, dividend_per_old=0):
    if before_price <= 0 or after_price < 0 or shares_per_old <= 0:
        raise ValueError("invalid share price or split ratio")
    return (after_price * shares_per_old + dividend_per_old) / before_price - 1

def write_json(name, value):
    (OUTPUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")

def write_csv(name, rows):
    if not rows:
        raise ValueError(f"no data for {name}")
    with (OUTPUT / name).open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

def source_registry(issuer, quotes):
    sources = []
    for filename in ("evidence_us_macro_sectors.json", "evidence_us_tech.json", "evidence_korea.json"):
        for source in load(filename)["sources"]:
            source = dict(source)
            if "id" not in source and "source_id" in source:
                source["id"] = source["source_id"]
            if "id" not in source:
                raise ValueError(f"source identifier missing in {filename}")
            sources.append(source)
    sources.extend(issuer)
    sources.extend(quotes)
    counts = Counter(s["id"] for s in sources)
    duplicates = [key for key, n in counts.items() if n != 1]
    if duplicates:
        raise ValueError(f"duplicate evidence IDs: {duplicates}")
    return sources, {s["id"]: s for s in sources}

def fact(source, metric):
    for item in source.get("numerical_facts", []):
        if item["metric"] == metric:
            return item
    return {"metric": metric, "value": None, "unit": None, "definition": "not provided"}

def percent_fact(source, metric):
    item = fact(source, metric)
    if item["value"] is None:
        return None
    if not str(item["unit"]).startswith("percent"):
        raise ValueError(f"explicit percent unit missing for {source['id']}:{metric}")
    return number(item["value"], metric) / 100

def run(output_dir=None):
    global OUTPUT
    if output_dir is not None:
        candidate = Path(output_dir)
        candidate = (ROOT / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
        if not candidate.is_relative_to(ROOT):
            raise ValueError("research replay output must stay inside the isolated research folder")
        OUTPUT = candidate
        OUTPUT.mkdir(parents=True, exist_ok=True)
    a = load("assumptions.json")
    validate_weights(a["weights"], a["probability_unit"])
    if a["official_forecast"] or a["scenario_role"] != "hypothetical_research_assumptions_not_validated_forecasts":
        raise ValueError("scenario must retain its separate hypothetical research role")
    issuers = load("issuer_observations.json")["observations"]
    quotes = load("closing_quotes.json")["quotes"]
    i_by, q_by = {r["ticker"]: r for r in issuers}, {r["ticker"]: r for r in quotes}
    expected_universe = {"XLC", "XLY", "XLP", "XLE", "XLF", "XLV", "XLI", "XLB", "XLRE", "XLK", "XLU", "SPY"}
    if set(i_by) != expected_universe or set(q_by) != expected_universe:
        raise ValueError("missing sector or benchmark observation")
    for ticker in expected_universe:
        if i_by[ticker].get("error") or q_by[ticker]["previous_close"] != i_by[ticker]["close"]:
            raise ValueError(f"issuer/vendor previous close does not reconcile for {ticker}")
        if q_by[ticker]["close_date"] != a["us_price_date"] or q_by[ticker]["after_hours_included"]:
            raise ValueError(f"wrong price date/session for {ticker}")
        check_available(q_by[ticker].get("market_close_at"), a["as_of"])
    sources, by_id = source_registry(issuers, quotes)
    release_status = {s["id"]: check_available(s.get("available_at"), a["as_of"]) for s in sources}
    days = (date.fromisoformat(a["us_horizon"]) - date.fromisoformat(a["us_price_date"])).days
    results, calculation_rows = [], []
    for asset in a["assets"]:
        missing = set(asset["source_ids"]) - set(by_id)
        if missing:
            raise ValueError(f"unknown source reference for {asset['id']}: {missing}")
        if asset["id"] in i_by:
            published_fee = i_by[asset["id"]].get("expense_ratio_annual_fraction")
        else:
            published_fee = percent_fact(by_id[f"TECH-{asset['id']}-ETF"], "expense_ratio")
        if published_fee is None or not math.isclose(asset["fee_annual"], published_fee, abs_tol=1e-12):
            raise ValueError(f"fund expense lacks a matching explicit issuer value for {asset['id']}")
        if asset["id"] in q_by:
            price = q_by[asset["id"]]["close"]
        else:
            price = fact(by_id[f"TECH-{asset['id']}-ETF"], "closing_price")["value"]
        if price is None:
            raise ValueError(f"no closing-price reference for {asset['id']}")
        price = number(price, "closing price")
        expense = asset["fee_annual"] * days / 365
        cases = {}
        for state in STATES:
            c = asset["cases"][state]
            if c["g_width"] < 0 or c["m_width"] < 0:
                raise ValueError("negative assumption uncertainty width")
            mid = scenario_return(c["g"], c["m"], asset["dividend_remaining"], expense)
            low = scenario_return(c["g"]-c["g_width"], c["m"]-c["m_width"], 0, expense)
            high = scenario_return(c["g"]+c["g_width"], c["m"]+c["m_width"], asset["dividend_remaining"], expense)
            if not low <= mid <= high:
                raise ValueError("scenario midpoint outside stated assumption bounds")
            after_price = price * (1 + mid - asset["dividend_remaining"]) / asset["split_ratio"]
            reconciled = split_economic_return(price, after_price, asset["split_ratio"], price * asset["dividend_remaining"])
            if not math.isclose(reconciled, mid, abs_tol=1e-12):
                raise ValueError("corporate-action/cash return fails reconciliation")
            cases[state] = {"mid": mid, "low": low, "high": high}
            calculation_rows.append({"asset":asset["id"], "state":state, "state_weight_assumption":a["weights"][state],
                "normalized_earnings_change_assumption":c["g"], "multiple_change_assumption":c["m"],
                "remaining_dividend_assumption":asset["dividend_remaining"], "fund_expense_assumption":expense,
                "return_mid":mid,"return_low":low,"return_high":high,"starting_price":price,
                "price_date":a["us_price_date"],"horizon":a["us_horizon"],"shares_per_old_share":asset["split_ratio"],
                "hypothetical_post_split_price_not_target":after_price,"role":a["scenario_role"]})
        mean = weighted_return({s:cases[s]["mid"] for s in STATES}, a["weights"])
        results.append({"id":asset["id"],"name":asset["name"],"class":asset["class"],"priority":asset["priority"],
            "price":price,"price_date":a["us_price_date"],"currency":"USD","cases":cases,
            "weighted_assumption_mid":mean,
            "weighted_assumption_low":weighted_return({s:cases[s]["low"] for s in STATES},a["weights"]),
            "weighted_assumption_high":weighted_return({s:cases[s]["high"] for s in STATES},a["weights"]),
            "rationale":asset["rationale"],"return_confidence":"low_not_empirically_validated"})
    result_by = {r["id"]:r for r in results}
    for result in results:
        result["conditional_excess_vs_spy_mid"] = result["weighted_assumption_mid"] - result_by["SPY"]["weighted_assumption_mid"]
    sensitivity = []
    win_count = Counter()
    for bull in a["sensitivity"]["bull_weights"]:
        for bear in a["sensitivity"]["bear_weights"]:
            weights = {"bull":bull,"base":1-bull-bear,"bear":bear}
            validate_weights(weights, "fraction")
            expected = {r["id"]:weighted_return({s:r["cases"][s]["mid"] for s in STATES},weights)
                        for r in results if r["priority"]}
            order = sorted(expected, key=expected.get, reverse=True)
            win_count[order[0]] += 1
            sensitivity.append({"bull_weight":bull,"base_weight":weights["base"],"bear_weight":bear,
                "SOXX":expected["SOXX"],"GRID":expected["GRID"],"XLC":expected["XLC"],
                "highest_in_this_assumed_combination":order[0],"role":"chosen_grid_not_winning_probability"})
    shock_rows = []
    for asset in a["assets"]:
        for dg, dm, zero_div in ((-.02,0,False),(.02,0,False),(0,-.03,False),(0,.03,False),(0,0,True)):
            returns = {s:scenario_return(asset["cases"][s]["g"]+dg,asset["cases"][s]["m"]+dm,
                0 if zero_div else asset["dividend_remaining"],asset["fee_annual"]*days/365) for s in STATES}
            shock_rows.append({"asset":asset["id"],"earnings_shock":dg,"multiple_shock":dm,"zero_dividend":zero_div,
                "weighted_assumption_mid":weighted_return(returns,a["weights"]),"role":"assumption_stress_not_confidence_interval"})
    sector_names = {"XLC":"통신서비스","XLY":"경기소비재","XLP":"필수소비재","XLE":"에너지","XLF":"금융",
                    "XLV":"헬스케어","XLI":"산업재","XLB":"소재","XLRE":"부동산","XLK":"정보기술","XLU":"유틸리티","SPY":"S&P 500"}
    screens = {
        "XLC":("우선군","AI 수익화·상대 FY1 가치","광고/현금전환 약화·집중 위험"),
        "XLK":("우선군","AI 수요·이익 전망 상향","높은 가격 기대·금리와 CAPEX 위험"),
        "XLI":("전력장비 선별","전력·공사 수주와 제조업","다년 수주 전환 지연·높은 평가배수"),
        "XLV":("방어적 대안","2027 이익 회복·방어적 수요","약가/보험손해율·이미 반등한 가격"),
        "XLE":("유가 조건부","고유가 이익 상향","유가 하락·높은 기저·경기 둔화"),
        "XLF":("금리곡선 조건부","완화되는 긴축·자본시장 회복","곡선 평탄화·신용비용 증가"),
        "XLY":("기업별 선별","일부 플랫폼·고소득 소비","추정치 상향 폭 협소·고용 둔화"),
        "XLB":("관찰","인프라 수요·자원 가격","추정치 하향·중국/제조업 변동"),
        "XLRE":("금리하락 조건부","금리 relief와 일부 DC 수요","조달 비용·FFO 공백"),
        "XLU":("금리하락 조건부","전력 수요와 낮아진 상대가치","CAPEX/부채·이익 전망 하향"),
        "XLP":("하락 방어 중심","반복 소비·배당","낮은 성장·원가 압박"),
        "SPY":("비교 기준","시장 전체의 이익 성장","금리·AI 집중")}
    earnings = {r["ticker"]:r for r in load("evidence_us_macro_sectors.json")["sector_earnings"]}
    sector_rows = []
    for ticker in sector_names:
        issuer, quote, eps = i_by[ticker],q_by[ticker],earnings.get(ticker,{})
        sector_rows.append({"sector":sector_names[ticker],"ticker":ticker,"screen":screens[ticker][0],"close":quote["close"],
            "close_date":quote["close_date"],"close_source":quote["url"],"nav_performance_date":issuer["performance_date"],
            "nav_total_return_ytd":issuer["nav_total_return_ytd"],"nav_total_return_1m":issuer["nav_total_return_1m"],
            "nav_total_return_3m":issuer["nav_total_return_3m"],"pe_fy1":issuer["pe_fy1"],"pe_date":issuer["valuation_date"],
            "pe_fy1_relative_to_spy":issuer["pe_fy1"]/i_by["SPY"]["pe_fy1"],
            "q3_eps_yoy_consensus":eps.get("q3_2026_yoy_eps_growth"),"cy2027_eps_qtd_revision":eps.get("cy2027_eps_qtd_revision"),
            "eps_reference_date":eps.get("data_as_of"),"positive_case":screens[ticker][1],"falsifier":screens[ticker][2],
            "issuer_url":issuer["url"],"return_unit":"fraction","growth_unit":"fraction",
            "role":"descriptive_screen_separate_from_hypothetical_returns"})
    theme_rows = []
    for ticker in ("SOXX","SMH","IGV","CIBR","SKYY","GRID","POWR"):
        src = by_id[f"TECH-{ticker}-ETF"]
        holdings_src = by_id.get(f"TECH-{ticker}-HOLDINGS",src)
        closing, pe = fact(src,"closing_price"),fact(src,"pe")
        theme_rows.append({"ticker":ticker,"close":closing["value"],"close_date":closing.get("as_of"),
            "nav_total_return_ytd":percent_fact(src,"ytd_nav_total_return"),
            "nav_total_return_1m":percent_fact(src,"one_month_nav_total_return"),
            "nav_total_return_3m":percent_fact(src,"three_month_nav_total_return"),"performance_date":"2026-09-30",
            "issuer_pe":pe["value"],"issuer_pe_definition":pe["definition"],"pe_date":pe.get("as_of"),
            "top5_weight":percent_fact(holdings_src,"top5_weight"),"top5_source_date":holdings_src.get("data_as_of"),
            "exposure_note":" / ".join(src["claims"]),"limitations":" / ".join(src["limitations"]),"source":src["url"],
            "source_publication_time_verified":src.get("available_at") is not None,"return_unit":"fraction","holdings_weight_unit":"fraction"})
    audit = load("internal_audit.json")
    preserved = audit["source_integrity"]
    changed = [name for name,digest in preserved["sha256_before"].items()
               if not (REPO/name).is_file() or sha256((REPO/name).read_bytes()).hexdigest()!=digest]
    if changed:
        raise ValueError(f"existing protected source changed: {changed}")
    output = {"as_of":a["as_of"],"role":a["scenario_role"],"official_forecast":False,
        "probability_unit":"fraction","return_unit":"fraction","weights":a["weights"],"calendar_days":days,
        "assets":results,"weight_grid":sensitivity,"grid_highest_count":dict(win_count),
        "grid_count_is_not_probability":True,"driver_stresses":shock_rows,
        "fx_assumptions":[{"usd_return":.1,"usdkrw_change":f,"krw_return":fx_return(.1,f)} for f in (-.05,0,.05)],
        "limitations":a["limitations"]}
    input_names = ["assumptions.json","closing_quotes.json","issuer_observations.json","evidence_us_macro_sectors.json",
                   "evidence_us_tech.json","evidence_korea.json","internal_audit.json"]
    validation = {"as_of":a["as_of"],"arithmetic_status":"pass","existing_sources_unchanged":True,
        "protected_source_count":len(preserved["sha256_before"]),"issuer_previous_close_checks":12,
        "new_session_quotes_independently_certified":False,"source_count":len(sources),
        "source_release_status":release_status,"official_forecast_writes":0,"errors":[],
        "warnings":["Dynamic public pages lack certified historical publication vintages.",
            "Return ranges and weights are analyst assumptions, not empirically calibrated forecasts.",
            "Korean numerical returns withheld because current price/normalized earnings/eligible dividends are incomplete.",
            "Broad GICS and industry baskets overlap; GRID is a global US-listed proxy.",
            "Midpoint ranking is not robust; bounds are assumption ranges, not confidence intervals."],
        "input_sha256":{name:sha256((ROOT/name).read_bytes()).hexdigest() for name in input_names}}
    write_json("scenario_results.json",output)
    write_json("validation.json",validation)
    write_json("source_manifest.json",{"as_of":a["as_of"],"sources":sources,"source_count":len(sources),
        "distinct_url_count":len({s["url"] for s in sources}),"dedup_policy":"same origin is not an independent vote; IDs retain fact roles"})
    write_csv("sector_comparison.csv",sector_rows)
    write_csv("theme_comparison.csv",theme_rows)
    write_csv("scenario_calculations.csv",calculation_rows)
    write_csv("sensitivity.csv",sensitivity)
    write_csv("driver_sensitivity.csv",shock_rows)
    print(json.dumps({"assets":[{"id":r["id"],"conditional_mid":r["weighted_assumption_mid"],
        "range":[r["weighted_assumption_low"],r["weighted_assumption_high"]]} for r in results],
        "weight_grid_highest_counts":dict(win_count),"sources":len(sources),"validation":"pass_with_explicit_limitations"},ensure_ascii=False))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", help="Optional research-folder subdirectory for nondestructive replay")
    run(parser.parse_args().output_dir)
