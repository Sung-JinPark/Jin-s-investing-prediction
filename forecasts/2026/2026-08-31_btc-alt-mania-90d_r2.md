---
forecast_id: 2026-08-31_btc-alt-mania-90d_r2
question_id: btc-alt-mania-90d
question_snapshot: "예측일로부터 90일 이내에 (a) BTC가 사상 최고가(종가 기준)를 경신하고 AND (b) 알트코인 시가총액(TOTAL2)이 윈도우 시작일 대비 +50% 이상 상승하는 두 조건이 모두 발생할 확률은?"
timestamp: 2026-08-31 19:10 KST
phase: P1
model: claude-opus-5 (Claude Code)
prompt_version: reasoning_core_v1
probability: 4
ci80: [1, 10]
window_end: '2026-11-29'
snapshots:
  btc_now: "$78,144.55 (2026-08-31 UTC 일간 종가, Coinbase BTC-USD). 교차확인 CoinGecko $78,022"
  btc_ath_close: "$124,720.09 (2025-10-06 종가, Coinbase) — 경신에 **+59.6%** 필요. 현재 ATH 대비 −37.34%"
  total2_now: "$1,038.1B (TradingView CRYPTOCAP:TOTAL2, 2026-08-31) — r1과 동일하게 TradingView 기준으로 판정. 교차: CoinMarketCap $1,053.0B · CoinGecko 파생 $1,056.8B"
  total2_target: "$1,557.2B (= $1,038.1B x 1.5)"
  btc_realized_vol: "30일 42.28% · 90일 38.18% (자체 산출, The Block 30일 43.75%와 정합)"
market_implied: null
edge: null
sources_count: 12
---

## [0] 질문 검증

판정 가능. rolling 90일이므로 이번 윈도우는 **2026-08-31 ~ 2026-11-29**로 확정한다. 두 조건의 **AND**이며, TOTAL2 기준값은 r1과 동일하게 TradingView로 고정한다(집계사 간 $1,038B~$1,057B 편차 존재).

r1(2026-07-08) 대비 **조건 (a)가 상당히 쉬워졌다.** 당시 BTC는 $63,229로 ATH 대비 −49.9%(+99.7% 필요)였는데, 지금은 $78,145로 **−37.3%(+59.6% 필요)**다. 반대로 조건 (b)는 기준값이 $893B에서 $1,038B로 올라 목표가 $1.34T에서 **$1.56T**로 높아졌다.

## [1] Outside View — base rate (anchor: 3%)

**조건 (a) — 90일 내 BTC 종가 ATH 경신.** Coinbase 일간 종가 전체 이력(2015-07-20~2026-08-31, 3,971개 중첩 윈도우) 기준 드로다운 구간별:

| ATH 대비 | 90일 내 신 ATH | n |
|---|---|---|
| 0~2% 하회 | 92.3% | 336 |
| 10~20% | 67.6% | 549 |
| 20~30% | 59.4% | 406 |
| **30~45% ← 현재 −37.3%** | **25.4%** | 500 |
| 45~60% | 4.6% | 712 |
| 무조건부 | 39.8% | 3,971 |

결정론 모델 교차확인: 90일 실현변동성 38.18%, 필요 상승 +59.6%는 **2.47 시그마**. 무드리프트 배리어 터치 확률 **약 1.4%**. 실증 버킷(25.4%)과 GBM(1.4%)의 괴리가 큰데, 버킷이 −30%~−45%를 뭉뚱그려 −30% 근처 사례가 성공을 주도하기 때문이다. 현재는 버킷 하단부라 실증값을 그대로 쓰면 과대평가다. **P(a) ≈ 6%**로 둔다(GBM 위, 버킷 아래).

**조건 (b) — 90일 내 TOTAL2 +50%.** CoinMarketCap 일간(2013~2026, 4,781 윈도우): 전체 24.6% / 2018년 이후 15.2% / **2022~2026년 6.8%** / TOTAL2가 ATH 대비 30~60% 하회 조건부(현재 −41.2%) 27.8%.

**결합.** 두 조건은 독립이 아니다 — BTC가 +59.6% 급등하는 국면이면 알트도 대체로 따라간다. **P(b | a) ≈ 0.6**로 본다(2026년은 BTC 주도장이라 과거보다 낮게). 0.06 x 0.6 = **3.6% → anchor 3%**.

## [2] Inside View — 보정 (항목별)

| 증거 | 방향 | 조정 |
|---|---|---|
| 8월 반등 실적 — 8/18 종가 $64,681 → 8/21 $78,326(**+21%, 3일**). 사상 최대급 숏 청산($2.74~3.0B) 동반. 크립토는 90일에 +60%가 물리적으로 불가능한 자산이 아니다 | 상승 | +2%p |
| 정책 촉매 — 2026-08-19 백악관 크립토 서밋에서 트럼프가 CLARITY Act 통과 촉구, 정부의 BTC "상당량" 매입 논의 언급. SEC가 크립토 ETP 일반 상장기준 승인(승인기간 240일→75일) | 상승 | +1%p |
| 8월 ETF 자금 +$3,322M로 2026년 최강월 | 상승 | +1%p |
| **알트시즌이 아니다** — CMC Altcoin Season Index **26~27**(2026-08-31), 임계 75. **최근 96일 중 75 도달 0일**. TOTAL3 3개월 +0.25%, OTHERS −1.92%로 롱테일 알트는 횡보~하락 | 하락 | −2%p |
| 2026년 ETF 누적은 여전히 **순유출 −$1,895M**이고 8/28엔 9거래일 연속 유입이 끊기며 −$202M | 하락 | −1%p |
| 역사적 회복 주기 — 사이클 정점에서 신 ATH까지 통상 **2~3년**(CoinGecko). ATH가 329일 전이므로 2027년 말~2028년을 시사 | 하락 | −1%p |
| CLARITY Act 2026년 통과 확률 Bernstein 추정 약 30%로 정체 | 하락 | 0%p |

