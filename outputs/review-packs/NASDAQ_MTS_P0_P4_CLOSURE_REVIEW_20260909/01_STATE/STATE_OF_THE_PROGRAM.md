# 현 위치 실측 — NASDAQ 다변량 시계열(MTS) 프로그램 / V13-VOL 트랙

**작성 2026-09-09 (KST) · 검토관용 · 이 문서는 팩 안의 파일만으로 재검증 가능하게 썼다.**

---

## 0. 이 문서를 읽는 법

### 0.1 경로 표기 규약

이 팩은 저장소 `C:/workspace/ai-investing` 의 부분 사본이다. 아래에서 경로는 두 가지로 적는다.

| 표기 | 뜻 |
|---|---|
| `팩:A_contracts/…` | 이 검토팩 루트(`outputs/review-packs/NASDAQ_MTS_P0_P4_CLOSURE_REVIEW_20260909/`) 기준 상대경로. **검토관이 직접 열 수 있다.** |
| `저장소:data/…` | 원본 저장소 경로. 팩 안 파일의 출처이며, 계약·원장·코드가 서로를 이 경로로 참조한다. |

**팩 사본이 원본과 동일함을 확인했다** (sha256 앞 16자리 대조, 2026-09-09):

| 파일 | 저장소 | 팩 | 일치 |
|---|---|---|---|
| V13 계약 | `data/contracts/multivariate_timeseries_v13_vol.yaml` | `A_contracts/multivariate_timeseries_v13_vol.yaml` | `243572f2aa04fad1` = `243572f2aa04fad1` ✔ |
| 라이브 포인터 | `data/timeseries_v13/vol/vol_latest.json` | `E_artifacts/vol/vol_latest.json` | `edf7904d5aa86ba1` ✔ |
| 홀드아웃 원장 | `data/timeseries_v13/ledgers/holdout_scorings.jsonl` | `E_artifacts/ledgers/holdout_scorings.jsonl` | `ff86e6c317e45961` ✔ |
| 라이브 원장 | `data/timeseries_v13/ledgers/vol_live.jsonl` | `E_artifacts/ledgers/vol_live.jsonl` | `fb7d5ee0c48fa235` ✔ |

### 0.2 30초 요약

- V13-VOL 은 **9셀 변동성 사건 확률** 트랙이다: P(VIX 종가 ≥ K 를 h영업일 내 터치), K∈{25,30}; P(RV21_ann > 0.1694 를 h영업일 내 초과), h∈{5,21,63} (`팩:A_contracts/multivariate_timeseries_v13_vol.yaml` L19-28).
- **champion 은 전 9셀 `persistence_pb`** — 당일 수준 단독 로짓. EWMA·HAR·매크로 3종 확장이 모두 이것을 못 이겼다 (계약 L200-217, 원장 4행).
- **홀드아웃(2015-2018) 1슬롯을 2026-09-09 에 소모했고 결과는 partial — 9셀 중 3셀 통과** (`팩:E_artifacts/ledgers/holdout_scorings.jsonl` 1행 `status: "partial"`, `pass_cells: ["rv_h21","rv_h5","vix25_h21"]`).
- **P4(무료 매크로 피처블록) 는 27검정 채택 0** — 적재 없이 시험 가능한 정보집합이 소진됐다 (`팩:E_artifacts/vol/ladder_rung4_macro.json` `k_obs_adopted: 0`, `tests_run: 27`).
- **현 단계 P5(외부 유료 정보집합)이고 차단 요인은 CBOE 라이선스 회신**이다. 그 편지는 아직 발송 전이다 (`팩:01_STATE/roadmap_status.txt` L18, `팩:D_governance/CBOE_DATASHOP_QQQ_SEND_20260909.md` L3-5).
- **P3(배선)은 실패가 아니라 사용자 보류**다 — 홀드아웃 통과 셀과 등록 질문이 겹치지 않았다 (영수증 `v13-approval:V13-D6-defer:2026-09-09:r1`).

---

## 1. 단계표 P0~P7 — 상태·종료 근거·차단 요인

설계도(`팩:C_design/mts_program_blueprint_v1_260909.md`) §3 이 단계를 정의하고, §9.3 이 **각 단계의 기계 판독 종료조건**을 정의한다.
`팩:F_code/tools/roadmap_status.py` 가 그 조건을 실제로 검사하며, `팩:01_STATE/roadmap_status.txt` 는 그 출력이다.
아래 표는 roadmap_status.txt 를 베낀 것이 아니라 **각 판정의 입력 파일·필드·수치를 직접 열어 확인한 것**이다.

