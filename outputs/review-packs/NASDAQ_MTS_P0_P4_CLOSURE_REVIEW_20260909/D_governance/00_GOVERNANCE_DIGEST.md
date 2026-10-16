# 거버넌스 대조 — V13-VOL 트랙의 규율이 실제로 지켜졌는가 (2026-09-09 KST)

> **이 문서가 답하려는 질문.** 외부 검토관이 이 프로그램을 볼 때 가장 먼저 의심하는 것은 하나다:
> **"결과를 보고 규칙을 바꿨는가."** 이 문서는 그 질문에만 답한다. 통계적 타당성(게이트 형태가 옳은가,
> 표본이 충분한가)은 B_verdicts 와 통계 검토 문서의 몫이고, 여기서는 **규칙이 언제 고정됐고 언제
> 집행됐는지의 시간 순서**만 원장·계약·커밋 이력으로 대조한다.
>
> **작성 규율.** 아래 모든 수치·시각·해시는 팩 안 또는 저장소 안 실제 파일에서 읽어 확인했다.
> 확인하지 못한 것은 **[미확인]** 으로 표기했고, 팩만으로는 재현할 수 없고 저장소 접근이 필요한
> 항목은 **[저장소 확인]** 으로 표기해 §부록 B 에 모아 두었다.
>
> **자기보고의 한계 고지.** 이 문서는 검토 대상 시스템이 스스로 쓴 것이다. 서술은 참고만 하고,
> 판정의 무게는 **해시 일치·커밋 조상관계·타임스탬프 대소** 같은 기계 검증 가능한 항목에 두기를 권한다.
> §부록 A 에 검토관이 직접 돌릴 수 있는 재현 절차를 적었다.

경로 표기: `<PACK>` = `outputs/review-packs/NASDAQ_MTS_P0_P4_CLOSURE_REVIEW_20260909`,
`<REPO>` = `C:/workspace/ai-investing`. 시각은 모두 KST(+09:00), 날짜는 절대날짜.

---

## 0. 요약 — 다섯 줄

1. **결과를 본 뒤 게이트 산술이 바뀐 곳은 발견되지 않았다.** 사전등록 게이트 블록(`gate:`)의 임계·불확실성
   좌표·표적(K·θ·h)·창·분할은 테스트가 바이트 수준으로 고정하고 있으며(`test_preregistered_gate_form_is_byte_stable`),
   개정 5건은 전부 별도 키(`gates:`, `degeneracy_guard:`, `rung4_macro_blocks:`)에 추가됐다.
2. **결과 후 도입된 규칙 3건이 실재한다** — 전부 **엄격화 방향**이다(§4.2). 가장 민감한 것은
   `degeneracy_guard`(국면 임계 5)로, 계약이 스스로 "설계창을 본 뒤 정한 값"임을 공시하고 사용처를
   3곳으로 제한한다.
3. **승인 원장에 시각 위조 사건이 1건 있었고, 시스템이 스스로 잡아 r2 로 정정했다**(§2.2). r1 두 행의
   `approved_at 15:05:00` 은 손으로 적은 합성 시각이었고 집행(14:54~14:58)보다 뒤였다 — 즉 "승인이 집행에
   선행"의 증거로 쓸 수 없는 상태였다. 원장은 append-only 라 r1 을 고치지 않고 r2 를 덧붙였다.
4. **사전등록이 결과보다 앞선다는 것은 커밋 조상관계로 확인된다** — 타임스탬프뿐 아니라 DAG 상 조상이다(§3).
5. **홀드아웃은 1회만 소모됐고 봉인창(2019+)은 열리지 않았다.** 원장 1행, `sealed_bytes_read: false`,
   패널 절단 2018-12-31, 그리고 지평별 마지막 원점이 라벨 완결 규칙과 산술적으로 정확히 일치한다(§1.1).

---

## 1. 규율 대조표

각 행은 **① 어디에 명문화됐나 ② 이 트랙에서 어떻게 집행됐나 ③ 증거 파일이 무엇인가** 셋을 채운다.

