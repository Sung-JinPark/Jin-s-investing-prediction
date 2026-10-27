# 외부 적대적 리뷰 해소 보고 (external_review_resolution)

작성: 2026-10-27 · 대상 리뷰: 리뷰팩 r1 에 대한 외부 AI 독립 리뷰 (F01~F14 + Q1~Q15 + 미질문 3건)
검증 방법: 쟁점군별 독립 검증 에이전트 5개가 실코드·계약·산출물과 전수 대조 (read-only,
합성 재현 포함) → 확정 결함은 코드·테스트 수정, 과장 서술은 문서 정정, 판단 불가는 필요 증거 명기.
수정 후 상태: `test_mts_research_*` **141 passed** (127 → +14), 동결 파일 변경 0, 원장 append-only 유지.

판정 어휘: **CONFIRMED**(지적이 실코드에서 사실) / **PARTIALLY_CONFIRMED**(일부만) /
**REJECTED_WITH_EVIDENCE**(코드가 이미 방어) / **NEEDS_EVIDENCE**(문서·코드만으로 판정 불가).

## 0. 리뷰 수검 중 실측으로 드러난 결함 1건 (리뷰 외 — 같은 날 CI 가 포착)

| | |
|---|---|
| 사건 | PR #357 CI 실패: `tier1_replay` 의 latest pointer 검증이 MISMATCH |
| 원인 | **우리 adapter 결함** — 운영 포인터는 원점 필드가 `as_of` 인데 adapter 가 `origin` 만 찾음. 포인터가 hold(숫자 없음) 상태인 동안은 이 경로가 실행된 적이 없어 테스트가 위험을 검증하지 못했다 (리뷰의 메타 지적 그대로) |
| 수정 | `adapters/v8.py` — `verify_latest_pointer()` 로 추출, `origin → as_of` 폴백, 합성 테스트 3종(라이브 as_of PASS / 변조 MISMATCH / hold·무매칭) 추가 |
| 검증 | 실포인터 투영 전 항목 bit 일치 (p10~p90×4지평 + probability_up) — identity 재생성: PB 33/34(+구sha 1)·해소 129/129, V8 9/9·23/23(grid-skip 4), **pointer PASS** |

## 1. F01~F14 판정·처리

### F01 [중대] 기계적 확정 비율의 BSS 귀속 — **CONFIRMED → 문서 정정**
- 근거: 측정은 '양성 중 rv_floor>θ 비율'(results.json summary)뿐 — Brier/BSS 를 기계적/비기계적
  부분집합으로 분해한 산출물이 어디에도 없음 (rv_mechanics.py 는 Brier 를 계산하지 않음).
- 수정: "큰 몫" 귀속을 rv_mechanics_audit.md·research_verdict.md·리뷰팩 §6.1 에서 **철회** —
  지지되는 진술("양성의 55~85%가 원점에서 확정")로 교체, Brier 분해(ΔBS = P(M)E[ΔL|M]+
  P(¬M)E[ΔL|¬M], 리뷰 Q12 표의 8/20/39·41/29/10 재계산 일치 확인)는 **사전등록 후속**으로 등재.
- 남은 위험: 분해 실행 전까지 RV 셀 성적의 조기경보 가치는 상한/하한 미정.

### F02 [중대] 성공 교집합 편향 — **CONFIRMED → 코드 수정**
- 근거: `candidate_failure_policy: hold_confirmatory_verdict` 는 계약·스키마 선언뿐, 집행 코드 0
  (eligible_paired_mean 은 성공 교집합 평균, CANDIDATE_FAILURE 는 기록만).
- 수정: `resampling.candidate_failure_count()` + `gates.enforce_candidate_failure_policy()`
  신설 — eligible 원점의 후보 실패 ≥1 이면 확증 판정 E7 HOLD, 미등록 정책은 예외. 테스트
  `test_f02_candidate_failure_counted_and_policy_enforced`.
- 남은 조건: W7 등록 시 registered_fallback_policy_hash 충전 + "전체 발행 정책 평가 vs 조건부
  성적+실패율 분리" 중 택일을 등록 (리뷰 권고 그대로).

