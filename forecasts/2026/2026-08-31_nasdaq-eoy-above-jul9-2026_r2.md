---
forecast_id: 2026-08-31_nasdaq-eoy-above-jul9-2026_r2
question_id: nasdaq-eoy-above-jul9-2026
question_snapshot: "NASDAQ Composite의 2026년 최종 거래일 종가가 26,206.89(2026-07-09 종가)를 초과할 확률은?"
timestamp: 2026-08-31 14:45 KST
phase: P1
model: claude-opus-5 (Claude Code)
prompt_version: reasoning_core_v1
probability: 60
ci80: [45, 73]
window_end: null
snapshots:
  baseline: "26,206.89 (2026-07-09 종가) — r1 확정, 변경 금지"
  current: "26,402.42 (2026-08-28 종가) — 기준 대비 **+0.75%**"
  remaining: "2026-12-31까지 약 85거래일"
market_implied: null
edge: null
sources_count: 26
---

## [0] 질문 검증

판정 가능. 기준 26,206.89은 r1에서 고정됐다. 판정은 **2026년 최종 거래일 종가 1개 값**만으로 이뤄지는 **종점형(terminal)** 질문이며, 중간에 얼마나 오르내렸는지는 무관하다. F1(ATH 터치형)과 구조가 다르다는 점이 이 회차의 핵심 구분이다.

현재 26,402.42로 기준 대비 **+0.75%** 위에 있다. 즉 지금 이 순간의 상태는 "간신히 YES"이며, 남은 85거래일 동안 −0.74% 이상 하락하지 않으면 된다.

## [1] Outside View — base rate (anchor: 55%)

종점형이므로 배리어가 아니라 **종점 분포**를 쓴다. 현재가가 기준을 0.75%만 상회하므로 무드리프트 가정에서는 사실상 동전 던지기에 가깝고, 주식의 장기 양의 드리프트가 얹히는 구조다.

결정론 모델(종점 로그정규, 85거래일, 임계 대비 +0.75%):

| 연율변동성 | 드리프트 0% | +5% |
|---|---|---|
| 16.6% | 51.2% | 58.1% |
| 20.0% | 50.2% | 56.0% |
| 22.0% | 49.8% | 55.0% |

무드리프트에서 약 50%, 연 +5% 드리프트(장기 주식 실질수익률 근사)에서 55~58%. 변동성이 커질수록 로그정규의 비대칭 때문에 확률이 미세하게 낮아지는 것이 특징이다.

역사적 보완: 나스닥의 9~12월 4개월 구간 상승 빈도는 장기적으로 60% 부근이나, 미드텀 연도 4분기 승률은 **62%(8/13)로 비미드텀 73%보다 오히려 낮다**(Welch p=0.687). "미드텀 4분기 +6.6%·승률 86%"는 S&P 통계를 변동성이 훨씬 큰 나스닥에 무보정 적용한 것이므로 사용하지 않는다.

**anchor 55%**.

## [2] Inside View — 보정 (항목별)

| 증거 | 방향 | 조정 |
|---|---|---|
| 현재가가 이미 기준 위(+0.75%) — 유지만 해도 YES | 상승 | (anchor에 반영) |
| 실적·가이던스 모멘텀 — Q2 블렌디드 52.0%, Q3 부정 가이던스 36%(5년 58%), CY2026·CY2027 EPS 12개월 연속 상향 | 상승 | +4%p |
| 하이퍼스케일러 capex 전원 유지·상향, NVDA Q3 가이던스 1,080억 달러 — 지수 상위 가중의 이익 경로가 훼손되지 않음 | 상승 | +3%p |
| 금융환경 완화 + 자사주 블랙아웃 10월 하순 해제(잔여 기간 내) | 상승 | +2%p |
| 미드텀 선거(11/03) 통과 후 불확실성 해소 — 방향보다 **변동성 축소** 효과 | 상승 | +1%p |
| 9월 FOMC 인상 리스크 약 56~58% — 종점형이라 일시 조정은 회복 가능하나, 인상 사이클 재개 시 연말 멀티플이 구조적으로 낮아짐 | 하락 | −3%p |
| 스태그플레이션 배치 — NFP −23,000, 근원 PCE 3.3%. 이익 추정 하향 시작 시 종점에 직접 타격 | 하락 | −2%p |
| 마진 압력 — NVDA 총이익률 가이던스 75.0%에서 74.0%로(메모리 원가). AI 하드웨어 마진 피크 신호 | 하락 | 0%p |

