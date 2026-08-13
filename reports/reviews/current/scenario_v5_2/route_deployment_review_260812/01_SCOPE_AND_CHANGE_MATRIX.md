# 변경 매트릭스

| 변경 | 원인 | 구현 | 검증 결과 |
|---|---|---|---|
| PR #14 `336e992` | 20거래일 샘플링 때문에 3개월 전망이 4개 점으로 축약 | 근접 구간 5거래일, 장기 20거래일 샘플링 | 라이브 전망 관측치 14개, 시나리오별 곡률 생존 |
| PR #15 `cbae33b` | Scenario V5.2 소스 변경이 Pages push filter 밖에 존재 | `src/ai_fc/scenario_v5_2/**` 배포 트리거 추가 | Pages run `31551138626` 성공 |
| PR #16 `fc2818a` | 새 차트가 `#future/research`에만 있고 `#future`는 구형 화면 | `#future`를 세 경로 기본 화면으로 연결 | 일반 URL에서 `세 가지 시장 경로` 확인 |
| champion 보존 | 연구 후보를 official champion으로 오해할 위험 | 기존 화면을 `#future/champion`에 유지 | 별도 경로에서 기존 제목·화면 확인 |

## 정확한 기능 diff

- `.github/workflows/pages.yml`
- `src/ai_fc/dashboard_parts/dashboard.js`
- `src/ai_fc/scenario_v5_2/artifact.py`
- `src/tests/test_dashboard.py`
- `src/tests/test_scenario_v5_2.py`

총 53 insertions / 8 deletions이다.

## 모델과 표시의 경계

- 변경됨: 표시용 날짜 샘플링, 고객 기본 라우트, 자동 배포 트리거.
- 변경 안 됨: 시나리오 생성기, DB 군집 정의, 닷컴 강도 0.60, probability space, candidate bands 원본, official forecast ledger.