### F03 [중대] "보호 bytes 읽기 0" 문구 — **PARTIALLY_CONFIRMED → 문서 정정**
- 근거: 무단 읽기는 없음 — tier-1/tier-2/PB 가 여는 파일 전수 확정(계약 yaml·원장 5종·무컷오프
  market archive·매크로 facts·dfm cache), sealed '검증'은 기존 봉인 평가 **산출 행**의 해시
  재검이지 봉인 원자료 재계산이 아니고, tier-2 는 생산 경로(주간 shadow)와 동일한 전체 bundle
  재생. 계약의 '소모' 정의(finalist 홀드아웃 채점·봉인 1회 공개)에 해당하지 않으며 replay/audit
  은 연구층 OPEN purpose 로 exposures.jsonl 에 기록됨. **그러나** "bytes 읽기 0" 문구는 문서
  자신의 '읽기=소모' 요약 기준으로 문자 그대로는 거짓.
- 수정: verdict·handoff·inventory·리뷰팩 4곳을 "guarded purpose(fit/평가) 읽기 0 + OPEN
  purpose 읽기는 전 기간·기록됨" 으로 정밀화.
- 남은 위험: 없음 (계약 위반 아님 확정) — 단 향후 가드가 loader 실읽기 전에 집행된다는 증거는
  W8 운영 배선 시 추가.

### F04 [중대] 발행 마감 부재 — **CONFIRMED → 코드·계약 수정**
- 근거: 발행창/마감 개념이 records·maturity·계약 어디에도 없고, 유일 상한 가드
  `assert_prospective_issue` 는 commit 경로에 **배선돼 있지 않았음** (호출자가 테스트뿐).
- 수정: `artifacts.verify_commit_preconditions()` 신설 + `commit_forecast` 가
  evidence_track='prospective' 에서 강제 — ① now < 첫 대상 세션 information cutoff (T15 상한),
  ② 등록된 `max_issuance_latency_seconds` 초과 발행 거부 (마감), ③ spec.information_cutoff_at
  == 세션 정책 값 (F14 잔여). draft 계약에 `max_issuance_latency_seconds: null` 추가 + run 필수
  null 목록 등재. 테스트 `test_f04_q6_prospective_commit_preconditions` (6경로).
- 과거 원장: 무수정 (prospective 발행 이력 0 — 적용 대상 없음).

### F05 [중대] 재생 모드의 적합·보정 관통 — **PARTIALLY_CONFIRMED → 부분 수정 + 증거 명기**
- 근거: 가용성·snapshot·라벨 성숙까지는 관통하나, fitted/calibration state 검증은 cutoff 비교뿐
  (replay mode·checkpoint 미결박), OofRecord 에 recorded_at 없음. 반면 `series_heads` 해시
  제외는 **방어 가능**(커밋된 이력의 순수 함수) — 그 하위 지적은 기각. first_seen_at←
  vintage_start 는 실수신 시각이 맞음(retrieved_at).
- 수정: `OofRecord.label_recorded_at` 추가 + `mature_oof_view(replay_mode=...)` —
  operational_replay 는 라벨 **기록 시각**도 cutoff 이내 요구 (maturity.matured_view 의 T59
  규율 복제). 테스트 `test_f05_operational_oof_requires_recorded_at`.
- NEEDS_EVIDENCE 로 남김: DFM smoothed-state·전체창 scaling 의 원점 고정(동결 코드 영역 —
  읽기 전용 추적 감사 후속), TrainingBatchRef/CalibrationStateRef 에의 replay_mode·checkpoint
  필드 추가는 W7 계약 등록과 함께 (스키마 변경이 등록 실험 좌표와 결합돼 있어 함께 동결).

### F06 [중대] 경로형 라벨의 revision 결박 — **CONFIRMED → 코드·정책 수정**
- 근거: LabelEvent.outcome_snapshot_id 가 MATURE 에도 Optional, 정정 채점 정책은 암묵
  latest-wins 뿐 (label_revision_policy_hash: null).