순 조정 **+1%p** → 4%.

## [3] 분해 트리

| 경로 | 확률 | (a)AND(b) 조건부 | 기여 |
|---|---|---|---|
| 정책 촉매 + 유동성 유입으로 대세 상승 재개 | 0.10 | 0.30 | 3% |
| BTC 주도 상승하나 알트 미동조(현 레짐 연장) | 0.35 | 0.02 | 1% |
| 횡보 | 0.40 | 0.00 | 0% |
| 재하락 | 0.15 | 0.00 | 0% |
| 합계 | | | **4%** |

## [4] Premortem — 틀릴 이유 3가지

1. **크립토의 꼬리를 과소평가한 경우.** 8/19~8/21에 3일 만에 +21%가 나왔다. 이런 사건이 두세 번 연쇄하면 +59.6%는 가능하고, 그 국면에서는 알트도 함께 튄다. 4%는 그 시나리오를 0.10x0.30으로만 반영했다.
2. **정부 BTC 매입이 현실화되는 경우.** 트럼프가 언급한 "상당량" 매입이 실제 정책이 되면 수급이 구조적으로 바뀐다. 기저율에 없는 조건이다.
3. **반대 방향 — 4%도 높은 경우.** GBM은 1.4%, 알트시즌 지수는 96일 연속 임계 미달, ETF는 연간 순유출이다. 두 조건 AND라는 점을 감안하면 2%가 맞을 수도 있다(r1이 그렇게 봤다).

## [5] 최종 출력

- 최종 확률: **4%** (80% CI: 1~10%)
- 직전 대비: r1 2% → r2 4% (**+2%p**). BTC가 ATH 대비 −49.9%에서 **−37.3%**로 올라와 조건 (a)의 필요 상승폭이 +99.7%에서 **+59.6%**로 줄어든 것이 주된 이유다. 조건 (b)는 오히려 목표가 $1.34T에서 $1.56T로 높아져 상쇄했다.
- **핵심 근거 3줄**:
  1. 두 조건 AND이며, BTC는 여전히 90일 내 **+59.6%**(2.47 시그마)가 필요하다.
  2. 드로다운 −37.3% 버킷의 실증 기저율 25.4%는 버킷 상단 사례가 주도한 값이라 현 위치에 그대로 쓸 수 없고, GBM은 1.4%다.
  3. 알트시즌 지수가 26으로 **96일 연속 임계(75) 미달**이라 조건 (b)의 독립적 성립 가능성이 낮다.
- **관찰 지표 2개**:
  1. **CMC Altcoin Season Index 50 돌파** — 알트 동조 신호. 돌파 시 10% 이상으로 상향.
  2. **BTC $100,000 회복** — ATH까지 −20% 이내로 좁혀지면 버킷이 바뀌어 15% 이상으로 상향.

> **P1 참고 의견 — 자금 결정의 단독 근거 아님** (P3 게이트: 해소 50문항+ & Brier < 0.18 통과 전).

## 출처 목록

- Coinbase Exchange BTC-USD 일간 캔들 API (현재가·ATH 종가·기저율 산출 원자료, 2015-07-20~2026-08-31) — https://api.exchange.coinbase.com/products/BTC-USD/candles
- CoinGecko BTC (교차확인 $78,022, ath_change −38.12%) — https://api.coingecko.com/api/v3/coins/bitcoin
- TradingView CRYPTOCAP:TOTAL2 (판정 기준 $1,038.1B) — https://www.tradingview.com/symbols/TOTAL2/
- CoinMarketCap altcoinMarketCap 일간 시계열 (30일·90일 전 값, TOTAL2 기저율 산출) — https://coinmarketcap.com
- The Block 30일 BTC 실현변동성 43.75% (2026-08-30) — https://www.theblock.co/data/crypto-markets/prices/annualized-btc-volatility-30d
- Farside Investors 미국 현물 BTC ETF 일간 자금흐름 — https://farside.co.uk/bitcoin-etf-flow-all-data/
- Bloomberg 2026-08-19 숏 청산·급등 — https://www.bloomberg.com/news/articles/2026-08-19/bitcoin-surges-most-since-march-ahead-of-white-house-meeting
- CoinDesk 2026-08-20 ($3B 숏 청산) — https://www.coindesk.com/markets/2026/08/20/bitcoin-breaks-out-of-six-week-range-tops-usd71-000-as-usd3-billion-in-shorts-get-wiped-out
- Washington Times 2026-08-19 백악관 크립토 서밋 — https://www.washingtontimes.com/news/2026/aug/19/donald-trump-hosts-crypto-execs-white-house-sec-guidelines-release/
- Cryptonomist 2026-08-03 CLARITY Act 통과 확률 약 30%(Bernstein) — https://en.cryptonomist.ch/2026/08/03/clarity-act-crypto-regulation-4/
- CoinGecko Research 사이클 정점→신 ATH 통상 2~3년 — https://www.coingecko.com/research/publications/when-bitcoin-all-time-highs
- 저장소 내부: `forecasts/2026/2026-07-08_btc-alt-mania-90d_r1.md` (직전 2%)

**[미검증]** 표기: CMC Altcoin Season Index 26~27과 96일 연속 임계 미달은 2차 집계 경유. 기저율의 90일 윈도우는 크게 중첩되므로 유효 표본은 약 4개 사이클 수준이며, CLAUDE.md §5에 따라 **base rate 참조이지 캘리브레이션 표본이 아니다**.
