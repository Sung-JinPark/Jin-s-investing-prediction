# V13-VOL 파생층 표시(T2→T3) + 외부검토 다음설계(C-1~C-5·D-1~D-4) 구현 계획

## Context

- 사용자 요청(2026-09-08): "t2 숨긴패널까지 진행하고, 라이브 카드 노출 진행 후 [외부 검토] 전수조사·분석 → 설계 계획 → 정밀 구현".
- 외부 검토 `CAMPAIGN_REVIEW_NEXT_DESIGN_260908.md`(zip과 동일, sha 2ecf9537) 판정: V9~V12 판정 전부 유지, V13-VOL만 진짜 긍정. 제언: C-1 지속성 기준선(PB) 사전등록, C-2 조건부 홀드아웃 1슬롯, C-3 EXIT 트리거 base rate 배선(가격 카드 아님), C-4 CBOE 발송·FirstRate 후순위(사용자), C-5 V12b 폐기→보류, D-1~D-4 거버넌스(홀드아웃 절차·자명 기준선 규칙·개정 시점=지금·main 잠금 우회 금지+사후 기록).
- 표시 정본: `docs/design/v13_vol_live_card_display_design_260908.md`(main d6b72554). 사다리 T0→T2(숨김)→T3(라이브)→T4(차단), X1 이름충돌 6항.
- 현재 상태: 브랜치 `claude/v13-next`@d6b72554, origin/main bc87496d(PR #166 병합, 내 브랜치보다 앞섬). **main은 Codex 워크트리(`C:/Users/91ssj/.codex/worktrees/7e4e/ai-investing`, 0c14900f)에 잠김** → GOV-1: 리프스펙 FF 푸시 금지, 브랜치 푸시+PR만.
- 계약 `data/contracts/multivariate_timeseries_v13_vol.yaml` 실제: `evaluations_spent: 0`(원장 2행 → 오기), `gates.armed`·`holdout_maximum_finalists`·홀드아웃 원장·`amendments_applied` 없음. 원장 `vol_experiments.jsonl` 미등록.

## 두 설계 간 충돌 해소 (내 결정)

| # | 충돌 | 결정 |
|---|---|---|
| R1 | 계수 동결 시점: 표시 설계는 "지금 EWMA 동결", 검토는 "C-1 champion(EWMA 또는 PB) 확정 뒤" | **C-1 뒤 동결.** C-1은 설계창 원장 재분석 1회(예산 3/8, 백테스트 0회)로 싸다. 잘못된 champion을 해시 핀하면 재동결·재발행이 더 비싸다 → 아래 "구현 순서" 참조(사용자 결정 반영) |
| R2 | artifact 이름 `ewma_logit_coefficients.json`(설계서 §3) vs champion 중립 | **`data/timeseries_v13/vol/champion_coefficients.json`** — 셀별 champion 모형이 다를 수 있음. 설계서 §3의 이름은 V13-D2′ amendment에 "정정"으로 기록(설계서 원문 무수정) |
| R3 | `amendments:` vs `amendments_applied:` | **`amendments_applied`**(V12 선례 L684-697). `gate:`(원문)는 무수정, 신규 키는 `gates:` 아래 |
| R4 | `evaluations_spent` 0→2 정정 위치 | V13-D2′ A6 한 곳에서만 |
| R5 | 80% 대역 정의 | **델타법**: `se(P)=P(1−P)·sqrt(zᵀCov(β)z)`, `Cov(β)`=동결 시 정지 블록 부트스트랩(ℓ13/B2000/seed 20260907) 3×3, `band80=clip(P±1.2816·se)`. 라벨 "계수 불확실성 기준 — 보정 대역 아님". 사다리 json의 se는 손실차 se라 오용 금지. V13-D2′에 사전등록 |
| R6 | 신선도 | NYSE 거래일 달력 `missing_sessions ≤ 1` (`ai_fc.ledger_audit._last_market_day` 재사용). 화~토 01:35 UTC refresh·월요일 4일 공백·토 01:30 pages cron을 정직하게 처리 |
| R7 | T2/T3 전환 | 계약 `publication.display_tier: t0_internal|t2_hidden_panel|t3_live_card` 한 줄. 코드 변경 0. **T2는 UI 숨김이지 payload(`data.json`) 비공개가 아님** → V13-D4 결정문에 명기 |
| R8 | 결정 ID 충돌 | 표시 설계 V13-D4(T2)·D5(T3) 유지; 검토의 "V13-D4 배선" = **V13-D6** |
| R9 | 홀드아웃 finalist | `holdout_maximum_finalists: 3` + `holdout_finalists_preregistered: [V13VOL_champion]` (검토 "3슬롯 중 1") |
| R10 | 승인 원장 | 신규 `data/timeseries_v13/ledgers/approvals.jsonl` (display_promotions 영수증은 표시 승격 전용 레지스트리) — 필드 스키마는 동일 |

## 구현 순서 (사용자 결정 2026-09-08 확정)

**A(사전등록+거버넌스) → B(C-1 PB rung) → C(champion 동결) → D(표시 T2 구축) → E(워크플로 → V13-D4 T2 검수 → V13-D5 T3 즉시, `<b>홀드아웃 미검증</b>` 상시) → [정지: C-1 결과·finalist·hold 판정 보고 후 V13-D3 승인 문자열 질문] → F(승인 원문 수신 시만) → G(홀드아웃 PASS 셀만)**.

사용자 결정 4항: ① 거버넌스 순(재동결 0회) ② T3는 T2 검수 통과 즉시(홀드아웃 선행 안 함, caveat 굵게) ③ 홀드아웃은 C-1 뒤 즉시 질문·정지(사전 승인 없음, 자동 실행 없음) ④ 푸시는 브랜치 push + PR만(리프스펙 FF 0회; GitHub 병합은 사용자 또는 지시 시 `gh pr merge`).

Phase 단위 브랜치 커밋. 시작 전 `git merge origin/main`(bc87496d) → `inventory` 재생성 → 충돌은 `inventory.generated.md`만 예상. T2/T3 검수 스크린샷은 사용자 확인용으로 SendUserFile.

---

## Phase A — V13-D2′ 사전등록 개정 + 거버넌스 기록 (결과 무관·결과 전 커밋)

**A1 계약** `data/contracts/multivariate_timeseries_v13_vol.yaml` — 기존 키 무수정, 추가:
- `baselines.persistence_pb`: `logit(P | 당일 수준 1피처)` (vix 셀 VIX_t, rv 셀 RV21_t; 절편 포함; 적합기 `_logit_fit` 동일; `nested_in: ewma_logit`; D-2 자명 기준선 역할)
- `gates.armed: false`(V13-D4에서 true), `gates.G2_champion_vs_persistence_pb`: 쌍대 Brier `d=BS_PB−BS_EWMA`, 양방향, 동일 부트스트랩, 규칙 (a) 양방향 CI90 하한>0 ∧ 증분 y-block 귀무≤0.10 → EWMA (b) 아니면 PB가 기후 대비 양방향 CI90 하한>0 ∧ PB 귀무≤0.10 → **PB**(단순 우선) (c) 아니면 HOLD(finalist 제외). 근거: 중첩 모형은 동률=단순; δ>0 마진은 magnitude 임계(L52 위반), δ=MDE는 부호검정으로 퇴화.
- `gates.champion: {decided_at: null, source_content_hash: null, cells: {}, finalist_id: null}` (C-1 뒤 채움)
- `reliability.cross_fit_isotonic_h63`: 대상 `[vix25_h63, vix30_h63, rv_h63]`, k=5 연속 블록, 경계 embargo h, PAV 가중, 파생층 전용(게이트 판정은 raw), 사전등록 fallback: `(BS_raw−BS_iso)` CI90 상단<0이면 raw 유지
- `live_display`: 포인터 `data/timeseries_v13/vol/vol_latest.json`, 원장 `ledgers/vol_live.jsonl`, `freshness{rule: nyse_trading_calendar, max_missing_sessions: 1}`, `band80{method: delta_method_block_bootstrap_cov, z: 1.2816, meaning: coefficient_uncertainty_not_calibration}`, `reliability_markers{h63: weak}`, `reference_question{id: vix-25-90d, horizon_calendar_days: 90, divergence_threshold_pp: 15, action: display_only}`
- `frozen_coefficients: {path: data/timeseries_v13/vol/champion_coefficients.json, sha256: null, content_hash: null, finalist_id: null, refit_prohibited: true}` (Phase C에서 채움)
- `publication: {display_tier: t0_internal, reference_opinion_only: true, holdout_status: not_consumed}`
- `development_protocol`: `evaluations_spent: 2`(A6 정정), `holdout_maximum_finalists: 3`, `holdout_finalists_preregistered: [V13VOL_champion]`, `holdout_single_scoring_per_finalist: true`, `holdout_requires_explicit_user_approval: true`, `holdout_execution_path: absent_by_construction`, `holdout_ledger: data/timeseries_v13/ledgers/holdout_scorings.jsonl`, `approvals_ledger: data/timeseries_v13/ledgers/approvals.jsonl`
- `stopping_points.holdout` 추가: `procedure`(사전등록 커밋→승인 원문→receipt→verb 1회→결과 무관 append→DECISIONS), `finalist`, `model_source: frozen artifact(재적합 금지)`, `origins: 2015-01-01≤origin≤2018-12-31 ∧ label-complete(origin+h≤2018-12-31)`, 패널 `observation_time ≤ 2018-12-31` 절단(봉인 미열람), `gate: G1 clim CI90 하한>0 ∧ G2 PB 대비 CI90 상단≥0(유의 열위 아님) ∧ G3 신뢰도 보고 ∧ G4 홀드아웃 y-block 귀무≤0.10`, `hold_condition: finalist 표 비면 소모 안 함`, `ledger_append: 결과 무관`, `wiring_eligibility: PASS 셀만`
- `prohibitions` 추가: `champion_on_climatology_alone: true`, `holdout_refit: true`, `sealed_bytes_in_holdout_panel: true`
- `amendments_applied.V13-D2′`: approved/approval_receipt/basis(외부 검토 §C-1·C-2·D-1~D-3)/timing_rationale(홀드아웃 열람 전, 결과 전 커밋 hash)/changes A1~A7(A7 = artifact 이름 정정·band80·freshness 사전등록)/`unchanged` 영수증
- `decisions_resolved: {V13-D1, V13-D2→V13-D2′}`, `decisions_pending: {V13-D3 조건부, V13-D4 T2, V13-D5 T3, V13-D6 배선}`

**A2 원장 등록** `data/contracts/ledger_registry.yaml`(V8 블록 L314-346 뒤): `timeseries_v13_vol_experiments`(jsonl/event/medium), `timeseries_v13_holdout_scorings`(jsonl/event/high, `expected_state: planned`), `timeseries_v13_approvals`(jsonl/event/high), `timeseries_v13_vol_live`(jsonl/trading_daily/high/`allow_empty_accumulating: true`, Phase E 이후 파일 생성), `timeseries_v13_vol_ladder_results`(`data/timeseries_v13/vol/ladder_*.json`, immutable_files), `timeseries_v13_vol_coefficients`(immutable_files, `expected_state: frozen`, Phase C 뒤). `cd src && python -m ai_fc audit-ledgers`로 manifest 기준선 커밋.

**A3 승인 원장** `data/timeseries_v13/ledgers/approvals.jsonl` 신설 — 행: `receipt_id "v13-approval:<DECISION>:<date>:r1"`, `decision_id`, `approved_at`(+09:00), `approver_role "repository_owner_and_operator"`, `approval_text`(사용자 메시지 원문), `approval_scope`, `conditions`, `semantic_reference`, `source`. Phase A에서 V13-D2′·GOV-1·V12b-park 3행(같은 원문).

**A4 문서**: `docs/DECISIONS.md` 형식 B 항목 `V13-D2′`, `GOV-1`(규칙 + 2026-09-08 리프스펙 FF 푸시 4033ec6e·d6b72554 사후 기록, "이것이 아닌 것: 되돌리기 아님"), `V12b-park`, "사용자 결정 대기" 블록(V13-D3 승인 문자열 형식·V13-D6·V12-D4 CBOE 사용자 발송·FR-1 후순위·약관 재확인 12-8 형식). `docs/review/V12B_PARKED_20260908.md`(종결 문서 무수정, 재개 조건 4항: 일중 데이터·사전등록 ℓ_z/φ·건전 y-block 귀무·CRPS 무손상). `data/method_changes.jsonl` r25. `docs/MODEL_REGISTRY.md` V13-VOL 행(candidate T0).

**A5 테스트** `src/tests/test_timeseries_v13_vol_contract.py`: 개정 형 검사·완화 0(`gate.*` 리터럴 동일)·`evaluations_spent == 원장 행수`·finalist 사전등록·`champion_on_climatology_alone`·`test_v13_no_holdout_verb_exists_before_v13_d3`(cli.py grep + 모듈 부재)·원장 4종 등록·`champion null before C-1`.

**A6 검증·커밋**: `inventory`(계약 파일 수 불변이나 schema 미변 — 드리프트 확인) → `sync --check` → `audit-ledgers --check` → pytest → 커밋 `feat(v13-vol): V13-D2′ 사전등록 개정 … 결과 전 커밋` → 후속 1줄 커밋으로 hash를 `timing_rationale`에 기입.

## Phase B — C-1 PB 기준선 rung-3 (예산 3/8, 설계 데이터만, 백테스트 창 0)

- 신규 `tools/v13_vol_rung3_pb.py` (import `tools/v13_vol_run as R`, `v13_vol_rung2.reliability`): `pb_features`(1열), `paired_model_ci`(d=(pb−y)²−(ewma−y)², `R.block_boot_ci`), `pb_vs_clim = R.eval_cell(...)`, `neg_control_increment`(y-block, `R._boot_lower_fast`, draws 120), `R.neg_control(pb)`, `pav`/`apply_pav`, `cross_fit_isotonic(k=5, embargo h)`, `iso_eval`(raw vs iso, fallback), `champion_rule`(순수 함수), `finalist_id = "V13VOL_champion_"+sha256(non-hold cells)[:12]`. `R.load_panel()` 그대로(설계창 절단).
- 출력 `data/timeseries_v13/vol/ladder_pb_baseline.json`, 원장 행 `V13VOL_pb_baseline`(`rung: persistence_pb_g2`, `content_hash`), `docs/review/V13_VOL_RUNG3_PB_VERDICT_<date>.md`(9셀 EWMA−PB 표·PB-vs-clim·귀무·champion 표·h63 iso 표·hold 판정·예산 3/8).
- 테스트 `src/tests/test_v13_vol_rung3_pb.py`: 1열 피처·champion 3분기·PAV 수계산·cross-fit 단조+무누수(mask 기록 monkeypatch)·쌍대 부호 규약.
- 계약 후기록(완화 아님): `gates.champion.*` 채움, `evaluations_spent: 3`, 테스트 반전(`champion matches ledger row`), method_changes r26(`champion_changed` iff PB 셀 존재), DECISIONS V13-D3 조건 대기 갱신. 커밋.
- **결정 게이트**: finalist 비면(전 셀 HOLD) → V13-D3 보류 기록, Phase F·G 불가(표시는 T0 유지 → Phase D는 구축만).

## Phase C — champion 계수 동결 (Phase B 뒤)

- 신규 패키지 `src/ai_fc/timeseries_v13/{__init__, contracts, features, pipeline}.py` (비봉인; `tools/`가 패키지를 import, 역방향 금지; **pandas 금지**, numpy만).
  - `contracts.py`: MODEL_ID `event_probability.volatility_v13`, PROBABILITY_SPACE `research_volatility_v13_base_rate`, 경로 상수, `CELL_ORDER`(9), `DISPLAY_TIERS`, `EWMA_ALPHA=2/22`, `Z80`, `canonical_hash`(`timeseries_v8.contracts` 공개 재수출), `TimeSeriesV13VolError(RuntimeError)`, `load_contract_v13`, `display_tier`, `load_frozen_coefficients(expected_sha256, expected_content_hash, expected_finalist_id)`
  - `features.py`: `build_panel`(VIX∩NASDAQCOM, rv21 = pandas rolling(21) 재현), `ewma`(`_ewma` 동일: 시드 x[0], 비유한 carry-forward, **전체 이력 연속**), `fill_rv_nan(rv, frozen_median)`, `logit_fit/logit_predict`(`_logit_fit/_logit_pred` 동일 수식), `delta_method_se`, `block_bootstrap_cov`, `pav_apply`, `cell_specs`
- 신규 `tools/v13_vol_freeze_coefficients.py`: `gates.champion.finalist_id` null이면 거부; 셀별 champion 모형(EWMA β3/μ2/σ2 또는 PB β2/μ1/σ1)을 설계창 전체(2007-01-03~2014-12-31, n≈2014) 1회 적합; EWMA champion 셀엔 `baseline_pb`도 동결(홀드아웃 G2용); h63 iso 대상 셀엔 `iso_map`; `cov_beta` 부트스트랩; **G0 대사**: numpy 피처로 early/late 반창 재적합 → `ladder_ewma_logit.json` 18개 BSS와 `≤1e-6` 불일치 시 쓰지 않음; 기록 `alpha_ewma`, `ewma_seed_rule`, `rv_definition`, `rv_nan_fill_median=0.1694207105468098`(rv_nan_count 21), `theta_rv=0.1694`, `hyperparameters`, `fit_window`, `n_fit`, `clim_base_rate`, `inputs_sha256{VIX,NASDAQCOM}`, `gate_evidence`, `provenance`, `content_hash`; stdout에 sha256·content_hash 인쇄 → 계약 `frozen_coefficients` 핀.
- 테스트 `src/tests/test_timeseries_v13_vol.py`: pandas 패리티(`importorskip`, atol 1e-10, NaN 21 위치)·logit 동일성·ewma 연속 실행 증명·NaN 채움 동결값·핀 일치(실제 repo: sha256·content_hash·finalist_id·reconciliation pass)·델타 대역 범위.
- 원장 등록(A2의 coefficients 항목 활성) → `audit-ledgers` 기준선 → 커밋.

## Phase D — 표시 파이프라인 + 읽기모델 + 대시보드 숨김 패널(T2 구축, tier는 t0 유지)

**D1 라이브 파이프라인** `src/ai_fc/timeseries_v13/pipeline.py`: `publish_latest_timeseries_v13_vol(root, *, now=None)` — 계약 `gates.armed` 확인 → 동결 계수 핀 대조 → `read_market_observations(root, knowledge_cutoff=now)`(read-only) → 전체 이력 피처 → 최신 행 9셀 `p/se/band80` → 거래일 신선도 → 포인터 `data/timeseries_v13/vol/vol_latest.json`(`status live|hold`, `customer_numbers_visible ⇔ live ⇔ gate 4항`, hold면 `cells/inputs` 부재, `content_hash`) → 원장 `_chain_append` 로컬 복제 + `timeseries_v8.artifact.append_unique`(같은 `as_of` 재실행은 skip). `verify_timeseries_v13_vol(root)`: 체인·핀·포인터 해시·아카이브 재계산 대사(abs diff<1e-9).
**D2 CLI** `src/ai_fc/cli.py`(L458-480 옆): `timeseries-v13-vol-latest`, `timeseries-v13-vol-verify` (`_timeseries_exit`).
**D3 표시 모듈** `src/ai_fc/timeseries_v13_vol_display.py`(stdlib+yaml+`ledger_audit._last_market_day`; 봉인 밖; v8 L1-13 사유 승계): `validate_latest`(content_hash·visibility⇔gate·reference_opinion_only·combined_with_* False·trading_signal False·hold면 cells 부재·live면 9셀 범위/대역 순서)·`_coefficients_pinned`(계약 핀==포인터==디스크 sha 3자 일치)·`_freshness`(빌드 시 재평가)·`build_projection(tier…)`(t0면 숫자 제거)·`load_projection`(**항상 dict**: absent|internal|hold|live; 마지막 값 캐시 금지). 투영 키: `schema_version, model_id, model_version, status, probability_space, probability_unit, combined_with_existing_models:false, numbers_visible, display_state, publication{display_tier, reference_opinion_only, holdout_status, holdout_caveat_bold, trading_signal}, gate{…reasons[]}, as_of, knowledge_cutoff, freshness, coefficients{sha256}, design_evidence, reference_question, inputs, cells, footnote`. `holdout_caveat_bold = tier==t3 ∧ holdout_status≠pass`.
**D4 읽기모델** `src/ai_fc/read_model_contract.py`: `V2_KEYS`에 `"timeseries_v13_vol": dict`(`timeseries` 슬롯 재사용 금지), `schema()` properties(required 10키·enum), `validate()` 블록(model_id/space/combined False/reference_opinion_only/trading_signal False/`numbers_visible is (status=="live")`/visible→gate 4항·9셀/not visible→cells·inputs 부재/t0→numbers False/t3∧≠pass→bold True) → `cd src && python -m ai_fc inventory`로 `docs/generated/read_model_v2.schema.json` 재생성. 테스트 `test_read_model_contract.py`: `_minimal_model()`에 absent 최소형 추가 + 6개 케이스; `test_dashboard.py::test_read_model_shape` 키 추가.
**D5 dashboard.py**: 상수 `TIMESERIES_V13_VOL_BUDGET_BYTES=24_000`·`TIMESERIES_V13_VOL_FILENAME`; L447-459 뒤 `load_timeseries_v13_vol_projection(root)` + 예산 가드(L850-861 패턴); `model[...]` L656 다음 `"timeseries_v13_vol"`; `write_dashboard`에 `reports/timeseries_v13_vol.json` 사이드카(로컬 검수); `write_pages`는 인라인이라 무변경. `data/contracts/dashboard_payload.yaml` `timeseries_v13_vol_max_bytes: 24000` + 섹션; `test_timeseries_redesign.py::test_payload_budget_declarations_match_code`에 assert 추가. "목표가" 부분문자열 금지.
**D6 dashboard.js/css**: `TS_TABS` 리터럴 보존(test_dashboard.py:1125) + `TS_V13_TAB=['volatility','변동성 기준율','05']`; `timeseriesTabsMarkup` 5탭; `UI_TERMS` 5항(persistence/base_rate/business_day/band80_coef/v13_weak); `timeseriesV13TabEnabled(v13)`(t3 또는 t2∧`?review=v13vol`); `renderTimeseriesV13VolPanel(v13)` — X1 6항 내장: ①제목 "변동성 지속성 base rate"·셀 "기준율"(예측 단어 금지) ②회색 배지 "수치모델 · 지속성" 상시 ③열 머리 "5/21/63영업일(≈90달력일)" ④caveat lead 상시 "설계창(2007-2014) 스킬 · **홀드아웃 미검증** · 참고 의견 — 매매 신호 아님" ⑤역할 문장 + 괴리 칩(`DATA.questions` `latest_prob` 퍼센트 정수 vs `round(p*100)`, ≥15 → "표시만(자동 조정 없음)") ⑥결합·평균·컨센서스 산식 0; 게이트 스트립 칩(기후 BSS/양방향/건전귀무/신선도·기준일(미국 거래일 종가)·VIX/홀드아웃); h63 `▲ 보정 약함` 텍스트 마커+80% 대역; hold → `timeseries-hold-reasons`; t0 → `timeseries-pending`; 모바일 지평 탭 `data-v13-h-tab`; 3개 렌더 경로(`renderTimeseriesV8`·`renderTimeseries` HOLD·레거시)에 `panel('volatility',…)` + 공용 `bindTimeseriesTabs`; `MID_CATEGORIES.timeseries` 레일 항목 `available:()=>…display_tier==='t3_live_card'`. CSS `.v13-vol-*`, 620px 지평 탭, 359px 세로 헤더; 배지·caveat 어떤 폭에서도 접지 않음. 줄 끝 `//` 주석 금지(node --check 테스트).
**D7 테스트**: `test_timeseries_v13_vol_display.py`(v8 미러 9케이스: absent·hash 변조·visibility>gate·hold cells·핀 불일치·주말 허용 신선도·t0 숫자 제거·t3 bold·e2e), `test_dashboard.py` 3건(hidden 기본·X1 6항 문자열·레일 tier 게이트), `test_write_pages` absent/internal 확인·24KB 초과 raise.
**D8 계보** `data/contracts/website_data_lineage_v1.yaml`(L203-241 템플릿) surface `volatility_base_rate_v13` — `source_artifacts` 존재 검사(test_website_data_lineage.py:78-80) 때문에 **포인터·원장 파일이 커밋된 뒤** 추가.

## Phase E — 라이브 워크플로 + T2 승격(V13-D4) + T3(V13-D5)

- `.github/workflows/timeseries-v13-vol-live.yml`(v8-shadow 미러): cron `40 3 * * 2-6`, `workflow_dispatch`, `contents: write`, concurrency `investing-data-writer-v13`, pip `.[pit,timeseries]`, `timeseries-v13-vol-latest` → `-verify` → v13 pytest → `inventory` → `git add data/timeseries_v13/vol/vol_latest.json data/timeseries_v13/ledgers/vol_live.jsonl docs/generated/inventory.generated.md`(unexpected 가드 정규식; 계수·계약·실험 원장은 allowlist 밖) → `pull --rebase` → push. `pages.yml:23`·`verify.yml:8` workflow_run 목록에 추가. 첫 실행은 로컬 1회(`timeseries-v13-vol-latest`) 산출물 커밋 → D8 계보 추가.
- **V13-D4(T2 진입)**: 로컬 tier 임시 `t2_hidden_panel` → `sync --rebuild` → `dashboard --pages-out ../_site` → 정적 서버 `#timeseries/volatility?review=v13vol` **탭 활성 상태** 1279/620/375 스크린샷 → X1 6항 체크리스트 + h63 마커 + HOLD 재현(hash 한 글자 변조) → 되돌림. 승인 시: DECISIONS V13-D4(D-g "payload에 숫자 실림" 명기), method_changes, approvals 행, 계약 `gates.armed: true` + `display_tier: t2_hidden_panel` + `amendments_applied.V13-D4`. 커밋·PR.
- **V13-D5(T3)**: 계약 `display_tier: t3_live_card` 한 줄(+amendment). 홀드아웃 미통과면 `holdout_status: not_consumed` → 가드가 `holdout_caveat_bold` 강제(`<b>홀드아웃 미검증</b>` 상시). 라이브 확인: 배포 후 `#timeseries/volatility` 탭 활성 스크린샷 3폭·X1 재검. T4는 enum에 없음(구조적 차단).

## Phase F — 홀드아웃 1슬롯 소모 V13-D3 (**사용자 명시 승인 시에만**, 자동 실행 절대 금지)

- 승인 문자열 형식: `V13-D3 홀드아웃 1회 소모 승인 finalist=<finalist_id>` (literal `V13-D3`·승인·정확한 finalist_id 포함). 승인 시 approvals.jsonl 행 → 계약 `holdout_execution_path: named_verb_guarded` + `amendments_applied.V13-D3` → 커밋 **뒤** 실행.
- 신규 `src/ai_fc/timeseries_v13/holdout.py`(V9 pipeline.py L172-186·L205-209·L259-264 패턴): `_require_approval`(빈 문자열/미존재 receipt/decision_id≠V13-D3/finalist 불일치 → raise, **데이터 읽기 전**), `_require_budget`(같은 finalist 재소모·3 초과·미사전등록 → raise), `_load_frozen`(sha·finalist 일치; 적합 함수 부재), `_holdout_panel`(`observation_time ≤ 2018-12-31` 절단, 2007~2018 연속 피처, origins = 창 ∧ label-complete), `score_holdout` → 셀별 G1/G2/G3/G4 + family P → `holdout_scorings.jsonl` **결과 무관 append**(`holdout_user_approval` 원문·receipt_id·coefficients_sha256·contract_hash·git_head·content_hash) + `data/timeseries_v13/runs/holdout_<finalist_id>.json`. `verify_timeseries_v13`.
- CLI `timeseries-v13-vol-holdout --approval-receipt <id>`(기본 "" → 거부, `--force`·env 없음), 워크플로 미참조(테스트 grep).
- 테스트 `test_timeseries_v13_holdout.py` 8건(승인 없이 거부·bogus receipt·2회 거부·예산·홀드아웃 창만·결과 무관 append·재적합 경로 부재·워크플로 미참조).
- 드라이런(반드시 실패): 승인 없이 exit 1, bogus exit 1, `holdout_scorings.jsonl` 부재 → 실제 1회 → `docs/review/V13_VOL_HOLDOUT_VERDICT_<date>.md`, 계약 `stopping_points.holdout.consumed{…}` + `publication.holdout_status: pass|fail`, method_changes r27, DECISIONS V13-D3. hold_condition(전 셀 HOLD)이면 소모 안 함.

## Phase G — C-3 base rate 배선 V13-D6 (홀드아웃 **PASS 셀 한정**)

- 허용: (a) `data/base_rates/volatility_v13_auto.md`(스킬/사람 경로; `scan_stale_base_rates`가 `*_auto.md` skip) (b) `due` 괴리 표시 전용(운영 CLI) (c) 대시보드는 V13-D4 X1 경로. 금지: `ml_digest_with_meta`/`reasoning_core` aux_context 주입, `data/ml_history` 행, `orchestrator.py:179-194` 변경, 자동 재예측, 산술 결합, `forecasts/`·`calibration/`·`questions/registry.yaml` 쓰기.
- 신규 `src/ai_fc/timeseries_v13/mapping.py` `V13_VOL_MAPS=(VolQuestionMap("vix-25-90d","vix25_h63", 정의차 ≥25 vs >25.00, 63영업일≈90달력일, above_path),)`; `timeseries_v13/base_rates.py` `render_base_rates`(ml/runner.py:343-379 미러; PASS 셀만, "base rate 참조 — LLM 예측과 산술 결합 금지 · 매매 신호 아님")·`write_base_rates`·`latest_vol_refs(root, now) -> dict[qid, MlRef]`(표시 로더 fail-closed 경유, stale→{}); `registry.py::compute_due(..., vol_refs=None)` 5b 블록(L226-239 복제, kind "divergence" 재사용 → `kind_order`·cli 1556 제외 유지); `cli.py cmd_due`에 `vol_refs=`; CLI `timeseries-v13-vol-base-rates --no-write`. 테스트 4건(`test_timeseries_v13_base_rates.py`) + 기존 `test_divergence_due.py` 회귀 0.
- 기록: DECISIONS V13-D6, method_changes r28(`display_only: true`), MODEL_REGISTRY → reference.

## 사용자 소유 행동(계획 밖, 기록만)
CBOE DataShop QQQ 발송(V12-D4, `docs/design/v13_cboe_datashop_qqq_request_260907.md`, 12-8 형식 기록), FirstRate 구매(FR-1 후순위, 라이선스 캡처 12-6/12-8), 약관 재확인(§A-3), V13-D3 승인 문자열, Codex 워크트리 main 잠금 해제 여부.

## 검증 (각 Phase 커밋 전)
```
cd C:/workspace/ai-investing/src
python -m pytest tests -q
python -m ai_fc sync --check
python -m ai_fc inventory && python -m ai_fc inventory --check
python -m ai_fc audit-ledgers && python -m ai_fc audit-ledgers --check
python -m ai_fc timeseries-v13-vol-latest && python -m ai_fc timeseries-v13-vol-verify
python -m ai_fc dashboard --pages-out ../_site   # data.json 의 timeseries_v13_vol status/tier/bytes 확인
ruff check ../tools/v13_vol_rung3_pb.py ../tools/v13_vol_freeze_coefficients.py ai_fc/timeseries_v13 ai_fc/timeseries_v13_vol_display.py
git diff --stat origin/main -- src/ai_fc/timeseries_v8 src/ai_fc/timeseries_v2 forecasts calibration data/timeseries_v8   # 비어야 함
```
브라우저: 탭 활성 상태에서 1279/620/375 스크린샷(rAF 함정), X1 6항 체크리스트, HOLD 재현. 홀드아웃 verb는 승인 없이 반드시 실패. 푸시: `git worktree list` 확인 → 브랜치 push → PR → GitHub 병합(리프스펙 금지). 시크릿 스캔·HEAD 확인 후 push.

## 핵심 파일
- `data/contracts/multivariate_timeseries_v13_vol.yaml` — V13-D2′ 개정·champion·핀·tier·amendments_applied
- `tools/v13_vol_rung3_pb.py`(신규), `tools/v13_vol_freeze_coefficients.py`(신규), `tools/v13_vol_run.py`(재사용)
- `src/ai_fc/timeseries_v13/{contracts,features,pipeline,holdout,mapping,base_rates}.py`(신규 비봉인 패키지)
- `src/ai_fc/timeseries_v13_vol_display.py`(신규), `src/ai_fc/read_model_contract.py`, `src/ai_fc/dashboard.py`, `src/ai_fc/dashboard_parts/dashboard.{js,css}`, `src/ai_fc/cli.py`, `src/ai_fc/registry.py`
- `data/contracts/{ledger_registry,dashboard_payload,website_data_lineage_v1}.yaml`, `.github/workflows/{timeseries-v13-vol-live,pages,verify}.yml`
- `docs/DECISIONS.md`, `data/method_changes.jsonl`, `data/timeseries_v13/ledgers/approvals.jsonl`(신규), `docs/review/V12B_PARKED_20260908.md`(신규)
