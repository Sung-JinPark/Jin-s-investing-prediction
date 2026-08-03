# 교차자산 예측 그래프 + AI 자본사이클 레짐 지도 설계서

작성일: 2026-08-03 KST  
상태: Graph 1 구현 완료 / Graph 2 구현 전 승인 설계  
원칙: 참고 의견이며 투자 자문이 아니다. 서로 다른 확률 공간을 산술 결합하지 않는다.

## 1. 결론

첫 번째 그래프는 **BTC·NASDAQ·Realty Income(O)의 AI 충격 전이 지도**로 구현한다.
가격 단위가 전혀 다른 세 자산은 TradingView의 `Indexed to 100` 방식처럼 비교 시작점을
100으로 통일한다. 닷컴버블 비교와 미래 충격 시나리오는 같은 화면에서 전환하되,
과거 실측과 미래 조건부 경로를 결합하거나 확률 가중하지 않는다.

두 번째 그래프는 또 하나의 가격선이 아니라 **AI Capital Cycle Regime Map**으로 설계한다.
핵심 질문은 “AI 투자 속도를 실제 수익화와 자금조달 여건이 계속 감당할 수 있는가?”다.
이 레짐 지도가 첫 그래프의 `동반 디레버리징`과 `완화·순환` 중 어느 경로가 강화되는지
선행 설명하게 한다.

## 2. Graph 1 — BTC · NASDAQ · Realty Income 전이 지도

### 2.1 실측 결론

공개 월말 종가를 2000-12=100으로 맞춰 2005-12까지 계산한 결과는 다음과 같다.

| 구간 | NASDAQ 가격 | Realty Income 가격 | Realty Income 총수익 proxy |
|---|---:|---:|---:|
| 2000-12 → 2005-12 | -6.7% | +87.3% | +160.8% |

연도별 결과:

| 연도 | NASDAQ 가격 | O 가격 | O 총수익 proxy |
|---:|---:|---:|---:|
| 2001 | -21.1% | +18.2% | +28.1% |
| 2002 | -31.5% | +19.0% | +27.5% |
| 2003 | +50.0% | +14.3% | +21.6% |
| 2004 | +8.6% | +26.5% | +33.9% |
| 2005 | +1.4% | -14.5% | -9.4% |

따라서 “닷컴 붕괴 때 O가 올랐다”는 관찰은 2001~2004에는 강하게 성립한다. 다만
2005년에는 반대로 하락했다. 기술주 자금이 REIT로 자동 이동했다기보다 다음 요인이 함께
작용한 결과로 해석해야 한다.

- 월 배당과 배당 재투자 효과
- 장기 임대 현금흐름과 당시 O의 사업 확장
- 2001년 침체 뒤의 금리·경기 국면
- 2004년 이후 긴축 전환에 따른 REIT 민감도 변화

O의 2005 Form 10-K에는 2001~2005 주당 배당이 지속 증가한 사실이 기록되어 있다.
한편 Nareit의 장기 연구는 REIT 수익이 금리 방향 하나로 결정되지 않고, 성장·경기·신용
국면에 따라 관계가 바뀐다고 지적한다. 그래서 미래 O 경로는 “금리 하락=무조건 상승”으로
설계하지 않는다.

### 2.2 Bitcoin에 대한 현재 판단

Bitcoin은 2009년에 시작했기 때문에 2001~2005 구간에 선을 그리지 않는다. UI에
`BTC DATA GAP · 정상 결측`을 표시한다. 이 결측을 2017·2020의 다른 데이터를 이어
붙여 채우면 잘못된 역사 비교가 된다.

현재 스냅샷(시장 기준 2026-07-31)의 실측 진단:

- 최근 60 공통거래일 BTC–NASDAQ 수익률 상관: **0.442**
- 최근 60 공통거래일 O–NASDAQ 수익률 상관: **-0.380**
- 최근 5년 NASDAQ 일간 하위 10% 구간 BTC downside beta: **1.599**
- 같은 구간 O downside beta: **0.471**

