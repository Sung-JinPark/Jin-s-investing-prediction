"""Prefix-only phase features and exhaustive historical descriptive matching.

No aggregate similarity score, forecast probability or Korean forward line.
Default is offline. --download-2009 optionally retains public historical HTML
for complete historical126-session outcomes; it never changes the frozen data.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import html
import json
import math
from pathlib import Path
import re
import urllib.parse
import urllib.request

ROOT=Path(__file__).resolve().parent
STUDY=ROOT.parent.parent
FROZEN=STUDY/"prices"/"prices.csv"
CUTOFF=dt.date(2026,10,15)
THRESHOLDS=(.10,.15,.20)
FEATURES=("peak_drawdown_fraction","sessions_since_peak","bounce_from_running_trough_fraction",
          "loss_recovered_from_running_trough_fraction","decline_from_latest_confirmed_rebound_fraction")
FLAGS=("below_last_confirmed_trough","new_postpeak_low","directional_change_state")
EXTENDED_FEATURES=("peak_drawdown_fraction","sessions_since_peak","decline_from_latest_confirmed_rebound_fraction",
                  "preceding_rebound_gain_fraction","preceding_rebound_prior_loss_recovered_fraction",
                  "preceding_rebound_sessions","sessions_since_confirmed_rebound_peak")
TIME_FEATURES=("sessions_since_peak","preceding_rebound_sessions","sessions_since_confirmed_rebound_peak")
TOLERANCES={"strict":(.025,10,.05),"base":(.05,21,.10),"loose":(.10,42,.20)}


def digest(path:Path)->str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_frozen()->dict[str,list[dict]]:
    data={}
    for raw in csv.DictReader(FROZEN.open(newline="",encoding="utf8")):
        if raw["symbol"] not in ("SSE_COMPOSITE","SSE_A","KOSPI"):
            continue
        r=dict(raw,date=dt.date.fromisoformat(raw["date"]),close=float(raw["close"]))
        if not math.isfinite(r["close"]) or r["close"]<=0 or r["date"]>CUTOFF:
            raise ValueError("Invalid frozen price")
        data.setdefault(r["symbol"],[]).append(r)
    for rows in data.values():
        rows.sort(key=lambda r:r["date"])
        if len({r["date"] for r in rows})!=len(rows):
            raise ValueError("Duplicate frozen date")
    meta=json.loads((STUDY/"prices"/"source_manifest.json").read_text(encoding="utf8"))
    if digest(FROZEN)!=meta["canonical_price_sha256"]:
        raise ValueError("Frozen canonical price SHA does not match source manifest")
    return data


def serialize(value):
    if isinstance(value,dt.date):return value.isoformat()
    if isinstance(value,dict):return {k:serialize(v) for k,v in value.items()}
    if isinstance(value,list):return [serialize(v) for v in value]
    return value


def directional_events(rows:list[dict],threshold:float,initial_state:str="falling")->dict:
    """Turns are recognized only after a threshold reversal actually occurs."""
    if threshold not in THRESHOLDS or not rows or initial_state not in ("falling","rising"):
        raise ValueError("Explicit threshold, observations and state required")
    state=initial_state;extreme=0;events=[]
    for i in range(1,len(rows)):
        price=rows[i]["close"]
        if state=="falling":
            if price<rows[extreme]["close"]:extreme=i
            if price/rows[extreme]["close"]-1>=threshold-1e-12:
                events.append(dict(kind="trough",extreme_index=extreme,date=rows[extreme]["date"],close=rows[extreme]["close"],
                                   confirmed_index=i,confirmed_at=rows[i]["date"],threshold_fraction=threshold))
                state="rising";extreme=i
        else:
            if price>rows[extreme]["close"]:extreme=i
            if price/rows[extreme]["close"]-1<=-threshold+1e-12:
                events.append(dict(kind="peak",extreme_index=extreme,date=rows[extreme]["date"],close=rows[extreme]["close"],
                                   confirmed_index=i,confirmed_at=rows[i]["date"],threshold_fraction=threshold))
                state="falling";extreme=i
    return dict(events=events,state=state,unconfirmed_extreme_date=rows[extreme]["date"],
                unconfirmed_extreme_close=rows[extreme]["close"])


def phase_features(prefix:list[dict],threshold:float)->dict:
    """Input starts at the observed peak and stops at the candidate date."""
    peak=prefix[0];last=prefix[-1]
    trough=min(prefix,key=lambda r:r["close"])
    turns=directional_events(prefix,threshold)
    lows=[e for e in turns["events"] if e["kind"]=="trough"]
    highs=[e for e in turns["events"] if e["kind"]=="peak"]
    last_low=lows[-1] if lows else None;last_high=highs[-1] if highs else None
    pair_low=None
    if last_high:
        high_pos=turns["events"].index(last_high)
        if high_pos>0 and turns["events"][high_pos-1]["kind"]=="trough":
            pair_low=turns["events"][high_pos-1]
    loss=peak["close"]-trough["close"]
    return dict(date=last["date"],close=last["close"],peak_date=peak["date"],peak_close=peak["close"],
        peak_drawdown_fraction=last["close"]/peak["close"]-1,sessions_since_peak=len(prefix)-1,
        running_trough_date=trough["date"],running_trough_close=trough["close"],
        bounce_from_running_trough_fraction=last["close"]/trough["close"]-1,
        loss_recovered_from_running_trough_fraction=(last["close"]-trough["close"])/loss if loss>0 else 0.0,
        last_confirmed_trough_date=last_low["date"] if last_low else None,
        last_confirmed_trough_close=last_low["close"] if last_low else None,
        last_trough_confirmed_at=last_low["confirmed_at"] if last_low else None,
        last_confirmed_rebound_date=last_high["date"] if last_high else None,
        last_confirmed_rebound_close=last_high["close"] if last_high else None,
        last_rebound_confirmed_at=last_high["confirmed_at"] if last_high else None,
        preceding_rebound_trough_date=pair_low["date"] if pair_low else None,
        preceding_rebound_trough_close=pair_low["close"] if pair_low else None,
        preceding_rebound_gain_fraction=last_high["close"]/pair_low["close"]-1 if pair_low else None,
        preceding_rebound_prior_loss_recovered_fraction=(last_high["close"]-pair_low["close"])/(peak["close"]-pair_low["close"]) if pair_low else None,
        preceding_rebound_sessions=last_high["extreme_index"]-pair_low["extreme_index"] if pair_low else None,
        sessions_since_confirmed_rebound_peak=len(prefix)-1-last_high["extreme_index"] if last_high else None,
        decline_from_latest_confirmed_rebound_fraction=last["close"]/last_high["close"]-1 if last_high else None,
        price_vs_last_confirmed_trough_fraction=last["close"]/last_low["close"]-1 if last_low else None,
        below_last_confirmed_trough=last["close"]<last_low["close"] if last_low else None,
        new_postpeak_low=last["close"]<min(r["close"] for r in prefix[:-1]) if len(prefix)>1 else False,
        directional_change_state=turns["state"],confirmed_turn_count=len(turns["events"]),
        unconfirmed_extreme_date=turns["unconfirmed_extreme_date"],unconfirmed_extreme_close=turns["unconfirmed_extreme_close"])


def runup_anchor(rows:list[dict])->tuple[list[dict],dict]:
    peak_idx=max(range(len(rows)),key=lambda i:rows[i]["close"])
    low_idx=min(range(peak_idx+1),key=lambda i:rows[i]["close"])
    low,peak=rows[low_idx],rows[peak_idx]
    return rows[low_idx:peak_idx+1],dict(rise_start_date=low["date"],rise_start_close=low["close"],
        available_start=rows[0]["date"],observed_peak_date=peak["date"],observed_peak_close=peak["close"],
        rise_return_fraction=peak["close"]/low["close"]-1,rise_sessions=peak_idx-low_idx,
        retrospective_anchor=True,coverage_warning="SSE starts2005-01; KOSPI available coverage starts2024-07, so global minima have different search coverage.")


def corrections(runup:list[dict],threshold:float)->list[dict]:
    events=directional_events(runup,threshold,"rising")["events"]
    result=[]
    for first,second in zip(events,events[1:]):
        if first["kind"]!="peak" or second["kind"]!="trough":continue
        subsequent=[(i,r) for i,r in enumerate(runup) if i>second["extreme_index"] and r["close"]>=first["close"]]
        recovery=subsequent[0] if subsequent else None
        result.append(dict(peak_date=first["date"],peak_close=first["close"],decline_confirmed_at=first["confirmed_at"],
            trough_date=second["date"],trough_close=second["close"],rebound_confirmed_at=second["confirmed_at"],
            drawdown_fraction=second["close"]/first["close"]-1,
            decline_sessions=second["extreme_index"]-first["extreme_index"],
            prior_peak_recovered_at=recovery[1]["date"] if recovery else None,
            trough_to_recovery_sessions=recovery[0]-second["extreme_index"] if recovery else None))
    return result


def drawdown_excursions(runup:list[dict])->list[dict]:
    """Whole underwater spells; an interim rebound does not split the correction."""
    high_idx=0;active=None;result=[]
    for i in range(1,len(runup)):
        price=runup[i]["close"]
        if active is None:
            if price>=runup[high_idx]["close"]:
                high_idx=i
            else:
                active=dict(peak_idx=high_idx,trough_idx=i)
        else:
            if price<runup[active["trough_idx"]]["close"]:active["trough_idx"]=i
            if price>=runup[active["peak_idx"]]["close"]:
                peak_idx=active["peak_idx"];trough_idx=active["trough_idx"]
                peak=runup[peak_idx];trough=runup[trough_idx]
                depth=trough["close"]/peak["close"]-1
                result.append(dict(status="complete",peak_date=peak["date"],peak_close=peak["close"],
                    first_underwater_date=runup[peak_idx+1]["date"],trough_date=trough["date"],trough_close=trough["close"],
                    first_recovery_date=runup[i]["date"],recovery_close=price,drawdown_fraction=depth,
                    peak_to_trough_sessions=trough_idx-peak_idx,trough_to_recovery_sessions=i-trough_idx,
                    peak_to_recovery_sessions=i-peak_idx,closes_strictly_below_prior_peak=i-peak_idx-1,
                    threshold_10pct_eligible=depth<=-.10+1e-12,threshold_15pct_eligible=depth<=-.15+1e-12,
                    threshold_20pct_eligible=depth<=-.20+1e-12,
                    anchor_role="Retrospectively completed whole underwater excursion, distinct from threshold-confirmed zigzag sublegs"))
                active=None;high_idx=i
    return result


def distances(candidate:dict,target:dict,features:tuple=FEATURES)->dict:
    d={name:abs(candidate[name]-target[name]) if candidate[name] is not None and target[name] is not None else None for name in features}
    d.update({name:0 if candidate[name]==target[name] else 1 for name in FLAGS})
    return d


def is_pareto(d:dict,others:list[dict],features:tuple=FEATURES)->bool:
    keys=features+FLAGS
    if any(d[k] is None for k in keys):return False
    for other in others:
        if any(other[k] is None for k in keys):continue
        if all(other[k]<=d[k] for k in keys) and any(other[k]<d[k] for k in keys):return False
    return True


def matches(d:dict,mode:str,features:tuple=FEATURES)->bool:
    depth,sessions,other=TOLERANCES[mode]
    tolerances={name:(sessions if name in TIME_FEATURES else other) for name in features};tolerances["peak_drawdown_fraction"]=depth
    return all(d[k] is not None and d[k]<=tolerances[k]+1e-12 for k in features) and all(d[k]==0 for k in FLAGS)


def historical_outcome(rows:list[dict],date:dt.date,n:int=126)->dict:
    idx=next(i for i,r in enumerate(rows) if r["date"]==date)
    future=rows[idx+1:idx+n+1]
    if len(future)<n:return dict(status="right_censored",observations_available=len(future),required=n,end_return_fraction=None)
    origin=rows[idx]["close"];peak=origin;mdd=0.0
    for r in future:
        peak=max(peak,r["close"]);mdd=min(mdd,r["close"]/peak-1)
    return dict(status="complete",observations_available=n,first_future_date=future[0]["date"],last_date=future[-1]["date"],
        end_return_fraction=future[-1]["close"]/origin-1,worst_origin_return_fraction=min([0.0]+[r["close"]/origin-1 for r in future]),
        minimum_future_observed_return_fraction=min(r["close"]/origin-1 for r in future),
        max_drawdown_fraction=mdd,additional_20pct_loss_event=any(r["close"]<=origin*.8 for r in future),
        role="One overlapping historical path outcome, not probability or independent observation")


def download_extension(data:dict)->None:
    raw=ROOT/"raw";raw.mkdir(exist_ok=True)
    sources=[];extension=[]
    for symbol,ticker in [("SSE_COMPOSITE","000001.SS"),("SSE_A","000002.SS")]:
        params={"period1":int(dt.datetime(2008,10,1,tzinfo=dt.timezone.utc).timestamp()),"period2":int(dt.datetime(2010,1,1,tzinfo=dt.timezone.utc).timestamp()),"frequency":"1d"}
        url="https://finance.yahoo.com/quote/"+ticker+"/history/?"+urllib.parse.urlencode(params)
        source_id="yahoo_"+symbol.lower()+"_2009_extension"
        request=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(request,timeout=40) as response:payload=response.read()
        path=raw/(source_id+".html");path.write_bytes(payload)
        parsed=[]
        for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>",payload.decode("utf8"),re.S):
            cells=[html.unescape(re.sub(r"<[^>]+>","",c)).strip() for c in re.findall(r"<td\b[^>]*>(.*?)</td>",tr,re.S)]
            if len(cells)!=7:continue
            try:date=dt.datetime.strptime(cells[0],"%b %d, %Y").date();close=float(cells[4].replace(",",""))
            except ValueError:continue
            parsed.append(dict(date=date,close=close,symbol=symbol,currency="CNY",source_id=source_id))
        official={r["date"]:r["close"] for r in data[symbol]}
        checks=[abs(r["close"]-official[r["date"]]) for r in parsed if r["date"] in official]
        if not checks or max(checks)>.011:raise ValueError("Extension overlapping official SSE crosscheck failed")
        extra=[r for r in parsed if dt.date(2009,1,1)<=r["date"]<=dt.date(2009,12,31)]
        if len(extra)<126:raise ValueError("Insufficient extension observations")
        extension.extend(extra)
        sources.append(dict(source_id=source_id,url=url,provider="Yahoo Finance",access_method="unauthenticated_static_historical_HTML",
            raw_file=path.relative_to(ROOT).as_posix(),sha256=digest(path),retrieved_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
            canonical_extension_rows=len(extra),overlap_crosscheck_rows=len(checks),maximum_overlap_difference=max(checks),tolerance_points=.011,
            first_extension_date=min(r["date"] for r in extra),last_extension_date=max(r["date"] for r in extra),
            role="historical outcome follow-through only; never changes frozen current inputs",publication_vintage="retrospective; original release timestamps unavailable"))
    with (ROOT/"prices_2009_extension.csv").open("w",newline="",encoding="utf8") as handle:
        writer=csv.DictWriter(handle,fieldnames=["date","symbol","currency","close","source_id"]);writer.writeheader();writer.writerows(serialize(sorted(extension,key=lambda r:(r["symbol"],r["date"]))))
    (ROOT/"extension_source_manifest.json").write_text(json.dumps(serialize(dict(sources=sources,
        canonical_extension_sha256=digest(ROOT/"prices_2009_extension.csv"))),ensure_ascii=False,indent=2)+"\n",encoding="utf8")


def main()->None:
    parser=argparse.ArgumentParser();parser.add_argument("--download-2009",action="store_true");args=parser.parse_args()
    ROOT.mkdir(parents=True,exist_ok=True);data=load_frozen();frozen_hash=digest(FROZEN)
    if args.download_2009:download_extension(data)
    extension={}
    ext_path=ROOT/"prices_2009_extension.csv"
    if ext_path.exists():
        extension_manifest=json.loads((ROOT/"extension_source_manifest.json").read_text(encoding="utf8"))
        if digest(ext_path)!=extension_manifest["canonical_extension_sha256"]:
            raise ValueError("Historical extension SHA mismatch")
        for source in extension_manifest["sources"]:
            if digest(ROOT/source["raw_file"])!=source["sha256"]:
                raise ValueError("Historical extension raw source SHA mismatch")
        ext_seen=set()
        for raw in csv.DictReader(ext_path.open(newline="",encoding="utf8")):
            row=dict(raw,date=dt.date.fromisoformat(raw["date"]),close=float(raw["close"]))
            key=row["symbol"],row["date"]
            if key in ext_seen or row["symbol"] not in ("SSE_COMPOSITE","SSE_A") or row["currency"]!="CNY" or row["date"].year!=2009 or not math.isfinite(row["close"]) or row["close"]<=0:
                raise ValueError("Invalid or duplicate historical extension observation")
            ext_seen.add(key);extension.setdefault(row["symbol"],[]).append(row)
    anchors={};runups={};postpeak={};anchor_rows=[];series_rows=[];phase_rows=[];excursion_rows=[];excursions={}
    for symbol,rows in data.items():
        runup,anchor=runup_anchor(rows);anchors[symbol]=anchor;runups[symbol]=runup
        complete=drawdown_excursions(runup)
        largest=min(complete,key=lambda e:e["drawdown_fraction"]) if complete else None
        excursions[symbol]=dict(all_completed=complete,largest_completed=largest)
        excursion_rows.extend(dict(symbol=symbol,**e) for e in complete)
        if largest:
            for label,date_key,close_key in [("mid_correction_peak","peak_date","peak_close"),("mid_correction_trough","trough_date","trough_close"),("mid_correction_recovery","first_recovery_date","recovery_close")]:
                anchor_rows.append(dict(symbol=symbol,threshold_fraction=None,anchor_type=label,date=largest[date_key],close=largest[close_key],confirmed_at=largest["first_recovery_date"]))
        postpeak[symbol]=[r for r in rows if r["date"]>=anchor["observed_peak_date"]]
        for label,date,close in [("rise_start",anchor["rise_start_date"],anchor["rise_start_close"]),("observed_peak",anchor["observed_peak_date"],anchor["observed_peak_close"])]:
            anchor_rows.append(dict(symbol=symbol,threshold_fraction=None,anchor_type=label,date=date,close=close,confirmed_at=None))
        for i,r in enumerate(postpeak[symbol]):series_rows.append(dict(symbol=symbol,sessions_since_peak=i,date=r["date"],close=r["close"],peak_rebased_100=r["close"]/anchor["observed_peak_close"]*100))
        phase_sets=[("rise_start_to_observed_peak",runup),("observed_peak_to_cutoff",postpeak[symbol])]
        if largest:phase_sets.append(("largest_completed_mid_correction",[r for r in rows if largest["peak_date"]<=r["date"]<=largest["first_recovery_date"]]))
        for label,selected in phase_sets:
            for i,r in enumerate(selected):phase_rows.append(dict(symbol=symbol,phase=label,sessions_since_phase_anchor=i,date=r["date"],
                close=r["close"],phase_anchor_rebased_100=r["close"]/selected[0]["close"]*100,source_id=r["source_id"]))
    payload=dict(schema_version=1,as_of="2026-10-16T09:00:00+09:00",cutoff_date=CUTOFF,
        input_frozen_prices_path="../../prices/prices.csv",input_frozen_prices_sha256=frozen_hash,method_contract_sha256=digest(ROOT/"method_contract.json"),
        probability_output=False,aggregate_similarity_score=None,price_unit="index_points",return_drawdown_unit="fraction",duration_unit="actual_trading_sessions",
        anchors=anchors,prepeak_excursions=excursions,by_threshold={},
        method_versions=dict(core_original_features=list(FEATURES),extended_shape_features=list(EXTENDED_FEATURES),
            note="Original outputs preserved; extended shape adds preceding rebound amplitude/recovery/durations to correct zero-reset semantic coverage, not outcome-based selection."),
        limitations=["Prior calendar study already inspected2008; this is not an independent blind preregistration.",
          "Retrospective rise minima and observed highs are descriptive anchors, not real-time tradable signals.",
          "Historical dates and126-session outcomes overlap; candidate counts are not independent sample sizes.",
          "All per-feature distances and tolerance choices are descriptive; no candidate implies a Korean return forecast.",
          "The future Korean line stops at the frozen cutoff;2009 extension is only for historical outcome completeness."])
    all_candidates=[];nearest=[]
    # Freeze all feature-based candidate sets before calculating any future outcomes.
    for threshold in THRESHOLDS:
        key=f"{threshold:.2f}";target=phase_features(postpeak["KOSPI"],threshold)
        block=dict(current=target,prepeak_corrections={},confirmed_postpeak_turns={},historical={})
        for symbol in data:
            corr=corrections(runups[symbol],threshold);block["prepeak_corrections"][symbol]=dict(all=corr,largest=min(corr,key=lambda r:r["drawdown_fraction"]) if corr else None)
            turns=directional_events(postpeak[symbol],threshold)
            block["confirmed_postpeak_turns"][symbol]=turns
            for event in turns["events"]:anchor_rows.append(dict(symbol=symbol,threshold_fraction=threshold,anchor_type="postpeak_"+event["kind"],date=event["date"],close=event["close"],confirmed_at=event["confirmed_at"]))
        for symbol in ("SSE_COMPOSITE","SSE_A"):
            candidates=[]
            for i in range(1,len(postpeak[symbol])):
                f=phase_features(postpeak[symbol][:i+1],threshold);d=distances(f,target)
                candidates.append(dict(symbol=symbol,threshold_fraction=threshold,features=f,distances=d,
                    extended_distances=distances(f,target,EXTENDED_FEATURES)))
            ds=[c["distances"] for c in candidates]
            extended_ds=[c["extended_distances"] for c in candidates]
            for c in candidates:
                c["pareto_nondominated"]=is_pareto(c["distances"],ds)
                c["tolerance_matches"]={mode:matches(c["distances"],mode) for mode in TOLERANCES}
                c["extended_pareto_nondominated"]=is_pareto(c["extended_distances"],extended_ds,EXTENDED_FEATURES)
                c["extended_tolerance_matches"]={mode:matches(c["extended_distances"],mode,EXTENDED_FEATURES) for mode in TOLERANCES}
            tops={}
            for feature in FEATURES:
                chosen=sorted([c for c in candidates if c["distances"][feature] is not None],key=lambda c:(c["distances"][feature],c["features"]["date"]))[:5]
                tops[feature]=[c["features"]["date"] for c in chosen]
                for rank,c in enumerate(chosen,1):nearest.append(dict(symbol=symbol,threshold_fraction=threshold,method="core_original",ranking_feature=feature,rank=rank,date=c["features"]["date"],distance=c["distances"][feature]))
            original=dict(candidate_count=len(candidates),top5_by_feature=tops,
                pareto_dates=[c["features"]["date"] for c in candidates if c["pareto_nondominated"]],
                tolerance_intersection_dates={mode:[c["features"]["date"] for c in candidates if c["tolerance_matches"][mode]] for mode in TOLERANCES})
            extended_tops={}
            for feature in EXTENDED_FEATURES:
                chosen=sorted([c for c in candidates if c["extended_distances"][feature] is not None],key=lambda c:(c["extended_distances"][feature],c["features"]["date"]))[:5]
                extended_tops[feature]=[c["features"]["date"] for c in chosen]
                for rank,c in enumerate(chosen,1):nearest.append(dict(symbol=symbol,threshold_fraction=threshold,method="extended_shape",ranking_feature=feature,rank=rank,date=c["features"]["date"],distance=c["extended_distances"][feature]))
            block["historical"][symbol]=dict(**original,core_original=original,
                extended_shape=dict(candidate_count=len(candidates),top5_by_feature=extended_tops,
                    pareto_dates=[c["features"]["date"] for c in candidates if c["extended_pareto_nondominated"]],
                    tolerance_intersection_dates={mode:[c["features"]["date"] for c in candidates if c["extended_tolerance_matches"][mode]] for mode in TOLERANCES}))
            all_candidates.extend(candidates)
        payload["by_threshold"][key]=block
    for candidate in all_candidates:
        symbol=candidate["symbol"];history=sorted(data[symbol]+extension.get(symbol,[]),key=lambda r:r["date"])
        candidate["historical_126_outcome"]=historical_outcome(history,candidate["features"]["date"])
    payload["historical_outcome_coverage"]=dict(extension_used=bool(extension),extension_path="prices_2009_extension.csv" if extension else None,
        complete_candidate_outcomes=sum(c["historical_126_outcome"]["status"]=="complete" for c in all_candidates),
        censored_candidate_outcomes=sum(c["historical_126_outcome"]["status"]!="complete" for c in all_candidates),
        outcomes_not_used_in_feature_selection=True)
    target=payload["by_threshold"]["0.10"]["current"]
    payload["current_126_session_arithmetic"]=dict(origin_close=data["KOSPI"][-1]["close"],
        additional_20pct_loss_threshold=data["KOSPI"][-1]["close"]*.8,
        prior_confirmed_trough_reclaim_level=target["last_confirmed_trough_close"],
        return_to_prior_trough_fraction=target["last_confirmed_trough_close"]/target["close"]-1,
        last_confirmed_rebound_reclaim_level=target["last_confirmed_rebound_close"],
        return_to_rebound_peak_fraction=target["last_confirmed_rebound_close"]/target["close"]-1,
        note="Threshold arithmetic only; no occurrence probability or predicted126-session return")
    control_date=dt.date(2007,7,5);known=[r for r in data["SSE_COMPOSITE"] if r["date"]<=control_date]
    observed_peak=max(known,key=lambda r:r["close"])
    control_prefix=[r for r in known if r["date"]>=observed_peak["date"]]
    control_history=sorted(data["SSE_COMPOSITE"]+extension.get("SSE_COMPOSITE",[]),key=lambda r:r["date"])
    recovery=next((r for r in control_history if r["date"]>control_date and r["close"]>=observed_peak["close"]),None)
    payload["bull_midcorrection_control"]=dict(date=control_date,symbol="SSE_COMPOSITE",
        label="Selected bullish mid-correction false-break control, outside post-October2007 candidate ranking",
        selection_warning="Known historical control chosen for structural comparison; not an independent case or a forecast weight.",
        observed_peak_as_of_control=observed_peak,
        features_by_threshold={f"{t:.2f}":phase_features(control_prefix,t) for t in THRESHOLDS},
        historical_126_outcome=historical_outcome(control_history,control_date),
        later_prior_high_first_reclaimed_date=recovery["date"] if recovery else None,
        later_prior_high_first_reclaimed_close=recovery["close"] if recovery else None,
        outcome_role="Historical outcome shown after prefix features; no projection onto Korean future.")
    (ROOT/"phase_analysis.json").write_text(json.dumps(serialize(payload),ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf8")
    def write(name,rows):
        with (ROOT/name).open("w",newline="",encoding="utf8") as handle:
            writer=csv.DictWriter(handle,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(serialize(rows))
    write("anchors.csv",anchor_rows);write("postpeak_aligned_series.csv",series_rows);write("nearest_candidates.csv",nearest)
    write("phase_aligned_series.csv",phase_rows)
    write("prepeak_drawdown_excursions.csv",excursion_rows)
    flat=[]
    for c in all_candidates:
        r=dict(symbol=c["symbol"],threshold_fraction=c["threshold_fraction"],**c["features"])
        r.update({"distance_"+k:v for k,v in c["distances"].items()});r["pareto_nondominated"]=c["pareto_nondominated"]
        r.update({"tolerance_"+k:v for k,v in c["tolerance_matches"].items()});r.update({"future126_"+k:v for k,v in c["historical_126_outcome"].items()});flat.append(r)
        r.update({"extended_distance_"+k:v for k,v in c["extended_distances"].items()})
        r["extended_pareto_nondominated"]=c["extended_pareto_nondominated"]
        r.update({"extended_tolerance_"+k:v for k,v in c["extended_tolerance_matches"].items()})
    fields=list(dict.fromkeys(k for r in flat for k in r))
    with (ROOT/"all_candidates.csv").open("w",newline="",encoding="utf8") as handle:
        writer=csv.DictWriter(handle,fieldnames=fields);writer.writeheader();writer.writerows(serialize(flat))
    if digest(FROZEN)!=frozen_hash:raise ValueError("Frozen source changed during run")
    print(json.dumps(serialize(dict(anchors=anchors,current={k:v["current"] for k,v in payload["by_threshold"].items()},
        intersections={k:v["historical"]["SSE_COMPOSITE"]["tolerance_intersection_dates"] for k,v in payload["by_threshold"].items()},coverage=payload["historical_outcome_coverage"])),ensure_ascii=False))


if __name__=="__main__":main()
