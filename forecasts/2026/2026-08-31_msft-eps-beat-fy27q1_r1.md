---
forecast_id: 2026-08-31_msft-eps-beat-fy27q1_r1
question_id: msft-eps-beat-fy27q1
question_snapshot: "Microsoft가 2026-10-28(장후 추정) 발표하는 FY2027 Q1 실적에서 EPS가 발표 직전 컨센서스를 상회할 확률은?"
timestamp: 2026-08-31 16:40 KST
phase: P1
model: claude-opus-5 (Claude Code)
prompt_version: reasoning_core_v1
probability: 87
ci80: [77, 93]
window_end: null
snapshots:
  consensus_eps: "$4.71 (Investing.com·TipRanks 일치, 범위 $4.43~4.83, 채취 2026-08-31 KST) — 판정 기준. AlphaQuery $4.67은 약간 시차 있는 평균"
  consensus_revenue: "$90.59B (Investing.com) — 회사 가이던스 $89.85~90.95B 범위 안"
  company_guidance: "매출 $89.85~90.95B(+16~17%), Azure 약 +45% cc, COGS $29.6~29.8B, OpEx $16.8~16.9B, 실효세율 약 20%, capex $50B 초과 (2026-07-29 콜). **EPS 가이던스 미제시**"
  report_date: "미확정 — Wall Street Horizon은 2026-10-28 UNCONFIRMED, TipRanks·Investing.com은 10-27 표기"
market_implied: null
edge: null
sources_count: 11
---

## [0] 질문 검증

판정 가능. 컨센서스는 **$4.71**로 고정한다(Investing.com·TipRanks 독립 일치, 제공사 스프레드 약 1%로 4개 메가캡 중 가장 좁다).

발표일은 회사 미확정이다. Wall Street Horizon이 2026-10-28을 UNCONFIRMED로 표기하고 TipRanks·Investing.com은 10-27로 적는다. 질문 마감 10-28과 정합하며 하루 차이는 판정에 영향이 없다.

MSFT는 GAAP과 non-GAAP 차이가 작아(FY26 Q4 GAAP $4.81 / non-GAAP $4.74) Alphabet 같은 기준 오염이 없다 — 4개 메가캡 중 **서프라이즈 시계열이 가장 깨끗하다**.

## [1] Outside View — base rate (anchor: 78%)

S&P 500 EPS 컨센서스 상회율(FactSet Earnings Insight 2026-08-28): **5년 평균 78% · 10년 평균 76% · Q2 2026 86%**(2021년 이후 최고). FactSet은 동률(tie)을 3%로 **별도 집계**하므로 이 수치는 이미 strict inequality 기준이며, 동률=NO인 본 질문에 그대로 쓸 수 있다.

두 가지 주의를 [2]에 반영한다. (1) Q3 2026 부정 가이던스 비율이 **36%**로 5년 평균 58%를 크게 밑돈다 — 워크다운이 약해 **다음 분기 허들이 높아졌다**. (2) 총계 서프라이즈 +26.5%는 Alphabet(지분증권 미실현이익 $98B)·Amazon($53.4B) 회계 아티팩트이며 제외 시 +10.8%, Mag 7은 +66.2%에서 **+4.4%**로 떨어진다.

MSFT 고유 이력: 8분기 **8/8 비트**, 평균 서프라이즈 **+8.2%**, 중앙값 +8.6%, **최소 +3.9%**, 최대 +13.2%.

## [2] Inside View — 보정 (항목별)

| 증거 | 방향 | 조정 |
|---|---|---|
| **8분기 무패에 최소 서프라이즈가 +3.9%** — 컨센서스가 3.9% 이상 틀려야 미스가 난다. 4개 메가캡 중 가장 두꺼운 안전마진 | 상승 | +8%p |
| Azure +45% cc 가이던스 — 클라우드 성장이 여전히 가속 구간. Intelligent Cloud 가이던스 +33~34% | 상승 | +3%p |
| 컨센서스 매출($90.59B)이 가이던스 범위 중앙 — 상단($90.95B) 달성 시 자연스러운 상방 | 상승 | +1%p |
| capex $50B 초과 + 데이터센터 내용연수 15→25년 연장 — 감가상각 인식 방식 변경이 EPS에 미치는 영향이 모델마다 다르게 반영될 수 있어 컨센서스 분산 요인 | 하락 | −2%p |
| 워크다운 약화(부정 가이던스 36%) — 허들 상승 | 하락 | −1%p |
| 메모리 원가 상승이 서버 COGS를 밀어올리는 국면 — 가이던스 COGS +23~24%가 이미 반영하나 초과 리스크 존재 | 하락 | −2%p |

순 조정 **+7%p** → 87%. (anchor 78% + 종목 프리미엄 +2%p + 순조정 +7%p)

## [3] 분해 트리

