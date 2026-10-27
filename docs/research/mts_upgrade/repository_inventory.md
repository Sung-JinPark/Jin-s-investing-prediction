# MTS Research 저장소 인벤토리 (W0)

설계서 `docs/design/NASDAQ_forecasting_upgrade_design_20261026.md` §17.1·§20 W0 산출물.
작성: 2026-10-26 (KST). 모든 사실은 **이 worktree에서 직접 검증**했거나 출처를 명기했다.

## 1. 저장소·환경 실상태

| 항목 | 값 |
|---|---|
| repository root | `C:\workspace\ai-investing\worktrees\active\mts-research-upgrade` (worktree) |
| branch / HEAD | `claude/mts-research-upgrade` @ `0abe0a57` (origin/main에서 분기, 2026-10-26) |
| dirty 상태 | 신규 설계서 1건(untracked)만 — 기존 추적 파일 무변경 |
| 원고 기준 commit | `91f1c12f` — **origin/main의 조상임을 확인**(`merge-base --is-ancestor` exit 0). `91f1c12f..0abe0a57` 사이 MTS 계약·`src/ai_fc/timeseries*`·`data/timeseries*`·MODEL_REGISTRY 변경 **0건** → 원고의 코드·계약 전제 유효 |
| Python | 3.12.10 (CI도 3.12) |
| 의존성 | pyproject.toml extras만(lock 파일 없음). 실측: numpy 2.4.3 · scipy 1.17.1 · pandas 2.3.3 · statsmodels 0.14.6(핀) · pyarrow 24.0.0 · duckdb 1.5.5 · scikit-learn 1.8.0 · exchange_calendars 4.13.2 · pydantic 2.13.4. **arch·properscoring·hypothesis 없음**(채점기·검정은 자체 구현 — 설계서 부록 A 의도와 일치) |
| 설계서 반입 | 원본 `C:\Users\91ssj\Downloads\NASDAQ_forecasting_upgrade_design_20261026.md`(151,199 bytes) → `docs/design/` 복사, SHA-256 `3783b26cff2e29825e06dc2642878f1677f54cdf76aeec3fa94349873acd900b` 원본·사본 일치 확인 후 원본 삭제(= 로컬 원본 이동) |
| 내부 원고(설계서의 source_document) | `C:\workspace\ai-investing\outputs\explainers\multivariate_timeseries_explainer_20261026.md` (untracked, 1,250줄, SHA-256 `b5999e9b73650aede596ea736f850edef004b0ce6e68dd78a8451c5d0d57eb75`) — 읽기 전용 대조 자료로만 사용 |

## 2. 원고 경로 → 실제 상태 대응표

원고의 21개 경로 전부 실존(이 worktree 기준). 역할이 이름과 다른 곳만 주석.

