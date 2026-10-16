"""Bounded retrospective chronology; no forecasting or ledger writes."""
from pathlib import Path
import csv, datetime, hashlib, json

ROOT = Path(__file__).resolve().parent
STUDY = ROOT.parents[1]
PRICE_FILE = STUDY/'china/daily_indices_2005_2008.csv'
MANIFEST = json.loads((ROOT/'source_manifest.json').read_text(encoding='utf-8'))
SOURCES = {r['source_id']:r for r in MANIFEST['sources']}
CREATED = datetime.datetime.now(datetime.timezone.utc).isoformat()

def metric(name, value, original_unit, normalized_value=None, normalized_unit=None, **kw):
    return dict(name=name, original_value=value, original_unit=original_unit,
                normalized_value=normalized_value, normalized_unit=normalized_unit, **kw)

def pct(name, value, **kw):
    return metric(name,value,'percent',value/100,'fraction',**kw)

rows=[]
def add(eid,date,period,universe,kind,claim,source_id,locator,metrics=None,status='confirmed',limitations=None):
    source=SOURCES[source_id]
    row=dict(evidence_id=eid,published_at=date,observation_period=period,universe=universe,
        event_kind=kind,claim_ko=claim,claim_status=status,source_id=source_id,
        source_url=source['url'],source_sha256=source.get('sha256'),locator=locator,
        metrics=metrics or [],limitations=limitations or [],
        document_date_observed_in_current_archive=True,original_vintage_authenticated=False,
        original_available_at_timestamp=None,intraday_publication_time_verified=False,
        point_in_time_use='Retrospective historical evidence only; no authenticated original bytes or first dissemination timestamp.',
        hindsight_note='Do not treat later aggregate reports or subsequent 2008 results as known at the 2007-10-16 price peak.')
    rows.append(row)
    return row

add('CNQ3_01','2007-11-01','2007-01-01/2007-09-30','SSE 855 reporting companies','realized_results',
    '10월 31일까지 3분기 공시를 마친 855개사의 1~9월 순이익은 크게 증가했다.',
    'orient_daily_20071101','PDF pp.2 (date), 6 (SSE results)',[
        metric('net_profit',5123,'CNY_100_million',512300000000,'CNY'),pct('net_profit_yoy',73.8),
        metric('weighted_average_eps',.301,'CNY_per_share'),pct('weighted_average_eps_yoy',98)],
    limitations=['Fund publisher reproduces Securities Times reporting attributed to SSE, not an original SSE statistical release.',
        'Nine-month cumulative profit, not standalone Q3 profit, index EPS or cash operating growth.',
        'Aggregate release is after peak; individual filings/forecasts could be known earlier. First firm filing date not established.'])
add('CNQ3_02','2007-11-01','2007-07-01/2007-09-30','SSE reporting companies','realized_momentum_warning',
    '동시대 결산 기사 자체가 단일 3분기 성장 모멘텀 둔화를 경고했다. 연말까지 아무 둔화 신호도 없었다고 할 수 없다.',
    'orient_daily_20071101','PDF p.7, 三季度业绩增长速度减缓',status='partial',limitations=[
        'Quarterly "环比" sentences contain internally ambiguous numbers versus cumulative/standalone profits. No QoQ net-profit decline rate is computed or used.'])
add('CNQ3_03','2007-11-01','2007-01-01/2007-09-30','SSE reporting companies','earnings_quality',
    '투자수익은 세전 이익의 중요한 부분이었다. 분모를 순이익과 섞거나 투자수익을 전부 주식 평가이익으로 바꿀 수 없다.',
    'orient_daily_20071101','PDF p.7, 投资收益',[
        metric('investment_income',1651,'CNY_100_million',165100000000,'CNY'),
        pct('investment_income_share_of_total_profit_before_tax',23.25),pct('investment_income_yoy',283)],
    limitations=['Investment income is broader than listed-stock gains, including equity holdings and investment disposal; not a clean causal contribution.'])
add('CNQ3_04','2007-11-01','2007-01-01/2007-09-30','SSE reporting companies','earnings_quality',
    '비경상손익의 시장 전체 비중은 작았지만 일부 ST기업에는 매우 컸다.',
    'orient_daily_20071101','PDF p.7, 非经常性损益',[
        metric('nonrecurring_income',178.03,'CNY_100_million',17803000000,'CNY'),pct('nonrecurring_share_of_total_profit_before_tax',2.5)],
    limitations=['Do not equate investment income with nonrecurring gains: classifications and denominators differ.'])
