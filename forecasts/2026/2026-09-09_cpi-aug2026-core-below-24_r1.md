---
forecast_id: 2026-09-09_cpi-aug2026-core-below-24_r1
question_id: cpi-aug2026-core-below-24
question_snapshot: "2026-09-11 발표되는 8월분 CPI에서 근원(core) CPI-U 전년동월비가 2.4% 이하일 확률은?"
timestamp: 2026-09-09 15:55 KST
phase: P1
model: claude-opus-5 (Claude Code)
prompt_version: reasoning_core_v1
probability: 65
anchor_pct: 70
ci80: [52, 77]
shadow_extremized: 75
window_end: null
snapshots:
  bls_core_nsa_index: "CUUR0000SA0L1E — 2025-07: 328.980 · 2025-08: 329.970 · 2026-06: 336.882 · 2026-07: 337.133 (BLS 공개 API 직접 취득, 2026-09-09 KST). NSA는 공표 후 개정되지 않음(final when issued) → 기저 고정"
  unrounded_july_core_yoy: "2.4783% (337.133/328.980) — 인쇄값 2.5%이나 2.45 반올림 경계에서 0.028%p 위. **판정 기준값 아님, 맥락값**"
  yes_threshold: "8월분 NSA core 지수 < 338.054 (= 329.970 x 1.0245) ⟺ **NSA MoM < +0.2733%** (SA 환산 약 +0.282%). 이 단일 조건이 YES/NO를 완전히 결정한다"
  aug2025_base: "2025-08 NSA MoM +0.3009% (329.970/328.980) — 롤오프되는 달이 임계보다 높아 base effect는 YES 방향 순풍"
  consensus_core_mom: "+0.2% (Trading Economics/Investing.com 집계). 서베이 표본 수 NOT FOUND"
  consensus_core_yoy: "2.4% (Trading Economics 명시) — 컨센서스 자체가 YES를 가리킴"
  cleveland_fed_nowcast: "2026-08 core CPI MoM +0.20% / YoY 2.38% (2026-09-08 갱신, clevelandfed.org)"
  bank_forecasts_core_mom: "Goldman Sachs +0.23%(→2.40%) · RBC +0.24%(→2.4%) · TD Securities +0.19% · Wells Fargo +0.24%. Morgan Stanley·JPM·Barclays·Citi·BofA NOT FOUND"
  core_mom_2026_sa: "1월 +0.295 · 2월 +0.216 · 3월 +0.196 · 4월 +0.376 · 5월 +0.208 · 6월 −0.017 · 7월 +0.215 (BLS 지수 산출). 3개월 평균 0.136 · 6개월 평균 0.199"
  release: "2026-09-11 08:30 ET (BLS 공식 일정, 각주 없음). 8월 PPI가 하루 전 2026-09-10 발표 — 재확인 창 1회 남음"
market_implied: 74
edge: -9
sources_count: 21
---

## [0] 질문 검증

판정 가능하고, **이 질문은 산술적으로 완전히 환원된다**.

BLS는 12개월 변화율을 **NSA(비계절조정) 지수**로 산출하고, NSA 지수는 공표 후 개정되지 않는다("final when issued"). 따라서 기저인 2025-08 지수 **329.970은 고정**이며 개정 리스크가 없다.

인쇄값 2.4%의 조건은 미반올림 YoY < 2.45%, 즉

> **2026-08 NSA core 지수 < 329.970 × 1.0245 = 338.054**
> ⟺ 2026-07(337.133) 대비 **NSA MoM < +0.2733%** (SA 환산 약 +0.282%)

이 단일 부등식이 YES/NO를 완전히 결정한다. 아래 모든 논의는 "8월 SA core MoM이 0.282%를 밑도는가"에 대한 것이다.

**임계 이하 구간이 넓다는 점을 명시한다.** 질문은 "2.4% 이하"이므로 2.3%·2.2%도 YES다. 6월(−0.017%) 같은 하방 사건은 전부 YES로 흡수된다 — 실패 경로는 상방 하나뿐이다.

**주의 (자기 정정 기록).** 초기 교차검증에서 337.133을 329.970으로 나눠 "미반올림 7월 YoY 2.171%"를 얻었는데, 이는 7월 YoY의 기저를 8월로 잘못 잡은 것이다. 올바른 기저는 2025-07(328.980)이고 값은 **2.4783%**다. BLS API로 직접 재확인했다. 판정 임계(0.2733%)는 이 오류와 무관하게 성립한다 — 임계는 2026-07과 2025-08만 쓰기 때문이다.

