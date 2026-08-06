# L0 Batch 1 Independent Review

- 검토일: 2026-08-06 KST
- 검토 대상: 현재 `main` 작업 트리의 미커밋 L0 Batch 1 diff
- 검토 방식: 지정 문서 재독, 현재 diff 정적 추적, 독립 동적 probe, targeted/full pytest 재실행, durable 파일 HEAD 대조, scenario snapshot 재현
- 코드 수정: 없음
- 최종 판정: **FAIL — 병합 권고 안 함**

## Executive conclusion

CI containment와 forecast 산술 검사는 정상적인 공식 `run_forecast` 경로에서 실제 append 이전에 여러 겹으로 실행된다. 기존 ledger·forecast·scenario snapshot도 변경되지 않았고 전체 404개 테스트는 통과한다.

그러나 expired guard가 `dry_run` 분기보다 앞에서 무조건 실행된다. 따라서 만료된 active 질문은 공식 revision뿐 아니라 scratch 전용 `dry_run=True`도 실행할 수 없다. 이는 “공식 forecast에만 정확히 적용” 및 “scratch를 불필요하게 차단하지 않음” 두 acceptance를 위반한다. 현재 테스트에는 만료된 dry-run 허용 계약이 없어 이 회귀를 발견하지 못한다.

추가 경고로, rounding 경계 테스트가 구현 상수 자체를 import해 0.5%p 정책을 독립적으로 고정하지 못하며, 기존 Pydantic 숫자 문자열 coercion은 계속 허용된다.

## 판정표

| # | 검증 항목 | 판정 | 독립 근거 |
|---:|---|---|---|
| 1 | CI containment가 공식 write 이전에 실제 실행되는가 | **PASS** | `ForecastResult` model validator → `llm_provider.validate_forecast_output` → `orchestrator.run_forecast` aggregate 검사 → `files.validate_new_record`가 모두 `_write_records`보다 앞에 있다. `point<low` 동적 probe는 `ProviderOutputError`; targeted tests 통과. |
| 2 | anchor + adjustments 산술 검사가 우회될 수 없는가 | **PASS WITH WARNING** | 일반 provider 및 aggregate 경로는 모두 `validate_forecast_consistency`를 거친다. `model_copy(update=...)`로 Pydantic을 우회한 fixture도 orchestrator에서 no-write로 거부된다. 다만 private `_write_records` 자체는 validation receipt를 요구하지 않아 직접 호출은 기술적으로 가능하다. runtime 호출자는 `run_forecast` 하나뿐이므로 현재 공식 경로는 보호된다. |
| 3 | expired question guard가 공식 forecast에만 정확히 적용되는가 | **FAIL** | `orchestrator.run_forecast`가 `dry_run` 분기 확인 전에 `_assert_official_forecast_open`을 무조건 호출한다. 독립 probe에서 expired active + `dry_run=True`가 `PreflightError`로 거부됐다. |
| 4 | 기존 ledger row가 변경되지 않았는가 | **PASS** | `git diff --quiet -- calibration forecasts` exit 0. calibration/benchmark/cost/shadow ledger SHA-256을 재계산했으며 tracked HEAD와 차이가 없다. historical ledger read test도 bytes unchanged. |
| 5 | silent clipping이나 silent coercion이 추가되지 않았는가 | **PASS WITH WARNING** | clipping/normalization 코드는 추가되지 않았고 범위 밖 값은 거부된다. 다만 Pydantic의 기존 non-strict coercion 때문에 숫자 문자열이 int/float로 수용되는 동작은 남아 있다. 독립 probe에서 문자열 `"60"`, `"5.0"`이 수용됐다. 이번 diff가 새로 만든 coercion은 아니다. |
| 6 | timezone 경계가 명확한가 | **PASS** | `config.TZ_NAME="Asia/Seoul"`, `_now_kst()` 사용, date-only deadline의 KST 당일 23:59:59 허용/다음 날 00:00 차단 테스트가 있다. OS local `date.today()` 의존은 제거됐다. |
| 7 | replay, shadow, scratch 동작을 불필요하게 차단하지 않는가 | **FAIL** | valid shadow와 기존 replay는 통과하지만 expired scratch dry-run이 차단된다. `dry_run`은 공식 파일을 만들지 않는 별도 scratch 모드이므로 official-only guard의 적용 대상이 아니다. |
| 8 | 기존 모델 확률과 snapshot이 변하지 않았는가 | **PASS** | scenario/model source는 diff 대상이 아니다. `nasdaq_latest.json`은 HEAD와 동일하고 reproducer가 `83/2/15`, 1,764 cells, mismatch 0을 재현했다. |
| 9 | 테스트가 구현 세부사항이 아니라 외부 동작을 검증하는가 | **PASS WITH WARNING** | provider output과 `run_forecast` no-write/file effects를 중심으로 검증한다. 다만 rounding test가 `FORECAST_ARITHMETIC_TOLERANCE_PP`를 import해 같은 상수로 pass/fail 값을 만들므로 정책값이 잘못 바뀌어도 테스트가 함께 이동한다. expired dry-run acceptance도 누락됐다. |
| 10 | 무관한 변경이나 과도한 리팩터링이 포함되지 않았는가 | **PASS** | application diff는 schema/provider/file/orchestrator의 관련 symbol 4곳에 한정되고 prompt, registry, model, scenario, ledger는 변경되지 않았다. 테스트 fixture 수정도 새 계약을 만족시키면서 기존 probability를 보존한다. |