add('ICBC_01','2007-10-29','2007-01-01/2007-09-30','ICBC company only','company_results_release',
    'ICBC는 10월 29일 실적 공표를 했다고 자사 기록에 명시하며 큰 순이익 증가를 보고했다.',
    'icbc_2007q3','Company article opening paragraphs; release date stated in body',[
        metric('ifrs_after_tax_profit',64.1,'CNY_billion',64100000000,'CNY'),pct('ifrs_after_tax_profit_yoy',66),
        metric('cas_after_tax_profit',63.9,'CNY_billion',63900000000,'CNY'),pct('cas_after_tax_profit_yoy',65.5)],
    limitations=['2007-10-29 is a results-publication date referenced in the company page, not a verified webpage timestamp.',
        'IFRS and Chinese accounting standards differ; one major bank is not the whole index.'])
add('OPTIMISM_01','2008-01-02','2008 forecasts','Selected institutions quoted in a 35-institution strategy digest','positive_forecast_counterevidence',
    '고점 이후에도 여러 기관이 2008년 순익 약 30% 안팎의 양의 성장을 예상했다.',
    'orient_daily_200801','PDF p.2 visible masthead date; p.16 outlook digest',[
        pct('quoted_xingye_net_profit_growth_low',30),pct('quoted_xingye_net_profit_growth_high',40),
        pct('quoted_orient_securities_net_profit_growth',30)],
    limitations=['Selected broker views reprinted by a fund; not a reconstructed consensus or independent original reports for each quoted institution.',
        'Positive growth forecasts can coexist with downgrades; they do not establish unchanged forecast EPS.'])
add('REVISION_01','2008-01-21','Forecast vintages shown in a contemporaneous chart; exact row dates unreadable','CSI300 companies, vendor 朝阳永续 / Great Wall Securities','forecast_revision_evidence',
    '1월 21일 장성증권 글은 CSI300 이익 성장 컨센서스의 하향이 시작됐다는 그림을 제시했다.',
    'greatwall_20080121','Newspaper C03; chart 2; original page PDF and chart image archived',[],status='partial',limitations=[
        'Chart legends are 2007/2008 net-profit forecast growth, not EPS levels. Largest visible step belongs to 2007 line.',
        'A smaller decline is visible in the 2008 line; low-resolution axis/values do not support exact first revision date or magnitude.',
        'No raw provider observations, fixed constituents, aggregation method or authenticated original forecast vintage were recovered.',
        'The January 21 publication proves the claim was publicly made by then, not that January 21 was the first downgrade.',
        'CSI300 universe differs from SSE Composite; do not substitute their series.'])
add('OPTIMISM_02','2008-01-21','2008 forecast','Great Wall Securities A-share strategy','positive_forecast_counterevidence',
    '같은 글도 이익 하향 필요성과 양의 성장 전망을 동시에 제시했다.',
    'greatwall_20080121','C03, 业绩预期或将向下修正; 08年沪综指波动于4300—6700点',[
        pct('own_neutral_profit_growth',25),pct('own_profit_growth_range_low',20),pct('own_profit_growth_range_high',30)],
    limitations=['House scenario/view, not observed subsequent growth or an aggregate consensus revision sequence.'])
add('QUALITY_01','2008-01-21','2007-01-01/2007-09-30 estimated stock-investment profits','Great Wall estimate of A-share companies','earnings_quality_estimate',
    '장성증권은 주식 투자이익만 따로 추산할 때 세전 이익의 약 8%라고 봤다.',
    'greatwall_20080121','C03, 业绩预期或将向下修正',[
        pct('estimated_stock_investment_share_of_total_profit_before_tax',8)],status='partial',limitations=[
        'Broker estimate, not audited exchange statistic. Broader investment income must not be relabelled stock gains.',
        'Hypothetical stock-gain reductions in article are scenarios, not observed causal losses.'])
