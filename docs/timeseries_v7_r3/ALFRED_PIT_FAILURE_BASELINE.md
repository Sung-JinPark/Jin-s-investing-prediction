# NASDAQ V7 ALFRED/PIT 실패 기준선

## 판정

`V7R3-P0-001`은 성공했다. 이 성공은 모델 Gate 통과가 아니라, 기존 실패 run을 독립적으로 재현하고 변경 불가능한 감사 기준선으로 고정했다는 의미다.

- run: `v7-alfred-20260825T083047Z`
- 모델 상태: `HOLD_RESEARCH_GATE`
- 연구 Gate: 실패
- 고객 숫자 공개: 비활성
- 자동 배포·매매: 비활성
- 다음 task 착수: 안 함

## 입력 무결성

| 입력 | 검증 결과 |
|---|---:|
| ALFRED/PIT 리뷰 ZIP SHA-256 | `72192f9369ec6a43e563650629ea2fbd986aa2ca15d8fcd665d6deaec9ae4087` |
| `MANIFEST.sha256` | 112/112 일치 |
| `MANIFEST.json` 파일·크기 대사 | 일치 |
| 미등록·누락 파일 | 0 |
| 경로 탈출·중복 경로·symlink | 0 |
| 압축 폭탄 제한 | 통과 |

설계 패키지의 delivery manifest도 별도로 검증했다. 내부 13개 명세 파일의 SHA-256과 크기가 모두 일치하며, 그 manifest가 지목한 리뷰 ZIP SHA도 실제 입력과 동일하다.

## 독립 재계산 결과

감사기는 `ai_fc`의 Gate 구현을 호출하지 않는다. 리뷰 ZIP의 전체 4,082행 score Parquet를 직접 읽어 horizon별 평균 CRPS, coverage, 방향 정확도, Brier, stress 구간 및 stationary block-bootstrap CI를 다시 계산했다.

| Horizon | Score 행 | Model CRPS | E0 CRPS | Skill |
|---:|---:|---:|---:|---:|
| 1 | 1,025 | 0.0072763 | 0.0073896 | +1.5335% |
| 5 | 1,024 | 0.0161069 | 0.0154374 | -4.3371% |
| 21 | 1,021 | 0.0664669 | 0.0303314 | -119.1357% |
| 63 | 1,012 | 0.0634524 | 0.0515336 | -23.1282% |

저장값과 독립 재계산값의 최대 절대 차이는 `4.44e-16`으로, 허용 오차 `1e-12` 이내다. 연구 Gate는 저장값과 재계산 모두 실패다.

## 데이터·receipt 재현

| 항목 | 재계산 값 |
|---|---:|
| receipt | 23 |
| 성공 receipt | 23 |
| ALFRED API receipt | 11 |
| ObservationFact | 151,251 |
| `native_pit` 행 | 61,078 |
| `supersedes` 행 | 56,572 |
| PIT snapshot 행 | 7,712 |
| score 행 | 4,082 |
| 고유 origin | 1,025 |

모든 receipt가 가리키는 gzip raw body를 다시 풀어 SHA-256을 계산했다. 실패는 0건이다. ALFRED 인증 실행 판정은 11개 `fred/series/observations` 성공 receipt, redacted request parameter, request fingerprint, raw hash 및 pipeline의 network-call 기록을 근거로 한다. 실제 API key 값이나 `.secrets`는 읽지 않았다.

## 확인된 구조 결함

1. `origin_cutoff_at`이 canonical XNAS close가 아니라 NASDAQCOM의 휴리스틱 `available_at`에서 생성된다. 2026-08-24 정규장 fixture에서는 실제 close보다 4시간 늦다.
2. ALFRED date-only vintage가 `23:59:59 UTC`로 변환되지만 next-session 보수 정책을 증명하지 못한다.
3. ALFRED 수집은 `output_type=1`과 1990년 시작일로 전체 history를 반복 요청하며 incremental cursor가 없다.
4. 최종 snapshot에는 feature별 observation/revision lineage가 없고 행별 `max_available_at` 집계만 남는다.
5. 월·분기 거시 level을 거래일 행으로 투영한 뒤 `.diff(21/63/252)`로 변화량을 계산한다.
6. `label_ends`를 읽지만 purge eligibility에는 사용하지 않고 row index를 사용한다.
7. `research_train / candidate_selection / stacking / calibration / outer_test` 5개 역할 분리 증거가 없다.
8. 실행 E2는 true joint Student-t NLL이 아니라 Ridge location + Ridge log-absolute-residual + fixed df=5다.
9. E0 floor를 최소 비중이 아닌 고정 비중으로 사용하고 E2 remainder를 강제로 배분한다.
10. learned stacking과 cross-fit calibration은 score path에서 호출되지 않았다.
11. controller는 PostgreSQL lease·heartbeat worker가 아니라 append-only file journal 단일 cycle이다.
12. predecessor baseline은 기존 4개 파일 차이로 이미 실패 상태다. 이번 task는 그 파일을 수정하지 않았다.

## 보호·보안 결과

작업 전후 보호 범위의 파일별 크기·SHA-256 manifest를 계산했다. 추가·삭제·변경은 모두 0이며 content hash가 동일하다. 리뷰 팩과 생성 산출물에서 credential URL 및 자격증명 할당 패턴을 검사했고 실제 secret 발견은 0건이다. 보안 단위테스트의 명시적 fixture 문자열은 provider credential과 구분했다.

## 테스트

- V7-R3 독립 감사 적대적 테스트: **13 passed**
- 저장소 전체 회귀: **620 passed, 1 failed**
- 전체 회귀의 단일 실패는 `dualdb/tests/test_sentinels.py::test_ixic_coverage`다. 로컬 `^IXIC` 최종일이 2026-08-12여서 실행일 2026-08-26 기준 7일 freshness 조건을 충족하지 못했다. 이번 허용 경로 밖의 기존 DB 신선도 문제로 분류했으며, 데이터를 갱신하거나 테스트 기준을 낮추지 않았다.

## 산출물

- `outputs/timeseries_v7_r3/audit/alfred_pit_reproduction.json`: 전체 재현 결과와 line-level 증거
- `outputs/timeseries_v7_r3/audit/protected_manifest_before.json`
- `outputs/timeseries_v7_r3/audit/protected_manifest_after.json`
- `outputs/timeseries_v7_r3/audit/generated_artifact_secret_scan.json`
- `outputs/timeseries_v7_r3/task_results/V7R3-P0-001/result.json`: 실행 시간·명령·return code·assertion·artifact hash

`V7R3-P0-002` 및 모델 수정·재학습은 이 task에서 시작하지 않았다.
