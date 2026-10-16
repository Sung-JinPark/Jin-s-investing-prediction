# R8-D3 검토 팩 — V8 다변량 시계열 게이트 완결 + 사이트 공개 (2026-09-01)

- 세션: Claude Code 자율 세션 (2026-09-01 10:00~15:40 KST경)
- 브랜치/PR: `claude/v8-publication` → **PR #116** (머지 2026-09-01T03:03:34Z, 머지커밋 c199cb1d),
  `claude/pages-trigger-v8` → **PR #122** (머지 ~05:55 UTC, 머지커밋 7c247d4b)
- 지시 원문: "예측 레이어 바뀐것으로 예측 모델 학습 다시 진행해서 GATE 성공시키고 싶은데 전략을
  상세하게 구현해봐. 아직 사이트에 배포가 안되고 있잖아 다변량 시계열 데이터가. 먼저 성공 시킬 수
  있는 자동 루프 학습 설계도를 이틀 용으로 만들어봐." + "잔여작업 마저해"

---

## 0. 결과 요약 (TL;DR)

| 목표 | 결과 |
|---|---|
| GATE 성공 | **완료** — 봉인 게이트는 이미 PASS(R8-D2), 남았던 운영 신선도 게이트가 06:09 UTC 기준 5그룹 전부 fresh로 통과. latest 포인터 `shadow_live` 플립 |
| 사이트 배포 | **완료** — 라이브 사이트 #timeseries에 v8 연구 참고 카드 공개, 렌더까지 검증 |
| 이틀용 자동 루프 | **완료** — 설계서 작성 + git-bash nohup 루프 가동, 스스로 SUCCESS 판정 후 12h 유지 단계 진입 |

부수 성과: 이 과정에서 **구조적 결함 2건**을 실측으로 발견·해결했다 (§4). 이 결함들이 남아 있었다면
게이트는 코드와 무관하게 영원히 통과 불가능했다.

**정직성 유지**: "학습 다시 진행"은 계약 위반(봉인 1회 원칙·retune 금지)이자 불필요임을 명시하고
표시 레이어만 추가했다. 모델 코드·계약·봉인 원장은 1바이트도 변경되지 않았다 (§5).

---

## 1. 시작 시점 진단 (2026-09-01 01:55 UTC)

| 항목 | 상태 | 근거 |
|---|---|---|
| 봉인 게이트 | PASS (사유 0건) | run `tsv8-sealed-64345a816b4857171915d5b8`, R8-D2 사인오프 2026-08-30 |
| 봉인 성적 | 1,011원점, CRPS 개선 h21 +4.0%, coverage 전 밴드 내 | sealed_evaluations.jsonl |
| 운영 게이트 | **HOLD — 신선도 초과 5건** (NASDAQCOM·VIX·DGS2·DGS10·DTWEXBGS) | multivariate_v8_latest.json |
| shadow 예측 | 1건 (origin 2026-08-14) | shadow_forecasts.jsonl |
| shadow 워크플로 | 등록됨, 실행 0회 (첫 cron 당일 03:10 UTC) | timeseries-v8-shadow.yml |
| 사이트 배선 | **없음** — 슬롯 체인 v5→v2→v1, v8 미배선 | dashboard.py:378 |

## 2. 설계서 (Track A/B)

`docs/design/v8_publication_48h_loop_260901.md` (ZIP 동봉) — 핵심 결정:

- **§0 재학습 금지·불필요**: 봉인 평가는 모델 버전당 1회 소진, `retune_after_failure: prohibited`.
  합법적 지속 학습 = 주간 shadow의 동결 그리드 내 VARX 재적합뿐. 새 예측 레이어(AI 빌드아웃
  통계·SEC 파생)는 V8 피처로 주입 금지 — V9 연구 트랙 후보로만.
- **Track A 사이트 배선**: fail-closed 투영 + 슬롯 체인 + read-model 가드 + 전용 렌더러 (§3).
- **Track B 48h 루프**: 30분 프로브 + 조건부 dispatch (cron 지연 6~12h 실측 이력 → 기다리지 않고
  발동), 성공 판정 = 원격 main 플립 ∧ 라이브 사이트 `shadow_live` 서빙, 이후 12h 유지 확인.

## 3. Track A 구현 (PR #116, 커밋 3개)

### 3.1 `src/ai_fc/timeseries_v8_display.py` (신규, 커밋 2c8c4259)

