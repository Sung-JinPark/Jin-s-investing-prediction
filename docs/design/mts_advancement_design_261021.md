# MTS 고도화 설계 v2 — 검증 결과 토대 전면 재검토와 수정·보완 명세 (2026-10-21, KST)

> **문서 지위**: 설계도(design) + 실행 명세. 결정이 아니다. 상위 헌법은 `CLAUDE.md` → `docs/DECISIONS.md` →
> `docs/design/mts_program_blueprint_v1_260909.md`(MTS 통치) · `ml_dl_strategy_blueprint_v1_260909.md`(ML 통치)
> → 트랙 계약. 이 문서는 어느 조항도 완화하지 않는다. 완화가 필요한 항목은 전부 §7 사용자 결정 묶음으로 올렸다.
>
> **작성 근거**: 2026-10-21 저장소 실측(origin/main `7d9ee56e`, 워크트리 `worktrees/active/mts-ml-advancement`)
> + 10에이전트 조사 워크플로(저장소 6축·웹 2축·화면 1축·완결성 비평 1) + 조사자 직접 검증.
> 조사 원문: 세션 스크래치 `understand/*.md`(저장소 밖). 핵심 수치는 전부 이 문서에 경로와 함께 옮겼다.
>
> **지위 공시**: 모든 산출은 참고 의견이며 매매 신호가 아니다. P3 게이트(해소 50문항+ · Brier < 0.18) 전에는
> 어떤 값도 자금 결정의 단독 근거가 아니다. 결정론 수치 모델의 과거 적합은 CLAUDE.md 5원칙 예외(dualdb §8)에
> 해당하나, 하이퍼파라미터(문턱·창·분할)가 정점 지식을 간접 내포할 수 있다는 caveat 를 유지한다.

---

## 0. 한 줄 판정

> **"모델을 하나 더 붙여서" 예측률을 올릴 근거는 없다** — 81검정 채택 1(퇴화 셀), 관측 |효과| 중앙값 0.003 < MDE 0.005
> (효과가 영 근처에 촘촘히 몰려 있음을 *측정*했다), V9~V12 가격분포 트랙도 같은 벽. 외부 문헌(변동성 예측에서
> 지속성 기준선을 이기기 어렵다는 HAR 계열 결론, TSFM 금융 실증의 8/9 실패)도 같은 방향이다.
>
> 그래서 이 설계는 **다섯 층**으로 간다. ① 유일한 무오염 증거인 **라이브 전진 표본의 무결성**을 고친다(원점 유실 9.4%·
> 중복 집계·사건-0 퇴화 미규정). ② 81검정이 한 번도 건드리지 않은 **정보 클래스**(예정 이벤트 달력·선물 포지셔닝)를
> 공공영역 데이터로 사전등록해 시험한다 — 이것이 사용자가 허용한 "외부 DB 오픈소스 레이어"다. ③ 93일째 멈춘
> **오픈웨이트 참조 계층**을 채점 가능한 상태로 만든다(추론 전용·라이브 전진 채점만). ④ 기준선의 자명성을 깨는
> 유일한 구조 변화인 **조건부 전이 표적(V14)** 을 계약 초안까지 준비한다. ⑤ 그 과정에서 바뀌면 안 되는 것을
> 바꾸지 않는다(홀드아웃·봉인·동결 계수·결과 후 규칙).

---

## 1. 현황 진단 — 검증 결과가 말하는 것

### 1.1 트랙별 상태 (2026-10-21 실측)

| 트랙 | 표적·손실 | 판정·상태 | 지금 숫자 | 근거 |
|---|---|---|---|---|
| **V13-VOL** | 변동성 사건 확률 9셀(VIX≥25/30 · RV21>0.1694, h∈{5,21,63}) · Brier | champion `persistence_pb`(당일 수준 1피처 로짓) · 홀드아웃 **partial 3/9**(rv_h5·rv_h21·vix25_h21) · T3 라이브 카드 | 라이브 원점 **29**(원장 30행, 09-04 중복) · 셀별 성숙 원점 h5 **25** / h21 **11** / h63 **0** · **라이브 구간 사건 0건**(VIX 14.2~18.4, RV21 0.121~0.167) | `data/timeseries_v13/ledgers/vol_live*.jsonl`, 계약 `publication.*` |
| **V8** | 가격 분위수 분포 · CRPS | GATE PASS · 봉인 1회 소모 · R8-D3 공개 · 점수판 **70점 B** | 섀도 **46/126** 세션(126번째 2027-02-16) · 첫 h63 성숙 2026-11-12 · DTWEXBGS 정체로 `shadow_operational_hold` | `data/timeseries_v8/ledgers/shadow_*.jsonl`, KNOWN_LIMITS A.36 |
| **daily6m** | 6개월 일별 분위수·상승확률 (연구 프리뷰) | `predictive_validation=not_established` | 해소 5행 · 평균 Brier **0.228**(0.25=무정보) | `data/timeseries_daily6m/ledgers` |
| **V9~V12** | exog·아키텍처·직교상태·방향전이 | 전부 동결·부정 결과 | — | DECISIONS |
| **ML 참조층** | Chronos-Bolt·Chronos-2·T5·GBM·FinBERT (추론 전용) | 가동 중이나 **93일 미실행**, 산출 **미채점** | 매핑 질문 5/18 · benchmark_ledger ml_prob 0/16 | `data/ml_history/2026.jsonl`, `src/ai_fc/ml/` |