| 경로 | 확률 | 비트 조건부 | 기여 |
|---|---|---|---|
| Azure 가이던스(+45% cc) 부합·초과 | 0.75 | 0.95 | 71% |
| Azure 소폭 미달하나 마진·세율이 상쇄 | 0.20 | 0.70 | 14% |
| Azure 유의 미달 또는 일회성 비용 | 0.05 | 0.35 | 2% |
| 합계 | | | **87%** |

## [4] Premortem — 틀릴 이유 3가지

1. **회계 변경이 예상 밖으로 작용하는 경우.** 데이터센터 내용연수 연장과 금융리스→운용리스 재분류는 감가상각·영업비용 인식을 동시에 바꾼다. 애널리스트 모델이 이를 균일하게 반영하지 않았다면 컨센서스 분산이 커지고, 실제값이 어느 쪽으로든 크게 벗어날 수 있다.
2. **AI 인프라 원가 급등.** 메모리 계약가가 1Q26 +93~98% QoQ로 폭등한 여파가 서버 COGS에 반영되는 국면이다. NVDA도 같은 이유로 총이익률 가이던스를 75.0%에서 74.0%로 낮췄다. MSFT의 COGS 가이던스가 이를 과소 반영했다면 마진이 훼손된다.
3. **반대 방향 — 87%도 낮은 경우.** 8분기 무패에 최소 서프라이즈 +3.9%다. 8/8을 그대로 믿으면 90% 이상이 맞고, 내가 얹은 하방 조정(회계·원가)은 실제로는 가이던스에 이미 반영돼 있을 수 있다.

## [5] 최종 출력

- 최종 확률: **87%** (80% CI: 77~93%)
- **핵심 근거 3줄**:
  1. 8분기 8/8 비트에 **최소 서프라이즈가 +3.9%** — 컨센서스가 4% 가까이 틀려야 미스가 나는 구조다.
  2. GAAP·non-GAAP 괴리가 작아 4개 메가캡 중 서프라이즈 시계열이 가장 깨끗하고, 제공사 컨센서스 스프레드도 1%로 가장 좁다.
  3. 하방은 AI 인프라 원가와 내용연수 회계 변경의 반영 편차이며, 방향을 뒤집기보다 폭을 줄이는 요인이다.
- **관찰 지표 2개**:
  1. **D-1 컨센서스 재채취** — $4.85 이상으로 상향되면 허들 상승으로 80%까지 하향.
  2. **Azure 성장률 가이던스 갱신** — 분기 중 +45% cc 하향 시사가 나오면 −8%p 이상 하향.

> **P1 참고 의견 — 자금 결정의 단독 근거 아님** (P3 게이트: 해소 50문항+ & Brier < 0.18 통과 전).

## 출처 목록

- Microsoft FY26 Q4 실적 보도자료 (매출 $90.0B, GAAP EPS $4.81 / non-GAAP $4.74) — https://www.microsoft.com/en-us/investor/earnings/fy-2026-q4/press-release-webcast (2026-07-29)
- Microsoft FY27 Q1 가이던스 (콜 트랜스크립트, Amy Hood) — https://www.investing.com/news/transcripts/earnings-call-transcript-microsoft-q4-2026-beats-forecasts-stock-jumps-8-93CH-4822020 (2026-07-29)
- Wall Street Horizon MSFT 실적 캘린더 (2026-10-28 UNCONFIRMED) — https://www.wallstreethorizon.com/microsoft-earnings-calendar
- Investing.com MSFT 실적 (컨센 $4.71, 매출 $90.59B) — https://www.investing.com/equities/microsoft-corp-earnings (채취 2026-08-31)
- TipRanks MSFT 실적 — https://www.tipranks.com/stocks/msft/earnings
- NVIDIA FQ2 2027 (메모리 원가로 총이익률 75.0%→74.0%) — https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-second-quarter-fiscal-2027
- TrendForce DRAM 계약가 QoQ (1Q26 +93~98%) — https://www.trendforce.com/presscenter/news/20260703-13134.html
- FactSet Earnings Insight 2026-08-28 (비트율 86%/78%/76%, 동률 3%, Q3 부정 가이던스 36%, Mag7 ex-2종목 +4.4%) — https://advantage.factset.com/hubfs/Website/Resources%20Section/Research%20Desk/Earnings%20Insight/EarningsInsight_082826.pdf
- Warsh 잭슨홀 연설 2026-08-28 — https://www.federalreserve.gov/newsevents/speech/warsh20260828a.htm

**[미검증]** 표기: 발표일은 회사 미확정(10-27 vs 10-28 제공사 상충). 8분기 서프라이즈 이력의 컨센서스는 MarketBeat·Investing.com·AlphaQuery 3사 교차로 확인했으나 원 벤더(LSEG/FactSet) 직접 확인은 실패.
