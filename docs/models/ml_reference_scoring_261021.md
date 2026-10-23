---
ai_fc_status: active
ai_fc_role: reference-ledger
ai_fc_gate: "기록·표시만 — 멤버 가중·강등·승격 없음, C5 분모 기여 0, 참고 의견 (CLAUDE.md ML 게이트·P3 게이트)"
technique_id: ML_M4_REFERENCE_SCORING
contract: data/contracts/ml_technique_m4_reference_scoring.yaml
ledger: data/ml_reference/ledgers/reference_scores.jsonl
registered: 2026-10-21
last_reviewed: 2026-10-21
---

# 오픈웨이트 참조 계층 손질 (2026-10-21) — 신선도 상한 · 참조 채점 원장 · 매핑 커버리지 · Chronos-2 꼬리 병기

`src/ai_fc/ml`(Chronos-Bolt·Chronos-2·T5·GBM·FinBERT)은 **추론 전용**이고 결합은 **고정
중앙값**뿐이다. 이 문서의 네 변경은 그 지위를 바꾸지 않는다 — 어떤 가중치도 갱신되지 않고,
어떤 출력도 매매 신호가 되지 않으며, 어떤 원장도 캘리브레이션 표본에 더해지지 않는다.

## 1. ML 참조 신선도 상한 (`resolver._ml_ref_before`)

- **전**: `run_ts ≤ forecast_ts` 만 걸어 예측 시점 **이전**이면 수개월 전 run 과도 짝지었다.
  2026-07-20 이후 ml run 이 없었으므로 10월 해소분의 `ml_prob` 는 7월 참조값이 됐을 것이다
  — "그 시점의 ML 의견"이라는 벤치마크 전제가 거짓이 된다.
- **후**: `forecast_ts − run_ts ≤ config.ML_REF_MAX_AGE_DAYS(7)` 를 추가. 초과·부재·해석 불가
  시각은 모두 `None`(벤치마크 원장 `ml_prob`/`ml_brier` NULL — 소급 조회 금지). 원장 열 추가 없음.
  `queries.latest_ml_refs`·`base_rates._latest_fresh_run` 과 같은 상수를 쓴다.
- 함수 안에서 `datetime`·`config` 를 국소 import 한다 — 허용 범위가 함수 하나라 모듈 import 블록을
  건드리지 않았다.
- 테스트: `src/tests/test_ml_ref_freshness.py` (합성 sqlite — 7일 이내·초과·경계 포함·해석 불가).
- **기존 테스트 충돌**: `src/tests/test_ws2_benchmark.py::test_ml_ref_lookahead_blocked` 는 run
  2099-06-01 ↔ 예측 2099-06-10 (9일 차) 픽스처로 "이전 최신"을 검증한다. 새 규칙에서는 9일 >
  7일이라 `None` 이 맞다. 픽스처의 run 날짜를 상한 안(예: `2099-06-05T00:00:00`)으로 옮기면
  룩어헤드 검증 의도는 그대로 유지된다. 그 파일은 이 작업의 허용 범위 밖이라 손대지 않았다.

## 2. 참조 채점 원장 (C2) — `ml/reference_scoring.py`

계약 `data/contracts/ml_technique_m4_reference_scoring.yaml` (블루프린트 §6 형식, 결과 전 커밋).
`technique_id ML_M4_REFERENCE_SCORING · layer L3 · gate_required none · c5_denominator_contribution 0
· decision_rule "기록·표시만" · minimum_sample 30(판정 아님 — 요약 표시 하한)`.

### 채점 대상과 실현치 원천 (전부 읽기 전용)

| 대상 | 무엇을 | 실현치 | 지표 |
|---|---|---|---|
| `question_probs` | run 의 `forecasts` 행(bolt/c2/t5/gbm/ensemble/quantile) 확률 | `calibration/ledger.csv` 해소 행의 `outcome` — **원장 외 추정 금지**. 레지스트리는 fixed/rolling 구분용 | Brier(분수), baseline = 같은 run 의 `gbm` 행, `prob_tail_c2` 가 있으면 `brier_tail_c2` 병기 |
| `series_bands` | 지평 종점 분위수 q10~q90 | 봉인 V2 아카이브 `read_market_observations` — `^IXIC → NASDAQCOM`, `^VIX → VIX` | pinball 5레벨·평균, p10–p90 커버리지, `crps_5q`(=2×mean pinball, 5점 근사), `/last_value` 상대값, baseline = 같은 run 의 `series_bands.gbm{mu_w,sigma_w}` 로 만든 GBM 분위수 |
| `series_bands` SOXX | — | 승인된 공식 원천 없음 | `status: unresolvable_no_licensed_source` 행만 (채점 없음) |

- **^IXIC 와 NASDAQCOM 은 같은 지수**(Nasdaq Composite 종가)다. Yahoo 심볼과 FRED 계열 ID 의 차이일
  뿐이며, 종가 값은 소수 둘째 자리에서 일치한다 [미검증: 두 원천의 개별 일자 대조는 이번에 하지 않았다].