### 1.2 V13 라이브 전진 — 숫자가 말하는 것과 말하지 않는 것

| 셀 | 성숙 원점 | 사건 | 모형 Σp | 기후 Σp | 라이브 Brier | 기후 Brier | BSS |
|---|---:|---:|---:|---:|---:|---:|---:|
| vix25_h5 | 25 | 0 | 0.28 | 7.7 | 0.0002 | 0.0946 | +0.998 |
| vix25_h21 | 11 | 0 | 1.30 | 4.6 | 0.0161 | 0.1760 | +0.909 |
| vix30_h5 | 25 | 0 | 0.08 | 4.5 | 0.0000 | 0.0318 | +1.000 |
| vix30_h21 | 11 | 0 | 0.47 | 2.8 | 0.0020 | 0.0634 | +0.968 |
| rv_h5 | 25 | 0 | 4.47 | 13.8 | 0.0381 | 0.3052 | +0.875 |
| rv_h21 | 11 | 0 | 4.53 | 7.4 | 0.1736 | 0.4500 | +0.614 |
| *_h63 | 0 | — | — | — | — | — | 첫 성숙 2026-12-04 |

(출처: `vol_live_resolutions.jsonl` 현행 계수 sha `1a857850` 행 집계. 기후 = 동결 아티팩트 `clim_base_rate`.)

**읽는 법 — 세 가지를 동시에 말해야 정직하다.**
1. BSS +0.6~+1.0 은 **실력의 증거가 아니다.** 고정 기후(GFC 포함 설계창 빈도: RV 0.55/0.67/0.88)는 평온 국면에서
   *자명하게* 지는 약한 기준선이다. 홀드아웃에서 vix30 계열이 "기후 대비 통과 → 건전 귀무에서 붕괴"한 것과 같은 모양이다.
2. **사건이 0건이면 y-block 귀무는 항등**이 되어 통과율 1.0 → 계약 346행에 따라 "판정 무효". 지금 9셀 전부가 그 상태인데,
   그 뒤 귀결(강등도 확인도 아님·축적 계속)이 계약에 **없다**. 60원점 도달(h5 2026-12-10/16) 전에 못 박지 않으면 결과 후 규칙 제작이 된다.
3. RV 셀은 **과대예측 방향**(모형 기대 4.5건 vs 실현 0)이고, 홀드아웃 신뢰도 곡선(rv_h21 중간 구간 pred .35~.54 vs obs .09~.19)과
   같은 방향이다 — 표본은 작지만 보정층(C3)이 다룰 결함의 모양은 이미 보인다.

### 1.3 원점 축적의 구조적 결손 (실측)

| 결손 | 실측 | 영향 |
|---|---|---|
| **원점 유실** | 32 거래일 중 3일(09-23·09-24·10-16, **9.4%**) — `pipeline.publish_latest` 가 패널 **마지막 날짜 1개**만 기록하므로 원천이 하루 늦게 들어오면 중간 날이 영구 소실 | 60원점 도달 ~1주 지연, 유실은 계속 누적 |
| **중복 집계** | 2026-09-04 원점이 구/신 계수 sha 로 2행 → `matured_counts`·`live_scoreboard.projection`·`roadmap_status` 가 **행 수**로 세어 25→26, 11→12 로 과다 | 60 을 원점 1개 먼저 넘고, Brier 에서 첫 원점 2배 가중 |
| **판정 verb 부재** | `cli.py` 의 V13 verb 는 latest/resolve/holdout/verify 4개. 60 도달 시 셀별 쌍대 손실차 CI90·귀무·T7 집계를 내는 코드가 **없다** | 결과 후 제작 위험 |
| **표시** | 라이브 누적 표가 60 전에도 Brier·개선% 숫자 노출, 사건 수 미표시 | "+88%" 를 실력으로 오독 |

### 1.4 81검정이 공통으로 고정했던 것 — 왜 "같은 종류 피처 하나 더"가 답이 아닌가