| 원고 경로 | 상태 | 주석 |
|---|---|---|
| `docs/design/mts_program_blueprint_v1_260909.md` | 있음 | MTS 거버넌스 정본. §2 자원표는 2026-09-09 스냅숏(정본은 contracts+`tools/roadmap_status.py`) |
| `docs/MODEL_REGISTRY.md` | 있음 | V8=shadow_live·research_reference, V13-VOL champion=persistence_pb, V14=research only, daily6m 행 포함 |
| `data/contracts/multivariate_timeseries_v2.yaml` | 있음 | V2 동결 기반 엔진, sealed run 불변 벤치마크 |
| `data/contracts/multivariate_timeseries_v8.yaml` | 있음 | `frozen_for_sealed_evaluation`; purge 63/embargo 5; PIT 성숙 104(성숙 판정 68=63+5); s=0.5는 frozen_winner override |
| `data/contracts/multivariate_timeseries_v13_vol.yaml` | 있음 | `live_reference`(동결은 계수 artifact); 개발 예산 8/8 소진; 홀드아웃 1/3 슬롯, 셀 3/9 통과; V13-D13 제한 라벨 |
| `data/contracts/multivariate_timeseries_v14_conditional.yaml` | 있음 | `prereg`; 예산 1/4; 챔피언 미정(V14-D10 대기); 홀드아웃 0슬롯(오염); 봉인 absent_by_construction |
| `data/contracts/timeseries_daily6m_v1.yaml` | 있음 | `predictive_validation: not_established`가 계약+코드 4곳에서 강제 |
| `src/ai_fc/timeseries_v2/model.py` | 있음 | **주의: V2 수치 커널 모음**(ridge VARX 선택·분포 파라미터·경로 시뮬). `RidgeVARXFit`은 V1(`ai_fc.timeseries.model`) 소속 |
| `src/ai_fc/timeseries_v2/dfm_cache.py` | 있음 | 원점별 DFM cache(adapter는 읽기 전용 — `build_origin_dfm_cache` 호출 금지) |
| `src/ai_fc/timeseries_v2/features.py` | 있음 | `assemble_candidate_bundle` — V8 입력 bundle 조립(read-only) |
| `src/ai_fc/timeseries_v2/market_archive.py` | 있음 | append-only 시장 아카이브. `MarketObservationV2`(available_at/data_grade/revision_seq/supersedes/raw_sha256/receipt_id) |
| `src/ai_fc/timeseries_v8/model.py` | 있음 | FHS=`fhs_horizon_samples`, PIT 재보정=`recalibration_levels` |
| `src/ai_fc/timeseries_v8/backtest.py` | 있음 | 순수 walk-forward(`walk_forward_dev_backtest_v8`, 파일 I/O 없음) + `_final_session_forecast`(200레벨 grid) |
| `src/ai_fc/timeseries_v8/pipeline.py` | 있음 | 조정·검증·원장 append. FHS/PIT 로직 자체는 model/backtest에 있음 |
| `src/ai_fc/timeseries_v8_display.py` | 있음 | **표시 전용**(fail-closed projection). 표시 allowlist는 계약이 아니라 DECISIONS R8-D4 + 이 모듈 |
| `data/timeseries_v13/vol/champion_coefficients.json` | 있음 | sha256 `1a857850…` 핀, θ_rv=0.1694, refit_prohibited |
| `data/timeseries_v13/ledgers/vol_live.jsonl` | 있음 | **33행** (최신 as_of 2026-10-23) |
| `data/timeseries_v13/ledgers/vol_live_resolutions.jsonl` | 있음 | **123행** |
| `data/timeseries_v2/ledgers/market_observations.jsonl` | 있음 | **47,909행** |
| `data/timeseries/facts/observations.parquet` | 있음 | **주의: ALFRED 거시 빈티지 저장소**(전 행 source_id=alfred, 25계열) — 시장 아카이브 아님 |
| `data/timeseries_v2/parquet/features_C1.parquet` | 있음 | V2 후보 C1 특징 행렬(7,131세션×9열), V8이 read-only 재사용 |

추가 확인: `src/ai_fc/timeseries_v14`는 **없음**(금지 — 아래 §4). V14 코드는 `tools/v14_cond_diagnostics.py`·`tools/v14_cond_run.py` 둘뿐.
`src/ai_fc/mts_research`·`data/mts_research`·`docs/research/mts_upgrade`는 본 작업 이전 어디에도 없었음(신규 namespace 충돌 없음).

## 3. 동결·보호·금지 (CI가 실제로 잡는 것)

| 보호 장치 | 범위 | 위반 시 |
|---|---|---|
| V8 `model_code_hash` (`timeseries_v8/contracts.py:139`) | `src/ai_fc/timeseries_v8/**/*.py` + `timeseries_v2/{model,backtest,features,dfm_cache}.py` + `timeseries/{model,backtest}.py` | 주간 원장 대조 테스트 실패 → **import-only, 한 줄도 수정 금지** |
| V14 자동화 금지 (`test_no_automation_exists_for_v14`) | `cli.py`·`.github/workflows/*.yml`의 `timeseries_v14`/`timeseries-v14` 문자열, `src/ai_fc/timeseries_v14/` 패키지 | V14-D10 결정 전 테스트 실패 |
| V5.2 보호 루트 (`scenario_v5/contracts.py::PROTECTED_PATHS`) | `data/{scenarios,ml_history,signals,liquidity,cross_asset,ai_capital_cycle}`, `forecasts/`, `calibration/`, `questions/registry.yaml` | **새 파일 추가조차** protected-hash 테스트 실패 (전례: ML 참조 원장을 `data/ml_reference/`로 분리) |
| V13 계수 핀 + gate 블록 byte-stable + 예산-원장 대조 | `champion_coefficients.json`, V13 계약 gate 블록 | 계약 테스트 실패 |
| V7 보호 glob (`timeseries_v7/protection.py`) | `src/tests/test_multivariate_timeseries*.py`, `tools/*timeseries*`, `.github/workflows/timeseries*.yml` 등 | 바이트 보호 — **신규 테스트는 `test_mts_research_*` 네이밍** |
| `.claude/hooks/validate-immutable.py` | `calibration/ledger.csv`, `forecasts/` 기존 파일 | Write/Edit 차단 |
| AGENTS.md (루트) | 원장 append-only+supersedes, 의존성 무단 설치 금지, 테스트의 영속 원장 변경 금지 | — |