add('ANNUAL_01','2008-02-05','2007-01-01/2007-12-31; early reports through 2008-02-02','75 nonfinancial companies, nonrandom early-reporting sample','realized_results_early_sample',
    '초기 연간실적 표본은 강했으며, 첫 연간보고서 공표는 1월 22일부터였다고 재정부가 밝혔다.',
    'mof_2007_early_annual','Q&A paragraphs 2-5; visible publication date February 5',[
        pct('sample_consolidated_net_profit_yoy',83.70),pct('sample_gross_profit_yoy',71.49),
        pct('increment_gross_profit_divided_by_increment_net_profit',94.75)],limitations=[
        'Only 75 early-reporting nonfinancial companies; selection and universe differ from all-market/SSE results.',
        'Ratio is an arithmetic comparison of gross-profit and net-profit increments, not a tax-adjusted causal attribution or cash-flow share.',
        'Do not generalize the two financial firms separately discussed by MOF to the whole bank/insurance sector.'])
add('ANNUAL_02','2008-06-02','2007-01-01/2007-12-31; filings through 2008-04-30','SSE listed companies; document cites 862 listed and one reporting exception','realized_results_complete_review',
    'SSE의 2007년 결산 검토는 연간 실적 성장과 주당이익 최고치를 고점 한참 뒤에 요약했다.',
    'sse_2007_annual','Opening paragraph',[
        pct('reported_overall_performance_growth',47.5),metric('weighted_eps',.42,'CNY_per_share')],limitations=[
        'Official summary says overall performance, not a same-constituent index EPS series.',
        'This June 2 summary date is not the first date each annual result became known; disclosures were largely completed by April 30.',
        'Do not use the full 2007 annual number in a forecast as of October 2007.'])
add('ANNUAL_03','2008-06-02','2007-01-01/2007-12-31','SSE reporting companies','earnings_quality',
    'SSE 검토에서 공정가치 변동손익은 연간 순익의 일부였다. 전체 실적 급증을 이 항목만으로 설명할 수 없다.',
    'sse_2007_annual','Second substantive paragraph',[
        pct('fair_value_change_gains_share_of_annual_net_profit',2.6)],limitations=[
        'Fair-value changes are distinct from realized investment income/disposals and from other comprehensive income.'])
add('Q108_01','2008-04-30','2008-01-01/2008-03-31','SZSE mainboard 487 reporting companies of 488','realized_results',
    '2008년 1분기 선전 주판 실적은 여전히 증가했지만 증가 속도는 느려졌다.',
    'szse_2008q1','Sections I and II',[
        metric('net_profit',259,'CNY_100_million',25900000000,'CNY'),pct('net_profit_yoy',41),
        pct('operating_profit_yoy',26),pct('weighted_eps_yoy',25.70),pct('weighted_eps_ex_nonrecurring_yoy',23.87)],limitations=[
        'SZSE mainboard is not SSE, all A-shares or CSI300. These growth rates cannot be spliced as one index earnings series.',
        'Quarterly positive YoY growth and slowing momentum are different from an outright fall in annual profit.'])
add('Q108_02','2008-04-30','2008-01-01/2008-03-31','SZSE mainboard reporting companies','earnings_quality',
    '선전의 투자수익은 전년 대비 증가했지만 직전 분기보다 크게 줄었다.',
    'szse_2008q1','Section II',[
        metric('investment_income',51.68,'CNY_100_million',5168000000,'CNY'),
        pct('investment_income_yoy',44.36),pct('investment_income_qoq',-61.19),
        pct('investment_income_share_of_net_profit',19.95)],limitations=[
        'Seasonality, composition and other drivers remain; a QoQ fall is not a YoY fall or a controlled causal effect.'])
add('Q108_03','2008-04-30','2008-01-01/2008-03-31','94 SZSE mainboard firms participating in securities investment','earnings_quality',
    '94개 증권투자 참여사의 관련 당기 손익은 합계 적자였다고 거래소가 보고했다.',
    'szse_2008q1','Section II, 94家公司',[
        metric('reported_securities_investment_profit_loss',-9.5,'CNY_100_million',-950000000,'CNY')],limitations=[
        'Participating-firm subset; losses cannot be attributed entirely to a specific index price move.'])
