# 리더 4명 원문 요약 — 본문 §2·§4·§7·§8 의 1차 근거

> 저장소 원문을 직접 읽은 4개 리더 에이전트의 산출물이다. 본문이 압축한 수치의 출처가 여기 있다.


---

# [reader:state] 현재 상태 지도

# 현재 상태 지도 — NASDAQ 다변량 시계열 캠페인 (2026-09-08 기준)

## 0. 이 지도가 명시적으로 지키는 거버넌스

1. **백테스트 금지의 경계**: LLM이 개입하는 과거 질문 평가는 원천 무효(`CLAUDE.md` 5원칙 5). 결정론 수치모델의 과거 적합·워크포워드만 허용되며(dualdb 스펙 v1.0 §8 예외, `docs/DECISIONS.md` 8-6), 그 산출은 **base rate 참조**이지 캘리브레이션 표본이 아니고, 하이퍼파라미터(창·임계·문턱)가 정점 지식을 간접 내포할 수 있다는 caveat를 붙인다. 아래 표의 모든 CRPS·Brier 수치가 이 지위다.
2. **ML 게이트**: 캘리브레이션 보정은 해소 100+, 앙상블 가중 학습은 해소 200+ 뒤(`CLAUDE.md` 하드 게이트). `src/ai_fc/ml/`의 Chronos-Bolt(`amazon/chronos-bolt-small`, `chronos_fc.py` L17)·Chronos-2·T5·FinBERT(`ProsusAI/finbert`, `sentiment.py` L39)는 추론 전용, 결합은 고정 중앙값·불일치 지수뿐(`data/base_rates/ml_auto.md`).
3. **창 규율**: design 2007–2014 / holdout 2015–2018 / sealed 2019+ (`data/contracts/multivariate_timeseries_v8.yaml` `model.windows`). 홀드아웃·봉인은 사전등록 finalist당 1회, 사용자 명시 승인 문자열 없이는 verb 자체가 없다(`multivariate_timeseries_v13_vol.yaml` `holdout_execution_path: absent_by_construction`). 건전 음성대조 = **y-block 순열**(p-순열 귀무는 누수, `docs/review/V13_TA_NULL_REPAIR_VERDICT_20260907.md`). 채택 기준 = early↔late 양방향 전이 + stationary block bootstrap CI90(Politis & Romano (1994) 'The Stationary Bootstrap', JASA). in-sample 통과 ≠ 채택.
4. **봉인 바이트 불변**: V8 패키지 + V2 8파일 sha256 `e3ff2fdb64ac71c0f05ae8e4508ef1c5a7c8fba7b78d81548918881032c8d224`(`docs/review/SUNDAY_LOOP_FINAL_REPORT.md` 표 I) — 캠페인 전 과정 0바이트 변경. `forecasts/`·`calibration/` append-only.
5. **지위**: 모든 출력은 '참고 의견'. P3 게이트(해소 50문항+ & Brier<0.18) 전 자본 결정 근거 불가. 표본 단위는 `COUNT(DISTINCT question_id)`(`docs/DECISIONS.md` 2026-09-07).
6. **데이터**: PIT(ALFRED first-release vintage·captured_forward), 합법 라이선스(FRED 공식 API 전용, 12-6). FirstRate/CBOE 구매·발송은 사용자 결정(`docs/DECISIONS.md` 2026-09-08 '사용자 결정 대기' 3·4).

## 1. 트랙 지도

### 1-A. 가격 분포 계보 V1–V8 (표적: NASDAQCOM 일간 로그수익 분포, h∈{1,5,21,63})

| 트랙 | 목표 · 정보집합 · 모델 | 평가 규약 | 판정 | 핵심 수치 (경로) | 산출물 | 봉인/동결 |
|---|---|---|---|---|---|---|
| **V1** `shadow.mf_dfm_ridge_varx_v1` | ALFRED PIT 거시(PAYEMS·CPI 등 10계열)+일간 시장 6계열 → 혼합빈도 DFM + ridge VARX (`data/contracts/multivariate_timeseries_v1.yaml` `sources`) | 사전등록 섀도 전용(`status: preregistered_shadow_only`) | 섀도 원장만 축적, 게이트 수치 본 지도에서 미열람 [미검증] | 섀도 예측 17행 `data/timeseries/ledgers/forecasts.jsonl` | 계약 v1 · `data/timeseries/` | V1 정본 ALFRED 스토어가 V9 vintage 수집의 저장소(`DECISIONS` V9-D5) |
| **V2** `shadow.mf_dfm_ridge_varx_v2` | V1 + PIT 등급 체계(native_pit/reconstructed/captured_forward), 후보 C1(core market + growth/inflation 요인) | 봉인 평가 1회, 2019+ | **FAIL/hold** — h21·63 개선<2%, CI 상단>0, GFC coverage<70% | 1,011원점: h21 −0.46%, h63 −9.54%, 장기 CI90 [+0.000263,+0.005448](양수=악화) `data/timeseries_v2/ledgers/sealed_evaluations.jsonl` | 계약 v2 · V8 계약 `v2_benchmark` run `tsv2-backtest-f995c40e…` `gate_result: fail`, `retune_prohibited` | **봉인 8파일**(위 해시). 2019+ 점수 공개로 후속 모델의 2019+는 준청정(`v8.yaml` `disclosure_caveat`) |
| **V3** `shadow.nasdaq_direct_regime_distribution_v3` | 직접 누적수익, 7성분(anchor·regime·event·market_implied 등), student-t/regime 잔차; 고정 앙상블 비교군(HS .5/FHS .3/SBB .2) | design pseudo-OOS(봉인 아님, `freeze_note`) | hold — <2%, 극단 Q4 coverage·stress regime 실패 | h21 +0.75%, h63 +2.02%, 장기 +1.39% `data/timeseries_v3/runs/tsv3-research-1f80a06b….json` | 계약 v3 · 포인터 `shadow_validation_hold` | 동결 연구 후보 |
| **V4** `…pit_market_event_distribution_v4` | V3 + CBOE VIX9D/VIX3M/VVIX/SKEW 이벤트 상태(`v4.yaml` `sources`) | V3 비교군·임계 무변경 | hold — 동일 3사유 | h21 +0.29%, h63 +1.69%, 장기 +0.99% `data/timeseries_v4/runs/tsv4-research-bd2ac04e….json` | 계약 v4 | `shadow_gate_hold` |
| **V5** `…pit_hybrid_distribution_v5` | 8패밀리 앙상블(quantile EN·student-t·HGB·DLM·soft regime·EVT·event LP, `v5.yaml` L124–131) | research+operational 게이트 | hold — 7사유(장기 −9%, 부호별·극단·stress) | 963원점: h21 −10.69%, h63 −7.38%, 쌍대 CI90 [+0.00133,+0.00607] `data/timeseries_v5/runs/tsv5-research-92c262ef….json` | 계약 v5 · `outputs/timeseries_v5/audit/` | 2007–2026 run은 진짜 봉인 홀드아웃 아님(`baseline_reproduction.json` L7) |
| **V6** `…pit_hierarchical_distribution_v6` | 11패밀리(파운데이션모델 챌린저·시장내재 보정 포함), 결정론 replay 컨테이너 | 봉인 2019+ 385원점 | hold — 8사유(coverage·<2%) | h21 +1.27%, h63 +0.58% `outputs/timeseries_v6/audit/FINAL_REVIEW_SUMMARY.json`; V7가 불변 재현(`outputs/timeseries_v7/audit/v6_gate_reproduction.json` `V6_HOLD_REPRODUCED_IMMUTABLY`) | 계약 v6(`contract_status: frozen`) | 봉인 run `tsv6-sealed-46d58750…` |
| **V7** `…hierarchical_distribution_v7` | V6 계승, 주간 원점·경로 20,000 | 전방 라벨 성숙 대기 | **WAIT_DATA**(historical 미실행, 숫자 비공개) | `outputs/timeseries_v7/status.json` | 계약 v7 `frozen_v7_p0_003`(2026-08-25) | 파킹(Codex 트랙) |
| **V8** `shadow.mf_dfm_varx_calibrated_v8` | V2 엔진 read-only + 분포 계층 B1~B5; 승자 E10 = FHS(h21/63) + HS 블렌드 .75 + PIT isotonic 재보정 s=.5 (`v8.yaml` `frozen_winner`) — FHS: Barone-Adesi, Giannopoulos & Vosper (1999) 'VaR without correlations…', J. Futures Markets | dev 24회 예산·stop-loss, holdout finalist ≤3·1회, 봉인 1회·사용자 사인오프(R8-D2) | **GATE PASS → 라이브(research_reference)**; 챔피언 승격 아님 | design +2.86% · holdout 209원점 쌍대 −0.002204 CI90 [−0.003266,−0.001060] `data/timeseries_v8/ledgers/holdout_scorings.jsonl` · 봉인 run `tsv8-sealed-64345a81…`: 전체창 1,011원점 h21 +3.96%/h63 +4.21%, 80% 적중 0.813/0.808, 장기 CI90 [−0.002639,−0.000858], GFC 0.782; **봉인창 385원점** h21 +3.47%/h63 +4.87%, CI90 [−0.003790,−0.000265], 자체 판정 hold(2008 원점 0) `sealed_evaluations.jsonl` | 계약 v8 · 원장 5종(`ledger_registry.yaml` L316–342) · `outputs/timeseries_v8/reports/R8D3_PUBLICATION_REVIEW_20260901.md` | `frozen_for_sealed_evaluation`(2026-08-30), `src/ai_fc/timeseries_v8/` model_code_hash `8361899f…` |

### 1-B. V8 위의 개선 시도 V9–V12, 신규 표적 V13, 인접 계층

| 트랙 | 목표 · 정보집합 · 모델 | 평가 규약 | 판정 | 핵심 수치 (경로) | 산출물 | 봉인/동결 |
|---|---|---|---|---|---|---|
| **V9** `…varx_liquidity_v9` | V8 승자 + 외생 열: M2SL·TOTCI·TOTLL·WRMFNS(ALFRED first-release) + VXN/VIX 스프레드(서브창 2010–14) | 단독 ablation, E0 항등(1e-12) 대비 쌍대 CRPS, 챔피언=신규 피처≥1 ∧ E0 개선 | **동결(대안 D)** — 6종 전부 무효익 | E1 +0.000014 [−0.000000,+0.000028]; **E2 +0.000043 [+0.000019,+0.000074] 유의 악화**; E6−E5 장기 +0.000006 [−0.000008,+0.000021], 단기 +1.65% 악화 `outputs/timeseries_v9/reports/E2_E4_ABLATION_REPORT_20260902.md`, `E5_E6_VXN_SPREAD_VERDICT_20260902.md`; 독립 재계산 5쌍 개선 0, 최대\|Δ\| 4.33e-05, se 4.04e-06~2.11e-05 → "측정된 영" `docs/review/V9_V10_V11_INDEPENDENT_VERDICT.md` §1.3 | 계약 v9(`status: draft`) · `data/timeseries_v9/ledgers/development_experiments.jsonl`(7행) | 예산 7/24, holdout 0/3. V9-D5 vintage 수집 트랙만 진행(`DECISIONS` 2026-09-02) |
| **V10** `…varx_regime_width_v10` | 분포 계층 5축: W1 상태조건부 재표집(κ)·W2 K-혼합·W3 상태조건부 블렌드(γ)·W4 isotonic 재보정·W5 단기 FHS; 상태=EWMA97 분산비 (`v10.yaml` `research_grids`) | V8 model/backtest 포크(source_pins) · 12회 stop-loss(<+1%) · 6렌즈 적대 검증 | **동결** — 유일 챔피언이 GFC 위기원점 인공물 | W3 γ=−0.10: +0.000277 CI90 [+0.000016,+0.000679] = **+0.64%**(417원점); GFC 78원점(18.7%)이 델타 83.8%, GFC 제거 0.64→0.13%, 상위5% 제거 −0.0000115, 클립 포화 7주=엣지 58%; holdout 게이트(+2%) 통과 확률 <2% 추정 `outputs/timeseries_v10/reports/V10_FREEZE_DECISION_20260903.md`, `SINGLES_COMPLETE_STOPLOSS_20260903.md`; D7 정정: 조합 격자 미표집, 12조합 중 6개 +1.04~1.15%나 상위5% 제거 후 CI90 하한 전부 음수 `V9_V10_V11_INDEPENDENT_VERDICT.md` §4.1 | 계약 v10 · `data/timeseries_v10/ledgers/development_experiments.jsonl`(12행) · `CHAMPION_ADVERSARIAL_VERIFY_20260903.json` | 예산 12/24, holdout 3/3 보존, V12-D5 재개 안 함 |
| **V11** (계약 없음) | 평시(비위기 하위 80%) 직교 상태 프록시 P1~P9 × PIT/부호/IQR 결함 × h21/63 = 54검정, 기존 E0 데이터만 | 사전등록 4중 기준 → 6렌즈 → 표본외 전이 | **동결** — real but not exploitable | 통과 4/54: P1 모멘텀→PIT h21 Δ −0.120 [−0.192,−0.035]; 전이: 순방향 CRPS +0.97% 악화, 역방향 +1.49% 악화; P(≥4)=0.25~0.32; 독립 재계산 채택 0/12, 순열 p=0.118 `outputs/timeseries_v11/reports/V11_FREEZE_DECISION_20260903.md`, `docs/review/V9_V10_V11_INDEPENDENT_VERDICT.md` §1.2 | `docs/design/v11_orthogonal_calm_diagnostic_260903.md` · `data/timeseries_v11/diagnostics/*.json` | 백테스트 0회, holdout 0 |
| **V12** `derived.first_touch_event_probability_v12` | V8이 이미 내는 −10% first-passage 확률(417원점, h21/63)의 재보정 맵 T1~T4 + 반사원리 2Φ 기준선 | 사전등록(커밋 `ec496463`) · 양방향 CI90 하한>0 · T5 음성대조 | **부정결과 계약**(`status: negative_result_draft`, `gates.armed: false`, 후보 0) | BS V8 h21 0.061485/h63 0.144973, BSS vs 기후 0.0498/0.0906이나 CI90 0 걸침; 채택 0/8, T5 pooled 0.254>0.10 `docs/review/SUNDAY_LOOP_FINAL_REPORT.md` 표 D·E; T-A 수리: N-p-block 0.201, N-y-block 0.000, N-blk-pair 0.000 → NOT_REPAIRED `V13_TA_NULL_REPAIR_VERDICT_20260907.md` | 계약 `multivariate_timeseries_v12.draft.yaml` · `data/timeseries_v12/{prereg,diagnostics,reports}` · `V12_DECISIONS_20260907.md` · 포스트모템 `V12_POSTMORTEM_NEXT_DESIGN_260907.md`(H3: 상수-σ i.i.d. 경로 생성기) | dev 예산 24 중 계약 기록 0(S3 환산 4 → 잔여 20 제안, `v12_gate_design.md` 표 E1), holdout 0 |
| **V12b** (경로 생성기 T-B) | 잔차 블록 재표집 ℓ_z∈{2,3,5}/AR(1) φ로 단기 되돌림 복원 | 새 사전등록 + 건전 y-block 귀무 + CRPS 무손상 | **파킹**(2026-09-08, 폐기→보류 재라벨) | P1 진단: 수익률 ACF lag1 −0.0762, z AR(1) φ̂ −0.0529, VR(5) 0.8736 `data/timeseries_v13/prereg/p1_h3_prediagnosis.json` — 크기 온건 | `docs/review/V12B_TERMINATION_20260907.md`(무수정) · `V12B_PARKED_20260908.md` | 예산 0, 재개는 일중 데이터(FR-1) 확보 후 새 ID |
| **V13-VOL** `event_probability.volatility_v13` | 변동성 이벤트 확률: P(VIX≥25/30 within 5/21/63 영업일), P(RV21_ann>0.1694); 봉인 V2 아카이브 read-only VIX·NASDAQCOM PIT, n_panel 2,014; 사다리 기후→EWMA-logit→HAR-logistic(Corsi (2009) 'A Simple Approximate Long-Memory Model of Realized Volatility', J. Financial Econometrics)→GARCH-t(미실행) + **자명 기준선 PB=당일 수준 단독 로짓**(A1) | 기후 대비 쌍대 Brier CI90 하한>0 **양방향**(early 2007–10↔late 2011–14), y-block ℓ=13 귀무 ≤0.10, B=2000 seed 20260907, Murphy 신뢰도 보고(Murphy (1973) 'A New Vector Partition of the Probability Score', J. Applied Meteorology); G2: 우월-아니면-단순-아니면-HOLD | **champion = persistence_pb 전 9셀 → T3 라이브 카드(참고 의견)**, 홀드아웃 미소모 | rung-1 EWMA 9/9, BSS +0.094~+0.898, 귀무 ≤0.017; rung-2 HAR 기후 9/9·EWMA 대비 0/9; rung-3 EWMA가 PB를 양방향으로 이긴 셀 **0/9**, PB 기후 9/9, 귀무 ≤0.033; h63 cross-fit isotonic fallback→raw `docs/review/V13_VOL_RUNG{1,2,3}_*VERDICT*.md`, `data/timeseries_v13/vol/ladder_*.json` | 계약 `multivariate_timeseries_v13_vol.yaml`(`status: live_reference`, `display_tier: t3_live_card`) · 원장 `vol_experiments.jsonl`(3행)·`vol_live.jsonl`(2행)·`approvals.jsonl`(7행) · `champion_coefficients.json` sha256 `1a857850…`(재동결, 이전 `51815bde…`, p 무변경) | 예산 3/8, holdout 0/3(finalist `V13VOL_champion_aec80c65038b` 1개 사전등록), 계수 immutable(`ledger_registry.yaml` L387) |
| **dualdb** | 닷컴↔AI 이중시대 일간 비교 DB; k-NN 아날로그·DTW·LPPL 워크포워드·트윈 대조 → `data/base_rates/*_auto.md` | 결정론 수치모델 예외의 근거 문서(§8) | reference; LPPL은 **demoted**(8-7) | `docs/MODEL_REGISTRY.md`, `dualdb/CHANGELOG.md` #1~#11 | `dualdb/` | 스펙-구현 이탈은 CHANGELOG 기록 |
| **시나리오 V5.2** `scenario_v5_2_scenario_clustered_db_v4` | 닷컴 국면 블록 재표집 3시나리오 경로(S1/S2/S3), `#future` 고객 기본 표면 | display-promotion 계약(`display_promotion.yaml` `active_decision` r2, 2026-08-18) · 배포시점 재봉인 + replay 검증 | **고객 기본 표시**(research_only, `official_or_champion_use: false`) | 분리 지표 S1–S2 표준화 DTW 0.1175→1.7185(임계 +0.8704), S2–S3 DTW 0.123 `docs/DECISIONS.md` 2026-09-07 결정 3 | `scenario_v5_2_weights.yaml`, `scenario_v5_3_separation.yaml` | 게이트 닫힘 시 `stale_last_valid` + 사유 공시(B안) |

