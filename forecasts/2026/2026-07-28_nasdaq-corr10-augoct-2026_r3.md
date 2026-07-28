---
forecast_id: 2026-07-28_nasdaq-corr10-augoct-2026_r3
question_id: nasdaq-corr10-augoct-2026
question_snapshot: "2026-08-01~10-31 기간 중 NASDAQ Composite 일간 종가가 24,384.51(= 사이클 ATH 27,093.90 x 0.90) 이하로 마감하는 날이 1일 이상 존재할 확률은?"
timestamp: 2026-07-28 11:44 KST
phase: P1
model: gpt-5 (Codex evidence synthesis)
prompt_version: reasoning_core_v1
probability: 65
ci80: [53, 76]
window_end: '2026-10-31'
snapshots:
  threshold: "24,384.51 (= 27,093.90 x 0.90) — 고정"
  current: "24,932.08 (2026-07-27 종가) — 임계까지 −2.20%"
market_implied: null
edge: null
sources_count: 14
method: research+dualdb+gbm
research_status: ok
pipeline_tier: standard
ml_divergence_pp: 1
---

## 판단

최신 100,000경로 GBM의 일간 배리어 확률은 63.5%다. 임계선은 현재가보다 2.2% 낮을 뿐이고, 8~10월에는 FOMC·실적·미드텀 계절성이 겹친다. 반대로 시장 폭은 견조하고 AI 실물매출도 강하다.

- **최종 확률: 65%** (80% CI 53~76%)
- **직전 대비:** 57% → 65% (**+8%p**)
- **상향 이유:** 임계와의 거리가 −4.45%에서 −2.20%로 축소됐고 최신 GBM이 63.5%를 제시
- **주요 반대근거:** 표본 종목의 70.8%가 200일선 위이고 반도체 급락 뒤 10거래일 반등 승률이 60%

상세 데이터·출처: `reports/md/semiconductor_market_update_260728.md`

