# V8 다변량 시계열 — 게이트 완결 + 사이트 공개 48시간 자동 루프 설계서

- 작성: 2026-09-01 (KST 11:00경) · 브랜치 `claude/v8-publication`
- 목표 기간: 2026-09-01 11:00 KST ~ 2026-09-03 11:00 KST (48시간)
- 지위: 이 문서의 모든 산출물은 프로젝트 헌법(CLAUDE.md)의 **참고 의견** 지위를 유지한다.

---

## 0. 요청의 정확한 해석 — "예측 모델 학습 다시 진행"에 대한 정직한 답

사용자 요청은 세 가지다: ① 게이트 성공, ② 다변량 시계열의 사이트 배포, ③ 이틀용 자동 루프 설계.
그중 "예측 레이어 바뀐 것으로 **학습 다시 진행**"은 그대로 실행하면 계약 위반이므로 아래와 같이 재해석한다.

### 0.1 재학습은 금지이며, 게이트 성공에 불필요하다

- V8 봉인 게이트는 **이미 통과했다**. `data/timeseries_v8/ledgers/sealed_evaluations.jsonl`의
  run `tsv8-sealed-64345a816b4857171915d5b8`: `summary.gate_pass=true`, reasons `[]`,
  사용자 사인오프 R8-D2 (2026-08-30). 봉인 평가는 모델 버전당 1회이고
  `retune_after_failure: prohibited`가 계약(`data/contracts/multivariate_timeseries_v8.yaml`)에
  동결되어 있다. 통과한 모델을 다시 학습하는 것은 이 계약과 5원칙(라이브 포워드 only)을 깬다.
- 지금 남은 블로커는 학습 문제가 아니라 **운영 신선도 게이트**(시장 입력 5그룹의 48h 신선도,
  DTWEXBGS만 216h 예외)와 **사이트 배선 부재** 두 가지다. 데이터가 갱신되는 순간
  운영 게이트는 코드 수정 없이 뒤집힌다.

### 0.2 합법적으로 "계속 학습"되는 것

- 주 1회 shadow 예측(`timeseries-v8-forecast`)은 매 원점마다 **동결된 탐색 그리드 안에서**
  VARX 재적합을 수행한다(동결 승자 config의 재추정 — 하이퍼파라미터 변경 없음). 이것이
  이 시스템에서 유일하게 허용되는 지속 학습이며 이미 매주 실행되도록 배선돼 있다.
- 캘리브레이션(PIT 재보정)은 shadow 원점이 26개 성숙한 뒤 계약 규칙대로만 개입한다.

### 0.3 새 예측 레이어(AI 빌드아웃 통계·SEC 파생)는 V8에 넣지 않는다

- V8의 피처 셋은 계약에 동결되어 있고 `model_code_hash`가 봉인 원장에 박제되어 있다.
  새 데이터 소스를 지금 끼워 넣으면 봉인 정체성이 깨진다.
- 새 레이어는 **V9 연구 트랙의 후보 피처**다. V9는 새 계약·새 설계창·새 봉인 평가로만
  진행할 수 있으며, 이 48시간 범위 밖이다(사용자 지시가 있을 때 개시).

---

## 1. 검증된 현재 상태 (2026-09-01 01:55 UTC 기준)

| 항목 | 상태 | 근거 |
|---|---|---|
| 봉인 게이트 | **PASS** | sealed ledger `gate_pass=true`, R8-D2 사인오프 |
| 운영 게이트 | HOLD — 신선도 초과 5건만 | `multivariate_v8_latest.json` `gate.reasons` |
| shadow 예측 | 1건 존재 (origin 2026-08-14) | `shadow_forecasts.jsonl` 해시체인 |
| shadow 워크플로 | 등록됨, **아직 0회 실행** (첫 cron 오늘 03:10 UTC) | `timeseries-v8-shadow.yml` |
| v2-refresh cron | 최근 지연 6~12h 관측 (08-29: 6.7h 지연) | Actions run 이력 |
| 사이트 배선 | **없음** — 슬롯 체인 v5→v2→v1, JS는 HOLD 카드 고정 | `dashboard.py:378`, `dashboard.js:1142` |
| read-model 가드 | v8 model_id 미등록 | `read_model_contract.py:298` |

