# AI Investing Scenario V5.1 Final Hardening + V6 Stateful Challenger
## Single Unified Codex Master Prompt

당신은 이 저장소의 수석 퀀트 엔지니어, 데이터 아키텍트, 모델 리스크 검증자, 확률예측 감사자, 프론트엔드 시각화 엔지니어다.

프로젝트 루트는 현재 Codex workspace root다. 외부에 별도 프롬프트나 Batch 문서를 요구하지 마라. 이 문서 하나가 이번 작업의 최상위 명세다.

---

## 0. 최종 목표

현재 Scenario V5의 다음 장점은 보존한다.

- official snapshot 불변
- append-only archive/receipt
- physical probability와 risk-neutral probability 분리
- scenario별 conditional distribution
- actual ensemble member lineage
- deterministic replay
- research candidate / not official / not champion governance

그러나 다음 결함을 수정한다.

1. 10월 2일 같은 actual-member sample date가 시장의 exact-date forecast처럼 보이는 문제
2. 3개 scenario가 2027년에 동일 GBM continuation을 가져 구조적으로 같은 전망이 되는 문제
3. 과거 forecast target을 horizon 시작 후에도 재예측·조건화 없이 그대로 사용하는 문제
4. V4/scenario-derived forecast를 V5 path weights에 다시 넣는 self-conditioning 문제
5. dependency cluster strength cap이 계약에만 있고 entropy engine에 적용되지 않는 문제
6. current official snapshot SHA를 확인하지 않는 runtime stale candidate 문제
7. 승인 report/liquidity/cross-asset/AI state가 실제 numerical input이 아닌데 반영된 것처럼 보일 수 있는 문제
8. weak runtime artifact validation
9. p50가 아닌 actual member가 기본 굵은 선인 문제
10. rolling-origin 검증 없이 최종 시장 전망으로 오해될 수 있는 문제

이번 작업은 두 층으로 나눈다.

```text
V5.1 = 현재 legacy-GBM research candidate의 정합성·정직성·표시 보강
V6   = 승인 PIT history가 존재할 때만 만드는 stateful challenger skeleton/implementation
```

승인 PIT 데이터가 부족하면 V6 결과를 만들어내지 말고 명시적으로 BLOCKED 처리하라. 임의 데이터, 합성 보고서, 가짜 calibration, 가짜 OOS score를 만들지 마라.

---

## 1. 절대 금지

- `data/scenarios/nasdaq_latest.json` 수정
- official probabilities 수정
- 기존 ledger row update/delete
- archive 삭제 또는 덮어쓰기
- 기존 forecast 원문 수정
- future data 사용
- `available_at` 이후 정보 사용
- 옵션 risk-neutral probability를 calibration 없이 physical probability로 변환
- LLM이 report prose에서 숫자를 임의 생성하여 numerical view로 사용
- S1/S2/S3를 시각적으로 벌리기 위한 random noise 추가
- fixed dip date, fixed rebound date, endpoint forcing, target-MDD forcing
- common residual template 재도입
- representative path ID 하드코딩
- exact trough date를 모델 forecast로 주장
- automatic commit, push, PR, merge
- unrelated 변경 reset/restore/checkout/clean/stash/delete
- rolling-origin 검증 없이 official/champion 승격

---

## 2. 시작 전 안전 검사

먼저 다음을 실행·기록한다.

```text
git rev-parse --show-toplevel
git branch --show-current
git rev-parse HEAD
git status --short
git diff --stat
git diff --cached --stat
```

현재 unrelated application change가 있으면 수정하지 말고 분류한다.

```text
scenario-v5 existing change
이번 작업 문서
unrelated change
unknown
```

기존 변경을 자동으로 되돌리지 마라.

다음 protected root의 시작 SHA manifest를 만든다.

```text
data/scenarios/nasdaq_latest.json
data/scenarios/archive
forecasts
calibration
questions/registry.yaml
data/ml_history
data/signals
data/liquidity
data/cross_asset
data/ai_capital_cycle
```

작업 종료 시 동일 manifest와 비교한다.

