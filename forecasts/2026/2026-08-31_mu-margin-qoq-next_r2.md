---
forecast_id: 2026-08-31_mu-margin-qoq-next_r2
question_id: mu-margin-qoq-next
question_snapshot: "Micron이 다음 분기 실적 발표에서 보고하는 GAAP 총마진(%)이 직전 분기 대비(QoQ) 하락할 확률은?"
timestamp: 2026-08-31 19:30 KST
phase: P1
model: claude-opus-5 (Claude Code)
prompt_version: reasoning_core_v1
probability: 7
ci80: [3, 14]
window_end: null
snapshots:
  baseline_gaap_gm: "FQ3 FY2026 GAAP 총마진 **84.6%** (매출 $41,456M, GAAP 매출총이익 $35,056M, 2026-06-24 8-K). YES = FQ4 GAAP GM < 84.6%"
  fq4_guidance: "매출 $50.0B ±$1.0B, **GAAP 총마진 약 86% · non-GAAP 약 86%**(회사가 두 기준을 모두 제시). GAAP EPS $30.73±1.00 / non-GAAP $31.00±1.00 (2026-06-24)"
  guidance_precision: "회사는 GAAP/non-GAAP GM 조정을 '— %'로 표기하나 COGS 내 SBC $159M / 매출 $50B = **0.32%p**. 즉 내재적으로 non-GAAP 약 86.0% · GAAP 약 85.7%"
  quarter_end: "FQ4 FY2026은 **14주 분기이며 2026-09-03 종료** (FY2026은 53주). 발표는 2026-09-30 (회사 확정 공지 2026-08-26)"
  guide_beat_history: "최근 3분기 GAAP GM이 가이던스를 **+3.6~+7.4%p** 상회 (FQ1 +5.5 / FQ2 +7.4 / FQ3 +3.6)"
market_implied: null
edge: null
sources_count: 11
---

## [0] 질문 검증

판정 가능. 기준은 **GAAP** 총마진이며 가이던스가 아닌 실제 보고치다. 비교 기준선은 FQ3 FY2026의 **84.6%**다.

r1의 스냅샷 두 가지를 이번 회차에서 정정한다.
- **발표일**: r1은 2026-09-29(TipRanks, `[부분 미검증]`)로 적었으나, Micron이 2026-08-26 보도자료로 **2026-09-30 (수) 14:30 MT**를 확정 공지했다.
- **분기 종료일**: FY2026은 **53주**이고 FQ4는 **14주 분기로 2026-09-03 종료**다(FQ3 10-Q 명시). 오늘 기준 아직 마감되지 않았다.

## [1] Outside View — base rate (anchor: 8%)

이 질문은 방향성 질문이라 일반 기저율보다 **회사 가이던스와 실적 이력**이 지배한다.

GAAP 총마진 추이: FQ2'25 36.8% → FQ3'25 37.7% → FQ4'25 44.7% → FQ1'26 56.0% → FQ2'26 74.4% → FQ3'26 **84.6%**. **6분기 연속 상승**이며 상승폭이 매우 크다.

FQ4 가이던스는 GAAP 약 86%로 **기준선보다 +1.4%p 높다**. 게다가 Micron은 최근 3분기 모두 GAAP GM 가이던스를 **+3.6~+7.4%p 상회**했다. 가이던스를 그대로 믿어도 상승이고, 이력대로면 훨씬 더 상승한다.

하락하려면 가이던스를 **1.4%p 이상 하회**해야 하는데, 최근 3분기는 반대 방향으로 3.6~7.4%p 빗나갔다. **anchor 8%**.

## [2] Inside View — 보정 (항목별)

