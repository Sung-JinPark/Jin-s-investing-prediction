# 다변량 시계열 예측 프로그램 — 현 위치·남은 단계·고도화 전략 설계 검토 (2026-09-08/09)

> **이 문서의 지위.** 다중 렌즈 합성본이다: 저장소 원문을 읽은 리더 4명 → 서로 다른 렌즈의 설계자 3명(고전 계량 /
> 현대 ML·DL / 정보집합 확장·이벤트 확률) → 방향마다 회의론자 2명 → 심판(채점·단계 지도) → 작성 → 완전성 비평 → 수정.
> 저장소 수치는 부록 A~F 원문에서 재계산 가능해야 하고, 인용은 `conf` 열과 `[미검증]` 표시를 우선 확인하라.
> 원자료: 01a(비평) · 01b(심판 순위) · 01c(방향 원안 24) · 01d(리더 요약).

## 1. 요약

### 1-1. 지금 어디에 있나

심판의 단계 계수 요약(`stage_count_summary`)을 그대로 인용한다.

> "현재 프로그램은 **총 9단계(S0~S8) 중 3단계**(S0 V1~V8 계보·봉인 1회 소모 → V8 GATE PASS, S1 V9~V12 단독 축 4종 소진 → 전부 부정, S2 V13-VOL 이벤트 표적 전환 → champion=persistence_pb·T3 라이브)**를 마쳤고, 남은 단계는 6개**(S3 0원 정보집합·표적축 스크린 / S4 홀드아웃 1회 소모 / S5 EXIT base rate 배선·라이브 전진 게이트 무장 / S6 유료 정보집합(옵션 표면·일중) / S7 라이브 전진 트랙레코드 축적 / S8 신규 버전 봉인 1회 + P3 게이트)다. 지금 위치는 정확히 **S2 완료·S3 진입 직전**이며, S3에서 즉시 착수 가능한 것은 비용 $0·비가역 자원 0의 다섯 슬롯이다."

같은 요약이 못 박은 네 가지 정직한 caveat는 §3-4에 전문을 옮겼다. 요지만 옮기면 ① 각 단계는 부정 결과로 끝날 수 있고 그것이 정상 종료이되 **셀별 MDE를 결과 전에 공표했을 때만** 그 null이 축을 닫는다, ② 남은 6단계가 성공을 전제하지 않는다, ③ 단계 수는 시간과 비례하지 않는다(S3~S6은 3~4개월이지만 S7·S8은 연 단위), ④ 완결해도 T4는 열리지 않는다(`v13_vol.yaml` `display_tiers_allowed`에 t4 값 자체가 없다).

### 1-2. 핵심 권고 5개

| # | 권고 | 근거 수치 |
|---|---|---|
| **R1** | **S3-a(옵션 지수 형상 → V13 9셀)를 단일 사전등록으로 병합해 최우선 착수한다.** `infoset-1`(78)·`ml-1`(72)·`classical-1`(71) 세 카드는 실질 동일 코어이므로 별도 예산 배정은 family만 키운다. | 살아남은 방향 중 유일하게 '신규 정보집합 × 검정력 있는 표적 × $0' 동시 성립. `ladder_pb_baseline.json` 실측 `ewma_vs_pb` MDE는 vix25_h21에서 0.001715/0.003289(Brier 0.0874/0.1335 = **1.96%/2.46% BSS**)라 기대치 +1~4%p가 검출 대역 안. 정보집합 신규성도 실측 확인 — V13 계약 `data_policy.series=[VIX, NASDAQCOM]`이라 형상 변수는 3 rung 어디에도 없었다. |
| **R2** | **퇴화 가드를 전 슬롯 공통으로, 결과 보기 전에 선언한다.** 양 반창 각각 min(사건, 비사건)이 문턱 미달인 셀은 `untestable_by_construction`으로 family에서 제외. | VIX3M 서브창 late leg(2012-04~2014-12, **692세션**)은 VIX≥30이 **정확히 0일**·≥25가 5일(2에피소드)이라 vix30 3셀은 양방향 판정이 구성상 불가능하고 y-block 귀무가 전부-0 벡터에서 퇴화한다(거짓 PASS 경로). 같은 구조가 `classical-8`(2012-10~2014-12 114원점 **사건 0건**)에서도 확인됐다. |
| **R3** | **V13-D3 홀드아웃 1슬롯을 지금 PB finalist에 쓰지 않는다(§10 D-1 권고 (b)).** S3-a 결과 후 더 나은 finalist와 함께 판단. | PB를 먼저 소모하면 2015–18의 동일 라벨 셀별 Brier가 공개돼 후속 finalist의 홀드아웃이 `v8.yaml` `disclosure_caveat` 의미의 **준청정**이 된다. S3-a 소요가 3~5일이라 대기 비용이 작다. 현 잔량은 V13 holdout **0/3**(finalist `V13VOL_champion_aec80c65038b` 1개 사전등록). |
| **R4** | **CBOE DataShop 질의(V12-D4)는 지금 발송하되 구매는 S3-a 결과에 조건화한다(§10 D-3).** | 질의 발송은 리드타임 독립·비가역 아님(회신 ~5영업일). 반면 구매의 1차 표적이던 −10% first-passage는 필요 마진이 기후 대비 BSS **h21 ≥+14.28%(BGK판 +21.12%)·h63 ≥+10.18%(+15.08%)**인데 방향 자신의 기대는 h63 +2~6%p·h21 +0~3%p — **요구 마진의 1/3~1/7**이라 정보 유무와 무관하게 '결정적 증거 없음'이 나온다. 사려는 형상 요약(SKEW 9,210행·VVIX 5,087행)의 상당부분이 이미 $0로 있다. |
| **R5** | **다중검정 절차를 결과 전에 택일해 명문화한다.** family = 퇴화 가드 통과 셀 × 피처, BH q=0.10 기본(상관 강한 셀 구조면 Romano–Wolf), 사다리는 MCS(α=0.10) 병기. 트랙 간 누적은 §9-3의 (i)/(ii) 중 택1. | 설계창 2007–2014는 V8(dev 12)·V9(7)·V10(12)·V11(48검정)·V12(8셀×2방향)·V13(9셀×3rung)로 이미 누적 채굴됐고, 저장소에 SPA/MCS/트랙 간 FWER 보정은 **존재하지 않는다**(현 대체물은 독립가정 이항 family P(k≥k_obs)와 V11 순열 P(≥4)=0.25~0.32뿐). |

### 1-3. 이 팩을 읽는 검토관이 가장 먼저 반박해야 할 주장 3가지

이 절은 데블스 애드버킷이다. 아래 세 주장은 팩 전체가 딛고 선 전제이며, 무너지면 §3~§5의 순위가 뒤집힌다.

**(1) "S3-a는 덮이지 않은 방향이다."** — 이 주장의 근거는 오직 **표적 교체**(가격 분포 CRPS → 변동성 이벤트 Brier)이고 **정보집합은 새롭지 않다.** 같은 지수 수준 입력이 V4(`multivariate_timeseries_v4.yaml`, 판정 hold — h21 +0.29%/h63 +1.69%)·V5에서 이미 시도돼 게이트를 통과하지 못했고, V9 E5/E6(Δlog(VXN/VIX), 2010–14 서브창 260원점)은 장기 쌍대 **+0.000006 CI90 [−0.000008, +0.000021]** 무효익 + 단기 h1+h5 **+1.65% [+0.000058, +0.000246] 유의 악화**로 채널이 폐기됐다 — **|ρ|=0.011로 직교인데도** 그랬다. 검토관은 "표적을 바꾸면 정보가 살아난다"가 이 저장소에서 실제로 관측된 적이 있는지 물어야 한다(있다: V13이 그 사례다. 단 그때 살아난 스킬은 지속성뿐이었다).

**(2) "V13-VOL은 캠페인의 긍정 결과다."** — 맞지만 라벨이 정정됐다. rung-3에서 **EWMA가 PB(당일 수준 단독 로짓)를 양방향으로 이긴 셀은 0/9**이고, |EWMA−PB| ≤ 0.008, 한 방향 유의 열위가 2셀이다. 즉 스킬은 "**당일 변동성 수준의 지속**"이며, 문헌 사전확률과 정합한다(Hansen & Lunde (2005)). 게다가 **홀드아웃 미소모**라 2015–18 전이는 미검증이고, h63 신뢰도는 rel≈0.08(오보정)이다. 검토관은 "긍정 1건"을 프로그램 진척의 증거로 읽지 말아야 한다.

**(3) "일간 종가 정보집합의 벽은 닫혔다."** — 벽은 **정보집합 × 표적 × 창 × 계보**의 벽이지 "일간 NASDAQ에 정보가 없다"가 아니다(V8은 historical simulation을 +3.96%/+4.21%로 이긴다). 또 **축 곱공간은 미표집**이며(V10 조합 격자는 가법 대리 최상 +1.147% CI90 [+1.07e-04, +9.99e-04]였으나 적격 12조합 **전부** 상위 5% 원점 제거 후 CI90 하한이 음수 → V12-D5 종결), **2015+에 대한 주장은 아무것도 없다**(미열람). 검토관은 §4-7의 "성립하지 않는 진술" 목록을 먼저 읽고, 팩의 어느 문장이 그 선을 넘는지 찾아야 한다.

---

## 2. 현재 상태 지도

> 이 절이 지키는 거버넌스(백테스트 금지의 경계·ML 게이트·창 규율·봉인 바이트 불변·참고 의견 지위·PIT/라이선스)는 §9에 정본이 있다. 여기서는 반복하지 않고, 표의 모든 CRPS·Brier 수치가 **결정론 수치모델의 base rate 참조 지위**(dualdb 스펙 v1.0 §8 예외, `docs/DECISIONS.md` 8-6)이며 하이퍼파라미터(창·임계·문턱)가 정점 지식을 간접 내포할 수 있다는 caveat만 재확인한다.

### 2-1. 트랙 지도 — 가격 분포 계보 V1~V8

표적: NASDAQCOM 일간 로그수익 분포, h∈{1,5,21,63}.

| 트랙 | 목표 · 정보집합 · 모델 | 평가 규약 | 판정 | 핵심 수치 (경로) | 산출물 | 봉인/동결 |
|---|---|---|---|---|---|---|
| **V1** `shadow.mf_dfm_ridge_varx_v1` | ALFRED PIT 거시(PAYEMS·CPI 등 10계열)+일간 시장 6계열 → 혼합빈도 DFM + ridge VARX (`data/contracts/multivariate_timeseries_v1.yaml` `sources`) | 사전등록 섀도 전용(`status: preregistered_shadow_only`) | 섀도 원장만 축적, 게이트 수치 본 지도에서 미열람 `[미검증]` | 섀도 예측 17행 `data/timeseries/ledgers/forecasts.jsonl` | 계약 v1 · `data/timeseries/` | V1 정본 ALFRED 스토어가 V9 vintage 수집의 저장소(`DECISIONS` V9-D5) |
| **V2** `shadow.mf_dfm_ridge_varx_v2` | V1 + PIT 등급 체계(native_pit/reconstructed/captured_forward), 후보 C1(core market + growth/inflation 요인) | 봉인 평가 1회, 2019+ | **FAIL/hold** — h21·63 개선<2%, CI 상단>0, GFC coverage<70% | 1,011원점: h21 −0.46%, h63 −9.54%, 장기 CI90 [+0.000263, +0.005448](양수=악화) `data/timeseries_v2/ledgers/sealed_evaluations.jsonl` | 계약 v2 · V8 계약 `v2_benchmark` run `tsv2-backtest-f995c40e…` `gate_result: fail`, `retune_prohibited` | **봉인 8파일**. 2019+ 점수 공개로 후속 모델의 2019+는 준청정(`v8.yaml` `disclosure_caveat`) |
| **V3** `shadow.nasdaq_direct_regime_distribution_v3` | 직접 누적수익, 7성분(anchor·regime·event·market_implied 등), student-t/regime 잔차; 고정 앙상블 비교군(HS .5/FHS .3/SBB .2) | design pseudo-OOS(봉인 아님, `freeze_note`) | hold — <2%, 극단 Q4 coverage·stress regime 실패 | h21 +0.75%, h63 +2.02%, 장기 +1.39% `data/timeseries_v3/runs/tsv3-research-1f80a06b….json` | 계약 v3 · 포인터 `shadow_validation_hold` | 동결 연구 후보 |
| **V4** `…pit_market_event_distribution_v4` | V3 + CBOE VIX9D/VIX3M/VVIX/SKEW 이벤트 상태(`v4.yaml` `sources`) | V3 비교군·임계 무변경 | hold — 동일 3사유 | h21 +0.29%, h63 +1.69%, 장기 +0.99% `data/timeseries_v4/runs/tsv4-research-bd2ac04e….json` | 계약 v4 | `shadow_gate_hold` |
| **V5** `…pit_hybrid_distribution_v5` | 8패밀리 앙상블(quantile EN·student-t·HGB·DLM·soft regime·EVT·event LP, `v5.yaml` L124–131) | research+operational 게이트 | hold — 7사유(장기 −9%, 부호별·극단·stress) | 963원점: h21 −10.69%, h63 −7.38%, 쌍대 CI90 [+0.00133, +0.00607] `data/timeseries_v5/runs/tsv5-research-92c262ef….json` | 계약 v5 · `outputs/timeseries_v5/audit/` | 2007–2026 run은 진짜 봉인 홀드아웃 아님(`baseline_reproduction.json` L7) |
| **V6** `…pit_hierarchical_distribution_v6` | 11패밀리(파운데이션모델 챌린저·시장내재 보정 포함), 결정론 replay 컨테이너 | 봉인 2019+ 385원점 | hold — 8사유(coverage·<2%) | h21 +1.27%, h63 +0.58% `outputs/timeseries_v6/audit/FINAL_REVIEW_SUMMARY.json`; V7가 불변 재현(`outputs/timeseries_v7/audit/v6_gate_reproduction.json` `V6_HOLD_REPRODUCED_IMMUTABLY`) | 계약 v6(`contract_status: frozen`) | 봉인 run `tsv6-sealed-46d58750…` |
| **V7** `…hierarchical_distribution_v7` | V6 계승, 주간 원점·경로 20,000 | 전방 라벨 성숙 대기 | **WAIT_DATA**(historical 미실행, 숫자 비공개) | `outputs/timeseries_v7/status.json` | 계약 v7 `frozen_v7_p0_003`(2026-08-25) | 파킹(Codex 트랙) |
| **V8** `shadow.mf_dfm_varx_calibrated_v8` | V2 엔진 read-only + 분포 계층 B1~B5; 승자 E10 = FHS(h21/63) + HS 블렌드 .75 + PIT isotonic 재보정 s=.5 (`v8.yaml` `frozen_winner`) — FHS: Barone-Adesi, Giannopoulos & Vosper (1999) | dev 24회 예산·stop-loss, holdout finalist ≤3·1회, 봉인 1회·사용자 사인오프(R8-D2) | **GATE PASS → 라이브(research_reference)**; 챔피언 승격 아님 | design +2.86% · holdout 209원점 쌍대 −0.002204 CI90 [−0.003266, −0.001060] `data/timeseries_v8/ledgers/holdout_scorings.jsonl` · 봉인 run `tsv8-sealed-64345a81…`: 전체창 1,011원점 h21 **+3.96%**/h63 **+4.21%**, 80% 적중 0.813/0.808, 장기 CI90 [−0.002639, −0.000858], GFC 0.782; **봉인창 385원점** h21 +3.47%/h63 +4.87%, CI90 [−0.003790, −0.000265], 자체 판정 **hold**(2008 원점 0) `sealed_evaluations.jsonl` | 계약 v8 · 원장 5종(`ledger_registry.yaml` L316–342) · `outputs/timeseries_v8/reports/R8D3_PUBLICATION_REVIEW_20260901.md` | `frozen_for_sealed_evaluation`(2026-08-30), `src/ai_fc/timeseries_v8/` |

> **`model_code_hash` 혼동 금지(§9-3b 정정)**: V8 계약(L36)의 값은 `bb225cbf963b095271452a669f7d8f1aa5eb29c8abda5a4ae1ed9ecd1d702c5c`이며, `8361899fd797…`는 V9 계약 L39·V10 계약 L37의 값이다.

### 2-2. 트랙 지도 — V8 위 개선 시도 V9~V12, 신규 표적 V13, 인접 계층

| 트랙 | 목표 · 정보집합 · 모델 | 평가 규약 | 판정 | 핵심 수치 (경로) | 산출물 | 봉인/동결 |
|---|---|---|---|---|---|---|
| **V9** `…varx_liquidity_v9` | V8 승자 + 외생 열: M2SL·TOTCI·TOTLL·WRMFNS(ALFRED first-release) + VXN/VIX 스프레드(서브창 2010–14) | 단독 ablation, E0 항등(1e-12) 대비 쌍대 CRPS, 챔피언=신규 피처≥1 ∧ E0 개선 | **동결(대안 D)** — 6종 전부 무효익 | E1 +0.000014 [−0.000000, +0.000028]; **E2 +0.000043 [+0.000019, +0.000074] 유의 악화**; E6−E5 장기 +0.000006 [−0.000008, +0.000021], 단기 +1.65% 악화 `outputs/timeseries_v9/reports/E2_E4_ABLATION_REPORT_20260902.md`, `E5_E6_VXN_SPREAD_VERDICT_20260902.md`; 독립 재계산 5쌍 개선 0, 최대\|Δ\| 4.33e-05, se 4.04e-06~2.11e-05 → **"측정된 영"** `docs/review/V9_V10_V11_INDEPENDENT_VERDICT.md` §1.3 | 계약 v9(`status: draft`) · `data/timeseries_v9/ledgers/development_experiments.jsonl`(7행) | 예산 7/24, holdout 0/3. V9-D5 vintage 수집 트랙만 진행 |
| **V10** `…varx_regime_width_v10` | 분포 계층 5축: W1 상태조건부 재표집(κ)·W2 K-혼합·W3 상태조건부 블렌드(γ)·W4 isotonic·W5 단기 FHS; 상태=EWMA97 분산비 | V8 model/backtest 포크(source_pins) · 12회 stop-loss(<+1%) · 6렌즈 적대 검증 | **동결** — 유일 챔피언이 GFC 위기원점 인공물 | W3 γ=−0.10: +0.000277 CI90 [+0.000016, +0.000679] = **+0.64%**(417원점); GFC 78원점(18.7%)이 델타 **83.8%**, GFC 제거 0.64→0.13%, 상위5% 제거 −0.0000115, 클립 포화 7주=엣지 58%; holdout 게이트(+2%) 통과 확률 **<2% 추정** `V10_FREEZE_DECISION_20260903.md`; D7 정정: 조합 격자 미표집, 12조합 중 6개 +1.04~1.15%나 상위5% 제거 후 CI90 하한 전부 음수 | 계약 v10 · dev 원장 12행 · `CHAMPION_ADVERSARIAL_VERIFY_20260903.json` | 예산 12/24, holdout 3/3 보존, V12-D5 재개 안 함 |
| **V11** (계약 없음) | 평시(비위기 하위 80%) 직교 상태 프록시 P1~P9 × PIT/부호/IQR 결함 × h21/63, 기존 E0 데이터만 | 사전등록 4중 기준 → 6렌즈 → 표본외 전이 | **동결** — real but not exploitable | 통과 4/54(판정서) — **실측은 48검정·프록시 8종**(`orthogonal_calm_screen.json`, §9-3 각주·D-13 ①); P1 모멘텀→PIT h21 Δ −0.120 [−0.192, −0.035]; 전이: 순방향 +0.97% 악화, 역방향 +1.49% 악화; P(≥4)=0.25~0.32 `[48/54 기준 미검증]`; 독립 재계산 채택 0/12, 순열 p=0.118 | `docs/design/v11_orthogonal_calm_diagnostic_260903.md` · `data/timeseries_v11/diagnostics/*.json` | 백테스트 0회, holdout 0 |
| **V12** `derived.first_touch_event_probability_v12` | V8이 이미 내는 −10% first-passage 확률(417원점, h21/63)의 재보정 맵 T1~T4 + 반사원리 2Φ 기준선 | 사전등록(커밋 `ec496463`) · 양방향 CI90 하한>0 · T5 음성대조 | **부정결과 계약**(`status: negative_result_draft`, `gates.armed: false`, 후보 0) | BS V8 h21 0.061485/h63 0.144973, BSS vs 기후 0.0498/0.0906이나 CI90 0 걸침; 채택 0/8, T5 pooled **0.254 > 0.10**; T-A 수리: N-p-block 0.201, N-y-block 0.000, N-blk-pair 0.000 → **NOT_REPAIRED** | 계약 `multivariate_timeseries_v12.draft.yaml` · `V12_DECISIONS_20260907.md` · 포스트모템(H3: 상수-σ i.i.d. 경로 생성기) | dev 예산 24 중 계약 기록 0(S3 환산 4 → 잔여 20), holdout 0 |
| **V12b** (경로 생성기 T-B) | 잔차 블록 재표집 ℓ_z∈{2,3,5}/AR(1) φ로 단기 되돌림 복원 | 새 사전등록 + 건전 y-block 귀무 + CRPS 무손상 | **파킹**(2026-09-08, 폐기→보류 재라벨) | P1 진단: 수익률 ACF lag1 **−0.0762**, z AR(1) φ̂ **−0.0529**, VR(5) **0.8736** `p1_h3_prediagnosis.json` — 크기 온건 | `V12B_TERMINATION_20260907.md`(무수정) · `V12B_PARKED_20260908.md` | 예산 0, 재개는 새 ID |
| **V13-VOL** `event_probability.volatility_v13` | 변동성 이벤트 확률: P(VIX≥25/30 within 5/21/63 영업일), P(RV21_ann>0.1694); 봉인 V2 아카이브 read-only VIX·NASDAQCOM PIT, n_panel 2,014; 사다리 기후→EWMA-logit→HAR-logistic→GARCH-t(미실행) + **자명 기준선 PB=당일 수준 단독 로짓** | 기후 대비 쌍대 Brier CI90 하한>0 **양방향**(early 2007–10↔late 2011–14), y-block ℓ=13 귀무 ≤0.10, B=2000 seed 20260907, Murphy 신뢰도 보고; G2: 우월-아니면-단순-아니면-HOLD | **champion = persistence_pb 전 9셀 → T3 라이브 카드(참고 의견)**, 홀드아웃 미소모 | rung-1 EWMA 9/9, BSS +0.094~+0.898, 귀무 ≤0.017; rung-2 HAR 기후 9/9·EWMA 대비 **0/9**; rung-3 EWMA가 PB를 양방향으로 이긴 셀 **0/9**, PB 기후 9/9, 귀무 ≤0.033; h63 cross-fit isotonic fallback→raw | 계약 `multivariate_timeseries_v13_vol.yaml`(`status: live_reference`, `display_tier: t3_live_card`) · 원장 `vol_experiments.jsonl`(3행)·`vol_live.jsonl`(2행)·`approvals.jsonl`(7행) · `champion_coefficients.json` sha256 `1a857850…` | 예산 3/8, holdout 0/3(finalist `V13VOL_champion_aec80c65038b`), 계수 immutable |
| **dualdb** | 닷컴↔AI 이중시대 일간 비교 DB; k-NN 아날로그·DTW·LPPL 워크포워드·트윈 대조 → `data/base_rates/*_auto.md` | 결정론 수치모델 예외의 근거 문서(§8) | reference; LPPL은 **demoted**(8-7) | `docs/MODEL_REGISTRY.md`, `dualdb/CHANGELOG.md` #1~#11 | `dualdb/` | 스펙-구현 이탈은 CHANGELOG 기록 |
| **시나리오 V5.2** | 닷컴 국면 블록 재표집 3시나리오(S1/S2/S3), `#future` 고객 기본 표면 | display-promotion 계약 r2(2026-08-18) · 배포시점 재봉인 + replay 검증 | **고객 기본 표시**(research_only, `official_or_champion_use: false`) | 분리 지표 S1–S2 표준화 DTW 0.1175→1.7185(임계 +0.8704), S2–S3 DTW 0.123 | `scenario_v5_2_weights.yaml`, `scenario_v5_3_separation.yaml` | 게이트 닫힘 시 `stale_last_valid` + 사유 공시(B안) |

인접 참조 계층(가격 분포 아님): `src/ai_fc/market/{kalshi,polymarket,options_bl}.py`는 market_implied/edge **기록 전용**(P3 봉인, 옵션은 risk-neutral 프록시 병기), `data/base_rates/volatility.md`는 `vix-25-90d` 질문의 수동 base rate(무조건부 44%, 8월말 앵커 조건부 33.3%/11.1%).

### 2-3. 오늘 사이트에 LIVE인 것과 그것을 정직하게 만드는 게이트

**(1) `#timeseries` 가격 카드 = V8 research_reference.** 슬롯 체인 `timeseries = v8 or (v5 or v2 or v1)` (`src/ai_fc/dashboard.py` L460). 포인터 `data/timeseries_v8/multivariate_v8_latest.json`: `status: shadow_live`, `display_state: research_reference`, `sealed_gate_pass ∧ operational_pass` 둘 다 true. 정직성 게이트:

- read-model 가드: visible ⟺ 두 게이트 동시 통과, `reference_opinion_only`, HOLD면 숫자 서버 단계 제거(`read_model_contract.py` L345–373; R8-D3 fail-closed).
- 운영 게이트: 시장 입력 48h(DTWEXBGS 216h), 최근 26원점 CRPS 열위 5% 초과 시 HOLD. 주말·월요일은 자연 HOLD.
- 원점 경과 2단 임계 warn 1 / hold 10 거래일, 만기 지평 실측 병기(`origin_age_policy`).
- 공개 범위: 봉인창(385원점)과 전체창(1,011원점, 개발기간 포함)을 **분리 공시**하고 봉인창 자체 판정 hold 사유를 인쇄; 방향 적중률·first_touch 점수는 비공개(R8-D4).
- 승격 아님: `promotion.automatic_champion: false`, `minimum_shadow_sessions: 126` — 현재 섀도 원점 **2개**, 해소 2건.

**(2) `#timeseries` 5번째 탭 = V13-VOL '변동성 이벤트 기준율' 카드(T3).** 전용 read-model 키 `timeseries_v13_vol`(가격 카드와 결합 금지, `dashboard.py` L466–467). 라이브 값(`vol_latest.json`, as_of 2026-09-04, VIX 14.53·RV21 0.1294): vix25_h63 기준율 **28% [80%: 21–36]**, vix30_h63 **11% [6–16]**, rv_h63 **81% [75–87]**, vix25_h21 6%, vix25_h5 0.5%. 정직성 게이트:

- 네 게이트(설계 증거 sha 대사·`gates.armed`·계수 핀 3자 일치·NYSE 거래일 신선도 `missing_sessions ≤ 1`) 전부 성립 시에만 숫자, 하나라도 어긋나면 HOLD + 사유, **마지막 값 재사용 없음**(V13-D4/D5 fail-closed; `read_model_contract.py` L379–415).
- caveat lead '설계창(2007~2014) 스킬 · **홀드아웃 미검증** · 참고 의견 — 매매 신호가 아닙니다' 굵게 상시, h63 셀 '▲ 보정 약함'(설계창 rel≈0.08), 80% 대역은 델타법 계수 불확실성이지 보정 대역 아님.
- X1 이름충돌 6항: 명칭 '기준율'(예측 아님), 배지 '수치모델 · 당일 수준 지속(PB)', 지평 단위 '영업일', `vix-25-90d` AI 예측과의 괴리 칩은 **표시만**(15%p, 자동 재예측·산술 결합 0).
- 라이브 전진 게이트 사전등록: 셀당 성숙 원점 60 이후 기후 대비 CI90 하한 ≤0이면 자동 강등, 재무장 없음. 계수 재적합 금지.
- 자동화: `timeseries-v2-refresh`(화~토 01:35 UTC) → `timeseries-v8-shadow`(03:10) → `timeseries-v13-vol-live`(03:40, V2 refresh 종속) → pages/verify `workflow_run` 연쇄.

**(3) `#future` = 시나리오 V5.2 3시나리오(고객 기본).** 배포시점 `scenario-v5-2-build --force` + replay 검증, 게이트 닫힘 시 마지막 유효 후보 + 기준일 + 사유 공시(B안).

### 2-4. 배포 사다리 T0~T4와 각 표면의 위치

