"""Offline chronology from retained official documents and historical XLS files.

No new estimates of people, retail flows, forced selling, or causal policy effects.
Policy rates are explicit percent/year; returns are fractions; no probabilities.
"""
from __future__ import annotations
import bisect
import calendar
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
import xlrd

ROOT = Path(__file__).resolve().parent
STUDY = ROOT.parent.parent
PRICE_PATH = STUDY / "prices/prices.csv"
PRICE_SHA = "77049dd7d90c981b73000d78e0c4897171941451f24e814b865acdb9a9940715"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(name, rows):
    with (ROOT / name).open("w", newline="", encoding="utf8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def load_prices():
    if sha(PRICE_PATH) != PRICE_SHA:
        raise ValueError("Frozen parent price input changed")
    with PRICE_PATH.open(encoding="utf8") as f:
        rows = [r for r in csv.DictReader(f) if r["symbol"] == "SSE_COMPOSITE"]
    if not rows:
        raise ValueError("SSE_COMPOSITE prices missing")
    values = {r["date"]: float(r["close"]) for r in rows}
    if len(values) != len(rows):
        raise ValueError("Duplicate Shanghai dates")
    return values


def first_session_at_or_after(date, prices):
    dates = sorted(prices)
    i = bisect.bisect_left(dates, date)
    if i == len(dates):
        return None
    return dict(date=dates[i], close=prices[dates[i]],
                calendar_gap_days=(dt.date.fromisoformat(dates[i])-dt.date.fromisoformat(date)).days)


def policy_events():
    events = []

    def add(eid, announcement, effective, kind, label, source_ids, locator, **values):
        events.append(dict(event_id=eid, announcement_date=announcement, effective_date=effective,
                           category=kind, label=label, source_ids=source_ids, locator=locator,
                           observation_date=effective, original_release_time_known=False, **values))

    rrr = [
        ("2007-01-05", "2007-01-15", 9.5, 0.5, 59),
        ("2007-02-16", "2007-02-25", 10, 0.5, 59),
        ("2007-04-05", "2007-04-16", 10.5, 0.5, 60),
        ("2007-04-29", "2007-05-15", 11, 0.5, 60),
        ("2007-05-18", "2007-06-05", 11.5, 0.5, 61),
        ("2007-07-30", "2007-08-15", 12, 0.5, 62),
        ("2007-09-06", "2007-09-25", 12.5, 0.5, 63),
        ("2007-10-13", "2007-10-25", 13, 0.5, 64),
        ("2007-11-10", "2007-11-26", 13.5, 0.5, 64),
        ("2007-12-08", "2007-12-25", 14.5, 1, 64),
    ]
    for announcement, effective, rate, change, page in rrr:
        add("RRR_"+effective.replace("-", ""), announcement, effective, "monetary_tightening",
            f"RMB depository-institution RRR +{change} percentage points to {rate}%",
            ["pbc_policy_2007q4"], {"pdf_page_1based": page, "printed_page": page-5,
             "note": "December 8 paragraph continues on PDF page 65" if announcement == "2007-12-08" else None},
            rrr_percent=rate, rrr_change_percentage_points=change)

    rates = [
        ("2007-03-17", "2007-03-18", 2.79, 6.39, "CYD_RATE20070317", 60),
        ("2007-05-18", "2007-05-19", 3.06, 6.57, "PBC_RATE20070518_PRIMARY", 61),
        ("2007-07-20", "2007-07-21", 3.33, 6.84, "XIN_RATE20070720", 62),
        ("2007-08-21", "2007-08-22", 3.60, 7.02, "XIN_RATE20070821", 63),
        ("2007-09-14", "2007-09-15", 3.87, 7.29, "PBC_RATE20070914_REPRINT", 63),
        ("2007-12-20", "2007-12-21", 4.14, 7.47, "XIN_RATE20071220", 65),
    ]
    for announcement, effective, deposit, lending, contemporaneous, page in rates:
        add("RATE_"+effective.replace("-", ""), announcement, effective, "monetary_tightening",
            f"One-year benchmark deposit/lending rates to {deposit}%/{lending}% per year",
            ["pbc_policy_2007q4", contemporaneous, "PBC_DEPOSIT_HISTORY", "PBC_LENDING_HISTORY"],
            {"pdf_page_1based": page, "printed_page": page-5,
             "note": "Retrospective PBC chronology sometimes labels the effective day as decision day; announcement is separately verified from the dated release/report."},
            deposit_rate_percent_per_year=deposit, lending_rate_percent_per_year=lending)

    for announcement, effective, rate in [
        ("2008-01-16", "2008-01-25", 15), ("2008-03-18", "2008-03-25", 15.5),
        ("2008-04-16", "2008-04-25", 16), ("2008-05-12", "2008-05-20", 16.5),
        ("2008-06-07", "2008-06-15", 17), ("2008-06-07", "2008-06-25", 17.5),
    ]:
        add("RRR_"+effective.replace("-", ""), announcement, effective, "monetary_tightening",
            f"RMB RRR +0.5 percentage points to {rate}% (general schedule; differential exemptions may apply)",
            ["NDRC_MONETARY2008"], {"html_locator": "2008年中国货币政策大事记; announcement-date paragraph",
             "note": "June 7 was one announcement with two installment dates, not two independent policy decisions."},
            rrr_percent=rate, rrr_change_percentage_points=0.5)

    add("CEWC_TIGHT_STANCE", "2007-12-05", None, "monetary_stance",
        "Central Economic Work Conference (Dec 3-5): tight monetary policy for 2008",
        ["XIN_CEWC20071205"], {"html_locator": "新华社北京12月5日电; 从紧的货币政策"},
        observation_start="2007-12-03", observation_end="2007-12-05")
    add("STAMP_HIKE", "2007-05-30", "2007-05-30", "equity_market_tightening",
        "A/B share transfer stamp duty to 3 per mille, charged to both counterparties",
        ["mof_stamp_duty_20070530"], {"html_locator": "财税〔2007〕84号; 发布日期/实施日期2007-05-30"},
        stamp_duty_per_mille_per_side=3,
        note="Original instrument release date is retained; official MOFCOM archival reprint was published July 4, not May 30. Exact intraday release time unknown.")
    add("STAMP_CUT", "2008-04-23", "2008-04-24", "equity_market_easing",
        "A/B share transfer stamp duty cut from 3 to 1 per mille, still bilateral",
        ["MOF_STAMP20080424"], {"html_locator": "正文：新华社北京4月23日电; 自4月24日起; page published Apr24"},
        stamp_duty_per_mille_per_side=1)
    add("DORMANT_ACCOUNT_SEGREGATION", "2007-10-09", "2007-10-08", "account_definition_break",
        "20.23 million dormant accounts segregated from trading system; not 20.23 million current investors exiting",
        ["csrc_dormant_accounts_20071009"], {"html_locator": "10月8日; 2023万个休眠账户; 另库存放"},
        dormant_account_count=20230000,
        note="Account clean-up notice issued August 13 and work began August 14; observed technical segregation October 8. Source is progress report published October 9.")
    add("UNLOCKED_SHARE_TRANSFER_GUIDANCE", "2008-04-20", "2008-04-20", "equity_share_supply_regulation",
        "Expected unlocked-share sales exceeding 1% of company shares within one month must use block-trading system",
        ["CSRC_UNLOCK20080420"], {"html_locator": "证监会公告[2008]15号; articles1,3,5,9"},
        expected_monthly_sales_threshold_fraction=0.01,
        note="Rule covers post-reform restricted shares and pre-IPO shares specified in article1; availability to sell is not an observation of an actual sale. Controlling-shareholder transfers prohibited within30days before annual/halfyear disclosure.")
    return sorted(events, key=lambda r: r["announcement_date"])


def extract_monthly(prices, sources):
    # January-June 2007 are taken from the earliest retained original July report.
    # Every later month uses its own contemporaneous month-end release, not a later revision.
    rows = []
    months = [f"2007-{m:02}" for m in range(1, 13)] + [f"2008-{m:02}" for m in range(1, 7)]
    for period in months:
        sid = "CSRC_MONTH_" + ("200707" if period < "2007-07" else period.replace("-", ""))
        source = sources[sid]
        book = xlrd.open_workbook(str(ROOT / source["local_path"]))
        trade = book.sheet_by_name("交易")
        matches = [r for r in range(trade.nrows) if isinstance(trade.cell_value(r, 0), (float,int))
                   and int(trade.cell_value(r, 0)) == int(period.replace("-", ""))]
        if len(matches) != 1:
            raise ValueError((period, "trade month missing/duplicate"))
        tr = matches[0]
        values = trade.row_values(tr)
        dates = sorted(d for d in prices if d.startswith(period))
        if len(dates) != int(values[1]):
            raise ValueError((period, "official market trading days disagree with SSE daily closes"))
        overview = book.sheet_by_name("概况")
        cols = [c for c in range(overview.ncols) if overview.cell_type(3,c) == xlrd.XL_CELL_DATE
                and xlrd.xldate_as_datetime(overview.cell_value(3,c), book.datemode).strftime("%Y-%m") == period]
        if len(cols) != 1:
            raise ValueError((period, "overview column missing/duplicate"))
        col = cols[0]
        labels = {str(overview.cell_value(r, 0)).strip():r for r in range(overview.nrows)}
        float_row = next(r for label,r in labels.items() if "其中：流通股本" in label)
        acct_rows = [r for label,r in labels.items() if "股票有效帐户数" in label]
        fund = book.sheet_by_name("筹资")
        frs = [r for r in range(fund.nrows) if fund.cell_type(r,0) == xlrd.XL_CELL_DATE
               and xlrd.xldate_as_datetime(fund.cell_value(r,0),book.datemode).strftime("%Y-%m") == period]
        if len(frs) != 1:
            raise ValueError((period, "funding row missing/duplicate"))
        fr = frs[0]
        previous_date = sorted(d for d in prices if d < dates[0])[-1]
        amount, days = float(values[2]), int(values[1])
        # Published daily averages are rounded to two decimals; do not overwrite them.
        avg, computed = float(values[4]), amount / days
        if avg <= 0 or computed <= 0:
            raise ValueError((period, "invalid turnover amount"))
        rows.append(dict(period=period, source_id=sid, published_date=source["published_date"],
                         source_vintage_note="earliest retained July XLS, retrospective Jan-Jun observation" if period < "2007-07" else "original own-month XLS",
                         observation_start=dates[0], observation_end=dates[-1], trading_days_official=days,
                         sse_actual_close_days=len(dates), stock_turnover_CNY_100million=amount,
                         daily_average_turnover_CNY_100million=avg,
                         daily_average_recomputed_CNY_100million=computed,
                         daily_average_published_minus_recomputed_CNY_100million=avg-computed,
                         within_standard_two_decimal_rounding=abs(avg-computed)<=0.00500001,
                         sse_month_end_close=prices[dates[-1]], sse_month_price_return_fraction=prices[dates[-1]]/prices[previous_date]-1,
                         float_share_count_100million=float(overview.cell_value(float_row,col)),
                         effective_stock_accounts_10000=float(overview.cell_value(acct_rows[0],col)) if acct_rows else None,
                         domestic_fundraising_CNY_100million=float(fund.cell_value(fr,2)),
                         A_share_IPO_proceeds_CNY_100million=float(fund.cell_value(fr,3)),
                         A_share_follow_on_proceeds_CNY_100million=float(fund.cell_value(fr,6)),
                         trade_cell_locator=f"交易!C{tr+1} monthly;B{tr+1} trading days;E{tr+1} daily average",
                         overview_cell_locator=f"概况!R{float_row+1}C{col+1} float shares" + (f";R{acct_rows[0]+1}C{col+1} effective accounts" if acct_rows else ""),
                         fundraising_cell_locator=f"筹资!C{fr+1} domestic total;D{fr+1} A IPO;G{fr+1} follow-on",
                         turnover_scope="CSRC national Shanghai+Shenzhen cash-stock trading, all investor types; not retail net purchases",
                         account_scope="exact source label 股票有效帐户数; not unique people, new accounts, holding accounts, or weekly active accounts"))
    return rows


def participation_evidence():
    common = "Account openings are gross new securities accounts, not unique persons or a purchase/sale balance. A-share universe not independently split into natural persons/institutions. Shanghai and Shenzhen accounts may count one investor twice."
    data = []
    for date, number, sid, pub, approx in [
        ("2007-09-21",199342,"SIN_NEWACC20070921","2007-09-24",False),
        ("2007-10-15",230000,"SHNEWS_PREPEAK_NEWACC","2007-10-17",True),
        ("2007-11-22",118776,"THS_NEWACC20071122","2007-11-24",False),
        ("2008-01-11",128769,"SIN_NEWACC20080111","2008-01-14",False),
    ]:
        data.append(dict(evidence_id="new_A_accounts_"+date.replace("-",""), indicator="gross_new_A_share_accounts",
            observation_start=date,observation_end=date, published_date=pub, value=number, unit="accounts/day", approximate=approx,
            source_ids=[sid],source_grade="dated contemporary secondary report explicitly attributing CSDC",
            locator="article body and historical daily table; Oct15 is '本周一' in Oct17 report", limitation=common+
            (" October article's separate September monthly total has ambiguous scope and conflicts with daily-table scale; that monthly figure is excluded." if approx else "")))
    data += [
        dict(evidence_id="active_A_accounts_20080114_18", indicator="A_share_accounts_participating_in_trades_during_week",
             observation_start="2008-01-14",observation_end="2008-01-18", published_date="2008-01-24", original_release_date_reported="2008-01-22",
             value=20818000,unit="accounts/week", source_ids=["CAIJING_ACTIVE20080118"],source_grade="dated contemporary secondary report attributing CSDC",
             locator="2008年1月14日至1月18日参与交易的A股账户数2081.8万户",
             limitation="Trading at least once during week, not net buyers or unique persons. No consistent pre-October active-account series retained; cannot establish pre-peak turning point."),
        dict(evidence_id="holding_A_accounts_20080118", indicator="A_share_accounts_with_holdings_at_week_end",
             observation_start="2008-01-18",observation_end="2008-01-18", published_date="2008-01-24", original_release_date_reported="2008-01-22",
             value=43958400,unit="accounts", source_ids=["CAIJING_ACTIVE20080118"],source_grade="dated contemporary secondary report attributing CSDC",
             locator="截至1月18日;沪深持仓A股账户4395.84万户;first disclosed Jan22 according to article",
             limitation="Stock of holding accounts, not active accounts or net flow; no pre-peak comparison. Article's fund-account number '2.22亿' appears erroneous and is excluded."),
        dict(evidence_id="saver_stock_preference_2007Q4", indicator="survey_stock_purchase_preference_change_vs_Q3",
             observation_start="2007-11-11",observation_end="2007-11-30", observation_date_precision="source says mid/late November; day 11/30 are broad calendar bounds, not exact fieldwork dates",
             published_date="2007-12-21",original_release_date_reported="2007-12-20", value=-8.5, unit="percentage_points",
             source_ids=["XIN_SURVEY2007Q4"],source_grade="dated Xinhua secondary report of PBC survey; original survey release not retained",
             locator="50 cities;20,000 valid questionnaires;11月中下旬;股票最合算占比比上季度下跌8.5个百分点",
             limitation="Stated preference, not realized purchases/sales; survey observed after Oct16 peak and after decline had begun. Cannot prove preference decline led peak."),
        dict(evidence_id="effective_accounts_20071231", indicator="effective_stock_accounts",
             observation_start="2007-12-31", observation_end="2007-12-31", published_date="2008-02-11",
             value=92805900,unit="accounts",source_ids=["CSRC_MONTH_200801"],source_grade="official original monthly XLS",
             locator="概况!B16:2007年;股票有效帐户数(万户)9280.59",
             limitation="Effective account stock after dormant segregation, not unique investors or gross openings. Jan2008 value is 94,789,900; difference is not identified retail purchases."),
    ]
    return data


def main():
    prices = load_prices()
    manifest = json.loads((ROOT/"source_manifest.json").read_text(encoding="utf8"))
    sources = {s["source_id"]:s for s in manifest["sources"]}
    events = policy_events()
    monthly = extract_monthly(prices,sources)
    participation = participation_evidence()
    all_dates=sorted(prices); peak_date="2007-10-16"; peak=prices[peak_date]; pi=all_dates.index(peak_date)
    timeline=[]
    def align(date):
        first=first_session_at_or_after(date,prices)
        if first is None:raise ValueError((date,"outside source range"))
        return dict(aligned_session=first["date"],aligned_close=first["close"],calendar_gap_days=first["calendar_gap_days"],
                    sessions_relative_to_2007_peak=all_dates.index(first["date"])-pi,
                    price_change_vs_2007_peak_fraction=first["close"]/peak-1,
                    closing_drawdown_from_running_peak_fraction=first["close"]/max(prices[d] for d in all_dates if d<=first["date"])-1)
    for event in events:
        for role in ["announcement_date","effective_date"]:
            date=event[role]
            if date:
                timeline.append(dict(date=date,event_id=event["event_id"],date_role=role,category=event["category"],label=event["label"],
                    source_ids=";".join(event["source_ids"]),source_publication_dates=";".join(str(sources[s].get("published_date")) for s in event["source_ids"]),
                    **align(date)))
    for e in participation:
        timeline.append(dict(date=e["observation_end"],event_id=e["evidence_id"],date_role="observation_end",category="participation_observation",
            label=e["indicator"],source_ids=";".join(e["source_ids"]),source_publication_dates=e["published_date"],**align(e["observation_end"])))
    for date,label in [("2007-05-29","pre-peak correction closing high"),("2007-07-05","pre-peak correction closing low"),
                       ("2007-10-16","cycle closing high"),("2007-11-28","first large postpeak closing trough"),
                       ("2008-01-14","first rebound closing high"),("2008-01-22","post-rebound old-trough breakdown case"),
                       ("2008-04-18","spring closing trough"),("2008-05-05","spring rebound closing high"),("2008-06-10","spring-trough breakdown case")]:
        timeline.append(dict(date=date,event_id="PRICE_"+date.replace("-",""),date_role="market_close",category="price_anchor",label=label,
                             source_ids="official SSE daily index yearbooks",source_publication_dates="retrospective yearbooks; see frozen price provenance",**align(date)))
    timeline.sort(key=lambda x:(x["date"],x["date_role"],x["event_id"]))
    for e in events+participation:
        e["source_details"]=[dict(source_id=s,url=sources[s]["url"],published_date=sources[s].get("published_date"),
            sha256=sources[s].get("sha256"),local_path=sources[s].get("local_path"),
            retrieved_at_utc=sources[s].get("retrieved_at_utc",sources[s].get("original_retrieved_at_utc"))) for s in e["source_ids"]]
    lookup={m["period"]:m for m in monthly}
    changes={f"{a}_to_{b}":lookup[b]["daily_average_turnover_CNY_100million"]/lookup[a]["daily_average_turnover_CNY_100million"]-1
             for a,b in [("2007-05","2007-07"),("2007-07","2007-08"),("2007-08","2007-09"),("2007-09","2007-10"),
                         ("2007-10","2007-11"),("2007-11","2007-12"),("2007-12","2008-01")]} 
    result=dict(schema_version=1,as_of="2026-10-16T09:00:00+09:00",scope="retrospective historical chronology; no forecast or probability",
        input_price_sha256=PRICE_SHA,rate_unit="percent per year",rrr_unit="percent; changes in percentage points",
        return_unit="fraction",probabilities=None,policy_events=events,monthly_activity=monthly,participation=participation,
        computed_daily_average_turnover_changes_fraction=changes,
        monetary_stock_growth_context=dict(source_id="pbc_policy_2007q4",pdf_page_1based=2,observation_end="2007-12-31",M2_yoy_percent=16.7,
            RMB_loans_yoy_percent=16.1,interpretation="Tighter policy did not mean an absolute contraction in outstanding money or credit."),
        share_supply_context=dict(source_id="CSRC_UNLOCK_DISCLOSURE",published_date="2008-08-15",
            locator="证监会答记者问;大小非 question;三是从2008年7月起...开始逐月披露",
            reported_start_of_monthly_unlocked_share_sales_disclosure="2008-07",
            interpretation="CSRC says CSDC began monthly major/minor nontradable-share-holder reduction disclosure in July2008. This source does not provide an Oct2007-Jan2008 monthly realized-sales panel; none is inferred from float-share stock changes."),
        verdicts=[
            dict(hypothesis="Tightening began only after the October stock peak",verdict="contradicted",
                 basis="Five of six 2007 benchmark-rate hikes and seven of ten effective RRR hikes preceded Oct16. Oct13 RRR announcement preceded peak; its Oct25 effective date followed peak."),
            dict(hypothesis="Tightening continued as prices fell",verdict="verified chronology, causal share unidentified",
                 basis="Nov26 and Dec25 RRR rises, Dec21 rate hike, Dec5 tight-stance announcement and H1 2008 RRR rises followed Oct16 peak. Equity-specific stamp duty eased Apr24 while RRR tightened Apr25."),
            dict(hypothesis="Market trading activity weakened before peak",verdict="verified but non-monotonic",
                 basis="Daily-average turnover fell May-to-July, recovered August, eased September; October straddles peak and cannot locate intramonth change."),
            dict(hypothesis="Trading activity weakened after peak",verdict="verified for Oct-Nov; not monotonic afterward",
                 basis="Nov average below Oct; Dec and Jan recovered. January market fell 16.69% despite higher turnover."),
            dict(hypothesis="Retail net purchases turned negative before peak",verdict="unconfirmed",
                 basis="No original monthly natural-person buy/sell split was retained. Gross openings, effective/holding/active-account stocks, survey preference and all-investor turnover do not identify signed retail flow."),
            dict(hypothesis="Falling new accounts identifies retail exit",verdict="not identified",
                 basis="Daily scattered observations are new-account flows, not sales or account closures; prepeak Oct15 openings were reported up. No continuous series or predeclared change-point test is supported."),
            dict(hypothesis="Share supply pressure rose around peak",verdict="fundraising/float stocks verified; actual unlock sales/causal impact unconfirmed",
                 basis="Official monthly IPO/follow-on proceeds and float-share totals are distinct. Float changes can include issuance/conversion/coverage changes; they do not measure insiders' realized selling."),
            dict(hypothesis="Nationwide account totals prove the entire population bought",verdict="unsupported",
                 basis="Accounts are not unique persons; dormant accounts and cross-exchange double counts matter. Oct8 segregation of20.23m dormant accounts is a structural break, not mass current-investor liquidation."),
        ],
        limitations=["Descriptive timing is not a controlled causal event study. Anticipation, inflation, earnings, issuance and global shocks confound effects.",
            "Monthly observations mix days before/after Oct16; month-end reports become public later. Observation time and release time are both retained.",
            "All-investor national stock turnover is not a direct Shanghai-only or retail-flow measure. CSRC reported trading-day counts equal actual SSE close counts in all18 months; Shenzhen daily calendar was not independently retrieved, so exact daily holiday identity is not claimed.",
            "Some original XLS published daily averages differ from monthly total divided by trading days by more than standard 2-decimal rounding (max0.018333 CNY100million/day). Both values and exact differences are retained; report/source comparisons use the published values consistently, without silent correction.",
            "Dated contemporary press is used only where CSDC original pages were not recovered; daily samples do not form a complete time series.",
            "Annual retail net-flow totals, even if positive or negative, cannot establish the month of a reversal; none are used to time it.",
            "CSRC_AR2007 downloaded PDF is a current navigation-page PDF, not the requested report, and is invalid/excluded. CSDC_AR2006 and PBOC_DEC20_QA direct retrieval failed; their bytes/search snippets are not primary evidence.",
            "All rate announcements are date-level; no event-return causality or intraday tradability is inferred. First-session alignment is a calendar label only, not a same-day response estimate."])
    (ROOT/"evidence.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    write_csv("monthly_market_activity.csv",monthly)
    write_csv("timeline.csv",timeline)
    checks=[]
    for source in manifest["sources"]:
        if source.get("status")=="saved":
            path=ROOT/source["local_path"]
            if sha(path)!=source["sha256"]:raise ValueError((source["source_id"],"raw hash mismatch"))
            checks.append(source["source_id"])
    audit=dict(status="passed",retained_valid_source_hashes_checked=len(checks),monthly_observations=len(monthly),
               all_reported_trading_day_counts_match_SSE_actual=True,rrr_2007_announcements=10,rrr_2007_effective_hikes=10,
               benchmark_rate_2007_hikes=6,timeline_rows=len(timeline),original_price_input_unchanged=sha(PRICE_PATH)==PRICE_SHA,
               published_daily_averages_within_standard_rounding_all=False,
               arithmetic_discrepancies_preserved_without_correction=True,
               maximum_published_daily_average_discrepancy_CNY_100million=max(abs(r['daily_average_published_minus_recomputed_CNY_100million']) for r in monthly),
               retail_net_flow_verified=False,
               forced_liquidation_verified=False,unique_retail_person_count_verified=False)
    (ROOT/"validation.json").write_text(json.dumps(audit,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps(audit,ensure_ascii=False))


if __name__=="__main__":
    main()
