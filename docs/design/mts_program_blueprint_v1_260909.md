# NASDAQ 다변량 시계열 예측 프로그램 — 통치 설계도 v1 (2026-09-09)

> **지위**: 이 문서는 다변량 시계열(multivariate time-series, MTS) 트랙 V1~V13과 그 후속 전부를 통치하는 **상위 설계도**다. 개별 트랙 계약(`data/contracts/multivariate_timeseries_*.yaml`)이 하위 정본이고, 이 문서는 그 계약들이 지켜야 할 형(form)·순서·승인 지점을 규정한다. 계약과 이 문서가 충돌하면 **계약이 이긴다** — 계약은 결과 전 커밋된 사전등록이고 이 문서는 그 위의 서술이기 때문이다. 다만 이 문서가 금지한 것을 계약이 새로 허용하려면 사용자 승인이 필요하다.
>
> **상위 헌법**: `CLAUDE.md`(5원칙·하드 게이트) → `docs/DECISIONS.md` → 이 문서 → 트랙 계약 → 실행 도구. 이 문서는 `CLAUDE.md`의 어떤 조항도 완화하지 않는다.
>
> **사용법**: 여러 세션·여러 주에 걸쳐 읽힌다. 다음 세션의 작업자(사람이든 Claude든)는 §9 "상태 파생 규약"을 먼저 실행해 현 단계를 기계로 확인하고, §3의 해당 단계 행으로 직행한다. 이 문서를 손으로 갱신해 상태를 관리하지 않는다.
>
> **작성 근거**: 외부 검토관 초안(`ROADMAP_BLUEPRINT_v0.md`·`REVIEW_VERDICTS.md`, 2026-09-09)을 입력으로 받되, 2026-09-09 저장소 실측 3갈래 조사에서 **다섯 개 주장이 뒤집혔다**. 차이와 근거는 부록 B.

---

## 0. 빠른 진입 — 새 세션의 첫 5분

이 문서는 길다. 처음부터 읽지 말고 아래 순서를 따른다.

| 순서 | 행동 | 산출 |
|---|---|---|
| 1 | `python tools/roadmap_status.py` 실행 (미구현이면 §9.3 표를 손으로 대조) | 현 단계 · 차단 요인 · 다음 승인 · 다음 명령 |
| 2 | §3에서 **그 단계의 행 하나만** 읽는다 | 진입 게이트 · 작업 · 종료 게이트 · 정지 규칙 |
| 3 | 승인이 필요하면 §8의 원문 템플릿을 사용자에게 제시하고 **대기한다** | 승인 원문 |
| 4 | 착수 전 §3.9(공통 정지 규칙)와 §5.4(금지 목록)를 훑는다 | 위반 예방 |
| 5 | 결과가 나오면 §10(부정 결과 처리)으로 판정한다 | '측정된 영' / 미결 / 채택 |

**절대 하지 말 것 (첫 5분에 가장 흔한 사고)**
- 이 문서의 "현 위치"(§2)를 **최신이라고 가정**하기 — §2는 2026-09-09 스냅샷이다. 진실은 §9.3의 파일·필드다.
- 승인 없이 홀드아웃·봉인 verb를 **구현**하기 — `absent_by_construction`은 "아직 안 만들었다"가 아니라 **"만들지 않기로 계약했다"**이다.
- 결과를 본 뒤에 임계·기준선·귀무를 조정하기 — 이것 하나로 캠페인 전체가 무효가 된다.

---

## 1. 지위·승계·완성 정의

### 1.1 승계하는 헌법 조항 (완화 불가)

| 조항 | 출처 | 이 프로그램에서의 의미 |
|---|---|---|
| 이벤트 → 가격 | CLAUDE.md 5원칙 ① | MTS 산출물은 **기한·임계값·판정기준이 있는 사건 확률**이다. V13의 9셀(VIX≥K 터치, RV21>θ 초과)이 이 형을 만족한다. 가격 수준 예측은 표적이 아니다. |
| 백테스트 절대 금지 + dualdb §8 예외 | CLAUDE.md 5원칙 ⑤ | 결정론 **수치 모델**의 과거 적합·워크포워드만 허용. 산출물은 **base rate 참조**이지 LLM 캘리브레이션 표본이 아니다. LLM이 개입하는 어떤 평가에도 이 예외를 적용하지 않는다. |
| ML 게이트 | CLAUDE.md 하드 게이트 | 해소 100+ 전 LLM 원장 isotonic/Platt 금지, 해소 200+ 전 가중 학습 결합 금지, DL 가격 학습 영구 금지. **결정론 트랙 내부의 cross-fit isotonic(V13 `reliability.cross_fit_isotonic_h63`)은 LLM 원장 보정이 아니므로 이 게이트와 무관** — 이 구분을 잃으면 안 된다. |
| 불변 기록 | CLAUDE.md 불변성 규칙 | 원장(`*_experiments.jsonl`·`*_live.jsonl`·`holdout_scorings.jsonl`·`approvals.jsonl`)은 append-only. 행 수정 금지. |
| 홀드아웃·봉인 1회 | 각 트랙 계약 `stopping_points` | V13 홀드아웃 슬롯 3, 봉인창 공개 `maximum_disclosures_per_model_version: 1`(V8 계약 L108). **비가역 자원** — 소모 전 사용자 원문 승인 필수. |
| 사전등록 | 각 트랙 계약 `development_protocol.preregistered_before_results: true` | 결과를 보기 전에 가설·손실함수·기준선·임계 형·MDE·귀무를 커밋한다. 결과 후 이들을 바꾸는 시도는 위반이며 즉시 중단 사유(§3 정지 규칙). |
| P3 게이트 | CLAUDE.md 하드 게이트 | 해소 50문항+ & Brier < 0.18 전에는 **어떤 출력도 실전 자금 결정의 단독 근거가 아니다**. 모든 표시에 "참고 의견" 지위 유지. |

### 1.2 프로그램 완성의 정의 — C0~C4 (T3 상한)

외부 검토관의 지적 하나는 채택한다: **C0(판정 기계 건전성)이 누락돼 있었다.** 귀무가 불건전하면 어떤 게이트 통과도 증거가 아니다. 다만 검토관이 든 근거(T-A의 p-순열 0.201)는 이미 계약이 `prohibitions.p_permutation_null_as_negative_control: true`로 봉인한 사건이므로, C0의 실질은 **에피소드 가드**와 **MDE 사전 공표**에 있다.

| 조건 | 이름 | 충족 판정 (기계 판독 가능한 형태는 §9) |
|---|---|---|
| **C0** | 판정 기계 건전성 | ① 건전 y-block 귀무(ℓ=13) 실측 통과율 ≤ 0.10 — 전 셀 ② **에피소드 가드 통과** — 반창×클래스별 연속 에피소드 수 ≥ 임계 ③ 결과 전 MDE 공표. 세 항 **상시** 조건 — 어느 단계에서도 깨지면 그 셀의 모든 판정이 무효. |
| **C1** | 라이브 전진 표본 | V13: 셀당 성숙 원점 ≥ 60(`live_forward_gate.minimum_matured_origins_per_cell`). V8: 섀도 세션 ≥ 126(`minimum_shadow_sessions`, V8 계약 L278). |
| **C2** | 홀드아웃 소모·판정 | V13 홀드아웃 1슬롯 소모 후 `publication.holdout_status ∈ {pass, partial, fail}`. **결과 무관 완결** — FAIL도 C2를 충족한다. |
| **C3** | 배선 | 홀드아웃 PASS 셀의 확률이 EXIT 트리거 질문의 base rate 공간에 **표시만** 연결(V13-D6). 산술 결합 0·자동 재예측 0. |
| **C4** | 표시 정직성 | 표시 사다리(§7)의 페일클로즈 가드 전부 통과 + 한계 공시(band80 의미·홀드아웃 상태·국면 표본 두께). |

**프로그램 완성 = C0 ∧ C1 ∧ C2 ∧ C3 ∧ C4, 표시 상한 T3.**

### 1.3 프로그램 **외부** 조건 — 오독 방지

| 조건 | 왜 외부인가 |
|---|---|
| **C5** — LLM 캘리브레이션 원장 해소 50문항+ & Brier < 0.18 | 이것은 `calibration/ledger.csv`(LLM 예측 원장)의 성질이지 수치 모델의 성질이 아니다. MTS 프로그램이 아무리 완벽해도 C5를 진전시키지 못한다. |
| **T4** — 실전 자금 결정 근거 | V13 계약 `publication.display_tiers_allowed`에 **t4 값 자체가 없다**(구조 차단). T4는 C5(=CLAUDE.md P3 게이트)에 종속하며, MTS 프로그램의 종료 조건이 아니다. |

> **오독 경보**: "프로그램을 완성했는데 T4가 안 열린다"는 실패가 아니라 **설계대로다**. C0~C4는 "이 수치 모델이 정직하고 검증됐다"를, C5/T4는 "이 시스템 전체가 돈을 걸어도 되는가"를 각각 답한다. 두 질문은 다르고, 후자의 답은 LLM 원장이 낸다.

---

## 2. 현 위치 실측표 (2026-09-09)

### 2.1 트랙 V1~V13 한 줄 요약

| 트랙 | 표적·손실 | 판정 | 자원 소모 |
|---|---|---|---|
| V1~V7 | 다변량 가격 분포 (CRPS) 계보 | V8로 승계·봉인 | — |
| **V8** | 가격 분위수 분포 (CRPS), 봉인창 공개 | **GATE PASS·봉인 1회 소모 완료**, R8-D3 공개 완결 | 봉인 공개 1/1 소모 (`maximum_disclosures_per_model_version: 1`) |
| **V9** | 신용·유동성 exog (CRPS) | **동결** — ablation 6종 전부 무효익, exog 경로 소진 | 홀드아웃 미소모 |
| **V10** | 아키텍처 연구 (CRPS) | **동결** — 챔피언 W3 γ=−0.10(+0.64%)이 6렌즈 적대적 검증에서 GFC 위기원점 인공물 판정 → 홀드아웃 **기각**, 슬롯 3/3 보존 | 홀드아웃 0/3 |
| **V11** | 평시 상태신호 직교 진단 | **동결** — 값싼 직교 진단이 후보를 포크 이전에 걸러냄(백테스트 0회) | 백테스트 창 0 |
| **V12** | 방향 이벤트 전이 | **부정 결과 확정** — 채택 0/8·T5 실패 | 계약평가 소모, 파킹 |
| **V13** | **변동성 사건 확률 (Brier)** — 9셀 | **진행 중**. champion = `persistence_pb` 전 9셀(EWMA 증분 0/9·HAR 증분 0/9). T3 라이브 카드 배포. 홀드아웃 **미소모** | 개발 평가 **3/8**, 홀드아웃 **0/3** |

### 2.2 라이브 표면 상태

| 표면 | 상태 | 실측 |
|---|---|---|
| **V13 변동성 카드** | `t3_live_card` | `publication.display_tier: t3_live_card`(V13-D5, 2026-09-08). `holdout_status: not_consumed`. caveat "홀드아웃 미검증" 굵게 강제(`t3_without_holdout_requires_bold_caveat: true`). `vol_live.jsonl` **2행이나 고유 원점은 1개(2026-09-04)**. 성숙 원점 **0** — h5 첫 성숙은 2026-09-11경. |
| **V8 섀도 카드** | `shadow_operational_hold` | `shadow_forecasts.jsonl` 2행 · `shadow_resolutions.jsonl` 2행(h1·h5만 성숙). 승격까지 `minimum_shadow_sessions: 126`. |

**V8 섀도 정체의 원인 (실측 확정)**: 원점은 필수 계열의 **공통 마지막 날짜**로 결정되는데, `DTWEXBGS`가 **2026-08-28에서 정지**(2026-09-09 기준 12일째)한 반면 VIX·NASDAQCOM·DGS2·DGS10은 2026-09-04까지 들어와 있다. 그래서 원점이 2026-08-28(ISO W35)에 고정된다. `tools/ops_status.py`가 적용하는 DTWEXBGS 주간 공표 허용치는 **216시간(9일)** — 12일은 그 허용치를 넘었다. V2 refresh 워크플로 자체는 **성공으로 종료**하므로 워크플로 상태만 보면 이상이 보이지 않는다. 이것이 §3의 **P1b**를 독립 단계로 둔 이유다.

### 2.3 비가역 자원 대장