| 단계 | 이름 | 상태 | 종료 조건 (설계도 §9.3) | 실측 근거 — 파일과 값 |
|---|---|---|---|---|
| **P0** | 판정 기계 건전성·에피소드 가드 | **완료** | guard 산출물 존재 ∧ 계약 `degeneracy_guard.rules.min_episodes_per_half_per_class` 존재 ∧ `design_window_result` 존재 ∧ 계약 선언 `episode_failures` == 실측 `summary.episode_guard_failures` | `팩:E_artifacts/vol/guard_mde_design.json` 존재(content_hash `e8cf914b4ea11cfa…`, generated_at `2026-09-09T02:06:01+00:00`, window `[2007-01-01, 2014-12-31]`, n_panel 2014, thresholds `{min_episodes_per_half_per_class: 5, min_events_per_half_per_class: 20}`). `summary.episode_guard_failures` = `[vix25_h21, vix25_h63, vix30_h5, vix30_h21, vix30_h63, rv_h63]` (6셀) — 계약 L245 `episode_failures` 와 **문자열 단위로 동일**. `counts_guard_failures` = `[]` (사건 수 가드는 9/9 통과) |
| **P1** | 라이브 전진 채점 | **완료(배선만)** | 계약 `live_forward_gate.execution_path ≠ absent_by_construction` ∧ `verb` 기재 ∧ CLI 에 `timeseries-v13-vol-resolve` 존재 | 계약 L347-348: `execution_path: named_verb_guarded`, `verb: timeseries-v13-vol-resolve`. 저장소 `src/ai_fc/cli.py:493` 에 `@app.command("timeseries-v13-vol-resolve")` 존재. **주의: "완료"는 채점 경로가 열렸다는 뜻이지 표본이 쌓였다는 뜻이 아니다** — 결과 원장 `data/timeseries_v13/ledgers/vol_live_resolutions.jsonl` 은 **파일 자체가 없다(0행)** |
| **P1b** | V8 섀도 정지 진단 | **완료** | `docs/KNOWN_LIMITS.md` 에 DTWEXBGS 항목 ∧ `docs/review/V8_SHADOW_ORIGIN_STALL_20260909.md` 존재 | `팩:D_governance/KNOWN_LIMITS.md` 36번 항목이 "V8 섀도 원점은 필수 계열의 공통 마지막 날짜인데 DTWEXBGS가…"로 등재. 진단서 `팩:B_verdicts/V8_SHADOW_ORIGIN_STALL_20260909.md` 존재 — 원인은 케이던스가 아니라 **DTWEXBGS 2026-08-28 정지(12일째)**, 유입 실측 `2026-08-20T09:07:48` 5,169행 → `2026-09-01T03:07:06` 10행, 이후 2회 수집은 신규 0행 |
| **P2** | 홀드아웃 1회 소모 | **완료(비가역 소모)** | `holdout_scorings.jsonl` 행 ≥ 1 ∧ 계약 `publication.holdout_status ∈ {pass,partial,fail}` ∧ approvals 에 `V13-D3` 행 | 원장 **1행**(`팩:E_artifacts/ledgers/holdout_scorings.jsonl`): `window ["2015-01-01","2018-12-31"]`, `status "partial"`, `finalist_id V13VOL_champion_aec80c65038b`, `coefficients_sha256 1a857850…`, `panel_truncated_at "2018-12-31"`, `sealed_bytes_read false`, `git_head 978e8936`. 계약 L331 `holdout_status: partial`. 승인 영수증 `팩:E_artifacts/ledgers/approvals.jsonl` 8행 `v13-approval:V13-D3:2026-09-09:r1`, `approved_at 2026-09-09T11:35:57+09:00`, 원문 = `V13-D3 홀드아웃 1회 소모 승인 finalist=V13VOL_champion_aec80c65038b` |
| **P3** | EXIT base rate 배선 | **보류(DEFERRED — 사용자 결정)** | approvals 에 `V13-D6` 행 ∧ `data/base_rates/volatility_v13_auto.md` 존재 ∧ `holdout_status ∈ {pass,partial}` | 세 조건 중 마지막만 충족. approvals 9행은 `V13-D6` 가 아니라 **`V13-D6-defer`**(`approved_at 2026-09-09T13:03:32+09:00`, 원문 "보류 — 전진 표본 쌓고 재판단", `approval_scope.wiring: false`, `conditions.reopen_when_matured_origins_per_cell: 60`). `data/base_rates/` 에 `volatility_v13_auto.md` 없음(`volatility.md` 만 존재). 차단 사유는 실패가 아니라 **구조적 불일치**: 등록 질문 `vix-25-90d` 의 대응 셀 `vix25_h63` 이 홀드아웃 실패, 배선 자격 셀 `rv_h5·rv_h21` 에는 대응 질문이 없다 (계약 L411-415, `팩:B_verdicts/V13_HOLDOUT_VERDICT_20260909.md` §4) |
| **P4** | 봉인 아카이브 내 신규 피처블록 | **완료(부정 종료)** | `vol_experiments.jsonl` 행 ≥ 4 ∧ 계약 `evaluations_spent ≥ 4` | 원장 **4행**(`팩:E_artifacts/ledgers/vol_experiments.jsonl`: `V13VOL_ewma_logit` / `V13VOL_har_logit` / `V13VOL_pb_baseline` / `V13VOL_rung4_macro`). 계약 L78 `evaluations_spent: 4`. 4행 값: `tests_run 27`, `k_obs_adopted 0`, `adopted []`, `family_p_binomial 0.9999999999999989`, `backtest_windows_opened 0`, `prereg_commit 0ce8569b` |
| **P5** | 외부 정보집합(옵션·일중) | **미종료 — 현 단계** | `docs/generated/licenses.generated.md` 의 **확정 표**(“Pending manual reviews” 절 **앞**)에 CBOE 행 존재 | 저장소 `docs/generated/licenses.generated.md` 에서 CBOE 는 **25행 "## Pending manual reviews" 뒤 27행**에만 등장("CBOE, Nasdaq Data Link, Google News RSS는 registry 편입 전 재배포 약관을 별도로 확인한다"). 즉 확정 표에 행이 없다 → 미종료. 발송본은 준비돼 있으나 **미발송**: `팩:D_governance/CBOE_DATASHOP_QQQ_SEND_20260909.md` L3 "이 문서는 사용자가 직접 보내는 것이다. 나는 발송하지 않았고 보낼 수도 없다" |
| **P6** | 라이브 전진 축적 | **미종료** | `vol_live_resolutions.jsonl` 의 champion 셀별 성숙 원점 **min ≥ 60** | 결과 원장 **파일 없음(0행)** → min = **0/60**. 원본 원장 `팩:E_artifacts/ledgers/vol_live.jsonl` 은 3행이나 **고유 원점(as_of)은 2개**(`2026-09-04` ×2, `2026-09-08` ×1). 임계는 계약 L343 `minimum_matured_origins_per_cell: 60` |
| **P7** | 신규 버전 봉인 + P3 게이트 | **미종료(구조적)** | 신규 버전 계약 ∧ 봉인 원장 ≥1 ∧ approvals 에 `SEAL-1` | `팩:F_code/tools/roadmap_status.py` 의 `_sealed_ok()` 는 **무조건 `False, ["신규 버전 봉인 미착수 (C5 종속)"]`** 를 돌려준다(구현 자체가 페일클로즈). 설계도 §3 P7 진입 게이트가 **C5(LLM 원장 50문항+·Brier<0.18)** 이고 C5 는 프로그램 외부(설계도 §1.3) |

