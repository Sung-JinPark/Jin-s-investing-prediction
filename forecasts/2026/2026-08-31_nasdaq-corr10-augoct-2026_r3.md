---
forecast_id: 2026-08-31_nasdaq-corr10-augoct-2026_r3
question_id: nasdaq-corr10-augoct-2026
question_snapshot: "2026-08-01~10-31 기간 중 NASDAQ Composite 일간 종가가 24,384.51(= 사이클 ATH 27,093.90 x 0.90) 이하로 마감하는 날이 1일 이상 존재할 확률은?"
timestamp: 2026-08-31 14:20 KST
phase: P1
model: claude-opus-5 (Claude Code)
prompt_version: reasoning_core_v1
probability: 30
ci80: [18, 45]
window_end: null
snapshots:
  threshold: "24,384.51 (= 27,093.90 x 0.90) — r1 확정, 변경 금지"
  current: "26,402.42 (2026-08-28 종가) — 임계까지 −7.64%, ATH 대비 −2.55%"
  august_low_close: "25,913.90 (2026-08-03) — 임계 대비 +6.27%, 8월 중 미터치 확정"
  window_remaining: "9~10월 약 42거래일 (윈도우의 약 62%)"
market_implied: null
edge: null
sources_count: 31
---

## [0] 질문 검증

판정 가능. 임계값 24,384.51은 등록 시점 고정이며 r1·r2에서 승계됐다. 판정은 ^IXIC **일간 종가**가 윈도우(2026-08-01~10-31) 중 1일 이상 이 값 이하로 마감했는지 여부다.

**윈도우 진행 상황 — 이번 회차의 핵심 사실.** 8월은 전부 경과했고 **터치는 발생하지 않았다**. 8월 최저 일간 종가는 25,913.90(2026-08-03)으로 임계 대비 **+6.27%** 위였다(FRED NASDAQCOM 일별 종가, Yahoo·Investing.com 교차 일치).

주의해야 할 근접 사건이 하나 있는데, **판정 대상이 아니다**. 2026-07-29 ^IXIC는 24,442.94로 마감해 임계값 위 **58.43p(0.24%)**까지 접근했고 장중 저가 24,425.34는 장중 ATH 대비 −10.10%였다. 그러나 이 날은 **윈도우 개시(08-01) 이전**이다. r2가 이 근접 사건을 목전에 두고 작성됐다는 점이 r2 확률을 끌어올린 주요 앵커였으므로, 이번 회차에서 명시적으로 분리한다.

## [1] Outside View — base rate (anchor: 20%)

참조군을 **"8월 말 시점에 ATH 근접·저변동성 상태에서, 이후 42거래일 내 ATH −10% 종가 터치"**로 좁힌다. 무조건부 기저율을 쓰면 참조군 오류가 된다.

| 참조군 | 기저율 | n |
|---|---|---|
| 8월말 ATH −4% 이내 | 25.0% | 4/16 |
| 동, + 8월말 VIX < 17 (현 상태) | 14.3% | 1/7 |
| 일별 교차검증: 드로다운 (−4%, 0%], 42거래일 지평 | 14.6% | 시대별 12.8~15.8% |

무조건부 미드텀 기저율은 61.5%(8/13)로 훨씬 높지만 **혼란변수에 오염돼 있다**. 미드텀 "적중" 연도는 대부분 9월을 **이미 깊은 드로다운·고변동성 상태로 진입**한 해다(1974 −54%, 1990 −21.5%/VIX 29, 2002 −74%/VIX 30, 2022 −26%/VIX 23). 출발 상태를 통제하면 효과가 사라진다(ATH 근접 연도 한정 미드텀 2/3 vs 비미드텀 3/16, Fisher p=0.155). r2가 미드텀 계절성을 가산한 것은 **기저율에 이미 포함된 연도를 이중 계상**한 것이다.

결정론 모델 교차확인(무드리프트~+8% 드리프트 GBM, 42거래일, 현재가 26,402.42 → −7.64% 필요):

