# Phase 2 — triage 결과

탐지 74건 → **Tier 1 실행 27건 / Tier 3 보고 47건**

## Tier 1 — 삭제 대상 (27)

증거: ① ruff 0.16.5 출력 ② 전역 재export 검증 **위험 0건**
(각 F401 심볼에 대해 `from <module> import <symbol>` 형태의 외부 참조를 저장소 전역 검색 — 0건)
③ 전부 모듈/함수 로컬 스코프 (설계도 §3 카테고리 A, 기본 Tier 1)

| # | 파일:라인 | 심볼 | 규칙 |
|---|---|---|---|
| 1-2 | src/ai_fc/evaluation.py:6,7 | log, Iterable | F401 |
| 3 | src/ai_fc/official_data_workbook.py:11 | hashlib | F401 |
| 4 | src/ai_fc/orchestrator.py:11 | json | F401 |
| 5 | src/ai_fc/quant/runner.py:9 | datetime | F401 |
| 6 | src/ai_fc/quant/feed.py:256 | header | F841 |
| 7 | src/ai_fc/registry.py:268 | segments | F841 |
| 8-10 | src/ai_fc/statistics_lab.py:1176,2701,2765 | by_key, observation_through, generated_time | F841 |
| 11 | src/tests/test_quant.py:11 | summarize | F401 |
| 12 | src/tests/test_sprint1.py:8 | shutil | F401 |
| 13 | src/tests/test_ws2_benchmark.py:6 | date | F401 |
| 14 | src/tests/timeseries_v7/test_gate_feasibility.py:2 | pytest | F401 |
| 15-16 | src/tests/timeseries_v7/test_v7_control_plane.py:3 | datetime, timezone | F401 |
| 17 | src/tests/timeseries_v7/test_v7_pit_boundaries.py:5 | pytest | F401 |
| 18-20 | tools/ralph_v7.py:17 | GenerationEvidence, decide_generation, generation_input_hash | F401 |
| 21 | tools/finalize_v7_wait_data.py:8 | hashlib | F401 |
| 22 | tools/build_v7_replay_pack.py:9 | sys | F401 |
| 23 | tools/audit_v5_gate.py:26 | timezone | F401 |
| 24 | scripts/build_data_integrity_review_pack.py:7 | io | F401 |
| 25 | dualdb/dualdb/__main__.py:41 | json | F401 |
| 26 | dualdb/dualdb/ingest/seeds.py:27 | now | F841 |
| 27 | dualdb/dualdb/ingest/yahoo.py:62 | exc | F841 |

## Tier 3 — 삭제 금지 (47)

### (a) 감사 증명서에 해시 박제 — triage에서 적발한 false positive **2파일 / 3건**
| 파일 | 증거 |
|---|---|
| tools/verify_v7_protected.py (F401 ×2) | `outputs/timeseries_v7/task_results/V7-P0-002/ARTIFACTS.sha256`에 현재 sha256 기록됨 |
| tools/freeze_v7_contract.py (F401 ×1) | `outputs/timeseries_v7/task_results/V7-P0-003/ARTIFACTS.sha256`에 현재 sha256 기록됨 |

→ 수정 시 V7 감사 증명이 파손된다. **RED-LINE에 추가 권고.**

### (b) 미사용 인자 ARG001/ARG002/ARG005 — 43건
설계도 §5 회색지대: 인터페이스 구현·오버라이드·스텁·람다 시그니처의 미사용 인자는 유지.
대표: `src/tests/timeseries_v7/test_v7_worker.py`의 `lease` ×3(프로토콜 구현),
`tools/capture_dashboard_screenshots.py:25` `args`, `test_v7_collectors.py:133` 람다 `at`.

### (c) Tier 3 파일 내부 건 — 1건
`src/ai_fc/dashboard.py:215` `qmap` (F841) — dashboard.py는 `scenario_v5/audit.py`의
DELIVERY_PATHS 바이트 목록 + 다수 테스트가 소스 문자열을 grep → 보고만.

## Deferred (심볼 레벨, 이번 회차 미실행)
`config.py` 경로 상수 11개, `official_sources.py` `*_request` 5종, `data_contracts.py` 3종 —
`.claude/skills/*/SKILL.md`·문서가 참조하는 공개 표면일 가능성. 증거 3종 재수집 후 별도 회차.