| 자원 | 총량 | 소모 | 잔여 | 소모 조건 |
|---|---|---|---|---|
| V13 홀드아웃 슬롯 (2015-01-01~2018-12-31) | 3 | 0 | **3** | 사용자 원문 승인(V13-D3) + `execution_path` 개정 커밋 |
| 봉인창 공개 (2019-01-01~) | 모델 버전당 1 | V8에서 1 소모 | **신규 버전에서만 1** | 사용자 승인 + 신규 모델 버전 |
| V13 개발 평가 예산 | 8 | 3 (rung-1 EWMA · rung-2 HAR · rung-3 PB) | **5** | 계약 `evaluations_spent` 증가로 기록 |
| V10 홀드아웃 슬롯 | 3 | 0 | 3 (동결 트랙) | — |

### 2.4 누적 채굴 검정수 — **단위 혼재 경보**

외부 초안은 "설계창 2007–14 누적 채굴 **122검정**"을 신규 계약 헤더에 기재하라고 했다. 실측 결과 **저장소 어디에도 `122`라는 값은 존재하지 않는다**(외부 집계). 그 122는 다음 합인데, **단위가 섞여 있다**:

| 트랙 | 값 | 단위 |
|---|---|---|
| V8 | 12 | 계약 평가 |
| V9 | 7 | 계약 평가 |
| V10 | 12 | 계약 평가 |
| V11 | 48 | **셀 검정** (8 프록시 × 2 지평 × 3 지표) |
| V12 | 16 | **방향 검정** (셀 단위로는 8) |
| V13 | 27 | **rung × 셀** (방향 단위로는 54) |
| 합 | **122** | 혼재 |

단위를 일관되게 맞추면: 셀 단위 하한 **114**(V12=8·V13=27), 방향 단위 상한 **149**(V12=16·V13=54). 따라서 신규 계약 헤더에는 다음처럼 **단위를 명시**해 적는다.

```yaml
campaign_prior_tests:
  value: 122
  unit: mixed_units_documented       # 단일 단위 아님 — 아래 분해 참조
  breakdown: {v8: 12, v9: 7, v10: 12, v11: 48, v12: 16, v13: 27}
  unit_notes: {v11: cell_tests, v12: direction_tests_cells_would_be_8, v13: rung_times_cell_directions_would_be_54}
  consistent_range: [114, 149]
  source: external_aggregate_2026_09_09   # 저장소에 이 값을 담은 파일은 없다
```

---

## 3. 단계 P0~P7

### 3.0 의존 그래프

| 단계 | 선행 (반드시 끝나야 함) | 병렬 가능 | 차단하는 후속 |
|---|---|---|---|
| **P0** 판정 기계 건전성·에피소드 가드 | 없음 | P1b | P2·P4 (전부) |
| **P1** 라이브 전진 채점 | P0 (셀 자격) | P1b·P4 | C1 |
| **P1b** V8 정지 진단 | 없음 | P0·P1·P4 | V8 C1 |
| **P2** 홀드아웃 1회 소모 | **P0** + V13-D3 승인 | — | P3·C2 |
| **P3** 결과 처리·배선 | P2 + V13-D6 승인 | — | C3 |
| **P4** 봉인 아카이브 내 신규 피처블록 | P0 | P1·P1b | (P2 finalist를 바꿀 수 있음 — §3.3 주의) |
| **P5** 외부 정보집합 | 라이선스 해소 + 적재 + P4 결과 | — | — |
| **P6** 전진 축적·강등 | P1 | — | C1 확정 |
| **P7** 신규 버전 봉인·P3 게이트 | P2 + P6 + **C5(외부)** | — | T4 (구조 차단 유지) |

```
P0 ──┬─→ P1 ──→ P6 ──┐
     │                 ├─→ P7 (C5 종속)
     ├─→ P4 ─ ─ ─ ─ ─ ┤
     │                 │
     └─→ P2 ──→ P3 ────┘
P1b ─(독립)─→ V8 C1
P5 ─(라이선스·적재 선행, P4 결과 조건부)
```

---

### P0 · 판정 기계 건전성과 에피소드 가드

| 항목 | 내용 |
|---|---|
| **목적** | 어떤 셀이 **판정 가능한가**를 결과 보기 전에 확정한다. 이 단계가 없으면 이후 모든 통과·실패가 해석 불가. |
| **진입 게이트** | 없음 (즉시 착수 가능, 새 데이터·비용 0) |
| **작업** | ① 부록 A 표를 계약에 사전등록 커밋 ② 에피소드 가드 임계를 **결과 전** 고정 ③ 셀별 MDE = 1.645·bootstrap_se 인쇄 ④ 건전 y-block(ℓ=13) 귀무 통과율 재확인 |
| **종료 게이트** | `outputs/timeseries_v13/p0_guard_mde.json` 존재 ∧ 계약에 `prereg.episode_guard` 블록 존재 ∧ 가드 실패 셀이 `untestable_by_construction`로 라벨됨 |
| **산출물** | `outputs/timeseries_v13/p0_guard_mde.json` · 계약 amendment(결과 전 커밋) |
| **승인 지점** | 0 (사용자 승인 불필요 — 강화만 하고 완화 0) |
| **예산·기간** | 개발 평가 **0회** 소모(기존 원장 재분석만·새 창 0) · 1주 · $0 |
| **정지 규칙** | 귀무 통과율 > 0.10인 셀 발견 시 그 셀 **전면 제외**. 사후 임계 조정 금지. |
| **부정 종료 확률** | 해당 없음 — P0은 판정 다리가 아니라 전제다. 다만 **가드 실패 셀이 다수 나올 사전확률은 높다**(아래). |

**핵심 발견 — 외부안의 퇴화 가드는 틀렸다.** 외부안은 `min_events_per_halfwindow: 20 ∧ min_nonevents_per_halfwindow: 20`을 제안했다. 실측: **9/9 셀 전부 통과**하며 최소값은 27(rv_h63 전반창 비사건)이다. 무해해 보인다. 그러나 이 가드는 **관측을 독립 표본으로 세는 오류**를 범한다. 이 셀들의 라벨은 지평 h만큼 중첩되고, 사건은 시장 국면(regime)에 뭉친다. 올바른 세기는 **연속 에피소드(contiguous run) 수**다.

| 극단 사례 (실측) | 관측 수 | 에피소드 수 | 실질 |
|---|---|---|---|
| vix30_h21 후반창 **사건** | 109 | **1** (2011-07-06 ~ 2011-12-07) | 2011년 유로존 위기 **단일 국면**. n=109가 아니라 사실상 n=1 |
| vix30_h63 후반창 **사건** | 151 | **1** (2011-05-05 ~ 2011-12-07) | 동일 국면 |
| vix30_h5 후반창 **사건** | 91 | **2** (2011-07-28~11-28 n=86, 12-01~12-07 n=5) | 같은 2011 국면의 두 조각 |
| rv_h63 전반창 **비사건** | 27 | **1** (2007-03-27 ~ 2007-05-03) | GFC 직전 한 달 |
| rv_h63 전반창 **사건** | 981 | **2** (57일 + **924일**: 2007-05-04~2010-12-31) | 사실상 상수 라벨 |

**가드 형(결과 전 고정)**: 반창(early/late) × 클래스(사건/비사건) 4칸 각각의 연속 에피소드 수 ≥ E_min.

| E_min | 통과 셀 | 실패 셀 |
|---|---|---|
| **≥5 (권장·사전등록)** | vix25_h5 · rv_h5 · rv_h21 (**3/9**) | vix25_h21 · vix25_h63 · vix30_h5 · vix30_h21 · vix30_h63 · rv_h63 |
| ≥3 (하한·"한계" 대역) | vix25_h5 · vix25_h21 · vix25_h63 · rv_h5 · rv_h21 (**5/9**) | vix30 3종 · rv_h63 |

> 실측 전수는 부록 A. **E_min은 P0에서 한 번 고르고 결과 후 절대 바꾸지 않는다.** 권고: `E_min = 5`를 판정 자격으로, `3 ≤ E < 5`를 **`▲ 국면 표본 얇음` 마커 부착 후 표시만 허용, 판정 다리 금지** 대역으로 사전등록.

**P0의 결과가 뒤바꾸는 것**: E_min=5를 채택하면 홀드아웃 finalist의 판정 자격 셀이 9 → 3으로 줄고, `family P(k≥k_obs)`의 family 크기가 바뀐다. **따라서 P0은 P2보다 반드시 먼저다.** 이 순서를 뒤집으면 홀드아웃 소모가 낭비된다.

---

### P1 · 라이브 전진 채점 (V13)

| 항목 | 내용 |
|---|---|
| **목적** | 설계창 밖, 봉인창 밖, **미래에서** 채점한다 — 정점 지식(peeking) 오염이 원리적으로 0인 유일한 표본. |
| **진입 게이트** | P0 종료(셀 자격 확정) ∧ 첫 원점 성숙(h5 기준 2026-09-11경) |
| **작업** | ① `live_forward_gate.execution_path`를 `absent_by_construction` → 명명 verb로 개정(사전등록 커밋) ② 채점 verb 구현 — 성숙 원점만, 미성숙 제외 ③ `vol_live_resolutions.jsonl` append |
| **종료 게이트** | 셀별 성숙 원점 ≥ **60**. 그 전에는 "표본 부족" 표시만, **판정 없음**. |
| **산출물** | `data/timeseries_v13/ledgers/vol_live_resolutions.jsonl` (append-only) — `forecasts/`·`calibration/` **무접촉** |
| **승인 지점** | 0 (규칙이 이미 2026-09-08 사전등록됨). 단 원점 케이던스 변경은 승인 필요. |
| **예산·기간** | $0 · **셀당 60 성숙 원점** — 일간 원점 기준 최소 60 거래일 + h. 현실적 6개월~1년 |
| **정지 규칙** | 강등 규칙 발동(기후 대비 쌍대 Brier 손실차 CI90 하한 ≤ 0) → 그 셀 표시 hold, **자동 재무장 없음**. 재개는 사용자 결정. |
| **부정 종료 확률** | **강등 발생 확률 40%** (셀 하나 이상, 60 원점 시점). 근거: champion이 `persistence_pb`(지속성)이고 라이브 구간이 저변동 국면이면 rv 셀 기저율이 설계창(GFC 지배)과 크게 어긋난다. 설계창 기후는 `rv h63 = 0.8751`인데 이는 명백히 2007-14 특유값이다. |

**현 실측**: `vol_live.jsonl` 2행이지만 고유 원점은 **1개(2026-09-04)**. 성숙 0. 즉 **C1은 0/60**이다.

---

### P1b · V8 섀도 정체 진단

| 항목 | 내용 |
|---|---|
| **목적** | V8 섀도 전진(126세션)이 **0에 가깝게 멈춘 이유**를 고치거나, 못 고치면 한계로 명문화한다. |
| **진입 게이트** | 없음 (독립·즉시) |
| **작업** | ① DTWEXBGS 정지 확인 — FRED 원본 공표 지연인가, 파이프라인 결함인가 ② 216시간 허용치 초과가 `ops_status.py`에 보고되는지 확인 ③ **필수 계열 집합에서 DTWEXBGS를 빼는 것은 계약 개정**이므로 별도 판단 |
| **종료 게이트** | 원인이 (a) FRED 공표 지연 → 대기·모니터 (b) 파이프라인 결함 → 수정 후 원점 전진 재개 (c) 계열 영구 중단 → 계약 개정 안건 상정 — 셋 중 하나로 **문서화** |
| **산출물** | `docs/KNOWN_LIMITS.md` 항목(§11) + 필요 시 이슈 |
| **승인 지점** | 계열 집합 변경 시 **사용자 승인 필수** (계약 좌표 변경 = `frozen_coordinates` 훼손 위험) |
| **예산·기간** | $0 · 1~3일 |
| **정지 규칙** | **케이던스로 우회하지 말 것** — 아래 참조 |
| **부정 종료 확률** | 30% — FRED 공표 지연이면 저절로 풀린다. 결함이면 수정 가능. 계열 영구 중단이 가장 나쁘고 가장 드물다. |

**핵심 발견 — 외부안의 "섀도 케이던스 레버"는 봉인을 깬다.** 외부안(§S7, REVIEW_VERDICTS Q2)은 "origin 케이던스를 격주→일간으로 바꾸면 126세션이 4.8년에서 ~6개월로 줄고, 이는 모델을 바꾸지 않는 계약 좌표"라고 주장했다. **둘 다 틀렸다.**

1. **좌표가 아니라 봉인 대상이다.** `evaluation.origin_frequency: weekly_last_completed_session`(V8 계약 L201)은 `frozen_coordinates()` 안에 있다(`src/ai_fc/timeseries_v8/contracts.py:122-136`). 실측 대사:
   - 현 `contract_hash` = `7c56ee4eaa5697823c71c504e524354a70d643d20b555de69120f11ac55f785b`
   - `daily`로 변경 시 = `4d301ae22a4f2951627f3026aa49d15ce3cc7fece162234142055dae9ab1fea8`
   - 추가로 ISO주 규칙은 `pipeline.py`(= `model_code_hash` 대상)에도 있으므로 **모델 코드 해시까지 움직인다**. "모델 무변경"이 아니다.
