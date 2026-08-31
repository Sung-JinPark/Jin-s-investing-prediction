---
forecast_id: 2026-08-31_soxx-eoy-down15_r3
question_id: soxx-eoy-down15
question_snapshot: "SOXX(iShares Semiconductor ETF)의 2026년 마지막 거래일 종가가 기준가(reference price) 대비 −15% 이하일 확률은?"
timestamp: 2026-08-31 15:00 KST
phase: P1
model: claude-opus-5 (Claude Code)
prompt_version: reasoning_core_v1
probability: 33
ci80: [20, 48]
window_end: null
snapshots:
  reference_price: "$551.69 (2026-07-07 종가) — r1 확정, 변경 금지"
  threshold: "$468.94 (= $551.69 x 0.85)"
  current: "$508.62 (2026-08-28 종가) — 기준가 대비 −7.81%, 임계까지 추가 −7.80% 필요"
  prior_threshold_breach: "2026-07-29 종가 $465.00 (기준가 −15.71%) — 임계 하회 마감 이력 있음. 단 본 질문은 종점형이라 판정과 무관"
  remaining: "2026-12-31까지 약 85거래일"
market_implied: null
edge: null
sources_count: 28
---

## [0] 질문 검증

판정 가능. 기준가 $551.69(2026-07-07 종가)와 임계 $468.94는 r1에서 확정됐다. 판정은 **2026년 최종 거래일 종가 1개 값**이 $468.94 이하인지 여부 — **종점형**이다.

**r2 분해식의 무효화 — 이번 회차의 핵심.** r2는 `P(임계 터치 55%) x P(연말까지 유지 40%) = 22%`(보고값 24%)로 계산했다. 그런데 2026-07-29 SOXX는 **$465.00으로 마감해 임계 아래에서 종가를 형성**했다. 터치 레그는 이미 100%로 해소됐으므로 그 분해식은 더 이상 쓸 수 없고, 남은 문제는 **"현재 $508.62에서 연말에 $468.94 이하로 끝나는가"**라는 순수 종점 문제다. 필요 낙폭은 −15%가 아니라 **−7.80%**다.

## [1] Outside View — base rate (anchor: 35%)

종점형이므로 종점 로그정규 분포로 앵커를 잡는다. 실현변동성을 직접 계산했다(검증된 일별 종가 기준): 8월 19거래일 일별 표준편차 2.62% → **연율 41.5%**, 최근 30거래일 → **연율 50.9%**.

| 연율변동성 | 드리프트 0% | +10% |
|---|---|---|
| 30% | 35.2% | 28.3% |
| 35% | 38.3% | 32.1% |
| 41.5% (8월 실현) | 41.4% | 36.1% |
| 50% | 44.6% | 40.1% |

저장소 `data/base_rates/market-regime.md`의 기존 앵커 **"^SOX 7월 초 → 연말 −15% 유지: 6/32 = 19%, 2008년 이후 0/17"**은 이번 회차에서 **사용하지 않는다**. 세 가지 결함이 있다.

1. **참조군 오류** — 무정보 상태(7월 초)의 무조건부 기저율인데, 현재는 이미 −7.81% 진행 + 임계 하회 종가 1회 이력이 있는 **조건부** 상태다.
2. **지수 불일치** — SOXX는 2021년 6월 이후 ^SOX(PHLX)가 아니라 **ICE Semiconductor Index**를 추종한다. 가중 상한 규칙도 다르다(SOX 12/10/8/4% 계층 vs ICE 상위 5종목 8%·나머지 4%). 기저율 산출 대상과 판정 대상이 다른 지수다.
3. **표본 부족을 낮은 확률로 오독** — "2008년 이후 0/17"의 17년 중, 상반기 +100% 급등 후 SOX 기준 2008년 이후 최악의 월(2026년 7월)을 겪은 해는 없다.

**anchor 35%** — 보수적 변동성(30~35%)에 소폭 양의 드리프트를 가정한 구간.

## [2] Inside View — 보정 (항목별)

