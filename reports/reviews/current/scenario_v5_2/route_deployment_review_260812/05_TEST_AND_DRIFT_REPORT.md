# 테스트 및 후속 데이터 드리프트 보고

## 기능 커밋의 독립 검증

| 대상 | 결과 | 증거 |
|---|---:|---|
| PR #14 verify | success | run 31550831270 |
| PR #15 verify | success | run 31551045637 |
| PR #16 verify | success | run 31552908335 |
| PR #15 Pages | success | run 31551138626 |
| PR #16 Pages | success | run 31552987704 |
| 로컬 기능 집중 테스트 | 69 passed | 기능 병합 직전 실행 기록 |
| 로컬 정적 Pages 빌드 | success | `static_build/` 동봉 |
| 라이브 DOM/SVG 검증 | success | `live/live_validation.json` |

## 현재 HEAD 재검증

현재 HEAD `19e58b7`에서 같은 집중 테스트를 다시 실행한 결과는 66 passed / 3 failed이다. JUnit 원문은 `evidence/targeted_tests.xml`에 동봉했다.

### F1 — 대시보드 임베드 용량 초과

- 실제: 1,025,511 bytes
- 계약: 1,025,000 bytes
- 초과: 511 bytes
- 분류: 후속 데이터 누적에 따른 payload budget 회귀

### F2 — stale 날짜 fixture 불일치

- 테스트는 2026-08-13에 candidate가 stale일 것으로 고정했다.
- 자동 데이터 갱신 후 candidate `as_of`는 2026-08-12이므로 해당 날짜에 `degraded`이면서 표시 가능하다.
- 분류: 데이터 cadence 이후 낡은 시간 고정 fixture

### F3 — method change hash 불일치

- append-only 기록의 r7 candidate hash: `af81a99886090687ec6b0a4da27c58017837a5bae2a3b01f329c399e8be81bd8`
- 현재 candidate model hash: `acf91105f215ea6f33528068af00cef5ffcfc546f25dedd9603e885272d86bce`
- 분류: 새 candidate refresh에 대응하는 append-only provenance 연결 검토 필요

## 분리 근거

- 기능 종료 merge: `3e3578b`
- 후속 데이터 refresh: `60b4d4d`
- source monitoring: `19e58b7`
- 기능 구간 `5dc1e14..3e3578b`의 보호 데이터 diff는 0개다.
- 현재 실패는 `3e3578b..19e58b7` 구간에서 candidate·calibration·archive가 갱신된 뒤 재현된다.
