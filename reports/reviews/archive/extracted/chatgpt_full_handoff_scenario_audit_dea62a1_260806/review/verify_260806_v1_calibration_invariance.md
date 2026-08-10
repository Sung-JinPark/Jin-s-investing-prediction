# VERIFY-260806 V-1 — 캘리브레이션 불변성 구현 기록

작성일: 2026-08-06 KST
범위: M-1/V-1만. V-2~V-5와 G-1/G-2 원장 등록은 포함하지 않는다.

## 변경 목적

시대 교체 민감도의 native 낙폭 범위만 보여주면 사용자는 시대 선택이 화면 낙폭까지 결정한다고 오해할 수 있다. 실제 연산은 각 시대 조합을 동일한 조정 base rate에 다시 맞추므로, 시대 선택은 위험창의 위치를 움직이고 화면 최대낙폭은 base rate에 수렴한다.

## 구현

- 구조 계약을 `2026-08-06.v3`으로 올렸다.
- calibration에 `depth_invariant_to_selection=true`와 `selection_moves=risk_window_center_month_only`를 직렬화했다.
- one-era replacement 전 조합에 S1 strength를 다시 추정하고 native·calibrated 낙폭, strength, 수렴 상태를 함께 기록했다.
- calibrated 낙폭이 목표의 ±0.2%p를 벗어나면 structural snapshot 생성을 거부한다.
- UI에 불변성 배지와 native/calibrated 2열 비교표를 추가했다.
- 정수 지수 경로 반올림으로 대안별 calibrated 실측은 -12.2%~-12.1%이며, 목표 -12.19%의 ±0.2%p 수렴 범위 안이다.
- S1/S2/S3 확률, 종점, fan, quantile table, path realism과 굵은 구조 경로 값은 변경하지 않는다.

## 계보

- correction: `CORR-260806-019`
- prior: `nasdaq-scenario:2026-08-03:r7`
- new revision: `nasdaq-scenario:2026-08-03:r8`
- supersedes는 r7을 가리키며 r7 archive byte는 수정하지 않는다.

## 범위 밖

- V-2 확률 부트스트랩 CI
- V-3 재현 정밀도 자기보고
- V-4 연준 대응 질문과 human forecast 등록
- V-5 LPPL/quant_auto 상태 감사