2. **단축되지도 않는다.** 승격 게이트는 `minimum_shadow_sessions: 126` — 단위가 **세션(session)**이지 origin이 아니다. 케이던스를 바꿔도 세션 수는 달력이 정한다.
3. **진짜 병목은 다른 데 있다.** §2.2 — DTWEXBGS 정지가 원점을 2026-08-28에 묶고 있다. 케이던스를 일간으로 바꿔도 **공통 마지막 날짜가 움직이지 않으면 원점은 하나뿐이다.**

> **결정**: V8 섀도 케이던스 변경은 **기각**. P1b(데이터 정지 해소)가 유일한 실질 레버다.

---

### P2 · 홀드아웃 1회 소모 (비가역)

| 항목 | 내용 |
|---|---|
| **목적** | 설계창에서 고른 champion이 **한 번도 안 본 창(2015-2018)**에서 살아남는지 단 1회 확인한다. |
| **진입 게이트** | **P0 종료**(셀 자격 확정) ∧ `gates.champion.finalist_id` 존재 ∧ `hold_condition` 미해당(전 셀 HOLD 아님) ∧ **사용자 원문 승인(V13-D3)** |
| **작업** | 사전등록 커밋 → 승인 원문 수신 → `approvals.jsonl` receipt → 계약 `execution_path` 개정 커밋 → **verb 1회 실행** → 결과 무관 `holdout_scorings.jsonl` append → DECISIONS 기록 |
| **종료 게이트** | 셀별 PASS = **G1 ∧ G2 ∧ G4**(G3 보고 의무). `publication.holdout_status`가 `pass`/`partial`/`fail` 중 하나로 확정 |
| **산출물** | `data/timeseries_v13/ledgers/holdout_scorings.jsonl` (PASS/FAIL 무관 append) |
| **승인 지점** | **1개 · 원문 필수** (§8 템플릿) |
| **예산·기간** | 홀드아웃 슬롯 **1/3 소모**(비가역) · 개발 평가 0 · 1~2주 · $0 |
| **정지 규칙** | `holdout_refit` 금지 — 동결 artifact만. 봉인창(2019+) 바이트 미열람(`sealed_bytes_in_holdout_panel` 금지). 자동화(cron·루프) 밖. |
| **부정 종료(FAIL) 확률** | **45%** [30, 60]. 근거: champion이 `persistence_pb`(당일 수준 단독)이므로 지속성이라는 물리는 강건하다 — G1(기후 대비)은 통과 개연성이 높다. 위험은 **기후 자체의 창 의존**이다. 설계창 기후는 GFC 지배(rv h63 = 0.8751)이고 2015-2018은 저변동 국면이라, 고정 기후값을 쓰는 G1이 오히려 **쉽게 통과할 수도**(champion이 낮은 확률을 내면 유리) 있다. G4(홀드아웃 y-block 귀무)가 실질 위험. |

**이미 사전등록된 홀드아웃 절차 (계약 `stopping_points.holdout`)** — 새로 설계할 것이 없다:

| 게이트 | 정의 | 판정 다리? |
|---|---|---|
| **G1** vs 기후 | 쌍대 Brier(clim − champ) CI90 하한 > 0 (엄격) | ✔ |
| **G2** PB 비열화 | 쌍대 Brier(PB − champ) CI90 **상단 ≥ 0** — "유의 열위 아님". champion=PB 셀은 **항등 통과** | ✔ |
| **G3** 신뢰도 보고 | Murphy(rel/res/unc) + 신뢰도 곡선(raw·iso) | ✘ (보고 의무) |
| **G4** 음성 대조 | 홀드아웃 y-block(ℓ=13) 순열, **모형 고정(재적합 없음)**, G1 통과율 ≤ 0.10 | ✔ |

`pass_rule`: 셀별 PASS = G1 ∧ G2 ∧ G4. `family P(k ≥ k_obs) ≤ 0.05` 병기.

**구현상 유일한 공백 (실측)**: `features.build_panel(observations, *, start, end=None)`이 `end` 절단을 지원하므로 2018-12-31 절단 패널은 만들 수 있고, 동결 artifact에 셀별 `baseline_pb`가 이미 있어 G2도 계산 가능하다. 그러나 **`compute_cells`는 마지막 행 전용**이라 **원점 벡터를 한꺼번에 채점하는 경로가 없다.** P2의 verb 구현은 이 하나를 채우는 일이다(모형·계수는 손대지 않는다).

**finalist 규칙 (결과 전 확정)**: 현행 계약은 `holdout_finalists_preregistered: [V13VOL_champion]` 하나만 등록돼 있고, `gates.champion.finalist_id = V13VOL_champion_aec80c65038b`(PB 전 9셀)이다. 외부 검토관이 제안한 "(a) 채택 셀 있으면 그것 / (b) 전부 측정된 영이면 PB" 분기는 **현 상태에서 이미 (b)로 확정**돼 있다 — 추가 등록은 결과 전 개정으로만 가능하다.

---

### P3 · 결과 처리·배선

| 항목 | 내용 |
|---|---|
| **목적** | 홀드아웃 결과를 표시에 **정직하게** 반영하고, PASS 셀만 EXIT 트리거 base rate로 배선한다. |
| **진입 게이트** | P2 종료 ∧ 사용자 승인(V13-D6) |
| **작업** | ① `publication.holdout_status`·`holdout_fail_cells` 기입 ② FAIL 셀은 숫자 대신 "홀드아웃 실패" 페일클로즈 ③ PASS 셀만 `physical_event` 공간에 **표시만** 배선 |
| **종료 게이트** | 배선된 질문에서 divergence 표시가 동작 ∧ 산술 결합 0 ∧ 자동 재예측 0 |
| **산출물** | 계약 amendment · 읽기모델 payload |
| **승인 지점** | **1개 (V13-D6)** |
| **예산·기간** | $0 · 1~2주 |
| **정지 규칙** | **앵커링 금지 (절대)**: `src/ai_fc/base_rates.py:1-7` — 질문별 매핑 확률은 LLM digest에 **절대** 주입 금지. 주입하면 divergence 트리거가 무력화된다. **시장내재확률만 예외.** |
| **부정 종료 확률** | 배선 대상 부족 확률 **높음** — 아래 |

**배선 가능 질문의 실측 재고**: `questions/registry.yaml` **43문항 중 9셀로 채점 가능한 것은 `vix-25-90d` 단 하나다.**

| 질문 | 배선 가능? | 이유 |
|---|---|---|
| `vix-25-90d` | **가능** | rolling-90d, "VIX 일간 종가 > 25.00이 1일 이상". V13 `vix25` 셀의 first-passage와 형이 일치. 단 지평 단위가 다르다(90 **달력일** vs h **영업일**) — X1 6항의 "지평 단위" 항목이 여기에 걸린다. |
| `nasdaq-corr10-augoct-2026` | **불가** | −10% 배리어는 V13 표적에 없다. 신설하려면 `prohibitions.post_hoc_target_addition: true`에 걸린다. **P7의 신규 트랙에서만 가능.** |
| 나머지 41문항 | 불가 | 표적 불일치 |

> **P3의 현실**: 배선의 실질 산출은 **질문 1개**다. 이것을 알고 P2에 홀드아웃을 태우는지, 모르고 태우는지가 다르다. C3의 정의는 "배선된 질문 수"가 아니라 "배선 경로가 정직하게 동작함"이므로 1개로도 C3는 충족된다.

---

### P4 · 봉인 아카이브 내 신규 피처블록 (기간스프레드·달러·EBP)

| 항목 | 내용 |
|---|---|
| **목적** | **새 데이터 적재 0·비용 0·라이선스 위험 0**으로 시험 가능한 마지막 정보집합을 소진한다. |
| **진입 게이트** | P0 종료 (판정 자격 셀 확정) |
| **작업** | 셀별 `logit[PB 피처 + β·F_k]` — 피처당 파라미터 1개 추가. F1 = 기간스프레드(DGS10 − DGS2), F2 = 달러(DTWEXBGS), F3 = EBP(FED_EBP) |
| **종료 게이트** | 양방향 쌍대 Brier(PB − 후보) CI90 하한 > 0 ∧ y-block ≤ 0.10 ∧ 다중비교 보정 통과 |
| **산출물** | `data/timeseries_v13/ledgers/vol_experiments.jsonl` append · `outputs/timeseries_v13/` |
| **승인 지점** | 0 (계약 예산 내) — 단 예산 소진 시 사용자 결정 |
| **예산·기간** | 개발 평가 **≤3회**(잔여 5 중) · 2~3주 · $0 |
| **정지 규칙** | 예산 소진 또는 전 셀 '측정된 영'. `post_hoc_target_addition` 금지 — 표적(K·θ·h)은 그대로. |
| **부정 종료 확률** | **75%** [60, 88] |

**왜 이것이 "미시험 조합"인가 (중요)**: V9가 이 세 계열을 이미 시험했다는 반론이 나올 수 있다. 실측상 V9의 표적은 **가격 분포(CRPS)**였고, 여기의 표적은 **변동성 사건(Brier)**이다. 손실함수와 표적이 모두 다르므로 **미시험 조합이 맞다.** 다만 이 논리가 부정 확률을 낮추지는 않는다 — V9의 무효익은 "이 계열들이 NASDAQ 예측에 증분 정보를 거의 안 준다"는 약한 사전확률을 제공한다.

**보유 계열 실측** (봉인 V2 아카이브, 적재 불필요):

| 계열 | 행 수 | 기간 | P4 사용 |
|---|---|---|---|
| VIX | 9,266 | 1990-01-02 ~ 2026-09-04 | 표적·PB 피처 |
| NASDAQCOM | 7,973 | ~ 2026-09-04 | 표적(rv) |
| DGS2 | 9,176 | ~ 2026-09-04 | **F1 기간스프레드** |
| DGS10 | 9,176 | ~ 2026-09-04 | **F1 기간스프레드** |
| DTWEXBGS | 5,179 | ~ **2026-08-28 정지** | **F2 달러** (설계창은 온전) |
| DTWEXB | 6,328 | ~ 2019-12-31 **종료** | 설계창 전용 대체 |
| FED_EBP | 643 | ~ 2026-07-01 | **F3 EBP** (월간·저빈도 caveat) |

---

### P5 · 외부 정보집합 (옵션·일중) — 라이선스·적재 선행

| 항목 | 내용 |
|---|---|
| **목적** | 저장소가 **보유하지 않은** 정보(IV 표면·풋콜·기간구조·일중)를 도입할지 결정한다. |
| **진입 게이트** | ① **CBOE 라이선스 3중 모순 해소**(§6) ② 적재 파이프라인 + PIT 등급 확정 ③ **P4에서 채택 ≥1셀** (정당화 조건) |
| **작업** | 라이선스 회신 확보 → 적재 계약 작성 → 사전등록 → 시험 |
| **종료 게이트** | P4와 동일 형 |
| **산출물** | 신규 계약 + 적재 영수증 |
| **승인 지점** | **구매 승인 1개** (§8) + 라이선스 회신 기록 |
| **예산·기간** | $300 ~ 수천 · 4~8주 |
| **정지 규칙** | **회신 전 표시 금지.** 라이선스 등급이 미확정인 데이터는 T0(내부)에서도 파생 산출물을 공개 payload에 싣지 않는다. |
| **부정 종료 확률** | **72%** [55, 88] — 착수 자체가 P4 조건부이므로 실효 확률은 더 낮다. |

**핵심 발견 — 외부안의 "옵션 형상 즉시 착수"는 불가능하다.** 외부안(§S3-a)은 "보유 CBOE CSV{VVIX, SKEW, VIX3M, VIX9D}로 3~5일 내 착수, 비용 $0, 승인 0"을 제시했다. 실측:

| 계열 | 행 수 | 기간 | 위치 | 문제 |
|---|---|---|---|---|
| VVIX | 5,087 | 2006-03-06 ~ 2026-08-20 | **V4 연구 스토어**(`data/timeseries_v4/ledgers/observations.jsonl`) | **봉인 V2 아카이브에 없음** |
| SKEW | 9,210 | — | V4 연구 스토어 | 동일 |
| VIX3M | 4,256 | — | V4 연구 스토어 | 동일 |
| VIX9D | 3,930 | — | V4 연구 스토어 | 동일 |

