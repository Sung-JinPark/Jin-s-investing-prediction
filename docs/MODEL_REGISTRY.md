# 모델 레지스트리 — 상태·승격/강등 근거 대장 (퀀트 플랫폼 관례의 경량 구현)

> 상태: `reference` (base rate 참조 전용 — 기본값) · `demoted` (특정 용도 사용 금지) · `candidate` (승격 검토 중).
> 승격/강등은 근거·일자 필수. 계보(파라미터·산출)는 `dualdb model_run`·`data/ml_history/` 참조.

| 모델 | 위치 | 상태 | 용도 | 근거·이력 |
|---|---|---|---|---|
| LLM 파이프라인 (OpenAI gpt-5.6-terra + 웹서치) | src/ai_fc | **공식 자동 예측 생산자** | 신규 rN 확률 (유일한 공식 확률) | 2026-08-03 소유자 승인. K회 중앙값 배관 보유(기본 K=1) |
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
| **V13-VOL 당일 수준 지속 로짓 (champion = persistence_pb)** | src/ai_fc/timeseries_v13 · tools/v13_vol_*.py · data/timeseries_v13 · data/contracts/multivariate_timeseries_v13_vol.yaml | **reference (T3 라이브 카드 '변동성 기준율', 2026-09-08)** — 홀드아웃 1슬롯 소모 2026-09-09 **partial 3/9**(V13-D3: `vix25_h21`·`rv_h5`·`rv_h21` 통과, 슬롯 잔여 2) · 배선 보류(V13-D6: 셀당 라이브 성숙 60원점 전 판단 않음, 현재 대상 0) · 라이브 전진 축적 중(distinct 원점 30, 2026-10-22 실측 — 판정은 계약이 막음 · 2026-10-22 V13-D12 원점 백필 late_capture · V13-D13 판정불가(제한) 라벨: 9셀 전부 제한, 배선 자격 0) | EXIT 트리거 변동성 이벤트 base rate 공급(VIX≥K·RV>θ 지평 5/21/63 영업일) — **매매 신호 아님, LLM 예측과 산술 결합 금지, 참고 의견** | 설계창(2007-2014): EWMA 기후 대비 9/9 · HAR 증분 0/9 · **rung-3 EWMA 는 PB 대비 양방향 우세 0/9 → champion=PB 전 9셀**(finalist V13VOL_champion_aec80c65038b, 귀무 ≤0.033) · rung-4 매크로 블록 채택 0/27(r33) · 계수 동결 sha 핀 · h63 isotonic fallback(raw, ▲ 보정 약함) · 국면 가드(episode_thin 셀은 PASS 여도 배선 불가, r30) · 라이브 전진 게이트 사전등록(셀당 60) |
| **V14 조건부 전이 — 조건부 지속 로짓 (conditional_persistence_pb)** | tools/v14_cond_{diagnostics,run}.py · data/timeseries_v14 · data/contracts/multivariate_timeseries_v14_conditional.yaml | **연구(설계창) — 라이브 포인터 없음** (track_open 2026-10-22 · gates.armed false · display t0) | EXIT 하드룰 조기경보 표적: 평온(VIX<20 / RV21≤θ)에서 h 거래일 안 VIX 25·θ 돌파 확률 — **매매 신호 아님, 참고 의견** | rung-1(2026-10-23, 사전등록 a93801cf, 예산 1/4): 외부 블록(E1 FOMC·P1 VIX 포지셔닝) 6검정 채택 0(측정된 영 — 4방향은 후보가 유의하게 나쁨). G0 조건부 PB > 조건부 기후 양방향·귀무 0.000 — crv_h5(BSS +0.318/+0.260)·cvix25_h21(국면 얇음); crv_h21 HOLD. 하드룰 셀 cvix25_h5 설계창 검정 불가(반창 사건 6·5). 홀드아웃 창 없음(C3) — 판정은 라이브 전진만(I3). champion·verb 는 V14-D10, rung-2 는 V14-D11(권고 보류) |
| **V8 다변량 시계열 (shadow.mf_dfm_varx_calibrated_v8)** | src/ai_fc/timeseries_v8(봉인 model_code_hash 집합 — 무수정) · timeseries_v8_display.py(표시) · timeseries_v8_daily.py(일일 표시) · data/timeseries_v8 · data/contracts/multivariate_timeseries_v8.yaml | **shadow_live · research_reference (R8-D3 2026-09-01, display-promotion)** — 봉인 GATE PASS(run `tsv8-sealed-64345a816b4857171915d5b8`, 전체창 1,011원점; 봉인창 2019+ 385원점은 2008 원점 0개로 자체 판정 hold, R8-D4) · 승격 전(계약 `promotion`: automatic_champion=false · minimum_shadow_sessions 126 · explicit_owner_approval; 섀도 세션 46/126, 2026-10-21 실측) | NASDAQ 1/5/21/63거래일 분위수·상승 확률 — **참고 의견, 공식 예측·시나리오 V5.2와 결합 금지, 매매 신호 아님** | R8-D2 봉인 평가 1회 종결 · R8-D3 표시 승격 · R8-D4 지표 공개 확대(방향 적중률·MASE·first_touch 비공개) · score100 표시(2026-10-06 r34, 70점 B — 봉인 4축 61.3점 고정, 총점 61~76 범위) · 일일 표시 포인터(2026-10-07, 채점 제외) · 섀도 원점 2026-08-14~10-16 주간 9행, 해소 19행(h1·h5, 63일 성숙 원점 0) · 진행률·상한 라벨(2026-10-21 r35) |
| **daily6m 6개월 일별 전망 (research.nasdaq_daily6m_varx_v1)** | src/ai_fc/timeseries_daily6m · data/timeseries_daily6m · data/contracts/timeseries_daily6m_v1.yaml | **independent_research_preview · 검증 전(predictive_validation=not_established)** — V8·시나리오와 독립, 결합 금지 | 일별 지수 범위(p10~p90)·전 거래일 대비 상승 확률(20,000 결합 경로, 6개월) — **참고 의견, 매매 신호 아님** | 발행 원장 3행(원점 2026-10-14·10-19·10-20, 1건 supersedes) · 해소 원장 5행(누적 Brier 0.228 vs 무정보 0.25 · 80% 구간 적중 4/5 · 발행 2/해소일 4 — 같은 발행의 일별 행 비독립, 판정 아님) · 전진 성적 표면(2026-10-21 r35) |

## LLM 공식·shadow 계보

| model_id | provider | 상태 | 출력 계보 | 비고 |
|---|---|---|---|---|
| `llm.forecaster.anthropic` | Anthropic | historical official / fallback | 기존 forecast append-only 기록 | 과거 계보 유지, 재분류 금지 |
| `llm.forecaster.openai.official.gpt-5.6-terra` | OpenAI Responses API | **official** | 2026-08-03 이후 신규 forecast | 승인 원장 정확 일치, family alias 금지 |
| `llm.forecaster.openai.<model>` | OpenAI Responses API | shadow 후보 | `calibration/provider_shadow_ledger.csv` 별도 기록 | 공식 확률과 결합 금지, 승인 전 전환 금지 |

신규 forecast frontmatter는 `provider`, `model_snapshot`, `provider_version`을 기록한다. 점수와 비용은 provider/model snapshot별로 분리하며 과거 Anthropic 점수를 OpenAI 버전으로 재분류하지 않는다.

**강등 절차** (8-7이 선례): 실측 근거 → DECISIONS 기록 → 렌더러 코드 게이트(문서 시정만으로는 재실행 침식) → KNOWN_LIMITS 갱신.
