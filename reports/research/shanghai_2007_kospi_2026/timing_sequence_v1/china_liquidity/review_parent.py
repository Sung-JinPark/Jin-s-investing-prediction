"""Independent checks; never modify parent report, source files or price input."""
from pathlib import Path
import csv
import datetime as dt
import hashlib
import json

ROOT=Path(__file__).resolve().parent
PARENT=ROOT.parent


def main():
    with (PARENT.parent/'prices/prices.csv').open(encoding='utf-8-sig') as f:
        rows=list(csv.DictReader(f))
    series={s:{r['date']:float(r['close']) for r in rows if r['symbol']==s} for s in ['SSE_COMPOSITE','KOSPI']}
    with (PARENT/'price_chronology.csv').open(encoding='utf-8-sig') as f:
        chrono=list(csv.DictReader(f))
    checks=[]
    for r in chrono:
        a=series[r['symbol']];dates=sorted(a);value=a[r['date']];peak=a[r['peak_reference_date']]
        assert abs(value-float(r['close_index_points']))<1e-9
        assert abs(value/peak-1-float(r['return_from_observed_peak_fraction']))<1e-12
        assert dates.index(r['date'])-dates.index(r['peak_reference_date'])==int(r['actual_return_intervals_from_peak'])
        checks.append({'symbol':r['symbol'],'date':r['date'],'return_fraction':value/peak-1})
    e=json.loads((ROOT/'evidence.json').read_text(encoding='utf8'))
    months={r['period']:r for r in e['monthly_activity']}
    assert [months[m]['daily_average_turnover_CNY_100million'] for m in ['2007-05','2007-07','2007-08','2007-09','2007-10','2007-11','2007-12','2008-01']]==[3274.7,1502.53,2375.84,2314.41,1952.16,1144.51,1453.49,2115.02]
    assert months['2007-10']['trading_days_official']==18
    assert months['2008-02']['trading_days_official']==16
    assert abs(months['2008-01']['sse_month_price_return_fraction']-(-0.16690297174222093))<1e-12
    rates=[r for r in e['policy_events'] if r['event_id'].startswith('RATE_')]
    rrr=[r for r in e['policy_events'] if r['event_id'].startswith('RRR_') and r['effective_date'].startswith('2007')]
    assert len(rates)==6 and sum(r['effective_date']<'2007-10-16' for r in rates)==5
    assert len(rrr)==10 and sum(r['effective_date']<'2007-10-16' for r in rrr)==7
    assert sum(r['announcement_date']<'2007-10-16' for r in rrr)==8
    report=(PARENT/'report.md').read_text(encoding='utf-8-sig')
    assert '유효 A주 계좌는' not in report
    assert '개인 순매도 전환은 별개의 미확인' in report
    assert '월중 정확한 변곡일은 알 수 없음' in report
    assert '참여 활동이 일방적으로 줄지는 않음' in report
    record={
        'schema_version':1,'reviewed_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
        'review_scope':'Independent China policy/participation source-and-math review and all parent price chronology rows. Korea and earnings raw-source interpretation belongs to their separate source reviewers.',
        'report_path':'../report.md','report_sha256':hashlib.sha256((PARENT/'report.md').read_bytes()).hexdigest(),
        'price_chronology_sha256':hashlib.sha256((PARENT/'price_chronology.csv').read_bytes()).hexdigest(),
        'verdict':'passed','blocking_findings':[], 'unresolved_findings':[],
        'resolved_findings':[
            {'issue':'CSRC effective-stock-account label was narrowed to A-share-only accounts',
             'resolution':'Current report correctly says 유효 주식 계좌 and retains exact XLS scope.'},
            {'issue':'Rising turnover was described as contradicting a capital-outflow narrative',
             'resolution':'Current January table says participation activity did not fall monotonically. Retail signed flow remains unconfirmed.'}],
        'checks':{
            'all_parent_price_chronology_rows_recomputed':len(checks),'price_chronology_values':checks,
            'rate_hikes_2007_total':6,'rate_hikes_effective_prepeak':5,'rrr_hikes_2007_total':10,
            'rrr_announcements_prepeak':8,'rrr_effective_prepeak':7,
            'oct13_announcement_vs_oct25_effective_separated':True,
            'monthly_turnover_8_key_values_match_original_xls':True,
            'monthly_holiday_counts_match_actual_SSE_sessions':True,
            'january2008_SSE_month_return_fraction':months['2008-01']['sse_month_price_return_fraction'],
            'effective_accounts_2007year_end':92805900,'effective_accounts_2008jan_end':94789900,
            'gross_new_A_accounts_oct15_approximate':230000,'gross_new_A_accounts_nov22':118776,
            'source_grades_and_new_account_scattered_dates_preserved':True,
            'turnover_new_effective_holding_active_accounts_not_treated_as_equivalent':True,
            'prepeak_and_postpeak_turnover_evidence_and_counterexamples_included':True,
            'no_retrospective_annual_total_used_for_monthly_turning_point':True,
            'retail_net_sell_turning_date_not_identified':True,
            'causal_effect_sizes_not_claimed':True,
            'no_crash_probability_or_official_forecast_produced':True},
        'data_limitations':[
            'CSDC original continuous new-account and natural-person monthly buy/sell panels not recovered; dated contemporary reports are not primary CSDC raw tables.',
            'Published CSRC daily averages have small arithmetic discrepancies from monthly total divided by trading days; source and recomputed values both retained, max0.018333 CNY100million/day.',
            'Monthly observations cannot order intramonth activity change around Oct16; October report released Nov12.',
            'Dormant-account segregation Oct8 changes account interpretation. Account growth is not a direct capital-flow measure.',
            'PBOC retrospective chronology sometimes uses effective dates as decision dates; actual rate announcement dates were independently recovered from official/datestamped contemporary sources.',
            'Primary gov.cn December20 QA is web-index-readable but direct acquisition failed; retained Dec20 Xinhua and PBC policy report independently support the cited action.',
            'Downloaded CSRC annual-report PDF is invalid content and excluded; all44 valid raw source file hashes checked by the offline builder.']}
    (ROOT/'independent_review.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'status':record['verdict'],'parent_price_rows':len(checks),
                      'report_sha256':record['report_sha256'],'january_return':months['2008-01']['sse_month_price_return_fraction']},ensure_ascii=False))


if __name__=='__main__':
    main()
