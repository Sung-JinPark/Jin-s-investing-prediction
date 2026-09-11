# T02 — 승인 12건 등록 기록 (2026-09-10)

> 계약 `questions/portfolio_prereg_v1.yaml` (커밋 `9337f183`, **결과 보기 전** 등록) 의
> `new_registration.user_approved_list` 12건을 `questions/registry.yaml` 에 등록했다.
> 사용자 승인: **A — 채택 9 + 예외 슬롯 3 = 12건 전부** (2026-09-10) ·
> 충돌 처리: **거부 유지 + 부정합 기록**.
>
> **등록은 예측이 아니다.** `forecasts/` 0건 생성 · `calibration/ledger.csv` 0행 추가.
> r1 실행은 별도 지시 사항이다(§5).

## 1. 등록 결과

`questions/registry.yaml` 문항 수 **67 → 79**.

| # | id | 도메인 | 마감 | z | σ | 정직확률 | 기대 Brier 바닥 | 예외 슬롯 |
|---|---|---|---|---|---|---|---|---|
| 1 | `adbe-eps-surprise-ge4pct-fq4-2026` | earnings | 2026-12-18 | 3.20 | 0.465%p | 0.04 | 0.0384 | — |
| 2 | `adbe-eps-above-guide-top-fq4-2026` | earnings | 2026-12-18 | **1.040** | $0.0271 | 0.85 | 0.1275 | **계약 1/3** |
| 3 | `nvda-rev-surprise-ge6pct-fq3-2027` | earnings | 2026-11-25 | 1.62 | 1.463%p | 0.09 | 0.0819 | — |
| 4 | `nvda-rev-miss-fq3-2027` | earnings | 2026-11-25 | 3.17 | 1.463%p | 0.05 | 0.0475 | — |
| 5 | `avgo-eps-surprise-ge5pct-fq4-2026` | earnings | 2026-12-18 | 2.17 | 1.239%p | 0.08 | 0.0736 | — |
| 6 | `avgo-eps-miss-fq4-2026` | earnings | 2026-12-18 | 2.67 | 1.239%p | 0.06 | 0.0564 | — |
| 7 | `nfp-dec2026-below-neg75k` | macro | 2027-01-08 | 1.53 | 95,000명 | 0.09 | 0.0819 | — |
| 8 | `fedfunds-upper-450-2026-12-09` | macro | 2026-12-09 | **0.810** | 0.267%p | 0.07 | 0.0651 | **2/3** |
| 9 | `vix-40-touch-by-2027-01-15` | volatility | 2027-01-15 | 2.18 | 6.553 | 0.08 | 0.0736 | — |
| 10 | `vix-above20-40days-by-2027-01-15` | volatility | 2027-01-15 | 1.60 | 20.015일 | 0.11 | 0.0979 | — |
| 11 | `t10y2y-100bp-by-2027-01-15` | market-regime | 2027-01-15 | 1.74 | 0.230%p | 0.06 | 0.0564 | — |
| 12 | `nasdaq-comp-30000-close-2027-01-15` | market-regime | 2027-01-15 | **0.954** | 0.08117(로그) | 0.17 | 0.1411 | **3/3** |

**포트폴리오 기대 Brier 바닥 평균 = 0.0784.** 문항별 상한 0.21 초과 0건 · 사구간 `[0.235, 0.765]` 진입 0건 ·
market-daily 0건 · 마감 전부 계약 상한 2027-01-15 이하.

## 2. 계약 훅 판정 — 12/12 통과

`ai_fc.portfolio_prereg.evaluate_batch(contract, candidates)` 를 등록 직전에 12건 전부에 돌렸다.
거부 0건. 훅은 원장을 읽지 않으므로 이 판정에 성적이 개입하지 않는다(테스트로 고정: `test_module_never_reads_the_ledger`).

**기계적 슬롯 소모 2/3 · 계약 기록 3/3.** 훅은 `z < 1.0 또는 기대 Brier > 0.21` 일 때만 슬롯을 청구하므로
`adbe-eps-above-guide-top-fq4-2026`(z=1.040, floor 0.1275)은 **슬롯 없이 통과**한다. 계약은 그럼에도
`n=4` 표본이 얇다는 이유로 이 문항에 슬롯 1개를 **자발적으로** 청구해 두었다. 즉 등록은 훅보다
**한 칸 더 보수적인 쪽**으로 기록됐다 — 반대 방향(훅이 요구하는 슬롯을 계약이 면제)은 없다.

## 3. 어느 문서의 숫자를 정본으로 썼는가

세 문서(후보 초안 3종 · `SELECTION.md` · 계약)가 같은 문항에 다른 숫자를 준 곳이 있다.
사후에 "왜 이 값을 골랐나"를 다투지 않도록 규칙을 먼저 적고 그대로 적용했다.