| 증거 | 방향 | 조정 |
|---|---|---|
| 2027년 메모리 물량 완판 — 삼성·SK하이닉스·MU의 2027 DRAM·HBM 캐파 매진, 하이퍼스케일러 약 220억 달러 선수금 선납. SK하이닉스 CEO "2027년은 공급 관점에서 업계 역사상 최악(=최대 타이트)" | 하락 | −5%p |
| 장비 사이클 무손상 — TSMC 2026 capex 520~560억에서 600~640억 달러로 3연속 상향, ASML 2026 가이던스 2연속 상향(430~450억 유로). CoWoS 완판이 바인딩 제약 | 하락 | −4%p |
| NVDA 실적 압도 — FQ2 매출 962억 달러(+106%), DC 890억, Q3 가이던스 1,080억. 수요 훼손 증거 없음 | 하락 | −3%p |
| 8월 V자 실증 — $465.00(7/29)에서 $559.12(8/17)로 13거래일 **+20.2%**. 딥 바잉이 실제로 작동 | 하락 | −3%p |
| 필요 낙폭 축소 — r2 시점 −10.1%에서 현재 **−7.80%**로. 직전 8거래일에 −9.0%(8/17→8/28)가 실제 발생한 폭 | 상승 | +6%p |
| 실현변동성 급등 — 8월 41.5%, 30일 50.9% 연율. 24%를 유지하려면 무드리프트 시 연율 19.8%로 붕괴하거나 연말까지 +12.5% 상승을 기대값으로 전제해야 하는데, 둘 다 근거 없음 | 상승 | +5%p |
| 메모리 가격 2차 미분 하락 — DRAM 계약가 QoQ 1Q26 +93~98%에서 2Q +58~63%, **3Q +13~18%**, 4Q +8~13%(TrendForce). 레벨은 최고지만 상승률 둔화는 반도체 사이클 고점의 전형 | 상승 | +4%p |
| 호재 소화 실패 — 8/27 NVDA +8.74%에도 SOXX는 **+1.95%**에 그쳤고 익일 −3.20%로 전량 반납. 섹터 벨웨더 최상급 호재를 이틀도 못 버팀 | 상승 | +3%p |
| 금리 역풍 — 9월 인상 확률 약 56~58%. 고듀레이션 반도체에 직접 타격이며 8/18·8/28 하락의 공통 원인 | 상승 | +3%p |
| 9월 이벤트 밀집 — 9/18 지수 리컨스티튜션, **9/30 Micron FQ4**(SOXX 비중 8.84%, GM 약 86% 가이던스라 피크아웃 확인 시 반응 비대칭) | 상승 | +2%p |
| 자금 미이탈 — 8월 SOXX 순유입 +15.3억 달러인데 AUM은 −46.0억 달러(가격 하락). 항복 신호 부재 = 하방 여지 잔존 | 상승 | +1%p |

순 조정 **−2%p** → 33%.

## [3] 분해 트리

| 연말 경로 | 확률 | $468.94 이하 마감 조건부 | 기여 |
|---|---|---|---|
| AI capex 서사 유지 + 금리 중립 → 재상승 | 0.40 | 0.05 | 2% |
| 횡보(현 수준 ±7%) | 0.25 | 0.30 | 8% |
| 금리 주도 디레이팅(인상 사이클 재개) | 0.20 | 0.65 | 13% |
| 메모리 피크아웃 확인(9/30 MU 등) + 사이클 전환 | 0.15 | 0.70 | 11% |
| 합계 | | | **34%** ≈ 33% |

**구조적 유의점 — SOXX는 NVDA 대리지표가 아니다.** 2026-08-20 기준 NVDA 비중은 **9.05%**에 불과하고 MU 8.84%가 거의 동일하다. 장비(AMAT·LRCX·KLAC·TER·ASML·ENTG 합 20.38%)와 아날로그·레거시(ADI·TXN·MPWR·NXPI·MCHP·ON 합 18.04%)가 합쳐 38%로, 이들은 AI 매출이 아니라 **capex 심리와 전통 사이클**에 연동되며 NVDA보다 높은 베타를 갖는다. 8/27 NVDA +8.74% 대비 SOXX +1.95%가 그 실증이다. "NVDA가 좋으니 SOXX도 방어된다"는 추론은 이 지수에 적용되지 않는다.

**ML 앙상블 대비.** `ml_auto.md`(2026-07-20) SOXX 앙상블 24%(bolt 24% / c2 57% / gbm 4% — **모델 불일치 플래그**). 본 예측 33%와 9%p 차이로 divergence 임계(15%p) 미만이다. 다만 ML 값은 6주 전 가격($521.81 부근) 기준이고 모델 간 편차가 53%p로 극단적이어서 **앙상블 중앙값의 정보량 자체가 낮다**. 이 회차에서는 참고선으로만 취급한다.

