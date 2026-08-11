# Scenario V5.3 UI Remediation — Acceptance Evidence Report

기준일: 2026-08-11 KST

기준 HEAD: `0868b8746be3fb560610060b8bf92b0ba21182cf`

작업 브랜치: `codex/v53-evidence-remediation`

배포 상태: 로컬 검증 완료 후 증거 팩 작성 단계. 이 작업에서는 commit·push·PR·merge·배포를 수행하지 않았다.

## 판정

사용자 검토의 P0-B는 사실이었다. 기존 `renderFlow`는 `ok` 또는 `degraded`인 Scenario V5.2를 `#future`에서 먼저 렌더링해, 승격 게이트를 통과하지 못한 연구 후보가 고객 기본 전망을 사실상 점유했다.

시정 후 계약은 다음과 같다.

- `#future`: champion `gbm-daily-252d-v2-lookup`, snapshot `nasdaq-scenario:2026-08-07:r1`
- `#future/research`: Scenario V5.2 연구 후보 전용 보기
- V5.2 고정 공시: 적격 사건 1/60, band calibration 3/60, walk-forward 미승인, 사람 승인 `run_id` 없음, `degraded`, 보정되지 않음
- V5.2는 `NOT_OFFICIAL_NOT_CHAMPION`, `champion_eligible=false`

## 항목별 시정과 증거

| 항목 | 파일 | 변경 요지 | 검증 | 판정 |
|---|---|---|---|---|
| P0-A 전체 증거 팩 | `scripts/build_scenario_v5_3_acceptance_evidence_pack.py` | 소스·patch·정적 빌드·data snapshot·파일별 manifest·스크린샷·원시 로그를 단일 ZIP에 수록 | ZIP CRC, 내부 `MANIFEST.json`, sidecar SHA-256 | 충족 |
| P0-B champion 기본 | `src/ai_fc/dashboard_parts/dashboard.js` | 기본 `sc`를 `DATA.scenario`로 고정하고 V5.2는 `modelView=research`일 때만 렌더링 | 브라우저 `#future`, `#future/research`; 계약 테스트 | 충족 |
| 연구 후보 배너 | JS/CSS, V5.2 projection | 1/60·3/60·승인 상태를 닫을 수 없는 상단 배너로 표시 | 브라우저 QA JSON·1280/390 PNG | 충족 |
| P1-A 방법 일지 | `data/method_changes.jsonl` | 실제 2026-08-10 기본 노출과 2026-08-11 champion 복원을 append-only 2개 revision으로 기록 | 순서·`supersedes` 테스트 | 충족 |
| P1-B 과정밀 억제 | dashboard JS | 네 결과 비율을 정수 %로 표시하고 “보정되지 않은 모의 경로 비율” 공시 | 브라우저 실측 73/83/93/29 | 충족 |
| 가산 잔차 의미 | dashboard JS | `정의상 0`, 항등 분해이며 독립 적합도 검증이 아님을 표시 | 문자열 계약·브라우저 QA | 충족 |
| 정직 장치 생존 | dashboard read model·schema·tests | method changes, band calibration, tracker, calendar, cross-asset, liquidity, history, path realism, horizon coverage 유지 | 생존 테스트·표 | 충족 |
| 구 해시 | dashboard JS·tests | 15개 legacy hash를 canonical route로 보존 | 브라우저 15/15 | 충족 |
| 닷컴 0.60 | V5.2 projection·UI | 승인 계약, receipt, dependency cap 0.60, 계산 감도와 0.40/0.60/0.80 정책 공시 | 0.80은 cap 초과로 계산·적용 차단 | 충족 |
| S2 표본 | V5.2 projection·UI | source 100, 선택 군집 n=16, 모의 3,000경로 표시 | projection 테스트·브라우저 실측 | 충족 |
| 시간축 배분 | dashboard JS/CSS | piecewise X축으로 과거 25%, 전망 75%; 구간 배경과 경계 표시 | SVG data contract·PNG | 충족 |

## 승격 4조건

| 조건 | 현재 | 요구 | 통과 |
|---|---:|---:|---|
| 직접 사건 관측 | 1 | 60 | 아니오 |
| band calibration | 3 | 60 | 아니오 |
| 승인된 walk-forward | 없음 | 승인 결과 | 아니오 |
| 사람 승인 원장 `run_id` | 없음 | 유효한 run_id | 아니오 |

이 표 때문에 V5.2는 연구 후보로만 남는다. UI 배지는 이 상태를 바꾸지 않는다.

## 닷컴 강도와 민감도

- 승인 계약: `data/scenario_views/approved/scenario_v5_2_dotcom_upside_260810.json`
- 활성 강도: S1 `0.60`, S2 `0.00`, S3 `0.00`
- dependency cap: `0.60`
- 계산 완료 감도: `0.28`, `0.45`, `0.60`
- 요청 비교값 `0.40`: cap 이내지만 현재 산출물에서는 비활성·미계산
- 요청 비교값 `0.80`: cap 초과이므로 계산·적용하지 않음

이는 사용자가 요구한 0.4/0.6/0.8 병기와 기존 사전등록·dependency cap 계약을 동시에 지키는 공시다.

## 브라우저 실측

- 1280×720, 390×844에서 오늘·기본 미래·연구 미래·기록·신뢰·교차자산·유동성 7개 화면 캡처
- 두 viewport 모두 document-level 가로 넘침 없음
- 모든 화면에서 `NaN`·`Infinity` 표시 없음
- 연구 차트 SVG: log scale, history share 0.25, forecast share 0.75
- 연구 결과: 73%, 83%, 93%, 29% 정수 표기
- S2: 역사 군집 n=16, 모의 3,000경로
- legacy redirect: 15/15 통과

원문은 `reports/screenshots/v53_acceptance_260811/browser_qa_results.json`과 `legacy_route_results.json`에 있다.

## 보호 범위

공식 snapshot·ledger·archive의 파일별 SHA는 변경 전후 동일하다.

- 보호 파일 수: 112
- manifest SHA-256: `d2b096f95e34cbd7836e3da9988b590694e3af70e5acd3fb33abaffc5c7ae73b`
- 변경·추가·삭제: 0/0/0

`data/method_changes.jsonl`은 방법 변경 원장이지만 V5.2 보호 manifest의 공식 forecast snapshot·ledger·archive 범위에는 포함되지 않는다. 기존 행은 수정하지 않고 새 행만 append했다.

## 테스트 결과

- 정적 빌드: 통과
- JavaScript 구문 검사: 통과
- targeted pytest: 74 passed
- 전체 pytest: 462 passed
- `git diff --check`: 통과
- ZIP CRC: 통과

첫 `uv` 실행은 실행 파일이 PATH에 없어 시작하지 못했다. 의존성을 변경하지 않고 기존 Python 3.12 환경으로 재실행했으며, 이는 코드 실패와 분리해 `ENVIRONMENT_NOTES_260811.txt`에 기록했다.

## 한계

- V5.2의 1/60 및 3/60 표본은 승격에 부족하다.
- 0.40 민감도는 사용자 요청 공시값이지만 현재 사전 계산 표에는 없어 숫자 결과를 만들지 않았다.
- 0.80은 dependency cap 때문에 의도적으로 미산출이다.
- 라이브 GitHub Pages 반영은 이 로컬 작업 범위에서 수행하지 않았다.
