---
license: apache-2.0
library_name: chronos-forecasting
pipeline_tag: time-series-forecasting
base_model: amazon/chronos-t5-small
tags: [time-series, forecasting, inference-only, sample-paths]
ai_fc_status: active
ai_fc_role: base-rate-reference
ai_fc_gate: "추론 전용 — 경로 터치 확률의 정공법 재료, 보정값이 정본 (raw 병기)"
last_reviewed: 2026-07-20
---

# Chronos-T5-small 샘플 경로 — 배리어 터치 (추론 전용 사용 카드)

## 용도와 한계
- 자기회귀 **샘플 경로 256개**(seed=42) → 경로 질문(F1/F2/VIX25)의 배리어 터치 확률.
- **v2 WS3**: 주간 이산 과소추정(T-11)을 브라운 브리지로 보정 — p=exp(−2·d₀·d₁/σ_w²),
  보정값이 divergence 판정 기준 (DECISIONS 9-2). σ_w 경로 내 추정 근사 (KNOWN_LIMITS 29).
- CPU 자기회귀 생성 수십 초~수 분 — 경로 질문 있는 시리즈에만 호출.

## 사용법
- `chronos_fc.sample_paths()` → `mc.barrier_prob`(raw) + `chronos_fc.bridge_touch_prob`(보정).

## 라이선스
Apache-2.0. 상류: https://huggingface.co/amazon/chronos-t5-small