81검정 내내 표적·기준선(`persistence_pb`)·후보 형태(`logit[PB+β·x]`)·창·게이트가 한 번도 바뀌지 않았고, 후보 열(HAR·EWMA·
기간스프레드·달러·EBP·부호점프·반분산비·VRP·VXN)은 **전부 "당일 변동성 수준"이라는 같은 잠재상태의 두 번째 측정**이었다
(`mts_v14_new_track_design_260910.md` §4.1). 그래서 남은 선택지는 둘뿐이다 — **(a) 같은 잠재상태가 아닌 정보 클래스**
(전향적 달력·포지셔닝), **(b) 기준선의 자명성을 깨는 표적 형태**(조건부 전이).

### 1.5 오픈웨이트 참조 계층 — "실력 미지" 상태

Chronos-2·Bolt·T5 는 로컬 캐시(`~/.cache/huggingface/hub`)에 있고 `chronos==2.3.1`·`torch 2.13 cpu` 로 추론 가능하다.
그러나 ① 마지막 실행 93일 전 ② 산출 확률이 **한 번도 채점되지 않음** ③ 매핑 질문 5/18 ④ 종점 확률 캡 0.07/0.93(Chronos-2 의
21분위수 꼬리를 쓰지 않음). "참조 확률"의 실력이 미지이므로 divergence 표시(15%p+)의 정보 가치도 미지다.
TimesFM·Moirai·TiRex 는 미설치(의존성 설치는 AGENTS.md 상 사용자 승인 사항).

---

## 2. "예측률"의 정의 — 무엇을 올리는가

사용자가 보는 화면의 숫자와 그 분모를 먼저 못 박는다. **MTS 의 어떤 고도화도 C5(LLM 원장 해소 50문항+·Brier<0.18)
분모에 기여하지 않는다** — 두 게이트는 별개다(ml_dl 블루프린트 §0).

| 표면 | 지표 | 현재 값 | 움직이는 조건 |
|---|---|---|---|
| `#timeseries/backtest` (V8) | 100점 점수판(정확도30·확실성10·약속지킴30·위기대응15·실전15) | 70 / B | 봉인 성적은 불변. **실전 15 는 섀도 126세션 후**에만 움직인다 |
| `#timeseries/volatility` (V13) | 셀별 확률·80% 대역·홀드아웃 배지·라이브 누적 표 | 사건 0 상태의 BSS | 60원점·사건 발생·판정 verb |
| `#timeseries/daily` (daily6m) | 분위수·상승확률 | 검증 전 | 전진 해소 축적(원장 5행) |
| 홈 카드 | V13 vix25_h21 ("다변량 시계열 기준") | 배선 불가 셀 | V13-D6 보류 |
| (없음) | ML 참조 확률의 Brier/CRPS | **없음** | 채점 원장 신설(§4.3) |

**EXIT 트리거 ↔ 트랙 매핑(S1, 설계의 첫 산출물)** — `src/ai_fc/vol_base_rate_wiring.py:43 CELL_QUESTION_MAP = {}` 이 현실이다.

| EXIT 트리거(사용자 하드룰) | 등록 질문 | 수치 트랙 셀 | 배선 상태 |
|---|---|---|---|
| VIX 25+ | `vix-25-90d`(90 달력일) | V13 vix25_h63(**홀드아웃 fail**) | 불가 |
| VIX 30 | `vix-30-touch-by-2026-11-30` | V13 vix30_h21/h63(fail) | 불가 |
| 드로다운 룰(RV 급등) | 없음 | V13 rv_h5·rv_h21(**pass·배선 자격**) | 대응 질문 없음 — 신설은 사용자 결정(V13-D6) |
| 2026-10-28 FOMC | 이벤트 캘린더 | (rung-7 달력 블록이 처음으로 연결) | — |
| NVDA·MU 실적·SOXX 추세·크립토 | 질문 파이프라인 | V8/daily6m 분포(간접) | — |

→ "예측률을 올린다"의 **정직한 의미**: (i) V13 라이브 전진 BSS 가 사건이 생긴 뒤에도 양수로 유지되고 60원점 판정을 통과한다,
(ii) V8 섀도 CRPS 가 봉인 성적과 동급을 유지한다, (iii) 새 정보 클래스가 사전등록 게이트를 통과해 champion 을 바꾼다,
(iv) ML 참조층이 채점돼 실력이 **알려진다**(모르는 상태에서 아는 상태로 — 이것도 개선이다).

---

## 3. 설계 제약 (완결성 비평 K1~K15 요약 — 전부 상위 문서의 승계)

