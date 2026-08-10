# L0 Batch 1 Implementation Report

- 작성일: 2026-08-06 KST
- 대상 저장소: `C:\workspace\ai-investing`
- 대상 브랜치: `main` 작업 트리
- 범위: B1-1 CI containment, B1-2 forecast probability arithmetic, B1-3 expired active question official-write guard
- 배포 상태: 커밋·병합·push하지 않음

## 변경 목적

이번 Batch 1은 모델 확률이나 시나리오를 재계산하지 않고, 새 forecast가 공식 기록 경계에 도달하기 전에 기존 v1 정수 퍼센트 계약의 내부 정합성을 결정적으로 검사한다.

1. `1 <= ci80_lo <= probability <= ci80_hi <= 99`를 강제한다.
2. `anchor_pct + signed adjustments = final probability`를 0.5%p 허용오차 안에서 강제한다.
3. KST fixed deadline 날짜가 지난 active 질문의 새 공식 revision을 preflight와 최종 append 직전에 차단한다.
4. 실패 값을 clipping·정규화·질문 상태 변경으로 숨기지 않고 validation/preflight error로 거부한다.

변경 전 동적 probe에서는 `point=80, CI=[45,75]`와 `anchor=55, adjustments=[], final=63`이 모두 수용됐다. 변경 전 관련 targeted suite는 `36 passed`였다.

## 변경 파일

| 파일 | 구분 | 변경 요지 |
|---|---|---|
| `src/ai_fc/schemas.py` | application | 확률 범위, CI containment, signed-adjustment 산술, 양수 delta, exact duplicate 검증 |
| `src/ai_fc/llm_provider.py` | application | provider-independent 출력 경계에서 공통 consistency validator 재호출 및 CI 방어 검사 |
| `src/ai_fc/files.py` | application | 신규 frontmatter의 CI 범위·순서·point containment 방어 검사 |
| `src/ai_fc/orchestrator.py` | application | aggregate 결과 consistency 검사, KST deadline preflight 및 official append 직전 재검사 |
| `src/tests/test_l0_batch1.py` | test, 신규 | CI·산술·누락·부호·중복·rounding·historical ledger read acceptance tests |
| `src/tests/test_sprint2.py` | test | deadline 이전/당일/이후, run 도중 deadline 경과, aggregate 불일치 no-write 테스트 |
| `src/tests/test_llm_provider.py` | test fixture | 기존 final 63 fixture에 명시적 +8%p 조정 추가 |
| `src/tests/test_provider_shadow.py` | test fixture | shadow final 61을 유지하면서 명시적 +11%p 조정 추가 |
| `docs/audit/phase2_260806/L0_BATCH1_IMPLEMENTATION_REPORT.md` | documentation, 신규 | 본 구현·검증 보고서 |

`AGENTS.md`, Prompt 본문, 질문 registry, forecast archive, calibration ledger, benchmark ledger, scenario snapshot은 수정하지 않았다.

## 변경 symbol

| Symbol | 위치 | 역할 |
|---|---|---|
| `FORECAST_ARITHMETIC_TOLERANCE_PP` | `src/ai_fc/schemas.py:15` | 기존 v1 정수 표시와 Prompt v2 계약에 맞춘 0.5%p 산술 허용오차 |
| `Adjustment.delta_pp` | `src/ai_fc/schemas.py::Adjustment` | 설명에만 있던 양수 조건을 `gt=0`으로 강제 |
| `ForecastResult.validate_probability_contract` | `src/ai_fc/schemas.py::ForecastResult` | Pydantic 생성 시 consistency validator 실행 |
| `validate_forecast_consistency` | `src/ai_fc/schemas.py:70` | 범위, CI containment, duplicate adjustment, signed sum을 clipping 없이 검사 |
| `validate_forecast_output` | `src/ai_fc/llm_provider.py:44` | provider 반환값의 공통 계약 검사 및 `ProviderOutputError` 변환 |
| `validate_new_record` | `src/ai_fc/files.py:157` | official frontmatter CI에 대한 defense-in-depth |
| `_assert_official_forecast_open` | `src/ai_fc/orchestrator.py:57` | fixed KST deadline 이후 새 공식 revision 차단 |
| `run_forecast` | `src/ai_fc/orchestrator.py:64` | 최초 deadline 검사, aggregate consistency 검사, append 직전 deadline 재검사 |

## Validation 흐름

```text
provider structured output
  → ForecastResult Pydantic field range checks
  → ForecastResult model validator
      ├─ 1..99 integer range
      ├─ low <= point <= high
      ├─ delta_pp > 0
      ├─ exact duplicate adjustment rejection
      └─ anchor + signed deltas == point within 0.5pp
  → llm_provider.validate_forecast_output defense-in-depth
  → aggregator
  → orchestrator validates aggregate final/CI against representative result
  → frontmatter validate_new_record CI defense-in-depth
  → KST deadline recheck immediately before _write_records
  → exclusive official forecast append
```

