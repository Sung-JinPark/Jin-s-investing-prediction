# AI Investing Scenario Graph V4 — Codex Master Implementation Prompt

이 문서는 `C:\workspace\ai-investing` 저장소에서 **Scenario Graph V4 Shadow**를 설계·구현·검증하기 위한 Codex GUI 실행 명세다.

권장 모델명:

```text
Continuous-Horizon Regime-Conditioned Filtered Historical Simulation
with Stationary Block Bootstrap
약칭: RCFHS-SB v1
model_family: rcfhs_sb
shadow_model_id: nasdaq_rcfhs_sb_v4_shadow
```

이 모델의 목적은 세 선을 시각적으로 다르게 만드는 것이 아니다. 목적은 다음 세 대상을 분리하고, 각 대상을 통계적으로 정직하게 시각화하는 것이다.

```text
1. 공식 시나리오 가중치 P(S1), P(S2), P(S3)
2. 조건부 경로분포 P(path | S1), P(path | S2), P(path | S3)
3. 해당 조건부 분포 안에 실제로 존재하는 대표 연속경로
```

---

# CODEX에 붙여넣을 실행 명령

당신은 이 저장소의 수석 퀀트 엔지니어, 확률예측 검증 책임자, 데이터 계보 감사자, 백엔드 엔지니어, 대시보드 엔지니어다.

이번 작업은 기존 그래프를 더 울퉁불퉁하게 꾸미는 작업이 아니다. **현재 단일 GBM·공통 역사 residual·연도별 splice·pointwise median 구조를 별도의 Shadow 경로모델로 대체하고, 분포와 대표경로를 정직하게 표시하는 작업**이다.

프로젝트 루트:

```text
C:\workspace\ai-investing
```

작업명:

```text
Scenario Graph V4 Shadow — RCFHS-SB v1
```

최종 원칙:

```text
- 하나의 일관된 joint path generator를 사용한다.
- 각 full path를 기존 S1/S2/S3 정의로 사후 분류한다.
- 2026→2027을 하나의 연속 252거래일 상태과정으로 계산한다.
- 세 시나리오별로 독립적인 조건부 fan을 계산한다.
- 굵은 대표선은 실제 ensemble member 한 개다.
- 날짜별 중앙값을 연결한 합성선은 굵은 대표선으로 사용하지 않는다.
- 시나리오 차이를 만들기 위한 수동 drift/noise/endpoint forcing을 금지한다.
- 조건부 분포가 실제로 겹치면 겹침을 숨기지 않는다.
- V4는 Shadow로만 구현하고 검증 전 official/champion을 변경하지 않는다.
```

---

# 0. 실행 전 안전조치

먼저 다음을 실행하고 결과를 보고서에 기록하라.

```powershell
git status --short
git branch --show-current
git rev-parse HEAD
git worktree list
```

가능하면 별도 Codex worktree와 branch를 사용한다.

```text
worktree: scenario-v4-rcfhs-shadow
branch: codex/scenario-v4-rcfhs-shadow
```

절대 규칙:

1. 기존 uncommitted 변경을 `reset`, `restore`, `checkout`, `stash`, 삭제하지 마라.
2. 기존 L0 Batch 1 또는 `expired dry_run` 수정과 이번 작업을 섞지 마라.
3. 같은 파일에서 충돌이 예상되고 안전한 별도 worktree가 아니면 코드 수정을 시작하지 말고 `BLOCKED_BY_DIRTY_WORKTREE`로 보고하라.
4. 자동 commit, push, PR 생성, main 병합을 하지 마라.
5. 공식 ledger, 공식 archive, 기존 `nasdaq_latest.json`을 수정하지 마라.
6. 외부 네트워크, 실시간 시세 API, 브로커 API, secret/API key를 사용하지 마라.
7. 새 dependency를 설치하거나 `pyproject.toml`에 추가하지 마라. 현재 NumPy·SciPy 범위 안에서 구현하라.

---

# 1. 반드시 먼저 읽을 파일

저장소 루트 안에서 다음 파일을 읽는다. 경로가 다르면 정확한 파일명으로 검색하되 프로젝트 밖은 검색하지 마라.

```text
AGENTS.md
CLAUDE.md
pyproject.toml

src/ai_fc/scenario.py
src/ai_fc/scenario_structure.py
src/ai_fc/quant/mc.py
src/ai_fc/quant/feed.py
src/ai_fc/evaluation.py
src/ai_fc/dashboard.py
src/ai_fc/dashboard_parts/dashboard.js
src/ai_fc/dashboard_parts/dashboard.css
src/ai_fc/cli.py

src/tests/test_scenario.py
src/tests/test_dashboard.py
src/tests/test_dashboard_js_geometry.py

data/contracts/scenario_structural_forecast.yaml
data/scenarios/nasdaq_latest.json

docs/audit/phase1_260806/AI_INVESTING_HANDOFF_PHASE1_AUDIT_260806.md
docs/audit/phase1_260806/AI_INVESTING_DEFECT_REGISTER_260806.csv
docs/audit/phase2_260806/CODEX_INTAKE_REPORT.md
prompts/v2/AI_INVESTING_PROMPT_V2_BLUEPRINT_260806.md
```

감사 파일 경로가 다르면 다음 파일명으로 검색한다.

```text
AI_INVESTING_HANDOFF_PHASE1_AUDIT_260806.md
AI_INVESTING_DEFECT_REGISTER_260806.csv
CODEX_INTAKE_REPORT.md
AI_INVESTING_PROMPT_V2_BLUEPRINT_260806.md
```

읽은 파일과 실제 경로를 `SCENARIO_V4_BASELINE_CHARACTERIZATION.md`에 기록한다.

---

# 2. 기존 그래프 결함을 독립 재검증

감사 문서를 정답으로 가정하지 말고 실제 코드·snapshot·테스트로 확인한다.

## 2.1 공통 residual 복제

확인 대상:

```text
src/ai_fc/scenario_structure.py::_structural_paths
src/ai_fc/scenario_structure.py::_year_residual
```

검증:

1. S1/S2/S3 구조경로의 주간 로그수익률 상관계수
2. 각 경로를 자기 기하 baseline으로 나눈 residual 간 최대 절대차
3. 세 경로의 국소 고점·저점 날짜 일치 여부
4. 동일 `raw` analog shape와 동일 `strength`가 세 경로에 적용되는지
5. 차이가 주로 시작값·종료값의 기울기인지

## 2.2 달력 연도 초기화

확인 대상:

```text
src/ai_fc/scenario_structure.py::_structural_paths
```

검증:

1. `for year in years` 또는 동등한 calendar-year 분할 존재 여부
2. 2026과 2027이 별도 detrend되는지
3. residual이 각 연도 시작·끝에서 다시 정규화되는지
4. 가격 외에 volatility, drawdown, regime, bootstrap state가 연도 경계를 통과하지 않는지

## 2.3 pointwise median 합성경로

확인 대상:

```text
src/ai_fc/scenario.py::_representative
```

검증:

1. 날짜별 `np.median(..., axis=0)` 사용 여부
2. 결과가 실제 하나의 path row인지
3. 대표선의 변동성, 하락 주 수, 방향전환 수가 해당 cohort의 몇 percentile인지

## 2.4 단일 unconditional fan

확인 대상:

```text
src/ai_fc/scenario.py::build_scenario
src/ai_fc/dashboard_parts/dashboard.js
```

검증:

1. fan이 전체 path pool의 분위수인지
2. S1/S2/S3별 p10/p25/p75/p90이 존재하는지
3. dashboard가 하나의 fan을 세 시나리오 분포처럼 보이게 하는지

## 2.5 단일 GBM 사후 분류와 동일 continuation

확인 대상:

```text
src/ai_fc/scenario.py::build_scenario
src/ai_fc/quant/mc.py::gbm_paths
```

검증:

1. 하나의 GBM pool을 생성한 뒤 S1/S2/S3로 분류하는지
2. classification 이후 모든 cohort가 동일 drift·volatility·normal innovation process를 계속 사용하는지
3. 2027 continuation return distribution이 cohort별로 실제로 구분되는지

## 2.6 analog lineage와 순환 calibration

확인 대상:

