# 모델 레지스트리 — 상태·승격/강등 근거 대장 (퀀트 플랫폼 관례의 경량 구현)

> 상태: `reference` (base rate 참조 전용 — 기본값) · `demoted` (특정 용도 사용 금지) · `candidate` (승격 검토 중).
> 승격/강등은 근거·일자 필수. 계보(파라미터·산출)는 `dualdb model_run`·`data/ml_history/` 참조.

| 모델 | 위치 | 상태 | 용도 | 근거·이력 |
|---|---|---|---|---|
| LLM 파이프라인 (opus-4-8 + 웹서치) | src/ai_fc | **공식 예측 생산자** | rN 확률 (유일한 공식 확률) | 8-8. K회 중앙값 배관 보유(기본 K=1) |
| Chronos-Bolt-small | src/ai_fc/ml | reference | 연말 분위수 | 앙상블 멤버 |
| Chronos-2 (공변량) | src/ai_fc/ml | reference | 연말 분위수 (VIX·TNX past-only) | 앙상블 멤버 |
| Chronos-T5-small 샘플경로 | src/ai_fc/ml | reference | 경로 터치 MC — **브라운 브리지 보정값이 정본** (raw 병기) | v2 WS3 (2026-07-20): p=exp(−2·d₀·d₁/σ_w²) 결정론 보정, 9-1 비저촉 판정. σ_w 근사는 KNOWN_LIMITS 29 |
| GBM MC | src/ai_fc/quant·ml | reference | 종점(주간)·배리어(**경로 질문은 일간 스텝** — T-11 근본 해결) | v2 WS3: 일간 μ·σ 재추정, 실패 시 주간 폴백. 정규가정·VIX 평균회귀 무시 고지 유지 |
| FinBERT 감성 | src/ai_fc/ml | reference | 분위기 정량화 — **비방향** | D-3 시정: 방향 증거 사용 금지 |
| 시장내재 (Polymarket·옵션 BL) | src/ai_fc/market | reference | market_implied/edge **기록 전용** | P3 봉인 (C7) |
| **LPPL** | quant + dualdb/models | **demoted** (조기경보 용도) | raw tc + 워크포워드 IQR 병기만 | **8-7 (2026-07-15)**: 닷컴 워크포워드 실측 — 정점 1개월 전에야 수렴, 경계히트 17/21. 보정 tc 비활성(코드 게이트, U-1). 리스크 판단 근거 사용 금지 |
| DTW (월간 시프트·일간 open-end) | quant + dualdb/models | reference | 위상 판독 (삼중 병기 중 하나) | 단일 위상 단정 금지 (KNOWN_LIMITS) |
| k-NN 아날로그 | dualdb/models | reference | Q15 전방수익 base rate | R-4: 미백색화 확정, 유효차원<5 고지. 준-앵커 라벨 |
| 트윈 대조 | dualdb/analysis | reference | Q14 종목 base rate | 생존 승자 표본 — 낙관적 하한 |
| 미드텀 시즌성 | src/ai_fc/quant | reference | **경로 리듬의 1차 근거** (v3.1.1 §3) | n=8~20 자체 산출 |
| Hurst·오버레이·Pearson | src/ai_fc/quant | reference | 체제 진단 | 앵커 민감도 실측 완료 (T-9) |

**강등 절차** (8-7이 선례): 실측 근거 → DECISIONS 기록 → 렌더러 코드 게이트(문서 시정만으로는 재실행 침식) → KNOWN_LIMITS 갱신.
