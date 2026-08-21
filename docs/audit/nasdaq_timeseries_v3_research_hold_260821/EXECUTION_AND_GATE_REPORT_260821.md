# 실행 및 Gate 보고

## 실행 좌표

| 항목 | 값 |
|---|---|
| 모델 | `shadow.nasdaq_direct_regime_distribution_v3` |
| 대상 | NASDAQ Composite 직접 누적 로그수익률 |
| horizon | 1 / 5 / 21 / 63 거래일 |
| 평가 원점 | 963개 주간 원점, 2007년 이후 |
| 최종 분포 표본 | 원점·component별 4,000개 |
| paired CI | stationary bootstrap, block 13, 1,000회, 90% |
| 비교군 | `fixed_anchor_ensemble_v3` |
| run ID | `tsv3-research-1f80a06bf6e991d887a5be40` |
| content hash | `74591b18cc845459f2572a301c7686cd7e6fc565ac46a0f813b00eeb785ad2b4` |
| contract hash | `1ee81902658c3c046b38ff1bd5113f0f3b42ad14c8033f6a0176ff7ec882010e` |
| model code hash | `5a919a61daf4611e1980ad38195794a4264a7bb8f360d523cf055f848ba1f3bc` |

## 장기 CRPS

| Horizon | V3 | 고정 기준선 | 개선률 | 개별 양수 Gate |
|---:|---:|---:|---:|---|
| 21일 | 0.02982524 | 0.03004934 | +0.75% | PASS |
| 63일 | 0.05076839 | 0.05181760 | +2.02% | PASS |
| 평균 | - | - | **+1.39%** | **HOLD: 2% 미달** |

paired loss difference 90% CI는 `[-0.00114416, -0.00008429]`로 상단이 0 이하여서 이 항목은 PASS다. 하지만 모든 Gate의 논리곱이 요구되므로 전체 판정은 HOLD다.

## Coverage 결함

| 조건 | 21일 V3 / 기준선 | 63일 V3 / 기준선 | Gate |
|---|---:|---:|---|
| 절대변동 Q4 p10–p90 | 32.78% / 50.21% | 35.68% / 48.13% | FAIL: 65% 미달·기준선보다 악화 |
| 2008 위기 p10–p90 | 68.25% / 71.43% | 65.08% / 69.84% | FAIL: 70% 미달 |
| 2020 급락 p10–p90 | 22.22% / 44.44% | 33.33% / 33.33% | FAIL: 70% 미달 |
| 2022 긴축 p10–p90 | 62.00% / 66.00% | 72.00% / 74.00% | 21일 FAIL |

## fail-closed 조치

- `research_gate_pass=false`
- `customer_numbers_visible=false`
- `display_state=validation_pending`
- forward shadow `captured_sessions=0`, `publication_allowed=false`
- 공식 forecast ledger write 0
- Scenario V5.2 write 0
- 기존 `#future` 및 기존 `#timeseries` 고객 UI 변경 0
- workflow 권한은 `contents: read`; schedule·commit·merge·Pages 단계 없음

## 비활성 component

- DFM: V2 cache에 named loading vector가 없어 sign/scale alignment를 증명할 수 없으므로 weight 0.
- event: PIT event count 0, ablation 미충족으로 weight 0.
- market-implied: realized outcome calibration 0건으로 weight 0.
- analyst report: 선택 challenger이며 이번 run에서는 미활성, weight 0.
- foundation challenger: 비교 증거가 없어 weight 0.

## 추가 평가 산출물

- volatility quartile과 component staleness 조건표를 21·63일에 생성했다.
- 1·5·21·63일별 PIT histogram과 상승확률 reliability bin을 생성했다.
- 1/5/10/25/50/75/90/95/99% quantile, mean pinball, tail-weighted CRPS를 저장했다.
- latest 4,000-path bundle에 endpoint 오차, 중복률, 최대 낙폭 깊이·기간 quantile, −10% first-touch를 저장했다.