```text
src/ai_fc/scenario_structure.py
dualdb/dualdb/models/knn_analog.py
data/contracts/scenario_structural_forecast.yaml
```

검증:

1. 실제 neighbor 날짜와 화면 각 점의 직접 lineage 존재 여부
2. neighbor별 forward path가 아니라 era label·고정 phase만 전달되는지
3. 대안 era마다 같은 MDD target으로 재보정한 뒤 강건성을 주장하는지

결과 파일:

```text
docs/audit/phase3_260806/SCENARIO_V4_BASELINE_CHARACTERIZATION.md
```

각 항목 판정:

```text
CONFIRMED
PARTIALLY_CONFIRMED
NOT_CONFIRMED
BLOCKED_BY_MISSING_DATA
BLOCKED_BY_ENVIRONMENT
```

모든 `CONFIRMED`에는 실제 파일 경로, symbol, 실행 명령, 수치를 넣는다.

---

# 3. 채택 모델과 경계

## 3.1 모델 식별자

```text
model_family: rcfhs_sb
full_name: Continuous-Horizon Regime-Conditioned Filtered Historical Simulation with Stationary Block Bootstrap
shadow_model_id: nasdaq_rcfhs_sb_v4_shadow
promotion_state: shadow_only
```

volatility filter 후보는 별도 candidate id를 사용한다.

```text
nasdaq_rcfhs_sb_ewma_v4_shadow
nasdaq_rcfhs_sb_garch11_v4_shadow
```

동일 model id 안에서 GARCH 실패를 조용히 EWMA로 바꾸지 마라. 어떤 filter로 생성했는지 model id와 snapshot에 명확히 남긴다.

## 3.2 Regime과 Scenario를 혼동하지 않는다

```text
Regime:
  단기 수익률·변동성 상태
  STRESS / RECOVERY / EXPANSION / RANGE
  path generator의 조건부 resampling과 drift에 사용

Scenario:
  기존 프로그램의 outcome category
  S1 / S2 / S3
  생성된 full path를 classification date에서 분류하는 데 사용
```

Scenario별로 수동 drift나 수동 shock를 따로 넣지 않는다. 하나의 joint generator에서 path를 만든 뒤 기존 정의로 조건부 cohort를 만든다.

## 3.3 V4가 변경하지 않는 것

이번 작업에서 다음은 변경하지 않는다.

```text
- 기존 공식 S1/S2/S3 확률 83/2/15 또는 공식 snapshot의 현재 값
- 기존 immutable revision과 archive
- 기존 ledger row
- 기존 legacy snapshot replay
- 기존 physical_event probability
- 기존 질문·forecast 파이프라인
```

V4 simulation membership 비율은 별도 진단값이다.

```text
official_weight_fraction
shadow_implied_weight_fraction
```

두 값을 합치거나 서로 대체하지 마라.

## 3.4 V4가 버리는 것

Shadow path arithmetic에서는 다음을 사용하지 않는다.

```text
- 공통 analog residual
- calendar-year splice
- target MDD에 맞춘 strength calibration
- legacy fixed endpoint forcing
- pointwise median thick line
- random noise로 선 모양 차별화
```

legacy endpoint는 비교용 annotation으로 보일 수 있지만 V4 path의 종료값을 강제로 맞추는 입력으로 사용하지 않는다.

---

# 4. 전체 아키텍처

```text
Immutable PIT NASDAQ close history
        ↓
Daily log return + trailing-only features
        ↓
Historical observable regime labels at t
        ↓
State-aligned next-day drift μ(state_t)
        ↓
Conditional-volatility filter
  Candidate A: EWMA
  Candidate B: GARCH(1,1) Gaussian QMLE
        ↓
Standardized empirical residual z_(t+1)
        ↓
Regime-conditioned stationary block bootstrap of z
        ↓
Continuous D+1…D+252 recursion
  no Jan-1 reset
        ↓
Existing S1/S2/S3 classification at preregistered date
        ↓
Conditional ensembles P(path | S1/S2/S3)
        ↓
Per-scenario quantiles + actual-path representative
        ↓
Three small-multiple fan charts
        ↓
Optional separately labelled official-weighted mixture
```

이 구조의 핵심은 다음이다.

1. 과거 실제 shock 분포와 극단값을 empirical residual로 보존한다.
2. 현재·미래 conditional volatility를 recursion으로 전달한다.
3. residual을 block으로 재표본화해 단기 serial dependence를 보존한다.
4. 전체 252거래일을 하나의 path로 생성한다.
5. 시나리오별 분포는 같은 path를 복사한 것이 아니라 각 scenario membership을 만족한 실제 ensemble subset이다.

---

# 5. Point-in-time 입력 데이터 계약

새 contract:

```text
data/contracts/scenario_path_model_v4.yaml
```

최소 구조:

```yaml
version: 2026-08-06.v4-shadow
status: shadow_only
model_family: rcfhs_sb
shadow_model_id: nasdaq_rcfhs_sb_v4_shadow
symbol: "^IXIC"

input:
  frequency: daily_close
  return_type: log_return
  point_in_time_required: true
  available_at_required: true
  target_start_date: 2000-01-03
  minimum_history_sessions: 2520
  preferred_history_sessions: 5000
  warmup_sessions: 252
  future_horizon_sessions: 252
  network_fetch_in_tests: prohibited

regimes:
  states: [STRESS, RECOVERY, EXPANSION, RANGE]
  rule_version: observable-v1
  minimum_aligned_tokens_per_state: 126
  silent_state_pool_fallback: prohibited

volatility:
  candidates: [ewma, garch11_qmle]
  ewma_lambdas: [0.94, 0.97, 0.985]
  garch_persistence_max: 0.995
  silent_filter_fallback: prohibited

bootstrap:
  type: regime_conditioned_stationary_block
  mean_block_lengths: [5, 10, 21]
  geometric_lengths: true
  circular_source: true
  seed_generator: numpy_pcg64

simulation:
  horizon_sessions: 252
  base_paths: 100000
  batch_size: 5000
  max_paths: 300000
  arithmetic_precision: float64
  storage_precision: explicit_and_versioned

quantile_gates:
  representative_and_p50_min_n: 200
  p25_p75_min_n: 500
  p10_p90_min_n: 1000
  p05_p95_min_n: 2000

representative_path:
  selector: actual_path_central_trajectory_v1
  pointwise_median_as_thick_line: prohibited
  smoothing: prohibited
  endpoint_forcing: prohibited

promotion:
  champion_overwrite: prohibited
  rolling_origin_review_required: true
```

실제 input row는 최소 다음 lineage를 가져야 한다.

```text
date
close
available_at
source
source_revision_or_vintage
ingested_at
```

입력 검증:

1. 날짜 strictly increasing
2. close finite positive
3. duplicate date 없음
4. `available_at <= as_of_cutoff`
5. as-of 이후 row 사용 금지
6. 최소 2,520 trading sessions 미만이면 실제 V4 shadow build를 `BLOCKED_BY_INSUFFICIENT_PIT_HISTORY`로 종료
7. fixture 기반 unit test는 계속 구현 가능
8. input canonical bytes 또는 canonical row serialization의 SHA-256, row count, start/end date를 snapshot에 저장
9. 테스트와 backtest는 network를 호출하지 않음
10. live refresh가 이미 존재하더라도 V4 기본 명령은 local immutable input을 읽음

입력이 2023년 이후만 존재한다면 4-state empirical pool을 억지로 만들지 말고 실제 shadow 결과 생성을 차단한다.

---

# 6. 시간 정렬과 누수 방지

반드시 다음 정렬을 사용한다.

```text
state_t:
  close t까지의 정보로 계산

next return:
  r_(t+1) = log(close_(t+1) / close_t)

state-conditioned drift:
  μ(state_t)로 r_(t+1)을 설명

volatility forecast:
  h_(t+1|t)는 t까지 이용 가능한 정보만 사용

standardized residual:
  z_(t+1) = [r_(t+1) - μ(state_t)] / sqrt(h_(t+1|t))
```

금지:

```text
- r_t와 state_t를 같은 종가 변동에 동시 정렬해 미래를 섞는 것
- 전체 표본 percentile로 과거 origin의 regime threshold를 계산하는 것
- 현재 as-of 이후 데이터로 hyperparameter를 선택하는 것
- backtest origin 이후 데이터로 state drift·volatility를 fit하는 것
```

