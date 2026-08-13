# Scenario V5.2 알고리즘 감사

- 후보: `scenario_v5_2_scenario_clustered_db_v4` / `RESEARCH_CANDIDATE_COMPLETE_SEPARATION_DB_LIMITED_EVENT_MAP` / `NOT_OFFICIAL_NOT_CHAMPION`.
- 확률 저장 단위: `fraction`. UI에서만 %로 변환합니다.
- 경로: 총 9,000, 시나리오별 3,000.
- S1: 닷컴+완화·확장 DB, 닷컴 generator share 0.60.
- S2: 균형·soft-landing DB.
- S3: 긴축·금융 stress DB.
- macro origin overlap: `{"S1__S2": 0, "S1__S3": 0, "S2__S3": 0}`.
- 63거래일 조건부 p50 수익: `{"S1": 0.12406725956676087, "S2": -0.003387948751612281, "S3": -0.12132224651242784}`.
- dependency cap gate: `true`.
- source hash: `true`.
- official snapshot overwrite: `false`.

## 이벤트 증거

- 고용: BLS 2026-07 official actual, revisions, unemployment, participation.
- 금리확률: CME 30-day Fed Funds futures를 기반으로 한 Investing.com 공개 화면 캡처. 공식/유료 CME API가 아니므로 secondary입니다.
- policy relief와 labor growth risk는 structural adapter에서 별도 좌표로 사용되고 dependency cap을 적용합니다.

## 승격 불가 사유

- S2 origin n=16 < 20.
- distinctness threshold shadow observations 0 < 30.
- S2/S3 일부 empirical kernel time-to-trough/recovery gate 실패.
- 따라서 계산 재현 성공은 calibrated forecast 또는 champion 승격을 뜻하지 않습니다.
