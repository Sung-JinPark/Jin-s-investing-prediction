# 푸시 전 적대적 검토(2026-09-08) — 발견 24건과 처리 (PR #167 정정 배치)

> 방식: 5렌즈(governance·numerics·display·ci·tests) 독립 검토 → 발견마다 3명 반박 검증(2/3 미반박 = 확정).
> 1차 실행은 세션 한도로 57/77 에이전트 실패(확정 1건만 산출) → 16:20 리셋 뒤 `resumeFromRunId` 재개 → **77/77 완료, 오류 0**.
> 최종 판정: **확정 5 / 반박 19** (24건). 확정 5건 = #1 영수증 시각(2/3), #2 band80 좌표(3/3), #3 홀드아웃 FAIL 페일클로즈(3/3),
> #9 계약 status·레지스트리 stale(2/3, 문서 수준), #10 라이브 전진 게이트 미사전등록(3/3). 반박된 19건 중 다수도 작성자가
> 방어적 보강으로 함께 고쳤다(표의 '처리' 열). 확정 5건은 전부 정정 커밋에 반영됨(HEAD 8243e1f0 기준 판정 → 정정 후 재검증 대상).

| # | 렌즈 | 발견 | 심각도 | 처리 |
|---|---|---|---|---|
| 1 | governance | V13-D4/D5 승인 영수증 `approved_at` 15:05 이 합성 시각 — 무장(14:54)·라이브(14:54)·T3(14:58) 보다 뒤 | medium (**3/3 확정**) | **정정 행 r2 append**(실제 동의 = 계획 승인 14:14:41 + 선택 13:53:55, 집행 시각 기록), 계약 포인터 r2, 영수증 비미래·supersede 테스트, DECISIONS 정정, method_changes r28. 교훈: 시각은 이벤트 기록에서만 |
| 2 | numerics | `block_bootstrap_cov` 재표집 재표준화 → 동결 μ/σ 좌표와 불일치, band80 과대(15~140%) | medium | **고정 표준화로 수정 + 재동결**(sha 51815bde→1a857850, 반창 대사 2e-15 동일, p 무변경, 대역 축소). 스케일 불변 테스트 |
| 3 | display×2 | 홀드아웃 FAIL 이 페일클로즈되지 않음(표시·가드 모두) | medium | 표시: `holdout_status: fail` → hold, `partial` → `holdout_fail_cells` 제거(전부면 hold). 읽기모델 가드 '홀드아웃 실패 후 숫자 금지'. JS '홀드아웃 실패' 라벨. 테스트 |
| 4 | display×2 | 계약 `gates.armed` 를 빌드 시점에 재확인하지 않음 — disarm 해도 다음 파이프라인 실행 전까지 숫자 유지 | medium/low | 빌드 시 계약 `armed` 재확인 → hold(`contract_disarmed_at_build`). 테스트 |
| 5 | display | 비-dict 포인터(null/list/gate=5) 가 AttributeError 로 빌드 중단 | low | isinstance 검사 + AttributeError 포착 → hold. 테스트(3 케이스) |
| 6 | numerics/tests | 같은 as_of 재발행 시 포인터 재작성·원장 미추가 → `pointer_content_hash` 괴리, verify 미검출 | low/medium | run_id = as_of + 계수 sha8(같은 계수=멱등, 재동결=새 행). verify 가 원장↔포인터 셀(p·band80)을 내용으로 교차검사. 테스트(멱등·재동결·변조 검출) |
| 7 | ci | 라이브 cron(03:40 UTC) 이 V2 refresh 완료를 보장하지 않음 → 지연 시 stale 로 hold 전환 | medium | `workflow_run: timeseries-v2-refresh completed` 1차 트리거 추가(cron 은 보조) |
| 8 | ci | `vol_live` 원장 cadence trading_daily + as_of(구조적 T-1) → 만성 stalled(경고) | low | `timestamp_field: knowledge_cutoff` |
| 9 | governance | 계약 `status: draft_prereg`·MODEL_REGISTRY 'candidate' 가 T3 라이브와 불일치 | low | `status: live_reference`, 레지스트리 행 갱신 |
| 10 | governance | 표시 설계서 §5 라이브 전진 자동 게이트가 사전등록되지 않은 채 결과 축적 시작 | low | 계약 `live_forward_gate` 사전등록(성숙 원점 ≥60·CI90·y-block·강등 규칙·verb 부재). 첫 원점 성숙(≥2026-09-11) 전 고정. 테스트 |
| 11 | tests | `paired_model_ci` 부호 테스트가 동일 피처라 a/b 뒤바뀜을 못 잡음 | medium | 정보 피처 vs 잡음 피처로 교체(양방향 우세·뒤집힘·동일) |
| 12 | tests | pipeline.py 테스트 0건 | medium | `test_timeseries_v13_pipeline.py` 신설: 미무장 hold·live 9셀·멱등·재동결 새 행·verify 교차검사·stale·신선도 helper(월요일/연휴/토요일/장중) |
| 13 | tests | `build_read_model` 이 V13 로더에 `now` 를 넘기지 않음 | medium | `now=now` 전달 |
| 14 | tests | rung-3 결과 json 이 바이트 핀 안 됨 | medium | design_evidence.persistence_pb 핀 + 원장 `results_sha256` 대조 테스트 |
| 15 | tests | 무장/티어와 승인 영수증 연결 테스트 없음 | medium | `test_arming_and_display_tier_are_backed_by_non_superseded_receipts` |
| 16 | tests | 모듈 수준 `importorskip` 이 ImportError 를 스킵으로 은폐 | low | 직접 import 로 교체(pandas 만 개별 skip) |
| 17 | tests | 표시 테스트가 존재하지 않는 `market_calendar.yaml` 복사 → 달력 부재 분기 미검사 | low | 실제 `nyse_holidays.yaml` 복사, 달력 부재 → hold 테스트, NOW 주석(노동절 다음 화요일) 정정 |
| 18 | tests | 워크플로 allowlist 미고정 | low | `test_live_workflow_commits_only_the_contract_declared_live_outputs` |
| 19 | tests | 읽기모델 가드 3분기 미검사 | low | 테스트 추가(visibility/status·research_reference·malformed cell) |
| 20 | tests | freshness.py 직접 단위 테스트 없음 | low | pipeline 테스트 파일에 4케이스 |
| 21 | governance | 실험 원장 content_hash 직렬화가 rung-1/2(기본 구분자)와 rung-3(compact) 불일치 | low | **미수정(기록만)**: 각 행은 자기 규약으로 자기정합, canonical_hash 규약(compact)이 정본. 향후 원장 검증기는 두 규약 모두 수용 |
| 22 | display | JS 가 fail 을 '미검증' 으로 표기 | low | #3 과 함께 수정 |
| 23 | (기존) | `dashboard.py:290 qmap` 미사용 변수(ruff) | — | 이 PR 범위 밖(기존 코드) — 미수정 |
| 24 | ci | 첫 CI 에서 `champion_coefficients.json` frozen 등록이 violation 이 되는가 | — | 아니다: 매니페스트에 없는 파일은 위반이 아니라 등록(그 뒤 변경만 위반). 재동결은 매니페스트 갱신(scenario-refresh 쓰기 모드) 전이라 안전 |

전체 테스트: 정정 전 1,109 통과 → 정정 후 재실행(진행 중, PR 갱신 전 확인). 봉인 V8/V2 0바이트 유지.
