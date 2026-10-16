# 완전성 비평 — 본문 초안에 요구된 수정 목록 (적용 전 원문)

> 다중 렌즈 합성 파이프라인의 비평 에이전트가 초안에 대해 낸 지적이다. 본문(01)에는 대부분 반영되었으나,
> 검토관은 이 목록을 체크리스트로 삼아 **아직 남아 있는 결함**을 다시 찾아야 한다.

# 완결성 비평 — 드래프트 팩 교정 목록 (2026-09-09)

아래 각 항목은 **정확한 절 위치 → 문제 → 그대로 붙여넣을 교정 문구** 순이다. 수치는 모두 저장소에서 직접 읽었으며, 확인 못 한 것은 `[미검증]`으로 표시했다.

---

## A. 저장소 사실과 어긋나거나 확인되지 않은 서술

**A-1. §6-5 첫 행 — 논문명이 사라진 고아 행**
문제: 표의 첫 행이 `폭 폭주 경고 | high |`로 시작해 논문 칸이 비어 있다(팩 본문 파손). ACI 행으로 추정되나 독자가 근거를 확인할 수 없다.
교정: 해당 행을 다음으로 복원.
> `| Gibbs & Candès (2021) 'Adaptive Conformal Inference Under Distribution Shift', NeurIPS | α_t 온라인 갱신 — 커버리지는 장기 평균으로만 보장되고 **구간 폭이 폭주**할 수 있음. S5-b는 인프라 전용, 판정 트랙 금지 | high |`

**A-2. §7-2 FirstRate 행 — "NDX 지수는 2008-01-02 시작" 이 저장소 계획서와 충돌**
문제: `docs/design/v13_firstrate_acquisition_plan_260907.md` L12는 "1분봉 이력 2000+, **설계창 2007-2014 커버**", L15는 "**틱은 2010+**라 설계창 하단(2007-2009)은 1분봉만"이라고 적는다. 팩의 "2008-01-02 시작 → 2007 결손"은 이 문서와 정면 충돌하며 출처가 없다.
교정: 해당 셀을 다음으로 교체.
> "커버리지 상충 미해소: 취득계획 `v13_firstrate_acquisition_plan_260907.md` L12는 NDX 1분봉 2000+·설계창 전구간 커버로, L15는 틱만 2010+로 적는다. 본 팩이 확인한 벤더 페이지 상 NDX 지수 1분봉 개시일은 2008-01-02 **[미검증 — 확인일·URL 미기록]**. **무료 2주 샘플로 개시일과 기기(NDX 지수 vs QQQ ETF)를 먼저 확정**하고, 결과에 따라 취득계획 L12를 정정 커밋할 것. 개시일이 2008이면 설계창 2007년분(약 250거래일)이 결손이므로 S6-b 사전등록의 창 정의가 바뀐다."

**A-3. §7-2 FirstRate 가격 — 저장소에 없는 숫자**
문제: "구독 $99.95/년·번들 $59.95/월"은 저장소 어디에도 없다. 계획서 L14는 "번들 ~$300–400 일회"다.
교정: "~$300 일회 [미검증]; 구독 $99.95/년·번들 $59.95/월" → **"계획서 L14 기준 번들 ~$300–400 일회(문서 기록값). 그 밖의 구독가(연/월)는 벤더 페이지 확인값 [미검증 — 확인일·URL 병기 필요]"**

**A-4. §7-1 "V2 raw VIX OHLC" 행 — 자체 계산 수치에 스크립트 경로 없음**
문제: "9,259행. 설계창 zero-range 0일"은 이 팩이 새로 계산한 진단인데, 팩 자신의 §11-2 규칙 1(새로 계산한 값은 스크립트 경로 + '원장 미기록' 명시)을 위반한다. 파일 수 13은 실측 일치.
교정: 셀 말미에 추가.
> "(행수·zero-range는 **검토용 진단, 원장 미기록** — 산출 스크립트 경로를 사전등록 부록에 첨부할 것. 또한 이 아카이브는 매회 전체 CSV 재다운로드 방식이라 **캡처 시점만 보증**되며, 1990~1991 구간 OHLC 결측 여부는 `[미검증]`. D-10으로 창을 1997+로 확장할 경우 이 확인이 선행 조건.)"

**A-5. §7-1 통계 스토어 행 — NASDAQSOX 서술의 범위 오류**
문제: `model_use: prohibited`는 `data/contracts/statistics_lab_v1.yaml` **L5의 계약 전역 정책**(L3 `status: active_reference_only`, L4 `probability_space: reference_only`)이지 NASDAQSOX 개별 필드가 아니다. NASDAQSOX(L56)는 role 정의만 갖는다.
교정: "NASDAQSOX는 `statistics_lab_v1.yaml` `model_use: prohibited`" → **"`statistics_lab_v1.yaml`은 계약 **전역**으로 `status: active_reference_only`·`probability_space: reference_only`·`model_use: prohibited`(L3–L5) — 49 시리즈 전부가 모델 입력 금지이며 NASDAQSOX도 그 일부다(L56은 role 정의뿐). 따라서 infoset-7 SOX 갈래뿐 아니라 이 스토어 전 계열이 차단된다."**