| 증거 | 방향 | 조정 |
|---|---|---|
| DRAM 계약가가 3Q26에도 **+13~18% QoQ 상승**(TrendForce 2026-07-03) — 분기 중 가격이 계속 올랐다 | 하락 | −2%p |
| 서버 DDR5 2H25 +64% 누적, 2026년 약 +270% 전망. HBM은 2026년 잔여분 완판, 2027년까지 프리셀 | 하락 | −1%p |
| **어떤 애널리스트도 FQ4 2026 마진 정점을 주장하지 않는다** — 가장 매파적인 Citi조차 가격 정점을 **2Q CY2027**로, GM 하락은 2027년으로 본다 | 하락 | −1%p |
| GAAP/non-GAAP 격차가 1.3%p에서 **0.3%p로 축소** — SBC가 정액인데 매출이 4.5배가 돼 GAAP 불이익이 사라졌다 | 하락 | −1%p |
| **UBS(Arcuri) 2026-08-18: "peaking gross margins as more volume moves inside of supply chain agreements struck at pricing from one to two quarters ago"** — SCA 시차 메커니즘을 명시. 계약 물량이 1~2분기 전 가격으로 믹스에 들어오므로 **가격이 계속 올라도 GM은 꺾일 수 있다**. 이번 회차에서 확인한 가장 강한 반대증거 | 상승 | +3%p |
| CFO Murphy: "FQ4 총마진 전망은 **가격 상승률의 의미 있는 둔화**를 반영한다" — 둔화이지 하락이 아니나, 회사가 감속을 명시했고 위 UBS 메커니즘과 정합 | 상승 | +2%p |
| **14주 분기**라는 이례 구조 — 주차가 1주 많아 고정비 배분과 원가 인식이 평소와 다르다. 방향은 불명이나 분산을 키운다 | 상승 | +1%p |
| SCA(전략고객계약) 구조상 최대 계약이 **CQ2 2026 시장가를 상한**으로 두고 있어, 매출의 약 40%가 고정·상한 가격이다. 상승 여력을 제한 | 상승 | +1%p |
| 스팟 시장 둔화 — DDR4 16Gb가 6/30→7/28 +14%였다가 7/28→8/18 **+1.9%**로 급감, "sideways consolidation" | 상승 | +1%p |

순 조정 **−1%p** → 7%.

## [3] 분해 트리

| 경로 | 확률 | GM 하락 조건부 | 기여 |
|---|---|---|---|
| 가이던스(약 86%) 이상 달성 — 최근 3분기 패턴 | 0.72 | 0.00 | 0% |
| 가이던스 소폭 하회하나 84.6% 초과 | 0.22 | 0.00 | 0% |
| 가이던스를 1.4%p 이상 하회 | 0.07 | 1.00 | 7% |
| 합계 | | | **7%** |

## [4] Premortem — 틀릴 이유 3가지

1. **SCA 시차가 이미 물린 경우.** UBS가 지목한 메커니즘이 핵심이다 — 계약 물량이 1~2분기 전 가격으로 인식되면 스팟이 오르는 중에도 실현 ASP는 정체하고 GM이 꺾인다. 매출의 약 40%가 고정·상한 가격이라 믹스 전환 속도에 따라 1.4%p는 사라질 수 있다. 이 경우 7%는 크게 낮다.
2. **14주 분기의 원가 구조를 잘못 본 경우.** 주차가 1주 많으면 고정비와 감가상각이 한 주치 더 들어간다. 매출도 함께 늘어 상쇄되는 것이 정상이지만, 원가가 먼저 인식되는 구조라면 마진이 눌릴 수 있다. 이 요인은 과거 분기 비교에 존재하지 않던 변수다.
3. **반대 방향 — 7%도 높은 경우.** 회사가 GAAP 86%를 명시적으로 가이드했고 3분기 연속 +3.6~7.4%p 초과 달성했다. 가격은 여전히 오르고 있고 아무도 FQ4 정점을 말하지 않는다. 3% 안팎이 맞을 수도 있다.

## [5] 최종 출력

- 최종 확률: **7%** (80% CI: 3~14%)
- 직전 대비: r1 7% → r2 **7%** (**변화 없음**). 양방향 증거가 상쇄됐다. 하향 요인으로 회사가 **GAAP 기준으로도 약 86%**를 가이드했음을 확인했고(r1은 non-GAAP 병기로만 봤다), 최근 3분기 가이던스 초과폭(+3.6~7.4%p)을 정량화했으며, FQ4 정점을 주장하는 애널리스트가 없음을 확인했다. 상향 요인으로 **UBS의 SCA 시차 메커니즘**과 **14주 분기**라는 구조적 변수를 새로 반영했다. r1의 스냅샷 2건(발표일·분기 종료일)도 정정했다.
- **핵심 근거 3줄**:
  1. GAAP 총마진이 **6분기 연속 상승**했고 FQ4 가이던스(약 86%)는 기준선 84.6%보다 +1.4%p 높다.
  2. Micron은 최근 3분기 GAAP GM 가이던스를 **+3.6~+7.4%p 상회**했다 — 하락하려면 반대 방향으로 1.4%p 이상 빗나가야 한다.
  3. 반대 방향의 최강 논거는 UBS가 지목한 **SCA 시차**로, 가격이 올라도 GM이 꺾일 수 있는 실제 메커니즘이다 — 다만 어떤 애널리스트도 그 정점을 FQ4 2026으로 특정하지 않았다.