| # | 제약 | 이 설계에서의 적용 |
|---|---|---|
| K1 | 라이브 포워드 only. LLM 개입 평가 백테스트 금지. 결정론 수치모델만 과거 적합 | 달력·포지셔닝 블록은 결정론 로짓 → 설계창 적합 허용. **TSFM(Chronos 등)은 과거 창 채점 [미규정] → 라이브 전진만**(U3) |
| K2 | 홀드아웃(2015-18)·봉인(2019+) 미열람 | 이 문서의 모든 작업은 설계창(2007-14)·라이브(2026-09~)만 읽는다 |
| K3 | 결과 후 변경 금지(표적·셀·블록·문턱·기준선·귀무·T7·동결계수) | 라이브 퇴화 규정(A4)·백필(A1)은 성숙 원점이 이미 있으므로 **사용자 승인 사항**으로 분리 |
| K4 | 사전등록 커밋이 첫 행동, MDE·가드 결과 전 공표, family binomial, 9셀 전수, 미구현 도구 기재 금지 | rung-7·8 은 "계약 키 + 사전등록 문서 커밋 → 실행" 순서. 직교성 진단은 라벨 미접촉 |
| K5 | V13 개발 예산 2/8 잔여·홀드아웃 2·봉인 0/1 | rung-7 집행(7/8), rung-8 은 사전등록·적재까지 하고 집행 여부는 rung-7 결과 뒤 판단(§5) |
| K6 | 오픈웨이트 추론 전용·고정규칙 결합·참조 지위·비상업 가중치 표시 금지 | 신규 멤버 설치 없음. 채점 원장은 기록·표시만, 가중 변경 없음 |
| K7 | ML 게이트(보정 100+·학습결합 200+) | 보정 코드 없음. 설계만 기록 |
| K8 | PIT·append-only·supersedes | 달력 블록 pit_grade `prepublished_schedule`, 포지셔닝 `reconstructed_release_lag` |
| K9 | 라이선스 순서: FRED 공식 API+키만·CBOE 보류·메일 발송 금지·pending 이면 공개 payload 금지·연방 공공영역 우선 | **연방기관 공공영역만 적재**(Fed Board·BLS·CFTC). CBOE·지역은행·학술 지수는 V14 후보 목록에만 |
| K10 | 새 표적은 V14 에서만, track_open 은 사용자 승인 | V14 는 `status: draft_prereg · track_open: false · armed: false` 초안까지 |
| K11 | 표시 사다리 T0→T2→T3, 결합 금지, 60 전 판정 문구 금지 | 라이브 표는 사건 수·"판정 전" 라벨 추가(표시 전용) |
| K12 | V8 봉인 해시 경계 | V8 코드·케이던스 무접촉. 표시 계층만 |
| K13 | 모델·확률 변경은 섀도 검증 | Chronos-2 꼬리 분위수는 **병기 필드**로만(교체 아님) |
| K14 | 의존성 설치는 사용자 승인 | 설치 0. TSFM 신규 멤버는 결정 묶음 |
| K15 | 트랙 등록 체크리스트 전수(ledger_registry·inventory·read_model·워크플로 구독) | 신규 원장·계약은 전부 등록 + inventory 재생성 |

---

## 4. 레이어 설계

### 4.1 L1 — 라이브 전진 표본의 무결성 (V13 운영, $0, 게이트 산술 무변경)

| ID | 변경 | 구현 | 승인 |
|---|---|---|---|
| **A2 distinct 원점 집계** | `matured_counts`·`live_scoreboard.projection`·`roadmap_status` 를 (cell, origin) distinct 로, 같은 원점에 두 sha 가 있으면 **계약에 핀된 sha 우선** | `src/ai_fc/timeseries_v13/resolve.py` `matured_counts` · `live_scoreboard.py` · `tools/roadmap_status.py` · 테스트 1건 | 불필요(읽기모델) |
| **A3 사건 수 공시** | 라이브 누적 표에 `사건 n / 모형 기대 Σp / 기후 기대 Σp` 열 + 60 전 "판정 전(표본 n/60)" 라벨 + 사건 0 이면 "사건 0건 — BSS 는 자명 이득" 문구 | `live_scoreboard.py` 집계 필드 추가 · `dashboard.js` 표 열 · 읽기모델 스키마 · 바이트 예산 24KB 내 | 불필요(표시 전용 C4) — method_changes `display_only` 행 |
| **A5 판정 verb(읽기 전용)** | `timeseries-v13-vol-live-verdict`: 셀별 성숙 원점·사건·쌍대 손실차(기후−모형) 블록부트 CI90(ℓ13·B2000·seed 20260907)·y-block 귀무 통과율·실행 시점 degeneracy_guard·T7 집계를 **인쇄만**. 원장 쓰기 0·강등 적용 0. 60 미만 셀은 "표본 부족"만 | `src/ai_fc/timeseries_v13/live_verdict.py` + CLI + 테스트(합성 원장) | 불필요(계약 348행 "verb 는 규칙을 실행만" — 규칙 무변경) |
| **A1 원점 백필(앞으로만)** | `publish_latest` 가 마지막 기록 as_of 이후 **모든** 패널 날짜에 행을 쓴다. 동결 계수·당일 x_t 1개뿐이라 늦게 계산해도 같은 p. 행에 `late_capture_sessions` 기록. **이미 유실된 3일 소급 금지** | 코드는 만들되 **승인 영수증(V13-D11) 없으면 단일 원점 모드로 동작**(fail-closed) | **필요** — AGENTS.md PIT 문면(available_at ≤ as_of)과 긴장. §7 U5 |
| **A4 라이브 게이트 퇴화 규정** | 계약 `live_forward_gate` 바이트 무수정, 신규 키 `live_forward_degeneracy`: 60 도달 시 클래스별 사건 <20 → `untestable_by_construction`(판정 보류·축적 계속), 국면 <5 → `episode_thin`, 귀무 >0.10 → 판정 무효(강등 아님·확인 아님) | 개정 YAML 블록을 §7 에 **원문 제시**, 적용은 승인 후 | **필요** — 성숙 원점이 이미 있어 엄밀히 결과 후. 보수 방향만. 마감 2026-12-10 |