- 수정: ① MATURE/RESTATED 에 **outcome_snapshot_id 필수** (model validator — 경로 전체 판은
  outcome snapshot 의 observation_revision_ids_hash 로 커밋), ② 라벨 revision 정책 정본
  `data/mts_research/contracts/label_revision_policy_v1.md` 신설(채점 대상=terminal 판·원판
  병렬 보고·역유입 금지) + draft 의 label_revision_policy_hash 를 그 sha256 으로 충전.
  테스트 `test_f06_terminal_label_requires_outcome_snapshot`.
- 남은 항목: informative censoring 가정은 hazard 실측 전 별도 검토 (W5 등록 좌표).

### F07 [중대] 검증 수준 합산 — **PARTIALLY_CONFIRMED → 문서·보고 수정**
- 근거: 코드·세부 절은 3수준을 구분하나 verdict thesis("바이트 수준 재현")·불리언 명명
  (v8_tier1_identity)이 합산. 설계서 T49 기준은 전행 재계산을 요구하지 않음(그 범위에서 PASS
  유효).
- 수정: verdict thesis 를 3단 구분으로 재서술, baseline_identity.json 에 `verdict_scope`
  필드 추가(각 불리언이 합치는 검증 수준 명시), PB 는 "허용오차 재계산" 명기.

### F07u [경미] "1~2 ulp" — **CONFIRMED → 문서 정정**
- 근거: grid 원소 |v| ≤ 0.085 에서 2.0e-16 은 최대 원소 기준 14.2 ulp·중앙값 기준 114 ulp —
  "1~2 ulp" 는 eps 단위 오기 (성립하려면 |v| ≥ ~0.5 필요).
- 수정: verdict·리뷰팩 2곳을 "절대 크기 0.1~0.9 eps / 값 크기 ulp 로 3.5~114 / 상대오차
  ≤1.4e-14" 로 정정. strict MISMATCH 판정·결론은 불변.

### F08 [중대] grid-skip 항등식의 전제 — **CONFIRMED(전제 성립) → 수정 불요 + 표적 정책 유지**
- 근거: 동결 코드가 리뷰의 조건부 정확성 전제 그대로다 — 수익을 **주식 세션에서 먼저** 계산
  (features.py `_log_change` 후 reindex)하고 **그 뒤** dropna 로 grid 선별 → 차감 항등식 exact
  (실측 2행 1e-9 재현; 2026-10-27 재생성에서 grid-skip 4행 전부 재현). "밀린 종료일 vs 빠진
  수익" 구분도 adapter 가 len(between)!=horizon 분기로 시끄럽게 보고 — 조용한 오통과 없음.
- 유지: legacy grid 표적은 동결 보존, 신규 표적은 대상 거래소 세션으로 별도 ID (handoff 기록
  — 리뷰 Q7 권고와 일치). "−0.0044" 수치는 저장소 미기록이라 리뷰팩에서 [저장소 미기록] 처리.

### F09 [중대] legacy 중복의 손실표 유입 — **CONFIRMED → 코드 수정 + 재생성**
- 근거: 실측 — origin_losses.parquet v13 행에 2026-09-04 중복 run 2벌(6셀×2모델=12행, 손실
  동일). rescore_resolved 에 dedupe 없음; V13 계약 dedupe_rule 과 기존 구현 distinct_resolutions
  은 미사용 상태였음.
- 수정: rescore_resolved 가 `distinct_resolutions`(핀 sha 우선→knowledge_cutoff 최신)를 적용,
  `v13_dropped_duplicates` 메타 보고, parquet 재생성(파생물): **292행 = V13 123 distinct×2 +
  V8 23×2, 중복 6 제거, (track,cell,origin,model) 유일성 테스트 고정**. 원장 무수정.

### F10 [중대] 희소 코호트 bootstrap 유효성 — **CONFIRMED → 코드 수정 + 등록 조건**
- 근거: min_paired·B_eff==0 외 기준 없음 — 퇴화 수는 보고만 되고 소비처 없음. draft null 좌표
  29개 전수 확인 (degenerate_replicate_policy_hash 포함).