1. **V13은 V2를 read-only 상속**하며 계약이 `no_write_to_sealed: true`. V4 스토어의 계열을 V13 패널에 넣으려면 **데이터 정책 변경 = 계약 개정**이다. "3~5일·승인 0"이 아니다.
2. **PIT 등급이 낮다.** 이 계열들의 PIT 등급은 `reconstructed_market_archive`이지 native vintage가 아니다. 홀드아웃·라이브 채점의 PIT 요건(`available_at <= origin`)을 만족한다는 증명이 별도로 필요하다.
3. **라이선스가 3중 모순이다** — §6.

---

### P6 · 전진 축적과 강등 규칙

| 항목 | 내용 |
|---|---|
| **목적** | 시간이 지나며 C1을 채우고, 채워지는 동안 **표시가 거짓말하지 않게** 유지한다. |
| **진입 게이트** | P1 채점 verb 가동 |
| **작업** | 성숙 원점 누적 · 셀별 쌍대 손실차 감시 · 강등 발동 시 표시 hold |
| **종료 게이트** | 셀당 성숙 원점 ≥ 60 → C1 충족 |
| **산출물** | `vol_live_resolutions.jsonl` 누적 |
| **승인 지점** | 강등된 셀의 **재무장은 사용자 결정** (자동 재무장 없음) |
| **예산·기간** | $0 · 6개월 ~ 1년 |
| **정지 규칙** | 강등은 자동, 재개는 수동 — 이 비대칭은 사전등록됐고 뒤집지 않는다. |
| **부정 종료 확률** | 해당 없음 (축적 단계) |

---

### P7 · 신규 버전 봉인·P3 게이트

| 항목 | 내용 |
|---|---|
| **목적** | 봉인창(2019+) 공개 1회를 신규 모델 버전에서 소모하고, CLAUDE.md P3 게이트를 마주한다. |
| **진입 게이트** | C2 확정 ∧ C1 충족 ∧ **C5(LLM 원장 50문항+·Brier < 0.18)** — C5는 **프로그램 외부** |
| **작업** | 신규 버전 사전등록 → 봉인 공개 1회 → P3 판정 |
| **종료 게이트** | 봉인 결과 원장 append (PASS/FAIL 무관) |
| **산출물** | 신규 계약 + 봉인 원장 |
| **승인 지점** | **봉인 소모 승인 1개 (원문 필수)** |
| **예산·기간** | C5 종속 — 수개월 ~ 수년 |
| **정지 규칙** | V8은 `maximum_disclosures_per_model_version: 1`을 이미 소진했다. **새 모델 버전에서만** 가능. T4는 `display_tiers_allowed`에 값 자체가 없어 구조적으로 차단 — 이 차단을 푸는 것은 이 프로그램의 권한 밖. |
| **부정 종료 확률** | C5 미달로 **무기한 대기할 확률 70%** — 이것이 §1.3의 오독 방지가 필요한 이유. |

---

### 3.9 전 단계 공통 정지 규칙

| # | 규칙 |
|---|---|
| ① | 건전 y-block 귀무 통과율 > 0.10인 셀 **즉시 제외** — 사후 조정 없음 |
| ② | 에피소드 가드 실패 셀은 `untestable_by_construction` — 판정 다리에서 제외 |
| ③ | 개발 평가 예산 소진 또는 stop-loss 도달 |
| ④ | **결과 후** 손실함수·기준선·문턱·가설·귀무 변경 **시도 자체가 위반** → 즉시 중단·기록 |
| ⑤ | 봉인 해시 변화 또는 원장 수정 감지 → 즉시 중단 |
| ⑥ | 홀드아웃·봉인 verb의 `absent_by_construction` 상태 유지 — 승인 전 구현 금지 |
| ⑦ | **'측정된 영'은 정상 종료** — 단 MDE를 결과 전 공표한 경우에만(§10) |
| ⑧ | 원점 케이던스·계열 집합 등 `frozen_coordinates` 항목 변경은 **봉인 훼손** — 승인 없이 금지 |

### 3.10 단계별 첫 명령·산출물 경로 요약

각 단계에 착수할 때 **가장 먼저 실행할 것**과 **결과가 떨어질 경로**. 경로가 없으면 그 단계는 미착수다(§9.3의 판정 근거와 같은 파일).

| 단계 | 첫 명령 (또는 첫 행동) | 산출물 경로 |
|---|---|---|
| **P0** | 부록 A 표를 계약 `prereg.episode_guard`로 커밋 → 셀별 MDE 인쇄 스크립트 실행 | `outputs/timeseries_v13/p0_guard_mde.json` |
| **P1** | 계약 `live_forward_gate.execution_path` 개정 커밋 → 채점 verb 구현 | `data/timeseries_v13/ledgers/vol_live_resolutions.jsonl` |
| **P1b** | `python tools/ops_status.py` → V2 아카이브 DTWEXBGS 최종 관측일 대조 | `docs/KNOWN_LIMITS.md` 항목 |
| **P2** | 사용자에게 §8.2 V13-D3 원문 요청 → **대기** | `data/timeseries_v13/ledgers/holdout_scorings.jsonl` |
| **P3** | 계약 `publication.holdout_status`·`holdout_fail_cells` 기입 → §8.2 V13-D6 요청 | 읽기모델 payload · 계약 amendment |
| **P4** | 신규 피처블록 사전등록 커밋(F1·F2·F3) → 셀별 적합 | `data/timeseries_v13/ledgers/vol_experiments.jsonl` |
| **P5** | §8.2 CBOE-1 원문 요청 → 회신 대기 | `docs/generated/licenses.generated.md` CBOE 행 |
| **P6** | (자동 누적 — 명령 없음) 주기적 `roadmap_status.py` 확인 | `vol_live_resolutions.jsonl` 누적 |
| **P7** | 신규 버전 계약 draft → §8.2 SEAL-1 요청 | 신규 계약 + 봉인 원장 |

### 3.11 단계 착수 전 3문 점검

착수 직전 다음 세 질문에 **전부 답할 수 있어야** 한다. 하나라도 못 답하면 아직 사전등록이 덜 된 것이다.

| # | 질문 | 못 답할 때의 위험 |
|---|---|---|
| 1 | **무엇이 이 단계를 실패로 만드는가?** (구체적 수치·조건) | 실패 조건이 없으면 어떤 결과든 성공으로 서술하게 된다 |
| 2 | **검출 가능한 최소 효과(MDE)는 얼마이고 어디에 인쇄했는가?** | MDE 없이 null이 나오면 '측정된 영'을 주장할 수 없다(§10.1) |
| 3 | **이 단계가 소모하는 비가역 자원은 무엇인가?** (홀드아웃 슬롯·봉인·예산·비용) | 자원을 모르고 쓰면 되돌릴 수 없다 |

---

## 4. 신규 트랙 계약 골격

아래는 복사해 쓰는 스켈레톤이다. 외부안 §0을 참고하되 **실측 검증 결과 5건을 반영해 고쳤다**(변경점은 주석 `# [정정]`).

```yaml
schema_version: 1
contract_id: <track_id>                      # 예: timeseries_v14_shape
model_id: event_probability.<domain>_v14
model_version: 14
track: <volatility_event_probability|path_event|...>
status: draft_prereg                         # 결과 전 커밋에서만 이 값
drafted: 'YYYY-MM-DD'
supersedes: none

lineage:
  parent: timeseries_v13_vol
  parent_untouched: true
  campaign_prior_tests:                      # [정정] 스칼라 122 금지 — 단위 명시 필수
    value: 122
    unit: mixed_units_documented
    breakdown: {v8: 12, v9: 7, v10: 12, v11: 48, v12: 16, v13: 27}
    unit_notes: {v11: cell_tests, v12: direction_tests, v13: rung_times_cell}
    consistent_range: [114, 149]
    source: external_aggregate_2026_09_09    # 저장소 내 원천 없음

data_policy:
  source: ai_fc.timeseries_v2.market_archive.read_market_observations
  series: [VIX, NASDAQCOM, ...]
  pit:
    rule: available_at <= origin (captured_forward)
    vintage_grade: <native_vintage|reconstructed_market_archive>   # [정정] 등급 명시 의무
  license:
    research: <ok|pending>
    display: <ok|forbidden|pending_written_reply>                  # [정정] pending 이면 T0 포함 공개 payload 금지
    evidence_path: docs/generated/licenses.generated.md            # 행이 없으면 pending 으로 취급
  no_write_to_sealed: true
  no_fred_key_in_loop: true

window:
  design: ['2007-01-01', '2014-12-31']
  split: {early: ['2007-01-01','2010-12-31'], late: ['2011-01-01','2014-12-31']}
  holdout: ['2015-01-01', '2018-12-31']
  sealed: ['2019-01-01', 'latest']
  # 재분할 금지 — V4~V8 역할 해시 승계

targets:                                     # 결과 보기 전 고정. 사후 추가 금지.
  <name>: {definition: ..., K: [...], horizons: [...]}

prereg:
  commit_before_results: required
  hypotheses: [...]                          # 셀×피처, 기대 부호·크기
  # [정정] 외부안의 min(사건,비사건) >= 20 은 무해하나 무의미 — 9/9 통과(최소 27).
  #        중첩 라벨·국면 뭉침 때문에 관측 수는 독립 표본이 아니다.
  episode_guard:
    unit: contiguous_run                     # 연속 에피소드 수
    scope: per_halfwindow_per_class          # early/late × 사건/비사건 = 4칸
    min_episodes: 5                          # 판정 자격
    marginal_band: [3, 4]                    # 표시만 허용 + '▲ 국면 표본 얇음' 마커, 판정 다리 금지
    below_marginal_action: untestable_by_construction
    measured_table: docs/design/mts_program_blueprint_v1_260909.md#부록-a
  power_plan:
    mde_per_cell: 1.645 * bootstrap_se
    printed_before_results: true             # 인쇄 없으면 '측정된 영' 주장 불가(§10)
  null:
    kind: y_block                            # 사건 라벨 블록 순열
    block_len: 13
    replicates: 1000
    pass_rate_max: 0.10
    p_permutation_forbidden: true            # T-A 누수 확인 — 영구 금지

baselines:
  - climatology
  - persistence_pb                           # 지속 계열 표적에는 필수 (champion_on_climatology_alone 금지)

gate:
  primary: 쌍대 손실차 CI90 하한 > 0 (엄격부등호)
  bidirectional_transfer: early<->late 두 방향 모두
  uncertainty:
    bootstrap: stationary_block              # [정정] 신규 구현 금지 — 승격된 공유 구현 1개만 import(§5)
    block_length: 13
    replicates: 2000
    seed: <int>
    interval: [5, 95]
  reliability: Murphy(rel/res/unc) + 신뢰도 곡선 보고 의무 (판정 다리 아님)
  multiplicity:
    method: family_p_binomial                # [정정] BH/Holm/Romano-Wolf 는 저장소에 없음 — 도입은 별도 작업(§5)
    family_definition: 판정 자격 셀 × 피처
    alpha: 0.05
  ladder_mcs: not_available                  # [정정] Model Confidence Set 미구현 — 사전등록에 쓰지 말 것

development_protocol:
  track_open: false                          # 사용자 승인으로만 true
  maximum_development_evaluations: <n>
  evaluations_spent: 0
  experiment_ledger: data/<track>/ledgers/<name>_experiments.jsonl
  ledger_append_only: true
  preregistered_before_results: true
  stop_loss: {after: <k>, min_gain: <x>}

stopping_points:
  holdout:
    window: ['2015-01-01', '2018-12-31']
    requires_explicit_user_approval: true
    execution_path: absent_by_construction   # 승인 후에만 named_verb_guarded 로 개정
    consumption: champion 당 1회
    gate: {G1_vs_climatology: ..., G2_not_inferior_to_pb: ..., G3_reliability_report: ..., G4_negative_control: ...}
    ledger_append: PASS/FAIL 무관
  sealed:
    window: ['2019-01-01', 'latest']
    requires_explicit_user_approval: true
    execution_path: absent_by_construction

irreversible:
  holdout_slots: 3
  sealed_disclosures_per_model_version: 1
  auto_execution_path: absent_by_construction
  user_approval_text_required: true

prohibitions:
  automatic_holdout_consumption: true
  automatic_sealed_disclosure: true
  gate_threshold_relaxation: true
  outer_window_reuse_after_results: true
  null_redesign_after_results: true
  post_hoc_target_addition: true
  p_permutation_null_as_negative_control: true
  champion_on_climatology_alone: true
  holdout_refit: true
  sealed_bytes_in_holdout_panel: true
  backtest_of_llm_questions: true
  mutate_v8_v2: true
  anchoring_mapped_probability_into_llm_digest: true    # [신설] base_rates.py:1-7 승계

publication:
  display_tier: t0_internal
  display_tiers_allowed: [t0_internal, t2_hidden_panel, t3_live_card]   # t4 값 자체가 없다
  reference_opinion_only: true
  holdout_status: not_consumed
  t3_without_holdout_requires_bold_caveat: true

artifacts:
  ledger: data/<track>/ledgers/
  results: outputs/<track>/
  review_pack: outputs/review-packs/
```