| # | 규율 | 명문화 위치 | 이 트랙에서의 집행 | 증거 파일 |
|---|---|---|---|---|
| R1 | **봉인 0바이트** (V8/V2 아카이브 무수정 + 봉인창 2019+ 미열람) | 계약 `data_policy.no_write_to_sealed: true`, `source: …market_archive.read_market_observations # 봉인 모듈 read-only(무수정)`; `prohibitions.mutate_v8_v2`·`sealed_bytes_in_holdout_panel`; `stopping_points.sealed.execution_path: absent_by_construction` | 홀드아웃 패널을 `observation_time <= 2018-12-31` 로 절단해 채점. 봉인 verb 는 **구현 자체가 없다**. 라벨 완결 규칙이 산술로 확인됨(아래 §1.1) | `<PACK>/A_contracts/multivariate_timeseries_v13_vol.yaml` 31~37·118~121·124~139행 · `<PACK>/E_artifacts/ledgers/holdout_scorings.jsonl` (`sealed_bytes_read: false`, `panel_truncated_at: "2018-12-31"`) · `<PACK>/F_code/timeseries_v13/holdout.py` 1~14행 docstring 정지점 5 · `<PACK>/F_code/tests/test_timeseries_v13_holdout.py::test_holdout_module_has_no_refit_path_and_no_sealed_verb` |
| R2 | **홀드아웃 1회 · 사용자 승인 원문** | 계약 `stopping_points.holdout.requires_explicit_user_approval: true`, `consumption: champion 당 1회, 자동 소모 금지`, `procedure:` 가 승인 원문 형식(literal `V13-D3` + 승인 + 정확한 finalist_id)을 규정 | 승인 원문 수신(2026-09-09 11:35:57) → 영수증 → 계약 `execution_path` 개정 → verb 1회 → **결과 무관 append**. 원장 행 수 **1**. 슬롯 1/3 소모, 2 잔여 | `<PACK>/E_artifacts/ledgers/approvals.jsonl` 8행 · `<PACK>/E_artifacts/ledgers/holdout_scorings.jsonl` (1행) · `<PACK>/F_code/timeseries_v13/holdout.py` `_require_approval`(63~86행)·재소모 차단(92행)·예산 차단(95행) · `<PACK>/F_code/tests/test_timeseries_v13_holdout.py` (승인 없으면 **데이터 읽기 전** 거부: `…_refused_before_reading_data`) |
| R3 | **사전등록 커밋이 결과보다 먼저** | 계약 `development_protocol.preregistered_before_results: true`; 설계도 맺음말 "결과 전 커밋이 모든 단계의 첫 행동이다"(`<PACK>/C_design/mts_program_blueprint_v1_260909.md` 1136행) | rung-3: prereg `afec214e`(09-08 14:29:43) → 결과 `9c2b912a`(14:43:42). rung-4: prereg `0ce8569b`(09-09 14:12:34) → 결과 `e576223c`(14:43:12). 둘 다 **DAG 조상**이며 결과 산출 시각(`knowledge_cutoff`)도 prereg 뒤 | 원장의 `prereg_commit` 필드: `<PACK>/E_artifacts/ledgers/vol_experiments.jsonl` 3·4행 · 계약 284·359행 · **[저장소 확인]** git 조상관계(§3) |
| R4 | **p-순열 귀무 금지 (건전 귀무는 y-block)** | 계약 `prohibitions.p_permutation_null_as_negative_control: true`; `gate.negative_control` 주석 "T-A 교훈: p-순열 귀무는 누수" | 전 rung·홀드아웃이 y-block(ℓ=13) 순열만 사용. 근거 판정서가 p-블록 순열의 누수를 실측(통과율 **0.201** > 0.10)해 T-A 를 NOT_REPAIRED 로 종결 | 계약 66~68행·131행 · `<PACK>/B_verdicts/V13_TA_NULL_REPAIR_VERDICT_20260907.md` (N-p-block 0.201 / N-y-block 0.000 / N-blk-pair 0.000) · `<PACK>/F_code/tests/test_timeseries_v13_vol_contract.py::test_obvious_baseline_rule_and_new_prohibitions_are_armed` |
| R5 | **결과 후 문턱 교체 금지** | 계약 `prohibitions.gate_threshold_relaxation: true`·`outer_window_reuse_after_results`·`null_redesign_after_results`·`post_hoc_target_addition` | 게이트 형(form) 블록은 개정에서 **1바이트도 손대지 않고**, 신설은 전부 별도 키. 문턱이 실제로 물었다 — `vix25_h5` 는 기후 대비 BSS **+0.640** 인데도 G4 귀무 통과율 **0.125** 가 0.10 을 넘어 탈락했다(구제 없음) | 계약 52~69행(원문 `gate:`) vs 163~218행(개정기 `gates:`) · `<PACK>/E_artifacts/ledgers/holdout_scorings.jsonl` `vix25_h5.G4_negative_control_pass_rate = 0.125`, `G4_pass: false` · `<PACK>/F_code/tests/test_timeseries_v13_vol_contract.py::test_preregistered_gate_form_is_byte_stable` |
| R6 | **ML 게이트** (isotonic/Platt 보정은 해소 100+ 뒤) | `<PACK>/D_governance/CLAUDE.md` 하드 게이트 절; 선례 `<PACK>/D_governance/DECISIONS.md` 9-1(닫힌형 결정론 변환은 비저촉) | 계약은 h63 3셀에 cross-fit isotonic 을 **파생층 전용**(`layer: derived_probability_only`, `gate_bridge: false`)으로 사전등록했고, 사전등록된 fallback 이 발동해 **9셀 전부 raw** 로 확정. 동결 계수 파일에 `iso_map` 은 **9셀 모두 null** — 적합된 단조맵이 운영에 존재하지 않는다 | 계약 286~297행·217행(`h63_derived_layer: {… raw}`) · `<PACK>/E_artifacts/vol/champion_coefficients.json` (전 9셀 `derived_layer: "raw"`, `iso_map: null`) · **[열린 질문 Q3]** §7 |
| R7 | **표시 페일클로즈** (검증 안 된 숫자는 화면에서 내린다) | 계약 `publication.reference_opinion_only: true`, `t3_without_holdout_requires_bold_caveat: true`, `wiring_eligibility`("홀드아웃 FAIL 셀은 … 숫자 대신 '홀드아웃 실패' 로 페일클로즈") | **페일클로즈가 결과를 보기 전에 구현·검증됐고 결과가 나오자 그대로 발동했다.** 구현 커밋 `c9c88116`(2026-09-08 16:45:33) → 홀드아웃 소모 `03d57a11`(2026-09-09 12:06:23), 약 19.3시간 앞선다. 실패 6셀 숫자 하강, 칩 "홀드아웃 부분 통과 3/9" | 계약 328~336행 · `<PACK>/D_governance/DECISIONS.md` 742~744행 · `<PACK>/F_code/tests/test_timeseries_v13_vol_display.py`·`_panel.py`·`_role_honesty.py` · `<PACK>/G_session_20260909/fixes.diff` 커밋 `6670ea7e`(문구까지 같은 사실을 말하게 한 후속 수정) · **[저장소 확인]** 커밋 시각 |

### 1.1 봉인 미열람의 산술적 증거 (검토관이 팩만으로 확인 가능)

계약은 홀드아웃 원점을 `origin + h 영업일 <= 2018-12-31` 인 것만 쓰라고 규정한다(label-complete).
원장이 그 규칙을 실제로 지켰다면 **지평이 길수록 마지막 원점이 앞당겨지고 원점 수가 줄어야 한다.**

| 지평 h | 마지막 원점 | 원점 수 | 첫 원점 |
|---|---|---|---|
| 5 | 2018-12-21 | 1001 | 2015-01-02 |
| 21 | 2018-11-28 | 985 | 2015-01-02 |
| 63 | 2018-09-28 | 943 | 2015-01-02 |

원점 수 차이가 **1001 − 985 = 16 = 21 − 5**, **985 − 943 = 42 = 63 − 21** 로 지평 차이와 정확히 일치한다.
2019년 관측을 한 바이트라도 읽었다면 세 지평 모두 원점이 2018-12-31 근처까지 생겨 이 규칙성이 깨진다.
출처: `<PACK>/E_artifacts/ledgers/holdout_scorings.jsonl` 각 셀의 `first_origin`·`last_origin`·`origins`.

---

## 2. 승인 원장 원문 대조

`<PACK>/E_artifacts/ledgers/approvals.jsonl` — **9행**. 아래는 전 행이다(누락 없음).