## [4] Premortem — 틀릴 이유 3가지

1. **펀더멘털의 가격 설명력을 과대평가한 경우(33%가 낮음).** 2027 완판·capex 상향은 **7월에도 이미 참이었고, 그럼에도 SOX는 −28.6% 하락**했다. 삼성은 기록적 실적 발표 후에도 주가가 빠졌다. 현 레짐은 이익이 아니라 멀티플·포지셔닝이 가격을 정하며, 디레이팅은 펀더멘털 균열 없이 진행된다. 이 경우 40%대가 맞다.
2. **한국 마진콜 언와인드가 미완인 경우.** 7/29 전후 한국에서 120만+ 계좌 마진콜, 32만~36만 계좌 강제청산이 보고됐다. 레버리지 청산이 아직 끝나지 않았다면 하방 꼬리가 두껍다.
3. **반대 방향 — 변동성 앵커가 과했을 경우(33%가 높음).** 8월 실현변동성 41.5%는 V자 반등이라는 **상방** 변동성이 대부분 만든 값이다. 방향성 없는 변동성을 하방 확률로 환산하면 과대평가된다. 공급 부족이 2027년까지 지속되고 금리가 중립화되면 연말 $520~560 구간이 자연스럽고, 이 경우 20%대 초반이 맞다.

## [5] 최종 출력

- 최종 확률: **33%** (80% CI: 20~48%)
- 직전 대비: r2 24% → r3 33% (**+9%p**). 근거는 새 악재가 아니라 **산술**이다 — (1) 가격이 6주간 기준가 −5.4%에서 **−7.81%**로 밀려 필요 추가 낙폭이 −10.1%에서 **−7.80%**로 축소, (2) 실현변동성이 연율 41.5%로 급등해 24%를 유지하려면 명시된 바 없는 강한 강세 드리프트가 필요, (3) r2가 쓴 터치×유지 분해식이 7/29 임계 하회 마감으로 무효화, (4) 기존 base rate 앵커(^SOX 2008년 이후 0/17)가 참조군·지수 불일치로 부적합함을 확인.
- **핵심 근거 3줄**:
  1. 종점형 질문에서 필요 낙폭이 −7.80%로 좁혀졌고, 이 폭은 직전 8거래일에 실제로 발생한 크기다.
  2. 실현변동성 41.5%(8월) 기준 종점 확률은 36~41%이며, 보수적 30% 변동성에서도 28~35%다.
  3. 펀더멘털(2027 완판·capex 상향)은 강하지만 7월에도 참이었고 −28.6% 하락을 막지 못했다 — 현 레짐은 디레이팅이 지배한다.
- **관찰 지표 2개**:
  1. **9/30 Micron FQ4 실적과 FQ1 가이던스** — SOXX 비중 8.84%. 총이익률 피크아웃이 확인되면 45%로 상향, 재상향 가이던스면 25%로 하향.
  2. **SOXX $490 지지 여부** — 8월 최저 종가 $506.18 아래로 종가 이탈 후 $490 붕괴 시 임계까지 −4%만 남아 50% 이상으로 상향. 반대로 $551.69(기준가) 회복 시 20%로 하향.

> **P1 참고 의견 — 자금 결정의 단독 근거 아님** (P3 게이트: 해소 50문항+ & Brier < 0.18 통과 전).

## 출처 목록

