# L2-2 Realty Income rolling-entry cohort — 구현·검증 보고

작성일: 2026-08-04 KST
범위: `GRAND_MODEL_BLUEPRINT §3.7`의 L2-2와 승인된 L1-1 accession 준비만. O 진입상태 규칙은 미등록.

## 결론

- 1998-01~2005-12의 96개 월말 신호를 각각 익월 첫 O 거래일에 체결해 3·6·12·24·36개월 가격/총수익 proxy를 같은 코드로 산출했다.
- 2008·2020·2022는 각각 24개 signal-month OOS 창으로 동일 파이프라인을 재실행했다.
- 총수익 proxy는 보유 중 ex-date가 실제로 지난 현금배당만 순차 재투자한다. 신호 계산에 미래 배당을 사용하지 않는다.
- 결과는 `reference_only` 과거 표본이다. 현재 진입상태·진입 가격·수량 규칙은 만들지 않았다.

## 사전 등록 계약

정본: `data/contracts/o_entry_cohort.yaml`

| 항목 | 고정 규칙 |
|---|---|
| signal | 달력 월의 마지막 확정 시장 종가 |
| execution | 익월 첫 Realty Income 거래일 종가 |
| 비용 | 진입 5bp + 청산 5bp = 왕복 10bp |
| 지평 | 3·6·12·24·36개월, 보간 금지 |
| 총수익 proxy | 실행일 이후~청산일 이내 ex-date 배당만 해당일 이후 첫 거래 종가로 재투자 |
| 신호 | Nasdaq 고점 대비 −10/20/30/40%, Fed easing state, HY OAS 63관측 정점 대비 100bp 후퇴, 10Y 126관측 변화 반전 |
| 미완결 | 통계에서 제외하고 `incomplete_count`로 보존 |

## 실측 결과

1998–2005 전체 월의 총수익 proxy:

| 보유 | n | 중앙값 | 양(+) 수익 비율 | 최악 | 중앙 MDD | 최악 MDD | 회복일 중앙값* | 미회복 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 3개월 | 96 | +4.13% | 65.62% | −11.85% | −6.49% | −20.50% | 21.5일 | 54 |
| 6개월 | 96 | +7.60% | 81.25% | −11.74% | −9.72% | −20.50% | 33일 | 48 |
| 12개월 | 96 | +19.40% | 82.29% | −13.82% | −14.79% | −20.50% | 60일 | 28 |
| 24개월 | 96 | +40.92% | 95.83% | −11.64% | −18.39% | −20.50% | 109일 | 12 |
| 36개월 | 96 | +64.79% | 98.96% | −15.00% | −20.34% | −48.36% | 140일 | 19 |

12개월 OOS 총수익 proxy:

| OOS 창 | n | 중앙값 | 양(+) 수익 비율 | 최악 | 중앙 MDD | 최악 MDD | 미회복 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2008–2009 | 24 | +38.74% | 83.33% | −22.39% | −28.75% | −48.39% | 8 |
| 2020–2021 | 24 | +13.61% | 75.00% | −19.01% | −11.82% | −48.28% | 9 |
| 2022–2023 | 24 | −7.55% | 29.17% | −18.87% | −25.11% | −29.70% | 18 |

\* 회복일 중앙값은 관측 지평 안에 회복한 사례에만 계산하며, 미회복 수는 별도 공개한다.

해석 제한: 인접 월 cohort는 보유기간이 겹쳐 독립 표본이 아니다. 따라서 위 비율은 사건 확률이나 미래 적중률이 아니며, 닷컴 구간의 우호적 결과를 2022 금리충격에 일반화할 수 없다.

## 산출물·UI

- 전체 증거: append-only `data/realty_income/o_entry_cohort_archive/2026-07-30.json` — 840 entry rows, 320 summary rows, 1,256,610 bytes.
- latest: `data/realty_income/o_entry_cohort_latest.json` — 320 summary rows와 archive 참조만 보존해 사례 중복 저장을 제거(139,971 bytes).
- Pages read-model: 화면이 사용하는 15개 aggregate만 포함하고 entry rows는 제외. `data.json` 284,283 bytes.
- UI: 5개 보유기간 표, 3개 OOS 카드, 7개 사전 등록 신호의 12개월 표. 항상 표본 n·최악 사례·MDD·미회복을 함께 표시.

## 게이트 검증

| 게이트 | 구현/테스트 | 판정 |
|---|---|---|
| PIT 익월 체결 | `test_o_entry_cohort_pit_uses_next_month_fill_and_realized_dividends_only` | 통과 |
| 당시 배당만 | 실행 이후·청산 이전 ex-date만 재투자, pre-entry/post-exit fixture 차단 | 통과 |
| 통계 재계산 | `test_o_entry_cohort_statistics_recalculate_from_fixed_fixture` | 통과 |
| 1998–2005 × 5지평 | 저장본 각 basis별 n=96 | 통과 |
| 2008/2020/2022 OOS | 12개월 각 n=24; 2022의 미완결 36개월 6건은 별도 표시 | 통과 |
| 상태 규칙 순서 | `entry_state_rules_registered=false`, `O_ENTRY_*` 부재 | 통과 |
| 히스테리시스 mock UI | JS renderer의 hold/boundary/clear 3상태 snapshot | 통과 |

## L1-1 병행 준비 상태

SEC submissions endpoint가 로컬 네트워크에서 HTTP 403을 반환했다. 완료를 꾸미지 않고 기존 filing-native Companyfacts accession만 복구해 `partial`로 저장했다.

| 회사 | 확보 accession | 요구 | 추출 상태 |
|---|---:|---:|---|
| MSFT | 4 | 12 | not_started |
| AMZN | 4 | 12 | not_started |
| GOOGL | 4 | 12 | not_started |
| META | 6 | 12 | not_started |

정본: `data/ai_capital_cycle/segment_filing_accessions_latest.json`. 세그먼트 수치·표 행은 0개이며 coverage gate 효과도 `none_segment_values_not_extracted`로 고정했다. GitHub 월간 workflow에서도 공식 SEC submissions를 재시도하되 실패 시 같은 partial 상태를 유지한다.

## 예약 scenario-refresh 운영 수정

2026-08-04 예약 실패는 Yahoo가 이미 공개된 2026-08-03보다 뒤처진 2026-07-31까지만 잠시 반환하면서 과거 불변 archive를 다시 열려 한 것이 원인이었다. `refresh_scenario`가 최신 snapshot보다 오래된 원천일에는 latest를 절대 후퇴시키지 않도록 가드와 회귀 테스트를 추가했다. 동일 조건 로컬 재실행은 `변경 없음 · 2026-08-03`으로 종료했다.
