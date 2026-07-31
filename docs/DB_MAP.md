# DB 스택 매핑 (Data Layer Map)

> 목적: AI 슈퍼포캐스터의 **데이터 축적 계층**을 한눈에 — 어떤 DB가, 무엇을, 얼마나, 어디까지 쌓고 있는지.
> 갱신: 실측 스냅샷 기준. 재생성은 `cd dualdb && python -c "..."` 조회로 확인.
> 최종 실측: 2026-07-31 (해소 원장 6행·entity 46·event 48 반영).

## 0. 큰 그림 — 2개 SQLite + 플랫파일 진실원장

```
① dualdb/db/dualdb.sqlite   혁신사이클 비교 DB (20 테이블). git추적 X, ingest/derive로 재구축.
② db/index.db               ai_fc 파생 인덱스 (gitignore). sync --rebuild로 재구축.
③ 플랫파일(진실의 원천)      forecasts/ · calibration/ledger.csv · data/ml_history/*.jsonl · data/base_rates/
                            → ①②는 파생/캐시, ③이 원본. 불변성 규칙은 ③에 적용.
```

원칙: **①②는 언제든 버리고 재생성 가능. ③은 append-only·불변.** 채점·게이트 판정의 근거는 항상 ③.

## 1. ① dualdb.sqlite — 5개 레이어

### L1 · 원천 가격/매크로 (raw, 라이브 최신)
| 테이블 | 행수 | 범위 | 내용 |
|---|--:|---|---|
| `price_daily` | 285k | 1970-01 ~ 최신 | 32 종목/지수 OHLCV (Yahoo) |
| `macro_daily` | 94k | 1954-07 ~ 최신 | VIX·DFF·DGS10/2·T10Y2Y·HY스프레드·NFCI (FRED) |
| `macro_monthly` | 9.2k | **1854-12** ~ 최신 | FEDFUNDS·CPI·UNRATE·USREC·Dow(1914+)·Shiller S&P(1871+) |
| `valuation_monthly` | 1.8k | **1871-02** ~ 2023-09 | Shiller CAPE·PE·PS |
| `factor_monthly` | 1.2k | **1927-01** ~ 최신 | Fama-French 5팩터 + Momentum |
| `margin_debt_monthly` | 14 | 2025-05 ~ 최신 | FINRA 신용융자 (얇음·신규) |

### L2 · 파생 (derived — era_id 제네릭, ingest 후 `derive`로 재계산)
| 테이블 | 행수 | 커버 |
|---|--:|---|
| `derived_daily` | 234k | **6 일간시대**: ai·dotcom·japan1989·crypto2021·biotech2015·niftyfifty1972 (vol/drawdown/rsi/200dma/norm) |
| `correction_episode` | 41 | **8 시대 전부** — 조정 base-rate 라이브러리 |
| `alignment` | 880 | 8 시대 정렬 (1901~2028) |

**조정 깊이 base rate (8시대 최심, 월/일 기준):**
다우1929 **−87%** · 일본1989 −80% · 닷컴 −75% · 크립토 −73% · 니프티50 −46% · 전기1900 **−38%(1907 패닉)** · 바이오 −34% · AI −27%(현재진행)

### L3 · 시대 메타 (seeds.csv 원천, `ingest`로 멱등 재적재)
| 테이블 | 행수 | 커버 | 비고 |
|---|--:|---|---|
| `era` | 8 | 8시대 전부 | 앵커·정점·바닥 메타 |
| `entity` | 46 | **6 시대** | 트윈 12(dotcom↔ai, is_twin=1) + 아날로그 4시대 대장주·사망종목(is_twin=0) |
| `event` | 48 | **6 시대** | 마일스톤(peak/crash/fed/ipo/macro/bottom) + 출처 URL |
| `capex_buildout_annual` | 11 | ai·dotcom | 인프라 build-out 전용(설치기 프레임) — 非인프라 시대 미적용 |
| `dotcom_casualty` | 25 | dotcom | 사망종목 대장 (붕괴 base rate 하한) |
| `role`·`ipo_annual`·`ritter` | 10·14·- | 혼합 | 트윈 역할 택소노미·IPO 통계 |

> **설계 주의**: `role` 택소노미(anchor·equip·memory·foundry·network·overbuild·power…)와 `capex`는
> **닷컴↔AI 반도체 트윈 비교 전용** 스캐폴드다. 아날로그 4시대 entity는 일반화 가능한
> anchor/platform/app만 쓰고 `is_twin=0`으로 격리 — 트윈 base rate(Q14) 오염 방지.