| 연율변동성 | 드리프트 0% | +5% | +8% |
|---|---|---|---|
| 16.6% (NDX 20일 실현) | 25.0% | 21.6% | 19.7% |
| 20.0% | 34.3% | 31.1% | 29.2% |
| 22.0% (NDX 60일 실현) | 39.1% | 36.0% | 34.2% |

**anchor 20%** — 실증 기저율(14~25%)과 실현변동성 기준 GBM 하단의 교집합.

## [2] Inside View — 보정 (항목별)

| 증거 | 방향 | 조정 |
|---|---|---|
| 9월 FOMC 인상 리스크 — 잭슨홀(08-28) Warsh 매파 발언 후 CME FedWatch 인상 확률 약 36%에서 56%로, 08-30 58%. 인하가 아닌 **인상** 사이클 재개는 기저율 표본에 사실상 없는 조건 | 상승 | +6%p |
| 실현변동성 > 내재변동성 — NDX 20일 실현 16.65% vs VIX 14.43(−2.14p). 옵션시장이 실제 발생한 변동성보다 낮게 가격 | 상승 | +3%p |
| CTA·체계적 전략 취약성 — SPX −3% / NDX −5% 부근에서 1,000억 달러+ 강제매도 트리거(BofA·GS). 저변동성이 레버리지를 키운 상태 | 상승 | +3%p |
| 포지셔닝 과열 — BofA FMS 8월 현금 3.5%(1998년 이후 6번째 최저, 자체 컨트라 매도 룰 4.0% 이하 발동), 주식 net 56% OW(2021-11 이후 최고) | 상승 | +2%p |
| 스태그플레이션 배치 — 7월 NFP **−23,000**(사이클 첫 감소), 근원 PCE 3.3% 정체. 고멀티플 자산에 최악 조합 | 상승 | +2%p |
| 2018 아날로그 — ATH 근접·8월말 VIX 12.77·미드텀이라는 현 setup의 유일한 정합 사례가 9~10월 −13.06% 하락 (n=1) | 상승 | +2%p |
| 시간 소진 — 윈도우의 38%(8월)가 무터치로 경과. r2 시점 68거래일에서 42거래일로 축소 | 하락 | −4%p |
| 거리 확대 — r2 시점 −4.45% 필요에서 현재 **−7.64%** 필요로. 7/29 저점 이후 +8.02% 반등 | 하락 | (anchor에 반영) |
| 실적 모멘텀 — Q2 블렌디드 성장 52.0%(6/30 추정 23.1%), EPS 서프라이즈 86%, Q3 부정 가이던스 36%(5년 평균 58%). NVDA 08-26 매출 962억 달러(+106%)·Q3 가이던스 1,080억 달러 | 하락 | −3%p |
| 금융환경 완화 — 시카고연준 NFCI −0.566(2021-11 이후 최완화), HY OAS 2.63%·IG 0.79%, 2s10s +0.39 정상 | 하락 | −2%p |
| 저변동성 레짐의 실증 — 7월 −9.78% 드로다운에도 VIX 최고 종가 20.66. 이 레짐은 하락을 저변동으로 소화 | 하락 | −1%p |

순 조정 **+10%p** → 30%.

## [3] 분해 트리

터치 경로를 촉매별로 분해한다(9~10월, 상호배타 근사).

| 경로 | 조건부 확률 | 터치 기여 |
|---|---|---|
| 9/15~16 FOMC 인상 단행 + 매파 SEP → 리프라이싱 | P(인상) 0.56 x P(터치·인상) 0.30 | 17% |
| 인상 없으나 9~10월 지표 충격(9/4 NFP·9/11 CPI·10/2·10/14) | 0.30 x 0.20 | 6% |
| AI 자금조달 신뢰 이벤트(부외 약정·CDS 확대·크레딧) | 0.15 x 0.35 | 5% |
| 지정학(호르무즈 재확대) | 0.10 x 0.25 | 2% |
| 합계 | | **30%** |