### 1.1 현 단계·다음 행동 (도구 출력과 대조)

`팩:01_STATE/roadmap_status.txt` L15-22:

- 현 단계 **P5** — P0·P1·P1b·P2·P4 완료, P3 는 `DEFERRED` 라 "현 단계" 후보에서 제외되는 것이 도구의 규칙이다 (`roadmap_status.py` `main()`: `if not ok and not _deferred(missing) and current is None`).
- 다음 승인: **구매·발송(사용자)** / 다음 명령: **CBOE 회신 기록 → 적재 계약 신설**.
- 이 출력이 읽은 체크아웃: `C:\workspace\ai-investing [claude/c5-sharpness-strategy @ 805c9d93]` (L2). `팩:01_STATE/git_log_main_recent.txt` L1 도 `805c9d93 data: publish V13-VOL volatility base-rate pointer` — **같은 커밋**이다.

### 1.2 단계 순서에 대한 검토관 주의 — 설계도 §2 는 이미 낡았다

설계도 `팩:C_design/mts_program_blueprint_v1_260909.md` §2.1 은 V13 을 "홀드아웃 **미소모**, 개발 평가 **3/8**", §2.3 은 "홀드아웃 잔여 **3**" 으로 적고 있다. **이 값들은 같은 날(2026-09-09) 오전 스냅샷이며 현재는 틀렸다.** 설계도 자신이 §0 에서 이를 경고한다: *"이 문서의 '현 위치'(§2)를 최신이라고 가정하기 — §2는 2026-09-09 스냅샷이다. 진실은 §9.3의 파일·필드다."* 같은 이유로 §9.2 에 실린 예시 출력(`현 단계 : P2`, `홀드아웃 슬롯 0/3`)도 P2 실행 **전**의 것이다. 진실은 원장이다.

---

## 2. 완성 정의 C0~C4 — 충족 판정

정의 출처는 설계도 §1.2 (`팩:C_design/mts_program_blueprint_v1_260909.md` L50-58). **프로그램 완성 = C0 ∧ C1 ∧ C2 ∧ C3 ∧ C4, 표시 상한 T3.**
설계도 §9.3 의 기계 판독 표에는 **C1·C2·C4 만 있고 C0·C3 의 기계 조건은 없다** — 이 둘은 아래에서 정의 원문을 직접 대조한다.