- SOXX 일별 종가·52주 레인지 — https://stockanalysis.com/etf/soxx/history/ (2026-08-28), https://www.investing.com/etfs/ishares-phlx-sox-semiconductor 교차확인
- SOXX 보유 비중 (2026-08-20, NVDA 9.05% · MU 8.84% 등) — https://stockanalysis.com/etf/soxx/holdings/
- NVIDIA FQ2 2027 실적 (매출 962억 달러, DC 890억, Q3 가이던스 1,080억, GM 75.0%에서 74.0%) — https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-second-quarter-fiscal-2027 (2026-08-26)
- Bloomberg NVDA 8/27 시총 +4,420억 달러 — https://www.bloomberg.com/news/articles/2026-08-27/nvidia-adds-442-billion-in-second-biggest-ever-stock-surge
- TSMC 7월 월매출 (NT$467.58B, YoY +44.7%) — https://pr.tsmc.com/english/news/3329 (2026-08-10)
- TSMC 2026 capex 600~640억 달러 상향 — https://www.trendforce.com/news/2026/07/16/news-tsmc-lifts-2026-capex-15-to-60-64b-hikes-sales-outlook-to-over-40-despite-q3-margin-dip/
- ASML Q2 2026 실적·가이던스 상향 — https://www.asml.com/en/news/press-releases/2026/q2-2026-financial-results (2026-07-15)
- AMD Q2 2026 실적 — https://ir.amd.com/news-events/press-releases/detail/1295/amd-reports-second-quarter-2026-financial-results (2026-08-04)
- Micron FQ3 2026 실적 (GM 84.9%, FQ4 가이던스) — https://investors.micron.com/news/press-release/2026/Micron-Technology-Inc--Reports-Record-Results-for-the-Third-Quarter-of-Fiscal-2026/default.aspx
- Micron FQ4 발표일 2026-09-30 — https://www.globenewswire.com/news-release/2026/08/26/3351673/14450/en/micron-technology-to-report-fiscal-fourth-quarter-results-on-september-30-2026.html
- TrendForce DRAM 계약가 QoQ 전망 (3Q26 +13~18%) — https://www.trendforce.com/presscenter/news/20260703-13134.html (2026-07-03)
- SK hynix 2026 Q2 실적 (영업이익률 76%) — https://news.skhynix.com/en/q2-2026-business-results/ (2026-07-29)
- CNBC 칩 셀오프 2026-07-29 (시총 1조 달러+ 증발) — https://www.cnbc.com/2026/07/29/chip-selloff-sk-hynix-samsung-softbank.html
- Bloomberg SOX 베어마켓 진입 (2026-07-17) — https://www.bloomberg.com/news/articles/2026-07-17/chips-stocks-tumble-into-bear-market-as-105-ai-rally-fizzles
- Motley Fool "Why the iShares Semiconductor ETF (SOXX) Plunged 21%" (2026-08-07) — https://www.fool.com/investing/2026/08/07/why-the-ishares-semiconductor-etf-soxx-plunged-21/
- Yahoo Finance 메모리주 베어마켓 진입 (2026-07-08) — https://finance.yahoo.com/markets/article/micron-samsung-sk-hynix-just-dragged-memory-stocks-into-a-bear-market-154549356.html
- CNBC 시장 (2026-08-23/24 NVDA 7거래일 연속 하락) — https://www.cnbc.com/2026/08/23/stock-market-today-live-updates.html
- Warsh 잭슨홀 연설 2026-08-28 — https://www.federalreserve.gov/newsevents/speech/warsh20260828a.htm
- CNBC 9월 FOMC 인상 확률 (2026-08-28) — https://www.cnbc.com/2026/08/28/-september-fed-decision-now-a-coin-flip-as-rate-hike-odds-increase.html
- Seeking Alpha 2027 메모리 물량 완판 — https://seekingalpha.com/news/4625688-samsung-sk-hynix-micron-sell-out-2027-memory-chip-supply-report
- IDC 스마트폰 출하 전망 −16.7% (2026-08-26) — https://www.idc.com/resource-center/blog/smartphone-shipments-set-for-record-16-7-drop-in-2026-as-the-memory-crisis-hits-full-force/
- 저장소 내부: `data/base_rates/ml_auto.md` (SOXX 앙상블 24%, 모델 불일치), `forecasts/2026/2026-07-20_soxx-eoy-down15_r2.md` (직전 24%)
- 실현변동성·종점 확률 계산: 검증된 일별 종가로 본 회차 자체 산출, 재현 가능

**[미검증]** 표기: 8월 ETF 자금흐름(SOXX +15.3억 달러 유입 / AUM −46.0억 달러)은 2차 출처. 한국 마진콜 계좌 수(120만+, 강제청산 32만~36만)는 2차 출처. Micron FQ4 가이던스 매출 500억 달러·GM 86%는 검색 요약 경유로 **[미검증]**. Michael Burry의 SOXX 풋 공시(2026-08-14)는 규모 미공개·2차 출처. 2026년 9월 지수 리컨스티튜션의 편입·편출 종목 리스트는 **NOT FOUND**.