어떤 단계에서도 확률을 0~1 또는 1~99로 clipping하지 않는다. `up`은 `+delta_pp`, `down`은 `-delta_pp`로만 계산한다. 중복 검사는 현재 v1 스키마에 adjustment ID가 없으므로 정규화된 evidence 문자열, direction, delta 값이 모두 같은 exact duplicate를 대상으로 한다.

### Aggregate 처리

`KRunMedian`이 활성화될 경우 공식 probability와 CI는 aggregate 값이고 설명은 representative `ForecastResult`다. 따라서 provider run별 검증만으로는 부족하다. `orchestrator.run_forecast`가 official aggregate probability/CI를 representative anchor·adjustments에 다시 대입해 검사한다. 설명과 공식 final이 0.5%p보다 크게 어긋나면 기록 전에 거부한다. 결합 규칙이나 probability 값 자체는 변경하지 않았다.

### Deadline/timezone 정책

- 기존 프로젝트 정책: `config.TZ_NAME = "Asia/Seoul"`.
- registry의 fixed deadline은 날짜이며 별도 시각 필드가 없다.
- 정책: KST deadline 날짜의 `23:59:59`까지 허용하고, 다음 KST 날짜 `00:00:00`부터 차단한다.
- 기존 `date.today()`의 암묵적 OS local-time 의존을 `_now_kst()`로 교체했다.
- 상태를 resolved/HOLD로 자동 변경하지 않는다.
- rolling 질문에는 별도 고정 resolution cutoff 필드가 없으므로 기존 rolling 정책을 변경하지 않았다.
- 초기 preflight가 통과한 뒤 자정이 지나도 공식 파일이 기록되지 않도록 `_write_records` 직전에 다시 검사한다.

## 정상/실패 acceptance test

| # | Acceptance | Test/evidence | 결과 |
|---:|---|---|---|
| 1 | CI `low < point < high` 정상 | `test_ci_contains_point_including_boundaries[60-40-75]` | PASS |
| 2 | CI `low == point` 정상 | `test_ci_contains_point_including_boundaries[40-40-75]` | PASS |
| 3 | CI `point == high` 정상 | `test_ci_contains_point_including_boundaries[75-40-75]` | PASS |
| 4 | `point < low` 실패 | `test_ci_rejects_non_containment_order_and_range` | PASS — rejected |
| 5 | `point > high` 실패 | 동일 parametrized test | PASS — rejected |
| 6 | `low > high` 실패 | 동일 parametrized test | PASS — rejected |
| 7 | `anchor + adjustments == final` 정상 | `test_forecast_arithmetic_exact_match` | PASS |
| 8 | 양수·음수 adjustment 혼합 정상 | `test_forecast_arithmetic_mixed_positive_and_negative_adjustments` | PASS |
| 9 | 산술 불일치 실패 | `test_forecast_arithmetic_rejects_mismatch_and_sign_error`; `test_inconsistent_aggregate_is_rejected_before_official_write` | PASS — rejected/no write |
| 10 | rounding 허용 범위 경계 | `test_forecast_arithmetic_rounding_tolerance_boundary` | PASS — 0.5%p accepted, 0.501%p rejected |
| 11 | deadline 이전 official write 정상 | `test_official_write_allowed_through_kst_deadline_date[before-deadline]` | PASS |
| 12 | deadline과 정확히 같은 시각 정책 | `test_official_write_allowed_through_kst_deadline_date[deadline-day-kst]` at 23:59:59 KST | PASS |
| 13 | deadline 이후 official write 실패 | `test_expired_active_question_cannot_write_official_revision`; `test_official_write_rechecks_deadline_after_forecast_work` | PASS — no official file |
| 14 | 기존 historical ledger read 정상 | `test_historical_ledger_read_is_backward_compatible_and_non_mutating` | PASS — bytes unchanged |
| 15 | 기존 snapshot/replay 결과 불변 | `python tools/reproduce_scenario_snapshot.py` | PASS — 83/2/15, 1,764 cells, mismatch 0 |

추가 acceptance:

- adjustment 필드 누락은 Pydantic/provider validation error.
- 잘못된 direction으로 final을 맞춘 sign-error payload는 산술 validation error.
- exact duplicate adjustment는 합계가 맞아도 validation error.
- CI low/point/high 각각 1..99 밖이면 validation error.
- official frontmatter가 point를 포함하지 않는 CI를 가지면 `validate_new_record`가 거부.

## 실행 명령

```powershell
Set-Location -LiteralPath 'C:\workspace\ai-investing'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONPATH = 'C:\workspace\ai-investing\src;C:\workspace\ai-investing\dualdb'

# 변경 전 targeted baseline
python -m pytest -q -p no:cacheprovider `
  src/tests/test_llm_provider.py `
  src/tests/test_sprint2.py `
  src/tests/test_sprint1.py `
  src/tests/test_audit_fixes.py::test_krun_median_fixed_rule

# 변경 후 targeted
python -m pytest -q -p no:cacheprovider `
  src/tests/test_provider_shadow.py `
  src/tests/test_l0_batch1.py `
  src/tests/test_llm_provider.py `
  src/tests/test_sprint2.py `
  src/tests/test_sprint1.py `
  src/tests/test_audit_fixes.py::test_krun_median_fixed_rule

# 전체 회귀
python -m pytest -q -p no:cacheprovider

# 기존 scenario/snapshot 결정성
python tools/reproduce_scenario_snapshot.py

# whitespace/error diff 검사
git diff --check
```