---

## 3. 현재 기준선 독립 재현

현재 candidate를 문서의 주장으로 믿지 말고 코드로 재현한다.

필수 기준값:

```text
candidate_id:
scenario_v5_evidence_conditioned_legacy_prior_v1

candidate canonical SHA:
02c4e4abd3b23e2499dc379755b83b274e57cc565c23cef54c0548f20d9a9933

source snapshot SHA:
d8754e6a7d1eed4aa46c17625b7ba1e7b1554a4e9799404128d64e3277be75bc

asof:
2026-08-06

prior:
40,000 paths
252 sessions
seed 42
mu daily 0.000916130518
sigma daily 0.011646537687

numerical views:
3

posterior ESS:
21454.9969 approximately

posterior scenario probability:
S1 0.6723102819
S2 0.0414824222
S3 0.2862072959

representative IDs:
S1 39026
S2 33828
S3 4550
```

반드시 재검증할 것:

- source 20,000-path prefix exact reproduction
- extended 40,000 paths deterministic reproduction
- EvidenceView condition matrix shape `(40000,3)`
- binary combination count가 최대 8인지
- entropy weights가 동일 binary combination 안에서 동일한지
- S1/S2/S3 partition exhaustive/mutually exclusive
- candidate bands and representative rows replay
- protected inputs unchanged

기준값이 다르면 원인을 조사하고 `BASELINE_DIVERGENCE`로 보고한다. 억지로 기대값에 맞추지 마라.

---

## 4. 10월 2일 원인 characterization

다음 결과를 test와 report로 고정한다.

### 4.1 Correction view의 의미

현재 numerical correction view는 다음 event 하나다.

```text
P(min close between 2026-08-01 and 2026-10-31 <= 24,384.51) = 0.57
```

이 view가 exact first-touch date 또는 trough date를 규정하지 않는다는 점을 코드 계약으로 명시한다.

### 4.2 Current path dates

현재 actual representative의 일간 저점:

```text
S1: 2026-10-01
S2: 2026-09-14
S3: full 2026-12-03, Aug-Oct minimum 2026-10-08
```

Dashboard의 5-session sampling에서 index 40이 2026-10-02라는 점을 test로 확인한다.

### 4.3 Correction timing distribution

posterior weighted first-touch distribution을 별도 산출물로 계산한다.

필수 필드:

```text
window_start
window_end
threshold
probability_of_any_touch
cumulative_touch_probability_by_date
first_touch_probability_by_date
conditional_first_touch_cdf_given_touch
weighted_median_first_touch_date
weighted_p25_first_touch_date
weighted_p75_first_touch_date
exact_date_forecast = false
```

현재 baseline에서 확인할 값:

```text
cumulative by 2026-08-31 ≈ 0.1307
cumulative by 2026-09-15 ≈ 0.2625
cumulative by 2026-09-29 ≈ 0.3660
cumulative by 2026-10-02 ≈ 0.3912
cumulative by 2026-10-15 ≈ 0.4532
cumulative by 2026-10-30 ≈ 0.5068
weighted median first touch conditional on an Aug-Oct touch ≈ 2026-09-15
```

10월 2일을 특별한 event date나 model low date로 직렬화하지 마라.

---

## 5. Phase A — Runtime integrity hardening

### A1. Dashboard candidate loader

현재 `load_candidate()`의 generated-age 검사만으로 default candidate를 허용하지 마라.

새 함수 예:

```python
load_current_candidate(root, now, maximum_age_trading_days=1)
```

필수 gate:

```text
candidate validation PASS
current data/scenarios/nasdaq_latest.json SHA == candidate.source_snapshot.sha256
current official asof == candidate.asof
current official snapshot_id/revision == candidate source receipt
candidate age <= 1 trading day
all numerical EvidenceView source files exist
all numerical EvidenceView source SHA match
all numerical available_at <= knowledge_cutoff
candidate build is not future-dated
```

하나라도 실패하면 V5를 기본 그래프로 사용하지 않는다. 조용히 오래된 V5를 보여주지 말고 명시적 unavailable/stale banner를 표시한다.

