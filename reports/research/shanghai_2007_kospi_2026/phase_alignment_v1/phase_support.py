"""Frozen price levels and explicitly unvalidated observation gates."""
from __future__ import annotations

import csv
import datetime as dt
import json
import math
from pathlib import Path
import statistics

ROOT=Path(__file__).resolve().parent
STUDY=ROOT.parent


def consecutive(closes:list[float],level:float,side:str)->int:
    if not closes or not math.isfinite(level) or level<=0 or side not in ("above","below"):
        raise ValueError("positive level, nonempty observations and explicit side required")
    if any(not math.isfinite(p) or p<=0 for p in closes):raise ValueError("invalid price")
    count=0
    for p in reversed(closes):
        if (side=="above" and p>level) or (side=="below" and p<level):count+=1
        else:break
    return count


def build()->dict:
    all_rows=list(csv.DictReader((STUDY/"prices/prices.csv").open(encoding="utf-8")))
    rows=[r for r in all_rows if r["symbol"]=="KOSPI"]
    prices=[float(r["close"]) for r in rows]
    by_date={r["date"]:float(r["close"]) for r in rows}
    origin=prices[-1]
    levels={"prior_trough":by_date["2026-07-30"],"last_pre_break_close":by_date["2026-10-14"],
            "observed_rebound_high":by_date["2026-09-23"],"observed_peak":by_date["2026-06-22"],
            **{f"sma_{n}":statistics.mean(prices[-n:]) for n in (20,60,120)}}
    records=[{"level":name,"value_index_points":value,"required_return_fraction":value/origin-1,
              "role":"frozen historical price reference" if not name.startswith("sma") else "moving average at cutoff; recompute each future day, not a fixed resistance forecast"}
             for name,value in levels.items()]
    gates=[
        {"id":"price_reclaim","condition_ko":"이전 저점 위 5거래일 연속 종가","side":"above","level":levels["prior_trough"],
         "observed_consecutive":consecutive(prices,levels["prior_trough"],"above"),"required":5,
         "meaning_ko":"초기 이탈 실패와 가격 안정의 관찰 기준. 상승 추세 확정은 아님."},
        {"id":"price_break","condition_ko":"이전 저점 아래 5거래일 연속 종가","side":"below","level":levels["prior_trough"],
         "observed_consecutive":consecutive(prices,levels["prior_trough"],"below"),"required":5,
         "meaning_ko":"하루짜리 이탈과 지속적인 저점 이탈을 구분하는 관찰 기준."},
    ]
    for gate in gates:
        gate.update(satisfied=gate["observed_consecutive"]>=gate["required"],
                    calibration="unvalidated research heuristic; not fitted, not a trading rule or probability")
    sensitivity=[]
    for eps,pe,label in [(.2,0,"이익 증가와 배수 유지"),(.2,-.2,"이익 증가와 배수 축소"),
                         (0,-.2,"이익 유지와 배수 축소"),(-.2,-.2,"이익 하향과 배수 축소"),(-.1,.2,"이익 감소와 배수 회복")]:
        ret=(1+eps)*(1+pe)-1
        sensitivity.append({"label_ko":label,"eps_change_fraction":eps,"pe_change_fraction":pe,
                            "price_return_fraction":ret,"illustrative_index_points":origin*(1+ret),
                            "role":"arithmetic assumptions, not a six-month price target or expected return; EPS must use the same index and forecast period"})
    cn=[r for r in all_rows if r["symbol"]=="SSE_COMPOSITE"]
    cases=[]
    for date,label in [("2007-07-05","상승 중간의 전저점 이탈 뒤 회복한 반례"),
                       ("2008-01-22","첫 하락 뒤 반등 실패와 전저점 이탈"),
                       ("2008-03-18","현재 한국 낙폭 문턱의 최초 하회"),
                       ("2008-06-10","깊은 하락 중 큰 반등 뒤 저점 재이탈")]:
        idx=next(i for i,r in enumerate(cn) if r["date"]==date)
        p0=float(cn[idx]["close"]);future=cn[idx+1:idx+127];old_high=max(float(r["close"]) for r in cn[:idx+1])
        if len(future)!=126:raise ValueError("Illustrative historical case needs 126 actual future intervals")
        values=[float(r["close"]) for r in future];peak=p0;mdd=0
        for value in values:peak=max(peak,value);mdd=min(mdd,value/peak-1)
        cases.append({"date":date,"label_ko":label,"origin_index_points":p0,"prior_observed_high":old_high,
                      "initial_drawdown_fraction":p0/old_high-1,"end_date":future[-1]["date"],
                      "end_126_return_fraction":values[-1]/p0-1,"worst_origin_return_fraction":min([p0]+values)/p0-1,
                      "best_origin_return_fraction":max([p0]+values)/p0-1,"future_max_drawdown_fraction":mdd,
                      "extrema_definition":"origin and 126 subsequent actual closes included; no clipping of returns",
                      "recovered_prior_observed_high":max(values)>=old_high,
                      "role":"Deliberately contrasting historical episodes; overlapping dates and paths, not independent samples, probabilities, targets or Korean projection"})
    kp=max(range(len(prices)),key=lambda i:prices[i]);cp=max(range(len(cn)),key=lambda i:float(cn[i]["close"]))
    n=len(prices)-kp-1;kc=prices[kp:];cc=[float(r["close"]) for r in cn[cp:cp+n+1]]
    phase_corr={"n_return_pairs":n,"n_closes":n+1,"historical_end":cn[cp+n]["date"],
                "closing_level_pearson":statistics.correlation(kc,cc),
                "daily_log_return_pearson":statistics.correlation([math.log(b/a) for a,b in zip(kc,kc[1:])],
                                                                    [math.log(b/a) for a,b in zip(cc,cc[1:])]),
                "role":"retrospective observed-peak alignment for equal elapsed actual sessions; level correlation does not establish predictive skill"}
    result={"as_of":"2026-10-16T09:00:00+09:00","price_cutoff":rows[-1]["date"],"origin_index_points":origin,
            "horizon_future_return_intervals":126,"fraction_unit_explicit":True,"probability_output":False,
            "levels":records,"price_gates":gates,"valuation_arithmetic":sensitivity,"contrasting_historical_cases":cases,
            "postpeak_equal_age_correlation":phase_corr,
            "additional_20pct_loss_threshold_index_points":origin*.8,
            "extra_20pct_loss_is_not_future_max_drawdown":True,
            "earnings_revision_series":None,
            "earnings_revision_missing_reason":"No original-vintage, common-provider fixed-FY2027 index EPS series acquired; current revision sign cannot be inferred from strong realized sales or profit guidance",
            "benchmark":None,"benchmark_reason":"Original study MSCI World source conflict remains unresolved; no benchmark-relative claim"}
    (ROOT/"phase_support.json").write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    with (ROOT/"current_levels.csv").open("w",newline="",encoding="utf-8-sig") as handle:
        writer=csv.DictWriter(handle,fieldnames=list(records[0]));writer.writeheader();writer.writerows(records)
    return result


if __name__=="__main__":
    r=build();print(json.dumps({"origin":r["origin_index_points"],"price_gates":r["price_gates"]},ensure_ascii=False))
