"""Independent descriptive stage checks from retained canonical closes only."""
from datetime import date, datetime, timezone
import csv
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
STUDY=ROOT.parents[1]
CANONICAL=STUDY/'prices/prices.csv'


def directional_turns(rows,anchor_date,threshold):
    """Forward-only confirmation; extremum label becomes known on confirmation."""
    by_date={r['date']:i for i,r in enumerate(rows)}
    a=by_date[anchor_date];mode='down';candidate=a;turns=[]
    for i in range(a+1,len(rows)):
        value=rows[i]['close']
        if mode=='down':
            if value<rows[candidate]['close']:
                candidate=i
            if value>=rows[candidate]['close']*(1+threshold):
                turns.append({'type':'trough','extremum':rows[candidate],'confirmed_on':rows[i]['date'],
                    'sessions_extremum_to_confirmation':i-candidate})
                mode='up';candidate=i
        else:
            if value>rows[candidate]['close']:
                candidate=i
            if value<=rows[candidate]['close']*(1-threshold):
                turns.append({'type':'rebound_peak','extremum':rows[candidate],'confirmed_on':rows[i]['date'],
                    'sessions_extremum_to_confirmation':i-candidate})
                mode='down';candidate=i
    return {'threshold_fraction':threshold,'confirmation_rule':'positive bounce from running low >= threshold; decline from running high >= threshold. Prefix-only confirmation, fixed anchor. Thresholds are sensitivity settings, not optimized.',
        'anchor':rows[a],'turns':turns,'last_state':mode,'unconfirmed_extremum':rows[candidate]}


def sequence(rows,name,peak_date,trough_date,rebound_date,anchor_selection):
    idx={r['date']:i for i,r in enumerate(rows)}
    p,t,h=map(idx.get,[peak_date,trough_date,rebound_date])
    P,T,H=[rows[i]['close'] for i in [p,t,h]]
    assert p<t<h and P>T and H>T
    first_breach=next((i for i in range(h+1,len(rows)) if rows[i]['close']<T),None)
    recovery=next((i for i in range(h+1,len(rows)) if rows[i]['close']>P),None)
    b=first_breach
    return {'label':name,'anchor_selection':anchor_selection,'peak':rows[p],'first_or_designated_trough':rows[t],
        'rebound_peak':rows[h],'trough_drawdown_from_peak_fraction':T/P-1,
        'rebound_return_from_trough_fraction':H/T-1,'recovered_lost_peak_to_trough_points_fraction':(H-T)/(P-T),
        'rebound_drawdown_from_original_peak_fraction':H/P-1,
        'sessions_peak_to_trough':t-p,'sessions_trough_to_rebound':h-t,
        'first_close_below_designated_trough_after_rebound':rows[b] if b is not None else None,
        'sessions_rebound_to_first_breach':b-h if b is not None else None,
        'sessions_peak_to_first_breach':b-p if b is not None else None,
        'breach_drawdown_from_peak_fraction':rows[b]['close']/P-1 if b is not None else None,
        'breach_return_from_rebound_fraction':rows[b]['close']/H-1 if b is not None else None,
        'breach_return_from_designated_trough_fraction':rows[b]['close']/T-1 if b is not None else None,
        'first_subsequent_close_above_original_peak':rows[recovery] if recovery is not None else None,
        'days_are_observed_session_gaps':'Index differences count actual return intervals; no weekend or holiday padding.'}


def outcome(rows,origin_date,horizon=126):
    i=next(i for i,r in enumerate(rows) if r['date']==origin_date)
    origin=rows[i];future=rows[i+1:i+horizon+1]
    if len(future)!=horizon:
        return {'status':'right_censored','observations_available':len(future),'result':None}
    path=[origin]+future;running_peak=origin;mdd=0.0;dd_peak=origin;dd_trough=origin
    for r in future:
        if r['close']>running_peak['close']:running_peak=r
        dd=r['close']/running_peak['close']-1
        if dd<mdd:mdd=dd;dd_peak=running_peak;dd_trough=r
    high=max(path,key=lambda r:r['close']);low=min(path,key=lambda r:r['close'])
    return {'status':'complete','origin':origin,'horizon_sessions':horizon,'first_future_date':future[0]['date'],
        'end':future[-1],'end_return_fraction':future[-1]['close']/origin['close']-1,
        'max_drawdown_fraction':mdd,'max_drawdown_peak':dd_peak,'max_drawdown_trough':dd_trough,
        'maximum_upside_from_origin_fraction':high['close']/origin['close']-1,'maximum_upside_observation':high,
        'minimum_return_from_origin_including_origin_fraction':low['close']/origin['close']-1,'minimum_origin_return_observation':low,
        'worst_future_return_excluding_origin_fraction':min(r['close']/origin['close']-1 for r in future),
        'additional_20pct_origin_loss_event':any(r['close']/origin['close']-1<=-.20 for r in future),
        'definition':'End return uses exactly126 later closes. Max drawdown uses running peak from origin. Origin-upside/minimum include the origin observation, so zero means the origin was never exceeded/undercut; no clipping or interpolation.',
        'role':'Equal-treatment descriptive historical outcome; anchors were selected by visible stage interpretation, not future return. Not a forecast or independent frequency observation.'}