### A2. Canonical hash 분리

다음을 분리한다.

```text
model_content_sha256
- model input, contract, evidence records, path outputs만 포함

build_receipt_sha256
- git head, branch, dirty state, generated_at, environment 포함
```

같은 model input은 branch/dirty state가 달라도 같은 model-content hash를 가져야 한다. build receipt는 별도다.

### A3. Strict artifact validator

다음을 모두 검증한다.

- 모든 numeric 값은 bool이 아닌 finite int/float
- 가격과 quantile은 positive
- dates strictly increasing, unique, ISO date
- 모든 bands 길이 == dates 길이
- pointwise `p05 <= p10 <= p25 <= p50 <= p75 <= p90 <= p95`
- path_count 합 == prior path_count
- scenario probability 합 == 1
- scenario probability와 posterior weight mass 일치
- band visibility와 weighted ESS gate 일치
- representative ID 범위 유효
- 대표선이 재생성 matrix의 해당 row와 byte/rounded tolerance 내 일치
- posterior view residual이 tolerance 안에 있는지
- event jump는 approved mapping receipt 없으면 0
- probability-space 이름 정확성
- source hashes 재검증
- PIT available_at 재검증

mutation test를 추가해 각 손상 payload가 거부되는지 확인한다.

---

## 6. Phase B — Evidence time alignment와 circularity 차단

### B1. 하드코딩 horizon 제거

`horizon_start = 2026-08-04` 하드코딩을 제거한다.

각 view는 question registry와 forecast snapshot에서 다음을 가져와야 한다.

```text
original_forecast_asof
original_horizon_start
original_horizon_end
candidate_asof
realized_segment_start
realized_segment_end
realized_event_status
remaining_horizon_start
remaining_horizon_end
```

### B2. Started-window view transport

Candidate as-of가 event window 시작 이후라면 원래 unconditional target을 그대로 쓰지 마라.

가능한 status:

```text
CURRENT_REFORECAST
SURVIVAL_CONDITIONED
REALIZED_TRUE
REALIZED_FALSE
BLOCKED_NEEDS_REFORECAST
REFERENCE_ONLY_STALE
```

Correction view 예:

```text
Original:
P(touch during Aug1-Oct31 | information on Jul20) = 0.57

Candidate asof Aug6 and no touch through Aug6:
Need P(touch during Aug7-Oct31 | no touch through Aug6, information through Aug6)
```

이 값을 정당하게 계산할 transport model이나 새 forecast가 없으면 numerical use를 차단한다. freshness decay만으로 대체하지 않는다.

ATH-touch view도 forecast 작성 후 candidate as-of까지 ATH 미돌파가 관측되었다면 동일 원칙을 적용한다.

### B3. State drift gate

Forecast 작성 당시와 candidate as-of 사이에 다음 상태가 크게 변했으면 stale로 차단하거나 reforecast를 요구한다.

```text
spot-to-barrier distance
realized volatility
remaining sessions
drawdown
moving-average distance
regime
```

Correction baseline:

```text
forecast current 25,520.24; threshold distance -4.45%
candidate anchor 26,348.35; threshold distance approximately -7.45%
```

이 차이가 있어도 57%를 그대로 쓰는 현재 동작은 제거한다.

### B4. Self-conditioning blocker

EvidenceView schema에 다음 필드를 추가한다.

```text
derived_from_model_ids
derived_from_candidate_ids
derived_from_report_ids
derived_from_scenario_weights
source_model_family
source_prompt_version
is_endogenous_to_current_model
endogeneity_reason
```

현재 candidate의 prior/model/ancestor에서 파생된 view는 price-path numerical input으로 사용하지 않는다.

특히 다음 baseline을 검사한다.

```text
nasdaq-ath-eoy-2026 62%: method v4-report-derived
nasdaq-eoy-above-jul9-2026 63%: v4 path weights에서 산출
```

해당 view가 current V5의 직접 조상 모델에서 파생되었다면 기본 정책은 `REFERENCE_ONLY_ENDOGENOUS`다.