→ 신규 데이터 루트 `data/mts_research/`는 모든 보호 목록 밖(안전). 신규 원장은 `ledger_registry.yaml`에 **추가-전용** 등록(`expected_state: planned`).

## 4. 예산·승인·접근 범위 실상태 (2026-10-26)

| 트랙 | 자원 상태 | 이번 작업에의 함의 |
|---|---|---|
| V8 | 봉인 공개 1/1 사용, shadow 46/126(10-21 기준) | adapter는 재현만 — 봉인·shadow 원장 무변경 |
| V13 | 개발 8/8 소진(재개=사용자), 홀드아웃 1/3 슬롯·셀 3/9 통과, V13-D13 제한으로 claim 가능 0셀 | 신규 V13 실험 없음 — PB replay(재현)만 |
| V14 | 개발 1/4(rung-1 채택 0), rung-2는 **V14-D11 결정+리터럴 승인 필요(미결)**, 홀드아웃 0슬롯, live 원장 0행 | **W5 실측 실험 BLOCKED** — hazard scaffold+합성 테스트만 |
| daily6m | `predictive_validation: not_established` | JOINT_EVAL 평가기는 상태 불변·평가만(후속 범위) |
| LLM P3 게이트 | 해소 50+·Brier<0.18 별개 | 본 작업과 독립(결합 금지) |

승인 관례: per-track `approvals.jsonl`(리터럴 "V14-D10 A1 승인" 형식, receipt_id `v1X-approval:<ID>:<date>:r<N>`), prereg_commit → 승인 → 계약 amendment → 1회 실행 → 결과 append → DECISIONS 기록.

## 5. 설계서 용어 → 저장소 실체 대응표

| 설계서 용어 | 저장소 실체 |
|---|---|
| `read_scope_receipt_id` | 동명 개념 없음. 대응물: V13/V14 계약의 `holdout_read`/`sealed_read`/`bytes_read_for_this_draft` 필드 + `named_verb_guarded` 실행 경로 + `approvals.jsonl` 영수증. mts_research는 이 모델로 `read_scope_guard`를 구현(보호 창은 계약에서 파생) |
| `available_at`의 §6.1 확장 | legacy 행은 `source_published_at`/`provider_available_at` **항상 null**(승격 금지); `first_seen_at`←`vintage_start`(market)/`retrieved_at`(ALFRED); `availability_upper_bound`←`available_at`(ALFRED는 ≈23:59:59 ET 보수 상계로 이미 저장) |
| `docs/research/mts_upgrade/` | 신설(관례 충돌 없음 — 설계·prereg는 `docs/design/`, 판정은 `docs/review/` 관례 병존) |
| 원고의 "display allowlist" | V8 계약에 없음 — DECISIONS R8-D4 + `timeseries_v8_display._horizon_metrics/_sealed_disclosure` |
| 원고의 "VIX<20 eligibility" | **V14 계약 소속**(V13 아님 — V13은 θ=0.1694만) |
| experiment budget receipt | 계약 `development_protocol.maximum_development_evaluations` + `*_experiments.jsonl` 행 수 대조(테스트가 단언) |

## 6. Active dependency graph (최종 출력까지)