경로 합이 anchor+보정과 일치한다. 인상 경로가 전체의 절반 이상을 차지하는 것이 이번 회차의 구조적 특징이다 — **이 예측은 사실상 9월 FOMC에 대한 베팅**이다.

**ML 앙상블 대비.** `ml_auto.md`(생성 2026-07-20) F2 앙상블 45%(t5 52% / gbm 39%). 본 예측 30%와 **15%p 괴리**이나, ML 산출은 6주 전 가격(25,508)·잔여 68거래일 기준이며 8월 무터치 경과와 −7.64%로 벌어진 거리를 반영하지 못한다. 동일 모델을 현재 상태로 재실행하면 하향될 것으로 보는 것이 자연스럽다. 괴리는 정보 불일치이지 판단 충돌이 아니다.

## [4] Premortem — 틀릴 이유 3가지

1. **9월 FOMC가 인상하고 시장이 그것을 "정책 실수"로 읽는 경우.** 근원 PCE 3.3%에 고용은 −23,000. 인상 후 성장 지표가 추가로 꺾이면 −7.6%는 며칠이면 소화된다. 2018년 10~12월이 정확히 이 구조였다. 이 경우 30%는 크게 낮다.
2. **거리·시간을 과대평가한 경우.** −7.64%는 이 시장에서 큰 폭이 아니다. 7/22~7/29에 −8%가 6거래일에 발생했다. 8월 무터치를 "안정"으로 읽었지만 8월은 반등 국면이었을 뿐, 하방 분포가 얇아졌다는 증거는 아니다.
3. **반대 방향 — 미드텀 계절성 기각이 과했을 경우.** 순열검정 p=0.131, 1980년 이후 소멸(p=0.270)이라는 통계는 표본이 작아 검정력 자체가 약하다. 효과가 실재하는데 기각한 것이라면 30%는 낮은 쪽으로 틀린다. 다만 이 경우에도 r2의 57%를 정당화하려면 42거래일간 **연율 32~35% 변동성 지속**이 필요한데, 이는 2026년 3월 이란 위기 정점 VIX(31.05)를 상회하는 수준이라 여전히 지지되지 않는다.

## [5] 최종 출력

- 최종 확률: **30%** (80% CI: 18~45%)
- 직전 대비: r2 57% → r3 30% (**−27%p**). 근거는 새 뉴스가 아니라 **상태 변화**다 — (1) 8월 무터치 경과로 윈도우 38% 소진, (2) 필요 낙폭 −4.45%에서 −7.64%로 확대, (3) r2가 앵커로 삼은 7/29 근접 사건이 윈도우 밖 사건임을 확인, (4) 미드텀 계절성 가산이 기저율 이중 계상이었음을 교정.
- **핵심 근거 3줄**:
  1. 8월이 무터치로 끝나 판정은 9~10월 42거래일로 축소됐고, 필요 낙폭은 −7.64%로 벌어졌다.
  2. 참조군을 ATH 근접·저변동성으로 좁힌 실증 기저율은 14~25%이며, 실현변동성 기준 GBM도 20~34%다.
  3. 상방 조정의 대부분은 9월 FOMC 인상 리스크(약 56~58%)이며, 이 예측은 실질적으로 그 이벤트에 대한 베팅이다.
- **관찰 지표 2개**:
  1. **9/15~16 FOMC와 SEP 점도표** — 인상 단행 여부와 2027 경로. 인상+매파 SEP이면 확률을 45~50%로 상향, 동결+비둘기면 15%로 하향.
  2. **^IXIC 25,600 하향 이탈 여부** — 8월 최저 종가(25,913.90) 아래로 종가 이탈 시 CTA 트리거대(−3%/−5%) 진입. 이탈 시 +10%p 이상 상향 필요.

> **P1 참고 의견 — 자금 결정의 단독 근거 아님** (P3 게이트: 해소 50문항+ & Brier < 0.18 통과 전).

## 출처 목록