### B5. Dependency cluster cap 구현

계약의 `dependency_cluster_id`와 strength cap을 실제 solver input에 적용한다.

요구사항:

- question별 cluster만으로 충분하지 않다.
- source model, source report, common evidence set, release ID를 반영한다.
- cluster별 effective strength 합 상한
- 동일 report 재인용 dedup
- leave-one-view-out
- leave-one-cluster-out
- view correlation matrix
- effective independent view count

Posterior report에 각 view/cluster의 marginal influence를 출력한다.

---

## 7. Phase C — Evidence registry 완성

### C1. 승인 report view 계약

`data/scenario_views/approved/*.json`은 다음 strict schema를 통과해야 한다.

```text
view_id
origin_type
publisher
report_id
title
published_at
available_at
retrieved_at
source_path
source_sha256
content_sha256
target_asset
horizon_start
horizon_end
view_kind
condition
unit
probability_space
target or distribution parameters
confidence/tolerance
assumptions
risk_factors
source_model
human_approval_receipt
dependency_cluster_id
duplicate_cluster_id
historical_reliability_status
used_numerically
```

LLM extraction은 `PROPOSED`만 만들 수 있다. Human approval receipt 없이는 numerical use 불가다.

보고서 숫자를 단순 평균하지 않는다. 독립 출처 dedup, horizon/definition alignment, historical reliability를 거친 consensus distribution만 soft view가 될 수 있다.

### C2. 옵션과 예측시장

- risk-neutral terminal density는 reference overlay로 유지
- physical calibration model과 OOS receipt가 있을 때만 numerical use
- QQQ proxy와 IXIC target의 basis risk 기록
- stale option surface, wide spread, low OI 차단
- prediction market은 정의·판정일·유동성·스프레드·중복 여부 검사

### C3. Event state

FOMC/CPI/NFP/NVDA는 단순 calendar icon과 probability state를 분리한다.

수치 경로 영향은 다음이 있을 때만 허용한다.

```text
surprise definition
consensus vintage
asset response window
PIT historical event sample
minimum sample gate
regime conditioning
outlier/winsorization rule
OOS calibration
approved mapping receipt
```

임의 event-day 상승/하락을 삽입하지 않는다.

### C4. Liquidity/cross-asset/AI capital cycle

실제 adapter가 없다면 화면에서 `NOT USED NUMERICALLY`로 표시한다.

구현할 경우 각 signal은 다음을 가져야 한다.

```text
source row hash
available_at
transformation
lag
standardization window
state definition
historical forward-return relation
OOS reliability
view mapping
strength cap
```

---

## 8. Phase D — 그래프 의미와 대표선 수정

### D1. Primary line

각 scenario panel의 기본 굵은 선은 weighted p50다.

```text
solid thick = conditional p50
thin/dotted = one actual simulated member
fan = valid ESS-gated conditional bands
```

actual member에는 항상 다음 라벨을 표시한다.

```text
ONE SIMULATED MEMBER
EXACT DATES ARE NOT FORECAST
```

### D2. Representative selector

actual member는 계속 실제 path여야 하지만 다음을 전체 horizon과 post-classification continuation에서 각각 평가한다.

```text
terminal return
annualized daily volatility
annualized weekly volatility
maximum drawdown
longest underwater duration
underwater share
weekly down count
weekly direction changes
largest 1-day loss
largest 5-day loss
trajectory distance to weighted p50
```

특정 날짜에서 대표선 percentile이 p05 아래 또는 p95 위인 구간 비중을 기록한다. Tail segment가 과도하면 sample badge를 경고하거나 다른 central path를 선택한다.

대표선이 p50 자체인 것처럼 설명하지 않는다.

### D3. Correction timing panel

8~10월 correction view는 다음으로 표시한다.

- any-touch probability
- cumulative first-touch CDF
- first-touch density/histogram
- p25/median/p75 first-touch date
- “exact date forecast=false”

10월 2일 같은 sample path 날짜를 위험창 중심일로 사용하지 않는다.