- **성숙 판정은 아카이브 거래일 인덱스**(V13 `resolve.py` 방식): 목표일 = run 주(월요일 anchor)의
  금요일 + 7·horizon_weeks 일, 실현 세션 = 목표일 이하의 마지막 아카이브 세션, 아카이브 마지막 세션이
  목표일 이상일 때만 성숙. SOXX 는 NASDAQCOM 인덱스를 달력 프록시로 쓴다.
- **rolling 질문**(vix-25-90d)은 원장 행의 `forecast_date` 가 run 일자 ±3일인 행만 같은 창으로 본다
  (ML 지평 13주 ≈ 90일). 없으면 `no_matching_rolling_window` 로 보류.
- **룩어헤드 가드**: run 일자가 원장 `resolved_date` 또는 질문 기한보다 뒤면 행을 만들지 않는다
  (`run_after_resolution`/`run_after_deadline`).
- `pre_registration = run_date < registered(2026-10-21)`. 2026-07-15·07-19·07-20 run 은 전부 true 이며
  `ml-reference-status` 요약에서 제외된다. 원장에는 남긴다 (기록은 하되 통계는 안 낸다).

### 행 스키마 (append-only · `append_unique(key=resolution_id)` · `newline="\n"`)

공통: `schema_version, technique_id, resolution_id, run_ts, kind, model, pre_registration,
knowledge_cutoff(UTC), content_hash(canonical_hash of body)`.
`kind=question_prob`: `question_id, question_kind, threshold, horizon_weeks, prob, realized(0/1),
outcome_source("ledger:<forecast_id>"), resolved_date, brier, baseline_model, baseline_prob,
baseline_brier, [prob_tail_c2, brier_tail_c2]`. `resolution_id = run_ts|question_id|model`.
`kind=series_band`: `series, symbol, archive_series, horizon_weeks, last_value, target_session,
quantiles, status, realized, realized_session, pinball{…}, pinball_mean, coverage_p10_p90, crps_5q,
pinball_mean_rel, crps_5q_rel, baseline_gbm{…}, [coverage_p01_p99_c2]`. `resolution_id = run_ts|series|h`.
금지 키(`forecasts/sentiment/market/question_probs`)는 `_finish()` 가 거부한다.

### CLI

- `python -m ai_fc ml-reference-resolve [--dry-run]` — 성숙 행 append. `--dry-run` 은 후보만 인쇄.
- `python -m ai_fc ml-reference-status` — pre_registration 제외 n·평균 Brier(모델별, gbm 기준 병기)·
  밴드 커버리지·CRPS. n < 30 이면 "표본 부족" 라벨.
- 2026-10-21 dry-run 실측: 후보 2행(07-15·07-19 run 의 q_vix 13주 밴드, 둘 다 pre_registration,
  실현 VIX 19.99 @2026-10-16, 커버 1), 보류 22건(immature 7 · no_ledger_resolution 15). **원장 파일은
  만들지 않았다** — 첫 append 는 상위 세션 판단.

## 3. 매핑 커버리지 (C3) — `ml/mapping.py` · `ml/runner.py`

추가(레지스트리 원문 임계·기한):

| question_id | 시리즈 | 임계 | mode | window | deadline |
|---|---|---|---|---|---|
| vix-30-touch-by-2026-11-30 | q_vix | 30.0 | above_path | 2026-09-10 ~ 2026-11-30 | 2026-11-30 |
| vix-13-touch-by-2026-12-18 | q_vix | 13.0 | below_path | 2026-09-10 ~ 2026-12-18 | 2026-12-18 |
| vix-40-touch-by-2027-01-15 | q_vix | 40.0 | above_path | 2026-09-11 ~ 2027-01-15 | 2027-01-15 |
| nasdaq-comp-30000-close-2027-01-15 | q_ixic | 30000.0 | above_terminal | — | 2027-01-15 |

지평 확인 결과: `run_all` 의 지평은 `max(4, min(60, (12-31 − today)//7))` — **연말 고정**이라
2027-01-15 종점은 표현 불가였다. 최소 변경:
- `QuestionMap.deadline` 필드 추가(기존 질문에도 기한 기입). `_series_horizons()` 가 시리즈별 지평을
  "매핑 질문의 가장 먼 기한(window 끝·deadline)이 들어오는 주 수"로 잡는다 (연말 기본값이 하한,
  VIX 상한 13주 유지, rolling 은 13주). 2026-10-21 기준 `q_ixic 12 · q_soxx 10 · q_vix 13`.
- 종점 질문은 지평 끝이 아니라 **기한이 속한 주 스텝**에서 평가한다(`_terminal_step`,
  `QuantileForecast.prob_above(threshold, step)`, GBM `gbm[:, step]`). 12-31 종점(F3·SOXX)은 q_ixic 지평이
  01-15 까지 늘어도 종전과 같은 스텝(인덱스 9)이다.
