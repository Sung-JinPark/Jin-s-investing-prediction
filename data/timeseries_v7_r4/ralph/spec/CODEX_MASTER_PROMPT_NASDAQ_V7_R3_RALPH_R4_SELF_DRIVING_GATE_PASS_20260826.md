# Codex Master Prompt — NASDAQ V7-R3 Ralph R4 Self-Driving Gate-Pass Loop

## 0. 이 프롬프트의 우선순위와 목적

이 문서는 기존 V7-R3, R3, QFIX1, 첫 Task 프롬프트에 있던 다음 지시를 **Ralph R4 실행에 한해 명시적으로 대체한다.**

```text
기존 지시: 한 Codex invocation은 한 task만 수행하고 다음 task를 시작하지 않는다.
R4 지시: 자식 Codex worker는 한 task만 수행한다. 그러나 부모 Ralph Supervisor는
         결과를 독립 검증한 즉시 다음 eligible task를 자동 lease하고 새 Codex worker를 실행한다.
```

다음 두 값은 의미를 분리한다.

```text
child_worker_started_another_task = false   # 항상 유지
supervisor_continued_after_child  = true    # terminal state 전까지 유지
```

기존 `next_task_started=false`를 전체 loop 중단 조건으로 해석하지 마라. 그 필드는 deprecated다.

이번 작업의 목표는 단일 보고서나 단일 Task를 완료하는 것이 아니다. 다음을 실제 코드와 상태 저장소로 구현하고, 같은 invocation에서 Supervisor를 시작해야 한다.

1. P0-001/P0-002 이후 멈춘 실행을 안전하게 이어받는다.
2. 기술적·데이터·모델 실패를 종료가 아니라 다음 Task로 변환한다.
3. FRED/ALFRED 및 공식 공개 데이터 DB를 증분 축적한다.
4. PIT snapshot과 mature label이 준비될 때마다 사전등록된 연구 generation을 실행한다.
5. 실제 Gate를 낮추거나 comparator를 바꾸지 않고 통과 가능성이 가장 높은 가설을 순차 검증한다.
6. 모든 자동 Gate가 진짜 PASS하면 `REVIEW_PROPOSAL`을 생성한다.
7. 새 정보가 없으면 상태를 보존한 `WAIT_DATA`로 정상 종료하고, trigger가 생기면 resume한다.
8. 보안·보호범위·거버넌스 위반만 hard stop으로 취급한다.

**계획만 작성하고 끝내지 마라. Supervisor 구현·테스트·부트스트랩 후 실제 run을 시작하라.**

---

## 1. 역할

당신은 다음을 동시에 담당하는 시니어 엔지니어다.

- 금융 probabilistic forecasting
- FRED/ALFRED point-in-time 데이터 엔지니어링
- XNAS calendar와 label interval 검증
- PostgreSQL task orchestration
- nested rolling-origin validation
- distributional stacking과 calibration
- Codex subprocess 격리·검증
- 모델 리스크와 append-only evidence governance

개별 자식 worker는 한 Task만 처리한다. 부모 Supervisor는 terminal state까지 반복한다.

---

## 2. 반드시 먼저 읽고 검증할 입력

다음 파일을 찾아 SHA-256을 계산하고, 제공된 값과 대조한다.

```text
NASDAQ_V7_R3_P0_001_P0_002_FULL_REVIEW_PACK_20260826.zip
SHA-256: 9c57725beb833b3da8a67963f3dfe4399484396e3e21c308935c1e04a9110e28
bytes:   16693897

NASDAQ_V7_ALFRED_PIT_TRAINING_REVIEW_PACK_20260825.zip
SHA-256: 72192f9369ec6a43e563650629ea2fbd986aa2ca15d8fcd665d6deaec9ae4087

NASDAQ_V7_FRED_ALFRED_OPEN_DATA_RALPH_R3_PACK_20260825.zip
SHA-256: 51fb83ac35e39e47edd53c2413f830565a6f9d816ad8b1b6ad551c4413a83b87

NASDAQ_V7_R3_LOOP_STOP_ROOT_CAUSE_AND_RALPH_R4_GATE_PASS_BLUEPRINT_20260826.md
NASDAQ_V7_R3_RALPH_R4_ROOT_CAUSE_EVIDENCE_20260826.json
NASDAQ_V7_R3_RALPH_R4_CONFIG_20260826.yaml
NASDAQ_V7_R3_RALPH_R4_BOOTSTRAP_BACKLOG_20260826.json
NASDAQ_V7_R3_RALPH_R4_GATE_DEFICIT_ROUTER_20260826.yaml
CODEX_TASK_ENVELOPE_TEMPLATE_V7_R4_20260826.json
CODEX_RESULT_TEMPLATE_V7_R4_20260826.json
```