사다리 원문: `docs/design/v12_gate_design.md` §4.3 (V13 승계: `docs/design/v13_vol_live_card_display_design_260908.md` §2).

| 단계 | 정의 · 게이트 | 지금 그 단계에 있는 것 |
|---|---|---|
| **T0** 내부 산출물 | 봉인 무변경·원장 무수정 | V1~V7 산출물(화면은 validation_pending), V9/V10 run·원장, V12 진단 JSON |
| **T1** 문서·리뷰팩 | 모든 수치에 CI90·귀무·미검증 표기 | V9·V10·V11 동결 판정서, V12 부정결과 계약·최종보고, V12b 파킹 문서, 리뷰팩 `outputs/review-packs/NASDAQ_*` |
| **T2** 대시보드 숨김 패널 | T1 + 게이트 무장 + G0 무손상 + 승인 | (경유만) V13-VOL — 2026-09-08 14:54 진입 후 14:58 T3 전환(`approvals.jsonl` r2). V12는 진입 불가(armed=false) |
| **T3** 라이브 카드 | T2 + 게이트 통과 + X1 해소 + '참고 의견' 상시 | **V13-VOL**(`display_tier: t3_live_card`) · **V8 가격 카드**(display-promotion 계약 R8-D3로 공개된 research_reference — T3 상당 배치는 필자 대응이며 계약 원문의 tier 값은 아님) · 시나리오 V5.2(별도 계약) |
| **T4** 실전 자금 결정 근거 | CLAUDE.md P3 게이트(해소 50문항+ & Brier<0.18) | **없음** — tier 값 자체가 없어 구조적 차단. LLM 캘리브레이션 원장은 해소 행 9 / 고유 이벤트 5 — DISTINCT question_id 기준 50에 원거리 |

> `v13_vol.yaml` L257 `display_tiers_allowed: [t0_internal, t2_hidden_panel, t3_live_card]` — **t1 값이 존재하지 않는다**. 신규 계약이 T1을 tier로 쓰려면 `t1_docs`를 정의하거나 문서 단계는 tier 밖 절차로 취급한다고 명기할 것(§9-1 [5b] 주).

### 2-5. 자원 대장 — 되돌릴 수 없는 것과 예산

잔량 대사표(계약 라인·원장 행수 실측)는 §9-3b에 있다. 여기서는 **비가역성** 관점의 대장을 싣는다.