- 기한만 있는 경로 질문(F1)은 `_path_steps` 가 기한 주까지만 센다 — 지평 확장이 터치 확률을 부풀리지 않는다.
- 주봉 인덱스 `_week_step(asof, end) = (monday(end) − monday(asof))/7 − 1` (Yahoo 1wk 봉 = 월요일 anchor
  [미확인: 오프라인 작업이라 Yahoo 주봉 anchor 를 이번에 실측하지 못했다 — 기존 코드의 암묵 가정과 같다]).
- **명시 window 질문은 기존 `_window_steps`(일수//7, ceil) 그대로**다. 이 근사는 창 끝이 주말이면 1~2주를
  과산입한다(F2 10-31 → s1=2, 주봉 인덱스로는 0). `test_mc_barrier::test_window_steps` 가 이 규약을
  고정하고 있어 손대지 않았다 — 고치려면 그 테스트와 함께 별도 결정.

**[미구현] 새 mode 필요** (구조상 표현 불가 — 추가하지 않음): `spx-drawdown-7pct-by-2026-11-30`,
`nasdaq-drawdown-15pct-by-2027-03-31`(롤링 고점 대비 드로다운 — 경로 의존 기준가),
`vix-above20-40days-by-2027-01-15`(초과 거래일 횟수), `vix-weekly-spike-50pct-by-2026-12-18`(주간 변화율),
`t10y2y-100bp-by-2027-01-15`·`hy-oas-500bp-2026q4-2027q1`(시리즈 없음).

`test_ml_history::test_question_maps_registry_alignment` 에 `status == active`·deadline 일치 검사를
추가했다 — 매핑 질문이 해소되면 테스트가 실패해 **매핑 정리를 강제**한다 (F2 는 2026-10-31 기한).

## 4. Chronos-2 꼬리 분위수 병기 (C5) — `ml/chronos_fc.py`

- `LEVELS`(Bolt 공용 5레벨)는 그대로. `LEVELS_C2 = [0.01,0.05,0.1,0.25,0.5,0.75,0.9,0.95,0.99]` 를
  Chronos-2 경로(`forecast_quantiles_c2`)에만 적용.
- **오프라인 스모크(HF_HUB_OFFLINE=1, 합성 시계열, 2026-10-21)**: `amazon/chronos-2` 학습 분위수는
  `{0.01,0.05,0.1,…,0.9,0.95,0.99}` 21개라 LEVELS_C2 전부 **보간·외삽 없이 인덱스로 직접** 나온다.
  9레벨 호출의 공통 5레벨 값이 5레벨 호출과 **최대차 0.0** — 기존 `prob` 경로는 비트 단위로 무변경.
  종점 9분위 단조 증가 확인.
- `QuantileForecast.tail_quantiles`(9레벨)와 `prob_above_tail()`(q01~q99 보간, 범위 밖 캡 0.99/0.01 —
  모델 자신의 1%/99% 분위수가 말하는 한계). 기존 `prob_above` 캡 0.07/0.93 유지.
- 러너: 종점 질문 `question_probs[qid]["prob_tail_c2"]`(없으면 None)·`detail["prob_tail_c2"]`,
  ml_history `forecasts` 의 **c2 행에만** `prob_tail_c2` 병기. 경로 질문은 하한 참고치의 꼬리판
  `detail["terminal_bound_tail_c2"]`. `series_bands[k]["terminal_tail_c2"] = {q01,q05,q95,q99}`.
  `ensemble`·`models` 에는 넣지 않는다 — **교체는 4주 병기 뒤 별도 결정**(AGENTS.md 섀도 검증 규율).
- 참조 채점 원장은 `prob_tail_c2` 가 있는 c2 행에 `brier_tail_c2` 를, 밴드 행에 `coverage_p01_p99_c2` 를
  병기해 4주 뒤 비교 재료를 남긴다.

## 5. 검증

`cd src && python -m pytest -q tests/test_ml_reference_scoring.py tests/test_ml_ref_freshness.py
tests/test_ml_history.py tests/test_ml.py tests/test_mc_barrier.py tests/test_digest.py` — 전부 통과.
`tests/test_ws2_benchmark.py` 는 §1 의 픽스처 충돌 1건(9일 차)만 실패하며 나머지 3건 통과.

## 6. 한계 (정직 고지)

- 참조 채점은 **라이브 전진 run 만** 받는다. 과거 run 을 재실행하거나 설계창을 채점하지 않는다.
- `crps_5q` 는 5점 균등 가중 근사다 — 절대값이 아니라 같은 정의끼리의 비교에만 쓴다.
- rolling 매칭(±3일)과 주봉 anchor 는 근사다. 표본이 쌓여도 이 원장은 게이트·가중·강등에 쓰이지 않는다.
- Chronos-2 꼬리(q01/q99)는 학습 분위수이지 검증된 꼬리가 아니다 — 캡 0.99/0.01 은 분포 꼬리를 단정하지
  않기 위한 상·하한일 뿐이다.