| 조건 | 정의 요지 | 판정 | 근거 |
|---|---|---|---|
| **C0** 판정 기계 건전성 | ① 건전 y-block(ℓ=13) 귀무 통과율 ≤ 0.10 **전 셀** ② 에피소드 가드 통과 ③ 결과 전 MDE 공표. **상시** 조건 — 깨지면 그 셀의 모든 판정 무효 | **부분** | **③ 충족**: `팩:E_artifacts/vol/guard_mde_design.json` 이 `2026-09-09T02:06:01Z` 에 셀·반창별 MDE 를 인쇄했고, 홀드아웃 채점은 `knowledge_cutoff 2026-09-09T02:37:57Z` — **31분 뒤**다. 홀드아웃 원장도 셀마다 `mde` 를 실었다. <br> **① 창에 따라 다름**: 설계창에서는 PB 귀무 통과율 0.000~0.033 으로 9/9 통과(`champion_coefficients.json` `gate_evidence.neg_control_pb_pass_rate`). **홀드아웃 창에서는 5셀이 0.10 초과** — vix30_h5 1.000 · vix30_h21 0.965 · rv_h63 0.805 · vix30_h63 0.485 · vix25_h5 0.125. <br> **② 창에 따라 다름**: 설계창 6/9 실패, 홀드아웃 창 4셀 `episode_thin`(vix30 3종·rv_h63). <br> **해석**: C0 는 *셀 단위 상시 조건*이고, 실패 셀은 실제로 판정에서 배제됐다(그 5셀은 전부 홀드아웃 FAIL 로 기록되고 화면에서 숫자가 내려갔다). 즉 **기계는 설계대로 작동했으나, "전 셀"이라는 문언 그대로는 충족되지 않는다.** 살아남은 3셀 기준으로는 충족 |
| **C1** 라이브 전진 표본 | V13 셀당 성숙 원점 ≥ 60 ∧ V8 섀도 세션 ≥ 126 | **미충족 (0/60, 2/126)** | V13: `vol_live_resolutions.jsonl` 부재 → 성숙 원점 **0**. 임계 60 은 계약 L343. <br> V8: `팩:B_verdicts/V8_SHADOW_ORIGIN_STALL_20260909.md` §0 — 섀도 예측 원장 2행(원점 2026-08-14·2026-08-28, W34 결번), 해소 원장 2행(h1·h5만 성숙), 승격 요건 `minimum_shadow_sessions: 126`. 병목은 DTWEXBGS 발행 속도이며 **우리 손에 없다**(같은 문서 §3) |
| **C2** 홀드아웃 소모·판정 | 1슬롯 소모 후 `holdout_status ∈ {pass, partial, fail}`. **결과 무관 완결 — FAIL 도 충족** | **충족** | 계약 L331 `holdout_status: partial`. 원장 1행이 PASS/FAIL 무관 append 됐고 `sealed_bytes_read: false`·`panel_truncated_at: 2018-12-31` 로 봉인창 미열람을 자기기록. C2 는 결과의 성패를 묻지 않으므로 **partial 로 완결** |
| **C3** 배선 | 홀드아웃 PASS 셀 확률을 EXIT 트리거 질문 base rate 공간에 **표시만** 연결(V13-D6). 산술 결합 0 | **미충족 — 사용자 보류로 미개시** | `V13-D6` 승인 영수증 없음. 대신 `V13-D6-defer` 영수증(approvals 9행). 구조적 이유: 계약 L335 `wiring_eligible_cells: [rv_h5, rv_h21]` 이고 계약 L314 `reference_question.cell: vix25_h63` 은 홀드아웃 실패 셀이다. 즉 **자격 있는 셀과 쓸 수 있는 질문이 서로소**다. 설계도 §3 P3 는 애초에 배선 가능 질문이 43문항 중 `vix-25-90d` 하나뿐임을 실측해 뒀다 |
| **C4** 표시 정직성 | 표시 사다리 페일클로즈 가드 전부 통과 + 한계 공시(band80 의미·홀드아웃 상태·국면 표본 두께) | **부분 (코드상 충족, 실행 검증은 팩 밖)** | **한계 공시는 실측 확인됨**: 포인터 각주(`vol_latest.json` `footnote`)가 "설계창(2007-2014) 스킬 · 홀드아웃 미검증 · 참고 의견 — 매매 신호 아님. 80% 대역은 계수 불확실성(델타법)이며 보정 대역이 아니다"; 카드 caveat 는 partial 일 때 **"<b>홀드아웃 부분 통과</b>(9셀 중 3셀만 통과 — 나머지는 표시하지 않습니다)"**(저장소 `src/ai_fc/dashboard_parts/dashboard.js:1683`); `▲ 보정 약함`·`▲ 국면 표본 얇음` 마커는 `dashboard.js:1706` 이 `reliability==='weak'`·`episode_sample==='thin'` 에서 렌더. <br> **페일클로즈 가드**: `팩:F_code/timeseries_v13_vol_display.py` 가 tier·armed·holdout_status=fail·핀 3자 일치·신선도를 각각 hold 로 떨어뜨린다(L138-153). <br> **미충족 위험 1건**: 설계도 §9.3 C4 는 "`episode_thin` 셀에 마커 부착"을 요구하는데, 검증기 `validate_latest` 는 `episode_sample` 이 **`None` 이어도 통과**시킨다(`timeseries_v13_vol_display.py:89-90`). 즉 마커 누락은 **기계로 막히지 않는다** — 현재 포인터에는 값이 들어 있으나 구조적 보증은 아니다. <br> `read_model_contract.validate` 실행 결과는 이 팩에 없다 → **[미확인]** |

**종합**: C2 만 완전 충족. C0·C4 는 부분, C1·C3 는 미충족. 설계도 §1.3 이 못 박은 대로 **C5(LLM 원장 50문항+·Brier<0.18)와 T4 는 이 프로그램의 종료 조건이 아니다** — V13 계약 L330 `display_tiers_allowed: [t0_internal, t2_hidden_panel, t3_live_card]` 에 t4 값 자체가 없다(구조 차단).

---

## 3. 자원 잔량 — 어느 원장 몇 행에서 나왔는가

`roadmap_status.py` 의 자원 줄은 다음 식으로 계산된다(도구 L256-258). 아래는 그 입력을 직접 센 것이다.

| 자원 | 값 | 계산식 (도구) | 원장·행 실측 |
|---|---|---|---|
| **개발 평가 예산** | **4 / 8** (잔여 4) | `development_protocol.evaluations_spent` / `maximum_development_evaluations` | 계약 L77-78. 원장 대사: `팩:E_artifacts/ledgers/vol_experiments.jsonl` **4행** — 1행 `V13VOL_ewma_logit`(rung ewma_logit) · 2행 `V13VOL_har_logit`(har_logistic) · 3행 `V13VOL_pb_baseline`(persistence_pb_g2, `evaluation_index 3`) · 4행 `V13VOL_rung4_macro`(macro_blocks_vs_pb, `evaluation_index 4`). 도구는 원장 행수 ≥ 4 **와** 계약 필드 ≥ 4 를 **둘 다** 요구한다(`_new_block_ok`) |
| **홀드아웃 슬롯** | **1 소모 / 3** (잔여 2) | `len({행의 finalist_id})` / `holdout_maximum_finalists` | `팩:E_artifacts/ledgers/holdout_scorings.jsonl` **1행**, `finalist_id = V13VOL_champion_aec80c65038b` → 고유 finalist 1. 상한은 계약 L85 `holdout_maximum_finalists: 3`. 계약 L402 "슬롯 1/3 소모 예정 — 남은 2는 이후 신규 정보집합 finalist 용" |
| **라이브 전진 원점** | **2** | `len({행의 as_of})` | `팩:E_artifacts/ledgers/vol_live.jsonl` **3행**이나 as_of 는 `2026-09-04`(1·2행) · `2026-09-08`(3행) → **고유 2**. 1행과 2·3행은 `coefficients_sha256` 이 다르다(`51815bde…` → `1a857850…`) — 계수 재동결 전후 |
| **성숙 채점 수** | **0행 → 셀별 최소 0 / 60** | `len(_rows(RESOLUTIONS))`, 셀별 count 의 min | `data/timeseries_v13/ledgers/vol_live_resolutions.jsonl` **파일 없음**. 이 팩에도 없다. 임계 60 은 계약 L343 |
| **봉인창 공개** | **모델 버전당 1, V8 에서 1 소모** | (도구 미계산) | 설계도 §2.3 — V8 계약 `maximum_disclosures_per_model_version: 1` 소진, 신규 버전에서만 재개 가능 |
| **표시 tier / 홀드아웃 상태** | `t3_live_card` / `partial` | 계약 `publication` | 계약 L328·L331 |