### 4.2 L2 — V13 rung-7: 예정 이벤트 달력 블록 (예산 7/8 · $0 · 연방 공공영역)

**가설(한 문장)**: 향후 h 세션 안에 예정된 정책·거시 발표(정례 FOMC 결정일·고용보고서·CPI)가 있으면, 당일 변동성 수준이 같아도
변동성 사건 확률이 높다 — 전향적 달력 정보는 `persistence_pb`(당일 수준)에 **없다**.

**왜 다른가**: 81검정 중 유일하게 "당일 수준의 재측정"이 아니다. 예정 발표일 주변의 실현변동성 집중은 확립된 채널
(Andersen–Bollerslev 계열)이고, VIX·RV 수준과의 상관은 ≈0 이 기대된다(사전 포크 진단으로 실측·공시).

**데이터 (신규 적재 — 루프 밖 1회, 영수증·sha 핀)**

| 원천 | 내용 | 라이선스 | PIT |
|---|---|---|---|
| Fed Board `fomchistorical{2007..2014}.htm` | 회의일(결정일 = 회의 마지막 날). **비예정(unscheduled) 회의·전화회의는 제외**(origin 시점에 알 수 없었던 정보) | 연방 공공영역(Board disclaimer: public domain, 고지 요청) | 연초 공표 일정 → `prepublished_schedule` |
| BLS 일정 아카이브 (Employment Situation · CPI) | 발표일. 2013-10 셧다운으로 지연된 2건(NFP 10-04→10-22, CPI 10-16→10-30)은 **원래 예정일**을 쓰고 실제일을 병기·공시 | 연방 공공영역(bls.gov/bls/linksite) | 동상 |

저장: `data/timeseries_v13/exog/scheduled_events_2007_2014.jsonl`(행: kind·scheduled_date·actual_date·source_url·raw_sha256),
`data/timeseries_v13/exog/raw/*.html` 원본, `raw_receipts.jsonl` append. `ledger_registry.yaml` 에 immutable 등록.
계약 `data_policy.series: [VIX, NASDAQCOM]` 은 바꾸지 않는다 — rung-6 과 같이 **신규 키**로만 등록(`no_write_to_sealed` 유지).

**블록 3개 (결과 전 고정 — 이 목록이 전부)**. 원점 인덱스 i 의 라벨 창은 세션 i+1..i+h(`features.labels_vix`). 블록도 같은 창.

| 블록 | 정의 | 단위 | 기대 |
|---|---|---|---|
| `E1_fomc_in_window` | 세션 i+1..i+h 중 정례 FOMC 결정일 수 | 정수(h5: 0/1, h63: 1~2) | h5·h21 에서 양(+) |
| `E2_macro_release_in_window` | 세션 i+1..i+h 중 고용보고서+CPI 발표일 수 | 정수(h5: 0~2) | h5 에서 양(+), h21/h63 은 거의 상수 → 측정된 영 예상 |
| `E3_log_sessions_to_next_fomc` | log(1 + 세션 i 이후 다음 정례 FOMC 결정일까지 세션 수) | 실수 | 음(−) — 가까울수록 사건 확률↑ |

