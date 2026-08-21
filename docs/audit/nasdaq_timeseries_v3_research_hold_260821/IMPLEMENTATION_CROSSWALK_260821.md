# 명세–구현 교차표

| 요구 | 구현 | 검증 상태 |
|---|---|---|
| V2 봉인·불변 | `timeseries_v3/contracts.py::verify_v2_benchmark` | PASS, 4개 identity/hash 일치 |
| 직접 1/5/21/63 target | `targets.py`, `pipeline.py::direct_targets_from_returns` | PASS, 재귀 1일 예측 금지 |
| PIT snapshot | `snapshots.py` | PASS, future available_at 거부 |
| 고정 기준선 | `baselines.py::FixedAnchorDistribution` | PASS, 0.50/0.30/0.20 고정 |
| direct Ridge residual | `models/direct_location.py::DirectHorizonModel` | PASS, sigma bound |
| analog quantile | `models/direct_location.py::AnalogQuantileModel` | PASS, 내부 purge/embargo |
| 변동성·tail 분리 | `models/volatility_tail.py` | PASS |
| soft regime | `models/regime_mixture.py` | PASS, hard forecast assignment 금지 |
| DFM 부호·scale 계약 | `dfm_alignment.py` | 구현 PASS, 실제 V2 cache 연결 HOLD |
| 이벤트 PIT·revision | `event_ledger.py` | 구현 PASS, 실제 표본 HOLD |
| 시장확률 physical calibration | `options_ledger.py` | 60 outcomes gate PASS, 실제 표본 HOLD |
| 보고서 구조화·중복제거 | `analyst_ledger.py` | 구현 PASS, numerical activation HOLD |
| no-regret stacking | `stacking.py` | PASS, anchor floor 및 absent=0 |
| endpoint 공동분포 | `path_reconciler.py` | PASS, copula + stochastic bridge |
| quantile monotonicity | `calibration.py` | PASS |
| 고정 비교·조건부 Gate | `backtest.py` | PASS, row-wise oracle=false |
| PIT·reliability·tail score | `backtest.py` | PASS, 4 horizons |
| path 낙폭 깊이·기간·first-touch | `pipeline.py::_path_risk_audit` | PASS |
| 운영 freshness/monitor | `monitoring.py` | PASS, sample-aware·calendar-aware |
| end-to-end research | `pipeline.py` | PASS, 최종 Gate 결과 HOLD |
| CLI | `timeseries-v3-backtest/forecast/verify/workbook` | PASS |
| Excel | `timeseries_v3/workbook.py` | PASS, 8 sheets |
| 자동화 | `.github/workflows/timeseries-v3-research.yml` | fail-closed 검증 전용; 배포 없음 |
| 고객 UI | 연결하지 않음 | PASS, Gate 실패 정책 준수 |

## 데이터 경계

V3는 `data/timeseries_v2/parquet/features_C1.parquet`와 `market_observations.parquet`을 읽기 전용으로 사용한다. 원천을 native PIT로 재명명하지 않는다. V3의 수치 산출물은 V3 전용 `data/timeseries_v3/**`에만 기록된다.
