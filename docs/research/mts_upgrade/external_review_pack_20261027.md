# MTS Research 계층 — 외부 검토 팩 (External Review Pack)

작성: 2026-10-27 (KST) · 작성 주체: Claude Code (구현 수행자 본인 — 이 문서는 자기 보고임을 감안하고 읽을 것)
대상 독자: **저장소 접근이 없는 외부 AI 리뷰어**
검토 대상: 2026-10-26 구현 → 2026-10-27 main 머지 완료분
(PR #356, merge commit `788505d7`, repo `Sung-JinPark/Jin-s-investing-prediction`)

---

## 0. 검토자 안내

### 0.1 이 문서의 목적

NASDAQ 다변량 시계열 예측 시스템에 "연구 계층(mts_research)"을 신설한 작업의 **설계·구현·검증·감사 전모**를,
저장소를 열어 보지 않고도 검토할 수 있도록 담았다. 요청하는 것은 두 가지다.

1. **오류 탐지**: 수식·통계 절차·시간 계약·구현 선택에서 틀린 것, 누수(leakage) 경로, 숨은 가정.
2. **설계 비판**: 더 나은 대안이 있는 선택, 과잉/과소 설계, 다음 단계(W5~W8)의 위험.

§12에 구체적 검토 질문 목록이 있다. §11은 작성자가 스스로 아는 약점 목록이다 — 거기서 멈추지 말고
그 밖의 약점을 찾아 달라.

### 0.2 검토자가 가정해도 되는 것 / 안 되는 것

- **가정 가능**: 이 문서의 수치·코드 발췌는 머지된 저장소 상태 기준이며, 작성 직후 **독립 검증
  패스**(별도 에이전트 5개가 전 섹션의 주장을 저장소 원본·원장 재계산과 전수 대조)가 찾아낸
  불일치를 전부 반영했다. 그 뒤에도 저장소에 증거가 없는 서술은 본문에 [저장소 미기록]으로 표시했다.
- **가정 금지**: "테스트 127개 통과"는 코드가 자기 계약을 지킨다는 뜻이지 **예측 성능의 증거가 아니다**.
  이 구분은 설계서 §19.2가 명시하고, 본 작업의 모든 판정이 이 구분을 따른다.
- 이 시스템의 어떤 출력도 매매 신호가 아니라 **참고 의견**이다 (프로젝트 헌법 CLAUDE.md).

### 0.3 용어 최소 사전

| 용어 | 뜻 |
|---|---|
| origin (원점) | 예측을 발행하는 거래일. 그 시점의 정보만 사용 가능 |
| horizon h | 원점 이후 h번째 **거래 세션** (h1/h5/h21/h63) |
| RV21 | 직전 21개 거래일 로그수익의 표본표준편차(ddof=1, 평균 제거) × √252 — 연율화 실현변동성 |
| θ (theta) | V13 RV 사건 임계 = 0.1694 (연율화 RV21이 이를 넘으면 사건) |
| PB (persistence baseline) | "현재 상태가 지속된다"는 로지스틱 지속성 기준선 — V13 챔피언 `persistence_pb` |
| FHS | Filtered Historical Simulation — EWMA 표준화 역사 수익으로 장기(h21/h63) 분포 생성 |
| PIT | Probability Integral Transform — 과거 예측 분포에서 실현값의 분위; 재보정 입력 |
| 성숙(mature) | 라벨 확정에 필요한 시간이 다 지나 결과를 아는 상태. 성숙 전 집계는 금지 |
| shadow | 공식 표시에 올리지 않고 병행 기록만 하는 운영 모드 |
| 봉인(sealed) / 홀드아웃 | 1회성 평가 전용 구간 — bytes 읽기 자체가 소모로 간주되는 보호 자원. V8의 창: 홀드아웃 2015-01-01~2018-12-31(1회 소모됨), 봉인 2019+(1회 평가 소모됨) |
| rung | 트랙의 개발 평가 사다리 단계 — rung 하나가 등록 실험 1회 묶음 |
| V14-D10 / V14-D11 / V13-D13 | 사용자 결정 ID — D10: V14 챔피언·모듈화 결정(대기), D11: V14 rung-2 실험 승인(대기), V13-D13: 사건<20 또는 국면<5인 셀의 '판정불가' 제한(2026-10-22 발효) |
| BSS | Brier Skill Score = 1 − Brier_model / Brier_climatology |
| identity (동일성) 재현 | 동결 모델의 기록된 출력을 재계산해 bit/허용오차 수준으로 일치시키는 검증 |

---

## 1. 시스템 배경 (이 작업이 놓인 지형)

### 1.1 프로젝트 성격

개인 포트폴리오의 EXIT 트리거 이벤트를 확률화하는 예측 시스템. LLM 기반 이벤트 예측(별도 트랙)과
**결정론 수치 시계열 모델**(이번 작업의 영역)이 공존한다. 핵심 헌법 조항:

- **라이브 포워드 only** — LLM이 개입하는 평가는 과거 질문 백테스트 금지. 단 **결정론 수치 모델의
  과거 데이터 적합·워크포워드는 명문화된 예외**(사전지식 오염이 없으므로). 이번 작업은 전부 예외
  범위(수치 모델) 안이며, 산출물은 base rate 참조이지 캘리브레이션 표본이 아니다.
- **불변 기록** — 예측·원장은 append-only. 정정은 새 행(supersedes)으로만.
- **확률 단위** — 저장은 fraction [0,1]. 침묵 clipping/정규화로 검증을 통과시키는 것 금지.
- **point-in-time** — 예측은 `available_at ≤ as_of`인 정보만 사용. 미래·사후정정 유입 금지.

### 1.2 시계열 트랙 지형 (이 작업 이전의 상태)

| 트랙 | 상태 | 요지 |
|---|---|---|
| V2 | 동결 기반 엔진 | ridge VARX 선택·분포 파라미터·경로 시뮬 커널. V8이 재사용 |
| V8 | `frozen_for_sealed_evaluation` + shadow 운영 | NASDAQ 로그수익 분포 예측 (h1/h5/h21/h63, 200레벨 quantile grid). 동결 전 성적: 설계창 CRPS +2.86% → **홀드아웃(2015-2018, 1회 소모) +4.04%** (CI90 상단 −0.00106, proxy PASS). **봉인 평가는 별도 1회 run** — 전체창 1,011원점 GATE PASS, 봉인창(2019+) 385원점 단독은 자체 판정 hold. 현재 126 shadow 세션 승격 게이트 진행 중 (2026-10-21 기준 46/126) |
| V13-VOL | `live_reference` | 변동성 사건 확률 (RV21>θ, VIX≥25, VIX≥30 × h5/h21/h63 = 9셀). 챔피언 `persistence_pb` = **셀 관측값 x_t 단일 회귀변수 로지스틱**(대안 후보 ewma_logit은 [x_t, EWMA21(x_t)]) — 설계창 2007-2014에서 1회 적합, 계수 sha256 핀 동결(refit_prohibited). θ=0.1694는 **설계창 RV21 중앙값**(사전등록 고정값). 개발 예산 8/8 소진, 홀드아웃 3/9 셀 통과(vix25_h21·rv_h5·rv_h21), 라이브 게이트 = 셀당 성숙 원점 60 |
| V14 | `prereg` | **평온 조건부**(원점 VIX<20, RV21≤θ) 돌파 전이 확률. 개발 예산 1/4 소진(rung-1 채택 0), rung-2는 사용자 결정 V14-D11 + 리터럴 승인 영수증 대기. 홀드아웃 0슬롯(오염-재사용불가), 판정은 live forward 전용 |
| daily6m | `predictive_validation: not_established` | 6개월 일별 경로 — 예측 검증 미확립 상태가 계약·코드 4곳에서 강제됨 |

### 1.3 저장소의 보호 장치 (이번 작업이 지켜야 했던 것)

CI가 실제로 잡는 것들이다. 이번 작업의 모든 설계 선택이 이 제약에서 출발한다.

| 보호 | 범위 | 함의 |
|---|---|---|
| V8 `model_code_hash` | `src/ai_fc/timeseries_v8/**/*.py` + `timeseries_v2/{model,backtest,features,dfm_cache}.py` + `timeseries/{model,backtest}.py` | 한 줄 수정도 주간 원장 대조 테스트 실패 → **adapter는 무수정 import-호출만** |
| V14 자동화 금지 테스트 | 공유 `cli.py`·workflows의 `timeseries_v14` 문자열, `src/ai_fc/timeseries_v14/` 패키지 | V14-D10 결정 전 금지 → hazard는 `mts_research` namespace에, 자체 CLI 분리 |
| V5.2 보호 루트 | `data/scenarios/nasdaq_latest.json`·`data/scenarios/archive`, `data/{ml_history,signals,liquidity,cross_asset,ai_capital_cycle}`, `forecasts/`, `calibration/`, `questions/registry.yaml` | **새 파일 추가조차** protected-hash 테스트 실패 → 신규 데이터 루트는 `data/mts_research/` (보호 밖) |
| V13 계수 핀 | `champion_coefficients.json` sha256 핀, refit_prohibited | PB replay는 저장 계수 read-only |
| V7 보호 glob | `test_multivariate_timeseries*.py` 등 이름 패턴 | 신규 테스트는 `test_mts_research_*` 네이밍 |
| 원장 거버넌스 | `ledger_registry.yaml` 등록 + `inventory --check` | 신규 원장 6종을 추가-전용 등록 (`expected_state: planned`) |

### 1.4 예산·승인 체계

실험은 트랙별 계약에 개발 평가 횟수 상한이 있고, 소진 후 재개·게이트 결정은 **사용자만** 내린다.
승인은 `approvals.jsonl`에 리터럴 텍스트 영수증(예: "V14-D10 A1 승인", receipt_id
`v14-approval:<ID>:<date>:r<N>`)으로 남아야 유효하다. 홀드아웃·봉인 구간은 **bytes 읽기 자체가
소모**다. 이번 작업은 **어느 트랙의 예산도 소모하지 않았고 홀드아웃·봉인 bytes를 0회 읽었다** (§8).

---

## 2. 입력: 고도화 설계서 개요

### 2.1 문서 자체

- `docs/design/NASDAQ_forecasting_upgrade_design_20261026.md` — 외부 AI가 이 시스템의 내부
  원고(1,250줄 explainer)를 읽고 작성한 2,300줄 설계서 (작성 주체가 ChatGPT라는 것은 세션 맥락
  기준 — [저장소 미기록]). 151,199 bytes, SHA-256 `3783b26c…acd900b`.
  Downloads 원본을 해시 검증 복사 후 삭제(=이동)로 반입.
- 구조: §0(읽는 규칙) ~ §22(참고문헌) + 부록 A(채점 수식)·B. 주요 장:
  §3 목표함수(평가 계약·3축 분리) / §4 표적·라벨 계약 / §5 아키텍처(챔피언 보호 연구 계층) /
  §6 데이터·시간 증거 / §7 외부 데이터 / §8 특징·DFM 감사 / §9 모델(단일 확률 객체·hazard) /
  §10 보정 / §11 daily6m 결합 / §12 검증(이중 시간 순서·성숙 OOF) / §13 통계(공동 블록
  재표집·다중검정) / §14 제한된 실험 명세 / §15 판정·승격 분리 / §16 운영·재현성 /
  §17 코드 구조·타입 계약 / §18 draft 실행 설정 / §19 수용 테스트 60종 / §20 작업 명세 /
  §21 실행 지시문.

### 2.2 작업 패키지 W0~W8

| W | 내용 | 이번 범위 |
|---|---|---|
| W0 | 저장소 인벤토리 (원고 전제 vs 실상태 대조) | **수행** |
| W1 | 시간·표적·snapshot 계약 (가용성 증거, 두 재생 모드) | **수행** |
| W2 | 동결 V8/PB 무변경 adapter + 기준선 동일성(T49) | **수행** |
| W3 | 성숙 OOF 평가·proper score·공동 블록 재표집·Holm | **수행** |
| W4 | 정합성·RV역학·목적정렬 감사 (감사만 — 튜닝 없음) | **수행** |
| W5 | 이산시간 hazard | **scaffold+합성 테스트만** (실측은 V14-D11 BLOCKED) |
| W6 | 새 정보 블록 (옵션·일중) | **인터페이스+fixture까지** (실자료 미보유 BLOCKED) |
| W7 | 등록 실험 실행 | **BLOCKED 기록** (계약 draft→registered 미충족) |
| W8 | 운영 연결 | **BLOCKED 기록** (운영 승인 없음) |

### 2.3 설계서의 합격 규율 (이번 작업이 따른 것)

- 미실행 테스트를 PASS로 표기하지 않는다 (§19.1·§19.3, §20.2 금지 조항).
- 수치 동일성 검증에서 **허용오차를 사후에 넓히지 않는다** — 불일치는 불일치로 기록하고 크기를 병기 (§19.2).
- 코드 테스트 PASS와 성능 evidence PASS는 **다른 판정**이다 (§19.2).
- 실험 결과는 세 축으로 분리: 정합성 개선 / 보정 개선 / 증분 예측력 — 하나로 합산 금지 (§3.3).

---

## 3. 실행 결과 개요 (한 눈에)

| 항목 | 결과 |
|---|---|
| 신규 코드 | `src/ai_fc/mts_research/` 25개 Python 파일 (코어 14 + adapters 3 + audits 4 + cli 1 + `__init__` 3) |
| 신규 테스트 | `src/tests/test_mts_research_*.py` 16파일 + 공유 fixture 1 — **127 passed / 0 failed** |
| 전체 회귀 | **3,632 passed / 1 failed / 20 skipped** (24분 46초). 유일 실패는 본 브랜치와 무관한 Windows socket flake (§8.2) |
| 기준선 동일성 (T49) | **PASS** — PB 라이브 32/33행 + 해소 123/123행, V8 tier-1 예측 9/9 + 해소 19/19 + 봉인 + 포인터 (§5) |
| V8 tier-2 전체 재계산 | 1회 감독 실행 (5,456초): h21/h63 분포 **bit 동일**, h1/h5 max\|Δ\| ≤ 2.0e-16 — 규율대로 strict MISMATCH로 기록 (§5.4) |
| 감사 확인 사실 | 5건 — RV 양성의 기계적 확정 85/70/55%, VARX 간접 경로, grid-종속 라벨, 달러 splice 정상, captured_forward 백필의 역사 증거 부재 (§6) |
| 신규 예측력 주장 | **0건 — 의도된 결과** (실측 실험은 전부 승인 게이트 뒤) |
| 보호 준수 | 동결 파일 변경 0 · 예산 소모 0 · 홀드아웃/봉인 bytes 읽기 0 (§8) |
| 반입 | PR #356 → main 머지 (2026-10-27), 머지 후 CI(verify·pages) 초록 |

**이 작업이 주장하는 것**: "동결 모델의 기록이 코드에서 재현되고, 앞으로의 어떤 후보도 공정하게
잴 수 있는 기반이 생겼으며, 기존 성적의 해석을 교정할 사실 4건을 확인했다."
**주장하지 않는 것**: 예측력이 올랐다, 새 모델이 좋다, 기존 성적이 틀렸다.

---

## 4. 아키텍처: mts_research 연구 계층 상세

### 4.0 설계 원칙

1. **동결 보존**: 기존 모델 파일은 한 줄도 건드리지 않는다. 호출은 무수정 import만
   (private 심볼 import는 V13이 V8 내부를 import하는 저장소 전례를 따름 — 해시 봉인으로 결합 수용).
2. **fail-closed**: 모든 계약 위반은 조용한 보정이 아니라 예외(`Mts*Error`)로 즉시 실패하고,
   거부도 감사 원장에 남긴다.
3. **namespace 격리**: 코드 `src/ai_fc/mts_research/`, 데이터 `data/mts_research/`,
   보고서 `docs/research/mts_upgrade/`, 테스트 `test_mts_research_*` — 전부 기존 보호
   목록·glob 밖의 신규 이름공간.
4. **증거 우선**: 시간·가용성 주장은 저장된 증거 필드로만. 증거 없는 값은 승격하지 않고 null 유지.

### 4.1 records.py — 타입 계약 (설계서 §17.3)

- 영속 레코드는 전부 pydantic v2 `BaseModel(frozen=True, extra="forbid")` — 필수 필드 누락·잉여
  필드·타입 오류를 생성 시점에 거부.
- 모든 datetime은 **tz-aware UTC 강제** (naive 거부, `require_utc`).
- `ForecastArtifact`(발행물)/`ForecastDraft`(발행 전) 상태 규칙: `ISSUED`면
  payload_ref·payload_hash·state_id 필수(issued_at은 상태와 무관한 공통 필수 필드),
  `HOLD`/`NOT_ELIGIBLE`면 payload **금지** — "보류를 확률 0으로 저장"하는 가짜 0 경로를 타입
  수준에서 차단 (T18과 짝).
- 시간 순서 계약 `fit_cutoff ≤ information_cutoff ≤ issued_at`은 두 모듈이 나눠 강제한다:
  records.py가 `issued_at ≥ information_cutoff_at`을, contracts.py의 `validate_fitted_state`가
  `fit_cutoff ≤ information_cutoff`(T08)를 거부.
- 논리 해시는 `model_dump(mode="json")` dict를 **동결 모듈의 `canonical_hash`로 무수정 재사용**
  (V13 전례) — 바이트 해시(`sha256_file`)와 논리 해시를 혼용하지 않는다.

### 4.2 contracts.py — 실행 설정과 접근 가드 (§18)

- `ResearchContract`: 설계서 §18 draft YAML 미러. `validate_for(action)`이
  state(draft/registered)·필수 null·audit_only 조합으로 **run을 거부**하고 부족 항목을 구체적으로
  보고 (T55). 합성 테스트·감사는 draft에서도 허용.
- 상속 계약 검사: V8/V13/V14/daily6m 계약 YAML을 read-only 로드해 충돌을 검출 — 실제 검출
  항목은 V8 model_id·동결 status 불일치, V13 챔피언 셀 불일치, v14/daily6m 계약 파일 부재,
  금지 조항 9종(auto_promote·production_publish·learned_ensemble·foundation_model·conformal·
  sequential_evidence 등) 누락. "마지막 YAML이 조용히 덮어쓰는" 사고 방지.
- `read_scope_guard`: 설계서의 read-scope 영수증 개념을 저장소의 실제 승인 모델
  (`approvals.jsonl` 리터럴 영수증 + 계약 파생 보호 창)으로 구현. 보호 창(V8 홀드아웃
  2015–2018, 봉인 2019+ 등 — **계약에서 파생, 하드코딩 아님**)에 대한 fit/평가 요청은 영수증
  scope ⊇ 요청일 때만 통과. `protected_holdout_read_enabled: true` 플래그 단독으로는 불충분
  (§18.1). **거부도 `data/mts_research/ledgers/exposures.jsonl`에 노출 이벤트로 기록 후 예외**
  (T50) — 허용 시에도 기록한다: 한 번 본 구간의 "청정성"은 복원되지 않는다는 원칙의 집행.
- `register_baseline`: 기준선 등록 시 `expectation_threshold_indicator` 류(기대값에 임계
  indicator를 적용한 유사 확률)를 **등록 거부** (T21).
- `validate_fitted_state` / `validate_calibration_state`: 적합·보정 상태의 cutoff가 라벨
  가용 시점보다 미래 정보를 쓰지 못하게 차단 (T56).

### 4.3 artifacts.py — 원자 발행·불변 기록 (§16.1)

- `append_event`: hash-chain append-only 원장 (`previous_hash` + `content_hash` + fsync +
  idempotent 재시도) — 저장소 daily6m 패턴 이식.
- `write_immutable_json`: tmp 파일 + `os.replace` 원자 쓰기; 기존 파일과 동일 내용이면 no-op,
  다른 내용이면 거부(불변).
- 발행 상태기계: `start_attempt`(STARTED) → `fail_attempt`(FAILED+사유) / `commit_forecast`
  (COMMITTED). **issued_at은 commit에서만** 찍힌다 — commit 전 실패는 ISSUED 레코드를 남기지
  않는다 (T57·T60). 비정상 종료는 `recover`가 비종결 attempt를 recovery 이벤트로 닫는다 (T51).
- `update_latest_pointer`: CAS(compare-and-swap) — 엄격히 더 새로운 (origin, issued_at)만 교체,
  과거로의 롤백 차단 (T52).
- `logical_forecast_key` vs `artifact_id` 분리: 같은 논리 예측의 재구성·재시도가 **독립 표본
  수를 늘리지 못한다** (T47·T58) — 재구성 artifact는 별도 ID + 원본 참조를 갖는다.

### 4.4 sessions.py — 거래 세션 달력

- `exchange_calendars` XNAS를 **유일한 세션 계산 엔진**으로 (DST 전환·조기폐장·세션 시각 — T10;
  calendar_hash 기록은 daily6m 전례). 테스트 오라클은 하드코딩: 2026-03 DST 전환 주,
  2025-07-03 조기폐장(17:00 UTC 마감), 2025-07-04 금요일 휴장.
- legacy 달력 2계보(V8의 커스텀 `nyse_holidays.yaml` 규칙, V13의 관측일 교집합 grid)는
  `CalendarRef`(calendar_id + hash)로 **표현만** 하고 재계산하지 않는다 — 동결 재현에서 달력
  대체가 생기지 않게.
- `information_cutoff_for`: 세션 종가 확정 후 15분 버퍼를 둔 16:15 ET settle 정책
  (`settle_1615et_v1` — 세션 close + 900초)의 UTC화 — 원점일의 정보 마감 시각.

### 4.5 availability.py — 가용성 증거 (§6.1~6.2)

기존 두 저장소(시장 아카이브 JSONL·ALFRED parquet)의 **read-only 정규화 투영**.

- `AvailabilityEvent` 필드 확장 규칙: legacy 행의 `source_published_at`/`provider_available_at`은
  **항상 null** — 증거가 없는 가용 시각을 만들어 내지 않는다(승격 금지를 코드로 강제).
  `first_seen_at` ← `vintage_start`(시장)/`retrieved_at`(ALFRED),
  `availability_upper_bound` ← `available_at` (ALFRED는 ≈23:59:59 ET 보수 상계로 이미 저장됨).
- **두 재생 모드** (§6.2 — 이 계층의 핵심 이분법):
  - `operational_replay`: "그때 우리 시스템이 실제로 갖고 있던 것" —
    `max(first_seen_at, recorded_at) ≤ cutoff` (T04·T05).
  - `historical_information_set_reconstruction`: "그때 세상이 알 수 있던 것" —
    `availability_upper_bound ≤ cutoff` (T03·T12). 백필(captured_forward) 행은
    available_at=수집 시각이라 **과거 cutoff에 보이지 않는다** — 역사 증거가 없으면 역사
    재구성에 못 들어간다.
- `LedgerCheckpoint`: 원장 접두(prefix) SHA-256으로 재생 시점의 원장 상태를 고정 — checkpoint
  밖(이후 append된) 행을 재생에서 제외 (T07).
- 등급(data_grade) 어휘: `native_pit`(원천 공개 시각 증거 보유) / `captured_forward`(우리 수집
  시각만 증거 — NASDAQCOM·VIX 백필 전체) / `reconstructed_market_archive`(사후 재구성 1판 —
  DGS2·DGS10만 post-close 보수 상계 보유). `recorded_at`은 행이 우리 원장에 append된 시각 —
  수집이 가용보다 늦는 운영 지연은 operational replay에서 그대로(보수적으로) 반영된다.

### 4.6 snapshots.py — 입력/결과 스냅숏 (§6.5~6.7)

- `SnapshotManifest`: 코드 해시·정책 해시·환경 lock 해시·원장 checkpoint·쿼리 좌표를 전부 담고,
  `snapshot_id = "mts-snap-" + canonical_hash(body)[:24]` (body = manifest에서 snapshot_id·
  series_heads를 제외한 전 필드) — transform 코드/가용성 정책/환경 lock이 바뀌면 캐시 키가
  바뀐다 (T09).
- 기간별 최신 가용판 해석(`resolve_latest_visible_revision_per_period`)은 **전체 revision 이력
  보존** 위에서 결정적 tie-break로 뽑는다 (T06) — 이력 덮어쓰기 없음.
- `kind: input / outcome` 타입 분리 + `assert_input_snapshot`: outcome(라벨용) 스냅숏이 특징
  경로로 유입되는 것을 타입으로 거부 (T14).

### 4.7 targets.py — 사건 표적 계약 (§4.3~4.5)

- `EventTargetSpec`: 사건 좌표 전부 명시 — 관측 필드, 임계값, **경계 연산자 `>=`/`>` 보존**
  (T19 equality 분기), 지평(세션 수), within-horizon(기간 내 1회) vs at-horizon(시점) 구분,
  include_origin=False.
- 결측 세션 → **UNRESOLVED** (0으로 채우지 않는다, T17). V13 legacy의 부분결측=0 관행과 다른
  정책임을 문서화 — adapter는 V13 정의로 재현하고, 신규 표적만 mts 정책을 쓴다 (V13 불변).
- `EligibilityRule` (V14 평온 조건: VIX<20 strict, RV21≤θ): NOT_ELIGIBLE 원점에 **확률 0 발행을
  차단** (T18) — "자격 없음"과 "사건 확률 0"은 다른 진술.
- `rv21_annualized`: **실제 V13 정의 그대로** — `std(r[t−20..t], ddof=1) × √252` (평균 제거 있음).
  설계서 원문의 무평균 수식이 아니라 실코드 정의를 채택했고, V13 함수와의 수치 일치를 테스트로
  고정.
- `decompose_rv21(returns, t, k)`: rv21[t+k]를 (알려진 합 S1, 알려진 제곱합 S2, n_known) +
  (미래 성분)으로 **정확 분해** — 재결합이 원식과 1e-12 수준 일치 (T20). §6.1 rv_floor의 기초.

### 4.8 maturity.py — 라벨 성숙 상태기계 (§4.6, §12)

- `LabelEvent` append-only 상태기계: PENDING → MATURE / UNRESOLVED / RESTATED / INVALIDATED.
  상태 변화는 기존 행 수정이 아니라 **새 이벤트 append**.
- `matured_view`: **완전 성숙 코호트만** 집계에 들어간다. 조기 양성(지평 중간에 이미 사건 발생)은
  `early_event_observed_at` 메타로만 기록하고 성숙 전 집계에서 제외 (T16) — "이미 맞은 것만
  먼저 세는" 선택 편향 차단.
- `label_available_at`(원천에서 라벨이 알 수 있게 된 시각)과 `recorded_at`(우리 시스템이 기록한
  시각) 분리 (T59) — operational replay는 recorded_at 기준, checkpoint 밖 제외.
- anchor revision(원점 기준가가 된 판)과 terminal revision(라벨 판정에 쓴 판)을 각각 보존 (T11).
- `assert_prospective_issue` (T15): `issued_at ≥ first_target_available_at`(첫 대상 관측이
  가용해진 시각)이면 prospective 등록을 **거부** — cutoff만 과거로 기입한 backdated 예측이
  "그때 냈던 예측"으로 둔갑하는 경로 차단. (발행 시각 < 정보 마감의 거부는 records.py의 별도
  검사다 — §4.1.)

### 4.9 distributions.py — 확률 객체 (§9.1)

- `WeightedEmpiricalDistribution`: (지지점, 가중치)의 명시적 분포 객체 — cdf/cdf_left(점질량
  경계의 일반화 역함수, T29)/quantile/p_above 제공.
- `QuantileGridForecast`: 분위수 격자만 아는 예측 — **cdf·CRPS capability를 거부**한다 (T31):
  격자에서 CRPS를 "대충" 계산해 주지 않고, 지지점 분포로의 명시적 변환을 요구.
- `mixture_cdf`(CDF 혼합)와 `quantile_average`(분위수 평균, Vincentization)는 **서로 다른
  연산**임을 타입과 반례 테스트로 고정 (T32) — 앙상블 결합에서 흔한 혼동 차단.
- PIT identity 검증: V8의 동결 `recalibration_levels`가 균일 PIT 이력에서 항등 보정이 되는지
  anchor 테스트 (T30).

### 4.10 scores.py — 채점기 (부록 A 전체 구현)

의존성 추가 금지 제약(arch·properscoring 부재)으로 전부 자체 구현. 전 함수 fail-closed.

- **Brier / log loss** (A.1): fraction 검증, log loss의 clip은 epsilon·적용 위치 명시 + 원확률
  보존. `brier_skill_denominator_guard`: 기준선 Brier 합 0이면 skill **NOT_IDENTIFIABLE**.
- **CRPS — weighted empirical, O(M log M)** (A.2): 정렬 + 누적합으로
  `CRPS = Σ wᵢ|xᵢ−y| − ΣΣᵢ<ⱼ wᵢwⱼ(xⱼ−xᵢ)` 를 계산. 핵심 코드:

  ```python
  order = np.argsort(values, kind="stable")
  x = values[order]
  ws = w[order]
  term1 = float(np.sum(ws * np.abs(x - y)))
  cumulative_w = np.concatenate([[0.0], np.cumsum(ws)[:-1]])   # W_{m-1}
  cumulative_s = np.concatenate([[0.0], np.cumsum(ws * x)[:-1]])  # S_{m-1}
  pair_half = float(np.sum(ws * (x * cumulative_w - cumulative_s)))
  return term1 - pair_half
  ```

  (발췌 앞에는 weight 검증 — 비음수·유한·모양 일치·합 1(1e-9 허용) — 이 선행한다; 발췌는
  균일 들여쓰기 제거 외 원본 자구 그대로.)
  오라클 테스트: 단일점 환원 CRPS=|x−y|, **동결 V8 `sample_crps`와의 교차 일치(1e-12)**,
  O(M²) 전수 대조, 평행이동·스케일 공변성. 주의 선언: 이는 "발행된 경험분포 자체"의 점수이며
  잠재 연속분포 점수의 무편향 추정이라는 주장은 하지 않는다.
- **fair-CRPS 보정 가드** (T35): iid·비가중·비결정 grid 조건이 전부 확인될 때만 허용 —
  의존 표본/가중 표본/deterministic quantile grid에는 자동 적용 거부.
- **WIS** (A.3): 요구 격자 = {0.5} ∪ {α/2, 1−α/2 ∀α}. 입력 격자가 **정확히** 일치하지 않으면
  `GridMismatch` — 다른 격자의 WIS를 같은 score ID로 비교 금지 (T34).
  `WIS = [0.5·|y−median| + Σ (α/2)·IS_α] / (K + 0.5)`,
  `IS_α(l,u;y) = (u−l) + (2/α)(l−y)₊ + (2/α)(y−u)₊`.
- **QLIKE** (A.4): `log σ̂² + RV/σ̂²` (분산 예측 양수 강제). 실현 proxy의 좌표(예: RV21²)는
  평가 계약에서 고정할 미결 좌표 — 현재 draft 미지정 (§12 Q5).
- **Energy score** (A.5): Euclidean 고정, `E‖X−y‖ − ½E‖X−X′‖` 가중 경험판, chunk 처리.
  스칼라 입력에서 ES≡CRPS 테스트.
- **Variogram score** (A.5): `Σ aᵢⱼ(|yᵢ−yⱼ|^p − E|Xᵢ−Xⱼ|^p)²`, p>0, aᵢⱼ≥0 명시.
- **coverage 타입 분리** (T37): pointwise(날짜별 적중률)와 simultaneous(경로 전체 동시 적중)를
  별개 타입으로 — `assert_simultaneous`가 pointwise의 승격 표기를 차단.

### 4.11 resampling.py — 공동 블록 재표집·검정 (§13)

- `LossPanel`: **원래 origin-달력 grid 전체를 보존**하는 (원점 × 모델 × 셀) 손실 텐서 +
  eligibility mask + missing_reason(OK/NOT_ELIGIBLE/UNRESOLVED/CANDIDATE_FAILURE/HOLD/
  NOT_ISSUED). eligible 날짜만 압축해 인접 행을 시간 블록처럼 재표집하는 오류를 구조로 차단
  (T41). NaN 손실 ↔ 결측 사유의 상호 정합을 생성자에서 강제.
- `joint_block_resample`: 기하 길이 circular stationary block(블록 생성 규약은 저장소 V13
  `block_boot_ci`와 동일) — **replicate당 단일 인덱스 벡터**를 생성해 모든 모델·셀 슬라이스와
  mask에 공동 적용 (T42). `ReplicateSet.panel_hash`가 다른 패널에의 재사용을 차단.
- `eligible_paired_mean`: 같은 원점·같은 셀에서 후보·기준선 **둘 다 유효한** paired 손실차
  평균. 후보 실패 원점을 삭제한 "성공 교집합"이 아니라, 실패는 missing_reason으로 **센다**.
- `centered_paired_bootstrap_test` (§13.5.1): H0: E[d] ≥ −δ vs H1: E[d] < −δ (손실 낮을수록
  좋음, δ는 손실 **단위**의 최소 실질 개선). 통계량:

  ```
  observed = mean(d) + δ
  null_b   = mean(d[idx_b]) − mean(d)        # 중심화된 부트스트랩 귀무 분포
  p_raw    = (1 + #{null_b ≤ observed}) / (B_eff + 1)   # 좌측꼬리
  ```

  퇴화 replicate(유효 paired 0)는 사전 고정 정책(count_and_exclude)으로 집계 제외·카운트하고
  **다시 뽑지 않는다** (T43). paired 관측 부족 → UNTESTABLE, 전 replicate 퇴화 →
  EVIDENCE_INSUFFICIENT. 문서화된 한계: 이것은 bootstrap 근사의 Monte Carlo 추정이지 유한표본
  보장이 아니다.
- `holm_adjust` (T44): step-down. **검정불능 비교는 p_for_adjustment=1로 family에 남긴다** —
  NaN 자동 제거로 family 크기를 줄여 다중성 보호를 약화시키지 않는다. adjusted p는 running max
  단조화.
- `skill_ratio`: 분모 불안정 시 NOT_IDENTIFIABLE 반환 (숫자 대신 상태).
- 등록 좌표의 현재 상태: draft 계약(`mts_research_v1.draft.yaml`)에서 `bootstrap_replicates`·
  `mean_block_length_in_origin_grid_rows`·`minimum_practical_effect`(δ)·seed manifest는 **null**
  — W7 등록 시 채워야 run이 가능하다 (T55 경로). `familywise_alpha = 0.05`는 고정.
- 저장소에 이미 있는 stationary bootstrap 구현들(V8 backtest `_stationary_bootstrap_mean_ci`,
  V13 scoring `block_boot_ci`·`paired_brier_ci` 등 — §11-6의 "5벌")은 단일 계열 CI용으로,
  원 grid+mask **공동** 재표집은 어느 것도 지원하지 않아 신규 작성했다 (블록 생성 규약은 V13과
  동일, 합성 패리티 테스트로 고정).

### 4.12 prequential.py — 성숙 OOF 평가 (§12)

- `purge_ok` 4조건 술어 (§12.3): ① train_origin < val_origin, ② 학습 라벨의 label_end_session
  < 평가 대상 시작, ③ 학습 라벨의 label_available_at ≤ 평가 cutoff, ④ 등록된 gap 규칙 충족 —
  고정 상수 purge가 아니라 표적의 **실제 label interval**에서 유도.
- `mature_oof_view`: 성숙 코호트만의 OOF 뷰 — 미성숙 라벨 유입 거부 (T39: 재생성 OOF가 기존
  뷰를 덮어쓰는 것 거부, reconstruction ID 요구; T56 보정 상태와 짝).
- `rescore_resolved`: **기존 해소 원장을 read-only 재채점**해
  `data/mts_research/derived/origin_losses.parquet`를 생성 — 신규 예측 없이 E게이트 파이프라인용
  실코호트 확보. 커밋본 284행 = V13 123행×2모델(246) + V8 19행×2(38)로 **생성 시점(2026-10-26)
  기준** — V8 해소 원장은 그 뒤에도 자라 2026-10-27 현재 23행(재실행 시 292행이 된다). 채점이
  저장 점수와 일치하는지 교차 검증 포함.

### 4.13 gates.py — 증거 게이트 (§15)

- `GateResult` (E0~E8): 각 게이트가 reason code·evidence 참조·입력/계약 해시를 지닌 구조체.
- `ResultAxes`: 정합성 개선 / 보정 개선 / 증분 예측력 / 운영 신뢰성의 **4축 비합산** — 단일
  합산 점수 API 자체가 없다 (T54).
- `NullDiagnostics`: G4류 "귀무 통과율"(passes/B)과 Monte Carlo permutation p-value
  ((1+c)/(B+1))를 **별개 타입**으로 (T45).
- `sample_sufficiency_gate`: "추정이 성공했다" ≠ "증거가 충분하다" (T46) — n·사건 수 하한을
  게이트로 분리.

### 4.14 hazard.py — 이산시간 hazard scaffold (§9.4~9.6, 합성 전용)

모델: `logit(λ_{t,k}) = a_{b(k)} + β·z_t` — 시간 bin 절편(기본 [1..5],[6..21],[22..63]) +
원점 특징 공유 slope.

- **데이터 계약이 모델보다 먼저**: `build_person_periods`는
  ① 사건 후 행 금지 (T22), ② `event_k > observed_end_k` 거부 — "보지 못한 사건" 입력 불가,
  잠재 생존시간 T를 아는 것으로 가정하지 않음 (T23), ③ z는 (n_origins, p) **원점 특징만** —
  시간축을 가진(미래) covariate를 모양 수준에서 거부 (T24), ④ 데이터 누락을 무사건 생존으로
  해석하지 않음(observed_end_k = 연속 완전 관측의 끝).
- 적합: **자체 penalized Newton-IRLS** — bin 절편은 무벌점, slope 블록에만 ridge
  (`penalty[n_bins:] = ridge`). sklearn이 이 벌점 구조를 표현하지 못해 자체 구현 (저장소 전례:
  V13 `logit_fit`). 수렴 실패 시 scipy L-BFGS-B fallback을 쓰되 `fallback_used` 플래그로 기록
  — 조용한 대체 없음. scaler는 **원점당 1회**(person-period 반복 가중 왜곡 방지) 학습 자료에서만.
- 누적 사건 확률: `p(h) = 1 − Π_{k≤h}(1−λ_k)` 를 `log-survival = Σ log1p(−λ)` →
  `p = −expm1(log-survival)` 경로로 계산 — **p(5) ≤ p(21) ≤ p(63) 지평 단조가 기계적으로 보장**
  (T25: 상수 λ 폐형 오라클 1e-9, T26).
- `SurfaceKey` (origin, cutoff, eligibility 해시, 관측 필드, within-horizon): 좌표가 다른 확률
  표면 간 제약 투영을 거부 (T27) — 예: V13 무조건부 표면과 V14 평온 조건부 표면의 결합 금지.
- `no_iid_ci=True` 고정: 중첩 원점의 person-period 합은 composite likelihood — naive iid
  Hessian CI 산출 경로 자체를 두지 않음. 계수 대역은 등록된 block 절차로만 (W7 이후).
- clip 상수 3종 분리: 학습 수치 안정(1e-10) / log score(1e-6) / 표시 반올림 — 하나의 epsilon으로
  뭉개지 않음 (§9.5).
- **실자료 경로 없음**: 이 모듈은 어떤 실자료도 읽지 않는다. 실측 적합은 V14-D11 + W7 등록 후.

### 4.15 adapters/ — 동결 모델 재현 (W2)

**호출 금지 목록을 먼저 정의**: 예산을 소모하는 `dev_backtest_*`·`sealed_backtest_*`, 원장에
append하는 `shadow_forecast/resolve_*`, 공개 경로 `publish_latest_*`, cache를 다시 짓는
`build_origin_dfm_cache` — adapter는 순수 계산 함수만 쓴다.

- `adapters/pb.py` (V13): 저장소가 이미 쓰는 1e-9 재계산 검증(`verify_timeseries_v13_vol`)을
  **라이브 전 행(33) + 해소 전 행(123)으로 일반화**. 각 행의 knowledge_cutoff로 아카이브를
  절단해 `build_panel` → 동결 계수 로지스틱 → 저장 확률과 대조. late_capture(원점 백필) 행은
  기록된 `backfill_cutoff_used`로 동일 조건 재구성. 구 sha 시대 1행은 hash 검증만(재계산 전제
  불충족을 PASS로 둔갑시키지 않음 — `hash_only_old_sha`).
- `adapters/v8.py` 2단:
  - **tier-1 (저렴, 전 행)**: 원장 hash-chain 검증 + content_hash 재검 + forecast_id 유도
    재현(`"tsv8-shadow-" + canonical_hash({'model','config','origin'})[:24]`) + **해소 행 전체
    재계산**(저장된 quantile_grid + 아카이브 수익률로 model_crps·baseline_crps·coverage bit
    재현 — 모델 재실행 없이) + telescoping 대조(`actual_log_return`과 아카이브
    `log(P_end/P_origin)`의 일치) + sealed 행 + latest pointer 투영(`grid[int(q*200)]`) +
    `model_code_hash`/계약 해시 대조 + 전후 보호 해시 무변경 확인.
  - **tier-2 (고가, 1행)**: 행의 knowledge_cutoff에서 bundle을 재구성해
    `walk_forward_dev_backtest_v8`(path_count=20000, origin별 deterministic seed)로 **전체
    모델을 재계산** — 200레벨 grid·ensemble weights·PIT 상태·p_up 전 필드 bit 대조.
    전제 드리프트는 REPLAY_PRECONDITION_DRIFT, 환경 불일치는 ENVIRONMENT_MISMATCH로
    fail-closed 분류 — 모델 불일치로 과잉 주장하지 않는다.
- `adapters/report.py`: 위 결과를 `baseline_identity.json`으로 집계 (environment lock 해시 포함).

### 4.16 audits/ — 감사 도구 4종 (W4; 결과는 §6)

- `rv_mechanics.py`: rv_floor 닫힌형 + 기계적 확정 판정 + window-mechanics 확률 기준선.
  **prereg 선기록 규율**: 실자료 계산 전에 생성기·seed·원점 표본 좌표를
  `experiments/rv_mechanics/prereg.json`에 기록하고, 이미 존재하면 좌표 불일치 시 거부 —
  결과를 보고 좌표를 바꾸는 경로 차단. 기대값 변종은 `not_a_probability` 라벨로만 산출 (T21).
- `objective_align.py`: 동결 코드의 파라미터→최종분포 영향 경로 정적 추적
  (ACTIVE/INDIRECT_VIA_LAMBDA/BYPASSED 어휘) + 합성·제한 grid 섭동 하니스 (V8 예산 비소모).
- `coherence.py`: V8 grid 단조·p_up=mean(grid>0) 동일 artifact 재현·pointer 투영·V13 33행
  지평/임계 단조성 — **보고만** (사후 "정합화 공개" 경로 없음, V14 표면과 비결합).
- `time_audit.py`: 달러지수 splice 중첩 구간 분석, captured_forward 증거 구조, 운영기 수집
  지연(최근 120거래일 창 — 백필 오염 제거), 정정 분포.

### 4.17 cli.py — 자체 CLI

`python -m ai_fc.mts_research.cli <verb>` — 공유 `cli.py` 무수정(= V14 문자열 금지·127개 커맨드
앱과의 충돌 회피). verbs: `inventory` / `validate-contract` / `audit-time` / `replay-baseline` /
`plan-experiment` / `run-experiment --dry-run`(코호트·권한·예산 검증만 — fit 0·예산 0) /
`evaluate`. exit code: 0 정상 / 2 검증 차단 / 3 scope 거부 / 4 전제 부족. 쓰기 가능 경로는
`data/mts_research/` + `docs/research/mts_upgrade/` 로 제한. 오프라인 동작 테스트 (T53).

### 4.18 데이터 영역·원장 등록

```
data/mts_research/
  contracts/mts_research_v1.draft.yaml   # §18 draft — state: draft (성능 실험은 이 상태로 시작 불가)
  source_specs/                          # W6 자리 — 현재 빈 디렉터리 (SourceSpec 기본 enabled=false)
  ledgers/exposures.jsonl                # 보호 창 접근 시도 기록 (허용·거부 모두)
  derived/{origin_losses.parquet, coherence_audit.json, data_time_audit.json,
           objective_align_audit.json, v8_tier2_replay.json}
  experiments/rv_mechanics/{prereg.json, results.json}
```

신규 원장 6종을 `data/contracts/ledger_registry.yaml`에 **추가-전용** 등록
(`expected_state: planned`) — 거버넌스 순회(`audit-ledgers --check`)에 포함, 기존 등록 무변경.

---

## 5. 기준선 동일성(identity) 검증 — 방법과 결과 (T49)

### 5.1 왜 identity가 첫 관문인가

연구 계층의 모든 후속 평가는 "동결 모델의 기록이 코드에서 재현된다"는 전제 위에 선다. 재현이
안 되면 ① 기록이 오염됐거나 ② 코드가 바뀌었거나 ③ 우리의 재현 절차가 틀린 것 — 어느 쪽이든
증분 비교가 무의미해진다. 그래서 W2의 수용 기준은 "공정한 비교 이전에 **같은 것**을 낼 수 있는가"다.

### 5.2 PB (V13 챔피언) — 전행 재현 **PASS**

| 원장 | 행수 | 결과 |
|---|---|---|
| `vol_live.jsonl` (라이브 발행) | 33 | **32 PASS** (1e-9 허용오차 재계산) + 1행은 구 sha 시대라 hash 검증만 — 재계산 전제 불충족을 구분 기록 |
| `vol_live_resolutions.jsonl` (해소/채점) | 123 | **123 PASS** |

방법: 각 행의 knowledge_cutoff(백필 행은 기록된 backfill_cutoff_used)로 시장 아카이브를 절단,
동결 계수(sha256 핀)로 패널 구축→로지스틱 확률 재계산→저장값 대조. PB의 로지스틱은 셀 관측값
단일 회귀변수다 (§1.2). climatology(기후 base rate)는 계약의 **설계창(2007-2014) 고정값**이며,
재현 기준은 실사용 artifact 값 — resolve 경로가 쓰는 값과 문서 값 사이에 저장소가 이미 문서화해
둔 전사 불일치 1건이 있어(adapters/pb.py 주석이 참조) 이는 PASS의 명시적 예외 조항이다. 구 sha
1행은 V13 재동결로 계수 artifact가 교체되기 **전** 발행분 — 현재 계수로의 재계산 전제가 성립하지
않아 hash 검증만 (전제 불충족을 PASS로 둔갑시키지 않음).

### 5.3 V8 tier-1 — 전행 재현 **PASS**

- 예측(shadow) 9/9행: hash-chain + content_hash + forecast_id 유도 재현.
- 해소 19/19행: 저장 grid + 아카이브 실현 수익률로 CRPS·coverage **bit 재현**. 이 중 2행은
  `PASS_WITH_GRID_SKIP`: telescoping 대조(저장 `actual_log_return` vs 아카이브
  `log(P_end/P_origin)`)가 하루치 수익만큼 어긋났고(어긋남의 크기는 실행 로그에서 관측 —
  [저장소 미기록], 커밋 산출물에는 사유만 남음), 원인은 **bundle grid가 국채 휴장 주식 거래일
  (2026-10-12 — 주식 개장·국채 휴장; 원장 기록은 날짜·시장 상태까지이고 'Columbus Day' 명칭은
  달력 추론)을 세션 grid에서 제외**해 h세션 라벨이 그 날 수익을 누락하는 동결 코드의 구조적
  성질. 탈락일 차감 항등식
  `adjusted = telescoped − Σ_d log(P_d/P_{d−1})` (d = grid가 떨어뜨린 주식 거래일)로 두 행이
  **정확히** 재현됨 → "grid-종속 라벨" 발견으로 분류 (수정이 아니라 공시 — §6.3).
- sealed 평가 행 1건 PASS, latest pointer는 fail-closed hold 상태(HOLD_POINTER —
  `shadow_operational_hold`: shadow 운영 보류로 투영할 공개 숫자가 없는 상태) 확인,
  `model_code_hash`·계약 해시 일치, 전후 보호 해시 무변경.

### 5.4 V8 tier-2 — 전체 모델 재계산 1회: 판정 규율의 사례

원점 2026-10-16 행 1건을 knowledge_cutoff에서 bundle 재구성 → 동결 walk-forward 전체 재실행
(5,456초; 재실행 내부의 PIT 성숙 원점 코호트 1,020개 재계산 — §13.C의 '재계산 성숙 원점'이
이 값이다). 결과:

- h21/h63 (FHS 경로): 200레벨 quantile_grid **전부 bit 동일**. ensemble_weights·blend·PIT
  상태·p_up 등 전 필드 동일.
- h1/h5 (VARX 경로 시뮬): `max|Δ| = 2.4e-17 (h1), 2.0e-16 (h5)` — 배정밀도 기계 엡실론
  (≈2.2e-16)의 1~2 ulp.
- **판정: strict MISMATCH로 기록** — §19.2 "허용오차를 사후에 넓히지 않는다"를 그대로 적용하되,
  크기가 기계 엡실론 수준이고 원 행은 주간 예약 잡 산출(실행 환경 비동일 가능, 행에 BLAS/CPU
  기록 없음)임을 병기. "환경 메타데이터를 행에 기록하라"는 후속 과제가 여기서 나온다.

### 5.5 환경 고정

`baseline_identity.json`에 environment_lock_hash(의존성 버전 지문) 기록. 실측 스택: Python
3.12.10, numpy 2.4.3, scipy 1.17.1, pandas 2.3.3, statsmodels 0.14.6(핀), pyarrow 24.0.0,
scikit-learn 1.8.0, exchange_calendars 4.13.2, pydantic 2.13.4. arch·properscoring·hypothesis
없음(자체 구현 사유).

---

## 6. 감사 결과 (W4) — 확인된 사실과 수치

### 6.1 RV_MECHANICS: RV 양성의 상당수는 원점에서 기계적으로 확정된다 — **확인**

**rv_floor 닫힌형 유도** (검산 요청 — §12 Q4): rv21[t+k]의 분산은
`(S2 + F2 − (S1+F1)²/21) / 20` (S1,S2 = 원점에 이미 알려진 21−k개 수익의 합·제곱합,
F1,F2 = 미래 k개 수익의 합·제곱합). 제약 F2 ≥ F1²/k (Cauchy-Schwarz, 미래 수익이 모두 같을 때
등호)에서 F2 = F1²/k로 두고 F1에 대해 최소화하면:

```
F1* = S1 · k / (21 − k)          (k < 21)
variance_min = (S2 + F1*²/k − (S1+F1*)²/21) / 20
rv_floor = sqrt(variance_min × 252)
```

k ≥ 21이면 알려진 성분이 없어 하한 0. 원점에서 `max_k rv_floor(k) > θ`이면 그 원점의
within-horizon 양성 라벨은 **미래와 무관하게 이미 확정**이다.

**실측** (설계창 2007-2014, stride 21 → 원점 96개, θ=0.1694, prereg 선기록 후 실행):

| 지평 | 양성 | 기계적 확정 | 비율 | base rate | WM-iid 평균 p | WM-ewma 평균 p |
|---|---|---|---|---|---|---|
| h5 | 55 | 47 | **85%** | 0.5729 | 0.6805 | 0.5558 |
| h21 | 67 | 47 | **70%** | 0.6979 | 0.9472 | 0.6212 |
| h63 | 86 | 47 | **55%** | 0.8958 | 0.9987 | 0.7209 |

(WM = window-mechanics 확률 기준선: 등록된 단순 수익 생성기 2종 — iid 2520일 재표집 / EWMA
재척도 재표집(λ=0.94 EWMA 분산으로 역사 표본을 현재 변동성 수준에 스케일) — 으로 미래 경로를
만들고 **실제 rolling 추정식**을 굴려 기간 내 max rv21 > θ 비율. n_paths=400 → 원점당 MC
표준오차 ≤ √(p(1−p)/400) ≈ 0.025.)

**세 지평의 확정 수가 모두 47인 이유**: 하한의 최댓값은 알려진 수익이 많이 남은 **작은 k**에서
달성된다 (`mechanical_positive`는 k ≤ min(h,20)을 탐색). 이 창에서는 확정이 전부 k ≤ 5에서
일어나 h5 확정 집합(47)이 h21·h63에서 그대로 유지됐고, k ∈ (6..20)에서 새로 확정된 원점이
없었다. 비율이 지평에 따라 떨어지는 것(85→70→55%)은 분모(양성 수)가 커지기 때문이다.

**해석의 경계** (주장 범위를 정확히):
- 확인된 것: V13 RV 셀의 낮은 Brier/높은 BSS의 **큰 몫이 지속성+창 역학**이다 — "미래 충격을
  맞혔다"로 읽으면 과대해석.
- **θ-창 순환성 주의**: θ=0.1694는 같은 설계창(2007-2014)의 RV21 **중앙값**으로 사전등록된
  고정값이다 — 본 진단의 실측창이 θ를 뽑은 창과 동일하므로 base rate(0.57~0.90)와 확정 비율은
  그 창에 대해 in-sample 성격이다. 결론(해석 교정)의 구조는 θ가 외생이어도 성립하지만, 수치의
  다른 창 외삽은 하지 않는다.
- 주장하지 않는 것: PB 대비 WM의 증분(사전등록된 비교가 아님), V13 성적의 무효(성적 자체는
  유효 — 해석이 교정될 뿐), 사건 정의 변경(현행 RV21 정의 불변 — `forward_realized_variance`
  류 "알려진 성분 제거 표적"은 별도 연구 후보로만 기록).

### 6.2 OBJECTIVE_ALIGN: V8 튜닝 파라미터의 실제 영향 경로 — **부분 확인**

가설: "VARX가 1일 NASDAQ 제곱오차로 선택되는데 장기(h21/h63) CRPS가 목적 — 목적 불일치."

배경 스펙 (동결 V8의 장기 분포 생성): h21/h63 최종 분포는 **FHS** — 수익률 단변량과
ewma_lambda만의 함수(tilt=0) — 와 VARX 무관 historical_simulation의 0.75/0.25 blend다.
λ ∈ {0.94, 0.97}은 동결 선택 함수(`select_distribution_parameters_v2`)가 적합 잔차·이력
기준으로 고르는 이진 스위치.

정적 추적 (동결 코드 좌표) + 합성 섭동 하니스 (V8 예산 비소모·계약 무변경):

| 파라미터 | 대상 지평 | 판정 | 근거 |
|---|---|---|---|
| varx.lag / varx.alpha | h21/h63 최종 분포 | **INDIRECT_VIA_LAMBDA** | h21/h63은 FHS 대체 — FHS 시그니처에 VARX fit 자체가 없음(구조적). 영향은 λ 이진 스위치·PIT 이력 경유만. 제한 grid 2점에서 λ 선택이 실제로 갈림({lag1_smallA: 0.97, lag5_largeA: 0.94}) |
| varx.lag / varx.alpha | h1/h5·first_touch | **ACTIVE** | 경로 시뮬레이션이 VARX 적합을 직접 사용 |
| distribution.block_length | h21/h63 | **BYPASSED** | FHS는 block_length를 인자로 받지 않음 |
| distribution.ewma_lambda | h21/h63 | **ACTIVE** | λ 0.94↔0.97 스위치의 분위 최대 차이: h21 0.0412, h63 0.1542 |

함의: 목적 재정렬(ablation) 실험은 **영향 경로가 있는 파라미터(λ, h1/h5의 VARX)에만** 의미가
있다 — h21/h63에서 (lag,α)·block_length를 재튜닝하는 실험은 설계 자체가 낭비. 실험은 W7 등록
후에만.

### 6.3 Coherence: 표시 체인 정합 — **PASS** + 발견 2건

- V8 해소 전행(19) 재계산 일치: quantile_grid 단조 + `p_up == mean(grid > 0)` 가 **같은
  artifact에서** 유도됨을 재현. latest pointer는 fail-closed hold 상태 확인.
- **발견 (라벨 정밀도)**: V8 grid는 중점 레벨 (i+0.5)/200 — pointer 투영 `grid[int(q*200)]`의
  "p10"은 정확히는 0.1025-분위다. 수학적 모순이 아닌 라벨 정밀도 관찰, 동결 좌표라 수정 아닌
  공시.
- **발견 (grid-종속 라벨)**: §5.3의 2026-10-12 사례 — V8의 h세션 수익 라벨은 "달력 h일"이
  아니라 "bundle grid의 h행"이며, grid는 **모든 입력 계열의 교집합 세션**이라 국채 휴장
  주식 거래일이 빠진다. 동결 코드의 성질로 공시하고, 신규 표적 계약 설계의 입력으로만 사용.
- V13 라이브 표면 33행 전측정: 지평 단조성(h↑→p↑) 위반 **0**, 임계 단조성(p(VIX≥30) ≤
  p(VIX≥25)) 위반 **0**. 보고만 — 사후 정합화 공개 경로 없음, V14 조건부 표면과 비결합 (T27).

### 6.4 데이터·시간 감사: 달러지수 splice — **정상 확인** (가설 기각)

가설(설계서): DTWEXB→DTWEXBGS 이어붙임에서 인공 수익률 발생 가능.

실측:
- 동결 `features.py`는 **계열별 log-change를 먼저** 계산한 뒤 `combine_first`(BGS 우선)로
  연결 — 서로 다른 base level의 직결로 인공 return이 생길 경로가 구조적으로 없음 → **T13 PASS**.
- 두 계열 base 비 0.9079 — level을 직결했다면 −9.7% 인공 수익이 생겼을 자리였다.
- 실효 전환점은 **2006-01-02** (BGS backcast가 2006부터 우선; 원고가 말한 2019-01-02는 FRED
  계열 교체 시점으로, splice 경계가 아님). 겹침 3,513일의 return 일치도: |Δ| 중앙값 1.67e-04,
  p99 1.25e-03.
- **T12 PASS**: BGS 방법론 공개일(2019-02-04) 이전 관측일 행 3,287건 중 "당시 가용(native
  point-in-time)" 주장 0건 — backcast는 captured 등급으로만 존재.