def main():
    raw=list(csv.DictReader(CANONICAL.open(encoding='utf8',newline='')))
    series={symbol:[{'date':r['date'],'close':float(r['close'])} for r in raw if r['symbol']==symbol] for symbol in ['SSE_COMPOSITE','KOSPI']}
    for symbol,rows in series.items():
        assert rows==sorted(rows,key=lambda r:r['date'])
        assert len({r['date'] for r in rows})==len(rows)
        assert all(r['close']>0 for r in rows)
    k=series['KOSPI'];cn=series['SSE_COMPOSITE']
    selection={'CN_MID_RALLY_2007':'Descriptive extrema within explicitly historical windows: peak May2007; low May30-Jun15; rebound Jun5-Jun30. These windows are retrospective case interpretation, not a prospective selection rule.',
        'CN_EARLY_POST_PEAK':'Observed maximum close Oct16; first low in Oct17-Nov30; rebound maximum Nov29-Jan21. Retrospective anchors require confirmation-date distinction.',
        'CN_DEEP_BEAR_2008':'Observed maximum Oct16; March-April decline low within Mar1-Apr30; rebound high within Apr19-May31. Not independent of other China windows.',
        'KOREA_OBSERVED_CURRENT':'Observed maximum through cutoff Jun22; subsequent low through Jul31; highest subsequent rebound close through Oct15. Not an assertion of a permanent final peak.'}
    sequences=[sequence(k,'KOREA_OBSERVED_CURRENT','2026-06-22','2026-07-30','2026-09-23',selection['KOREA_OBSERVED_CURRENT']),
        sequence(cn,'CN_MID_RALLY_2007','2007-05-29','2007-06-04','2007-06-19',selection['CN_MID_RALLY_2007']),
        sequence(cn,'CN_EARLY_POST_PEAK','2007-10-16','2007-11-28','2008-01-14',selection['CN_EARLY_POST_PEAK']),
        sequence(cn,'CN_DEEP_BEAR_2008','2007-10-16','2008-04-18','2008-05-05',selection['CN_DEEP_BEAR_2008'])]
    threshold=sequences[0]['breach_drawdown_from_peak_fraction']
    peak=next(r for r in cn if r['date']=='2007-10-16')
    match=next(r for r in cn if r['date']>peak['date'] and r['close']/peak['close']-1<=threshold)
    turns={symbol:{str(q):directional_turns(rows,anchor,q) for q in [.10,.15,.20]}
        for symbol,rows,anchor in [('SSE_COMPOSITE',cn,'2007-10-16'),('KOSPI',k,'2026-06-22')]}
    result={'schema_version':1,'created_at_utc':datetime.now(timezone.utc).isoformat(),'price_cutoff':'2026-10-15',
        'source_csv':'../../prices/prices.csv','source_sha256':hashlib.sha256(CANONICAL.read_bytes()).hexdigest(),
        'source_china_evidence':'../../china/evidence.json','source_china_evidence_sha256':hashlib.sha256((STUDY/'china/evidence.json').read_bytes()).hexdigest(),
        'research_only':True,'probabilities':None,'unit_policy':'All ratios, returns, recoveries and thresholds are explicitly fractions; close is index_points; session counts are observed return intervals.',
        'historical_anchor_type':'retrospective observed extrema, with separate prefix-only threshold confirmations',
        'anchor_sequences':sequences,'depth_only_first_crossing':{'threshold_drawdown_fraction':threshold,'date':match['date'],'close':match['close'],'actual_drawdown_fraction':match['close']/peak['close']-1,
            'role':'Depth-only comparator, not a stage-equivalent conclusion. It precedes the April-May2008 large rebound.'},
        'equal_horizon_historical_outcomes':{date:outcome(cn,date) for date in ['2007-07-05','2008-01-22','2008-06-10']},
        'directional_confirmation_sensitivities':turns,
        'bounded_conclusion':'Current Korea has an observed peak, deep first decline, sizable rebound and the first marginal break of the first trough. The Oct2007-Jan2008 Chinese sequence is similar in event order and duration under10% confirmation, but its14.46% bounce fails15/20% sensitivity. The April-May-June2008 sequence passes larger-bounce filters but is deeper and older. March18 is a depth crossing, not by itself an equivalent rebound stage. No unique date is robust across dimensions.',
        'not_inferred':['causal economic equivalence','a final peak known prospectively','a permanent downtrend from one close below prior low','future Korean path or probability','independent sample size increased by multiple China windows']}
    (ROOT/'initial_review_metrics.json').write_text(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps({'sequences':len(sequences),'thresholds':[.10,.15,.20],'depth_only':result['depth_only_first_crossing'],'file':'initial_review_metrics.json'},ensure_ascii=False))


if __name__=='__main__':main()