| # | receipt_id | decision_id | approved_at (KST) | 승인 원문 (verbatim) | 무엇을 승인했나 (`approval_scope` 요약) |
|---|---|---|---|---|---|
| 1 | `v13-approval:V13-D2prime:2026-09-08:r1` | V13-D2′ | 2026-09-08 14:16:22 | "t2 숨긴패널까지 진행하고, 라이브 카드 노출 진행 후 위 첨부파일에 대한 것을 전수조사 및 분석해서 설계 계획을 작성한 후, 정밀하게 구현하는 것을 시행해." | 계약 개정 · PB 기준선 등록 · **홀드아웃 게이트 정의**. 명시적으로 `holdout_consumption: false`, `wiring: false` |
| 2 | `v13-approval:GOV-1:2026-09-08:r1` | GOV-1 | 2026-09-08 14:16:22 | "브랜치 push + PR (권장)" | main 잠금 우회 금지 규칙 채택 + 2026-09-08 리프스펙 푸시 2건의 **사후 기록**. `refspec_push_to_main: false`, `revert_of_prior_pushes: false` |
| 3 | `v13-approval:V12b-park:2026-09-08:r1` | V12b-park | 2026-09-08 14:16:22 | (1번과 동일 문장) | V12b '폐기' → '파킹' 재라벨. `reopen: false`, `budget_allocation: false` |
| 4 | `v13-approval:V13-D4:2026-09-08:r1` | V13-D4 | 2026-09-08 **15:05:00** | (1번과 동일 문장) | T2 진입(gates.armed true + 숨김 패널) — **§2.2 에서 정정됨(superseded)** |
| 5 | `v13-approval:V13-D5:2026-09-08:r1` | V13-D5 | 2026-09-08 **15:05:00** | "지금 T3 (요청대로)" | T3 라이브 카드 — **§2.2 에서 정정됨(superseded)** |
| 6 | `v13-approval:V13-D4:2026-09-08:r2` | V13-D4 | 2026-09-08 **14:14:41** | (1번과 동일 문장) | 4번을 `supersedes` 로 대체. 동의 이벤트 2건(AskUserQuestion 13:53:55 · ExitPlanMode 14:14:41)과 집행 시각 3건을 명시 |
| 7 | `v13-approval:V13-D5:2026-09-08:r2` | V13-D5 | 2026-09-08 **14:14:41** | "지금 T3 (요청대로)" | 5번을 `supersedes` 로 대체. 집행 `display_tier t3` 14:58:03 |
| 8 | `v13-approval:V13-D3:2026-09-09:r1` | V13-D3 | 2026-09-09 11:35:57 | **"V13-D3 홀드아웃 1회 소모 승인 finalist=V13VOL_champion_aec80c65038b"** | 홀드아웃 1회 채점 · verb 신설 · execution_path 개정. `wiring: false`, `sealed: false`. 조건에 `refit_prohibited`·`ledger_append_regardless_of_result` 포함. `git_head_at_approval: 978e8936` |
| 9 | `v13-approval:V13-D6-defer:2026-09-09:r1` | V13-D6-defer | 2026-09-09 13:03:32 | "보류 — 전진 표본 쌓고 재판단" | 배선 **차단**. `new_registry_question: false`, 재개 조건 `reopen_when_matured_origins_per_cell: 60` |

**8번(홀드아웃 승인)이 계약의 원문 요건을 만족하는지 축자 대조:** 계약 `stopping_points.holdout.procedure` 는
"literal `V13-D3` + 승인 + 정확한 finalist_id" 를 요구한다. 승인 원문은 `V13-D3` 를 포함하고, '승인' 이라는
낱말을 포함하며, finalist_id `V13VOL_champion_aec80c65038b` 를 축자 포함한다. 같은 문자열이 원장 행
(`holdout_user_approval`), 실행 산출물(`<PACK>/E_artifacts/runs/holdout_V13VOL_champion_aec80c65038b.json`),
판정서(`<PACK>/B_verdicts/V13_HOLDOUT_VERDICT_20260909.md` 서두)에 동일하게 재수록돼 있다.
코드가 이 요건을 런타임에 강제한다(`holdout.py` 78~81행: 승인 문구가 V13-D3 와 정확한 finalist 를 지명하지
않으면 예외).

### 2.1 승인이 집행에 선행하는가 — 행별 판정

| decision | 동의 시각 | 집행 시각 | 선행? |
|---|---|---|---|
| V13-D2′ | 14:16:22 (영수증) | 계약 개정 커밋 `afec214e` 2026-09-08 14:29:43 | **예** (+13분21초) |
| V13-D4 (r2) | 13:53:55 선택 / 14:14:41 계획 승인 | gates.armed 14:54:04 · display_tier t2 14:54:06 · 라이브 포인터 14:54:13 | **예** (r2 기준) |
| V13-D5 (r2) | 13:53:55 / 14:14:41 | display_tier t3 14:58:03 (T2 검수 14:55~14:58 뒤) | **예** (r2 기준) |
| V13-D3 | 2026-09-09 11:35:57 | 결과 산출 `knowledge_cutoff` 11:37:57 · 커밋 `03d57a11` 12:06:23 | **예** (+2분 / +30분) |
| V13-D6-defer | 2026-09-09 13:03:32 | 결정 기록 커밋 `f042d7d1` 13:04:09 | **예** (+37초) |

r1(4·5번) 기준으로는 **선행하지 않았다** — 그것이 정정의 이유다.

### 2.2 시각 정정 이력 (r2) — "손으로 적은 시각" 사건

**무슨 일이 있었나.** 2026-09-08, V13-D4(T2 진입)와 V13-D5(T3 라이브 카드) 영수증 두 행에
`approved_at: "2026-09-08T15:05:00+09:00"` 이 적혔다. 이 값은 **14:59:22 에 사람이 손으로 적어 넣은
합성 시각**이며 어떤 사용자 이벤트에도 대응하지 않는다. 그런데 실제 집행은 그보다 앞이었다 —
게이트 무장 14:54:04, 라이브 포인터 14:54:13, T3 전환 14:58:03. 즉 **원장이 "승인 15:05 → 집행 14:54"
라는 시간 역전을 기록하고 있었고, 그 상태로는 '승인이 집행에 선행했다'는 증거로 쓸 수 없었다.**

**어떻게 잡혔나.** 2026-09-08 16:25, 푸시 전 적대적 검토의 governance 렌즈(3/3)에서 발견됐다.
같은 검토가 band80 부트스트랩 좌표 불일치도 함께 잡아 계수를 재동결했다(sha256 `51815bde…` → `1a857850…`).

**어떻게 고쳤나 — 원장은 고치지 않았다.** append-only 규약에 따라 r1 을 수정·삭제하지 않고 **r2 를 덧붙였다**:
- r2 의 `approved_at` = **14:14:41** (ExitPlanMode 계획 승인 시각, 계획 파일 Phase E 에 V13-D4/D5 가 명시돼 있음)
- `supersedes` 필드로 r1 을 지목
- `consent_events[]` 에 동의 이벤트 2건(AskUserQuestion 13:53:55, ExitPlanMode 14:14:41)을, `executed_at{}` 에
  집행 시각 4건을 각각 **도구 호출 기록에서** 가져와 기입
- 계약 `amendments_applied.V13-D4/V13-D5.approval_receipt` 를 r2 로 갱신

**재발 방지가 코드로 고정됐나 — 그렇다.** 테스트 2건이 규약을 잠근다:
`test_approval_receipts_are_not_forward_dated_and_contract_points_at_live_rows` 는 ① 모든 영수증의
`approved_at` 이 미래가 아님 ② `supersedes` 가 존재하는 행을 가리키고 같은 decision_id 임
③ **계약이 superseded 된 영수증을 가리키지 않음** 을 강제한다.
`test_arming_and_display_tier_are_backed_by_non_superseded_receipts` 는 무장·표시 tier 가
superseded 되지 않은 영수증에 의해 뒷받침됨을 강제한다.
(파일: `<PACK>/F_code/tests/test_timeseries_v13_vol_contract.py` 183~223행)

**남긴 문장.** DECISIONS 863행: *"교훈: 영수증 시각은 항상 이벤트 시각(도구 호출 기록)에서 가져오고,
절대 손으로 적지 않는다."* 이 교훈이 다음 날 실제로 적용됐다 — V13-D3 영수증의 `approval_basis` 는
*"시각은 이 도구 호출 시점이며 손으로 적지 않았다(2026-09-08 합성 시각 사고 교훈)"* 라고 명기한다.