IMF 연구는 2020년 이후 crypto와 글로벌 주식, 특히 기술주·소형주의 동조화가 강화됐고
긴축 충격에 crypto가 주식과 비슷하거나 더 민감하게 반응했다고 분석한다. 따라서 AI 버블이
갑자기 터지는 첫 국면의 기본값은 **BTC도 함께 하락**이다. BTC의 차별 반등은 그 다음에
금리 인하, 달러 유동성 확대, 위험선호 회복이 실제로 관측되는 조건부 경로다.

### 2.3 세 개의 12개월 조건부 경로

| 충격 경로 | M+12 NASDAQ | M+12 Bitcoin | M+12 O | 핵심 조건 |
|---|---:|---:|---:|---|
| 동반 디레버리징 | 82.0 | 70.2 | 97.5 | 신용경색이 정책 완화보다 빠름 |
| AI 조정 후 완화·순환 | 91.0 | 130.6 | 123.8 | 초기 투매 뒤 장기금리·달러 유동성 전환 |
| 소프트랜딩·자산 순환 | 112.0 | 137.2 | 113.7 | 이익 성장·신용시장 안정 유지 |

숫자는 현재=100인 sensitivity index다. 목표가격, 기대수익, 사건 확률이 아니다. NASDAQ
충격 경로에 최근 5년 downside beta를 제한 범위로 적용하고, 명시한 유동성·금리 offset을
더했다. 시나리오별 out-of-sample 표본이 충분하지 않아 가중치는 **가중치 미산출
(충격 유형별 캘리브레이션 부족)** 상태로 보존하며 `null`을 화면에 노출하지 않는다.
O 미래선에는 현금배당을 포함하지 않는다.

### 2.4 구현된 데이터 계층

```text
Yahoo chart API
  ├─ ^IXIC daily/monthly close
  ├─ BTC-USD daily adjusted close
  └─ O daily/monthly close + adjusted close
          │
          ▼
src/ai_fc/cross_asset.py
  ├─ 공통 거래일 정렬
  ├─ 60d/252d 상관
  ├─ 252d beta / 5y downside beta
  ├─ 2001~2005 가격·총수익 proxy
  └─ 3개 조건부 12개월 전이 경로
          │
          ▼
data/cross_asset/
  ├─ cross_asset_latest.json
  └─ archive/YYYY-MM-DD.json
          │
          ▼
read-model.cross_asset → 시장전망 03 자산 전이
```

자동 갱신은 `python -m ai_fc cross-asset`이며 일일 시장 시나리오 workflow와 주간
OpenAI investing workflow 양쪽에 연결한다. 가격 계산 자체에는 OpenAI API 비용이 들지 않는다.

## 3. Graph 2 — AI Capital Cycle Regime Map

### 3.1 왜 이 그래프인가

가격 그래프만 추가하면 “왜 버블이 유지되거나 깨지는지”를 설명하지 못한다. 2026년 Fed
금융안정보고서는 AI 관련 위험으로 높은 주식 밸류에이션, 부채로 조달되는 자본지출, 노동시장
충격을 들었다. IMF는 AI 생태계를 builder·energy·chip·hardware·hyperscaler·neocloud·data
center 등으로 분해하고, leverage·liquidity·profitability·capex intensity·valuation을 함께
봐야 충격 증폭을 판단할 수 있다고 분석한다. IEA는 전력·그리드·변압기·칩 공급 제약이 실제
투자 속도를 제한한다고 본다.

따라서 두 번째 그래프는 다음 네 개 질문에 답해야 한다.

1. Capex 증가를 AI/Cloud 매출과 FCF가 따라가고 있는가?
2. 투자가 현금흐름이 아니라 채권·private credit·순환금융에 더 의존하는가?
3. 전력·그리드·장비 병목이 매출 인식 시점을 늦추는가?
4. 위 세 변화가 높은 밸류에이션·시장 집중도와 동시에 악화되는가?