add('REVISION_02','2008-05-07','2008 forecast; former estimate described only as last year','CICC covered listed companies; 266 companies referenced in adjacent discussion','quantified_house_forecast_revision',
    '중금은 2008년 순익 성장 전망을 작년 31.6%에서 25.3%로 낮췄다고 명시했다.',
    'cicc_20080507_original_article','Section II.2, 盈利增长预测下调',[
        pct('prior_2008_net_profit_growth_forecast',31.6),pct('new_2008_net_profit_growth_forecast',25.3),
        metric('growth_forecast_change',-6.3,'percentage_points',-.063,'fraction_points')],status='partial',limitations=[
        'Same institution explicitly describes its revision, but the old report date and fixed-universe/base-year calculation are not established.',
        'The article rounds the change to 6 percentage points; exact arithmetic on quoted endpoints is -6.3 percentage points.',
        'This is expected net-profit growth, not EPS level, EPS percentage cut or a market consensus forecast series.',
        'May 7 is a public upper bound on documented revision availability, not the first downgrade date.',
        'Original newspaper author attribution is CICC research department; original brokerage PDF/date-vintage not independently authenticated.'])
add('Q108_04','2008-05-07','2008-01-01/2008-03-31','CICC comparable-company calculation','realized_results',
    '같은 원문에서 비교가능 기업 기준 1분기 순익 성장률은 전체와 비금융에서 달랐다.',
    'cicc_20080507_original_article','Section I.1',[
        pct('all_comparable_net_profit_yoy',17.8),pct('nonfinancial_comparable_net_profit_yoy',-1.6)],limitations=[
        'Broker-defined comparable sample, not SZSE mainboard, SSE or a matched-constituent index EPS series.'])
add('QUALITY_02','2008-05-07','2007 and 2008-01-01/2008-03-31','CICC analysis of listed-company profits','earnings_quality',
    '중금은 2007년 이익 증가의 주된 기반을 주영업으로 보면서, 2008년 1분기에는 투자수익·공정가치 변동의 악화를 지적했다.',
    'cicc_20080507_original_article','Section II.3 and I.3(2)',[
        pct('net_investment_income_plus_fair_value_change_yoy_2008q1',-35)],limitations=[
        'Analyst attribution and accounting aggregation; market prices and investment-related profits can move together/endogenously.',
        'Not a regression or causal identification; do not classify all 2007 growth as share-price gains.'])
add('OPTIMISM_03','2008-05-06','2008 outlook','Ping An Securities own published views','positive_forecast_counterevidence',
    '5월에도 평안증권은 이익 성장의 큰 흐름이 바뀌지 않았다고 평가하며 반등에 우호적이었다.',
    'pingan_20080506','Report 3, sections 2 and conclusion; Report 4',limitations=[
        'A named house view that coexists with CICC downgrades; not proof all analysts remained optimistic.'])
add('ACTUAL08_01','2009-05-19','2008-01-01/2008-12-31; filings through 2009-04-30','CSRC domestic listed-company aggregate, 1624 companies','later_realized_results',
    '2008년 연간 결산에서는 순이익과 투자수익의 감소, 공정가치 손실이 확인됐다.',
    'csrc_2008_annual','Question I',[
        pct('net_profit_yoy',-16.82),pct('investment_income_yoy',-33.59),
        metric('fair_value_change_loss',500,'CNY_100_million',50000000000,'CNY'),
        pct('operating_net_cash_inflow_yoy',40.28)],limitations=[
        'Published May 2009, unavailable in October 2007 or early 2008. It does not date the first forecast revision.',
        'Aggregate operating cash flow increased, so no claim of an all-market cash-flow collapse.',
        'Net profit includes financing, impairment and other components; investment losses are not the only mechanism.'])

prices=[]
with PRICE_FILE.open(encoding='utf-8-sig',newline='') as f:
    for r in csv.DictReader(f):
        if r['index_id']=='sse_composite': prices.append((r['date'],float(r['close'])))
prices.sort(); peak_date='2007-10-16'; peak=next(v for d,v in prices if d==peak_date)
def context(date):
    observed=[(d,v) for d,v in prices if d<=date]
    if not observed:return None
    d,v=observed[-1]
    if date>'2008-12-31':return None
    return dict(price_date=d,close=v,unit='index_points',drawdown_from_observed_peak_fraction=v/peak-1,
        sessions_after_observed_peak=sum(peak_date<day<=d for day,_ in prices),
        price_use_note='Historical same-day closing context only, not a claim that document preceded that day\'s close.')