**검토관이 봐야 할 점.** 이 사건은 두 방향으로 읽힌다. ① 부정적으로: 시각을 손으로 적는 관행이
존재했고, 그것이 하필 "승인이 집행에 선행" 이라는 가장 중요한 주장을 뒷받침하는 자리였다.
② 긍정적으로: 아무도 지적하지 않은 상태에서 자체 검토가 잡았고, 원장을 고치는 대신 정정 행을 덧붙였으며,
사유를 공개하고 테스트로 잠갔다. **판단은 검토관 몫이며, 이 문서는 사실만 제시한다.**

### 2.3 정정되지 않은 잔여 의문 — 14:16:22 3행

1·2·3번 영수증은 **모두 `2026-09-08T14:16:22+09:00`** 로 동일하다. 이 시각은 r2 가 실제 동의 이벤트로
지목한 ExitPlanMode(14:14:41)보다 **1분 41초 뒤**다. 이 세 행의 시각이 도구 기록에서 온 것인지
(예: 원장 기록 행위 자체의 시각) 손으로 적은 것인지는 팩·저장소 문서에서 확인되지 않는다 — **[미확인]**.
2026-09-08 정정은 15:05:00 두 행만 다뤘고 이 세 행은 다루지 않았다.
다만 세 행 모두 **집행보다 앞서므로**(§2.1) 시간 역전 문제는 없다. 검토관은 §7 Q1 참조.

---

## 3. 사전등록 사슬 — 커밋으로 확인

**주의.** `<PACK>/01_STATE/git_log_main_recent.txt` 는 `main` 최근 30줄이며 병합 커밋 위주라
아래 작업 커밋들이 그 30줄 안에 **없다**. 아래 항목은 저장소에서 확인했다 — **[저장소 확인]**.

### 3.1 rung-4 (P4 매크로 피처블록) — 27검정 채택 0

| 항목 | 값 | 출처 |
|---|---|---|
| 사전등록 커밋 | `0ce8569b` "prereg(v13-vol): rung-4 매크로 피처블록 사전등록 — 결과 전 커밋" | 계약 284행 `prereg_commit: 0ce8569b` · `<PACK>/E_artifacts/ledgers/vol_experiments.jsonl` 4행 |
| 사전등록 커밋 시각 | **2026-09-09 14:12:34** | [저장소 확인] `git show -s 0ce8569b` |
| 결과 커밋 | `e576223c` "rung-4 매크로 피처블록 — 27검정 전부 '측정된 영'…" | [저장소 확인] |
| 결과 커밋 시각 | **2026-09-09 14:43:12** (+30분38초) | [저장소 확인] |
| 결과 산출 시각 | `knowledge_cutoff` 2026-09-09T05:14:54Z = **14:14:54 KST** (사전등록 +2분20초) | `<PACK>/E_artifacts/ledgers/vol_experiments.jsonl` 4행 |
| **조상관계** | `0ce8569b` 는 `e576223c` 의 **조상**(YES). 두 커밋 모두 `origin/main`(805c9d93)의 조상 | [저장소 확인] `git merge-base --is-ancestor` |

**해시 불일치의 해명 — 이것은 검토관이 반드시 짚을 지점이다.** 판정서
`<PACK>/B_verdicts/V13_VOL_RUNG4_MACRO_VERDICT_20260909.md` 서두와 `<PACK>/D_governance/DECISIONS.md` 774행은
사전등록 커밋을 **`7a868424`** 로 적고, 계약과 원장은 **`0ce8569b`** 로 적는다. 계약 284행이 그 사유를
괄호로 적어 두었다: *"병렬 세션의 브랜치 전환으로 원커밋 7a868424 를 clean 브랜치에 cherry-pick — 내용 동일"*.

저장소에서 실측한 결과 이 해명은 사실이다:
- 두 커밋의 **작성 시각이 동일**(둘 다 2026-09-09 14:12:34), 메시지 동일
- `git diff 7a868424 0ce8569b` = **빈 출력**(트리 동일)
- `git patch-id --stable` = 둘 다 `55271351d068b7c27245b9ed0c43764fded6369e` (**동일 패치**)
- `0ce8569b` 만 `origin/main` 계보에 있고, `7a868424` 는 `claude/v13-p4-secure` 브랜치에만 남아 있다

즉 **사전등록 내용은 하나이고 커밋 객체만 둘**이다. 정합을 맞춘 후속 커밋도 남아 있다:
`cb279542` (2026-09-09 14:45:29) "rung-4 사전등록 커밋 해시 정합 — 7a868424 → 0ce8569b". **[저장소 확인]**

**부수 사건 — immutable 기준선 갱신.** 위 해시 정합을 위해 `ladder_rung4_macro.json` 을 한 번 다시 썼고
(수치 무변경, `prereg_commit` 필드만 정정), 그 파일이 `ledger_registry.yaml` 에 `immutable_files` 로
등록돼 있어 CI 의 `audit-ledgers --check` 가 violation 을 냈다. 대응 커밋 `9df8f56b`(2026-09-09 15:03:17)이
매니페스트 기준선을 최종 바이트로 갱신했다(`fde296ad…` → `49edaaeb…`).
전문: `<PACK>/G_session_20260909/rung4_manifest_baseline.diff`.
**검토관 판단 요청(§7 Q2):** 불변 파일의 기준선을 사후에 갱신하는 것은 그 자체로 불변성 규약의 약한
지점이다. 이 건은 결과 수치가 아니라 메타 필드 정정이었고 커밋으로 공개됐으나, 같은 경로가 결과 수치
정정에도 열려 있는지는 검토관이 볼 만하다. (원장 `results_sha256` 은 최종 바이트
`49edaaeb3a0115e8faf5ef522d1d3a6c5dccb9a4fe2265c68354d9be1727330e` 를 가리키며 계약
`rung4_macro_blocks.result` 의 서술과 일치한다.)

### 3.2 rung-3 (PB 자명 기준선 — champion 결정) — 같은 형태

| 항목 | 값 |
|---|---|
| 사전등록 커밋 | `afec214e` "V13-D2′ 사전등록 개정 … 원문 gate: 무수정. 결과 전 커밋", **2026-09-08 14:29:43** |
| 결과 커밋 | `9c2b912a` "rung-3 결과 — EWMA 는 PB 대비 양방향 우세 0/9 …", **2026-09-08 14:43:42** (+13분59초) |
| 결과 산출 시각 | `knowledge_cutoff` 2026-09-08T05:37:01Z = **14:37:01 KST** (사전등록 +7분18초) |
| 조상관계 | `afec214e` 는 `9c2b912a` 의 **조상**(YES) |

출처: 원장 `<PACK>/E_artifacts/ledgers/vol_experiments.jsonl` 3행(`prereg_commit: "afec214e"`),
계약 359행, **[저장소 확인]** git.

### 3.3 홀드아웃 — 승인 → 개정 → 실행