### 3.2 시각 구조

메인 시각은 시간축 선 그래프가 아니라 2차원 레짐 지도다.

- X축: **Funding & Liquidity** — 왼쪽 `긴축/취약`, 오른쪽 `완화/풍부`
- Y축: **AI Monetization Coverage** — 아래 `Capex가 수익화보다 빠름`, 위 `수익화가 Capex를 커버`
- 원의 크기: **Valuation + Concentration pressure**
- 원의 테두리: **Physical bottleneck**(전력·그리드·칩·냉각)
- 8개 분기 trail: 과거 위치가 흐려지고 현재 위치가 가장 크고 선명함
- 점선 화살표: 4개 분기 조건부 예상 방향. fan은 충분한 vintage가 쌓인 뒤에만 추가

사분면 의미:

| 사분면 | 이름 | 해석 | Graph 1 연결 |
|---|---|---|---|
| 우상 | Funded expansion | 자금과 수익화가 모두 지지 | 소프트랜딩 강화 |
| 우하 | Crowded monetization gap | 돈은 많지만 회수력이 뒤처짐 | NASDAQ 조정, BTC 변동성 확대 |
| 좌하 | Deleveraging unwind | 회수력·자금조달 동시 악화 | 세 자산 동반 하락 강화 |
| 좌상 | Policy reflation / rotation | 실적은 버티고 자금이 재완화 | BTC·O 차별 반등 강화 |

### 3.3 신규 DB layer

모든 테이블은 `observation_period`, `available_at`, `source_url`, `source_fingerprint`,
`revision_vintage`를 가져 point-in-time 누수를 막는다.

| layer | 주기 | 핵심 필드 | 1차 출처 |
|---|---|---|---|
| `company_capex_quarterly` | 분기 | capex, D&A, FCF, debt issuance | SEC Companyfacts·10-Q/10-K |
| `ai_monetization_quarterly` | 분기 | cloud revenue, growth, margin, AI disclosure coverage | 회사 IR·SEC |
| `funding_conditions_daily` | 일 | real yield, term premium, IG/HY spread, VIX, DXY proxy | FRED·Fed |
| `market_structure_daily` | 일 | top-10 concentration, breadth, valuation spread | 공개 가격·지수 factsheet |
| `physical_capacity_monthly` | 월/분기 | data-center power, grid queue, equipment lead time | IEA·EIA·공식 사업자 자료 |
| `circular_finance_events` | 사건 | issuer, counterparty, debt/equity/lease, amount, confidence | SEC filing 원문 |
| `ai_regime_snapshot` | 월 | 축 점수, 구성요소, 결측률, quadrant | 위 layer의 파생 스냅샷 |

기업 집계는 MSFT·AMZN·GOOGL·META를 우선하되, 회사가 AI 매출을 분리 공시하지 않으면
추정치를 만들지 않고 `disclosure_coverage`를 낮춘다. NVIDIA 매출을 hyperscaler 수익화로
중복 집계하지 않는다. circular financing은 LLM이 숫자를 창작하지 않고 filing 문단을
분류하는 보조 역할만 하며 금액은 정형 공시에서 가져온다.

### 3.4 점수 계산

초기 버전은 학습 모델이 아니라 투명한 고정 규칙을 쓴다.

```text
Monetization coverage
  = 35% robust_z(cloud/AI-related revenue growth)
  + 25% robust_z(FCF margin)
  + 20% robust_z(earnings growth - capex growth)
  + 20% disclosure coverage penalty-adjusted breadth

Funding & liquidity
  = -25% robust_z(real 10y yield)
  - 25% robust_z(HY spread)
  - 15% robust_z(IG spread)
  - 15% robust_z(VIX)
  + 20% robust_z(real M2 / Fed liquidity impulse)

Bubble pressure (bubble size)
  = valuation percentile + concentration percentile
    + capex intensity percentile + circular-finance share
```