## [1] Outside View — base rate (anchor: 70%)

참조 클래스: **"미국 월간 SA core CPI MoM이 0.282% 미만인 달"**. 임계가 절대 수치로 환원되므로 참조 클래스도 그렇게 잡는 것이 정확하다.

| 슬라이스 | 임계 미만 비율 | 출처 |
|---|---|---|
| 최근 10개월 (2025-11~2026-07 유효) | **7/10 = 70%** | BLS CUSR0000SA0L1E 직접 산출 |
| 최근 10년의 8월 (2016~2025) | **7/10 = 70%** — 초과 3회(2020 +0.386 · 2022 +0.490 · 2025 +0.310) | 동일 |
| 인쇄 core YoY 전월 대비 하락 (2015~2026, n=126) | 41.6% | 동일 |
| 위 조건부 — 전월도 하락했을 때 | 54.9% (51회 중 28회) | 동일 |

**두 개의 독립 슬라이스(최근 10개월·최근 10개 8월)가 모두 70%로 일치**하므로 anchor를 **70%**로 둔다. 하위 두 행(YoY 하락률 41.6%/54.9%)은 참조 클래스가 다르다 — 그것은 "임의 크기의 하락"이고 이 질문은 "이미 경계에 붙어 있는 상태에서의 임계 통과"라 직접 쓰면 과소평가가 된다.

## [2] Inside View — 보정 (항목별)

| 증거 | 방향 | 조정 |
|---|---|---|
| **예측기관 군집이 임계 아래에 몰려 있다** — Cleveland Fed 나우캐스트 +0.20%, 컨센서스 +0.20%, GS +0.23%, RBC +0.24%, TD +0.19%, WF +0.24%. 평균 0.225%로 임계(0.282%)까지 여유 0.057%p. 서로 독립적인 6개 추정이 한 방향 | 상승 | **+8%p** |
| **최근 모멘텀이 임계에서 멀다** — 3개월 평균 0.136%, 6개월 평균 0.199%. 6월은 −0.017%로 음수 | 상승 | **+4%p** |
| **반올림 절벽** — 나우캐스트 여유는 MoM 기준 0.08%p인데 core MoM 나우캐스트 통상 오차는 약 0.10%p. **쿠션이 1σ 미만**이다. 0.27%는 YES, 0.28%는 NO로 0.01%p가 결과를 뒤집는다 | 하락 | **−6%p** |
| **8월 잔여 계절성** — 최근 4개 8월 평균 +0.314%로 **임계를 넘는다** (2022 +0.49 · 2023 +0.20 · 2024 +0.25 · 2025 +0.31). 10년 평균(0.239%)은 아래지만 최근 쏠림이 위 | 하락 | **−5%p** |
| **상방 리스크가 서비스에 집중** — ISM 서비스 물가 8월 **72.6**(7월 70.3, 2022-08 이후 최고) · OER +0.3%/주거임대료 +0.3%로 둘 다 여전히 뜨겁고 Zillow ZORI 8월 +2.5% YoY로 재가속 · 7월 숙박 −2.75%의 반등 여지(반등 +2%면 core +0.035%p) · 제트유 IATA 기준 전년 대비 약 +70%로 항공료 압력(GS는 +4.0%를 가정하고도 0.23%) | 하락 | **−5%p** |
| **측정 노이즈 증가** — 가격의 약 19%가 추정(imputation, 2022년말 5.1%에서 급증), 표본 수집 축소. BLS 자신이 변동성 증가 가능성을 공지. 임계까지 여유가 0.028%p(YoY)인 상황에서 노이즈는 우세 쪽을 잠식 | 하락 | **−2%p** |
| **시장내재가 anchor를 지지** — Kalshi `KXCPICOREYOY-26AUG-T2.4` 최종체결 P(>2.4%)=0.26 → **P(YES)≈0.74**. 다만 호가 0.12/0.23으로 스프레드가 넓고 유동성이 얇다 | 상승 | **+1%p** |
| 기저효과(2025-08 +0.3009% 롤오프) | — | **0%p** — anchor의 8월 슬라이스와 예측기관 전망에 이미 반영. 이중계상 금지 |

**70 + 8 + 4 − 6 − 5 − 5 − 2 + 1 = 65%**

## [3] 분해 트리

YES ⟺ 8월 SA core MoM < 0.282%. core를 서비스(76.2%)·재화(23.8%)로 분해하고 7월 실적에서 각 항목을 전개한다.