> **주의(도구의 자백)**: `roadmap_status.py` 는 자신이 읽은 체크아웃을 인쇄한다. 도구 주석 L197-200 은 *"워크트리가 여럿이면… 그 체크아웃이 옛 브랜치에 머물러 있으면 원장이 뒤처진 채로 '라이브 원점 1' 같은 숫자가 나온다(2026-09-09 실측: 실제 2, 보고 1)"* 라고 적고 있다. **파생 상태 도구를 믿으려면 출처 줄을 함께 봐야 한다.**

---

## 4. 9셀 현황표

### 4.1 라이브 확률·대역·기후 (포인터 `팩:E_artifacts/vol/vol_latest.json`, as_of **2026-09-08**)

입력(같은 파일 `inputs`): VIX 종가 **15.72**, VIX EWMA21 15.36, RV21_ann **0.1214**, RV21 EWMA21 0.1713.
`freshness`: `nyse_trading_calendar`, `missing_sessions 0 / max 1`, `status fresh`, 평가시각 `2026-09-09T10:27:59Z`.

| 셀 | 표적 | h(영업일) | champion p | 80% 대역 | se(raw) | 기후 기저율 | 파생층 | 신뢰도 마커 | 국면 표본 | 홀드아웃 | **화면 표시** |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `vix25_h5` | VIX≥25 터치 | 5 | **0.9%** | 0.6%–1.3% | 0.0024 | 0.3076 | raw | good | ok | **FAIL (G4 0.125)** | ✘ 숨김 |
| `vix25_h21` | VIX≥25 터치 | 21 | **9.5%** | 6.1%–12.9% | 0.0264 | 0.4195 | raw | good | **thin** | **PASS** | **✔ 표시 + ▲ 국면 표본 얇음** |
| `vix25_h63` | VIX≥25 터치 | 63 | **36.3%** | 28.2%–44.4% | 0.0631 | 0.6079 | raw | **weak** | **thin** | **FAIL (G1)** | ✘ 숨김 |
| `vix30_h5` | VIX≥30 터치 | 5 | **0.3%** | 0.2%–0.4% | 0.0009 | 0.1782 | raw | good | **thin** | **FAIL (G4 1.000)** | ✘ 숨김 |
| `vix30_h21` | VIX≥30 터치 | 21 | **3.6%** | 1.8%–5.4% | 0.0140 | 0.2519 | raw | good | **thin** | **FAIL (G4 0.965)** | ✘ 숨김 |
| `vix30_h63` | VIX≥30 터치 | 63 | **14.7%** | 9.1%–20.3% | 0.0437 | 0.4070 | raw | **weak** | **thin** | **FAIL (G1·G4 0.485)** | ✘ 숨김 |
| `rv_h5` | RV21>0.1694 | 5 | **6.8%** | 5.3%–8.3% | 0.0117 | 0.5524 | raw | good | ok | **PASS** | **✔ 표시** |
| `rv_h21` | RV21>0.1694 | 21 | **35.4%** | 28.0%–42.7% | 0.0572 | 0.6708 | raw | good | ok | **PASS** | **✔ 표시** |
| `rv_h63` | RV21>0.1694 | 63 | **78.3%** | 71.2%–85.4% | 0.0551 | 0.8765 | raw | **weak** | **thin** | **FAIL (G4 0.805)** | ✘ 숨김 |

- 전 9셀 `model: persistence_pb` (계약 L204-213 `gates.champion.cells`, 포인터 각 셀 `model` 필드).
- `derived_layer` 가 9셀 모두 `raw` 인 이유: h63 세 셀의 isotonic 은 **사전등록된 fallback 이 발동**해 raw 로 되돌아갔다 (계약 L217 `h63_derived_layer: {vix25_h63: raw, vix30_h63: raw, rv_h63: raw}`, L296 `fallback_rule_preregistered`).
- **80% 대역의 의미**: 계약 L308-311 — `delta_method_block_bootstrap_cov`, z=1.2816, `meaning: coefficient_uncertainty_not_calibration`. **보정 대역이 아니다.**
- `episode_sample`(thin 6셀)은 **설계창** 실측이다 — 계약 L313 `live_display.episode_thin_cells` = `[vix25_h21, vix25_h63, vix30_h5, vix30_h21, vix30_h63, rv_h63]`, 원천은 `guard_mde_design.json` `summary.episode_guard_failures`.

### 4.2 설계창 증거 (2007-2014, n=2014, split 2011-01-01)

`팩:E_artifacts/vol/champion_coefficients.json` — `fit_window ['2007-01-03','2014-12-31']`, `finalist_id V13VOL_champion_aec80c65038b`, sha256 `1a857850…`, content_hash `1fdeb136…`, 반창 재적합 대사 `reconciliation.abs_diff` 최대 **~5.6e-16**.