그리고 저장소에서 다음을 읽는다.

```text
tools/ralph_v7.py
tools/ralph_timeseries.py
기존 V7-R3 controller 및 pipeline
V7 contract와 frozen Gate
105개 V7-R3 backlog
P0-001/P0-002 task result
FRED/ALFRED collector
PIT snapshot builder
backtest/stacking/calibration/model source
관련 tests와 CI workflow
```

입력 hash가 다르면 원본을 수정하지 말고 `BLOCKED_INPUT_INTEGRITY`로 기록한다.

---

## 3. 변경할 수 없는 현재 사실

```text
model_id:                 shadow.nasdaq_pit_hierarchical_distribution_v7
latest ALFRED run:         v7-alfred-20260825T083047Z
latest ALFRED state:       HOLD_RESEARCH_GATE
latest ALFRED return code: 2
P0-001:                    SUCCEEDED
P0-002:                    SUCCEEDED
P0-003 started:            false
next eligible tasks:       V7R3-P0-003, V7R3-P0-004
task branch:               codex/timeseries-v2-ralph
task HEAD:                 57ced6daf8efb4a37e00b649784059ce147adc36
latest IXIC date:          2026-08-12
evaluation date:           2026-08-26
```

직전 Gate 수치도 immutable evidence다.

```text
h1 skill:                 +1.5335433157%
h5 skill:                 -4.3370846495%
h21 skill:              -119.1357300901%
h63 skill:               -23.1281767099%
21/63 mean skill:         -71.1319534000%
paired CI upper:           +0.0444542047
coverage 80%:              76.1636452719%
coverage 50%:              43.7775600196%
balanced direction:        51.4027847000%
P(up) Brier:                0.2505960908
base-rate Brier:            0.2340827346
extreme Q4 coverage:        58.8638589618%
catastrophic degradation: 650.5626038747%
```

이 수치를 삭제·덮어쓰기·재분류하여 PASS로 바꾸지 마라.

---

## 4. 왜 기존 loop가 멈췄는지 코드로 재현할 것

Supervisor 구현 전에 최소 regression test로 다음 원인을 모두 재현한다.

1. legacy prompt가 다음 Task를 금지했다.
2. 자식 종료 후 다음 Task를 lease할 부모 process가 없다.
3. research Gate HOLD가 exit code 2라 `set -e` wrapper가 종료된다.
4. controller가 collect-to-qualification 한 cycle만 실행한다.
5. 같은 run ID의 append-only directory 재사용이 거부된다.
6. P0-001/P0-002 산출물이 untracked라 clean base가 아니다.
7. IXIC freshness 실패가 collector Task로 route되지 않는다.
8. automation 구현이 backlog P6 뒤쪽에 있다.
9. deterministic technical reviewer가 수동 dependency blocker다.
10. Gate deficit을 새 data/model/calibration Task로 변환하는 router가 없다.

각 regression은 수정 전 실패하고 수정 후 통과해야 한다.

---

## 5. 절대 보호 범위와 버전 경계

다음은 read-only다.

```text
data/timeseries_v1/**
data/timeseries_v2/**
data/timeseries_v3/**
data/timeseries_v4/**
data/timeseries_v5/**
data/timeseries_v6/**
기존 V7 sealed run 및 correction ledger
outputs/timeseries_v1/** ~ outputs/timeseries_v7의 기존 sealed artifacts
data/scenarios/**
data/forecasts/**
기존 official/customer numerical surface
```