| 구성 | core 내 비중 | 8월 가정 MoM | 기여 |
|---|---|---|---|
| Shelter (OER 31.5 + 주거임대료 등) | 44.7% | +0.25% (7월 OER +0.26·임대료 +0.3, 숙박 반등 일부) | +0.112%p |
| 의료서비스 | 8.7% | +0.30% (7월 +0.56의 평균회귀, 건강보험 계수는 10월까지 고정) | +0.026%p |
| 항공료 | 1.4% | +3.0% (GS 가정 +4.0%보다 보수) | +0.042%p |
| 기타 core 서비스 | 21.4% | +0.19% | +0.041%p |
| core 재화 | 23.8% | +0.10% (Manheim 8월 −0.9%는 약 2개월 시차라 8월 CPI엔 부분 반영) | +0.024%p |
| **합계** | 100% | — | **+0.245%p** |

검산: 7월 실적으로 같은 식을 돌리면 0.23×0.762 + 0.20×0.238 = 0.223 ≈ 실제 0.215 (오차 0.008%p) — 분해 구조가 재현된다.

중심 0.245%, 임계 0.282%. 월간 core MoM의 예측오차 표준편차를 0.10%p로 두면
**P(MoM < 0.282%) = Φ((0.282−0.245)/0.10) = Φ(0.37) ≈ 64%**. σ=0.12로 늘리면 62%.

[2]의 65%와 분해의 62~64%가 정합한다. 예측기관 평균(0.225%)을 중심으로 쓰면 76%까지 올라가지만, 내 분해가 그보다 보수적인 이유는 숙박 반등과 항공료를 명시적으로 얹었기 때문이며 그 보수성을 유지한다.

## [4] Premortem — 크게 틀릴 이유 3가지

**1. 서비스 반등이 동시에 온다 (가장 그럴듯).** 7월 숙박은 −2.75%, 항공료는 +2.22%였다. 8월에 숙박이 +2%로 돌아서고(+0.035%p) 항공료가 +6%면(+0.083%p) 그것만으로 +0.12%p가 얹혀 MoM이 0.33%가 된다 → NO. 제트유가 전년 대비 +70%이고 ISM 서비스 물가가 4년 최고라는 두 증거가 이 경로를 실재하게 만든다.

**2. 주거가 다시 붙는다.** shelter는 core의 44.7%다. 7월 총 shelter가 +0.1%로 낮게 보인 것은 변동성 큰 숙박이 끌어내린 결과이고, **지속성 있는 OER·주거임대료는 둘 다 +0.3%**였다. shelter가 +0.35%로 가면 +0.045%p가 추가된다. Zillow ZORI와 Apartment List가 동시에 재가속을 가리킨다.

**3. 반올림 하나로 진다.** 0.28%가 나오면 언론은 "0.3%"라 쓰고 core YoY는 2.5%로 인쇄된다. 여유는 YoY 기준 **0.028%p**뿐이며, 추정 비중 19%라는 측정 환경에서 이 크기는 노이즈와 구분되지 않는다. 즉 이 예측은 "예측이 맞았는가"보다 "노이즈가 어느 쪽으로 떨어졌는가"에 상당 부분 걸려 있다.

**세 경로가 전부 같은 방향(상방)을 가리킨다**는 점이 이 질문의 비대칭이다. 하방으로 크게 틀릴 경로는 사실상 없다 — 임계 이하 구간이 열려 있기 때문이다. 이 비대칭을 반영해 분해값(62~64%)보다 위로 올리지 않고 **65%에서 멈춘다**.

## [5] 데블스 애드버킷 — 반대증거 종합

전담 리서치가 수집한 반대증거를 원문 그대로 남긴다.

