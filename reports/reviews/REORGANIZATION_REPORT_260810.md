# 검토 산출물 구조화 및 무결성 보고서 (2026-08-10)

## 결과

검토 ZIP과 동결 검토 자료를 `reports/reviews/` 한 곳으로 통합했다. 공개 검토 ZIP 13개와 로컬 전용 검토 ZIP 7개를 포함한 검토 ZIP 20개가 모두 이 트리 아래에 있으며, 전체 20개가 ZIP CRC 검사를 통과했다. 원천데이터 ZIP 6개는 모델 입력이므로 `dualdb/data/raw/`에 그대로 유지했다.

## 최종 구조

| 경로 | 용도 | 수량 |
|---|---|---:|
| `current/scenario_v4/` | V4 PR3 현재 문서 전달 번들 | manifest 항목 10개 + manifest |
| `current/scenario_v5/` | V5 현재 delivery ZIP 및 SHA-256 | ZIP 1개 |
| `current/scenario_v5_1/` | V5.1 현재 최종 검토 ZIP 및 SHA-256 | ZIP 1개 |
| `current/scenario_v5_2/` | V5.2 현재 최종 검토 ZIP 및 SHA-256 | ZIP 1개 |
| `archive/packages/` | 과거 공개 검토 ZIP 및 신규 SHA-256 sidecar | ZIP 10개 |
| `archive/extracted/` | 검토 provenance를 위한 동결 해제본 | 디렉터리 4개, 파일 507개 |
| `archive/local_only/` | Git 비추적 로컬 검토 자료 | ZIP 7개 + 문서 4개 |

`INDEX.json`은 공개 ZIP 13개의 경로, 바이트 크기, SHA-256, ZIP 멤버 수, CRC 및 sidecar 상태를 결정적으로 기록한다. `archive/local_only/`는 의도적으로 공개 인덱스와 Git 추적 대상에서 제외한다.

## 이동 매핑

| 이전 위치 | 현재 위치 |
|---|---|
| 저장소 루트의 V4 PR3 delivery 디렉터리 | `reports/reviews/current/scenario_v4/` |
| 저장소 루트의 V5 delivery ZIP | `reports/reviews/current/scenario_v5/` |
| 저장소 루트의 V5.1 review ZIP/sidecar | `reports/reviews/current/scenario_v5_1/` |
| 저장소 루트의 V5.2 review ZIP/sidecar | `reports/reviews/current/scenario_v5_2/` |
| `reports/review_packages/`의 공개 ZIP | `reports/reviews/archive/packages/` |
| `reports/review_packages/`의 해제본 | `reports/reviews/archive/extracted/` |
| `reports/audit/_local_only/` | `reports/reviews/archive/local_only/` |

V5와 V5.2 생성기도 앞으로 저장소 루트가 아니라 각 `current/` 경로에 직접 ZIP과 sidecar를 생성하도록 변경했다. 과거 공개 ZIP 10개에는 현재 바이트 기준 SHA-256 sidecar를 추가했다.

## 중복 및 보존 판단

- `archive/packages/` ZIP과 `archive/extracted/` 해제본의 공존은 삭제 대상 중복이 아니라 과거 검토 시점의 provenance 보존이다.
- `prompts/scenario_v4/`의 실행용 정본과 V4 전달 번들 내부의 동결 사본은 역할이 다르므로 둘 다 유지했다.
- official snapshot, ledger 및 데이터 archive는 이동·수정·삭제하지 않았다.
- `.tmp`, `_site`, 저장소 내 비추적 `__pycache__`/`.pytest_cache` 등 재생 가능한 캐시·미리보기 디렉터리 23개를 제거했다.

## 검증 결과

- 대상 테스트: `59 passed in 11.62s`
- 전체 테스트: `458 passed in 154.49s`
- 전체 ZIP CRC: `26/26 PASS` (검토 20, 원천데이터 6)
- V4 manifest: `10/10 PASS`
- V5 manifest: `46/46 PASS`
- V5.2 manifest: `100/100 PASS`
- 공개 ZIP sidecar: `13/13 verified`
- 보호 대상 비교: added `0`, removed `0`, changed `0`
- 보호 manifest SHA-256 before/after: `d2b096f95e34cbd7836e3da9988b590694e3af70e5acd3fb33abaffc5c7ae73b`

## 현재 패키지 해시

| 패키지 | SHA-256 |
|---|---|
| V5 | `4a3f7b2c8881d80f96da7c6260bcf50173d028bd1881b0f8ae1597565082cc83` |
| V5.1 | `3558b9f43cbe892934e1e4f6cca0ccf3f5cad875f1be4dc41f39155431827247` |
| V5.2 | `d6b6f18e1174c64393334fd75f45c504940782394e0d6ecce24401c255e87f40` |

이 구조화 작업은 source-control publication이나 모델 승격을 수행하지 않는다.