- 전부 1열·lag 0(일정은 선공표)·상호작용 없음. 자동기각 규칙(|corr| > 0.85 vs VIX_t·RV21_t) 승계 — 사전 진단으로 실측.
- 후보 형태 `logit[PB 피처 + β·E]`, 게이트 = 셀별 쌍대 Brier(PB−후보) **양방향** CI90 하한 > 0 ∧ 증분 y-block(ℓ13) 귀무 ≤ 0.10.
  family 대표값 binomial P(k ≥ k_obs | n=27, p=0.05). degeneracy_guard 실행 시점 적용. 9셀 전수.
- 정지 규칙: ① 설계창 밖 데이터 필요 시 중단 ② 블록 정의를 바꿔야 결과가 나오면 부정 결과로 기록 ③ 채택 셀이 나와도 홀드아웃은
  이 rung 만으로 소모하지 않음(사용자 승인).
- 부정 결과 프로토콜: 채택 0 이면 "예정 이벤트 달력 정보도 당일 수준에 흡수된다(h5 포함)"로 기록. 그 경우 달력 정보는 V14 조건부
  표적에서만 재시험 가능.
- 산출: `data/timeseries_v13/vol/ladder_rung7_calendar.json`, 원장 `vol_experiments.jsonl` 1행, `evaluations_spent 6→7`,
  판정서 `docs/review/V13_VOL_RUNG7_CALENDAR_VERDICT_<date>.md`.

### 4.3 L3 — 오픈웨이트 참조 계층: 채점 가능 상태로 (ML, 추론 전용)

| ID | 변경 | 규율 |
|---|---|---|
| **C2 참조 채점 원장** | 사전등록 계약 `data/contracts/ml_technique_m4_reference_scoring.yaml`(ml_dl §6 형식: layer L3·gate none·primary brier/crps·decision_rule "기록·표시만, 강등 없음"). 원장 `data/ml_history/reference_scores.jsonl`(append-only). verb `ml-reference-resolve`: ml_history 의 run 행마다 ① 질문 매핑 확률 → 판정일 뒤 Brier ② 분위수 밴드(q10~q90) → 지평 종점 실현치로 pinball·p10–p90 커버리지·CRPS(5분위 근사), 베이스라인 GBM. 성숙은 거래일 인덱스. **라이브 전진만**(run_ts 이후 실현치) — 과거 창 재예측·채점 없음 | 채점≠학습(CLAUDE.md:29). 홀드아웃·봉인 무관. U3 보수 기본값 |
| **C3 매핑 커버리지** | `QUESTION_MAPS` 5 → 레지스트리의 수치 임계 질문 전부(vix-30/13/40·spx-7%·ndx-15%·comp-30000·t10y2y·hy-oas 등 — 결정론 임계 비교). 극단 임계 종점 질문은 캡 대신 T5 경로 종점 경험분포 | 결정론 매핑 → 부합. `test_question_maps_registry_alignment` 정합 |
| **C5 Chronos-2 꼬리 분위수** | 종점 확률 캡 0.07/0.93 대신 Chronos-2 21분위수(q01·q05·q95·q99) 보간값을 **병기 필드** `prob_tail_c2` 로 기록. 교체는 4주 병기 후 별도 결정 | 고정 규칙 변경이나 K13(섀도 검증) → 병기 |
| **C1 재가동 배선** | 현재 Yahoo 의존(^IXIC·SOXX·^VIX·^TNX)과 CI 미설치(`[ml]` extra·HF 캐시 ~820MB)가 걸림. ^IXIC → FRED `NASDAQCOM`(공식 API+키) 이관은 코드로 하고, **실행 환경(로컬 예약 vs CI job)은 결정 묶음** | §7 U9 |
| 신규 TSFM 멤버(TiRex-2·Sundial·TTM r2.1) | 설치 없음. 라이선스·CPU·분위수 레벨 [미확인] | CHANGELOG 2026-07-20 "별도 지시 대기" 유지 |

### 4.4 L4 — V14 조건부 전이 트랙 초안 (사용자 결정 U1 대기 · 비가역 자원 0)

`data/contracts/multivariate_timeseries_v14_conditional.yaml` — `status: draft_prereg · track_open: false · gates.armed: false`.