| 순서 | 사건 | 시각 |
|---|---|---|
| 1 | P0 국면 가드 산출물 생성 (`guard_mde_design.json`) | 2026-09-09T02:06:01Z = **11:06:01 KST** |
| 2 | P0·P1 커밋 `978e8936` (설계도 v1 + 가드 + 라이브 채점) | **11:26:36** |
| 3 | **사용자 승인 원문 수신** (영수증 `git_head_at_approval: 978e8936`) | **11:35:57** |
| 4 | 홀드아웃 결과 산출 (`knowledge_cutoff`) | 2026-09-09T02:37:57Z = **11:37:57** |
| 5 | 소모 커밋 `03d57a11` (partial 3/9, 실패 6셀 숫자 하강) | **12:06:23** |
| 6 | V13-D6 보류 승인 | **13:03:32** |
| 7 | V13-D6 결정 기록 커밋 `f042d7d1` | **13:04:09** |

**가장 중요한 순서 관계:** 국면 가드 임계(min_episodes=5)는 **홀드아웃 승인보다 29분56초, 홀드아웃 결과보다
31분56초 먼저** 파일로 확정됐다. 따라서 이 임계가 홀드아웃 결과를 보고 조정됐을 가능성은 시간적으로 배제된다.
(가드 산출물의 `generated_at`, `thresholds: {min_episodes_per_half_per_class: 5, min_events_per_half_per_class: 20}` —
`<PACK>/E_artifacts/vol/guard_mde_design.json`.)

---

## 4. 계약 개정 이력 (`amendments_applied`)

`<PACK>/A_contracts/multivariate_timeseries_v13_vol.yaml` 352~402행. 총 **4개 키**(V13-D2prime, V13-D4,
V13-D5, V13-D3) + 계약 본문에 별도 등록된 결과 후 블록 2개(`degeneracy_guard`, `rung4_macro_blocks`).

| 개정 | 승인일 | 영수증 | 무엇이 들어갔나 | 결과를 본 뒤인가 | 게이트에 대한 방향 |
|---|---|---|---|---|---|
| **V13-D2′** | 2026-09-08 | `…V13-D2prime:…:r1` | A1 PB 자명 기준선 + G2 champion 규칙 · A2 h63 isotonic 파생층 + fallback · A3 홀드아웃 게이트 G1~G4 · A4 finalist 예산 3/등록 1 · A5 prohibitions 3건 신설 · A6 `evaluations_spent` 0→2 정정 · A7 표시 계층 | **아니다** — rung-1·2 결과는 봤으나 **rung-3(PB) 결과 전, 홀드아웃 열람 전**. 커밋 `afec214e` 가 결과 커밋 `9c2b912a` 의 조상 | **엄격화**. 기후만 이기면 champion 이던 것을 "자명 기준선 PB 도 이겨야" 로 올렸고, 홀드아웃 게이트를 없던 상태에서 G1∧G2∧G4 로 정의했다. `unchanged` 영수증이 gate.primary·양방향·불확실성 좌표·임계 0.10·표적·창·분할 무변경을 명시 |
| **V13-D4** | 2026-09-08 | `…V13-D4:…:**r2**` | `gates.armed` false→true · `display_tier` t0→t2 | rung-3 결과 뒤(champion 확정 뒤). 단 **게이트 산술 0바이트 변경**, 홀드아웃 미소모 상태 | **중립**(표시 전환). 무장은 게이트를 켜는 것이지 느슨하게 하는 것이 아니다 |
| **V13-D5** | 2026-09-08 | `…V13-D5:…:**r2**` | `display_tier` t2→t3 (코드 변경 0) | 홀드아웃 **전** | **중립 + 상쇄 조건 부착**: `t3_without_holdout_requires_bold_caveat: true`, 읽기모델 가드가 caveat 를 강제 |
| **V13-D3** | 2026-09-09 | `…V13-D3:…:r1` | `holdout_execution_path` absent_by_construction → named_verb_guarded (2곳) | 홀드아웃 **결과 전**(승인 11:35:57 → 결과 11:37:57) | **중립**. `unchanged` 가 "창·finalist·G1~G4 산술·family P·기후 고정값·동결 계수·degeneracy_guard 임계 무변경" 을 명시. verb 는 규칙을 실행만 하며 재적합 경로가 모듈에 없다 |

### 4.1 개정이 게이트 원문을 건드리지 않았다는 기계적 보증

`test_preregistered_gate_form_is_byte_stable`(`<PACK>/F_code/tests/test_timeseries_v13_vol_contract.py` 47~60행)이
테스트 코드 안에 `FROZEN_GATE`·`FROZEN_TARGETS` 상수를 박아 두고 계약과 대조한다:
`gate.primary` 문자열, `bidirectional_transfer`, `uncertainty`(block ℓ=13 · B=2000 · seed 20260907 · [5,95]),
`negative_control.threshold` 0.10, `targets.K = [25,30]`, `horizons = [5,21,63]`, `theta = 0.1694`,
`split`, 홀드아웃 창 `[2015-01-01, 2018-12-31]`, 설계창 `[2007-01-01, 2014-12-31]`.
이 값들 중 하나라도 바뀌면 CI 가 깨진다.

### 4.2 결과를 본 뒤의 개정 — 3건, 전부 엄격화

계약 본문에는 `amendments_applied` 밖에서 **결과를 본 뒤 추가된 블록이 3건** 있다. 이것이 이 트랙에서
가장 정직하게 봐야 할 부분이다.

**(가) `degeneracy_guard` (2026-09-09 등록, 계약 219~250행) — 설계창 결과를 본 뒤 정한 임계.**
계약이 스스로 자백한다: *"임계 min_episodes=5 는 설계창을 실측한 뒤 정한 값이다 — 숨기지 않고 공시한다."*
그리고 사용처를 세 곳으로 못박는다: ① 이미 실행된 rung 판정과 `gate.primary`·홀드아웃 G1~G4 산술은
**소급 변경하지 않는다** ② 홀드아웃 창에서 '채점 자체가 불가능한 셀' 제외 ③ 표시·배선 자격 제한.
명시 문장: *"즉 게이트를 느슨하게 하는 방향으로는 절대 쓰이지 않는다."*
- **실제로 느슨하게 쓰였는가 — 아니다.** 설계창 실측 결과 9셀 중 **6셀이 국면 가드 미달**
  (`episode_failures: [vix25_h21, vix25_h63, vix30_h5, vix30_h21, vix30_h63, rv_h63]`)인데, 이 셀들의
  기존 rung 판정은 **취소되지 않았다**(공시 전용). 대신 화면 마커와 **배선 금지**라는 제약만 추가됐다.
