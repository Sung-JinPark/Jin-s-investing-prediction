"""Rebuild the descriptive research matrix from preserved inputs; no network/DB."""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def read(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8-sig"))

def main():
    macro = read("evidence_us_macro_sectors.json")
    issuer = {x["ticker"]: x for x in read("issuer_observations.json")["observations"]}
    quotes = {x["ticker"]: x for x in read("closing_quotes.json")["quotes"]}
    earnings = {x["ticker"]: x for x in macro["sector_earnings"]}
    sources = {x["id"]: x for x in macro["sources"]}
    sources.update({x["id"]: x for x in read("evidence_us_tech.json")["sources"]})
    sources.update({x["id"]: x for x in issuer.values()})
    sources.update({x["id"]: x for x in quotes.values()})
    with (ROOT / "sector_comparison.csv").open(encoding="utf-8-sig", newline="") as f:
        screen = list(csv.DictReader(f))
    # Qualitative observations below are explicit research inferences, not new data.
    thematic = {
        "XLK": ("AI 연산·클라우드 실제 매출과 투자 전망; 기술 섹터 전체 현금흐름 전망은 미확보", "hyperscaler 투자·AI 매출의 연결; 산업 전체 CAPEX 합산은 미확보", ["TECH-NVDA-FY27Q2", "TECH-AVGO-FY26Q3", "TECH-MSFT-FY26Q4", "TECH-MSFT-FY26Q4-CALL"], "다음 기업 전망에서 수요·마진·투자비와 이익 수정이 유지되는지 확인"),
        "XLC": ("광고·클라우드 매출 성장과 현금 전환을 함께 확인; Alphabet 투자평가이익은 반복 이익과 구분", "Alphabet·Meta AI 투자 확대; 기업별 기간·현금 CAPEX 정의가 달라 섹터 합산하지 않음", ["TECH-GOOGL-2026Q2", "TECH-META-2026Q2"], "AI·광고 수익화와 투자비·감가상각 증가의 균형 확인"),
        "XLY": ("기업별 선별; Amazon AWS 성장과 TTM FCF 악화를 함께 확인; 전체 섹터 현금 전망 미확보", "Amazon 설비투자·소비 수요는 서로 다른 노출; 섹터 CAPEX 합산 미확보", ["TECH-AMZN-2026Q2"], "반복 플랫폼 이익·소비 수요와 투자 후 현금 전환 확인"),
        "XLI": ("전력장비의 주문·잔고와 현금 전환을 기업 수준에서 확인; 전체 산업재와 동일시하지 않음", "Eaton·GE Vernova 전력 수요·잔고; 전체 섹터 수요/CAPEX 수치는 미확보", ["TECH-ETN-2026Q2", "TECH-GEV-2026Q2"], "주문 잔고 매출 전환·납기·선수금 제외 현금 확인"),
        "XLRE": ("DLR Core FFO·EQIX AFFO 가이드 참고; GAAP EPS나 FCF와 동일 지표가 아님", "데이터센터 임대 수요·투자 전망 참고; 전체 부동산 CAPEX 합산 미확보", ["TECH-DLR-2026Q2", "TECH-EQIX-2026Q2"], "임대 개시 지연·현금 전환·전력 연결과 자본 비용 확인"),
    }
    rows = []
    for s in screen:
        t = s["ticker"]
        i, q = issuer[t], quotes[t]
        e = earnings.get(t)
        ids = [i["id"], q["id"], "US-FED-0916"]
        if e:
            ids.append(e["source_id"])
            eps, eps_date, eps_id = e["q3_2026_yoy_eps_growth"], e["data_as_of"], e["source_id"]
            revision = e["cy2027_eps_qtd_revision"]
        else:
            f = sources["US-FACTSET-1009"]
            eps, eps_date, eps_id = f["facts"]["current_q3_eps_growth_fraction"], "2026-10-09", f["id"]
            revision = None
            ids.append(eps_id)
        default = ("섹터 EPS 컨센서스만 확보; 현금흐름 전망 원문·수치는 미확보", "섹터 전체 수요·CAPEX 정량 자료 미확보", [], "새 이익 전망과 현재 가격에 반영된 기대의 균형 확인; 특정 발표 일정 미확인")
        cash, demand, extra, catalyst = thematic.get(t, default)
        ids += extra
        row = {
            "sector": s["sector"], "ticker": t, "screen": s["screen"],
            "earnings_cashflow_outlook": {"q3_2026_eps_yoy_fraction": eps, "data_as_of": eps_date, "source_id": eps_id, "status": "external_consensus_not_realized", "cashflow_forecast": None, "qualitative": cash, "qualitative_type": "research_inference", "company_source_ids": extra, "gap": "전체 섹터의 같은 기간 현금흐름 전망 없음; 일부 기업 자료는 섹터 대표값이 아님"},
            "estimate_revisions": {"cy2027_eps_qtd_revision_fraction": revision, "data_as_of": e["data_as_of"] if e else None, "source_id": e["source_id"] if e else None, "definition": "2027년 EPS 전망의 분기 중 수정; 2026년 EPS 수정 또는 남은 연말 수익률이 아님", "status": "external_consensus_reference" if e else "missing", "gap": None if e else "SPY의 같은 날짜·동일 정의 CY2027 수정치 미확보"},
            "current_valuation": {"regular_close_usd": q["close"], "close_date": q["close_date"], "close_source_id": q["id"], "pe_fy1": i["pe_fy1"], "valuation_date": i["valuation_date"], "definition": i["pe_definition"], "source_id": i["id"], "pit_certified": False, "gap": "가격과 평가배수 날짜 차이; 동적 페이지 공개시각/과거 수정 vintage 미확보; 정상화 2027 EPS 배수 미확보"},
            "demand_capex": {"sector_capex_forecast": None, "sector_demand_growth": None, "qualitative": demand, "type": "research_inference" if extra else "missing", "source_ids": extra, "gap": "기업별 회계기간·현금/리스 CAPEX가 달라 동일 기간 섹터 합산 없음"},
            "rate_sensitivity": {"measured_beta": None, "direction": "상승한 할인율·조달 비용의 부담을 평가하되 기업별 이익 효과는 다름", "type": "research_inference", "policy_target_fraction": [0.0375, 0.04], "policy_date": "2026-09-16", "source_id": "US-FED-0916", "gap": "섹터별 금리 민감도 계수·실증 회귀 미확보"},
            "momentum_concentration": {"nav_ytd_fraction": i["nav_total_return_ytd"], "nav_1m_fraction": i["nav_total_return_1m"], "nav_3m_fraction": i["nav_total_return_3m"], "performance_date": i["performance_date"], "performance_definition": i["performance_definition"], "holdings_count": i.get("holdings_count"), "top5_weight_fraction": None, "source_id": i["id"], "gap": "보유 종목 수는 집중도와 다름; 최신 대분류 ETF top5 비중 미확보"},
            "year_end_catalysts": {"qualitative": catalyst, "type": "research_assumption_conditional_not_observed", "confirmed_event_dates": None, "source_ids": extra + ([eps_id] if not extra else []), "gap": "모든 섹터 공통의 확정 기업 발표 달력 미확보; 조건 확인 항목이지 미래 결과가 아님"},
            "falsifiers": {"qualitative": s["falsifier"], "type": "research_inference", "basis": "report.md와 sector_comparison.csv의 정성 screening", "source_ids": ids},
            "confidence": {"observations": "날짜·정의가 표시된 공개 원문 참고값", "ranking": "조건부 정성 판단; 자료 공백을 고려하면 단독 순위/정밀 기대수익 확정 불가", "probability": None, "type": "research_judgment_not_calibrated"},
            "data_status_missing_reasons": {"status": "descriptive_screen_research_reference_not_official_forecast", "available_at_certified_for_all_sources": False, "missing": ["섹터 현금흐름 전망", "섹터 CAPEX 동일기간 합산", "금리 민감도 실증계수", "최신 top5 비중", "모든 기업 연말 확정 발표 일정", "완전한 point-in-time publication vintage"], "numeric_missing_is_null": True},
            "sources": [{"id": x, "url": sources[x]["url"], "published_at": sources[x].get("published_at"), "data_as_of": sources[x].get("data_as_of"), "pit_certified": sources[x].get("pit_certified")} for x in dict.fromkeys(ids)],
            "fraction_unit_fields": "returns/growth/revisions/weights: fraction; PE: multiple; price: USD"
        }
        rows.append(row)
    obj = {"as_of": macro["as_of"], "scope": "11 US sectors plus SPY; preserved evidence only; no new observations or official model", "ordered_dimensions": list(rows[0])[3:-1], "row_count": len(rows), "rows": rows}
    (ROOT / "sector_research_matrix.json").write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    with (ROOT / "sector_research_matrix.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False, separators=(",", ":")) if isinstance(v, (dict, list)) else v for k, v in row.items()})
    assert len(rows) == 12 and len({r["ticker"] for r in rows}) == 12
    assert all(r["estimate_revisions"]["cy2027_eps_qtd_revision_fraction"] == earnings[r["ticker"]]["cy2027_eps_qtd_revision"] for r in rows if r["ticker"] in earnings)
    print("Created sector_research_matrix.json and .csv: 12 rows; 11 sectors + SPY; same ordered dimensions; source IDs validated")

if __name__ == "__main__":
    main()
