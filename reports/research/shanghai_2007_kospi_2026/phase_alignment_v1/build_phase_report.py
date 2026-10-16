"""Korean phase-alignment follow-up; preserves the original calendar study."""
import base64
import json
from pathlib import Path
import re
import markdown

ROOT=Path(__file__).resolve().parent


def table(headers,rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+
                     ['| '+' | '.join(str(x) for x in row)+' |' for row in rows])


def pct(x,d=2):return f'{x:+.{d}%}'


def main():
    a=json.loads((ROOT/'prices/phase_analysis.json').read_text(encoding='utf-8'))
    s=json.loads((ROOT/'phase_support.json').read_text(encoding='utf-8'))
    review=json.loads((ROOT/'review/initial_review_metrics.json').read_text(encoding='utf-8'))
    seq={x['label']:x for x in review['anchor_sequences']}
    k=seq['KOREA_OBSERVED_CURRENT'];early=seq['CN_EARLY_POST_PEAK'];bull=seq['CN_MID_RALLY_2007'];deep=seq['CN_DEEP_BEAR_2008']
    labels=[('SSE_COMPOSITE','상해종합'),('KOSPI','코스피')]
    rise_table=table(['국면 기준','상해종합','코스피'],[
        ['확보 기간 내 상승 시작 종가',f"{a['anchors']['SSE_COMPOSITE']['rise_start_date']} · 1,011.50",f"{a['anchors']['KOSPI']['rise_start_date']} · 2,293.70"],
        ['관측 종가 고점','2007-10-16 · 6,092.06','2026-06-22 · 9,114.55'],
        ['상승 시작부터 고점까지',f"{a['anchors']['SSE_COMPOSITE']['rise_sessions']}거래일 · {pct(a['anchors']['SSE_COMPOSITE']['rise_return_fraction'])}",f"{a['anchors']['KOSPI']['rise_sessions']}거래일 · {pct(a['anchors']['KOSPI']['rise_return_fraction'])}"],
        ['중간 조정 시작 → 최저점','2007-05-29 → 07-05','2026-02-26 → 03-31'],
        ['중간 조정 낙폭',pct(a['prepeak_excursions']['SSE_COMPOSITE']['largest_completed']['drawdown_fraction']),pct(a['prepeak_excursions']['KOSPI']['largest_completed']['drawdown_fraction'])],
        ['조정 전 고점 첫 회복','2007-07-26 · 조정 시작 후 42거래일','2026-04-21 · 조정 시작 후 37거래일']])
    dimensions=table(['고점 뒤 첫 반등과 재이탈','현재 코스피','상해 2007년 말~2008년 초','상해 2008년 4~6월'],[
        ['첫 저점 또는 지정 저점',k['first_or_designated_trough']['date'],early['first_or_designated_trough']['date'],deep['first_or_designated_trough']['date']],
        ['그 저점의 종전 고점 대비 낙폭',pct(k['trough_drawdown_from_peak_fraction']),pct(early['trough_drawdown_from_peak_fraction']),pct(deep['trough_drawdown_from_peak_fraction'])],
        ['저점 → 반등 고점',pct(k['rebound_return_from_trough_fraction']),pct(early['rebound_return_from_trough_fraction']),pct(deep['rebound_return_from_trough_fraction'])],
        ['직전 하락분을 되찾은 비율',f"{k['recovered_lost_peak_to_trough_points_fraction']:.2%}",f"{early['recovered_lost_peak_to_trough_points_fraction']:.2%}",f"{deep['recovered_lost_peak_to_trough_points_fraction']:.2%}"],
        ['저점 → 반등 고점 소요',f"{k['sessions_trough_to_rebound']}거래일",f"{early['sessions_trough_to_rebound']}거래일",f"{deep['sessions_trough_to_rebound']}거래일"],
        ['반등 뒤 전저점 첫 이탈',k['first_close_below_designated_trough_after_rebound']['date'],early['first_close_below_designated_trough_after_rebound']['date'],deep['first_close_below_designated_trough_after_rebound']['date']],
        ['기준 고점 → 첫 재이탈 소요',f"{k['sessions_peak_to_first_breach']}거래일",f"{early['sessions_peak_to_first_breach']}거래일",f"{deep['sessions_peak_to_first_breach']}거래일"],
        ['재이탈 당시 고점 대비 낙폭',pct(k['breach_drawdown_from_peak_fraction']),pct(early['breach_drawdown_from_peak_fraction']),pct(deep['breach_drawdown_from_peak_fraction'])]])
    counts=table(['전환 확인 문턱','엄격 조건 일치','기본 조건 일치','느슨한 조건 일치'],
                 [[t+'%',*[len(a['by_threshold'][f'{float(t)/100:.2f}']['historical']['SSE_COMPOSITE']['extended_shape']['tolerance_intersection_dates'][mode]) for mode in ['strict','base','loose']]] for t in ['10','15','20']])
    hist_table=table(['상해 비교일과 선택 이유','그 뒤 126거래일 수익','기간 중 최대 상승','기간 중 최대낙폭'],
        [[c['date']+' '+c['label_ko'],pct(c['end_126_return_fraction']),pct(c['best_origin_return_fraction']),pct(c['future_max_drawdown_fraction'])] for c in s['contrasting_historical_cases']])
    levels=table(['현재 관찰 기준','지수 수준','현재 종가 대비 필요한 상승','의미'],
        [[{'prior_trough':'7월 전저점','last_pre_break_close':'급락 직전 10월 14일 종가','sma_20':'20일 단순평균','sma_60':'60일 단순평균','observed_rebound_high':'9월 반등 고점','observed_peak':'6월 관측 고점'}[x['level']],f"{x['value_index_points']:,.2f}",pct(x['required_return_fraction']),
          '초기 복구 기준' if x['level']=='prior_trough' else ('매일 재계산하는 추세 참고선' if x['level'].startswith('sma') else '이미 관측한 종가 기준점')]
         for name in ['prior_trough','last_pre_break_close','sma_60','sma_20','observed_rebound_high','observed_peak'] for x in s['levels'] if x['level']==name])
    valuation_table=table(['설명용 조합','EPS 변화 가정','PER 변화 가정','가격 변화 산술'],
        [[x['label_ko'],pct(x['eps_change_fraction'],0),pct(x['pe_change_fraction'],0),pct(x['price_return_fraction'],0)] for x in s['valuation_arithmetic']])
    corr=s['postpeak_equal_age_correlation']
    samsung='https://news.samsung.com/global/samsung-electronics-announces-earnings-guidance-for-third-quarter-2026'
    ict='https://www.motir.go.kr/kor/article/ATCL3f49a5a8c/172289/view'
    bok='https://www.bok.or.kr/fileSrc/portal/b50286a27541421da326b1c88ac4bab2/2/467fa8c543c947e9a0a77d153e1912d6.pdf'
    report=f"""# 국면으로 비교한 현재 코스피와 상해의 하락 전환

**현재 코스피는 2007년 상해의 상승 중간 조정보다, 2008년 초의 ‘첫 하락 후 반등 실패와 전저점 재이탈’이라는 가격 단계에 더 가깝다.** 순서와 경과 기간을 우선하면 2008년 1월 하순이 참고 구간이고, 낙폭만 맞추면 3월이다. 큰 반등의 확인 기준을 엄격하게 적용하면 5~6월 사례도 비교 대상이 된다. 따라서 특정 날짜와 완전히 같다는 결론은 성립하지 않는다.

기준은 **2026년 10월 16일 오전 9시 KST**, 가격은 **10월 15일 종가 5,554.22**다. 코스피는 6월 관측 종가 고점에서 39.06% 하락했고, 7월 저점을 0.70% 밑돈 것은 아직 하루 종가다. **가격은 경계해야 할 단계지만, 삼성의 3분기 잠정 이익과 9월 반도체 가격·수출은 여전히 강하다. 향후 126거래일의 분기점은 이익 기대까지 꺾이는지, 소폭 저점 이탈이 회복되는지다.**

이전 보고서의 달력 정렬 상관 0.00089는 달력이 고정된 비교의 결과다. 이를 국면 유사성 전체의 부정으로 사용하지 않는다. 이번 분석은 기존 자료와 보고서를 보존한 별도의 국면 확장 연구다.

## 상승 시작과 중간 조정을 맞추면

![국면별 출발점 정렬](charts/phase_anchors.png)

{rise_table}

중간 조정은 단기 반등 때마다 나누지 않고, **직전 최고 종가 아래에 머물다가 그 종가를 처음 회복할 때까지의 전체 구간**으로 정의했다. 이 구간 안의 최저 종가를 조정 저점으로 삼는다. 중국은 42거래일, 한국은 37거래일이 걸렸고, 양쪽 모두 저점에서 전고점 회복까지 15거래일이었다. 첨부 차트에서 느낀 중간 조정과 재상승의 유사성은 이 비교에서 상당 부분 확인된다.

반면 전체 상승 기간과 상승률은 다르다. 중국은 확보한 2005년 이후 자료, 한국은 2024년 7월 이후 자료에서 관측 고점 이전의 최저 종가를 택했다. 두 시장의 시작점 탐색 범위가 같지 않고, 종가 저점은 장중 저점과도 다르므로 이를 영구적인 상승 사이클의 객관적 시작일이라고 부르지는 않는다.

고점을 0일로 놓고 같은 77거래일을 비교하면, 종가 수준의 Pearson 상관은 **{corr['closing_level_pearson']:.3f}**이고 일별 로그수익률 상관은 **{corr['daily_log_return_pearson']:.3f}**다. 앞의 달력 비교와는 정렬과 수익률 빈도가 달라, 두 수치의 차이를 유사도 개선으로 해석하지 않는다. 큰 굴곡은 비슷해 보여도 일별 움직임이나 이후 수익을 복제하는 근거는 되지 않는다. 가격 수준의 상관은 두 하락 경로의 공통 추세 때문에 높아질 수 있다.

## 현재는 어느 단계에 가장 가까운가

코스피의 관측 순서는 다음과 같다.

**6월 22일 9,114.55 → 7월 30일 5,593.56 → 9월 23일 7,080.92 → 10월 15일 5,554.22.**

첫 하락은 27거래일에 38.63%였고, 반등은 38거래일에 26.59%였다. 이 반등은 앞서 잃었던 지수 포인트의 42.24%를 되찾았다. 이어 12거래일 만에 반등 고점에서 21.56% 하락해 이전 저점을 소폭 밑돌았다. 9,114.55는 현재까지 관측한 최고 종가이며 최종 사이클 고점으로 확정한 것은 아니다.

![반등 실패와 회복력의 비교](charts/phase_sequence.png)

{dimensions}

**가격 단계의 대표 비교는 2008년 1월 하순이다.** 이는 순서와 경과 기간을 우선한 조건부 해석이며, 종합 유사도 순위에서 1위를 확인했다는 뜻은 아니다. 상해도 첫 하락과 31거래일의 반등 뒤, 기준 고점에서 68거래일째 전저점을 다시 이탈했다. 한국의 77거래일과 순서·경과가 비교적 가깝고, 손실 회복률도 중국 53.89%, 한국 42.24%다. 그러나 중국 당시 낙폭은 25.15%여서 현재 한국의 39.06%보다 훨씬 얕았다. 한국은 더 깊게 떨어졌다가 더 큰 비율로 반등했으므로 같은 단계의 단순 복사본은 아니다.

낙폭 39.06%를 처음 하회한 중국 날짜는 **2008년 3월 18일**이다. 그날 실제 낙폭은 39.78%였다. 다만 이는 깊이만 맞춘 날짜다. 그때 중국은 첫 반등 고점에서 이미 더 오랫동안 하락 중이었으며, 4~5월의 큰 반등도 아직 나오기 전이다. 현재 한국을 3월 18일에 고정하면 지나온 반등의 순서와 시간 정보를 놓친다.

한편 15~20% 이상 반등을 별도 단계로 요구하면, 중국의 초기 반등 14.46%는 기준을 충족하지 못한다. 대신 2008년 4월 저점 이후 5월의 21.53% 반등과 그 뒤 저점 재이탈이 눈에 들어온다. 그러나 그때 중국은 고점에서 약 50% 하락했고 경과 시간도 훨씬 길었다. 6월 10일 재이탈은 20% 하락 전환의 확인일과도 같지 않다. **국면을 나누는 기준에 따라 비교 날짜가 달라진다는 점 자체가 핵심 한계다.**

### 모든 조건을 만족하는 동일 단계가 있는가

각 역사 날짜까지 실제로 관측할 수 있었던 가격만 사용해 낙폭, 고점 경과 거래일, 지나온 반등률·손실 회복률·기간, 반등 고점 이후 하락률, 전저점 이탈 여부를 비교했다. 임의의 가중치를 합친 유사도 점수는 만들지 않았다.

{counts}

엄격 조건은 낙폭 차이 2.5%p·기간 10거래일·다른 비율 5%p, 기본은 5%p·21거래일·10%p, 느슨한 조건은 10%p·42거래일·20%p 이내다. 전저점 이탈·신저점·방향 상태도 같아야 한다. 기준들은 검증된 시장 법칙이 아닌 연구 선택이며 사전 등록된 예측 규칙이 아니다. 10% 전환과 느슨한 조건에서만 2008년 2월 1일~4월 1일 사이 일부 날짜가 남는다. 이 12개 날짜는 서로 겹치는 **하나의 중국 하락 경로**이며 독립 표본이나 붕괴 확률의 분모가 아니다.

이 검색은 중국의 2007년 10월 관측 고점 이후에 한정된 조건부 비교다. 그 자체로 한국의 6월 고점이 최종 고점임을 입증할 수 없다. 같은 이유로 아래의 상승 중간 반례를 함께 봐야 한다.

## 전저점 재이탈 후에도 회복했던 반례

2007년 상해는 **5월 29일 4,334.92 → 6월 4일 3,670.40 → 6월 19일 4,269.52 → 7월 5일 3,615.87**로 움직였다. 첫 반등 뒤 전저점을 1.49% 밑돌았지만 7월 26일 전고점을 회복했다. 이탈 당시 모습 하나만으로 이후 폭락을 확정하는 주장은 이 반례를 설명하지 못한다.

회복력에는 차이가 있었다. 이 중국 반등은 앞선 하락분의 **90.16%**를 되찾았지만, 현재 코스피 반등은 **42.24%** 회복에 그쳤다. 전체 중간 조정 낙폭도 상해 16.59%, 당시 코스피 19.89%였던 데 비해, 현재 한국은 39.06%다. 따라서 현재 가격 증거는 과거의 얕은 중간 조정 반복보다 하락 전환 쪽을 더 경계하게 한다. 그럼에도 소폭 저점 이탈 하루로 회복 가능성을 닫을 근거는 없다.

{hist_table}

기간 중 최대 상승은 비교일 종가 대비 최고값이고, 최대낙폭은 그 뒤 새로 형성된 고점에서의 하락도 포함한다. 출발 종가도 경로에 포함했다. 예를 들어 2007년 7월 사례는 6개월 수익이 약 49%였어도 그 과정의 최대낙폭은 21.15%였다. **이 표는 결과가 다른 사례를 일부러 나란히 놓은 사후 진단**이며 한국의 목표 수익률·확률·상한·하한이 아니다. 세계 금융위기가 진행된 2008년의 외부 충격도 포함된다.

## 실적과 금융 여건은 가격만큼 악화됐는가

현재 공개된 숫자는 실적이 이미 붕괴했다는 해석을 지지하지 않는다.

- 삼성전자는 10월 8일 3분기 영업이익 잠정치를 **107.4조원**으로 제시했다. 2분기 회사 공시값 약 89.49조원 대비 약 **20.0% 증가**다. 아직 최종 확정 실적이 아니며 2027년 이익 전망의 상향을 뜻하지도 않는다. [삼성전자 발표]({samsung})
- 산업부의 10월 14일 자료에서 9월 반도체 수출은 **603.3억 달러**, 전년 동월 대비 **262.8% 증가**였다. DDR5 16Gb 고정가격은 6월 40달러에서 9월 **48달러**, NAND 128Gb는 28.8달러에서 **30.6달러**로 올랐다. 이 범용 제품 가격을 HBM 가격이나 주문 잔고로 대체할 수는 없다. [산업부 ICT 수출입]({ict})
- 한국은행 10월 15일 자료의 10월 14일 CP금리는 **3.66%**로 8월 말보다 41bp 높았다. 그러나 AA- 3년 회사채와 국고채의 스프레드는 **68bp**로 같은 비교에서 확대되지 않았다. 조달 부담 증가는 관측되지만, 광범위한 신용위기가 확인됐다는 뜻은 아니다. 당국은 10월 주가 하락 배경으로 AI 투자 둔화·반도체 경쟁 심화에 대한 우려를 설명했다. [한국은행 금융시장 동향]({bok})

따라서 현 단계의 설명은 **‘좋았던 현재 실적에도 시장이 미래 지속성과 위험 프리미엄을 다시 평가하는 과정’이라는 가설**에 가깝다. 같은 제공자의 고정된 2027년 EPS 전망 시계열을 확보하지 못했으므로 실제 추정치 하향 폭을 숫자로 단정할 수는 없다.

좋은 현재 실적만으로 바닥이 확인되는 것도 아니다. 중국의 2007년 양호한 연간 실적은 2008년 하락 중 사후 발표됐다. 가격은 후행 실적보다 먼저 이익 사이클과 금융 여건을 반영할 수 있다. 이번에도 **높은 전년비 성장률**보다 **동일 기간의 예상 이익 수준이 계속 유지되는지**가 더 중요한 관찰 대상이다.

## 향후 126거래일의 구체적인 분기점

아래 5거래일·10%·2개월 같은 문턱은 관찰을 명확히 하기 위한 **미검증 연구 기준**이다. 적중률을 검증한 매매 규칙이나 확률 모델이 아니며, 자료가 없는 항목은 통과나 실패로 간주하지 않는다.

### 가격은 초기 복구와 추세 회복을 나눠 본다

{levels}

**초기 복구:** 5,593.56을 다시 넘고 5거래일 연속 종가로 지지하는지 본다. 현재는 그 아래 종가가 하루이며 복구도 지속 이탈도 아직 이 연구 기준을 충족하지 않았다. 10월 14일 종가 6,008.81 회복은 이번 급락 구간의 되돌림을 보여주지만 전체 하락 추세의 종료를 의미하지 않는다.

**추세 회복:** 매일 다시 계산하는 20·60일 평균 위에서 10거래일 정도 유지하고, 이후 9월 반등 고점 7,080.92를 회복하는지 본다. 현재의 평균선은 약 6,654~6,684다. 이 숫자를 미래의 고정 저항선으로 쓰지는 않는다. 두 반도체 기업만의 반등보다 종목 전반의 참여가 동반되는지 확인해야 한다. 종목별 확산 자료는 아직 미확보다.

**추가 하락 확인:** 이전 저점 아래 종가가 5거래일 지속되고 반등 고점과 저점이 계속 낮아지면서, 아래의 이익 전망·가격·신용 조건도 악화되면 첫 반등 실패가 더 긴 하락으로 이어진다는 가설이 강해진다. 현재 대비 추가 20% 손실선은 **{s['additional_20pct_loss_threshold_index_points']:,.2f}**지만, 이는 손실 사건을 정의한 산술 값이지 목표가나 바닥 추정치가 아니다.

### 실적과 주문은 다음 정보를 확인한다

| 관찰 항목 | 추가 하락 가설을 강화하는 변화 | 회복 가설을 강화하는 변화 | 현재 확인 상태 |
| --- | --- | --- | --- |
| 같은 2027년 예상 이익 수준 | 동일 공급자·구성의 FY2027 EPS가 4주 동안 10% 이상 낮아지고 2회 주간 관측에서 유지 | 같은 수준이 추가 하향되지 않고 새 확정 실적이 잠정 범위를 지지 | 공통 전망 시계열 미확보로 판정 보류 |
| 메모리 가격과 HBM 주문 | 동일 규격 고정가격이 2개월 연속 하락하고 9월 대비 10% 이상 하락하며, 공식 주문·출하 계획 하향도 동반 | 가격이 유지되고 고객 투자·HBM 출하·계약 계획이 새 발표에서 유지 | 9월 가격은 강함. 최신 미래 주문 잔고는 미계량 |
| 수출과 현금 전환 | 조업일 보정 수출의 3개월 추세가 약해지고, 재고 증가·현금 회수 악화가 동반 | 물량과 현금 회수가 이익을 지지하고 재고가 악화하지 않음 | 명목 9월 수출은 최고치. 보정 수출·최신 분기 현금흐름 판정은 불완전 |

10% 가격 하락의 설명용 기준은 DDR5 **43.2달러**, NAND **27.54달러**다. 한 제품의 하락만으로 AI 수요 전체가 무너졌다고 판단하지 않는다. 큰 이익 증가율이 남아 있어도 내년 예상 이익 수준이 내려가면 주가에는 부담이 될 수 있고, 성장률이 둔화해도 이익 수준이 유지된다면 회복 여지가 남는다.

다음 실적 설명 기회는 회사 공시상 SK하이닉스 **10월 28일**, 삼성전자 **10월 29일**이다. 삼성 3분기 최종 실적과 반도체 부문 이익·현금흐름, 양사의 이후 분기 계획을 우선 확인한다. 조회한 일정의 원래 게시 시각은 완전히 인증하지 못했으므로 일정은 현재 조회 참고이며 이미 발표된 실적으로 취급하지 않는다. 다음 연초 분기 실적의 정확한 날짜는 확정하지 않았다. [SK하이닉스 SEC 공시](https://www.sec.gov/Archives/edgar/data/2120882/000119312526420934/d413172d6k.htm), [삼성 IR 일정](https://www.samsung.com/global/ir/?keeplink=true)

### 수급과 신용은 강제 청산과 정상 상환을 구분한다

신용잔액이 줄었다는 사실만으로 추가 폭락이나 건전한 정리를 판정하지 않는다. **가격 신저점·신용 축소·실제 반대매매 급증이 함께 나타나는지** 확인해야 한다. 연구용 경보는 20거래일 신용 10% 감소와 함께, 비교 가능한 반대매매 통계가 직전 60거래일 중앙값의 2배를 5일 중 3일 이상 기록하는 조합이다. 해당 일별 시계열은 미확보이므로 현재 이미 강제 청산 국면이라고 확정하지 않았다.

회복 쪽 증거는 가격이 전저점을 되찾는 가운데 반대매매가 진정되고 예탁금·신용 비율이 안정되는 것이다. 단순한 신용 재확대가 반등을 이끄는 경우는 복원력 개선과 구분한다. 일부 반대매매 통계가 미수금만 포함할 수 있어 신용융자 담보 처분과 동일 지표로 합치지도 않는다.

주식 밖의 신용 악화도 구분해 본다. 10월 14일 대비 CP금리 50bp 상승과 AA- 스프레드 30bp 확대가 함께 5거래일 유지되는 경우를 연구용 확산 경보로 둔다. 현재 기준으로 각각 약 **4.16%와 98bp**에 해당한다. 반대로 CP가 3.66% 이하, 스프레드가 68bp 이하로 안정되는 흐름은 조달 여건 회복의 근거다. 이 기준은 원문이 제시한 예측 문턱이 아니라 본 연구의 관찰 가정이다.

### 6개월은 세 구간으로 나눠 판단한다

1. **향후 2~4주:** 전저점 복구·지속 이탈 여부와 10월 말 실적 설명을 확인한다. 하루 반등이나 한 번의 좋은 잠정 실적만으로 방향을 확정하지 않는다.
2. **다음 1~3개월:** 고정된 내년 이익 전망, 월별 같은 규격 메모리 가격, 주문·출하 계획과 차입 청산이 함께 안정되는지 본다.
3. **다음 3~6개월:** 추정 이익을 실제 현금과 재고·출하가 뒷받침하는지 확인한다. 이익은 유지되는데 가격·신용이 안정되면 회복 경로, 이익 하향과 평가배수 축소가 겹치면 추가 하락 경로가 더 설득력 있다.

{valuation_table}

위 표는 동일 지수·동일 예상 기간의 EPS와 PER를 가정한 `(1+EPS변화)×(1+PER변화)-1` 산술이다. 삼성의 영업이익 증가율을 지수 EPS에 대입하지 않았다. 특히 이익이 20% 늘어도 PER가 20% 줄면 가격은 4% 하락한다. 좋은 이익과 약한 주가가 동시에 나타날 수 있는 이유이며, 각 행은 6개월 예측값이 아니다.

## 방법과 재현 범위

국면의 확인은 10·15·20% 전환을 별도로 계산하며, 저점·고점이 실제로 나타난 날과 반전 폭으로 확인된 날을 구분한다. 역사 날짜별 특징은 그 날짜까지의 가격만 사용한다. 다만 전체 상승 시작과 관측 최고점 앵커는 사후 기술이며, 이전 연구에서 이미 2008년 결과를 살펴봤기 때문에 독립적인 미열람 검증이라고 주장하지 않는다.

중국 2007~2008년 가격은 기존 공식 SSE 정본을 유지했다. 126거래일 결과가 연말에서 잘리지 않도록 2009년 공개 과거가격을 별도 폴더에 추가하고, 2008년 겹치는 공식 종가와 교차검증했다. 2009년 자료는 역사 사례의 사후 결과에만 사용하며 현재 한국 특징이나 후보 선정에 사용하지 않는다. 상해 A주를 바꿔 넣은 민감도도 별도로 보존했다.

최신 재무·산업 자료는 기준 시점 전에 발표된 날짜를 확인한 공개 원문을 현재 회고 수집했다. 수집 시각·공개일·관측일·원문 해시를 분리해 보존했지만, 원래 발표 당시 보관본의 빈티지까지 모두 인증한 것은 아니다. 이를 엄격한 과거 시점 예측 검증이나 공식 모델 입력의 적격성 인증으로 사용하지 않는다.

`prices/phase_analysis.json`과 후보 CSV는 전체 후보·각 지표의 차이·조건별 일치·사후 결과를 보존한다. `fundamentals/evidence.json`과 `fundamentals/condition_matrix.json`은 최신 원문과 7개 관찰 축의 기준·미확보 상태를 기록한다. `phase_support.json`은 가격 기준점·관측 일수·대조 사례와 설명용 산술을 담는다. 독립 재계산과 확인 시점 검증은 `review/` 및 `validation.json`에 있다.

이전 보고서와 공식 전망·확률·원장·모델을 수정하지 않았다. 이번 판단은 **현재 가격 구조가 초기 하락 전환에 더 가까워 경계하되, 양호한 실적과 소폭 저점 이탈의 회복 여부를 통해 그 가설을 계속 반증할 수 있어야 한다**는 조건부 연구 결론이다.
"""
    (ROOT/'report.md').write_text(report,encoding='utf-8')
    body=markdown.markdown(report,extensions=['tables','fenced_code','toc'])
    def inline(m):return 'src="data:image/png;base64,'+base64.b64encode((ROOT/m.group(1)).read_bytes()).decode()+'"'
    body=re.sub(r'src="(charts/[^"]+\.png)"',inline,body)
    body=re.sub(r'(<table>.*?</table>)',r'<div class="table-wrap">\1</div>',body,flags=re.S)
    css="""*{box-sizing:border-box}html{background:#f6f5f1;color:#202b36}body{margin:0;font-family:'Malgun Gothic','Segoe UI',sans-serif;font-size:16px;line-height:1.87}main{max-width:1080px;margin:auto;padding:56px 48px 90px;background:white}h1{font-size:35px;color:#173d61;line-height:1.5;margin:0 0 28px}h2{font-size:25px;margin:56px 0 22px;padding-top:22px;border-top:2px solid #cbd7df;line-height:1.5}h3{font-size:20px;margin:34px 0 16px;color:#214e71}p{margin:0 0 20px}a{color:#1269a5;overflow-wrap:anywhere}img{width:100%;height:auto;display:block;margin:28px auto 36px}.table-wrap{overflow-x:auto;margin:24px 0}table{width:100%;border-collapse:collapse;font-size:14px;line-height:1.75}td,th{padding:12px;min-width:105px;border-bottom:1px solid #dce3e8;vertical-align:top;text-align:left}th{background:#edf3f6}td:first-child,th:first-child{min-width:155px}code{font-size:.86em;background:#f0f3f5;padding:2px 4px;overflow-wrap:anywhere}li{margin:10px 0}header{font-size:12px;letter-spacing:1.5px;color:#637e90;margin-bottom:24px}@media(max-width:650px){main{padding:28px 20px 65px}body{font-size:15px}h1{font-size:27px}h2{font-size:22px;margin-top:40px}h3{font-size:19px}}@media print{html{background:white}main{padding:0;max-width:none}img,table{break-inside:avoid}h2,h3{break-after:avoid}}"""
    output='<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>국면으로 비교한 코스피와 상해</title><style>'+css+'</style></head><body><main><header>PHASE COMPARISON · 2026 10 16</header>'+body+'</main></body></html>'
    (ROOT/'report.html').write_text(output,encoding='utf-8')
    print(json.dumps({'report_characters':len(report),'html_bytes':len(output.encode())}))


if __name__=='__main__':main()
