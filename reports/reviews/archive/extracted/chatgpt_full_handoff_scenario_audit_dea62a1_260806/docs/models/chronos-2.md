---
license: apache-2.0
library_name: chronos-forecasting
pipeline_tag: time-series-forecasting
base_model: amazon/chronos-2
tags: [time-series, forecasting, inference-only, covariates]
ai_fc_status: active
ai_fc_role: base-rate-reference
ai_fc_gate: "추론 전용 — past-only 공변량, 미래 공변량 사용 금지"
last_reviewed: 2026-07-20
---

# Chronos-2 — 공변량 조건부 분위수 (추론 전용 사용 카드)

## 용도와 한계
- ^IXIC·SOXX에 **past-only 공변량(VIX·TNX)** 조건부 분위수 — "미래 VIX를 아는 척하지 않는다".
- Bolt와 고정 중앙값 결합 (2모델 구간에선 평균과 동일 — 이상치 방어는 3개+부터, D-8).
- 로드 실패 시 Bolt 단독 fail-soft (`c2_error` 기록).

## 사용법
- 호출 지점: `src/ai_fc/ml/chronos_fc.py` `forecast_quantiles_c2()` — 공변량 뒤끝 정렬(`_align_covariates`).
- 120M(~480MB) · CPU 추론.

## 라이선스
Apache-2.0. 상류: https://huggingface.co/amazon/chronos-2