timeline=[]
for date,eid,kind,summary,period,sid in [
    ('2007-10-16','PRICE_PEAK','price','관측된 종가 고점 6092.06; 최종 고점 식별은 사후적','trading_day','upstream_official_price_tables'),
    ('2007-10-29','ICBC_01','company_actual','ICBC 1~9월 큰 순익 증가 공표(자사 기사에 기재된 실적 공표일)','2007-01-01/2007-09-30','icbc_2007q3'),
    ('2007-11-01','CNQ3_01','aggregate_actual','SSE 1~9월 순익 +73.8% 보도; 단일분기 성장 모멘텀 둔화도 경고','2007-01-01/2007-09-30','orient_daily_20071101'),
    ('2007-11-28','PRICE_FIRST_DD','price','관측 고점 대비 종가 약 -21.15%','trading_day','upstream_official_price_tables'),
    ('2008-01-02','OPTIMISM_01','forecast_positive','다수 기관 2008년 이익 약 +30% 성장 전망 재전재','2008_forecast','orient_daily_200801'),
    ('2008-01-21','REVISION_01','forecast_revision_partial','CSI300 이익 성장 컨센서스 하향 그림 공개; 최초일/정량값 미확인','2007/2008_forecast_vintages','greatwall_20080121'),
    ('2008-01-22','ANNUAL_FIRST_REFERENCED','filing_availability','MOF가 첫 2007년 연간보고서 공표 시작일로 명시','2007-01-01/2007-12-31','mof_2007_early_annual'),
    ('2008-02-05','ANNUAL_01','early_sample_actual','75개 비금융 조기 연간공시 표본 순익 +83.7%','2007-01-01/2007-12-31','mof_2007_early_annual'),
    ('2008-03-18','PRICE_DEEP_DD','price','종가 기준 고점 대비 약 -39.78%','trading_day','upstream_official_price_tables'),
    ('2008-04-30','Q108_01','aggregate_actual','선전 주판 Q1 순익 +41%; 투자수익 +44.36% YoY / -61.19% QoQ','2008-01-01/2008-03-31','szse_2008q1'),
    ('2008-04-30','ANNUAL_FILINGS_REFERENCED','filing_availability','SSE 2007년 연간 공시 대부분 완료(6월 2일 검토에서 확인)','2007-01-01/2007-12-31','sse_2007_annual'),
    ('2008-05-06','OPTIMISM_03','forecast_positive','평안증권: 이익 성장 추세가 근본적으로 바뀌지 않았다는 관점','2008_outlook','pingan_20080506'),
    ('2008-05-07','REVISION_02','quantified_house_revision','중금 2008년 순익 성장 전망 31.6%→25.3%; EPS 수준 하향과 구분','2008_forecast','cicc_20080507_original_article'),
    ('2008-06-02','ANNUAL_02','aggregate_actual_review','SSE 2007년 연간 실적 +47.5% 공식 검토 발표','2007-01-01/2007-12-31','sse_2007_annual'),
    ('2009-05-19','ACTUAL08_01','later_actual_review','2008년 연간 순익 -16.82%, 투자수익 -33.59%; 영업 현금흐름 +40.28%','2008-01-01/2008-12-31','csrc_2008_annual'),
]:
    timeline.append(dict(date=date,event_id=eid,event_kind=kind,summary_ko=summary,observation_period=period,
        source_id=sid,source_url=SOURCES.get(sid,{}).get('url'),document_available_on_event_date=(kind!='filing_availability'),
        availability_note=('Date is availability event referenced by later source; do not move source publication backward.' if kind=='filing_availability' else 'Historical stated publication/event date; original bytes and intraday time not authenticated.'),
        original_vintage_authenticated=False,price_context=context(date)))

