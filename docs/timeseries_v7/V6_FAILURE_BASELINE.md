# NASDAQ V6 실패 기준선

`V7-P0-001`은 V6를 고치거나 재학습하는 작업이 아니다. V6 리뷰 팩의
manifest와 sealed score 행을 독립적으로 읽어, 기존 HOLD 판정과 구조적
결함을 변경 불가능한 V7 감사 기준선으로 남긴다.

## 동결된 판정

- Model: `shadow.nasdaq_pit_hierarchical_distribution_v6`
- Sealed run: `tsv6-sealed-46d58750db2abe8b40cec159`
- Integrity Gate: PASS
- Research Gate: FAIL
- Operational Gate: FAIL
- Overall: `shadow_gate_hold`
- Customer numbers: hidden

감사 도구의 성공은 V6가 Gate를 통과했다는 뜻이 아니다. 아래 실패를
누락하거나 V6 데이터를 변경하지 않고 정확히 재현했다는 뜻이다.

## 독립 재현 기준

| 항목 | 동결 값 |
|---|---:|
| score 행 | 1,540 |
| origin | 385 |
| 1일 CRPS 개선 | 3.29% |
| 5일 CRPS 개선 | 3.50% |
| 21일 CRPS 개선 | 1.27% |
| 63일 CRPS 개선 | 0.58% |
| 21·63일 평균 개선 | 0.93% |
| 21일 하락 TNR | 0% |
| 63일 하락 TNR | 0% |

V6 계약은 2019년 이후 sealed origin만 평가하면서 2008~2009 GFC origin을
20개 이상 요구한다. 두 기간은 교차하지 않으므로 이 Gate는 동결된 V6
계약 아래 구조적으로 통과할 수 없다.

또한 구현의 `index - 68`은 63-session purge와 5-session embargo가 아니라
68개의 주간 origin을 제거한다. 감사 도구는 이 단위 불일치를 소스와
실제 sealed origin 간격 양쪽에서 검출한다.

## 재현 한계

팩에 저장된 1,540개 score 행의 집계, coverage, 방향 진단과 loss 기반
stationary bootstrap은 재계산할 수 있다. 반면 origin별 예측 sample 전체가
동봉되지 않았으므로 CRPS를 sample에서 처음부터 다시 계산하는 작업과 V6
모델 재적합은 이 감사 범위에 포함하지 않는다.

V7 모델 학습, Ralph 후속 task, 고객 공개, promotion, 주문·매매는 시작하지
않는다.