### L4 · 수치모델 산출 (`model_run` — append, run_id 증가)
9회 실행: `knn_analog`·`dtw_daily`·`lppl_walkforward`·`twins_q14`.
전부 **결정론 수치모델**(백테스트 금지 예외, DECISIONS 8-6) — base rate 참조용, 매매 신호 아님.

### L5 · 미착수/얇음 (Phase 2 대기)
| 테이블 | 상태 | 사유 |
|---|---|---|
| `sentiment_weekly` | 0행 | AAII 심리 — k-NN 상태벡터 결측 차원(R-4). 무료 데이터 확보 시. |
| `fundamentals_annual` | 0행 | EDGAR 재무 — 미착수 |
| `cycle_compare` | 0행 | 구 2열 비교 → `alignment` long-format으로 대체됨(사실상 폐기) |

## 2. ③ 플랫파일 — 예측/채점 진실원장

| 레이어 | 상태 | 규칙 |
|---|---|---|
| `questions/registry.yaml` | 38 질문 (active 34 / resolved 4) | 판정기준 첫 예측 후 변경 금지 |
| `forecasts/YYYY/` | 39 불변 기록 | **생성 후 수정·삭제 절대 금지** |
| `calibration/ledger.csv` | **6 해소** (대표 5, 1건 research=failed 제외) | append-only |
| `calibration/benchmark_ledger.csv` | LLM vs ML vs 시장 3자 병행 | 표시 전용(게이트 무관) |
| `data/ml_history/2026.jsonl` | market=3·ml=3·context=7 | append-only, DB 재구축 원천 |
| `data/base_rates/` | 수동 6 + `*_auto.md` 5 | outside view 라이브러리 |

**해소 표본 (2026-07-31):** spx-up(0.25)·soxx-up(0.29)·fomc-07-29 r1~r4(0.0225/0.0009/0.0144/0.0036).
대표 Brier ≈ **0.116** (n=5). FOMC는 동결(9-3, 3명 인상 반대의견) → 4회차 전부 정확.

## 3. 데이터 → 예측 흐름 (정합도 경로)

```
raw(L1) ─┬─ derive → derived_daily·correction_episode(L2) ─┐
         │                                                  ├─ models → model_run(L4)
         └─ french/shiller → factor·valuation(L1) ──────────┘        │
                                                                      ▼
                          context_bridge → data/ml_history(kind:context) ─┐
                                                                          ▼
   base_rates.ml_digest ── (최신 ml/context/market run 주입) → 프롬프트 evidence → 예측
                          ※ 매핑 확률 없이 base rate 맥락만 (R-4 앵커링 방지)
```

**주의**: `entity`/`event`(L3)는 현재 **자동 예측 digest에 배선되지 않음** — 대시보드 타임라인·
트윈 모델(Q14)·향후 확장용 사료(史料)다. 정합도(예측 정확도)에 직접 기여하는 경로는
L2(조정·k-NN)·L1(팩터·레짐)뿐.

## 4. 건강 진단 (2026-07-31)

- ✅ **정량 레이어 매우 건강**: 가격/매크로/파생/팩터가 다중시대·심층역사(~1854)·최신까지 축적.
  조정 에피소드 41개·8시대 = 두꺼운 base-rate 라이브러리.
- ⚠️ **얕은 곳**: `sentiment_weekly`(심리 결측 차원 미해소), `fundamentals_annual` 공백.
  entity/event는 채웠으나 자동 예측 파이프라인 미배선.
- ❗ **진짜 병목 = DB가 아니라 채점 회전율**: 예측 39·질문 38은 쌓였으나 해소 **6건**.
  P3 게이트(50 해소 + Brier<0.18)까지 표본이 병목. `resolve` 회전이 시스템 목표의 실제 율속단계.

## 5. 재생성 명령

```bash
cd dualdb && python -m dualdb ingest    # L1·L3 원천 적재 (네트워크)
cd dualdb && python -m dualdb derive     # L2 파생 재계산
cd dualdb && python -m dualdb models      # L4 수치모델 실행
cd dualdb && python -m dualdb context     # context run → ml_history append
cd src && python -m ai_fc sync --rebuild  # ② index.db 재구축
```