### D4. Risk label 수정

`unconditional_prob_touch_corr10`을 `변동성 저/중/고`로 부르지 마라.

정확한 표현:

```text
-10%선 누적 터치확률 저/중/고
```

실제 volatility를 표시하려면 별도 conditional-volatility series가 있어야 한다.

### D5. Fan scale

S2의 p10/p90가 ESS gate로 숨겨지면 공통 y-scale 계산에도 포함하지 않는다. 표시되는 series만 scale에 포함한다.

Unconditional fan은 `posterior_predictive_unconditional`로 표시한다. Scenario fan만 `scenario_conditional`이다.

### D6. Legacy label

남아 있는 `RCFHS-SB v1 shadow` 오표기를 제거한다. 실제 RCFHS가 아니면 legacy actual-member diagnostic로 명명한다.

---

## 9. Phase E — 2027 scenario 동학 처리

### E1. 현재 V5의 정직한 fallback

현재 legacy GBM은 2026-12-31 이후 memoryless continuation이다. 다음 diagnostic을 계산한다.

```text
scenario별 post-classification return distribution
normalized p50 level correlation
Wasserstein distance
energy distance
conditional vol/drawdown difference
```

다음 조건이면 “3개 distinct continuation” 표시를 차단한다.

```text
normalized p50 level correlation > 0.98
and distribution distance below registered minimum
```

이 경우 화면은 다음처럼 표시한다.

```text
2026: scenario-specific conditional distribution
2027: common-model continuation; scenario-specific starting level only
```

세 개 actual-member line을 우연히 다르게 뽑아 경제적으로 다른 2027 전망처럼 보여주지 않는다.

Baseline expected continuation:

```text
S1 p50 ≈ 13.47%
S2 p50 ≈ 13.11%
S3 p50 ≈ 13.92%
normalized p50 level correlation ≈ 0.994~0.999
```

### E2. V6 stateful challenger

승인 PIT long history가 있을 때만 구현한다.

권장 구조:

```text
PIT daily history
→ observable regime
→ state-conditioned drift
→ EWMA/GARCH conditional volatility
→ standardized empirical residual
→ regime-conditioned stationary block bootstrap
→ optional approved event jump layer
→ one continuous 252-session path
→ outcome partition
→ scenario conditional distribution
```

Post-classification state vector:

```text
price
running high
drawdown
time underwater
conditional variance
regime
trend
liquidity state
rate state
AI capex/earnings state
```

S1/S2/S3는 분류일 가격만이 아니라 post-classification state distribution이 달라야 한다. Transition은 데이터에서 추정한다.

PIT history에 다음이 없으면 V6 build를 차단한다.

```text
date
value
available_at
source
source_revision/vintage
response_sha/content_sha
ingested_at
```

---

## 10. Phase F — Prior risk와 sensitivity

현재 252-session sample mean drift 23.09%를 그대로 확정 prior로 쓰지 마라.

Shadow challenger에서 비교할 후보:

```text
GBM with shrinkage drift
EWMA filtered historical simulation
GARCH filtered historical simulation
RCFHS stationary bootstrap
```

필수 sensitivity:

- drift shrinkage prior
- lookback 252/504/756/1260
- path count 40k/100k/200k
- seeds 최소 10개
- block length distribution
- regime threshold
- evidence strength/tolerance
- leave-one-view/cluster-out

Representative trough date와 scenario probability의 seed/source-refresh stability를 보고한다.

Exact date stability가 낮으면 날짜 표시를 더 강하게 억제한다.

---

## 11. Phase G — 테스트

### G1. Time/PIT

- hardcoded horizon start 없음
- started-window unconditional target 그대로 사용하면 실패
- survival-conditioned 또는 fresh reforecast만 numerical
- future/naive available_at 실패
- source hash mismatch 실패
- official SHA mismatch 시 dashboard V5 disabled

### G2. Circularity/dependency

- current ancestor model에서 파생된 view numerical use 실패
- cluster strength cap 초과 실패
- duplicate report cluster 중복 가중 실패
- leave-one-cluster-out report 생성