V7-R3 구현 완성 범위에서 허용되는 것:

- 이미 계약에 선언된 collector, PIT, fold, E0~E7, stacking, calibration의 실제 구현
- orchestration·runtime·freshness·lineage·검증 결함 수정
- 새로운 cycle/generation/attempt 생성
- append-only correction

다음은 새 계약과 새 model ID가 필요하다.

- Gate threshold 변경
- comparator 정의 변경
- weekly origin frequency 변경
- horizon 변경
- V7 contract 밖 신규 expert
- evaluation window 변경
- prospective cohort 재시작 또는 교체

이런 변경이 필요하면 자동으로 V8 contract proposal Task를 만들되 V7 결과를 수정하지 마라.

---

## 6. Secret·권한 경계

Codex worker 환경에서는 다음을 제거한다.

```text
FRED_API_KEY
BLS_API_KEY
BEA_API_KEY
EIA_API_KEY
CME_API_KEY
CBOE_API_KEY
NASDAQ_DATA_LINK_API_KEY
GH_TOKEN
GITHUB_TOKEN
모든 provider credential
```

- `.secrets`를 읽지 않는다.
- Collector worker만 provider secret을 사용할 수 있다.
- Collector는 코드 수정 권한이 없다.
- Trainer/Evaluator는 frozen snapshot만 읽는다.
- Codex는 sanitized diagnostics, fixture, receipt/object hash만 받는다.
- 로그와 result에 secret 값, query-string credential, authorization header를 남기지 않는다.

---

## 7. R4 구현 namespace와 목표 CLI

기존 모델 ID를 바꾸지 않고 orchestration patch를 별도 namespace에 구현한다.

```text
tools/ralph_v7_r4.py
src/ai_fc/timeseries_v7_r4/
migrations/timeseries_v7_r4/
data/timeseries_v7_r4/ralph/
outputs/timeseries_v7_r4/
src/tests/timeseries_v7_r4/
```

필수 CLI:

```bash
python tools/ralph_v7_r4.py bootstrap   --review-pack NASDAQ_V7_R3_P0_001_P0_002_FULL_REVIEW_PACK_20260826.zip   --config NASDAQ_V7_R3_RALPH_R4_CONFIG_20260826.yaml   --backlog NASDAQ_V7_R3_RALPH_R4_BOOTSTRAP_BACKLOG_20260826.json

python tools/ralph_v7_r4.py run   --run-id <RUN_ID>   --auto-codex   --continuous   --until REVIEW_PROPOSAL,WAIT_DATA,HARD_BLOCK

python tools/ralph_v7_r4.py resume <RUN_ID> --auto-codex --continuous
python tools/ralph_v7_r4.py status <RUN_ID> --json
python tools/ralph_v7_r4.py report <RUN_ID>
python tools/ralph_v7_r4.py pause <RUN_ID>
python tools/ralph_v7_r4.py abort <RUN_ID>
```

`run`은 단순 plan 출력이 아니라 실제 task lease·worker dispatch·validation·replan을 수행해야 한다.

---

## 8. Control plane

### 8.1 PostgreSQL 우선

실제 collector·training·evaluation loop는 PostgreSQL control plane을 사용한다.

연결 우선순위:

1. `DATABASE_URL`로 지정된 외부 PostgreSQL
2. Docker가 가능하면 project-local PostgreSQL 자동 기동
3. 둘 다 불가하면 engineering bootstrap만 local journal에 기록하고 `WAIT_INFRA_POSTGRES`

SQLite/local JSON은 다음에만 허용된다.

- review pack import
- bootstrap migration 준비
- PostgreSQL 연결 전 engineering Task evidence

모델 학습·Gate run의 authoritative task state로는 사용하지 않는다.

### 8.2 Task identity

```text
run_id
cycle_id
generation_id
hypothesis_id
task_key
attempt_id
```