**외부안 §0에서 고친 것**: `degeneracy_guard`(관측 수 → 에피소드 수) · `multiplicity`(BH/Romano-Wolf → 실재하는 `family_p_binomial`) · `ladder_mcs`(존재하지 않음을 명시) · `campaign_prior_tests`(스칼라 → 단위 명시 구조) · `license`(단순 ok/pending → 증거 경로 + pending 시 전면 금지) · `pit`(vintage 등급 의무).

---

## 5. 판정 기계 표준

### 5.1 있는 것 / 없는 것 (실측)

| 도구 | 상태 | 경로 |
|---|---|---|
| Diebold-Mariano (HAC) | **있음** | `src/ai_fc/timeseries/backtest.py:123` — `diebold_mariano_hac` |
| Stationary bootstrap | **있음 — 5중 중복 구현** | v3 / v5 / v6 / v11 / v13 각각 |
| CRPS · pinball | **있음** (다수) | 트랙별 |
| Murphy 분해 | **있음 (SQLite 기반)** | `db/queries.py:203` — `murphy_decomposition` |
| reliability (배열 기반) | **있음** | `tools/v13_vol_rung2.py:36` |
| PAV isotonic | **있음** | `src/ai_fc/timeseries_v13/features.py` — `pav`/`pav_apply` |
| 순열 multiplicity | **있음** | `tools/v12_transfer_test.py:406` |
| `family_p_binomial` | **있음** | V12/V13 계약이 참조 |
| **BH / Holm / Bonferroni / Romano-Wolf** | **없음** | — |
| **Model Confidence Set (MCS)** | **없음** | — |
| **split conformal / CQR / ACI** | **없음** | — |
| **Platt scaling** | **없음** | — |

> **규율**: 사전등록 계약에 **없는 도구의 이름을 쓰지 않는다.** 외부안은 `multiplicity: {method: BH, alt: romano_wolf}`와 `ladder_mcs_alpha: 0.10`을 골격에 넣었으나 둘 다 미구현이다. 사전등록 시점에 구현이 없으면 그 사전등록은 실행 불가능한 약속이 되고, 결국 결과 후 대체(= 위반)로 이어진다.

### 5.2 단계별 도입 순서

| 단계 | 도입 | 비고 |
|---|---|---|
| **P0** | 에피소드 가드 · MDE 사전 인쇄 · 건전 y-block 귀무 | 전부 기존 도구로 가능 |
| **P2·P4** | `family_p_binomial`(있음) · DM-HAC 보조(있음) | BH/Romano-Wolf는 **필요해지면 그때 구현하고 다음 트랙부터 사전등록** |
| **P3·P6** | 신뢰도 대역 · Winkler | 구현 필요 |
| **P5** | 이산 모니터링 보정 · 중첩 기준선 | 구현 필요 |
| **P7** | Brier(P3 게이트) | 기존 |

### 5.3 stationary bootstrap 중복 문제

**5개 구현이 각자 존재한다**(v3·v5·v6·v11·v13). 서로 다른 시드 규약·블록 길이 처리·경계 처리를 가질 수 있고, 트랙 간 결과 비교를 원리적으로 불가능하게 만든다.

> **규칙**: **새 구현 추가 금지.** 하나를 공유 모듈로 **승격**하고 나머지는 그것을 import한다. 승격 대상은 V13 구현(`src/ai_fc/timeseries_v13/features.py`) — 가장 최근이고 동결 μ/σ 좌표 처리가 명시적이다(`logit_fit`의 `standardize` 인자 주석). 단 **승격은 기존 트랙의 산출 해시를 바꿀 수 있으므로**, 봉인·동결된 트랙(V8·V13 champion)의 코드 경로는 건드리지 않고 **신규 트랙만 공유 구현을 쓴다**.

### 5.4 금지 목록 (영구)

| # | 금지 | 근거 |
|---|---|---|
| 1 | **p-순열 귀무를 음성 대조로 사용** | T-A에서 누수 확인. 계약 `prohibitions.p_permutation_null_as_negative_control: true` |
| 2 | **결과 후 문턱·손실함수·기준선·귀무 교체** | 사전등록의 정의 그 자체 |
| 3 | **기후 단독 우월로 champion 선언** | 지속 계열 표적에는 PB 대비 판정 필수. `champion_on_climatology_alone: true` |
| 4 | **ML 게이트 전 가중 학습 결합** | 해소 200+ 전 금지. 고정 규칙(중앙값·불일치 지수)만 |
| 5 | **DL 가격 예측 학습** | CLAUDE.md 영구 금지 |
| 6 | **홀드아웃 재적합** | `holdout_refit: true` — 동결 artifact만 |
| 7 | **봉인 바이트를 홀드아웃 패널에 열람** | `sealed_bytes_in_holdout_panel: true` |
| 8 | **매핑 확률을 LLM digest에 주입** | `base_rates.py:1-7` — divergence 트리거 무력화. 시장내재확률만 예외 |
| 9 | **새 bootstrap 구현 추가** | §5.3 |
| 10 | **미구현 도구를 사전등록에 기재** | §5.1 |

### 5.5 도구를 언제 실제로 구현하는가

"BH가 없으니 도입하자"는 그 자체로는 근거가 아니다. 도구 도입도 예산을 쓰고 새 자유도를 만든다. 다음 조건을 **전부** 만족할 때만 구현한다.

| 조건 | 설명 |
|---|---|
| ① 현행 도구로 판정이 **실제로 막혔다** | `family_p_binomial`로 충분한데 BH를 넣는 것은 자유도 추가일 뿐 |
| ② 구현 후 **첫 사용이 사전등록 시점**이다 | 결과를 본 뒤 "더 나은 보정"으로 갈아타면 위반 |
| ③ 기존 트랙의 산출 해시를 **바꾸지 않는다** | 봉인·동결 트랙 코드 경로 무접촉(§5.3과 같은 규율) |
| ④ 단일 구현·단일 위치 | 중복 구현 금지 |

**현 시점 판단**: BH·Romano-Wolf·MCS 모두 ①을 만족하지 않는다. P0에서 판정 자격 셀이 9 → 3으로 줄면 family가 작아져 `family_p_binomial`로 충분해질 가능성이 오히려 높다. **P4 결과를 본 뒤 재검토**한다.

**ACI/CQR/split conformal**은 판정 도구가 아니라 **커버리지 인프라**다. 도입하더라도 게이트 다리로 쓰지 않는다(외부 검토관도 동의: "인프라 전용, 판정 트랙 금지").

---

## 6. 데이터·라이선스 등급과 구매 트리거

### 6.1 데이터 등급표

| 계열/데이터셋 | 위치 | 행 수 | PIT 등급 | 표시 권리 | 비용 | 사용 가능 단계 |
|---|---|---|---|---|---|---|
| VIX | **봉인 V2** | 9,266 | native vintage | 공식 | $0 | 전부 |
| NASDAQCOM | 봉인 V2 | 7,973 | native vintage | 공식 | $0 | 전부 |
| DGS2 / DGS10 | 봉인 V2 | 9,176 / 9,176 | native vintage | 공식 | $0 | **P4 (F1 기간스프레드)** |
| DTWEXBGS | 봉인 V2 | 5,179 (**2026-08-28 정지**) | native vintage | 공식 | $0 | **P4 (F2 달러)** |
| DTWEXB | 봉인 V2 | 6,328 (2019-12-31 종료) | native vintage | 공식 | $0 | 설계창 전용 대체 |
| FED_EBP | 봉인 V2 | 643 (2026-07-01) | native vintage | 공식 | $0 | **P4 (F3 EBP)** |
| VVIX | **V4 연구 스토어** | 5,087 (2006-03-06~2026-08-20) | `reconstructed_market_archive` | **모순 — §6.2** | $0 | **P5 (계약 개정 선행)** |
| SKEW | V4 연구 스토어 | 9,210 | `reconstructed_market_archive` | 모순 | $0 | P5 |
| VIX3M | V4 연구 스토어 | 4,256 | `reconstructed_market_archive` | 모순 | $0 | P5 |
| VIX9D | V4 연구 스토어 | 3,930 | `reconstructed_market_archive` | 모순 | $0 | P5 |
| **옵션 IV 표면 · 풋콜 · 기간구조** | **미보유 (0건)** | — | — | — | $500~ | P5 |
| **일중 (intraday)** | **미보유 — `data/intraday/` 디렉터리 없음** | — | — | — | ~$300 | P5 |

### 6.2 CBOE 라이선스 3중 모순 (해소 필수)

| 출처 | 라벨 |
|---|---|
| V4 receipts | `repository_raw_allowed` |
| V6 registry | `private_raw_derived_public` |
| **`docs/DECISIONS.md` 12-1** | **명시적 금지** — CBOE Terms of Use §2(Last Updated 2022-11-16)가 허용하는 것은 개인 비상업 목적의 1부 열람·인쇄·다운로드뿐이며, `display`·`publish`·`distribute`·`create a derivative work`·`store … in an electronic retrieval system`을 사전 서면 동의 없이 금지 목록에 열거. "Materials" 정의에 `databases`·`text` 포함. **비상업 면제 없음** |

추가 실측: **`docs/generated/licenses.generated.md`에 CBOE 행 자체가 없고, "Pending manual reviews"에만 등장한다.**

**해소 경로 (순서 고정)**:

| 순서 | 행동 | 상태 |
|---|---|---|
| 1 | CBOE 앞 서면 문의 발송 — 초안 2종 이미 존재: `docs/cboe_permission_request_draft.md`, `docs/design/v13_cboe_datashop_qqq_request_260907.md` | **미발송** (수신 영수증 0건) — **사용자 승인 필요** |
| 2 | 회신 수령 → `docs/generated/licenses.generated.md`에 CBOE 행 기입 (등급 확정) | 대기 |
| 3 | 등급이 `display 허용`이면 V4 계열의 P5 사용 가능. `금지`면 **연구 내부(T0)에서도 공개 payload 파생 금지** | 대기 |
| 4 | DataShop 구매는 P4 결과 조건부 + 별도 승인 | 대기 |

> **중간 규율**: 회신 전까지 **DECISIONS 12-1(가장 보수적 해석)이 유효**하다. 세 라벨이 충돌할 때는 가장 제한적인 것을 따른다.

### 6.3 구매를 정당화하는 선행 조건

| 구매 | 정당화 조건 (전부 충족) |
|---|---|
| CBOE DataShop QQQ 옵션 EOD (~$500) | ① CBOE 회신으로 표시 등급 확정 ② **P4에서 채택 ≥1셀** — 무료 정보집합이 소진됐음을 증명 ③ 사용자 구매 승인 원문 |
| FirstRate 일중 (~$300) | ① P4 결과 ② 경로 생성기 트랙 재개 결정 ③ 약관 원문 확인 `[미검증]` |
| TAQ · OptionMetrics | 보류 — 설계창 2007-14 IV 표면 공백 문제가 별도로 있음 |

> **역논리 명시**: P4에서 채택이 **0셀**이면 이는 구매 실패가 아니라 **성공한 정보다** — "봉인 아카이브 내 무료 정보는 소진됐고, 유료 정보의 기대가치도 함께 하향된다"는 결론. 구매를 정당화하려던 근거가 사라지므로 P5는 **보류**가 정답이다.

### 6.4 PIT 등급 정의

계약 `data_policy.pit.vintage_grade`에 쓰는 값. 등급이 낮을수록 "그 시점에 정말 알 수 있었는가"의 보증이 약하다.

| 등급 | 의미 | 홀드아웃·라이브 채점에 사용 가능? |
|---|---|---|
| `native_vintage` | 공표 시점의 값이 그대로 보존됨(ALFRED vintage 등). 개정 이력 추적 가능 | **가능** |
| `reconstructed_market_archive` | 현재 시점에 수집한 시계열을 과거로 재구성. 개정이 있었다면 반영되지 않음 | **조건부** — 해당 계열이 무개정(EOD 확정)임을 별도 증명해야 함 |
| `vendor_eod_archive` | 벤더가 일자 파일로 제공. 파일 자체가 PIT 증거 | 가능(영수증 필수) |
| `unknown` | 출처·개정 이력 불명 | **불가** |