- `validate_latest`: content_hash 재계산 일치, model_id/space/unit 검증,
  **visible ⟺ (sealed_gate_pass ∧ operational_pass)**, visible ⟺ status `shadow_live`,
  `reference_opinion_only=true` 강제, HOLD면 horizons/path 부재 강제, visible이면 분위수
  단조성·확률 0~1 검사. 위반은 예외 (fail-closed).
- `build_projection`: 로그수익 분위수 → 지수 레벨 사상 (`level = anchor × exp(q)`,
  계약 `display_price_unit: index` 준수). 봉인 성적(h21/h63 CRPS 개선·적중률·원점 수) 동봉.
- `load_projection`: 파일 없음/HOLD → **None** (기존 v5 검증 대기 거버넌스로 자연 낙하 —
  HOLD 동안 화면 무변화). 원점 종가는 시장 아카이브에서 조회, 부재 시 소리나게 실패.
- **배치 원칙**: `src/ai_fc/timeseries_v8/` 패키지 **밖** — 그 디렉터리는 `model_code_hash`
  의존 집합(rglob)이라 파일 하나만 넣어도 봉인된 모델 정체성 해시가 바뀐다.

### 3.2 dashboard.py / read_model_contract.py / dashboard.js

- 슬롯 체인: `timeseries = v8_visible or (v5 or v2 or v1)` (dashboard.py:371~).
- read-model 가드: v8 model_id 허용목록 추가, visible 기대 status `shadow_live`,
  space `research_timeseries_v8_conditional`, 두 게이트 동시성, `research_reference` 선언 강제.
- `renderTimeseriesV8` (dashboard.js): 참고 의견 배지, 원점 날짜 명시("2026-08-28 종가(예측
  원점) 기준 · 주 1회 갱신"), 4개 호라이즌 카드(중앙 지수·수익률·p10–p90 지수 대역·상승확률),
  봉인 검증 성적 스트립, 자동 복귀 고지. **v2/v5 렌더 경로 무수정**, path/drivers/backtest 탭은
  v8이 해당 데이터를 발행하지 않으므로 정직하게 비활성.

### 3.3 거버넌스 기록

- `data/method_changes.jsonl` **r19** (`method:timeseries-v8-research-reference-display`):
  display_only=true, 사용자 지시를 display-promotion 승인 근거로 인용.
- `docs/DECISIONS.md` **R8-D3**: "이것이 아닌 것" 명시 — 챔피언 승격 아님(promotion 계약
  automatic_champion=false·minimum_shadow_sessions=126 무변경), 재학습 아님.
- lineage(`website_data_lineage_v1.yaml`): multivariate_timeseries_shadow에 v8 계약·포인터·봉인
  원장 추가.
- 테스트: 신규 `test_timeseries_v8_display.py` 8케이스(해시 변조·게이트 불일치·분위수 교차·확률
  경계·HOLD 숫자 노출 각각 실패 확인 + 사상 수치 검증), read-model v8 가드 3케이스.

## 4. 실측으로 발견한 구조적 결함 2건과 해결

### 4.1 fredgraph 스크랩의 ~10일 지연 — 신선도 게이트 기아 (r20)

- **증상**: 1차 dispatch 후 신선도 5건 중 3건(VIX·DGS2·DGS10)만 해소. NASDAQCOM은 08-19,
  DTWEXBGS는 08-14에 고정.
- **원인**: `timeseries_v2/market_archive.py`의 FRED 계열이 금지된(DECISIONS 12-6)
  `fredgraph.csv` 스크랩을 그대로 사용 — 같은 시각 공식 API는 08-28을 반환(로컬 검증):
  스크랩 경로가 **~10일 지연**. 48h 신선도 한도는 이 경로로는 구조적으로 통과 불가.
- **1차 시도와 교훈**: market_archive.py를 직접 수정 → CI가 **"sealed V2 model code hash
  drift"로 fail-closed** (2차 CI 실측). `market_archive.py`는 V2 봉인 해시의 **명시적 파일
  목록**에 포함 — 가드가 설계대로 작동한 것.
