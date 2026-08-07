# L0 구현·수용 게이트 검토서

- 작성일: 2026-08-04 KST
- 기준 커밋: `48fc8930f5ef75912641fb7818af99d366218122`
- 작업 브랜치: `main`
- 실행 범위: `IMPLEMENTATION_SEQUENCE.md`의 `L0-1`~`L0-6`만
- 범위 밖: L1 이후 데이터 수집·모델·UI는 착수하지 않음
- 전체 회귀: `349 passed in 77.46s`
- 원장 감사: violation 0 · stalled 1(`dualdb_model_runs`, 의도된 탐지)
- 정적 Pages 빌드: 성공 · `index.html` 441,002 bytes · `data.json` 278,198 bytes

## 1. 적용 문서와 우선순위

구현 순서는 사용자가 지정한 우선순위를 그대로 적용했다.

1. 실행 범위와 순서: `IMPLEMENTATION_SEQUENCE.md`
2. 구현 사양: `GRAND_MODEL_BLUEPRINT.md`
3. 수정 이유와 증거: `INDEPENDENT_REVIEW.md`
4. 완료 판정: `ACCEPTANCE_GATES.md`

| 문서 | SHA-256 |
|---|---|
| `IMPLEMENTATION_SEQUENCE.md` | `1756DBA930D7D7DA805DDEF38C62DAD07204B7F25B31D52341ABC7827A047F45` |
| `GRAND_MODEL_BLUEPRINT.md` | `80255B6168FBC2B3B8B86FAF9BB8D0D38DD7CB27623FC048252FB1ACCA7B4741` |
| `INDEPENDENT_REVIEW.md` | `137CD848CB6824C914181549C57982A88D23F734A0C5292BB4C4C030FB37BD02` |
| `ACCEPTANCE_GATES.md` | `F4E286EA28EB14779E71D17645AD8DDD4B89C8D3F8B07CB55B1F6DAEE19DE818` |

## 2. L0 항목별 완료 판정

| 항목 | 파일 | diff 요지 | 테스트명 | 게이트 충족 여부 |
|---|---|---|---|---|
| L0-1 F1 태그 체인·recency guard | `data/contracts/sec_tag_chains.yaml`, `src/ai_fc/ai_capital_cycle.py`, 2026-08-04 capex/coverage archive·latest | 회사×metric 우선순위 체인, USD 전용, PIT 필터, 400일 recency guard를 추가했다. 첫 번째 fresh USD 태그만 채택하고 stale 행은 records와 collection coverage에서 제외한다. AMZN capex는 `PaymentsToAcquireProductiveAssets`, max period `2026-06-30`으로 교체됐다. | `test_stale_tag_is_marked_and_excluded_from_collection_coverage`, `test_company_tag_chain_uses_first_fresh_amzn_capex_tag`, `test_recency_guard_boundary` | **충족** — §4 테스트 1·2·4 및 §5 AMZN 고정값 통과 |
| L0-2 F2 지표 상태·비USD 격리 | `src/ai_fc/ai_capital_cycle.py`, `data/ai_capital_cycle/company_capex_quarterly_latest.json`, `data/ai_capital_cycle/coverage_latest.json` | metric 상태를 `collected / tag_missing / not_disclosed / tag_stale / unit_unsupported`로 분리했다. 임의 첫 단위 fallback을 제거했다. MSFT·GOOGL의 capex/OCF/D&A는 각 8행, debt는 `not_disclosed`다. segment extraction은 하지 않아 coverage 0%와 D3 block을 유지한다. | `test_missing_metric_states_distinguish_tag_mapping_from_nondisclosure`, `test_non_usd_companyfact_is_quarantined`, `test_l0_sec_snapshot_regression_constants`, `test_d1_excludes_facts_not_available_by_asof` | **충족** — §4 테스트 3·5, PIT 회귀, §5 4지표×8행 또는 사유 상태 통과 |
| L0-3 F3 앵커 필드 분리 | `dualdb/schema.sql`, `dualdb/config.yaml`, `dualdb/dualdb/config.py`, `dualdb/dualdb/db.py`, `dualdb/dualdb/ingest/seeds.py`, `src/ai_fc/era_analog.py`, `src/ai_fc/read_model_contract.py`, `dashboard.js` | `overlay_start`와 `model_anchor`를 DB·설정·read model·UI에서 별도 소비한다. 기존 DB는 additive migration으로 열을 추가하고 `anchor_month`는 model-anchor 호환 별칭으로 유지한다. 닷컴은 1995-01/1996-01을 화면에 병기한다. | `test_overlay_and_model_anchor_are_separate_and_consumed`, `test_era_analog_is_log_normalized_and_reference_only`, `test_json_schema_lists_all_additive_and_legacy_keys` | **충족** — §4 테스트 19, §5 exact anchor 값 통과 |
| L0-4 F5 model_run cadence·run asof | `data/contracts/ledger_registry.yaml`, `src/ai_fc/ledger_audit.py`, `data/model_runs/knn_analog_latest.json`, `src/ai_fc/dashboard.py`, `dashboard.js`, 생성된 ledger audit | SQLite `model_run.asof`를 읽는 weekly 원장을 등록했다. 최신 DualDB run `2026-07-20`이 현재 기준 10일을 넘겨 `stalled`로 검출된다. 정적 UI에는 KNN `run asof 2026-07-17`을 표시한다. | `test_dualdb_model_run_weekly_cadence_detects_stalled_sqlite`, `test_small_knn_forward_is_case_list_only_with_run_asof`, `test_template_interactions_present` 내 run-asof 문자열 계약 | **충족** — 정체를 숨기지 않고 stalled로 검출·표시 |
| L0-5 F7 β 게이트 히스테리시스 | `src/ai_fc/realty_income.py`, `src/ai_fc/cross_asset.py`, `dashboard.js` | n<156 첫 실패는 직전 non-zero used β를 한 번 유지하고 `hysteresis_hold_1_of_2`를 기록한다. 두 번째 연속 실패에서 0으로 전환한다. CI가 0을 가로지르면 즉시 0이다. 이전 snapshot의 streak를 다음 refresh에 전달하며 UI에 1/2 유지·at-boundary 배지를 표시한다. | `test_significance_gate_requires_two_consecutive_sample_failures`, `test_hysteresis_does_not_delay_ci_failure`, `test_significance_gate_zeros_crossing_or_short_beta` | **충족** — β 게이트 계약과 at-boundary 표기 유지 |
| L0-6 F6·F11 소표본 UI | `data/model_runs/knn_analog_latest.json`, `src/ai_fc/era_analog.py`, `dashboard.js`, `dashboard.css` | KNN forward n=5는 1996~1999 개별 5사례와 1/3/6/12M 관측값만 나열한다. 중앙값 강조를 금지하고 `anchor_sensitivity=not_computed`를 유지한다. S1/S2/S3 카드에 표본 수를 상시 표시하여 S2 n=302가 데이터 기반으로 렌더된다. | `test_small_knn_forward_is_case_list_only_with_run_asof`, `test_template_interactions_present` 내 `CASE LIST ONLY`, `표본 n=...`, `run asof` 문자열 계약 | **충족** — UI 게이트 22·24·25 해당분 통과 |