**VIX·SKEW 등 CBOE 지수의 특수성**: 이들은 EOD 확정 후 개정이 없다는 것이 통례이므로 `reconstructed_market_archive`여도 실질 PIT 위험은 낮다. 다만 **"통례"는 증명이 아니다** — P5 착수 시 무개정 여부를 확인하고 그 확인 자체를 영수증으로 남긴다. 확인 전까지는 `[미검증]`.

---

## 7. 표시 사다리와 페일클로즈

### 7.1 사다리

| 단계 | 내용 | 진입 게이트 | V13 현재 |
|---|---|---|---|
| **T0** `t0_internal` | 내부 전용, **숫자 미표시** | 기본값 (페일클로즈 착지점) | — |
| **T2** `t2_hidden_panel` | 대시보드 숨김 패널(`?review=` 열람) | 게이트 무장 + G0 무손상 대사 + 승인 | 통과 (V13-D4) |
| **T3** `t3_live_card` | 라이브 카드 노출 | T2 + 게이트 두 지평 전부 통과 + **X1 해소(6항)** + "참고 의견" 상시 | **현재** (V13-D5) |
| ~~T4~~ | 실전 자금 결정 근거 | — | **값 자체가 없음** — `display_tiers_allowed`에 미등재. 구조 차단 |

> **주의**: 외부안은 "표시: **T1**(설계 판정서)만"이라고 썼으나 `DISPLAY_TIERS`(`contracts.py:26`)는 `("t0_internal", "t2_hidden_panel", "t3_live_card")`로 **T1 값이 존재하지 않는다**. 등가는 `t0_internal`이다.

### 7.2 이미 구현된 페일클로즈 가드

| 가드 | 구현 | 동작 |
|---|---|---|
| **네 게이트** | `read_model_contract.py` — "numbers visible before all four gates pass" | 네 게이트 전부 통과 전에는 숫자 미표시 |
| **계수 핀 3자 일치** | `contracts.py:90-117` `load_frozen_coefficients` | 파일 `sha256` · `content_hash` · `finalist_id` 셋 중 하나라도 어긋나면 raise |
| **거래일 신선도** | 계약 `live_display.freshness` | `nyse_trading_calendar`, `max_missing_sessions: 1` — 주말·연휴·화~토 refresh 정직 처리 |
| **홀드아웃 fail/partial** | `read_model_contract.py` — "numbers visible after holdout failure" | FAIL 셀은 숫자 대신 "홀드아웃 실패" |
| **계약 disarm** | `display_tier()` (`contracts.py:68-75`) | 계약 파일 부재 시 **t0로 페일클로즈**. 허용 목록 밖 값도 t0 |
| **비-dict 포인터** | `read_model_contract.py:380` `isinstance(v13, dict) and v13` | 포인터가 dict가 아니거나 비면 v13 검증 블록 자체를 건너뛰고 표시하지 않음 |
| **T3 caveat 강제** | `read_model_contract.validate` — "live card without holdout pass must bold the caveat" | `t3 ∧ holdout_status ≠ pass ⇒ holdout_caveat_bold` |
| **t0 숫자 금지** | "t0 tier must not carry numbers" | T0 payload에 셀 숫자 불가 |

### 7.3 X1 이름충돌 6항 (계약 `x1_name_collision_rule`)

동일 화면에 LLM 예측(`vix-25-90d`)과 수치 모델 확률(V13 `vix25` 셀)이 나란히 놓일 때 반드시 구분해야 하는 6항:

| # | 항목 | 규율 |
|---|---|---|
| 1 | **명칭** | 서로 다른 이름 — 같은 "VIX 25" 라벨 금지 |
| 2 | **출처 배지** | `[수치모델·지속성]` vs `[LLM 예측]` |
| 3 | **지평 단위** | V13은 **영업일** h, 질문은 **90 달력일** — 단위 병기 필수 |
| 4 | **caveat lead** | "홀드아웃 미검증" 굵게 상시(T3 ∧ not pass) |
| 5 | **역할 관계** | 수치 모델은 **base rate 참조**, LLM은 예측 — 상하 관계 명시 |
| 6 | **결합 금지** | 두 숫자의 산술 결합·평균 표시 금지 |

### 7.4 신규 추가 마커

**`▲ 국면 표본 얇음`** — P0의 에피소드 가드에서 `marginal_band [3,4]`에 든 셀에 부착한다.

| 속성 | 값 |
|---|---|
| 트리거 | 해당 셀의 반창×클래스 최소 에피소드 수가 3 또는 4 |
| 표시 | 셀 숫자 옆 `▲ 국면 표본 얇음` + 툴팁 "설계창에서 이 셀의 사건이 소수 국면에 집중돼 있어 표본 다양성이 낮습니다" |
| 판정 영향 | **판정 다리에서 제외** — 숫자는 보이되 게이트 통과 여부를 근거로 쓰지 않는다 |
| 기존 마커와의 관계 | `▲ 보정 약함`(h63, `reliability_markers: {h63: weak}`)과 **병존 가능** — 서로 다른 결함이다 |

### 7.5 표시 변경 시 회귀 점검 목록

표시 계층을 건드릴 때마다 아래를 전부 확인한다. 과거 사고는 대부분 이 목록의 한 줄을 건너뛴 데서 나왔다.

| # | 점검 | 실패 시 증상 |
|---|---|---|
| 1 | `read_model_contract.validate` 무오류 | payload가 조용히 거부되거나 잘못된 숫자가 노출 |
| 2 | 계약 `display_tier` 값이 `display_tiers_allowed` 안 | `display_tier()`가 t0로 페일클로즈 — 카드가 사라짐 |
| 3 | 계수 핀 3자 일치(`sha256`·`content_hash`·`finalist_id`) | `load_frozen_coefficients` raise |
| 4 | T3 ∧ `holdout_status ≠ pass` → caveat 굵게 | 검증 실패 |
| 5 | payload 크기 ≤ `payload_budget_bytes` (24,000) | 예산 초과 |
| 6 | X1 6항(§7.3) 전부 충족 — 특히 **지평 단위**(영업일 vs 달력일) | 사용자가 두 숫자를 같은 것으로 오독 |
| 7 | 패널이 hidden이거나 폭 0이면 rAF가 멈춰 **빈 스크린샷**이 나온다 | 검증 실패를 코드 결함으로 오진 |
| 8 | 브라우저 검수는 1400 / 620 / 375 세 폭에서, **탭 활성 상태**로 | V13-D4 선례 |

---

## 8. 승인 지점과 원문 템플릿

### 8.1 승인 지점 목록

| ID | 대상 | 비가역? | 언제 |
|---|---|---|---|
| **V13-D3** | 홀드아웃 1슬롯 소모 | **예** | P2 진입 |
| **V13-D6** | EXIT base rate 배선 | 아니오(되돌림 가능) | P3 |
| **CBOE-1** | CBOE 서면 문의 발송 | 아니오 | P5 선행 |
| **BUY-1** | DataShop 구매 | 예(비용) | P5, P4 조건부 |
| **SEAL-1** | 봉인창 공개 1회 | **예** | P7 |
| **COORD-1** | `frozen_coordinates` 항목 변경(계열 집합 등) | **예**(해시 변경) | P1b 결과에 따라 |

### 8.2 원문 템플릿 (사용자가 채팅에 그대로 입력)

```
V13-D3 홀드아웃 1회 소모 승인 finalist=V13VOL_champion_aec80c65038b
```

```
V13-D6 EXIT base rate 배선 승인 대상질문=vix-25-90d 표시전용
```

```
CBOE-1 CBOE 라이선스 문의 발송 승인 초안=docs/cboe_permission_request_draft.md
```

```
BUY-1 CBOE DataShop QQQ 옵션 EOD 구매 승인 상한=$<금액>
```

```
SEAL-1 봉인창 공개 1회 소모 승인 모델버전=<version> finalist=<id>
```

> **엄격 대조**: verb는 승인 원문에 **리터럴 결정 ID**와 **정확한 finalist_id**가 포함될 때만 실행된다. 부분 일치·의역·요약은 승인이 아니다. 계약 `stopping_points.holdout.procedure`가 이 대조를 규정한다.

### 8.3 승인 영수증 스키마 (`approvals.jsonl` 실측 필드)

```jsonc
{
  "receipt_id":        "v13-approval:<DECISION_ID>:<YYYY-MM-DD>:r<N>",
  "decision_id":       "V13-D3",
  "approved_at":       "<도구 호출 기록의 실제 타임스탬프>",
  "approver_role":     "user",
  "approval_text":     "<사용자 원문 그대로 — 요약 금지>",
  "approval_basis":    "<근거 문서 경로·절>",
  "approval_scope":    "<이 승인이 허용하는 정확한 범위>",
  "conditions":        ["<충족돼야 할 선행 조건>"],
  "semantic_reference":"<계약 내 필드 경로>",
  "source":            "<채팅|문서>",
  // 정정 영수증에만:
  "supersedes":        "<이전 receipt_id>",
  "consent_events":    [{"at": "<실제 시각>", "what": "<동의 내용>"}],
  "executed_at":       "<집행 시각>"
}
```

### 8.4 시각 규칙 (2026-09-08 사고 교훈)

> **`approved_at`·`executed_at`·`consent_events[].at`의 값은 도구 호출 기록에서만 가져온다. 추정·반올림·"대략 그 무렵"으로 쓰지 않는다.**

2026-09-08에 `v13-approval:V13-D4:2026-09-08:r1`의 `approved_at`(15:05)이 **합성 시각**이었고, `r2`가 이를 정정했다(실제 동의 14:14:41 계획 승인, 집행 14:54). V13-D5도 동일하게 r1 → r2 정정(실제 동의 13:53:55 선택 + 14:14:41 계획 승인, 집행 14:58:03).

| 규칙 | 내용 |
|---|---|
| 1 | 시각을 모르면 **영수증을 쓰지 않는다**. 빈 영수증이 틀린 영수증보다 낫다. |
| 2 | 합성 시각을 발견하면 **행을 수정하지 않는다**(append-only) — `supersedes`를 단 정정 영수증 `r<N+1>`을 추가한다. |
| 3 | `consent_events`는 동의의 **여러 계기**(선택 시각·계획 승인 시각)를 분리 기록한다. 하나로 뭉치면 정정이 불가능해진다. |
| 4 | `executed_at`은 `approved_at`보다 **뒤여야 한다**. 역전은 자동 검증으로 잡는다. |

---

## 9. 상태 파생 규약

### 9.1 원칙

> **상태를 손으로 관리하는 파일을 만들지 않는다.**

이 문서에는 "현재 단계: P1" 같은 줄이 **없다**. 그런 줄은 반드시 낡고, 낡은 상태 파일은 잘못된 다음 행동을 유도한다. **진실의 원천은 원장·계약·CI**이며, 그것을 읽어 현 단계를 **파생**한다.

### 9.2 `tools/roadmap_status.py` (구현 완료 2026-09-09)

`tools/ops_status.py` 패턴을 따른다: **1회 수동 실행 · 읽기 전용 · 스케줄 금지**.

```bash
PYTHONUTF8=1 python tools/roadmap_status.py
```

실제 출력(2026-09-09 실행):

```
단계    상태       이름
P0    완료       판정 기계 건전성·에피소드 가드
P1    완료       라이브 전진 채점
P1b   완료       V8 섀도 정지 진단
P2    미종료      홀드아웃 1회 소모
...
현 단계 : P2 (홀드아웃 1회 소모)
차단 요인: [P2] holdout_scorings.jsonl 행 0 — 미소모
          [P2] publication.holdout_status=not_consumed
          [P2] approvals 에 V13-D3 승인 영수증 부재
다음 승인: V13-D3 원문: 'V13-D3 홀드아웃 1회 소모 승인 finalist=<finalist_id>'
다음 명령: cd src && python -m ai_fc timeseries-v13-vol-holdout --approval-receipt <id>

자원 잔량: 개발 예산 3/8 · 홀드아웃 슬롯 0/3 · 라이브 원점 1 · 해상 0행
          표시 tier t3_live_card · 홀드아웃 not_consumed
```

### 9.3 단계별 기계 판독 조건 (도구가 실제로 검사하는 것)

각 행은 "어떤 파일의 어떤 필드가 무슨 값이면 그 단계가 끝났는가"다. **경로·필드명은 구현과 일치한다** —
문서와 코드가 갈라지면 코드가 정본이고, 이 표를 고쳐야 한다.

