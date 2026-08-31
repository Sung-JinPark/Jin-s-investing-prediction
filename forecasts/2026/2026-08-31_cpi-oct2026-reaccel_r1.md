---
forecast_id: 2026-08-31_cpi-oct2026-reaccel_r1
question_id: cpi-oct2026-reaccel
question_snapshot: "2026-11-10 발표되는 10월분 CPI 헤드라인 YoY(%)가 9월분 확정치(2026-10-14 공표)를 상회할 확률은?"
timestamp: 2026-08-31 17:40 KST
phase: P1
model: claude-opus-5 (Claude Code)
prompt_version: reasoning_core_v1
probability: 45
ci80: [30, 61]
window_end: null
snapshots:
  comparison_basis: "9월분 headline CPI-U YoY 최초 공표치(2026-10-14 발표) — 발표 시점에 확정, 사후 수정 무관. **2026-08-31 현재 미공표**"
  latest_print: "7월분 headline 3.4% YoY, core 2.5% (2026-08-12 공표)"
  nowcast: "Cleveland Fed Inflation Nowcast 2026-08-28 기준 — 8월분 CPI +0.36% MoM / **3.37% YoY**, core CPI +0.20% / 2.38%"
  release: "2026-11-10 (10월분), 비교 대상 9월분은 2026-10-14"
market_implied: null
edge: null
sources_count: 9
---

## [0] 질문 검증

판정 가능하나 **비교 기준이 아직 존재하지 않는다.** 9월분 CPI는 2026-10-14에 공표되며, 그 최초 공표치가 비교 기준으로 고정된다. 즉 이 질문은 두 미래 시점 값의 **차분 부호**를 묻는다.

차분 질문이라는 점이 중요하다. 절대 수준(현재 3.4%)이 높은지 낮은지가 아니라, 10월분 YoY가 9월분 YoY보다 **올라가는지**만 본다. 이는 주로 **기저효과**(전년 동월 대비)와 월간 모멘텀의 상호작용으로 결정된다.

## [1] Outside View — base rate (anchor: 47%)

2026년 헤드라인 CPI YoY 최초 공표 경로: 1월 2.4% → 2월 2.4% → 3월 **3.3%** → 4월 **3.8%** → 5월 **4.2%** → 6월 3.5% → 7월 3.4%.

월간 전이 6회 중 **상승 3회(2→3월, 3→4월, 4→5월), 하락 2회(5→6월, 6→7월), 보합 1회(1→2월)**. 보합을 NO로 처리하면 상승 비율 **3/6 = 50%**.

무조건부로 YoY 방향은 동전 던지기에 가깝다. 다만 2026년 경로에는 명확한 구조가 있다 — **3~5월 급등은 전량 에너지 충격**(이란 분쟁, 3월 휘발유 +21.2% MoM으로 1967년 계열 시작 이래 최대)이었고, 5월 정점(4.2%) 이후 에너지 정상화와 함께 두 달 연속 하락했다. **근원은 연중 2.5~2.8% 밴드에서 안정적**이라 헤드라인 변동은 거의 전부 에너지가 만든다.

Cleveland Fed 나우캐스트는 8월분을 **3.37%**로 본다 — 7월 3.4%에서 사실상 보합~미세 하락이다. **anchor 47%**(50%에서 에너지 정상화 방향을 소폭 반영).

## [2] Inside View — 보정 (항목별)

| 증거 | 방향 | 조정 |
|---|---|---|
| **최근 2개월 연속 하락**(4.2% → 3.5% → 3.4%) — 에너지 기저효과가 역방향으로 작동하기 시작 | 하락 | −4%p |
| Cleveland Fed 나우캐스트 8월 3.37%로 하락 방향 지속 시사. Q3 연율 CPI 나우캐스트는 1.07%로 매우 낮음 | 하락 | −3%p |
| 근원이 2.5%로 안정 — 헤드라인을 밀어올릴 광범위한 압력이 없다 | 하락 | −2%p |
| **호르무즈 해협이 여전히 봉쇄 상태** — 8/4~8/6 통항 8~15척/일(분쟁 전 약 130척). 이란이 제재 완화·배상을 재개 조건으로 제시. 재확대 시 유가 급등이 즉시 헤드라인에 반영 | 상승 | +5%p |
| 브렌트유가 7/29~8/25 $86.47~96.95 밴드에서 등락 — 방향성 없이 높은 수준 유지. 전년 동월 유가에 따라 기저효과가 상방으로 뒤집힐 수 있다 | 상승 | +2%p |
| 서비스 인플레이션 가속 — 7월 PCE 기준 서비스 +0.3% MoM(직전 +0.1%) | 상승 | +2%p |
| 지평이 멀다(10~11월) — 두 번의 CPI 공표가 먼저 지나가며 기저율로 회귀 | 하락 | −2%p |

