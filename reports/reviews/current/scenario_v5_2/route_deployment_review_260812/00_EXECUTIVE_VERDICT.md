# 집행 판정

## 기능 변경 판정: PASS

1. 원본 후보에는 일별 경로가 존재했지만 대시보드 투영이 20거래일마다 한 점만 남겨 3개월 곡률을 숨기고 있었다.
2. 표시 투영을 향후 110거래일까지 5거래일 간격, 장기는 20거래일 간격으로 변경했다.
3. GitHub Pages 경로 필터에 `src/ai_fc/scenario_v5_2/**`를 추가해 같은 배포 누락이 반복되지 않게 했다.
4. `#future`를 독립 3경로 화면으로 연결하고 기존 champion을 `#future/champion`에 보존했다.
5. 라이브 페이지에서 S1/S2/S3 각각 14개 전망 관측치와 서로 다른 방향 전환 횟수를 확인했다.

## 거버넌스 판정: PASS WITH DISCLOSURE

- 기능 diff는 소스·테스트·워크플로 5개 파일뿐이다.
- `data/**`, `forecasts/**`, `calibration/**`, `questions/**`는 기능 diff에서 변경되지 않았다.
- 후보 확률, official snapshot, append-only ledger, archive, champion 산출물을 기능 커밋이 덮어쓰지 않았다.
- `#future` 기본 노출은 고객 표시 결정이다. Scenario V5.2의 저장 상태는 `degraded`이고 champion 자격을 부여하지 않는다.

## 현재 HEAD 판정: HOLD — 후속 데이터 드리프트 3건

기능 병합 뒤의 자동 데이터 갱신 `60b4d4d`가 candidate와 누적 payload를 바꾸면서 다음 3개 테스트가 실패한다.

1. 임베드 대시보드 용량: 1,025,511 bytes로 1,025,000-byte 계약을 511 bytes 초과.
2. stale fixture: 2026-08-12 후보 갱신 후에도 2026-08-13을 stale로 기대하는 테스트가 낡았다.
3. append-only method change의 candidate hash `af81...`와 현재 candidate hash `acf9...`가 불일치한다.

이는 세 기능 커밋의 실패가 아니라 이후 데이터 갱신으로 발생한 별도 검토 항목이다. 원문은 `evidence/targeted_tests.xml`에 있다.