| 단계 | 종료 판정 조건 (AND) |
|---|---|
| **P0** | `data/timeseries_v13/vol/guard_mde_design.json` 존재 <br> ∧ 계약 `degeneracy_guard.rules.min_episodes_per_half_per_class` 존재 <br> ∧ 계약 `degeneracy_guard.design_window_result` 존재 <br> ∧ 계약이 선언한 `episode_failures` == 실측 `summary.episode_guard_failures` |
| **P1** | 계약 `live_forward_gate.execution_path != "absent_by_construction"` <br> ∧ 같은 블록 `verb` 기재 <br> ∧ `src/ai_fc/cli.py`에 `timeseries-v13-vol-resolve` 존재 |
| **P1b** | `docs/KNOWN_LIMITS.md`에 DTWEXBGS 항목 존재 ∧ `docs/review/V8_SHADOW_ORIGIN_STALL_20260909.md` 존재 |
| **P2** | `data/timeseries_v13/ledgers/holdout_scorings.jsonl` **행 수 ≥ 1** <br> ∧ 계약 `publication.holdout_status ∈ {pass, partial, fail}` <br> ∧ `approvals.jsonl`에 `decision_id == "V13-D3"` 행 존재 |
| **P3** | `approvals.jsonl`에 `decision_id == "V13-D6"` 행 존재 <br> ∧ `data/base_rates/volatility_v13_auto.md` 존재 <br> ∧ 계약 `publication.holdout_status ∈ {pass, partial}` |
| **P4** | `vol_experiments.jsonl` 행 수 ≥ 4 ∧ 계약 `development_protocol.evaluations_spent >= 4` |
| **P5** | `docs/generated/licenses.generated.md`의 **확정 표**(Pending 절 앞)에 CBOE 행 존재 |
| **P6** | `vol_live_resolutions.jsonl`에서 champion 셀별 성숙 원점 수 **min ≥ `minimum_matured_origins_per_cell`(60)** |
| **P7** | 신규 버전 계약 존재 ∧ 봉인 원장 행 ≥ 1 ∧ `approvals.jsonl`에 `SEAL-1` 행 (현재는 C5 종속으로 항상 미종료 보고) |
| **C1** | P6 조건 ∧ V8 `shadow_resolutions.jsonl` 성숙 세션 ≥ 126 — **단 V8 몫은 DTWEXBGS 발행 속도에 종속**(§P1b) |
| **C2** | P2 조건 (FAIL 도 충족) |
| **C4** | `read_model_contract.validate` 무오류 ∧ `episode_thin` 셀에 `▲ 국면 표본 얇음` 마커 부착 |

### 9.4 도구 규율

| 규칙 | 내용 |
|---|---|
| 읽기 전용 | `roadmap_status.py`는 어떤 파일도 쓰지 않는다. 판정만 인쇄한다. |
| 스케줄 금지 | cron·GitHub Actions에 넣지 않는다. 무인 자동화는 승인 없이 상태를 바꿀 위험이 있다. |
| 실패 시 침묵 금지 | 파일 부재·필드 부재는 "알 수 없음"이 아니라 **"미종료"**로 보고한다(페일클로즈). |
| `gh` 사용 | 워크플로 결론 조회는 `ops_status.py`와 같은 방식. GitHub cron 지연 수 시간은 정상이며 실패가 아니다. |

---

## 10. 부정 결과 처리 규약

### 10.1 '측정된 영'의 정의 (엄격)

> **'측정된 영'(measured zero) = MDE를 결과 전 공표했고, 관측된 효과 크기가 그 MDE 미만인 경우.** 이 경우에만 **정상 종료**다.

| 상황 | 판정 |
|---|---|
| MDE 공표 O, |Δ| < MDE | **'측정된 영' — 정상 종료.** "이 정보집합에서 이 크기 이상의 효과는 없다"는 **양의 지식**. |
| MDE 공표 O, |Δ| ≥ MDE 이나 CI90 하한 ≤ 0 | **미결(inconclusive)** — 종료 아님. 표본 부족이거나 잡음. |
| **MDE 공표 X**, 결과 null | **종료 아님.** 무엇을 검출할 수 있었는지 모르므로 "효과가 없다"고 말할 수 없다. |
| 결과 후 MDE 계산 | **위반.** 사후 MDE는 관측 분산에 의존하므로 자기충족적이다. |

### 10.2 동결·파킹 문서 양식

부정 결과로 종료한 트랙은 다음 형식으로 기록한다(V11·V12 선례 승계).

```markdown
# <트랙 ID> 동결 — <일자>

## 판정
<채택 0/N · '측정된 영' 또는 미결>

## 결과 전 공표된 MDE
| 셀 | MDE | 관측 abs(Δ) | 판정 |
|---|---|---|---|

## 소모 자원
개발 평가 <n>/<max> · 홀드아웃 0/3 · 봉인 0/1 · 비용 $<x>

## 무엇이 배제됐는가 (양의 지식)
<이 정보집합에서 MDE 이상의 효과가 없다는 진술>

## 무엇이 배제되지 않았는가
<더 큰 표본·다른 손실함수·다른 아키텍처에서는 열려 있는 것>

## 되돌리지 않는 것
<이 판정을 뒤집으려면 무엇이 필요한가 — 새 데이터? 새 창? 그 비용은?>
```

### 10.3 되돌리지 않는 원칙

| 규칙 | 내용 |
|---|---|
| 1 | 동결된 트랙의 결과를 **재해석해 살리지 않는다**. 다른 손실함수·다른 부분집합으로 재채점하는 것은 새 검정이며 새 예산을 쓴다. |
| 2 | 동결 판정을 뒤집으려면 **새 정보**(새 데이터·새 창·새 아키텍처)가 있어야 한다. 같은 데이터의 재분석은 채굴이다. |
| 3 | 부정 결과는 **캠페인 누적 채굴 수에 포함**된다(§2.4). 실패했다고 지우지 않는다. |
| 4 | 동결 문서는 `docs/design/`에 남기고 계약 `status`를 `frozen`으로 바꾼다. 계약 파일을 삭제하지 않는다. |
| 5 | V9·V10·V11·V12가 모두 이 형식으로 동결됐다. **효율적 시장 벽에 반복해 부딪히는 것은 프로그램의 실패가 아니라 프로그램이 정직하게 작동하는 증거다.** |

### 10.4 부정 결과의 가치 회계

동결된 트랙이 남긴 것을 명시적으로 세어 둔다. 이것을 안 세면 "네 트랙이 다 실패했으니 접자" 또는 반대로 "다섯 번째는 다를 거야"라는 두 오류에 빠진다.

| 트랙 | 배제한 가설 | 남긴 자산 | 소모한 비가역 자원 |
|---|---|---|---|
| V9 | 신용·유동성 exog가 **가격 분포(CRPS)** 에 증분을 준다 | exog 적재 경로 · ablation 하네스 | 0 (홀드아웃 미소모) |
| V10 | 아키텍처 변형(W3 γ)이 증분을 준다 | 6렌즈 적대적 검증 절차 — **위기원점 인공물 탐지법** | 0 (홀드아웃 기각으로 슬롯 보존) |
| V11 | 평시 상태신호 후보가 vol-직교·GFC-강건하면 표본외로 전이한다 | **값싼 직교 진단** — 포크 이전에 거르는 필터 | 0 (백테스트 창 0회) |
| V12 | 방향 이벤트가 전이한다 | 방향 검정 하네스 · 부정결과 계약 양식 | 계약 평가 |
| V13 (진행) | richer 변동성 측도(EWMA·HAR)가 **당일 수준**을 이긴다 | **지속성이 champion**이라는 실측 · 9셀 판정 기계 · 표시 계층 | 개발 평가 3/8 |

**읽는 법**: 네 번의 동결에서 **홀드아웃 슬롯 소모는 0**이다. 이는 게이트가 설계대로 작동했다는 뜻이다 — 약한 후보가 비가역 자원에 도달하기 전에 걸러졌다. V10의 "챔피언을 찾았으나 적대적 검증에서 인공물로 판정해 홀드아웃을 **기각**"이 이 프로그램에서 가장 값진 사건이다. 그때 슬롯을 태웠다면 지금 V13에 쓸 슬롯이 2개였을 것이다.

**다섯 번째가 다를 이유는 없다.** V13이 P4까지 가서도 채택 0이면 그것이 답이다 — "봉인 아카이브 내 정보로는 이 표적을 당일 수준 이상으로 예측할 수 없다"는 결론은 **완성된 프로그램의 정당한 산출물**이며(§1.2 C0~C4는 여전히 충족 가능), 실패가 아니다.

---

## 11. 한계 증분 (`docs/KNOWN_LIMITS.md` 추가 초안)

아래 5항을 `docs/KNOWN_LIMITS.md`에 추가한다. 배치: 1·2·3·4는 **A. 통계·방법론**, 5는 **B. 데이터** 또는 **C. 시스템·운영**.

| # | 항목 | 초안 |
|---|---|---|
| **1** | band80은 계수 불확실성 한정 | V13 라이브 카드의 80% 대역(`band80`)은 **델타법 + 블록 부트스트랩 공분산으로 계산한 계수 불확실성**이지 **보정 대역(calibration band)이 아니다**. 계약 `live_display.band80.meaning: coefficient_uncertainty_not_calibration`. 즉 "실제 확률이 이 구간에 들어갈 확률 80%"가 아니라 "같은 모형·같은 데이터생성과정을 반복 표집했을 때 추정 확률이 이 구간에 들 확률 80%"다. 사다리 json의 `se`는 **손실차 se**이며 P의 se가 아니므로 대역 계산에 쓰지 않는다. |
| **2** | 설계창 GFC 지배 | V13 설계창 2007-01-01~2014-12-31(2,014 거래일)의 전반창(2007-2010)은 절반이 금융위기다. 기후 기저율이 그만큼 높다(`rv_h63 = 0.8751`, `vix25_h63 = 0.6079`). 따라서 (a) 기후 대비 게이트는 **위기↔평온 전이 검정의 성격**을 갖고 (b) 이 기후값을 홀드아웃·라이브에 고정 적용하면 저변동 국면에서 기후가 과대평가돼 champion에게 유리하게 작동할 수 있다. V10~V12 공통 한계. |
| **3** | vix30 계열은 단일 국면에 의존 | 후반창(2011-2014)의 vix30 사건은 **2011년 유로존 위기 한 국면**이 사실상 전부다: `vix30_h21` 사건 109개 = **연속 에피소드 1개**(2011-07-06~2011-12-07), `vix30_h63` 사건 151개 = **에피소드 1개**(2011-05-05~2011-12-07), `vix30_h5` 사건 91개 = 에피소드 2개(같은 국면의 두 조각). 관측 수 기준 퇴화 가드(min ≥ 20)는 통과하나 **독립 표본으로는 n≈1**이다. 이 세 셀의 양방향 전이 판정은 "2011년 위기를 예측했는가"와 거의 동치다. |
| **4** | rv_h63 근퇴화 | 전반창(2007-2010)의 `rv_h63`은 비사건 27개가 **단일 구간**(2007-03-27~2007-05-03)이고, 사건 981개 중 924개가 **한 덩어리**(2007-05-04~2010-12-31)다. 즉 라벨이 사실상 상수다. 어떤 모형도 이 반창에서 유의미하게 판별할 것이 없으며, 통과·실패 모두 해석 불가. |
| **5** | DTWEXBGS 정지가 V8 전진을 막는다 | V8 섀도 원점은 필수 계열의 **공통 마지막 날짜**로 결정된다. 2026-09-09 기준 DTWEXBGS가 **2026-08-28에서 정지**(12일째, `tools/ops_status.py`의 216시간 허용치 초과)한 반면 VIX·NASDAQCOM·DGS2·DGS10은 2026-09-04까지 들어와 있어, 원점이 2026-08-28(ISO W35)에 고정됐다. 그 결과 `shadow_forecasts.jsonl` 2행·`shadow_resolutions.jsonl` 2행(h1·h5만 성숙)에 머물고 V8 카드가 `shadow_operational_hold`다. **V2 refresh 워크플로는 성공으로 종료하므로 워크플로 상태만으로는 이 정체가 보이지 않는다.** 승격 요건 `minimum_shadow_sessions: 126`은 세션 단위라 원점 케이던스 변경으로 단축되지 않으며, 케이던스 변경은 `frozen_coordinates`를 훼손해 `contract_hash`를 바꾼다. |

---

## 부록 A · 9셀 설계창 사건/비사건·에피소드 표

**산출 조건 (재현 가능)**: 봉인 V2 아카이브 `read_market_observations` → `build_panel(start='2007-01-01', end='2014-12-31')` → 패널 2,014행(2007-01-03 ~ 2014-12-31). 라벨은 `labels_vix(vix, K, h)` / `labels_rv(rv21, θ=0.1694, h)`, 미성숙 원점(NaN) 제외. 반창은 계약 `split`(early 2007-01-01~2010-12-31, late 2011-01-01~2014-12-31). "에피소드"는 같은 반창 내 같은 클래스의 **연속 거래일 run** 수.

