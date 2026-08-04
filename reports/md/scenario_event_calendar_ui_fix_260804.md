# 시장 시나리오 이벤트 캘린더·차트 가독성 정정

작성일: 2026-08-04 KST

정정 ID: `CORR-260804-011`

대상: `scenario_snapshots / 2026-08-03`

## 정정 목적

미래 분포 차트에서 주간 날짜가 과밀하게 출력되고, 날짜 조회용 파란 표식이 상단 이벤트 라벨과 겹치는 문제를 수정한다. 동시에 기존 일정 목록에 섞여 있던 계절성·아날로그 해석을 제거하고, 공식 출처가 날짜를 공개한 이벤트만 2027년까지 별도 캘린더로 제공한다.

## 데이터 변경

- 2026 고용보고서 발표일은 BLS 공식 일정에 공개된 8월 7일, 9월 4일, 10월 2일, 11월 6일, 12월 4일을 등록했다.
- 2026년 8월 26일 NVIDIA FY27 2분기 실적 발표는 NVIDIA IR 공지를 근거로 등록했다.
- 2026 FOMC와 2027 FOMC 8회는 Federal Reserve 공식 캘린더를 사용했다. 연준의 안내에 맞춰 2027 일정은 `tentative`로 표시한다.
- 2026년 11월 3일 중간선거는 FEC 공식 선거일 안내를 근거로 등록했다.
- `9/29 미드텀 저점 중위`, `산타랠리`처럼 공식 일정과 시장 해석이 섞인 표현은 이벤트 캘린더에서 제거했다.
- 2027 고용보고서와 NVIDIA 실적일은 공식 발표 전이므로 추정값을 만들지 않는다.
- 252거래일 모델 지평 밖의 2027 일정은 경로 좌표에 억지로 배치하지 않고 아래 공식 일정판에 `모델 범위 밖 · 일정만 표시`로 구분한다.

## UI 변경

- 하단 x축은 전체 지평에서도 최대 6개 대표 눈금만 출력한다.
- 이벤트 라벨은 x 위치와 글자 폭을 반영한 최대 5개 자동 레인으로 배치한다.
- 날짜 조회 라벨은 이벤트 레인 아래의 독립된 파란 레인에 배치한다.
- 차트 상단 여백을 확대해 이벤트·조회 라벨과 실제 분포 영역을 분리한다.
- 2026/2027 공식 일정판을 추가하고 공개·잠정 상태, 차트 표시 여부, 공식 출처 링크를 함께 노출한다.

## 출처

- Federal Reserve FOMC calendars: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
- BLS Employment Situation schedule: https://www.bls.gov/schedule/news_release/empsit.htm
- NVIDIA Investor Relations: https://investor.nvidia.com/events-and-presentations/events-and-presentations/event-details/2026/NVIDIA-2nd-Quarter-FY27-Financial-Results/default.aspx
- Federal Election Commission: https://www.fec.gov/introduction-campaign-finance/election-results-and-voting-information/

## 불변성·검증 원칙

기존 `2026-08-03` 스냅샷은 덮어쓰지 않는다. 승인된 correction ledger를 근거로 새 revision을 만들며 기존 20,000경로, seed 42, 분위수, 시나리오 확률은 변경하지 않는다. 스키마 검증은 이벤트 날짜 정렬·중복, 상태값, HTTPS 출처, 차트 인덱스 범위를 검사한다.