같은 `collect`, `train`, `score` Task가 새 cycle/generation에서 반복 가능해야 한다.

### 8.3 Task state

```text
PENDING
READY
LEASED
RUNNING
VALIDATING
SUCCEEDED
RETRY_WAIT
WAIT_DATA
SKIPPED_DEPENDENCY
BLOCKED
HOLD
FAILED
CANCELLED
```

### 8.4 Lease

```text
SELECT ... FOR UPDATE SKIP LOCKED
lease_seconds = 300
heartbeat_seconds = 30
fencing_token required
result commit requires current owner + fencing token
expired worker result rejected
```

장기 subprocess 중 background heartbeat를 유지한다.

---

## 9. 프로세스 exit code 의미를 수정할 것

다음은 정상적인 연구 상태이며 exit code 0이다.

```text
REPLAN
RETRY_WAIT
WAIT_DATA
DATA_REFRESH
RESEARCH_GATE_FAILED_REPLAN
REVIEW_PROPOSAL
```

다음만 non-zero hard failure다.

```text
BLOCKED_INPUT_INTEGRITY
BLOCKED_SECURITY
BLOCKED_SECRET_LEAK
BLOCKED_PROTECTED_SCOPE
BLOCKED_GOVERNANCE
CONTROLLER_BUG
DATABASE_CORRUPTION
```

모델 Gate 미달을 process crash로 반환하지 마라.

Shell wrapper에서도 `set -e`가 연구 HOLD를 중단시키지 않도록 machine-readable state를 먼저 읽고 처리한다.

---

## 10. 부모 Supervisor와 자식 Codex Worker

### 10.1 부모 Supervisor

부모는 다음 loop를 유지한다.

```python
while not aborted:
    reconcile_expired_leases()
    propagate_dependency_states()
    import_new_receipts_and_labels()
    wake_waiting_tasks()

    tasks = select_runnable_tasks_by_priority_and_capability()
    if tasks:
        dispatch_in_parallel_with_limits(tasks)
        validate_and_finalize_results()
        continue

    gate = latest_frozen_generation_gate()
    if gate and gate.all_automatic_gates_pass:
        create_review_proposal()
        transition('REVIEW_PROPOSAL')
        break

    if gate and not gate.pass_:
        deficits = diagnose_gate_deficits(gate)
        new_tasks = route_deficits(deficits)
        if new_tasks:
            enqueue_deduplicated_tasks(new_tasks)
            transition('REPLAN')
            continue

    if trigger_expected_or_future_labels_pending():
        transition('WAIT_DATA')
        persist_wake_conditions()
        break

    transition('HOLD_NO_ADMISSIBLE_NEXT_STEP')
    break
```

### 10.2 자식 Codex Worker

각 자식은 Task envelope 하나만 처리한다.

```text
- isolated git worktree
- allowlisted paths
- no provider secrets
- failing test first
- minimum coherent patch
- targeted tests
- required acceptance commands
- result.json
- child_worker_started_another_task=false
- 종료
```

자식이 끝나면 부모가 즉시 검증하고 다음 Task를 시작한다.

### 10.3 Codex 호출

부모는 `codex exec`를 직접 호출한다. 명령은 플랫폼에 맞게 구성하되 최소한 다음을 포함한다.

```text
--sandbox workspace-write
-C <isolated_worktree>
--json
--output-last-message <task_output>
<task_specific_prompt>
```

Codex invocation 실패도 Task retry로 처리한다. 같은 normalized blocker가 세 번 반복되면 동일 프롬프트를 반복하지 말고 다른 해결 family로 route한다.

---

## 11. R4 부트스트랩을 가장 먼저 실행

### B0-001 — 최신 팩 검증·상태 import

- ZIP 안전 추출
- 55개 Manifest hash 검증
- P0-001/P0-002 result import
- task HEAD·branch·untracked path 확인
- immutable audit receipt 생성

### B0-002 — clean audit base

- P0 관련 untracked 파일 allowlist·secret scan
- 테스트 재실행
- 별도 audit commit
- clean base SHA 저장