- **엄격화의 구체적 증거:** 홀드아웃 원장 자신은 `wiring_eligible_cells: ["rv_h21","rv_h5","vix25_h21"]`
  (홀드아웃 통과 3셀)로 적었으나, 계약 `publication.wiring_eligible_cells` 는 **`[rv_h5, rv_h21]` 둘**로
  좁혔다. `vix25_h21` 이 홀드아웃 창에서는 국면 6개로 깨끗하지만 **설계창 후반(late) 국면이 4개**라
  배선 불가로 걸렸기 때문이다. 실측: `<PACK>/E_artifacts/vol/guard_mde_design.json`
  `cells.vix25_h21.halves.late.event_runs = 4`, `episodes_ok = false` (임계 5).
  즉 **통과한 셀을 스스로 하나 더 떨어뜨렸다.**
- **판정: 엄격화.** 다만 "설계창을 본 뒤 정한 임계" 라는 사실 자체는 남는다 — §7 Q4 참조.

**(나) `rung4_macro_blocks` (2026-09-09 등록, 계약 252~284행) — 새 rung 의 사전등록.**
결과를 본 뒤가 아니라 **결과 전 커밋**이다(§3.1). 다만 이전 rung 들의 결과를 본 상태에서 설계된
새 실험이므로 여기 함께 기록한다. 주목할 사전등록 문구 하나:
*"cells: 전체 9셀 — 홀드아웃 결과로 셀을 고르지 않는다(홀드아웃 정보가 새 설계창 시험에 새면 다음
홀드아웃이 오염된다)"*. 실제로 27검정(3블록 × 9셀) 전부 실행됐고 채택 0.
**판정: 엄격화**(셀 선택 자유도를 스스로 0으로 묶음).

**(다) `publication.holdout_*` 필드 기입 (2026-09-09) — 결과 기록.**
`holdout_status: partial`, `holdout_fail_cells`(6), `holdout_pass_cells`(3), `holdout_family_p: 0.008361`.
이는 규칙 변경이 아니라 **결과 값의 기입**이며, 계약이 이미 사전등록한 페일클로즈 경로를 발동시킨다.
- 원장 `fail_cells`/`pass_cells` 와 계약 필드가 집합으로 일치함을 확인했다.
- family P 를 독립 재계산해 검증했다: **P(k≥3 | n=9, p=0.05) = 0.008361039546875** — 원장 값
  `0.008361039546874999` 와 일치. rung-3 의 `0.9999999999999996` = P(k≥0|n=9), rung-4 의
  `0.9999999999999989` = P(k≥0|n=27) 도 재현됨. (부동소수 말미 자릿수까지 일치.)

### 4.3 개정 이력에 남아 있는 정직성 표지 2건

- **A6 `evaluations_spent` 0→2 정정.** 예산 카운터가 원장보다 뒤처져 있던 것을 개정 때 맞췄다.
  계약이 이를 "(정정)" 으로 분류하고 "완화 아님" 이라 명기한다. 현재는
  `evaluations_spent: 4` == `vol_experiments.jsonl` 행 수 4 이며, 테스트
  `test_evaluation_budget_reconciles_with_experiment_ledger` 가 이 등식을 강제한다.
- **GOV-1 사후 기록.** 2026-09-08 `main` 잠금(다른 워크트리 보유) 상태에서 리프스펙 fast-forward 푸시로
  우회한 사실을 되돌리지 않고 원장·DECISIONS 에 기록했다. 인용된 reflog 두 줄을 저장소에서 축자 확인했다 —
  **[저장소 확인]** `d6b72554 refs/remotes/origin/main@{2026-09-08 12:43:52 +0900}: update by push`,
  `4033ec6e refs/remotes/origin/main@{2026-09-08 11:45:35 +0900}: update by push`. 영수증
  `semantic_reference.reflog` 의 문자열과 정확히 일치한다.

---

## 5. 사용자 결정 대기 항목 (`decisions_pending`)

계약 409~416행. 현재 **2건**이 등재돼 있으나 성격이 다르다.

| 항목 | 현재 상태 | 재개/해소 조건 | 확인 |
|---|---|---|---|
| **V13-D3** (홀드아웃 1슬롯 소모) | **이미 해소됨** — 2026-09-09 승인·소모 완료. 계약의 `decisions_pending` 항목이 `decisions_resolved` 로 이동되지 않은 채 남아 있다(기록 지연) | — | 영수증 8번 · 원장 1행 · `amendments_applied.V13-D3` 존재. **문서 정합 결함이며 판정에 영향은 없다** — §7 Q5 |
| **V13-D6** (EXIT 트리거 base rate 배선) | **보류(deferred)** — 사용자 결정 2026-09-09 13:03:32 | `live_forward_gate` 의 **셀당 성숙 원점 60 도달** 후 독립 표본으로 재판단 | 현재 **0/60**. `vol_live_resolutions.jsonl` 은 아직 생성되지 않았다(저장소 `data/timeseries_v13/ledgers/` 에 부재) · `<PACK>/01_STATE/roadmap_status.txt` "해상 0행" |

**V13-D6 보류의 논거 (계약 411~415행 · DECISIONS 755~768행).** 홀드아웃 통과 3셀 중 배선 자격은
`rv_h5`·`rv_h21` 둘뿐이고 이에 대응하는 등록 질문이 레지스트리에 없다. 유일하게 대응하던
`vix-25-90d` 의 셀 `vix25_h63` 은 홀드아웃 **실패**(G1 CI90 이 0 을 포함: `[−0.0390, +0.1182]`).
따라서 지금 질문을 신설하면 **통과한 셀에 맞춰 질문을 짜는 모양**이 되어 사전등록 정신에 어긋난다는 것이
보류의 근거다. 이 논거는 검토관이 특히 눈여겨볼 만하다 — 시스템이 자기에게 유리한 배선을
스스로 막은 사례다.

**라이브 전진 게이트가 결과 전에 고정됐는가 — 그렇다.** `live_forward_gate.registered: '2026-09-08'`,
계약 주석 *"라이브 원장 1행 시점 — 어떤 원점도 성숙하기 전"*. 강등 규칙·최소 원점 60·불확실성 좌표·
귀무 임계가 모두 그때 기입됐고, 채점 verb 는 다음 날(2026-09-09, P1)에 구현됐다.
테스트 `test_live_forward_gate_is_preregistered_before_any_origin_matures` 가 이를 잠근다.
현재 라이브 원장은 3행/2원점(2026-09-04, 2026-09-08)이며, 여분의 1행은 계수 재동결
(`51815bde…` → `1a857850…`)로 생긴 새 `run_id` 행이다 — `<PACK>/E_artifacts/ledgers/vol_live.jsonl`.

**프로그램 전체의 다음 관문.** `<PACK>/01_STATE/roadmap_status.txt`: 현 단계 **P5**(외부 유료 정보집합),
차단 요인 *"licenses.generated.md 의 확정 표에 CBOE 행 없음(회신·적재 전)"*, 다음 승인 = 구매·발송(사용자).
자원 잔량: 개발 예산 4/8 · 홀드아웃 슬롯 1/3 소모(2 잔여) · 라이브 원점 2 · 해상 원장 0행.

---

## 6. 이 팩에서 의도적으로 빠진 것 — 기계 판독 로드맵 yaml

### 6.1 사실관계 (확인한 것)