각 aligned token에는 다음을 저장할 수 있어야 한다.

```text
source_state_t
return_date_t_plus_1
source_index_t_plus_1
raw_return_t_plus_1
state_drift_t
forecast_variance_t_plus_1
standardized_residual_t_plus_1
```

---

# 7. Observable regime engine

권장 신규 파일:

```text
src/ai_fc/scenario_regimes.py
```

각 날짜 t의 state는 t까지의 trailing data만 사용한다.

필수 feature:

```text
ret_20  = log(close_t / close_t-20)
ret_60  = log(close_t / close_t-60)
vol_20  = std(daily_log_return last 20) * sqrt(252)
vol_60  = std(daily_log_return last 60) * sqrt(252)
vol_ratio_20_60 = vol_20 / vol_60
drawdown_252 = close_t / max(close[t-251:t]) - 1
dist_200dma = close_t / mean(close[t-199:t]) - 1
rsi_14
```

V1 preregistered rule은 다음으로 구현한다. 이 threshold를 그래프 모양을 보고 조정하지 마라.

```text
STRESS:
  drawdown_252 <= -0.10
  OR (ret_20 <= -0.05 AND vol_ratio_20_60 >= 1.20)
  OR rsi_14 <= 30

RECOVERY:
  not STRESS
  AND at least one STRESS label in prior 63 sessions
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

요구사항:

1. warmup 이전은 `UNAVAILABLE`, 억지 state 부여 금지
2. RSI 계산 방식과 zero-loss 처리 명시
3. feature 계산은 pure deterministic function
4. 각 state의 aligned next-return token 수 저장
5. state별 token 수가 126 미만이면 실제 shadow build 차단
6. state를 자동 병합하거나 global pool로 조용히 fallback하지 않음
7. historical transition matrix는 diagnostics로 계산할 수 있지만 V1 future path에 transition matrix와 bootstrap state를 동시에 적용해 state를 두 번 변경하지 않음
8. regime은 scenario와 별도 개념임을 schema와 UI에 유지

추가 challenger rule을 만들 수는 있지만 V1 official shadow 결과와 섞지 말고 별도 version으로 평가한다.

---

# 8. State-conditioned drift

state t와 next-day return t+1 정렬을 사용한다.

state별 raw drift:

```text
μ_raw_s = 1%·99% winsorized mean of r_(t+1) where state_t = s
```

winsorization은 **drift 추정에만** 적용한다. residual 자체를 clip하거나 tail을 제거하지 마라.

강한 shrinkage:

```text
w_s = n_s / (n_s + prior_strength)
μ_s = w_s * μ_raw_s + (1 - w_s) * μ_global
```

candidate prior strength:

```text
[252, 504]
```

선택은 rolling-origin tuning 구간의 probabilistic score로만 한다.

금지:

```text
- S1에 bullish drift, S3에 bearish drift를 직접 부여
- legacy endpoint에서 drift 역산
- 2027선을 요동치게 하기 위한 drift schedule
- annual target return을 path마다 강제
```

snapshot diagnostics:

```text
state
n_tokens
mu_raw_daily
mu_shrunk_daily
mu_shrunk_annualized_252
shrinkage_weight
prior_strength
```

---

# 9. Conditional-volatility filter 후보

권장 파일:

```text
src/ai_fc/quant/volatility.py
```

공통 protocol을 만든다.

```python
class VolatilityFilter(Protocol):
    def fit(self, innovations: np.ndarray) -> VolatilityFit: ...
    def variance_forecast_for_history(self) -> np.ndarray: ...
    def initial_forecast_variance(self) -> float: ...
    def update(self, *, variance_forecast: float, innovation: float) -> float: ...
```

`innovation`은 `epsilon = return - state_drift`이며 standardized z가 아니다.

## 9.1 EWMA candidate

```text
h_(t+1|t) = λ h_(t|t-1) + (1-λ) ε_t²
```

candidate:

```text
λ ∈ [0.94, 0.97, 0.985]
```

초기 variance, warmup, zero variance 처리, finite gate를 명시한다.

## 9.2 GARCH(1,1) Gaussian QMLE candidate

```text
ε_t = sqrt(h_t) z_t
h_(t+1) = ω + α ε_t² + β h_t
```

제약:

```text
ω > 0
α >= 0
β >= 0
α + β < 0.995
```

요구사항:

1. 기존 NumPy·SciPy만 사용
2. `scipy.optimize.minimize` 가능
3. parameter transform 또는 constrained optimization 사용
4. multi-start가 필요하면 deterministic start set 사용
5. optimizer success, finite objective, finite positive variance, persistence gate 확인
6. fit failure를 숨기지 않음
7. GARCH candidate 실패 시 같은 model id로 EWMA를 대신 생성하지 않음
8. 별도 EWMA candidate 결과를 만들 수 있으나 filter id와 상태를 분리

fit diagnostics:

```text
optimizer_method
success
message
objective
omega
alpha
beta
persistence
n_observations
initial_variance
min_variance
max_variance
```

## 9.3 standardized residual

```text
z_(t+1) = epsilon_(t+1) / sqrt(h_(t+1|t))
```

요구사항:

1. z pool finite
2. residual mean-centering과 unit-variance rescaling을 적용할 경우 transform을 versioned metadata로 기록
3. 기본적으로 z를 winsorize/clip/truncate하지 않음
4. non-finite residual을 조용히 삭제하지 않음
5. state별 z token 수 gate
6. empirical skewness, kurtosis, min/max, percentiles diagnostics

## 9.4 filter 선택

EWMA와 GARCH를 모두 구현했다면 현재 그래프 모양으로 선택하지 않는다.

```text
primary selection objective:
  tuning-period normalized CRPS 또는 WIS

secondary gates:
  interval coverage
  path-level Energy/Variogram score
  volatility/MDD realism
  fit stability across origins
```

선택 결과는 validation·holdout 전에 freeze한다.

---

# 10. Regime-conditioned stationary block bootstrap

권장 파일:

```text
src/ai_fc/quant/stationary_bootstrap.py
```

핵심 데이터는 historical standardized residual `z`와 그 residual의 **source start state**다.

V1 알고리즘:

1. simulation path마다 current simulated regime을 보유한다.
2. 최초 또는 block restart 시 current regime과 동일한 historical `source_state_t`를 가진 residual start index 중 하나를 seeded RNG로 선택한다.
3. geometric distribution으로 block length L을 뽑는다.
4. 선택한 source index부터 standardized residual z를 연속 L개 복사한다.
5. block 내부에서는 residual source index를 순서대로 진행해 empirical serial dependence를 보존한다.
6. 각 generated return 후 simulated price history를 갱신하고 observable regime rule로 current simulated regime을 다시 계산한다.
7. block이 끝나면 그 시점의 simulated regime에 맞는 새로운 historical start index를 선택한다.
8. source 끝에 도달하면 contract의 circular rule을 적용한다.
9. D+252까지 반복한다.

중요한 구분:

```text
historical source state:
  block 시작 residual pool을 고르는 조건

simulated current state:
  생성된 path 자체의 trailing feature로 매일 재계산
```

historical state sequence를 future state라고 그대로 복사하지 마라. source state는 lineage와 start conditioning에만 사용한다.

stationary bootstrap:

```text
P(block ends after each draw) = 1 / mean_block_length
L ~ Geometric(p)
```

candidate mean block length:

```text
[5, 10, 21]
```

요구사항:

1. `numpy.random.Generator(PCG64)`
2. 같은 input/config/seed이면 index sequence 재현
3. path별·batch별 RNG stream을 deterministic hash로 파생
4. 모든 path가 동일 block sequence를 공유하지 않음
5. source index/date/block length/state lineage를 대표경로에 저장 가능
6. source index가 warmup unavailable 구간이나 invalid gap을 통과하지 않도록 eligible contiguous token map 생성
7. block length 1은 iid residual baseline으로 별도 평가 가능하나 기본 후보는 5/10/21
8. fixed block bootstrap와 비교 baseline 유지

금지:

```text
- 매일 독립 normal shock를 뽑고 FHS라고 명명
- raw return을 현재 volatility에 그대로 곱함
- scenario별로 같은 random stream을 재사용
- 세 대표선에 같은 residual index sequence 적용
- residual block 뒤에 hand-drawn adjustment 삽입
```

---

# 11. Continuous 252-session path recursion

권장 신규 파일:

```text
src/ai_fc/scenario_v4.py
```

기존 `scenario.py`, `scenario_structure.py`는 legacy baseline으로 보존한다.

시점 정렬을 다음처럼 고정한다.

```text
At close t:
  price_t
  state_t = observable regime from data through t
  h_next = variance forecast for return t+1
  source residual pointer/block state