- 수정: `centered_paired_bootstrap_test(min_effective_replicates=, max_degenerate_rate=)` —
  등록 임계 미달이면 p 없이 EVIDENCE_INSUFFICIENT. 테스트
  `test_f10_registered_degenerate_thresholds_downgrade_to_insufficient`.
- 등록 조건(W7): 두 임계를 degenerate_replicate_policy 문서에 명시 후 hash 충전. 리뷰 Q1 의
  민감도 산술 범위(p_lo/p_exclude/p_hi)는 등록 문서에 포함 권고.

### F11 [중대] 사건 0 bin 비식별 — **CONFIRMED (리뷰보다 악성) → 코드 수정**
- 근거(합성 실측): 사건 0 bin 에서 절편 −201 로 발산해도 L-BFGS-B fallback 이 converged=True
  보고; **risk-set 0 bin 은 절편이 초기값 0 에 머물러 λ=0.5·p(63)=1.0 을 무경고 날조** —
  리뷰 지적보다 나쁨. 완화: 합성 전용 scaffold·계약 hazard.enabled=false.
- 수정: bin별 risk/사건 사전 점검 → `non_identified_bins`(행0·사건0·전건)·`slope_divergence`
  (|β|>35, 분리)·`estimable` property 신설 — **converged 와 식별가능 분리**;
  `hazard_curve`/`cumulative_event_probability` 가 비식별 bin 을 지나는 지평 거부(식별 구간은
  허용 — p(5)/p(21) 가능, p(63) 거부). 테스트 3종(사건0 bin·빈 bin·ridge=0 분리).
- 등록 조건(W5): 비식별 시 fallback(HOLD·baseline·사전 지정 bin 통합)은 **모형 정의 변경**이라
  V14-D11 계약에 등록.

### F12 [중대] "재튜닝 낭비" 단정 — **CONFIRMED → 문서 정정**
- 근거: 같은 문서의 실측(λ 선택 분기·분위차 0.0412/0.1542)과 모순 — 간접 영향의 존재는 영향
  없음을 지지하지 않음.
- 수정: 리뷰팩 §6.2 함의 문장 정정((lag,α) 제외는 철회, '낭비'는 BYPASSED block_length 만),
  objective_align_audit.md 에 "INDIRECT_VIA_LAMBDA = 영향 경로 있음" 명시. Q13 의 미추적 경로
  4종(과거 λ 이력·잔차/표준화 전달·lag 의 이력/캐시 영향·재보정 재유입)은 handoff 후속 감사로
  등재.

### F13 [경미] 채점기 계약 — **CONFIRMED(일부 기각) → 코드·문서 수정**
- 근거(실측): WIS round(q,12) 붕괴 키 4개가 격자 검사 통과 + 삽입 순서로 점수 0.6↔0.667 분기,
  variogram 은 X+50·1 균일 편향에 점수 불변(상대차 9e-15). **log_loss clip 비대칭 주장은 기각**
  — min(max(p,ε),1−ε) 대칭 설계 실측 확인.
- 수정: wis() 에 반올림 붕괴 키·중복 alpha GridMismatch 가드, variogram docstring 에 "균일
  bias 불변 — 단독 사용 금지·CRPS/Energy 병용" caveat + 균일 편향 맹점 실측 테스트. QLIKE
  proxy 좌표(RV21² 여부 등)는 미결 등록 좌표로 명기 (Q5).

### F14 [경미] 시간 계약 명칭 — **REJECTED_WITH_EVIDENCE (잔여 간극만 수정)**
- 근거(실측): 조기폐장 2025-07-03 cutoff = 17:15 UTC(13:15 ET) — **close+900s 가 맞고 고정
  16:15 ET 아님** (리뷰가 우려한 downstream 고정 시각 해석 경로 없음). ForecastDraft 에
  issued_at 없음 — commit 에서만 확정 (의미 혼동 없음).
- 잔여 수정: '함수가 spec 에 결박되지 않던' 간극은 F04 의 commit 검사 ③ 이 해소. policy_id
  명칭 개선(settle_close_plus_900s_v1)은 다음 계약 버전 과제로 기록.

## 2. Q1~Q15 처리 (판정 + 반영 위치)

