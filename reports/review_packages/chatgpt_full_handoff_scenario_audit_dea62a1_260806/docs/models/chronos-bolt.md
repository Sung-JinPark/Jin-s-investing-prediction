---
license: apache-2.0
library_name: chronos-forecasting
pipeline_tag: time-series-forecasting
base_model: amazon/chronos-bolt-small
tags: [time-series, forecasting, inference-only, zero-shot]
ai_fc_status: active
ai_fc_role: base-rate-reference
ai_fc_gate: "추론 전용 — 학습·가중치 갱신 금지, 결합은 고정규칙(중앙값)만 (CLAUDE.md ML 게이트)"
last_reviewed: 2026-07-20
---

# Chronos-Bolt-small — 추론 전용 사용 카드

## 용도와 한계
- 주간 종가 → 연말 지평 **분위수(q10/25/50/75/90)** zero-shot 예측. `data/base_rates/ml_auto.md` 공급용 참조 확률 — **매매 신호 아님**.
- 무조건부 모델: FOMC·실적·선거 등 이벤트 캘린더를 모름 — 시나리오 분석의 참조선.
- 분위수 5점 CDF 선형 보간의 꼬리 캡 0.93/0.07 (`prob_above` — 분포 꼬리 단정 금지).
- LLM rN과 15%p+ 괴리는 `due` divergence 표시만 — 자동 재예측 금지.

## 사용법
- 호출 지점: `src/ai_fc/ml/chronos_fc.py` `forecast_quantiles()` ← `ml/runner.py run_all()`
- ~48M 파라미터 · CPU 수 초 · 최초 실행 시 HF 다운로드(~190MB) 후 로컬 캐시.

## 성능 근거 (외부)
- 상류 카드 벤치마크 + GIFT-Eval 계열 리더보드 상위권 (2026-07 리서치 — reports/research/hf_landscape_260720.md).

## 라이선스
Apache-2.0 (상업 사용 가능). 상류: https://huggingface.co/amazon/chronos-bolt-small