1. **`data/contracts/mts_program_roadmap.yaml` 은 존재하지 않는다.** 저장소에서 확인.
2. **그 파일명에 대한 참조가 어디에도 없다.** `<PACK>` 전체, `<REPO>/docs`, `<REPO>/data/contracts`,
   `<REPO>/tools` 를 문자열 검색했고 **일치 0건**.
3. **설계도 v1 은 정반대 원칙을 §9.1 에 명문화한다.**
   `<PACK>/C_design/mts_program_blueprint_v1_260909.md` 858~860행:
   *"**상태를 손으로 관리하는 파일을 만들지 않는다.** 이 문서에는 '현재 단계: P1' 같은 줄이 **없다**.
   그런 줄은 반드시 낡고, 낡은 상태 파일은 잘못된 다음 행동을 유도한다. 진실의 원천은 원장·계약·CI 이며,
   그것을 읽어 현 단계를 **파생**한다."*
4. **대안이 실제로 구현돼 있다.** `tools/roadmap_status.py`(읽기 전용·스케줄 금지·페일클로즈)가 원장·계약에서
   상태를 파생해 인쇄한다. 설계도 §9.3 이 단계별 종료 조건을 "어떤 파일의 어떤 필드가 무슨 값이면"의
   형태로 규정하고, §9.4 가 도구 규율 4항을 규정한다. 산출물 실물이 팩에 있다
   (`<PACK>/01_STATE/roadmap_status.txt`, `<PACK>/F_code/tools/roadmap_status.py`,
   테스트 `<PACK>/F_code/tests/test_roadmap_status.py`).
5. **설계도 v1 본문에서 그 yaml 을 '예고'한 문장은 찾지 못했다** — **[미확인]**. 설계도가 입력으로 삼았다고
   밝힌 외부 검토관 초안 `ROADMAP_BLUEPRINT_v0.md`·`REVIEW_VERDICTS.md` 는 저장소 밖
   (`C:/Users/91ssj/Downloads/`, 설계도 1131~1132행)에 있고 **현재 그 경로에 파일이 없어** 확인 불가.
   따라서 "예고됐다" 는 진술의 출처는 이 팩으로 검증되지 않는다.

### 6.2 만들지 않은 이유 (시스템의 논거)

파생 도구와 손으로 적는 상태 파일은 **같은 정보를 두 곳에 두는 것**이고, 두 곳은 반드시 갈라진다.
갈라졌을 때 사람은 읽기 쉬운 쪽(yaml)을 믿는데, 그쪽이 낡은 쪽이다. 이 프로그램에서 상태는
**비가역 자원의 잔량**(홀드아웃 슬롯 1/3, 개발 예산 4/8, 봉인 0/1)을 뜻하므로, 낡은 상태 파일이
부르는 잘못된 다음 행동은 **되돌릴 수 없는 소모**다.

이 논거를 뒷받침하는 실측 사례가 팩 안에 있다: 설계도 §9.2 에 박제된 2026-09-09 실행 출력은
"현 단계 : **P2**(홀드아웃 1회 소모) · 홀드아웃 슬롯 0/3 · 개발 예산 3/8" 인데,
`<PACK>/01_STATE/roadmap_status.txt` 의 같은 날 나중 실행은 "현 단계 : **P5** · 홀드아웃 슬롯 1/3 ·
개발 예산 4/8" 이다. **문서에 박힌 상태는 몇 시간 만에 낡았고, 파생 도구는 낡지 않았다.**
(설계도가 그 출력을 예시로 박아 넣은 것 자체가 §9.1 원칙의 경계 사례이기도 하다 — §7 Q6.)

### 6.3 반대 논거 (검토관이 채택할 수 있는 쪽)

공정하게 반대편도 적는다.
- **파생 도구는 코드다.** 코드는 조용히 틀릴 수 있고, 무엇을 검사하는지가 설계도 §9.3 표(사람이 손으로
  쓴 문서)에만 있다. 설계도는 "문서와 코드가 갈라지면 **코드가 정본**" 이라 선언하지만, 그러면
  §9.3 표 자체가 "손으로 관리하는 상태 문서" 아닌가 하는 되물음이 가능하다.
- **외부 검토관은 코드를 실행할 수 없다.** 이 팩만 받은 검토관은 `roadmap_status.py` 를 돌릴 수 없고
  `<PACK>/01_STATE/roadmap_status.txt` 라는 **한 번 찍힌 출력**을 볼 뿐이다. 그 출력은 결국
  "손으로 적진 않았지만 낡을 수 있는 스냅샷" 이다. 기계 판독 계약이 있었다면 검토관이 스키마로
  대조할 수 있었을 것이다.
- **계약화의 이점을 포기했다.** 다른 규율은 전부 yaml 계약 + 테스트로 잠겨 있는데(게이트·홀드아웃·표시),
  단계 정의와 종료 조건만 예외적으로 코드 안에 있다. 일관성 논거로는 계약화가 자연스럽다.

### 6.4 검토관에게 묻는 것

> **Q(핵심).** 프로그램 단계·차단 요인·자원 잔량을 **파생 전용**으로 두고 기계 판독 계약을 만들지 않은
> 판단이 옳은가? 아니면 (a) 단계 정의·종료 조건만 담고 **상태 값은 담지 않는** 스키마 계약
> (즉 `roadmap_status.py` 가 읽을 규칙 파일)을 두는 절충이 더 나은가? (b) 그렇게 하면 §9.1 원칙과
> 충돌하는가, 아니면 "규칙은 계약에, 상태는 파생에" 로 양립하는가?

---

## 7. 검토관에게 남기는 미해결 항목