| Q | 판정 | 반영 |
|---|---|---|
| Q1 부트스트랩 방향·퇴화 | 식·방향·B_eff·보고는 코드 그대로 **확인**; 퇴화 제외의 조건부 분포 문제는 사실 | F10 수정(임계 2종) + 등록 문서에 민감도 범위 포함 권고 |
| Q2 블록 길이 | 수용 — 사전등록 선택 규칙(결과 전 확정, 최소 p 쇼핑 금지) | W7 등록 좌표 (draft null 유지) |
| Q3 Holm | **REJECTED_WITH_EVIDENCE** — 구현이 리뷰 식과 정확히 일치 (무작위 2,000회 참조 구현 대조 불일치 0, adjusted_p≤α 동치) | 수정 불요 |
| Q4 rv_floor | **CONFIRMED+강화** — 닫힌형 유리수 항등(500/500), k 비증가 정리(argmax≡1), floor(1)≤RV21, V14 평온 자격의 구조적 배제(평온 48원점 확정 0) | 리뷰팩 §6.1 정리 교체 + 정리 테스트 2종 추가 |
| Q5 QLIKE proxy | 수용 — proxy 수식·조건부 무편향 조건·좌표 목록 | 미결 등록 좌표로 명기 (scores.py·리뷰팩) |
| Q6 영속화 전 사용 | **CONFIRMED** — commit 이 snapshot 문자열만 기록 | F04 수정 ①(영속 manifest 결박) — checkpoint 의 commit 단계 바이트 재검은 W8 배선 과제 |
| Q7 grid-skip·신규 표적 | 항등식 조건부 정확성의 전제 성립 확인 (F08); 신규 기본 = 대상 거래소 h세션 | handoff 기존 기록 유지 |
| Q8 분모 보존 | **PARTIALLY** — matured_view 는 UNRESOLVED 보존(리뷰 가정과 다름)하나 미발행 원점은 구조상 불가, 실원장 LossPanel 빌더 미구현 | handoff 에 빌더 원칙 1줄(예정 원점 달력 우선) + F02 게이트 연계 |
| Q9 계수 bootstrap | 미구현 확정 — 의도된 W7 범위 (no_iid_ci 플래그·문서 일관) | W7 등록 시 원점 블록 trajectory 재표집 + F11 비식별 처리 선행 |
| Q10 bin fallback | 수용 — 첫 실험 bin 고정, 비식별=추정불가+등록 fallback | F11 수정이 감지측 선행 구현; fallback 등록은 V14-D11 계약 |
| Q11 조건부 PB | **확정** — rung-1 조건부 PB = 조건 충족 부분집합 내 방향별 신규 적합 (V14 계약 baselines.conditional_persistence_pb; 동결 계수 비승계 명시) — 동결 V13 챔피언과 다른 객체 | 명칭 혼동 주의를 resolution 에 기록 (이 표) |
| Q12 분해 감사 | 표(8/20/39·41/29/10) 재계산 일치; 양성만 분해 금지·재결합 요건 수용 | F01 후속(사전등록 Brier 분해)의 설계 입력 |
| Q13 λ 간접 경로 | 수용 — 미추적 경로 4종 | handoff 후속 감사 목록에 등재 |
| Q14 해제 순서 | 수용 — W5 즉시 적합 아님, W7 등록 선행 + 운영 계측은 기존 권한 내 준비 | §4 재판정에 반영 |
| Q15 최위험 미질문 | 수용 — "재현되는 계산이 당시 가능했던 계산인가" | F05 수정 + DFM/ASOF_AGE 후속 감사, DQ1 과 동일 축 |

## 3. 미질문 3건 (DQ)

- **DQ1 (미래 자료 추가 후 과거 operational 불변)**: 부분 반영 — F05 의 recorded_at 가드 +
  Q6 의 snapshot 결박이 재료. 원점 단위 end-to-end 증거(입력 revision→전처리→상태→발행)는
  **NEEDS_EVIDENCE** — 허용 fixture 로 W7 전 1회 수행 권고 (등록 좌표에 포함).