**A-6. §7-2 CFTC 행 — D0 권한 문구 인용이 부정확**
문제: 실제 키는 `automated_access: permitted_subject_to_reasonable_rate_limits`(L81), `predictive_analytics_use: permitted_for_cftc_government_content`(L82), `model_use: prohibited`(L23)다. 팩은 "automated_access·predictive_analytics permitted"로만 적어 `model_use: prohibited`와의 긴장을 흐린다.
교정: 라이선스 칸을 **"공공 도메인. `cftc_cot_bitcoin_d0.yaml` L81 `automated_access: permitted_subject_to_reasonable_rate_limits`, L82 `predictive_analytics_use: permitted_for_cftc_government_content`이나 **L23 `model_use: prohibited`가 상위**로 유지 — 승격 없이는 피처 사용 불가"**로 교체.

**A-7. §7-2 CFTC 행 — "2010-12-03 backcast 절벽" 출처 없음**
교정: "**2010-12-03 backcast 절벽**" 뒤에 **"(TFF 보고서 자체 특성 — 저장소 내 근거 파일 없음 `[미검증: 원천 CFTC 공표문 URL·확인일 필요]`)"** 추가.

**A-8. §7-2 CFTC 행의 '필요한 방향'이 §10 D-9 권고와 모순**
문제: 표는 필요 방향을 "S3-h"로 적어 검정 트랙처럼 읽히는데, D-9 권고는 "인프라만, 모델 사용 보류"다.
교정: '필요한 방향' 칸을 **"S3-h **인프라만**(수집·PIT 레인·라이브 전진). 설계창 검정은 D-9 권고에 따라 불성립 — 2010-12-03 이전 부재 + 2012-10~2014-12 사건 0"**으로 교체.

**A-9. §8-1 KEEP — 부트스트랩 좌표표에 V9·V10 계약 좌표 누락**
문제: 이 표의 목적이 "신규 계약이 어느 좌표를 승계하는지"인데 V9(`qualification_statistics`)·V10(`dual_statistics`) 행이 빠졌다.
교정: 표에 두 행 추가.
> `| V9 계약 `qualification_statistics` | ℓ = `two_times_horizon`(지평 의존) · B 2000 · seed 미기재 · mde 지평별 공표 |`
> `| V10 계약 `dual_statistics` | ℓ 13주 · B 2000 · mde50 공표 |`
> 그리고 각주: "ℓ이 **고정 13이 아닌 트랙이 존재**한다(V9). 신규 계약은 `two_times_horizon`과 고정 13 중 어느 쪽을 승계하는지 결과 전 명시할 것."

**A-10. §8-3 — 시장내재 격차 금지 문구가 이미 배포된 V13 카드와 충돌**
문제: "**Q−P 격차를 화면에 나란히 놓지 말 것**"은 X1 6항(라이브 카드의 `vix-25-90d` AI 예측 괴리 칩 15%p **표시만**)과 충돌하는 것으로 읽힌다.
교정: 해당 셀을 **"기록·표시 전용, risk-neutral 병기. 금지 대상은 **시장내재확률(Q측도)과 자체 확률을 나란히 배치해 edge로 읽히게 하는 것**이며, X1 6항이 규정한 'AI 예측(rN) ↔ 기준율' 괴리 칩은 **표시만·자동 재예측 0**으로 계속 허용된다(두 규칙을 혼동하지 말 것)"**로 교체.

---

## B. 반증됐는데 열려 있는 것처럼 제시된 방향

**B-1. §7-1 V4 행 / S3-a 전반 — VIX 계열 '지수 수준' 선례 미고지**
문제: SKEW·VVIX·VIX3M·VIX9D를 "S3-a 주력"으로 두면서, 같은 지수 수준 입력이 이미 V4(계약 v4, `shadow_gate_hold`)·V5에서 시도되어 hold였고 V9 E5/E6의 VXN 스프레드가 무효익(장기 +0.000006 [−0.000008,+0.000021], **단기 h1+h5 +1.65% 악화**, |ρ|=0.011로 직교인데도)이었다는 사실이 없다.
교정: V4 행 메모와 S3-a 사전등록 초안 서두에 다음을 추가.
> "**선례 고지(필수)**: 이 계열의 지수 수준 입력은 V4(`multivariate_timeseries_v4.yaml`, 판정 hold — h21 +0.29%/h63 +1.69%)·V5에서 이미 시도되어 게이트 미통과였고, V9 E5/E6(Δlog(VXN/VIX), 2010–14 서브창 260원점)은 장기 +0.000006 [−0.000008,+0.000021] 무효익 + 단기 +1.65% [+0.000058,+0.000246] 악화로 채널 폐기됐다. S3-a가 덮이지 않았다는 주장은 오직 **표적 교체**(가격 분포 CRPS → 변동성 이벤트 Brier)에 근거하며, 정보집합은 새롭지 않다. 이 비대칭을 사전등록에 명문화하고, 기대효과를 그에 맞게 하향할 것."

**B-2. §10 D-6 — V12 reopen 전제조건을 일부만 인용**
문제: `only_path: 다른 데이터`만 인용하고, 같은 블록의 **P2(검정 기계 수리: pooled 통과율 ≤0.10 AND 셀별 ≤0.05를 결과 보기 전에 입증)**·P3(새 등록)·P1(V12-D1·V12-D4 승인)을 빠뜨렸다.
교정: D-6 근거 칸에 추가.
> "`multivariate_timeseries_v12.draft.yaml` L602–608: `only_path: 다른 데이터` 외에 **P1(V12-D1 트랙 개시 + V12-D4 승인) · P2(검정 기계 수리 — 수리된 기계가 새 음성대조를 결과 전에 통과, 기준 pooled ≤0.10 **AND 셀별 ≤0.05**) · P3(새 사전등록)** 전부가 required다. T-A가 NOT_REPAIRED(N-p-block 0.201)로 끝났으므로 **P2가 미충족 상태**이며, 이는 (b)안을 사실상 봉쇄한다 — D-6 권고 (c)의 근거로 명시할 것."