### 집계

- PASS: 5
- PASS WITH WARNING: 3
- FAIL: 2
- NOT TESTABLE: 0

FAIL이 있으므로 현재 diff의 병합을 권고하지 않는다.

## 문제 파일과 symbol

### Blocking issue R1 — expired dry-run 차단

- 파일: `src/ai_fc/orchestrator.py`
- symbol: `run_forecast`, `_assert_official_forecast_open`
- 근거 위치:
  - 초기 무조건 호출: `run_forecast`의 registry/status/tbd 검사 직후
  - scratch 분기: 이후의 `if dry_run`
  - 최종 official 재검사: `_write_records` 직전

현재 순서:

```text
load active question
→ deadline guard (unconditional)
→ research/reasoning
→ if dry_run: scratch only
→ final deadline guard
→ official write
```

expired dry-run은 첫 번째 guard에서 종료된다. 최종 official guard는 정확히 배치돼 있으므로 유지해야 한다.

### Warning R2 — rounding test가 구현 상수에 결합

- 파일: `src/tests/test_l0_batch1.py`
- symbol: `test_forecast_arithmetic_rounding_tolerance_boundary`
- 문제: 테스트가 `FORECAST_ARITHMETIC_TOLERANCE_PP`를 import해 허용/거부 입력을 만든다.
- 영향: 구현 상수가 0.5에서 잘못 변경되어도 테스트 입력도 함께 변경돼 정책 회귀를 놓칠 수 있다.

### Warning R3 — 기존 numeric coercion

- 파일: `src/ai_fc/schemas.py`
- symbol: `Adjustment`, `ForecastResult`
- 문제: Pydantic 필드가 strict type이 아니므로 숫자 문자열이 조용히 int/float로 변환된다.
- 영향: 이번 diff가 추가한 동작은 아니지만 “원천 타입 그대로의 엄격한 계약”은 아니다.
- 조치: Batch 1 blocking fix와 분리해 backward-compatibility 조사 후 결정한다.

### Warning R4 — private writer는 validation receipt를 요구하지 않음

- 파일: `src/ai_fc/orchestrator.py`
- symbol: `_write_records`
- 현재 runtime 호출자는 검증된 `run_forecast`뿐이다. 테스트가 원자성을 확인하기 위해 직접 호출한다.
- 현 단계 병합 차단 사유는 아니지만, 향후 외부 호출자가 추가되면 공식 write gate를 우회할 수 있으므로 caller-count 회귀 또는 validated envelope를 고려할 수 있다.

## 재현 명령

```powershell
Set-Location -LiteralPath 'C:\workspace\ai-investing'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONPATH = 'C:\workspace\ai-investing\src;C:\workspace\ai-investing\dualdb'

# 현재 diff와 write caller 확인
git diff --name-status
git diff --check
rg -n "_write_records\(|validate_forecast_consistency\(|_assert_official_forecast_open\(" src/ai_fc src/tests

# targeted
python -m pytest -q -p no:cacheprovider `
  src/tests/test_provider_shadow.py `
  src/tests/test_l0_batch1.py `
  src/tests/test_llm_provider.py `
  src/tests/test_sprint2.py `
  src/tests/test_sprint1.py `
  src/tests/test_audit_fixes.py::test_krun_median_fixed_rule

# full
python -m pytest -q -p no:cacheprovider

# snapshot/replay
python tools/reproduce_scenario_snapshot.py

# durable tracked data가 HEAD와 동일한지 확인
git diff --quiet -- calibration forecasts data/scenarios/nasdaq_latest.json
```

Expired dry-run 재현용 pure probe의 핵심은 `load_registry`와 `_now_kst`만 가공 active/expired 값으로 교체하고 다음을 호출하는 것이다.

```python
run_forecast(memory_connection, repo, "expired-fixture", dry_run=True)
# actual: PreflightError("... 기한 경과 ...")
```