| 항목 | 초안 값 | 근거 |
|---|---|---|
| 표적 | `P(VIX_close ≥ 25 within h | VIX_t < 20)` h∈{5,21,63} · `P(RV21 > θ within h | RV21_t ≤ θ)` θ=0.1694(V13 동결 승계) h∈{5,21,63} = **6셀** | 조건은 운영 의미(평온 → 하드룰 25 발동 전 조기경보). 문턱을 통계가 통과하도록 고르지 않는다(V14 §7-6) |
| 창 | V13 설계창 2007-2014 재사용, split 2011-01-01. 홀드아웃·봉인 무접촉 | V14-D1 B5 |
| 기준선 | 조건부 기후 · 조건부 `persistence_pb`(부분집합 내 적합) — 부분집합에서 수준의 분산이 줄어 자명성이 약해진다 | V14 §4.4 C1 |
| 후보 | rung-7/8 블록(달력·포지셔닝)·지속기간 블록 — 전부 **결과 전** 계약에 고정 | — |
| 가드 | 에피소드 가드(반창×클래스 ≥5, marginal 3~4) 를 **track_open 승인 뒤 P0 로 실측·공시**(측정 후 선택했음을 공시) | V14 §7-5 |
| 홀드아웃 | `absent_by_construction` — V13 홀드아웃(2015-18) 재사용 **불허**(C3). 판정은 라이브 전진(I3) 또는 사용자 결정 | V14-D2 C3·D8 |
| 예산 | 4 (E1) | V14-D4 |

### 4.5 L5 — 외부 공공영역 데이터 레이어 (rung-8 후보 적재·사전등록, 집행은 조건부)

| 원천 | 블록 후보 | 라이선스 | PIT | 상태 |
|---|---|---|---|---|
| **CFTC TFF (Socrata `gpe5-46if`)** — VIX 선물(CFE) · NASDAQ-100 e-mini | `P1_vix_lev_net`: 레버리지펀드 순포지션/미결제 · `P2_vix_am_net`: 자산운용사 순포지션/미결제 · `P3_nq_lev_net`: NQ 레버리지펀드 순/미결제 | 공공영역(cftc.gov "available for public download and use"), 기존 `cftc_cot_bitcoin_d0` 와 같은 엔드포인트 | 화요일 포지션 → 금요일 15:30 ET 발표. 보수 지연 **4 세션**(발표 다음 거래일부터) `reconstructed_release_lag` | 적재·직교성 진단·사전등록까지 이 세션. **집행(8/8 소진)은 rung-7 결과·직교성·커버리지 균형 확인 뒤** |
| OFR FSI 하위지수(funding·credit) | V14 후보 | 연방 공공영역(원자료 Datastream — 지수값만) | T+2, 개정 이력 파일 존재 | 목록만(적재 안 함) |
| EPU 일간(CC BY 4.0) | V14 후보(h21/h63 전용, lag ≥22) | CC BY 4.0 | 30일 재추출 → 빈티지 없음 | 목록만 |
| Philly Fed ADS(전 빈티지) | V14 후보 | 지역은행 'research only' — **사용자 판단** | native vintage | 목록만 |
| Cboe VIX9D·VIX3M·VVIX·SKEW / FRED 경유 CBOE 지수 | **제외** | 12-1·12-5·V13-D9 보류 | — | — |

---

## 5. 실행 순서 (커밋 단위 — 사전등록이 결과보다 먼저)

```
S1  설계 문서(이 파일) + 결정 묶음 초안 커밋
S2  L1-A2·A3·A5 구현 + 테스트                              [커밋 2]
S3  rung-7 적재: Fed·BLS 일정 fetch → exog jsonl + receipts + ledger_registry 등록
S4  rung-7 직교성 진단(라벨 미접촉) → prereg/rung7_calendar_orthogonality.json
S5  rung-7 사전등록: 계약 신규 키 rung7_calendar_blocks + prereg 문서     [커밋 3 = prereg_commit]
S6  rung-7 집행: tools/v13_vol_rung7_calendar.py → ladder json·원장 1행·판정서·evaluations_spent 7 [커밋 4]
S7  rung-8 적재(CFTC TFF)·직교성·사전등록(집행 보류 가능)              [커밋 5]
S8  L3-C2·C3·C5 구현 + 사전등록 계약                                   [커밋 6]
S9  V14 초안 계약 + 도구 골격(실행 verb 없음)                            [커밋 7]
S10 문서: DECISIONS·MODEL_REGISTRY·KNOWN_LIMITS·inventory 재생성          [커밋 8]
S11 검증: 표적 pytest → 전체 스위트 → dashboard 빌드 → sync/audit/inventory --check
S12 PR → CI 초록 확인 → 머지 (사용자 규율: 초록일 때만)
```

rung-8 집행 조건(사전 고정): ① rung-7 판정서 커밋 완료 ② 세 블록 |corr| ≤ 0.85 ③ 설계창 early/late 커버리지 각 ≥ 90%
④ 실행 시점 degeneracy_guard 로 untestable 셀 ≤ 3. 네 조건을 전부 만족하면 집행(8/8), 하나라도 미달이면 "사전등록된 미집행 자산"으로 남긴다.

---

## 6. 검증 계획