**B-3. §10 D-7 — 근거는 옳으나 인용 위치가 없음**
교정: D-7 근거 칸에 **"취득계획 §5(L40) 원문: 'V12b(T-B): 경로 생성기 검정에 일중이 필수는 아님(일간 잔차 재표집 구조 문제) — FirstRate는 사건(배리어 터치)의 일중 실현 검증용 **보조**'"** 를 인용으로 삽입.

**B-4. 부록 E(반증 대장) 필수 항목 누락 — V10 조합 격자 종결**
문제: 분포 계층 조합을 다시 제안하는 슬롯이 생기면 반드시 걸려야 할 종결 사실이 팩에 없다.
교정: §11-4 부록 E 지시에 다음 항목을 명시적으로 추가.
> "**V10 조합 격자(V12-D5 종결)**: 가법 대리 최상 +1.147% CI90 [+1.07e-04, +9.99e-04]였으나 적격 12조합 **전부** 상위 5% 원점 제거 후 CI90 하한이 음수 → 재개 안 함. 분포 계층 조합을 제안하는 어떤 슬롯도 이 결과를 인용하고 무엇이 다른지 적을 것."

---

## C. 누락된 트랙·수치

**C-1. §7-1 — V3~V7 자산 행 전체 누락**
문제: 보유 자산표에 V3·V5·V6·V7 계약과 산출물(`outputs/timeseries_v3~v7`, run JSON, audit)이 없다. §8-1/8-2가 "저장소 미구현"이라 부르는 도구 중 일부는 이 트랙들에 **이미 구현되어 있다**(아래 C-2).
교정: §7-1에 행 추가.
> `| **V3~V7 동결 코드·산출** `data/contracts/multivariate_timeseries_v{3,4,5,6,7}.yaml`, `outputs/timeseries_v{5,6,7}/` | V3 h21 +0.75%/h63 +2.02%(hold) · V5 963원점 h21 −10.69%/h63 −7.38%(hold, 7사유) · V6 봉인 385원점 h21 +1.27%/h63 +0.58%(hold, 8사유) · V7 `WAIT_DATA`(`status.json`, 계약 `frozen_v7_p0_003`) | design pseudo-OOS·봉인 1회(V6) | — | **코드 자산이지 승인 모델 아님**(전부 `shadow_gate_hold`/HOLD). 신규 슬롯이 이 코드를 재사용하면 그 사실과 HOLD 지위를 사전등록에 적을 것 |`

**C-2. §8-1/§8-2 — 이미 있는 프리미티브를 '신규 도입'으로 적음**
문제: ADD의 "좌측 가중 CRPS·pinball τ=0.05"는 저장소에 **이미** `src/ai_fc/timeseries_v3/backtest.py::tail_weighted_crps`(9분위 격자, 가중 1+4|q−0.5|)와 `timeseries/backtest.py::pinball_loss`가 존재한다. 또 v3 `GroupConformalScale`, v5/v6 GPD-EVT 꼬리(E6), quantile EN(E1), DLM(E4), soft regime(E5), v7 SLSQP 스태킹도 미언급.
교정: §8-1 KEEP 표에 행 추가 + §8-2 ADD 문구 수정.
> KEEP 추가: `| 꼬리가중 CRPS(기존) | `timeseries_v3/backtest.py::tail_weighted_crps` 9분위·가중 1+4\|q−0.5\| | **대칭 가중**이라 좌측 전용이 아님. HOLD 트랙 코드지만 재구현 불필요 |`
> KEEP 추가: `| pinball(기존) | `timeseries/backtest.py::pinball_loss` | R8-D4로 **공개 제외** — 내부 판정에만 |`
> ADD 수정: "좌측 가중 CRPS·pinball τ=0.05·FZ0" → "**좌측 비대칭** 가중 CRPS(기존 대칭 `tail_weighted_crps`의 가중함수만 교체) · pinball τ=0.05(기존 구현 재사용, 표시 금지) · FZ0(신규)"

**C-3. §7-1 — V8 원장 5종의 실측 행수 누락**
교정: '예측·원장' 행의 V8 부분을 다음으로 교체.
> "V8 원장 5종(`ledger_registry.yaml` L316–342): `development_experiments.jsonl` **12행(E0~E11, 전부 design)** · `holdout_scorings.jsonl` **1행(E10 PASS, 장기개선 0.0734, CI90 상단 −0.00106)** · `sealed_evaluations.jsonl` **1행**(전체창 1,011원점 pass / 봉인창 385원점 hold, 사유 'GFC 원점 0') · `shadow_forecasts.jsonl` **2행** · `shadow_resolutions.jsonl` **2행**"