순 조정 **+5%p** → 60%.

## [3] 분해 트리

| 연말 경로 | 확률 | 26,206.89 초과 조건부 | 기여 |
|---|---|---|---|
| ATH 경신 후 연말 유지 (F1 성립, 상단 유지) | 0.62 | 0.90 | 56% |
| ATH 경신했으나 4분기 후반 되돌림으로 기준 하회 | 0.17 | 0.00 | 0% |
| ATH 미경신·기준 부근 횡보 | 0.13 | 0.35 | 5% |
| 하락 전환(−10% 이상, 연말 미회복) | 0.08 | 0.00 | 0% |
| 합계 | | | **61%** ≈ 60% |

F1(ATH 터치 79%)과의 정합: ATH를 터치해도 연말에 기준 아래로 되돌아올 수 있으므로 F3 ≤ F1은 필연이며, 79%에서 60%로의 감쇠는 "터치 후 되돌림" 경로(0.17)가 만든다. 두 값은 정합적이다.

**ML 앙상블 대비.** `ml_auto.md`(2026-07-20) F3 앙상블 55%(bolt 52% / c2 55% / gbm 67%). 본 예측 60%와 5%p 차이로 **수렴**.

## [4] Premortem — 틀릴 이유 3가지

1. **기준선이 너무 가까워 사실상 노이즈에 지배되는 경우.** +0.75%는 이 지수의 하루 표준편차(약 1%) 수준이다. 연말 단 하루의 종가로 판정되므로, 12월 마지막 주의 사소한 수급(세금 손실 매도, 리밸런싱)이 결과를 뒤집을 수 있다. 60%든 55%든 실질 정보량이 크지 않다는 점을 인정한다.
2. **인상 사이클이 실제로 재개되는 경우.** 9월과 12월(12/8~9) 두 차례 인상이 들어오면 연말 멀티플은 구조적으로 낮아진다. 특히 11월 CPI가 12월 FOMC **이후**에 나오므로, 12월 회의는 불완전 정보 하에서 매파적으로 기울 여지가 있다.
3. **반대 방향 — 드리프트를 과소 반영했을 경우.** 4개월 지평에서 주식은 역사적으로 양의 드리프트를 가지며, 자사주 재개와 미드텀 후 계절성이 겹친다. 이 경우 65~70%가 맞고 60%는 낮다.

## [5] 최종 출력

- 최종 확률: **60%** (80% CI: 45~73%)
- 직전 대비: r1 63% → r2 60% (**−3%p**). 지수는 기준 대비 +0.75%로 소폭 유리해졌으나, (1) r1 시점에 없던 **인상 리스크**(9월 약 56~58%)가 생겼고, (2) "미드텀 4분기 승률 86%"라는 r1의 계절성 근거가 S&P 통계의 무보정 전용이었음을 교정해(나스닥 실측 62%, 비미드텀보다 낮음) 상방 가산을 축소했다. 두 효과가 상쇄돼 소폭 하향.
- **핵심 근거 3줄**:
  1. 종점형 질문이고 현재가가 기준을 +0.75%만 상회해, 출발점 자체가 거의 동전 던지기다.
  2. 종점 로그정규 모델은 무드리프트 50%, 연 +5% 드리프트에서 55~58%를 준다.
  3. 이익 모멘텀·capex 유지·자사주 재개가 상방이고, 9월 인상 리스크와 고용 둔화가 하방이며, 순 조정은 +5%p에 그친다.
