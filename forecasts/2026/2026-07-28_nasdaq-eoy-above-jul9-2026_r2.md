---
forecast_id: 2026-07-28_nasdaq-eoy-above-jul9-2026_r2
question_id: nasdaq-eoy-above-jul9-2026
question_snapshot: "NASDAQ Composite의 2026년 최종 거래일 종가가 26,206.89(2026-07-09 종가)를 초과할 확률은?"
timestamp: 2026-07-28 11:44 KST
phase: P1
model: gpt-5 (Codex evidence synthesis)
prompt_version: reasoning_core_v1
probability: 52
ci80: [39, 65]
window_end: '2026-12-31'
snapshots:
  baseline: "26,206.89 (2026-07-09 종가) — 고정"
  current: "24,932.08 (2026-07-27 종가) — 기준선까지 +5.11% 필요"
market_implied: 38
edge: null
sources_count: 14
method: research+dualdb+options+gbm
research_status: ok
pipeline_tier: standard
ml_divergence_pp: 1
---

## 판단

최신 100,000경로 GBM은 52.7%, 옵션 기반 위험중립 확률은 38.0%다. 가까운 과거 상태 5개의 3개월 수익률 중앙값은 +7.0%이나 표본이 매우 작다. 강한 AI 매출과 견조한 시장 폭은 상방, 극단적 집중·마진부채·순환금융은 하방이다.

- **최종 확률: 52%** (80% CI 39~65%)
- **직전 대비:** 63% → 52% (**−11%p**)
- **하향 이유:** 현 종가가 고정 기준선보다 5.1% 낮고 옵션시장이 더 보수적으로 가격
- **주요 반대근거:** TSMC·NVIDIA·Micron의 실물 수요가 강하고 장기 추세는 아직 유지

상세 데이터·출처: `reports/md/semiconductor_market_update_260728.md`

