# AI Investing Scenario Graph PR3 — Codex Master Remediation & True RCFHS-SB Implementation Prompt

**문서 버전:** 2026-08-07  
**목적:** 이미 merge된 PR2의 의미·분포·UI 결함을 교정하고, Legacy diagnostic과 실제 RCFHS-SB shadow를 엄격하게 분리한다.  
**작업 원칙:** 한 번의 Codex chat에서 한 Batch만 수행하고 반드시 멈춘다. 자동 commit·push·PR·merge 금지.

---

# 0. 역할

당신은 이 저장소의 다음 역할을 동시에 수행한다.

- 수석 Quant Engineer
- 시계열·Monte Carlo 검증자
- 금융 데이터 lineage·PIT 감사자
- Python application engineer
- Dashboard information architect
- 테스트·재현성 책임자

이 작업의 목적은 그래프를 눈에 띄게 다르게 만드는 것이 아니다.

목적은 다음과 같다.

```text
1. 모델 이름과 실제 구현을 일치시킨다.
2. 확률분포, 대표경로, official weight, candidate implied weight를 분리한다.
3. 같은 input/config/seed에서 같은 canonical artifact가 나오게 한다.
4. 오래된 source에서 만든 shadow를 현재 결과로 표시하지 않는다.
5. 시나리오별 fan은 실제 pointwise conditional quantile로만 만든다.
6. 대표선은 실제 ensemble member이며 다변량으로 중앙적인 경로를 선택한다.
7. 진짜 RCFHS-SB는 승인된 PIT history가 있을 때만 생성한다.
8. rolling-origin 검증 전에는 어떤 candidate도 champion으로 승격하지 않는다.
```

---

# 1. 배경과 현재 판정

PR2 merge commit:

```text
0c14900fec2f1276e799df09f68c8270fd5d9646
```

현재 PR2는 다음 장점이 있다.

- 공식 `data/scenarios/nasdaq_latest.json` 미변경
- 별도 shadow artifact
- dashboard toggle default OFF
- 실제 legacy GBM ensemble member를 굵은 선으로 표시

하지만 다음 이유로 **RCFHS-SB 구현으로 인정하지 않는다.**

1. `src/ai_fc/scenario_v4_shadow.py`는 기존 official GBM snapshot을 입력으로 사용한다.
2. regime engine, state-conditioned drift, EWMA/GARCH, standardized residual, stationary bootstrap가 없다.
3. `scenario_conditional_fans`의 p25/p50/p75는 pointwise quantile이 아니라 terminal percentile actual path다.
4. p25≤p50≤p75가 S1 19/52, S2 28/52, S3 27/52 지점에서 깨진다.
5. dashboard는 `scenario_conditional_fans`를 렌더링하지 않고 `sc.fan`만 렌더링한다.
6. shadow 활성 시 `RCFHS-SB v1 official`이라고 표시한다.
7. `generated_at=now()` 때문에 동일 입력 재실행이 no-op이 아니다.
8. source snapshot SHA와 stale 상태를 검증하지 않는다.
9. full legacy path matrix는 공식 snapshot만으로 정확히 재현 가능하지만 PR2는 이를 BLOCKED로 잘못 판정했다.
10. rolling-origin validation이 없다.

현재 artifact의 올바른 의미는 다음이다.

```text
Legacy GBM Actual-Member Display Diagnostic
```

현재 artifact에 사용하면 안 되는 표현:

```text
RCFHS-SB
actual V4 quant engine
official
champion
validated conditional distribution
```

---

# 2. Source of truth와 필수 파일

작업 시작 전에 아래 파일을 전부 읽는다.

```text
AGENTS.md

prompts/scenario_v4/AI_INVESTING_SCENARIO_V4_MODEL_DECISION_260806.md
prompts/scenario_v4/AI_INVESTING_SCENARIO_V4_CODEX_MASTER_PROMPT_260806.md
prompts/scenario_v4/AI_INVESTING_SCENARIO_V4_PR3_REMEDIATION_MASTER_PROMPT_260807.md

docs/audit/phase3_260807/AI_INVESTING_SCENARIO_V4_PR2_DEEP_AUDIT_260807.md
docs/audit/phase3_260807/AI_INVESTING_SCENARIO_V4_PR2_DEFECT_REGISTER_260807.csv
docs/audit/phase3_260807/AI_INVESTING_SCENARIO_V4_PR2_AUDIT_METRICS_260807.json
```

기존 원본 문서 예상 SHA-256:

```text
AI_INVESTING_SCENARIO_V4_MODEL_DECISION_260806.md
e0fc35b9d544e223545e8a81939c46ea1606497943ec3e83bf5397c28f58baf3

AI_INVESTING_SCENARIO_V4_CODEX_MASTER_PROMPT_260806.md
e995506fa76664dd0ade7e805bb92e17eb45651876c8f0f78ef6602eb074f0ba
```

감사 산출물 예상 SHA-256:

```text
AI_INVESTING_SCENARIO_V4_PR2_DEEP_AUDIT_260807.md
898373f2a298ab01878738b79a6195cfe6bdeaa2064f40fcbbf5407a81a8a62f

AI_INVESTING_SCENARIO_V4_PR2_DEFECT_REGISTER_260807.csv
ee04325b3ca190464f9bcd64a208bb0c36bf51f5e15188f247b957c11922d1f3

AI_INVESTING_SCENARIO_V4_PR2_AUDIT_METRICS_260807.json
c9a7f4932401559753c876459395360d3b3333cda3004e82ef52e10d28a84b03
```

PR2 검토 원본 ZIP SHA-256:

```text
d55d04af0f111499d29535e8fe58fd905857c6bcfe8e5abf46d26f3150a26588
```

우선순위:

```text
1. AGENTS.md의 저장소 공통 안전규칙
2. 이 PR3 Master Prompt
3. PR2 Deep Audit와 Defect Register
4. 기존 Scenario V4 Master Prompt
5. 실제 저장소 코드와 test
```

상위 문서와 실제 코드가 충돌하면:

- 실제 현재 동작은 코드로 확인한다.
- 목표 동작은 상위 명세를 따른다.
- 차이를 보고서에 기록한다.
- 임의 해석으로 범위를 넓히지 않는다.

---

# 3. Mandatory hard-stop preflight

## 3.1 파일 누락

필수 파일이 하나라도 없으면:

```text
status = BLOCKED_MISSING_SPEC
application source changes = 0
data artifact changes = 0
```

다음 보고서만 생성하고 멈춘다.

```text
docs/audit/phase3_260807/PR3_PRECHECK_BLOCKED.md
```

누락된 Master Prompt를 대신 추측하여 축소 구현하지 않는다.

## 3.2 Git 상태

다음을 실행하고 기록한다.

```powershell
git status --short
git branch --show-current
git rev-parse HEAD
git rev-parse --show-toplevel
git worktree list
git merge-base --is-ancestor 0c14900fec2f1276e799df09f68c8270fd5d9646 HEAD
```

규칙:

- 현재 변경을 `reset`, `restore`, `checkout`, `clean`, `stash`, 삭제하지 않는다.
- unrelated uncommitted change가 있으면 코드 작업을 중단하고 보고한다.
- PR2 merge commit이 HEAD의 ancestor가 아니면 중단하고 보고한다.
- main에서 직접 작업하지 않는다.
- 권장 permanent worktree 이름은 `scenario-v4-pr3-remediation`이다.

## 3.3 Allowed path gate

PR3A에서 허용되는 경로:

```text
AGENTS.md
prompts/scenario_v4/**
docs/audit/phase3_260807/**
reports/md/**
data/contracts/scenario_path_shadow_v2.yaml
data/scenarios/shadow/**
src/ai_fc/scenario_v4_shadow.py
src/ai_fc/scenario_shadow/**
src/ai_fc/cli.py
src/ai_fc/dashboard.py
src/ai_fc/read_model_contract.py
src/ai_fc/dashboard_parts/dashboard.js
src/ai_fc/dashboard_parts/dashboard.css
src/tests/test_scenario_shadow_*.py
src/tests/test_scenario_legacy_*.py
src/tests/test_scenario_representative.py
src/tests/test_dashboard.py
src/tests/test_read_model_contract.py
tools/reproduce_scenario_snapshot.py
tools/verify_scenario_shadow_package.py
```

allowlist 밖 변경을 발견하면 자동 수정하지 말고 보고한다.

특히 다음은 PR3A에 포함하지 않는다.

```text
data/source_monitoring/**
calibration/**
ledger/**
data/scenarios/nasdaq_latest.json
data/scenarios/archive/**
unrelated generated inventory changes
```

## 3.4 네트워크와 의존성

- 외부 네트워크 호출 금지
- 실시간 시장 API 호출 금지
- 새 dependency 설치 금지
- `pyproject.toml` dependency 변경 금지
- secret·token 출력 금지
- 실제 투자 주문 및 broker API 호출 금지

---

# 4. 불변 조건

다음 파일·값은 모든 Batch에서 보존한다.

```text
data/scenarios/nasdaq_latest.json
official scenario probabilities
official snapshot id/revision
calibration ledger
forecast ledger
data/scenarios/archive/**
legacy replay output
```

공식 snapshot 기준 SHA-256:

```text
7526638e1b11a04e91112a673fbbca91c00ceb4c00cb1211774532f05d796f9c
```

모든 Batch 시작·종료 시 이 hash를 재검사한다.

또한 다음을 금지한다.

```text
- scenario별 수동 drift/noise
- 그래프 분리를 위한 jitter
- fixed dip date
- endpoint forcing
- target MDD forcing
- common residual template
- year별 path splice
- Jan 1 model reset
- pointwise median을 actual representative라고 표시
- conditional sample 부족 시 unconditional fan 복사
- quantile을 weighted average하여 mixture quantile로 계산
- official probability를 shadow implied weight로 덮어쓰기
- validation을 통과시키기 위한 silent clipping
- failure를 숨기는 silent fallback
```

---

# 5. 작업 단위와 PR 전략

한 번에 모두 구현하지 않는다.

```text
PR3A-R0  Baseline characterization / no behavior change
PR3A-R1  Semantic safety hotfix / retire misidentified RCFHS artifact
PR3A-R2  Honest legacy GBM actual-member diagnostic
PR3A-R3  Dashboard state/view redesign
PR3A-R4  Evidence package and independent review

PR3B-D0  Approved PIT history contract and data gate
PR3B-Q1  Regime / drift / volatility / residual / bootstrap core

PR3C-Q2  Continuous RCFHS paths and conditional distributions
PR3D-UI  True V4 shadow dashboard
PR3E-OOS Rolling-origin validation
```

각 Batch 종료 후:

1. 테스트 실행
2. 보고서 작성
3. git diff 검토
4. 반드시 멈춤
5. 다음 Batch 자동 시작 금지
6. 자동 commit/push/PR/merge 금지

---

# 6. PR3A-R0 — Baseline characterization

## 6.1 목표

코드를 고치기 전에 PR2 결함과 공식 기준선을 결정론적으로 고정한다.

## 6.2 수행 항목

1. PR2 current artifact와 source code를 읽는다.
2. 공식 snapshot SHA-256을 기록한다.
3. old shadow SHA-256을 기록한다.
4. `tools/reproduce_scenario_snapshot.py`를 실행한다.
5. 공식 snapshot만으로 full 20,000×252 path matrix가 재현되는지 확인한다.
6. S1/S2/S3 counts를 확인한다.
7. 1,764 quantile cells mismatch를 확인한다.
8. old coarse conditional arrays의 monotonicity violation을 재계산한다.
9. old representative path의 metric percentile을 재계산한다.
10. dashboard에서 `scenario_conditional_fans` 참조 여부를 확인한다.
11. shadow active label에 `official`이 들어가는지 확인한다.
12. 동일 input으로 build 두 번 했을 때 payload가 달라지는지 확인한다.
13. loader가 source stale을 차단하는지 확인한다.
14. current full test baseline을 실행하고 환경 blocker를 구분한다.