- **관찰 지표 2개**:
  1. **12월 FOMC(12/8~9) 직전 지수 위치** — 12월 중순 종가가 기준 대비 +3% 이상이면 75%로 상향, −3% 이하면 30%로 하향.
  2. **CY2027 상향 EPS 추정치의 지속 여부(FactSet 월간)** — 12개월 연속 상향 흐름이 꺾이면 −8%p 이상 하향.

> **P1 참고 의견 — 자금 결정의 단독 근거 아님** (P3 게이트: 해소 50문항+ & Brier < 0.18 통과 전).

## 출처 목록

- FRED NASDAQCOM 일별 종가 — https://fred.stlouisfed.org/series/NASDAQCOM (2026-08-28)
- FOMC 성명 2026-07-29 — https://www.federalreserve.gov/newsevents/pressreleases/monetary20260729a.htm
- FOMC 일정 (9/15-16, 10/27-28, 12/8-9) — https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
- Warsh 잭슨홀 연설 2026-08-28 — https://www.federalreserve.gov/newsevents/speech/warsh20260828a.htm
- CNBC 9월 FOMC 인상 확률 (2026-08-28) — https://www.cnbc.com/2026/08/28/-september-fed-decision-now-a-coin-flip-as-rate-hike-odds-increase.html
- FactSet Earnings Insight 2026-08-28 (Q2 52.0%, Q3 부정 가이던스 36%, CY26/CY27 EPS) — https://advantage.factset.com/hubfs/Website/Resources%20Section/Research%20Desk/Earnings%20Insight/EarningsInsight_082826.pdf
- NVIDIA FQ2 2027 실적·Q3 가이던스·총이익률 (2026-08-26) — https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-second-quarter-fiscal-2027
- Alphabet Q2 2026 capex 가이던스 상향 — https://s206.q4cdn.com/479360582/files/doc_news/2026/Jul/22/attachments/2026q2-alphabet-earnings-release.pdf
- Microsoft FY26 Q4 (capex 회계 재분류) — https://www.microsoft.com/en-us/investor/events/fy-2026/earnings-fy-2026-q4
- BLS 고용상황 2026년 7월 (NFP −23,000) — https://www.bls.gov/news.release/empsit.nr0.htm
- CNBC 근원 PCE 3.3% (2026-08-26) — https://www.cnbc.com/2026/08/26/feds-preferred-inflation-gauge-shows-core-prices-rose-3point3percent-annually-in-july.html
- US Inflation Calculator CPI 발표 일정 (11월 CPI가 12월 FOMC 이후) — https://www.usinflationcalculator.com/inflation/consumer-price-index-release-schedule/
- 시카고연준 NFCI — https://www.chicagofed.org/research/data/nfci/current-data
- Morgan Stanley 2026 미드텀 선거 시장 영향 — https://www.morganstanley.com/insights/articles/2026-us-midterm-elections-stock-market-impact
- 저장소 내부: `data/base_rates/ml_auto.md` (F3 앙상블 55%), `forecasts/2026/2026-07-10_nasdaq-eoy-above-jul9-2026_r1.md` (직전 63%)
- 나스닥 미드텀 4분기 승률 실측(8/13, 62%)·Welch p=0.687: FRED NASDAQCOM 이력 직접 집계, 재현 가능
- 종점 로그정규 계산: 본 회차 자체 산출, 재현 가능

**[미검증]** 표기: 자사주 승인 규모(2026년 약 1조 달러, Birinyi 1.55조 달러 추정)는 2차 출처 경유. 미드텀 후 계절성의 통계적 유의성은 순열검정 p=0.131로 **유의하지 않으며**, 본 예측에서 +1%p만 반영했다.