순 조정 **−2%p** → 45%.

## [3] 분해 트리

| 10월 국면 | 확률 | YoY 상승 조건부 | 기여 |
|---|---|---|---|
| 에너지 안정·하락 지속 | 0.50 | 0.25 | 13% |
| 에너지 횡보 + 서비스 완만 가속 | 0.30 | 0.55 | 17% |
| 호르무즈 재확대·유가 급등 | 0.12 | 0.90 | 11% |
| 광범위한 디스인플레 가속 | 0.08 | 0.05 | 0% |
| 중복 보정 | | | +4%p |
| 합계 | | | **45%** |

**이 질문의 실체는 유가 베팅에 가깝다.** 근원이 2.5%에서 안정적인 한 헤드라인 YoY의 방향은 에너지가 결정하고, 에너지는 호르무즈 상황에 달려 있다.

## [4] Premortem — 틀릴 이유 3가지

1. **호르무즈가 재확대되는 경우.** 통항이 정상의 10% 수준에 머무는 상태에서 추가 충격이 오면 유가가 한 달 만에 20~30% 뛸 수 있고, 헤드라인 YoY는 즉시 반전한다. 3월에 실제로 일어난 일이다.
2. **기저효과를 정량화하지 못했다.** 2025년 9~10월 CPI 수준을 확보하지 못해(**NOT FOUND**) 기저효과의 방향과 크기를 계산할 수 없었다. 2025년 가을 유가가 낮았다면 2026년 10월 YoY가 기계적으로 올라간다. 이것이 이 예측의 가장 큰 구멍이다.
3. **반대 방향 — 45%도 높은 경우.** 근원 2.5% 안정에 Q3 CPI 나우캐스트 연율 1.07%, 두 달 연속 하락이다. 유가만 안정되면 35% 부근이 맞다.

## [5] 최종 출력

- 최종 확률: **45%** (80% CI: 30~61%)
- **핵심 근거 3줄**:
  1. YoY 차분 질문이라 무조건부로는 동전 던지기(2026년 상승 3/6)이며, 앵커를 47%에서 출발했다.
  2. 근원이 2.5~2.8% 밴드에서 안정적이라 헤드라인 변동은 **거의 전부 에너지**가 만들고, 최근 2개월은 하락 방향이다.
  3. 상방은 호르무즈 재확대 리스크이며, 이 질문은 실질적으로 유가 베팅에 가깝다.
- **관찰 지표 2개**:
  1. **호르무즈 해협 통항량과 브렌트유** — 브렌트 $100 돌파 시 60% 이상으로 상향.
  2. **9월분 CPI(10/14 공표)와 그때의 기저효과** — 비교 기준이 확정되는 시점이므로 이때 재예측 필요.

> **P1 참고 의견 — 자금 결정의 단독 근거 아님** (P3 게이트: 해소 50문항+ & Brier < 0.18 통과 전).

## 출처 목록

- BLS CPI 2026년 7월 (헤드라인 3.4%, 근원 2.5%) — https://www.bls.gov/news.release/archives/cpi_08122026.htm (2026-08-12)
- CNBC 2026년 7월 CPI — https://www.cnbc.com/2026/08/12/cpi-inflation-report-july-2026.html
- BLS TED 2026년 3월 CPI (3.3%, 휘발유 +21.2% MoM) — https://www.bls.gov/opub/ted/2026/consumer-prices-up-3-3-percent-over-the-year-0-9-percent-over-the-month-in-march-2026.htm
- BLS TED 2026년 5월 CPI (4.2% 정점) — https://www.bls.gov/opub/ted/2026/consumer-prices-up-4-2-percent-over-the-year-ended-may-2026.htm
- CNBC 2026년 6월 CPI (3.5%) — https://www.cnbc.com/2026/07/14/consumer-price-index-inflation-report-june-2026.html
- Cleveland Fed Inflation Nowcasting (2026-08-28 기준 8월 CPI 3.37%) — https://www.clevelandfed.org/indicators-and-data/inflation-nowcasting
- US Inflation Calculator CPI 발표 일정 — https://www.usinflationcalculator.com/inflation/consumer-price-index-release-schedule/
- Al Jazeera 호르무즈 통항·유가 (2026-08-10, 2026-08-12) — https://www.aljazeera.com/economy/2026/8/10/oil-prices-climb-as-iranian-demands-cloud-outlook-for-strait-of-hormuz
- FRED DCOILBRENTEU (브렌트유) — https://fred.stlouisfed.org/series/DCOILBRENTEU

**[미검증]** 표기: **2025년 9~10월 CPI 수준을 확보하지 못해 기저효과를 정량화하지 못했다(NOT FOUND)** — 본 예측의 가장 큰 한계로 명시한다. 2026년 2·5·6월 core YoY도 NOT FOUND. 9월분 비교 기준은 2026-10-14까지 미존재.