| 셀 | 피처 | β(절편, 기울기) | BSS vs 기후 early→late | late→early | PB y-block 귀무 | 반창 최소 국면 (early/late) | MDE(PB) early/late |
|---|---|---|---|---|---|---|---|
| `vix25_h5` | vix_close | −1.079, 6.028 | +0.900 | +0.794 | 0.017 | 14 / 5 | 0.0129 / 0.0757 |
| `vix25_h21` | vix_close | +0.200, 4.128 | +0.752 | +0.687 | 0.008 | 7 / **4** | 0.0450 / 0.0677 |
| `vix25_h63` | vix_close | +1.364, 3.189 | +0.456 | +0.601 | 0.017 | **3** / **3** | 0.0644 / 0.0464 |
| `vix30_h5` | vix_close | −3.110, 4.649 | +0.880 | +0.721 | 0.017 | 10 / **2** | 0.0257 / 0.0827 |
| `vix30_h21` | vix_close | −1.468, 3.053 | +0.813 | +0.530 | 0.000 | 7 / **1** | 0.0156 / 0.0836 |
| `vix30_h63` | vix_close | −0.126, 2.703 | +0.612 | +0.493 | 0.017 | **4** / **1** | 0.0345 / 0.0763 |
| `rv_h5` | rv21_ann | +2.678, 8.148 | +0.825 | +0.879 | 0.000 | 7 / 12 | 0.0509 / 0.0334 |
| `rv_h21` | rv21_ann | +2.287, 4.417 | +0.518 | +0.592 | 0.017 | 5 / 8 | 0.0550 / 0.0358 |
| `rv_h63` | rv21_ann | +2.888, 2.446 | +0.095 | +0.437 | 0.033 | **1** / 5 | 0.0120 / 0.0076 |

굵은 값 = 국면 가드 임계 5 미달. 최악 사례(계약 L247-249, `팩:B_verdicts/V13_GUARD_MDE_20260909.md` §2): `vix30_h21` 후반창 사건 109일 = **연속 구간 1개**(2011-07-06~2011-12-07), `vix30_h63` 후반창 151일 = **1개**(2011-05-05~2011-12-07), `rv_h63` 전반창 비사건 27일 = **1구간**.

### 4.3 홀드아웃 창 실측 (2015-01-01~2018-12-31, 1회 소모)

원장: `팩:E_artifacts/ledgers/holdout_scorings.jsonl` 1행. 창 내 가드는 **verb 실행 시점에** 계산됐다(계약 L234-239 — 사전 점검은 미열람 위반).

| 셀 | 원점 수 | 사건/비사건 | 사건 run / 비사건 run | 창 가드 | BSS vs 기후 | G1 CI90 | G1 MDE | G4 귀무 | 판정 |
|---|---:|---|---|---|---|---|---|---|---|
| `rv_h5` | 1001 | 285 / 716 | 8 / 7 | ok | **+0.828** | [+0.2051, +0.2495] | 0.0221 | **0.000** | **PASS** |
| `rv_h21` | 985 | 354 / 631 | 6 / 5 | ok | **+0.600** | [+0.1490, +0.2422] | 0.0468 | **0.015** | **PASS** |
| `vix25_h21` | 985 | 169 / 816 | 6 / 6 | ok | **+0.446** | [+0.0551, +0.1237] | 0.0346 | **0.080** | **PASS** |
| `vix25_h5` | 1001 | 74 / 927 | 8 / 8 | ok | +0.640 | [+0.0683, +0.0880] | 0.0100 | 0.125 | FAIL (G4) |
| `rv_h63` | 943 | 492 / 451 | 5 / 4 | **episode_thin** | +0.275 | [+0.0651, +0.1419] | 0.0383 | 0.805 | FAIL (G4) |
| `vix30_h21` | 985 | 57 / 928 | 3 / 3 | **episode_thin** | +0.373 | [+0.0164, +0.0499] | 0.0168 | 0.965 | FAIL (G4) |
| `vix30_h5` | 1001 | 25 / 976 | 3 / 3 | **episode_thin** | +0.615 | [+0.0259, +0.0326] | 0.0033 | 1.000 | FAIL (G4) |
| `vix25_h63` | 943 | 353 / 590 | 5 / 5 | ok | +0.145 | [**−0.0390**, +0.1182] | 0.0782 | 0.000 | FAIL (G1) |
| `vix30_h63` | 943 | 141 / 802 | 3 / 3 | **episode_thin** | +0.162 | [**−0.0239**, +0.0813] | 0.0525 | 0.485 | FAIL (G1·G4) |

- 원점 구간: 전 셀 첫 원점 `2015-01-02`, 마지막 원점 h 에 따라 `2018-12-21`(h5) / `2018-11-28`(h21) / `2018-09-28`(h63) — 계약 L103 label-complete 요건대로 절단됐다.
- **G2 는 9셀 전부 `identity: true`** — champion 이 PB 자신이라 항등 통과(계약 L108). 따라서 이번 홀드아웃에서 실질 판정 다리는 **G1 과 G4 둘뿐**이다.
- **family**: `family_p_binomial = 0.008361` = P(k≥3 | n=9, p=0.05). 계약 L334 에도 같은 값이 기입돼 있다.
- **G3(신뢰도)는 보고 의무**: 통과 셀 rel = `vix25_h21` 0.0040 · `rv_h5` 0.0099 · `rv_h21` 0.0325; 최악은 `rv_h63` 0.0986 · `vix30_h63` 0.0418.
- `untestable_cells: []`, `episode_thin_pass_cells: []` — 즉 **사건 수 미달로 채점 제외된 셀은 없고, episode_thin 이면서 PASS 한 셀도 없다.**

### 4.4 검토관이 특히 볼 곳 — 홀드아웃 원장과 계약이 한 줄 다르다