- caveat: 운영 '현재' 패널의 pre-2019 달러 return은 신방법론 backcast다 — 동결 V8 평가는
  2026-08 아카이브 구축 후 실행이라 내적으로 일관하나, "그때 그 모델이 봤을 값"과는 다르다.
- 구조 사실: NASDAQCOM·VIX 백필 전체가 captured_forward(available_at=수집 시각) — 역사 재구성
  에서 pre-capture cutoff에 보이지 않는 것이 **정상 동작**이다. 정정(revision) 행은 현재 0.
- 운영기 수집 지연 (최근 120거래일, 이 아카이브의 수집 케이던스이지 원천 공개 지연이 아님):
  NASDAQCOM/DGS 계열 중앙값 ≈17일, VIX ≈20일, DTWEXBGS ≈22일 — 주간 refresh 묶음의 반영.

### 6.5 미확인으로 남긴 가설 (후속 감사 대상)

- DFM smoothed-state/전체창 scaling의 과거 OOF 유입 — 원점별 cache 구조상 차단 설계이나 미검증.
- 입력 공통 마지막 날짜로 인한 원점 지연(ASOF_AGE) 정량화.
- window-mechanics baseline의 PB 대비 증분 — 사전등록된 비교가 아니므로 **주장 보류**.

---

## 7. 수용 테스트 T01~T60 전체 매핑