미충족으로 완료 표시한 L0 항목은 없다.

## 3. ACCEPTANCE_GATES §4 — 이번 L0 해당 테스트 증거

| 번호 | 요구사항 | 구현 테스트 | 결과 |
|---:|---|---|---|
| 1 | 낡은 태그 → `tag_stale`, coverage 제외 | `test_stale_tag_is_marked_and_excluded_from_collection_coverage` | PASS |
| 2 | 태그 체인 폴백 순서, AMZN 최신 capex | `test_company_tag_chain_uses_first_fresh_amzn_capex_tag` | PASS |
| 3 | `tag_missing` vs `not_disclosed` | `test_missing_metric_states_distinguish_tag_mapping_from_nondisclosure` | PASS |
| 4 | recency 399d 통과 / 401d 차단 | `test_recency_guard_boundary[399-collected]`, `[401-tag_stale]` | PASS |
| 5 | 비USD 격리 | `test_non_usd_companyfact_is_quarantined` | PASS |
| 19 | overlay/model anchor 분리 소비 | `test_overlay_and_model_anchor_are_separate_and_consumed` 및 era read-model assertion | PASS |

L0 직접 UI 게이트도 함께 고정했다.

| 번호 | 요구사항 | 증거 | 결과 |
|---:|---|---|---|
| 22 | KNN n<20 사례 나열형 | read model `display_mode=case_list`, 5개 neighbor, `median_emphasis_allowed=false` | PASS |
| 24 | run-asof 배지 | Pages `data.json`의 `run_asof=2026-07-17`, UI `run asof` 문자열 | PASS |
| 25 | S2 소표본 병기 | Pages `data.json`의 `S2.sample_count=302`, UI data-driven 표본 문자열 | PASS |

## 4. ACCEPTANCE_GATES §5 회귀 고정값