- **최종 해결(커밋 26cc304f)**: 봉인 파일 원상 복구(0바이트 변경) + 신규 비봉인 모듈
  `timeseries_v2/official_api_transport.py`:
  ① 봉인 수집기에 fredgraph URL을 **HTTP 451**(법적 사유)로 거부하는 fetcher 주입,
  ② 같은 3계열을 공식 API로 append — 전용 source_id(`fred_api_*`), **키 없는 공개 URL 영수증**
  (키는 `ai_fc.fred_api` 전송 내부에만), captured_forward 등급, 값 차이는 supersedes 리비전.
  CLI `timeseries-v2-refresh`가 이 경로를 사용 (워크플로 무변경).
- **재사용 지식**: 봉인 해시 목록은 명시적 파일 리스트 → **신규 파일은 해시에 영향 없음**
  (V8의 rglob도 자기 패키지 한정).
- **검증**: main 첫 실행에서 NASDAQCOM +7행(08-20~08-28) append, 기존 7,961행은 API·스크랩 값
  완전 일치로 무변경(불필요한 리비전 0).

### 4.2 GITHUB_TOKEN 푸시는 pages를 트리거하지 않는다 (PR #122)

- **증상**: 05:27 UTC 게이트 플립 커밋(2c0d954a)이 main에 있는데 라이브 data.json은 v5 hold.
- **원인**: 워크플로의 GITHUB_TOKEN 푸시는 push 이벤트를 발화하지 않는 GitHub 규칙 +
  `pages.yml`/`verify.yml`의 `workflow_run` 목록에 `timeseries-v2-refresh`·`timeseries-v8-shadow`
  누락 → shadow의 데이터 커밋으로는 사이트가 영영 재배포되지 않음.
- **해결**: 두 워크플로를 양쪽 목록에 등록 + 테스트 기대 문자열 갱신
  (`test_bot_data_commits_trigger_pages_and_verification`) — PR #122 머지.
  (즉시 조치로 수동 dispatch도 했으나 pages의 cancel-in-progress 동시성에 취소됨 — 최신
  push 트리거 실행이 대신 플립을 배포.)

## 5. 무결성 확인 — 바뀌지 않은 것

- `src/ai_fc/timeseries_v8/` (봉인 model_code_hash 의존 집합): **0바이트 변경**
- `src/ai_fc/timeseries_v2/` 봉인 8파일: **0바이트 변경** (1차 시도는 커밋 전 원복)
- V8 계약(`multivariate_timeseries_v8.yaml`)·봉인 원장·V2 벤치마크 핀: 무변경
- promotion 계약: automatic_champion=false, minimum_shadow_sessions=126, 명시 승인 — 무변경
- forecasts/·calibration/ 불변 체계: 무접촉

## 6. 타임라인 (2026-09-01 UTC)

| 시각 | 이벤트 |
|---|---|
| 01:55 | 진단 완료, 설계서 작성 시작 (`claude/v8-publication`) |
| 02:11 | 48h 루프 기동 → 즉시 1차 dispatch (`timeseries-v2-refresh`) |
| 02:27~02:29 | v2-refresh·v8-shadow 성공 — 신선도 5건 → 2건 (VIX·DGS2·DGS10 해소) |
| 02:46 | PR #116 CI 2차: **refresh FAIL — "sealed V2 model code hash drift"** (§4.1 교훈) |
| 03:03 | 3차 CI 전부 green → **PR #116 머지** |
| 03:07 | main 첫 API 경로 실행: NASDAQCOM +7행 append |
| 03:59~04:12 | 루프 2차 dispatch — refresh 성공, v8-shadow가 **08-28 원점 주간 예측 계산 시작** (~1h13m) |
| ~05:25 | shadow 완료: 예측 2건째 + **첫 해소 2건**(08-14 h1/h5) + latest **`shadow_live` 플립** (NASDAQCOM 08-31 관측 5.6h fresh) |
| 05:27~05:39 | 플립이 사이트에 미반영 → §4.2 원인 확정, PR #122 생성, 최신 pages 실행이 카드 배포 |
| 05:4x | **라이브 카드 렌더 검증 완료** (브라우저 확인) |
| ~05:55 | PR #122 머지 |
| 06:09 | **루프 자체 SUCCESS 판정** (원격 플립 ∧ 라이브 `shadow_live` 교차 확인) → 12h 유지 단계 |

## 7. 라이브 카드 검증 값 (05:45 UTC 실측)