- FRED NASDAQCOM 일별 종가 (2026년 8월 전 거래일) — https://fred.stlouisfed.org/series/NASDAQCOM (2026-08-28)
- FRED VIXCLS — https://fred.stlouisfed.org/series/VIXCLS (2026-08-28)
- CBOE VIX_History.csv — https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv (2026-08-28)
- FOMC 성명 2026-07-29 (3.50~3.75% 동결, 9-3, 인상 반대 3인) — https://www.federalreserve.gov/newsevents/pressreleases/monetary20260729a.htm
- Warsh 잭슨홀 연설 2026-08-28 — https://www.federalreserve.gov/newsevents/speech/warsh20260828a.htm
- CNBC "September Fed decision now a coin flip as rate hike odds increase" (2026-08-28) — https://www.cnbc.com/2026/08/28/-september-fed-decision-now-a-coin-flip-as-rate-hike-odds-increase.html
- Forbes / Bill Stone, 9월 인상 확률 58% (2026-08-30) — https://www.forbes.com/sites/bill_stone/2026/08/30/fed-rate-hike-odds-rise-after-warshs-jackson-hole-speech/
- BLS 고용상황 2026년 7월 (NFP −23,000, 실업률 4.1%) — https://www.bls.gov/news.release/empsit.nr0.htm (2026-08-07)
- BEA/CNBC 근원 PCE 3.3% (2026-08-26) — https://www.cnbc.com/2026/08/26/feds-preferred-inflation-gauge-shows-core-prices-rose-3point3percent-annually-in-july.html
- BLS CPI 2026년 7월 (헤드라인 3.4% YoY) — https://www.bls.gov/news.release/archives/cpi_08122026.htm (2026-08-12)
- FOMC 일정 (9/15-16, 10/27-28, 12/8-9 — 11월 회의 없음) — https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
- FactSet Earnings Insight 2026-08-28 (Q2 블렌디드 52.0%, 서프라이즈 86%) — https://advantage.factset.com/hubfs/Website/Resources%20Section/Research%20Desk/Earnings%20Insight/EarningsInsight_082826.pdf
- NVIDIA FQ2 2027 실적 (2026-08-26) — https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-second-quarter-fiscal-2027
- FINRA 마진부채 통계 (2026-06 1조 5,020억 달러 사상최고) — https://www.finra.org/sites/default/files/2021-03/margin-statistics.xlsx
- BofA Global Fund Manager Survey 2026년 8월 (현금 3.5%) — https://finance.yahoo.com/markets/articles/investor-bullishness-surges-bofa-survey-141800790.html
- Stage Analysis 시장 폭 2026-08-28 (51.40%) — https://stageanalysis.substack.com/p/market-breadth-moving-averages-124
- Motley Fool "The Nasdaq Just Entered Second Correction of 2026" (2026-07-31) — https://www.fool.com/investing/2026/07/31/the-nasdaq-just-entered-second-correction-of-2026/
- Morgan Stanley 2026 미드텀 선거 시장 영향 — https://www.morganstanley.com/insights/articles/2026-us-midterm-elections-stock-market-impact
- 시카고연준 NFCI −0.566 (2026-08-21 주) — https://www.chicagofed.org/research/data/nfci/current-data
- 저장소 내부: `data/base_rates/ml_auto.md` (2026-07-20 생성, F2 앙상블 45%)
- 저장소 내부: `forecasts/2026/2026-07-20_nasdaq-corr10-augoct-2026_r2.md` (직전 회차 57%)
- 기저율 계산: FRED NASDAQCOM 전체 이력(1971~2026, n=14,009) 직접 집계 — 8월말 앵커 조건부, 재현 가능
- GBM 배리어 계산: 본 회차 자체 산출(무드리프트·드리프트 반영 폐형식), 재현 가능

**[미검증]** 표기: CTA 강제매도 트리거 규모(1,000억 달러+, BofA·GS)는 2차 출처 경유로 원문 미확보. Kalshi 9월 인상 48%는 단일 출처.