- **DQ2 (감사의 라벨 꼬리)**: **PARTIALLY_CONFIRMED → 공시·정정** — 실측: 마지막 원점
  2014-12-04 의 h63 라벨 끝 = **2015-03-09** (XNAS 63세션), V8 홀드아웃 창 가격을 라벨 경로가
  소비. 계약 정의상 평가 소모 아님(모델 후보 채점 없음·claims_excluded)이나 노출 영수증
  window(~2014-12-31)는 과소 신고 → 정정 행 `rv-mechanics-20261026-correction-r2`
  (window 끝 2015-03-09, 사유 명기) append + rv_mechanics_audit.md 공시. 향후 감사의
  requested_window 끝 = design_end + max(horizon) 세션 규칙 채택.
- **DQ3 (연구자 선택·노출 이력의 family)**: 수용 — 구조적 반영은 W7 등록 좌표(이전 결과 노출
  이력·개발/확증 구분·미래 평가 시작점·중간 확인·종료 규칙). 현 세션의 모든 노출(rung-1 결과,
  중간 Brier, 본 감사)은 리뷰팩·본 문서가 공개 기록으로 남긴다 — 이미 본 코호트의 독립 확증
  표본 소급 지정 금지 원칙 유지.

## 4. W5~W8 실행 가능 여부 재판정 (2026-10-27)

| 단계 | 판정 | 남은 차단 조건 (정확한 좌표) |
|---|---|---|
| W5 실측 (V14 rung-2 hazard) | **BLOCKED 유지** | ① 사용자 결정 **V14-D11** + `data/timeseries_v14/ledgers/approvals.jsonl` 리터럴 영수증, ② rung-2 prereg, ③ **이번에 추가된 선행 조건**: 비식별/분리 fallback 정책 등록(F11)·전체 발행 정책 vs 조건부 성적 택일(F02)·발행창(F04)·δ/블록/B_eff·퇴화율(F10, Q2)·bin 고정(Q10)·조건부 PB 기준선 모델 ID 분리(Q11) |
| W6 실자료 | **BLOCKED 유지** | 원천 1개의 계약·권한·coverage verified 후 source_spec enabled 전환 — "한 번에 1블록" |
| W7 등록 실험 | **BLOCKED 유지 (조건 목록은 더 구체화됨)** | 계약 draft→registered: 잔여 null **29−1=28개** (label_revision_policy_hash 는 2026-10-27 충전; max_issuance_latency_seconds 신설로 +1) + read scope/예산 영수증 + DQ1 의 원점 단위 시간 증거 1회 |
| W8 운영 연결 | **BLOCKED 유지** | 운영 계약·표시 승급 승인; commit 단계 checkpoint 바이트 재검 배선은 이때 |
| 기존 승인 범위 작업 | **완료** — 본 문서의 코드 7건·문서 6건·파생 재생성·노출 정정이 그것 | — |

## 5. 요약 집계

| 분류 | 건수 | 항목 |
|---|---|---|
| CONFIRMED → 코드 수정 | 7 | F02 F04 F06 F09 F10 F11 F13(+pointer 결함) |
| CONFIRMED/PARTIALLY → 문서 정정 | 6 | F01 F03 F07 F07u F12 DQ2 |
| REJECTED_WITH_EVIDENCE | 3 | Q3(Holm) F14(조기폐장 cutoff·issued_at) F13-clip(대칭) |
| 확인·강화 (수정 불요) | 3 | F08(전제 성립) Q4(정리 승격) Q11(정의 확정) |
| NEEDS_EVIDENCE (후속) | 3 | F05-DFM/상태결박 일부 · DQ1 end-to-end · F03-가드 선행 집행 증거(W8) |
| W7 등록 좌표로 수용 | 6 | Q2 Q5 Q9 Q10 Q12 DQ3 |

모든 수정은 `src/ai_fc/mts_research/**`·`data/mts_research/**`·`docs/research/mts_upgrade/**`
안에서만 이루어졌다 — 동결 모델·계수·보호 파일 무수정, 기존 원장 행 무수정(정정은 append),
허용오차 무확장(tier-2 MISMATCH 유지), 홀드아웃·봉인 신규 열람 0, 예산 소모 0, V14-D11/W7/W8
권한 비대체.
