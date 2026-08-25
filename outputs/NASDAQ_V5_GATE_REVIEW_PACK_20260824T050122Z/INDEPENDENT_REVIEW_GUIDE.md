# 독립 검토 체크리스트

## P0 — 반드시 재검산

- `research_gate.pass=false`인데 horizon/path 숫자가 노출되지 않는가
- V5가 존재할 때 V2로 조용히 fallback하지 않는가
- `probability_unit=fraction`, `probability_space=research_timeseries_v5_conditional`인가
- `available_at <= origin_cutoff_at` 위반이 0인가
- 장 마감 1초 뒤 자료가 완료 세션으로 역류하지 않는가
- 기존 V1~V4·Scenario·official manifest에 added/removed/changed가 0인가
- 후보와 Gate가 봉인 결과를 본 뒤 변경되지 않았는가

## P1 — 모델리스크

- 21·63일 직접분포 모형이 comparator보다 열등하다는 HOLD 판정이 정확한가
- 하락 origin, extreme-move Q4, 2020, 2022 coverage 실패가 은폐되지 않았는가
- reconstructed archive가 native PIT로 잘못 표시되지 않는가
- forward-only event 자료가 60개 전 계수화되지 않는가
- anchor floor와 convex stacking 제약이 inner fold 밖 정보를 사용하지 않는가

## P2 — 운영

- XNAS 세션 기준 freshness가 주말·휴일을 stale로 오판하지 않는가
- collector secret이 compute/Codex worker로 전달되지 않는가
- Neon/R2 80% HOLD와 원문 삭제 금지가 구현돼 있는가
- Pages는 HOLD artifact를 고객 숫자 없이 렌더하는가

## 예상 판정

코드·계보·보호범위 구현은 PASS 가능하다. 그러나 현재 성능과 신선도 기준으로 숫자 공개는 HOLD가 정합적이다. Gate를 낮추거나 수치를 강제 공개하는 시정은 금지한다.