### G3. Artifact

- NaN/Inf/bool numeric 실패
- date duplicate/out-of-order 실패
- quantile crossing 실패
- array length mismatch 실패
- representative row mismatch 실패
- ESS visibility mismatch 실패
- probability-space mismatch 실패

### G4. 10월 2일

- S1 daily trough 2026-10-01 baseline characterization
- dashboard 5-session point 2026-10-02 characterization
- correction view가 exact-date constraint가 아님을 테스트
- UI가 “10월 2일 저점 예측” 문구를 포함하지 않음
- first-touch distribution이 제공됨

### G5. Scenario shapes

- raw actual-member return correlation만으로 distinct 판정하지 않음
- normalized p50 level and distribution-distance gate 추가
- 2027 distributions가 유사할 때 distinct continuation line hidden 또는 common continuation disclosure
- random noise로 gate 통과 금지

### G6. Browser QA

실제 브라우저 screenshot/evidence를 생성한다.

필수 화면:

- V5 current candidate banner
- p50 primary + actual member secondary
- S1/S2/S3 conditional fans
- correction first-touch panel
- evidence USED/REFERENCE/BLOCKED
- stale/unavailable state
- 2027 common-continuation disclosure
- mobile layout

빈 representative/fan 상태에서 Infinity/NaN SVG 좌표가 없어야 한다.

### G7. Regression

- targeted tests
- full suite
- JavaScript syntax
- legacy official replay
- protected hash comparison
- deterministic model-content hash

---

## 12. Phase H — 산출물

다음 산출물을 생성한다.

```text
docs/audit/scenario_v5_1/SCENARIO_V5_1_FINAL_HARDENING_REPORT.md
docs/audit/scenario_v5_1/SCENARIO_V5_1_DATA_QUALITY_REPORT.csv
docs/audit/scenario_v5_1/SCENARIO_V5_1_EVIDENCE_DEPENDENCY_REPORT.csv
docs/audit/scenario_v5_1/SCENARIO_V5_1_TIMING_DISTRIBUTION.json
docs/audit/scenario_v5_1/SCENARIO_V5_1_2027_DISTINCTNESS_REPORT.json
docs/audit/scenario_v5_1/SCENARIO_V5_1_TEST_REPORT.md
docs/audit/scenario_v5_1/SCENARIO_V5_1_PROTECTED_HASHES.json
```

V6가 blocked이면:

```text
docs/audit/scenario_v6/SCENARIO_V6_BLOCKER_REPORT.md
```

을 작성하고 거짓 candidate를 생성하지 않는다.

---

## 13. 최종 Gate

### V5.1 merge recommendation 가능 조건

- official/protected files 불변
- source snapshot exact-match runtime gate
- forecast time transport 구현
- endogenous/self-derived numerical view 차단
- dependency cluster cap 구현
- strict validator mutation tests 통과
- p50 primary
- actual-member exact-date disclosure
- correction first-touch distribution
- 2027 common-continuation disclosure/gate
- browser evidence 존재
- targeted/full tests 결과 기록
- clean reproducible model-content hash

### V6 promotion 금지 조건

다음 중 하나라도 없으면 promotion 금지다.

- approved PIT history
- rolling-origin evaluation
- benchmark comparison
- coverage/calibration
- seed/parameter stability
- human approval

---

## 14. 최종 응답 형식

작업 종료 시 다음을 순서대로 보고한다.

1. Executive verdict
2. 변경 파일 목록
3. 10월 2일 원인 최종 설명
4. 실제 numerical evidence와 blocked evidence
5. time-alignment/circularity 수정 결과
6. V5.1 그래프 전후 의미 차이
7. 2027 distinctness 판정
8. V6 구현 또는 blocker
9. 실행 테스트와 pass/fail/skip
10. protected SHA 전후 비교
11. candidate model-content SHA와 build receipt SHA
12. browser evidence 경로
13. 미해결 위험
14. merge recommendation
15. git diff summary

자동 commit, push, PR, merge는 하지 마라.