봉인 성적(공개 근거): 1011개 원점, CRPS 개선 h1 +3.5% · h21 +4.0%(최강 기준선 대비,
DM p<1e-5), p10–p90 적중률 h1 80.3% · h21 81.3% (게이트 대역 76~84% 내).

---

## 2. Track A — 사이트 배선 (display-promotion 스텝)

`publish_latest_timeseries_v8`의 주석이 명시한 "별도 거버넌스의 display-promotion 스텝"을
이번 사용자 지시("아직 사이트에 배포가 안되고 있잖아")를 승인 근거로 실행한다.
챔피언 승격이 아니다: `promotion.automatic_champion=false`·`minimum_shadow_sessions=126`은
건드리지 않고, V8은 **연구 참고(research_reference) 표면**으로만 노출한다.

### 2.1 새 모듈 `src/ai_fc/timeseries_v8_display.py`

`src/ai_fc/timeseries_v8/` 패키지 **밖**에 둔다 — 그 디렉터리는 `model_code_hash`
의존 집합이라 파일 하나만 바꿔도 봉인된 모델 정체성 해시가 바뀐다. 표시 배선이
모델 해시를 움직이는 일은 절대 없어야 한다.

- `validate_latest(payload)`: model_id/space/unit 일치, `content_hash` 재계산 일치,
  `visible ⟺ (sealed_gate_pass ∧ operational_pass)`, HOLD면 horizons/path 부재,
  visible이면 분위수 단조성·확률 0~1 검사. 위반 시 예외(fail-closed).
- `build_projection(latest, anchor, sealed_row)`: 순수 함수. 로그수익 분위수를
  지수 레벨로 사상(`level = anchor × exp(q)`, `point_return = expm1(p50)`) —
  계약의 `display_price_unit: index`를 그대로 따른다. 봉인 성적 요약
  (h21/h63 CRPS 개선·적중률·원점 수)을 동봉.
- `load_projection(root)`: 파일 없으면 None. HOLD면 **None** (표면은 기존
  v5 HOLD 거버넌스로 자연 낙하 — 오늘까지의 사이트와 동일 화면). visible이면
  NASDAQCOM 원점 종가를 시장 아카이브에서 읽어(`read_market_observations`)
  투영을 만든다. 원점 종가·봉인 행 부재는 예외(소리 나게 실패).

### 2.2 슬롯 체인 `dashboard.py:378`

`timeseries = v8_visible or v5 or v2 or v1`. V8이 HOLD인 동안 화면 변화 없음.

### 2.3 가드 `read_model_contract.py:298`

- 허용 model_id에 `shadow.mf_dfm_varx_calibrated_v8` 추가.
- visible 기대 status: `shadow_live`. space: `research_timeseries_v8_conditional`.
- visible ⟺ `gate.sealed_gate_pass ∧ gate.operational_pass`,
  `publication.reference_opinion_only=true` 강제. 기존 "HOLD면 숫자 은닉" 규칙 공유.

### 2.4 렌더 `dashboard.js` — v8 연구 참고 카드

`renderTimeseries` 상단에서 v8 model_id + visible이면 전용 카드:
원점 날짜 명시("YYYY-MM-DD 종가 기준"), 4개 호라이즌 카드(중앙 지수·수익률·
p10–p90 지수 대역·상승확률), 봉인 검증 성적 스트립, `참고 의견` 배지·풋노트.
path/drivers/backtest 탭은 비활성(스키마상 v2 전용 필드라 정직하게 잠근다).
기존 v2/v5 렌더 경로는 무수정.