Generate t+1:
  z_next = bootstrap residual
  mu_next = mu[state_t]
  epsilon_next = sqrt(h_next) * z_next
  r_next = mu_next + epsilon_next
  price_next = price_t * exp(r_next)

Update:
  h_after = volatility_filter.update(
      variance_forecast=h_next,
      innovation=epsilon_next
  )
  append price_next and r_next to simulated history
  state_next = classify_regime(history through t+1)
  running_high_next = max(running_high_t, price_next)
  drawdown_next = price_next / running_high_next - 1
```

다음 iteration에서는:

```text
price_t = price_next
state_t = state_next
h_next = h_after
```

절대 불변식:

1. horizon은 정확히 252 future trading sessions
2. day 0 anchor 포함 여부를 schema에서 통일
3. 2026-12-31/2027-01 첫 trading day에 special branch 없음
4. price, variance, state, running high, drawdown, block pointer가 연속
5. year view는 동일 path array의 slice일 뿐 재계산이 아님
6. endpoint를 사전 지정하지 않음
7. legacy end value에 맞추지 않음
8. 모든 path는 자기 RNG/block lineage 보유
9. NaN/Inf batch를 조용히 버리지 않음
10. invalid batch는 run failure 또는 explicit quarantine

메모리:

- base 100,000 × 253 path 전체를 무조건 RAM에 여러 사본으로 올리지 마라.
- batch generation과 `numpy.memmap` 또는 동등한 local temporary store를 검토한다.
- 계산은 float64로 하고, 저장 precision을 줄이면 오차와 version을 기록한다.
- quantile과 대표경로 선택에 reservoir sampling을 기본 사용하지 마라.
- temporary path store는 official data가 아니며 정리 정책을 문서화한다.

성능 benchmark:

```text
n_paths
batch_size
wall time
peak memory estimate
temporary file size
```

---

# 12. 기존 Scenario partition 보존

실제 코드에서 classification date와 기준값을 먼저 추출해 contract에 직렬화한다.

현재 코드가 다음 정의를 사용한다면 그대로 유지한다.

```text
S1:
  classification date까지 ATH를 한 번 이상 초과

S2:
  ATH 미돌파
  AND classification-date close > fixed registered reference price

S3:
  나머지
```

실제 코드가 다르면 코드가 기준이며 차이를 보고한다.

불변식:

```text
S1 ∩ S2 = ∅
S1 ∩ S3 = ∅
S2 ∩ S3 = ∅
S1 ∪ S2 ∪ S3 = all valid paths
```

중요:

1. classification date 이후 2027 값으로 2026 scenario를 역분류하지 않음
2. 각 path는 classification 이후에도 동일 price/variance/regime/block state를 계속 사용
3. Jan 1에서 path를 다시 생성하지 않음
4. S1/S2/S3별 generation parameter를 수동 변경하지 않음
5. V4 implied scenario weights는 diagnostic일 뿐 official probability가 아님

V4 implied weight:

```text
count(Si) / total_valid_paths
```

추가 저장:

```text
standard_error = sqrt(p * (1-p) / N)
confidence_interval_method
confidence_interval
```

canonical unit은 `[0,1]` fraction이며 UI 경계에서만 percent로 바꾼다.

---

# 13. Path 수와 Monte Carlo gate

기본 생성:

```text
base_paths = 100000
batch_size = 5000
max_paths = 300000
```

절차:

1. base 100,000 unconditional paths 생성
2. scenario별 count 계산
3. 필요한 conditional band gate가 부족하면 동일 joint generator에서 독립 batch 추가
4. max 300,000까지 반복
5. 특정 scenario를 별도 파라미터로 oversample하지 않음
6. max 이후에도 부족하면 해당 band를 숨기고 `insufficient_conditional_sample`

고정 gate:

```text
n >= 200:
  actual representative + p50 허용

n >= 500:
  p25/p75 허용

n >= 1000:
  p10/p90 허용

n >= 2000:
  p05/p95 허용
```

추가 안정성 진단:

- scenario weight Monte Carlo SE
- terminal p10/p50/p90 bootstrap SE
- selected checkpoints의 quantile bootstrap interval
- 추가 batch 전후 quantile 변화

fixed n gate를 통과해도 Monte Carlo instability가 과도하면 warning을 남긴다. threshold와 계산법을 contract에 명시한다.

금지:

```text
- S2 표본 부족 시 unconditional fan 복사
- sample path 복제
- jitter를 넣어 sample 수 증가
- 임의 weight 보정
- p10/p90이 없는데 UI에서 있는 것처럼 표시
```

---

# 14. 조건부 분위수와 mixture

V4 shadow snapshot은 매일 또는 contract가 정한 frequency로 다음을 저장한다.

```text
unconditional:
  p05 p10 p25 p50 p75 p90 p95

per scenario:
  S1 p05 p10 p25 p50 p75 p90 p95
  S2 p05 p10 p25 p50 p75 p90 p95
  S3 p05 p10 p25 p50 p75 p90 p95