- **최근 4개 8월 평균 SA MoM 0.314%로 임계 초과.** 2025년 8월 자체가 +0.310%였다. 8월은 구조적으로 뜨거운 달일 수 있다.
- **2025~2026 창에서 core YoY 3개월 연속 하락 전례가 없다.** 최장 2개월이며, 8월이 하락하면 이 창의 첫 3연속이 된다.
- **나우캐스트 쿠션(0.07%p)이 나우캐스트 오차(약 0.10%p)보다 작다.** 2.38%를 "2.4% 확정"으로 읽는 것은 오독이다.
- **TD Securities는 자기 전망에 상방 편향 경고를 붙였다** — "관세 노출 품목의 대폭 하락을 가정하고 있어 상방 리스크"라고 명시. 즉 낮은 전망치들이 공통 가정을 공유할 수 있다.
- **연준 내부는 인플레가 안 꺾인다고 본다.** 7월 FOMC에서 Hammack·Kashkari·Logan 3인이 인상 지지로 반대표(방향 일치 3인 반대는 2016-09 이후 처음), 의사록은 리스크 상방 편향으로 기록.
- **PCE−CPI 괴리 역전.** core PCE 3.4% vs core CPI 2.5%로 약 90bp 벌어져 있고, PIMCO는 1985년 이후 최대급 역전이라고 분석. core CPI의 낮은 수치가 측정 차이의 산물이면 축소 방향 서프라이즈 리스크가 있다.
- **시장은 확실시하지 않는다.** Kalshi에서 "정확히 2.4%"에 약 43%가 걸려 있고, ≤2.3%를 더해도 55~62% 수준이라는 해석이 가능하다. 최종체결 기준 0.74와 이 해석 사이에 폭이 있으며, 유동성이 얇아 어느 쪽도 강한 증거가 아니다.
- 리서치가 **검색 상위 결과 다수를 오염원으로 판정**했다: "컨센서스 core 2.5%" 인용 상당수가 7월분 프리뷰이거나 2025년 9월 기사였다. Morningstar 인용 건(Natixis·GS core +0.36%/YoY 3.13%)은 2025년 기사일 가능성이 높아 **[미검증]으로 배제**했다. "0.2% MoM AND 2.5% YoY" 조합은 지수 산술상 내적 모순이다.

**반대증거를 반영한 순효과는 이미 [2]에서 −18%p(절벽 −6, 계절성 −5, 서비스 −5, 노이즈 −2)로 계상됐다.** 데블스 애드버킷의 권고 밴드는 55~70%였고 최종 65%는 그 안에 있다.

## [6] 최종 출력

- **확률: 65%** · 80% 신뢰구간 **[52, 77]**
- 시장내재 74% 대비 **−9%p** — **기록 전용**이다. P3 게이트(해소 50문항·Brier<0.18) 미통과 상태이므로 edge 시그널로 쓰지 않는다.

**핵심 근거 3줄**
1. 판정은 "8월 SA core MoM < 0.282%" 하나로 환원되고, 6개 독립 추정(나우캐스트·컨센서스·GS·RBC·TD·WF)이 평균 0.225%로 전부 임계 아래에 있다.
2. 임계 미만 base rate가 최근 10개월과 최근 10개 8월에서 모두 70%로 일치하며, 롤오프되는 2025-08(+0.3009%)이 임계보다 높아 base effect가 순풍이다.
3. 그럼에도 여유가 YoY 기준 0.028%p뿐이고 8월 잔여 계절성(최근 4년 평균 0.314%)과 서비스 상방(ISM 물가 4년 최고·OER 재가속·항공료)이 실재해 70%에서 65%로 내렸다.

**확률을 바꿀 관찰 지표 2개**
1. **2026-09-10 08:30 ET 8월 PPI** — 특히 항공여객·의사서비스 세부(CPI/PCE 브릿지 항목). core PPI가 7월(+0.4%)처럼 강하면 하향, 둔화하면 상향.
2. **Cleveland Fed 나우캐스트 9/10 갱신값** — 현재 core MoM 0.20%/YoY 2.38%. 0.24% 이상으로 올라오면 쿠션이 사라져 55% 부근까지 하향해야 한다.

---

## 사전등록 대비 — 예상확률이 크게 빗나갔다 (기록 의무)

C5 사전등록(`questions/portfolio_prereg_v1.yaml`)은 이 질문의 **예상 확률을 22%로 고정**했고, 첫 예측 실제값은 **65%**다. 괴리 **43%p**로 사전등록의 기록 임계(15%p)를 크게 넘는다.

**왜 틀렸나.** 등록 시점에 "core가 2.6%→2.5%로 왔으니 2.4%까지 한 계단 더는 어렵다"고 인쇄값만 보고 추정했다. 실제로는 미반올림 7월 YoY가 **2.4783%로 이미 경계에서 0.028%p 위**였고, 컨센서스와 나우캐스트가 둘 다 2.4%를 가리키고 있었다. **지수 수준 산술을 하지 않고 인쇄값의 계단만 센 것이 오류의 원인**이다.

**예산 영향.** 예상 p=22%의 p(1−p)=0.1716이었으나 실제 p=65%는 **0.2275**로 사전등록의 개별 상한 **0.21을 초과**한다. 이 질문은 예외 슬롯이 아니므로 **예산 위반이 첫 예측에서 확정됐다**. 사전등록의 `recompute_on_actual: true`에 따라 대사표를 실제값으로 재계산해 보고하며, 예측 확률을 예산에 맞추는 조정은 하지 않는다 — 그것이 곧 캘리브레이션 조작이다.