suite: `cd src && python -m pytest tests/test_mts_research_*.py -q` → **127 passed / 0 failed**.
범례: IMPLEMENTED_PASS(구현·실행·통과) / IMPLEMENTED_PARTIAL(기반 통과, 일부 축 후속) /
MEASURED_PASS(실자료 read-only 감사로 실측 통과).
주의: 아래 한 줄 주제는 설계서 §19 원문 기준의 **요약 라벨**이다 — 원문 합격 기준 전문(각 T당
수 문장)은 이 팩에 동봉하지 않았으므로, 매핑의 충실성까지 검토하려면 설계서 §19 발췌가 추가로
필요하다 (요청 시 제공).

| T | 주제 | 상태 |
|---|---|---|
| T01 | 늦게 공개된 관측의 cutoff 제외 | IMPLEMENTED_PASS |
| T02 | cutoff 시점 최신 가시 revision 선택 | IMPLEMENTED_PASS |
| T03 | 날짜 정밀도의 장중 사용 차단 (보수 상계) | IMPLEMENTED_PASS |
| T04 | 백필의 operational vs historical 분리 | IMPLEMENTED_PASS |
| T05 | operational replay의 수신 경계 준수 | IMPLEMENTED_PASS |
| T06 | 기간별 revision 전체 이력 보존 | IMPLEMENTED_PASS |
| T07 | checkpoint 밖 행 재생 제외 (접두 sha) | IMPLEMENTED_PASS |
| T08 | fit_cutoff > information_cutoff 차단 | IMPLEMENTED_PASS |
| T09 | 코드/정책/lock 변경 → cache 키 변경 | IMPLEMENTED_PASS |
| T10 | 세션 달력 (DST·조기폐장·휴장) | IMPLEMENTED_PASS |
| T11 | anchor/terminal revision 분리 보존 | IMPLEMENTED_PASS |
| T12 | 공개일 전 native 가용 주장 금지 | **MEASURED_PASS** (실측 3,287행 중 0건) |
| T13 | splice 인공 수익 탐지 | **MEASURED_PASS** (return-먼저-연결 확인) |
| T14 | outcome snapshot의 특징 유입 거부 | IMPLEMENTED_PASS |
| T15 | backdated 발행 거부 | IMPLEMENTED_PASS |
| T16 | 조기 양성 메타만·성숙 전 집계 제외 | IMPLEMENTED_PASS |
| T17 | 결측 세션 → UNRESOLVED (0 아님) | IMPLEMENTED_PASS |
| T18 | NOT_ELIGIBLE의 확률 0 발행 차단 | IMPLEMENTED_PASS |
| T19 | 경계 연산자(>=/>) equality 분기 | IMPLEMENTED_PASS |
| T20 | RV21 분해 재결합 (1e-12) + 실추정식 일치 | IMPLEMENTED_PASS |
| T21 | 기대값 변종 = not_a_probability·등록 거부 | IMPLEMENTED_PASS |
| T22 | 사건 후 person-period 행 금지 | IMPLEMENTED_PASS |
| T23 | censoring 경계 (보지 못한 사건 입력 불가) | IMPLEMENTED_PASS |
| T24 | 미래 covariate 거부 | IMPLEMENTED_PASS |
| T25 | 상수 hazard 폐형 오라클 (NLL 1e-9) | IMPLEMENTED_PASS |
| T26 | 지평 단조 기계 보장 (log1p/expm1) | IMPLEMENTED_PASS |
| T27 | 불일치 표면 간 제약 투영 거부 | IMPLEMENTED_PASS |
| T28 | grid 단조·p_up 동일 artifact (합성+실 19행) | IMPLEMENTED_PASS |
| T29 | 점질량 경계·일반화 역함수 | IMPLEMENTED_PASS |
| T30 | PIT identity 앵커 (동결 recalibration_levels) | IMPLEMENTED_PASS |
| T31 | QuantileGrid의 cdf/CRPS capability 거부 | IMPLEMENTED_PASS |
| T32 | CDF 혼합 vs 분위수 평균 반례 | IMPLEMENTED_PASS |
| T33 | CRPS 오라클 (단일점·동결 교차·O(M²)·이동/스케일) | IMPLEMENTED_PASS |
| T34 | WIS GridMismatch + K=1 손계산 | IMPLEMENTED_PASS |
| T35 | fair-CRPS 보정 거부 3경로 | IMPLEMENTED_PASS |
| T36 | 스칼라 ES≡CRPS + 의존구조 평균 분리 | IMPLEMENTED_PASS |
| T37 | pointwise/simultaneous coverage 타입 분리 | IMPLEMENTED_PASS |
| T38 | purge 4조건 술어 + 등록 gap 규칙 | IMPLEMENTED_PASS |
| T39 | 재생성 OOF 덮어쓰기 거부 | IMPLEMENTED_PASS |
| T40 | 후보 실패 집계 정책 | IMPLEMENTED_PARTIAL (확증 fallback 전체 경로는 W7) |
| T41 | 희소 eligibility — 원 grid+mask 공동 재표집 | IMPLEMENTED_PASS |
| T42 | replicate당 단일 인덱스 (panel hash 결박) | IMPLEMENTED_PASS |
| T43 | UNTESTABLE·퇴화 정책·NOT_IDENTIFIABLE | IMPLEMENTED_PASS |
| T44 | 방향·δ 단위·Holm 손계산·family 보존 | IMPLEMENTED_PASS |
| T45 | 귀무 통과율 vs permutation p 분리 | IMPLEMENTED_PASS |
| T46 | 추정 성공 ≠ 증거 충분 | IMPLEMENTED_PASS |
| T47 | 논리 키 유일성 (재시도 ≠ 새 표본) | IMPLEMENTED_PASS |
| T48 | RESTATED 라벨 처리 | IMPLEMENTED_PARTIAL (실제 정정 발생 시 병렬 보고 — 현재 정정 0행) |
| T49 | **기준선 동일성** | IMPLEMENTED_PASS (§5 — tier-2는 1회 감독 실행 별도 기록) |
| T50 | scope 거부도 노출 감사 기록 | IMPLEMENTED_PASS |
| T51 | 비종결 attempt 복구 | IMPLEMENTED_PASS |
| T52 | pointer CAS — 과거 롤백 차단 | IMPLEMENTED_PASS |
| T53 | 오프라인 동작 (no_network) | IMPLEMENTED_PASS |
| T54 | 4축 비합산 | IMPLEMENTED_PASS |
| T55 | draft/필수 null/audit_only → run 거부 | IMPLEMENTED_PASS |
| T56 | 미래 라벨 보정 상태 차단 | IMPLEMENTED_PASS |
| T57 | STARTED→FAILED, 가짜 정상 artifact 0 | IMPLEMENTED_PASS |
| T58 | live/재구성 artifact 분리 | IMPLEMENTED_PASS |
| T59 | recorded_at vs label_available_at 분리 | IMPLEMENTED_PASS |
| T60 | commit 전 실패 → ISSUED 없음 | IMPLEMENTED_PASS |