## 6.3 Characterization tests

현재 잘못된 old artifact를 대상으로 다음 사실을 고정하는 test를 추가할 수 있다.

```text
test_pr2_archived_artifact_declares_rcfhs_but_uses_legacy_gbm_source
test_pr2_archived_coarse_paths_are_not_monotone_quantiles
test_pr2_archived_dashboard_label_contains_incorrect_official_text
test_legacy_snapshot_reproduction_is_exact
test_current_shadow_build_is_timestamp_nondeterministic
```

이 테스트는 active future design을 승인하는 테스트가 아니다. old artifact가 왜 retired되는지 증명하는 audit characterization이다.

## 6.4 산출물

```text
docs/audit/phase3_260807/PR3A_R0_BASELINE_CHARACTERIZATION.md
docs/audit/phase3_260807/PR3A_R0_METRICS.json
```

보고서 판정:

```text
CONFIRMED
PARTIALLY CONFIRMED
NOT CONFIRMED
BLOCKED BY ENVIRONMENT
```

## 6.5 Gate

다음이 모두 PASS여야 R1로 갈 수 있다.

```text
- official hash unchanged
- exact legacy reproduction confirmed
- old fan monotonicity defect confirmed
- old RCFHS identity mismatch confirmed
- old UI official mislabel confirmed
- no application behavior changed
- no data artifact changed
```

---

# 7. PR3A-R1 — Semantic safety hotfix

## 7.1 목표

사용자가 현재 artifact를 RCFHS·official로 오인할 가능성을 즉시 제거한다.

## 7.2 Old artifact retirement

현재 파일:

```text
data/scenarios/shadow/rcfhs_sb_v1_latest.json
```

다음 원칙으로 처리한다.

1. 기존 bytes와 SHA-256을 보존한다.
2. active `latest`로 더 이상 load하지 않는다.
3. audit archive로 이동하거나 exact copy를 보존한다.

권장:

```text
data/scenarios/shadow/archive/
  rcfhs_sb_v1_misidentified_20260806_<sha-prefix>.json

data/scenarios/shadow/archive/
  rcfhs_sb_v1_retirement_receipt.json
```

retirement receipt 필수 필드:

```json
{
  "retired_candidate_id": "rcfhs-sb-v1",
  "reason": "model_identity_mismatch_not_actual_rcfhs",
  "original_sha256": "...",
  "replacement_candidate_id": "legacy_gbm_actual_member_v1",
  "official_snapshot_affected": false,
  "retired_at": "...",
  "promotion_state": "retired_never_eligible"
}
```

`retired_at`은 receipt field이며 canonical source artifact bytes를 바꾸지 않는다.

## 7.3 Model identity contract

신규 권장 파일:

```text
src/ai_fc/scenario_shadow/contracts.py
data/contracts/scenario_path_shadow_v2.yaml
```

필수 identity:

```python
ModelFamily = Literal["legacy_gbm", "rcfhs_sb"]
ArtifactStatus = Literal[
    "shadow_only",
    "stale_source",
    "blocked_missing_data",
    "retired_misidentified",
]
```

RCFHS capability gate:

```text
family == rcfhs_sb 또는 candidate_id에 "rcfhs" 포함 시
다음 전부 true + evidence receipt 필수:

approved_pit_history
observable_regime
state_conditioned_drift
conditional_volatility
standardized_empirical_residuals
stationary_block_bootstrap
source_block_lineage
continuous_252_session_recursion
adaptive_joint_simulation
pointwise_conditional_quantiles
actual_member_representative
```

하나라도 없으면 validator가 reject한다.

static self-asserted boolean만으로 통과시키지 않는다. capability마다 다음이 필요하다.

```text
implementation_component
config_version
diagnostic_summary
test_receipt
input lineage
```

## 7.4 CLI compatibility

기존 command:

```text
python -m ai_fc scenario-v4-shadow
```

는 더 이상 잘못된 artifact를 생성하면 안 된다.

허용되는 방식 중 기존 CLI style에 맞는 최소 변경을 선택한다.

권장:

```text
- deprecation error를 출력
- exit non-zero
- "rcfhs-sb-v1 was retired because it was a legacy GBM wrapper"
- 새 artifact write 0건
- 공식 artifact write 0건
```

R2에서 신규 command를 추가한다.

```text
python -m ai_fc scenario-legacy-actual-shadow
```

## 7.5 Dashboard 즉시 안전조치

R2/R3가 완료되기 전에는 old toggle을 숨긴다.

다음 문자열은 active UI에 0건이어야 한다.

```text
RCFHS-SB v1 official
RCFHS-SB v1 shadow
```

retired artifact만 존재하면 read model은 chart candidate로 노출하지 않는다.

## 7.6 R1 tests

```text
test_rcfhs_identity_rejected_without_capabilities
test_misidentified_pr2_artifact_is_retired
test_retired_artifact_bytes_hash_preserved
test_old_cli_does_not_write_artifact
test_read_model_does_not_expose_retired_candidate
test_dashboard_has_no_rcfhs_or_official_shadow_label
test_official_snapshot_hash_unchanged
```

## 7.7 R1 산출물

```text
docs/audit/phase3_260807/PR3A_R1_SEMANTIC_HOTFIX_REPORT.md
```

## 7.8 R1 Gate

```text
- active RCFHS mislabel 0
- active shadow official label 0
- old bytes/hash preserved in audit archive
- official snapshot unchanged
- ledger/archive unchanged
- unrelated file changes 0
```

---

# 8. PR3A-R2 — Honest Legacy GBM Actual-Member Diagnostic

## 8.1 목표

PR2의 유효한 아이디어인 “실제 ensemble member 표시”를 통계적으로 올바른 legacy diagnostic으로 완성한다.

candidate id:

```text
legacy_gbm_actual_member_v1
```

artifact path:

```text
data/scenarios/shadow/legacy_gbm_actual_member_v1_latest.json
```

promotion:

```text
not_eligible_diagnostic_baseline
```

이 candidate는 champion 후보가 아니다. true V4와 비교하기 위한 정직한 baseline이다.

---