| 대상 | 검증 |
|---|---|
| L1 | 합성 원장으로 distinct 집계·핀 sha 우선·판정 verb 의 원장 무수정(해시 전후 동일)·60 미만 "표본 부족" |
| rung-7 | 적재 원본 sha 핀 · 비예정 회의 제외 목록 명시 · 블록 값 spot-check(예: 2008-12-16 FOMC) · 러너 결과 JSON content_hash · 원장 행 = 계약 evaluations_spent |
| L3 | 참조 원장 append-only·성숙 전 채점 거부·Brier 산식 단위(fraction) |
| 전역 | `pytest -q`(src/ 안, ~26분, 백그라운드) · `python -m ai_fc dashboard` 예산 · `sync --check` · `audit-ledgers --check` · `inventory --check` · 보호 해시 무변경(V8·V2·V5.2 루트 무접촉) |

---

## 7. 사용자 결정 묶음 (원문 승인 없이는 집행하지 않는 것)

| ID | 결정 | 선택지 | 권고 | 왜 내가 못 정하는가 |
|---|---|---|---|---|
| **U1 (V14-D0)** | V14 조건부 전이 트랙을 여는가 | A2 개설 / A4 보류 | A2 | `track_open` 은 사용자 승인(블루프린트 §8) |
| **U3 (ML-A6)** | TSFM(Chronos 등) 참조 확률의 평가 범위 | 라이브 전진만 / 설계창 포함 | 라이브 전진만 | CLAUDE.md 미규정 — 사전지식 오염을 배제 못 함(M4 금융 1,559계열 익명) |
| **U4 (V13-D12)** | 라이브 게이트 퇴화 규정(§4.1 A4) 등록 | 등록 / 미등록 | 등록(마감 2026-12-10) | 성숙 원점이 이미 있어 결과 후 규칙 추가 |
| **U5 (V13-D11)** | 원점 백필(앞으로만, `late_capture_sessions` 공시) | 허용 / 불허 | 허용 | AGENTS PIT 문면과 긴장 |
| **U7** | 2026-09-10 "메일 발송 금지"의 현 상태 | 유지 / 해제 | — | 연방 공공영역 fetch 는 무관하나 CBOE-1 은 이 지시에 종속 |
| **U8** | `calendar_sources.yaml probability_linkage: forbidden` 해석 | "일정→확률 직접 연결 금지"(더미 피처 사전등록 허용) / 전면 금지 | 전자 — rung-7 은 이 해석 아래 집행 | 조항 해석 |
| **U9** | ML 참조층 실행 환경 | 로컬 예약(토 11:30 전) / CI job(`[ml]` 설치+HF 캐시) / 미가동 | 로컬 예약 | 비용·Yahoo 약관 |
| **U10 (V13-D13)** | rung-8(CFTC 포지셔닝) 집행 — §5 조건 미달 시 | 집행 / 보류 | 조건 충족 시 집행 | 마지막 예산 단위 |

승인 원문 템플릿(블루프린트 §8.2 형식):
```
V14-D0 A2 승인
ML-A6 라이브전진만 승인
V13-D12 라이브 게이트 퇴화 규정 등록 승인
V13-D11 원점 백필(앞으로만) 승인
V13-D13 rung-8 집행 승인
```

---

## 8. 하지 않을 것

홀드아웃·봉인 열람 / 동결 계수·게이트 산술·60·CI 형·T7 변경 / 결과 후 블록 추가 / 이미 실패한 피처 반복(HAR·EWMA·DGS·달러·EBP·
부호점프·반분산비·VRP·VXN·CBOE 지수) / TSFM 파인튜닝·LoRA·트리부스팅 "모델 하나 더" / 의존성 설치 / 메일 발송 / `forecasts/`·
`calibration/ledger.csv`·V8·V2 봉인 코드 수정 / 홀드아웃 통과 셀에 맞춘 질문 신설 / 숫자를 실전 자금 결정의 단독 근거로 제시.

---

## 9. 정직한 기대치

| 레이어 | 성공 확률(주관) | 실패해도 남는 것 |
|---|---|---|
| L1 무결성 | 확실(결정론) | — |
| rung-7 달력 | 채택 ≥1셀 **25%**(캠페인 경험 1/81 대비 높게 본 이유: 정보 클래스가 처음 바뀜) | "달력 정보도 당일 수준에 흡수된다"는 새 지식 → V14 후보 축소 |
| rung-8 포지셔닝 | 15% | 동상 |
| L3 채점 | 확실(기록) | 실력이 *알려진다* |
| V14 | 개설 자체가 결정 — 개설 시 성공 20% | 자명 기준선 문제의 정면 돌파 기록 |

전체적으로 **부정 결과가 정상 종료**다(블루프린트 §10). 이 문서의 가치는 "무엇이 배제됐는가"를 사전등록으로 못 박는 데 있다.