| 필드 | 정본 | 이유 |
|---|---|---|
| `z` (예외 3건) | **계약** `exception_slot_assignments` 의 실효 z | 계약이 결과 전 커밋됐고 초안 z 보다 보수적이다 |
| `z` (나머지 9건) | 후보 초안 | `SELECTION.md §0` 이 "산술 오류 0건, 전 후보 z 재현" 으로 검증 완료 |
| `honest_probability_estimate` | **`SELECTION.md §1`** (예외 3건은 초안) | 재검증 패스의 값 |
| `sigma` · `sigma_source` | 후보 초안 (원 출처 경로·표본 명시) | `SELECTION.md` 는 요약만 싣는다 |
| `deadline` | 후보 초안 | `SELECTION.md` 는 일부를 계약 상한 2027-01-15 로 정규화했으나, 발표일 기반 상한이 더 정확하다(전부 계약 상한 이하) |

**적용하지 않은 것 — `SELECTION.md §5-1` 권고 교정.** 검증은 정직확률 3건의 상향/하향을 권고했다
(`vix-40-touch` 0.08→0.13 · `t10y2y-100bp` 0.06→0.09 · `fedfunds-upper-450` 0.07→0.04).
등록값은 바꾸지 않고 해당 질문의 `prereg.reference_class_correction` 에 **병기**했다.
근거: ① 권고는 승인 대상 목록에 포함되지 않았고, ② 어느 값을 써도 채택/거부 판정이 바뀌지 않는다
(0.13 의 바닥 0.1131 · 0.09 의 바닥 0.0819 — 둘 다 문항 상한 0.21 아래).
숫자를 조용히 갈아끼우는 대신 둘 다 보이게 뒀다.

## 4. 각 질문 파일에 기록된 것

계약 `z_rule.required_fields_on_registration` 4필드는 전 12건의 `prereg` 블록에 있다
(`z` · `sigma` · `sigma_source` · `honest_probability_estimate`). 추가로:

- `center_estimate` — z 의 분자를 사후에 재현할 수 있게 한다.
- `z_draft` · `z_note` (예외 3건) — 초안 z 와 실효 z 가 왜 다른지.
- `correlated_with` · `correlation_note` — NVDA 2건·AVGO 2건은 **같은 컨센 스냅샷을 공유**해 동시 void 되고,
  VIX 2건은 같은 vol-regime 드라이버를 탄다. 게이트 DISTINCT 로는 12문항이지만 유효표본은 그보다 작다.
- `known_inconsistency` (`fedfunds-upper-450-2026-12-09`) — 기등록 `fedfunds-upper-425-2026-12-09`(예상 12%)와
  함께 보면 `P(3회째|2회)=58%` 를 함의한다. **기등록 질문은 무수정**이고 이 사실만 기록한다(사용자 결정).
- `threshold_note` (`vix-above20-40days`) — 40일 임계를 고른 근거가 결과가 아니라 사구간 밖 + 시대 간 추정 일치임을 명시.
- `preflight` 3항목 — 2026-09-10 컷오프 이후 등록분 필수. 창형 4건은 창 시작이 **2026-09-11**(등록일 다음 날)이라
  등록 시점에 창 안 관측이 0이고, 종점형 8건은 판정 대상 발표·세션이 전부 미래다.

**정적 점검 결과**: `c5_certificate.question_preflight` 결함 후보 5건은 **전부 기등록 질문**이며 신규 12건은 0건.
`registry.factory_filter_violation` 위반 0건(12건 모두 notes 에 `등록필터:` 근거 기재).

## 5. 하지 않은 것 · 남은 결정

- **예측 0건.** `forecasts/` diff 0 · `calibration/ledger.csv` diff 0 · 게이트 SQL·문턱 무변경.
- **r1 실행은 지시 대기.** 12건 × (r1 + D-3) = 24회차, 표준 8건·경량 4건 배분으로 대략 $50~78.
  자동 배치로 태우지 않는다.
- **`adbe-eps-above-guide-top-fq4-2026` 은 r1 시점 제약이 있다.** 임계 `G_high` 는 2026-09-10 장후
  FQ3 2026 실적 발표에서 처음 공표되므로, 그 이전에 r1 을 실행하면 스냅샷할 수치가 없다.
- **`nfp-dec2026-below-neg75k` 의 마감 2027-01-08 은 BLS 일정 추정치**다(2027-01-01 이 금요일·공휴일).
  판정 규칙은 실제 발표일 기준으로 쓰여 있어 일정이 바뀌어도 질문은 유효하다.
- **`vix-40-touch` 와 `vix-above20-40days` 는 유효표본 2 가 아니라 1.5 에 가깝다**(SELECTION.md §5-2).
  게이트 분모는 2를 세지만 이 사실을 분모의 크기와 혼동하지 않는다.

## 6. 재현

```bash
cd C:/workspace/ai-investing/src
PYTHONUTF8=1 python -m ai_fc sync --check        # 질문 79 / 예측 56 / 해소 11
PYTHONUTF8=1 python -m ai_fc inventory --check
PYTHONUTF8=1 python -m pytest tests/test_portfolio_prereg.py tests/test_c5_preflight.py -q
```