## 8.2 Exact legacy matrix reproduction

기존 `tools/reproduce_scenario_snapshot.py`의 stochastic reconstruction logic을 reusable library로 옮긴다.

권장 파일:

```text
src/ai_fc/scenario_shadow/legacy_reproduction.py
```

권장 API:

```python
@dataclass(frozen=True)
class LegacyGBMReproduction:
    future_daily: np.ndarray
    sampled_weekly: np.ndarray
    trading_days: tuple[str, ...]
    week_dates: tuple[str, ...]
    masks: dict[str, np.ndarray]
    counts: dict[str, int]
    probability_percent: dict[str, int]
    verification: dict[str, Any]

def reproduce_legacy_snapshot(snapshot: Mapping[str, Any]) -> LegacyGBMReproduction:
    ...
```

불변식:

```text
n_paths = snapshot.model.n_paths
horizon = snapshot.model.horizon_business_days
seed = snapshot.model.seed
mu = serialized mu_daily_log_return
sigma = serialized sigma_daily_log_return
anchor = snapshot.anchor
classification = snapshot.model.classification_date
partition thresholds = snapshot ATH/reference_price
```

verification:

```text
expected counts == reproduced counts
expected rounded probabilities == reproduced probabilities
expected daily quantile cells == reproduced cells
quantile mismatch == 0
```

하나라도 다르면 artifact를 생성하지 않는다.

`tools/reproduce_scenario_snapshot.py`는 이 library를 호출하도록 바꿔 중복 구현을 제거한다.

---

## 8.3 True pointwise scenario conditional quantiles

각 scenario mask의 실제 cohort matrix에서 시점별 percentile을 계산한다.

```python
q_s(t) = percentile(path_values[mask_s, t], q)
```

terminal percentile actual path를 p25/p50/p75로 사용하지 않는다.

sample gate:

```text
n >= 200  : representative + p50
n >= 500  : p25/p75
n >= 1000 : p10/p90
n >= 2000 : p05/p95
```

현재 expected:

```text
S1 n=16702: all gates
S2 n=302  : representative + p50 only
S3 n=2996 : all gates
```

quantile validator:

```text
for every t:
p05 <= p10 <= p25 <= p50 <= p75 <= p90 <= p95
```

존재하지 않는 quantile key를 빈 배열로 넣지 않는다.

```json
{
  "available_quantiles": ["p50"],
  "blocked_quantiles": {
    "p25_p75": "insufficient_conditional_sample_n_302_lt_500",
    "p10_p90": "insufficient_conditional_sample_n_302_lt_1000",
    "p05_p95": "insufficient_conditional_sample_n_302_lt_2000"
  }
}
```

---

## 8.4 Mixture와 conditional distribution

다음 세 가지를 분리한다.

```text
1. official model-conditional scenario weights
2. unconditional joint GBM distribution
3. scenario-conditional distributions
```

기존 `official_weighted_mixture_fan` 명칭을 그대로 답습하지 않는다.

Legacy matrix에서는 S1/S2/S3가 전체 sample의 partition이므로 full matrix의 unconditional quantile이 joint mixture distribution이다.

중요:

```text
mixture quantile != weighted average of conditional quantiles
```

mixture는 다음 중 하나로 계산한다.

```text
- full joint sample matrix에서 직접 percentile
- cohort samples를 원래 count대로 concatenate한 matrix에서 percentile
```

quantile을 weight로 평균하지 않는다.

official weights:

```json
{
  "unit": "fraction",
  "source": "official_snapshot_partition",
  "values": {"S1": 0.83, "S2": 0.02, "S3": 0.15}
}
```

UI에서만 percent로 변환한다.

---

## 8.5 Actual central representative selector

권장 파일:

```text
src/ai_fc/scenario_shadow/representative.py
```

대표경로는 scenario cohort의 실제 row 하나여야 한다.

각 path의 최소 metric:

```text
terminal_return
annualized_daily_volatility
annualized_weekly_volatility
maximum_drawdown
max_drawdown_date
recovery_date_or_none
time_under_water_sessions
longest_underwater_sessions
down_day_fraction
down_week_count
weekly_direction_change_count
largest_1day_loss
largest_5day_loss
weekly_return_autocorrelation_lag1
squared_daily_return_autocorrelation_lag1
squared_daily_return_autocorrelation_lag5
```

candidate gate:

```text
terminal return percentile: 35~65
annualized daily volatility percentile: 10~90
maximum drawdown magnitude percentile: 10~90
time under water percentile: 10~90
weekly direction-change percentile: 10~90
```

candidate가 없으면:

1. terminal range만 25~75로 한 번 완화
2. 완화 사실 기록
3. 그래도 없으면 representative 숨김
4. smoothing 또는 synthetic path 생성 금지

trajectory:

```text
normalized_log_path_i(t) = log(P_i(t) / P_i(0))
median_trajectory(t) = cohort pointwise median
trajectory_distance_i = mean(abs(path_i - median_trajectory))
```

robust metric distance:

```text
distance = abs(metric_i - cohort_median) / IQR
```

IQR=0은 제외하고 diagnostics에 기록한다.

score:

```text
1.00 trajectory distance
0.50 terminal return distance
0.75 volatility distance
0.75 MDD distance
0.50 time-under-water distance
0.50 direction-change distance
```

tie:

```text
lowest original global path index
```

snapshot metadata:

```text
path_id
original_global_path_index
scenario_local_index
path_sha256
selection_rule_version
selection_score
candidate_gate_status
relaxed_terminal_gate
metric_values
metric_percentiles
terminal_percentile
weekly_values
```

selected values는 original row와 exact 동일해야 한다.

---

## 8.6 Deterministic canonical artifact

권장 파일:

```text
src/ai_fc/scenario_shadow/persistence.py
```

artifact를 다음 두 부분으로 개념적으로 분리한다.

```text
canonical_content
receipt
```

canonical hash에 포함:

```text
schema
candidate identity
source snapshot id/SHA/asof
config
seed
n_paths
quantiles
representatives
diagnostics
```

canonical hash에서 제외:

```text
generated_at
local absolute path
wall-clock runtime
machine username
temporary directory
```

필수 metadata:

```text
source_snapshot_id
source_snapshot_sha256
source_asof
config_sha256
canonical_payload_sha256
generator_version
code_revision_if_available
```

동일 input/config/seed:

```text
canonical_payload_sha256 same
second refresh changed=false
latest bytes unchanged
```

write:

1. validate in memory
2. canonical hash 계산
3. existing latest와 비교
4. same이면 write하지 않음
5. 다르면 temp sibling write
6. flush/fsync 가능한 범위 적용
7. atomic replace
8. immutable shadow archive receipt 생성

---

## 8.7 Stale source gate

loader API는 current official snapshot을 입력받아 검증한다.

```python
def load_candidate(
    root: Path,
    *,
    current_official_snapshot: Mapping[str, Any],
) -> CandidateLoadResult:
    ...
```

다음 중 하나라도 다르면 active payload를 반환하지 않는다.

```text
source_snapshot_id
source_snapshot_sha256
source_asof
canonical hash
schema version
identity capability consistency
```

result:

```json
{
  "status": "stale_source",
  "display_allowed": false,
  "reason": "...",
  "candidate_metadata": "non-price summary only"
}
```

invalid JSON을 조용히 `None`으로 삼키지 않는다. caller에 structured error/status를 반환하고 dashboard에 표시한다.

---

## 8.8 Legacy diagnostic schema

```json
{
  "schema_version": 2,
  "artifact_kind": "scenario_path_shadow",
  "candidate_id": "legacy_gbm_actual_member_v1",
  "status": "shadow_only",
  "promotion_state": "not_eligible_diagnostic_baseline",
  "model_identity": {
    "family": "legacy_gbm",
    "engine_id": "gbm-daily-252d-v2-lookup",
    "display_variant": "actual_member_conditional_diagnostic",
    "is_rcfhs": false,
    "capabilities": {
      "approved_pit_history": false,
      "observable_regime": false,
      "state_conditioned_drift": false,
      "conditional_volatility": false,
      "standardized_empirical_residuals": false,
      "stationary_block_bootstrap": false,
      "source_block_lineage": false,
      "continuous_252_session_recursion": true,
      "pointwise_conditional_quantiles": true,
      "actual_member_representative": true,
      "rolling_origin_validation": false
    }
  },
  "source": {
    "snapshot_id": "...",
    "snapshot_sha256": "...",
    "asof": "...",
    "method": "gbm-daily-252d-v2-lookup"
  },
  "reproducibility": {},
  "official_weights": {},
  "unconditional_distribution": {},
  "scenario_distributions": {},
  "representatives": {},
  "diagnostics": {},
  "receipt": {}
}
```

nested official `model` object 전체를 복사하지 않는다. source provenance 아래 필요한 원문만 보존한다.

---

## 8.9 R2 tests

최소:

```text
test_legacy_reproduction_counts_exact
test_legacy_reproduction_daily_quantiles_exact_1764_cells
test_legacy_reproduction_seed_change_detected
test_conditional_quantiles_are_pointwise
test_conditional_quantiles_monotone
test_s1_quantile_gate_allows_all
test_s2_quantile_gate_allows_only_p50_and_rep
test_s3_quantile_gate_allows_all
test_unconditional_distribution_equals_partition_union
test_mixture_quantile_is_not_weighted_quantile_average
test_representative_is_actual_global_row
test_representative_candidate_metrics_in_gate
test_representative_tie_break_lowest_path_id
test_representative_hidden_when_no_candidate
test_canonical_hash_same_for_same_input
test_generated_at_excluded_from_canonical_hash
test_second_refresh_is_noop
test_source_sha_mismatch_marks_stale
test_corrupt_artifact_returns_structured_invalid_status
test_atomic_write_does_not_leave_partial_latest
test_official_snapshot_hash_unchanged
```

## 8.10 R2 report

```text
docs/audit/phase3_260807/PR3A_R2_LEGACY_DIAGNOSTIC_IMPLEMENTATION.md
docs/audit/phase3_260807/PR3A_R2_REPRODUCTION_RECEIPT.json
docs/audit/phase3_260807/PR3A_R2_REPRESENTATIVE_METRICS.csv
```

---

# 9. PR3A-R3 — Dashboard redesign

## 9.1 목표

모델 전환 시 data와 설명이 완전히 같은 candidate를 가리키도록 state-driven dashboard를 만든다.

## 9.2 Model mode

권장 mode:

```text
official_legacy
legacy_actual_member_diagnostic
rcfhs_shadow
```

현재 PR3A에서는 앞의 두 개만 존재한다.

기본값:

```text
official_legacy
```

legacy diagnostic은 명시적 toggle로만 활성화한다.

표시 문구:

```text
LEGACY GBM ACTUAL-MEMBER · SHADOW DIAGNOSTIC
NOT RCFHS · NOT OFFICIAL · NOT CHAMPION
```

금지 문자열:

```text
RCFHS-SB v1 official
RCFHS-SB v1 shadow
```

true RCFHS artifact가 실제 capability gate를 통과하기 전에는 active UI에 RCFHS를 표시하지 않는다.

## 9.3 View model adapter

서로 다른 schema object를 단순히 `sc=shadow`로 바꾸지 않는다.

권장:

```javascript
function buildScenarioChartViewModel({mode, official, candidates}) {
  return {
    candidateId,
    title,
    subtitle,
    status,
    methodLabel,
    asof,
    sourceStatus,
    officialWeights,
    impliedWeights,
    representativeSeries,
    conditionalDistributions,
    unconditionalDistribution,
    sampleGates,
    warnings,
    yearRanges,
    supportsStructuralBaseline,
    supportsLookup,
    accessibilityText
  };
}
```

모드 전환 시 이 view model을 새로 만들고 model-dependent component를 전부 갱신한다.

## 9.4 Layout

```text
A. Model identity/status banner
B. D=100 actual representative comparison
C. S1/S2/S3 conditional small multiples
D. Unconditional/joint distribution separate panel
E. diagnostics and sample gate table
F. source freshness and reproducibility receipt
```