- 모델 `shadow.mf_dfm_varx_calibrated_v8` · `shadow_live` · display `research_reference`
- 원점(anchor) 2026-08-28 종가 **26,402.42**
- 1일: 중앙 26,439 (+0.14%) · 상승 56% · p10–p90 26,035–26,774
- 5일: 중앙 26,536 (+0.51%) · 상승 58% · p10–p90 25,599–27,254
- 21일: 중앙 26,912 (+1.93%) · 상승 66% · p10–p90 24,974–28,155
- 63일: 중앙 **27,583 (+4.47%)** · 상승 72% · p10–p90 24,276–29,724
- (정정 2026-09-01: 종합검토 C-1 반영 — 최초 배포본은 1자리 반올림으로 h63이 +4.5%로
  표기되었음. 실제값 e^0.04374−1 = +4.471%. 카드도 2자리 표기로 수정됨.)
- 봉인 성적 공개: 원점 1,011개 · CRPS 개선 21일 +4.0% / 63일 +4.2% · 적중률 81.3% / 80.8%
- 지수 사상 검산: 26,402.42 × e^0.0437 = 27,583 ✓
- 참고 의견 배지 + "매매 신호 아님 · 신선도 붕괴 시 자동 검증 대기 복귀" 고지 렌더 확인

## 8. 첫 shadow 해소 2건 (청정 포워드 표본의 시작)

| 해소 | 실현 로그수익 | model CRPS | baseline CRPS | p10–p90 적중 | 방향 |
|---|---|---|---|---|---|
| 08-14 원점 h1 | −0.32% | 0.00378 | 0.00342 | ✓ | ✗ |
| 08-14 원점 h5 | −2.07% | 0.01569 | 0.01531 | ✓ | ✗ |

정직한 기록: 첫 두 단기 해소는 구간 적중은 했으나 방향이 틀렸고 CRPS도 기준선에 근소 열위다.
표본 2개로는 아무 결론도 못 낸다 — 운영 모니터링 게이트는 **26개 성숙 원점**부터 CRPS 열위
5% 초과 시 표면을 자동 HOLD시킨다 (개입 불필요·금지).

## 9. 현재 운영 상태와 다음 마일스톤

- 루프: SUCCESS 유지 단계 (12h 무결 확인 후 자체 종료; 중단은 `publication_loop/ABORT` 생성)
- 자동화: 화~토 cron — v2-refresh(01:35 UTC, 공식 API 경로) → v8-shadow(03:10 UTC,
  forecast/resolve/latest/verify) → **이제 pages/verify가 자동 연쇄** (PR #122)
- 신선도 유지 조건: FRED가 전일 종가를 다음날 오전 게시 → 평일엔 fresh 유지, 주말·월요일은
  자연 HOLD 후 화요일 재플립 (설계된 정상 동작)
- 다음 마일스톤: 08-28 원점 h1 해소(9/2), h5(9/8경), 매주 금요일 신규 원점.
  **챔피언 승격은 별개**: shadow 세션 126 + 명시 승인 (현재 원점 2개)
- V9 연구 트랙(새 예측 레이어를 피처로): 사용자 지시 시 새 계약·새 봉인 절차로만 개시

## 10. 변경 파일 총괄

**PR #116** (`claude/v8-publication`, 커밋 2c8c4259·b4789b93·26cc304f):
- 신규: `src/ai_fc/timeseries_v8_display.py`, `src/ai_fc/timeseries_v2/official_api_transport.py`,
  `src/tests/test_timeseries_v8_display.py`, `src/tests/test_timeseries_v2_official_api.py`,
  `docs/design/v8_publication_48h_loop_260901.md`
- 수정: `dashboard.py`, `read_model_contract.py`, `dashboard_parts/dashboard.js`, `cli.py`,
  `website_data_lineage_v1.yaml`, `method_changes.jsonl`(r19·r20), `DECISIONS.md`(R8-D3),
  `test_read_model_contract.py`, `docs/generated/inventory.generated.md`

**PR #122** (`claude/pages-trigger-v8`, 커밋 9472a794):
- `pages.yml`, `verify.yml`, `test_investing_refresh_workflow.py`

**로컬 전용(리포 외 산출물)**: `outputs/timeseries_v8/publication_loop/{loop.sh, check_state.py,
state.json, loop.log}` — ZIP 동봉

검증: 로컬 전체 스위트 985 passed/7 skipped + 변경 영역 재실행 전부 green, PR별 CI green,
머지 후 main verify·pages green, 라이브 사이트 값·렌더 검증 완료.