| 항목 | 원장(`holdout_scorings.jsonl`) | 계약(`…v13_vol.yaml` L335) | 정본 |
|---|---|---|---|
| `wiring_eligible_cells` | `[rv_h21, rv_h5, vix25_h21]` — **3셀** | `[rv_h5, rv_h21]` — **2셀** | **계약(2셀)** |

이유는 판정서가 명시한다(`팩:B_verdicts/V13_HOLDOUT_VERDICT_20260909.md` L63-64): 원장은 **홀드아웃 창** 가드만 보고 3셀을 적었으나(그 창에서 `vix25_h21` 은 국면 6), 계약은 **설계창과 홀드아웃 창 둘 다** 통과를 요구한다. `vix25_h21` 은 설계창 후반 국면이 4개라 `degeneracy_guard.consequences.wiring`(계약 L242)에 걸린다. **원장은 append-only 라 고치지 않고 계약과 판정서가 정본**이라는 것이 저장소의 처리다.

### 4.5 두 번째 불일치 — 기후 상수 (검토관 판단 요망)

계약 L41-42 는 기후 기저율을 **사전등록 고정값**으로 못 박는다(`rv h21: 0.6760`, `rv h63: 0.8751`). 그런데 실제 채점은 산출물의 전정밀 값(`rv_h21 0.670848`, `rv_h63 0.876474`)을 썼다. 홀드아웃 `bs_baseline` 을 두 값으로 각각 재계산해 대조한 결과:

| 셀 | 계약값 | 사용된 값 | 원장 `bs_baseline` | 계약값으로 계산 시 | 사용값으로 계산 시 |
|---|---|---|---|---|---|
| `rv_h21` | 0.6760 | 0.670848 | 0.327235 | 0.330470 | **0.327235** ✔ |
| `rv_h63` | 0.8751 | 0.876474 | 0.375364 | 0.374391 | **0.375364** ✔ |
| 나머지 7셀 | — | — | — | 소수 넷째 자리까지 일치(반올림 차) | ✔ |

즉 **rv 두 셀에서 계약의 사전등록 상수와 실제 사용 상수가 다르다**(rv_h21 은 0.52%p 차). 방향은 champion 에게 **불리한 쪽**이다 — 계약값을 썼다면 G1 손실차가 rv_h21 에서 +0.0032 더 커져 통과가 더 쉬웠다. 판정을 뒤집지는 않지만(rv_h21 은 어느 쪽이든 PASS, rv_h63 은 G4 로 실패), **사전등록 고정값이 실행 경로에서 강제되지 않는다**는 사실 자체가 검토 대상이다. 이 팩에는 이 불일치를 다룬 문서가 없다 — **[미확인: 의도된 것인지 여부]**.

---

## 5. 지금 라이브 사이트에 무엇이 보이는가

계약 L327-336 의 `publication` 블록과 표시 코드(`팩:F_code/timeseries_v13_vol_display.py`, 저장소 `src/ai_fc/dashboard_parts/dashboard.js:1665-1734`)에서 유도하면 다음과 같다.
시계열 화면의 다섯 번째 탭 **"변동성 기준율"** 이 열려 있다 — `display_tier` 가 `t3_live_card` 이므로 `?review=` 파라미터 없이 **누구에게나 활성**이다(`dashboard.js:1666-1669`). 카드 머리에는 `수치모델 · 당일 수준 지속(PB)` 배지가 붙고, 첫 문장(caveat lead)은 굵은 글씨로 **"설계창(2007~2014) 스킬 · <b>홀드아웃 부분 통과</b>(9셀 중 3셀만 통과 — 나머지는 표시하지 않습니다) · <b>참고 의견 — 매매 신호가 아닙니다.</b> 아래 숫자는 예측이 아니라 기준율입니다."** 로 렌더된다(`dashboard.js:1683,1686` — cellN=9, passN=3 은 계약의 `holdout_pass_cells`·`holdout_fail_cells` 길이에서 나온다). 게이트 칩 줄에는 `설계창 게이트 통과` · `신선도 OK · 기준일 2026-09-08` · **`홀드아웃 부분 통과 3/9`** · `VIX 15.7 · RV21 12.1%` 가 뜬다. 표는 3행(VIX 25 이상 터치 / VIX 30 이상 터치 / 실현변동성 > 16.9%) × 3열(5·21·63 영업일)이지만 **9칸 중 6칸이 "—"** 다 — 표시 모듈이 `holdout_fail_cells` 에 든 셀을 payload 에서 아예 빼기 때문이다(`timeseries_v13_vol_display.py:196-197`). 남는 숫자는 셋뿐이다: **VIX 25 터치 / 21영업일 = 기준율 9%** [80%: 6–13%] (기후 42%, `▲ 국면 표본 얇음` 마커 부착), **실현변동성 초과 / 5영업일 = 7%** [80%: 5–8%] (기후 55%), **실현변동성 초과 / 21영업일 = 35%** [80%: 28–43%] (기후 67%). 63영업일 열은 세 칸 모두 비었고, 그래서 모바일 기본 지평이 63 이 아니라 숫자가 있는 지평으로 열리도록 코드가 조정돼 있다(`dashboard.js:1707-1709`). 카드 아래 역할 문장은 실패 분기로 갈린다: 등록 질문 `vix-25-90d` 의 대응 셀 `vix25_h63` 이 실패 목록에 있으므로 **"…대응하는 셀(63영업일)은 <b>홀드아웃(2015~2018)을 통과하지 못해 base rate를 공급하지 않습니다.</b> 위 숫자는 지평·사건이 다른 기준율이며 이 질문에 대입하지 않습니다."** 가 뜨고, 같은 이유로 **AI 예측 대비 괴리 칩은 아예 생성되지 않는다**(`dashboard.js:1715-1718` 이 `cells.vix25_h63` 을 참조하는데 그 셀이 없다). 즉 **화면에는 LLM 확률과 수치모델 확률이 나란히 놓이는 지점이 지금은 없다.** 각주는 80% 대역이 계수 불확실성이지 보정 구간이 아님을 명시하고, 배선(V13-D6)은 열리지 않았으므로 이 숫자들은 어떤 질문의 base rate 로도 주입되지 않는다 — `publication` 의 `combined_with_official_forecasts`·`combined_with_scenario_v5_2`·`combined_with_timeseries_v8`·`trading_signal` 이 전부 `false` 이고, 표시 모듈이 그중 하나라도 참이면 예외를 던진다(`timeseries_v13_vol_display.py:72-73`).