## 테스트 결과

| 검증 | 독립 재실행 결과 |
|---|---|
| Targeted suite | `58 passed in 10.53s` |
| Full suite | `404 passed in 83.14s` |
| Scenario reproducer | `passed=true`, `83/2/15`, 1,764 cells, mismatch 0 |
| Invalid CI probe | rejected with `ProviderOutputError` |
| Invalid arithmetic probe | rejected with `ProviderOutputError` |
| Valid forecast probe | accepted |
| Expired dry-run probe | rejected with `PreflightError` — blocking defect reproduced |
| Numeric-string probe | accepted and coerced to int/float — warning reproduced |
| Durable tracked paths | HEAD diff exit 0 |
| `git diff --check` | clean |

전체 pytest green은 구현된 테스트와 기존 회귀가 통과한다는 뜻이다. expired dry-run 요구사항이 테스트로 표현되지 않았으므로 blocking behavior defect와 모순되지 않는다.

## Ledger 및 snapshot 독립 증거

| 파일 | 현재 SHA-256 | HEAD diff |
|---|---|---|
| `calibration/ledger.csv` | `AA180A76CA49EC59CC10A35D62C0CA3ABAFDB01F467A9111639E3259A5D7CD0E` | none |
| `calibration/benchmark_ledger.csv` | `D0175707D623F0B7A0C1F4E4CDFD1732A57ECEA418E9880E4B8FE6C4C79EB696` | none |
| `calibration/cost_log.csv` | `F71DB21B1FAFDD329002692AF3531EFD9F88D6B31755A6BBE3D26FD01BFFD83C` | none |
| `calibration/provider_shadow_ledger.csv` | `15D54640C1F436466D6BC7110E19EA3622D1D92FC19C15F4A37A9CF2118A2FCE` | none |
| `data/scenarios/nasdaq_latest.json` | `7526638E1B11A04E91112A673FBBCA91C00CEB4C00CB1211774532F05D796F9C` | none |

## 회귀 위험

| 위험 | 수준 | 설명 |
|---|---|---|
| Expired scratch/dry-run 차단 | High | 공식 원장에 영향을 주지 않는 검토·재현용 경로를 사용할 수 없다. blocking defect. |
| Even-K aggregate explanation mismatch | Medium, intended rejection | median final이 representative anchor math와 0.5%p 이상 다르면 공식 기록이 거부된다. 결합 설명의 정합성 확보 전에는 안전한 실패지만 운영 중단 가능성이 있다. |
| Numeric-string coercion | Medium | upstream JSON이 숫자를 문자열로 보내도 수용된다. 기존 호환성이나 provider schema와 함께 검토해야 한다. |
| Exact duplicate만 탐지 | Low | 동일 evidence라도 delta/direction이 다르면 duplicate로 보지 않는다. v1에 adjustment ID가 없어 의미 중복 탐지는 제한적이다. |
| Private `_write_records` 직접 호출 | Low | 현재 production caller는 하나지만 validation receipt 자체를 요구하지 않는다. |
| Deadline crossing after shadow call | Low | final guard는 official write를 막지만, 자정이 shadow call 도중 지나면 사용된 shadow 비용/관찰의 처리 경로를 추가 점검할 가치가 있다. |

## 병합 권고 여부

**병합 권고: NO**

사유: 검증 항목 3과 7이 FAIL이다. full test 404 green만으로 official-only deadline scope 위반을 상쇄할 수 없다.

## 최소 수정 범위

코드 수정은 이 독립 검토에서 수행하지 않았다. 권장 최소 후속 diff는 다음뿐이다.

1. `src/ai_fc/orchestrator.py::run_forecast`
   - 초기 deadline preflight를 official run에만 적용한다.
   - 예: `if not dry_run: _assert_official_forecast_open(q, now)`.
   - `_write_records` 직전 최종 guard는 그대로 유지한다.
   - 질문 status는 변경하지 않는다.
2. `src/tests/test_sprint2.py`
   - expired active + `dry_run=True`가 `[DRY]`로 완료되는지 확인한다.
   - official forecast files가 0개이고 scratch 파일만 생기는지 확인한다.
   - expired active + `dry_run=False` no-write 테스트는 유지한다.
3. `src/tests/test_l0_batch1.py`
   - rounding 입력을 구현 상수에서 계산하지 말고 사양값 `5.5`와 `5.501`로 고정한다.
   - 필요하면 별도로 `FORECAST_ARITHMETIC_TOLERANCE_PP == 0.5` 계약을 명시한다.

Numeric-string strictness와 private writer receipt는 별도 호환성 검토 대상이며, blocking fix에 섞지 않는 편이 안전하다.