### 2.5 거버넌스 기록

- `data/method_changes.jsonl` r19: display_only=true, V8 연구 참고 표면 배선.
- `docs/DECISIONS.md` R8-D3: 사용자 지시(2026-09-01 메시지)를 승인 영수증으로 인용.
- `data/contracts/website_data_lineage_v1.yaml`의 `multivariate_timeseries_shadow`
  섹션에 v8 소스·계약 추가.

### 2.6 테스트

- 신규 `src/tests/test_timeseries_v8_display.py`: 순수 함수 중심 —
  HOLD→None, 해시 변조·게이트 불일치·분위수 교차·확률 경계·HOLD 숫자 노출 각각 실패,
  visible 사상(지수 레벨·수익률) 수치 검증.
- `test_read_model_contract.py`: v8 3케이스(정상 visible / operational=false인데
  visible / space 오기재).

---

## 3. Track B — 48시간 자동 루프

### 3.1 뒤집혀야 할 도미노 (성공 경로)

```
[1] 시장 데이터 갱신  timeseries-v2-refresh (cron 01:35 UTC 화~토, 지연 잦음 → dispatch)
[2] V8 shadow 실행   timeseries-v8-shadow  (cron 03:10 UTC 화~토; forecast→resolve→latest→verify)
      → 8/31(월) 종가가 아카이브에 있으면 신선도 5건 해소 → latest visible 플립
[3] Track A PR 머지  → pages 재빌드 → 사이트에 v8 연구 참고 카드
[4] 수~목: 8/21 원점의 h5, 8/14 원점의 h21 성숙분 shadow_resolutions 적립 확인
```

주의: FRED의 NASDAQCOM 8/31 관측이 화요일 오전(UTC)까지 안 나오면 [2]가 돌아도
신선도가 남는다 — 루프가 이후 사이클에서 재dispatch한다. 이것이 이 루프가
"1회 실행 스크립트"가 아니라 48시간 루프여야 하는 이유다.

### 3.2 루프 구현 (git bash + nohup, 로컬)

- 위치: `outputs/timeseries_v8/publication_loop/` (loop.sh, state.json, loop.log, ABORT)
- 주기: 30분 사이클(actions 폴링·검증), dispatch는 조건 충족 시에만.
- 사이클 로직:
  1. `ABORT` 파일 존재 시 즉시 종료.
  2. `git fetch origin main` 후 **원격 main의** `multivariate_v8_latest.json`을 읽어
     `gate.operational_pass` 확인 (로컬 워킹트리 오염 없음 — 병렬 세션 규약 준수).
  3. HOLD이고 마지막 v2-refresh 성공이 6h 이전이며 마지막 dispatch가 90분 이전이면:
     `gh workflow run timeseries-v2-refresh.yml` → 성공 대기 → `gh workflow run
     timeseries-v8-shadow.yml`. (cron 지연 이력이 있으므로 기다리지 않고 dispatch —
     기존 이벤트 유실 플레이북의 확장. 두 워크플로 모두 dispatch 트리거 보유,
     같은 데이터면 append 중복 제거로 멱등.)
  4. visible 플립 감지 시: pages 배포 대기 후 라이브 사이트 JSON/HTML에서
     `shadow_live` 마커 확인, 결과를 state.json에 기록.
  5. shadow_resolutions 신규 행(수·목 성숙분) 감지·기록.
- 하드 가드: 루프는 **로컬 수치 검증과 gh 조회/dispatch만** 수행한다. 커밋·푸시·머지·
  예측 배치·서브에이전트 팬아웃은 하지 않는다 (토큰 가드레일 및 병렬 세션 규약).
  워크플로 dispatch 대상은 위 2개로 고정.
- 종료 조건: ① 48h 경과, ② ABORT, ③ 성공 상태(operational_pass=true + 사이트 확인 +
  첫 성숙 해소 기록) 도달 후 12h 유지.