### B0-003 — Supervisor 최소 기능

- task table/migration
- dependency resolver
- lease/heartbeat/fencing
- child dispatcher
- validator
- automatic continuation

### B0-004 — exit semantics

- `HOLD_RESEARCH_GATE`를 `RESEARCH_GATE_FAILED_REPLAN`으로 매핑
- exit code 0
- shell integration test

### B0-005 — 기존 105개 backlog import·재배치

기존 ID와 acceptance를 보존하면서 다음 순서로 재배치한다.

```text
R4 bootstrap automation
→ P0-003/P0-004
→ P0 governance/runtime
→ P1 PostgreSQL control plane
→ P2 FRED/ALFRED incremental
→ P3 PIT/calendar/features/folds
→ P4 models/stacking/calibration
→ Gate
→ P5 official open-data challengers
→ P6 prospective operations
```

### B0-006 — 즉시 실행 가능한 원래 Task

`V7R3-P0-003`과 `V7R3-P0-004`를 dependency가 허용하는 범위에서 병렬 실행한다.

P0-003 지시:

```text
original baseline을 수정·삭제하지 않는다.
superseding append-only correction을 추가한다.
original hash, corrected hash, 4개 path, commit provenance를 기록한다.
```

P0-004 지시:

```text
Python runtime, OS, wheel hashes, exchange_calendars, parquet runtime을 동결한다.
review pack 단독 replay와 full repository replay를 구분한다.
```

### B0-007 — IXIC freshness 자동 remediation

```text
DATA_STALE
→ collector refresh task
→ completed XNAS session까지 수집
→ receipt/hash/reconciliation
→ sentinel 재실행
→ 원래 regression 재개
```

---

## 12. GateDeficitRouter

Gate 결과는 boolean으로 끝내지 않고 다음 Task를 생성한다.

| 실패 | 원인 후보 | 자동 Task family |
|---|---|---|
| target stale | collector/cursor | refresh-target, reconcile-target |
| PIT violation | cutoff/availability/lineage | calendar-repair, provenance-rebuild |
| contract/runtime mismatch | hard-coded candidate | candidate-factory, hash-binding |
| h21/h63 < 0 | destructive component | ablation, weight-zero, E0 fallback |
| long skill < 2% | location signal 부족 | direct-horizon residual expert |
| CI upper > 0 | instability/sample | shrinkage, fold robustness, wait-data |
| 50% coverage low | central scale too narrow | cross-fit central-scale calibration |
| extreme coverage low | conditional tails | asymmetric EVT, regime scale |
| Brier worse | P(up) miscalibration | zero-threshold CDF calibration |
| direction < 52% | base-rate only | direction-probability challenger |
| catastrophic > 10% | regime transition failure | regime partial pooling, analog trajectories |
| source absent/stale | data availability | collector or exact weight=0 |

Router는 동일 hypothesis/data/code/runtime 조합을 중복 생성하지 않는다.

---

## 13. 연구 가설 registry

모든 모델 변경은 실행 전에 다음을 동결한다.

```json
{
  "hypothesis_id": "...",
  "mechanism": "어떤 원리로 어떤 Gate를 개선하는가",
  "target_gates": ["h21_skill", "extreme_q4"],
  "allowed_features": ["..."],
  "allowed_components": ["..."],
  "candidate_budget": 12,
  "allowed_evidence_roles": ["research_train", "candidate_selection"],
  "forbidden_evidence_roles": ["outer_test", "prospective"],
  "success_criteria": "...",
  "falsification_criteria": "...",
  "fallback": "E0_only"
}
```

같은 아래 조합은 다시 평가하지 않는다.

```text
hypothesis_hash
contract_hash
dataset_snapshot_hash
code_hash
runtime_hash
```

---

## 14. 검증 fold를 실제 다섯 역할로 분리

각 outer origin에서 다음 역할을 분리한다.

```text
research_train
candidate_selection
stacking
calibration
outer_test
```

각 label에는 다음을 저장한다.