- 각 입력은 winsorize 후 rolling robust z-score(MAD)를 쓴다.
- 결측 component는 0으로 채우지 않고 분모에서 제외하며 coverage를 별도 표시한다.
- 가중치는 최소 12개 분기 vintage와 사전 정의된 방향성 검증 전에는 학습하지 않는다.
- 신호가 바뀐 이유를 component contribution waterfall로 항상 노출한다.
- 미래 화살표는 BVAR/상태공간 모형을 바로 champion으로 쓰지 않고 shadow로 병렬 검증한다.

### 3.5 UI/UX 사양

- 시장전망에 `04 AI 자본사이클` 탭을 추가한다.
- 기본 화면에는 현재 사분면, 8분기 trail, 가장 크게 움직인 component 3개만 보인다.
- hover/키보드 이동 시 해당 분기의 축 점수, capex, FCF, spread, 데이터 coverage를 읽는다.
- `왜 이동했나` 버튼으로 waterfall을 열고 source receipt까지 한 단계로 내려간다.
- `Graph 1 연결` 토글은 현재 레짐이 세 교차자산 경로 중 어느 경로를 강화/약화하는지만
  표시한다. 확률 숫자는 충분한 캘리브레이션 전까지 표시하지 않는다.
- 모바일은 사분면을 먼저, component table은 접힌 disclosure로 둔다.

## 4. 구현 우선순위

1. SEC Companyfacts와 FRED 원천 수집기 + append-only vintage 저장
2. 공시 coverage와 정합성 검증, 결측·revision UI
3. 고정 규칙 레짐 점수와 8분기 trail
4. 시장전망 `04 AI 자본사이클` 탭
5. 12개 분기 이상 누적 뒤 shadow 상태공간/BVAR 비교
6. directional hit-rate와 regime transition calibration 통과 후에만 fan/가중치 검토

## 5. 참고 근거와 벤치마크

- [Realty Income 2005 Form 10-K](https://www.sec.gov/Archives/edgar/data/726728/000110465906011663/a06-1908_110k.htm)
- [Realty Income annual results archive](https://www.realtyincome.com/investors/quarterly-and-annual-results)
- [IMF — The Crypto Cycle and US Monetary Policy](https://www.imf.org/-/media/files/publications/wp/2023/english/wpiea2023163-print-pdf.pdf)
- [IMF — Global Financial Stability Report, April 2026](https://www.imf.org/-/media/files/publications/gfsr/2026/april/english/text.pdf)
- [Federal Reserve — Financial Stability Report, May 2026](https://www.federalreserve.gov/publications/files/financial-stability-report-20260508.pdf)
- [Federal Reserve — Estimating Aggregate Data Center Investment](https://www.federalreserve.gov/econres/feds/estimating-aggregate-data-center-investment-with-project-level-data.htm)
- [IEA — Key Questions on Energy and AI](https://www.iea.org/reports/key-questions-on-energy-and-ai)
- [Nareit — REITs and Interest Rates](https://www.reit.com/investing/reits-and-interest-rates)
- [TradingView — Indexed to 100 comparison](https://www.tradingview.com/support/solutions/43000477709-when-comparing-symbols-i-only-see-detached-lines-on-the-chart/)
- [TradingView — Fundamental Graphs](https://www.tradingview.com/support/solutions/43000763376-fundamental-graphs-learn-to-chart-financial-metrics/)

## 6. 승인 기준

- Graph 1은 실측과 조건부 경로를 한 화면에서 명확히 분리한다.
- Bitcoin의 2001~2005 결측을 숨기거나 합성하지 않는다.
- O 가격과 총수익 proxy를 혼용하지 않는다.
- Graph 2는 원천 공시가 없는 AI 매출을 임의 추정하지 않는다.
- 모든 파생값은 source·available_at·vintage·결측률을 재구성할 수 있다.
- 확률 또는 fan은 out-of-sample 검증 전에는 표시하지 않는다.