---

**P0/P1 참고 의견 — 자금 결정의 단독 근거가 아닙니다.** (P3 게이트 미통과: 해소 7문항 / 50, Brier 0.1599)

## 출처

1. BLS 공개 API, 계열 CUUR0000SA0L1E (NSA core CPI 지수) — 2025-07 328.980 · 2025-08 329.970 · 2026-06 336.882 · 2026-07 337.133 (직접 취득 2026-09-09)
2. BLS 7월분 CPI 보도자료 (2026-08-12) https://www.bls.gov/news.release/archives/cpi_08122026.htm — headline 3.4% YoY/+0.1% MoM, core 2.5% YoY/+0.2% MoM
3. BLS CPI 발표 일정 https://www.bls.gov/schedule/news_release/cpi.htm — 2026-09-11 08:30 ET
4. Cleveland Fed Inflation Nowcasting (2026-09-08 갱신) https://www.clevelandfed.org/indicators-and-data/inflation-nowcasting — 8월 core MoM 0.20% / YoY 2.38%
5. Trading Economics 컨센서스 https://tradingeconomics.com/united-states/core-inflation-rate — core YoY 2.4%
6. Goldman Sachs 8월 CPI 프리뷰 (2026-09-09, 2차 경유) https://thedarksideoftheboom.substack.com/p/august-cpi-preview-goldman-sees-a — core +0.23% → 2.40% [부분 미검증]
7. RBC US Week Ahead (2026-09-04) https://www.rbc.com/en/economics/us-week-ahead/cpi-can-make-or-break-the-feds-holding-pattern/ — core +0.24% → 2.4%
8. TD Securities 코멘트 (2026-09-08, FXStreet 경유) https://www.fxstreet.com/news/united-states-core-inflation-stays-contained-as-goods-soften-td-securities-202609081917 — core +0.19%, 상방 편향 경고 [부분 미검증]
9. BLS CPI Table 2 상대중요도 (2026-07) https://www.bls.gov/news.release/cpi.t02.htm
10. ISM Services PMI 8월 (2026-09-04) https://www.prnewswire.com/news-releases/services-pmi-at-55-4-august-2026-ism-services-pmi-report-302868046.html — 물가지수 72.6
11. Manheim 중고차 지수 8월 (2026-09-08) https://www.coxautoinc.com/insights/manheim-used-vehicle-value-index-august-2026-trends/ — 208.2, MoM −0.9%
12. St. Louis Fed, 관세 효과 안정화 (2026-08-18) https://www.stlouisfed.org/on-the-economy/2026/aug/tariff-effects-inflation-stabilize-recent-months
13. BLS 건강보험 지수 방법론 (4월·10월만 계수 갱신) https://www.bls.gov/cpi/additional-resources/improvements-cpi-health-insurance-index.htm
14. BLS PPI 7월분 (2026-08-13) https://www.bls.gov/news.release/archives/ppi_08132026.htm — core PPI +0.4% MoM
15. BLS 고용상황 8월분 (2026-09-04) https://www.bls.gov/news.release/archives/empsit_09042026.htm — AHE +0.3% MoM, NFP +162k, 실업률 4.1%
16. CNBC, 7월 FOMC 3인 반대 (2026-07-29) https://www.cnbc.com/2026/07/29/fed-rate-decision-july-2026.html
17. CNBC, 7월 FOMC 의사록 (2026-08-19) https://www.cnbc.com/2026/08/19/fed-minutes-july-2026-officials-saw-need-for-rate-hike-if-inflation-doesnt-cool.html
18. Kalshi `KXCPICOREYOY-26AUG-T2.4` (2026-09-08 19:42 UTC 최종체결 0.26) https://kalshi.com/tag/core-cpi — P(YES)≈0.74 [유동성 얇음]
19. PIMCO, PCE−CPI 괴리 역전 https://www.pimco.com/us/en/insights/us-inflation-measures-tell-two-different-stories [부분 미검증]
20. Forbes, 제트유 가격 (2026-07-24) https://www.forbes.com/sites/suzannerowankelleher/2026/07/24/surging-jet-fuel-costs-higher-airfares/
21. CNN Business, BLS 표본 수집 축소·추정 비중 (2025-06-05) https://www.cnn.com/2025/06/05/economy/cpi-data-bls-reductions
