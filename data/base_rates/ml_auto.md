# Base Rates — 오픈웨이트 ML 자동 산출 (추론 전용, 재생성 가능)

> `python -m ai_fc ml` — Chronos(시계열)·FinBERT(감성), 전부 로컬 CPU 추론.
> 생성: 2026-09-21 · 예측 지평 14주(연말) · **학습 없음 — ML 게이트 준수**.
> 모델 결합은 고정 중앙값 (가중 학습 아님 — **모델 2개 구간에서는 평균과 동일**하며
> 중앙값의 이상치 방어는 3개 이상부터 유효, AUDIT-260715 D-8). zero-shot 분포는
> 이벤트 캘린더를 모르는 무조건부 추정 — 참조선일 뿐.

## Chronos 연말 분위수 예측 — Bolt·Chronos-2 중앙값 결합 (컨텍스트 194주)
- **^IXIC**: 중앙값 27,239 (+2.7%) · 50% 밴드 [26,158, 28,218] · 80% 밴드 [24,971, 29,190]
- **SOXX**: 중앙값 558 (+4.7%) · 50% 밴드 [499, 617] · 80% 밴드 [438, 682]
- **^VIX** (13주 지평): 중앙값 16 (+7.8%) · 50% 밴드 [14, 18] · 80% 밴드 [13, 22]
- Chronos-2(120M) 공변량 조건부 + Bolt 결합 — ^IXIC·SOXX에 past-only 공변량(VIX·TNX) 적용, 미래 공변량 미사용

## 시스템 질문 임계값 매핑 (오픈웨이트 vs LLM 추론 비교용)
| 질문 | 임계값 | 앙상블 | 모델별 |
|---|---|---|---|
| F1 연말 ATH 경신 (^IXIC) | 27,093.90 | **81%** | t5 77% · gbm 86% (보정값 — raw 주간: t5 68% · gbm 80% · 보정: t5 브리지·gbm 일간, 분위수 종점 53%는 하한) |
| F2 −10% 터치 8~10월 (^IXIC) | 24,384.51 | **13%** | t5 15% · gbm 11% (보정값 — raw 주간: t5 10% · gbm 9% · 보정: t5 브리지·gbm 일간, 분위수 종점 7%는 하한) |
| F3 연말 > 7/9 종가 (^IXIC) | 26,206.89 | **71%** | bolt 71% · c2 77% · gbm 70% |
| SOXX 연말 −15% (≤468.94) | 468.94 | **17%** | bolt 17% · c2 18% · gbm 6% |
| VIX 25 터치 (90일) | 25.00 | **13%** ⚠불일치 | t5 0% · gbm 26% (보정값 — raw 주간: t5 0% · gbm 16% · 보정: t5 브리지·gbm 일간, 분위수 종점 7%는 하한) |

- 사용법: 앙상블 참조 확률과 시스템 rN 확률의 괴리 15%p+ 는
  `due`에 divergence로 표시된다 (재예측 후보 — 자동 실행 없음, 판단은 사람).

## FinBERT 헤드라인 감성 (GDELT)
| 피드 | 헤드라인 수 | 감성 지수 [-1,+1] | Δ7d |
|---|---|---|---|
| ai-semis | 0 | +0.000 | -0.102 |
| fed-macro | 25 | -0.073 | +0.020 |
| market | 25 | +0.133 | +0.455 |
| nvda | 25 | -0.044 | -0.111 |
| memory | 4 | +0.097 | +0.376 |
- **종합**: +0.010 (0 = 중립)
- 최근 부정 헤드라인 샘플:
- The Bond Market Is Rattled, and History Says That Could Be a Warning Signal to Investors
- The Bond Market Is Rattled, and History Says That Could Be a Warning Signal to Investors
- The Bond Market Is Rattled, and History Says That Could Be a Warning Signal to Investors
- Will There Be a Stock Market Crash in Year 6 of Donald Trump Presidency? One Historically Flawless Metric Paints a Worrisome Picture.
- 출처: The GDELT Project — https://www.gdeltproject.org/

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