```

sample gate 미충족 quantile은 빈 배열로 위장하지 말고 명시적 availability 상태를 둔다.

quantile 불변식:

```text
p05 <= p10 <= p25 <= p50 <= p75 <= p90 <= p95
```

## 14.1 Official-weighted mixture

조건부 ensemble과 기존 official weight를 조합한 mixture는 선택적으로 계산할 수 있다.

```text
P_mix(path) = Σ official_weight_fraction(Si) × P_v4(path | Si)
```

조건:

1. V4 scenario 정의와 official weight의 scenario 정의가 정확히 동일
2. weight owner와 source snapshot id 저장
3. scenario quantile의 숫자 가중평균으로 mixture quantile을 만들지 않음
4. scenario를 official weight로 먼저 샘플링하고 그 scenario의 actual path를 뽑는 deterministic stratified resampling 또는 동등한 weighted empirical mixture 사용
5. mixture는 `official-weighted shadow mixture`로 명확히 표시
6. V4 implied weight로 만든 unconditional distribution과 구분

정의가 불일치하면 mixture를 `blocked_definition_mismatch`로 설정한다.

---

# 15. Shadow snapshot schema

권장 output:

```text
data/scenarios/shadow/nasdaq_<ASOF>_rcfhs_sb_v4.json
```

기존 `data/scenarios/nasdaq_latest.json`을 수정하지 마라.

최소 구조:

```json
{
  "schema_version": "2026-08-06.v4-shadow",
  "status": "shadow_ok",
  "as_of": "YYYY-MM-DD",
  "promotion_state": "shadow_only",
  "model": {
    "family": "rcfhs_sb",
    "id": "nasdaq_rcfhs_sb_v4_shadow",
    "selected_filter_candidate_id": "...",
    "regime_rule_version": "observable-v1",
    "bootstrap": "regime-conditioned-stationary-block",
    "horizon_sessions": 252,
    "master_seed": 42
  },
  "input": {
    "symbol": "^IXIC",
    "start_date": "...",
    "end_date": "...",
    "row_count": 0,
    "sha256": "...",
    "source": "...",
    "point_in_time_status": "pass"
  },
  "scenario_definition": {
    "version": "...",
    "classification_date": "...",
    "ath_reference": 0.0,
    "reference_price": 0.0
  },
  "dates": ["..."],
  "weights": {
    "S1": {
      "official_weight_fraction": 0.83,
      "shadow_implied_weight_fraction": 0.0,
      "shadow_implied_mc_se": 0.0,
      "official_weight_source_snapshot_id": "..."
    }
  },
  "regime_diagnostics": {},
  "volatility_diagnostics": {},
  "bootstrap_diagnostics": {},
  "unconditional": {
    "sample_count": 0,
    "quantiles": {}
  },
  "scenarios": {
    "S1": {
      "status": "ok_or_insufficient",
      "sample_count": 0,
      "available_quantiles": ["p10", "p25", "p50", "p75", "p90"],
      "quantiles": {},
      "representative_path": {},
      "sample_paths": [],
      "path_metric_distribution": {},
      "regime_occupancy_distribution": {}
    }
  },
  "similarity_diagnostics": {},
  "mixture": {},
  "year_slices": {
    "2026": {"start_index": 0, "end_index": 0},
    "2027": {"start_index": 0, "end_index": 0}
  },
  "lineage": {},
  "validation": {},
  "guardrails": {}
}
```

schema validation:

1. arrays length와 dates 일치
2. positive finite prices
3. quantile monotonicity
4. probability/weight fraction `[0,1]`
5. official와 implied weight 분리
6. representative path hash 재계산 가능
7. representative가 해당 scenario ensemble actual member임을 build-time assertion
8. `year_slices`는 같은 array의 index slice일 뿐 별도 model output이 아님
9. selected filter id와 diagnostics 일치
10. source input hash와 config hash 저장
11. canonical JSON ordering과 deterministic serialization

동일 input/config/seed 재실행 시 canonical output hash가 같아야 한다. 단 `generated_at` 같은 비결정 필드는 canonical hash 대상에서 제외하거나 deterministic metadata policy를 명시한다.

---

# 16. Actual-path representative selector

권장 함수:

```text
select_actual_representative_path()
```

대표선은 반드시 해당 scenario path matrix의 실제 row 하나다.

## 16.1 path metrics

각 path에 최소 다음을 계산한다.

```text
terminal_return
annualized_daily_volatility
annualized_weekly_volatility
maximum_drawdown
max_drawdown_date
recovery_date_or_none
time_under_water_sessions
down_day_fraction
down_week_count
weekly_direction_change_count
largest_1day_loss
largest_5day_loss
weekly_return_autocorrelation_lag1
squared_daily_return_autocorrelation_lag1
squared_daily_return_autocorrelation_lag5
```

## 16.2 candidate gate

기본 candidate path는 다음을 만족해야 한다.

```text
terminal return percentile: 35~65
realized volatility percentile: 10~90
maximum drawdown percentile: 10~90
time under water percentile: 10~90
direction-change percentile: 10~90
```

candidate가 없으면:

1. terminal 범위를 25~75로 한 번만 완화
2. 완화 사실과 이유 기록
3. 그래도 없으면 representative를 숨기고 `representative_selection_failed`
4. 임의 smoothing path를 생성하지 않음

## 16.3 central trajectory score

weekly normalized log-price trajectory를 사용한다.

```text
normalized_log_path_i(t) = log(P_i(t) / P_i(0))
median_trajectory(t) = pointwise median across cohort
```

중앙 궤적과의 거리:

```text
trajectory_distance_i
  = mean(abs(normalized_log_path_i - median_trajectory))
```

추가 metric distance를 IQR로 robust scale한다.

```text
score_i
  = 1.0 * trajectory_distance_i
  + 0.50 * terminal_return_distance_i
  + 0.75 * volatility_distance_i
  + 0.75 * mdd_distance_i
  + 0.50 * time_under_water_distance_i
  + 0.50 * direction_change_distance_i
```

IQR=0인 metric은 제외하고 diagnostics에 남긴다. 가장 낮은 score를 선택하며 tie는 lowest original path id다.

중요:

- pointwise median은 selection target일 뿐 굵은 path 자체가 아님
- selected path values는 원본 row와 exact 또는 명시 tolerance 내 동일
- smoothing 금지
- interpolation으로 path values 변경 금지
- legacy endpoint forcing 금지
- year별 path splice 금지

snapshot metadata:

```text
path_id
original_global_path_index
scenario_local_index
path_hash_sha256
selection_rule_version
selection_score
metric_values
metric_percentiles
terminal_percentile
source_block_lineage
```

## 16.4 optional thin sample paths

사용자 toggle용으로 실제 path 7~9개를 deterministic하게 선택할 수 있다.

예시 terminal strata:

```text
10, 25, 40, 50, 60, 75, 90 percentile
```

각 path는 actual member이며 path id/hash를 가진다. 기본 화면은 숨김 또는 매우 얇은 선으로 표시한다.

---

# 17. 시나리오 분리도와 현실성 진단

목표는 상관을 억지로 낮추는 것이 아니다. 실제 조건부 분포가 얼마나 다른지 진단한다.

## 17.1 representative similarity

```text
pairwise weekly log-return correlation
normalized trajectory distance
turning-point date overlap
path hash equality
source residual index overlap
```

hard fail:

```text
- 동일 path hash
- tolerance 내 동일 return vector
- 한 path가 다른 path의 상수배·상수이동일 뿐임
- 동일 residual index sequence를 세 scenario가 공유
```

warning:

```text
pairwise weekly return correlation > 0.98
```

warning 시 noise를 추가하지 말고 아래 distribution 진단을 함께 본다.

## 17.2 conditional distribution similarity

scenario pair별로 다음을 비교한다.

```text
terminal return Wasserstein distance
maximum drawdown Wasserstein distance
realized volatility Wasserstein distance
time-under-water Wasserstein distance
regime occupancy difference
quantile-band overlap ratio
classification-to-horizon continuation return distribution
```

표준화된 거리와 계산법을 snapshot에 기록한다.

세 분포가 실질적으로 매우 유사하면:

```text
SCENARIO_DYNAMICS_OVERLAP_HIGH
```

상태를 부여한다. UI에는:

```text
“세 시나리오의 후속 동학이 현재 모델에서 명확히 구분되지 않음”
```

을 표시한다.

## 17.3 representative realism gate

대표경로는 자기 cohort에서 다음 percentile 범위에 있어야 한다.

```text
annualized volatility: 5~95
maximum drawdown: 5~95
down-week count: 5~95
direction-change count: 5~95
time-under-water: 5~95
largest 5-day loss: 5~95
```

두 개 이상이 범위를 벗어나면 기본 thick line으로 표시하지 말고 warning 또는 selection failure로 처리한다.

legacy와 비교표:

```text
legacy pointwise median
legacy structural path
V4 p50 trajectory
V4 actual representative
V4 cohort metric distribution
```

보고서:

```text
docs/audit/phase3_260806/SCENARIO_V4_REALISM_REPORT.md
```

---

# 18. Analog와 event 처리

기존 `scenario_structure.py`의 analog shape는 V4 price arithmetic에 사용하지 않는다.

analog 허용 범위:

```text
- 별도 historical reference panel
- D=100 normalized thin dashed line
- source era/neighbor/date/forward offset lineage가 있을 때만 표시
```

lineage가 없으면:

```text
reference_untraceable
```

로 표시하고 기본 숨김한다.

이벤트:

- event date는 vertical marker 또는 evidence annotation
- path generator의 drift, volatility, shock, representative selection을 변경하지 않음
- event array를 추가·삭제해도 V4 path output hash가 동일해야 함
- exact-day market move claim 금지

필수 metamorphic test:

```text
same input/config/seed + different event annotations
→ model path bytes identical
```

---

# 19. Dashboard 설계

모델 core·schema·tests가 통과한 뒤 dashboard를 수정한다.

V4는 explicit feature flag 또는 model selector로만 연다.

```text
legacy_v3
rcfhs_sb_v4_shadow
```

검증 전 legacy default를 유지한다.

## 19.1 primary layout

한 chart에 굵은 선 세 개만 겹치지 말고 S1/S2/S3 **small multiples 3개**를 기본으로 한다.

각 패널:

```text
scenario label
classification rule
공식 weight %
V4 implied weight % — shadow diagnostic
conditional sample count
p10~p90 band
p25~p75 band
p50 dashed line — 시점별 중앙값
actual representative solid line
filter/model id
band availability status
```

p05/p95는 n>=2000이고 stability gate를 통과할 때만 선택적으로 표시한다.

## 19.2 overview

상단 선택형 overview:

```text
D=100 normalized three-scenario comparison
```

동일 Y-domain을 사용하고:

- actual representative 3개
- 매우 옅은 conditional band
- `SCENARIO_DYNAMICS_OVERLAP_HIGH` warning

을 표시한다.

## 19.3 축과 기간 toggle

```text
absolute price / D=100 normalized
shared Y-axis / independent Y-axis
weekly / daily
full 252-session / 2026 slice / 2027 slice
```

기본값:

```text
D=100 + shared Y-axis + weekly + full horizon
```

`2027 slice`는 동일 continuous output의 slice다. 2027을 다시 계산하지 않는다.

실제 horizon이 2027-08-04에 끝나면 `2027 전체`라고 쓰지 말고 실제 날짜 범위를 표시한다.

## 19.4 의미 설명

대표선 tooltip:

```text
이 선은 해당 시나리오 조건을 만족한 모의경로 중 중앙 궤적과 위험지표에 가장 가까운 실제 연속경로 한 개입니다.
가장 가능성 높은 정확한 일별 경로를 의미하지 않습니다.
```

p50 tooltip:

```text
시점별 중앙값을 연결한 통계 요약선이며 실제 한 경로가 아닙니다.
```

fan tooltip:

```text
이 밴드는 P(path | scenario)의 조건부 분위수입니다.
전체 시장 무조건부 분포와 동일하지 않습니다.
```

mixture tooltip:

```text
공식 시나리오 가중치와 V4 조건부 경로분포를 결합한 Shadow 혼합분포입니다.
```

## 19.5 sample 부족

- 없는 band를 그리지 않음
- overall fan을 scenario panel에 대체하지 않음
- `표본 부족 — 조건부 p10~p90 미표시` 명시

## 19.6 접근성과 회귀

- 색상만으로 scenario를 구분하지 않음
- line style·label 병행
- keyboard toggle
- missing/corrupt V4 snapshot은 legacy fallback과 warning
- silent catch 금지
- legacy screen default regression test

---

# 20. Rolling-origin 평가 설계

권장 도구:

```text
tools/backtest_scenario_v4.py
```

또는 명시적인 CLI subcommand.

기존 `src/ai_fc/evaluation.py`의 다음을 우선 재사용·확장한다.

```text
crps_ensemble
pinball_loss
interval_diagnostics
expanding_walk_forward
run_baseline_suite
clustered_bootstrap_mean
```

## 20.1 데이터 분할

PIT daily history가 2000년부터 충분할 때 권장 split:

```text
training/tuning origins:
  first eligible origin ~ 2018-12-31