### A. Banner

필수:

```text
candidate id
family
status
promotion state
source asof
source freshness
canonical hash prefix
```

### B. D=100 비교

```text
each representative normalized to 100 at common origin
common Y scale
actual member only
no fan
no baseline duplication
```

설명:

```text
대표선은 해당 cohort의 실제 경로 한 개이며 p50 자체가 아니다.
모양의 차이는 확률 차이가 아니다.
```

### C. Small multiples

S1/S2/S3 각각:

```text
sample_count
official model-conditional weight
available quantiles
p50
p25-p75 if allowed
p10-p90 if allowed
actual representative
sample gate warning
```

현재 S2:

```text
n=302
p50 only
p25/p75 hidden
p10/p90 hidden
clear insufficient-sample message
```

### D. Unconditional panel

scenario conditional fan과 한 chart에 섞지 않는다.

명칭:

```text
Legacy joint unconditional distribution
```

official weights와 별도.

## 9.5 Dynamic refresh list

toggle 시 다음을 모두 갱신한다.

```text
title
subtitle
candidate id
status badges
method copy
legend
focus buttons
shape/baseline controls
realism cards
probability-space copy
sample counts
warnings
chart aria-label
chart note
lookup source
readout labels
year label
```

## 9.6 Structural baseline

`supportsStructuralBaseline=false`이면:

```text
baseline toggle hidden
baseline path not rendered
structural risk window not rendered
DB-conditioned structural copy not rendered
```

동일 series hash가 display와 baseline에서 중복되면 validator/test가 실패한다.

## 9.7 Lookup

candidate에 daily quantile table이 있을 때만 lookup을 지원한다.

lookup copy는 candidate의 distribution space를 정확히 설명해야 한다.

legacy diagnostic의 conditional small multiples와 unconditional lookup을 혼동하지 않는다.

## 9.8 Accessibility

- toggle `aria-pressed`
- status를 색만으로 구분하지 않음
- SVG aria-label에 candidate id/status/method
- hidden fan은 screen reader에도 없는 것으로 처리
- insufficient sample message를 `role=note` 또는 적절한 live region으로 제공
- keyboard focus 유지

## 9.9 R3 tests

```text
test_dashboard_defaults_to_official_legacy
test_dashboard_diagnostic_toggle_never_says_official
test_dashboard_diagnostic_toggle_never_says_rcfhs
test_toggle_updates_all_model_dependent_copy
test_diagnostic_has_no_structural_baseline_control
test_no_duplicate_display_and_baseline_path
test_dashboard_renders_s1_and_s3_allowed_bands
test_dashboard_s2_renders_p50_only
test_dashboard_does_not_use_unconditional_fan_as_scenario_fan
test_dashboard_shows_source_stale_warning_and_disables_chart
test_dashboard_displays_official_weights_as_comparison_only
test_dashboard_d100_comparison_uses_actual_members
test_dashboard_accessibility_labels_match_active_candidate
```

## 9.10 R3 report

```text
docs/audit/phase3_260807/PR3A_R3_DASHBOARD_REPORT.md
```

가능하다면 브라우저 증거를 생성하되 새 dependency를 설치하지 않는다. 기존 screenshot infrastructure가 없으면 DOM/SVG contract test로 대체하고 `BLOCKED_BY_ENVIRONMENT`를 기록한다.

---

# 10. PR3A-R4 — Evidence package

## 10.1 패키지 내용

```text
source diff
changed-file list
test logs
command/exit-code receipts
official hash before/after
old retired artifact hash
new candidate hash
canonical no-op refresh result
stale-source test result
UI semantic test result
reports
```

## 10.2 Cryptographic manifest

`MANIFEST.txt` 같은 잘린 absolute path 표를 만들지 않는다.

CSV 또는 JSON Lines:

```text
relative_path
size_bytes
sha256
```

ZIP 생성 후 별도 ZIP SHA-256을 기록한다.

0-byte evidence file 금지. “diff 없음”은 다음처럼 명시한다.

```text
command
exit_code
stdout = NO_DIFF
stderr
checked_paths
```

## 10.3 verifier

권장:

```text
tools/verify_scenario_shadow_package.py
```

모든 entry size/hash 검증.

## 10.4 R4 report

```text
docs/audit/phase3_260807/PR3A_R4_REVIEW_PACKAGE_REPORT.md
```

---

# 11. PR3A merge gate

다음이 전부 PASS여야 merge 권고 가능하다.

```text
- current active artifact에 RCFHS 오표시 0
- active shadow에 official 오표시 0
- old artifact retired and hash preserved
- exact legacy path reproduction
- true pointwise conditional quantiles
- all displayed quantiles monotone
- sample gates enforced
- S2 p50-only
- representative actual row
- representative central metric gates
- deterministic canonical hash
- second refresh no-op
- stale source blocks chart
- UI metadata/chart candidate consistency
- no duplicate baseline
- official snapshot hash unchanged
- ledger/archive unchanged
- unrelated path changes 0
- targeted tests pass
- possible full tests categorized
```

PR3A는 여전히 true RCFHS가 아니다.

PR3A 완료 문구:

```text
Legacy GBM diagnostic corrected.
True RCFHS remains not implemented.
```

---

# 12. PR3B-D0 — Approved PIT history contract

이 Batch는 PR3A 독립 검증과 merge 후 별도 worktree/PR에서 수행한다.

## 12.1 목표

실제 RCFHS의 입력 데이터를 감사 가능하게 만든다.

필수 contract:

```text
data/contracts/nasdaq_pit_history.yaml
```

필수 row:

```text
date
close
available_at
source_id
vintage_id
ingested_at
response_sha256
row_sha256
```

필수 metadata:

```text
symbol
calendar
timezone
price adjustment policy
missing-session policy
duplicate policy
correction/revision policy
license status
approved use
minimum sessions
source snapshot SHA
```

PIT gate:

```text
date <= forecast_asof
available_at <= forecast_generated_at
no row from future
strictly increasing unique trading dates
finite positive close
```

minimum:

