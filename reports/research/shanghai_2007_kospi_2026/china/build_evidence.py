"""Curated historical evidence with explicit source units and vintage limits."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = json.loads((ROOT / "source_manifest.json").read_text(encoding="utf8"))
SOURCE = {s["source_id"]: s for s in MANIFEST["sources"]}


def measure(name, value, unit, normalized=None, normalized_unit=None, **extra):
    item = {"name": name, "original_value": value, "original_unit": unit,
            "normalized_value": value if normalized is None else normalized,
            "normalized_unit": unit if normalized_unit is None else normalized_unit}
    item.update(extra)
    return item


def fraction(name, value, kind="share"):
    return measure(name, value, "percent", value / 100, "fraction", semantic_type=kind, conversion="original percent / 100", is_probability=False)


def fact(fid, statement, sid, locator, period, measurements=None, status="supported", caveat=None):
    s = SOURCE[sid]
    pub = s["published_at"]
    before_peak = bool(pub and ((len(pub) == 10 and pub < "2007-10-16") or (len(pub) == 7 and pub < "2007-10")))
    return {"evidence_id": fid, "statement": statement, "claim_status": status,
        "data_period": period, "source_id": sid, "source_url": s["url"],
        "source_local_path": s["local_path"], "source_sha256": s["sha256"],
        "source_locator": locator, "source_published_at": pub,
        "retrieved_at_utc": s["retrieved_at_utc"],
        "available_at": None,
        "availability_note": "Exact original public availability timestamp is not established. Publication date is separate metadata, not an intraday availability timestamp.",
        "pit_relation_to_2007_10_16_peak": "contemporaneous_or_earlier_source" if before_peak else "retrospective_source_or_publication_date_unknown",
        "measurements": measurements or [], "interpretation_caveat": caveat}


def main():
    facts = []
    add = facts.append
    add(fact("CN_INDEX_IDENTITY", "2007-10-16 intraday highs differ between SSE Composite and SSE A Share; the attachment's approximately 6429 level is consistent with A Share, conditional on chart identity verification.", "sse_yearbook_2008", "PDF page 19 (1-based), printed page 7, Data of SSE Index Series 2007", "2007-10-16", [measure("composite_intraday_high", 6124.04, "index_points"), measure("a_share_intraday_high", 6429.68, "index_points")], caveat="Intraday highs are not daily closes. Do not compare Composite peak 6124 with A Share level 6429 or treat chart annotations as an independently authenticated series."))
    add(fact("CN_PRICE_2007", "SSE Composite 2007 annual price return was 96.66%; A Share was 96.14%.", "sse_yearbook_2008", "PDF page 19 (1-based), printed page 7", "2007-01-01/2007-12-31", [fraction("composite_annual_price_return",96.66,"price_return"),fraction("a_share_annual_price_return",96.14,"price_return")], caveat="Price returns exclude dividends and currency translation."))
    add(fact("CN_PRICE_2008", "2008 annual price returns were -65.39% for Composite and -65.38% for A Share.", "sse_yearbook_2009", "PDF page 13 (1-based), printed page 7", "2008-01-01/2008-12-31", [fraction("composite_annual_price_return",-65.39,"price_return"),fraction("a_share_annual_price_return",-65.38,"price_return")], caveat="This outcome is hindsight and cannot be used to select an ex ante 2007 warning rule or as a Korea forecast probability."))
    add(fact("CN_PE_DEFINITION", "The historical SSE definition uses stock price divided by prior-year after-tax EPS; aggregate PE is sum(close*issued shares)/sum(EPS*issued shares).", "sse_yearbook_2008", "PDF page 5 (1-based), printed page 1, definitions 14 and 17; visually checked in qa/pe_definition_2008.png", "2007", caveat="A lagged annual earnings denominator, not TTM or forward consensus. Published loss-company treatment and revision schedules have not been separately established. Average PE is not the arithmetic mean of constituent PE values."))
    add(fact("CN_PE_LEVELS", "Year-end SSE average PE rose materially from 2005 through 2007.", "sse_yearbook_2008", "PDF page 16 (1-based), printed page 4, Overview / Average P/E Ratio", "2005-12-31/2007-12-31", [measure("2005_year_end_average_pe",16.33,"times"),measure("2006_year_end_average_pe",33.30,"times"),measure("2007_year_end_average_pe",59.24,"times")], caveat="2007 year-end PE follows the October peak. Denominators, index membership, issuance, accounting changes and valuation date must match before any earnings/valuation decomposition."))
    add(fact("CN_EQUITY_SUPPLY", "The boom also coincided with sharply higher A-share capital raising and a large difference between issued and negotiable capitalization.", "sse_yearbook_2008", "PDF page 15 (1-based), printed page 3, Overview / Capital Raised and Market Capitalization", "2006-12-31/2007-12-31", [measure("2007_a_share_capital_raised",6701.33,"CNY_100_million",670133000000,"CNY"),measure("2006_a_share_capital_raised",1713.51,"CNY_100_million",171351000000,"CNY"),measure("2007_year_end_total_stock_market_capitalization",269838.87,"CNY_100_million",26983887000000,"CNY"),measure("2007_year_end_negotiable_market_capitalization",64532.17,"CNY_100_million",6453217000000,"CNY")], caveat="Capital raised is not labeled IPO-only and should not be described as such. Total issued and negotiable capitalization are different universes. Supply changes and listing composition confound a simple earnings-versus-PE return attribution."))
    add(fact("CN_SECTOR_PRICE_RETURNS", "The exchange reports different 2007 price returns across its legacy sector indices.", "sse_yearbook_2008", "PDF page 19 (1-based), printed page 7, Data of SSE Index Series 2007", "2007-01-01/2007-12-31", [fraction("industrial_index_price_return",137.47,"price_return"),fraction("real_estate_index_price_return",148.60,"price_return"),fraction("utilities_index_price_return",174.75,"price_return"),fraction("conglomerates_index_price_return",52.53,"price_return")], caveat="These are sector-index price returns, not sector contributions to Composite or A Share returns. Legacy sector definitions and contemporaneous weights need separate reconciliation."))
    add(fact("CN_RETAIL_TURNOVER", "In the SSE's 2007 share-investor table, natural persons had 86.01% trading share and a positive net purchase balance.", "sse_yearbook_2008", "PDF page 352 (1-based), printed page 340, Balance of Investors in 2007", "2007-01-01/2007-12-31", [fraction("natural_person_trading_share",86.01),measure("natural_person_net_purchase",2854.45,"CNY_100_million",285445000000,"CNY",conversion="original 100 million CNY * 100000000"),measure("general_corporation_net_purchase",-4100.18,"CNY_100_million",-410018000000,"CNY"),measure("professional_institution_net_purchase",1246.12,"CNY_100_million",124612000000,"CNY")], caveat="Do not generalize this share-investor table to all securities such as bond/repo trades. Annual exchange-level net balance is not household new cash contributed or continuous daily buying. Source rounding means investor-category balances need not sum exactly to zero."))
    add(fact("CN_RETAIL_ACCOUNTS", "Natural-person new A-share accounts rose sharply; accounts are not a national unique-investor headcount.", "sse_yearbook_2008", "PDF pages 349-350 (1-based), printed pages 337-338, Historical Data of Shareholder's Accounts", "2006-01-01/2007-12-31", [measure("2006_new_natural_person_a_accounts",150.5,"ten_thousand_accounts",1505000,"accounts"),measure("2007_new_natural_person_a_accounts",1867.4,"ten_thousand_accounts",18674000,"accounts"),measure("2006_natural_person_a_account_total",3778.5,"ten_thousand_accounts",37785000,"accounts"),measure("2007_natural_person_a_account_total",5645.9,"ten_thousand_accounts",56459000,"accounts")], caveat="This SSE-only A-share count must not be mixed with CSRC combined-exchange or SSE fund-inclusive account counts. Account activity, dormant-account treatment and unique-person coverage differ."))
    add(fact("CN_RETAIL_HOLDINGS", "Natural persons held 48.29% of the year-end shareholding market value reported in the investor table, while their trading share was substantially higher.", "sse_yearbook_2008", "PDF page 352 (1-based), printed page 340, Share Hold of Investors by 2007", "2007-12-31", [fraction("natural_person_shareholding_value_share",48.29),measure("natural_person_holding_accounts",24867825,"accounts")], caveat="Investor table's holdings universe differs from total issued capitalization. Do not equate 48.29% with natural persons owning that share of all Chinese corporate equity."))
    add(fact("CN_RETAIL_MONTHLY_ACCOUNT_CUMULATIVE", "The monthly 2007 account-opening table reports cumulative year-to-date additions, not additions during each month.", "sse_yearbook_2008", "PDF page 353 (1-based), printed page 341, Open Account of Investor", "2007-01-01/2007-12-31", [measure("a_share_ytd_openings_end_january",69.26,"ten_thousand_accounts",692600,"accounts"),measure("a_share_ytd_openings_end_may",756.67,"ten_thousand_accounts",7566700,"accounts"),measure("a_share_ytd_openings_end_october",1599.88,"ten_thousand_accounts",15998800,"accounts"),measure("a_share_ytd_openings_end_december",1873.24,"ten_thousand_accounts",18732400,"accounts")], caveat="December value equals the stated annual total; summing monthly rows would double count. Original rows include all A-share accounts, whereas the natural-person annual table excludes institutions."))
    add(fact("CN_DORMANT_CLEANUP", "20.23 million dormant accounts were segregated on October 8, 2007 under the account-standardization process.", "csrc_dormant_accounts_20071009", "Article body, account segregation effective October 8", "2007-10-08", [measure("dormant_accounts_segregated",2023,"ten_thousand_accounts",20230000,"accounts")], caveat="Account cleaning creates a potential measurement break in active/total account series; this is not equivalent to investors withdrawing on that day."))
    add(fact("CN_RETAIL_OFFICIAL_WARNING", "CSRC acknowledged rapid entry by inexperienced small investors and explicitly emphasized risk education and cautious participation.", "csrc_retail_risk_20071018", "Interview on October 17, article published October 18; section on current priority of investor risk education", "2007-10-17", caveat="Published two days after the October 16 peak, so this particular article is not a pre-peak warning observation. Earlier risk education is described but primary publication timestamps must be established separately."))
    add(fact("CN_CONCENTRATION", "Year-end 2007 A-share capitalization was concentrated in energy, banks and insurers rather than a pure export-manufacturing basket.", "sse_yearbook_2008", "PDF page 77 (1-based), printed page 65, Top 10 A Shares by Market Capitalization", "2007-12-31", [fraction("top10_share",51.87),fraction("petrochina_share",18.67),fraction("icbc_share",7.60),fraction("sinopec_share",6.10),fraction("china_life_share",4.49),fraction("bank_of_china_share",4.38),fraction("china_shenhua_share",4.03)], caveat="These are year-end full-issued capitalization shares, not free-float weights at the October peak. PetroChina entered in November 2007. Do not project this membership back onto the pre-peak period."))
    add(fact("CN_EARNINGS_2007_REPORTED", "SSE's review states overall listed-company performance grew 47.5% and weighted EPS reached CNY 0.42.", "sse_2007_earnings_review", "Article dated 2008-06-02, opening paragraph; reports disclosed by 2008-04-30", "2007-01-01/2007-12-31", [fraction("exchange_reported_overall_performance_yoy",47.5,"earnings_growth"),measure("weighted_earnings_per_share",0.42,"CNY_per_share")], caveat="The source labels 47.5% as overall performance, not a same-constituent point-in-time index EPS growth series. Realized 2007 annual performance released in 2008 cannot validate what investors knew at the 2007 peak. Global first-place ranking remains unverified."))
    add(fact("CN_ACCOUNTING_2007", "The 2007 new accounting standards changed opening equity and introduced a fair-value change line in reported earnings.", "sse_2007_earnings_review", "Second substantive paragraph on new accounting standards", "2007-01-01/2007-12-31", [fraction("opening_equity_upward_adjustment_approximate",9,"accounting_adjustment"),fraction("fair_value_change_share_of_annual_net_profit",2.6)], caveat="The 2.6% line alone does not measure all investment-related gains or all accounting comparability effects. Adjustments need an explicit reconciliation; no silent restatement."))
    add(fact("CN_EXPORTS_2007", "China's goods exports and industrial profits expanded strongly in 2007, supporting the real-economy boom hypothesis.", "nbs_2007_communique", "Foreign Economic Relations / Table 6; Industrial and Construction / Table 3", "2007-01-01/2007-12-31", [fraction("goods_exports_yoy",25.7,"growth_rate"),measure("goods_exports_value",1218.0,"USD_billion",1218000000000,"USD"),fraction("industrial_profit_jan_nov_yoy",36.7,"growth_rate"),fraction("private_industrial_profit_jan_nov_yoy",50.9,"growth_rate")], caveat="Industrial profits cover designated-size enterprises and only January-November, not the listed index or full calendar-year earnings. All figures belong to the February 2008 vintage."))
    add(fact("CN_GDP_VINTAGE", "The February 2008 statistical communique initially reported 2007 real GDP growth of 11.4%.", "nbs_2007_communique", "General Outlook, opening GDP paragraph", "2007-01-01/2007-12-31", [fraction("initial_reported_real_gdp_yoy",11.4,"growth_rate")], caveat="Subsequently revised GDP histories must be stored as separate vintages. Do not silently substitute later revisions in an ex ante reconstruction."))
    add(fact("CN_EXPORT_RANK", "WTO ranks China second in 2007 merchandise exports after Germany; China moved ahead of the United States.", "wto_2008_trade_review_pdf", "Press/520/Rev.1; ranking discussion and Appendix leading merchandise exporters", "2007-01-01/2007-12-31", [measure("merchandise_export_country_rank",2,"ordinal_rank")], caveat="Export rank is not earnings-growth rank, manufacturing value-added rank, or stock-return rank. PDF is dated April 17, 2008; the HTML and PDF are this revised release vintage."))
    add(fact("CN_SPLIT_SHARE_REFORM", "The nontradable share reform began in April 2005; by April 2006 almost 900 of approximately 1350 companies, representing 70% of capitalization, had completed it.", "imf_2006_article_iv", "Equity market box / non-tradable share reform discussion", "2005-04/2006-04", [measure("companies_completed_approximate",900,"companies"),measure("companies_total_approximate",1350,"companies"),fraction("capitalization_completed_share",70)], caveat="This supports government-led market institution reform; it does not prove an official promise to prevent price declines or an instruction for every household to buy."))
    add(fact("CN_MANUFACTURING_TREND", "An IMF September 2007 analysis describes export integration, investment incentives and low capital cost as multi-year drivers of China becoming a world workshop.", "imf_rebalancing_200709", "How it began / Why is investment high?", "1994/2007", caveat="A policy-and-finance mechanism extending over years, not a megatrend first appearing in 2007. The document is an IMF staff analysis, not proof that 2007 China led global listed-company earnings growth."))
    add(fact("CN_MONETARY_TIGHTENING", "PBC records six benchmark rate increases and ten reserve-requirement increases in 2007, with reserve ratios rising by 5.5 percentage points.", "pbc_policy_2007q4", "PDF pages 2 and 14 (1-based), Executive Summary and printed page 9", "2007-01-01/2007-12-31", [measure("benchmark_rate_hike_count",6,"events"),measure("reserve_ratio_hike_count",10,"events"),measure("cumulative_reserve_ratio_change",5.5,"percentage_points",0.055,"fraction_point_change",conversion="percentage points / 100",is_probability=False)], caveat="Historical policy action chronology is available in Appendix 1. The annual narrative is dated February 22, 2008. Monetary policy addressed inflation/liquidity; a direct stock-price causal effect is a separate hypothesis."))
    add(fact("CN_STAMP_DUTY", "The May 30, 2007 MOF/SAT notice imposed securities stamp duty at 3 per mille on each counterparty to A/B share transfers.", "mof_stamp_duty_20070530", "Caishui [2007] 84, stated issuance/effective date May 30; MOFCOM repost July 4", "2007-05-30", [measure("stamp_duty_rate_per_side",3,"per_mille",0.003,"fraction",conversion="per mille / 1000",is_probability=False)], caveat="Original notice date and repost date are distinct. This notice establishes the new rate; the prior 1-per-mille rate is not independently established by this archived notice alone."))
    add(fact("CN_STAMP_DUTY_PRIOR_RATE", "MOF's fiscal-revenue analysis explicitly confirms the May 30, 2007 stamp duty increase from 1 per mille to 3 per mille, charged to both sides.", "mof_2007_revenue_review", "Section 7, securities transaction stamp tax; footer states publication date March 5, 2008", "2007-05-30", [measure("prior_stamp_rate_per_side",1,"per_mille",0.001,"fraction",conversion="per mille / 1000",is_probability=False),measure("new_stamp_rate_per_side",3,"per_mille",0.003,"fraction",conversion="per mille / 1000",is_probability=False)], caveat="Retrospective corroboration of the prior rate. URL includes August 2008 migration date; the visible footer publication date is March 5, 2008."))
    add(fact("CN_MARGIN_STRUCTURE", "CSRC's January 8, 2010 notice announces approval in principle of margin-trading pilot and stock-index futures.", "csrc_margin_pilot_20100108", "Article body on State Council approval", "2010-01-08", caveat="2007 should not be analyzed using the 2015 official margin-financing mechanism or current Korean margin balances without recognizing different market structures. This notice does not exclude every possible informal leverage channel in 2007."))

    events = []
    reserve_events = [
        ("2007-01-05","2007-01-15",0.5,None,59),
        ("2007-02-16","2007-02-25",0.5,None,59),
        ("2007-04-05","2007-04-16",0.5,10.5,60),
        ("2007-04-29","2007-05-15",0.5,11.0,60),
        ("2007-05-18","2007-06-05",0.5,11.5,61),
        ("2007-07-30","2007-08-15",0.5,12.0,62),
        ("2007-09-06","2007-09-25",0.5,12.5,63),
        ("2007-10-13","2007-10-25",0.5,13.0,64),
        ("2007-11-10","2007-11-26",0.5,13.5,64),
        ("2007-12-08","2007-12-25",1.0,14.5,64),
    ]
    for announcement, effective, delta, target, page in reserve_events:
        events.append({"event_id": f"CN_RRR_{announcement}", "event_type": "reserve_requirement_increase", "announcement_date": announcement,
            "effective_date": effective, "source_id": "pbc_policy_2007q4", "source_pdf_page_1based": page,
            "source_printed_page": page-5, "source_published_at": "2008-02-22", "available_at": None,
            "original_change_percentage_points": delta, "normalized_change_fraction_points": delta/100,
            "original_target_percent": target, "normalized_target_fraction": None if target is None else target/100,
            "timing_caveat": "Retrospective chronology reports original announcement/effective dates; exact original announcement timestamp not independently archived here. December action continues on PDF page 65."})
    rates = [
        ("2007-03-18",2.52,2.79,6.12,6.39,60),
        ("2007-05-19",2.79,3.06,6.39,6.57,61),
        ("2007-07-21",3.06,3.33,6.57,6.84,62),
        ("2007-08-22",3.33,3.60,6.84,7.02,63),
        ("2007-09-15",3.60,3.87,7.02,7.29,63),
        ("2007-12-21",3.87,4.14,7.29,7.47,65),
    ]
    for action, depold, depnew, loanold, loannew, page in rates:
        events.append({"event_id":f"CN_RATE_{action}", "event_type":"benchmark_rate_increase", "action_date_as_stated":action,
            "announcement_date":None, "effective_date":None, "source_id":"pbc_policy_2007q4", "source_pdf_page_1based":page,
            "source_printed_page":page-5, "source_published_at":"2008-02-22", "available_at":None,
            "one_year_deposit_old_percent":depold,"one_year_deposit_new_percent":depnew,
            "one_year_lending_old_percent":loanold,"one_year_lending_new_percent":loannew,
            "one_year_deposit_old_fraction":depold/100,"one_year_deposit_new_fraction":depnew/100,
            "one_year_lending_old_fraction":loanold/100,"one_year_lending_new_fraction":loannew/100,
            "timing_caveat":"Appendix uses an action/decision date. Do not assume this is a precise announcement timestamp. May 19 effective date is separately stated in pbc_rate_20070519."})
    events.append({"event_id":"CN_STAMP_20070530", "event_type":"securities_stamp_duty_change", "announcement_date":None, "effective_date":"2007-05-30", "source_id":"mof_stamp_duty_20070530", "source_published_at":"2007-07-04", "original_notice_date":"2007-05-30", "available_at":None,"rate_original_per_mille_per_side":3,"rate_fraction_per_side":0.003,"direction":"increased_transaction_cost","timing_caveat":"Saved page is July 4 repost with original May 30 notice; original announcement date/time not independently authenticated. Effective date is not assumed to be the announcement date."})

    result = {"schema_version":1,"created_at_utc":datetime.now(timezone.utc).isoformat(),"research_as_of_date":"2026-10-16",
        "purpose":"Historical China comparator evidence for Shanghai 2007 versus KOSPI 2026; descriptive research only.",
        "official_forecast":False,"probability_outputs":[],
        "unit_policy":"Every original numeric unit is explicit. Growth, return and share percentages normalize by /100; per mille by /1000; percentage-point changes by /100 to fraction-point changes. These rates are not forecast probabilities. No magnitude-based unit inference, clipping or normalization to force validity.",
        "source_manifest":"source_manifest.json",
        "claims":[
            {"claim_id":"world_factory_beneficiary","status":"partially_supported","evidence_ids":["CN_EXPORTS_2007","CN_EXPORT_RANK","CN_MANUFACTURING_TREND"],"conclusion":"Strong export/profit boom is established; a uniquely first-place country beneficiary and direct listed-index exposure are not established."},
            {"claim_id":"china_2007_global_first_earnings_growth","status":"unverified","evidence_ids":["CN_EARNINGS_2007_REPORTED","CN_EXPORTS_2007"],"conclusion":"No matched global country-index EPS growth ranking or contemporary forecast vintage is available in this China evidence pack."},
            {"claim_id":"retail_frenzy","status":"supported_with_qualification","evidence_ids":["CN_RETAIL_TURNOVER","CN_RETAIL_ACCOUNTS","CN_RETAIL_HOLDINGS","CN_DORMANT_CLEANUP"],"conclusion":"Heavy natural-person turnover, positive annual net purchases and very rapid account growth; not literal universal participation."},
            {"claim_id":"uniform_government_buying_encouragement","status":"contradicted_as_a_uniform_claim","evidence_ids":["CN_SPLIT_SHARE_REFORM","CN_MONETARY_TIGHTENING","CN_STAMP_DUTY","CN_RETAIL_OFFICIAL_WARNING"],"conclusion":"Market development reform coexisted with tightening, tax increases and risk warnings. No evidence here of an unconditional household-buying directive."},
            {"claim_id":"chart_path_predicts_korea_crash","status":"not_established","evidence_ids":["CN_INDEX_IDENTITY","CN_PRICE_2008","CN_CONCENTRATION","CN_MARGIN_STRUCTURE"],"conclusion":"Two selected episodes cannot establish a predictive crash probability or causal correlation. Prospective matched-universe analysis and counterexamples are required."}],
        "observations":facts,"policy_events":events,
        "daily_data":{"canonical_all_years":"daily_indices_2005_2008.csv","core_2006_2008":"daily_indices_2006_2008.csv","all_years_audit":"daily_extraction_audit_2005_2008.json","origin":"Original SSE numeric tables, not generated prices. No interpolated dates or inferred levels.","vintage":"Retrospective official yearbooks; original daily release timestamps unverified."},
        "remaining_gaps":["Comparable global point-in-time country-index forward EPS growth rankings for 2007 and 2026","2007 peak-date composition/free-float sector contribution and same-company earnings growth","Authenticated original timestamps for every policy announcement and historical consensus snapshot","Comparable unique household ownership/active-account metrics across China and Korea","A causal identification design separating trend earnings, revaluation, liquidity, regulation and the global financial crisis"]}
    (ROOT/'evidence.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
    for s in MANIFEST['sources']:
        assert s['status']=='saved',s
        path=ROOT/s['local_path']
        assert hashlib.sha256(path.read_bytes()).hexdigest()==s['sha256'],s['source_id']
    derived=[]
    for path in sorted(ROOT.glob('raw_table_page_*.txt'))+sorted((ROOT/'sources').glob('*.txt'))+sorted((ROOT/'qa').glob('*.png')):
        derived.append({"local_path":path.relative_to(ROOT).as_posix(),"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"bytes":path.stat().st_size,"origin":"Derived text-layer/HTML text extraction or PDF rendering; original document bytes retained separately."})
    MANIFEST['derived_artifacts']=derived
    MANIFEST['validation']={"all_saved_source_hashes_match":True,"source_count":len(SOURCE),"evidence_count":len(facts),"policy_event_count":len(events)}
    (ROOT/'source_manifest.json').write_text(json.dumps(MANIFEST,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
    print(json.dumps(MANIFEST['validation'],indent=2))


if __name__=='__main__':
    main()