validation origins:
  2019-01-01 ~ 2022-12-31

holdout origins:
  2023-01-01 ~ latest origin with complete realized horizon
```

정확한 origin은 trading calendar와 minimum history를 반영한다.

- monthly origin
- 각 origin에서 origin까지 데이터만 fit
- 252-session realized outcome이 없는 최신 origin은 shorter horizon만 평가하고 censoring 표시
- holdout은 hyperparameter 선택에 사용하지 않음

## 20.2 비교 baseline

```text
random walk with drift
IID historical simulation
fixed block bootstrap
legacy GBM
RCFHS-SB EWMA candidates
RCFHS-SB GARCH11 candidates
```

legacy structural thick line은 density model이 아니므로 probabilistic score 대상이 아니다. path realism 비교만 한다.

## 20.3 candidate grid

regime rule은 V1에서 고정해 과적합을 줄인다.

```text
EWMA lambda: [0.94, 0.97, 0.985]
mean block length: [5, 10, 21]
drift prior strength: [252, 504]
```

GARCH candidate:

```text
GARCH11 fit
mean block length: [5, 10, 21]
drift prior strength: [252, 504]
```

선택 순서:

1. tuning origins에서 primary score 계산
2. deterministic tie-break
3. config freeze
4. validation 평가
5. 마지막에 holdout 평가

그래프 모양을 보고 config를 변경하지 않는다.

## 20.4 forecast horizon

```text
5, 21, 63, 126, 252 sessions
```

## 20.5 probabilistic score

terminal 또는 cumulative return distribution:

```text
CRPS
WIS
pinball loss
median absolute error
50% interval coverage and width
80% interval coverage and width
```

path vector:

```text
Energy score at cumulative-return checkpoints [5,21,63,126,252]
Variogram score for checkpoint vector or weekly returns
```

ensemble subsample을 사용하면 seed, sample size, rule을 기록한다.

## 20.6 scenario probability 평가 제한

현재 S2가 fixed current reference price를 사용한다면 과거 origin에 그대로 적용하지 마라.

다음이 사전등록되기 전에는 multiclass S1/S2/S3 Brier·log score를 계산하지 않는다.

```text
- historicalized reference-price rule
- origin-relative ATH/reference definition
- 동일 classification horizon
- immutable outcome mapping
```

준비되지 않으면:

```text
SCENARIO_PROBABILITY_SCORE_NOT_EVALUATED_DEFINITION_NOT_HISTORICALIZED
```

로 보고한다.

ATH hit처럼 과거 origin에서도 동일하게 정의 가능한 binary event는 별도 preregistered evaluation으로 계산할 수 있다.

## 20.7 primary selection과 promotion gate

primary tuning objective:

```text
mean normalized CRPS across horizons
```

secondary:

```text
WIS
coverage error
Energy/Variogram score
fit stability
```

realism metric은 graph appearance 최적화 점수가 아니라 rejection gate다.

Shadow candidate 권고 조건 예시:

1. PIT violation 0
2. deterministic replay pass
3. no calendar reset
4. representative actual-member pass
5. conditional sample gate pass
6. holdout CRPS가 GBM보다 통계적으로 비열등하고 주요 horizon 2개 이상에서 개선
7. 어떤 핵심 horizon에서도 사전등록된 허용치보다 크게 악화되지 않음
8. 50%/80% coverage가 legacy보다 nominal에 같거나 가까움
9. Energy/Variogram score가 trajectory dependence에서 비열등
10. GARCH 사용 시 origin별 fit failure rate 허용 범위 이내
11. dashboard semantics audit pass

score difference confidence interval은 origin 단위 block/bootstrap으로 계산한다. 표본이 부족하면 champion 승격을 권고하지 않는다.

이번 Codex 작업의 최종 champion recommendation은 반드시:

```text
NO
또는
NOT YET — SHADOW VALIDATION REQUIRED
```

이다.

---

# 21. 권장 구현 파일

신규:

```text
data/contracts/scenario_path_model_v4.yaml
src/ai_fc/scenario_regimes.py
src/ai_fc/quant/volatility.py
src/ai_fc/quant/stationary_bootstrap.py
src/ai_fc/scenario_v4.py
tools/build_scenario_v4_shadow.py
tools/backtest_scenario_v4.py