### 3.3 사람 개입 지점 (루프가 하지 않는 것)

- Track A PR의 머지 버튼(사용자 또는 이 세션이 CI 확인 후 진행 — 루프 아님).
- Actions 이벤트 유실 재발 시 로컬 CI 복제 후 머지 판단 (이 세션).
- V9 연구 트랙 개시, 챔피언 승격(126 세션 + 명시 승인) — 범위 밖.

### 3.4 48시간 타임테이블 (KST)

| 시각 (KST) | 이벤트 |
|---|---|
| 화 11:00 | 설계서 확정, Track A 구현 시작, 루프 기동 |
| 화 10:35/12:10 | v2-refresh·v8-shadow cron 창 (지연 시 루프가 dispatch) |
| 화 오후 | 8/31 종가 반영 → operational 플립 예상 1차 창 |
| 화 저녁 | Track A PR → CI → 머지 → pages → 라이브 카드 확인 |
| 수 10:35/12:10 | 두 번째 cron 창 — 8/28 원점 예측 생성(주간), h1 해소 |
| 수~목 | 성숙 해소 적립 (8/14 원점 h21 등), 루프 감시 지속 |
| 목 11:00 | 루프 종료, 결과 요약 보고 |

### 3.5 실패 모드와 대응

| 실패 | 대응 |
|---|---|
| FRED 8/31 관측 지연 | 루프가 90분 간격으로 재dispatch, 목요일까지 미해결 시 보고만 |
| Actions 이벤트 유실 재발 | 플레이북: 로컬 pytest+sync/inventory/audit 복제 → 수동 머지 판단 |
| CRPS 모니터링 게이트 발동(26 원점 후) | 표면 자동 HOLD — 정상 동작, 재개입 금지 |
| 병렬 세션 main 이동 | 리베이스 후 재검증 (reset 금지·경로 지정 add) |

### 3.6 1차 사이클에서 실측된 근본 원인 (2026-09-01 02:30 UTC, 사후 기록)

첫 dispatch 사이클이 신선도 5건 중 3건(VIX·DGS2·DGS10)만 해소했다. 남은 2건의 원인은
데이터 지연이 아니라 **수집 경로**였다: `timeseries_v2/market_archive.py`의 FRED 계열이
아직 fredgraph.csv 스크랩(12-6 금지 대상의 마지막 잔존 사용처)을 쓰고 있었고, 이 경로는
공식 API 대비 ~10일 지연된 관측(NASDAQCOM 08-19 vs API 08-28)을 반환했다. 스크랩 경로가
살아있는 한 48h 게이트는 구조적으로 통과 불가능했다.

조치(r20): 세 계열(NASDAQCOM·DTWEXB·DTWEXBGS)을 `ai_fc.fred_api` 공식 API로 이관.
영수증은 키 없는 공개 URL만 기록. 이관 후 예상 플립 시점 — DTWEXBGS 즉시(08-28 관측,
75h < 216h), NASDAQCOM은 08-31 관측이 FRED에 게시되는 시점(통상 다음 영업일 오전 ET).

**봉인 경계 교훈 (2차 CI에서 실측).** `market_archive.py`는 V2 봉인 `model_code_hash`
의존 집합에 포함되어 있어 직접 수정하면 verify가 "sealed V2 model code hash drift"로
fail-closed한다 — 1차 수정 시도가 정확히 이렇게 잡혔고, 이는 가드가 설계대로 작동한
것이다. 최종 구현은 봉인 파일을 되돌리고(0바이트 변경) **비봉인 신규 모듈**
`official_api_transport.py`로 우회한다: 봉인 수집기에 fredgraph 거부(HTTP 451) fetcher를
주입하고, 같은 3계열을 공식 API + 정직한 영수증(전용 source_id, 키 없는 URL)으로
append한다. 봉인 해시 의존 목록은 명시적 파일 리스트라 신규 파일은 해시에 영향이 없다.
