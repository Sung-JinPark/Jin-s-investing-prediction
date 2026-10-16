"""Build independent fundamental research input; never writes an official ledger."""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASELINE = ROOT.parent / "sector_outlook_2026_eoy"
AS_OF = "2026-10-12T10:38:50+09:00"


def fact(metric, value, unit, definition, nature="reported_observation"):
    return dict(metric=metric, value=value, unit=unit, definition=definition, nature=nature)


def source(id_, title, url, publisher, published_at, data_as_of, facts, claim, limitations, available_at=None):
    explicit_release_time = available_at is not None
    if available_at is None and published_at is not None:
        # For a date-only publication, use the following UTC midnight explicitly.
        available_at = (datetime.fromisoformat(published_at).replace(tzinfo=timezone.utc)
                        + timedelta(days=1)).isoformat().replace("+00:00", "Z")
    return dict(id=id_, title=title, url=url, publisher=publisher,
                published_at=published_at, data_as_of=data_as_of,
                available_at=available_at,
                retrieved_at=None,
                compiled_at=datetime.now(timezone.utc).isoformat(),
                retrieval_timestamp_status="Web tool original inspected in this research session; exact source-fetch timestamp not supplied. compiled_at is the record-build timestamp, not a fetch or availability timestamp.",
                availability_basis=("Original source explicitly states public release time; available_at records that time, not vendor delivery or our fetch time. Historical deployment proof is not archived."
                                    if explicit_release_time else "Original dated announcement; next UTC midnight is a conservative date-only availability convention, not an observed vendor arrival timestamp. No archived deployment proof."
                                    if published_at else "Event/reference date verified but original publication timestamp not available. Context only, excluded from numerical model features."),
                lookahead_status="eligible_dated_primary" if published_at else "context_only_publication_time_unverified",
                numerical_facts=facts, claims=[claim], limitations=limitations,
                dedup_group=id_)