src/tests/test_scenario_v4_characterization.py
src/tests/test_scenario_v4_regimes.py
src/tests/test_scenario_v4_volatility.py
src/tests/test_scenario_v4_bootstrap.py
src/tests/test_scenario_v4_paths.py
src/tests/test_scenario_v4_schema.py
src/tests/test_scenario_v4_dashboard.py
src/tests/test_scenario_v4_backtest.py
```

최소 수정 가능:

```text
src/ai_fc/cli.py
src/ai_fc/dashboard.py
src/ai_fc/dashboard_parts/dashboard.js
src/ai_fc/dashboard_parts/dashboard.css
src/ai_fc/evaluation.py
```

원칙적으로 보존:

```text
src/ai_fc/scenario.py
src/ai_fc/scenario_structure.py
data/contracts/scenario_structural_forecast.yaml
data/scenarios/nasdaq_latest.json
```

공통 helper 추출을 위한 최소 수정은 가능하지만 legacy output hash와 replay가 달라지면 안 된다.

---

# 22. 작업 Batch와 stage gate

한 번에 전부 수정하지 말고 다음 순서로 진행한다.

## Batch A — Baseline characterization

작업:

- 기존 결함 수치 재현
- legacy targeted tests 실행
- 기존 snapshot/replay hash 기록
- V4 design document 작성
- contract 작성
- characterization tests 추가

산출:

```text
SCENARIO_V4_BASELINE_CHARACTERIZATION.md
SCENARIO_V4_MODEL_DESIGN.md
scenario_path_model_v4.yaml
```

Gate:

```text
- legacy baseline 결과 기록
- official 파일 변경 0
- 기존 결함 메커니즘 확인
```

## Batch B — Quant core

작업:

- regime engine
- state-aligned drift
- EWMA
- GARCH candidate
- standardized residual builder
- regime-conditioned stationary bootstrap

Gate:

```text
- deterministic tests
- PIT alignment tests
- filter constraint/fit tests
- no silent fallback
- no new dependency
```

## Batch C — Continuous path + conditional distributions

작업:

- 252-session generator
- scenario partition
- adaptive unconditional batching
- per-scenario quantiles
- representative selector
- schema/persistence
- reproduction tool

Gate:

```text
- no Jan-1 reset
- actual-member representative
- partition exhaustive/disjoint
- sample gates
- official/implied weights separated
- legacy snapshot unchanged
```

## Batch D — Dashboard Shadow mode

작업:

- three small multiples
- D=100/absolute
- shared/local scale
- weekly/daily
- year slice toggle
- mixture separate
- semantic labels

Gate:

```text
- legacy default preserved
- V4 explicit toggle only
- no fake fan
- true date range
- accessibility tests
```

## Batch E — Rolling-origin evaluation

작업:

- baseline extension
- candidate grid
- tuning/validation/holdout
- proper scores
- realism report
- recommendation

Gate:

```text
- no holdout tuning
- no invalid historical S1/S2/S3 scoring
- no visual-only promotion
- missing PIT history honestly blocked
```

각 batch 후 targeted tests를 실행한다. 다음 batch가 실패한 gate에 의존하면 진행하지 않는다. 독립적인 문서·fixture 작업은 가능하다.

---

# 23. 필수 acceptance tests

## 23.1 Legacy immutability

1. 기존 `nasdaq_latest.json` SHA-256 불변
2. legacy replay 결과 불변
3. legacy S1/S2/S3 probability 불변
4. legacy archive/ledger diff 없음

## 23.2 Determinism

1. same input/config/seed → canonical V4 hash 동일
2. same seed → source residual index lineage 동일
3. different seed → ensemble 다름
4. deterministic tie-break
5. representative hash 재현

## 23.3 PIT

1. as-of 이후 poison row가 output에 영향 0
2. `available_at > cutoff` row 거부
3. state threshold·drift·volatility fit에 future row 없음
4. backtest origin 이후 값 변경이 origin output에 영향 0

## 23.4 Regime

1. synthetic STRESS fixture
2. synthetic RECOVERY fixture
3. synthetic EXPANSION fixture
4. synthetic RANGE fixture
5. warmup UNAVAILABLE
6. state t / return t+1 alignment
7. state token minimum gate

## 23.5 Volatility

1. EWMA finite positive
2. GARCH constraints
3. GARCH success fixture
4. GARCH failure explicit
5. no same-id silent EWMA fallback
6. z residual finite
7. no default clipping

## 23.6 Bootstrap

1. geometric block length behavior
2. long-run mean block length near target
3. restart start index matches current simulated state
4. contiguous source residual sequence inside block
5. circular source handling
6. path별 block sequence 차이
7. representative block lineage valid

## 23.7 Continuous path

1. 252 future sessions
2. no Jan-1 branch
3. price/variance/state continuous
4. year slice equals original array slice
5. running high/drawdown continuous
6. finite positive price
7. no endpoint forcing

## 23.8 Scenario partition

1. exhaustive
2. mutually exclusive
3. classification 이후 data 미사용
4. continuation은 같은 path state 유지
5. implied weights fraction `[0,1]`
6. MC SE correct

## 23.9 Conditional fan

1. scenario별 p10/p25/p50/p75/p90
2. p05/p95 sample gate
3. quantile monotonicity
4. unconditional fan과 scenario fan이 같은 object/data가 아님
5. sample 부족 시 숨김
6. mixture quantile이 quantile weighted average가 아님

## 23.10 Representative

1. actual ensemble row
2. correct scenario membership
3. path id/hash values 일치
4. metric percentile gate
5. no smoothing
6. no splice
7. weekly sample은 daily path에서 정확히 추출
8. pointwise p50과 representative 구분

## 23.11 Common-template regression

Hard fail:

```text
- S1/S2/S3 representative hashes 동일
- normalized return vectors tolerance 내 동일
- constant scaling/translation만으로 동일
- source residual sequence 완전 동일
```

Warning only:

```text
correlation > 0.98
```

warning은 noise로 해결하지 않고 distribution overlap disclosure로 처리한다.

## 23.12 Analog/event separation

1. analog on/off → V4 path hash 동일
2. event marker on/off → V4 path hash 동일
3. legacy structural module이 V4 core에서 호출되지 않음

## 23.13 UI

1. small multiples
2. scenario conditional fan labels
3. actual representative/p50 line style 구분
4. full/2026/2027은 동일 output slice
5. actual date range
6. sample 부족 문구
7. overlap warning
8. legacy fallback warning
9. color-only 구분 금지

## 23.14 Backtest

1. rolling/expanding origin
2. no future data
3. holdout untouched until final
4. CRPS/WIS implementation 검증
5. Energy/Variogram deterministic
6. invalid historical multiclass definition 시 score 차단
7. baseline comparison

---

# 24. 금지사항

```text
- official nasdaq_latest.json overwrite
- official archive/ledger 수정
- official 83/2/15 또는 현재 official weights 변경
- legacy snapshot replay drift
- 새 dependency 설치
- 인터넷 기반 테스트
- live broker/order API
- secret 접근
- scenario별 수동 bullish/bearish drift
- common residual template
- fixed correction dates
- hand-drawn 2027 dip/rebound
- endpoint forcing
- MDD target calibration
- calendar-year path splice
- pointwise median thick line
- smoothing/jitter로 현실성 위장
- correlation을 낮추기 위한 noise
- sample 부족 은폐
- probability unit 자동 추론
- invalid output silent clipping
- GARCH 실패 silent EWMA fallback
- scenario quantile의 가중평균을 mixture quantile로 사용
- holdout 기반 hyperparameter 변경
- 테스트 assertion 약화 또는 삭제
- 무관한 L0 리팩터링
- 대규모 포맷팅
```

---

# 25. 필수 보고서

디렉터리:

```text
docs/audit/phase3_260806/
```

파일:

```text
SCENARIO_V4_BASELINE_CHARACTERIZATION.md
SCENARIO_V4_MODEL_DESIGN.md
SCENARIO_V4_IMPLEMENTATION_REPORT.md
SCENARIO_V4_REALISM_REPORT.md
SCENARIO_V4_BACKTEST_REPORT.md
SCENARIO_V4_UI_AUDIT.md
SCENARIO_V4_DIFF_AND_ROLLBACK.md
```

## 25.1 MODEL_DESIGN 목차

```text
# 1. Problem Definition
# 2. Legacy Failure Mechanisms
# 3. Regime vs Scenario
# 4. Probability Weight vs Conditional Path Distribution
# 5. PIT Input Contract
# 6. Time Alignment
# 7. Observable Regime Rules
# 8. State-Conditioned Drift
# 9. Volatility Filter Candidates
# 10. Standardized Residuals
# 11. Stationary Block Bootstrap
# 12. Continuous Path Recursion
# 13. Scenario Partition
# 14. Monte Carlo Sample Gates
# 15. Conditional Quantiles and Mixture
# 16. Actual Representative Selection
# 17. Similarity and Realism Diagnostics
# 18. Dashboard Semantics
# 19. Rolling-Origin Evaluation
# 20. Risks, Assumptions, Non-Goals
# 21. Promotion Gates
```

## 25.2 IMPLEMENTATION_REPORT 필수 항목

```text
worktree/branch/base commit
변경 파일
변경 symbol
input lineage
config hash
seed lineage
PIT controls
regime counts
filter candidates/selected filter
bootstrap config
memory/performance
scenario counts
quantile availability
representative path verification
legacy compatibility
targeted tests
full tests
blockers
```

## 25.3 REALISM_REPORT 필수 표

```text
metric | legacy pointwise median | legacy structural | V4 S1 rep | V4 S2 rep | V4 S3 rep | cohort percentile
```

metrics:

```text
annualized weekly vol
MDD
down weeks
direction changes
time under water
largest 5-day loss
```

## 25.4 DIFF_AND_ROLLBACK

```text
legacy files unchanged
new files
modified dashboard files
feature flag off procedure
shadow snapshot disable/delete procedure
temporary store cleanup
rollback commands without touching unrelated changes
official ledger/archive immutability
```

---

# 26. 실행 명령

실제 저장소의 uv/venv 방식을 먼저 확인한다. 아래는 예시다.

```powershell
python -m pytest src/tests/test_scenario.py -q
python -m pytest src/tests/test_scenario_v4_characterization.py -q
python -m pytest src/tests/test_scenario_v4_regimes.py -q
python -m pytest src/tests/test_scenario_v4_volatility.py -q
python -m pytest src/tests/test_scenario_v4_bootstrap.py -q
python -m pytest src/tests/test_scenario_v4_paths.py -q
python -m pytest src/tests/test_scenario_v4_schema.py -q
python -m pytest src/tests/test_scenario_v4_dashboard.py -q
python -m pytest src/tests/test_scenario_v4_backtest.py -q
python -m pytest src/tests -q
python -m pytest -q
```

legacy replay:

```powershell
python tools/reproduce_scenario_snapshot.py
```

V4 build 예시:

```powershell
python tools/build_scenario_v4_shadow.py `
  --as-of 2026-08-03 `
  --input <LOCAL_IMMUTABLE_PIT_FILE> `
  --output data/scenarios/shadow/nasdaq_2026-08-03_rcfhs_sb_v4.json
```