```text
origin_session
label_start_session
label_end_session
mature_at
horizon_sessions
```

필수 조건:

```text
train.label_end_session + embargo_sessions < next_role.origin_session
```

weekly row index에서 `index - 68` 같은 purge를 금지한다. 동일 origin 또는 overlapping label interval이 두 역할에 동시에 들어가면 fail-closed한다.

---

## 15. 데이터/PIT 개선

### 15.1 canonical XNAS cutoff

```text
origin_cutoff_at = versioned XNAS completed-session close + frozen latency
```

ALFRED date-only vintage는 같은 session에 사용하지 않는다. 별도 공식 release timestamp가 없으면 다음 eligible session부터 사용한다.

### 15.2 FRED/ALFRED 증분 수집

```text
초기: bounded full vintage backfill
일상: last successful vintage 이후 output_type=3 증분 revision
주간: partial checksum reconciliation
월간: critical series full-vintage reconciliation
분기: complete series audit
```

cursor는 raw object, receipt, parse outcome, DB commit이 모두 성공한 뒤 원자적으로 전진한다.

### 15.3 feature-value provenance

모든 `origin × feature`에 다음을 보존한다.

```text
origin_id
origin_cutoff_at
feature_id
feature_value
source_observation_ids
source_revision_ids
source_available_at
max_available_at
transformation_hash
age_seconds
missing_policy
data_grade
```

`max_available_at <= origin_cutoff_at`을 전수 검사한다.

### 15.4 macro feature

일별 forward-filled level 차분 대신 다음을 사용한다.

```text
first_release_value
latest_known_at_origin
revision_amount
revision_count
revision_volatility
change_since_previous_release
release_surprise
release_age
revision_age
filtered factor innovation
```

---

## 16. Gate 통과 확률을 높이는 generation 순서

### G0 — 손실 차단

목표: 대형 음수 skill 제거.

- exact E0 empirical samples
- E0 sample hash 동일성
- E0-only benchmark
- component ablation
- E2가 열위면 weight=0
- no-regret fallback

E0-only보다 나쁜 challenger는 final mixture에 들어갈 수 없다.

### G1 — direct horizon core

계약 안에서 다음을 실제 구현한다.

```text
E1 direct quantile elastic net
E2 true Student-t location-scale regression
E3 contract-driven quantile HGB
E4 filtered dynamic linear model
```

모든 모델은 1·5·21·63-session 누적수익률을 직접 학습한다. E0 대비 bounded correction으로 시작한다.

E2:

```text
df    ∈ {3,5,8,12}
alpha ∈ {0.01,0.1,1.0}
objective = Student-t NLL + horizon CRPS + stability penalty
scale residual = cross-fitted only
```

### G2 — 실제 mixture CRPS stacking

component별 CRPS의 단순 가중평균을 최소화하지 마라.

Empirical mixture의 실제 objective:

```text
CRPS(F_w,y)
= Σ_i w_i E|X_i-y|
  - 0.5 Σ_i Σ_j w_i w_j E|X_i-X_j|
  + turnover_penalty
  + complexity_penalty
```

제약:

```text
w_i >= 0
Σw_i = 1
w_E0 >= anchor_floor
stale/unavailable component = 0
mixture가 E0보다 개선되지 않으면 E0=1
```

### G2 calibration

별도 calibration fold에서 다음을 cross-fit한다.

- location
- central scale
- positive tail
- negative tail
- zero-threshold CDF / P(up)

### G3 — stress와 extreme

- learned soft regime with partial pooling
- asymmetric positive/negative EVT
- full 63-session analog daily trajectories
- high-volatility conditional scale/conformal challenger

전체 band를 무조건 넓히지 말고 stress/extreme state에서만 tail을 조정한다.

### G4 — 공식 공개데이터 challenger

G0~G3가 장기 +2%에 도달하지 못하고 사전등록된 데이터 가설이 있을 때만 다음을 별도 challenger로 평가한다.

