# D.R. Horton 닷컴 조정기 실측 비교 추가

- 정정 ID: `CORR-260827-020`
- 승인 대상: `cross_asset_snapshots / 2026-08-24`
- 실제 반영: `cross-asset:2026-08-26:r1` (신규 기준일 스냅샷)
- 기간: `2001-03`부터 `2006-03`까지 61개 월 관측치
- 원천: Yahoo Finance chart API, ticker `DHI`, monthly close and adjusted close
- 변환: 2001-03을 100으로 둔 가격지수와 수정종가 기반 총수익 proxy
- 확률공간: `reference_only`; 기존 Scenario·공식 확률·Bitcoin beta에 결합하지 않음

`CORR-260827-020` 승인 뒤 수집 실행 중 더 최신 기준일이 확정되어, 과거
`cross-asset:2026-08-24:r1`을 정정하는 방식은 사용하지 않았다. 기존 스냅샷은
byte-for-byte 보존하고 DHI가 포함된 `cross-asset:2026-08-26:r1`을 신규 생성했다.
따라서 이 실행에는 `supersedes` 관계가 없다. DHI의 당시 상승은 주택·금리
사이클과 함께 관측된 역사적 결과일 뿐, 다음 기술주 조정기 수혜의 인과 증거나
확률 예측으로 사용하지 않는다.

## 기존 연구 시나리오 비회귀 확인

교차자산 최신 파일과 정정 원장 append가 Scenario V5.2의 보호 해시를 바꾸므로,
연구 후보를 `--force`로 재검증해 보호 영수증을 갱신했다. 후보 ID와 source hash는
동일하고 S1/S2/S3 p50 경로의 최대 절대 차이는 모두 `0`이다. 고객 화면의 주요
확률 5개에서 생긴 최대 절대 차이는 `4.17e-16`으로 부동소수점 재실행 오차뿐이다.
후보 상태는 계속 `NOT_OFFICIAL_NOT_CHAMPION`이며 공식 원장에는 기록하지 않았다.