backtest 예시:

```powershell
python tools/backtest_scenario_v4.py `
  --input <LOCAL_IMMUTABLE_PIT_FILE> `
  --output-dir docs/audit/phase3_260806/backtest_outputs
```

실제 CLI가 다르면 `--help`와 exact command를 보고서에 기록한다.

테스트 실패 분류:

```text
CODE_DEFECT
ENVIRONMENT_OR_DEPENDENCY
MISSING_DATA_OR_ARTIFACT
LEGACY_PREEXISTING_FAILURE
EXPECTED_CHARACTERIZATION
BLOCKED_BY_DIRTY_WORKTREE
```

---

# 27. 완료 판정

다음이 모두 충족되어야 한다.

```text
SHADOW_IMPLEMENTATION_COMPLETE
```

조건:

1. official snapshot/ledger/archive 변경 0
2. legacy replay 불변
3. V4 separate shadow output
4. PIT alignment tests pass
5. regime pool gates pass 또는 실제 data 부족 명시
6. continuous 252-session path
7. Jan-1 reset 없음
8. scenario partition invariant
9. scenario별 conditional fan
10. actual-member representative
11. no common residual copy
12. no endpoint forcing
13. sample gates
14. official/implied weight 분리
15. overlap warning
16. dashboard semantics pass
17. backtest harness 존재
18. 성능 수치가 없으면 허위로 생성하지 않음
19. champion 승격하지 않음

다음은 완료가 아니다.

```text
- 선이 더 울퉁불퉁해짐
- 세 선이 눈으로 달라 보임
- 기존 테스트만 통과
- mock JSON만 생성
- dashboard만 수정
- in-sample fit만 개선
```

최종 상태는 다음 중 하나다.

```text
SHADOW_IMPLEMENTATION_COMPLETE
PARTIAL — CODE BLOCKER
PARTIAL — MISSING PIT DATA
BLOCKED — DIRTY WORKTREE
BLOCKED — ENVIRONMENT
```

---

# 28. Codex 최종 응답 형식

최종 채팅 응답에는 다음을 정확히 제공한다.

```text
1. Worktree / branch / base commit
2. 읽은 핵심 파일
3. 기존 결함 재검증 결과
4. 구현한 RCFHS-SB 구조
5. 생성·수정 파일
6. Batch A~E 상태
7. 입력 PIT 데이터 상태와 hash
8. regime token counts
9. EWMA/GARCH 후보 상태와 선택 결과
10. path 수와 scenario counts
11. scenario별 available quantiles
12. representative actual-member 검증
13. similarity/overlap 진단
14. 실행한 테스트와 pass/fail/skip
15. legacy snapshot/replay 불변 여부
16. shadow snapshot 경로와 hash
17. backtest 결과 또는 blocker
18. 미해결 위험
19. Champion 승격 권고: 반드시 NO 또는 NOT YET
20. git diff 요약
```

계획서만 작성하고 멈추지 마라. 안전 gate를 지키면서 구현 가능한 Batch를 실제로 구현하고 테스트하라. 다만 PIT history가 없으면 실제 성능 수치나 실제 shadow forecast를 꾸며내지 말고 fixture 기반 코드·테스트·문서까지만 완료한 뒤 blocker를 명시한다.

---

# 구현 완료 후 독립 검증용 프롬프트

다른 Codex 새 채팅에서 다음을 실행한다.

```text
이번 작업은 Scenario Graph V4 Shadow — RCFHS-SB v1의 독립 검증이다.
코드를 수정하지 마라.

먼저 AGENTS.md와 다음 문서를 읽어라.

- docs/audit/phase3_260806/SCENARIO_V4_BASELINE_CHARACTERIZATION.md
- docs/audit/phase3_260806/SCENARIO_V4_MODEL_DESIGN.md
- docs/audit/phase3_260806/SCENARIO_V4_IMPLEMENTATION_REPORT.md
- docs/audit/phase3_260806/SCENARIO_V4_REALISM_REPORT.md
- docs/audit/phase3_260806/SCENARIO_V4_BACKTEST_REPORT.md
- docs/audit/phase3_260806/SCENARIO_V4_UI_AUDIT.md
- docs/audit/phase3_260806/SCENARIO_V4_DIFF_AND_ROLLBACK.md
- data/contracts/scenario_path_model_v4.yaml

현재 git diff와 실제 source/test를 독립적으로 검토한다.

검증 항목:

1. official snapshot·ledger·archive 불변
2. legacy replay 불변
3. state_t와 return_t+1 정렬
4. PIT cutoff 이후 데이터 미사용
5. regime과 scenario 구분
6. scenario별 수동 drift/noise 없음
7. standardized empirical residual 사용
8. volatility recursion 정렬
9. GARCH/EWMA id 및 failure 분리
10. stationary block이 geometric length와 contiguous residual을 사용
11. block restart가 simulated current regime에 조건화
12. 모든 path가 동일 residual sequence를 공유하지 않음
13. 2026→2027 calendar reset 없음
14. classification date 이후 값으로 scenario 역분류하지 않음
15. conditional fan이 실제 scenario member로 계산
16. sample gate 실패 시 fan 숨김
17. mixture가 quantile 가중평균이 아님
18. representative가 actual ensemble member
19. representative에 smoothing·endpoint forcing 없음
20. p50과 representative 의미 분리
21. analog/event가 path arithmetic에 영향 없음
22. overlap을 noise로 숨기지 않음
23. dashboard의 실제 date range와 year slice
24. backtest rolling-origin/PIT
25. holdout tuning 없음
26. historicalized 정의 없이 multiclass scenario score를 계산하지 않음
27. 새 dependency 또는 무관한 L0 수정 없음

각 항목 판정:

- PASS
- PASS WITH WARNING
- FAIL
- NOT TESTABLE
- BLOCKED BY MISSING DATA
- BLOCKED BY ENVIRONMENT

다음 중 하나라도 있으면 승격을 권고하지 마라.

- PIT violation
- official mutation
- common residual copy
- calendar-year reset
- representative not actual member
- endpoint forcing
- silent filter fallback
- fake conditional fan
- sample insufficiency concealment
- invalid mixture
- holdout leakage
- score defect
- legacy replay drift

직접 targeted tests와 가능한 full tests를 실행한다.

최종 응답:

1. 판정표
2. 문제 파일과 symbol
3. 재현 명령
4. 테스트 결과
5. legacy 불변성
6. model/data/UI 위험
7. Champion 승격 권고: YES/NO/NOT TESTABLE
8. 최소 수정 범위

코드는 수정하지 마라.
```