| 고정값 | 실측 | 판정 |
|---|---:|---|
| AMZN capex max period ≥ 2026-03-31 | `2026-06-30` | PASS |
| AMZN capex tag | `PaymentsToAcquireProductiveAssets` | PASS |
| MSFT 4지표 | capex 8 · OCF 8 · D&A 8 · debt `not_disclosed` | PASS |
| GOOGL 4지표 | capex 8 · OCF 8 · D&A 8 · debt `not_disclosed` | PASS |
| era overlay/model | `1995-01` / `1996-01` | PASS |
| cross-asset history labels | `61` | PASS |
| NASDAQ/O가격/O총수익 | `-10.7 / +73.8 / +140.9` | PASS |
| S1 sample count | `16,702` | PASS |
| S1 path realism | `12.7 / 20.9 / 100 / 76` | PASS |
| segment coverage ≥0.6 accession 조건 | 현재 coverage `0.0`; 조건 미발동, D3 blocked | PASS(조건부 게이트 유지) |

## 5. 데이터 스냅샷 결과

- SEC asof: `2026-08-04`
- standardized company metric records: `112`
- AMZN capex: 8행, `2024-09-30`~`2026-06-30`, 태그 `PaymentsToAcquireProductiveAssets`
- MSFT·GOOGL debt: standardized fact 미공시 → `not_disclosed`
- 회사별 cloud/AI segment 수익: L1 filing-dimension extraction 미착수 → disclosure coverage `0%`
- AI regime map: `blocked`, coordinates `null`, trail 빈 배열
- 보존된 의미: YTD 수치를 임의 분기화하지 않음, 미래 filing을 asof 이전 데이터로 사용하지 않음

## 6. 검증 명령과 결과

```text
PYTHONPATH=src;dualdb python -m pytest -q
349 passed in 77.46s

PYTHONPATH=src python -m ai_fc audit-ledgers
accumulating=26 stalled=1 inactive=0 violation=0 planned=3

PYTHONPATH=src python -m ai_fc inventory --check
inventory current

node --check src/ai_fc/dashboard_parts/dashboard.js
exit 0

PYTHONPATH=src python -m ai_fc dashboard --pages-out <temp>
Pages build success
```

정적 산출물 확인:

- `era_analog.run_asof = 2026-07-17`
- `era_analog.forward_reference.n = 5`
- `era_analog.forward_reference.cases = 5`
- `dotcom.overlay_start = 1995-01`
- `dotcom.model_anchor = 1996-01`
- `scenario.path_realism.S2.sample_count = 302`

## 7. 의도된 경고와 해석

`dualdb_model_runs`의 `stalled`는 실패나 미충족이 아니다. L0-4의 목적이 “오래된 모델 실행을 최신처럼 보이지 않게 원장과 UI에서 드러내는 것”이므로, 최신 run이 2026-07-20인 현재 감사에서 stalled가 나오는 것이 수용 기준 충족 증거다. 이번 L0에서는 모델을 재학습하거나 새 결과로 바꾸지 않았다.

SEC company-panel coverage 0%도 L0 실패가 아니다. L1의 filing-level segment extraction을 금지한 이번 범위에서는 D3 map을 계속 차단해야 한다. `coverage_latest ≥0.6`은 L1 완료 후에만 열릴 조건부 게이트다.

## 8. L1 이후 미착수 확인

아래 항목은 코드·데이터 생성에 착수하지 않았다.

- filing-level segment revenue 추출 및 canonical segment map 확장
- commitments maturity·circular finance edges
- AI bust hazard·physical_event 질문·위험시계
- 닷컴 phase ledger·fundamentals 160행·cycle_compare 충전
- Realty Income entry cohort·진입 상태 규칙
- 단기조정 challenger·walk-forward·champion 승격
- LLM·외부 서버·새 확률공간

## 9. 검토자가 먼저 볼 파일

1. `data/contracts/sec_tag_chains.yaml`
2. `src/ai_fc/ai_capital_cycle.py`
3. `data/ai_capital_cycle/coverage_latest.json`
4. `dualdb/schema.sql` + `dualdb/dualdb/db.py` + `dualdb/dualdb/ingest/seeds.py`
5. `src/ai_fc/era_analog.py` + `src/ai_fc/dashboard_parts/dashboard.js`
6. `src/ai_fc/ledger_audit.py` + `docs/generated/ledger_audit.json`
7. `src/ai_fc/realty_income.py` + `src/ai_fc/cross_asset.py`
8. `src/tests/test_l0_acceptance_gates.py` 및 L0 관련 테스트 파일

## 10. 검토 ZIP 주의사항

ZIP은 소스 문서 4개, 본 검토서, L0 변경 파일, 최신·archive 데이터, 생성 계약/감사 결과, 관련 테스트를 포함한다. 사용자 소유의 기존 미추적 HTML·이전 검토 프롬프트·이전 ZIP은 포함하지 않고 수정하지 않았다. `dualdb.sqlite`는 85MB 파생 DB이자 git-ignore 대상이라 ZIP에 넣지 않고, schema/config/seed 코드와 감사 추출 결과로 검증 가능하게 구성한다.