---

## 8. 보호·불변성 준수 증거

### 8.1 준수 선언 (전부 기계 검증 가능)

- 동결 파일(`model_code_hash` 범위·V13 계수·계약) 변경 **0** — identity 테스트가 read-only를 단언.
- V5.2 보호 루트 아래 새 파일 **0**. `timeseries_v14` 문자열/패키지 추가 **0** (공유 cli.py 무수정).
- 홀드아웃·봉인 bytes 읽기 **0** — read_scope_guard가 영수증 없는 접근을 거부하고 거부를
  exposures 원장에 기록.
- 실험 예산 소모 **0**: V13 8/8(기존)·V14 1/4(기존) 불변 — 어떤 실험 원장에도 쓰지 않음.
- 신규 예측 발행 **0** — `origin_losses.parquet`는 기존 해소 기록의 재채점.

### 8.2 회귀 결과

전체 스위트: **3,632 passed / 1 failed / 20 skipped** (24:46). 유일 실패
`test_trendlines_local_service.py::test_http_never_runs_refresh_or_writes`는 재실행마다 실패
파라미터가 바뀌는(PUT→POST) Windows 소켓 flake(ConnectionAbortedError, WinError 10053) — 본
브랜치는 trendlines 코드·테스트 무변경이고, 저장소의 알려진 Windows 전용 실패 패턴과 동류.
머지 후 main CI(Linux)의 verify는 **통과**.

