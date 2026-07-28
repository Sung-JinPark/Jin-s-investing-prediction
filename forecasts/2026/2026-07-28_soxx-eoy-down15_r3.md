---
forecast_id: 2026-07-28_soxx-eoy-down15_r3
question_id: soxx-eoy-down15
question_snapshot: "SOXX의 2026년 마지막 거래일 종가가 기준가(reference price) 대비 −15% 이하일 확률은?"
timestamp: 2026-07-28 11:44 KST
phase: P1
model: gpt-5 (Codex evidence synthesis)
prompt_version: reasoning_core_v1
probability: 27
ci80: [16, 40]
window_end: '2026-12-31'
snapshots:
  reference_price: "$551.69 (2026-07-07 종가) — 고정"
  threshold: "$468.94 (= $551.69 x 0.85)"
  current: "$516.23 (2026-07-27 종가) — 임계까지 −9.16%"
market_implied: null
edge: null
sources_count: 14
method: research+dualdb+gbm
research_status: ok
pipeline_tier: standard
ml_divergence_pp: 22
divergence_class: model_limit
divergence_note: "최신 단순 GBM 4.8%는 독립·정규 수익률과 일정 드리프트를 가정해 반도체 공급주기, 변동성 군집, 순환금융·중국 공급의 사건 꼬리를 과소표현한다. 2026-07-20 Chronos·GBM 혼합 앙상블은 24%였으나 최신 Chronos는 Windows 애플리케이션 제어가 torch_python.dll을 차단해 재실행하지 못했다."
---

## 판단

현금 매출과 HBM 수요는 강하지만, 높은 마진부채·순환금융·중국의 성숙공정 공급은 연말 하락 꼬리를 키운다. 단기 반등 가능성과 연말 손실 확률은 동시에 성립할 수 있다.

- **최종 확률: 27%** (80% CI 16~40%)
- **직전 대비:** 24% → 27% (**+3%p**)
- **상향 이유:** 임계까지 거리가 10.1%에서 9.2%로 줄고 새로운 구조적 위험이 확인됨
- **주요 반대근거:** TSMC 6월 매출 +67.9% YoY, NVIDIA DC +92% YoY, 1~2주 반등 base rate

상세 데이터·출처: `reports/md/semiconductor_market_update_260728.md`