| 자원 | 소모 | 근거 |
|---|---|---|
| V2 봉인 공개 | 1/1 소모 — FAIL, 재조정 금지 | `sealed_evaluations.jsonl`, `v8.yaml` `v2_benchmark` |
| V6 봉인 run | 1회(385원점 2019+) — hold | `outputs/timeseries_v6/audit/FINAL_REVIEW_SUMMARY.json` |
| V8 dev 예산 | 12/24 (E0~E11) | dev 원장 12행 |
| V8 holdout finalist | **1/3 소모**(E10, PASS) | `holdout_scorings.jsonl` 1행 |
| V8 봉인 공개 | **1/1 소모**(disclosure #1, 2026-08-30 R8-D2) | `sealed_disclosure_number: 1` |
| V8 섀도 승격 시계 | 원점 **2 / 126** | `shadow_forecasts.jsonl` |
| V9 | dev 7/24 · holdout 0/3 · 봉인 0 | `E5_E6_VXN_SPREAD_VERDICT_20260902.md` |
| V10 | dev 12/24(stop-loss) · holdout 0/3 · 봉인 0 | `SINGLES_COMPLETE_STOPLOSS_20260903.md` |
| V11 | 백테스트 0 · holdout 0 | `V11_FREEZE_DECISION_20260903.md` §5 |
| V12 | 계약 기록 소모 0(S3 환산 4 → 잔여 20), holdout 0, 봉인창 미계산 | `v12_gate_design.md` 표 E1 |
| V13-VOL | dev **3/8** · holdout **0/3**(finalist 1 등록) · 봉인 0 | `v13_vol.yaml` `evaluations_spent` |
| 봉인 바이트 | V8+V2 `e3ff2fdb64ac71c0f05ae8e4508ef1c5a7c8fba7b78d81548918881032c8d224` **0바이트**, V8 원장 `b9c492be…` 일치 | `SUNDAY_LOOP_FINAL_REPORT.md` 표 I |
| **캠페인(V9~V13) 비가역 행동** | **0** | `NASDAQ_CAMPAIGN_SESSION_REVIEW_20260908/00_SESSION_TIMELINE.md` |
| 계산 비용(기록된 것) | V10 6렌즈 검증 7 에이전트·44만 토큰·8.4분; V12 루프 13태스크 완주 | 위 두 문서 |
| 데이터 구매·발송(사용자) | FirstRate ~$300–400 미구매(FR-1) · CBOE DataShop QQQ 질의 **미발송**(V12-D4) | `DECISIONS` 2026-09-08 결정 대기 3·4 |
| 거버넌스 사고 | main 잠금 리프스펙 FF 푸시 2회(손실 0) → GOV-1 우회 금지 | `DECISIONS` GOV-1, `approvals.jsonl` r1 |

미결 사용자 결정: **V13-D3**(홀드아웃 1슬롯), **V13-D6**(EXIT base rate 배선), **V12-D4**(CBOE 질의), **FR-1**(FirstRate). 결정표 전문·승인 원문 템플릿은 §10·§10-b.

### 2-6. 2026-09-09 갱신 (본 개정에서 추가된 사실)

| 항목 | 사실 | 지위 |
|---|---|---|
| **PR #167 병합** | 병합 커밋 `a789a2c2`("Merge pull request #167 from Sung-JinPark/claude/v13-next"). 직전 이력: `bcae3076`(PR #168 analytics owner opt-out), `2df3a5fc`(origin/main `8b546cc6` 머지 — inventory 재생성으로 충돌 해소) | 저장소 실측(`git log`) |
| **V13-VOL T3 라이브 카드 배포 완료** | 9셀 champion = `persistence_pb`, 계수 sha256 `1a857850…`(3자 핀 일치), `display_tier: t3_live_card`, **홀드아웃 미소모**(0/3) | 배포 행위 완결 — 카드 지위는 여전히 '참고 의견 · 홀드아웃 미검증' |
| **라이브 워크플로 CI 실행 성공** | `timeseries-v13-vol-live`가 체인(v2-refresh 01:35 → v8-shadow 03:10 → v13-vol-live 03:40 UTC) 안에서 정상 실행, **멱등 확인** | 자동화 체인 정상. 신규 카드를 이 체인에 끼워 넣는 것은 **배포 행위**이므로 사용자 승인 대상(§9-4) |
| **V8 가격 카드 HOLD** | 자체 신선도 게이트(입력 48h·DTWEXBGS 216h·원점 경과 2단 임계)에 의한 HOLD | **고장이 아니라 설계된 fail-closed**. 주말·월요일 자연 HOLD와 같은 계열이며, 카드에 그 취지 문구를 두는 것이 §9-5 권고 |

---

## 3. 단계 지도 — 지금 어디, 무엇이 남았나

> 심판의 `stage_map_markdown`을 본문 체계에 맞춰 다듬었다. 거버넌스 전제는 §9에 정본이 있어 여기서는 반복하지 않는다.

### 3-1. '완결된 프로그램'의 조작적 정의

이 지도는 다음 다섯 조건이 **동시에** 충족된 상태를 완결로 본다. **어느 하나도 '좋은 결과'를 요구하지 않는다** — 판정이 확정되면 부정 결과도 충족이다.

| # | 완결 조건 | 현재 실측 | 근거 파일 |
|---|---|---|---|
| **C1** | 라이브 전진 트랙레코드: V13-VOL 셀당 **성숙 원점 60** 이상, V8 섀도 **126세션** | V13 라이브 원장 2행 · V8 섀도 원점 **2/126** | `vol_live.jsonl`, `shadow_forecasts.jsonl` |
| **C2** | 홀드아웃·봉인 자원 판정 확정 | V8 holdout **1/3**·sealed **1/1** 소모 · V13 holdout **0/3**(finalist 1 등록) | `holdout_scorings.jsonl`(1행), `sealed_evaluations.jsonl`(1행), `v13_vol.yaml` L86 |
| **C3** | 미검증 정보집합 2종(옵션 표면·일중)에 대해 **채택 또는 측정된 영** 판정 | 둘 다 미착수 · `data/intraday/` **부재** | `CAMPAIGN_REVIEW_NEXT_DESIGN_260908.md` §C-4 |
| **C4** | EXIT 트리거 base rate 배선 완료(V13-D6 형식, 표시만·산술 결합 0) | 미결정 | `docs/DECISIONS.md` 사용자 결정 대기 |
| **C5** | P3 게이트: 해소 **50문항+** & Brier<0.18 (표본 단위 = DISTINCT question_id) | `calibration/ledger.csv` **9행 / 5문항** | 실측 |

**정직한 비대칭**: C5는 LLM 예측 원장의 문제이고 C1~C4는 수치모델 트랙의 문제다. **수치모델이 완벽해도 C5 없이는 T4가 열리지 않는다** — 남은 거리가 가장 먼 조건은 C5(45문항)다.

### 3-2. 완료된 단계 (S0~S2)

| 단계 | 진입 게이트 | 종료 게이트 | 산출물 | 결과 |
|---|---|---|---|---|
| **S0. 가격 분포 계보 확립 (V1~V8)** | 계약 v1 사전등록 | V8 봉인 1회 공개 + 사용자 사인오프(R8-D2) | 계약 v1~v8, 원장 5종, `R8D3_PUBLICATION_REVIEW_20260901.md` | **GATE PASS → T3 라이브(research_reference)**. 전체창 1,011원점 h21 +3.96%/h63 +4.21%, 장기 CI90 [−0.002639, −0.000858]; **봉인창 385원점 자체 판정 hold**(사유 단 하나 — 'GFC 2008 원점 0'). 챔피언 승격 아님 |
| **S1. V8 위 단독 축 4종 소진 (V9~V12)** | 각 축 사전등록 커밋 | 예산 소진 또는 stop-loss | dev 원장 V9 7행·V10 12행, V11 진단 JSON, V12 부정결과 계약 | **전부 부정**. V9 외생 6종 무효익(E2 유의 악화) · V10 유일 챔피언 W3 +0.64%가 GFC 78원점(18.7%)이 델타 83.8% → 인공물 · V11 통과 4가 양방향 전이 실패 · V12 채택 0/8 + T5 실패(0.254>0.10). **세 챔피언 origin별 Δ 상관 \|r\| ≤ 0.154 = 서로 다른 실패** |
| **S2. 이벤트 표적 전환 (V13-VOL)** | 계약 사전등록(결과 전 커밋) | rung-3 champion 확정·계수 동결·X1 6항 검수 | 계약 `live_reference`, `champion_coefficients.json` sha `1a857850…`, 원장 3종 | **캠페인 유일 긍정 — 단 스킬 라벨은 '당일 변동성 수준의 지속'**. rung-2 HAR의 EWMA 대비 증분 **0/9**, rung-3 EWMA의 PB 대비 양방향 우세 **0/9** → champion = `persistence_pb`. T3 라이브 카드, **holdout 0/3 미소모** |

### 3-3. 남은 단계 (S3~S8) — 게이트·산출물·승인·기간·비용·부정 종료 확률

부정 종료 확률은 **필자 주관 사전확률**이며(1% 단위·80% 구간 병기), 근거는 각 카드의 자기 사전확률(§5)과 심판의 감점 사유다. 저장소 산출값이 아니다.

| 단계 | 진입 게이트 | 종료 게이트 | 산출물 | 승인 지점 | 기간 | 비용 | **부정 결과로 끝날 확률** |
|---|---|---|---|---|---|---|---|
| **S3** 0원 정보집합·표적축 스크린 (**현재 진입점**) | 새 계약 ID의 사전등록 커밋이 결과보다 **선행**. V13 계약(예산 3/8, finalist 1, 계수 동결·T3 라이브)은 **무접촉** — 개정이 아니라 신규 ID | 셀별 MDE를 결과 전 공표한 상태에서 ① ≥1셀 양방향 CI90 하한>0 ∧ y-block ≤0.10 ∧ BH q=0.10, **또는** ② 전 셀 '측정된 영'(검정력이 있었음을 MDE로 입증). **검정력 없이 나온 null은 종료가 아니다** | 새 계약 YAML, dev 원장, T1 판정서, 리뷰팩 | S3-a~e **불필요**(비가역 자원 0). S3-h만 CFTC D0 `model_use` 승격 결정 1건 | 병렬 2~3슬롯 기준 **3~6주** | **$0** | 슬롯별 §3-3b |
| **S4** 홀드아웃 1회 소모 (**비가역**) | S3에서 양방향 채택 셀 발생 + 그 셀만 finalist로 **결과 전** 사전등록 | 홀드아웃 1회 채점, 결과 무관 원장 append(`holdout_refit` 금지) | `holdout_scorings.jsonl` 1행, 판정서 | **사용자 명시 원문 필수**(§10-b D-1). 승인 없으면 verb 자체가 없다(`holdout_execution_path: absent_by_construction`) | 1~2주 | $0 | **FAIL 확률 55% [80%: 35~75%]** — V8 E10은 design→holdout 전이에 성공했으나(+2.86%→+4.04%) V10은 통과 확률 <2%로 자체 추정돼 슬롯을 보존했다 |
| **S5** base rate 배선 + 라이브 전진 게이트 무장 | 홀드아웃 PASS 셀 존재(S4) **또는** '홀드아웃 미검증' caveat 유지 합의 | `vix-25-90d`·FOMC·드로다운 EXIT 질문에 base rate가 **표시만**으로 연결(산술 결합 0, 자동 재예측 0) + 라이브 전진 게이트(셀당 성숙 원점 60, 미달 시 자동 강등·재무장 없음) 무장. 부속 슬롯 **S5-b**(ACI conformal, `ml-7`)는 판정 트랙이 아니라 커버리지 보증 인프라로만 | 배선 규칙 문서, 승인 원장 append | **V13-D6** 사용자 결정 | 1~2주 | $0 | 배선은 판정이 아니라 결선이므로 '부정 종료' 개념이 없다. 다만 S5-b가 무손상 확인에 그칠 확률 **70% [80%: 55~85%]** |
| **S6** 유료 정보집합 (**S3 결과 조건부**) | **S3-a($0 형상 스크린) 결과가 구매를 정당화할 때만**. 스크린이 0이면 '옵션 지수 수준 정보는 PB에 흡수'가 $0로 확정되고 유료 갈래의 기대가치가 내려간다. S6-b는 S3-d 결과 + rv 셀 VIX_t 중첩 스크린 뒤 | V13 셀 양방향 CI90 하한>0 ∧ y-block ≤0.10 ∧ BH/Romano–Wolf. **−10% first-passage는 채택 게이트가 아니라 base rate 산출로 강등** | 새 등급 `vendor_eod_archive` 계약, 적재 영수증, 판정서 | **V12-D4**(질의 발송 — 지금 보내도 손실 0), 구매 결정, **FR-1**. CBOE §2b 파생표시 조건 소유자 회신 전 T2/T3 금지 | 4~8주 | **$300~수천** | S6-a **65% [80%: 50~80%]**, S6-b **72% [80%: 55~85%]** |
| **S7** 라이브 전진 트랙레코드 축적 (**시간이 유일한 비용**) | S5 배선 완료 + 자동화 체인 정상(2026-09-09 CI 성공·멱등 확인) | **C1** — V13 셀당 성숙 원점 60, V8 섀도 126세션 | 라이브 원장 누적 | 신규 카드의 체인 편입은 사용자 승인 | **1~5년** (V8 섀도는 원점 2·격주 케이던스라 126세션까지 **약 4.8년**, 주간이면 ~2.4년. V13 h63은 라벨 성숙에 63영업일 추가) | ≈$0 | 부정 종료 개념 없음 — **단축 수단이 없다**. 그것이 라이브 포워드 only 원칙의 대가 |
| **S8** 신규 버전 봉인 1회 + P3 게이트 → T4 | S7 트랙레코드 + 신규 모델 버전의 봉인 finalist 사전등록. V8은 `maximum_disclosures_per_model_version: 1` 소진·`retune_after_failure: prohibited`이므로 **새 버전으로만** | **C2 확정 + C5**(해소 50문항+ & Brier<0.18). 현재 9행/5문항 → **45문항 부족** | 봉인 원장 1행, 사인오프 기록 | 사용자 사인오프(R8-D2 형식). **Phase 전환은 사용자만** | C5에 종속(수년) | $0 | **T4는 여전히 구조적으로 차단** — `display_tiers_allowed`에 t4 값 자체가 없다 |

### 3-3b. S3 슬롯 상세

| 슬롯 | 내용 | 예산 | 시간 | 비용 | 부정 종료 확률(필자 주관) |
|---|---|---|---|---|---|
| **S3-a** | 옵션 지수 형상(VVIX·SKEW **표준 split**, VIX3M·VIX9D는 서브창) → V13 9셀. `infoset-1`·`ml-1`·`classical-1` **단일 사전등록 병합** | ≤5 | 3~5일 | $0 | **65% [80%: 50~80%]** (카드 자기 사전 채택 30~40%) |
| **S3-b** | 발표 캘린더(정례 FOMC·CPI·NFP) → V13 **rv 셀 주효과**. `infoset-3` 주도, `ml-3`·`classical-3` 흡수 | ≤4 | 3~5일 | $0 | **58% [80%: 42~75%]** (h5 채택 40~50%, 단 VIX 셀은 정의상 기준선 안) |
| **S3-c** | MDD 깊이 분포 회귀(연속 CRPS) + −5% 배리어. `ml-6` 주도, `infoset-6` 흡수 | ≤6 | 4~6일 | $0 | **70% [80%: 55~85%]** |
| **S3-d** | 경로 생성기 ℓ_z 블록 재표집(V12b T-B) — **일중 데이터 불필요**(취득계획 §5 L40) | ≤4 | 3~4일 | $0 | **75% [80%: 60~88%]** (MDE h21 0.004590 vs 기대 ΔBrier 0.00065~0.00194 = 1/2.4~1/7) |
| **S3-e** | 꼬리 손실 재채점 진단(좌측 가중 CRPS·pinball τ=.05) — **판정 다리 아님** | 0(진단) | 2~3일 | $0 | 해당 없음 — T1 종료가 정상 산출 |
| **S3-f~h** | 텍스트(`infoset-8`)·교차자산 상관(`ml-4`·`classical-2`)·CFTC **인프라만**(`infoset-5`·`classical-8`) — 후순위, 재설계 선행 | ≤3 각 | 각 4~6일 | $0 | **85% [80%: 72~93%]** |

**사전등록 전 필수 수정(전 슬롯 공통)**: 퇴화 가드 — 양 반창 각각 min(사건, 비사건) 최소값 미달 셀은 **결과 보기 전에** `untestable_by_construction` 선언하고 family에서 제외. 실측 예: VIX3M 서브창 late leg(2012-04~2014-12, 692세션)은 VIX≥30 **0일**·≥25 5일(2에피소드).

### 3-4. 단계 간 의존 그래프

```
S0 ✔ ── S1 ✔ ── S2 ✔ ──┬─ S3-a(형상 $0) ──┬─ S4(홀드아웃 1회, 승인) ── S5(배선) ── S7(전진 60/126) ── S8(봉인+P3) → T4
                        ├─ S3-b(캘린더 $0) ─┘                                         ▲
                        ├─ S3-c(MDD $0)                                               │
                        ├─ S3-d(경로생성기 $0) ──────── S6-b(일중 $300) ──────────────┤
                        └─ S3-e~h(진단·후순위) ──────── S6-a(옵션 $500~) ─────────────┘
```

핵심 규율 세 줄:

1. **비가역 자원은 항상 $0 스크린 뒤에.** 구매(S6)도 홀드아웃(S4)도 S3 결과에 조건화된다.
2. **검정력 없는 셀은 사전 제외.** 사후 stop-loss가 아니라 결과 전 `untestable_by_construction` 선언 — 그렇지 않으면 전부-0 라벨에서 y-block 귀무가 퇴화해 거짓 PASS를 낸다.
3. **표적이 검정력을 결정한다.** V13 일간 패널 셀(n_eval 943~1008, `ewma_vs_pb` MDE ≈0.5~3.4% BSS)은 검정 가능하고, −10% first-passage(h21 late 7건)는 불가능하다. **같은 정보집합도 어느 표적에 붙이느냐로 운명이 갈린다.**

---

## 4. 반증된 방향과 그 함의

> 아래 수치는 전부 결정론 수치모델의 design 창(2007-01~2014-12) 적합·워크포워드 결과이며 **base rate 참조**다. 문턱·창 선택(θ=0.1694, K∈{25,30}, τ=학습창 80분위, split 2010-12-31, GFC 창 2008-01~2009-06)이 정점 지식을 간접 내포할 수 있다. **LLM 과거 질문 백테스트는 전 캠페인 0회.**

### 4-1. 기준점: V8 봉인 — 무엇이 통과했고 무엇이 HOLD인가

| 창 | 원점 | CRPS 개선 vs 최선 기준선(historical_simulation) h1/h5/h21/h63 | DM p값 | p10–p90 coverage | 장기 손실차 CI90 | 판정 |
|---|---|---|---|---|---|---|
| 전체 2007-01-05~2026-05-14 (개발창 626원점 포함) | 1,011 | +3.50% / +3.48% / +3.96% / +4.21% | 3.1e-6 / 6.8e-5 / 9.8e-6 / 0.011 | .803/.790/.813/.808 | [−0.00264, −0.00086] | **gate PASS** |
| 봉인 2019-01-04~2026-05-14 | 385 | +1.17% / +1.69% / +3.47% / +4.87% | 0.288 / 0.128 / **0.026** / 0.135 | .818/.771/.792/.782 | [−0.00379, −0.00026] | **status hold** — 사유 "필수 위기 국면 누락: great_financial_crisis_2008" |

- **통과한 것**: 분포 계층(FHS + blend .75 + PIT isotonic shrinkage .5)이 design +2.86% → holdout(2015-18, 1회) +4.04%(CI90 상단 −0.00106) → 전체창 +4.08%로 **전이**했고, 장기 손실차 CI90 상단이 두 창 모두 0 미만. B1(대칭 vol 평균회귀)·E11(기간구조 vol)·B2 tilt는 design에서 기각.
- **HOLD인 것**: 봉인창 자체 판정은 위기 국면 요건 미충족으로 보류. 봉인창 안에서 유의한 지평은 h21 하나(p=0.026). **국면 비대칭**이 남아 있다 — pandemic_2020 coverage 0.917(과잉폭), tightening_2022 0.750(과소폭). first_touch Brier는 봉인창 h21 0.082 / h63 0.194로 전체창(0.068/0.166)보다 나쁘다. 방향 적중률은 원장에 있으나 R8-D4로 비공개.
- **추론**: V8이 이긴 상대는 무조건부 historical simulation이며, 이득의 본질은 **폭(width)의 조건부화**다. 2020/2022 비대칭이 V10의 표적이 됐다.

### 4-2. V9 — 외생 거시·유동성 열

가설: 신용·MMF·VXN 정보가 V8 분포를 날카롭게 한다. 검정: E0(V8 비트 항등) 대비 쌍대 CRPS 차이(E−E0, **양수=악화**), 834 원점쌍(417×h21/63), ALFRED first-release PIT, |ρ|>0.85 기각 규칙.

| 실험 | 피처 | 장기 쌍대 | CI90 | 판정 |
|---|---|---|---|---|
| E1 | M2SL | +0.000014 | [−0.000000, +0.000028] | 무효익 |
| E2 | TOTCI | +0.000043 | [+0.000019, +0.000074] | **유의 악화** |
| E3 | TOTLL | +0.000004 | [−0.000002, +0.000009] | 무효익 |
| E4 | WRMFNS | +0.000003 | [−0.000016, +0.000022] | 무효익 |
| E6−E5 | Δlog(VXN/VIX), 서브창 2010-14(260원점) | +0.000006 (+0.019%) | [−0.000008, +0.000021]; 단기 h1+h5 **+1.65%** [+0.000058, +0.000246] 악화 | 채널 폐기 |

**추론**: 쌍대 se 4.0e-06~2.1e-05로 +2%급 효과(≈0.0006)를 볼 검정력이 있었는데 개선 0/5 — **검출 실패가 아니라 측정된 영(null)**. VXN 스프레드는 |ρ|=0.011로 직교인데도 무익 = 순수 노이즈 주입. 주간·월간 first-print 수준 변화는 일간 지수 분포에 추가 정보가 없다. **이 트랙이 '측정된 영'을 기록할 자격이 있었던 이유는 오직 그 se다** — S3의 모든 슬롯이 같은 자격 기준을 충족해야 한다(§11-1(B) 종료 조건 표).

### 4-3. V10 — 국면·γ 가중 분포 계층

가설: vol 상태 조건부 재표집·혼합·블렌드가 2020/2022 비대칭을 고친다. 검정: V8 포크(E0 비트 항등), 상태 = EWMA97 분산비 v_now/v̄(2520), 단독 12개 사전등록, 쌍대(E0−exp, **양수=개선**), stop-loss "12회 후 최고 <+1%".

| 축 | 결과 |
|---|---|
| W1 κ∈{0.5,1.0} | −0.10%/−0.22% 유의 악화, h63 coverage 0.8417 > 밴드 0.84 FAIL |
| W2 3성분 혼합 | coverage 0.85–0.88 과분산 FAIL |
| **W3 γ=−0.10** | **+0.000277 CI90 [+0.000016, +0.000679] = +0.64%** (유일 챔피언, <1% stop-loss) |
| W4a isotonic | +0.000014 [+0.000006, +0.000023] = +0.03% (유의하나 무의미 크기) |
| W5 h5 FHS | −0.000019 [−0.000267, +0.000212] |

6렌즈 적대검증: GFC 78원점(18.7%)이 총델타의 **83.8%** 견인; GFC 제거 시 +0.64%→+0.13%; 상위 5% 원점(21개) 제거 시 평균 −0.0000115("0과 구분 불가" — 절사 CI90이 0 포함); 2008-10~12 클립(w 하한 0.5) 포화 7주가 엣지의 58%. 홀드아웃 게이트(+2% AND CI 상단≤0) 통과 확률 **<2% 추정** → 슬롯 3/3 보존·동결. **정정 기록(V12-D5 종결)**: 조합 격자는 미표집이었고 가법 대리 최상 +1.147% CI90 [+1.07e-04, +9.99e-04]였으나, **적격 12조합 전부** 상위 5% 제거 후 CI90이 0을 포함.

**추론**: vol 수준 상태는 위기에서만 baseline과 달라진다. **이득은 실재하나 위기원점 인공물** — 홀드아웃(2015-18)에는 발화 조건이 없다.

### 4-4. V11 — 평시 직교 상태 신호

가설: 비위기 하위 80% 원점에서 V8 결함(PIT·CRPS)을 예측하는, vol에 직교인 프록시가 있다. 검정: **백테스트 0회**. 판정서는 "9 프록시 × 3 결함지표 × 2 지평 = 54검정"이라 적으나 진단 산출물 실측은 **48검정·프록시 8종(P4 부재)**이다(§9-3 각주, D-13 ①).

- 통과 4 (P9 음성 대조군 미통과): P1 21일 모멘텀→PIT 위치 h21 Δ=−0.120 [−0.192, −0.035](ρ=−0.19); P7 growth factor→CRPS h21 −0.017 [−0.026, −0.008], h63 −0.056 [−0.104, −0.019].
- **표본외 전이**: P1 순방향(2007-10 적합→2011-14) CRPS **+0.97% 악화**(부트스트랩 96% 악화 쪽), 역방향 **+1.49% 악화**. 독립 재계산(3 split × 선형/저모멘텀 tertile × 양방향 = 24셀): 채택 0/12, 순열 p=0.118; 저모멘텀 변형 h63 순방향 +8.1~18.2% 악화.
- 다중검정: 관측 4통과 = 귀무분포 68~75퍼센타일, **P(≥4)=0.25~0.32** `[48/54 기준 미검증]`.
- **미검정 발견(ml-2 심사에서 확인)**: **P4(VRP 프록시)는 검정된 적이 없다** — `orthogonal_diagnostic.py` L151의 `_trailing_z`가 선행 NaN 위 cumsum으로 전량 NaN이 되어 L245 `valid.sum()<30`에서 **무음 제외**됐다. VRP는 미검정이지 미통과가 아니다.

**추론**: in-sample 실재·vol 직교·GFC 강건인 신호도 **2013-14 저변동 tail에만 살고 옮겨가지 않았다**. V10과 다른 실패 모드로 같은 벽. 핵심 교훈: **in-sample 통과·직교·강건 ≠ exploitable**.

### 4-5. V12 — first_touch 재보정 T1–T5, T-A, H3/T-B

가설: V8의 −10% 접촉 확률 상단 과신을 1-파라미터 맵으로 재보정하면 창을 넘어 전이한다. 표적: 지평 내 일간 종가 경로 최소값 ≤ 0.90·S₀, 417 원점, h21 터치 29 / h63 83.

**S2 계측**(기준선 = 반사원리 p=2Φ(ln0.9/(σ√T)), σ=EWMA λ=.97, 자유 파라미터 0):

| h | BS V8 / 반사 / 기후 | BSS(V8\|기후) 쌍대 CI90 | V8−반사 쌍대 CI90 | 상위분위 gap V8 / 반사 | AUC V8 | ρ_s(V8,반사) |
|---|---|---|---|---|---|---|
| 21 | 0.061485 / 0.060135 / 0.064708 | +4.98%, [−0.011884, +0.020559] | −0.001350 [−0.006668, +0.002511] | +0.1230 [−0.0097, +0.2394] / +0.1232 [+0.0078, +0.2233] | 0.8054 [0.6315, 0.9039] | **0.9514** |
| 63 | 0.144973 / 0.149889 / 0.159424 | +9.06%, [−0.022054, +0.057643] | +0.004917 [−0.001855, +0.010982] | +0.2107 [+0.0355, +0.3817] / +0.2417 [+0.0654, +0.4069] | 0.7325 [0.5713, 0.8513] | **0.9126** |

2000경로 DFM-VARX 앙상블의 접촉 확률은 **EWMA σ 하나의 단조 변환과 통계적으로 구분되지 않는다.** 판별력(AUC)만 CI90으로 지지되고, 그 77~83%는 σ가 만든다. BGK 이산 모니터링 보정(β=0.5826)은 **기준선** 과신을 h21 45%·h63 20% 줄이지만 V8은 이미 일간 종가로 판정하므로 V8 과신의 설명이 아니다.

**S3 사전등록 검정**(커밋 `ec496463`): **채택 0/8, 16방향 중 하한>0 0개**(하한<0 10, 하한=0 6). T3 전→후는 CI90 상한<0(h21 −0.000010, h63 −0.000123) — 악화. T4는 단조 위반 0건 — 무비용·무효과. |Δ|<MDE 9/16. **T5 실패**: p-순열 귀무 아래 T1 통과율 pooled **0.254 > 0.10**, 귀무 평균 통과 셀 2.764.

**T-A 수리 시도(NOT_REPAIRED)**: N-p-block **0.201**, N-y-block 0.000, N-blk-pair 0.000. 해석(외부 검토 재현 (361+41)/2000=0.201): T1의 이득은 p→y 관계가 아니라 **창의 y 평균으로의 수축(calibration-in-the-large)**. p-순열 귀무는 계약으로 금지(`p_permutation_null_as_negative_control: true`).

**H3/T-B**: 과신의 주인을 상수-σ i.i.d. FHS 경로 생성기로 좁혔고, 그 크기는 ACF(1)=−0.076, φ̂=−0.053, VR(5)=0.874, VR(21)=0.919, VR(63)=1.044 — 방향 확증, 크기 온건 → **보류(파킹)**, 재개 조건 4항.

**추론**: 종점 분포(CRPS)가 맞아도 경로 의존 사건 확률은 틀릴 수 있고, 그 오차는 1-파라미터 맵으로 옮겨지지 않는다. 표적 고유성 주장은 `[미검증]`으로 강등.

### 4-6. V13-VOL — HAR/EWMA vs 지속성

| rung | 대조 | 결과 (9셀 = {vix25, vix30, rv} × {h5, h21, h63}) |
|---|---|---|
| 1 EWMA-logit | 기후 | 9/9 양방향 CI90>0, BSS e2l +0.094~+0.898, 건전 y-block 귀무 0.000~0.017 — **캠페인 첫 긍정** |
| 2 HAR-logistic | EWMA | 기후 대비 9/9, **EWMA 대비 증분 0/9** (vix25_h63 l2e −0.00388 [−0.00697, −0.00090]; rv_h5 l2e −0.00246 [−0.00516, −0.00013]). GARCH-t moot(`arch` 미설치) |
| 3 PB = logit(당일 수준 1피처) | EWMA | **EWMA가 PB를 양방향으로 이긴 셀 0/9**, \|EWMA−PB\| ≤0.008, 한 방향 유의 열위 2셀. PB 기후 대비 9/9, 귀무 ≤0.033 → **champion = persistence_pb 전 9셀** |

h63 cross-fit isotonic은 사전등록 fallback 발동(iso 유의 열위, vix30_h63 e2l rel 0.081→0.239) → raw 유지. reliability h5 rel≈0.002(양호)·h63 rel≈0.08(오보정). 기후 기저율(설계창, GFC 포함): K25 h5/h21/h63 = 0.308/0.420/0.608, K30 = 0.178/0.252/0.407, RV>θ = 0.552/0.676/0.875.

**추론**: **스킬 = "당일 변동성 수준의 지속"**. 문헌과 정합(Poon & Granger (2003); Andersen et al. (2003); Hansen & Lunde (2005)). 가치는 EXIT 트리거 base rate 공급이지 시장 엣지가 아니다.

### 4-7. '일간 종가 정보집합의 벽' 명제 — 무엇을 말하고 무엇을 말하지 않나

**성립하는 진술**: **NASDAQ Composite 일간 종가 정보집합**(수익률·VIX 종가·DGS2·커브·달러 + DFM 성장/물가 팩터 + 주간/월간 first-print) 위에서, **표적 = h21/h63 CRPS 분포와 −10% first-passage 확률**, **창 = 2007-2014**, **판정 = 양방향 전이**일 때, (a) 외생 열 추가, (b) vol 상태 조건부 분포 계층, (c) 평시 직교 상태, (d) 이벤트 확률 재보정 **네 각도가 모두 표본외 개선을 내지 못했다.** 이것이 같은 잡음의 재측정이 아니라는 증거는 세 트랙 origin별 Δ 상관이 **|r| ≤ 0.154**로 직교하다는 점 — **서로 다른 실패**다. 남은 실재 스킬은 변동성 지속성뿐이며, 이는 Christoffersen & Diebold (2006)과 정합한다. 문헌 사전확률도 같은 쪽(Welch & Goyal (2008); Campbell & Thompson (2008)).

**성립하지 않는 진술** — 검토관은 이 네 줄을 넘는 문장을 팩 안에서 찾아야 한다:

1. "일간 NASDAQ에 정보가 없다." **아니다** — V8은 historical simulation을 +3.96%/+4.21%로 이긴다.
2. "재보정이 원리상 불가능하다." **아니다** — 등록된 네 맵(T1~T4)과 이 검정 절차만 부정됐다.
3. "2015+에 대한 주장." **없다** — 홀드아웃·봉인은 미열람이다(V8 봉인 1회 제외).
4. "축 곱공간까지 소진." **아니다** — V10 조합 격자는 미표집이었고(사후 정정), 다만 적격 12조합 전부가 상위 5% 제거 후 CI90 하한 음수라 **기대는 낮다**.

**벽은 정보집합 × 표적 × 창 × 계보의 벽이다.** 단독 축이 소진됐을 뿐이고, 일중·옵션 정보집합은 **합법 소스가 실재하나 미검증**이다(외부 검토 보정 ①). 그리고 V13이 보여준 것은 **표적을 바꾸면 판정이 달라질 수 있다**는 것이지 **정보가 새로 생긴다**는 것이 아니다(외부 검토 보정 ②) — S3-a가 정확히 이 경계에 서 있다.

---

## 5. 고도화 전략 방향 — 순위표 + 방향 카드

> **반대증거(데블스 애드버킷) 고지**: 이 절의 모든 카드에는 심판의 **회의론자 지적**이 붙어 있고, 그 지적은 전부 저장소 실측 또는 문헌 오적용 확인에서 나왔다. 카드의 '기대효과'는 **설계자 자기 사전확률(주관)**이며 저장소 산출값이 아니다. 반대증거 없는 카드는 §11-4 규약상 무효다.

### 5-1. 심판 순위표 (23개)

원안은 24개(`directions.json`: infoset-1~8, classical-1~8, ml-1~8)였고 **`classical-7`(log-VIX 평균회귀·점프 첫통과 모형)은 순위표에서 드롭**됐다 — 사유: 진단 전제 반증 + 클래스 상한(오라클 전이 rel **0.083~0.165**) > 목표 0.04.

| 순위 | id | 방향 | 점수 | 단계 | 게이트(요지) | 전제(승인·선행) |
|---|---|---|---|---|---|---|
| 1 | `infoset-1` | VIX 기간구조·VVIX·SKEW → V13 셀 PB 대비 증분 | **78** | **S3-a 1순위** (신규 ID `event_probability.volatility_v14_shape`) | 양방향 쌍대 Brier(PB−후보) ℓ=13·B=2000·CI90 하한>0 ∧ y-block ≤0.10 ∧ BH q=0.10 ∧ MDE 병기 | 승인/구매 0. 선행 수정 3건(vix30 3셀 사전 퇴화 선언 / V4 `first_publication_date` 가드 / 새 계약 ID) |
| 2 | `infoset-3` | 발표 캘린더 + 통화정책 서프라이즈 → 발표창 조건부 | **75** | **S3-b 2순위** | 위 + **캘린더 라벨 블록 순열** 보수 귀무 병기 ∧ h63 영효과 부정 대조 사전등록 | 승인/구매 0. 정례 FOMC만·의사록 공표시각 정렬·D-5 판정·주효과를 rv 셀로 재지정 |
| 3 | `ml-6` | MDD 깊이 분포 회귀(최소 CRPS) + 브라운 MDD 기준선 | **74** | **S3-c 3순위** | 쌍대 CRPS(이산 MDD 기준선−후보) ∧ (V8 경험 MDD−후보) 양방향 ∧ 꼬리가중 CRPS 병기(둘 다 통과 시에만) ∧ 상위5% 부호 유지 ∧ Holm | 승인/구매 0. 이산 모니터링 MC 기준선 교체·라벨 정의 명기·h63 파라미터 2~3 |
| 4 | `ml-1` | 옵션내재 형상 → V13 rung-4 ridge-logit | **72** | **S3-a 병합**(별도 예산 금지) | infoset-1 + 셀별 {PB, EWMA, HAR, rung4} **MCS(α=0.10)** | 새 계약 ID·예산 산술 정정·rung-5 조건부 |
| 5 | `classical-1` | 위 + **VIX 일중범위**(OHLC) | **71** | **S3-a 병합**(범위 피처만 단독 ablation 1슬롯) | infoset-1 + 범위 피처는 **h5 셀 한정** 사전등록 | VIX OHLC 재파싱은 새 원장에만·개장 인쇄 인공물·2014-10 방법론 변경 caveat |
| 6 | `infoset-2` | QQQ 옵션 표면(CBOE EOD) → 리스크중립 꼬리·VRP | **69** | **S6-a**(S3-a 조건부) | 표적 재설계 후 V13 셀 양방향 ∧ y-block ∧ BH/RW. **first-passage 갈래는 base rate로 강등** | 사용자 결정 2건(V12-D4 발송·구매) + **S3-a 선행**. 새 등급 `vendor_eod_archive`, 2019+ 절단, §2b 회신 전 T2/T3 금지 |
| 7 | `ml-2` | 위 + V13 셀 병행(표적 B) | **68** | **S6-a 병합** | 표적 B 우선: 쌍대 Brier vs PB 양방향 ∧ y-block ∧ BH. 표적 A는 MDE 공표 후 base rate만 | infoset-2 + **V11 P4 미검정 사실 정정 기재** + V13 문서 54→48 정정 |
| 8 | `infoset-4` | 일중 실현측도(FirstRate) → 세미분산·점프·overnight + V12b | **65** | **S6-b**((b) 팔은 S3-d 분리) | (a) rv 셀 vs [RV21, **VIX_t**] 중첩 기준선 양방향 ∧ y-block ∧ BH. (b) E0 항등 ∧ CRPS 무손상 | FR-1 — 단 **S3-d와 rv 셀 VIX_t 스크린($0)을 먼저**. 무료 2주 샘플 선검증 |
| 9 | `classical-4` | 옵션 표면 → 가격 꼬리 사건·V13 | **63** | **S6-a 병합** | **BGK 이산보정판을 구속 기준선으로 결과 전 고정** + 무구매 rung 통과 시에만 구매 rung | infoset-2 + stop-loss를 물리측도 변환 후로 재명세 + H4a 강등 |
| 10 | `ml-5` | 일중 → V12b 재개 + RS⁻·점프 | **62** | **S3-d((b), $0) + S6-b((a))로 분할** | (b) 경로 법칙 자체를 proper scoring rule로 채점 ∧ CRPS 무손상. (a) rv 셀 양방향 | (b)는 승인·구매 0(**사용자 판정 1건**: 파킹 문서 vs 취득계획 모순). MCS 신규 코드 |
| 11 | `classical-5` | 꼬리 표적·꼬리 손실 재채점 + EVT/CAViaR | **61** | **S3-e**(H5a만), H5b 재설계 | H5a: 판정 다리 아님 — 쌍대 CI90 보고(T1 종료). H5b: h21 × {좌측 가중 CRPS, pinball .05, FZ0} | 비교값을 **design E10(+3.02%/+2.71%)**으로 고정, τ=0.01·ES5·h63·Christoffersen 판정 제외 |
| 12 | `classical-6` | 일중 → V13 rv/vix 셀 + T-B | **60** | **S6-b 병합** | infoset-4 + σ 교체와 T-B 재개를 **별개 가설로 분리** | FR-1 + $0 선행 rung 2종. σ 교체 팔은 **E11 선례** 명기·기대 하향 |
| 13 | `infoset-6` | 이산시간 hazard/survival 다중 배리어·드로다운 | **58** | **S3-c 병합**(깊이 팔만; hazard·−10%/−15% 보류) | −5% 배리어 + 깊이 CRPS만, 사건수·MDE 결과 전 인쇄 | 승인 1건(V12 reopen 관계). 공변량 d 삭제 또는 배리어 재정의, hazard→랜드마크 직접 로짓 |
| 14 | `ml-3` | 발표 캘린더 → 발표일 조건부 FHS 스케일 + V13 h5 | **56** | **S3-b 병합** | **h1 종점 폐기.** 발표 포함 원점 부분집합 조건부 쌍대 CRPS + LR_cc(판정 아님) | 승수를 분산 보존형으로, scheduled/unscheduled 필드 신설 |
| 15 | `infoset-8` | FOMC 텍스트 결정론 사전 + EDGAR 8-K 밀도 | **55** | **S3-f**(재설계 선행) | 전 일간 패널 계단 공변량 재구성 시 블록길이 재사전등록 ∧ 사전 검정력 계획 공표 | 거래소 필터 삭제(전체 filer/SIC), 중앙은행 특화 사전, EPU 설계창 제외 |
| 16 | `classical-3` | 예정 매크로 발표 → 분산 승수 + V13 h5 | **53** | **S3-b 병합** | H3b(h5 count 더미) 1슬롯만, **부호 무관**·y-block·BH. H3a는 진단으로 강등 | h1 다리 삭제, 승수 prior를 주식지수 문헌값(1.1~1.3)으로 |
| 17 | `ml-7` | ACI conformal 래퍼 | **52** | **S5-b**(판정 트랙 아님) | 쌍대 interval(Winkler) score CI90 하한 ≥0 무손상 + 장기 주변 커버리지. LR_cc는 표시 지표 | 동기를 dev-창 증거로 재작성(`disclosure_caveat` 저촉), 68세션 지연 점화식 재정식화, ML 게이트 저촉 사용자 판정 |
| 18 | `ml-4` | 교차자산 동조 국면 이벤트 | **51** | **S3-g** 또는 보류 | 부호 규약 정정 후 **min(사건, 비사건) ≥20 양 반창** 가드 통과 셀만 등록 | 부호 규약 재정의 + '2022 국면을 알고 표적을 정했다' 정점지식 caveat, 지수 하나로 고정 |
| 19 | `infoset-5` | CFTC TFF 순포지션 → 변동성 급등·드로다운 | **49** | **S3-h 인프라만** | 설계창을 2010-07-20 이후로 재정의, 양방향 포기 시 대체 검정 결과 전 등록 | **사용자 결정 1건**(D0 `model_use` 승격). 2010-12-03 절벽 반영, 등급 `reconstructed_with_2010_vintage_classifications` |
| 20 | `classical-2` | 주식-채권 상관 국면 — '채권 헤지 실패' | **47** | **S3-g 병합** 또는 보류 | ml-4와 동일 | 표적 통계량을 ρ̂63/필터 상관으로, 임계를 학습창 분위로, 사전 검정력 계획 선등록 |
| 21 | `classical-8` | 주간 포지셔닝 → 월간 드로다운 | **46** | **S3-h 병합**(인프라만) | 사전진단에서 사건수·MDE 공표 → **사건 0이면 사전 제외 규칙**(사후 stop-loss 아님) | infoset-5 + h21 셀 삭제(사건 7), 임계 −5% 또는 변동성 사건으로 이전, 신규성 문구 정정 |
| 22 | `infoset-7` | 교차자산 꼬리 의존(copula λ_L) | **42** | **보류**(재설계 시 S3-g 흡수) | χ̄ 점근독립 진단을 1단계로 두고 '점근독립 판정 자체가 산출물'인 경로를 미리 열 것 | COMP–NDX·SOX 쌍 폐기, 롤링 MLE→동적/모형자유, 부정 대조를 ρ̂ 직교화 잔차로 |
| 23 | `ml-8` | Chronos-2 zero-shot → V13 챌린저 | **40** | **보류**(현 사양 실행 불가) | 실행 가능해질 경우: 반창별 쌍대 Brier CI90 ∧ y-block ∧ BH, T0 상한·오염 caveat 상시 | **사용자 결정 1건**(§8 예외의 사전학습 TSFM 적용). N≥400~1000, 체크포인트 sha·라이선스 영수증 |
| — | `classical-7` | log-VIX 평균회귀·점프 첫통과 모형 | **드롭** | — | — | 진단 전제 반증 + 오라클 전이 rel 0.083~0.165 > 목표 0.04 |

### 5-2. 상위 10개 상세 카드

---

#### **카드 1 — `infoset-1` (78점) · S3-a 1순위**

- **가설**: 조건 시점의 VIX 기간구조 기울기 ln(VIX/VIX3M)·ln(VIX9D/VIX), VVIX(vol-of-vol), SKEW(리스크중립 왜도)를 '당일 VIX 수준 단독' 로짓(PB, V13 champion)에 **중첩 추가**하면 P(VIX≥K within h)의 쌍대 Brier가 PB 대비 early↔late 양방향 CI90 하한>0으로 개선된다. 반증 조건: 9셀×4피처 중 양방향 채택 0, 또는 y-block 귀무 통과율 >0.10.
- **정보집합**: 옵션 시장의 만기 간 IV 구조(9일/30일/3개월)·vol-of-vol·행사가 비대칭. **일간 종가 정보집합에는 없다** — V13 계약 `data_policy.series=[VIX, NASDAQCOM]` 실측 확인.
- **방법**: V13 사다리와 동일 적합기(`timeseries_v13/features.py::logit_fit`: zscore ddof0·Newton 200·l2 1e-3)로 중첩 로짓 PB ⊂ PB+{slope} ⊂ PB+{slope, VVIX, SKEW}. 단독 ablation 4 + 사전등록 조합 1. 표적·K·θ·h는 V13 계약 고정값 재사용(새 표적 추가 없음). 파생 isotonic 없음(raw 확률로 판정).
- **논문**: Johnson (2017) 'Risk Premia and the VIX Term Structure', JFQA `[미검증: 권·호]` · Mixon (2007) 'The Implied Volatility Term Structure of Stock Index Options', J. Empirical Finance · Huang, Schlag, Shaliastovich & Thimme (2019) 'Volatility-of-Volatility Risk', JFQA · Bekaert & Hoerova (2014) 'The VIX, the Variance Premium and Stock Market Volatility', J. Econometrics · Christensen & Prabhala (1998) 'The Relation between Implied and Realized Volatility', JFE.
- **데이터·라이선스**: V4 스토어(기보유, $0) — SKEW 9,210행(1990-01-02~), VVIX 5,087행(2006-03-06~), VIX3M 4,256행(2009-09-18~), VIX9D 3,930행(2011-01-04~). 등급 `reconstructed_market_archive`(native PIT 아님 명기). **CBOE는 12-1/12-5 회색지대** — 내부 연구는 기존 판정 범위, 라이브 표시는 `cboe_permission_request_draft` 발송 후.
- **거버넌스 적합성**: 결정론 로짓의 design 창 적합·워크포워드(§8 예외) — 산출은 base rate 참조. ML 게이트 무관(자유도 소). 홀드아웃·봉인 무접촉. **V13 계약 개정이 아니라 새 계약 ID** — 계수 3자 핀을 건드리면 `read_model_contract.py`의 `coefficients_pinned` 가드가 T3 카드를 HOLD로 fail-close한다.
- **검정 프로토콜**: 양방향(early 2007-10 ↔ late 2011-14) 쌍대 Brier(PB − 후보), stationary block bootstrap ℓ=13·B=2000, CI90 하한>0 **양방향** ∧ y-block(ℓ=13) 귀무 ≤0.10(p-순열 금지) ∧ BH q=0.10(family = **퇴화 가드 통과 셀만**) ∧ MDE 병기.
- **기대효과**(설계자 자기 사전, 주관): vix25/30 h5·h21 셀 BSS(vs PB) +1~4%p, h63 ≈0, rv 셀 ≈0. 최소 1셀 양방향 채택 확률 30~40%. **검정력 확보 근거**: `ladder_pb_baseline.json` 실측 `ewma_vs_pb` MDE vix25_h21 0.001715/0.003289(Brier 0.0874/0.1335 = 1.96%/2.46% BSS).
- **비용**: 데이터 $0 · 계산 노트북급(로짓 45개×부트 2000 ≈ 수십 분) · 엔지니어링 3~5일.
- **단계**: S3-a(0원 스크린) → 채택 셀 발생 시에만 S4.
- **왜 기존 반증을 우회하는가**: V4는 같은 지수를 **가격 분포 CRPS 표적**의 event-state 성분으로 넣어 HOLD였고 단독 ablation이 없었다. V13 rung-1~3은 VIX·NASDAQCOM 두 계열만 썼다. V11 P4는 평시 서브샘플·V8 결함 표적이라 표본·표적이 모두 다르다(게다가 §4-4대로 **무음 제외되어 미검정**이다).
- **회의론자 지적(심판)**: ① **VIX3M 서브창 late leg(2012-04~2014-12, 692세션)은 VIX≥30이 0일·≥25가 5일(2에피소드)** — vix30 3셀은 양방향 판정이 구성상 불가능하고 y-block 귀무가 퇴화한다(거짓 PASS 경로). ② **V4 스토어 `available_at`이 합성**(SKEW 1990-01-02T21:15Z)인데 실제 지수 공표는 SKEW ~2011-02·VVIX ~2012 — `first_publication_date` 가드 없이는 계약 자신의 `available_at_must_not_exceed_origin`을 문언상 위반한다. ③ 문헌 사전확률 하향: Johnson (2017)의 slope는 **P-측도 VIX 경로가 아니라 분산위험 프리미엄을 전달**한다. ④ **선례 고지 의무**(§7-1 V4 행): V4/V5 hold + V9 E5/E6 무효익을 사전등록 서두에 인용하고 "새로움은 표적 교체에만 있고 정보집합에는 없다"는 비대칭을 명문화할 것.

---

#### **카드 2 — `infoset-3` (75점) · S3-b 2순위**

- **가설**: 예정 발표(FOMC·CPI·NFP)의 **타이밍**이 발표창을 포함하는 지평의 변동성 이벤트 확률을 PB 대비 개선한다.
- **정보집합**: 발표 **시점**(수준이 아니라). V9가 시험한 것은 거시 '수준'(M2SL·TOTCI·TOTLL·WRMFNS)이고 '시점'은 V1~V13 어디에도 없다.
- **방법**: V13 일간 패널(n≈2,014)에 계단형 캘린더 공변량을 중첩 로짓으로 추가. 원점 격자는 V13 패널을 그대로 써서 V8 주간 원점 함정을 구조적으로 회피.
- **논문**: Savor & Wilson (2013) 'How Much Do Investors Care About Macroeconomic Risk?', JFQA · Andersen, Bollerslev, Diebold & Vega (2003) 'Micro Effects of Macro Announcements', AER · Lucca & Moench (2015) 'The Pre-FOMC Announcement Drift', JF · Giannone, Reichlin & Small (2008) 'Nowcasting', JME.
- **데이터·라이선스**: **PIT 등급 전 후보 중 최고** — CPI/NFP 발표일은 `data/timeseries/facts/observations.parquet`의 vintage `realtime_start` 그 자체(2008년 12개월 전수 대사 완료), FOMC 일정은 연방정부 저작물. `data/calendar/events.csv` 53건 + `calendar_sources.yaml`(`confirmed_definition: institution_or_issuer_published_date`). $0·신규 수집 0.
- **거버넌스 적합성**: native PIT·결정론·홀드아웃 무접촉. 단 `calendar_sources.yaml` L4 `policy.probability_linkage: forbidden`의 **적용 범위가 D-5 미결** — 착수 전 명문 개정 권고.
- **검정 프로토콜**: V13 9셀 쌍대 Brier vs PB, ℓ=13·B=2000·CI90 하한>0 양방향 ∧ y-block ≤0.10 **+ 캘린더 라벨 블록 순열(y 고정) 보수 귀무 ≤0.10 병기** ∧ Holm/BH q=0.10 ∧ **h63 영효과를 부정 대조로 사전 등록**.
- **기대효과**(자기 사전): h5 셀 BSS(vs PB) +2~5%p, h21 +0~2%p, h63 ≈0. h5 ≥1 채택 확률 40~50%.
- **비용**: $0 · 계산 소 · 엔지니어링 3~4일.
- **단계**: S3-b. `ml-3`(56)·`classical-3`(53) 흡수.
- **왜 기존 반증을 우회하는가**: V9의 무효익은 '수준'의 결론, V3~V5의 event 성분은 앙상블 내부 요소로 단독 ablation 없음, V8~V13은 캘린더를 전혀 쓰지 않았다.
- **회의론자 지적(심판)**: ① **효과크기 사전확률이 약하다** — Savor & Wilson의 11.4bp vs 1.1bp는 **Sharpe가 10배**라는 것이므로 변동성 비율은 ≈1.04이고, warmup 창(1997–2006) z² 실측도 **NFP 1.18·CPI 1.07**이다. ② **VIX는 30일 전향 내재변동성이라 h5·h21 창의 예정 이벤트를 이미 가격에 담고 있어** vix 셀에서 캘린더는 정의상 기준선 안에 있다 — **진짜 미가격 셀은 후행 RV21을 쓰는 rv 3셀**이다(주효과 셀을 rv_h5/rv_h21로 재지정할 것). ③ **2007–2008 비정례 FOMC 6건이 전부 직전 5세션에 VIX≥25가 이미 터진 창 안**(29.99/31.01/32.24/57.53/28.84/35.06)이라 최종 캘린더 backfill은 위기 구간에 **100% 룩어헤드**를 주입한다 — 정례만 사용 + 비정례 6건 제외를 결과 전 명문화. ④ 의사록은 공표 시각 정렬 필수(결정 3주 후 ≈ h21 지평이라 회의일 정렬 시 완전 누수).

---

#### **카드 3 — `ml-6` (74점) · S3-c 3순위**

- **가설**: −10% 이진 표적 대신 **최대 드로다운 깊이를 연속 표적**으로 두면 417 원점 전부가 정보를 실어 CRPS로 채점되므로, 같은 정보집합에서도 판정 가능한 검정이 만들어진다.
- **정보집합**: 신규 없음(표적·손실의 전환). 옵션 형상 피처를 얹는 갈래는 조건부.
- **방법**: 최소 CRPS 추정 EMOS 급 분포 회귀(location-scale), 자유도 ≤10(h63은 2~3), 해석 기준선은 브라운 MDD 분포 → **이산 모니터링 몬테카를로 판으로 교체**(자유 파라미터 0 유지).
- **논문**: Magdon-Ismail, Atiya, Pratap & Abu-Mostafa (2004)(§6-6) · Gneiting, Raftery, Westveld & Goldman (2005) 'Calibrated Probabilistic Forecasting Using Ensemble Model Output Statistics and Minimum CRPS Estimation', Monthly Weather Review · Rigby & Stasinopoulos (2005) 'Generalized Additive Models for Location, Scale and Shape', JRSS-C · Chekhlov, Uryasev & Zabarankin (2005)(§6-6) · Gneiting & Ranjan (2011)(§6-4).
- **데이터·라이선스**: $0(V8 동결 코드 read-only 재실행).
- **거버넌스 적합성**: **EXIT 정합성 최고 수준** — 사용자의 드로다운 하드룰이 사는 곳이 정확히 여기이고, 산출은 룰의 대체가 아니라 **조기경보 base rate**다. 학습 자유도 ≤10이라 ML 게이트 무관.
- **검정 프로토콜**: 쌍대 CRPS(이산 모니터링 MDD 기준선 − 후보) **및** (V8 경험 MDD − 후보) 양방향 CI90 하한>0 ∧ 꼬리가중 CRPS 동일 형식 병기(**둘 다 통과 시에만 채택**) ∧ y-block ≤0.10 ∧ 상위5% 원점 제거 부호 유지 ∧ Holm.
- **기대효과**(자기 사전): 표적 전환 단독(피처=σ만)은 브라운 기준선과 거의 동률. 옵션 형상 피처가 더해질 때 h63 CRPS +2~5%, h21 +0~2%. 통과 확률 25~35%.
- **비용**: $0 · 엔지니어링 3~5일 · 컴퓨트 수십 분. **단 dev 예산 1회로 계상**해야 한다(아래 지적 ④).
- **단계**: S3-c. `infoset-6`(58) 깊이 팔 흡수.
- **왜 기존 반증을 우회하는가**: V12는 이진 −10% 접촉의 1-파라미터 재보정만 검정했고 사건 29/83건의 검정력 한계·p-순열 누수로 끝났다. 연속 MDD 표적은 미시험이고, 꼬리 가중 손실도 미시험이다.
- **회의론자 지적(심판)**: ① **정보집합이 새롭지 않다** — 옵션 형상 피처를 얹는 갈래는 V3→V4 동일 963원점·동일 baseline_crps 실측에서 h21 +0.746%→**+0.288%**, h63 +2.025%→**+1.695%**로 **오히려 나빠진 선례**가 있다. ② **연속시간 브라운 MDD 기준선은 일간 종가 그리드보다 드로다운을 과대추정**하므로 후보가 이산화 편향만으로 통과할 수 있다 — V12 S2-2가 BGK 보정(β=0.5826)으로 gap을 h21 −45%·h63 −20% 줄인 그 함정이다. ③ Kelly & Jiang (2014) 인용은 **오적용**(개별종목 횡단면 Hill 추정치이며 저장소엔 PIT 구성종목이 없다). ④ **'V8 원장 재분석 = 0 백테스트'는 성립 불가** — 원장에 경로가 없어 동결 코드 read-only 재실행이 필요하다. ⑤ P(MDD≥10%)와 V8 first_touch는 **라벨이 다른 사건**(러닝맥스 대비 vs 원점 대비)이므로 계약에 명기하고 판정 다리에서 제외할 것.

---

#### **카드 4 — `ml-1` (72점) · S3-a 병합**

- **가설·정보집합·방법**: `infoset-1`과 실질 동일. 차이는 **검정 위생**이 가장 촘촘하다는 점(사다리 통합·MCS·BH).
- **논문**: Johnson (2017); Park (2015) `[미검증: 서지]`; §6-3 표 참조.
- **상관 스크린 실측 지지**: 설계창 corr(log VIX, feature) = **SKEW −0.466 · log VVIX +0.379 · log(VIX/VIX3M) +0.574** — V9의 |ρ|>0.85 기각선 아래라 "수준의 단조변환일 뿐"이라는 반박은 성립하지 않는다.
- **검정 프로토콜**: infoset-1과 동일 + 셀별 {PB, EWMA, HAR, rung4} **Model Confidence Set(Hansen, Lunde & Nason (2011), α=0.10)** 보고. MCS는 **저장소 미구현**이라 신규 코드 + 결과 전 커밋, 공수 산정에 포함.
- **기대효과**(자기 사전): h21/h63 vix 셀 BSS +0.01~+0.05, h5 ≈0, rv ≈0 `[필자 사전확률, 미검증]`. ≥1셀 양방향 통과(FDR 후) 30~40%.
- **비용**: $0 · 로컬 CPU 수십 분 · 엔지니어링 2~3일.
- **회의론자 지적(심판)**: ① **예산 산술 오류** — V13 `evaluations_spent` 3/8에 rung-4 A/B 2 + rung-5 1을 더하면 **6/8**이지 '최대 5/8'이 아니다. 무엇보다 V13은 champion 확정·계수 동결·T3 라이브 상태라 rung 추가는 **계약 개정이 아니라 새 계약 ID**여야 한다. ② rung-5 HGB(monotonic_cst)는 이 표본에서 정보를 더하지 못할 개연이 높은데(V13 rung-2/3가 이미 richer 모형 증분 0/9) **다중검정 family만 키운다** — rung-4 통과 셀이 있을 때만 조건부 등록. ③ infoset-1과 동일한 VIX3M 서브창 퇴화·소급 산출 PIT 결함을 공유한다. ④ **세 중복 방향(infoset-1·ml-1·classical-1)은 하나의 사전등록으로 병합하는 것이 예산·family 양쪽에서 옳다.**

---

#### **카드 5 — `classical-1` (71점) · S3-a 병합(범위 피처 단독 ablation 1슬롯)**

- **추가되는 것**: VIX **일중 고가·저가**에서 만든 범위 피처 ln(High/Low), (High−Close)/Close. **세 중복 방향 중 유일한 진짜 추가분**이며 '종가는 도달했으나 종가는 미달' 경로 정보를 담아 vix 셀에 개념적으로 정합하다.
- **데이터**: `data/timeseries_v2/raw/market/cboe_vix_archive/*.gz` **13파일**이 DATE·OPEN·HIGH·LOW·CLOSE를 담고 있고 현 파서(`market_archive.py` L182)는 **CLOSE만 읽는다** → 새 파서·새 원장은 **봉인 바이트 무접촉**. (행수 9,259·설계창 zero-range 0일은 **검토용 진단, 원장 미기록** — 산출 스크립트 경로를 사전등록 부록에 첨부. 1990~1991 OHLC 결측 여부는 `[미검증]`.)
- **논문**: Parkinson (1980) 'The Extreme Value Method for Estimating the Variance of the Rate of Return', J. Business; Garman & Klass (1980) `[전이 미검증]`.
- **검정 프로토콜**: infoset-1과 동일 + **범위 피처는 h5 셀 한정 사전등록**(단기 집중 사전확률).
- **기대효과**(자기 사전): h5 ≈0(PB 포화, |EWMA−PB| ≤0.008), h21/h63 vix 셀 기간구조 +1~4%p, VVIX·SKEW +0~2%p, 범위는 h5에서만 소폭. ≥1셀 통과 30~35%.
- **회의론자 지적(심판)**: ① **Parkinson (1980)은 거래자산 로그가격 확산의 분산추정 효율 결과**라 VIX(지수) 임계 접촉 예측 근거로는 휴리스틱이다. ② VIX 일중 고가의 **개장 직후 stale-quote 스파이크**와 **2014-10-06 weeklys 방법론 변경**(이력 미재산출 여부 `[미검증]`)이 late 서브창 2에피소드 중 하나에 걸린다. ③ 서브창 퇴화·PIT 소급 결함은 형제 방향과 동일. ④ **CBOE 발자국이 4지수+OHLC 파생으로 가장 넓어져 12-1 회색지대 노출이 가장 크다** — 파생값 표시 확대는 소유자 회신 후.

---

#### **카드 6 — `infoset-2` (69점) · S6-a(S3-a 조건부)**

- **가설**: 행사가 차원의 리스크중립 꼬리(BL 밀도·25Δ 스큐·좌측 꼬리 지수)와 VRP가 가격 꼬리 사건·변동성 이벤트에 σ 밖의 정보를 준다.
- **정보집합**: **전 후보 중 최고 신규성** — 행사가 차원은 V1~V13 어디에도 없고, 외부 검토가 '유일한 미검증 정보집합'으로 지목했다.
- **방법**: EOD 체인 → 무차익 필터 → MFIV/BKM 적률 → BL 밀도(**de-Americanization 단계를 결과 전 고정** — QQQ는 미국형) → V13 셀 중첩 로짓 + (강등된) first-passage base rate.
- **논문**: Bollerslev, Tauchen & Zhou (2009); Bollerslev & Todorov (2011); Bollerslev, Todorov & Xu (2015); Jiang & Tian (2005); Britten-Jones & Neuberger (2000); Bakshi, Kapadia & Madan (2003); Breeden & Litzenberger (1978) — 전부 §6-3.
- **데이터·라이선스**: CBOE DataShop / LiveVol QQQ EOD(2004+). Subscriber Agreement §1 내부연구 허용, **§2b 파생 표시 조건부**(소유자 원문 재확인 필요). 비용 EOD $500/월, 일중 애드혹 $1.5–2.5k/월, 구독 $5–6k/월, **일회 이력가 `[미검증]`**. 새 등급 `vendor_eod_archive` 신설 필요 + `reconstructed_archive_is_native_pit: false`에 상응하는 자기부정 필드(§11-1(D)).
- **거버넌스 적합성**: **2019+ 바이트 패널 절단**(`sealed_2019_access_during_development`), §2b 회신 전 T2/T3 진입 금지, risk-neutral 측도·QQQ 이중 프록시 병기(^IXIC→QQQ, ETF 배당·조기행사 caveat).
- **검정 프로토콜**: 표적 재설계 후 V13 셀 쌍대 Brier vs PB 양방향 CI90 하한>0 ∧ y-block ≤0.10 ∧ BH q=0.10 또는 Romano–Wolf. **first-passage 갈래는 채택 게이트가 아니라 base rate 산출(T0/T1)로 강등.**
- **기대효과**(자기 사전): h63·−10% BSS +2~6%p, h21은 MDE 미달 가능성. 채택 확률 35~45%.
- **비용**: $500~수천 · 계산 중 · 엔지니어링 10~15일 · 리드타임 회신 ~5영업일.
- **왜 기존 반증을 우회하는가**: V12 S2가 V8 접촉확률이 **EWMA σ의 단조변환과 구분되지 않음**(ρ_s 0.9514/0.9126)을 보였으므로 'σ 밖의 정보'가 정확히 이 방향의 검정 대상이다.
- **회의론자 지적(심판)**: ① **검정력이 상위권 진입을 막는다** — `s3_split_power` 실측 h21 late **7건**·h63 late 24건이고, V12_S2_2가 계산한 반사원리 기준선 극복 문턱은 기후 대비 BSS **h21 ≥+14.28%(BGK판 +21.12%)·h63 ≥+10.18%(+15.08%)**인데 이 방향의 기대는 h63 +2~6%p·h21 +0~3%p — **요구 마진의 1/3~1/7**이라 정보 유무와 무관하게 '결정적 증거 없음'이 나온다. ② **0-파라미터 σ=IV 기준선은 VRP>0 때문에 EWMA판보다 더 과신**하므로 사전등록 stop-loss가 **스케일 인공물로 트랙을 죽일 수 있다**. ③ **사려는 형상 요약(SKEW·VVIX)의 상당부분이 이미 $0로 저장소에 있다** — 구매는 S3-a 결과에 조건화돼야 한다.

---

#### **카드 7 — `ml-2` (68점) · S6-a 병합**

- **개선점**: 같은 구매를 겨냥하되 **V13 셀(표적 B)을 병행해 검정력 있는 다리를 하나 확보**했다 — V13 9셀은 `n_eval` **943~1008**로 Brier 차 0.004 수준을 CI90으로 가른다.
- **검정 프로토콜**: 표적 B 우선(쌍대 Brier vs PB 양방향 ∧ y-block ≤0.10 ∧ BH q=0.10), 표적 A는 **MDE 사전 공표 후 base rate 산출만**.
- **거버넌스**: 표적 B는 **새 계약 ID**(V13 계수 동결·라이브 무접촉). 사전등록에 **V11 P4 미검정 사실**과 V13 문서 '54검정→48검정' 정정을 기재.
- **회의론자 지적(심판)**: ① **기초 불일치** — 표적 B의 사건은 SPX 기반 VIX≥K인데 사려는 표면은 QQQ다. 그 셀에 정합한 SPX 표면 요약(SKEW 9,210행 1990~, VVIX 5,087행 2006-03~, VIX3M 4,256행 2009-09~)은 **이미 무료로 있다**. ② **VRP=IV²−RV²의 표준 구현은 VIX²−RV²**(Carr & Wu (2009); Bollerslev, Tauchen & Zhou (2009) 관례)이므로 **구매 없이 계산 가능**하다. ③ Martin (2017) QJE의 SVIX 하한은 **기대수익률 하한 정리**이지 배리어 접촉확률의 Q→P 변환 구속이 아니다(**오적용**). ④ 따라서 구매가 실제로 더하는 것은 **NDX 고유 스큐·행사가 곡률뿐**이고, V9_E6(|ρ|=0.011 직교인데 장기 +0.000006·단기 +1.65% 악화)이 그 성분에 부정적 선례를 남겼다.

---

#### **카드 8 — `infoset-4` (65점) · S6-b((b) 팔은 S3-d로 분리)**

- **가설**: 일중 실현측도(5분 RV·서명 세미분산 RS⁻·BPV/점프·overnight)가 rv 셀 이벤트 확률을 개선하고, 잔차 블록 재표집이 경로 생성기의 과신을 고친다.
- **정보집합**: 일중 — 옵션과 함께 남은 두 미검증 정보집합 중 하나. **`data/intraday/` 디렉터리 자체가 부재**(실측).
- **논문**: Andersen, Bollerslev, Diebold & Labys (2003); Andersen, Bollerslev & Diebold (2007); Barndorff-Nielsen & Shephard (2004); Liu, Patton & Sheppard (2015); Bollerslev, Patton & Quaedvlieg (2016) — 전부 §6-2.
- **데이터·라이선스**: FirstRate Data NDX/QQQ 1분봉. **연구·파생물 발행 허용(귀속표기), raw 재배포 금지** → `data/intraday/firstrate_raw/` gitignore. 등급은 `captured_forward`가 아니라 **`reconstructed_market_archive`**. 계획서 L14 기준 번들 **~$300–400 일회**(문서 기록값); 그 밖 구독가는 `[미검증 — 확인일·URL 병기 필요]`.
- **검정 프로토콜**: (a) V13 rv 셀 쌍대 Brier vs **[RV21_t, VIX_t] 중첩 기준선**, 양방향 CI90 하한>0 ∧ y-block ≤0.10 ∧ BH q=0.10. (b) E0 항등(ℓ_z=1 비트동일) ∧ **CRPS 무손상**(coverage 밴드 [0.76,0.84] 유지) ∧ 경로 사건 채점.
- **기대효과**(자기 사전): rv 셀에서만 RS⁻·JV가 +1~3%p, (b)는 h21 터치 BSS +1~3%p. 채택 확률 25~35%.
- **비용**: ~$300–400 일회 · 엔지니어링 6~10일.
- **회의론자 지적(심판)**: ① **표적 겹침** — V13 rv 셀 라벨은 후행 RV21의 실현값이므로 h=5에서 미래 RV21 편차제곱합의 **중앙값 0.782가 원점 시점에 이미 관측**돼 있고, 일중 정밀도가 개선할 여지는 새로 발생하는 5일치뿐이다. ② **rung-2 오독** — V13 HAR은 일간 종가 제곱수익률이 아니라 **RV21의 3스케일 평활**이었으므로 'HARQ가 일간 RV 잡음을 고친다'는 논거의 전제가 틀렸다. 정작 문헌 사전확률이 가장 높은 **무료 피처(rv 셀에 VIX_t 추가)**는 V13에서도 이 방향에서도 미시험이다. ③ **V12b 재개를 구매에 묶은 것은 저장소 자체 문서와 모순** — 취득계획 §5 L40: "V12b(T-B): 경로 생성기 검정에 일중이 필수는 아님(일간 잔차 재표집 구조 문제) — FirstRate는 사건의 일중 실현 검증용 **보조**". ④ **커버리지 상충 미해소** — 계획서 L12는 1분봉 2000+·설계창 전구간 커버, L15는 틱만 2010+; 본 팩 확인 벤더 페이지는 NDX 지수 1분봉 개시 2008-01-02 `[미검증 — 확인일·URL 미기록]`. **무료 2주 샘플로 개시일과 기기(NDX 지수 vs QQQ ETF)를 먼저 확정**하고 L12를 정정 커밋할 것(개시일이 2008이면 설계창 2007년분 약 250거래일 결손 → S6-b 창 정의가 바뀐다).

---

#### **카드 9 — `classical-4` (63점) · S6-a 병합**

- **개선점**: **무구매 선행 rung**(σ ∈ {EWMA, VIX, VXN} 교체, SPX 기간구조·SKEW·VVIX 중첩)을 명시적으로 열거해 구매 결정을 조건화할 여지를 스스로 만들었고, V12 draft 계약의 `reopen_protocol`(`only_path` = 다른 데이터)과 형식상 정합하다.
- **검정 프로토콜**: **BGK 이산보정판을 구속 기준선으로 결과 전 고정** + 무구매 rung 통과 시에만 구매 rung 진입. 채택은 V13 셀 양방향 CI90 하한>0 ∧ y-block ≤0.10.
- **회의론자 지적(심판)**: ① **사전등록 산술이 가장 낙관적이다** — 필요 마진(h21 +14.28%/BGK +21.12%, h63 +10.18%/+15.08%)에 기대(h63 +2~6%p, h21 +0~3%p)를 양방향으로 요구하면 통과 확률이 **한 자릿수 %**인데 '40~50%'로 적었다. ② stop-loss를 'IV σ 교체 rung이 반사 기준선 대비 비열화 실패면 후속 미실행'으로 걸었는데 **IV는 위험중립이라 평균적으로 RV를 초과(VRP>0)해 2Φ(σ_IV)가 더 과신**하므로, 정보가 있어도 스케일 인공물로 트랙이 죽는다 — stop-loss를 **물리측도 변환 후**로 재명세할 것. ③ 약한 2Φ·λ=0.97 선택은 **사후 완화**이므로 기준선을 BGK 보정판으로 사전 고정.

---

#### **카드 10 — `ml-5` (62점) · S3-d((b), $0) + S6-b((a))로 분할**

- **실질 가치**: (b) 경로 생성기 팔. **일중 데이터가 필요 없고**(취득계획 §5) 즉시 사전등록 가능하다.
- **긍정 요소(심판 인정)**: Liu, Patton & Sheppard (2015)로 측도 격자를 **5분 RV에 사전 고정**해 스누핑을 억제했고, Holm+MCS·BH를 넣어 저장소 다중검정 결손을 메운 점은 **이 방향군에서 가장 낫다**.
- **검정 프로토콜**: (b) E0 항등 비트검증 후 **경로 법칙 자체를 proper scoring rule로 채점**(단일 −10%·h21 Brier는 후반창 7건이라 채택 종점 부적격) ∧ CRPS 무손상. (a) rv 셀 쌍대 Brier vs [RV21, VIX_t] 양방향 ∧ y-block ≤0.10.
- **회의론자 지적(심판)**: ① **사전등록된 채택 종점이 도달 불가** — SUNDAY_LOOP 표 D의 417원점 쌍대 CI90에서 MDE는 h21 **0.004590**·h63 **0.006419**인데 포스트모템 기대이득 h21 BSS +1~3%p는 ΔBrier 0.00065~0.00194로 **1/2.4~1/7**이다. 그래서 종점을 proper scoring rule로 갈아야 한다. ② (a) 팔은 rv 셀 겹침으로 여지가 작다. ③ **"RS⁻·BPV가 일간 종가에서 정의조차 안 된다"는 서술은 부정확** — 정의는 되고 해상도·측정오차만 다르다. 따라서 **일간판 RS⁻·(RV−BPV) 스크린이 $0로 선행 가능**하다. ④ MCS는 저장소 미구현이라 신규 코드 + 결과 전 커밋. ⑤ V12b 파킹 문서와 취득계획의 내부 모순은 **사용자 판정 1건**(§10 D-7, 권고 (b) 취득계획 우선).

---

### 5-3. 탈락·감점 방향과 사유 (원안 대비)

| id | 원안이 주장한 것 | 심판 조정 | 사유(저장소 실측·문헌) |
|---|---|---|---|
| `classical-5`(61) | 꼬리 손실 재채점 + EVT/CAViaR 교체, H5b 통과 25% | **H5a만 S3-e(진단), H5b는 재설계 후 별도** | ① **기전 불일치** — E10의 h21/h63 marginal은 엔진 경로가 아니라 중첩 h일 창합을 창 시작 EWMA로 표준화해 재구성한 FHS 표본(`backtest.py` L156–172)이라 '표준화 잔차 GPD로 경로 p≤0.05 교체'가 적용될 **객체가 없다**. ② 꼬리 검정력 부재 — design p10 위반 h63 **30건/4군집**이라 τ=0.01·ES5는 1~2 에피소드가 판정을 지배. ③ **비교값 +3.96%/+4.21%는 1,011원점 봉인 포함 수치**라 그대로 쓰면 봉인 재접촉을 요구 → **design E10(+3.02%/+2.71%)**로 교체. ④ Christoffersen LR_ind는 주간 원점×h21/63 중첩(MA(h−1))에서 허위 기각 |
| `classical-6`(60) | 일중 σ 교체 + T-B | **S6-b 병합, σ 교체 팔 기대 하향** | **저장소가 이미 두 번 기각한 기전** — V8 dev E11(`fhs_vol_projection=term_structure_phi_0.97`)이 E10 대비 쌍대 −0.000998 vs −0.001266, coverage h21 **0.859**/h63 **0.892**로 밴드 이탈·GFC 0.718 실패; 포스트모템 H1(σ 수준 기전)은 gap이 변동성 3분위에 균일(+0.036/+0.010/+0.033)·corr(gap, RV21)=**+0.04**로 기각 |
| `infoset-6`(58) | 이산시간 hazard로 다중 배리어·드로다운 | **깊이 팔만 S3-c 흡수, hazard·−10%/−15% 보류** | ① −10%×h21 후반창 **7건**이라 5모수 hazard **EPV 1.4** — 채택도 반증도 불가. ② 공변량 d = ln(S_t/K)/σ_t는 K=0.90·S₀에서 **σ의 결정론적 함수** — 랜드마크에서 분산 0이고 이기려는 기준선의 인자 그 자체. ③ 지평 확률에 미래 공변량이 필요해 원점 고정하면 단조변환으로 붕괴, 시뮬레이션하면 파킹된 경로 생성기로 회귀. ④ V12 `reopen_protocol`과 정면 충돌(D-6) |
| `ml-3`(56) | 발표일 조건부 FHS 스케일 + h1 | **h1 종점 폐기, S3-b 병합** | V8 원점은 ISO주 마지막 세션이라 418원점 중 금 **403**·목 14 → h1 표적일 월 **380**·화 36인데 ALFRED vintage 복원 발표 요일은 PAYEMS {금 105, 목 3, 화 1}·CPI {수 36, 금 31, 목 21, 화 20}로 **월요일 0건** → h1 표적일이 CPI/NFP 발표일인 원점 **0/417**. 오라클 상한도 승수 **1.0555** CI90 [0.860, 1.283](1 포함)에 FOMC를 2.0으로 둬도 h1 CRPS 이득 **0.107%** = 필요 절대효과 7.4e-05의 **1/14** |
| `infoset-8`(55) | FOMC 텍스트 + 8-K 밀도 | **S3-f, 재설계 선행** | ① **'NASDAQ 상장사' 8-K 필터를 저장소가 만들 수 없다** — PIT 상장 멤버십 부재(KL 14), 현시점 exchanges 필드로 거르면 look-ahead+생존편향. 전체 filer 카운트로 재정의하면 native PIT가 산다. ② FOMC 서브패널 64회(방향당 32)에서 양성사건 3~6개라 **'측정된 영'조차 낼 수 없다**. ③ Loughran & McDonald (2011) 단어목록은 **10-K용**이고, 인용된 FOMC 논문 둘은 LDA 토픽이지 LM 지수가 아니다. ④ EPU 일간은 **소급 재정규화로 PIT 부적격** |
| `classical-3`(53) | 발표일 분산 승수 1.5~2.5배 | **H3b만 1슬롯, H3a 진단 강등** | E10의 h21/h63은 `np.convolve` 창합 재구성이라 **일별 σ에 √m을 곱할 일별 경로가 없고** `step_scale` 훅은 h1/h5 엔진에만 있다. 승수 1.5~2.5배는 **채권·FX 고빈도 문헌 값**이며 자기 인용(Savor & Wilson)과 충돌 → 주식지수 문헌값 1.1~1.3으로 재기술 |
| `ml-7`(52) | ACI로 봉인 HOLD의 커버리지 결함 해결 | **S5-b 인프라, 판정 트랙 아님** | ① **동기 오진** — 봉인 HOLD 사유는 `reasons` 단 한 줄 '필수 위기 국면 누락: great_financial_crisis_2008'(regime origins 0)이지 커버리지가 아니며, 봉인창 4지평 커버리지는 **전부 밴드 안**이다. ② 표적 수치가 잡음 — pandemic 48원점 ≈ 유효블록 3.8·tightening 52 ≈ 4.1, 0.750은 순진 z조차 **−0.90**. ③ Gibbs & Candès의 보증은 **장기 주변 커버리지**이고 ACI의 음의 되먹임은 LR_ind를 오히려 악화시킬 수 있다. ④ h63 라벨이 purge 63/embargo 5로 **약 68세션(≈13.6주) 지연** 도착 |
| `ml-4`(51) | 교차자산 동조 국면 이벤트 | **S3-g 후순위 또는 보류** | 부호 규약이 반대이고, 설계창 frac(ρ>0) **0.911**·홀드아웃 0.831인데 **2022형 헤지 소멸 국면(봉인창 0.527)만 표적** — 겨냥한 현상이 접근 가능한 두 창 모두에 사실상 없다. 21관측 표본상관 잡음 지분 **46.8%**(Fisher-z sd 0.3444 vs SE 0.2357), 자기상관 lag21 **+0.216** vs VIX/RV +0.823/+0.661 → 'PB가 9/9로 이긴다'는 사다리 바닥 전제조차 충돌. 살릴 것은 달러 다리 조건부 리프트(P(달러\|주식)=0.394 vs 0.168) |
| `infoset-5`(49) | CFTC TFF 포지셔닝 | **S3-h 인프라만**(D-9) | TFF는 2010-07-20 정기 발행 시작·2006-06까지 이력은 **2010-12-03 소급 공개**이고 CFTC 자신이 대형거래자 분류 이력을 보관하지 않아 **2010년 분류를 과거에 적용**했다 — early leg 전체가 PIT가 아니고 라벨 자체가 소급 부여(GFC 100% backcast). 사용 가능 창은 2011–2014뿐이고 반분하면 V9_E6 서브창(260원점)보다 작다. 겨냥한 일화(2018-02)는 **홀드아웃 창에 있다** |
| `classical-2`(47) | 주식-채권 상관 국면 | **S3-g 병합 또는 보류** | 설계창 ρ̂21<0은 1,998일 중 **172일(8.6%)**인데 참 ρ=0.4에서 잡음만으로 3.6%, ρ=0.3에서 **9.5%** — 관측치가 거의 전부 추정 잡음. ρ̂21<0 일의 **67%가 ρ̂63>0** 상태. late 73일 중 **63일이 2013 taper tantrum 단일 에피소드**. PB in-sample Brier 0.0782 vs 기후 0.0786(BSS≈**0.5%**)로 사다리 바닥조차 위태. 문헌 방향도 반대(Connolly, Stivers & Sun (2005): 고VIX → 헤지 성공) |
| `classical-8`(46) | 주간 포지셔닝 → 월간 드로다운, '값싸게 축을 닫음' | **S3-h 인프라만** | PIT 청정 구간(2010-07-20~2014) 225원점 중 사건 43개가 **3개 중첩 에피소드에 전부 몰려** 있고 후반 2012-10~2014-12 114원점은 **사건 0건** → 양방향 CI90 하한>0이 한쪽에서 **정의 불가**. **0-검정력 null을 '포지셔닝 종결'로 기록하면 V9가 피한 오류를 범한다.** 또 '어느 트랙도 포지셔닝을 쓰지 않았다'는 사실과 다름(v5 `features.py` L136–148, `v5.yaml` L102, v6 `CFTC_NASDAQ_LEV_NET_PCT_OI` 1,054행이 봉인 run에 실림 — 단독 ablation 0이므로 반증은 아니고 **신규성 문구 정정 사안**) |
| `infoset-7`(42) | 교차자산 꼬리 의존 copula λ_L | **보류** | COMP–NDX는 ρ=**0.9855**·하방 χ(0.05)=0.867이고 NDX는 Composite의 구성 부분집합이라 λ̂_L 평균 0.797·sd 0.015로 **상수** — 그런데 문헌이 지지하는 유일한 쌍이 이 **void 쌍**이다(전부 주식–주식 연구). COMP–USD는 χ(0.05)=0.040·공동초과 **4건/1983**으로 점근 독립. 63일 창 공동초과는 완전의존에서도 최대 ≈3건이라 ν 미식별 → λ̂_L이 ρ̂의 단조변환으로 붕괴(corr 0.41~0.48) = **사전등록된 피어슨 부정 대조가 처치의 복제본**. 표적도 P(joint)/P(주식 꼬리)=**0.93** |
| `ml-8`(40) | Chronos-2 zero-shot 챌린저 | **보류(현 사양 실행 불가)** | 설치본 `chronos` 2.3.1 `Chronos2Pipeline`은 `forecast_type=QUANTILES`이고 `predict()`에 `num_samples`가 없어 **경로 표본이 안 나온다**. V13 표적은 경로 최대값 사건이라 스텝별 주변 분위수로 결정되지 않는다. N=20·p≈0.3이면 Var(p̂)로 인한 Brier 증가 **+0.0105**로 vix25_h5 MDE(0.00068/0.00026)의 **15~40배** — 노이즈만으로 패배가 확정돼 '문서화된 음성'이 아무것도 말해주지 못한다. **§8 예외 적용 여부는 사용자 판정**(D-8, 기본 (b) 불적용) |
| `classical-7` | log-VIX 평균회귀·점프 첫통과로 h63 오보정 교정 | **드롭** | 진단 전제 반증 + **클래스 상한(오라클 전이 rel 0.083~0.165) > 목표 0.04** — 오라클조차 목표에 못 미친다 |

### 5-4. 원안(`directions.json`)과 심판 점수의 대조 — 세 가지 체계적 조정

1. **중복 병합**: 24개 원안 중 실질 코어는 8~9개다. 심판은 `infoset-1`·`ml-1`·`classical-1` → **S3-a**, `infoset-3`·`ml-3`·`classical-3` → **S3-b**, `ml-6`·`infoset-6`(깊이 팔) → **S3-c**, `infoset-2`·`ml-2`·`classical-4` → **S6-a**, `infoset-4`·`ml-5`(a)·`classical-6` → **S6-b**로 묶었다. 사유는 동일 — **예산·family 중복**. 원안의 개별 예산 계상은 전부 무효다.
2. **기대효과 하향**: 원안 카드의 자기 사전확률은 대체로 심판의 검정력 계산보다 낙관적이었다. 대표 사례는 `classical-4`(원안 40~50% → 심판 "한 자릿수 %"), `ml-5`(b)(원안 20~30% → 채택 종점 자체가 도달 불가), `infoset-2`(요구 마진의 1/3~1/7). **원안의 `expected_effect`를 그대로 사전등록에 옮기면 안 된다.**
3. **'신규성' 주장의 정정**: `classical-8`의 "어느 트랙도 포지셔닝을 쓰지 않았다", `infoset-4`의 "RS⁻·BPV는 일간에서 정의 불가", `ml-5`의 V12b 재개 조건, `infoset-1` 계열의 "덮이지 않았다" — 넷 다 저장소 실측 또는 자체 문서와 어긋나며 **사전등록 서두에서 정정 고지**해야 한다.

---

## 6. 탐구할 논문 목록

> **형식**: Author(s) (Year) 'Title', venue. 각 행의 '추출'은 **이 캠페인이 그 논문에서 정확히 무엇을 가져와야 하는지**다. `conf`는 서지·전이 신뢰도이며, 논문의 **존재**와 **이 표적으로의 전이**를 구분한다(§11-3 자기점검 8번).
>
> **§6-9와의 중복 처리**: 저장소 판정 기계가 딛고 선 원전(부트스트랩·스코어링 룰·예측정확도 비교·변동성 기준선)은 §6-9의 대사표가 정본이다. 아래에서 역할이 다를 때만 재수록하고, 중복 행에는 `→ §6-9`를 표시한다. **§6-9 목록에 없는 원전으로 판정 문장을 쓰지 말 것.**

### 6-1. 예측가능성 회의론·수익률 예측

| 논문 | 추출 | conf |
|---|---|---|
| Welch & Goyal (2008) 'A Comprehensive Look at the Empirical Performance of Equity Premium Prediction', RFS | 표본외 전이 실패가 규칙이라는 기준 사례 — V9/V10/V11 동결 서사의 문헌 대응물. `→ §6-9` | high |
| Campbell & Thompson (2008) 'Predicting Excess Stock Returns Out of Sample: Can Anything Beat the Historical Average?', RFS | 이론 제약(부호·비음)을 걸면 소폭 회복 — **신규 슬롯이 계수 부호를 결과 전에 사전등록해야 하는 이유**. `→ §6-9` | high |
| Goyal, Welch & Zafirov (2024) 'A Comprehensive Look at the Empirical Performance of Equity Premium Prediction II', RFS | 확장 변수군까지의 재검토 — 신규 exog 제안 시 사전확률 기준선 | medium `[미검증: 권·호]` |
| Boudoukh, Richardson & Whitelaw (2008) 'The Myth of Long-Horizon Predictability', RFS | **중첩 표본이 장기 예측력을 과대**한다 — h63·417원점·ℓ=13 유효표본 ≈32(반창당 ≈16)에 직결 | high |
| Christoffersen & Diebold (2006) 'Financial Asset Returns, Direction-of-Change Forecasting, and Volatility Dynamics', Management Science | 방향 적중률이 변동성 동학의 부산물 — R8-D4 비공개 정책의 이론 근거. `→ §6-9` | high |
| Lo & MacKinlay (1988) 'Stock Market Prices Do Not Follow Random Walks: Evidence from a Simple Specification Test', RFS | 분산비 통계량의 원전 — V13 P1 진단 VR(5)=0.8736·VR(21)=0.919·VR(63)=1.044의 해석 좌표. 저장소에 **표준오차 보정 구현 없음** | high(논문)/medium(추론 좌표) |
| Fama (1970) 'Efficient Capital Markets: A Review of Theory and Empirical Work', JF | 효율성 명제를 '정보집합'으로 한정하는 언어 — §4-7이 벽을 정보집합×표적×창×계보로 쓰는 형식의 원전 | high |
| Sullivan, Timmermann & White (1999) 'Data-Snooping, Technical Trading Rule Performance, and the Bootstrap', JF | 규칙 탐색 스누핑의 크기 실증 — 설계창 누적 채굴(V8 12·V9 7·V10 12·V11 48·V12 16·V13 27)의 정량화 논거 | high |
| Pesaran & Timmermann (1995) 'Predictability of Stock Returns: Robustness and Economic Significance', JF | 모형 불확실성 하 예측력 평가 — §9-3 (ii) 통합 family 설계 참고 | medium |
| Rapach & Zhou (2013) 'Forecasting Stock Returns', in *Handbook of Economic Forecasting* | 결합·경제적 제약 지도 — 신규 결합 제안 시 사전확률 | medium `[미검증: 권·쪽]` |
| Ang, Hodrick, Xing & Zhang (2006) 'The Cross-Section of Volatility and Expected Returns', JF | **횡단면 결과** — 시장폭·횡단면 축의 사전확률. 지수 사건 표적으로의 전이 금지 | high(논문)/low(전이) |

### 6-2. 변동성·실현측도

| 논문 | 추출 | conf |
|---|---|---|
| Poon & Granger (2003) 'Forecasting Volatility in Financial Markets: A Review', JEL | 변동성 예측 문헌 지도. `→ §6-9` | high |
| Hansen & Lunde (2005) 'A Forecast Comparison of Volatility Models: Does Anything Beat a GARCH(1,1)?', J. Applied Econometrics | 단순 기준선 우위 — **신규 rung 기대효과 하향의 근거**이자 rung-3(PB 9/9)의 문헌 대응물. `→ §6-9` | high |
| Corsi (2009) 'A Simple Approximate Long-Memory Model of Realized Volatility', J. Financial Econometrics | HAR 원전(V13 rung-2). **주의**: V13 HAR은 일간 제곱수익률이 아니라 RV21의 3스케일 평활이었다. `→ §6-9` | high |
| Andersen, Bollerslev, Diebold & Labys (2003) 'Modeling and Forecasting Realized Volatility', Econometrica | RV의 정의·분포 — S6-b 측도 정의의 원전 | high |
| Liu, Patton & Sheppard (2015) 'Does Anything Beat 5-Minute RV? A Comparison of Realized Measures Across Multiple Asset Classes', J. Econometrics | **측도 격자를 5분 RV에 사전 고정**해 스누핑을 억제하는 방법 — `ml-5`가 이미 채택 | high |
| Andersen, Bollerslev & Diebold (2007) 'Roughing It Up: Including Jump Components in the Measurement, Modeling, and Forecasting of Return Volatility', REStat | 점프 성분 분리 — S6-b RS⁻·JV 팔 | high |
| Barndorff-Nielsen & Shephard (2004) 'Power and Bipower Variation with Stochastic Volatility and Jumps', J. Financial Econometrics | BPV — **일간판 (RV−BPV) $0 선행 스크린**이 가능하다는 근거(심판 지적 ③) | high |
| Bollerslev, Patton & Quaedvlieg (2016) 'Exploiting the Errors: A Simple Approach for Improved Volatility Forecasting', J. Econometrics | HARQ(측정오차 반영). **전제 불일치 주의** — V13 rung-2 오독의 진원 | high(논문)/low(전이) |
| Christensen & Prabhala (1998) 'The Relation between Implied and Realized Volatility', JFE | **IV가 역사 vol을 포섭** — PB가 강한 기준선인 이유이자 rv 셀 **VIX_t 중첩 스크린($0)**의 근거 | high |
| Blair, Poon & Taylor (2001) 'Forecasting S&P 100 Volatility: The Incremental Information Content of Implied Volatilities and High-Frequency Index Returns', J. Econometrics | IV + 고빈도의 **증분** — S3-d/S6-b 착수 순서 결정의 직접 근거 | high |
| Bekaert & Hoerova (2014) 'The VIX, the Variance Premium and Stock Market Volatility', J. Econometrics | VIX를 조건부 분산과 VRP로 분해 — 형상 피처가 어디에 증분을 줄 수 있는지 | high |
| Nelson (1991) 'Conditional Heteroskedasticity in Asset Returns: A New Approach', Econometrica | 비대칭(레버리지) — V10 이후 남은 **형태 축**의 모형 후보 | medium |
| Engle (1982) 'Autoregressive Conditional Heteroscedasticity with Estimates of the Variance of United Kingdom Inflation', Econometrica; Bollerslev (1986) 'Generalized Autoregressive Conditional Heteroskedasticity', J. Econometrics | ARCH/GARCH 원전 — **`arch` 미설치로 V13 GARCH-t rung 미실행**이라는 사실을 기술할 때의 근거 | high |
| Parkinson (1980) 'The Extreme Value Method for Estimating the Variance of the Rate of Return', J. Business | 범위 기반 분산추정 — `classical-1` VIX OHLC 범위 피처. **지수 임계 접촉 예측 근거로는 휴리스틱** | high(논문)/low(전이) |
| Garman & Klass (1980) 'On the Estimation of Security Price Volatilities from Historical Data', J. Business | 범위 추정량 확장 — 채택 시 어느 추정량인지 결과 전 고정 | medium `[전이 미검증]` |
| Lou, Polk & Skouras (2019) 'A Tug of War: Overnight versus Intraday Expected Returns', JFE | overnight/intraday 분해의 존재. **오적용 경고** — 기대수익 결과이지 변동성 사건 확률이 아니다 | high(논문)/오적용 경고 |

### 6-3. 옵션 내재정보

| 논문 | 추출 | conf |
|---|---|---|
| Bollerslev, Tauchen & Zhou (2009) 'Expected Stock Returns and Variance Risk Premia', RFS | VRP의 예측력이 **분기 지평 R² 수 %** — S6-a 기대효과의 상한을 문헌으로 고정 | high |
| Bollerslev & Todorov (2011) 'Tails, Fears, and Risk Premia', JF | 꼬리 프리미엄의 분리 — 좌측 꼬리 지수 정의 | high |
| Bollerslev, Todorov & Xu (2015) 'Tail Risk Premia and Return Predictability', JFE | 꼬리 성분의 예측력 — S6-a 표적 A(가격 꼬리)의 이론 근거 | high |
| Jiang & Tian (2005) 'The Model-Free Implied Volatility and Its Information Content', RFS | MFIV — VIX² 산출식과 표면에서의 재현 | high |
| Britten-Jones & Neuberger (2000) 'Option Prices, Implied Price Processes, and Stochastic Volatility', JF | 모형자유 내재분산의 원전 | high |
| Bakshi, Kapadia & Madan (2003) 'Stock Return Characteristics, Skew Laws, and the Differential Pricing of Individual Equity Options', RFS | **BKM 왜도·첨도 적률** — 표면 요약 통계량의 표준 정의 | high |
| Breeden & Litzenberger (1978) 'Prices of State-Contingent Claims Implicit in Option Prices', J. Business | BL 밀도. **유럽형 전제** — QQQ는 미국형이라 de-Americanization 단계를 결과 전 고정 | high(논문)/medium(전이) |
| Carr & Wu (2009) 'Variance Risk Premiums', RFS | VRP의 합성 분산스왑 정의 — **VIX²−RV²는 구매 없이 계산 가능**하다는 근거(ml-2 지적 ②) | high |
| Johnson (2017) 'Risk Premia and the VIX Term Structure', JFQA | 기간구조 slope의 예측력. **오적용 경고**: slope는 P-측도 VIX 경로가 아니라 **분산위험 프리미엄**을 전달한다 — S3-a 기대효과 하향의 직접 근거 | high(논문)/low(직접 전이) `[미검증: 권·호]` |
| Mixon (2007) 'The Implied Volatility Term Structure of Stock Index Options', J. Empirical Finance | 기간구조가 기대가설 대비 단기 IV를 과대예측하나 **방향 정보는 있다** — S3-a 계수 부호(backwardation→상승) 사전등록 근거 | medium |
| Huang, Schlag, Shaliastovich & Thimme (2019) 'Volatility-of-Volatility Risk', JFQA | VVIX의 vol-of-vol 프리미엄 — VVIX 갈래의 유일한 직접 근거 | medium |
| Simon & Campasano (2014) 'The VIX Futures Basis: Evidence and Trading Strategies', J. Derivatives | 베이시스가 VIX 변화를 예측. **수익률 전략 문헌**이라 이벤트 확률로의 전이는 `[미검증]` | medium |
| Martin (2017) 'What Is the Expected Return on the Market?', QJE | SVIX 하한. **오적용 경고**: 기대수익률 하한 정리이지 배리어 접촉확률의 Q→P 변환 구속이 아니다 | high(논문)/오적용 경고 |
| Andersen, Fusari & Todorov (2015) 'The Risk Premia Embedded in Index Options', JFE | 좌측 꼬리 요인의 시간변동 — 위기원점 인공물 검사(⑥)를 왜 표면 피처에 반드시 걸어야 하는지 | medium |
| Chang, Christoffersen & Jacobs (2013) 'Market Skewness Risk and the Cross Section of Stock Returns', JFE | 왜도 위험의 가격결정. **횡단면 결과** — 지수 사건 표적 전이는 `[미검증]` | medium |
| Cboe 'Cboe Volatility Index (VIX) White Paper' | VIX 산출 규칙과 **2014-10-06 weeklys 방법론 변경** — `classical-1` caveat의 1차 출처가 되어야 할 문서 | low `[미검증: 판·발행연도·URL·접근일 미확인 — 근거로 인용하지 말고 확인 후 기재]` |

### 6-4. 예측 결합·평가·다중비교

| 논문 | 추출 | conf |
|---|---|---|
| Politis & Romano (1994) 'The Stationary Bootstrap', JASA | 전 트랙 CI90의 재표집 원전(ℓ·B·seed 좌표의 근거). `→ §6-9` | high |
| Gneiting & Raftery (2007) 'Strictly Proper Scoring Rules, Prediction, and Estimation', JASA | CRPS·interval(Winkler) score의 proper 성립 근거. `→ §6-9` | high |
| Diebold & Mariano (1995) 'Comparing Predictive Accuracy', JBES; **Harvey, Leybourne & Newbold (1997) 'Testing the Equality of Prediction Mean Squared Errors', IJF** | `diebold_mariano_hac`의 원전과 **소표본 보정이 저장소에 없다는 사실**의 근거 — 서브패널 DM 인용 시 반드시 병기. `→ §6-9` | high |
| Diebold (2015) 'Comparing Predictive Accuracy, Twenty Years Later: A Personal Perspective on the Use and Abuse of Diebold–Mariano Tests', JBES | DM은 **모형이 아니라 예측**의 비교 — DM을 게이트 판정 다리로 승격하지 말라는 규칙의 이론 근거 | medium |
| Giacomini & White (2006) 'Tests of Conditional Predictive Ability', Econometrica | rolling 재추정·**국면 조건부(calm vs GFC)** 비교 — V10 "위기원점 인공물" 판정을 정식 검정으로 대체(§8-2 ADD) | high |
| Hansen, Lunde & Nason (2011) 'The Model Confidence Set', Econometrica | 사다리 {PB, EWMA, HAR, 신규 rung}의 **동등 집합** — 현재는 쌍대 vs 최선/E0만 있다. 저장소 미구현 | high |
| White (2000) 'A Reality Check for Data Snooping', Econometrica; Hansen (2005) 'A Test for Superior Predictive Ability', JBES | 트랙 간 누적 스누핑 보정의 후보 절차(§9-3 (ii)). `→ §6-9` | high |
| Romano & Wolf (2005) 'Stepwise Multiple Testing as Formalized Data Snooping', Econometrica | 강한 FWER stepdown — **같은 부트스트랩 재표집을 공유**하므로 상관 강한 셀 구조에서 BH의 대안(택1 고정) | high |
| Benjamini & Hochberg (1995) 'Controlling the False Discovery Rate: A Practical and Powerful Approach to Multiple Testing', JRSS-B | family = **퇴화 가드 통과 셀만**, q=0.10 — 9셀×다피처 family의 기본 절차 | high |
| Holm (1979) 'A Simple Sequentially Rejective Multiple Test Procedure', Scandinavian J. Statistics | 셀 수가 적을 때의 보수적 대안 — S3-c 게이트가 채택 | high |
| Clark & West (2007) 'Approximately Normal Tests for Equal Predictive Accuracy in Nested Models', J. Econometrics | **중첩 모형 비교의 편의 보정** — PB ⊂ PB+{형상}이 정확히 중첩 구조인데 저장소에 구현이 없다. S3-a 사전등록에서 사용 여부를 결과 전 택일할 것 | high |
| Gneiting & Ranjan (2011) 'Comparing Density Forecasts Using Threshold- and Quantile-Weighted Scoring Rules', JBES | 좌측 비대칭 가중 — S3-e 손실축. 기존 대칭 `tail_weighted_crps`의 **가중함수만 교체**하면 된다(§8-2) | high |
| Gneiting, Balabdaoui & Raftery (2007) 'Probabilistic Forecasts, Calibration and Sharpness', JRSS-B | "최대 샤프니스 subject to 캘리브레이션" 원리 — 신규 rung이 보정을 재는지 정보를 재는지 가르는 언어(ml-8 지적 ⑤) | high |
| Politis & White (2004) 'Automatic Block-Length Selection for the Dependent Bootstrap', Econometric Reviews | ℓ 자동 선택 — **ℓ=13 고정의 대안**이자 시드·블록 민감도 부록(ℓ∈{8,13,21})의 근거 | high |
| Hansen & Timmermann (2012) 'Choice of Sample Split in Out-of-Sample Forecast Evaluation' | split 선택이 검정 크기에 미치는 영향 — **split 2010-12-31의 정점지식 caveat**를 정량화할 근거 | medium `[미검증: 발행처·권·호]` |
| Timmermann (2006) 'Forecast Combinations', in *Handbook of Economic Forecasting* | 단순 결합이 최적 가중을 이기는 사전확률 — **고정 중앙값·convex blend 0.75·52원점 역CRPS 가중 유지**의 근거이자 가중 학습을 해소 200+ 뒤로 미루는 비용이 작다는 논거 | high |
| Bates & Granger (1969) 'The Combination of Forecasts', Operational Research Quarterly | 결합의 원전 | high |
| Hoeting, Madigan, Raftery & Volinsky (1999) 'Bayesian Model Averaging: A Tutorial', Statistical Science | BMA — **해소 200+ 게이트로 구조적 보류**(§8-3) | high |
| Brier (1950) 'Verification of Forecasts Expressed in Terms of Probability', Monthly Weather Review; Murphy (1973) 'A New Vector Partition of the Probability Score', J. Applied Meteorology | Brier와 3분해(`murphy_decomposition`, n_bins=10) — 신뢰도 보고 의무의 원전. `→ §6-9` | high |

### 6-5. 캘리브레이션·컨포멀·구간 예측

| 논문 | 추출 | conf |
|---|---|---|
| Gibbs & Candès (2021) 'Adaptive Conformal Inference Under Distribution Shift', NeurIPS | α_t 온라인 갱신 — 커버리지는 장기 평균으로만 보장되고 **구간 폭이 폭주**할 수 있음. S5-b는 인프라 전용, 판정 트랙 금지 | high |
| Angelopoulos, Candès & Tibshirani (2023) 'Conformal PID Control for Time Series Prediction', NeurIPS | 적분·비례 항 — α_t 자체가 적산기임에 유의 | medium |
| Foygel Barber, Candès, Ramdas & Tibshirani (2021) 'The limits of distribution-free conditional predictive inference', Information and Inference | 조건부 커버리지 불가능성 — LR_cc를 1차 지표로 두지 말 것 | high |
| Zadrozny & Elkan (2002) 'Transforming Classifier Scores into Accurate Multiclass Probability Estimates', KDD | PAV isotonic — V8 B4·V13 cross-fit의 원전 | high |
| Bröcker & Smith (2007) 'Increasing the Reliability of Reliability Diagrams', Weather and Forecasting | reliability 신뢰대(저장소 미구현) | medium [미검증: 코드 전수는 grep 기반] |
| Berkowitz (2001) 'Testing Density Forecasts, with Applications to Risk Management', JBES | PIT 정식 검정 | medium [미검증] |
| Christoffersen (1998) 'Evaluating Interval Forecasts', IER | LR_uc/LR_ind/LR_cc — **중첩 원점에서 허위 기각** 주의 | high |
| Kupiec (1995) 'Techniques for Verifying the Accuracy of Risk Measurement Models', J. Derivatives | 1% 분위 검정력 한계 | high |

### 6-6. 이벤트·생존·극단값

| 논문 | 추출 | conf |
|---|---|---|
| Broadie, Glasserman & Kou (1997) 'A Continuity Correction for Discrete Barrier Options', Mathematical Finance | β=0.5826 이산 배리어 보정 — 기준선 명세의 핵심 | high |
| Magdon-Ismail, Atiya, Pratap & Abu-Mostafa (2004) 'On the Maximum Drawdown of a Brownian Motion', J. Applied Probability | 브라운 MDD 분포. **(μ,σ) 2모수·연속시간** → 이산판으로 교체 | high(논문)/low(직접 기준선) |
| McNeil & Frey (2000) 'Estimation of Tail-Related Risk Measures for Heteroscedastic Financial Time Series: An Extreme Value Approach', J. Empirical Finance | GARCH 필터+POT-GPD. **1-step 조건부**이며 h일 경로 사건 근거 아님 | high(논문)/low(전이) |
| Engle & Manganelli (2004) 'CAViaR: Conditional Autoregressive Value at Risk by Regression Quantiles', JBES | 분위수 직접 동학(분포 가정 없는 rung) | high |
| Fissler & Ziegel (2016) 'Higher Order Elicitability and Osband's Principle', Annals of Statistics; **Patton, Ziegel & Chen (2019) 'Dynamic Semiparametric Models for Expected Shortfall (and Value-at-Risk)', J. Econometrics** | (VaR,ES) 공동 elicitability와 FZ0의 실제 명명 | high |
| Kuester, Mittnik & Paolella (2006) 'Value-at-Risk Prediction: A Comparison of Alternative Strategies', J. Financial Econometrics | FHS가 이미 EVT급 — H5b 기대 하향 | high |
| Ferro & Segers (2003) 'Inference for Clusters of Extreme Values', JRSS-B | 초과분 군집 declustering — 창합 GPD의 전제 | high |
| Shumway (2001) 'Forecasting Bankruptcy More Accurately: A Simple Hazard Model', J. Business; Singer & Willett (1993) 'It's About Time: Using Discrete-Time Survival Analysis to Study Duration and the Timing of Events', J. Educational Statistics | 이산시간 hazard = 로짓 동치. **h-step 예측기가 아님** | high |
| Kalbfleisch & Prentice (2002) 'The Statistical Analysis of Failure Time Data', 2nd ed., Wiley; van Houwelingen (2007) 'Dynamic Prediction by Landmarking in Event History Analysis', Scandinavian J. Statistics | 내생 시변 공변량·랜드마킹 | high / [권·쪽 미검증] |
| Peduzzi, Concato, Kemper, Holford & Feinstein (1996) 'A Simulation Study of the Number of Events per Variable in Logistic Regression Analysis', J. Clinical Epidemiology; Vittinghoff & McCulloch (2007) 'Relaxing the Rule of Ten Events per Variable in Logistic and Cox Regression', AJE | EPV≥10(완화판 5~9) — 후반창 7건 설계의 판정 근거 | high |
| Chekhlov, Uryasev & Zabarankin (2005) 'Drawdown Measure in Portfolio Optimization', IJTAF | 드로다운 위험 측도 — EXIT 룰 연결 | medium |
| Longin & Solnik (2001) 'Extreme Correlation of International Equity Markets', JF; Ang & Chen (2002) 'Asymmetric Correlations of Equity Portfolios', JFE; Christoffersen, Errunza, Jacobs & Langlois (2012) 'Is the Potential for International Diversification Disappearing? A Dynamic Copula Approach', RFS; Patton (2006) 'Modelling Asymmetric Exchange Rate Dependence', IER; Poon, Rockinger & Tawn (2004) 'Extreme Value Dependence in Financial Markets: Diagnostics, Models, and Financial Implications', RFS | 꼬리 의존·비대칭 상관. **전부 주식–주식**이고 롤링 MLE를 쓰지 않음 | high(논문)/low(교차자산 전이) |
| Demarta & McNeil (2005) 'The t Copula and Related Copulas', International Statistical Review; **Embrechts, McNeil & Straumann (2002) 'Correlation and Dependence in Risk Management: Properties and Pitfalls', in *Risk Management: Value at Risk and Beyond* (ed. Dempster), Cambridge University Press** | λ_L이 ν 고정 시 ρ의 순증가 함수 — 부정 대조 오염의 수식 근거 | high |

### 6-7. ML in asset pricing (도입 전 사전확률·게이트 확인용)

| 논문 | 추출 | conf |
|---|---|---|
| Makridakis, Spiliotis & Assimakopoulos (2018) 'Statistical and Machine Learning Forecasting Methods: Concerns and Ways Forward', PLOS ONE | ML이 통계 기준선을 못 이기는 경우가 흔함 | high |
| Rigby & Stasinopoulos (2005) 'Generalized Additive Models for Location, Scale and Shape', JRSS-C; Gneiting, Raftery, Westveld & Goldman (2005) 'Calibrated Probabilistic Forecasting Using Ensemble Model Output Statistics and Minimum CRPS Estimation', Monthly Weather Review; Koenker & Bassett (1978) 'Regression Quantiles', Econometrica | 자유도 작은 분포·분위수 회귀 = ML 게이트 밖 안전지대 | high |
| Hamilton (1989) 'A New Approach to the Economic Analysis of Nonstationary Time Series and the Business Cycle', Econometrica; Ang & Bekaert (2002) 'International Asset Allocation with Regime Shifts', RFS; Amaya, Christoffersen, Jacobs & Vasquez (2015) 'Does Realized Skewness Predict the Cross-Section of Equity Returns?', JFE | 국면·형상(왜도) 조건화 — V10/V11 이후 남은 형태 축 | medium |
| Rapach, Ringgenberg & Zhou (2016) 'Short Interest and Aggregate Stock Returns', JFE; Hong & Yogo (2012) 'What Does Futures Market Interest Tell Us about the Macroeconomy and Asset Prices?', JFE; Wang (2003) 'The Behavior and Performance of Major Types of Futures Traders', J. Futures Markets `[미검증: 권·호]`; Sanders, Irwin & Merrin (2009) 'Smart Money: The Forecasting Ability of CFTC Large Traders in Agricultural Futures Markets', JARE; Cheng, Kirilenko & Xiong (2015) 'Convective Risk Flows in Commodity Futures Markets', Review of Finance | 포지셔닝 축의 혼재·부정·**역인과** 증거 | high/medium |
| Baker & Wurgler (2006) 'Investor Sentiment and the Cross-Section of Stock Returns', JF; Da, Engelberg & Gao (2011) 'In Search of Attention', JF; Tetlock (2007) 'Giving Content to Investor Sentiment: The Role of Media in the Stock Market', JF; Loughran & McDonald (2011) 'When Is a Liability Not a Liability? Textual Analysis, Dictionaries, and 10-Ks', JF | 심리·주의·텍스트 축의 사전확률과 도메인 제약 | high |
| Kelly & Jiang (2014) 'Tail Risk and Asset Prices', RFS | **횡단면 Hill 추정** — 지수 드로다운 공변량 근거로 오적용 금지 | high(논문)/오적용 경고 |

### 6-8. Foundation models

| 논문 | 추출 | conf |
|---|---|---|
| Ansari et al. (2024) 'Chronos: Learning the Language of Time Series', TMLR (arXiv:2403.07815) | 아키텍처·**학습 코퍼스 구성**(설계창/봉인창 오염 판단의 핵심) | medium [코퍼스 세부 미검증] |
| Das, Kong, Sen & Zhou (2024) 'A decoder-only foundation model for time-series forecasting', ICML | TSFM zero-shot 성능 범위 — 금융 계열 약세 사전확률 | medium-high |
| Aksu et al. (2024) 'GIFT-Eval: A Benchmark for General Time Series Forecasting Model Evaluation', arXiv `[미검증: 식별번호]` | 도메인·주기별 편차 | medium [세부 미검증] |
| Amazon Science (2025) 'Chronos-2' 기술 보고서 `[미검증: 저자·발행처·URL·접근일 미확인]` | **근거로 인용하지 말 것.** 저장소가 확인한 사실만 기술: 로컬 `chronos` 2.3.1 설치, 현 API 출력이 QUANTILES라 **경로 표본 불가** | low [서지 미검증] |
| Halawi et al. (2024) 'Approaching Human-Level Forecasting with Language Models', arXiv:2402.18563 | LLM 예측 스캐폴드 — 원칙 5 경계와 함께 읽을 것 | medium |
| Lopez-Lira & Tang (2023) 'Can ChatGPT Forecast Stock Price Movements? Return Predictability and Large Language Models' | LLM 직접 예측 주장 | [미검증: 워킹페이퍼·재현성] |

### 6-9. 저장소 판정 기계가 실제로 딛고 선 기초 문헌 (6-1~6-4와 중복 시 병합할 것)

이 절은 **본 팩의 판정 좌표(부트스트랩·스코어링 룰·예측정확도 비교·변동성 기준선)가 인용해야 하는 원전**을 한 자리에 모은 대사표다. 6-1~6-4에 이미 실린 항목은 중복 삭제하되, **아래 목록에 없는 원전으로 판정 문장을 쓰지 말 것**.

| 논문 | 저장소에서의 역할 | conf |
|---|---|---|
| Politis & Romano (1994) 'The Stationary Bootstrap', JASA | 전 트랙 CI90의 재표집 원전(ℓ·B·seed 좌표의 근거) | high |
| Gneiting & Raftery (2007) 'Strictly Proper Scoring Rules, Prediction, and Estimation', JASA | CRPS·interval(Winkler) score의 proper 성립 근거 | high |
| Diebold & Mariano (1995) 'Comparing Predictive Accuracy', JBES | `diebold_mariano_hac` 표시 지표의 원전 | high |
| **Harvey, Leybourne & Newbold (1997) 'Testing the Equality of Prediction Mean Squared Errors', IJF** | DM 소표본 보정 — **저장소에 구현이 없다는 사실**의 근거. 서브패널 DM 인용 시 반드시 병기 | high |
| Brier (1950) 'Verification of Forecasts Expressed in Terms of Probability', Monthly Weather Review; Murphy (1973) 'A New Vector Partition of the Probability Score', J. Applied Meteorology | Brier와 그 3분해(`murphy_decomposition`) | high |
| Corsi (2009) 'A Simple Approximate Long-Memory Model of Realized Volatility', J. Financial Econometrics | HAR rung의 원전(V13 rung-2) | high |
| **Hansen & Lunde (2005) 'A Forecast Comparison of Volatility Models: Does Anything Beat a GARCH(1,1)?', J. Applied Econometrics** | 변동성 기준선 우위의 사전확률 — 신규 rung 기대효과 하향의 근거 | high |
| Poon & Granger (2003) 'Forecasting Volatility in Financial Markets: A Review', JEL | 변동성 예측 문헌 지도 | high |
| Welch & Goyal (2008) 'A Comprehensive Look at the Empirical Performance of Equity Premium Prediction', RFS; Campbell & Thompson (2008) 'Predicting Excess Stock Returns Out of Sample: Can Anything Beat the Historical Average?', RFS | 표본외 전이 실패의 기준 사례 — V9/V10/V11 동결 서사의 문헌 대응물 | high |
| Christoffersen & Diebold (2006) 'Financial Asset Returns, Direction-of-Change Forecasting, and Volatility Dynamics', Management Science | 방향 적중률이 변동성 동학의 부산물일 수 있음 — R8-D4 비공개 정책의 이론 근거 | high |
| Barone-Adesi, Giannopoulos & Vosper (1999) 'VaR without Correlations for Portfolios of Derivative Securities', J. Futures Markets | FHS 원전 | high |
| White (2000) 'A Reality Check for Data Snooping', Econometrica; Hansen (2005) 'A Test for Superior Predictive Ability', JBES | 트랙 간 누적 스누핑 보정의 후보 절차(§9-3 (ii)) | high |

---

## 7. 학습·수집할 DB 목록

### 7-1. 보유 자산 (held)

| 레인 (경로) | 범위·규모 | PIT 등급 | 라이선스 | 어느 방향이 쓰나 |
|---|---|---|---|---|
| **V1 정본 ALFRED vintage** `data/timeseries/facts/observations.parquet` | 26 시리즈 · **1,505,217행**, raw 549 gz·영수증 1,250행. PAYEMS·UNRATE·INDPRO·HOUST·GDPC1(1996-01), RSAFS(2001-07), CPIAUCSL(1996-02)·CPILFESL(1997-01)·PCEPI·PCEPILFE(2000-08), M2SL(1996-01)·TOTCI·TOTLL(1996-12)·WRMFNS(2002-11)·WALCL(2011-07)·WTREGEN(2008-12)·RRPONTSYD(2016-03)·NFCI(2011-06, 916,923행), DGS2·DFF(2005-07)·VIXCLS(관측 2004-06, 첫 vintage 2010-11)·NASDAQCOM(2014-05)·T10Y2Y(2014-01)·DTWEXB(2014-03)·DTWEXBGS(2019-02)·BAMLH0A0HYM2(2023-08~) | **native_pit** | FRED 공식 API approved. **KNOWN_LIMITS 34**: 약관의 AI/ML "development" 문언·store/cache 금지와 PIT 아카이브 커밋의 긴장 미해결 | **S3-b**(CPI·NFP 발표일 = vintage realtime_start), V9(소진) |
| **V2 공식 시장 아카이브** `data/timeseries_v2/ledgers/market_observations.jsonl` | **47,741행**·영수증 142·raw 89파일. NASDAQCOM 1995-01-03~(7,973), VIX 1990-01-02~(9,266), DGS2·DGS10 1990~(각 9,176), DTWEXB 1995~2019(6,328)+DTWEXBGS 2006~(5,179), FED_EBP 1973-01~2026-07 월간(643) | reconstructed 17,512 + captured_forward 30,229 | FRED·Treasury·Fed 공식. **CBOE 회색지대**(12-1 금지 조항 vs fair use 유보; 12-5 대체 없음) | S3-a·b·c·d·g, S5, V13 전량 |
| **V2 raw VIX OHLC** `data/timeseries_v2/raw/market/cboe_vix_archive/*.gz` | 13파일(실측 일치), DATE·OPEN·HIGH·LOW·CLOSE, 9,259행. 설계창 zero-range 0일. (행수·zero-range는 **검토용 진단, 원장 미기록** — 산출 스크립트 경로를 사전등록 부록에 첨부할 것. 또한 이 아카이브는 매회 전체 CSV 재다운로드 방식이라 **캡처 시점만 보증**되며, 1990~1991 구간 OHLC 결측 여부는 `[미검증]`. D-10으로 창을 1997+로 확장할 경우 이 확인이 선행 조건.) | 위와 동일 | CBOE 회색 | **S3-a 범위 피처**(새 파서·새 원장, 봉인 무접촉) |
| **V4 후보 스토어** `data/timeseries_v4/ledgers/observations.jsonl` | **113,615행**(스냅샷 2026-08-20). SKEW 9,210(1990-01-02~), VVIX 5,087(2006-03-06~), VIX3M 4,256(2009-09-18~), VIX9D 3,930(2011-01-04~), CBOE 거래량 4종(2009-01~), NASDAQ100 7,963(1995-01-03~, private locator), Cleveland 나우캐스트(2012~), Philly SPF(1990~), CME FedWatch·BLS·NFP 컨센서스(2026-08-06/07 캡처만) | reconstructed_market_archive 등 | CBOE 회색·Fed 공식·CME 유료 | **S3-a 주력**, S3-c(형상 갈래), S6-a(무구매 rung). **선례 고지(필수)**: 이 계열의 **지수 수준 입력은 이미 시도돼 게이트를 통과하지 못했다** — V4(`multivariate_timeseries_v4.yaml`, 판정 hold — h21 +0.29%/h63 +1.69%)·V5, 그리고 V9 E5/E6(Δlog(VXN/VIX), 2010–14 서브창 **260원점** — 원장 `data/timeseries_v9/ledgers/development_experiments.jsonl`의 `V9_E5_subwindow_baseline` 장기 쌍대평균 **−0.0025864502**, `V9_E6_vxn_vix_spread` **−0.0025802706** → 델타 **+0.000006**, 판정서 `outputs/timeseries_v9/reports/E5_E6_VXN_SPREAD_VERDICT_20260902.md` L9 CI90 [−0.000008, +0.000021] **개선 없음**, L10 단기 h1+h5 **+1.65%** [+0.000058, +0.000246] **유의 악화**). S3-a가 "덮이지 않았다"는 주장은 오직 **표적 교체**(가격 분포 CRPS → 변동성 이벤트 Brier)에 근거하며 **정보집합은 새롭지 않다**. 이 비대칭을 사전등록 서두에 명문화하고 기대효과를 그에 맞게 하향할 것 |
| **V9 시장 레인** `data/timeseries_v9/ledgers/market_observations.jsonl` | VXN 2009-09-14~ **4,270행**(실측 일치) | reconstructed | private locator(raw 비커밋) | S6-a 무구매 rung(σ 교체) |
| **V3~V7 동결 코드·산출** `data/contracts/multivariate_timeseries_v{3,4,5,6,7}.yaml`, `outputs/timeseries_v{5,6,7}/`(v3·v4는 산출 디렉터리 부재 — 실측) | V3 h21 +0.75%/h63 +2.02%(hold) · V5 963원점 h21 −10.69%/h63 −7.38%(hold, 7사유) · V6 봉인 385원점 h21 +1.27%/h63 +0.58%(hold, 8사유) · V7 `WAIT_DATA`(`outputs/timeseries_v7/status.json` 실재 확인, 계약 `frozen_v7_p0_003`). 수치는 각 트랙 계약·판정서 인용값이며 **본 개정에서 재계산하지 않았다** | design pseudo-OOS·봉인 1회(V6) | — | **코드 자산이지 승인 모델 아님**(전부 `shadow_gate_hold`/HOLD). 신규 슬롯이 이 코드를 재사용하면 그 사실과 HOLD 지위를 사전등록에 적을 것 |
| **FRED current-vintage 시그널** `fred_market_signals.yaml` | BAMLH0A0HYM2·DFII10·DTWEXBGS·WALCL·WTREGEN·RRPONTSYD·DGS10·BAMLC0A0CM·VIXCLS | **captured** — "historical current-vintage rows are not valid for backtests" | approved(12-6). `source_registry.yaml`·`licenses.generated.md`가 endpoint를 `fredgraph.csv`로 적어 계약과 **문서 드리프트**(확인일 2026-08-01), v5 `sources.py`도 fredgraph 잔존(C-3) | 라이브 표시만 |
| **통계 authoritative 스토어** `data/statistics/official_store/` | 정규화 **53,660행**·영수증 890, 49 시리즈(NASDAQCOM·SP500·NASDAQSOX·CBBTCUSD·DCOILWTICO·T10Y3M·T10Y2Y·NFCI·M2SL·MMMFFAQ027S·Z.1 계열·BEA·Census C30·SEC_IPO_QUARTERLY·DRTSCILM·HQMCB10YR) | captured | 미국 정부 저작물 + FRED API. SEC 연락처 UA(KL 35, 2026-09-01 해소) | `statistics_lab_v1.yaml`은 계약 **전역**으로 `status: active_reference_only`·`probability_space: reference_only`·`model_use: prohibited`(**L3–L5**, 실측) — **49 시리즈 전부가 모델 입력 금지**이며 NASDAQSOX도 그 일부다(L56은 role 정의뿐: `role: us_semiconductor_index_reference`). 따라서 infoset-7 SOX 갈래뿐 아니라 **이 스토어 전 계열이 차단**된다 |
| **발표 캘린더** `data/calendar/events.csv`(**53건**, 실측) · `data/contracts/calendar_sources.yaml`(`as_of: 2026-08-04`) | FOMC·CPI·NFP·GDP·NVDA IR 등 공식 IR·기관 일정 | native(공표일, L5 `confirmed_definition: institution_or_issuer_published_date`) | 공공 | **S3-b 1차 입력**. 단 L4 `policy.probability_linkage: forbidden`의 **범위는 D-5 미결** |
| **base rate 라이브러리** `data/base_rates/` (수동 + `*_auto.md`) | `volatility.md`: `vix-25-90d` 무조건부 **44%(7/16년, 2010~2025)**, 조건부 **33.3%(2/6년)** / 대조군 **11.1%(1/9년)** | 큐레이션 | — | V13 기준율 카드와 **같은 사건을 다른 방법으로** 추정 중 — 신규 슬롯은 둘의 불일치 표시 규칙(X1 6항)을 승계 |
| **IPO 레이어** `data/statistics/ipo/` | Ritter 1995–1999 vs Renaissance AI 코호트 2023–2026, SEC EDGAR 분기 IPO, dualdb `ipo_annual` 14행 | 큐레이션(Tier-3 근사, KL 12) | Ritter 재배포 약관 미기록 [미검증] | 해당 없음 |
| **dualdb** `dualdb/db/dualdb.sqlite` | price_daily **285,289행**·33 시리즈, macro_daily 8·monthly 8, Shiller CAPE 1871~2023-09, Ken French 1927~2026-05, margin_debt 14개월(2025-05~2026-06), event 48, dotcom_casualty 25, capex_buildout 11, model_run 9. raw 470파일 | **비-PIT 현행 vintage** | Yahoo 자동수집 금지 문언(12-5·12-8), Shiller·French 약관 미기록 [미검증], Stooq 2026-07-15 이후 차단 | base rate 참조 전용. sentiment_weekly 0행(AAII 수동 대기, KL 28), fundamentals_annual 0행 |
| **시장내재 아카이브** `data/ml_history/2026.jsonl` | 21행(2026-07-15~). Polymarket·CBOE 지연시세 QQQ N(d2)·Kalshi(호가 공란) | captured_forward만. **옵션 표면 이력 0** | 회색·약관 미기록 [미검증] | S6-a의 부재 증명 |
| **ML 추론 산출** `src/ai_fc/ml` | Chronos-Bolt-small·Chronos-T5-small·Chronos-2(Apache-2.0), FinBERT, GDELT 헤드라인(12-7, 3/5 성공) | captured_forward | GDELT 명시 허용, Google News RSS 중단(12-4a) | ml-8(보류), S3-f 2단계(사용자 결정) |
| **V13-VOL** `data/timeseries_v13/vol/` | champion 9셀, 계수 sha256 **1a85785056738775f732531dc442616908e20ca0f356187eb5fd1adb614b3ac1**(실측·계약 L248 일치), `vol_latest.json` 2026-09-04, 라이브 원장 `vol_live.jsonl` **2행**, 승인 원장 `approvals.jsonl` **7행** | V2 read-only | — | 전 슬롯의 기준선 |
| **예측·원장** | `forecasts/2026` 72파일 · `calibration/ledger.csv` **9행(질문 5)** · `questions/registry.yaml` 약 43문항. V8 원장 5종(`ledger_registry.yaml` L316–342, **전부 실측 대사**): `development_experiments.jsonl` **12행(E0~E11, 전부 design)** · `holdout_scorings.jsonl` **1행(E10 PASS, 장기개선 0.0734, CI90 상단 −0.00106)** · `sealed_evaluations.jsonl` **1행**(전체창 1,011원점 pass / 봉인창 385원점 hold, 사유 'GFC 원점 0') · `shadow_forecasts.jsonl` **2행** · `shadow_resolutions.jsonl` **2행** | append-only | — | C5·S5 |

### 7-2. 후보 (candidate)

| 후보 | 추가 정보집합 | PIT | 라이선스 | 비용 | 필요한 방향 | 판정 |
|---|---|---|---|---|---|---|
| **CBOE DataShop / LiveVol** QQQ 옵션 EOD(2004+) | 행사가별 IV 표면·스큐·꼬리·VRP | 상급(as-traded 캡처). 2007–2014 Calcs 소급·일중 IV 표면은 공백 | Subscriber Agreement §1 내부연구, §2b 파생표시 조건부 — 소유자 원문 재확인 | EOD $500/월, 일중 애드혹 $1.5–2.5k/월, 구독 $5–6k/월, 일회 이력가 [미검증] | **S6-a** | 부정결과가 **덮지 않음**. 새 등급 `vendor_eod_archive` 신설 필요 |
| **FirstRate Data** NDX/QQQ 1분봉 | 5분 RV·RS⁻·BPV·overnight | 중(back-adjust 재구성본). **커버리지 상충 미해소**: 취득계획 `docs/design/v13_firstrate_acquisition_plan_260907.md` **L12**는 "NDX 지수+QQQ+구성종목 1분봉 (설계창 2007-2014 커버; 1분봉 이력 2000+)"로, **L15**는 "**틱은 2010+**라 설계창 하단(2007-2009)은 1분봉만"으로 적는다. 본 팩이 확인한 벤더 페이지 상 NDX 지수 1분봉 개시일은 2008-01-02 **[미검증 — 확인일·URL 미기록]**. **무료 2주 샘플로 개시일과 기기(NDX 지수 vs QQQ ETF)를 먼저 확정**하고, 결과에 따라 취득계획 L12를 정정 커밋할 것. 개시일이 2008이면 설계창 2007년분(약 250거래일)이 결손이므로 **S6-b 사전등록의 창 정의가 바뀐다** | 연구·파생물 허용(귀속), raw 재배포 금지 | **계획서 L14 기준 번들 ~$300–400 일회(문서 기록값)**. 그 밖의 구독가(연/월)는 벤더 페이지 확인값 **[미검증 — 확인일·URL 병기 필요]** | **S6-b** | 부분(V13 HAR 증분 0/9) |
| AlgoSeek / NYSE TAQ / Nasdaq ITCH / Databento / Polygon | 틱·NBBO·오더북 | TAQ·ITCH 최상 | WRDS 학술 게이트 또는 고가; Polygon 표시 금지 | 엔터프라이즈 | 없음 | 저가·표시합법·vintage-PIT 동시성 부재 |
| **OptionMetrics IvyDB US** | EOD IV 표면 1996+ | 강 | WRDS 학술 전용 | 기관 [미확인] | S6-a 대안 | 경로 없음 |
| CRSP / Compustat | 무생존편향 수익률·PIT 멤버십 | 강 | WRDS 게이트 | 기관 | S3-f(8-K 필터)·시장폭 | 접근 없음 → **필터 재정의로 우회** |
| **Fed FOMC 역사 캘린더** | 정례 회의 일정 | native(공표일) | 공공저작물 | $0 | **S3-b** | 필수. 비정례 6건 제외 필드 신설 |
| **CFTC TFF** `fut_fin_txt_YYYY.zip` | 유형별 순포지션 | **2010-12-03 backcast 절벽** — (TFF 보고서 자체 특성 — 저장소 내 근거 파일 없음 `[미검증: 원천 CFTC 공표문 URL·확인일 필요]`) | 공공 도메인. `cftc_cot_bitcoin_d0.yaml` **L81** `automated_access: permitted_subject_to_reasonable_rate_limits`, **L82** `predictive_analytics_use: permitted_for_cftc_government_content`이나 **L23 `model_use: prohibited`가 상위**로 유지(실측: L20 `enabled: false`, L21 `collector_status: prohibited_until_d0_pass`) — 승격 없이는 피처 사용 불가 | $0 | S3-h **인프라만**(수집·PIT 레인·라이브 전진). 설계창 검정은 D-9 권고에 따라 불성립 — 2010-12-03 이전 부재 + 2012-10~2014-12 사건 0 | D0 `model_use: prohibited` 승격 승인 필요 |
| **SEC EDGAR FTS**(2001+) | 8-K·S-1 이벤트 카운트 | native(accepted) | 공공, 연락처 UA | $0 | S3-f | 거래소 필터 삭제 후 유효 |
| Treasury 입찰 결과(FiscalData) | bid-to-cover·tail | 발표일 확정 | 공공 | $0 | 미배정 | 온보딩 낮음(`treasury_fiscaldata` 등록 완료). 단 **DGS2 변화 자체가 이미 V8 내생 5변량에 들어 있어** 수급 충격의 상당 부분이 endogenous — 신규 정보 증분이 작을 개연 |
| FINRA 공매도잔고·마진 | 격주 공매도잔고·월간 마진 1997+ | 공표일 captured | **D0 `blocked_legal_terms`** | $0 | — | 법적 게이트 선행 |
| AAII / UMich | 주간 심리·소비자심리 | 발표일 확정 | AAII 수동(KL 28), 재배포 [미검증] | 무료~저가 | — | V11 유형(저주파 심리) |
| Google Trends | 검색 관심 | **불가**(상대 척도·재추출) | 스크래핑 금지 | $0 | — | PIT 부적격 |
| Chicago Fed NFCI | 금융여건 105지표 | ALFRED vintage 2011-06~ | D0 `legal_review_required` | $0 | — | V9 conditionally_registered |
| BIS / NY Fed Nowcast / Philly ADS | 분기 신용·실시간 성장 | 개정·vintage 공개 [미검증] | 공공 | $0 | — | 사실상 V2 DFM·V11 P7이 덮음 |
| EPU 일간(policyuncertainty.com) | 텍스트 불확실성 | **소급 재정규화 → 설계창 부적격** | 약관 [미검증] | $0 | S3-f(captured_forward만) | 강등 |
| Nakamura–Steinsson / Bauer–Swanson 서프라이즈 | 30분 창 통화정책 충격 | 발표시각 | 학술 배포 [미검증] | $0 | S3-b 2단계 | 대안: DGS2 발표일 변화 프록시 |
| **Fed Board H.8 / H.15 원생산자** | 없음(TOTCI·TOTLL은 ALFRED, DGS는 Treasury 원본) | Board DDP는 **현행 vintage만** → ALFRED 우월(V9-D5) | 공공 | $0 | **예 — 부정결과가 덮는다**: V9_E2(+0.000043 유의 악화)·E3 무효익 | 은행 계약 §4.1 원생산자 조항은 PIT 사유로 미적용(선례 기록) |
| **Refinitiv / Bloomberg (I/B/E/S 컨센서스)** | 실적·매크로 컨센서스 이력 = 서프라이즈의 분모 | 상세 이력 타임스탬프 보유 `[미검증]` | 재배포·파생 표시 엄격 | 단말 연 수만 달러 `[미검증]` | 아니오 — 다만 1차 목표 대비 비용 불균형 | `market_consensus.yaml`은 영수증 소스만 허용, `synthetic_backfill: prohibited` |
| **Citi CESI(매크로 서프라이즈)** | 컨센서스 대비 실적 집계 | 독점·재배포 불가 | 독점 | 단말 종속 | 아니오 | 대안: Scotti (2016) 'Surprise and Uncertainty Indexes: Real-Time Aggregation of Real-Activity Macro-Surprises', J. Monetary Economics 방법론으로 보유 SPF·Cleveland 나우캐스트에서 자체 구성 `[미검증: 공개 코드 URL]` |
| **실적 캘린더 벤더** | 실적 시즌 군집·서프라이즈 | 과거 캘린더 PIT 불명 | Nasdaq.com·Zacks 약관 제한 | 유료 | 아니오 | 보유 `calendar/events.csv`(53건)는 공식 IR 일정만 |
| **브레드스 벤더(Barchart 등)** | A/D·신고가/신저가·MA 상회 비율 | PIT 구성종목 멤버십 필요 → CRSP 없이는 생존편향 | 거래소·벤더 약관 제한 | 유료 | 아니오 | dualdb 24종목 자체 구성은 표본 편향으로 불가 |
| **Kalshi·Polymarket 과거 시세** | 예측시장 대조 | 캡처 전진만, 과거 API `[미검증]` | 공개 API 약관 미기록 `[미검증]` | $0 | 해당 없음(P3 봉인, 기록 전용) | Kalshi 호가 공란 실측(2026-07-15) |
| **Nasdaq Data Link** | 대체 데이터 | 중상, 창 하단 결측 | **무료 익명 티어 약관 문서 NOT FOUND — 회색**(12-3 미사용) | 프리미엄 | 해당 없음 | 보유 FRED·Treasury와 중복, 우선순위 낮음 |

### 7-3. 구조적 공백 (검토자 우선 확인)

1. **옵션 정보집합 전무** — 지수 수준(VIX·VIX9D·VIX3M·VVIX·SKEW·VXN)만, 행사가별 IV 표면·VRP·put/call·딜러 감마 없음.
2. **일중 전무** — `data/intraday/` 디렉터리 자체가 부재.
3. **설계창 신용스프레드 불가** — HY OAS 2023+, EBP 월간·전이력 개정, NFCI vintage 2011~.
4. **심리·포지셔닝·브레드스 부재** — AAII 0행, ICI 5주, FINRA 14개월(역사 법적 차단), A/D·신고가 없음.
5. **컨센서스·서프라이즈 이력 없음** — NFP_CONSENSUS 1행, FedWatch 과거 유료.
6. **시장 일간 first-print 부재** — V2·V4는 재구성본, VIX 아카이브는 매회 전체 CSV 재다운로드.
7. **DTWEXBGS 주간 발행 SLA 구조적 stale**(KL 33).
8. **약관 긴장 미해결 3건** — FRED AI/ML·캐시(34), CBOE fair use 유보(12-5), Yahoo 자동수집(12-8). "무료 개인 티어" 논거 금지(12-7).
9. **문서 정합 결함 2건** — `source_registry.yaml`/`licenses.generated.md`의 fred_market_signals endpoint fredgraph 잔존; v5 `sources.py` fredgraph 잔존(C-3).
10. **V11 계약 파일 부재(실측)** — `data/contracts/`에 `multivariate_timeseries_v11.yaml`이 없다. V11은 진단 산출물(`data/timeseries_v11/diagnostics/`)과 판정서로만 존재하므로, 신규 계약이 V11 좌표를 승계한다고 쓸 때 **인용 대상이 계약이 아니라 진단 JSON임**을 명시할 것.

---

## 8. 통계·ML 기법 재점검

### 8-1. KEEP (현행 유지 — 계약 좌표 그대로)

| 기법 | 구현·좌표 | 유지 이유 |
|---|---|---|
| 경험 CRPS | `timeseries/backtest.py::sample_crps`, `evaluation.py::crps_ensemble` | Gneiting & Raftery (2007) proper. 폐형 O(n log n) |
| Brier·log score | `evaluation.py::brier_score`, `log_score`(eps 1e-12) | V13 계약 `scoring` |
| 정지 블록 부트스트랩 | `_stationary_bootstrap_mean_ci` mean_block **10**·B 2000·seed **19_960_107**·CI90·n<20 NaN / V5 13·2000·52026 / V6 13·5000·62026 / V11 13·2000·**20260903**(실측: `orthogonal_calm_screen.json` `block` 13 · `bootstrap` 2000 · `seed` 20260903) / V12 13·2000·20260902 / V13 `block_boot_ci` 13·2000·**20260907** | 트랙별 좌표가 다름 — 신규 계약은 어느 좌표를 승계하는지 명시. **`block_boot_ci`에는 n<20 가드가 없다** → 서브패널 사용 시 가드 신설 |
| **V9 계약 `qualification_statistics`** | ℓ = `two_times_horizon`(지평 의존) · B 2000 · seed 미기재 · mde 지평별 공표 | 부트스트랩 좌표 승계 대사표 |
| **V10 계약 `dual_statistics`** | ℓ 13주 · B 2000 · mde50 공표 | 위와 동일 |
| 쌍대 손실차(원점당 1값) | `timeseries_v8/backtest.py::paired_differences_vs_best` | 교차지평 종속 보존 |
| MDE = 1.645·se | V13 `gate.mde`, V12 `point_estimate_form` | \|Δ\|<MDE = '결정적 증거 없음' |
| Murphy 분해·캘리브레이션 곡선 | `db/queries.py::murphy_decomposition`(n_bins=10), `v_calibration_curve` | 신뢰도 보고 의무 |
| PAV isotonic(cross-fit k=5, embargo h) | `timeseries_v13/features.py::pav`, V8 B4 identity 수축 0.5 | 사전등록 fallback 있음 |
| Newton 로짓(zscore ddof0, l2 1e-3, clip) | `timeseries_v13/features.py::logit_fit` | 결정론·자유도 소 |
| y-block 순열 음성대조 | `neg_control` draws=120, 경량 부트 b=400 | 유일한 건전 귀무 |
| 델타법 band80(z=1.2816) | `features.py::block_bootstrap_cov` | 계수 불확실성이지 보정 대역 아님(표시 caveat) |
| 기준선 6종 | `_baseline_samples`: random_walk, drift_rw, ar1, gbm, historical_simulation, block_bootstrap(mean_block=min(10,h)) | 비교군 고정 |
| DM-HAC(표시 지표) | `diebold_mariano_hac`, Bartlett/NW, max_lag=ceil(h/5) | **게이트 판정 다리 아님**. Harvey–Leybourne–Newbold (1997) 소표본 보정은 **미구현**이므로 서브패널 인용 시 병기 |
| **꼬리가중 CRPS(기존)** | `src/ai_fc/timeseries_v3/backtest.py::tail_weighted_crps` (실측 L26) — 9분위 격자 `[0.01,0.05,0.10,0.25,0.50,0.75,0.90,0.95,0.99]`, 가중 `1+4|q−0.5|`, 반환 `2·가중평균(pinball)` | **대칭 가중**이라 좌측 전용이 아님. HOLD 트랙 코드지만 **재구현 불필요** — 가중함수만 교체하면 된다 |
| **pinball(기존)** | `src/ai_fc/timeseries/backtest.py::pinball_loss`(L33). 동명 구현이 `evaluation.py`(L28)·`timeseries_v3/backtest.py`(L21)에도 있어 **시그니처가 서로 다르다**(인자 순서 상이) — 재사용 시 어느 것인지 계약에 명시 | R8-D4로 **공개 제외** — 내부 판정에만 |

### 8-2. ADD (이번 사전등록에서 신규 도입 — 결과 전 커밋 필수)

| 기법 | 목적 | 근거 | 도입 조건 |
|---|---|---|---|
| **Benjamini–Hochberg FDR q=0.10** | 9셀×다피처 family | Benjamini & Hochberg (1995) 'Controlling the False Discovery Rate: A Practical and Powerful Approach to Multiple Testing', JRSS-B | family = **퇴화 가드 통과 셀만**. 저장소 미구현 → 신규 코드 + 사전등록 부록 |
| **Romano–Wolf stepdown** | 같은 부트스트랩 재표집 공유, 강한 FWER | Romano & Wolf (2005) 'Stepwise Multiple Testing as Formalized Data Snooping', Econometrica | S6-a처럼 검정 수 많을 때 BH 대안(택1 고정) |
| **Model Confidence Set(α=0.10)** | 사다리 {PB, EWMA, HAR, 신규 rung} 동등 집합 | Hansen, Lunde & Nason (2011) 'The Model Confidence Set', Econometrica | 저장소 미구현 — 공수 산정에 포함 |
| **퇴화 가드**(양 반창 min(사건, 비사건) 최소값) | 전부-0 라벨의 거짓 PASS 차단 | 본 팩 권고 2 | **전 슬롯 공통**, 결과 전 선언 |
| **사전 검정력 계획**(셀별 사건수·MDE 인쇄) | '측정된 영' 자격 확보 | V9 선례(se 4.0e-06~2.1e-05) | 전 슬롯 공통 |
| **이산 모니터링 기준선**(BGK β=0.5826 / MDD MC) | 이산화 편향으로 인한 거짓 통과 차단 | Broadie, Glasserman & Kou (1997) | S3-c·S6-a 결과 전 고정 |
| **중첩 Platt 기준선** logit[logit p_V8] | 재보정 이득 vs 정보 이득 분리 | T-A 교훈 | S6-a 필수 |
| Giacomini–White 조건부 검정 | calm vs 위기 원점 조건부 비교(표시 지표) | Giacomini & White (2006) 'Tests of Conditional Predictive Ability', Econometrica | V10 "인공물" 판정의 정식 대체 |
| **좌측 비대칭** 가중 CRPS · pinball τ=0.05 · FZ0 | 꼬리 손실 축(S3-e) | Gneiting & Ranjan (2011) 'Comparing Density Forecasts Using Threshold- and Quantile-Weighted Scoring Rules', JBES; Patton, Ziegel & Chen (2019) | **좌측 비대칭 가중 CRPS = 기존 대칭 `tail_weighted_crps`의 가중함수만 교체**(신규 구현 아님) · **pinball τ=0.05는 기존 구현 재사용, 표시 금지**(R8-D4) · **FZ0만 신규**. 셋 다 **결과 전** 손실 고정(V12 C-gate-arith 정신) |
| 최소 CRPS EMOS location-scale | MDD 깊이 분포 회귀 | Gneiting et al. (2005); Rigby & Stasinopoulos (2005) | 파라미터 ≤10, h63은 2~3 |
| interval(Winkler) score | ACI 무손상 1차 지표 | Gneiting & Raftery (2007) | S5-b |
| 시드·블록 민감도 표준 절차(ℓ∈{8,13,21}, 시드 5) | 부트스트랩 절차 민감도를 계약 좌표로 | V10 L1 임시 사용 선례 | 신규 계약 표준 부록 |
| **reliability 신뢰대** | 신뢰도 곡선의 표본 불확실성 표시 | Bröcker & Smith (2007) 'Increasing the Reliability of Reliability Diagrams', Weather and Forecasting | h63 rel≈0.08 오보정을 '점 추정 vs 대역'으로 구분하려면 필수. **저장소 미구현** |
| **PIT 정식 검정** | 밀도 예측 검정 | Berkowitz (2001) 'Testing Density Forecasts, with Applications to Risk Management', JBES | 현재는 coverage 사후 검사뿐 — **중첩 원점에서 허위 기각** caveat 병기 |
| **Christoffersen LR_uc/LR_ind (보조 지표)** | 구간 예측 검정 | Christoffersen (1998), IER; Kupiec (1995), J. Derivatives | **1차 지표 금지**(중첩 원점 허위 기각·조건부 커버리지 불가능성 — Foygel Barber et al. 2021). **표시 전용**으로만 |

### 8-3. FORBID-UNTIL-GATE (게이트 전 금지 — CLAUDE.md 연결)

| 기법 | 차단 게이트 | 비고 |
|---|---|---|
| isotonic/Platt **실보정**(LLM 원장) | 해소 **100+** | V8 B4·V13 cross-fit은 결정론 트랙 내부라 별개 |
| 앙상블 **가중 학습** 결합 | 해소 **200+** | 현재 허용은 고정 중앙값·불일치 지수·convex blend 0.75·52원점 역CRPS 가중뿐 |
| Bayesian model averaging | 해소 200+ | Hoeting, Madigan, Raftery & Volinsky (1999) 'Bayesian Model Averaging: A Tutorial', Statistical Science — **구조적 보류** |
| TSFM 파인튜닝·가중치 갱신 | 영구 금지(추론 전용) | 봉인창 오염(포스트모템 D1) 별도 |
| **DL 가격 예측 학습**(N-BEATS/PatchTST/TFT) | CLAUDE.md 하드 게이트 | 설계서 §02 — n≈2,014일·유효표본 ≈32분기로도 원천 제외 |
| market_implied **edge 활성화** | P3(해소 50+ & Brier<0.18) | 기록·표시 전용, risk-neutral 병기. 금지 대상은 **시장내재확률(Q측도)과 자체 확률을 나란히 배치해 edge로 읽히게 하는 것**이며, X1 6항이 규정한 'AI 예측(rN) ↔ 기준율' 괴리 칩은 **표시만·자동 재예측 0**으로 계속 허용된다(**두 규칙을 혼동하지 말 것**) |
| 결과 본 뒤 손실함수·기준선·문턱 교체 | 영구 금지 | V12 C-gate-arith, `gate_threshold_relaxation`, `binding_baseline_swap_after_results` |
| 홀드아웃 재적합(`holdout_refit`)·봉인 재조정(`retune_after_failure`) | 영구 금지 | 계약 명문 |
| p-순열 귀무를 음성대조로 | 영구 금지 | `p_permutation_null_as_negative_control: true` |
| 온라인 재보정(ACI)의 **판정 트랙 사용** | 사용자 DECISIONS 판정 전 | S5-b는 인프라로만 |
| 사전학습 TSFM에 §8 예외 적용 | 사용자 판정 전 | 근거 사유("사전지식 오염 없음")가 성립하지 않음 |
| **기후 단독 대비 우월만으로 챔피언 지정** | 영구 금지 | `multivariate_timeseries_v13_vol.yaml` **L134** `champion_on_climatology_alone: true` — 자명 기준선(PB류)을 반드시 함께 둔다. rung-3가 EWMA의 스킬을 '당일 수준 지속'으로 환원시킨 이유 |
| **홀드아웃 패널에 봉인 바이트 반입** | 영구 금지 | 같은 계약 **L136** `sealed_bytes_in_holdout_panel: true`(홀드아웃 패널에 2019+ 관측 미열람) |

### 8-4. 런타임 정합 경고

- pages 빌드(`.github/workflows/pages.yml` L44)는 `numpy scipy Pillow`+pydantic류만 → 표시 계층(`timeseries_v8_display.py`, `timeseries_v13_vol_display.py`)은 numpy/scipy 전용. V13 `features.py`가 "numpy만"으로 도구 수식을 1:1 재현하는 이유. **신규 카드도 이 제약을 승계**.
- extras: `timeseries` = pandas>=2.2,<3 + **statsmodels==0.14.6**(버전 불일치 시 fail-closed, `timeseries_v2/contracts.py`); `timeseries-v5` = scikit-learn; `ml` = torch/transformers/chronos.
- 봉인 runtime 영수증: python 3.12.10, numpy 2.5.2, pandas 2.3.3, scipy 1.17.1, statsmodels 0.14.6.
- **로컬 실측(2026-09-08)**: numpy 2.4.3, scipy 1.17.1, **pandas 3.0.1(핀 `<3`과 불일치 — 봉인 재현 시 확인 필요 [미검증])**, statsmodels 0.14.6, sklearn 1.8.0, torch 2.13.0+cpu, chronos 2.3.1, duckdb 1.5.5, **arch 미설치**(V13 GARCH-t rung 미실행 사유).

---

## 9. 거버넌스·검증 프로토콜

### 9-1. 표준 파이프라인

```
[-1] G0 무손상 대사 — V8/V2 봉인 sha e3ff2fdb…, V8 원장 b9c492be…,
     V13 계수 3자 핀 1a857850… 일치 확인 + V8 store 쓰기 0 검증
     (multivariate_timeseries_v12.draft.yaml L410 G0_crps_no_damage, hard: true,
      실패 시 계약 아래 모든 평가 무효). 실행 전·후 2회.
      ↓
[0] 새 계약 ID 개설 (V13·V8 계약 무접촉)
      ↓
[1] 사전진단 (T0, 백테스트 0회) — 셀별 사건수·에피소드 수·MDE·기저율 산출
      ↓
[2] 사전등록 커밋 (결과보다 선행) — 피처 정의·split·l2 고정·손실함수·기준선·퇴화 가드·
    family 정의·다중검정 절차·예산·stop-loss·부호 기대·조건부 finalist 규칙
    말미: 사전등록 커밋 해시를 계약 revision_history에 기록(V12 선례 커밋 ec496463).
          새 원장은 data/contracts/ledger_registry.yaml 에 등록.
      ↓
[3] 설계창 2007–2014 양방향 (early 2007–2010 ↔ late 2011–2014)
      쌍대 통계량 → 정지블록 부트스트랩 CI90 → y-block 귀무 → MDE 병기
      → 상위5% 원점 제거 부호 유지 → BH/RW → MCS 보고 → Murphy 분해
      → 6렌즈 적대 검증(독립 재현·vol직교·표본외 전이·교란 통제·다중검정 위양성·
        국면 제거 민감도. V10에서 GFC 78원점(18.7%)이 델타 83.8%를 견인함을 잡아낸 절차)
        — GFC 원점 제거·상위 5% 제거 후 **부호 유지**가 채택의 필요조건
      ↓
   [3x] stop-loss 발동 → 부정결과 계약 등록(status: negative_result_draft,
        gates.armed: false, evaluated_candidates: 0)과 판정서 T1 산출.
        V12 선례를 형식으로 승계 — 결과를 본 뒤 문턱·손실·기준선을 바꾸는 대신
        **축을 닫고 기록한다**.
      ↓  (채택 셀 발생 시에만)
[3b] 독립 재계산 — 별도 스크립트·별도 실행자로 쌍대 통계량·CI·귀무를 재산출하고
     부호·크기 일치를 확인한다(docs/review/V9_V10_V11_INDEPENDENT_VERDICT.md 선례:
     5쌍 개선 0·최대|Δ| 4.33e-05 / 채택 0/12·순열 p=0.118 / D7 조합 격자 정정).
     불일치 시 후보는 [4]로 진행 불가.
      ↓
[4] finalist 사전등록 (결과 전) → **사용자 명시 승인 원문** → 홀드아웃 1회 → 원장 append
      ↓
[5a] T2 진입 — 게이트 무장 + G0 무손상 + **사용자 승인 → approvals.jsonl append**
     (V13 선례 실측: V13-D4 r2 executed_at gates_armed 2026-09-08T14:54:04+09:00,
      display_tier_t2 동시각대; 승인 원장 7행, r2가 r1의 합성 시각 15:05:00을 정정)
      ↓
[5b] T3 전환 — X1 이름충돌 6항 해소 + caveat lead 굵게 + read-model 키 분리 확인
     + 승인 원장 append (V13 선례: display_tier_t3 2026-09-08T14:58:03+09:00)
     주: multivariate_timeseries_v13_vol.yaml L257
         display_tiers_allowed: [t0_internal, t2_hidden_panel, t3_live_card] —
         **t1 값이 존재하지 않는다**. 신규 계약이 T1(문서·리뷰팩)을 tier로 쓰려면
         t1_docs 를 계약에 **정의**하거나, 문서 단계는 tier 밖 절차로 취급한다고 명기할 것.
      ↓
[5c] base rate 배선(표시만) + 라이브 전진 게이트 무장
     (셀당 성숙 원점 60, 자동 강등·재무장 없음)
      ↓
[6] 라이브 전진 축적 (V13 셀 60 / V8 섀도 126)
      ↓
[7] 신규 버전 봉인 1회 + 사용자 사인오프 → (C5 충족 시) T4 논의
    말미: cd src && python -m ai_fc sync --check 불변성 검사 + inventory 재생성
          (verify drift 방지) + 리뷰팩 outputs/review-packs/<NAME>/ + .zip.sha256 산출.
          forecasts/·calibration/ 무수정 확인.
```

### 9-2. 사전등록 문서의 필수 항목 체크리스트

1. 계약 ID·상속 관계·무접촉 선언(V13 계수 3자 핀, V8/V2 봉인 sha, 원장 append-only).
2. 표적 정의(K·θ·h·배리어·라벨 기준점 — 원점 대비인지 러닝맥스 대비인지 **명시**).
3. 정보집합·피처 정의식·PIT 규칙(`available_at ≤ origin`, first_publication_date 가드, backfill 금지).
4. 기준선(자명 기준선 포함)과 그 **명세**(이산 보정 여부, λ, 중첩 Platt).
5. 창·split·서브창 프로토콜(V9-D7 승계 시 `baseline_rerun_required`·`mde_republication_required`).
6. 손실함수(결과 전 고정)와 채점 규칙.
7. 불확실성 좌표(ℓ, B, seed, CI 수준)와 **n 최소 가드**.
8. 음성대조: y-block(ℓ=13) + (해당 시) 처치 라벨 블록 순열. p-순열 금지 명문.
9. **퇴화 가드**: 셀별 최소 사건·비사건 수, 미달 시 `untestable_by_construction`.
10. 사전 검정력 계획: 셀별 MDE와 기대효과의 비교표.
11. 다중검정: family 정의·BH q 또는 RW·MCS.
12. 예산(dev 상한)·stop-loss 규칙.
13. 조건부 finalist 규칙(결과 후 고르지 않도록 기계적으로).
14. 정점지식 caveat(문턱·창·split·블록길이 선택).
15. 표시 계획(T0/T1/T2/T3)과 caveat 문구, risk-neutral·프록시 병기.
16. 자원 회계(dev n/N, holdout n/3, sealed n/1)와 **홀드아웃 순서 caveat**.
17. **재현 좌표**: python·numpy·pandas·scipy·statsmodels 버전 영수증(봉인 기준 3.12.10 / 2.5.2 / 2.3.3 / 1.17.1 / 0.14.6), `seed_rule`(V8 `sha256_model_version_and_as_of`), 계약 해시·`model_code_hash`. **로컬 pandas 3.0.1이 핀 `<3`과 불일치**하므로 실행 전 확인(D-16).

### 9-3. 다중검정 통제 설계

- **트랙 내부**: family = 퇴화 가드 통과 셀 × 피처. BH q=0.10 기본, 상관 강한 셀 구조에서는 Romano–Wolf stepdown(같은 부트스트랩 재표집 재사용).
- **사다리 내부**: MCS(α=0.10)로 동등 집합 보고 — 채택 판정은 여전히 쌍대 CI90.
- **트랙 간 누적**: 설계창 2007–2014는 V8(dev 12)·V9(7)·V10(12)·V11(**48검정** — 각주 참조)·V12(8셀×2방향)·V13(9셀×3rung)로 이미 누적 채굴됐고, 저장소에 SPA/MCS/트랙 간 FWER 보정은 **존재하지 않는다**. 신규 계약은 둘 중 하나를 **결과 전에** 택해 명문화한다: **(i)** family를 트랙 내부로 한정하고 '트랙 간 누적 스누핑은 미보정'임을 판정서에 상시 인쇄한다, 또는 **(ii)** White (2000) Reality Check / Hansen (2005) SPA를 S3 전 슬롯 통합 family에 적용하고 부트스트랩 재표집(ℓ=13, B=2000, seed 고정)을 슬롯 간 **공유**한다. (ii)는 슬롯 간 원점 정렬이 전제이므로 구현 공수를 예산에 계상할 것.
- **보고 의무**: 통과 셀 수 k와 family P(k≥k_obs)(독립가정 이항 근사임을 caveat) 병기.

> **각주 (V11 검정 수)**: 판정서 `outputs/timeseries_v11/reports/V11_FREEZE_DECISION_20260903.md` L11은 "9개 후보 프록시 × 3지표 × 2수평선 = 54검정", L38은 "4/54"로 적혀 있으나, 진단 산출물 `data/timeseries_v11/diagnostics/orthogonal_calm_screen.json` 실측은 **`tests` 48행 · 프록시 8종(P1, P2, P3, P5, P6, P7, P8, P9 — P4 부재) · `passing` 4 · `verdict` PROCEED_TO_ADVERSARIAL_VERIFY**다. 판정서는 불변 파일이 아니므로 정정 커밋 가능(D-13 ①). 단 순열 귀무 P(≥4)=0.25~0.32가 **48 기준인지 54 기준인지는 `[미검증]`** — 재확인 후 함께 기재할 것.

### 9-3b. 현재 자원 잔량 (2026-09-09 실측)

| 트랙 | dev | holdout | 봉인 | 근거(실측 좌표) |
|---|---|---|---|---|
| **V8** | **12/24** | **1/3 소모**(E10) | **1/1 소모**(disclosure #1, R8-D2) | 계약 L155 `maximum_development_evaluations: 24`, L108 `maximum_disclosures_per_model_version: 1`; 원장 `development_experiments.jsonl` 12행 · `holdout_scorings.jsonl` 1행 · `sealed_evaluations.jsonl` 1행. 섀도 승격 원점 **2/126**(`shadow_forecasts`·`shadow_resolutions` 각 2행) |
| **V9** | **7/24** | **0/3** | 0 (동결) | 계약 L184 max 24 · L186 holdout 3; 원장 7행 |
| **V10** | **12/24** (stop-loss) | **0/3** | 0 (동결) | 계약 L116 max 24 · L118 holdout 3; 원장 12행 |
| **V11** | 백테스트 **0** | **0** | 0 | **계약 파일 없음** — 진단 JSON(48검정)과 판정서만 |
| **V12** | `evaluations_spent: 0` · 개시 시 `evaluations_spent_on_open: 4` 계상(**잔여 20**) | **0** | 0 | draft 계약 L585–587 |
| **V13-VOL** | **3/8** | **0/3**(finalist `V13VOL_champion_aec80c65038b` **1개 사전등록**) | 0 | 계약 L77–78 · L85; 원장 `vol_experiments.jsonl` 3행 · `approvals.jsonl` 7행 · `vol_live.jsonl` 2행 |

- **봉인 바이트**: V8+V2 `e3ff2fdb64ac71c0f05ae8e4508ef1c5a7c8fba7b78d81548918881032c8d224` 0바이트 변경(v12 draft L170) · V8 원장 `b9c492be276f684832aac373f80252b305cee980d4312ba3d1e5a707b04bf803` 일치(L172).
- **`model_code_hash` 정정(중요)**: **V8 계약(L36)의 값은 `bb225cbf963b095271452a669f7d8f1aa5eb29c8abda5a4ae1ed9ecd1d702c5c`이며, `8361899fd797…`는 V9 계약 L39·V10 계약 L37의 값이다**(실측). 두 값을 혼동해 인용하지 말 것.
- **V13 계수 핀**: 현행 sha256 `1a85785056738775f732531dc442616908e20ca0f356187eb5fd1adb614b3ac1`(파일 실측 = 계약 L248), 이전 `51815bde…`(계약 L298, 반창 대사 max|Δ| 2e-15, p 무변경).
- **캠페인(V9~V13) 비가역 행동 누계: 0**.

### 9-4. 승인 규약

| 결정 | 형식 | 근거 |
|---|---|---|
| 홀드아웃 1회 소모 | 사용자 명시 원문 (예: `V13-D3 홀드아웃 1회 소모 승인 finalist=V13VOL_champion_aec80c65038b`) | `holdout_execution_path: absent_by_construction` |
| 봉인 공개 | 사용자 사인오프(R8-D2 형식) + `maximum_disclosures_per_model_version: 1` | 재조정 금지 |
| 구매·질의 발송 | 사용자 결정(V12-D4, FR-1) | 취득 ≠ 트랙 개시 |
| D0 소스 승격(model_use) | 별도 승인된 S1 변경 | `cftc_cot_bitcoin_d0.yaml` 활성화 게이트 |
| Phase 전환 | 사용자만 | CLAUDE.md |
| main 푸시 | GOV-1 우회 금지 | 리프스펙 FF 사고 2회 |
| **base rate 배선(표시만)** | **사용자 결정 V13-D6** | 홀드아웃 PASS 셀 한정 원칙과 caveat 유지 여부를 함께 승인 |
| **신규 카드의 자동화 체인 편입** | **사용자 승인** | `timeseries-v2-refresh`(화~토 01:35 UTC) → `v8-shadow`(03:10) → `v13-vol-live`(03:40) → pages/verify `workflow_run` 연쇄에 끼워 넣는 것은 **배포 행위** |
| **부정결과 계약 상태 전환** | **사용자 승인** | `negative_result_draft` → 확정 |

### 9-5. 표시(T-사다리) 정직성 규약

- read-model fail-closed: 게이트 하나라도 어긋나면 숫자 제거 + 사유, 마지막 값 재사용 없음.
- 카드별 read-model 키 분리(가격 카드 ↔ V13 vol 카드 결합 금지). 신규 카드도 별도 키.
- caveat lead 굵게 상시('홀드아웃 미검증 · 참고 의견 — 매매 신호가 아닙니다').
- 이름충돌 6항(X1) 승계: '기준율' 명칭, 모델 배지, 지평 단위 '영업일', AI 예측과의 괴리는 **표시만**.
- R8-D4 비공개 지표(방향 적중률·pinball·first_touch)를 새 카드가 우회 공개하지 않을 것.
- CBOE 파생값 표시 확대는 `docs/cboe_permission_request_draft.md` 발송·회신 후.
- **게이트 닫힘 시 처리는 두 선례가 다르다**: V13 카드는 마지막 값 재사용 없이 HOLD+사유(fail-closed), 시나리오 V5.2는 `display_promotion.yaml` B안으로 `stale_last_valid` + 기준일 + 사유 공시. **신규 카드는 어느 쪽인지 계약에 명시**할 것(권고: fail-closed).
- **원점 경과 2단 임계**(`origin_age_policy` warn 1 / hold 10 거래일)와 **입력 신선도**(48h, DTWEXBGS 216h) 규칙을 승계할지 명시. 주말·월요일 자연 HOLD를 '고장'으로 오독하지 않게 카드에 문구를 둘 것.
- **공개 범위 분리(R8-D4)**: 개발기간 포함 전체창과 표본외 창을 **분리 공시**하고 표본외 창 자체 판정을 인쇄한다.

---

## 10. 열린 질문과 결정표

| # | 질문 | 선택지 | 권고 |
|---|---|---|---|
| **D-1** | V13-D3 홀드아웃 1슬롯을 **지금** PB finalist에 쓰나? | (a) 지금 소모 (b) **S3-a 결과 후** 더 나은 finalist와 함께 판단 (c) 영구 보류 | **(b)**. PB를 먼저 소모하면 2015–18의 동일 라벨 셀별 Brier가 공개돼 후속 finalist의 홀드아웃이 준청정이 된다. S3-a가 3~5일이므로 대기 비용이 작다 |
| **D-2** | V13-D6 EXIT base rate 배선을 홀드아웃 전에 하나? | (a) 홀드아웃 PASS 후 (b) **'홀드아웃 미검증' caveat 유지한 채 지금 배선** (c) 미배선 | **(b)**. 배선은 표시만·산술 결합 0이며 라이브 전진 게이트(성숙 원점 60) 무장이 C1 시계를 앞당긴다 |
| **D-3** | CBOE DataShop 질의(V12-D4) 발송 시점 | (a) **지금 발송** (b) S3-a 후 (c) 미발송 | **(a) 발송, 구매는 (b)**. 리드타임 독립·비가역 아님. 질의에 §2b 파생표시 조건·2007–2014 Calcs 소급 커버리지·일회 이력가를 명시 요청 |
| **D-4** | FirstRate(FR-1) ~$300–400 집행 | (a) 지금 (b) **S3-d + rv 셀 VIX_t 스크린 후** (c) 미집행 | **(b)**. **무료 2주 샘플로 개시일(2000 vs 2008)과 기기(NDX 지수 vs QQQ)를 먼저 확정**한다. 취득계획 L12(1분봉 2000+·설계창 전구간 커버)와 본 팩이 본 벤더 페이지(2008-01-02 개시 [미검증])가 충돌하므로, 샘플 결과에 따라 **L12를 정정 커밋**하고 S6-b 창 정의를 재작성한다 |
| **D-5** | `calendar_sources.yaml` L4 `probability_linkage: forbidden`의 범위 | (a) 표시층 규칙만(수치모델 공변량 허용) (b) 수치모델까지 금지 | **(a) + 계약 문구 명확화**. grep상 이 키는 계약 자신 외 참조 0건이고 근거 문서는 조회 카드 문구 규칙이다. 다만 S3-b 착수 전 명문 개정 권고 |
| **D-6** | V12 `reopen_protocol.only_path = 다른 데이터` 와 S3-c/S6-a의 관계 | (a) −10%·417원점·split 2010-12-31 재사용 금지(다른 데이터만) (b) 새 표적·새 통계량이면 허용 (c) 표적 A 자체를 base rate로만 | **(c)를 기본, (b)는 명시 판정 시에만**. 근거: `multivariate_timeseries_v12.draft.yaml` L602–608은 `only_path: 다른 데이터` **외에** `preconditions_all_required`로 **P1(V12-D1 트랙 개시 + V12-D4 승인) · P2(검정 기계 수리 — 수리된 기계가 새 음성대조를 결과 보기 전에 통과, 기준 pooled 통과율 ≤0.10 **AND** 셀별 ≤0.05) · P3(새 사전등록) · P4(새 데이터의 PIT·영수증 등급 충족) · P5(V8/V2 봉인 해시 무변경)** 전부를 요구한다. **T-A가 NOT_REPAIRED(N-p-block 0.201)로 끝났으므로 P2가 미충족**이며, 이것이 (b)안을 사실상 봉쇄한다. `post_hoc_hypotheses_on_same_sample` 금지와도 충돌 소지가 있어 사용자 판정이 선행돼야 한다 |
| **D-7** | `V12B_PARKED_20260908.md` 재개조건 ①(일중 확보) vs 취득계획 §5(일중 불필요)의 **내부 모순** | (a) 파킹 문서 우선(구매 후 재개) (b) **취득계획 우선(ℓ_z 팔은 $0로 지금)** | **(b)**. 인용 원문 — 취득계획 §5 **L40**: "**V12b(T-B): 경로 생성기 검정에 일중이 필수는 아님(일간 잔차 재표집 구조 문제) — FirstRate는 사건(배리어 터치)의 일중 실현 검증용 보조**". ℓ_z 사전 기대가 이미 P1 진단으로 고정됐고, 일중이 필요한 것은 사건의 일중 실현 검증(보조)뿐이다. 결정 시 파킹 문서를 개정 커밋으로 정정 |
| **D-8** | 사전학습 TSFM(Chronos)·FinBERT에 §8 예외를 적용하나? | (a) 적용(추론 전용이므로) (b) **불적용**(예외 근거가 '사전지식 오염 없음'인데 코퍼스 오염 가능) (c) T0 상한 조건부 적용 | **기본은 (b) 불적용**(§8 예외의 근거가 '사전지식 오염 없음'인데 코퍼스 오염 가능성이 이를 무너뜨린다). **(c)는 사용자가 명시 판정한 경우에만** 가능하며, 그때도 T0 상한·오염 caveat 상시·홀드아웃/봉인 무접촉·체크포인트 sha·라이선스 영수증 커밋이 조건이다. 현 API로는 경로 표본이 불가하므로 실무적으로는 보류. (§8-3의 "사용자 판정 전 금지"와 이 권고는 동일한 규칙이다) |
| **D-9** | CFTC D0 `model_use: prohibited`(L23) → S1 승격 | (a) 승격(설계창 2010-07+ 한정) (b) **인프라만 구축(수집·PIT 레인·라이브 전진), 모델 사용 보류** (c) 미착수 | **(b)**. 2010-12-03 backcast 절벽과 2012-10~2014-12 사건 0으로 설계창 검정이 성립하지 않는다. 인프라 가치는 온전히 남는다. (§7-2의 '필요한 방향' 칸도 **S3-h 인프라만**으로 일치시킬 것) |
| **D-10** | 설계창을 1997–2014로 확장할 수 있나(S3-g 등 사건 희소 표적) | (a) 불가(관례 유지) (b) **새 계약 ID에 한해 가능, 정점지식 caveat + V8 계보 관례 이탈 명기** (c) 사안별 | **(b)**. V2 아카이브는 NASDAQCOM 1995~·VIX 1990~을 보유한다. 단 확장은 표적별로 사전등록에 근거를 적고, 확장 창에서 얻은 결과를 2007–2014 결과와 섞지 말 것. **선행 조건**: VIX OHLC 아카이브의 1990~1991 결측 여부 확인(§7-1) |
| **D-11** | 꼬리 분위수·MDD 등 신규 지표의 T3 표시 (R8-D4 비공개 정책과 충돌) | (a) T1 종료 (b) **별도 카드로 T3 허용하되 R8-D4 지표는 여전히 비공개** (c) 전면 공개 | **(b)**. MDD 깊이 base rate는 EXIT 룰 조기경보로 가치가 있으나, 방향 적중률·pinball·first_touch는 계속 비공개 |
| **D-12** | 새 계약 ID 명명 — `v14` 충돌 | (a) `v14` 사용 (b) **역할 기반 ID**(`event_probability.volatility_v14_shape`, `derived.drawdown_depth_v14`, `event_probability.calendar_v14` 등) | **(b)**. `V12B_PARKED_20260908.md`가 `v14`를 V12b 재개용으로 언급한 이력이 있어 숫자 단독 ID는 충돌한다 |
| **D-13** | 문서 결함 정정 커밋 | (a) 나중에 (b) **S3 사전등록과 동시** | **(b)**. ① `V11_FREEZE_DECISION_20260903.md` L11 '9개 후보 프록시 × 3지표 × 2수평선 = 54검정' → '**8개 프록시 × 3지표 × 2수평선 = 48검정**(진단 산출물 `data/timeseries_v11/diagnostics/orthogonal_calm_screen.json` `tests` 48행·프록시 8종, P4는 미실행)', L38 '4/54' → '**4/48**(직교통과 36셀 중 4)'. **불변 파일이 아니므로 정정 커밋 가능**하나, 순열 귀무 P(≥4)=0.25~0.32가 48 기준인지 54 기준인지는 `[미검증]` — 재확인 후 함께 기재할 것. ② `source_registry.yaml`/`licenses.generated.md` fredgraph→공식 API, ③ v5 `sources.py` fredgraph 잔존(C-3), ④ `classical-8` 계열의 "포지셔닝 0회 등록" 서술 정정, ⑤ 취득계획 L12 커버리지(D-4 샘플 결과 반영) |
| **D-14** | `block_boot_ci`의 n 최소 가드 신설 | (a) 현행 유지 (b) **n<20 NaN 가드 추가**(`_stationary_bootstrap_mean_ci`와 동형) | **(b)**. 서브패널(FOMC 33/34 원점 등)에서 CI가 조용히 반보수적으로 나온다 |
| **D-15** | SOX(NASDAQSOX) `model_use: prohibited` 완화 | (a) 유지 (b) 완화 | **(a) 유지**. 애초에 이 금지는 `statistics_lab_v1.yaml` **계약 전역(L3–L5)**이라 SOX 단독 완화가 아니라 **49 시리즈 전체 정책 변경**을 뜻한다. 후보 방향(infoset-7)이 보류이고 지수 중첩 문제로 정보 가치도 낮다 |
| **D-16** | pandas 3.0.1 로컬 vs 핀 `<3` 불일치 | (a) 방치 (b) **봉인 재현 경로에 3.x 검증 또는 2.3.x 고정** | **(b)**. 봉인 replay 요구 시 fail-closed 위험 [미검증] |

### 10-b. 승인 원문 템플릿 (사용자가 그대로 붙여넣는 문자열)

- **D-1**: `V13-D3 홀드아웃 1회 소모 승인 finalist=<ID>` — 보류 시: `V13-D3 보류 — S3-a 결과 후 재판단`
- **D-2**: `V13-D6 base rate 배선 승인 — 표시만, 홀드아웃 미검증 caveat 유지`
- **D-3**: `V12-D4 CBOE DataShop 질의 발송 승인 (구매 아님)`
- **D-4**: `FR-1 FirstRate 집행 승인 금액=$___` / 또는 `FR-1 보류 — 무료 샘플 선검증`
- **D-5**: `D-5 판정 — (a) 표시층 규칙만, calendar_sources.yaml 문구 개정 승인` 등 택1
- **D-6**: `V12 reopen 판정 — (c) 표적 A는 base rate 전용` 등 택1
- **D-7**: `D-7 판정 — (b) 취득계획 우선, V12B_PARKED 개정 커밋 승인` 등 택1
- **D-8**: `TSFM §8 예외 판정 — (b) 불적용` 등 택1
- **D-9**: `CFTC D0 인프라만 승인, model_use 승격 보류`
- **D-10**: `설계창 확장 승인 — 계약 ID <ID> 한정, 2007–2014 결과와 혼합 금지`
- **D-11**: `D-11 판정 — (b) 별도 카드 T3, R8-D4 지표 비공개 유지`
- **D-12**: `D-12 판정 — (b) 역할 기반 ID 채택`
- **D-13**: `D-13 정정 커밋 승인 — ①~⑤ 동시`
- **D-14**: `D-14 승인 — block_boot_ci n<20 가드 신설`
- **D-15**: `D-15 유지 — statistics_lab_v1 전역 model_use: prohibited 불변`
- **D-16**: `D-16 승인 — 봉인 재현 경로 pandas 2.3.x 고정`

---

## 11. 설계도 작성 지침 (외부 검토자에게)

### 11-1. 설계도가 반드시 담아야 할 것

**(A) 프로그램 지도**
1. S0~S8 단계 정의와 각 단계의 **진입 게이트·종료 게이트**(위 3장 승계, 필요 시 재분할·재명명 가능하나 C1~C5 완결 조건은 유지).
2. 단계 간 의존 그래프 + **비가역 자원이 어디서 소모되는지** 표시(§9-3b 잔량표를 기준선으로 인용).
3. 각 단계의 달력 시간·비용·승인 필요 여부.

**(B) 슬롯별 사전등록 초안(최소 S3-a·S3-b·S3-c·S3-d 4종)**
각 슬롯마다 9-2의 **17항** 체크리스트를 채운 **사전등록 문서 초안**. 특히:
- 표적 정의에서 라벨 기준점(원점 대비 vs 러닝맥스 대비)을 명시할 것.
- 자명 기준선과 그 명세(이산 보정·λ·중첩 Platt)를 **결과 전 고정**할 것.
- 퇴화 가드의 수치 문턱(예: 양 반창 각각 min(사건, 비사건) ≥ N)을 제시할 것 — N 값 선택 근거를 적을 것.
- 셀별 MDE 산출 방법과 기대효과 비교표의 양식을 제시할 것.
- family 정의와 BH/RW 중 택1을 고정할 것.
- **S3-a 초안 서두에는 §7-1 V4 행의 '선례 고지'를 그대로 옮길 것** — V4/V5 hold와 V9 E5/E6 무효익(장기 +0.000006 [−0.000008,+0.000021], 단기 h1+h5 **+1.65%** 악화)을 인용하고, 새로움이 **표적 교체에만 있고 정보집합에는 없다**는 비대칭을 명문화하며 기대효과를 하향한다.
- **각 슬롯 초안은 종료 조건 표를 포함한다**: 열 = [셀, 사건수, 기대효과(문헌·선례 근거), MDE=1.645·se, 판정('개선'·'측정된 영'·'검정력 부족')]. **MDE가 기대효과를 덮는 셀에서만 null을 '측정된 영'으로 부를 수 있고**, 덮지 못하면 그 셀은 '검정력 부족'으로 기록해 **축을 닫지 않는다**(V9의 se 4.0e-06~2.1e-05 선례가 자격 기준).

**(C) 구현 계약 초안**
- 새 계약 YAML의 골격: `status`, `data_policy`(series·PIT 등급·available_at 규칙·first_publication_date 가드), `model_ladder`, `gate`(bidirectional_transfer·uncertainty ℓ/B/seed·mde·multiplicity), `prohibitions`(p_permutation_null_as_negative_control, post_hoc_target_addition, gate_threshold_relaxation, holdout_refit, binding_baseline_swap_after_results, **champion_on_climatology_alone, sealed_bytes_in_holdout_panel**), `budget`(maximum_development_evaluations·holdout_maximum_finalists), `display_tiers_allowed`(t4 없음 — **t1 값도 현행 V13 계약에 없으므로 쓰려면 `t1_docs`를 정의**), `known_limits`.
- 원장 스키마(`*_experiments.jsonl`, `*_holdout_scorings.jsonl`, `approvals.jsonl`)와 `ledger_registry.yaml` 등록 항목.
- 표시 계층 제약(pages 빌드 numpy/scipy 전용, read-model 키 분리, fail-closed 가드).

**(D) 데이터 작업 명세**
- 신규 파서(VIX OHLC), 신규 스토어(발표 캘린더 역사 행), 신규 등급(`vendor_eod_archive`, `reconstructed_with_2010_vintage_classifications`, '소급 산출 지수') 정의.
- 영수증 스키마와 sha256 캡처 규약, raw gitignore 경계.
- 구매 대상별 사양 요청서(무엇을 물어야 하는가: Calcs 소급 여부, 일회 이력가, §2b 조건, 1분봉 커버리지·기기·**개시일**).
- **등급 신설 절차**: 신규 PIT 등급(`vendor_eod_archive` 등)을 만들면 `multivariate_timeseries_v2.yaml` `data_policy`의 기존 3등급(native_pit / reconstructed_market_archive / captured_forward)과의 관계를 정의하고, **`reconstructed_archive_is_native_pit: false`에 상응하는 자기부정 필드**를 반드시 둔다. 등급 신설은 **계약 개정 커밋 + 자산표 갱신 + `licenses.generated.md` 재생성까지가 한 단위**다.

**(E) 결정 요청서**
- 10장 결정표를 사용자 서명 가능한 형태로 정리 — **§10-b의 승인 원문 템플릿을 그대로 포함**한다.

**(F) 리스크·중단 조건**
- 슬롯별 stop-loss와 그 발동 시 기록 형식(부정결과 계약 형태 — 파이프라인 `[3x]`).
- "측정된 영"으로 축을 닫을 자격 조건(MDE가 기대효과를 덮었는가).
- 사후 완화 금지 목록(손실함수·기준선·문턱·λ 교체).

**(G) 비용 계획**
- 슬롯당 **서브에이전트 1~4개 이내**(CLAUDE.md 비용 가드레일), 토큰·API 예산 상한, 질문당 $1.5~4 목표(설계서 §09).
- **'토큰비용 높은 배치는 지시 후 실행'** 관례 — 예측 배치·서브에이전트 팬아웃은 자동 실행하지 않고 제안 후 지시를 기다린다(로컬 결정론 수치모델은 예외).

### 11-2. 설계도가 하지 말아야 할 것

1. **저장소 수치 창작 금지.** 인용하는 모든 수치는 이 팩 또는 저장소 파일에서 온 것이어야 하며, 새로 계산한 값은 **계산 스크립트 경로와 함께 '검토용 진단, 원장 미기록'임을 명시**할 것(§7-1 VIX OHLC 행이 그 형식의 본보기).
2. **홀드아웃·봉인 창 열람 금지.** 기저율·사건수 산출도 설계창에 한정. 불가피하게 열람했다면 사전등록에 공시(infoset-7 검수의 2015–18 기저율 0.0457 열람 사례가 선례).
3. **결과를 본 뒤 기준 조정 금지.** 특히 약한 2Φ·λ=0.99 선택, 손실함수 교체, 셀 사후 제외.
4. **V13 계약·계수·라이브 카드 개정 금지.** 신규 rung은 새 계약 ID로. 계수 3자 핀을 건드리면 T3 카드가 HOLD로 fail-close된다. **무접촉 선언에는 실제 값을 박아 넣을 것**: V13 `champion_coefficients.json` sha256 `1a85785056738775f732531dc442616908e20ca0f356187eb5fd1adb614b3ac1`(이전 `51815bde…`, p 무변경) · V8/V2 봉인 sha256 `e3ff2fdb64ac71c0f05ae8e4508ef1c5a7c8fba7b78d81548918881032c8d224` · V8 원장 `b9c492be276f684832aac373f80252b305cee980d4312ba3d1e5a707b04bf803` · **V8 계약 `model_code_hash: bb225cbf963b095271452a669f7d8f1aa5eb29c8abda5a4ae1ed9ecd1d702c5c`**(V9/V10 계약의 `8361899f…`와 다른 값이므로 혼동 금지). 신규 계약은 이 값들을 `source_pins`로 복사해 넣고 **실행 전후 대사**한다.
5. **매매 신호 어휘 금지.** 모든 산출은 '기준율·참고 의견'. **시장내재확률(Q측도)과 자체 확률을 나란히 배치해 edge로 읽히게 하지 말 것**(P3 전). 단 X1 6항의 'AI 예측(rN) ↔ 기준율' 괴리 칩은 **표시만**으로 허용되며, 이는 별개 규칙이다.
6. **문헌 과대 인용 금지.** 논문 존재와 효과 전이를 구분할 것 — 이 팩에서 확인된 오적용 사례(Johnson 2017의 slope=프리미엄, Kelly & Jiang 2014의 횡단면 Hill, Lou/Polk/Skouras 2019의 기대수익, Rapach et al. 2016의 현물 공매도잔고, Martin 2017의 기대수익 하한, McNeil–Frey 2000의 1-step, Cheng et al. 2015의 역인과)를 반복하지 말 것.

### 11-3. 설계도의 판단 기준(자기 점검)

설계도가 완성됐는지 다음 8문으로 점검한다.

1. 각 슬롯에서 **어떤 결과가 나오면 축이 닫히는가**가 사전에 명시돼 있는가? 그 null이 검정력을 갖는가(MDE 표가 있는가)?
2. 각 슬롯의 **자명 기준선**이 무엇이며 그 명세가 결과 전에 고정돼 있는가?
3. 퇴화 가드가 모든 셀에 적용돼 있으며, 제외된 셀이 family에서도 빠졌는가?
4. **비가역 자원**(홀드아웃·봉인·구매)이 $0 스크린 뒤에 배치돼 있는가? 홀드아웃 순서 caveat가 적혀 있는가?
5. V13·V8·V2의 어떤 파일도 수정하지 않고 실행 가능한가? 새 계약 ID·새 원장·read-only 포크로 닫혀 있는가?
6. 산출물의 **표시 경로**(T0→T1→T2→T3)와 각 단계 승인·caveat가 정의돼 있는가? T4가 구조적으로 차단돼 있는가?
7. C5(P3 게이트, 현재 9행/5문항 → 45문항 부족)에 대해 설계도가 **무엇을 하는가 또는 하지 않는가**가 명시돼 있는가? 수치모델 트랙이 완벽해도 C5 없이는 T4가 열리지 않는다는 비대칭이 문서화돼 있는가?
8. 인용한 각 논문에 대해 **'존재'와 '이 표적으로의 전이'가 구분**돼 있는가? 6장이 확정한 오적용 목록(Johnson 2017의 slope=프리미엄, Kelly & Jiang 2014의 횡단면 Hill, Lou/Polk/Skouras 2019의 기대수익, Rapach et al. 2016의 현물 공매도잔고, Martin 2017의 기대수익 하한, McNeil–Frey 2000의 1-step, Cheng et al. 2015의 역인과)을 **한 건도 반복하지 않았는가**?

### 11-4. 권장 산출물 형식

- 본문: 한국어(기술 용어 영어 병용), 절대날짜(YYYY-MM-DD), **확률은 1% 단위이며 80% 신뢰구간을 병기**한다, 모든 사실 주장에 출처(파일 경로 또는 URL·날짜), 미검증은 `[미검증]`. **리서치성 절에는 반대증거(데블스 애드버킷) 섹션이 필수 — 없으면 그 절은 무효**(CLAUDE.md 출력 규약).
- 부록 A: 슬롯별 사전등록 초안 4종(종료 조건 표 포함).
- 부록 B: 새 계약 YAML 골격.
- 부록 C: 결정 요청서(§10-b 승인 원문 템플릿 포함).
- 부록 D: 문헌 목록(본 팩 6장 + §6-9 기초 문헌 대사표 승계 + 검토자 추가분, confidence 표기 유지, **Author(s) (Year) 'Title', venue 형식 통일**).
- 부록 E: 반증 대장(이 팩 4장 + 검수에서 확정된 재설계 요구 사항의 슬롯별 체크리스트). **아래 항목을 반드시 포함**:
  - **V10 조합 격자(V12-D5 종결)**: 가법 대리 최상 **+1.147% CI90 [+1.07e-04, +9.99e-04]**였으나 **적격 12조합 전부** 상위 5% 원점 제거 후 CI90 하한이 음수 → **재개 안 함**. 분포 계층 조합을 제안하는 어떤 슬롯도 이 결과를 인용하고 **무엇이 다른지** 적을 것.
  - **V9 exog 채널 종결**: E2(+0.000043 유의 악화)·E3 무효익·E5/E6(장기 +0.000006 [−0.000008,+0.000021], 단기 +1.65% 악화) — 지수 수준 변동성 입력 재제안 시 인용 의무.
  - **V11 평시 상태신호 종결**: 48검정 중 통과 4, 순열 귀무 P(≥4)=0.25~0.32 `[48/54 기준 미검증]` — 포크 이전 차단 선례.
  - **V12 T1~T4 소진 + T5 실패(pooled 0.254)** 및 재개 5조건(P1~P5) 중 **P2 미충족**.
  - **classical-7 드롭**: 진단 전제 반증 + 클래스 상한(오라클 전이 rel 0.083~0.165) > 목표 0.04.

---

### 부기 — 이 팩이 승계한 검수 판정 요약

| 지위 | ID | 사유(요약) |
|---|---|---|
| 병합 후 진행 | infoset-1, ml-1, classical-1 → **S3-a** | 동일 코어. 예산·family 중복. **V4/V5 hold·V9 E5/E6 무효익 선례 고지 의무** |
| 병합 후 진행 | infoset-3, ml-3, classical-3 → **S3-b** | h1 다리 공허·승수 정규화·비정례 FOMC 수정 조건 |
| 병합 후 진행 | ml-6, infoset-6(깊이 팔) → **S3-c** | 기준선 이산화·라벨 정의·hazard 프레이밍 제거 조건 |
| 분리 진행 | ml-5(b), infoset-4(b) → **S3-d** | 일중 불필요, 종점 재설계 조건 |
| 진단만 | classical-5 H5a → **S3-e** | H5b는 FHS 객체 불일치·꼬리 검정력 부재로 재설계 |
| 재설계 선행 | infoset-8 → S3-f, ml-4·classical-2 → S3-g, infoset-5·classical-8 → **S3-h(인프라만)** | 각 장의 검수 노트 참조. S3-h는 D-9에 따라 설계창 검정 불성립 |
| 인프라 | ml-7 → **S5-b** | 동기 오진 정정 후 커버리지 보증 전용 |
| 구매 조건부 | infoset-2, ml-2, classical-4 → **S6-a** / infoset-4(a), ml-5(a), classical-6 → **S6-b** | 표적 A 강등·무구매 rung 선행 조건. S6-b는 FirstRate 개시일 확정 후 창 정의 |
| 보류 | infoset-7, ml-8 | 쌍 void·점근독립·부정대조 오염 / 현 API로 경로 표본 불가·표본 잡음 15~40배 |
| **드롭** | classical-7 | 진단 전제 반증 + 클래스 상한(오라클 전이 rel 0.083~0.165) > 목표 0.04 |

---

### 부기 2 — 즉시 확인이 필요한 미결 (팩에 `[미검증]`으로 남긴 항목)

1. **V11 순열 귀무 P(≥4)=0.25~0.32가 48검정 기준인지 54 기준인지** — 재확인 후 D-13 ①에 병기.
2. **FirstRate NDX 1분봉 실제 개시일(2000 vs 2008)** — 무료 2주 샘플로 확정, 취득계획 L12 정정 여부 결정(D-4).
3. **로컬 pandas 3.0.1 vs 핀 `<3`** — 봉인 replay 경로에서 fail-closed 발생 여부(D-16).
4. **`calendar_sources.yaml` L4 `probability_linkage: forbidden`의 적용 범위** — grep 상 이 키를 참조하는 코드가 계약 자신 외에 없음(D-5). S3-b 착수 전 명문 개정.
5. **V2 raw VIX OHLC 아카이브의 1990~1991 구간 OHLC 결측 여부** — D-10(창 1997+ 확장)의 선행 조건.
6. **CBOE DataShop 일회 이력가·§2b 파생표시 조건 원문** — D-3 질의 회신으로 확정.

---

> **본 개정에서 재확인한 저장소 좌표(실측)**: `data/contracts/statistics_lab_v1.yaml` L3–L5·L56 / `data/contracts/cftc_cot_bitcoin_d0.yaml` L20–L23·L81–L82 / `data/contracts/multivariate_timeseries_v12.draft.yaml` L170·L172·L405–L414·L585–L587·L602–L610 / `data/contracts/multivariate_timeseries_v13_vol.yaml` L77–L78·L85·L134·L136·L248·L257·L298 / `data/contracts/multivariate_timeseries_v8.yaml` L36·L108·L155 / `multivariate_timeseries_v9.yaml` L39·L184·L186 / `multivariate_timeseries_v10.yaml` L37·L116·L118 / `data/timeseries_v11/diagnostics/orthogonal_calm_screen.json`(tests 48·프록시 8·passing 4·block 13·B 2000·seed 20260903) / V8 원장 5종 행수(12·1·1·2·2) / V9 원장 7행·V10 12행·V13 vol 3행·approvals 7행·vol_live 2행 / `data/timeseries_v9/ledgers/development_experiments.jsonl`(E5 −0.0025864502, E6 −0.0025802706, 각 260원점) / `outputs/timeseries_v9/reports/E5_E6_VXN_SPREAD_VERDICT_20260902.md` L9–L10 / `data/calendar/events.csv` 53행 / `data/contracts/calendar_sources.yaml` L2·L4·L5 / `data/base_rates/volatility.md` L4·L27 / `src/ai_fc/timeseries_v3/backtest.py` L21·L26 / `src/ai_fc/timeseries/backtest.py` L33 / `src/ai_fc/evaluation.py` L28 / `docs/design/v13_firstrate_acquisition_plan_260907.md` L12·L14·L15·L40 / `data/timeseries_v13/vol/champion_coefficients.json` sha256.
>
> **주의**: 본 개정에 넘겨받은 드래프트는 §6-5 표 중간에서 시작하는 파손본이었다. §1~§6-4는 이 개정의 입력에 포함되지 않았으므로 **여기서 재작성하지 않았다**(없는 본문을 창작하지 않는다는 §11-2 규칙 1의 적용). 최종 팩 조립 시 §1~§6-4를 원본에서 이어 붙이고, §6-9의 기초 문헌이 §6-1~6-4와 중복되면 병합할 것.
