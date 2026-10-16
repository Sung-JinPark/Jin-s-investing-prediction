"""Build canonical observations from retained static documents.

Normal run acquires missing supplemental public historical HTML once.
Use --offline to reproduce canonical observations without any network access.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import urllib.parse

from acquire import ROOT, RAW, download, yahoo_rows


def supplemental(offline: bool) -> list[dict]:
    receipt = RAW / "supplemental_manifest.json"
    metas = json.loads(receipt.read_text(encoding="utf8")) if receipt.exists() else []
    by_id = {r["source_id"]: r for r in metas}
    jobs = [("yahoo_kospi_prehistory_2024", "^KS11", "KOSPI", "KRW", "2024-07-01", "2024-10-01")]
    for start,end in [("2005-01-01","2009-01-01"),("2024-07-01","2026-10-16")]:
        for ticker,symbol,currency in [("KRW=X","KRW_PER_USD","KRW/USD"),("CNY=X","CNY_PER_USD","CNY/USD")]:
            jobs.append((f"yahoo_{symbol.lower()}_{start[:4]}_{end[:4]}",ticker,symbol,currency,start,end))
    for source_id,ticker,symbol,currency,start,end in jobs:
        if source_id in by_id:
            by_id[source_id].update(requested_start=start,requested_end_exclusive=end)
            continue
        if offline:
            raise ValueError(f"Missing cached source for offline reproduction: {source_id}")
        params=dict(period1=int(dt.datetime.fromisoformat(start).replace(tzinfo=dt.timezone.utc).timestamp()),
                    period2=int(dt.datetime.fromisoformat(end).replace(tzinfo=dt.timezone.utc).timestamp()),frequency="1d")
        url="https://finance.yahoo.com/quote/"+urllib.parse.quote(ticker,safe="")+"/history/?"+urllib.parse.urlencode(params)
        try:
            payload,meta=download(source_id,url)
            rows=yahoo_rows(payload,symbol,currency,source_id)
            if not rows:
                raise ValueError("No daily observations")
            meta.update(provider="Yahoo Finance",provider_ticker=ticker,symbol=symbol,currency=currency,
                        requested_start=start,requested_end_exclusive=end,
                        row_count=len(rows),first_observation=rows[0]["date"],last_observation=rows[-1]["date"],
                        unit="local_currency_per_usd" if "PER_USD" in symbol else "index_points",
                        price_type="reference_fx_local_currency_per_usd" if "PER_USD" in symbol else "unadjusted_index_close",
                        available_at_policy="Retrospectively retrieved historical table; original publication timestamps unavailable",
                        role="canonical",status="saved")
            by_id[source_id]=meta
            print(source_id,len(rows),rows[0]["date"],rows[-1]["date"],flush=True)
        except Exception as exc:
            by_id[source_id]=dict(source_id=source_id,url=url,symbol=symbol,currency=currency,
                                  status="unavailable",error=f"{type(exc).__name__}: {exc}")
            print(source_id,"UNAVAILABLE",str(exc),flush=True)
        receipt.write_text(json.dumps(list(by_id.values()),ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    receipt.write_text(json.dumps(list(by_id.values()),ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    return list(by_id.values())


def main() -> None:
    parser=argparse.ArgumentParser();parser.add_argument("--offline",action="store_true")
    args=parser.parse_args()
    base=ROOT/"source_manifest.base.json"
    if not base.exists():
        base.write_bytes((ROOT/"source_manifest.json").read_bytes())
    manifest=json.loads(base.read_text(encoding="utf8"))
    metas=supplemental(args.offline)
    rows=[]
    yahoo_china={}
    for meta in manifest["sources"]+metas:
        if meta.get("status")=="unavailable":
            continue
        symbol=meta["symbol"]
        if not meta["source_id"].startswith("yahoo_"):
            continue
        payload=(ROOT/meta["raw_file"]).read_bytes()
        parsed=yahoo_rows(payload,symbol,meta["currency"],meta["source_id"])
        meta["observations_excluded_from_canonical"]=[
            dict(date=r["date"],close=r["close"],reason="after_frozen_observation_cutoff" if r["date"]>"2026-10-15" else "outside_requested_historical_range")
            for r in parsed if r["date"]>"2026-10-15" or r["date"]<meta.get("requested_start","0001-01-01")
            or r["date"]>=meta.get("requested_end_exclusive","9999-12-31")]
        parsed=[r for r in parsed if r["date"] <= "2026-10-15"
                and r["date"] >= meta.get("requested_start","0001-01-01")
                and r["date"] < meta.get("requested_end_exclusive","9999-12-31")]
        meta["canonical_eligible_row_count"]=len(parsed)
        if symbol in ("SSE_COMPOSITE","SSE_A"):
            yahoo_china.update({(r["symbol"],r["date"]):r["close"] for r in parsed})
            meta["role"]="independent_crosscheck_only"
        else:
            if "PER_USD" in symbol:
                for row in parsed:
                    row["price_type"]="reference_fx_local_currency_per_usd"
            meta["role"]="canonical"
            if symbol=="MSCI_WORLD":
                meta["validation_status"]="unverified_conflicting_public_snapshots"
                meta["role"]="retained_proxy_not_used_in_numeric_conclusions"
            rows.extend(parsed)
    official_path=ROOT.parent/"china"/"daily_indices_2005_2008.csv"
    official=list(csv.DictReader(official_path.open(newline="",encoding="utf8")))
    official_sources=json.loads((ROOT.parent/"china"/"source_manifest.json").read_text(encoding="utf8"))["sources"]
    official_ids={r["source_id"] for r in official}
    mismatches=[]
    max_diff=0.0
    for row in official:
        symbol={"sse_composite":"SSE_COMPOSITE","sse_a_share":"SSE_A"}[row["index_id"]]
        close=float(row["close"])
        key=symbol,row["date"]
        if key in yahoo_china:
            difference=abs(close-yahoo_china[key]);max_diff=max(max_diff,difference)
            if difference>0.011:
                mismatches.append(dict(symbol=symbol,date=row["date"],official=close,yahoo=yahoo_china[key],absolute_difference=difference))
        rows.append(dict(date=row["date"],close=close,symbol=symbol,currency="CNY",source_id=row["source_id"],
                         price_type="unadjusted_index_close",source_path="../china/"+row["source_path"],
                         source_pdf_page_1based=row["source_pdf_page_1based"]))
    for original in official_sources:
        if original["source_id"] not in official_ids:
            continue
        meta=dict(original);meta.update(role="canonical",provider="Shanghai Stock Exchange",
               raw_file="../china/"+original["local_path"],unit="index_points",currency="CNY",
               symbol="SSE_COMPOSITE,SSE_A",original_publication_timestamp_available=False)
        manifest["sources"].append(meta)
    # This text snapshot contains the public historical table obtained by web.run.
    # It is a parsed snapshot, not the original HTML; retain that distinction.
    extension_path=RAW/"investing_kospi_20261015.web.txt"
    text=extension_path.read_text(encoding="utf8")
    matches=re.findall(r"(2026)년\s*(\d+)월\s*(\d+)일\s*\|\s*([\d,]+\.\d+)",text)
    investing={f"{int(y):04d}-{int(m):02d}-{int(d):02d}":float(v.replace(",","")) for y,m,d,v in matches}
    if "2026-10-15" not in investing:
        raise ValueError("Oct15 close missing in retained Investing table")
    kospi={r["date"]:r["close"] for r in rows if r["symbol"]=="KOSPI"}
    overlap=[dict(date=d,yahoo_close=kospi[d],investing_close=v,difference=v-kospi[d])
             for d,v in sorted(investing.items()) if d in kospi]
    if not overlap or any(abs(r["difference"])>0.011 for r in overlap):
        raise ValueError("Investing/Yahoo overlapping KOSPI closes fail 0.011 point tolerance")
    source_id="investing_kospi_20261015"
    if "2026-10-15" in kospi:
        raise ValueError("Unexpected duplicate Oct15 KOSPI observation")
    rows.append(dict(date="2026-10-15",close=investing["2026-10-15"],symbol="KOSPI",currency="KRW",
                     source_id=source_id,price_type="unadjusted_index_close"))
    payload=extension_path.read_bytes()
    manifest["sources"].append(dict(source_id=source_id,provider="Investing.com",symbol="KOSPI",currency="KRW",unit="index_points",
          url="https://kr.investing.com/indices/kospi-historical-data",raw_file=extension_path.relative_to(ROOT).as_posix(),
          sha256=hashlib.sha256(payload).hexdigest(),bytes=len(payload),role="canonical_latest_session_extension",
          snapshot_format="web.run historical-table text extraction; not original HTML",row_count=1,
          first_observation="2026-10-15",last_observation="2026-10-15",
          snapshot_saved_at=dt.datetime.fromtimestamp(extension_path.stat().st_mtime,dt.timezone.utc).isoformat(),
          retrieved_at=None,retrieved_at_note="web.run supplies no exact retrieval timestamp; filesystem snapshot save time recorded separately",
          independent_crosscheck_urls=["https://en.yna.co.kr/view/AEN20261015007800320","https://freesis.kofia.or.kr/index.jsp","https://eng.kofia.or.kr/index.do"],
          independent_crosscheck_note="Dated Yonhap Oct15 report and official KOFIA FreeSIS card stamped10/15 both report5554.22,-454.59,-7.57%. FreeSIS card omits year and is in a partial HTML snapshot with complete card block; current2026context and dated news provide year crosscheck. Sources preserved in ../korea/.",
          available_at_policy="Oct15 exchange close described in public historical table; exact provider publication time unavailable"))
    manifest["sources"].extend(metas)
    manifest["crosschecks"]=dict(china_official_vs_yahoo=dict(n_pairs=len(official),absolute_tolerance_index_points=0.011,
                maximum_absolute_difference=max_diff,mismatches=mismatches,canonical_choice="official SSE yearbook regardless of Yahoo difference"),
            kospi_latest=dict(yahoo_latest_date=max(kospi),canonical_latest_date="2026-10-15",canonical_latest_close=investing["2026-10-15"],
                             date_staleness_not_same_date_price_conflict=True,overlap=overlap))
    manifest["definitions"]=dict(SSE_COMPOSITE="SSE Composite Index000001; A and B share composite; official SSE daily close",
            SSE_A="SSE A Share Index000002; distinct from Composite and from an individual company's Shenzhen000002",
            KOSPI="KOSPI Composite Index; local KRW price index close",
            MSCI_WORLD="Yahoo ^990100-USD-STRD titled MSCI WORLD; USD index. Historical table does not certify dividend/net/gross return treatment; used only as a broad price-level proxy, not certified total return.",
            FX="Yahoo KRW=X/CNY=X local currency units per USD; exact-date historical close, time-of-day not supplied")
    manifest["benchmark_validation"]=dict(symbol="MSCI_WORLD",status="unverified",usable_for_relative_conclusions=False,
            conflict_date="2026-10-15",download_query_close=4938.22,web_search_default_history_close=4891.07,
            conflict_source_url="https://finance.yahoo.com/quote/%5E990100-USD-STRD/history/",
            conflict_discovery="web search extraction for ticker/price query; direct re-fetch later returned429",
            suppression="usd_global_comparison default benchmark_verified=False; world return and relative return are null")
    manifest["policies"].update(canonical_china="Official SSE2005-2008 only; Yahoo stored as independent crosscheck",
            fx_join="Exact observed dates only; no forward fill; FX and equity close times differ",
            market_close_availability="Cutoff protects observation dates; source histories are retrospective vintages, not certified PIT release records",
            offline_reproduction="python consolidate.py --offline && python analytics.py",
            msci_benchmark_return_definition_uncertified=True)
    fields=["date","symbol","currency","close","open","high","low","adjusted_close","source_id","price_type","source_path","source_pdf_page_1based"]
    with (ROOT/"prices.csv").open("w",newline="",encoding="utf8") as handle:
        writer=csv.DictWriter(handle,fieldnames=fields);writer.writeheader();writer.writerows(sorted(rows,key=lambda r:(r["symbol"],r["date"])))
    manifest["canonical_price_sha256"]=hashlib.sha256((ROOT/"prices.csv").read_bytes()).hexdigest()
    (ROOT/"source_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("canonical_rows",len(rows),"china_max_crosscheck_difference",max_diff,"KOSPI_Oct15",investing["2026-10-15"],flush=True)


if __name__=="__main__":
    main()