인접 참조 계층(가격 분포 아님): `src/ai_fc/market/{kalshi,polymarket,options_bl}.py`는 market_implied/edge **기록 전용**(P3 봉인, 옵션은 risk-neutral 프록시 병기), `data/base_rates/volatility.md`는 `vix-25-90d` 질문의 수동 base rate(무조건부 44%, 8월말 앵커 조건부 33.3%/11.1%).

## 2. 오늘 사이트에 LIVE인 것과 그것을 정직하게 만드는 게이트

**(1) `#timeseries` 가격 카드 = V8 research_reference.** 슬롯 체인 `timeseries = v8 or (v5 or v2 or v1)` (`src/ai_fc/dashboard.py` L460). 포인터 `data/timeseries_v8/multivariate_v8_latest.json`: `status: shadow_live`, `display_state: research_reference`, as_of 2026-08-28, `sealed_gate_pass ∧ operational_pass` 둘 다 true. 정직성 게이트:
- read-model 가드: visible ⟺ 두 게이트 동시 통과, `reference_opinion_only`, HOLD면 숫자 서버 단계 제거(`src/ai_fc/read_model_contract.py` L345–373; `DECISIONS` R8-D3 fail-closed).
- 운영 게이트: 시장 입력 48h(DTWEXBGS 216h), 최근 26원점 CRPS 열위 5% 초과 시 HOLD (`v8.yaml` `operational_gate`). 주말·월요일은 자연 HOLD(`R8D3_PUBLICATION_REVIEW` §9).
- 원점 경과 2단 임계 warn 1 / hold 10 거래일, 만기 지평 실측 병기(`v8.yaml` `origin_age_policy`, `DECISIONS` 2026-09-07).
- 공개 범위: 봉인창(385원점)과 전체창(1,011원점, 개발기간 포함)을 분리 공시하고 봉인창 자체 판정 hold 사유를 인쇄; 방향 적중률·first_touch 점수는 비공개(R8-D4).
- 승격 아님: `promotion.automatic_champion: false`, `minimum_shadow_sessions: 126` — 현재 섀도 원점 2개(2026-08-14·08-28, `shadow_forecasts.jsonl`), 해소 2건(08-14 h1/h5: 구간 적중, 방향 오답, CRPS 기준선 근소 열위 `shadow_resolutions.jsonl`).

**(2) `#timeseries` 5번째 탭 = V13-VOL '변동성 이벤트 기준율' 카드(T3).** 전용 read-model 키 `timeseries_v13_vol`(가격 카드와 결합 금지, `dashboard.py` L466–467). 라이브 값(`data/timeseries_v13/vol/vol_latest.json`, as_of 2026-09-04, VIX 14.53·RV21 0.1294): vix25_h63 기준율 28% [80%: 21–36], vix30_h63 11% [6–16], rv_h63 81% [75–87], vix25_h21 6%, vix25_h5 0.5%. 정직성 게이트:
- 네 게이트(설계 증거 sha 대사·`gates.armed`·계수 핀 3자 일치·NYSE 거래일 신선도 `missing_sessions ≤ 1`) 전부 성립 시에만 숫자, 하나라도 어긋나면 HOLD + 사유, 마지막 값 재사용 없음(`DECISIONS` V13-D4/D5 fail-closed; `read_model_contract.py` L379–415).
- caveat lead '설계창(2007~2014) 스킬 · **홀드아웃 미검증** · 참고 의견 — 매매 신호가 아닙니다' 굵게 상시(`holdout_caveat_bold` 가드), h63 셀 '▲ 보정 약함'(설계창 rel≈0.08), 80% 대역은 델타법 계수 불확실성이지 보정 대역 아님(`v13_vol.yaml` `known_limits`).
- X1 이름충돌 6항: 명칭 '기준율'(예측 아님), 배지 '수치모델 · 당일 수준 지속(PB)', 지평 단위 '영업일', `vix-25-90d` AI 예측과의 괴리 칩은 **표시만**(15%p, 자동 재예측·산술 결합 0).
- 라이브 전진 게이트 사전등록: 셀당 성숙 원점 60 이후 기후 대비 CI90 하한 ≤0이면 자동 강등, 재무장 없음(`v13_vol.yaml` `live_forward_gate`). 계수 재적합 금지.
- 자동화: `timeseries-v2-refresh`(화~토 01:35 UTC) → `timeseries-v8-shadow`(03:10) → `timeseries-v13-vol-live`(03:40, V2 refresh 종속) → pages/verify `workflow_run` 연쇄(`R8D3_PUBLICATION_REVIEW` §4.2·§9, `DECISIONS` V13-D4/D5).

**(3) `#future` = 시나리오 V5.2 3시나리오(고객 기본).** 배포시점 `scenario-v5-2-build --force` + replay 검증, 게이트 닫힘 시 마지막 유효 후보 + 기준일 + 사유 공시(`DECISIONS` 2026-09-02 두 항목).

## 3. 배포 사다리 T0~T4와 각 표면의 위치

사다리 원문: `docs/design/v12_gate_design.md` §4.3 (V13 승계: `docs/design/v13_vol_live_card_display_design_260908.md` §2).

| 단계 | 정의 · 게이트 | 지금 그 단계에 있는 것 |
|---|---|---|
| **T0** 내부 산출물 | 봉인 무변경·원장 무수정 | V1~V7 산출물(포인터 `shadow_validation_hold`/`shadow_gate_hold`, 화면은 validation_pending), V9/V10 run·원장, V12 진단 JSON |
| **T1** 문서·리뷰팩 | 모든 수치에 CI90·귀무·미검증 표기 | V9·V10·V11 동결 판정서, V12 부정결과 계약·최종보고, V12b 파킹 문서, 리뷰팩 `outputs/review-packs/NASDAQ_*` |
| **T2** 대시보드 숨김 패널 | T1 + 게이트 무장 + G0 무손상 + 승인 | (경유만) V13-VOL — 2026-09-08 14:54 진입 후 14:58 T3 전환(`approvals.jsonl` r2). V12는 진입 불가(armed=false) |
| **T3** 라이브 카드 | T2 + 게이트 통과 + X1 해소 + '참고 의견' 상시 | **V13-VOL**(`display_tier: t3_live_card`, 홀드아웃 전이라 caveat 굵게) · **V8 가격 카드**(사다리 문서 이전에 display-promotion 계약 R8-D3로 공개된 research_reference — 본 지도의 T3 상당 배치는 필자 대응이며 계약 원문의 tier 값은 아님) · 시나리오 V5.2(별도 display-promotion 계약) |
| **T4** 실전 자금 결정 근거 | CLAUDE.md P3 게이트(해소 50문항+ & Brier<0.18) | **없음** — tier 값 자체가 없어 구조적 차단(`v13_vol.yaml` `display_tiers_allowed`). LLM 캘리브레이션 원장은 해소 행 9 / 고유 이벤트 5(`SUNDAY_LOOP_FINAL_REPORT.md` 표 J, 2026-09-06) — 게이트 표본 단위 DISTINCT question_id 기준 50에 원거리 |

## 4. 자원 대장 (되돌릴 수 없는 것과 예산)