```text
2520 sessions
```

recommended:

```text
5000 sessions
```

state token gate:

```text
each observable state aligned next-return tokens >= 126
```

승인된 dataset이 없으면:

```text
status = BLOCKED_BY_MISSING_APPROVED_PIT_HISTORY
actual V4 forecast artifact = not generated
```

허용:

```text
contract
validator
synthetic fixtures
unit tests
blocker report
```

금지:

```text
network fetch
unapproved Yahoo live pull
fixture를 real forecast로 저장
```

---

# 13. PR3B-Q1 — True RCFHS quantitative core

## 13.1 Observable regime

각 t는 t까지의 데이터만 사용한다.

feature:

```text
ret_20  = log(close_t / close_t-20)
ret_60  = log(close_t / close_t-60)
vol_20  = std(last 20 daily log returns) * sqrt(252)
vol_60  = std(last 60 daily log returns) * sqrt(252)
vol_ratio_20_60 = vol_20 / vol_60
drawdown_252 = close_t / max(close[t-251:t]) - 1
dist_200dma = close_t / mean(close[t-199:t]) - 1
rsi_14
```

fixed V1 rules:

```text
STRESS:
  drawdown_252 <= -0.10
  OR (ret_20 <= -0.05 AND vol_ratio_20_60 >= 1.20)
  OR rsi_14 <= 30

RECOVERY:
  not STRESS
  AND at least one STRESS in prior 63 sessions
  AND ret_20 >= 0.05
  AND rsi_14 >= 50

EXPANSION:
  not STRESS
  AND not RECOVERY
  AND dist_200dma >= 0
  AND ret_60 > 0
  AND rsi_14 >= 50

RANGE:
  otherwise
```

warmup은 `UNAVAILABLE`.

그래프 모양을 보고 threshold 변경 금지.

## 13.2 State/return alignment

```text
state_t uses data through close t
target return = r_(t+1)
```

누수 test에서 한 row를 future에서 바꿔도 과거 state가 바뀌면 실패한다.

## 13.3 State-conditioned drift

```text
mu_raw_s = 1%/99% winsorized mean of r_(t+1) where state_t=s
w_s = n_s / (n_s + prior_strength)
mu_s = w_s * mu_raw_s + (1-w_s) * mu_global
prior_strength candidates = [252, 504]
```

winsorization은 drift에만 적용한다. residual tail은 clip하지 않는다.

## 13.4 Volatility candidates

EWMA:

```text
h_(t+1|t) = lambda * h_(t|t-1) + (1-lambda) * epsilon_t^2
lambda in [0.94, 0.97, 0.985]
```

GARCH(1,1):

```text
h_(t+1) = omega + alpha*epsilon_t^2 + beta*h_t

omega > 0
alpha >= 0
beta >= 0
alpha+beta < 0.995
```

- NumPy/SciPy only
- deterministic start set
- failed GARCH는 GARCH id로 결과 생성 금지
- EWMA로 silent fallback 금지
- separate candidate id

## 13.5 Standardized residual

```text
epsilon_(t+1) = r_(t+1) - mu[state_t]
z_(t+1) = epsilon_(t+1) / sqrt(h_(t+1|t))
```

- finite
- no silent deletion
- no default clipping
- source date/state/index lineage
- skew/kurtosis/percentile diagnostics
- state token gate

## 13.6 Stationary block bootstrap

block start는 현재 simulated regime과 같은 historical source state pool에서 선택한다.

```text
P(block end after each draw) = 1 / mean_block_length
mean_block_length candidates = [5, 10, 21]
```

block 내부 residual index는 연속 진행한다.

각 generated return 후 simulated price history로 regime을 다시 계산한다.

historical state sequence를 future state로 그대로 복사하지 않는다.

RNG:

```text
numpy.random.Generator(PCG64)
path/batch stream derived deterministically
```

모든 path가 같은 residual block을 공유하면 실패한다.

representative에는 source block lineage를 저장한다.

---

# 14. PR3C-Q2 — Continuous path and distributions

## 14.1 Recursion

At close t:

```text
price_t
state_t
h_next
running_high_t
drawdown_t
block pointer
```

Generate t+1:

```text
z_next = bootstrapped empirical residual
mu_next = state drift
epsilon_next = sqrt(h_next) * z_next
r_next = mu_next + epsilon_next
price_next = price_t * exp(r_next)
```

Update:

```text
variance
simulated history
state_next
running high
drawdown
block pointer
```

불변:

```text
252 future sessions exactly
2026-12-31 / 2027-01 special branch 0
same continuous path array
year view = slice only
endpoint not predetermined
no path splice
```

## 14.2 Joint generator

S1/S2/S3별 파라미터를 만들지 않는다.

```text
one joint generator
→ all paths
→ existing pre-registered partition
→ conditional cohorts
```

시나리오가 비슷하게 나오면 warning을 표시하고 인위적으로 분리하지 않는다.

## 14.3 Adaptive Monte Carlo

```text
base_paths = 100000
batch_size = 5000
max_paths = 300000
```

동일 joint generator에서 독립 deterministic batch를 추가한다.

특정 S2만 별도 모델로 oversample 금지.

sample gates는 R2와 동일.

메모리:

- batch generation
- memmap 또는 동등한 temporary path store
- float64 calculation
- wall time/peak estimate/temp size 기록

## 14.4 Partition

현재 official code definition을 보존한다.

```text
S1: classification date까지 ATH 한 번 이상 초과
S2: S1 아님 AND classification-date close > registered reference price
S3: 나머지
```

mutually exclusive + exhaustive.

classification 이후 2027 값을 사용해 scenario를 역분류하지 않는다.

## 14.5 Probability spaces

```text
official_weights_for_comparison
v4_implied_partition_weights
```

분리.

V4 implied:

```text
count / total valid paths
unit = fraction
Monte Carlo SE
confidence interval
```

official을 덮어쓰지 않는다.

## 14.6 Conditional distributions

각 cohort actual matrix에서 pointwise quantile.

unconditional joint distribution separate.

representative selector는 동일 central actual-path rule, RCFHS에서는 source block lineage 포함.