- **V8 h1/h5**: bundle(market archive + DFM cache + features_C1) → `select_ridge_varx_v2`(1일 NASDAQ 제곱오차로 lag·α 선택) → 앙상블+경로 시뮬 → PIT 재보정(s=0.5, 성숙≥104) → 200레벨 quantile_grid.
- **V8 h21/h63**: 위와 동일 전단 but 최종 분포는 **FHS 대체**(`fhs_horizon_samples` — 수익률 단변량+ewma_lambda만의 함수, tilt=0) × 0.75 blend(상대는 VARX 무관 historical_simulation). → **VARX (lag,α)는 λ 스위치·PIT 이력 경유로만 장기 분포에 영향**(OBJECTIVE_ALIGN 감사 대상, W4에서 섭동 검증).
- **V8 표시**: shadow ledger → `multivariate_v8_latest.json`(`grid[int(q*200)]` 투영) → `timeseries_v8_display.build_projection`.
- **V13**: market archive(cutoff 필터) → `build_panel`(VIX∩NASDAQCOM 관측일 교집합 grid) → 동결 계수 로지스틱+delta band(h63은 PAV) → `vol_live.jsonl`/`vol_latest.json`.
- **V14**: tools 2종만, 산출물은 `data/timeseries_v14/`(prereg·ladder json), live 0행.

## 7. 신규 코드 연결 지점 (최소)

| 연결 | 방식 |
|---|---|
| CLI | `src/ai_fc/mts_research/cli.py` 자체 argparse(`python -m ai_fc.mts_research.cli`) — 공유 `cli.py` 무수정 |
| 테스트 | `src/tests/test_mts_research_*.py` + `src/tests/mts_research_fixtures.py`, 실행 `cd src && python -m pytest tests -q` |
| 해시 | `timeseries_v8.contracts.canonical_hash` 무수정 import(v13 전례), 파일 해시는 `models.sha256_file` |
| 원장 | `ledger_registry.yaml` 추가-전용 등록 + `python -m ai_fc inventory` 재생성 1회 |
| 달력 | `exchange_calendars` XNAS(+calendar_hash 기록, daily6m 전례); legacy 달력·관측일 grid는 `CalendarRef`로 표현만 |

## 8. 감사 가설 상태 (설계서 §2.4 — W4에서 갱신)

| 감사 가설 | 상태 | 비고 |
|---|---|---|
| VARX 1일 MSE 선택 vs 장기 CRPS 목적 불일치 | **부분 확인(정적)** — h21/63은 FHS 대체로 (lag,α) 대부분 우회, λ·PIT 경유만 | W4 섭동으로 정량화 예정 |
| DFM smoothed state/전체창 scaling의 과거 OOF 유입 | 미확인 | 원점별 cache 구조상 차단 설계이나 미검증 |
| 입력 공통 마지막 날짜로 원점 지연 | 미확인 | ASOF_AGE 후속(W7 성격) |
| 보정 분위수와 상승확률의 분포 불일치 | 미확인 → W4 coherence 감사 | `p_up`은 같은 grid에서 산출(코드 확인) — 전 행 재계산으로 확증 예정 |
| 셀 확률의 지평/임계 단조성 위반 | 미확인 → W4에서 V13 33행 측정(보고만) | |
| 조기 양성 선학습 | 미확인 | V13 resolve 구조상 성숙 후 채점 — mts 계층은 T16으로 강제 |
| `2019-blind` 명칭 vs `2019-04-30` 절단 혼동 | 확인됨(혼동 아님) | `DEVELOPMENT_TRUNCATION_AFTER=2019-04-30`은 개발 절단, 봉인은 2019+ 별도 |
| DTWEXB→DTWEXBGS splice 인공 변화 | 미확인 → `audit-time` 산출물에서 검사 | 방법론 적용일 2019-02-04(공개) vs 전환일 2019-01-02(원고) |
| 홀드아웃 +4.04% vs +7.34% 집계 혼동 | 해당 수치 재계산은 범위 밖 | 집계 범위 분리는 scores/resampling 계약으로 강제 |

## 9. 이번 작업의 증거 계층 선언

- 본 작업의 모든 실자료 사용은 **legacy reproduction**(동결 출력 재현)과 **exposed historical research**(이미 공개된 원장·설계창 진단)에 한정된다. **prospective confirmation 생산 없음**, 보호 창 guarded purpose(fit/평가) 읽기 **0** (정밀화 2026-10-27, F03: replay/audit 은 OPEN purpose 로 아카이브 전 기간을 읽고 exposures.jsonl 에 기록 — 계약의 '소모' 아님).
- LLM 캘리브레이션(P3 게이트)과 무관 — 본 계층은 결정론 수치 모델 전용(CLAUDE.md 5-5 예외 범위), 산출물은 base rate 참조 지위.