```text
BLS
BEA
Census Economic Indicators
Treasury nominal/real curve
New York Fed rates/liquidity
SEC EDGAR fundamentals/revisions
OFR FSI
Cboe volatility indices
CFTC positioning
EIA
```

새 source를 이미 본 outer 결과에 맞춰 같은 generation에 추가하지 않는다.

---

## 17. Candidate funnel과 evidence budget

```text
smoke candidates:       최대 160
inner screen:           최대 48
robust inner:           최대 12
full nested:            최대 4
qualification:          최종 1
```

- smoke/inner 결과는 반복 가능
- robust inner는 exposure budget 적용
- full nested qualification은 generation당 한 번
- qualification 실패 후 같은 generation 수정 금지
- 새 generation은 새 data 또는 사전등록된 새로운 mechanism 필요
- prospective 결과는 재튜닝에 사용 금지

---

## 18. Gate는 동결

다음 기존 V7 historical Gate를 낮추지 않는다.

```text
21·63 mean CRPS skill >= 2%
each long-horizon skill >= 0
paired dependence-aware CI upper <= 0
80% coverage in [76%,84%]
50% coverage in [45%,55%]
balanced direction accuracy >= 52%
P(up) Brier < base-rate Brier
extreme Q4 coverage >= 60%
catastrophic phase underperformance <= 10%
historical stress qualification pass
```

Gate를 통과하지 못하면 threshold를 바꾸지 말고 deficit router로 이동한다.

---

## 19. Technical auto-review와 human review 경계

다음은 deterministic policy로 자동 승인 가능하다.

- tests pass
- manifest/hash pass
- protected scope unchanged
- secret scan pass
- migration apply/rollback pass
- feature lineage completeness
- contract/runtime candidate match
- task acceptance evidence complete

다음은 사람 승인이 필요하다.

- Gate threshold 변경
- comparator 변경
- 새 model contract freeze
- prospective primary freeze/replacement
- 고객 공개
- 실제 거래

사람 승인이 필요한 Task만 `WAIT_HUMAN_REVIEW`로 둔다. 기술적 검증을 이유로 전체 loop를 수동 대기시키지 마라.

---

## 20. 실패·재시도·대안 탐색

### 20.1 동일 blocker

- 같은 normalized blocker 1~2회: 수정 후 retry
- 3회: 같은 prompt 중단, 다른 해결 family 생성
- 3개 독립 family도 실패: `WAIT_DATA` 또는 `HOLD_NO_ADMISSIBLE_NEXT_STEP`

### 20.2 Ordinary failure는 loop 종료 사유가 아님

다음은 Task/Generation 재계획 대상이다.

```text
test failure
collector transient failure
schema drift
candidate underperformance
Gate failure
coverage failure
freshness failure
runtime dependency absence
```

### 20.3 Hard stop

다음만 자동 loop를 즉시 멈춘다.

```text
secret leak
protected mutation
input hash mismatch
governance leakage
corrupt authoritative DB
unauthorized publication/trading
```

---

## 21. WAIT_DATA가 실제 wakeable state가 되게 할 것

다음 trigger를 DB에 저장한다.

```text
new mature weekly origins >= 4
new independent resolved events >= 5
approved hypothesis exists
material feature drift
material target drift
new source revision
scheduled collector tick
manual resume
```

`WAIT_DATA` report에는 다음을 반드시 포함한다.

```text
현재 부족한 데이터
현재 count / required count
다음 wake 조건
마지막 collector 성공 시각
다음 예정 task
재개 명령
```

---

## 22. 필수 observability

각 run/cycle/generation/task에 다음을 기록한다.

```text
state transition
started_at / completed_at / duration
command / return code
worker capability
input hashes
output hashes
test receipts
Gate metrics and deficits
hypothesis id
candidate exposure counts
lease/heartbeat/fencing
retry/blocker signature
next action
```

대시보드나 report는 `task count`가 아니라 실제 acceptance evidence를 보여야 한다.

---

## 23. Supervisor acceptance tests

최소한 다음 tests를 작성한다.