## 14.7 True V4 candidate ids

```text
nasdaq_rcfhs_sb_ewma_v4_shadow
nasdaq_rcfhs_sb_garch11_v4_shadow
```

filter 실패를 같은 id 안에서 대체하지 않는다.

---

# 15. PR3D-UI — True V4 shadow UI

PR3A에서 만든 view model과 small-multiple layout을 재사용한다.

true V4일 때만 표시:

```text
RCFHS-SB · SHADOW
filter id
PIT dataset id/hash
regime version
block length
seed/config hash
V4 implied weights
rolling-origin state
```

default OFF.

Official Legacy / Legacy Diagnostic / V4 Shadow를 서로 다른 mode로 표시한다.

다음 표현은 금지:

```text
V4 official
V4 champion
V4 more accurate
```

rolling-origin 완료 전:

```text
promotion_state = blocked_pending_rolling_origin_validation
```

---

# 16. PR3E-OOS — Rolling-origin validation

## 16.1 Split

시간순으로 최소:

```text
tuning
validation
holdout
```

threshold/config selection은 tuning에서만.

validation/holdout 보고 전에 freeze.

## 16.2 Baselines

```text
legacy GBM
iid historical simulation
fixed-block bootstrap
EWMA-FHS without regime conditioning
RCFHS-SB EWMA
RCFHS-SB GARCH
```

## 16.3 Horizons

최소:

```text
20
60
126
252 sessions
```

## 16.4 Primary scores

```text
CRPS 또는 normalized WIS
interval coverage
interval width/sharpness
Energy score
Variogram score
```

path realism:

```text
volatility
MDD
time under water
down-week count
direction changes
largest losses
volatility clustering
```

## 16.5 Promotion gate

최소:

```text
- no material CRPS/WIS regression vs frozen baseline
- coverage within preregistered tolerance
- no leakage
- fit stability
- deterministic reproduction
- representative realism gates
- data/lineage complete
- failure rate acceptable
- manual review
```

자동 champion 승격 금지.

결과가 좋지 않으면 shadow 유지.

---

# 17. 필수 test matrix

## Identity/semantic

```text
model id matches actual capabilities
RCFHS name rejected without full capabilities
retired artifact not exposed
shadow never labeled official
promotion state single and consistent
```

## Reproduction/distribution

```text
legacy exact counts
1764 quantile cells exact
pointwise conditional quantiles
monotonicity
sample gates
mixture computed from samples, not quantile average
```

## Representative

```text
actual row exact
candidate gates
robust score
deterministic tie break
path hash
no smoothing/interpolation
```

## Persistence

```text
canonical hash deterministic
generated_at excluded
second refresh no-op
source stale gate
corruption structured status
atomic write
archive receipt
```

## UI

```text
default official
dynamic model copy
no old labels
small multiples
S2 p50-only
separate unconditional
D=100
no duplicate baseline
accessibility
```

## PIT/Quant

```text
no future row
state_t/return_t+1 alignment
regime threshold boundaries
drift shrinkage
EWMA recursion
GARCH constraints/failure
residual lineage
bootstrap determinism
different path streams
```

## Continuous path

```text
252 sessions
no Jan reset
state/variance/drawdown continuity
partition exhaustive
adaptive batches deterministic
invalid batch explicit
```

## OOS

```text
time split
tuning-only selection
score formulas
coverage
promotion gate
```

---

# 18. 실행 명령 원칙

저장소의 실제 package manager를 먼저 확인한다.

기존 project가 `uv`를 사용하면 우선:

```powershell
uv run python -m pytest ...
uv run python -m ai_fc ...
```

그렇지 않으면 현재 venv의 Python을 사용한다.

새 dependency를 설치하지 않는다.

각 명령은 보고서에 다음과 같이 기록한다.

```text
command
working directory
exit code
stdout summary
stderr summary
classification:
  PASS
  CODE FAILURE
  ENVIRONMENT BLOCKER
  DATA BLOCKER
```

---

# 19. 필수 보고서

각 Batch 보고서 공통 목차:

```text
# 1. Scope
# 2. Input and Source Hashes
# 3. Git/Worktree State
# 4. Current Behavior
# 5. Changes
# 6. Files and Symbols
# 7. Data/Probability Semantics
# 8. Tests and Commands
# 9. Invariants
# 10. Failures and Classification
# 11. Remaining Risks
# 12. Gate Decision
# 13. Git Diff Summary
# 14. Rollback
```

판정:

```text
PASS
PASS WITH WARNING
FAIL
BLOCKED
NOT TESTABLE
```

FAIL 또는 BLOCKED가 하나라도 있으면 다음 Batch 진행 권고를 하지 않는다.

---

# 20. Codex 최종 응답 형식

각 Batch 종료 시 채팅에는 다음만 구조적으로 요약한다.

```text
1. Batch
2. Gate result
3. Read files
4. Changed files
5. Key implementation
6. Tests/commands/results
7. Official snapshot hash before/after
8. Data/ledger/archive impact
9. Known failures/blockers
10. Diff summary
11. Next Batch allowed: YES/NO
```

마지막 줄:

```text
STOPPED AFTER <BATCH_ID>. NO COMMIT/PUSH/PR/MERGE PERFORMED.
```

---

# 21. 절대 완료 조건

진짜 Scenario V4 RCFHS-SB로 부를 수 있는 조건:

```text
- approved PIT history
- observable regime implemented
- state-conditioned drift implemented
- conditional volatility implemented
- empirical standardized residuals
- stationary block bootstrap
- source block lineage
- continuous 252-session path
- adaptive joint simulation
- true scenario conditional quantiles
- actual central representative
- deterministic canonical artifact
- stale source gate
- shadow-only dashboard
- rolling-origin validation complete
```

이 조건을 충족하지 않으면 정확한 상태를 다음 중 하나로 남긴다.

```text
legacy_diagnostic
blocked_missing_data
quant_core_only
shadow_unvalidated
```

그래프가 더 자연스러워 보인다는 이유만으로 완료 또는 champion이라고 판단하지 않는다.