**C-4. 팩 전체 — 자원 대장(비가역 소모 회계) 표 부재**
문제: §9-2 항목 16이 사전등록에 자원 회계를 요구하는데, 팩 자신에는 현재 잔량 표가 없다. 신규 설계자가 남은 슬롯을 오판할 수 있다.
교정: §9-4 앞에 표 신설.
> "### 9-3b. 현재 자원 잔량 (2026-09-09 실측)
> V8: dev 12/24 · holdout **1/3 소모**(E10) · 봉인 **1/1 소모**(disclosure #1, R8-D2) · 섀도 승격 원점 2/126
> V9: dev 7/24 · holdout 0/3 · 봉인 0 (동결) — V10: dev 12/24(stop-loss) · holdout 0/3 · 봉인 0 (동결)
> V11: 백테스트 0 · holdout 0 — V12: `evaluations_spent: 0`, 개시 시 `evaluations_spent_on_open: 4` 계상(잔여 20), holdout 0
> V13-VOL: dev **3/8**(`v13_vol.yaml` L77–78) · holdout **0/3**(finalist `V13VOL_champion_aec80c65038b` 1개 사전등록) · 봉인 0
> 봉인 바이트: V8+V2 `e3ff2fdb…` 0바이트 변경 · V8 원장 `b9c492be…` 일치 · V8 `model_code_hash: 8361899f…`
> 캠페인(V9~V13) 비가역 행동 누계: **0**"

**C-5. §11-2 규칙 4 — 무접촉 선언에 실제 해시가 없음**
교정: §11-2 4번 문장에 값을 박아 넣을 것.
> "V13 계약·계수(`champion_coefficients.json` sha256 `1a857850…`, 이전 `51815bde…`, p 무변경)·라이브 카드 개정 금지. V8/V2 봉인 sha256 `e3ff2fdb64ac71c0f05ae8e4508ef1c5a7c8fba7b78d81548918881032c8d224`, V8 원장 `b9c492be…`, `model_code_hash 8361899f…` — 신규 계약은 이 값들을 `source_pins`로 복사해 넣고 실행 전후 대사한다."

**C-6. §9-3 — V11 검정 수 표기가 판정서 원문과 실측 사이에서 미정리**
문제: 팩은 "V11(48검정)"과 D-13(54→48 정정)을 동시에 적었으나, 판정서 원문(`V11_FREEZE_DECISION_20260903.md` L11 "54검정", L38 "4/54(직교통과 36셀 중 4)")은 아직 그대로다. 실측은 `orthogonal_calm_screen.json` **tests 48 · 프록시 8종(P1,P2,P3,P5,P6,P7,P8,P9 — P4 부재) · passing 4**.
교정: D-13 ①을 다음으로 확장하고 §9-3에 각주 추가.
> "① `V11_FREEZE_DECISION_20260903.md` L11 '9개 후보 프록시 × 3지표 × 2수평선 = 54검정' → '**8개 프록시 × 3지표 × 2수평선 = 48검정**(진단 산출물 `data/timeseries_v11/diagnostics/orthogonal_calm_screen.json` `tests` 48행·프록시 8종, P4는 미실행)', L38 '4/54' → '**4/48**(직교통과 36셀 중 4)'. **불변 파일이 아니므로 정정 커밋 가능**하나, 순열 귀무 P(≥4)=0.25~0.32가 48 기준으로 산출된 값인지 54 기준인지는 `[미검증]` — 재확인 후 함께 기재할 것."

**C-7. §7-1 — S3-b가 쓸 보유 자산이 자산표에 없음**
문제: 발표 캘린더 슬롯의 입력인 `data/calendar/events.csv`(53건, FOMC·CPI·NFP·GDP·NVDA IR 공식 일정)와 `data/contracts/calendar_sources.yaml`(as_of 2026-08-04, `confirmed_definition: institution_or_issuer_published_date`)이 보유 자산표에 없다. `data/base_rates/`(수동 base rate, `volatility.md`의 무조건부 44%·조건부 33.3%/11.1%)도 없다.
교정: §7-1에 두 행 추가.
> `| **발표 캘린더** `data/calendar/events.csv`(53건) · `data/contracts/calendar_sources.yaml` | 공식 IR·기관 일정 | native(공표일, `confirmed_definition: institution_or_issuer_published_date`) | 공공 | **S3-b 1차 입력**. 단 `policy.probability_linkage: forbidden`(L4)의 범위는 D-5 미결 |`
> `| **base rate 라이브러리** `data/base_rates/` (수동 + `*_auto.md`) | `volatility.md`: `vix-25-90d` 무조건부 44%, 8월말 앵커 조건부 33.3%/11.1% | 큐레이션 | — | V13 기준율 카드와 **같은 사건을 다른 방법으로** 추정 중 — 신규 슬롯은 둘의 불일치 표시 규칙(X1 6항)을 승계 |`

---

## D. 누락된 데이터 소스 (후보 표)

**D-1. §7-2 — digest에 있던 후보 7종이 통째로 빠짐**
교정: 다음 행들을 §7-2에 추가(전부 "부정결과가 덮는가"·판정 포함).
> `| **Fed Board H.8 / H.15 원생산자** | 없음(TOTCI·TOTLL은 ALFRED, DGS는 Treasury 원본) | Board DDP는 **현행 vintage만** → ALFRED 우월(V9-D5) | 공공 | $0 | **예 — V9_E2(+0.000043 유의 악화)·E3 무효익** | 은행 계약 §4.1 원생산자 조항은 PIT 사유로 미적용(선례 기록) |`
> `| **Refinitiv / Bloomberg (I/B/E/S 컨센서스)** | 실적·매크로 컨센서스 이력 = 서프라이즈의 분모 | 상세 이력 타임스탬프 보유 `[미검증]` | 재배포·파생 표시 엄격 | 단말 연 수만 달러 `[미검증]` | 아니오 — 다만 1차 목표 대비 비용 불균형 | `market_consensus.yaml`은 영수증 소스만 허용, `synthetic_backfill: prohibited` |`
> `| **Citi CESI(매크로 서프라이즈)** | 컨센서스 대비 실적 집계 | 독점·재배포 불가 | 독점 | 단말 종속 | 아니오 | 대안: Scotti (2016) 'Surprise and uncertainty indexes: Real-time aggregation of real-activity macro-surprises', J. Monetary Economics 방법론으로 보유 SPF·Cleveland 나우캐스트에서 자체 구성 `[미검증: 공개 코드 URL]` |`
> `| **실적 캘린더 벤더** | 실적 시즌 군집·서프라이즈 | 과거 캘린더 PIT 불명 | Nasdaq.com·Zacks 약관 제한 | 유료 | 아니오 | 보유 `calendar/events.csv`는 공식 IR 일정만 |`
> `| **브레드스 벤더(Barchart 등)** | A/D·신고가/신저가·MA 상회 비율 | PIT 구성종목 멤버십 필요 → CRSP 없이는 생존편향 | 거래소·벤더 약관 제한 | 유료 | 아니오 | dualdb 24종목 자체 구성은 표본 편향으로 불가 |`
> `| **Kalshi·Polymarket 과거 시세** | 예측시장 대조 | 캡처 전진만, 과거 API `[미검증]` | 공개 API 약관 미기록 `[미검증]` | $0 | 해당 없음(P3 봉인, 기록 전용) | Kalshi 호가 공란 실측(2026-07-15) |`
> `| **Nasdaq Data Link** | 대체 데이터 | 중상, 창 하단 결측 | **무료 익명 티어 약관 문서 NOT FOUND — 회색**(12-3 미사용) | 프리미엄 | 해당 없음 | 보유 FRED·Treasury와 중복, 우선순위 낮음 |`

**D-2. §7-2 Treasury 입찰 행 — 기대 근거가 비어 있음**
교정: 메모 칸에 추가 → **"온보딩 낮음(`treasury_fiscaldata` 등록 완료). 단 **DGS2 변화 자체가 이미 V8 내생 5변량에 들어 있어** 수급 충격의 상당 부분이 endogenous — 신규 정보 증분이 작을 개연."**

---

## E. 누락된 단계 게이트 (§9-1 파이프라인)

**E-1. 진입 전 G0 무손상 확인 단계 없음**
교정: `[0]` 앞에 단계 신설.
> "`[-1] G0 무손상 대사` — V8/V2 봉인 sha `e3ff2fdb…`, V8 원장 `b9c492be…`, V13 계수 3자 핀 `1a857850…` 일치 확인 + V8 store 쓰기 0 검증(`multivariate_timeseries_v12.draft.yaml` L410 `G0_crps_no_damage`, `hard: true`, 실패 시 **계약 아래 모든 평가 무효**). 실행 전·후 2회."

**E-2. 독립 재계산 게이트 없음**
문제: V9·V10·V11 동결은 모두 **독립 재계산**(`docs/review/V9_V10_V11_INDEPENDENT_VERDICT.md`: 5쌍 개선 0·최대|Δ| 4.33e-05 / 채택 0/12·순열 p=0.118 / D7 조합 격자 정정)으로 확정됐는데 파이프라인에 그 단계가 없다.
교정: `[3]`과 `[4]` 사이에 삽입.
> "`[3b] 독립 재계산` — 채택 후보가 나오면 **별도 스크립트·별도 실행자**로 쌍대 통계량·CI·귀무를 재산출하고 부호·크기 일치를 확인한다(V9/V10/V11 선례). 불일치 시 후보는 `[4]`로 진행 불가."

**E-3. 6렌즈 적대적 검증이 파이프라인에 없음**
교정: `[3]` 마지막에 추가 → **"→ 6렌즈 적대 검증(독립 재현·vol직교·표본외 전이·교란 통제·다중검정 위양성·국면 제거 민감도. V10에서 GFC 78원점(18.7%)이 델타 83.8%를 견인함을 잡아낸 절차) — GFC 원점 제거·상위 5% 제거 후 **부호 유지**가 채택의 필요조건"**

**E-4. T2·T3 승인 단계가 사다리에서 누락**
문제: `[5]`가 "base rate 배선 + 라이브 게이트 무장"으로 바로 가서 T2(숨김 패널) → T3(라이브 카드) 승인 기록(`approvals.jsonl`)이 빠졌다. 또 `v13_vol.yaml` L257 `display_tiers_allowed: [t0_internal, t2_hidden_panel, t3_live_card]`에는 **t1 값이 없다**.
교정: `[5]`를 분할.
> "`[5a] T2 진입` — 게이트 무장 + G0 무손상 + **사용자 승인 → `approvals.jsonl` append**(V13 선례: 2026-09-08 14:54 T2 진입, 14:58 T3 전환, r2).
> `[5b] T3 전환` — X1 이름충돌 6항 해소 + caveat lead 굵게 + read-model 키 분리 확인 + 승인 원장 append.
> 주: `v13_vol.yaml` `display_tiers_allowed`에 **t1 값이 존재하지 않는다**. 신규 계약이 T1(문서·리뷰팩)을 tier로 쓰려면 `t1_docs`를 계약에 **정의**하거나, 문서 단계는 tier 밖 절차로 취급한다고 명기할 것."

**E-5. stop-loss 발동 시 기록 경로가 파이프라인에 없음**
교정: `[3]` 옆 분기로 추가 → **"`[3x] stop-loss 발동` → 부정결과 계약 등록(`status: negative_result_draft`, `gates.armed: false`, `evaluated_candidates: 0`)과 판정서 T1 산출. V12 선례를 형식으로 승계 — 결과를 본 뒤 문턱·손실·기준선을 바꾸는 대신 **축을 닫고 기록한다**."**

**E-6. 커밋·검증 위생 단계 없음**
교정: `[2]`와 `[7]` 각각에 추가.
> "`[2]` 말미: 사전등록 커밋 해시를 계약 `revision_history`에 기록(V12 선례 커밋 `ec496463`). 새 원장은 `data/contracts/ledger_registry.yaml`에 등록.
> `[7]` 말미: `cd src && python -m ai_fc sync --check` 불변성 검사 + inventory 재생성(verify drift 방지) + 리뷰팩 `outputs/review-packs/<NAME>/` + `.zip.sha256` 산출. `forecasts/`·`calibration/` 무수정 확인."

**E-7. 런타임 영수증 캡처 단계 없음**
교정: §9-2 체크리스트에 17번 신설.
> "17. **재현 좌표**: python·numpy·pandas·scipy·statsmodels 버전 영수증(봉인 기준 3.12.10 / 2.5.2 / 2.3.3 / 1.17.1 / 0.14.6), `seed_rule`(V8 `sha256_model_version_and_as_of`), 계약 해시·`model_code_hash`. **로컬 pandas 3.0.1이 핀 `<3`과 불일치**하므로 실행 전 확인(D-16)."

---

## F. 거버넌스 서술 오류·누락

**F-1. §8-3 — V13이 신설한 금지 2건 누락**
교정: FORBID 표에 두 행 추가.
> `| **기후 단독 대비 우월만으로 챔피언 지정** | 영구 금지 | `v13_vol.yaml` A5 `champion_on_climatology_alone` — 자명 기준선(PB류)을 반드시 함께 둔다. rung-3가 EWMA의 스킬을 '당일 수준 지속'으로 환원시킨 이유 |`
> `| **홀드아웃 패널에 봉인 바이트 반입** | 영구 금지 | `v13_vol.yaml` A5 `sealed_bytes_in_holdout_panel` |`

**F-2. §9-4 — 승인 규약에 빠진 결정 3종**
교정: 표에 행 추가.
> `| base rate 배선(표시만) | 사용자 결정 V13-D6 | 홀드아웃 PASS 셀 한정 원칙과 caveat 유지 여부를 함께 승인 |`
> `| 신규 카드의 자동화 체인 편입 | 사용자 승인 | `timeseries-v2-refresh`(화~토 01:35 UTC) → `v8-shadow`(03:10) → `v13-vol-live`(03:40) → pages/verify `workflow_run` 연쇄에 끼워 넣는 것은 배포 행위 |`
> `| 부정결과 계약 상태 전환 | 사용자 승인 | `negative_result_draft` → 확정 |`

**F-3. §9-5 — 표시 규약에 빠진 3항**
교정: 목록에 추가.
> "- 게이트 닫힘 시 처리는 **두 선례가 다르다**: V13 카드는 마지막 값 재사용 없이 HOLD+사유(fail-closed), 시나리오 V5.2는 `display_promotion.yaml` B안으로 `stale_last_valid` + 기준일 + 사유 공시. **신규 카드는 어느 쪽인지 계약에 명시**할 것(권고: fail-closed).
> - 원점 경과 2단 임계(`origin_age_policy` warn 1 / hold 10 거래일)와 입력 신선도(48h, DTWEXBGS 216h) 규칙을 승계할지 명시. 주말·월요일 자연 HOLD를 '고장'으로 오독하지 않게 카드에 문구.
> - 공개 범위 분리(R8-D4): 개발기간 포함 전체창과 표본외 창을 **분리 공시**하고 표본외 창 자체 판정을 인쇄한다."

**F-4. §11-4 / §11-1 — CLAUDE.md 출력 규약 2건 누락**
교정: §11-4 첫 항목에 추가 → **"확률은 1% 단위이며 **80% 신뢰구간을 병기**한다. 리서치성 절에는 **반대증거(데블스 애드버킷) 섹션이 필수** — 없으면 그 절은 무효(CLAUDE.md 출력 규약)."**
또 §11-1에 항목 신설 → **"(G) 비용 계획 — 슬롯당 서브에이전트 1~4개 이내, 토큰·API 예산 상한, 그리고 '토큰비용 높은 배치는 지시 후 실행' 관례."**

**F-5. §10 결정표 — 승인 원문 템플릿 부재(§11-1(E) 자기요구 위반)**
교정: §10 표 아래에 블록 추가.
> "### 10-b. 승인 원문 템플릿(사용자가 그대로 붙여넣는 문자열)
> - D-1: `V13-D3 홀드아웃 1회 소모 승인 finalist=<ID>` (보류 시: `V13-D3 보류 — S3-a 결과 후 재판단`)
> - D-2: `V13-D6 base rate 배선 승인 — 표시만, 홀드아웃 미검증 caveat 유지`
> - D-3: `V12-D4 CBOE DataShop 질의 발송 승인 (구매 아님)`
> - D-4: `FR-1 FirstRate 집행 승인 금액=$___ / 또는 FR-1 보류 — 무료 샘플 선검증`
> - D-6: `V12 reopen 판정 — (c) 표적 A는 base rate 전용` 등 택1
> - D-8: `TSFM §8 예외 판정 — (b) 불적용` 등 택1
> - D-9: `CFTC D0 인프라만 승인, model_use 승격 보류`
> - D-10: `설계창 확장 승인 — 계약 ID <ID> 한정, 2007–2014 결과와 혼합 금지`"

**F-6. §10 D-8 — 권고가 사용자 결정을 선점**
문제: §8-3은 "사전학습 TSFM에 §8 예외 적용 = 사용자 판정 전 금지"인데 D-8 권고는 (c) 조건부 적용이다.
교정: D-8 권고 칸을 **"**기본은 (b) 불적용**(§8 예외의 근거가 '사전지식 오염 없음'인데 코퍼스 오염 가능성이 이를 무너뜨린다). (c)는 **사용자가 명시 판정한 경우에만** 가능하며 그때도 T0 상한·오염 caveat 상시·홀드아웃/봉인 무접촉·체크포인트 sha·라이선스 영수증 커밋이 조건. 현 API로는 경로 표본이 불가하므로 실무적으로 보류."**로 교체.

---

## G. 인용 결함

**G-1. §6-6·6-7 전반 — 논문 제목 누락(출처 규약 위반)**
문제: `Longin & Solnik (2001), JF` / `Ang & Chen (2002), JFE` / `Vittinghoff & McCulloch (2007), AJE` / `Rapach, Ringgenberg & Zhou (2016), JFE` / `Hong & Yogo (2012), JFE` / `Cheng, Kirilenko & Xiong (2015), Review of Finance` / `Koenker & Bassett (1978), Econometrica` 등 다수가 저자·연도·저널만 있고 제목이 없다. 팩 자신의 인용 형식(Author(s) (Year) 'Title', venue)과 불일치.
교정: 6장 전 표를 제목 포함 형식으로 통일. 최소 다음을 복원.
> Longin & Solnik (2001) 'Extreme Correlation of International Equity Markets', JF · Ang & Chen (2002) 'Asymmetric Correlations of Equity Portfolios', JFE · Patton (2006) 'Modelling Asymmetric Exchange Rate Dependence', IER · Poon, Rockinger & Tawn (2004) 'Extreme Value Dependence in Financial Markets: Diagnostics, Models, and Financial Implications', RFS · Christoffersen, Errunza, Jacobs & Langlois (2012) 'Is the Potential for International Diversification Disappearing?', RFS · Vittinghoff & McCulloch (2007) 'Relaxing the Rule of Ten Events per Variable in Logistic and Cox Regression', AJE · Peduzzi et al. (1996) 'A Simulation Study of the Number of Events per Variable in Logistic Regression Analysis', J. Clinical Epidemiology · Chekhlov, Uryasev & Zabarankin (2005) 'Drawdown Measure in Portfolio Optimization', IJTAF · Patton, Ziegel & Chen (2019) 'Dynamic Semiparametric Models for Expected Shortfall (and Value-at-Risk)', J. Econometrics · Rapach, Ringgenberg & Zhou (2016) 'Short Interest and Aggregate Stock Returns', JFE · Hong & Yogo (2012) 'What Does Futures Market Interest Tell Us about the Macroeconomy and Asset Prices?', JFE · Cheng, Kirilenko & Xiong (2015) 'Convective Risk Flows in Commodity Futures Markets', Review of Finance · Koenker & Bassett (1978) 'Regression Quantiles', Econometrica · Makridakis, Spiliotis & Assimakopoulos (2018) 'Statistical and Machine Learning Forecasting Methods: Concerns and Ways Forward', PLOS ONE · Rigby & Stasinopoulos (2005) 'Generalized Additive Models for Location, Scale and Shape', JRSS-C.

**G-2. §6-6 Embrechts, McNeil & Straumann (2002) — 제목·수록처 없음**
교정: **"Embrechts, McNeil & Straumann (2002) 'Correlation and Dependence in Risk Management: Properties and Pitfalls', in *Risk Management: Value at Risk and Beyond* (ed. Dempster), Cambridge University Press"**

**G-3. §6-8 Amazon (2025) 'Chronos-2' technical report — 서지 불명확**
교정: **"Amazon Science (2025) 'Chronos-2' 기술 보고서 `[미검증: 저자·발행처·URL·접근일 미확인]` — 근거로 인용하지 말고, 저장소가 확인한 사실(로컬 `chronos` 2.3.1 설치, 현 API 출력이 QUANTILES라 경로 표본 불가)만 기술할 것."**

**G-4. §6-8 Aksu et al. (2024) 'GIFT-Eval' — 부제·식별번호 없음**
교정: **"Aksu et al. (2024) 'GIFT-Eval: A Benchmark for General Time Series Forecasting Model Evaluation', arXiv `[미검증: 식별번호]`"**

**G-5. §6-7 Wang (2003) — 확인 표시 필요**
교정: **"Wang (2003) 'The Behavior and Performance of Major Types of Futures Traders', J. Futures Markets `[미검증: 권·호]`"**

**G-6. §6-5·6-8 — 저장소가 실제로 쓰는 기초 문헌이 6장에 있는지 확인 필요**
교정(6-1~6-4에 없다면 추가): Politis & Romano (1994) 'The Stationary Bootstrap', JASA · Gneiting & Raftery (2007) 'Strictly Proper Scoring Rules, Prediction, and Estimation', JASA · Diebold & Mariano (1995) 'Comparing Predictive Accuracy', JBES · **Harvey, Leybourne & Newbold (1997) 'Testing the Equality of Prediction Mean Squared Errors', IJF**(DM 소표본 보정이 저장소에 **없다**는 사실의 근거) · Brier (1950), Murphy (1973), Corsi (2009) · **Hansen & Lunde (2005) 'A Forecast Comparison of Volatility Models: Does Anything Beat a GARCH(1,1)?', J. Applied Econometrics** · Poon & Granger (2003) 'Forecasting Volatility in Financial Markets: A Review', JEL · Welch & Goyal (2008), Campbell & Thompson (2008), RFS · Christoffersen & Diebold (2006) 'Financial Asset Returns, Direction-of-Change Forecasting, and Volatility Dynamics', Management Science · Barone-Adesi, Giannopoulos & Vosper (1999), J. Futures Markets.

---

## H. 브리프 대비 얇은 절

**H-1. §8-2 ADD — digest가 지목한 결손 중 3종이 ADD·FORBID 어디에도 없음**
교정: ADD 표에 세 행 추가(또는 "도입하지 않는 이유"를 명시).
> `| reliability 신뢰대 | 신뢰도 곡선의 표본 불확실성 표시 | Bröcker & Smith (2007) 'Increasing the Reliability of Reliability Diagrams', Weather and Forecasting | h63 rel≈0.08 오보정을 '점 추정 vs 대역'으로 구분하려면 필수. 저장소 미구현 |`
> `| PIT 정식 검정 | Berkowitz LR로 밀도 예측 검정 | Berkowitz (2001), JBES | 현재는 coverage 사후 검사뿐 — **중첩 원점에서 허위 기각** caveat 병기 |`
> `| Christoffersen LR_uc/LR_ind (보조 지표) | 구간 예측 검정 | Christoffersen (1998), IER; Kupiec (1995), J. Derivatives | **1차 지표 금지**(중첩 원점 허위 기각·조건부 커버리지 불가능성, Foygel Barber et al. 2021). 표시 전용으로만 |`

**H-2. §9-3 — 트랙 간 누적 스누핑 보정이 "가능하면 검토"로 끝남**
교정: 해당 문단을 다음으로 교체.
> "**트랙 간 누적**: 설계창 2007–2014는 V8(dev 12)·V9(7)·V10(12)·V11(**48검정**)·V12(8셀×2방향)·V13(9셀×3rung)로 이미 누적 채굴됐고, 저장소에 SPA/MCS/트랙 간 FWER 보정은 **존재하지 않는다**. 신규 계약은 둘 중 하나를 **결과 전에** 택해 명문화한다: (i) family를 트랙 내부로 한정하고 '트랙 간 누적 스누핑은 미보정'임을 판정서에 상시 인쇄한다, 또는 (ii) White (2000) Reality Check / Hansen (2005) SPA를 S3 전 슬롯 통합 family에 적용하고 부트스트랩 재표집(ℓ=13, B=2000, seed 고정)을 슬롯 간 **공유**한다. (ii)는 슬롯 간 원점 정렬이 전제이므로 구현 공수를 예산에 계상할 것."

**H-3. §11-3 자기점검 — 문헌 오적용 점검 문항 없음**
교정: 8번 문항 신설.
> "8. 인용한 각 논문에 대해 **'존재'와 '이 표적으로의 전이'가 구분**돼 있는가? 6장이 확정한 오적용 목록(Johnson 2017의 slope=프리미엄, Kelly & Jiang 2014의 횡단면 Hill, Lou/Polk/Skouras 2019의 기대수익, Rapach et al. 2016의 현물 공매도잔고, Martin 2017의 기대수익 하한, McNeil–Frey 2000의 1-step, Cheng et al. 2015의 역인과)을 한 건도 반복하지 않았는가?"

**H-4. §11-1(B) — 사전등록 초안 4종에 '무엇이 나오면 축이 닫히는가'의 양식이 없음**
교정: (B) 말미에 추가.
> "각 슬롯 초안은 **종료 조건 표**를 포함한다: 열 = [셀, 사건수, 기대효과(문헌·선례 근거), MDE=1.645·se, 판정('개선'·'측정된 영'·'검정력 부족')]. **MDE가 기대효과를 덮는 셀에서만 null을 '측정된 영'으로 부를 수 있고**, 덮지 못하면 그 셀은 '검정력 부족'으로 기록해 축을 닫지 않는다(V9의 se 4.0e-06~2.1e-05 선례가 자격 기준)."

**H-5. §11-1(D) — 데이터 작업 명세에 영수증/등급 신설 절차의 승인 경로가 없음**
교정: (D) 말미에 추가.
> "신규 PIT 등급(`vendor_eod_archive` 등)을 만들면 `multivariate_timeseries_v2.yaml` `data_policy`의 기존 3등급(native_pit / reconstructed_market_archive / captured_forward)과의 관계를 정의하고, **`reconstructed_archive_is_native_pit: false`에 상응하는 자기부정 필드**를 반드시 둔다. 등급 신설은 계약 개정 커밋 + 자산표 갱신 + `licenses.generated.md` 재생성까지가 한 단위다."

---

## I. 즉시 확인이 필요한 미결(팩에 `[미검증]`으로 남길 것)

1. V11 순열 귀무 P(≥4)=0.25~0.32가 48검정 기준인지 54 기준인지 — 재확인 후 D-13에 병기.
2. FirstRate NDX 1분봉 실제 개시일(2000 vs 2008) — 무료 샘플로 확정, 취득계획 L12 정정 여부 결정.
3. 로컬 pandas 3.0.1 vs 핀 `<3` — 봉인 replay 경로에서 fail-closed 발생 여부(D-16).
4. `calendar_sources.yaml` `probability_linkage: forbidden`(L4)의 적용 범위 — grep 상 이 키를 참조하는 코드가 계약 자신 외에 없음(D-5). S3-b 착수 전 명문 개정.