- **관찰 지표 2개**:
  1. **9/30 실적의 GAAP 총마진 실측** — 판정 그 자체. 84.6% 근처면 다음 분기 질문에서 확률을 크게 올려야 한다.
  2. **DRAM 스팟 가격 방향** — DDR4/DDR5 스팟이 QoQ 하락으로 전환하면 다음 분기 기준 +10%p 이상 상향.

> **P1 참고 의견 — 자금 결정의 단독 근거 아님** (P3 게이트: 해소 50문항+ & Brier < 0.18 통과 전).

## 출처 목록

- Micron FQ3 FY2026 실적 8-K EX-99.1 (매출 $41,456M, GAAP 매출총이익 $35,056M = 84.6%, FQ4 가이던스 GAAP/non-GAAP GM 약 86%) — https://www.sec.gov/Archives/edgar/data/723125/000072312526000013/a2026q3ex991-pressrelease.htm (2026-06-24)
- Micron FQ3 FY2026 10-Q (FY2026 53주, FQ4는 14주 분기 명시) — https://www.sec.gov/Archives/edgar/data/723125/000072312526000015/mu-20260528.htm
- Micron FQ3 FY26 Prepared Remarks (CFO Murphy: 가격 상승률의 의미 있는 둔화, SCA 구조·RPO 약 $100B) — https://s25.q4cdn.com/621799436/files/doc_financials/2026/q3/Q3-FY26-Prepared-Remarks.pdf
- Micron FQ4 실적 발표일 확정 공지 2026-09-30 — https://www.globenewswire.com/news-release/2026/08/26/3351673/14450/en/micron-technology-to-report-fiscal-fourth-quarter-results-on-september-30-2026.html (2026-08-26)
- Micron FQ2 FY2026 8-K EX-99.1 (GAAP GM 74.4%) — https://www.sec.gov/Archives/edgar/data/723125/000072312526000004/a2026q2ex991-pressrelease.htm
- Micron FQ1 FY2026 8-K EX-99.1 (GAAP GM 56.0%) — https://www.sec.gov/Archives/edgar/data/723125/000072312525000044/a2026q1ex991-pressrelease.htm
- Micron FQ4 FY2025 8-K EX-99.1 (GAAP GM 44.7%) — https://www.sec.gov/Archives/edgar/data/723125/000072312525000024/a2025q4ex991-pressrelease.htm
- TrendForce 3Q26 conventional DRAM +13~18% QoQ (2026-07-03) — https://www.trendforce.com/presscenter/news/20260703-13134.html
- TrendForce 2026-08-25 서버 DRAM·eSSD 2026년 누적 상승률, HBM 2027 +70~140% — https://www.trendforce.com/presscenter/news/20260825-13198.html
- UBS(Timothy Arcuri) SCA 시차로 인한 GM 정점 언급, Buy·PT $1,625 유지 (2026-08-18) — https://www.investing.com/news/analyst-ratings/ubs-reiterates-micron-stock-rating-on-ai-memory-demand-outlook-93CH-4865201
- Citi(Atif Malik) 목표가 $1,400→$1,150, 가격 정점 2Q CY2027·GM 미드70%대 전망 — https://finance.yahoo.com/markets/stocks/articles/citi-cuts-micron-stock-target-124820288.html (2026-08-07)
- 저장소 내부: `forecasts/2026/2026-07-08_mu-margin-qoq-next_r1.md` (직전 7%)

**[미검증]** 표기: TrendForce **4Q26 conventional DRAM +8~13%는 NOT FOUND** — r1 이후 확인 결과 해당 수치를 담은 TrendForce 공표물이 존재하지 않으며, 폐기된 4Q25 전망의 잔상으로 보인다. 사용하지 않았다. 애널리스트 목표주가 표는 2차 집계(dailypolitical) 경유 **[부분 미검증]**. Morgan Stanley의 "가격 상승률 4Q26 정점" 견해는 한국 언론 경유 **[미검증]**.