def main():
    original_path = BASELINE / "evidence_us_tech.json"
    original_bytes = original_path.read_bytes()
    original = json.loads(original_bytes)
    reuse = {
        "TECH-SOXX-ETF", "TECH-SOXX-HOLDINGS", "TECH-SOXX-SPLIT",
        "TECH-IGV-ETF", "TECH-IGV-HOLDINGS", "TECH-NVDA-FY27Q2",
        "TECH-AVGO-FY26Q3", "TECH-MSFT-FY26Q4", "TECH-MSFT-FY26Q4-CALL",
        "TECH-CRM-FY27Q2", "TECH-CRWD-FY27Q2", "TECH-TSMC-2026SEP-SALES",
        "TECH-GS-2026OCT-AI", "TECH-FID-2026AUG-AI", "TECH-JPM-2026SEP-CAPEX"
    }
    sources = []
    for item in original["sources"]:
        if item["id"] in reuse:
            item = copy.deepcopy(item)
            item["reused_from"] = str(original_path)
            item["baseline_research_as_of"] = original["research_as_of"]
            item["dedup_group"] = item["id"]
            sources.append(item)
    assert len(sources) == len(reuse), "Missing baseline source; do not silently omit."

    sources += [
        source("REL-MU-FY26Q4", "Micron FY2026 Q4 and full-year results", "https://www.sec.gov/Archives/edgar/data/723125/000072312526000018/a2026q4ex991-pressrelease.htm", "Micron / SEC", "2026-09-30", "2026-09-03", [
            fact("quarter_revenue", 54.229, "USD_billion", "FY26Q4"),
            fact("previous_quarter_revenue", 41.456, "USD_billion", "FY26Q3"),
            fact("previous_year_quarter_revenue", 11.315, "USD_billion", "FY25Q4"),
            fact("gaap_gross_margin", .868, "fraction", "FY26Q4"),
            fact("quarter_operating_cash_flow", 43.97, "USD_billion", "FY26Q4; rounded"),
            fact("quarter_net_capex", 10.77, "USD_billion", "Company capex net of incentives; non-GAAP"),
            fact("quarter_adjusted_fcf", 33.20, "USD_billion", "Company adjusted FCF; rounded"),
            fact("next_quarter_revenue_midpoint", 61.5, "USD_billion", "FY27Q1", "management_guidance"),
            fact("next_quarter_revenue_plus_minus", 1.5, "USD_billion", "Guidance range, not confidence interval", "management_guidance")
        ], "메모리 성장과 현금창출은 확인된다. 현재 높은 이익률을 연말 이후 정상 이익률로 고정하지 않는다.", ["HBM-only revenue is not separately supplied here.", "Net capex/adjusted FCF is not gross-capex FCF; incentives and customer funding matter.", "Quarterly/yearly rows must remain separate; no automatic annualization."]),
        source("REL-AMD-2026Q2", "AMD second quarter 2026 results", "https://ir.amd.com/news-events/press-releases/detail/1295/amd-reports-second-quarter-2026-financial-results", "AMD", "2026-08-04", "2026-06-27", [
            fact("quarter_revenue", 11.536, "USD_billion", "Q2 calendar 2026"),
            fact("revenue_yoy", .50, "fraction", "Q2 2026 vs Q2 2025"),
            fact("data_center_revenue", 6.7, "USD_billion", "EPYC CPUs plus Instinct GPUs; rounded"),
            fact("data_center_revenue_yoy", 1.07, "fraction", "Not pure AI GPU growth"),
            fact("gaming_revenue_yoy", -.31, "fraction", "Q2 gaming; weak semi-custom demand"),
            fact("gaap_operating_income", 1.990, "USD_billion", "Q2 2026"),
            fact("quarter_fcf", 1.558, "USD_billion", "Company CFO minus capex"),
            fact("sbc", .503, "USD_billion", "Operating income reconciliation"),
            fact("prior_year_mi308_inventory_charge", .8, "USD_billion", "Prior-year comparison base"),
            fact("next_quarter_revenue_midpoint", 13, "USD_billion", "Q3 2026 +/-0.3bn", "management_guidance")
        ], "AI 연산과 서버 CPU 수요는 강하지만 게임은 감소한다. 전체 반도체 수요를 AI 성장률 하나로 대체할 수 없다.", ["Prior-year export-control inventory charge inflates operating/EPS growth comparisons.", "GAAP net income also includes investment effects; use operating result separately."]),
        source("REL-INTC-2026Q2", "Intel second quarter 2026 results", "https://www.intc.com/news-events/press-releases/detail/1776/intel-reports-second-quarter-2026-financial-results", "Intel", "2026-07-23", "2026-06-27", [
            fact("quarter_gaap_operating_income", 1.796, "USD_billion", "Q2 2026"),
            fact("quarter_gaap_net_income", -11.033, "USD_billion", "Attributable to Intel"),
            fact("escrow_mark_to_market_charge", 12.529, "USD_billion", "Non-operating fair-value charge"),
            fact("quarter_operating_cash_flow", 7.006, "USD_billion", "Q2 2026"),
            fact("gross_capex", 2.652, "USD_billion", "Q2 2026"),
            fact("partner_contributions_net", -12.216, "USD_billion", "SCIP partner contribution adjustment"),
            fact("adjusted_fcf", -8.419, "USD_billion", "Company adjusted measure including partner settlement and leases")
        ], "SOXX의 주요 Intel 노출은 NVIDIA형 수익성이 아니다. GAAP 손실과 조정 FCF에도 큰 비영업·파트너 정산 항목이 있다.", ["Do not infer normalized loss from GAAP net income alone.", "Adjusted FCF is not comparable to CFO minus gross capex.", "Altera deconsolidation changes the revenue comparison perimeter."], "2026-07-23T20:01:00Z"),
        source("REL-AMAT-FY26Q3", "Applied Materials third quarter fiscal 2026 results", "https://ir.appliedmaterials.com/news-releases/news-release-details/applied-materials-announces-third-quarter-2026-results", "Applied Materials", "2026-08-13", "2026-07-26", [
            fact("quarter_revenue", 9.115, "USD_billion", "FY26Q3"),
            fact("quarter_revenue_yoy", .25, "fraction", "FY26Q3"),
            fact("gaap_operating_margin", .337, "fraction", "FY26Q3"),
            fact("quarter_operating_cash_flow", 3.04, "USD_billion", "Rounded"),
            fact("quarter_fcf", 2.330, "USD_billion", "Company non-GAAP FCF"),
            fact("china_revenue_weight", .28, "fraction", "FY26Q3; customer shipment geography"),
            fact("next_quarter_revenue_midpoint", 10.250, "USD_billion", "FY26Q4 +/-0.5bn", "management_guidance")
        ], "DRAM·첨단 로직·패키징 수요가 장비 성장으로 연결된다. 중국 노출은 수출규제 반증 조건이다.", ["Revenue rose 25% while FCF rose 14%; profit growth does not imply equal cash growth.", "Guidance is company outlook, not an ETF return estimate."], "2026-08-13T20:01:00Z"),
        source("REL-LRCX-2026JUN", "Lam Research June quarter 2026 results", "https://investor.lamresearch.com/2026-07-29-Lam-Research-Corporation-Reports-Financial-Results-for-the-Quarter-Ended-June-28,-2026", "Lam Research", "2026-07-29", "2026-06-28", [
            fact("quarter_revenue", 6.722238, "USD_billion", "June quarter"),
            fact("previous_quarter_revenue", 5.841488, "USD_billion", "March quarter"),
            fact("gaap_operating_margin", .374, "fraction", "June quarter"),
            fact("systems_revenue", 4.249848, "USD_billion", "New leading-edge equipment"),
            fact("support_related_and_other_revenue", 2.472390, "USD_billion", "Services, spares, upgrades AND non-leading-edge Reliant equipment"),
            fact("china_revenue_weight", .26, "fraction", "June quarter"),
            fact("next_quarter_revenue_midpoint", 8.10, "USD_billion", "September quarter +/-0.4bn", "management_guidance")
        ], "성장하는 설치 기반과 장비 투자가 함께 작동한다. 고객지원 매출 전부를 SaaS형 반복매출로 부를 수 없다.", ["Quarter ended September 27 is still an unpublished result at the cutoff.", "China export-control risk remains despite AI order strength."]),
        source("REL-TXN-2026Q2", "Texas Instruments second quarter 2026 results", "https://www.ti.com/about-ti/newsroom/news-releases/2026/2026-07-22-ti-reports-second-quarter-2026-financial-results-and-shareholder-returns.html", "Texas Instruments", "2026-07-22", "2026-06-30", [
            fact("quarter_revenue", 5.46, "USD_billion", "Q2 2026; rounded"),
            fact("quarter_revenue_yoy", .23, "fraction", "Industrial, data center, automotive led growth"),
            fact("ttm_operating_cash_flow", 8.667, "USD_billion", "12 months ended June 30"),
            fact("ttm_capex", 3.312, "USD_billion", "12 months ended June 30"),
            fact("ttm_chips_incentive_proceeds", 1.179, "USD_billion", "Company FCF adds CHIPS proceeds"),
            fact("ttm_company_fcf", 6.534, "USD_billion", "CFO-capex+CHIPS proceeds")
        ], "비AI 산업·자동차 수요도 회복 근거가 있다. 보조금을 포함한 FCF는 보조금 없는 유기 현금창출과 구분한다.", ["CFO also includes CHIPS tax-credit benefits; CFO-capex is not fully incentive-neutral.", "TTM FCF must not be compared as though it were a quarterly amount."]),
        source("REL-PANW-FY26Q4", "Palo Alto Networks fourth quarter fiscal 2026 results", "https://investors.paloaltonetworks.com/news-releases/news-release-details/palo-alto-networks-reports-fiscal-fourth-quarter-and-fiscal-10", "Palo Alto Networks", "2026-09-01", "2026-07-31", [
            fact("quarter_revenue", 3.410, "USD_billion", "FY26Q4"),
            fact("quarter_revenue_yoy", .34, "fraction", "Includes acquired businesses"),
            fact("ngs_arr_growth", .63, "fraction", "ARR stock growth, not revenue growth"),
            fact("gaap_operating_income", .172, "USD_billion", "Prior-year .497bn"),
            fact("gaap_net_income", -.282, "USD_billion", "FY26Q4"),
            fact("sbc_related_charges", .487, "USD_billion", "Includes related payroll tax"),
            fact("quarter_adjusted_fcf", 1.3, "USD_billion", "Rounded; company adjusted FCF"),
            fact("fy27_ngs_arr_growth_range", [.22,.23], "fraction", "Full-year outlook vs acquisition-related base", "management_guidance"),
            fact("fy27_adjusted_fcf_margin", .38, "fraction", "Full fiscal year", "management_guidance")
        ], "보안 수요는 강하지만 인수 기여와 SBC·무형자산 상각을 분리해야 한다. ARR 성장 감속은 기저효과와 함께 검증한다.", ["Adjusted FCF excludes selected cash outflows; 38% guidance is not GAAP profitability.", "ARR, RPO and revenue have different horizons and cannot be added."]),
        source("REL-NOW-2026Q2", "ServiceNow second quarter 2026 results", "https://investor.servicenow.com/news/news-details/2026/ServiceNow-Reports-Second-Quarter-2026-Financial-Results/default.aspx", "ServiceNow", "2026-07-22", "2026-06-30", [
            fact("quarter_revenue", 3.987, "USD_billion", "Q2 2026"),
            fact("quarter_revenue_yoy", .24, "fraction", "Reported; constant currency .225"),
            fact("crpo_growth", .21, "fraction", "Next-12-month contract obligation stock"),
            fact("ai_acv_lower_bound", 1, "USD_billion", "AI annual contract value, NOT quarter recognized revenue"),
            fact("quarter_gaap_operating_income", .162, "USD_billion", "Q2 2026"),
            fact("quarter_sbc", .655, "USD_billion", "Operating reconciliation"),
            fact("quarter_operating_cash_flow", .587, "USD_billion", "Q2 2026"),
            fact("quarter_capex", .114, "USD_billion", "Q2 cash PP&E"),
            fact("quarter_adjusted_fcf", .634, "USD_billion", "Company adds .161bn combination costs")
        ], "워크플로·보안의 AI 수익화가 계약으로 확인된다. 다만 GAAP 이익·SBC·인수 비용 조정의 현금 차이가 크다.", ["Reported FCF is CFO-capex+selected cash acquisition costs, not plain cash residual.", "AI ACV cannot be added to current revenue."]),
        source("REL-SNOW-FY27Q2", "Snowflake second quarter fiscal 2027 results", "https://investors.snowflake.com/news/news-details/2026/Snowflake-Reports-Financial-Results-for-the-Second-Quarter-of-Fiscal-2027/default.aspx", "Snowflake", "2026-09-02", "2026-07-31", [
            fact("quarter_revenue", 1.546793, "USD_billion", "FY27Q2"),
            fact("product_revenue_yoy", .37, "fraction", "FY27Q2; reported"),
            fact("net_revenue_retention", 1.26, "ratio", "Dollar-based retention"),
            fact("gaap_operating_income", -.262967, "USD_billion", "FY27Q2"),
            fact("sbc_related_charges", .456363, "USD_billion", "Operating reconciliation incl payroll tax"),
            fact("quarter_operating_cash_flow", .091357, "USD_billion", "FY27Q2"),
            fact("quarter_fcf", .083803, "USD_billion", "CFO minus capex"),
            fact("fy27_product_revenue_guidance", 6.070, "USD_billion", "Previously5.840; 36% YoY", "management_guidance")
        ], "AI 데이터 소비 증가와 가이던스 상향은 소프트웨어 반론이다. GAAP 손실·주식보상과 소비 최적화 위험은 함께 고려한다.", ["Dated release verified; dynamic quarterly summary contained mismatched stale quotes, excluded.", "NRR is a retention metric, not a probability; quarterly FCF is seasonal."]),
        source("REL-PLTR-2026Q2", "Palantir second quarter 2026 results", "https://www.sec.gov/Archives/edgar/data/1321655/000132165526000039/a2026q2ex991pressrelease.htm", "Palantir / SEC", "2026-08-03", "2026-06-30", [
            fact("quarter_revenue", 1.935464, "USD_billion", "Q2 2026"),
            fact("quarter_revenue_yoy", .93, "fraction", "Reported"),
            fact("us_commercial_revenue_yoy", 1.49, "fraction", "US commercial subset"),
            fact("gaap_operating_income", .912004, "USD_billion", "Q2 2026"),
            fact("quarter_operating_cash_flow", 1.216167, "USD_billion", "Q2 2026"),
            fact("quarter_capex", .014554, "USD_billion", "Q2 cash PP&E"),
            fact("quarter_adjusted_fcf", 1.220359, "USD_billion", "CFO-capex+SBC-related payroll tax .018746"),
            fact("next_quarter_revenue_range", [2.160,2.164], "USD_billion", "Q3 2026", "management_guidance")
        ], "AI 구현 기업에는 이미 높은 GAAP 이익과 현금 창출을 내는 예외가 있다. 소프트웨어 전체를 수익화 미완성으로 규정할 수 없다.", ["Government/commercial mix and contract cancellation clauses matter.", "Rule-of-40 is an operating score, not an expected investment return.", "Current market multiple is not verified here; strong growth alone does not prove undervaluation."]),
        source("REL-ORCL-FY27Q1", "Oracle first quarter fiscal 2027 results", "https://www.oracle.com/news/announcement/q1fy27-earnings-release-2026-09-10/", "Oracle", "2026-09-10", "2026-08-31", [
            fact("quarter_revenue", 19.3, "USD_billion", "FY27Q1; rounded"),
            fact("quarter_revenue_yoy", .30, "fraction", "Reported"),
            fact("iaas_revenue_yoy", 1.21, "fraction", "Infrastructure business"),
            fact("saas_revenue_yoy", .10, "fraction", "Applications business"),
            fact("rpo", 664, "USD_billion", "Multi-year obligations, not current quarter revenue"),
            fact("quarter_operating_cash_flow", 23, "USD_billion", "Company rounded value"),
            fact("quarter_fcf", -5, "USD_billion", "Company rounded value"),
            fact("atm_equity_sale", 20, "USD_billion", "Before commissions; during quarter")
        ], "IGV 상위 종목에도 막대한 데이터센터 투자·자금조달 부담이 있다. 인프라 성장과 응용 SaaS 성장의 속도가 다르다.", ["CFO23 minus FCF(-5) implies28bn cash spend only at release's rounding precision.", "RPO must be discounted by recognition timing, counterparties, financing and margins."]),
        source("REL-ADBE-FY26Q3", "Adobe third quarter fiscal 2026 results", "https://www.sec.gov/Archives/edgar/data/796343/000079634326000147/adbeex991q326.htm", "Adobe / SEC", "2026-09-10", "2026-08-28", [
            fact("quarter_revenue", 6.76, "USD_billion", "FY26Q3; rounded"),
            fact("quarter_revenue_yoy", .13, "fraction", "Reported; constant currency .12"),
            fact("total_arr", 27.50, "USD_billion", "Annualized recurring revenue stock"),
            fact("ai_first_arr_growth_lower_bound", 1.50, "fraction", "More than150% YoY; not total revenue"),
            fact("quarter_gaap_operating_income", 2.354, "USD_billion", "FY26Q3"),
            fact("quarter_operating_cash_flow", 2.523, "USD_billion", "FY26Q3"),
            fact("quarter_capex", .085, "USD_billion", "Cash PP&E"),
            fact("quarter_sbc", .539, "USD_billion", "Cash-flow adjustment")
        ], "기존 창작 SaaS에도 현금 창출과 AI 성장이 있다. AI ARR 빠른 성장과 전체 ARR 성장·대체 위험은 따로 판단한다.", ["AI ARR growth is not identical to revenue contribution or replacement losses.", "Freemium adoption/MAUs do not directly identify paid monetization or stock upside."]),
        source("REL-FED-2026SEP", "FOMC statement September 16, 2026", "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm", "Federal Reserve", "2026-09-16", "2026-09-16", [
            fact("target_range", [.0375,.04], "fraction_per_year", "After25bp hike"),
            fact("target_increase", .0025, "fraction_per_year", "25basis points")
        ], "정책금리 인상은 양쪽 섹터의 배수 확대를 제한할 수 있다. 낮은 성장 SaaS가 자동으로 금리 방어주가 되는 것은 아니다.", ["Policy rate is not the long Treasury discount rate.", "No assumption that rate changes cause a fitted relative-price move."], "2026-09-16T18:00:00Z"),
        source("REL-BLS-2026SEP-JOBS", "Employment Situation September 2026", "https://www.bls.gov/news.release/archives/empsit_10022026.htm", "Bureau of Labor Statistics", "2026-10-02", "2026-09-30", [
            fact("nonfarm_monthly_change", 29000, "persons", "September initial release vintage"),
            fact("unemployment_rate", .042, "fraction", "September household survey"),
            fact("prior_two_month_revision", -60000, "persons", "July/August combined at this vintage")
        ], "고용 둔화와 금리 인상이 공존한다. 연착륙·성장 둔화·인플레이션 지속의 조건을 별도로 검토한다.", ["Monthly changes have sampling uncertainty and are subsequently revised.", "Use this release vintage for as-of analysis, not later revisions."], "2026-10-02T12:30:00Z"),
        source("REL-NVDA-CALL-CALENDAR", "NVIDIA fiscal Q2 2027 call calendar remarks", "https://investor.nvidia.com/files/content_files/TRANSCRIPT_-NVIDIA-Corp-NVDA-US-Q2-2027-Earnings-Call-26-August-2026-5_00-PM-ET.pdf", "NVIDIA-hosted FactSet transcript", None, "2026-08-26", [
            fact("next_earnings_call_date", "2026-11-17", "date", "FY27Q3 planned call", "announced_schedule"),
            fact("gtc_berlin_keynote_date", "2026-10-21", "date", "CEO scheduled keynote", "announced_schedule")
        ], "연말 이전 주요 촉매는 실적·다음 분기 전망과 공급·제품 전환 확인이다.", ["Corrected transcript's historical upload/correction timestamp not archived.", "Dates can change; event results after cutoff are excluded."]),
        source("REL-LRCX-CALENDAR", "Lam Research upcoming earnings calendar", "https://investor.lamresearch.com/events?item=95", "Lam Research", None, "2026-10-12", [
            fact("next_earnings_call_date", "2026-10-21", "date", "September2026 quarter planned results", "announced_schedule")
        ], "9월 분기 장비 수요와 다음 분기 매출 가이던스가 반도체 상대 논리를 시험한다.", ["Original announcement publication timestamp missing; context only."]),
        source("REL-MSFT-CALENDAR", "Microsoft upcoming earnings calendar", "https://www.microsoft.com/en-us/investor/default?l=5", "Microsoft", None, "2026-10-12", [
            fact("next_earnings_call_date", "2026-10-28", "date", "FY27Q1 planned results", "announced_schedule")
        ], "Azure·Copilot 매출, 투자와 현금 전환이 하드웨어 수요와 소프트웨어 수익화를 동시에 검증한다.", ["Dynamic event page lacks original announcement timestamp; context only."]),
        source("REL-ORCL-CALENDAR", "Oracle investor FAQ earnings calendar", "https://investor.oracle.com/faq/default.aspx", "Oracle", None, "2026-10-12", [
            fact("next_earnings_call_date", "2026-12-14", "date", "FY27Q2 planned results", "announced_schedule")
        ], "다년 계약의 매출 인식·투자비·자금조달을 연말 전에 재확인하는 촉매다.", ["Dynamic FAQ publication timestamp missing; context only."])
    ]
    ids = [s["id"] for s in sources]
    assert len(ids) == len(set(ids)), "Duplicate source ids"
    as_of = datetime.fromisoformat(AS_OF)
    for s in sources:
        if s.get("available_at"):
            assert datetime.fromisoformat(s["available_at"].replace("Z", "+00:00")) <= as_of, s["id"]
    result = dict(
        schema_version=1, research_as_of=AS_OF, price_as_of="2026-10-09",
        horizon_end="2026-12-31", currency="USD", official_forecast=False,
        probability_unit="fraction", validated_sector_probability=None,
        compiled_at=datetime.now(timezone.utc).isoformat(),
        timestamp_policy="New REL-source exact web-fetch timestamps are unavailable and therefore null; compiled_at only records this build. Reused TECH-source metadata retains the earlier study's explicit compilation-time convention. Availability proxies and exact stated public release times are distinguished.",
        baseline_sha256=hashlib.sha256(original_bytes).hexdigest(),
        sources=sources,
        feature_policy={
            "corporate_facts_use": "Qualitative current-state comparison; not fitted point-in-time historical ML features",
            "current_etf_snapshot_use": "Issuer-dated observations with unverified historical page availability, explicit limit",
            "guidance_use": "Management outlook; never relabeled realized earnings or year-end stock return",
            "scenario_input_use": "Explicit analyst assumptions from preserved baseline; no calibration from these facts",
            "probability_policy": "No conversion from internal Brier or EPS-event accuracy to SOXX-vs-IGV success probability"
        },
        excluded_or_missing=[
            "Archived historical forward EPS/FCF expectations and normalized common valuation denominator not available",
            "Dynamic Snowflake quarterly summary stale quote/output mixed; dated press release used",
            "Treasury10/9 official long-yield page unavailable in this research tool; GS9/30 commentary not passed as10/9 spot",
            "Micron HBM revenue split not separately verified; memory revenue not called HBM-only",
            "Future quarters/results after cutoff excluded even where earnings dates are known"
        ]
    )
    out = ROOT / "relative_evidence.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"sources":len(sources),"baseline_reused":len(reuse),"new_sources":len(sources)-len(reuse),"output":str(out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
