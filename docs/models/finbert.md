---
license: other
library_name: transformers
pipeline_tag: text-classification
base_model: ProsusAI/finbert
tags: [financial-sentiment, inference-only]
ai_fc_status: active
ai_fc_role: sentiment-context
ai_fc_gate: "비방향 원칙 (D-3) — 방향 증거 사용 금지, 분위기 정량화만"
last_reviewed: 2026-07-20
---

# FinBERT — 헤드라인 감성 지수 (추론 전용 사용 카드)

## 용도와 한계
- Google News RSS 5피드 × 25 헤드라인 → 감성 지수 [−1,+1] = mean(P(pos)−P(neg)).
- **동행~후행 지표** — 방향 예측이 아니라 현재 분위기의 정량화 (D-3 시정 사항).
- 피드 1개 실패는 해당 피드만 생략 (fail-soft).
- 교체/보강 후보 검토: reports/research/hf_landscape_260720.md (FOMC-RoBERTa 등).

## 사용법
- `src/ai_fc/ml/sentiment.py` — ~110M, CPU. Δ7d는 DB 이력 기반.

## 라이선스
상류 카드 확인 필요 (ProsusAI — 연구 목적 명시): https://huggingface.co/ProsusAI/finbert
