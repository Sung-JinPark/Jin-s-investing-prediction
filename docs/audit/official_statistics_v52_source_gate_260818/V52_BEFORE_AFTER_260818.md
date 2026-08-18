# Scenario V5.2 source-gate before/after

비교 기준:

- Before: Git HEAD의 candidate model hash `8d01c5a03a37669b03412c8c847002d9e28fad3b871602f76c94fde7dd7ad32a`
- After: worktree candidate model hash `99d3d500775e81ed38371e6d02ffa3a025c80544f48d7e87bf68965f4d2655a5`
- 단위: probability와 score는 저장 fraction. 표의 `%`만 표시 경계 변환이다.

## 1. evidence score

| 항목 | Before | After | 변화 원인 |
|---|---:|---:|---|
| labor growth-risk bounded score | 0.738149 | 0.478780 | private consensus surprise를 제거하고 BLS actual level/revision/layoff만 사용 |
| policy-relief bounded score | 0.557133 | 0.000000 | Investing.com-derived rate distribution을 source receipt 미승인으로 차단 |
| cross-asset bounded score | 0.310411 | 0.000000 | AP/secondary aggregator state를 source receipt 미승인으로 차단 |
| private payroll consensus numerical use | 사용 흔적 존재 | false | narrative-only |

## 2. full-evidence 결과

| metric | Before | After | delta |
|---|---:|---:|---:|
| P(2026 terminal > anchor) | 78.1994% | 72.7018% | -5.4976%p |
| P(-10% first touch by Oct end) | 16.0141% | 20.4485% | +4.4344%p |
| P(2027 terminal > anchor) | 81.3781% | 76.5401% | -4.8380%p |
| S1 cohort mass | 74.9706% | 69.2164% | -5.7542%p |
| S2 cohort mass | 13.7829% | 15.1927% | +1.4097%p |
| S3 cohort mass | 11.2464% | 15.5909% | +4.3445%p |

After의 prior-only와 labor-only/labor+rate/full-evidence:

| view | P(2026 terminal > anchor) | P(-10% touch) | P(2027 terminal > anchor) |
|---|---:|---:|---:|
| prior-only | 73.7146% | 18.7846% | 77.4807% |
| labor-only | 70.4122% | 21.4837% | 73.3572% |
| labor+rate | 70.4122% | 21.4837% | 73.3572% |
| full-evidence | 72.7018% | 20.4485% | 76.5401% |

`labor+rate == labor-only`인 것은 승인된 authoritative rate receipt가 없어 policy score를 0으로 fail-closed 처리했기 때문이다.

## 3. 구조 경로는 유지

- S1 dotcom strength 0.60, S2/S3 0.
- S1/S2/S3 episode interval overlap 0.
- 63-session conditional p50 return: S1 +11.4478%, S2 -0.0295%, S3 -12.7556%.
- no exact October 2 forecast, no forced endpoint, no forced October direction, no fake p50 wiggle.
- direct event return kernel은 `REFERENCE_ONLY_INSUFFICIENT_N`, future event jump 0.

## 4. 남은 HOLD

| 항목 | 실측 | 상태 |
|---|---|---|
| hard-event eligible sample | 1 / preferred 60 / weak 30 | HOLD |
| distinctness threshold calibration | 0 / 30 trading days | HOLD |
| S1 origin minimum | 167 / 15 | PASS |
| S2 origin minimum | 16 / 20 | HOLD |
| S3 origin minimum | 29 / 12 | PASS |
| valuation/PER cross-era PIT | unavailable | HOLD |
| Fed rate authoritative receipt | absent | HOLD; numerical strength 0 |
| cross-asset authoritative receipt | absent | HOLD; numerical strength 0 |
| approval receipt ↔ official raw-receipt ledger binding | central policy/ledger/raw/URI/hash/time/source/series 전수 결합 | PASS |
| artifact source-mapping narrative consistency | `reference_only_blocked_unapproved_source_receipt` | PASS |
| official/champion promotion | `NOT_OFFICIAL_NOT_CHAMPION` | HOLD |

## 5. 검증 결과

`python -m ai_fc scenario-v5-2-verify`:

```json
{
  "ok": true,
  "errors": [],
  "candidate_id": "scenario_v5_2_scenario_clustered_db_v4",
  "model_content_sha256": "99d3d500775e81ed38371e6d02ffa3a025c80544f48d7e87bf68965f4d2655a5",
  "replay_checked": true
}
```

이 PASS는 artifact schema·수학·replay 검증이며 공식 승격 승인이 아니다.