> **같은 화면의 다른 카드**: V8 가격 카드는 `shadow_operational_hold` 로 숫자가 없다 — 사유는 DTWEXBGS 정지(§1 P1b). 즉 시계열 화면에서 지금 숫자가 나오는 표면은 **V13 변동성 카드의 3칸이 전부**다.

---

## 6. 검토관이 오독하기 쉬운 지점 (요약)

| # | 함정 | 사실 |
|---|---|---|
| 1 | "P0~P4 완료 = 프로그램 완성" | 아니다. 완성은 C0~C4 이고 현재 **C2 만 완전 충족**이다(§2). 단계 완료와 완성 조건은 다른 축이다 |
| 2 | 설계도 §2 의 "홀드아웃 미소모 · 예산 3/8" | 같은 날 오전 스냅샷이며 **낡았다**. 현재 홀드아웃 1/3 소모 · 예산 4/8 (§1.2) |
| 3 | "홀드아웃 3/9 통과 = 약한 결과" | family P(k≥3|n=9,p=0.05)=**0.0084** 로 다중비교를 통과한다. 다만 **G2 가 항등 통과라 실질 판정 다리는 G1·G4 둘뿐**이었다(§4.3) |
| 4 | "기후 대비 BSS 가 크면 스킬" | `vix30_h5` 는 BSS +0.615 인데 라벨을 블록 순열해도 **100% 재현**된다(G4 1.000). 사건 희소성(25/1001)에서 오는 자명한 이득이다(`팩:B_verdicts/V13_HOLDOUT_VERDICT_20260909.md` §2) |
| 5 | "배선이 안 된 것은 실패" | `V13-D6-defer` 는 **사용자의 명시적 보류 결정**이고 재개 조건(셀당 성숙 원점 60)이 영수증에 기록돼 있다 |
| 6 | "P5 는 돈만 쓰면 열린다" | 선행 조건이 셋이다: CBOE **회신** · 적재+PIT 등급 · P4 채택 ≥1셀(설계도 §3 P5). **P4 채택은 0** 이므로 설계도 §6.3 의 역논리대로 **보류가 정답**인 상태다 |
| 7 | `vol_live.jsonl` 3행 = 원점 3개 | 아니다. 고유 as_of 는 **2개**이고 성숙 채점은 **0** 이다 |

---

## 7. 이 팩만으로는 확인할 수 없는 것 — [미확인]

| 항목 | 왜 미확인인가 |
|---|---|
| `read_model_contract.validate` 의 실제 실행 결과(C4 판정 다리) | 해당 모듈(`src/ai_fc/read_model_contract.py`)이 팩에 없다. 팩에는 `F_code/tests/` 만 있고 테스트 실행 로그도 없다 |
| 라이브 사이트의 렌더 결과 자체 | 스크린샷·빌드 산출 payload 가 팩에 없다. §5 는 계약 + 표시 코드에서 **유도**한 것이다 |
| 계약의 사전등록 기후 상수와 실행 상수의 차이(§4.5)가 의도된 것인지 | 이 불일치를 다룬 판정서·결정 기록이 팩에 없다 |
| rung-4 사전등록 커밋 해시 | 판정서는 `7a868424`, 계약 L284·원장은 `0ce8569b` 로 적는다. 계약이 "병렬 세션의 브랜치 전환으로 원커밋을 clean 브랜치에 cherry-pick — 내용 동일"이라 설명하나, **두 커밋의 내용 동일성 자체는 팩에서 검증 불가** |
| 홀드아웃 verb 의 드라이런 3종 거부 기록 | 판정서 §5 가 "데이터를 읽기 전에 거부됨을 확인했다"고 서술하나 그 실행 로그는 팩에 없다 |
| V8 섀도 원장(`shadow_forecasts.jsonl`·`shadow_resolutions.jsonl`) 원본 | 팩에 없다. C1 의 V8 몫(2/126)은 `팩:B_verdicts/V8_SHADOW_ORIGIN_STALL_20260909.md` 의 서술을 인용한 것이다 |
| P5 차단 요인의 1차 증거 `docs/generated/licenses.generated.md` | 팩에 포함돼 있지 않다. §1 P5 행의 인용(25행 "## Pending manual reviews" / 27행 CBOE 언급)은 **저장소 원본을 직접 열어 확인한 것**이며, 팩만 보는 검토관은 재검증할 수 없다 |
| `data/timeseries_v13/runs/holdout_V13VOL_champion_aec80c65038b.json` 의 전체 내용 | 팩 `E_artifacts/runs/` 에 파일은 있으나 이 문서의 수치는 전부 **원장(`holdout_scorings.jsonl`)** 에서 읽었다. 두 파일의 상호 대사는 하지 않았다 |