| 셀 | 반창 | n | 사건 | 비사건 | min(사건,비사건) | 사건 에피소드 | 비사건 에피소드 | **min 에피소드** | 최장 사건 run |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| vix25_h5 | early | 1008 | 493 | 515 | 493 | 14 | 15 | **14** | 219 |
| vix25_h5 | late | 1001 | 125 | 876 | 125 | 5 | 6 | **5** | 102 |
| vix25_h21 | early | 1008 | 643 | 365 | 365 | 7 | 8 | **7** | 314 |
| vix25_h21 | late | 985 | 193 | 792 | 193 | 4 | 5 | **4** | 118 |
| vix25_h63 | early | 1008 | 848 | 160 | 160 | 3 | 3 | **3** | 608 |
| vix25_h63 | late | 943 | 338 | 605 | 338 | 4 | 3 | **3** | 160 |
| vix30_h5 | early | 1008 | 267 | 741 | 267 | 10 | 11 | **10** | 186 |
| vix30_h5 | late | 1001 | 91 | 910 | 91 | **2** | 3 | **2** | 86 |
| vix30_h21 | early | 1008 | 393 | 615 | 393 | 7 | 8 | **7** | 225 |
| vix30_h21 | late | 985 | 109 | 876 | 109 | **1** | 2 | **1** | 109 |
| vix30_h63 | early | 1008 | 643 | 365 | 365 | 4 | 5 | **4** | 267 |
| vix30_h63 | late | 943 | 151 | 792 | 151 | **1** | 2 | **1** | 151 |
| rv_h5 | early | 992 | 741 | 251 | 251 | 7 | 8 | **7** | 481 |
| rv_h5 | late | 1001 | 360 | 641 | 360 | 12 | 13 | **12** | 153 |
| rv_h21 | early | 1008 | 843 | 165 | 165 | 5 | 6 | **5** | 611 |
| rv_h21 | late | 985 | 494 | 491 | 491 | 8 | 9 | **8** | 175 |
| rv_h63 | early | 1008 | 981 | 27 | **27** | 2 | **1** | **1** | **924** |
| rv_h63 | late | 943 | 729 | 214 | 214 | 6 | 5 | **5** | 260 |

### A.1 관측 수 가드 vs 에피소드 가드

| 가드 | 통과 | 실패 |
|---|---|---|
| **외부안**: 반창별 min(사건, 비사건) ≥ 20 | **9/9 셀** (전 반창 최소 27) | 없음 |
| **에피소드 ≥ 5** (권장) | vix25_h5 · rv_h5 · rv_h21 → **3/9** | vix25_h21(late 4) · vix25_h63(early 3, late 3) · vix30_h5(late 2) · vix30_h21(late 1) · vix30_h63(late 1) · rv_h63(early 1) |
| **에피소드 ≥ 3** (한계 하한) | vix25_h5 · vix25_h21 · vix25_h63 · rv_h5 · rv_h21 → **5/9** | vix30_h5 · vix30_h21 · vix30_h63 · rv_h63 |

### A.2 단일 국면 에피소드의 날짜 (실측)

| 셀·반창·클래스 | 에피소드 |
|---|---|
| vix30_h21 · late · 사건 | (2011-07-06, 2011-12-07, n=109) — **1개** |
| vix30_h63 · late · 사건 | (2011-05-05, 2011-12-07, n=151) — **1개** |
| vix30_h5 · late · 사건 | (2011-07-28, 2011-11-28, n=86), (2011-12-01, 2011-12-07, n=5) — 2개, 같은 국면 |
| rv_h63 · early · 비사건 | (2007-03-27, 2007-05-03, n=27) — **1개** |
| rv_h63 · early · 사건 | (2007-01-03, 2007-03-26, n=57), (2007-05-04, 2010-12-31, **n=924**) — 2개 |

---

## 부록 B · 외부 검토관 안과의 차이표

| # | 외부안 주장 | 판정 | 근거 (실측) |
|---|---|---|---|
| 1 | 퇴화 가드 = 반창별 `min(사건,비사건) ≥ 20` | **수정** | 9/9 셀 전부 통과(최소 27)해 무해하지만 무의미. 중첩 라벨·국면 뭉침 때문에 관측 수는 독립 표본이 아니다. **에피소드 수**로 대체하면 ≥5에서 3/9만 통과. 부록 A. |
| 2 | S3-a "보유 CBOE CSV로 3~5일·$0·승인 0 즉시 착수" | **기각(연기)** | VVIX·SKEW·VIX3M·VIX9D는 **V4 연구 스토어에만** 있고 봉인 V2 아카이브에 없다. V13은 V2를 read-only 상속(`no_write_to_sealed: true`)이므로 **계약 개정**이 선행. PIT 등급도 `reconstructed_market_archive`. 라이선스 3중 모순 미해소. → **P5**로 이동. |
| 3 | S7 "V8 섀도 origin 격주→일간은 모델 무변경 계약 좌표, 126세션이 ~6개월로 단축" | **기각** | `origin_frequency`가 `frozen_coordinates()` 안(`contracts.py:122-136`). 해시 실측: `7c56ee4e…` → daily 시 `4d301ae2…`. ISO주 규칙은 `pipeline.py`(model_code_hash 대상)에도 있어 **모델 코드 해시도 변한다**. 게다가 `minimum_shadow_sessions: 126`은 **세션** 단위라 케이던스로 단축 불가. |
| 4 | V8 섀도 정체는 케이던스 문제 | **원인 정정** | 실제 원인은 **DTWEXBGS 2026-08-28 정지**(12일, 216h 허용치 초과). 원점이 필수 계열 공통 마지막 날짜라 W35에 고정. V2 refresh 워크플로는 **성공으로 종료**해 표면상 정상. → 신규 단계 **P1b**. |
| 5 | "캠페인 누적 채굴 **122검정**을 신규 계약 헤더에 기재" | **수정** | 저장소에 `122`라는 값은 **없다**(외부 집계). 12+7+12+48+16+27이며 단위가 혼재(V11 셀검정·V12 방향검정·V13 rung×셀). 단위를 맞추면 **114~149**. 단위 명시 구조로 기재. |
| 6 | 계약 골격 `multiplicity: {method: BH, alt: romano_wolf}` · `ladder_mcs_alpha: 0.10` | **수정** | BH/Holm/Bonferroni/Romano-Wolf·MCS **전부 저장소에 없다**. 실재하는 것은 `family_p_binomial`·`diebold_mariano_hac`·순열 multiplicity. 미구현 도구를 사전등록에 쓰면 결과 후 대체(= 위반)로 이어진다. |
| 7 | S3-a 표시 "T1(설계 판정서)만" | **수정** | `DISPLAY_TIERS`에 **T1 값이 없다** — `("t0_internal","t2_hidden_panel","t3_live_card")`. 등가는 `t0_internal`. |
| 8 | S4 finalist 규칙 (a) 채택 셀 / (b) 전부 측정된 영 → PB | **채택(이미 충족)** | 현 계약이 이미 (b) 상태다: `gates.champion.cells` 전 9셀 `persistence_pb`, `finalist_id = V13VOL_champion_aec80c65038b`, `hold_cells: []`. 추가 finalist 등록은 결과 전 개정으로만. |
| 9 | S3-0 신설 — 가드·MDE·귀무를 별도 태스크로 결과 전 커밋 | **채택** | **P0**으로 채택하고 강화: P0은 **P2보다 반드시 먼저**다(셀 자격이 family 크기와 finalist 판정 범위를 바꾸므로). |
| 10 | C0(판정 기계 건전성) 상시 조건 추가 | **채택** | §1.2 C0. 다만 근거로 든 p-순열 0.201은 이미 `prohibitions`로 봉인된 사건이므로, C0의 실질은 **에피소드 가드 + MDE 사전 공표**로 재정식. |
| 11 | C5(LLM 원장)는 프로그램 외부, T4 구조 차단 | **채택** | §1.3. `display_tiers_allowed`에 t4 값 부재로 실측 확인. |
| 12 | S5 배선 대상 "vix-25-90d · FOMC · 드로다운 EXIT" | **수정** | 실측: 43문항 중 9셀로 채점 가능한 것은 **`vix-25-90d` 단 하나**. `nasdaq-corr10-augoct-2026`(−10% 배리어)은 표적 신설이 필요해 `post_hoc_target_addition` 금지에 걸린다. |
| 13 | S6 구매는 S3-a 결과 조건부 | **채택·강화** | 조건에 **CBOE 라이선스 회신 확보**를 추가(DECISIONS 12-1이 display를 명시적 금지로 읽는다). 또한 P4(무료 정보집합) 소진을 선행 조건으로 추가. |
| 14 | 단계 순서 S3→S4→S5→S6→S7→S8 | **재배열** | P4(봉인 아카이브 내 무료 피처블록)를 **P5(유료) 앞**으로 명시 분리하고, P1b(V8 진단)를 독립 단계로 신설. 의존 그래프 §3.0. |
| 15 | 부정 종료 확률(S3-a 65% 등) | **일부 승계** | P4 75%·P2 45%·P5 72%로 재기술. 외부안의 S3-a/b/c/d는 데이터 가용성 실측 후 P4/P5로 재편됐으므로 1:1 대응하지 않는다. |
| 16 | 새 bootstrap·통계 구현 추가 | **금지 신설** | 실측 stationary bootstrap **5중 중복**(v3/v5/v6/v11/v13). "새 구현 추가 금지, 하나를 승격해 공유"를 §5.3 규칙으로 신설. |
| 17 | 앵커링 금지 | **신설(외부안에 없음)** | `src/ai_fc/base_rates.py:1-7` — 질문별 매핑 확률의 LLM digest 주입 절대 금지. 배선(P3)의 최대 위험이므로 계약 `prohibitions`에 항목 신설. |

---

## 부록 C · 다음 세션이 읽어야 할 파일 (경로만)

**헌법·정본**
- `CLAUDE.md`
- `docs/DECISIONS.md`
- `docs/KNOWN_LIMITS.md`
- `docs/ARCHITECTURE.md`
- `docs/design/system_design_v1.0.html`

**이 프로그램**
- `docs/design/mts_program_blueprint_v1_260909.md` (이 문서)

**V13 (현행 트랙)**
- `data/contracts/multivariate_timeseries_v13_vol.yaml`
- `src/ai_fc/timeseries_v13/contracts.py`
- `src/ai_fc/timeseries_v13/features.py`
- `src/ai_fc/timeseries_v13/pipeline.py`
- `src/ai_fc/timeseries_v13/freshness.py`
- `data/timeseries_v13/ledgers/vol_experiments.jsonl`
- `data/timeseries_v13/ledgers/vol_live.jsonl`
- `data/timeseries_v13/ledgers/approvals.jsonl`
- `data/timeseries_v13/vol/champion_coefficients.json`
- `data/timeseries_v13/vol/ladder_pb_baseline.json`
- `docs/design/v13_next_design_prereg_260907.md`
- `docs/design/v13_vol_live_card_display_design_260908.md`

**V8 (봉인·섀도)**
- `data/contracts/multivariate_timeseries_v8.yaml`
- `src/ai_fc/timeseries_v8/contracts.py`
- `src/ai_fc/timeseries_v8/pipeline.py`
- `tools/ops_status.py`

**표시·읽기모델**
- `src/ai_fc/read_model_contract.py`
- `data/contracts/display_promotion.yaml`
- `data/contracts/dashboard_payload.yaml`

**배선·앵커링**
- `questions/registry.yaml`
- `src/ai_fc/base_rates.py`

**라이선스**
- `docs/generated/licenses.generated.md`
- `docs/cboe_permission_request_draft.md`
- `docs/design/v13_cboe_datashop_qqq_request_260907.md`

**동결 트랙 (선례)**
- `docs/design/v11_orthogonal_calm_diagnostic_260903.md`
- `docs/design/v12_s3_verdict.md`
- `docs/design/v10_architecture_research_design_260902.md`

**도구**
- `tools/v13_vol_run.py`
- `tools/v13_vol_rung2.py`
- `tools/v13_vol_rung3_pb.py`
- `tools/v13_vol_freeze_coefficients.py`
- `src/ai_fc/timeseries/backtest.py`

**외부 검토 입력 (저장소 밖)**
- `C:/Users/91ssj/Downloads/ROADMAP_BLUEPRINT_v0.md`
- `C:/Users/91ssj/Downloads/REVIEW_VERDICTS.md`

---

*v1 끝. 다음 행동은 §9의 `roadmap_status.py`가 인쇄한다. 결과 전 커밋이 모든 단계의 첫 행동이다.*