---

## 9. 지금 진행 중인 것 — 라이브 상태와 판정 시점 (2026-10-27 기준)

이번 작업은 **새 예측력 주장을 만들지 않았다**(설계상). "실제 예측률"은 기존 트랙의 라이브
전진 축적이 게이트에 도달할 때 판정된다.

### 9.1 트랙별 현재 표본과 게이트

| 트랙 | 현재 | 게이트 | 도달 추정* |
|---|---|---|---|
| V13 h5 셀 (rv/vix25/vix30) | 성숙 원점 27/60 | 셀당 성숙 60 | **2026-12 중순** |
| V13 h21 셀 | 12/60 | 〃 | **2027-01 중순** |
| V13 h63 셀 | 0/60 (2026-12 초부터 성숙 시작) | 〃 | **2027-02 말 ~ 03** |
| V8 shadow | 46/126 세션 (2026-10-21 기준) | 126세션 후 승격 검토 | **2027-02 중순** |
| V14 rung-2 (hazard 본령) | 실험 미실행 | V14-D11 승인 → 설계창 성적 즉시, live 확증은 평온 원점 성숙 60 | 승인 + 수개월 |

\* 추정 근거: 라이브 원점은 거래일당 1개(2026-09-04 개시, 현재 33행 — distinct 원점 32,
2026-09-04가 재동결 전후 두 run으로 중복 발행), 성숙은 원점+h세션 후. 거래일 ≈ 21/월로 환산한
기계적 추정 — 휴장·운영 중단 시 밀린다.

