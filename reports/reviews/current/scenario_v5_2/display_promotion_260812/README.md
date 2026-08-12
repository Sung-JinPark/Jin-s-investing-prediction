# Scenario V5.2 route-governance remediation review pack

기준 시각: 2026-08-12 16:26 KST  
기준 커밋: `d4f140a867ca4cdcf7d357daf57bdbe6e75236eb`  
작업 브랜치: `codex/route-governance-remediation`

## 판정

- H1 payload/fixture/semantic reference: **PASS**
- H2 display-promotion contract: **PASS — 운영자 승인 영수증 연결 완료**
- H3 Playwright render evidence: **PASS, 15 routes × 2 viewports = 30/30**
- H4 generator separation and projection preservation: **PASS as shadow/report-only**
- Full repository regression: **PASS, 485 tests**
- Protected official snapshot/ledger/archive: **PASS, changed 0 / added 0 / removed 0**
- Commit/push/PR/merge/live deploy: **승인 완료, 이 팩 봉인 후 순차 실행**

표시 승격 6개 게이트가 모두 통과하여 `#future` 기본값은 V5.2 연구 후보입니다. 이는 champion 모델 승격이나 공식 확률 변경이 아니며, 후보가 blocked되거나 게이트가 소실되면 기본값은 즉시 champion으로 자동 회수됩니다.

## 핵심 실측

| 게이트 | 실측 | 결과 |
|---|---:|---|
| embedded HTML | 881,860 / 900,000 bytes | PASS |
| `future_paths.json` | 156,529 / 240,000 bytes | PASS |
| 3개월 표시 관측치 | 14 | PASS |
| 방향 run S1/S2/S3 | 3 / 11 / 5 | PASS |
| 3개월 종점 S1/S2/S3 | +13.251% / -0.298% / -13.169% | PASS |
| S1–S3 종점 분리 | 26.421%p | PASS |
| 에피소드 구간 교집합 | 0 | PASS |
| residual pool 고유 수 | 3 | PASS |
| Playwright 캡처 | 30/30, 오류 0, overflow 0 | PASS |

상세 내용은 `AUDIT_REPORT.md`, 원문 테스트는 `tests/full_suite.xml`, 렌더 원문은 `screenshots/render_manifest.json`, 보호 비교는 `evidence/protected_hash_comparison.json`을 참조하십시오.