signals=[
 dict(signal_id='PRICE_BEFORE_FULL_GOOD_RESULTS',status='confirmed',conclusion_ko='가격 하락이 완결된 호실적 공시보다 먼저였고, 고점 후에도 강한 실적 발표가 이어졌다는 공개일 순서는 확인된다.',evidence_ids=['ICBC_01','CNQ3_01','ANNUAL_01','ANNUAL_02'],
      limits_ko='공개일 순서의 사후 확인이다. 경제활동 기간의 순서, 최초로 알려진 기대, 실적 악화의 첫 순간 또는 가격의 예측력을 입증하지 않는다.'),
 dict(signal_id='PRICE_BEFORE_REALIZED_DETERIORATION',status='partial',conclusion_ko='연간 순익 감소가 확정되기 전에 가격이 하락했다. 다만 2007Q3부터 성장 모멘텀 둔화 경고가 있었고 2008Q1도 표본별로 양의 성장·일부 비금융 감소가 공존했다.',evidence_ids=['CNQ3_02','Q108_01','Q108_04','ACTUAL08_01'],
      limits_ko='같은 지수/고정 기업의 분기 EPS 시계열이 없어 정확한 실적 정점과 하락 선행 개월 수는 미확인이다.'),
 dict(signal_id='DOCUMENTED_REVISIONS_AFTER_PRICE_PEAK',status='partial',conclusion_ko='고점 뒤 1월 21일 하향 관측의 공개 증거와 5월 7일 중금의 정량 성장 전망 하향 설명이 있다.',evidence_ids=['REVISION_01','REVISION_02'],
      limits_ko='특정 하향이 고점 후 보도됐다는 뜻이며, 시장 전체 최초 하향이 고점 후였음을 뜻하지 않는다.'),
 dict(signal_id='PRICE_BEFORE_FIRST_SAME_PROVIDER_2008_EPS_DOWNGRADE',status='unverified',conclusion_ko='가격이 동일 제공자·고정 유니버스 2008년 예상 EPS의 최초 하향보다 먼저였다는 명제는 미확인이다.',evidence_ids=['REVISION_01','REVISION_02'],
      matched_eps_level_series=None,first_downgrade_date=None,lead_trading_sessions=None,
      limits_ko='이익 성장률 그림/기관 성장률 전망을 EPS 수준 시계열로 대체하지 않는다. 최초 하향일·빈티지·분모·유니버스 미확인.'),
 dict(signal_id='POST_PEAK_OPTIMISM_PERSISTED',status='confirmed',conclusion_ko='일부 기관의 낙관적 양의 이익 전망은 고점 뒤에도 남았다.',evidence_ids=['OPTIMISM_01','OPTIMISM_02','OPTIMISM_03'],
      limits_ko='일부 기관의 낙관은 컨센서스 불변이나 이익 전망 무하향의 증거가 아니다.'),
 dict(signal_id='EARNINGS_QUALITY_PRICE_FEEDBACK',status='partial',conclusion_ko='투자·증권 관련 이익 비중과 뒤이은 감소는 가격과 보고 이익 사이의 피드백 가능성을 뒷받침한다.',evidence_ids=['CNQ3_03','QUALITY_01','QUALITY_02','Q108_02','Q108_03','ACTUAL08_01'],
      limits_ko='가격 하락의 인과효과 크기 미식별. 영업 성장·세제·상품가격·금리·손상차손 등과 분리되지 않는다. 영업현금흐름 전체 붕괴 주장 금지.'),
]

output=dict(schema_version=1,created_at_utc=CREATED,market_as_of='2026-10-16T09:00:00+09:00',
    korean_price_as_of='2026-10-15',study_kind='retrospective_timing_sequence_not_forecast',
    probability_outputs=None,causal_effect_estimates=None,original_vintage_authenticated=False,
    upstream_price_input=dict(path=str(PRICE_FILE.relative_to(STUDY)).replace('\\','/'),sha256=hashlib.sha256(PRICE_FILE.read_bytes()).hexdigest(),
        index_id='sse_composite',origin='Official SSE yearbook daily numeric tables; observed-peak designation is hindsight.'),
    unit_contract='All stored percentage/rate normalizations use explicit fractions; percentage-point differences use fraction_points. Currency retains original scale and explicit CNY conversions. EPS levels are CNY_per_share, never percentages.',
    chronology_rules=['Observation period end, individual filing availability and aggregate-summary publication are different timestamps.',
        'A good YoY result can coexist with slower momentum and forecast reductions.',
        'Same-day historical close is context, not evidence that release preceded the close.',
        'Date-stamped public historical documents are retrieved now; independent original-vintage authentication was not performed.',
        'SSE / SZSE mainboard / CSI300 / CICC covered sample / early reporters must remain distinct.'],
    signals=signals,evidence=rows,timeline=timeline,
    unresolved_gaps=['Same-provider fixed-universe 2008 EPS level revision series spanning before and after October 16 2007.',
        'Earliest 2008 earnings downgrade date and exact intraday availability.',
        'Original contemporaneously archived bytes authenticated against a historical capture.',
        'Fixed-constituent quarterly index EPS and cash operating earnings sequence.',
        'Exact chart numerical vintages: low-resolution 2008-01-21 graph is qualitative only.'])
