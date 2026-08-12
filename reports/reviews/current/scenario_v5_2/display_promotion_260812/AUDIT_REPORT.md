# H1–H4 audit report

## 변경·검증 매핑

| 항목 | 파일 | diff 요지 | 검증 | 판정 |
|---|---|---|---|---|
| H1-1 payload split | `src/ai_fc/dashboard.py`, `data/contracts/dashboard_payload.yaml` | V5.2와 미래 전용 5개 묶음을 `future_paths.json`으로 분리하고 기본 payload에는 상태·거버넌스·체크포인트만 유지 | `test_future_paths_are_split_with_semantic_identity_and_fixed_budgets` | PASS |
| H1-1 explicit failure | `src/ai_fc/dashboard_parts/dashboard.js` | fetch 실패 시 체크포인트 요약과 실패 배너; silent model fallback 금지 | 30-route render + source contract | PASS |
| H1-2 stale fixture | `src/tests/test_scenario_v5_2.py` | 고정 날짜가 아니라 candidate cutoff 이후 거래일을 계산 | `test_dashboard_projection_fresh_and_stale_fallback` | PASS |
| H1-3 semantic reference | `src/ai_fc/scenario_v5_2/artifact.py`, `data/method_changes.jsonl` | 불변 키를 candidate/model/rules version으로 변경, hash는 정보 필드로 강등 | `test_v52_method_changes_are_append_only_and_disclose_the_default_decision` | PASS |
| H2 governance | `data/contracts/display_promotion.yaml`, `src/ai_fc/display_promotion.py`, `data/display_promotions/approval_receipts.jsonl` | 공시·배너·운영자 승인·렌더 증명·runtime·semantic 6중 게이트, 실패 시 champion 기본값 | `src/tests/test_display_promotion.py` | PASS |
| H2 banner proof | dashboard JS/CSS + Playwright PNG | `연구 후보 · degraded · 적격 사건 1/60 · 보정되지 않음` 상시 표시 | `future-research__1280.png`, `future-research__390.png` | PASS |
| H3 capture backend | `tools/capture_dashboard_screenshots.py`, `pyproject.toml` | 직접 CDP를 제거하고 bundled Chromium Playwright 캡처·DOM·overflow·SHA manifest 생성 | `test_render_evidence_pipeline_uses_playwright_not_direct_cdp`, render manifest | PASS |
| H3 defects found | dashboard JS/CSS | deferred liquidity 모델의 잘못된 bind 차단, 390px method feed overflow 수정 | 30/30 render gate | PASS |
| H4 complete separation audit | existing V5.3 separation contract/candidate + new projection test | episode 교집합 0, 고유 residual pools, 경험적 phase, event adapter, display projection shape 검증 | `test_projection_preserves_direction_changes` + strict candidate suite | PASS/report-only |

## H1 실측

경로 배열 분리는 model/champion 변경이 아닌 전달 계층 변경입니다. `scenario_v5_2`, `scenario_v4_shadow`, `cross_asset`, `era_analog`, `liquidity`, `ai_regime` 상세를 단일 route payload로 이동했습니다.

- self-contained embedded HTML: 881,860 bytes (예산 900,000)
- Pages shell: 563,572 bytes
- base `data.json`: 318,479 bytes
- `future_paths.json`: 156,529 bytes (예산 240,000)
- route payload identity: `(scenario_v5_2_scenario_clustered_db_v4, complete_separation_empirical_episode_databases_v6, weights-v3+complete-separation-v1)`

## H2 표시 승격 상태

현재 통과: append-only disclosure, persistent banner, operator approval receipt, 1280/390 proof, candidate runtime, semantic reference.  
현재 미통과: 없음.

따라서 기본 라우트는 연구 후보이며 champion은 `#future/champion`에서 보존됩니다. 사용자 승인 원문은 append-only receipt와 method_changes r9에 연결했습니다.

## H4 재측정

- 기존 baseline S1–S2 p50 log-level correlation: 0.963
- 완전 분리 shadow: -0.965210
- 표시 계층 3개월 correlation: S1/S2 -0.701665, S1/S3 -0.939186, S2/S3 0.819410
- 3개월 표시: 14 points, 방향 run 3/11/5
- 종점: S1 +13.251%, S2 -0.298%, S3 -13.169%; S1–S3 26.421%p
- episode interval overlap 0, feature schema distinct true, unique residual pool 3, fixed phase false
- event adapter dependency cap: 0.35, 최대 절대 log-weight adjustment 0.147630, gate pass true, probability-only update false

이는 모델을 새로 승격한 결과가 아니라 기존 완전 분리 candidate를 동일 입력으로 재검증한 shadow/report-only 결과입니다.

## 보호 범위·SCM

candidate build receipt의 protected-before manifest와 현재 protected manifest는 동일합니다. manifest SHA는 양쪽 모두 `8a19adb89387ca208c93791166816cad79874f2e8a0b7fd2a456cc4471f1e3a7`입니다.

사용자의 일괄 승인을 받은 뒤 이 팩을 봉인했습니다. 로컬 `_site`와 Playwright 30개 렌더를 승인 상태로 다시 생성했으며, SCM·Pages 결과는 PR/배포 완료 후 최종 응답에서 별도로 보고합니다.