| 자원 | 소모 | 근거 |
|---|---|---|
| V2 봉인 공개 | 1/1 소모 — FAIL, 재조정 금지 | `data/timeseries_v2/ledgers/sealed_evaluations.jsonl`, `v8.yaml` `v2_benchmark` |
| V6 봉인 run | 1회(385원점 2019+) — hold | `outputs/timeseries_v6/audit/FINAL_REVIEW_SUMMARY.json` |
| V8 dev 예산 | 12/24 (E0~E11) | `data/timeseries_v8/ledgers/development_experiments.jsonl` 12행 |
| V8 holdout finalist | **1/3 소모**(E10, PASS) | `holdout_scorings.jsonl` 1행 |
| V8 봉인 공개 | **1/1 소모**(disclosure #1, 2026-08-30 R8-D2) | `sealed_evaluations.jsonl` `sealed_disclosure_number: 1` |
| V8 섀도 승격 시계 | 원점 2 / 126 | `shadow_forecasts.jsonl` |
| V9 | dev 7/24 · holdout 0/3 · 봉인 0 | `E5_E6_VXN_SPREAD_VERDICT_20260902.md` |
| V10 | dev 12/24(stop-loss) · holdout 0/3 · 봉인 0 | `SINGLES_COMPLETE_STOPLOSS_20260903.md` |
| V11 | 백테스트 0 · holdout 0 | `V11_FREEZE_DECISION_20260903.md` §5 |
| V12 | 트랙 미개시, 계약 기록 소모 0(S3 환산 4), holdout 0, 봉인창 미계산 | `v12_gate_design.md` 표 E1 |
| V13-VOL | dev **3/8** · holdout **0/3**(finalist 1 등록, `holdout_scorings.jsonl` 미생성) · 봉인 0 | `v13_vol.yaml` `evaluations_spent`, `data/timeseries_v13/ledgers/` |
| 봉인 바이트 | V8+V2 `e3ff2fdb…` 0바이트, V8 원장 `b9c492be…` 일치 | `SUNDAY_LOOP_FINAL_REPORT.md` 표 I |
| 캠페인(V9~V13) 비가역 행동 | **0** | `outputs/review-packs/NASDAQ_CAMPAIGN_SESSION_REVIEW_20260908/00_SESSION_TIMELINE.md` 자원 대장; 외부 검토 §B |
| 계산 비용(기록된 것) | V10 6렌즈 검증 7 에이전트·44만 토큰·8.4분; V12 루프 13태스크 완주 | `V10_FREEZE_DECISION_20260903.md`, `SUNDAY_LOOP_FINAL_REPORT.md` 표 A |
| 데이터 구매·발송(사용자) | FirstRate ~$300 미구매(FR-1) · CBOE DataShop QQQ 질의 미발송(V12-D4) | `DECISIONS` 2026-09-08 결정 대기 3·4, `V12_INTRADAY_LEGAL_SOURCE_SURVEY_20260907.md` |
| 거버넌스 사고 | main 잠금 리프스펙 FF 푸시 2회(손실 0) → GOV-1 우회 금지 규칙 | `DECISIONS` GOV-1, `approvals.jsonl` r1 |

미결 사용자 결정: **V13-D3**(홀드아웃 1슬롯, 승인 원문 `V13-D3 홀드아웃 1회 소모 승인 finalist=V13VOL_champion_aec80c65038b`), **V13-D6**(EXIT base rate 배선 — 홀드아웃 PASS 셀 한정), V12-D4, FR-1.

## 5. 관통선 — "효율적 시장 벽 + V13는 지속성"

캠페인 자체 서술(`00_SESSION_TIMELINE.md` '관통 결론'): V8 승자 위에서 외생변수(V9)·분포 계층(V10)·평시 상태신호(V11)·이벤트 재보정(V12) 네 각도가 모두 표본외 개선을 내지 못했다. 이것이 같은 잡음의 재측정이 아니라는 증거는 세 챔피언의 origin별 Δ 상관이 |r| ≤ 0.154로 직교하다는 점(`V9_V10_V11_INDEPENDENT_VERDICT.md` §3). 단 같은 문서가 못 박은 한정: 벽은 **h21/63 CRPS 표적 · 2007–14 창 · 일간 종가 정보집합**에 대한 진술이며, 단독 축이 소진됐을 뿐 축 곱공간은 미표집이고, 일중·옵션 정보집합은 합법 소스가 실재하나 미검증이다(외부 검토 `CAMPAIGN_REVIEW_NEXT_DESIGN_260908.md` 보정 ①). V12 포스트모템은 first_touch 과신의 주인을 "표적"이 아니라 상수-σ i.i.d. 경로 생성기(H3)로 좁혔고, 그 크기는 VR(5)=0.874로 온건해 파킹됐다.

V13-VOL은 캠페인 유일의 진짜 긍정이지만 rung-3가 스킬 라벨을 "**당일 변동성 수준의 지속**"으로 정정했다 — EWMA 평활조차 PB 대비 증분 0/9. 따라서 가치는 시장 엣지가 아니라 CLAUDE.md 1차 목표(EXIT 트리거 이벤트 확률화)의 **base rate·outside view 공급**이며(외부 검토 보정 ②), 그 공급조차 홀드아웃(2015–18) 검증 전이라 화면에 '홀드아웃 미검증'을 굵게 단 참고 의견으로만 서 있다.

## 6. 인용 문헌

Brier (1950) 'Verification of Forecasts Expressed in Terms of Probability', Monthly Weather Review · Murphy (1973) 'A New Vector Partition of the Probability Score', J. Applied Meteorology · Politis & Romano (1994) 'The Stationary Bootstrap', JASA · Diebold & Mariano (1995) 'Comparing Predictive Accuracy', J. Business & Economic Statistics(V8 봉인 원장 `diebold_mariano` 필드) · Barone-Adesi, Giannopoulos & Vosper (1999) 'VaR without correlations for portfolios of derivative securities', J. Futures Markets(FHS) · Zadrozny & Elkan (2002) 'Transforming Classifier Scores into Accurate Multiclass Probability Estimates', KDD(isotonic PAV) · Gneiting & Raftery (2007) 'Strictly Proper Scoring Rules, Prediction, and Estimation', JASA(CRPS) · Corsi (2009) 'A Simple Approximate Long-Memory Model of Realized Volatility', J. Financial Econometrics(HAR) · Halawi et al. (2024) 'Approaching Human-Level Forecasting with Language Models', arXiv:2402.18563(`docs/ARCHITECTURE.md`) · Ansari et al. (2024) 'Chronos: Learning the Language of Time Series', arXiv [식별번호 미검증].


---

# [reader:data] 데이터 자산과 공백

## 데이터 자산과 공백

> 거버넌스 전제(이 절의 모든 판단에 적용): ① LLM이 개입하는 과거 질문 백테스트는 금지(CLAUDE.md 원칙 5). 결정론 수치모델의 과거 적합·워크포워드만 허용(dualdb 스펙 v1.0 §8 예외, DECISIONS 8-6)하되 산출물은 base rate 참조이지 캘리브레이션 표본이 아니며, 하이퍼파라미터(탐색 경계·창 선택)가 정점 지식을 간접 내포할 수 있다는 caveat를 병기한다. ② ML 게이트: 캘리브레이션 보정은 해소 100+, 앙상블 가중 학습은 200+ 이후. `src/ai_fc/ml`(Chronos-Bolt·T5·Chronos-2·FinBERT)은 추론 전용, 결합은 고정 규칙(중앙값·불일치 지수)만. ③ 홀드아웃(2015–2018)·봉인(2019+)은 사전등록 finalist당 1회, 사용자 명시 승인 시에만 소모. 설계창 2007–2014. 음성대조는 y-블록 순열(p-순열 귀무는 누수, `multivariate_timeseries_v13_vol.yaml` prohibitions). 채택 기준은 stationary block bootstrap CI90(Politis & Romano (1994) 'The Stationary Bootstrap', JASA) 양방향 전이 — in-sample 통과 ≠ 채택. ④ V8/V2 봉인 코드·데이터 바이트 불변(`e3ff2fdb…`), `forecasts/`·`calibration/` append-only. ⑤ 모든 출력은 참고 의견. P3 게이트(해소 50문항+, Brier<0.18) 전 자본 결정 근거 금지 — 현재 `calibration/ledger.csv`는 9행·해소 질문 5개. ⑥ PIT(ALFRED 네이티브 vintage / captured-forward 영수증)와 합법 라이선스가 데이터 적격의 전제. 스크래핑 없음. FirstRate·CBOE 구매·발송은 사용자 결정. 아래 수치는 전부 2026-09-08 저장소에서 직접 읽은 값이다.

### 1. 보유 데이터 자산 지도

**표 1 — PIT 등급별 레인 (`data/contracts/multivariate_timeseries_v2.yaml` data_policy 등급: native_pit / reconstructed_market_archive / captured_forward)**

| 레인 (경로) | 시리즈·범위 | 주기 | PIT 등급 | 라이선스 지위 | 알려진 공백 |
|---|---|---|---|---|---|
| **V1 정본 ALFRED vintage 스토어** (`data/timeseries/facts/observations.parquet`, raw 549 gz·영수증 1,250행) | 26 시리즈 · 1,505,217행. 성장: PAYEMS·UNRATE·INDPRO·HOUST·GDPC1(첫 vintage 1996-01), RSAFS(2001-07). 물가: CPIAUCSL(1996-02)·CPILFESL(1997-01)·PCEPI·PCEPILFE(2000-08). 유동성·신용: M2SL(1996-01)·TOTCI·TOTLL(1996-12, V9-D5 백필 완료)·WRMFNS(2002-11)·WALCL(2011-07)·WTREGEN(2008-12)·RRPONTSYD(2016-03)·NFCI(2011-06, 916,923행). 시장: DGS2·DFF(2005-07)·VIXCLS(관측 2004-06, 첫 vintage 2010-11)·NASDAQCOM(2014-05)·T10Y2Y(2014-01)·DTWEXB(2014-03)·DTWEXBGS(2019-02)·BAMLH0A0HYM2(관측 2023-08~) | release-calendar / 일간 | **native_pit** (realtime_start 보존, final-vintage 대체 금지 — `alfred.yaml`) | FRED 공식 API approved. 단 **KNOWN_LIMITS 34**: 약관의 AI/ML "development" 문언·store/cache 금지와 PIT 아카이브 커밋의 긴장 미해결(법률 영역) | 일간 시장 시리즈의 vintage 온셋이 늦어(VIXCLS 2010, NASDAQCOM 2014) 설계창 PIT는 이 레인으로 불가 → V2 재구성 아카이브에 의존. HY OAS는 2023+만(ICE 3년 롤링) → 설계창 신용스프레드 불가(`v9.yaml` blocked `daily_credit_spread`) |
| **V2 공식 시장 아카이브** (`data/timeseries_v2/ledgers/market_observations.jsonl` 47,741행·영수증 142·raw 89파일) | NASDAQCOM 1995-01-03~(FRED, 7,973) · VIX 1990-01-02~(CBOE `VIX_History.csv`, 9,266) · DGS2·DGS10 1990~(Treasury XML, 각 9,176) · DTWEXB 1995~2019(6,328)+DTWEXBGS 2006~(5,179, Fed H.10, 브리지 규칙 `v1.yaml` registered_historical_bridges) · FED_EBP 1973-01~2026-07 월간(643) | 일간(EBP 월간) | reconstructed_market_archive 17,512행 + captured_forward 30,229행. 규칙: `available_at ≤ origin`, observation_period backfill 금지, release-state carry-forward는 available_at 이후만, **재구성본은 native PIT가 아님을 명시**(`reconstructed_archive_is_native_pit: false`). EBP는 전 이력 개정 가능 → 캡처 시점 이후만 유효(`data/timeseries_v2/README.md`) | FRED·Treasury·Fed 공식. **CBOE는 회색지대**(12-1 명시 금지 조항 vs fair use 유보; 12-5 대체 경로 없음; `docs/cboe_permission_request_draft.md` 미발송) | BAMLH0A0HYM2 봉인표본 불가로 제외(`v2.yaml` excluded_required_sources). V8~V13 전부 이 레인을 read-only 상속 |
| **V4 후보 스토어** (`data/timeseries_v4/ledgers/observations.jsonl` 113,615행, 스냅샷 2026-08-20) | VIX9D 2011-01~ · VIX3M 2009-09~ · VVIX 2006-03~ · SKEW 1990-01~ · CBOE 미국주식 거래량 4종(총액·Tape C 비중·장외 비중·건수) 2009-01~ · NASDAQ100 1995~(private locator) · Cleveland Fed 물가 나우캐스트 2012~ · Philly Fed SPF(EMP·CPI·UNEMP·RECESS 평균·분산) 1990~ · CME FedWatch·BLS 실적·NFP 컨센서스(2026-08-06/07 캡처만) | 일간/분기/이벤트 | reconstructed_market_archive · reconstructed_official_forecast_archive · captured_forward(FedWatch 과거는 `licensed_api_required`) | CBOE(위와 동일 회색) · Fed 지역은행 공식 · CME 유료 | V4/V5 계보는 게이트 미통과(`v6.yaml` predecessor `shadow_gate_hold`) — VIX 기간구조·SKEW·VVIX **지수 수준**은 시도됐으나 행사가별 표면은 없음 |
| **V9 시장 레인** (`data/timeseries_v9/ledgers/market_observations.jsonl`) | VXN 2009-09-14~(4,270행, CBOE `VXN_History.csv`) | 일간 | reconstructed_market_archive | private locator(raw 비커밋, 12-1/12-5 자세) | 온셋 2009 → 서브창(2010–2014) 전용. V9_E6 무효익(|ρ|=0.011 직교인데도) |
| **FRED current-vintage 시그널** (`fred_market_signals.yaml`) | BAMLH0A0HYM2·DFII10·DTWEXBGS·WALCL·WTREGEN·RRPONTSYD·DGS10·BAMLC0A0CM·VIXCLS | 영업일 | **captured** — "historical current-vintage rows are not valid for backtests" | approved(12-6 공식 API 전환) | `source_registry.yaml`·`docs/generated/licenses.generated.md`(확인일 2026-08-01)는 endpoint를 아직 `fredgraph.csv`로 적고 있어 계약과 불일치(문서 드리프트). v5 `sources.py`도 fredgraph 잔존(OPEN_QUESTIONS C-3) |
| **통계 authoritative 스토어** (`data/statistics/official_store/`, 정규화 53,660행·영수증 890) | 49 시리즈: NASDAQCOM·SP500·NASDAQSOX·CBBTCUSD·DCOILWTICO·T10Y3M·T10Y2Y·NFCI·M2SL·MMMFFAQ027S·Z.1 가계·기업 계열(BOGZ1…·FL663067003 브로커딜러 마진 프록시·FL103163005)·BEA GDP·Y034RC1Q027SBEA·Y001RC1Q027SBEA·Census C30 건설(전력·데이터센터·통신·컴퓨터전자)·SEC_IPO_QUARTERLY·DRTSCILM·HQMCB10YR | 일~분기 | captured(현행 vintage) — `authoritative_statistics_sources.yaml`: 정부·중앙은행·규제기관·거래소만 수치 입력 허용, 리서치·미디어·집계 벤더는 insight-only | 미국 정부 저작물 + FRED API. SEC는 연락처 UA 규약(KNOWN_LIMITS 35) | reference_only, model_use 금지. 참조 JSON: ICI 주간 주식 ETF 플로우(2026-07-08~, 5행) · NAHB HMI 1995~ |
| **IPO 레이어** (`data/statistics/ipo/`, dualdb `ipo_annual` 14행) | Ritter 워크북(기술주·인터넷 플래그) 1995–1999 vs Renaissance 정의 AI 코호트 2023–2026 · SEC EDGAR 분기 IPO 건수 | 연/분기 | 큐레이션(Tier-3 근사, KNOWN_LIMITS 12) | Ritter 학술 페이지 — 재배포 약관 미기록 [미검증] | 1999 적자 IPO 72% vs 2025 66%; 첫날수익 등은 근사치 |
| **dualdb 닷컴↔AI 이중시대 DB** (`dualdb/db/dualdb.sqlite`, raw 470파일) | price_daily 285,289행·33 시리즈(Yahoo: ^IXIC 1971~·^SPX·^NDX 1985~·^SOX 1994~·^VIX·^TNX·^N225·BTC-USD·IBB + 트윈 12·AI측 12 종목). 1995–2004 ^IXIC 종가 정본=FRED NASDAQCOM(9-5). macro_daily 8(FRED)·macro_monthly 8(CPI·FEDFUNDS·M2SL·PAYEMS·UNRATE·USREC 1854~·Dow 1914–68·Shiller S&P 1871~) · valuation Shiller CAPE 1871~2023-09 · factor Ken French 1927~2026-05 · margin_debt FINRA Tier-2 14개월(2025-05~2026-06) · event 48 · dotcom_casualty 25 · capex_buildout 11(FCC 근사) · model_run 9(knn·dtw·lppl·twins) | 일/월/연 | **비-PIT 현행 vintage**(Yahoo 조정종가는 소급 개정) — 결정론 모델 base rate 전용(§8 예외) | Yahoo 자동수집 금지 문언(12-5·12-8) — dualdb 백본이 여전히 Yahoo; O·DHI·IYR은 대안 부재(12-8). Shiller·French 학술 데이터 약관 미기록 [미검증]. Stooq JS 게이트로 2026-07-15 이후 차단 | sentiment_weekly 0행(AAII 수동 대기, KNOWN_LIMITS 28), fundamentals_annual 0행, 닷컴 마진부채 1997–2003 gap, 사망 기업 일간 데이터 부재(생존자 표본, 14·15) |
| **시장내재 아카이브** (`data/ml_history/2026.jsonl` 21행, 2026-07-15~) | Polymarket gamma API(FOMC 인상 버킷 합산) · CBOE 지연시세 QQQ 체인→IV 보간 N(d2)(risk-neutral, ^IXIC→QQQ 프록시) · Kalshi(시장 목록만, 호가 공란 실측) | 주간 | captured_forward만. **옵션 표면 이력 0** | CBOE 지연시세는 12-1 회색; Polymarket·Kalshi 공개 API 약관 미기록 [미검증] | P3 전 기록·표시 전용. 역사 옵션 surface·put/call·IV 기간구조 미보유 |
| **ML 추론 산출** (`src/ai_fc/ml`) | Chronos-Bolt-small·Chronos-T5-small·Chronos-2(Apache-2.0, 로컬 CPU) 분위수·경로터치 · FinBERT 감성 — 헤드라인은 GDELT(12-7, 인용 의무·API 불안정 3/5 성공) | 주간 | captured_forward | Google News RSS 중단(12-4a). GDELT 명시 허용 | 사전학습 코퍼스가 2019+ 포함 → 봉인창 오염 위험으로 TSFM 파인튜닝 보류(포스트모템 D1) |
| **파생·시나리오 계층** | `data/scenarios`(V5.2 팬차트)·`rate_events/registry.yaml`(사전등록 6창)·`calendar/events.csv` 53건(FOMC·CPI·NFP·GDP·NVDA IR 공식 일정)·`liquidity`(WALCL−WTREGEN−RRP)·`cross_asset`(FRED NASDAQCOM·CBBTCUSD + Yahoo O·DHI·IYR)·`realty_income`·`ai_buildout`(SEC companyfacts capex)·`ai_capital_cycle`(SEC-first D1/D2) | 주간 | captured | 위와 동일 | D0 후보 계약: NFCI(legal_review_required)·STLFSI4(monitoring)·CFTC COT BTC(monitoring)·FINRA 마진(**blocked_legal_terms**)·Fed Z.1 마진 프록시(monitoring)·DefiLlama·BTC ETF·IEA/EIA(review_required) |
| **V13-VOL 변동성 기준율** (`data/timeseries_v13/vol/`) | champion=persistence_pb 9셀, 계수 sha `1a857850…`, `vol_latest.json` 2026-09-04, 라이브 원장 2행 | 화~토 | V2 read-only(captured_forward) | — | 홀드아웃 미소모(V13-D3 대기), 배선 전(V13-D6), h63 신뢰도 rel≈0.08 |
| **예측·원장** | `forecasts/2026` 72파일 · `calibration/ledger.csv` 9행(질문 5) · `questions/registry.yaml` 약 43문항 · V8 봉인원장 1행(전체창 1,011원점 pass / 봉인창 385원점 hold: GFC 원점 0) | 이벤트 | append-only | — | P3 표본 50문항까지 원거리 |

### 2. 구조적 공백 (검토자가 먼저 봐야 할 것)

1. **옵션 정보집합 전무**: VIX 계열 지수 수준(VIX·VIX9D·VIX3M·VVIX·SKEW·VXN)만 있고 행사가별 IV 표면·VRP·put/call·딜러 감마 없음. 외부 검토가 "유일한 미검증 정보집합"으로 지목(`CAMPAIGN_REVIEW_NEXT_DESIGN_260908.md` §C-4).
2. **일중 전무**: `data/intraday/` 부재. 일간 ACF(1)=−0.076·VR(5)=0.874(V13 P1 진단)의 되돌림 구조는 일간에서만 계측됨.
3. **설계창 신용스프레드 불가**: HY OAS 2023+, EBP는 월간·전이력 개정, NFCI vintage 2011~. V9 blocked 목록 그대로.
4. **심리·포지셔닝·브레드스 부재**: AAII 0행, UMich 미보유, ICI 플로우 5주, CFTC는 BTC D0만, FINRA 마진 14개월(역사 xlsx 법적 차단), 공매도잔고·A/D 라인·200일선 상회 비율 없음. V4 breadth 블록은 NDX/Composite 상대강도 1개뿐.
5. **컨센서스·서프라이즈 이력 없음**: `market_consensus`·`market_implied_rate_distribution`은 영수증 기반 captured-forward(NFP_CONSENSUS 1행). FedWatch 과거는 유료.
6. **시장 일간 시리즈의 first-print 부재**: V2·V4는 재구성본. VIX 아카이브는 매회 전체 CSV 재다운로드(13파일)로 캡처 시점만 보증.
7. **DTWEXBGS 주간 발행 SLA 구조적 stale**(KNOWN_LIMITS 33), NASDAQCOM fredgraph 피드 정체 이력.
8. **약관 긴장 미해결 3건**: FRED AI/ML·캐시 조항(34), CBOE fair use 유보(12-5), Yahoo 자동수집(dualdb·O/DHI). "무료 개인 티어"는 법인 대표에게 닫혀 있음(12-7 교차 발견) — 새 소스 검토 시 "비영리라서 괜찮다" 논거 금지.

### 3. 미보유 후보 DB 평가표

캠페인 부정결과의 범위: V9(외생 열 6종: M2SL·TOTCI·TOTLL·WRMFNS·VXN 스프레드)·V10(분포 계층)·V11(평시 직교 상태: 모멘텀·growth factor 등 9 프록시)·V12(first_touch 재보정)는 모두 **일간 종가 정보집합**에서 표본외 개선 실패. Welch & Goyal (2008) 'A Comprehensive Look at the Empirical Performance of Equity Premium Prediction', RFS의 표본외 예측 실패 결과와 정합. 따라서 "이미 덮음" 판정은 (a) 같은 정보집합(일간 종가·주간 매크로)의 변형인지, (b) 새 정보집합(옵션·일중·포지셔닝)인지로 가른다.

| 후보 | 추가되는 정보집합 | PIT 가능성 | 라이선스 | 대략 비용 | 부정결과가 덮는가 | 메모 |
|---|---|---|---|---|---|---|
| **CBOE DataShop / LiveVol** (QQQ 옵션 트레이드·NBBO·IV/그릭스 Calcs, 2004+) | 행사가별 IV 표면·기간구조·스큐·VRP — 물리분포 꼬리(Bollerslev, Tauchen & Zhou (2009) 'Expected Stock Returns and Variance Risk Premia', RFS; Bollerslev, Todorov & Xu (2015) 'Tail risk premia and return predictability', JFE) | 상급(캡처 영수증, as-traded). 진짜 일중 IV 표면 2007–2014는 무벤더 공백(조사 §4) | Subscriber Agreement §1 내부연구 허용, §2b 파생 표시 조건부(재배포권 선택·역설계 불가·지수 아님). QQQ 프록시로 Nasdaq 제3자 오버레이 회피 — **소유자 약관 원문 재확인 필요** | EOD $500/월, 일중 애드혹 $1.5–2.5k/월, 구독 $5–6k/월 | **아니오** — 유일 미검증 정보집합. V4의 VVIX·SKEW 지수 수준 시도와는 다름 | V12-D4 질의 초안 `docs/design/v13_cboe_datashop_qqq_request_260907.md` 미발송. 외부 검토 "지금 발송". ETF 배당·조기행사 차이 caveat |
| **FirstRate Data** (NDX·QQQ·구성종목 1분봉 2000+, 틱 2010+) | 일중 실현변동성(Andersen, Bollerslev, Diebold & Labys (2003) 'Modeling and Forecasting Realized Volatility', Econometrica), 일중 되돌림, 배리어 터치의 일중 검증 | **중** — back-adjust 재구성본, first-print 아님. 캡처 영수증만 | 연구+파생물 발행 허용(귀속 표기), raw 재배포 금지 → `data/intraday/firstrate_raw/` gitignore | ~$300 일회, 무키 | **부분** — V13 rung-2가 일간 HAR 증분 0/9 → 일중 RV의 변동성 사건 이득 작음. 가치는 파킹된 V12b(경로 생성기)에 있음 | FR-1 저비용·후순위(반대 아님). 계획서 `v13_firstrate_acquisition_plan_260907.md`. 무료 2주 샘플 선검증 권고 |
| **AlgoSeek / NYSE Daily TAQ / Nasdaq ITCH / Kibot / Databento / Polygon** | 틱·NBBO·오더북(TAQ 2003+, AlgoSeek 2007+, ITCH ~2010+, Databento 2018+, Polygon 2004+) | TAQ·ITCH 최상(first-print), AlgoSeek 상급, Polygon 강 | TAQ는 WRDS 학술 게이트(비학술 CEO 접근 불가) 또는 고가 상업; Polygon 표시 금지 | 엔터프라이즈(AlgoSeek 분봉 ~$4k+$630/월 [미확인]), Databento 종량 | 아니오(일중) | 조사 §1·§4: "저가·표시합법·vintage-PIT 동시성 부재". 틱→1996 소급 벤더 없음 |
| **OptionMetrics IvyDB US** | EOD IV 표면(만기×델타)·그릭스 1996+ — 설계창 전 구간 커버 | 강(버전 태깅 vintage) | WRDS 학술 전용, 상업 별도 고가 | 기관 애드온 [미확인] | 아니오 | 학술 제휴 없이는 경로 없음(조사 §3) |
| **Nasdaq Data Link** | USETH/GITH 틱(2014/2012+), 각종 대체 데이터 | 중상, 창 하단 결측 | 저장소 미사용(12-3). 무료 익명 티어 약관 문서 NOT FOUND — 회색 | 프리미엄 구독 | 해당 없음 | 보유 FRED·Treasury 시리즈와 중복. 우선순위 낮음 |
| **CRSP / Compustat** | 상장폐지 포함 무생존편향 수익률·기초 재무 | CRSP 월/일 확정치, Compustat point-in-time 스냅샷 존재 여부 [미검증] | WRDS 학술 게이트 | 기관 | 아니오 — 단 V8 계보가 아니라 **dualdb 아날로그 레이어**의 공백(사망 기업 일간·닷컴 사상자, KNOWN_LIMITS 14) | 접근 경로 없음. 대안: SEC EDGAR 전문 + 파산 공시로 부분 보완 |
| **Refinitiv / Bloomberg** (I/B/E/S 컨센서스, 매크로 컨센서스) | 실적·매크로 컨센서스 이력, 서프라이즈 계산의 분모 | I/B/E/S 상세 이력은 타임스탬프 보유 [미검증] | 재배포·파생 표시 엄격 | Bloomberg 단말 연 수만 달러 [미검증]; Refinitiv 데이터 라이선스 별도 | 아니오 — 그러나 1차 목표(EXIT 이벤트 확률화) 대비 비용 불균형 | `market_consensus` 계약은 영수증 소스를 허용하지만 이력 백필 금지(`synthetic_backfill: prohibited`) |
| **Fed Board H.8 / H.15 원생산자 다운로드** | 없음(TOTCI·TOTLL·예금은 ALFRED로 이미 보유, DGS는 Treasury 원본) | Board DDP는 **현행 vintage만** — ALFRED가 우월(V9-D5 결정) | 공공 저작물 | 무료 | **예** — V9_E2·E3 무효익 | 은행 계약 §4.1의 원생산자 조항은 PIT 사유로 이번 트랙 미적용(선례 기록) |
| **BIS** (credit-to-GDP gap, 실효환율, 총신용) | 글로벌 신용 사이클 (분기) | 개정 있음, vintage 없음 → reconstructed | 무료, 출처 표기 | 무료 | 사실상 예 — 주간 신용(TOTCI·TOTLL) 무효익이 분기 신용에도 연장될 개연성; 일간 표적에 저주파 exog는 V9 교훈 | dualdb 다중 시대(japan1989 등) base rate에는 유용 |
| **Treasury 입찰 결과** (FiscalData `auctions_query`) | bid-to-cover·tail·간접낙찰 — 수급 충격 | 발표 시각 captured; 과거 결과는 발표일 확정 | 공공 | 무료 | 아니오(미시도) | `treasury_fiscaldata` 소스 이미 등록 → 온보딩 비용 낮음. 다만 DGS2 변화 자체가 이미 endogenous |
| **CFTC COT** (TFF NDX 선물 포지션) | 레버리지펀드·자산운용사 순포지션 (주간, 화요일 기준·금요일 발표) | 발표일 규칙 알려져 reconstructed 가능, 이후 captured | 공공(이미 `cftc.gov` 깨끗 소스 판정 12-8) | 무료 | 부분 — 주간 저주파는 V9 교훈이나 포지셔닝은 새 정보집합 | v5 `cftc_tff` 스펙·BTC D0 계약 존재. 온보딩 비용 낮음, 기대 이득 불확실 |
| **FINRA 공매도잔고·마진** | 격주 공매도잔고(Rapach, Ringgenberg & Zhou (2016) 'Short interest and aggregate stock returns', JFE — 월간 지평), 월간 마진부채 1997+ | 공표일 기준 captured; 결제일 지연 | **D0 `blocked_legal_terms`**(`finra_margin_statistics_d0.yaml`) | 무료 | 아니오 | 법적 게이트 선행. 대체는 Z.1 브로커딜러 프록시(분기, 보유) |
| **AAII / UMich 심리** | 주간 강세비율·월간 소비자심리(예비/확정) | UMich 발표일 확정, AAII 주간 | AAII 자동 파싱 부적합·수동 다운로드(KNOWN_LIMITS 28), 재배포 약관 [미검증]; UMich 재배포 제한 [미검증] | 무료~저가 | 부분 — V11 평시 상태신호 실패와 같은 유형(저주파 심리) | dualdb `sentiment_weekly` 파서 대기. Baker & Wurgler (2006) 'Investor Sentiment and the Cross-Section of Stock Returns', JF |
| **Google Trends** | 검색 관심(Da, Engelberg & Gao (2011) 'In Search of Attention', JF) | **불가** — 상대 척도·표본 재추출로 재현 불가 | 스크래핑 금지 | 무료 | 아니오 | PIT 부적격으로 사실상 배제 |
| **SEC EDGAR 전문검색** (FTS 2001+) | 8-K·S-1 이벤트 카운트, 파산·감원 공시 | **native**(accepted 타임스탬프) | 공공, 연락처 UA | 무료 | 아니오 | `sec_edgar` 이미 approved. dualdb 사상자·IPO 레이어 보강에 적합, NASDAQ 변동성 표적에는 간접 |
| **실적 캘린더** (벤더) | 실적 시즌 군집·서프라이즈 | 벤더 과거 캘린더는 PIT 불명 | Nasdaq.com·Zacks 등 약관 제한 | 유료 | 아니오 | `calendar/events.csv`는 공식 IR 일정만(NVDA). 컨센서스 없이는 서프라이즈 불가 |
| **매크로 서프라이즈 지수** (Citi CESI) | 컨센서스 대비 실적 집계 | Citi 지수는 재배포 불가 | 독점 | 단말 종속 | 아니오 | 대체: Scotti (2016) 'Surprise and uncertainty indexes', JME 방법론(Fed 공개) [미검증 URL] 또는 보유 SPF·Cleveland 나우캐스트로 자체 구성 |
| **NY Fed Nowcast / Philly Fed ADS** | 실시간 성장 상태(Aruoba, Diebold & Scotti (2009) 'Real-Time Measurement of Business Conditions', JBES) | 양쪽 vintage 아카이브 공개 [미검증] | 공공 | 무료 | **예** — V2 DFM growth factor(ALFRED 기반)가 동일 정보, V11 P7 growth→CRPS 표본외 전이 실패 | 보유 SPF도 같은 방향 |
| **Chicago Fed NFCI** | 금융여건 105지표 합성(Brave & Butters (2011) 'Monitoring financial stability', Chicago Fed Economic Perspectives) | ALFRED vintage 2011-06~ (보유) — 설계창 부분 | D0 `legal_review_required`(model_use_rights) | 무료 | 부분 — V9 conditionally_registered(온셋 부족)로 미검정 | 서브창 프로토콜(V9-D7)로 검정 가능하나 위기(2008) 미포함 한계 |
| **브레드스** (A/D, 신고가/신저가, MA 상회 비율) | 시장 내부 참여도 | 구성종목 PIT 멤버십 필요 → CRSP/Nasdaq 라이선스 없이는 생존편향 | 거래소·벤더(Barchart 등) 약관 제한, 공공 무료 없음 | 유료 | 아니오 | V4 breadth 블록은 NDX/Composite 상대강도 1종. 자체 구성은 dualdb 24종목으로 불가(표본 편향) |
| **Kalshi·Polymarket 과거 시세** | 예측시장 캘리브레이션 대조 | 캡처 전진만(현행). 과거 API [미검증] | 공개 API 약관 미기록 [미검증] | 무료 | 해당 없음(P3 봉인 기록 전용) | Kalshi 호가 공란 실측(2026-07-15) |

### 4. 검토자용 판정 요약

- **덮이지 않은 정보집합은 둘뿐**: 옵션 표면(CBOE DataShop QQQ)과 일중(FirstRate 등). 나머지 후보는 (i) 일간·주간 exog의 변형으로 V9/V11이 이미 벽을 확인했거나, (ii) PIT 부적격(Google Trends), (iii) 법·접근 게이트(WRDS·FINRA·Citi)다.
- **PIT 등급이 가장 좋은 신규 후보는 SEC EDGAR 전문(native)·Treasury 입찰·CFTC COT(발표일 확정)** — 전부 무료·공공이며 온보딩 비용이 낮지만 1차 목표(변동성·EXIT 이벤트)와의 연결은 간접적이다.
- **구매 결정(사용자)**: CBOE 질의 발송은 리드타임 독립이라 지금이 합리적, FirstRate는 저비용·후순위. 둘 다 취득 ≠ 트랙 개시 — 새 사전등록·건전 y-블록 귀무·CRPS 무손상 제약·봉인 무접촉이 전제(`V12B_PARKED_20260908.md` 재개 조건 4항).
- **문서 정합 결함 2건**: `source_registry.yaml`/`licenses.generated.md`의 fred_market_signals endpoint가 fredgraph로 잔존(12-6과 불일치, 확인일 2026-08-01 stale); v5 `sources.py` fredgraph 잔존(C-3). 데이터 결함은 아니나 감사자가 스크랩 중으로 오독할 수 있다.


---

# [reader:methods] 검증 기계와 방법론 자산

# 검증 기계와 방법론 자산

> 이 절은 저장소에 **이미 존재하는** 평가·검증 기계를 파라미터 수준까지 지도화하고, 고급 프로그램에 **없는** 것을 적는다. 모든 수치는 저장소 파일에서 읽은 값이며(재계산·추정 없음), 확인 못한 부분은 `[미검증]`.

## 0. 이 자산이 놓인 거버넌스 (전제 — 어떤 자산도 이를 넘지 못한다)

1. **LLM 백테스트 금지** (`CLAUDE.md` 원칙 5). 결정론 수치 모델만 과거 적합·워크포워드 허용 — 사용자 제공 dualdb 스펙 v1.0 §8을 `docs/DECISIONS.md` 8-6이 헌법에 이식(스펙 원문은 저장소 밖). 조건 ① 산출은 base rate 참조이지 캘리브레이션 표본 아님 ② 하이퍼파라미터의 정점지식 내포 caveat 명기 ③ LLM 개입 평가엔 적용 불가.
2. **ML 게이트**: isotonic/Platt 실보정은 해소 100+, 앙상블 가중 학습은 200+ 뒤. `src/ai_fc/ml`(Chronos-Bolt·Chronos-2·T5·FinBERT)은 추론 전용·가중치 갱신 0, 결합은 고정 규칙(중앙값·불일치 지수)만.
3. **홀드아웃(2015–2018)·봉인(2019+)** 은 사전등록 finalist당 1회, 사용자 명시 승인 시에만. 설계창 2007–2014. 건전 음성대조 = y-블록 순열(p-순열은 누수, V13 계약 `p_permutation_null_as_negative_control: true`). 채택 기준 = early↔late 양방향 전이 + 정지블록 부트스트랩 CI90. in-sample 통과 ≠ 채택.
4. V8/V2 봉인 코드·데이터 바이트 불변(해시 `e3ff2fdb…`), `forecasts/`·`calibration/` append-only.
5. 모든 산출은 **참고 의견**. P3 게이트(해소 50문항+ & Brier<0.18) 전 자금 결정 근거 불가. 현재 원장 실측: `calibration/ledger.csv` **9행 · 5문항** — 게이트와의 거리는 문항 45개.
6. 데이터는 PIT(ALFRED vintage·captured_forward)·합법 라이선스만. FirstRate·CBOE 구매는 사용자 결정.

## 1. 점수 함수와 LLM 원장 채점 (구현 위치·정의)

| 자산 | 구현 | 정의·파라미터 |
|---|---|---|
| CRPS | `src/ai_fc/timeseries/backtest.py::sample_crps`, `evaluation.py::crps_ensemble` | 경험분포 E\|X−y\| − ½E\|X−X′\| (정렬 O(n log n) 폐형). Gneiting & Raftery (2007) 'Strictly Proper Scoring Rules, Prediction, and Estimation', JASA |
| 꼬리가중 CRPS | `timeseries_v3/backtest.py::tail_weighted_crps` | 9분위 격자, 가중 1+4\|q−0.5\| (HOLD 트랙 잔존) |
| pinball | `timeseries/backtest.py::pinball_loss` | p10/p50/p90 보고 (R8-D4로 공개 제외) |
| Brier · log | `evaluation.py::brier_score`, `log_score` (eps 1e-12) | V13 계약 `scoring: [brier, log_score]` |
| Murphy 분해 | `db/queries.py::murphy_decomposition` (n_bins=10) | Brier = REL − RES + UNC. Murphy (1973) 'A New Vector Partition of the Probability Score', J. Applied Meteorology |
| 캘리브레이션 곡선 | `db/schema.sql::v_calibration_curve` | 확률 10분위 × 평균 결과 |
| rolling Brier | `db/queries.py::rolling_brier` window 10 | 추세 감시 |
| 게이트 | `v_gate_status`: P2 = DISTINCT question_id ≥30 ∧ Brier<0.20, P3 = ≥50 ∧ <0.18 (`config.py` GATE_P2/P3) | 표본은 `v_brier_primary`(research_status='failed' 제외, 8-2c). 도메인 차단 `v_domain_skill`: Brier>0.22 ∧ n≥10 |
| 섀도 보정 | `config.py` EXTREMIZE_ALPHA=√3, `shadow_extremized` 열 표시 전용 | log-odds 극단화, 공식 확률 아님 (8-9). 근거 문헌은 config 주석 'Neyman-Roughgarden' `[미검증: 서지]` |
| K회 중앙값 | `AI_FC_REASONING_RUNS` 기본 1 | P2 게이트 후 활성 (사용자 결정) |

## 2. 쌍대 손실차·정지 블록 부트스트랩·DM

**쌍대 손실차** — `timeseries_v8/backtest.py::paired_differences_vs_best`: 주간 원점마다 h21·h63의 (모델 CRPS − 최선 기준선 CRPS)를 평균해 **원점당 1값**(교차지평 종속 보존) → `_stationary_bootstrap_mean_ci`. V2도 동일(`timeseries_v2/backtest.py`, method `weekly_origin_mean_of_21d_and_63d_raw_loss_differences`).

**정지 블록 부트스트랩** (Politis & Romano (1994) 'The Stationary Bootstrap', JASA) — 트랙별 좌표가 다르다:

| 트랙 | ℓ | B | seed | CI |
|---|---|---|---|---|
| V2/V8/V9/V10 포크 (`timeseries/backtest.py::_stationary_bootstrap_mean_ci`) | mean_block **10** (기하 재시작) | 2000 | **19_960_107** | 90% (5/95), n<20이면 NaN |
| V5 `timeseries_v5/evaluation.py` | 13 | 2000 | 52026 | 90% |
| V6 `timeseries_v6/research_gate.py` | 13 | 5000 | 62026 | 90% |
| V9 계약 `qualification_statistics` | `two_times_horizon` | 2000 | — | mde 지평별 공표 |
| V10 계약 `dual_statistics` | 13주 | 2000 | — | mde50 공표 |
| V11 `timeseries_v11/orthogonal_diagnostic.py` | 13 | 2000 | 20260903 | 90% |
| V12 계약 G3 | 13 | 2000 | 20260902 | percentile [5,95] |
| V13 `tools/v13_vol_run.py::block_boot_ci`, `timeseries_v13/features.py::block_bootstrap_cov` | 13 (기하 길이·순환) | 2000 | 20260907 | [5,95]; Cov(β)→델타법 band80 z=1.2816 |

**MDE** = 1.645·bootstrap_se 를 셀마다 병기(V13 `gate.mde`, V12 `point_estimate_form`). |Δ|<MDE는 '결정적 증거 없음' 라벨.

**Diebold–Mariano** — `timeseries/backtest.py::diebold_mariano_hac`: Bartlett/NW 장기분산, max_lag = ceil(h/5) (h1→1, h21→5, h63→13), 정규근사 양측 p. Diebold & Mariano (1995) 'Comparing Predictive Accuracy', JBES. 소표본 보정(Harvey, Leybourne & Newbold (1997) 'Testing the Equality of Prediction Mean Squared Errors', IJF) **없음**. 봉인 원장 실측(`data/timeseries_v8/ledgers/sealed_evaluations.jsonl`): 전체창(1011원점) h21 −4.42 (p 9.8e-6), h63 −2.56 (p 0.0106); 봉인창(385원점) h21 −2.23 (p 0.026), h63 −1.50 (p 0.135), h1 p 0.288. **DM은 표시 지표이지 게이트 판정 다리가 아니다** — 게이트는 부트스트랩 CI90 상단.

## 3. V2/V8 게이트 구조와 예산 (`data/contracts/multivariate_timeseries_v8.yaml`)

- **창**: warmup 1996–2006 · development 2007–2018 · design 2007–2014 · holdout 2015–2018 · truncation 2019-04-30 · sealed 2019+ · rolling 2520세션. 원점 `weekly_last_completed_session`, purge 63 · embargo 5, minimum_origins 250, required_regimes [GFC 2008, pandemic 2020, tightening 2022].
- **publication_gate**(V2 수치 무변경 복사): 단기(h1/h5) CRPS 열위 ≤0.02, 장기 평균 개선 ≥0.02, 부트 CI 상단 ≤0, coverage p10–p90 [0.76,0.84] · p25–p75 [0.45,0.55], 국면 p10–p90 ≥0.70, pit_leakage 0, receipt_linkage 1.0. 실패 표면 `validation_pending_without_numbers`.
- **dev_gate_proxy** (R8-D1 개정, revision_history 보존): design 장기 개선 ≥0.025, paired se ≤0.001, 전체창 투영 CI90 상단 ≤−0.0004 (projection_reference 1011), 단기 열위 ≤0.01, GFC coverage ≥0.72; holdout 개선 ≥0.02 ∧ CI90 상단 ≤0.
- **예산**: `maximum_development_evaluations: 24`, `holdout_maximum_finalists: 3`, finalist당 1회, 명시 승인. 원장 실측: `development_experiments.jsonl` 12행(E0~E11, 전부 design), `holdout_scorings.jsonl` 1행(E10 — proxy 관측 장기개선 0.0734, CI90 상단 −0.00106, PASS; 계약 주석은 "+4.04%" — 정의 차이 여부 `[미검증]`), `sealed_evaluations.jsonl` 1행. V9 7/24, V10 12/24(stop-loss 12회·<+1%), V13 3/8.
- **봉인 1회** (`maximum_disclosures_per_model_version: 1`, `retune_after_failure: prohibited`, 서명 R8-D2): run `tsv8-sealed-64345a816b4857171915d5b8`, 2019-01-01~2026-08-14, 경로 20,000. 전체창 pass (CI90 [−0.00264, −0.00086]); **봉인창 385원점 hold** — 사유 'GFC 원점 0'(CI90 [−0.00379, −0.00026], h21 coverage 0.792/0.470, h63 0.782/0.504 — 밴드 내). R8-D4로 봉인창을 표본외 기준선으로 앞세워 공시.
- **operational_gate**: 입력 나이 48h(DTWEXBGS 216h), recent_origins 26, CRPS 열위 ≤0.05; `origin_age_policy` warn 1 / hold 10 거래일(동결 좌표 밖).
- **승격**: `automatic_champion: false`, `minimum_shadow_sessions: 126`, 전진 원장 `shadow_forecasts/resolutions.jsonl` 각 2행.

## 4. 워크포워드·PIT·DFM·VARX (`multivariate_timeseries_v2.yaml`)

- **정렬**: information_time = `available_at`, 관측기간 backfill 금지, release-state carry-forward는 available_at 이후만, 발표 후 경과일 피처 포함. 데이터 등급 native_pit / reconstructed_market_archive / captured_forward.
- **DFM**: 요인 [growth, inflation], order 1, idiosyncratic AR(1), EM tol 1e-5, cold/warm 300회, 우도 감소 불허, cache key [contract_hash, cutoff, input_hash], `parameter_pit: origin_specific_refit_required`. 엔진 statsmodels `DynamicFactorMQ` — **0.14.6 버전 불일치 시 fail-closed** (`timeseries_v2/contracts.py`).
- **Ridge-VARX**: 내생 5(nasdaq, vix, dgs2, curve, dollar), lag [1,2,5], α ∈ {1e-4…100} 7값, 학습창 robust median/IQR 표준화, clipping 금지. 앙상블 expanding + rolling 2520, 52원점 역CRPS 가중, 가중 [0.25,0.75]. 분포: 블록 [5,10,21] × EWMA λ [0.94,0.97] 원점별 선택(봉인 원장 실측: ℓ21 398·λ0.97 612/1011), 경로 2000(dev)/20000(sealed), `seed_rule: sha256_model_version_and_as_of`.
- **V8 분포층**: FHS h21/63(EWMA burn-in 60, current_ewma), convex blend w=0.75, B4 PIT 재보정 = 과거 PIT ecdf 역함수에 identity 수축 0.5 (`timeseries_v8/model.py::recalibration_levels`), minimum_matured 104, purge 63/embargo 5. E0 항등(중립 파라미터 = V2 비트 재현) 테스트 강제.
- **기준선 6종** (`_baseline_samples`): random_walk, drift_rw, ar1, gbm, historical_simulation, block_bootstrap(mean_block=min(10,h)).

## 5. 이벤트 확률 트랙 기계 (V12·V13)

- **양방향 전이**: early 2007-01-01~2010-12-31 ↔ late 2011~2014. 채택 = 두 방향 모두 CI90 하한 >0(엄격) ∧ y-블록 귀무 통과율 ≤0.10; family P(k≥k_obs) 병기(이항, 셀 종속 caveat).
- **T-A 교훈 수치** (`docs/review/V13_TA_NULL_REPAIR_VERDICT_20260907.md`, `tools/v13_ta_null_repair.py` ℓ=13·n=1000·seed_base 730000): V12 N1 i.i.d. p-순열 통과율 **0.254**(문턱 0.10, T5 실패) → 블록판 N-p-block **0.201**(여전히 누수), N-y-block **0.000**, N-blk-pair **0.000**. 해석(외부 검토 재현 (361+41)/2000=0.201): 수축 맵은 p→y 관계가 아니라 창 y평균으로의 수축(calibration-in-the-large)으로 통과한다. V13 y-블록 귀무 실측: EWMA 0.000~0.017, PB 0.000~0.033 (`neg_control` draws=120, 경량 부트 b=400).
- **V13 로짓 기계** (`tools/v13_vol_run.py::_logit_fit` = `timeseries_v13/features.py::logit_fit`): zscore(ddof0), Newton 200회, l2 1e-3, clip [1e-6, 1−1e-6]; n=2014 설계창 거래일. champion = persistence_pb 9/9(PB 기후 대비 BSS e2l/l2e: vix25_h5 +0.900/+0.794 … rv_h63 +0.095/+0.437; EWMA−PB 양방향 우세 0/9). 계수 동결 sha256 `1a857850…`, 반창 대사 max|Δ| 2e-15. h63 파생층 cross-fit isotonic(k=5 연속 블록, embargo h, PAV `features.py::pav`) — 사전등록 fallback 발동, raw 유지(예: vix30_h63 e2l rel 0.081→0.239 악화). 라이브 전진 게이트 `minimum_matured_origins_per_cell: 60`.
- **V12 구속 기준선**: 반사원리 2Φ(−ln(S/K)/(σ√T)) 및 BGK 이산 보정(Broadie, Glasserman & Kou (1997) 'A Continuity Correction for Discrete Barrier Options', Mathematical Finance). G2 요구값 예: h21 후보 Brier ≤0.051041(BSS ≥0.211214) — 완전 재보정 상한 미달로 도달 불가(armed=false).

## 6. 결정론 수치 모델·추론 전용 모델·시장내재 기록

| 자산 | 위치 | 규칙·상태 |
|---|---|---|
| LPPL 워크포워드 | `dualdb/dualdb/models/lppl_walkforward.py`, `quant/lppl.py` | DE(seed 고정)+선형 LS 2단 적합; 닷컴 1998-06~2000-02 월 이동. 경계히트 17/21 → **demoted**(8-7), 보정 tc 코드 게이트 비활성. Johansen, Ledoit & Sornette (2000) 'Crashes as Critical Points', IJTAF |
| DTW | `models/dtw_daily.py` | 주간 norm_m0, 비용 \|ln norm 차\|, open-end 접두 정렬(closed-end는 참고 병기) |
| k-NN | `models/knn_analog.py` | 5차원 상태벡터, 과거 시대 풀 z-표준화, k=5, 같은 시대 90일 간격, 지평 21/63/126/252; 미백색화 확정(KNOWN_LIMITS 25) |
| GBM MC | `quant/mc.py` (n 10000, seed 42), ml runner 일간 스텝 | 정규가정 고지; T5 브리지 보정 p=exp(−2d₀d₁/σ_w²) (9-1, 학습 0) |
| GARCH(1,1) | `shadow_models.py::fit_garch11` | 레지스트리 `shadow.garch11` "EWMA 대비 paired 검증 전"; `arch` 미설치 → V13 GARCH-t rung 미실행 |
| Hurst R/S·Pearson/Spearman·시즌성 | `quant/stats.py`, `quant/seasonality.py` | n=8~20 소표본 고지 |
| Chronos-Bolt / Chronos-2 / T5 / FinBERT | `ml/chronos_fc.py`, `ml/runner.py` | `combine_median` 고정 중앙값; `disagreement` >20%p(`ML_DISAGREEMENT_PP`)면 low_confidence 제외; LLM 괴리 15%p(`ML_DIVERGENCE_PP`)는 `due` 표시만. FinBERT 비방향(D-3) |
| 시장내재 | `market/kalshi.py`(mid) → `polymarket.py`(YES) → `options_bl.py`(CBOE 지연시세, IV 선형보간 N(d2), RISK_FREE 0.04, ^IXIC→QQQ 프록시, risk-neutral 고지) | 기록: `data/ml_history/2026.jsonl`, `calibration/benchmark_ledger.csv`(llm/ml/market prob·brier 병기). P3 봉인, 쌍대 n<10 표시만(KL 30) |

## 7. 코드 프리미티브와 라이브러리 가용성

- **pages 빌드** (`.github/workflows/pages.yml` L44): `numpy scipy Pillow`+pydantic류만 → 표시 계층(`timeseries_v8_display.py`, `timeseries_v13_vol_display.py`)은 numpy/scipy 전용 — V13 `features.py`가 "numpy 만"으로 도구 수식을 1:1 재현하는 이유.
- **extras** (`pyproject.toml`): `timeseries` = pandas>=2.2,<3 + **statsmodels==0.14.6**; `timeseries-v5` = scikit-learn(v7 LogisticRegression·E3 HGB); `ml` = torch/transformers/chronos. 봉인 runtime 영수증: python 3.12.10, numpy 2.5.2, pandas 2.3.3, scipy 1.17.1, statsmodels 0.14.6.
- **로컬 실측(2026-09-08)**: numpy 2.4.3, scipy 1.17.1, **pandas 3.0.1**(핀 `<3`과 불일치 — 봉인 재현 시 확인 필요 `[미검증]`), statsmodels 0.14.6, sklearn 1.8.0, torch 2.13.0+cpu, chronos 2.3.1, duckdb 1.5.5, **arch 미설치**.
- **자체 구현 프리미티브**(외부 라이브러리 없이): 정지 블록 부트스트랩(4개 사본), 경험 CRPS, PAV isotonic, Newton 로짓, DM-HAC, Wilson 90% 구간(`timeseries_v3/calibration.py`), **GroupConformalScale**(v3: 그룹별 |y−median|/half_width의 0.80분위, clip [0.5,2.5], min 30행), quantile elastic-net(Powell, v6/v7 E1), Student-t 로케이션-스케일(E2), 분위수 HGB(E3), 베이지안 DLM(E4), soft regime partial pooling(E5), GPD EVT 꼬리(E6), 비음 스태킹 SLSQP(v7 `stacking.py`). **단 V3~V7은 전부 `shadow_gate_hold`/HOLD**(V5 장기 −9.03%, V6 Research Gate FAIL) — 코드 자산이지 승인 모델이 아니며 V8 계보에 흡수되지 않았다.

## 8. 고급 프로그램을 위해 없는 것 (grep·문서 전수 기준)

| 결손 | 현황 | 왜 필요한가 |
|---|---|---|
| **Giacomini–White 조건부 예측능력 검정** | 없음 (DM만, 게이트 밖) | Giacomini & White (2006) 'Tests of Conditional Predictive Ability', Econometrica — rolling 재추정·국면 조건부(GFC vs calm) 비교에 정합. V10 "위기원점 인공물" 판정을 정식 검정으로 대체 가능 |
| **Model Confidence Set** | 없음 | Hansen, Lunde & Nason (2011) 'The Model Confidence Set', Econometrica — V10 단독 12개·V6 E1~E7·V13 사다리처럼 다후보 비교에서 '동등 집합'을 정의. 현재는 쌍대 vs 최선/E0만 |
| **Reality Check / SPA** | 없음 | White (2000) 'A Reality Check for Data Snooping', Econometrica; Hansen (2005) 'A Test for Superior Predictive Ability', JBES — 24회 dev 예산·격자 탐색·rung 다수의 스누핑 보정. 현 대체물은 독립가정 이항 family P(k≥k_obs)(`tools/v12_s4_2_gate_design.py` `familywise_any_pass_independent_approx`)와 V11 순열 P(≥4)=0.25~0.32뿐 |
| **FWER/FDR 보정** | 없음 (SUNDAY 보고 §8 "셀별 명목 수준 보정 없음") | Benjamini & Hochberg (1995) 'Controlling the False Discovery Rate', JRSS-B; Romano & Wolf (2005) 'Stepwise Multiple Testing as Formalized Data Snooping', Econometrica — 9셀×2방향(V13), 8셀×2(V12), 54검정(V11) |
| **Conformal prediction** | v3 GroupConformalScale 잔존(HOLD), V8 미사용 | Gibbs & Candès (2021) 'Adaptive Conformal Inference Under Distribution Shift', NeurIPS — coverage 게이트는 사후 검사이지 보증이 아님; B4 isotonic PIT 재보정이 유일한 보정 |
| **Quantile regression** | E1(Powell 자체 최적화)만, statsmodels QuantReg 미사용, V8 계보 부재 | Koenker & Bassett (1978) 'Regression Quantiles', Econometrica — 직접 지평 분위수 모형 |
| **Regime-switching** | 없음; 대체 = V10 상태조건부(W1~W3, 동결)·E5 soft regime | Hamilton (1989) 'A New Approach to the Economic Analysis of Nonstationary Time Series and the Business Cycle', Econometrica — 단 V10·V11 결과상 일간 정보집합에서 국면 이득은 위기원점 의존 |
| **Bayesian model averaging** | 없음; 결합은 고정 중앙값(8-8)·convex blend 0.75·52원점 역CRPS 가중 | Hoeting, Madigan, Raftery & Volinsky (1999) 'Bayesian Model Averaging: A Tutorial', Statistical Science — 학습 결합은 해소 200+ 게이트 뒤라 **구조적으로 보류** |
| reliability 신뢰대·PIT 정식 검정 | Murphy 분해·곡선만 | Bröcker & Smith (2007) 'Increasing the Reliability of Reliability Diagrams', Weather and Forecasting; Berkowitz (2001) 'Testing Density Forecasts, with Applications to Risk Management', JBES `[미검증: 코드 전수는 grep 기반]` |
| GARCH 계열 | `arch` 미설치, 자체 GARCH(1,1) shadow | HAR(Corsi (2009) 'A Simple Approximate Long-Memory Model of Realized Volatility', J. Financial Econometrics) 증분 0/9라 우선순위 낮음 |
| 시드·블록 민감도 표준 절차 | V10 L1(시드 20×블록 5)에서만 임시 | 부트스트랩 CI의 절차 민감도를 계약 좌표로 |
| 사전 검정력 계획 | n* 외삽만(h63 +943년) | 표본 정보량이 CI 폭을 결정하는 구조(417원점·ℓ13 유효표본≈32) |

**정직한 결론**: 이 저장소의 검증 기계는 "사전등록 → 쌍대 손실차 → 정지블록 CI90 → 양방향 전이 → 건전 y-블록 귀무 → 1회 봉인"이라는 단일 축으로 깊이 파여 있고, 그 축 안에서 파라미터는 계약 파일에 바이트 단위로 고정돼 있다. 결손은 전부 **다중 후보·다중 검정의 정식 보정**(MCS·SPA·FDR·GW)과 **분포 보정의 보증형 도구**(conformal)에 몰려 있다. 어느 것을 추가하더라도 §0의 게이트(ML 100+/200+, 홀드아웃 1회, 참고 의견 지위)는 바뀌지 않으며, 추가 자체가 새 사전등록 개정 커밋을 요구한다.


---

# [reader:refuted] 무엇이 반증되었고 무엇이 아직 안 시험되었나

# 무엇이 반증되었고 무엇이 아직 안 시험되었나

## 0. 이 절이 서 있는 거버넌스 (명시)

- **백테스트 금지의 예외 안에서만 읽을 것.** 아래 수치는 전부 결정론 수치모델의 design 창(2007-01~2014-12) 적합·워크포워드 결과다 (CLAUDE.md 원칙 5 예외 = dualdb 스펙 v1.0 §8, DECISIONS 8-6). 산출물은 base rate 참조이지 캘리브레이션 표본이 아니며, 문턱·창 선택(θ=0.1694, K∈{25,30}, τ=학습창 80분위, split 2010-12-31, GFC 창 2008-01~2009-06)은 정점 지식을 간접 내포할 수 있다. LLM 과거 질문 백테스트는 전 캠페인 0회.
- **되돌릴 수 없는 자원.** 홀드아웃(2015-2018)은 V8만 1회 소모(E10), V9·V10·V11·V12·V13 슬롯 소모 0. 봉인(2019+)은 V8 1회 공개(run `tsv8-sealed-64345a816b4857171915d5b8`), 나머지 트랙 미열람. V8/V2 봉인 해시 `e3ff2fdb…` 무변경, `forecasts/`·`calibration/` append-only 무수정.
- **채택 기준.** 사전등록 → 양방향 전이(early 2007-10 ↔ late 2011-14) + stationary block bootstrap(ℓ=13, B=2000; Politis & Romano (1994) 'The Stationary Bootstrap', JASA) CI90 하한>0 + 건전 음성대조(y-block 순열 — p-순열 귀무는 T-A에서 누수 확인). in-sample 통과 ≠ 채택.
- **ML 게이트.** Chronos·FinBERT는 추론 전용, 결합은 고정 중앙값·불일치 지수만(`src/ai_fc/ml/runner.py`). 보정 학습은 해소 100+, 가중 학습은 200+ 뒤. 모든 출력은 참고 의견 — P3 게이트(해소 50문항+·Brier<0.18) 전 자금 결정 근거 아님.
- **데이터.** PIT(ALFRED first-release·captured-forward)·합법 라이선스만. FirstRate·CBOE DataShop 구매/발송은 사용자 결정.

## 1. 반증된 방향 — 가설·검정·수치·추론

### 1.1 기준점: V8 봉인 — 무엇이 통과했고 무엇이 HOLD인가

| 창 | 원점 | CRPS 개선 vs 최선 기준선(historical_simulation) h1/h5/h21/h63 | DM p값 (Diebold & Mariano (1995) 'Comparing Predictive Accuracy', JBES) | p10–p90 coverage | 장기 손실차 CI90 | 판정 |
|---|---|---|---|---|---|---|
| 전체 2007-01-05~2026-05-14 (개발창 626원점 포함) | 1,011 | +3.50% / +3.48% / +3.96% / +4.21% | 3.1e-6 / 6.8e-5 / 9.8e-6 / 0.011 | .803/.790/.813/.808 | [−0.00264, −0.00086] | **gate PASS** |
| 봉인 2019-01-04~2026-05-14 | 385 | +1.17% / +1.69% / +3.47% / +4.87% | 0.288 / 0.128 / **0.026** / 0.135 | .818/.771/.792/.782 | [−0.00379, −0.00026] | **status hold** — 사유 "필수 위기 국면 누락: great_financial_crisis_2008" |

- 통과한 것: 분포 계층(FHS + blend .75 + PIT isotonic shrinkage .5)이 design +2.86% → holdout(2015-18, 1회) +4.04%(CI90 상단 −0.00106) → 전체창 +4.08%로 전이했고, 장기 손실차 CI90 상단이 두 창 모두 0 미만. B1(대칭 vol 평균회귀)·E11(기간구조 vol)·B2 tilt는 design에서 기각(계약 `B5.status: activated_after_E5_stop_loss`).
- HOLD인 것: 봉인창 자체 판정은 위기 국면 요건 미충족으로 보류(R8-D4가 화면에 사유와 함께 공시). 봉인창 안에서 유의한 지평은 h21 하나(p=0.026). **국면 비대칭**이 남아 있다 — pandemic_2020 coverage 0.917(과잉폭), tightening_2022 0.750(과소폭). first_touch Brier는 봉인창 h21 0.082 / h63 0.194로 전체창(0.068/0.166)보다 나쁘다. 방향 적중률은 원장에 있으나 R8-D4로 비공개(매매 신호 오독 위험) — 이 문서도 인용하지 않는다.
- 추론: V8이 이긴 상대는 무조건부 historical simulation이며, 이득의 본질은 **폭(width)의 조건부화**다. 2020/2022 비대칭이 V10의 표적이 됐다.

### 1.2 V9 — 외생 거시·유동성 열 (가설: 신용·MMF·VXN 정보가 V8 분포를 날카롭게 한다)

검정: E0(V8 비트 항등) 대비 쌍대 CRPS 차이(E−E0, **양수=악화**), 834 원점쌍(417×h21/63), ALFRED first-release PIT, |ρ|>0.85 기각 규칙.

| 실험 | 피처 | 장기 쌍대 | CI90 | 판정 |
|---|---|---|---|---|
| E1 | M2SL | +0.000014 | [−0.000000, +0.000028] | 무효익 |
| E2 | TOTCI | +0.000043 | [+0.000019, +0.000074] | **유의 악화** |
| E3 | TOTLL | +0.000004 | [−0.000002, +0.000009] | 무효익 |
| E4 | WRMFNS | +0.000003 | [−0.000016, +0.000022] | 무효익 |
| E6−E5 | Δlog(VXN/VIX), 서브창 2010-14(260원점) | +0.000006 (+0.019%) | [−0.000008, +0.000021]; 단기 h1+h5 **+1.65%** [+0.000058, +0.000246] 악화 | 채널 폐기 |

추론: 쌍대 se 4.0e-06~2.1e-05로 +2%급 효과(≈0.0006)를 볼 검정력이 있었는데 개선 0/5 — **검출 실패가 아니라 측정된 영(null)**. VXN 스프레드는 |ρ|=0.011로 직교인데도 무익 = 순수 노이즈 주입. 주간·월간 first-print 수준 변화는 일간 지수 분포에 추가 정보가 없다. 예산 7/24, 동결.

### 1.3 V10 — 국면·γ 가중 분포 계층 (가설: vol 상태 조건부 재표집·혼합·블렌드가 2020/2022 비대칭을 고친다)

검정: V8 포크(E0 비트 항등), 상태 = EWMA97 분산비 v_now/v̄(2520), 단독 12개 사전등록, 쌍대(E0−exp, **양수=개선**), stop-loss "12회 후 최고 <+1%".

| 축 | 결과 |
|---|---|
| W1 κ∈{0.5,1.0} | −0.10%/−0.22% 유의 악화, h63 coverage 0.8417 > 밴드 0.84 FAIL |
| W2 3성분 혼합 | coverage 0.85–0.88 과분산 FAIL |
| **W3 γ=−0.10** | **+0.000277 CI90 [+0.000016, +0.000679] = +0.64%** (유일 챔피언, <1% stop-loss) |
| W4a isotonic | +0.000014 [+0.000006, +0.000023] = +0.03% (유의하나 무의미 크기) |
| W5 h5 FHS | −0.000019 [−0.000267, +0.000212] |

6렌즈 적대검증: GFC 78원점(18.7%)이 총델타의 83.8% 견인; GFC 제거 시 +0.64%→+0.13%; 상위 5% 원점(21개) 제거 시 평균 −0.0000115(정확히는 "0과 구분 불가" — 절사 CI90이 0 포함); 2008-10~12 클립(w 하한 0.5) 포화 7주가 엣지의 58%. 홀드아웃 게이트(+2% AND CI 상단≤0) 통과 확률 <2% 추정 → 슬롯 3/3 보존·동결. 정정 기록: 조합 격자는 미표집이었고(가법 대리 최상 +1.147% CI90 [+1.07e-04, +9.99e-04]), 그러나 적격 12조합 전부 상위 5% 제거 후 CI90이 0을 포함(V12-D5 종결).

추론: vol 수준 상태는 위기에서만 baseline과 달라진다. **이득은 실재하나 위기원점 인공물** — 홀드아웃(2015-18)에는 발화 조건이 없다.

### 1.4 V11 — 평시 직교 상태 신호 (가설: 비위기 하위 80% 원점에서 V8 결함(PIT·CRPS)을 예측하는, vol에 직교인 프록시가 있다)

검정: 백테스트 0회. 9 프록시 × 3 결함지표 × 2 지평 = 54검정, 4중 기준(CI90 0 배제·효과 바닥·|Spearman|<0.30·반기 부호 동일), P9 음성 대조군.

- 통과 4/54 (P9 미통과): P1 21일 모멘텀→PIT 위치 h21 Δ=−0.120 [−0.192, −0.035](ρ=−0.19); P7 growth factor→CRPS h21 −0.017 [−0.026, −0.008], h63 −0.056 [−0.104, −0.019].
- **표본외 전이**: P1 순방향(2007-10 적합→2011-14) CRPS **+0.97% 악화**(부트스트랩 96% 악화 쪽), 역방향 **+1.49% 악화**. 독립 재계산(3 split × 선형/저모멘텀 tertile × 양방향 = 24셀): 채택 0/12, 순열 p=0.118; 저모멘텀 변형 h63 순방향 +8.1~18.2% 악화.
- 다중검정: 관측 4통과 = 귀무분포 68~75퍼센타일, P(≥4)=0.25~0.32.

추론: in-sample 실재·vol 직교·GFC 강건인 신호도 **2013-14 저변동 tail에만 살고 옮겨가지 않았다**. V10과 다른 실패 모드로 같은 벽. 핵심 교훈: in-sample 통과·직교·강건 ≠ exploitable.

### 1.5 V12 — first_touch 재보정 T1–T5, T-A, H3/T-B (가설: V8의 −10% 접촉 확률 상단 과신을 1-파라미터 맵으로 재보정하면 창을 넘어 전이한다)

표적: 지평 내 일간 종가 경로 최소값 ≤ 0.90·S₀ (first-passage), 417 원점, h21 터치 29 / h63 83.

**S2 계측** (기준선 = 반사원리 p=2Φ(ln0.9/(σ√T)), σ=EWMA λ=.97, 자유 파라미터 0):

| h | BS V8 / 반사 / 기후 | BSS(V8\|기후) 쌍대 CI90 | V8−반사 쌍대 CI90 | 상위분위 gap V8 / 반사 | AUC V8 | ρ_s(V8,반사) |
|---|---|---|---|---|---|---|
| 21 | 0.061485 / 0.060135 / 0.064708 | +4.98%, [−0.011884, +0.020559] | −0.001350 [−0.006668, +0.002511] | +0.1230 [−0.0097, +0.2394] / +0.1232 [+0.0078, +0.2233] | 0.8054 [0.6315, 0.9039] | 0.9514 |
| 63 | 0.144973 / 0.149889 / 0.159424 | +9.06%, [−0.022054, +0.057643] | +0.004917 [−0.001855, +0.010982] | +0.2107 [+0.0355, +0.3817] / +0.2417 [+0.0654, +0.4069] | 0.7325 [0.5713, 0.8513] | 0.9126 |

- 2000경로 DFM-VARX 앙상블의 접촉 확률은 EWMA σ 하나의 단조 변환과 통계적으로 구분되지 않는다. 판별력(AUC)만 CI90으로 지지되고, 그 77~83%는 σ가 만든다.
- BGK 이산 모니터링 보정(β=0.5826; Broadie, Glasserman & Kou (1997) 'A Continuity Correction for Discrete Barrier Options', Mathematical Finance)은 **기준선** 과신을 h21 45%·h63 20% 줄이지만 V8은 이미 일간 종가로 판정하므로 V8 과신의 설명이 아니다.

**S3 사전등록 검정** (커밋 `ec496463` 결과 전): T1 상단 수축 p′=p−λ(p−b)·1{p>τ} / T2 양방향 최소 λ / T3 반사 앵커 혼합 w / T4 지평 단조 제약 / T5 음성 대조. 채택 = 양방향 CI90 하한>0.

- **채택 0/8, 16방향 중 하한>0 0개** (하한<0 10, 하한=0 6). T3 전→후는 CI90 상한<0(h21 −0.000010, h63 −0.000123) — 악화. T4는 단조 위반 0건 — 무비용·무효과. |Δ|<MDE 9/16.
- **T5 실패**: p-순열 귀무 아래 T1 통과율 pooled **0.254 > 0.10**, 귀무 평균 통과 셀 2.764. → 이 기계의 '통과'는 증거가 못 된다.
- **T-A 수리 시도** (NOT_REPAIRED): N-p-block **0.201**, N-y-block 0.000, N-blk-pair 0.000. 해석(외부 검토 재현 (361+41)/2000=0.201): T1의 이득은 p→y 관계가 아니라 **창의 y 평균으로의 수축(calibration-in-the-large)** — 재보정 트랙 B1 확정 종결. p-순열 귀무는 계약으로 금지(`p_permutation_null_as_negative_control: true`).
- **H3/T-B** (과신의 주인 = 상수-σ i.i.d. FHS 경로 생성기): 일간 ACF(1)=−0.076, z AR(1) φ̂=−0.053, VR(5)=0.874, VR(21)=0.919, VR(63)=1.044 — 방향 확증, 크기 온건(포스트모템 0.72 아님). 기대 이득 h21 BSS +1~3%p 추정 → **보류(파킹)**, 재개 조건 4항(일중 데이터·새 사전등록·y-block 귀무·CRPS 무손상).

추론: 종점 분포(CRPS)가 맞아도 경로 의존 사건 확률은 틀릴 수 있고, 그 오차는 1-파라미터 맵으로 옮겨지지 않는다. 표적 고유성 주장은 [미검증]으로 강등.

### 1.6 V13-VOL — HAR/EWMA vs 지속성 (가설: 변동성 이벤트 P(VIX≥K within h), P(RV21>θ)는 예측 가능하며 richer 모형이 증분을 준다)

| rung | 대조 | 결과 (9셀 = {vix25, vix30, rv} × {h5, h21, h63}) |
|---|---|---|
| 1 EWMA-logit | 기후 | 9/9 양방향 CI90>0, BSS e2l +0.094~+0.898, 건전 y-block 귀무 0.000~0.017 — 캠페인 첫 긍정 |
| 2 HAR-logistic (Corsi (2009) 'A Simple Approximate Long-Memory Model of Realized Volatility', J. Financial Econometrics) | EWMA | 기후 대비 9/9, **EWMA 대비 증분 0/9** (예: vix25_h63 l2e −0.00388 [−0.00697, −0.00090]; rv_h5 l2e −0.00246 [−0.00516, −0.00013]). GARCH-t moot(미실행) |
| 3 PB = logit(당일 수준 1피처) | EWMA | EWMA가 PB를 양방향으로 이긴 셀 **0/9**, \|EWMA−PB\|≤0.008, 한 방향 유의 열위 2셀(vix25_h63 l2e −0.00781 [−0.01191, −0.00356]; vix30_h63 e2l −0.00371 [−0.00604, −0.00133]). PB 기후 대비 9/9, 귀무 ≤0.033 → **champion = persistence_pb 전 9셀** |

- h63 cross-fit isotonic은 사전등록 fallback 발동(iso 유의 열위, 예: vix30_h63 e2l rel 0.081→0.239) → raw 유지. reliability h5 rel≈0.002(양호)·h63 rel≈0.08(오보정).
- 기후 기저율(설계창, GFC 포함): K25 h5/h21/h63 = 0.308/0.420/0.608, K30 = 0.178/0.252/0.407, RV>θ = 0.552/0.676/0.875.
- 홀드아웃 미소모(V13-D3 대기), T3 라이브 카드는 "홀드아웃 미검증" 굵게 상시.

추론: **스킬 = "당일 변동성 수준의 지속"**. 문헌과 정합 — 변동성은 강하게 예측 가능하고(Poon & Granger (2003) 'Forecasting Volatility in Financial Markets: A Review', JEL; Andersen, Bollerslev, Diebold & Labys (2003) 'Modeling and Forecasting Realized Volatility', Econometrica), 단순 모형을 이기기 어렵다(Hansen & Lunde (2005) 'A forecast comparison of volatility models: does anything beat a GARCH(1,1)?', J. Applied Econometrics). 가치는 EXIT 트리거 base rate 공급이지 시장 엣지가 아니다.

### 1.7 관통 추론 — '일간 종가 정보집합 위의 효율적 시장 벽'의 정확한 범위

성립하는 진술: **NASDAQ Composite 일간 종가 정보집합**(수익률·VIX 종가·DGS2·커브·달러 + DFM 성장/물가 팩터 + 주간/월간 first-print) 위에서, **표적 = h21/h63 CRPS 분포와 −10% first-passage 확률**, **창 = 2007-2014, 판정 = 양방향 전이**일 때, (a) 외생 열 추가, (b) vol 상태 조건부 분포 계층, (c) 평시 직교 상태, (d) 이벤트 확률 재보정 네 각도가 모두 표본외 개선을 내지 못했다. 세 트랙 origin별 Δ 상관 |r|≤0.154 — 같은 잡음의 재측정이 아니라 서로 다른 실패다. 남은 실재 스킬은 변동성 지속성뿐이며, 이는 수익률 방향 예측성이 변동성 동학에서 파생된다는 Christoffersen & Diebold (2006) 'Financial asset returns, direction-of-change forecasting, and volatility dynamics', Management Science와 정합한다. 문헌 사전확률도 같은 쪽 — Welch & Goyal (2008) 'A Comprehensive Look at the Empirical Performance of Equity Premium Prediction', RFS; Campbell & Thompson (2008) 'Predicting Excess Stock Returns Out of Sample', RFS.

성립하지 않는 진술: "일간 NASDAQ에 정보가 없다"(V8은 historical simulation을 이긴다), "재보정이 원리상 불가능하다"(등록된 네 맵과 이 검정 절차만 부정됨), "2015+에 대한 주장"(미열람), "축 곱공간까지 소진"(V10 조합 격자는 미표집·기대 낮음). 벽은 **정보집합 × 표적 × 창 × 계보**의 벽이다.

## 2. 아직 시험되지 않은 것 — 정보집합·표적·손실함수

| # | 항목 | 저장소 현 상태 | 문헌 사전확률 | 정직한 기대·제약 |
|---|---|---|---|---|
| 1 | **옵션 내재 정보** — IV surface(스큐·기간구조), VVIX, SKEW, VRP=IV²−RV | V8 번들의 VIX 종가 1개가 유일한 옵션 파생 입력. `options_bl.py`는 CBOE 지연시세 N(d2) 기록 전용(risk-neutral). 2007-2014 IV 표면은 미보유 — Cboe DataShop(2004+, §2b 조건부 표시) QQQ 질의 초안·OptionMetrics(학술 전용) 조사 완료 | **강함(변동성 표적)**: Christensen & Prabhala (1998) 'The relation between implied and realized volatility', JFE; Jiang & Tian (2005) 'The Model-Free Implied Volatility and Its Information Content', RFS — IV가 역사 vol을 포섭. **약~중(수익률 표적)**: Bollerslev, Tauchen & Zhou (2009) 'Expected Stock Returns and Variance Risk Premia', RFS — VRP는 분기 지평에서 R² 수 % 수준; Bekaert & Hoerova (2014) 'The VIX, the variance premium and stock market volatility', J. Econometrics; Bollerslev & Todorov (2011) 'Tails, Fears, and Risk Premia', JF(꼬리 프리미엄) | V13 표적(VIX≥K·RV>θ)에는 IV 표면이 PB를 이길 가장 유력한 후보 — 단 VIX 자체가 이미 IV라 증분은 스큐·기간구조에서만 나온다. 가격 꼬리(−10% 접촉)에는 VRP·스큐가 "유일한 미검증 정보집합". 진짜 일중 옵션 IV 표면 2007-2014는 무벤더 공백(EOD만 가능) |
| 2 | **일중 실현 측도** — RV/BPV/jump, overnight vs intraday | 일간 종가 RV21만 사용. FirstRate 1분봉(2000+, ~$300, 조정본·vintage 아님) 계획 문서만. 합법 소스 실재 확인(LEGAL_SOURCE_EXISTS) | **강함(변동성)**: Andersen, Bollerslev & Diebold (2007) 'Roughing It Up', REStat; Barndorff-Nielsen & Shephard (2004) 'Power and Bipower Variation…', J. Financial Econometrics; Liu, Patton & Sheppard (2015) 'Does anything beat 5-minute RV?', J. Econometrics. **중(수익률 분해)**: Lou, Polk & Skouras (2019) 'A tug of war: Overnight versus intraday expected returns', JFE | V13에서 HAR(3스케일)조차 증분 0이므로 일중 RV가 이벤트 확률을 더 올릴 여지는 작다. 실질 가치는 파킹된 T-B(되돌림 구조·jump 조건부 경로 생성)에 있다. PIT는 캡처 영수증으로만 보강 |
| 3 | **미시구조·주문흐름** — 스프레드·깊이·VPIN·틱 불균형 | 전무. TAQ(2003+)·AlgoSeek(2007+)은 고가·자격 게이트 | 중(단기 vol/유동성 사건): Easley, López de Prado & O'Hara (2012) 'Flow Toxicity and Liquidity in a High-Frequency World', RFS — 단 VPIN의 사전 예측력 논쟁 [미검증: 후속 반박 문헌 세부] | 일간 이벤트 확률 표적에는 지평 불일치. 비용·PIT 순정성 대비 기대 낮음 |
| 4 | **횡단면·시장폭** — 상승/하락 종목 비율, 52주 신고/신저, 분산도 | 지수 단일 계열만. dualdb는 생존자 표본(KNOWN_LIMITS 14) — PIT 구성종목 리스트 부재 | 약~중 [미검증: 시장폭 단독의 학술 증거 빈약]; 횡단면 vol은 Ang, Hodrick, Xing & Zhang (2006) 'The Cross-Section of Volatility and Expected Returns', JF | 생존자 편향 없는 PIT 구성종목(CRSP류) 없이는 설계창 검정 자체가 오염. 현실적으로 2015+ captured-forward만 가능 → 표본 부족 |
| 5 | **포지셔닝** — CFTC COT(NDX 선물), FINRA 공매도잔고, 마진부채 | COT는 BTC 계약만(`cftc_cot_bitcoin_d0.yaml`); FINRA 마진·Fed Z1은 통계 레이어에만, V-트랙 피처로 미등록 | **중(월간 지수)**: Rapach, Ringgenberg & Zhou (2016) 'Short interest and aggregate stock returns', JFE — 총공매도잔고가 가장 강한 월간 예측변수 중 하나. COT 지수 예측력은 혼재 [미검증] | 주간·반월 케이던스 → V9와 같은 빈도 불일치 함정. 표적을 월간·분기 이벤트로 바꿔야 의미. first-release vintage 확보 필요(FINRA는 공개 이력, PIT 가능) |
| 6 | **거시 서프라이즈·나우캐스트** | DFM 성장/물가 팩터(ALFRED PIT)는 이미 번들 안 — 나우캐스트 자체는 시험됨. **컨센서스 대비 서프라이즈**·발표일 더미는 미시험(`market_consensus.yaml` 범위 [미검증]) | 강(발표일 효과): Andersen, Bollerslev, Diebold & Vega (2003) 'Micro Effects of Macro Announcements', AER; Savor & Wilson (2013) 'How Much Do Investors Care About Macroeconomic Risk?', JFQA; Lucca & Moench (2015) 'The Pre-FOMC Announcement Drift', JF. 나우캐스트: Giannone, Reichlin & Small (2008) 'Nowcasting', JME | 서프라이즈는 컨센서스 아카이브(상업)가 필요. 무료 대안은 발표 캘린더 더미(`calendar_sources.yaml`) — 조건부 분포 폭(발표일 vol) 표적이면 시험 가능 |
| 7 | **텍스트·LLM 감성** (FinBERT 추론 전용) | GDELT 헤드라인 FinBERT 지수는 **비방향** base rate(D-3). V-트랙 피처 미등록 | 약~중: Tetlock (2007) 'Giving Content to Investor Sentiment', JF(단기 압력 후 되돌림); Loughran & McDonald (2011) 'When Is a Liability Not a Liability?', JF; LLM 직접 예측은 Lopez-Lira & Tang (2023) 'Can ChatGPT Forecast Stock Price Movements?' [미검증: 워킹페이퍼·재현성] | 헌법 원칙 5: LLM 과거 평가 금지. FinBERT는 사전학습 분류기라 결과 오염은 낮으나 **예외 적용 여부는 사용자 결정 필요** [미검증]. GDELT 2015+라 설계창 부재 → 라이브 포워드만 |
| 8 | **국면 조건부 분포 형태(위치 아님)** — 비대칭·첨도·점프 | V10 W1/W2/W3은 vol 수준 상태 조건부 **폭**만 다뤘고 CRPS(중심 지배)로 채점. 왜도·꼬리 형태를 별도 조건화·채점한 적 없음 | 중: Hamilton (1989) 'A New Approach to the Economic Analysis of Nonstationary Time Series…', Econometrica; Ang & Bekaert (2002) 'International Asset Allocation with Regime Shifts', RFS; Amaya, Christoffersen, Jacobs & Vasquez (2015) 'Does realized skewness predict…', JFE | 2020(과잉폭)·2022(과소폭) 비대칭은 설계창에 대리가 없어 봉인에서만 드러난다(V10 설계 §A′). 형태 표적은 꼬리 가중 채점(#12)과 함께 등록해야 의미 |
| 9 | **긴 지평 63d+·분기** | V8·V13 모두 h63 상한. h63에서 스킬 감쇠(rv_h63 BSS +0.095)·오보정(rel≈0.08) | 약: Boudoukh, Richardson & Whitelaw (2008) 'The Myth of Long-Horizon Predictability', RFS — 중첩 표본의 과대. VRP만 분기 지평에서 유효(BTZ 2009) | 설계창 8년 = 비중첩 분기 32개, ℓ=13 유효표본 ≈32 → 검정력 부재. 옵션 정보(#1) 없이는 시험 가치 낮음 |
| 10 | **다른 표적** — 드로다운 깊이/회복시간, 꼬리 분위수(p5·p1), vol-of-vol, 상관 국면 | 시험됨: −10% first-passage(h21/63, 부정), VIX≥K·RV>θ(긍정·지속성). 미시험: 최대 드로다운 분포, ES, VVIX, 자산 간 상관 전환 | 드로다운: Magdon-Ismail, Atiya, Pratap & Abu-Mostafa (2004) 'On the Maximum Drawdown of a Brownian Motion', J. Applied Probability(분석 base rate). 상관 국면: Longin & Solnik (2001) 'Extreme Correlation of International Equity Markets', JF; Ang & Chen (2002) 'Asymmetric Correlations of Equity Portfolios', JFE. vol-of-vol: Huang, Schlag, Shaliastovich & Thimme (2019) 'Volatility-of-Volatility Risk', JFQA [미검증: 세부] | 상관 국면은 V8 5변량 VARX 안에 원재료(NASDAQ·VIX·금리·달러)가 이미 있어 **0 신규 데이터로 사전등록 가능** — EXIT 트리거(교차자산 동조 급락)와 직결. vol-of-vol은 VVIX(2006+) 데이터 미보유 |
| 11 | **다른 손실함수** — 꼬리 가중 CRPS, 임계 가중, ES 백테스트, 경제 손실(하드룰 발동 비용) | CRPS·coverage·Brier·log만. DM 검정 사용 | Gneiting & Ranjan (2011) 'Comparing density forecasts using threshold- and quantile-weighted scoring rules', JBES; Gneiting & Raftery (2007) 'Strictly Proper Scoring Rules…', JASA; Fissler & Ziegel (2016) 'Higher order elicitability and Osband's principle', Annals of Statistics; Christoffersen (1998) 'Evaluating Interval Forecasts', IER | CRPS는 중심에 가중 — V10 W3의 "폭 이득"이 꼬리에서는 어떤지 미채점. 같은 원장 재분석으로 0 백테스트 가능하나 **채점 규칙 변경 = 새 사전등록**이며 결과 본 뒤 손실함수 교체는 금지(V12 C-gate-arith 정신) |
| 12 | **모형 계층 결합** — vol 예측 → 경로 생성기(확률변동성 FHS), TSFM(Chronos) 조건부 | B1·E11(vol 기간구조)은 V8 design 기각. Chronos는 ml 레이어 참조 전용, 사전학습 코퍼스 2019+ 포함 → 봉인창 오염 위험(포스트모템 D1) | GARCH류 경로 vs FHS: Bollerslev, Patton & Quaedvlieg (2016) 'Exploiting the errors', J. Econometrics(측정오차 반영 HARQ) | T-B 파킹 조건과 동일. Chronos 파인튜닝은 ML 게이트·오염 양쪽에서 차단 |

## 3. 정직한 요약

반증된 것은 정확히 이것이다 — 일간 종가 정보집합에서 V8 위에 얹은 네 종류의 개입(외생 열·vol 국면 가중·평시 직교 상태·재보정 맵)은 2007-2014 양방향 전이를 넘지 못했고, 유일한 표본외 후보(V10 W3 +0.64%)는 GFC 원점 인공물이며, 변동성 이벤트에서 살아남은 스킬은 당일 수준의 지속성으로 환원된다. 시험되지 않은 것 중 문헌 사전확률이 높은 순서는 (1) 옵션 표면·VRP → 변동성 이벤트 및 가격 꼬리, (2) 자산 간 상관 국면(신규 데이터 0), (3) 꼬리 가중 손실함수로의 재채점(신규 데이터 0), (4) 총공매도잔고·마진 같은 월간 포지셔닝(표적을 월간으로 재정의해야 함)이다. 일중 RV·미시구조·시장폭·텍스트는 데이터·PIT·헌법 제약 대비 기대가 낮다. 어느 경로든 사전등록 → design 창 → (사용자 승인 시) 홀드아웃 1회의 순서와 "in-sample 통과 ≠ 채택"은 그대로이며, 결과는 참고 의견 지위를 벗어나지 않는다.

**원천 파일**: `C:\workspace\ai-investing\CLAUDE.md`, `docs\DECISIONS.md`(R8-D3/D4, V13-D2′, V12b-park), `data\timeseries_v8\ledgers\sealed_evaluations.jsonl`, `data\contracts\multivariate_timeseries_v8.yaml`·`v10.yaml`·`v12.draft.yaml`·`v13_vol.yaml`, `outputs\review-packs\NASDAQ_CAMPAIGN_SESSION_REVIEW_20260908\01_freeze_v9_v10_v11\{E2_E4_ABLATION_REPORT,E5_E6_VXN_SPREAD_VERDICT,SINGLES_COMPLETE_STOPLOSS,V10_FREEZE_DECISION,V11_FREEZE_DECISION,V9_V10_V11_INDEPENDENT_VERDICT}`, `docs\review\{SUNDAY_LOOP_FINAL_REPORT,V12_S2_1_FIRST_TOUCH_MEASUREMENT,V12_S2_2_REFLECTION_BASELINE,V12_POSTMORTEM_NEXT_DESIGN_260907,V13_TA_NULL_REPAIR_VERDICT_20260907,V13_VOL_RUNG1/2/3_*,V12B_PARKED_20260908,V12_INTRADAY_LEGAL_SOURCE_SURVEY_20260907}.md`, `docs\design\{v11_orthogonal_calm_diagnostic_260903,v12_s3_verdict,v13_next_design_prereg_260907}.md`, `data\timeseries_v13\{vol\champion_coefficients.json,prereg\p1_h3_prediagnosis.json}`, `C:\Users\91ssj\Downloads\CAMPAIGN_REVIEW_NEXT_DESIGN_260908.md`.