집계 규칙: 성숙 원점 수는 계약의 dedupe 규칙 — **(cell, origin)당 1행** — 로 센다 (행수로 세면
60원점 게이트를 하루 먼저 넘고 첫 원점 Brier가 2배 가중된다고 V13 resolve 구현이 명시 경고).
2026-09-04 중복(확률·라벨 동일) 때문에 행수 집계(28/13)와 1씩 다르다. 60 도달 후의 **판정
규칙**(V13 계약 명시): G1 기후 대비 쌍대 Brier CI90 하한 > 0 · G2 PB 비열위 · G4 y-block 순열
negative control ≤ 0.10 · family 보정 P(k ≥ k_obs) ≤ 0.05. V8의 126세션 도달 후 승격 검토
기준은 계약 promotion 블록을 따른다.

### 9.2 중간 집계 (판정 아님 — 성숙분만, 참고용)

| 셀 | n(성숙, dedupe) | PB Brier | 기후 Brier |
|---|---|---|---|
| rv_h5 | 27 | 0.0548 | 0.3013 |
| rv_h21 | 12 | 0.1873 | 0.4500 |
| vix25_h21 | 12 | 0.0150 | 0.1760 |

(dedupe 적용 집계 — 중복 포함 행 평균은 '첫 원점 Brier 2배 가중'이라 계약이 금지한다. 기후
Brier의 base rate는 설계창 고정값이다.)