변경 전 결함 재현은 파일을 만들지 않는 pure Python probe로 수행했다. invalid CI와 invalid arithmetic payload가 기존 `validate_forecast_output`을 통과함을 확인했다.

## 테스트 결과

| 단계 | 결과 |
|---|---|
| 변경 전 targeted | `36 passed in 10.56s` |
| 변경 전 pure behavior probe | invalid CI accepted, invalid arithmetic accepted |
| 최초 변경 후 targeted | `57 passed in 11.60s` |
| 최초 전체 회귀 | `1 failed, 403 passed in 100.83s` |
| fixture 정합화 후 targeted | `58 passed in 11.16s` |
| 최종 전체 회귀 | `404 passed in 109.71s` |
| scenario snapshot reproducer | `passed=true`, probabilities `83/2/15`, 1,764 cells, mismatches `0` |
| `git diff --check` | clean |

### 기존 테스트 실패 원인 분류

최초 전체 회귀의 유일한 실패는 `src/tests/test_provider_shadow.py::test_shadow_is_separate_and_append_only`였다.

- 분류: **test fixture contract defect**
- 원인: fixture가 `anchor=50`, adjustments 없음, `final=61`을 생성해 새 산술 계약을 위반했다.
- 처리: shadow probability 61, CI, 비용, append-only 동작은 그대로 두고 fixture에 `+11%p` 가공 adjustment를 명시했다.
- 애플리케이션 코드·환경·데이터 누락 문제는 아니었다.
- 수정 후 관련 targeted 58개와 전체 404개가 통과했다.

## Backward compatibility 검토

- 기존 forecast/ledger reader는 변경하지 않았다. historical ledger read·byte 불변 테스트가 통과했다.
- 기존 Markdown/frontmatter에 anchor/adjustment 필드를 소급 추가하거나 재검증하지 않는다.
- `parse_forecast_file`의 관대한 legacy read 정책은 그대로다.
- provider 및 orchestrator 함수의 공개 호출 signature는 변경하지 않았다.
- `ForecastResult` JSON schema에는 기존 설명과 일치하는 범위·양수 제약이 추가됐다. 내부적으로 모순된 새 payload만 거부한다.
- 유효한 shadow 실행은 기존 확률·비용·별도 append-only ledger 동작을 유지한다.
- 모델 probability, K-run 결합 규칙, scenario distribution, structural path는 변경하지 않았다.
- 예상되는 의도적 호환성 변화: 이전에 수용되던 모순된 신규 provider payload와 모순된 aggregate 설명은 이제 validation error가 된다.

## Ledger 불변성 확인

변경 전후 SHA-256:

| 파일 | Before | After | 결과 |
|---|---|---|---|
| `calibration/ledger.csv` | `AA180A76CA49EC59CC10A35D62C0CA3ABAFDB01F467A9111639E3259A5D7CD0E` | 동일 | unchanged |
| `calibration/benchmark_ledger.csv` | `D0175707D623F0B7A0C1F4E4CDFD1732A57ECEA418E9880E4B8FE6C4C79EB696` | 동일 | unchanged |
| `data/scenarios/nasdaq_latest.json` | `7526638E1B11A04E91112A673FBBCA91C00CEB4C00CB1211774532F05D796F9C` | 동일 | unchanged |

테스트는 `tmp_path`의 가공 forecast/ledger만 썼다. 기존 ledger row를 update/delete하지 않았고 새 공식 row도 생성하지 않았다.

## 미구현 L0 항목

요청에 따라 다음은 구현하지 않았다.

- 질문 READY/HOLD 상태머신 및 registry migration
- 빈 `required_snapshots` 정책 변경
- degraded research의 official-write 차단
- benchmark probability correction/supersedes 도구
- SourceRecord/EvidenceClaim 구조화
- 프롬프트 인젝션 경계와 프롬프트 본문 개편
- provider citation provenance 변경
- 모델 확률·시나리오 구조경로 변경

## Rollback 방법

아직 커밋하지 않았으므로 검토자가 이 Batch 1만 되돌리려면 먼저 `git diff`로 경로를 다시 확인한 뒤 다음 tracked 파일을 복원한다.

```powershell
git restore -- `
  src/ai_fc/schemas.py `
  src/ai_fc/llm_provider.py `
  src/ai_fc/files.py `
  src/ai_fc/orchestrator.py `
  src/tests/test_llm_provider.py `
  src/tests/test_provider_shadow.py `
  src/tests/test_sprint2.py
```

그 다음 신규 `src/tests/test_l0_batch1.py`와 본 보고서만 삭제한다. 기존 untracked Phase 1/Phase 2 문서와 다른 review package는 삭제하면 안 된다. rollback 후 변경 전 targeted 명령이 다시 `36 passed`인지 확인한다.
