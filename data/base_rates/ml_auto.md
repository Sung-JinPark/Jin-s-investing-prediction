# Base Rates — 오픈웨이트 ML 자동 산출 (추론 전용, 재생성 가능)

> `python -m ai_fc ml` — Chronos(시계열)·FinBERT(감성), 전부 로컬 CPU 추론.
> 생성: 2026-10-26 · 예측 지평 ^IXIC 11주 · SOXX 9주 · ^VIX 13주
> (매핑 질문의 가장 먼 기한까지 — 연말 기본 9주) · **학습 없음 — ML 게이트 준수**.
> 모델 결합은 고정 중앙값 (가중 학습 아님 — **모델 2개 구간에서는 평균과 동일**하며
> 중앙값의 이상치 방어는 3개 이상부터 유효, AUDIT-260715 D-8). zero-shot 분포는
> 이벤트 캘린더를 모르는 무조건부 추정 — 참조선일 뿐.

## Chronos 연말 분위수 예측 — Bolt·Chronos-2 중앙값 결합 (컨텍스트 199주)
- **^IXIC**: 중앙값 26,513 (+2.1%) · 50% 밴드 [25,388, 27,513] · 80% 밴드 [24,166, 28,474]
- **SOXX**: 중앙값 492 (+2.8%) · 50% 밴드 [440, 545] · 80% 밴드 [391, 602]
- **^VIX** (13주 지평): 중앙값 18 (-9.2%) · 50% 밴드 [15, 21] · 80% 밴드 [14, 26]
- Chronos-2(120M) 공변량 조건부 + Bolt 결합 — ^IXIC·SOXX에 past-only 공변량(VIX·TNX) 적용, 미래 공변량 미사용

## 시스템 질문 임계값 매핑 (오픈웨이트 vs LLM 추론 비교용)
| 질문 | 임계값 | 앙상블 | 모델별 |
|---|---|---|---|
| F1 연말 ATH 경신 (^IXIC) | 27,093.90 | **64%** | t5 66% · gbm 63% (보정값 — raw 주간: t5 56% · gbm 52% · 보정: t5 브리지·gbm 일간, 분위수 종점 33%는 하한) |
| F2 −10% 터치 8~10월 (^IXIC) | 24,384.51 | **3%** | t5 5% · gbm 2% (보정값 — raw 주간: t5 5% · gbm 3% · 보정: t5 브리지·gbm 일간, 분위수 종점 7%는 하한) |
| F3 연말 > 7/9 종가 (^IXIC) | 26,206.89 | **53%** | bolt 50% · c2 66% · gbm 53% · c2꼬리(q01~q99 보간, 병기) 66% |
| SOXX 연말 −15% (≤468.94) | 468.94 | **36%** | bolt 36% · c2 42% · gbm 30% · c2꼬리(q01~q99 보간, 병기) 42% |
| VIX 25 터치 (90일) | 25.00 | **28%** ⚠불일치 | t5 0% · gbm 55% (보정값 — raw 주간: t5 0% · gbm 45% · 보정: t5 브리지·gbm 일간, 분위수 종점 12%는 하한) |
| VIX ≥30 터치 ~2026-11-30 (^VIX) | 30.00 | **8%** | t5 0% · gbm 17% (보정값 — raw 주간: t5 0% · gbm 11% · 보정: t5 브리지·gbm 일간, 분위수 종점 7%는 하한) |
| VIX ≤13 하회 ~2026-12-18 (^VIX) | 13.00 | **42%** | t5 43% · gbm 40% (보정값 — raw 주간: t5 18% · gbm 30% · 보정: t5 브리지·gbm 일간, 분위수 종점 7%는 하한) |
| VIX ≥40 터치 ~2027-01-15 (^VIX) | 40.00 | **6%** | t5 0% · gbm 13% (보정값 — raw 주간: t5 0% · gbm 8% · 보정: t5 브리지·gbm 일간, 분위수 종점 7%는 하한) |
| ^IXIC 2027-01-15 종가 ≥30,000 | 30,000.00 | **7%** | bolt 7% · c2 7% · gbm 7% · c2꼬리(q01~q99 보간, 병기) 1% |

- 사용법: 앙상블 참조 확률과 시스템 rN 확률의 괴리 15%p+ 는
  `due`에 divergence로 표시된다 (재예측 후보 — 자동 실행 없음, 판단은 사람).

## FinBERT 헤드라인 감성 (GDELT)
| 피드 | 헤드라인 수 | 감성 지수 [-1,+1] | Δ7d |
|---|---|---|---|
| ai-semis | 0 | +0.000 | -0.102 |
| fed-macro | 25 | -0.381 | -0.288 |
| market | 25 | -0.073 | +0.248 |
| nvda | 0 | +0.000 | -0.068 |
| memory | 0 | +0.000 | +0.279 |
- **종합**: -0.227 (0 = 중립)
- 최근 부정 헤드라인 샘플:
- Reserve Bank interest rates: Commonwealth Bank economist warns further hikes could trigger a recession
- Gold falls for fourth session as oil rally fuels inflation concerns
- Gold Prices Fall for Third Day as Oil Surge Fuels Fed Rate Hike Fears
- Nasdaq Eliminates Sub - $4 Initial Listing Path On The Nasdaq Capital Market
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