**두 겹의 경고**: ① 셀당 60 미만의 중간 숫자는 판정이 아니다. ② §6.1의 발견 때문에 rv 셀
격차의 상당 부분은 창 역학이다 — "조기경보 가치"로 읽을 몫은 저 격차보다 작다.

### 9.3 판정 불가 조건 (게이트 도달해도)

V13-D13 제한: 성숙 60을 채워도 **사건 < 20 또는 변동성 국면 < 5**면 해당 셀은 "표본 부족 —
판정 불가" 라벨 유지. 연말까지 평온하면 VIX 셀은 사건이 쌓이지 않아 더 밀린다. 이 제한은 이번
작업의 `sample_sufficiency_gate`(T46) 철학과 같은 계열이다.

---

## 10. BLOCKED 항목과 해제 조건

| 항목 | 막는 것 | 해제 시 정확한 행동 |
|---|---|---|
| W5 실측 (V14 rung-2 hazard) | 사용자 결정 **V14-D11** + `approvals.jsonl` 리터럴 영수증 + rung-2 prereg | `hazard.py`를 V14 조건부 코호트에 적합, 조건부 PB 대비 **등록 비교** (δ·family 사전 고정) |
| W6 실자료 (옵션/일중) | 원천 1개의 계약·권한·coverage 확인 | source_spec 전 좌표 verified 후 `enabled` 전환 — **한 번에 1블록** |
| W7 등록 실험 | 계약 draft→registered (read scope/예산 영수증·primary metric·family·블록 규칙·seed manifest 전부 채움) | `run-experiment` — 모든 시도 불변 기록 |
| W8 운영 연결 | 운영 계약 + 표시 승급 승인 | shadow 발행·HOLD·모니터링 연결 |
| V8 tier-2 반복 | 장시간 실행 승인 (회당 ≈91분) | 추가 원점 재계산 + 행에 환경 메타데이터(BLAS/CPU) 기록 과제 |

---

## 11. 알려진 한계·약점 (작성자 자인 — 데블스 애드버킷)

검토자는 최소한 이 목록의 각 항목을 더 밀어붙이고, 목록에 없는 약점을 찾아 달라.

1. **tier-2는 1행·단일 환경**: h1/h5의 1~2 ulp 차이가 "환경 차이"라는 설명은 그럴듯하지만
   증명되지 않았다(원 행에 BLAS/CPU 기록이 없음). 동일 머신 반복 재현성(run-to-run)은 확인
   했으나 cross-env 재현은 미확인.
2. **rv_mechanics의 prereg는 같은 세션 내 선기록**: 결과 전에 좌표를 고정하는 규율은 지켰지만,
   좌표 선택(stride 21, 생성기 2종, n_paths 400) 자체가 같은 작성자의 판단이다. 외부 사전등록
   만큼의 구속력은 없다.
