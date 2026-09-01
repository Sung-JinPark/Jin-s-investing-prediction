# OPEN QUESTIONS — 종합검토 260901 확인 항목 조사 결과 (C-2·C-3·C-4·C-7)

> 지위: 조사 기록 (수정 보류 — 종합검토 설계서의 지시). 각 항목의 수정 여부는 별도 결정.
> 조사: 2026-09-01, 브랜치 `claude/v9-gate`, 읽기 전용 4에이전트 병렬 실측.

## C-2 shadow 원장 origin 필드 — **필드명 오인, 스키마 변경 불필요 (종결 권고)**

- 정식 필드는 최상위 `origin`("2026-08-14"·"2026-08-28")이며 `iso_week`·`knowledge_cutoff`가 병존.
  검토자가 조회한 `origin_date`는 존재한 적 없는 이름 — 데이터 결손이 아니라 파서 불일치.
- 생산·소비 전 경로가 `origin`으로 정합: forecast_id 해시(pipeline.py:670)·주간 중복 방지(:646)·
  성숙 판정 `index_by_date.get(forecast["origin"])`(:707)·해소 기록(:731)·latest `as_of`(:825)·
  성숙 원점 집계(:798,802). `origin_date`는 backtest.py 로컬 변수뿐.
- 원장은 해시체인 append-only라 기존 행 개명 불가, 신규 행에만 별칭 추가는 스키마 이질성만 생성.
  **판정: 변경 불필요 — 외부 파서 안내(필드명 `origin`)로 종결.**

## C-3 v4/v5/v6 fredgraph 잔여 — **게이트 기아 재발 위험 없음, v5·v4 이관은 권장(긴급 아님)**

- **v6**: `public_archive.py`의 fredgraph는 수동 도구(tools/collect_v6_public.py)·테스트 전용,
  워크플로 배선 없음 → **(a) 과거-only, 지연 무해**.
- **v5**: `sources.py:42-51`에 fredgraph 6종(NFCI·WALCL·WTREGEN·RRPONTSYD 포함)이 있고 평일 cron으로
  실시간 수집. 단 **신선도 게이트(pipeline.py:278-283)의 data_cutoff는 v4→v3 replay→V2 canonical
  parquet 경로**라 r20의 V2 공식 API 이관으로 게이트는 이미 fredgraph 지연에서 분리됨.
  남은 리스크는 v5 자체 수집 피처 6종의 **게이트 없는 조용한 노화**뿐.
- **v4**: NASDAQ100을 fredgraph로 주 1회 수집(cron '20 3 * * 6') — 주간 캐덴스라 수일 지연 실질 무해.
- **판정: (b) official_api_transport 패턴 이관을 v5(우선)·v4에 권장하되 긴급성 낮음.**
  KNOWN_LIMITS 1줄 판정 문구 후보: "v5/v4 fredgraph 수집은 신선도 게이트 경로 밖(무해)이나
  약관·노화 관점에서 official API 이관 대상; v6은 과거-only로 제외."

## C-4 cross_asset 첫 FRED 스냅샷 — **성공 확인, 관찰 종료 가능 (종결 권고)**

- 2026-09-01 06:23 UTC 커밋 8e84b1ac: asof=2026-08-31 스냅샷 생성. 영수증에 NASDAQCOM·CBBTCUSD
  모두 `fred-observations`(api.stlouisfed.org) 기록, data_quality "fred-api" status=ok, dropped_rows=0.
- path_tracking_v2.csv에 08-31 3자산 행 추가(weeks_elapsed=4) — 추적 원장 정상 진행.
- #113 회귀 커버 확인: `test_recorded_tracking_day_is_final_even_if_revalues_differ`(기록일 최종성·
  원장 바이트 무수정) + `test_partially_recorded_tracking_day_still_raises`(예외 미삼킴) +
  `test_refresh_excludes_intraday_us_market_bar`(동일 asof no-op).
- **판정: P3 미해결 표에서 명시 종료 가능.**

## C-7 결정 번호·순서 — **불일치 0건, 단 병렬 카운터 중복·배치 역전 실재 (명문화 권고)**

- DECISIONS.md 배치 역전 실재: 12-8(209행)·12-9(255행)가 12-7(310행)보다 앞에 위치
  (번호↔날짜 자체는 일치, 파일 내 배치만 역순 — 내용 무결).
- method_changes.jsonl 38행: rN은 전역 시퀀스가 아니라 **병렬 체인 3개**(메인 r1~r20 /
  scenario-v5-2 r2~r9 / multi-year-stress r1~r3). 각 체인 내부는 번호·시간순 완전 단조(불일치 0).
  단 체인 간 번호 재사용 + append 순서 역전 1건(13↔14행).
- 불변식 명문화 문서는 현재 없음(KNOWN_LIMITS·CLAUDE.md·DECISIONS 전부 부재).
- **판정: KNOWN_LIMITS에 "결정 번호·rN·append 순서는 시간순 일치, 병렬 카운터는 접두사 구분"
  항목 신설이 적절한 재발 방지 위치. (기록 자체는 정확 — 우선순위 낮음, 수정 보류.)**