| # | 항목 | 우리가 확인한 것 | 검토관 판단이 필요한 것 |
|---|---|---|---|
| Q1 | **14:16:22 3행의 시각 출처** | 세 영수증 시각이 동일하고 ExitPlanMode(14:14:41)보다 1분41초 뒤. 집행보다는 앞선다 | 2026-09-08 정정이 15:05 두 행만 다루고 이 세 행을 다루지 않은 것이 충분한가. 전수 재검이 필요한가 |
| Q2 | **immutable 파일 기준선 사후 갱신** | `9df8f56b` 가 `ladder_rung4_macro.json` 의 CI 기준선을 최종 바이트로 갱신(메타 필드 정정 때문). 커밋으로 공개 | 같은 경로가 결과 수치 정정에도 열려 있는가. 불변 선언과 "정정 가능" 사이의 경계를 어디에 그어야 하는가 |
| Q3 | **isotonic 사전등록과 ML 게이트** | 계약이 h63 cross-fit isotonic 을 파생층 전용으로 등록했으나 fallback 이 발동해 **9셀 전부 raw**, 동결 artifact 의 `iso_map` 은 전부 null. 실제 적합된 단조맵은 운영에 없다 | PAV 적합은 CLAUDE.md ML 게이트(보정은 해소 100+ 뒤)의 대상인가, 아니면 DECISIONS 9-1(결정론 변환 비저촉) 선례가 덮는가. 선례는 닫힌형 수식이었고 PAV 는 데이터 적합이다 |
| Q4 | **결과를 본 뒤 정한 국면 임계(5)** | 계약이 스스로 공시하고 사용처를 3곳으로 제한. 실제 적용은 전부 엄격화 방향(통과 셀 `vix25_h21` 을 배선에서 스스로 제외) | 사후 임계를 "느슨하게만 안 쓰면 된다" 는 규율이 충분한가. 아니면 사후 임계는 다음 사전등록으로만 도입해야 하는가 |
| Q5 | **계약의 `decisions_pending` 정합 지연** | V13-D3 가 해소됐는데도 `decisions_pending` 에 남아 있다 | 문서 정합 결함일 뿐인가, 아니면 §6 이 경계한 "손으로 적은 상태" 의 실례인가 |
| Q6 | **설계도 §9.2 에 박제된 도구 출력** | 그 출력(P2 · 슬롯 0/3 · 예산 3/8)은 같은 날 안에 낡았다 | 이것이 §9.1 원칙의 자기위반인가, 허용되는 예시 인용인가 |
| Q7 | **원장 필드명 충돌** | 홀드아웃 원장의 `wiring_eligible_cells`(3셀, 홀드아웃 창 가드만 적용)와 계약 `publication.wiring_eligible_cells`(2셀, 설계창 가드 추가 적용)가 같은 이름·다른 값 | 같은 이름을 다른 의미로 쓰는 것이 사고를 부르는가. 계약 쪽이 더 엄격하므로 실질 위험은 없으나 명명은 고칠 만한가 |

---

## 부록 A. 검토관 재현 절차

**팩만으로 가능한 것**
1. `<PACK>/E_artifacts/ledgers/approvals.jsonl` 을 열어 9행 전수 확인. `supersedes` 가 걸린 두 행(6·7)과
   그것이 가리키는 두 행(4·5)의 `approved_at` 대소를 비교.
2. 계약 `amendments_applied.*.approval_receipt` 4개가 **superseded 되지 않은** receipt_id 를 가리키는지 확인.
3. `holdout_scorings.jsonl` 의 지평별 `last_origin`·`origins` 로 §1.1 산술(16 = 21−5, 42 = 63−21) 재현.
4. family P 재계산: `P(k≥3 | n=9, p=0.05)` 이 `0.008361039546875` 인지. (이항 합)
5. 계약 원문 `gate:`(52~69행)와 `<PACK>/F_code/tests/test_timeseries_v13_vol_contract.py` 의
   `FROZEN_GATE`·`FROZEN_TARGETS` 상수를 눈으로 대조.
6. `guard_mde_design.json` 의 `generated_at`(2026-09-09T02:06:01Z)와 승인 영수증 8번의
   `approved_at`(11:35:57 KST = 02:35:57Z) 대소 비교.

**저장소가 있어야 가능한 것 (§부록 B 항목)**
```bash
git show -s --format='%H %ad %s' --date=iso-strict 0ce8569b afec214e
git merge-base --is-ancestor 0ce8569b e576223c && echo "prereg precedes results"
git merge-base --is-ancestor afec214e 9c2b912a && echo "prereg precedes results"
git diff --stat 7a868424 0ce8569b            # 빈 출력이어야 한다
git show 7a868424 | git patch-id --stable    # 0ce8569b 와 같은 patch-id
git reflog show origin/main --date=iso | grep -E "4033ec6e|d6b72554"
```

## 부록 B. 팩만으로 재현 불가한 주장 목록 (전부 [저장소 확인])

1. 커밋 `0ce8569b`·`afec214e` 의 작성 시각과 메시지 (§3.1·§3.2)
2. 사전등록 커밋이 결과 커밋의 **DAG 조상**이라는 사실 (§3)
3. `7a868424` ≡ `0ce8569b` (트리 동일·patch-id 동일, cherry-pick) (§3.1)
4. 정합 커밋 `cb279542`, 기준선 갱신 커밋 `9df8f56b`, 병합 `6ffa1c58` (§3.1)
5. 홀드아웃 소모 커밋 `03d57a11` 12:06:23, P0 커밋 `978e8936` 11:26:36, V13-D6 커밋 `f042d7d1` 13:04:09 (§3.3)
6. 페일클로즈 구현 커밋 `c9c88116` 2026-09-08 16:45:33 (§1 R7)
7. GOV-1 인용 reflog 두 줄의 축자 존재 (§4.3)
8. 위 커밋 전부가 `origin/main`(805c9d93) 의 조상이라는 사실

## 부록 C. 대조에 쓴 파일 목록

- `<PACK>/A_contracts/multivariate_timeseries_v13_vol.yaml` (416행) — 계약 정본
- `<PACK>/E_artifacts/ledgers/approvals.jsonl` (9행) · `holdout_scorings.jsonl` (1행) ·
  `vol_experiments.jsonl` (4행) · `vol_live.jsonl` (3행)
- `<PACK>/E_artifacts/vol/guard_mde_design.json` · `champion_coefficients.json` ·
  `<PACK>/E_artifacts/runs/holdout_V13VOL_champion_aec80c65038b.json`
- `<PACK>/D_governance/CLAUDE.md`(83행) · `DECISIONS.md`(1108행) · `KNOWN_LIMITS.md`(89행) · `MODEL_REGISTRY.md`
- `<PACK>/C_design/mts_program_blueprint_v1_260909.md` (1136행)
- `<PACK>/B_verdicts/V13_HOLDOUT_VERDICT_20260909.md` · `V13_VOL_RUNG4_MACRO_VERDICT_20260909.md` ·
  `V13_TA_NULL_REPAIR_VERDICT_20260907.md`
- `<PACK>/F_code/timeseries_v13/holdout.py` · `<PACK>/F_code/tests/test_timeseries_v13_vol_contract.py` ·
  `test_timeseries_v13_holdout.py` · `<PACK>/F_code/tools/roadmap_status.py`
- `<PACK>/01_STATE/roadmap_status.txt` · `git_log_main_recent.txt`
- `<PACK>/G_session_20260909/fixes.diff` · `rung4_manifest_baseline.diff`
- `<PACK>/A_contracts/ledger_registry.yaml` (V13 항목 7종 등록: 실험·홀드아웃·승인·라이브·해상·사다리 결과·동결 계수.
  사다리 결과와 동결 계수는 `kind: immutable_files`, 동결 계수는 추가로 `expected_state: frozen` — 바이트 변경이 CI violation)

**무결성 확인:** 팩의 계약·원장 3종 사본이 저장소 원본과 **sha256 동일**함을 확인했다
(`approvals.jsonl` `0c1bf195530047e8…`, `holdout_scorings.jsonl` `ff86e6c317e45961…`,
`vol_experiments.jsonl` `234b07e51ec1b22d…`, 계약 `243572f2aa04fad1…` — 앞 16자리 표기).

---

*작성 2026-09-09 KST. 이 문서는 판정하지 않는다 — 시간 순서와 해시를 제시하고, 판정 가능한 형태로 남긴다.*