(ROOT/'evidence.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')

fields=['date','event_id','event_kind','summary_ko','observation_period','source_id','source_url','availability_note','price_date','sse_composite_close','drawdown_fraction','sessions_after_peak','original_vintage_authenticated']
with (ROOT/'timeline.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fields);w.writeheader()
    for r in timeline:
        c=r['price_context'] or {}
        w.writerow({k:r.get(k) for k in fields if k not in ['price_date','sse_composite_close','drawdown_fraction','sessions_after_peak']}|
            dict(price_date=c.get('price_date'),sse_composite_close=c.get('close'),drawdown_fraction=c.get('drawdown_from_observed_peak_fraction'),sessions_after_peak=c.get('sessions_after_observed_peak')))

md=['# 중국 실적·이익 전망과 가격의 시간 순서','',
    '가격은 기존 분석과 동일하게 2026년 10월 16일 09:00 KST / 코스피 10월 15일 종가를 유지한다. 이 파일은 중국의 과거 기록을 지금 모은 사후 연구이며, 당시 원빈티지를 인증한 예측 자료가 아니다.','',
    '| 판정 대상 | 결과 | 해석 |','|---|---|---|']
for s in signals:md.append(f"| {s['signal_id']} | {s['status']} | {s['conclusion_ko']} {s['limits_ko']} |")
md += ['', '가격은 상하이종합 **종가** 2007-10-16 6092.06을 관측 고점으로 한다. 장중 6124.04, A주 지수와 혼용하지 않는다. 아래 종가는 공개일 당일 또는 직전 거래일의 사후 맥락이며 당일 공개 시각 선후를 입증하지 않는다.','',
    '| 사건/공개일 | 관측기간 | 기록 | 같은 날/직전 종가; 고점 대비 | 출처 |','|---|---|---|---|---|']
for r in timeline:
    c=r['price_context']; price='—' if c is None else f"{c['price_date']} {c['close']:.2f}; {c['drawdown_from_observed_peak_fraction']:.2%}"
    url=r['source_url'];source=r['source_id'] if not url else f"[{r['source_id']}]({url})"
    md.append(f"| {r['date']} | {r['observation_period']} | {r['summary_ko']} | {price} | {source} |")
md += ['', '주의사항:', '',
    '- 1~9월 누계 순익 성장률, 단일분기 성장 모멘텀, 연간 이익, 예상 성장률과 EPS 수준은 별개다. 2007Q3 자료의 모호한 환비 문장으로 분기 순익 감소율을 만들지 않았다.',
    '- SSE 투자수익 1,651억 위안의 23.25% 분모는 세전 이익이다. 증권투자·처분이익·공정가치변동·비경상손익을 같은 항목으로 묶지 않는다.',
    '- 2008-01-21 그래프는 2007/2008 **순익 성장 예상치**이다. 가장 큰 계단 하락은 2007년 선이다. 2008년 선의 작은 하향을 정밀 수치·최초 하향 날짜로 디지털화하지 않았다.',
    '- 중금의 31.6%→25.3%는 성장률 차이 6.3%p이다. EPS가 6.3% 하향됐다는 뜻이 아니다. 옛 전망 날짜와 동일 분모가 없어 EPS 수준 하향률을 산출하지 않았다.',
    '- 2008년 영업현금 유입 전체는 CSRC 집계상 증가했다. 보고 이익 부진을 곧바로 현금 영업 붕괴로 바꿔 해석하지 않는다.',
    '- 2009년 결산 결과는 2007년이나 2008년 초에 알려졌던 정보가 아니다. 주가와 이익의 동행/피드백은 인과효과 크기를 식별하지 않는다.',
    '', '세부 수치·원 단위·정규화 단위·자료 범위·공개일·원문 SHA는 evidence.json과 source_manifest.json에 남겼다. 유료/인증 데이터베이스나 실시간 증권 API를 사용하지 않았다.']
(ROOT/'timeline.md').write_text('\n'.join(md)+'\n',encoding='utf-8')
print('evidence',len(rows),'timeline',len(timeline),'signals',len(signals))