1. child one-task 종료 후 supervisor가 다음 task를 자동 lease
2. research Gate fail이 exit 0 + REPLAN
3. shell `set -e`에서도 loop 지속
4. 같은 run에서 새 cycle/generation 생성
5. expired lease recovery
6. stale fencing token result 거부
7. heartbeat 중 task 중복 lease 방지
8. dependency success propagation
9. dependency hard failure propagation
10. technical reviewer 자동 승인
11. IXIC stale → collector task 자동 생성
12. transient collector failure → retry wait
13. same blocker 3회 → alternate family
14. Gate deficit → 정확한 router task
15. no new evidence → quantified WAIT_DATA
16. all automatic Gate pass → REVIEW_PROPOSAL
17. protected mutation → diff 폐기 + exit 2
18. secret output → block + redact
19. qualification generation당 1회
20. prospective score가 training input으로 사용되면 governance block

Chaos test로 Supervisor kill/restart 후 동일 state에서 resume되는 것도 검증한다.

---

## 24. 초기 실행 순서

이번 invocation에서 다음을 실제로 수행한다.

```text
1. 입력 검증
2. R4 root-cause regression 작성
3. R4 Supervisor/bootstrap 구현
4. PostgreSQL 준비 또는 project-local Docker PostgreSQL 기동
5. P0-001/P0-002 import
6. clean audit commit
7. original 105 backlog import/reorder
8. P0-003/P0-004 자동 lease
9. IXIC freshness remediation
10. broad test rerun
11. continuous Supervisor 시작
```

초기 Codex invocation이 Supervisor를 구현한 뒤, 다음 Task를 직접 수행하지 말고 Supervisor process가 새 child Codex를 호출하게 한다.

실행 예:

```bash
python tools/ralph_v7_r4.py bootstrap   --review-pack /path/to/NASDAQ_V7_R3_P0_001_P0_002_FULL_REVIEW_PACK_20260826.zip   --config /path/to/NASDAQ_V7_R3_RALPH_R4_CONFIG_20260826.yaml   --backlog /path/to/NASDAQ_V7_R3_RALPH_R4_BOOTSTRAP_BACKLOG_20260826.json

python tools/ralph_v7_r4.py run   --run-id <BOOTSTRAP_OUTPUT_RUN_ID>   --auto-codex --continuous   --until REVIEW_PROPOSAL,WAIT_DATA,HARD_BLOCK
```

`run`을 시작하지 않고 plan/report만 제출하면 이번 Task는 실패다.

---

## 25. 최종 종료 조건

### 정상 성공

```text
REVIEW_PROPOSAL
```

조건:

- integrity/data/validation/model/stress/operational automatic Gate PASS
- immutable frozen generation
- complete receipts
- no protected/secret/governance violation

### 정상 대기

```text
WAIT_DATA
WAIT_HUMAN_REVIEW
```

상태·DB·checkpoint·wake condition을 저장하고 exit 0.

### Hard block

```text
BLOCKED_SECURITY
BLOCKED_PROTECTED_SCOPE
BLOCKED_GOVERNANCE
BLOCKED_INPUT_INTEGRITY
DATABASE_CORRUPTION
```

exit 2와 상세 evidence.

### 금지된 종료

다음 이유만으로 전체 run을 종료하지 마라.

```text
한 Task 완료
한 candidate 실패
historical Gate 실패
수집 temporary failure
테스트 한 건 실패
IXIC stale
다음 Task를 자식이 시작하지 않았음
```

---

## 26. 최초 결과 보고 형식

초기 bootstrap invocation 종료 전 다음을 출력한다.

```text
R4 run_id
control-plane backend
clean base SHA
imported P0 receipts
current task counts by state
active child worker
last completed task
next queued tasks
latest Gate deficits
Supervisor process/command
current terminal or continuing state
artifact paths and SHA-256
```

Supervisor가 `REVIEW_PROPOSAL`, quantified `WAIT_DATA`, 또는 hard block에 도달하기 전에는 단순히 “P0-003을 다음에 실행하면 된다”라고 말하고 끝내지 마라.
