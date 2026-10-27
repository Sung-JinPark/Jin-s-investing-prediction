# 데이터·시간 감사 (AUDIT_TIME, W4)

기계 판독본: `data/mts_research/derived/data_time_audit.json` · 전부 read-only 실측.

## 달러지수 splice (§6.4, T12·T13)

- 구현 확인: **return-먼저-연결** — `timeseries_v2/features.py:116-118` 은 계열별 log-change 를
  계산한 뒤 `combine_first(DTWEXBGS 우선)` 한다. 다른 base level 직결의 인공 return 경로가
  구조적으로 없다 → **T13 PASS**.
- 실효 전환점: **2006-01-02** (BGS backcast 가 2006 부터 우선;
  원고의 2019-01-02 는 FRED 계열 교체 시점). DTWEXB 범위 ['1995-01-04', '2019-12-31'], DTWEXBGS ['2006-01-02', '2026-10-16'].
- base 차이: 전환점 level 비 0.9079 — level 을 직결했다면
  인공 −9.7% return 이 생겼을 자리다.
- 겹침 구간 return 일치도(공통 3513일): 중앙값 |Δ| 1.67e-04,
  p99 1.25e-03, 최대 8.45e-03 — 방법론 차이는 return 수준에서 미세.
- **T12 PASS**: 방법론 공개일(2019-02-04) 이전 관측일의 BGS 행 3287건 중
  native_pit(당시 가용) 주장 0건 — backcast 는 captured 등급으로만 존재.
- 잔여 caveat: backcast 가 captured_forward 라 역사 재구성에서 pre-capture cutoff 에는 BGS 가 보이지 않는다 — 당시 정보집합 재구성은 DTWEXB 로 내려간다 (정상). 단 운영 '현재' 패널의 pre-2019 달러 return 은 신방법론 backcast 다 — 동결 V8 평가는 2026-08 아카이브 구축 후 실행이라 내적으로 일관.

## 구조적 사실

- captured_forward 행은 available_at=수집 시각 — 역사적 공개 증거가 없어 historical reconstruction 에서 과거 cutoff 에 보이지 않는다 (NASDAQCOM·VIX 백필 전체가 해당). 설계서 §6.2 의 '증거 없는 승격 금지' 를 저장소가 이미 지킨다.
- reconstructed_market_archive 1판만 post-close 보수 상계를 갖는다 (DGS2·DGS10).
- 달러 주간 발표(H.10) 지연은 collection_lag_recent 의 DTWEXBGS 행에서 실측된다.

## 운영기 수집 지연 (관측일 최근 120거래일)

| 계열 | n | 중앙값(일) | p90(일) |
|---|---|---|---|
| DGS10 | 115 | 17.38 | 85.38 |
| DGS2 | 115 | 17.38 | 85.38 |
| DTWEXBGS | 110 | 22.38 | 86.38 |
| FED_EBP | 2 | 80.38 | 80.38 |
| NASDAQCOM | 116 | 17.38 | 85.38 |
| VIX | 120 | 20.38 | 86.38 |

주: 이 수치는 **이 아카이브의 수집 케이던스**(주간 refresh 묶음)이지 원천 공개 지연이 아니다 —
legacy 행에는 원천 공개 시각 증거가 없다 (`source_published_at=null` 유지).

## 정정(revision) 분포

NASDAQCOM·VIX 정정 행 0 — 아카이브는 첫 수집값 유지 중. 종가 정정(§6.3)은 revision_seq 체계로
수용 가능하나 현재까지 관측 0 (T11 의 anchor/terminal 분리는 mts 계층 스키마로 준비됨).
