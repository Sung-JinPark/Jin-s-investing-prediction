# Base Rates — 오픈웨이트 ML 자동 산출 (추론 전용, 재생성 가능)

> `python -m ai_fc ml` — Chronos(시계열)·FinBERT(감성), 전부 로컬 CPU 추론.
> 생성: 2026-07-20 · 예측 지평 23주(연말) · **학습 없음 — ML 게이트 준수**.
> 모델 결합은 고정 중앙값 (가중 학습 아님 — **모델 2개 구간에서는 평균과 동일**하며
> 중앙값의 이상치 방어는 3개 이상부터 유효, AUDIT-260715 D-8). zero-shot 분포는
> 이벤트 캘린더를 모르는 무조건부 추정 — 참조선일 뿐.

## Chronos 연말 분위수 예측 — Bolt·Chronos-2 중앙값 결합 (컨텍스트 185주)
- **^IXIC**: 중앙값 26,411 (+3.5%) · 50% 밴드 [24,771, 27,998] · 80% 밴드 [23,040, 29,460]
- **SOXX**: 중앙값 499 (-4.4%) · 50% 밴드 [415, 598] · 80% 밴드 [340, 706]
- **^VIX** (13주 지평): 중앙값 18 (-4.3%) · 50% 밴드 [16, 21] · 80% 밴드 [14, 26]
- Chronos-2(120M) 공변량 조건부 + Bolt 결합 — ^IXIC·SOXX에 past-only 공변량(VIX·TNX) 적용, 미래 공변량 미사용

## 시스템 질문 임계값 매핑 (오픈웨이트 vs LLM 추론 비교용)
| 질문 | 임계값 | 앙상블 | 모델별 |
|---|---|---|---|
| F1 연말 ATH 경신 (^IXIC) | 27,093.90 | **74%** | t5 68% · gbm 80% (보정값 — raw 주간: t5 60% · gbm 75% · 보정: t5 브리지·gbm 일간, 분위수 종점 39%는 하한) |
| F2 −10% 터치 8~10월 (^IXIC) | 24,384.51 | **45%** | t5 52% · gbm 39% (보정값 — raw 주간: t5 47% · gbm 36% · 보정: t5 브리지·gbm 일간, 분위수 종점 22%는 하한) |
| F3 연말 > 7/9 종가 (^IXIC) | 26,206.89 | **55%** | bolt 52% · c2 55% · gbm 67% |
| SOXX 연말 −15% (≤468.94) | 468.94 | **24%** ⚠불일치 | bolt 24% · c2 57% · gbm 4% |
| VIX 25 터치 (90일) | 25.00 | **27%** ⚠불일치 | t5 4% · gbm 51% (보정값 — raw 주간: t5 1% · gbm 42% · 보정: t5 브리지·gbm 일간, 분위수 종점 13%는 하한) |

- 사용법: 앙상블 참조 확률과 시스템 rN 확률의 괴리 15%p+ 는
  `due`에 divergence로 표시된다 (재예측 후보 — 자동 실행 없음, 판단은 사람).

## FinBERT 헤드라인 감성 (Google News RSS, 무료)
| 피드 | 헤드라인 수 | 감성 지수 [-1,+1] | Δ7d |
|---|---|---|---|
| ai-semis | 25 | +0.102 | — |
| fed-macro | 25 | -0.093 | — |
| market | 25 | -0.321 | — |
| nvda | 25 | +0.067 | — |
| memory | 25 | -0.279 | — |
- **종합**: -0.105 (0 = 중립)
- 최근 부정 헤드라인 샘플:
- Semiconductor stocks trim losses as investors buy the dip - Yahoo Finance
- TSMC: The Market Is Punishing The Wrong AI Stock (NYSE:TSM) - Seeking Alpha
- Why the SOXS Semiconductor Bear ETF Is Surging as Chip Stocks Sell Off - 24/7 Wall St.
- Fed minutes: Officials deeply divided over future path of US inflation - AP News

## 한계 (정직 고지)
- Chronos는 계절성·자기상관만 학습한 무조건부 모델 — FOMC·미드텀 같은 이벤트 구조를 모름.
  시나리오 분석(v4·주간 차트)의 이벤트 조건부 경로와 '보완' 관계이지 대체가 아님.
- 경로 터치 확률은 보정값 기준 (T-11 상환, v2 WS3): GBM은 일간 스텝 재추정(근본 해결),
  T5는 주간 경로에 브라운 브리지 보정 — p=exp(−2·d0·d1/σ_w²), σ_w는 경로 내 추정 근사.
  raw 주간값 병기 (추적성). divergence 판정도 보정값 기준 (DECISIONS 기록).
  GBM(모수·정규수익률)과 T5(비모수·경험분포)는 추정 대상 분포의 정의가 달라
  결합값은 이질 모델 평균임.
- VIX에 대한 GBM은 평균회귀 특성을 무시한 참조치 — T5 경로와 병기해 상호 점검.
- FinBERT 감성은 동행~후행 지표 — 방향 예측이 아니라 현재 분위기의 정량화.
- 본 파일은 자동 생성본. 어떤 가중치도 갱신되지 않았음 (추론 전용).
  이력 원본: data/ml_history/*.jsonl (append-only).