3. **설계창(2007-2014)의 대표성**: 85/70/55%는 고변동 구간이 포함된 창의 수치다. 평온기 위주
   라이브 구간에서는 기계적 확정 비율이 다를 수 있다 (방향은 불명).
4. **섭동 하니스는 합성+제한 grid**: INDIRECT_VIA_LAMBDA 판정의 λ 분기 증거는 제한된 2점
   grid에서 나왔다. 전체 탐색 공간에서 (lag,α)→λ 경로의 민감도는 미측정.
5. **127 테스트 ≠ 성능 증거**: 이 계층 자체가 아직 어떤 예측 개선도 보여주지 않았다 — 의도된
   상태지만, "인프라 투자 대비 회수"는 W5~W7이 승인·실행될 때만 발생한다.
6. **공동 재표집은 신규 구현**: 저장소의 기존 bootstrap 5벌과 블록 생성 규약 패리티는 합성
   테스트로만 고정했다. 실데이터 규모에서의 수치 특성(희소 셀의 퇴화율 등)은 실험 전 미지.
7. **WIS의 float 격자 비교**: `round(q, 12)` 동치 비교는 이진 부동소수 표현 경계에서 이론상
   취약 — 등록 격자가 십진 소수(0.025 등)라 실무 문제는 없다고 판단했으나 설계로 아름답진 않다.
8. **Holm의 untestable=1 처리**: 검정불능을 p=1로 family에 남기는 것은 보수적(FWER 보호)이지만,
   family가 untestable로 가득하면 검정력이 0에 수렴한다 — 희소 사건 셀에서 "영원히 아무것도
   기각 못 하는" 상태가 될 수 있다. 설계서의 선택이고 대안(계층적 family)은 후속.
9. **availability의 legacy null 정책**: 증거 없는 가용 시각을 null로 두는 보수성은 역사 재구성
   커버리지를 좁힌다 — NASDAQCOM·VIX 백필 전체가 재구성에서 빠지므로, 2026-08 이전 cutoff의
   재구성은 사실상 ALFRED 계열로 제한된다. "증거를 사서 채우는" 경로(원천 공개 기록 수집)는 W6
   성격의 후속.
10. **hazard는 합성에서만 검증**: 실측 코호트의 분리성(평온 원점의 사건 희소성), IRLS 수렴성,
    bin 경계 민감도는 미지. 특히 V14 평온 조건부 셀은 rung-1에서 "하드룰 셀 검정 불가"가 이미
    실측된 영역이다.
11. **채점기 자체 구현 리스크**: properscoring류 표준 구현과의 교차 검증은 CRPS(동결
    sample_crps와 1e-12)만 있다. WIS·Energy·Variogram은 손계산 오라클과 성질 테스트뿐 —
    외부 레퍼런스 구현 대조가 없다.
12. **단일 작성자 검증 편향**: 구현·테스트·감사·이 문서가 전부 같은 에이전트의 산출물이다.
    (이 문서는 별도 검증 패스로 전수 대조했지만, 그 검증자도 같은 모델 계열이다.) 이 리뷰팩의
    존재 이유.
13. **θ-창 순환성**: §6.1의 θ는 실측창과 같은 창의 중앙값이다 — h5 base rate가 ~0.57로 나오는
    것부터가 부분적으로 구성의 결과다. 진단 구조는 θ가 외생이어도 성립하나 수치 외삽은 금물.

---

## 12. 검토 요청 질문 (구체)

**A. 통계 절차**
1. §4.11의 centered paired bootstrap: 통계량 정의(observed = mean(d)+δ, null = 재표집 평균의
   중심화)와 좌측꼬리 p = (1+c)/(B_eff+1)이 H0: E[d] ≥ −δ에 대해 올바른가? 퇴화 replicate를
   분모에서 빼는 것(B_eff)이 p의 보수성을 해치는 경우가 있는가?
2. 블록 길이(mean_block)의 선택 규율이 설계에 없다 — 손실 자기상관 추정 기반 선택 vs 등록 상수,
   무엇을 권하는가? 지평 h와 원점 간격의 함수로 두는 게 맞는가?
3. Holm에서 untestable=1 유지(§11-8)의 대안으로 gatekeeping/계층 family를 쓸 때, 사전등록
   가능한 가장 단순한 구조는?
4. rv_floor 닫힌형(§6.1)의 유도를 검산해 달라 — 특히 F2 ≥ F1²/k 제약 하 최소화가 전역
   최소인지, ddof=1(분모 20)·평균 제거 정의와의 정합.
5. QLIKE를 RV 제곱(실현 분산 proxy)에 적용할 때의 proxy 노이즈 편향 — 이 설계에서 추가로
   고정해야 할 좌표가 있는가?

**B. 시간·라벨 계약**
6. 두 재생 모드(§4.5)의 경계 정의에 구멍이 있는가? 특히 "operational = max(first_seen,
   recorded) ≤ cutoff"에서 recorded_at이 first_seen보다 늦는 운영 지연의 처리.
7. grid-종속 라벨(§5.3, §6.3)의 차감 항등식 — 재현 목적으로 타당한가? 신규 표적 계약에서는
   "달력일 라벨 vs grid 라벨" 중 무엇을 기본으로 권하는가?
8. 조기 양성 제외(T16)와 within-horizon 사건 정의의 조합이 어떤 선택 편향을 남길 수 있는가?

**C. hazard (W5 실행 전 설계 검토)**
9. person-period composite likelihood에 naive CI 금지(§4.14)까지는 갔다 — 계수 불확실성
   보고를 block bootstrap으로 할 때, 원점 블록과 k(세션) 축의 2중 의존을 어떻게 다루는 게
   맞는가?
10. bin 경계 [1..5],[6..21],[22..63]의 사전 고정 vs 데이터 적응 — 평온 조건부 희소 사건에서
    절편 분리가 실패(사건 0 bin)할 때의 등록 가능한 fallback은?
11. V13 무조건부 PB와 V14 조건부 hazard의 공정 비교 설계 — eligibility가 다른 두 표면을 같은
    LossPanel에 넣을 때 mask 정의의 함정이 있는가?

**D. 감사 해석**
12. §6.1의 "기계적 확정 85/70/55%"에서, 남은 15/30/45%의 비기계적 양성에 대한 PB의 성적을
    분해 보고하는 것이 다음 감사로 적절한가, 아니면 사전등록 없이는 그것도 사후선택인가?
13. §6.2의 INDIRECT_VIA_LAMBDA 판정이 틀렸을 수 있는 경로(코드 추적 누락, PIT 이력의 간접
    전파 크기)를 지적해 달라.

**E. 전략**
14. W5~W8의 해제 순서 권고 — 현재 계획은 V14-D11(실험) 먼저, 운영 연결(W8) 나중이다. 반대
    순서(연구 계층의 shadow 운영화 먼저)의 논거가 있는가?
15. 이 전체 설계에서 우리가 **묻지 않은 질문** 중 가장 위험한 것은?

---

## 13. 부록

### A. 신규 파일 전체 목록

```
docs/design/NASDAQ_forecasting_upgrade_design_20261026.md      # 설계 정본 (반입)
src/ai_fc/mts_research/
  __init__.py  records.py  contracts.py  artifacts.py  sessions.py
  availability.py  snapshots.py  targets.py  maturity.py
  distributions.py  scores.py  resampling.py  prequential.py  gates.py
  hazard.py  cli.py
  adapters/__init__.py  adapters/v8.py  adapters/pb.py  adapters/report.py
  audits/__init__.py  audits/rv_mechanics.py  audits/objective_align.py
  audits/coherence.py  audits/time_audit.py
src/tests/
  mts_research_fixtures.py
  test_mts_research_{availability,snapshots,sessions,targets,maturity,hazard,
    contracts,artifacts,distributions,scores,resampling,prequential,gates,
    adapters_identity,audits,cli}.py                            # 16파일·127 테스트
data/mts_research/
  contracts/mts_research_v1.draft.yaml
  ledgers/exposures.jsonl
  derived/{origin_losses.parquet, coherence_audit.json, data_time_audit.json,
           objective_align_audit.json, v8_tier2_replay.json}
  experiments/rv_mechanics/{prereg.json, results.json}
data/contracts/ledger_registry.yaml                             # mts 6종 추가-전용
docs/research/mts_upgrade/
  repository_inventory.md  data_time_audit.md  coherence_audit.md
  objective_align_audit.md  rv_mechanics_audit.md  research_verdict.md
  implementation_handoff.md  checkpoint.md
  baseline_identity.json  test_results.json
  external_review_pack_20261027.md                              # 이 문서
```

### B. 재현 명령 (저장소 접근 시)

```bash
cd src && python -m pytest tests/test_mts_research_*.py -q      # 127 passed
cd src && python -m ai_fc.mts_research.cli inventory
cd src && python -m ai_fc.mts_research.cli replay-baseline      # T49 identity
cd src && python -m ai_fc.mts_research.cli audit-time
cd src && python -m ai_fc.mts_research.cli run-experiment --dry-run
```

### C. 핵심 수치 재인용 (대조용 한 곳 모음)

- 설계서: 151,199 bytes, SHA-256 `3783b26c…acd900b`
- identity: PB 32/33 + 123/123 · V8 tier-1 9/9 + 19/19(+grid-skip 2) · tier-2 h21/h63 bit
  동일, h1 max|Δ|=2.43e-17, h5 1.98e-16, 5,456.2s, 재계산 성숙 원점 1,020
- RV mechanics: 원점 96, 양성 h5 55/h21 67/h63 86, 기계적 확정 각 47 (85%/70%/55%)
- objective align: λ 분위 차 h21 0.0412 / h63 0.1542
- splice: base 비 0.9079, 겹침 3,513일 |Δ| 중앙값 1.67e-04, 공개일 전 native 주장 0/3,287
- 테스트: 신규 127/127, 전체 3,632 pass / 1 fail(환경) / 20 skip
- 라이브: V13 33행(distinct 원점 32; 2026-09-04~10-23), 성숙(dedupe) h5 27·h21 12·h63 0,
  V8 shadow 46/126(10-21)

### D. 본 문서가 인용한 저장소 내 정본

`research_verdict.md`(판정) · `implementation_handoff.md`(인계) · `repository_inventory.md`(W0)
· `baseline_identity.json`(identity) · `test_results.json`(T매핑) · 감사 보고서 4건 ·
설계서 `NASDAQ_forecasting_upgrade_design_20261026.md` · 프로젝트 헌법 CLAUDE.md · AGENTS.md

---

*이 문서는 참고 의견이며 어떤 내용도 매매 신호가 아니다. 모든 확률·점수는 연구 지위다.*
