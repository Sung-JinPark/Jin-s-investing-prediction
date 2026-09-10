# V13 P5 사전등록 — 외부 정보집합(FRED 호스팅 옵션 변동성 지수) **rung-5E** (2026-09-10)

> **이 문서는 결과를 보기 전에 커밋되는 사전등록이다.** 커밋 이후 가설·블록 정의·지연·문턱·귀무·
> 기준선·셀 집합을 **한 글자도 바꾸지 않는다**. 결과를 본 뒤의 어떤 수정도 위반이며, 위반 시 이 rung 의
> 산출물은 폐기한다.
>
> 상위 계약: `data/contracts/multivariate_timeseries_v13_vol.yaml` (contract_id `timeseries_v13_vol`).
> 이 문서가 추가하는 것은 계약의 신규 키 `rung5e_external_vol_blocks` 하나뿐이며, 기존 키
> (`gate`·`gates`·`degeneracy_guard`·`stopping_points`·`prohibitions`·`rung4_macro_blocks`)는
> **1바이트도 수정하지 않는다**. §부록 A 가 이식용 YAML 원문이다.
>
> **이름**: 이 문서가 등록하는 rung 은 **rung-5E**(External)다. 병렬 세션의
> `docs/design/mts_p5_user_decision_options_260910.md` 가 같은 예산 1단위(4/8 → 5/8)를 쓰는
> 다른 후보 구성(무료 형상 변환 — 부호점프변동·반분산비·VRP)을 **rung-5** 로 부르고 있어
> 식별자 충돌을 피한다. 결정 ID 도 그 문서(V13-D7 구매 · V13-D8 표시 · V13-D9 경로)와 겹치지 않게
> **V13-D9 = 실행 전 경로 결정**, **V13-D10 = rung-5E 판정 기록**으로 쓴다.
>
> 지위: **참고 의견**. 이 트랙의 산출물은 EXIT 트리거 base rate 참조이지 매매 신호가 아니며,
> P3 게이트(해소 50문항+ · Brier < 0.18) 이전에는 어떤 값도 자금 결정의 단독 근거가 아니다.
> 결정론 수치 모델의 과거 적합이므로 CLAUDE.md 5원칙 예외(dualdb 스펙 §8) 범주이며,
> LLM 캘리브레이션 표본이 아니다.

---

## 0. 실행 전 차단 조건 (fail-closed) — **이 절이 미해소면 §1 이하는 실행되지 않는다**

### 0.0 이 문서는 **두 후보 구성 중 하나**다 — 예산 1단위를 두고 상호배타

같은 개발 평가 예산 1단위(4/8 → 5/8)를 두고 두 구성이 경합한다. 사용자 결정 **V13-D9** 가 어느 쪽을
집행할지 정한다.

| 구성 | 블록 | 라이선스 | 커버리지 | 문서 |
|---|---|---|---|---|
| **rung-5E** (이 문서) | G1 VXN 수준 · G2 VXN−VIX · G3 VXV−VIX | **미해소** (§0 B-1~B-4) | 2014/2014/1782 | 이 문서 |
| **rung-5** (형상 변환) | 부호점프변동 · 반분산비 · VRP log(VIX/RV21) | 노출 **0** (봉인 read-only 파생) | 2014 전부 완전균형 | `mts_p5_user_decision_options_260910.md` §5 |

- 병렬 세션의 결정 자료는 **C3 = rung-5(형상 변환) 우선**을 권고한다. 이 문서는 그 권고를
  **뒤집지 않는다** — 사용자가 **C2(FRED 경유 전환)** 를 고를 경우에 대비해, 그때 필요한 사전등록을
  결과 전에 미리 고정해 두는 것이 이 문서의 목적이다.
- **둘 다 실행하려면 예산 2단위(4/8 → 6/8)** 이며 별도 승인이 필요하다. 한 단위로 6블록 54검정을
  묶는 것은 rung-4 선례(3블록 27검정 = 1단위)를 넘어서므로 하지 않는다.
- 사용자가 C3 를 고르면 이 문서는 **집행되지 않은 사전등록**으로 남는다. 그 상태는 낭비가 아니라
  자산이다 — 나중에 옵션 갈래를 열 때 "결과를 보기 전에 고정된 설계"가 이미 존재한다.

### 0.1 취득 경로의 충돌 (실측)

이 rung 의 데이터는 이미 저장소에 적재돼 있다(커밋 `7b5fff08`,
`data/timeseries_v13/external/vol_indices.jsonl` 27,894행 · 영수증 10건). 그러나 **취득 경로가
저장소의 기존 결정 2건과 충돌한다.** 사전등록 문서가 이 충돌을 감추면 사전등록의 의미가 없으므로
차단 조건으로 명문화한다.

| # | 사실 (실측) | 충돌 대상 | 상태 |
|---|---|---|---|
| B-1 | 수집기 `tools/v13_fetch_external_vol.py`:44 의 URL 은 `https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}` | **DECISIONS 12-6**(2026-08-31): "`fredgraph.csv` 스크랩이 약관 위반임을 확인해 전환했다. FRED 자동 수집은 API 키를 쓰는 공식 API로만 한다. 스크랩 폴백은 두지 않는다." | **미해소** |
| B-2 | 대상 5계열(VXNCLS·VXVCLS·VXDCLS·OVXCLS·GVZCLS)은 전부 Cboe 소유 산출 지수 | **DECISIONS 12-5**(2026-08-31): CBOE→FRED 이전은 "더 나쁨" — CBOE 저작권이 따라오면서 **AI/ML 사용 금지 조항**과 store·cache 금지가 *추가*된다 | **미해소** |
| B-3 | `data/contracts/fred_market_signals.yaml` 의 `series_ids` = `[BAMLH0A0HYM2, DFII10, DTWEXBGS, WALCL, WTREGEN, RRPONTSYD, DGS10, BAMLC0A0CM, VIXCLS]` — **VXNCLS·VXVCLS 는 없다** | 같은 파일 `endpoint: https://api.stlouisfed.org/fred/series/observations` | **미해소** — 계약 범위 밖 |
| B-4 | `docs/generated/licenses.generated.md` 6행 확인일 **2026-08-01**, 17행 엔드포인트 `fredgraph.csv` | 12-5·12-6(둘 다 2026-08-31)보다 한 달 **앞선 stale 산출물**이며, 계약(`api.stlouisfed.org`)과 어긋난 registry drift | **정정 필요** |

수집기 docstring 과 영수증 10건의 `license` 필드가 근거로 든 것은 B-4 의 stale 대장 한 줄이다.
**그 한 줄은 12-5·12-6 에 의해 이미 갱신됐어야 하는 값이므로, 이 rung 의 라이선스 근거로 쓸 수 없다.**

### 차단 해제 조건 — 사용자 결정 **V13-D9** (승인 원문 없이는 실행 금지)

실행 전에 아래 세 가지가 **모두** 충족돼야 한다. 하나라도 미충족이면 러너는 데이터를 읽기 전에 거부한다
(`stopping_points.holdout` 의 named_verb_guarded 패턴 승계).

1. **경로 준수화** — 동일 5계열을 `api.stlouisfed.org/fred/series/observations`(키 경로, 12-6 준수)로
   **1회 재수집**하고, 기존 fredgraph 바이트와 값 대사한다. V13 계약 37행 `no_fred_key_in_loop: true`
   와는 충돌하지 않는다 — 이 수집은 **루프 밖 1회 백필**이며, 실험 루프는 적재된 원장만 읽는다.
   대사 결과는 영수증에 남기고, 불일치가 있으면 revision 으로 기록한다(값을 덮지 않는다).
2. **계약 범위 확장** — `fred_market_signals.yaml` 의 `series_ids` 에 `VXNCLS`·`VXVCLS` 를 추가하는
   개정(= 사용 범위 확장). 이는 V9-D6 과 동형의 **사용자 결정 사항**이며 자동으로 주어지지 않는다.
   동시에 `data/source_registry.yaml`(84행)·`licenses.generated.md` 의 registry drift 를 교정한다.
3. **미해결 사항 공시** — 12-5 가 든 FRED 의 AI/ML 사용 금지 조항과 store·cache 금지가 본 시스템의
   사용 형태를 포섭하는지는 **법률 검토 영역이며 미해결**이다(12-6 이 이미 KNOWN_LIMITS 대상으로 적었다).
   이 rung 을 실행한다면 `docs/KNOWN_LIMITS.md` 에 항목으로 남긴다.

**대안 경로(사용자 선택지 = V13-D9 의 C3)**: 위 3건을 밟지 않고 이 rung 을 **집행하지 않는 것**도
정당한 결론이다. 그 경우 P5 는 "라이선스 위치가 개선되지 않아 외부 정보집합을 열지 않음"으로 기록하고,
예산 1단위를 §0.0 의 **rung-5(형상 변환)** 에 쓴다 — 라이선스 노출 0·적재 0·커버리지 완전균형.
**이 문서는 그 선택을 대신하지 않으며, 그 선택을 권고에서 배제하지도 않는다.**

> 메일 발송은 이 문서의 범위가 아니다. 사용자가 2026-09-10 에 메일 발송 금지를 지시했으므로
> CBOE `permissions@cboe.com` 경로(12-5 가 제시한 §19(b) Delayed Open Website 라이선스)는 닫혀 있다.
> 판정서 §3 P7 의 "CBOE QQQ 회신 발송 완료"는 **사실이 아니다** — 저장소에 발송·수신 영수증이 0건이고,
> `outputs/handoff/CBOE_DATASHOP_QQQ_SEND_20260909.md` 머리말이 "사용자가 직접 보내는 것"이라 적는다.

---

## 1. 무엇을 시험하는가

### 1.1 질문 (한 문장)

> **옵션 시장이 매기는 전향적 변동성 정보(내재변동성 수준·나스닥 초과분·기간구조)를 champion
> `persistence_pb` 에 한 열 더했을 때, 9개 셀 각각에서 사건 확률의 Brier 가 양방향 전이에서 유의하게
> 개선되는가?**

### 1.2 표적 — **무변경** (`prohibitions.post_hoc_target_addition` 준수)

계약 `targets` 를 그대로 쓴다. K·θ·h 를 추가하지도 바꾸지도 않는다.

| 셀 | 표적 | 정의 |
|---|---|---|
| `vix25_h5` `vix25_h21` `vix25_h63` | vix_touch | P(VIX 종가 ≥ 25 를 h영업일 내 터치) |
| `vix30_h5` `vix30_h21` `vix30_h63` | vix_touch | P(VIX 종가 ≥ 30 를 h영업일 내 터치) |
| `rv_h5` `rv_h21` `rv_h63` | rv_exceedance | P(미래 RV21_ann > θ=0.1694 를 h영업일 내 초과) |

**9셀 전부를 시험한다.** 홀드아웃 결과(통과 셀 `vix25_h21`·`rv_h5`·`rv_h21`)로 셀을 고르지 않는다 —
홀드아웃 정보가 새 설계창 시험에 새면 남은 홀드아웃 슬롯 2개가 오염된다(rung-4 가 명문화한 규칙).

### 1.3 기준선 — champion `persistence_pb` (무변경)

- vix 셀: `PB = logit(절편 + β₁·z(VIX_t))`
- rv 셀: `PB = logit(절편 + β₁·z(RV21_t))`
- 후보: `logit(절편 + β₁·z(level_t) + β₂·z(x_t))` — 블록당 파라미터 **1개** 추가.
- 표준화 z 는 **적합창 내부에서만** 계산한다(`_logit_fit` 내장, ddof0, sd 하한 1e-9).
  전체 창 표준화는 분할을 가로지르는 누수이므로 **금지**.
- 기후(climatology) 단독 비교로 champion 을 선언하지 않는다
  (`prohibitions.champion_on_climatology_alone` 준수). 이 rung 의 기준선은 오직 PB 다.

### 1.4 구조 승계 — rung-4 와 동일

| 항목 | 값 | 출처 |
|---|---|---|
| 설계창 | 2007-01-01 ~ 2014-12-31 (패널 2014 세션) | `data_policy.design_window` |
| 분할 | early 2007-01-01~2010-12-31 / late 2011-01-01~2014-12-31 | `split` |
| 전이 | early→late, late→early 양방향 (fit 한쪽, eval 다른쪽) | `gate.bidirectional_transfer` |
| 불확실성 | stationary block bootstrap ℓ=13 · B=2000 · seed 20260907 · [5,95] | `gate.uncertainty` |
| 적합기 | `_logit_fit` (표준화 + 뉴턴, iters 200, lr 0.3, l2 1e-3) | `tools/v13_vol_run.py:61` |
| 귀무 | y-block(ℓ=13) 순열 — **p-순열 금지** | `gate.negative_control` · `prohibitions.p_permutation_null_as_negative_control` |
| 퇴화 가드 | `degeneracy_guard.rules` (min_events 20 · min_episodes 5) | 계약 |

---

## 2. 피처 블록 정의 — **수식 수준 확정 · 블록 수 3개로 못 박음**

### 2.0 기호

패널 날짜를 `D = (d₁ … d_n)`, n = 2014 (VIX ∩ NASDAQCOM 세션, 설계창 절단).
외부 계열 `S ∈ {VXNCLS, VXVCLS}` 에 대해 정렬 연산자를 다음과 같이 정의한다.

```
align(S, L)[i]  =  S(τ)   where  τ = max{ t ∈ dates(S) : t ≤ d_(i−L) },   i > L
                =  NaN    (그런 τ 가 없거나 i ≤ L)
```

즉 **① 패널 일자 이하의 마지막 관측으로 step-fill → ② L 세션만큼 뒤로 시프트**.
`tools/v13_vol_rung4_macro.py:_align` 과 **동일 함수**를 쓴다(재구현 금지).
`VIX` 는 봉인 V2 패널 열이므로 정렬 없이 `VIX[i−L]` 로 시프트만 한다.

- step-fill 은 미래를 보지 않으므로 PIT 안전하다. 다만 결측일에는 값이 하루 낡을 수 있다 — 공시 사항.
- **모든 블록의 지연 L = 1 세션** (§4). 결과를 본 뒤 L 을 바꾸지 않는다.

### 2.1 블록 3개 (이 목록이 전부다)

| 블록 | 열 정의 | 단위 | 설계창 유효행 (early/late) |
|---|---|---|---|
| **G1_vxn_level** | `x_t = align(VXNCLS, 1)[t]` | 변동성 포인트 | 2014 (1008 / 1006), 결측 0 |
| **G2_vxn_vix_spread** | `x_t = align(VXNCLS, 1)[t] − VIX[t−1]` | 포인트 차 | 2014 (1008 / 1006), 결측 0 |
| **G3_vxv_vix_term** | `x_t = align(VXVCLS, 1)[t] − VIX[t−1]` | 포인트 차 | 1782 (776 / 1006), 결측 232 |

- 각 블록은 **1열**이다. 다열 블록·상호작용항·비선형 변환은 이 rung 에 없다.
- **차이(포인트) 형태로 고정한다.** 로그비(`log(VXN/VIX)`)·비율·표준화된 스프레드로 바꾸지 않는다 —
  §2.3 의 사전 진단이 잰 것이 정확히 차이 형태이고, 결과를 본 뒤 형태를 바꾸면 사후 선택이다.
- 시프트 때문에 각 블록은 패널 첫 세션 1개를 잃는다(G1·G2 유효 2013, G3 유효 1781 근방).
  정확한 수는 실행 시점에 산출물에 기록한다.

### 2.2 **시험하지 않는 것 — 결과 후 추가 금지**

저장소에 적재된 5계열 중 **3계열은 이 rung 에서 시험하지 않는다.** 사전에, 결과를 보기 전에 제외한다.

| 제외 계열 | 제외 사유 (사전) |
|---|---|
| `VXDCLS` (DJIA) | 설계창 VIX 와 상관 **0.9969** — VIX 의 사실상 복제. 새 자유도가 없다 |
| `OVXCLS` (원유 ETF) | 교차자산 채널. rung-4 의 거시 블록 27검정이 전부 measured_zero 였고 같은 계열의 실패 모양. 결측 88 |
| `GVZCLS` (금 ETF) | 위와 동일 + 결측 356(early 652) 로 양방향 전이가 심하게 불균형 |

**이 rung 의 검정 수는 3 × 9 = 27 로 고정한다.** 결과를 본 뒤 블록이나 계열을 추가하면 다중검정
분모가 사후에 바뀌므로 family 판정이 무효가 된다. 추가하고 싶으면 **별도 rung + 별도 사전등록 +
평가 예산 1 추가 소모**만이 유일한 경로다.

### 2.3 각 블록이 왜 표적을 예측할 수 있는가 (한 문단씩) — 그리고 그 반대

**G1_vxn_level.** VXN 은 NASDAQ-100 옵션에서 역산한 30일 내재변동성으로, 우리 표적의 기초자산
(NASDAQCOM 실현변동성 초과, 그리고 그와 강하게 연동되는 VIX 터치) 자신의 전향적 변동성 가격이다.
이론적 연결은 가장 직접적이다: 시장이 앞으로 30일의 나스닥 변동성을 높게 매기고 있다면 향후 h영업일
내 RV21 이 θ 를 넘거나 VIX 가 K 를 터치할 확률도 높아야 한다. **그러나 반대 근거가 강하다** —
설계창에서 VXN 수준과 VIX 수준의 상관은 **0.9879** 이고, vix 셀의 PB 피처가 바로 그 VIX 수준이다.
즉 vix 셀에서 G1 은 사실상 같은 잠재상태의 두 번째 측정치이며, 이 캠페인이 45번 실패한 바로 그
모양이다(V9 는 원시 Δlog(VXN) 을 기존 vix_change 와 ρ=0.918 로 자동 기각했다). **rv 셀에서만**
G1 은 성격이 다르다 — 그 셀의 PB 는 후향적 RV21_t 단독이므로 내재(전향) 정보가 통째로 새 자유도다.
G1 의 존재 이유는 "PB 가 옵션 수준 정보를 흡수하는가"를 **측정 가능한 명제로 만드는 것**이며,
사전 기대는 vix 셀 거의 0, rv 셀 낮음이다.

**G2_vxn_vix_spread.** VXN−VIX 는 "나스닥 초과 변동성" — 시장이 광의 대형주(S&P500) 대비 기술주
집중 지수에 얹는 추가 변동성 프리미엄이다. 우리 표적은 나스닥 사건인데 champion 피처는 VIX(S&P500)
또는 나스닥 실현변동성이므로, 이 스프레드는 **표적 지수 고유의 위험 가격**을 분리해 준다. 설계창에서
스프레드와 VIX 수준의 상관은 **−0.3373** 으로 수준형(0.9879)보다 훨씬 직교하며, 평균 +1.54pt ·
표준편차 1.63pt 로 부호가 뒤집히는 국면이 실제로 존재한다. **반대 근거**: 같은 형태가 V9 에서 이미
실행돼 실패했다 — `V9_E6_vxn_vix_spread` 는 서브창 260원점에서 −6.180e-06(−0.019%),
CI90 [−1.890e-05, +3.203e-06] 로 **채택 아니오**였다. 다만 그 표적은 가격 분포(CRPS)였고 여기는
변동성 사건(Brier)이며 창·손실함수·기준선이 모두 다르므로 미시험 조합이다(rung-4 가 V9 계열을
재시험할 때 쓴 것과 같은 논거). 이 선례는 **약한 부정 사전확률**을 준다.

**G3_vxv_vix_term.** VXV(=VIX3M)−VIX 는 S&P500 내재변동성의 **기간구조 기울기**다. 콘탱고
(3개월 > 1개월)는 평온 국면, 백워데이션(역전)은 급성 스트레스 국면의 고전적 지표이며, 스트레스
국면에서는 단기 임계 터치 확률이 비선형적으로 커진다. 즉 이 블록은 수준이 아니라 **국면의 부호**를
준다는 점에서 PB 와 성격이 다르다. **반대 근거 셋**: ① 스프레드와 VIX 수준의 상관이 **−0.675** 로
G2 보다 훨씬 덜 직교하다(기간구조는 VIX 가 높을 때 기계적으로 역전한다). ② 설계창 결측 232행
(11.5%)이 전부 early 앞부분(VXVCLS 는 2007-12-04 시작)이라 early 유효 776 vs late 1006 의 불균형이
생기고, GFC 직전 구간이 통째로 빠진다 — 하필 기간구조가 가장 정보적이었을 구간이다.
③ 자기 기간구조(EWMA 단기/장기 비)는 rung-1·rung-2 가 이미 시험해 0/9·0/9 로 실패했다.

### 2.4 사전 진단을 이미 보았다는 사실의 공시

블록을 고르기 전에 `data/timeseries_v13/external/feature_design_inputs.json`
(content_hash `6cdbe71b…`)의 **피처↔피처 상관표를 보았다.** 숨기지 않는다.

- 본 것: 계열별 `corr_level_with_vix`·`corr_spread_with_vix`·결측 수 (설계창 2014행).
- **보지 않은 것**: 라벨 y. 그 파일 자체가 `labels_touched: false`·`holdout_read: false` 로 기록한다.
- 따라서 이 표는 "무엇을 시험할 가치가 있는가"만 알려주며, **게이트 결과에 대한 사전 정보는 주지 않는다**.
- 그럼에도 블록 선택의 정당화는 상관값이 아니라 **§2.3 의 이론**에 둔다. 상관값은 제외 사유(§2.2)를
  공시하는 데만 쓴다.

### 2.5 사전 예측 (결과 전 기록 — 사후 서술 방지)

| 대상 | 사전확률 (1% 단위) | 근거 |
|---|---|---|
| G1 이 최소 1셀 채택 | **3%** | vix 셀 ρ=0.988 로 거의 흡수. rv 셀만 실낱 |
| G2 가 최소 1셀 채택 | **5%** | 최고 직교(−0.337)이나 V9_E6 선례가 부정 |
| G3 가 최소 1셀 채택 | **4%** | 국면 부호 정보이나 early 불균형 + ρ −0.675 |
| **27검정 중 최소 1건 채택** | **10%** | 캠페인 채택 기저율 rung-2·3·4 합산 **0/45** |
| 전 셀 measured_zero 로 종료 | **85%** | 위의 여집합 중 귀무 누수·untestable 제외분 |

---

## 3. 게이트 — rung-4 와 동일 산술 + 종속조정 family 병기

### 3.1 셀별 게이트 (블록 × 셀 = 27쌍 각각)

`d_t = BS_PB,t − BS_후보,t` (양수 = 후보 우세). 방향 `early→late`(early 적합·late 평가)와
`late→early` 각각에 대해 stationary block bootstrap(ℓ=13, B=2000, seed 20260907)로 CI90 을 낸다.

```
채택(cell, block) ⇔
    (A) CI90_lower(d | early→late) > 0        (엄격 부등호)
  ∧ (B) CI90_lower(d | late→early) > 0        (엄격 부등호)
  ∧ (C) 증분 y-block(ℓ=13) 귀무 통과율 ≤ 0.10  (draws = 120, seed 승계)
```

- (C) 는 (A)∧(B) 가 참일 때만 계산한다(rung-4 와 동일 — 계산 비용 절약이지 규칙 완화가 아니다).
- 판정 라벨: `adopted` / `measured_zero`((A)∨(B) 실패) / `null_leak`((A)∧(B) 통과, (C) 실패) /
  `untestable_by_construction`(§5) / `adopted_episode_thin`(채택이나 국면 미달).
- **MDE 병기 의무**: 모든 셀에 `mde = 1.645 · bootstrap_se` 를 기록한다. `|d| < MDE` 는
  "결정적 증거 없음"이지 "효과 없음"이 아니다.
- **방향별 유의 열위 기록 의무**: `ewma_significantly_worse`(= CI90 상단 < 0)를 방향별로 남긴다.
  이것이 있어야 "검정력이 있어 측정된 영"과 "검정력 부족"을 사후에 새 계산 없이 가를 수 있다
  (판정서 RQ7 이 요구한 재분류를 이 rung 에서는 처음부터 가능하게 한다).

### 3.2 family — **두 값 모두 사전등록, 대표값은 지금 확정**

| 이름 | 정의 | 지위 |
|---|---|---|
| `family_p_binomial` | `P(k ≥ k_obs | n = tested, p = 0.05)` — `S.family_p_binomial` | **참고값**. 셀 독립 가정이며 셀 종속 caveat 병기 의무 |
| `family_p_yblock` | y-block 재표집 family 귀무 (아래 정의) | **대표값** — 이 rung 의 다중비교 판정은 이 값으로 말한다 |

**`family_p_yblock` 의 정확한 정의 (이미 구현된 원시함수만 사용)**

```
1. 관측 통계량:  k_ci_obs = #{(cell, block) : _adopt_increment_fast(PB, 후보, y, me, ml) = True}
   (= 양방향 고속 CI90 하한 > 0 인 쌍의 수. 27쌍 중 untestable 제외분에 대해서만.)
2. 귀무 draw d = 1 … D (D = 200, seed = 20260910):
   - ℓ=13 블록 순열 인덱스 idx_d 를 한 번 뽑아 **모든 셀에 동일하게 적용**한다.
     (셀마다 다른 순열을 쓰면 셀 간 종속이 파괴돼 조정의 의미가 사라진다.)
   - k_null(d) = #{(cell, block) : _adopt_increment_fast(PB, 후보, y[idx_d], me, ml) = True}
3. family_p_yblock = #{d : k_null(d) ≥ k_ci_obs} / D
```

- 관측과 귀무에 **같은 결정규칙**(고속 CI, b=400)을 쓴다. 한쪽만 정밀 규칙을 쓰면 비교가 성립하지 않는다.
- 산출물에는 `k_obs`(정밀 규칙·§3.1 채택 수)와 `k_ci_obs`(고속 CI 규칙) 둘 다 기록한다. 두 값이
  다를 수 있다는 것을 미리 적어 둔다 — 다르면 그것이 근사 오차의 크기이며, 감추지 않는다.
- 셀 간 양의 종속(중첩 지평·공유 VIX)이 있으므로 `family_p_yblock ≥ family_p_binomial` 이 기대되나
  **보장은 아니다.**

**family 판정 규칙 (사전 확정)**

> 이 rung 이 "무언가를 발견했다"고 말할 수 있는 조건은
> **`family_p_yblock ≤ 0.05` **그리고** `family_p_binomial ≤ 0.05`** 이다(둘 다).
> 개별 셀의 채택 여부는 §3.1 셀 게이트가 정하고, family 는 **집합 수준 주장**만 규율한다.
> 두 값 중 큰 쪽이 기준이 되므로 이 규칙은 어느 한 도구를 고르는 것보다 항상 보수적이다.

**하지 않는 것**: BH·Holm·Bonferroni·Romano-Wolf·MCS·Westfall–Young 은 이 저장소에 **미구현**이다.
미구현 도구를 사전등록에 적으면 실행 시점에 다른 것으로 대체하게 되고, 그것이 결과 후 도구 교체다.
위 두 값은 **오늘 저장소에 존재하는 원시함수만으로 계산된다**(`S.family_p_binomial`,
`PB3._adopt_increment_fast`, `R.BLOCK`).

**소급 적용 금지**: 이 절은 rung-1~4 판정과 홀드아웃 판정(`publication.holdout_family_p = 0.008361`)에
**소급 적용되지 않는다.** 이미 실행된 판정의 대표값을 사후에 바꾸는 것은 결과 후 도구 교체다.

### 3.3 신뢰도 보고 (판정 다리 아님)

Murphy 분해(rel/res/unc) + 신뢰도 곡선을 채택 셀에 한해 보고한다. `gate.reliability` 승계 —
**보고 의무이지 게이트가 아니다.** h63 셀의 rel≈0.08 오보정은 알려진 한계이며, 이 rung 은
`reliability.cross_fit_isotonic_h63` 파생층을 **건드리지 않는다**(게이트는 raw 확률로 판정).

---

## 4. PIT · 지연 — **단일 지연만 사전등록**

### 4.1 등급과 지연 (3블록 공통)

```yaml
pit_grade:    assumed_lag      # 세 블록 모두
lag_sessions: 1                # 세 블록 모두 — 단일값
```

### 4.2 이 값을 고른 이유

- **`archive_verified` 를 줄 수 없다.** rung-4 에서 lag 0·archive_verified 를 받은 유일한 블록
  F1(DGS2·DGS10)은 원장의 과거 행 `available_at` 이 관측일 당일로 backdated 돼 있다는 **실측**이
  근거였다. 새로 적재한 외부 계열은 구조상 `available_at = 수집 시각`(2026-09-10)이므로 그 증거가
  존재할 수 없다.
- **개정이 실재한다(실측).** ALFRED 빈티지와 현재 vintage 를 대조한 결과 VXNCLS 는 값이 바뀐 행이
  존재한다(설계창 2건, 2001~2020 전체 6건). 즉 `fredgraph.csv`(최신 vintage only)는 PIT 가 아니다.
  저장소 자신의 계약도 같은 판정을 이미 적어 뒀다 — `fred_market_signals.yaml`
  `point_in_time_scope`: "historical current-vintage rows are not valid for backtests."
- **1 이 측정에 근거한 유일한 값이다.** 정직하게 응답한 ALFRED 빈티지 12건 중 10건은 당일 종가를
  포함하고 2건(2014-06-02→05-30, 2016-07-12→07-11)은 직전 영업일까지만 담는다 →
  **측정된 최대 발행지연 = 1영업일**. rung-4 의 규칙("측정된 최대 발행지연을 덮는 보수적 지연")의
  기계적 적용 결과가 1이다. 2 이상은 측정 근거가 없는 임의값이라 오히려 방어가 안 된다.
- **부수 효과가 유리하다.** L=1 이면 G2·G3 의 VIX 항도 `VIX[t−1]` 이 되어, 블록이 `VIX_t` 의
  두 번째 측정치를 몰래 끌어들일 수 없다. 또한 V13 라이브 경로가 구조적으로 T+1 이므로
  설계창 실험과 미래 배선의 정렬이 같아진다.

### 4.3 금지

- **`lag_sessions = 0` 금지.** archive_verified 근거가 없는 계열에 lag 0 을 주는 것은 rung-4 규칙 위반.
- **두 지연을 모두 돌려 좋은 쪽 채택 금지.** 이것은 p-hacking 이다. 계약에 1 하나만 박는다.
- **결과 후 지연 변경 금지.** 채택이 나오지 않았다고 L 을 바꿔 재실행하면 그 순간 이 rung 은 무효다.

### 4.4 원장 필드와의 충돌 공시 — 계약이 정본

수집기가 관측 행에 쓴 `data_grade: "published_close_no_revision"` 과 docstring 의
"사후 개정되지 않는다"는 서술은 **위 실측과 어긋난다**. 원장은 append-only 이므로 **고치지 않는다**.
대신 rung-4 선례("pit_grade·lag_sessions 는 원장이 아니라 계약에 적는다")를 따라
**계약 `rung5e_external_vol_blocks` 의 값이 정본**임을 여기서 확정한다.

### 4.5 알려진 데이터 손상 1건 — 그대로 쓴다

현재 vintage 의 **VXNCLS 2010-04-27 = 17.81** 은 직전 거래일 2010-04-26 값과 완전 동일한 복사값으로
보인다(같은 날 VIX 는 17.47 → 22.81 급등, VXN 다음날 20.51, 2014 vintage 는 21.30).
설계창 early half 의 변동성 급등일 하나가 평온한 날로 기록돼 있다.

**사전등록된 처리: 손대지 않는다.** 수집본 그대로 쓰고 이 사실을 공시한다. 결과를 본 뒤 값을 고치면
그것이 데이터 조작이다. 방향성 caveat: 이 손상은 급등 정보를 **지우므로** 블록을 실제보다 약하게
보이게 한다 — 즉 **거짓 채택 쪽으로는 편향되지 않는다**(보수적).

### 4.6 결측·정렬 규칙

- 결측(`.`)은 파싱 단계에서 버린다. **0 으로 바꾸지 않는다.**
- 정렬은 step-fill(직전 관측 이월) 후 시프트. 이월은 미래를 보지 않으므로 PIT 안전.
- `usable = isfinite(y) & isfinite(x)`. NaN 원점은 **제외**하며 대체·보간하지 않는다.
- PB 기준선도 **동일한 usable 마스크**에서 재적합·재평가한다 → 쌍대 비교가 같은 원점 집합 위에서
  성립한다. 따라서 G3 의 PB 기준선 수치는 G1·G2 의 것과 다를 수 있다(정상이며, 산출물에 각각 기록).

---

## 5. 퇴화 가드 — 실행 시점 적용

계약 `degeneracy_guard` 를 **그대로** 적용한다. 임계를 바꾸지 않는다.

```
min_events_per_half_per_class   = 20     # 사건/비사건 중 작은 쪽
min_episodes_per_half_per_class = 5      # 라벨 연속 구간(run) 수 중 작은 쪽
```

- 가드는 **블록별 usable 마스크로 제한된 반창**에서 계산한다 —
  `degeneracy_report(where(early & usable, y, NaN))`, late 도 동일.
  G3 는 early 가 776행으로 줄어들므로 **일부 셀이 여기서 탈락할 수 있다**. 이는 규칙의 정상 작동이다.
- **사건 수 미달** → `untestable_by_construction`. 채점하지 않고 **family 분모(`tested`)에서도 제외**한다
  (페일클로즈).
- **국면 수 미달** → 채점하되 `episode_thin` 라벨을 붙인다. 채택되면 `adopted_episode_thin`.
- 설계창에서 이미 국면 미달인 셀은 6개다:
  `vix25_h21 · vix25_h63 · vix30_h5 · vix30_h21 · vix30_h63 · rv_h63`
  (깨끗한 셀은 `vix25_h5 · rv_h5 · rv_h21` 셋). 블록 제한으로 이 목록이 더 나빠질 수는 있어도
  좋아질 수는 없다.
- **가드는 게이트를 느슨하게 하는 방향으로 쓰지 않는다**(`degeneracy_guard.provenance` 승계).
  이 rung 에서 가드의 유일한 효과는 분모 축소(= family P 상승 = 더 엄격)와 라벨 부착이다.

**배선 관련 주의**: 이 rung 은 설계창 전용이므로 **어떤 셀도 배선 자격을 얻지 않는다**(V13-D6 은 보류
상태이며 배선은 홀드아웃 PASS ∧ 국면 가드 통과 셀만). 부수적으로, 코드가 배선 자격을 홀드아웃 창
가드만으로 계산해 계약(두 창 모두 요구)보다 느슨하다는 기존 불일치가 있으나 **이 rung 의 범위 밖**이며,
여기서 고치지 않는다(다른 세션의 코드 정합 과제).

---

## 6. 정지 규칙 — 어떤 조건에서 중단하는가

| # | 조건 | 조치 |
|---|---|---|
| **S0** | §0 차단 조건(V13-D9 미승인)  | **실행 자체를 하지 않는다.** 러너는 데이터를 읽기 전에 승인 영수증을 확인하고 없으면 거부(exit≠0). 예산 미소모 |
| **S1** | `vol_experiments.jsonl` 에 `V13VOL_rung5e_external_vol` 행이 이미 있음 | **재실행 거부**(exit 2). 평가 예산은 단일 사용이다 — rung-4 가드 그대로 |
| **S2** | 원장 raw sha256 재대사 실패 / API 재수집본과 값 불일치 | **중단.** 불일치는 revision 으로 append 하고, 어느 vintage 로 실험할지는 사전등록 개정(결과 전)으로만 정한다 |
| **S3** | 어떤 셀·블록이 `untestable_by_construction` | 그 쌍만 제외하고 나머지는 계속. family 분모 축소 |
| **S4** | 27검정 전부 `measured_zero` | **정상 종료 = 부정 결과.** §7 프로토콜 실행. 추가 rung 을 이 예산으로 시작하지 않는다 |
| **S5** | 채택 셀 ≥ 1 | **루프 즉시 정지 · 사용자 질문**(`stopping_points.champion_action` 승계). 홀드아웃 자동 진입 **금지**. champion 재판정은 별도 결정 |
| **S6** | `null_leak` (양방향 CI 통과했으나 y-block 귀무 > 0.10) | 그 셀 채택 **무효**. 27쌍 중 3쌍 이상에서 누수가 나오면 **검정 기계 점검 모드**로 전환(T-A 선례) — 이 rung 의 모든 채택을 보류하고 사용자에게 보고 |
| **S7** | 적합 비수렴·수치 폭주(`beta` 발산, NaN 확률) | **중단.** 원장 기록 전 중단이면 예산 미소모. 원인(다중공선성 등)을 판정서에 적고 사전등록 개정 없이는 재실행 금지 |
| **S8** | 런타임이 상식 범위를 넘음(family 귀무 D=200 포함 90분 초과) | **중단.** D 를 줄여 재실행하지 않는다 — D 축소는 검정력 변경이며 결과 전 개정으로만 가능 |
| **S9** | 실행 중 홀드아웃(2015-2018) 또는 봉인(2019+) 바이트를 읽는 코드 경로가 발견됨 | **즉시 중단 · 산출물 폐기 · 사용자 보고.** 이 rung 은 설계창 절단 패널만 읽는다 |

---

## 7. 부정 결과 프로토콜 — 채택 0 이면 무엇을 기록하고 무엇을 결론짓는가

부정 결과는 실패가 아니라 **이 rung 이 사는 정보**다. 결과가 영이어도 아래를 전부 기록한다.

### 7.1 기록물 (전부 필수)

| 산출물 | 경로 | 내용 |
|---|---|---|
| 결과 JSON | `data/timeseries_v13/vol/ladder_rung5e_external_vol.json` | 27쌍 전부의 방향별 `paired_mean`·`ci90`·`mde`·`ewma_significantly_worse`·퇴화 리포트·`k_obs`·`k_ci_obs`·family 2값·`content_hash` |
| 실험 원장 1행 | `data/timeseries_v13/ledgers/vol_experiments.jsonl` (append-only) | `experiment_label: V13VOL_rung5e_external_vol` · `evaluation_index: 5` · `backtest_windows_opened: 0` · `prereg_commit` · `results_sha256` · `content_hash` · caveat |
| 판정서 | `docs/review/V13_VOL_RUNG5E_EXTERNAL_VERDICT_<YYYYMMDD>.md` | 셀×블록 표 · 데블스 애드버킷 · §7.3 의 "결론짓지 않는 것" |
| 계약 1줄 | `rung5e_external_vol_blocks.result` | 결과 요약 한 줄 (규칙 바이트는 무수정) |
| 결정 기록 | `docs/DECISIONS.md` | V13-D9(경로 결정 · 실행 전) · **V13-D10**(rung-5E 판정 · 실행 후) |

**필수 세부 기록 2건** (판정서 RQ7 의 교훈을 처음부터 반영):

1. **`measured_zero` 를 두 종류로 갈라 적는다.**
   - *진짜 측정된 영*: 어느 방향에서 `ewma_significantly_worse = true`(CI90 상단 < 0) — 검정력이 있어
     "영 또는 열위"임이 측정된 경우.
   - *검정력 부족*: 양측 CI 가 0 을 포함하고 `|d| < mde` — 무결정.
   두 가지를 뭉뚱그려 "효과 없음"이라 쓰지 않는다.
2. **문턱 근접 공시.** 어떤 셀·블록의 `min_count` 나 `min_episodes` 가 임계(20 / 5)에 근접하면
   그 수치를 판정서에 명시한다. (선례: 홀드아웃 `vix30_h5` 의 min_count 는 25 로 임계 20 을 겨우
   넘겼다 — 결과를 본 뒤 문턱을 만지면 안 되는 이유의 교과서적 사례.)

### 7.2 "옵션 형상도 PB 에 흡수된다"는 결론이 갖는 의미

27검정 전부가 영이면 다음을 **말할 수 있다**.

1. **PB 의 충분성 증거가 한 겹 두꺼워진다.** 설계창(2007-2014)·이 손실함수(Brier)·이 표적
   (K/θ/h 9셀)에서, 옵션 시장의 전향적 정보 세 형태(내재수준·지수 초과분·기간구조)는
   **당일 실현 수준 하나에 흡수된다**. 이는 "시장 참여자가 이미 같은 상태변수를 보고 있다"는
   효율적 시장 해석과 정합적이다.
2. **캠페인 채택 기저율이 0/45 → 0/72 가 된다.** 45번의 실패는 언제나 같은 모양이었다 —
   *같은 잠재상태의 두 번째 측정치를 더한 것*. 이 rung 이 영이면 그 모양이 27건 더 확인된 것이며,
   **다음 후보를 고르는 규칙**이 강해진다: 새 측정치를 더하지 말고 **기존 변수를 분해하거나 격차를 쓰라**.
3. **유료 데이터 구매의 기대가치가 낮아진다.** 무료 옵션 지수(일간 종가)가 영이라면, 같은 채널의
   유료 고빈도판(FirstRate·CBOE DataShop)이 통과할 사전확률도 함께 낮아진다 — 정보 채널이 같기
   때문이다. **이것이 이 rung 의 가장 실용적인 산출물이다**: 지출 결정을 싸게 정보화한다.

### 7.3 **결론짓지 않는 것** (과장 금지 — 사전 봉인)

이 목록은 결과를 보기 전에 못 박는다. 부정 결과가 나와도 아래 문장들은 쓸 수 없다.

- ❌ **"옵션 정보는 무가치하다."** → 이 표적·이 손실함수·이 창·이 지연·1열 선형 로짓이라는
  좁은 조건에서 증분이 없다는 뜻일 뿐이다. 다른 표적(가격 분포·조건부 분위수)이나 비선형 결합은
  시험하지 않았다.
- ❌ **"무료 정보집합이 소진됐다."** → **이 문장을 쓰는 것을 사전 금지한다.** 계약 282행
  (`rung4_macro_blocks.result`)의 "무료 정보집합 소진"은 **과장이며 정정 대상**이다. 정확한 문장은
  "봉인 아카이브 안의 **미사용 계열**이 소진됐다"이며, **기존 계열의 미시험 형상 변환**은 남아 있다 —
  반분산 분해(상방/하방 RV)·부호점프변동·VRP 스프레드 `log(VIX/RV21)` 는 새 바이트 0·라이선스 노출
  0·커버리지 완전균형(1008/1006)으로 만들어지며 한 번도 시험되지 않았다. rung-5 가 영이어도
  이들은 그대로 남는다.
- ❌ **"표본외에서도 영이다."** → 홀드아웃을 열지 않았다. 이 rung 의 모든 진술은 설계창 한정이다.
- ❌ **"champion 이 옳음이 증명됐다."** → 설계창 early 절반이 GFC 지배라 전이 검정이 위기↔평온 성격
  이라는 기존 한계(`known_limits` 1행)가 그대로 적용된다. 또한 동결 기후 기준선이 홀드아웃 창에서
  심하게 오보정돼 있었다는 사실(예: `vix25_h5` 기후 0.3076 vs 홀드아웃 실현 0.0739)은 이 트랙의
  기준선 자체가 창 의존적임을 뜻한다.
- ❌ **매매·자금 배분 함의.** 전 출력은 "참고 의견"이며 매매 신호가 아니다.

### 7.4 채택이 나온 경우 (드문 경로)

S5 로 즉시 정지하고 사용자에게 보고한다. **자동으로 하지 않는 것**: 홀드아웃 진입, champion 교체,
라이브 카드 표시 변경, 배선. 홀드아웃 슬롯 2개는 사용자 승인 원문(`V13-D…` + finalist_id) 없이
소모되지 않는다. 채택 셀이 `episode_thin` 이면 라벨을 달고 배선 불가로 남는다.

---

## 8. 예산 회계

| 자원 | 실행 전 | 실행 후 | 근거 |
|---|---|---|---|
| 개발 평가 예산 | **4 / 8** | **5 / 8** | `vol_experiments.jsonl` 4행(ewma_logit·har_logit·pb_baseline·rung4_macro) → 5행. `development_protocol.evaluations_spent` 4→5 |
| 홀드아웃 슬롯 | 1 소모 / 3 | **1 소모 / 3 (미변동)** | **이 rung 은 홀드아웃을 소모하지 않는다.** 잔여 2슬롯 무접촉 |
| 봉인(2019+) | 미열람 | **미열람** | `execution_path: absent_by_construction` |
| 새 백테스트 창 | — | **0** | 설계창 2007-2014 재분석. 창을 열지 않는다 |
| 새 표적 | — | **0** | K·θ·h 무변경 |
| 새 계열 적재 | 5계열 (적재 완료) | 추가 0 | 그중 **2계열만** 사용(VXNCLS·VXVCLS) |
| 봉인 V2 아카이브 | 무수정 | **무수정** | 신규 스토어 `data/timeseries_v13/external/` 를 어댑터로 읽는다 (`no_write_to_sealed` 준수) |
| API 비용 | $0 | $0 | FRED 무료. 단 §0 의 준수 재수집 1회 필요 |

**rung-4 선례와의 정합**: rung-4 는 3블록 × 9셀 = 27검정을 평가 예산 **1단위**로 처리했다.
이 rung 도 동일 형태(3블록 × 9셀 = 27검정)이므로 1단위다.

**상호배타 회계**: 이 1단위는 §0.0 의 rung-5(형상 변환)와 **경합한다**. 둘 다 하려면 2단위
(4/8 → 6/8)이며 별도 승인이 필요하다. 한 단위에 6블록 54검정을 묶는 것은 rung-4 선례를 넘어서고
family 분모를 두 배로 만들어 검정력을 떨어뜨리므로 **하지 않는다**.

---

## 9. 하지 않는 것 (금지 목록 — 위반 시 이 rung 무효)

1. **표적 추가·변경 금지.** K∈{25,30}, θ=0.1694, h∈{5,21,63} 고정 (`post_hoc_target_addition`).
2. **홀드아웃(2015-2018) 열람 금지.** 패널은 `observation_time ≤ 2014-12-31` 로 절단한다.
   사전 점검·"살짝 보기"도 열람이다.
3. **봉인(2019+) 열람 금지.**
4. **결과 후 블록 추가·교체 금지.** 블록은 G1·G2·G3 셋뿐. VXD·OVX·GVZ 는 이 rung 에서 시험하지 않으며,
   결과를 본 뒤 추가할 수 없다.
5. **결과 후 지연·문턱·귀무·기준선 교체 금지.** L=1, CI90 하한>0(엄격), y-block ℓ=13 ≤0.10,
   기준선=PB. `gate_threshold_relaxation`·`null_redesign_after_results` 승계.
6. **p-순열 귀무 사용 금지** (T-A 에서 누수 확인). 건전 y-block 귀무만.
7. **기후 단독 비교로 champion 선언 금지** (`champion_on_climatology_alone`).
8. **자동 홀드아웃 진입 금지 · 자동 봉인 공개 금지.**
9. **셀 선택 금지.** 9셀 전부. 홀드아웃 통과 셀에 맞춰 좁히지 않는다.
10. **전체 창 표준화 금지.** z 는 적합창 내부에서만.
11. **원장 수정 금지.** `vol_indices.jsonl`·`raw_receipts.jsonl`·`vol_experiments.jsonl` 은 append-only.
    `data_grade` 필드가 §4 실측과 어긋나도 **고치지 않고 계약으로 정정**한다.
12. **손상 의심 값(2010-04-27) 수정 금지.** 공시만 한다.
13. **미구현 다중비교 도구 사용 금지.** §3.2 의 두 값만.
14. **`push_without_success` 승계** — 게이트 통과 전 원격 푸시 금지. 사전등록 커밋은 예외가 아니라
    별개다(사전등록은 결과 전 커밋이며, 브랜치 정책은 사용자 규율을 따른다).
15. **메일·대외 발송 금지.** 이 문서는 어떤 메일도 작성·발송하지 않으며 권고하지도 않는다.
16. **rung-5(형상 변환)와 한 예산으로 묶기 금지.** 6블록 54검정을 1단위로 처리하지 않는다.
    두 구성은 각자 1단위이며, 둘 다 하려면 별도 승인으로 2단위를 쓴다.
17. **이 문서를 결과 후 개정하지 않는다.** 개정이 필요하면 **집행 전**에만, 개정 이유와 함께
    새 커밋으로 한다. 집행 후 개정본은 사전등록이 아니다.

---

## 10. 데블스 애드버킷 — 이 rung 이 실패할 가장 그럴듯한 방식 (그리고 성공해도 의심할 이유)

1. **기저율이 압도적으로 불리하다.** rung-2 0/9 · rung-3 0/9 · rung-4 0/27 = **채택 0/45**.
   10% 사전확률조차 낙관적일 수 있다.
2. **양방향 전이가 죽인다.** rung-4 의 최선 조합(`vix30_h63|F1`)은 early→late 로 +0.030 유의하게 좋고
   late→early 로 −0.102 로 **세 배 크게 유의하게 나빴다**. 설계창 early 절반이 GFC 지배라 옵션
   기간구조·초과변동성의 성격이 두 반창에서 근본적으로 다르며, G3 는 정확히 같은 모양으로 무너질
   가능성이 가장 높다(게다가 early 776행으로 GFC 직전이 빠져 있다).
3. **G1 은 다중공선성으로 죽는다.** vix 셀에서 ρ=0.9879 이면 `l2=1e-3` 릿지가 수치적으로는 버텨도
   두 계수가 서로를 상쇄해 예측이 PB 와 사실상 동일해진다 — `measured_zero` 가 아니라 **항등에 가까운
   영**이 나올 것이다. 이것은 정보가 없다는 증거가 아니라 **설계가 정보를 꺼내지 못한다는 증거**다.
4. **G2 는 이미 죽은 적이 있다.** `V9_E6_vxn_vix_spread` −0.019%, 채택 아니오. 표적·손실함수가
   다르다는 논거는 참이지만, 같은 논거를 rung-4 에도 썼고 rung-4 는 0/27 이었다.
5. **채택이 나와도 의심해야 한다.** 27검정에서 p=0.05 수준 1~2건 통과는 우연으로도 흔하다
   (`family_p_binomial(1, 27) ≈ 0.75`). 그래서 §3.2 의 종속조정 family 가 필요하고, 단일 셀 통과는
   **발견이 아니다**. 또 통과 셀이 `episode_thin` 이면 그 통과는 단일 국면에 얹힌 것일 수 있다
   (설계창 `vix30_h21` 후반창 사건 109개 = 1국면).
6. **라이선스가 통계보다 먼저 죽인다.** §0 이 미해소면 통계는 아예 의미가 없다. 이 rung 의 실질적
   실패 확률에서 가장 큰 조각은 통계가 아니라 거버넌스다.

---

## 부록 A — 계약 이식용 YAML (그대로 붙여 넣는다)

`data/contracts/multivariate_timeseries_v13_vol.yaml` 의 `rung4_macro_blocks` 블록 **뒤에** 신규 키로
추가한다. 기존 키는 1바이트도 수정하지 않는다.

```yaml
# [P5 사전등록 2026-09-10 — 결과 전 커밋] 외부 정보집합: FRED 호스팅 옵션 변동성 지수 (rung-5)
# 설계서: docs/design/mts_p5_external_infoset_prereg_260910.md (이 블록의 정본 해설)
# 표적(K·θ·h) 무변경. 봉인 V2 무접촉 — 별도 비봉인 스토어를 어댑터로 읽는다.
rung5e_external_vol_blocks:
  registered: '2026-09-10'
  design_doc: docs/design/mts_p5_external_infoset_prereg_260910.md
  prereg_commit: TBD                      # 결과 전 커밋 해시를 후속 1줄 커밋으로 기입
  status: blocked_pending_V13-D9          # §0 차단 조건 해소 전 실행 금지 (fail-closed)

  blocking_preconditions:
    licence_path: |
      DECISIONS 12-6 이 fredgraph.csv 스크랩을 약관 위반으로 판정했고 12-5 가 CBOE→FRED 이전을
      '더 나쁨'으로 기각했다. 실행 전 (1) api.stlouisfed.org 공식 API 로 1회 재수집·값 대사,
      (2) fred_market_signals.yaml series_ids 에 VXNCLS·VXVCLS 추가(사용자 결정 V13-D9),
      (3) FRED AI/ML·store 조항 미해결을 KNOWN_LIMITS 에 공시. 셋 다 충족 전에는 러너가 거부한다.
    user_decision_required: V13-D9
    approvals_ledger: data/timeseries_v13/ledgers/approvals.jsonl
    registry_drift_to_fix:
      - data/source_registry.yaml:84 endpoint fredgraph.csv → api.stlouisfed.org
      - docs/generated/licenses.generated.md (확인일 2026-08-01, 12-5·12-6 이전 stale)

  rationale: |
    champion=persistence_pb 는 '당일 실현 수준의 지속'이다. 옵션 시장의 전향적 정보(내재변동성 수준·
    나스닥 초과분·기간구조)가 그 위에 증분을 주는지 시험한다. V9 가 VXN 을 시험했으나 표적이
    가격분포(CRPS)였고 여기는 변동성 사건(Brier)이라 미시험 조합이다. 다만 V9_E6_vxn_vix_spread 의
    무효익(−0.019%, CI90 [−1.890e-05, +3.203e-06])은 약한 부정 사전확률을 준다. 기대 부정 종료 85%.

  data_source:
    store: data/timeseries_v13/external/vol_indices.jsonl      # 비봉인 · append-only
    receipts: data/timeseries_v13/external/raw_receipts.jsonl
    adapter: V2 관측 스키마 필드명 동일(series_id·observation_time·value·available_at) → _series_by_date 무수정 재사용
    sealed_archive_write: false
    fred_key_in_loop: false                                    # 루프 밖 1회 백필만

  series_used: [VXNCLS, VXVCLS]
  series_collected_but_not_tested: [VXDCLS, OVXCLS, GVZCLS]
  exclusion_reasons:
    VXDCLS: 설계창 VIX 와 상관 0.9969 — VIX 복제, 새 자유도 없음
    OVXCLS: 교차자산 채널(rung-4 거시 27검정 measured_zero 와 동형) · 결측 88
    GVZCLS: 위와 동일 · 결측 356(early 652) 로 양방향 전이 불균형

  cells: 전체 9셀 — 홀드아웃 결과로 셀을 고르지 않는다
  baseline: persistence_pb (현 champion). 후보 = logit[PB 피처 + β·G_k] — 블록당 파라미터 1개 추가
  standardization: 적합창 내부 z-score 만(_logit_fit 내장). 전체 창 표준화 금지
  alignment: tools/v13_vol_rung4_macro.py:_align 동일 — step-fill(직전 관측 이월) 후 lag 시프트
  missing_policy: usable = isfinite(y) & isfinite(x). NaN 원점 제외 · 보간 금지 · PB 도 동일 마스크에서 재적합

  block_count: 3                            # 결과 후 추가 금지. 추가는 별도 rung + 예산 1 추가 소모
  blocks:
    G1_vxn_level:
      definition: x_t = align(VXNCLS, lag=1)[t]                      # 변동성 포인트, 1열
      pit_grade: assumed_lag
      lag_sessions: 1
      design_window_rows: {total: 2014, early: 1008, late: 1006, missing: 0}
      prior_adopt_probability: 0.03
      note: vix 셀에서 corr(VXN, VIX)=0.9879 로 거의 흡수 예상. rv 셀에서만 내재↔실현의 새 자유도
    G2_vxn_vix_spread:
      definition: x_t = align(VXNCLS, lag=1)[t] − VIX[t−1]           # 나스닥 초과 변동성, 포인트 차
      pit_grade: assumed_lag
      lag_sessions: 1
      design_window_rows: {total: 2014, early: 1008, late: 1006, missing: 0}
      prior_adopt_probability: 0.05
      note: corr(spread, VIX)=−0.3373 로 최고 직교. V9_E6 선례는 부정
    G3_vxv_vix_term:
      definition: x_t = align(VXVCLS, lag=1)[t] − VIX[t−1]           # 기간구조 기울기, 포인트 차
      pit_grade: assumed_lag
      lag_sessions: 1
      design_window_rows: {total: 1782, early: 776, late: 1006, missing: 232}
      prior_adopt_probability: 0.04
      note: VXVCLS 는 2007-12-04 시작 — early 불균형. corr(spread, VIX)=−0.675

  pit:
    grade_for_all_blocks: assumed_lag
    lag_sessions_single_value: 1
    evidence: |
      ALFRED 빈티지 대조 실측 — VXNCLS 는 개정되는 계열이다(설계창 2건, 2001~2020 전체 6건 불일치).
      정직 응답 빈티지 12건 중 10건 당일 종가 포함, 2건(2014-06-02→05-30, 2016-07-12→07-11)이
      직전 영업일까지 → 측정된 최대 발행지연 1영업일. archive_verified 는 구조상 불가
      (신규 적재 계열의 available_at = 수집 시각).
    contract_is_authoritative: |
      수집기가 원장에 쓴 data_grade='published_close_no_revision' 은 위 실측과 어긋난다. 원장은
      append-only 이므로 수정하지 않고, pit_grade·lag_sessions 는 이 계약 값이 정본이다(rung-4 선례).
    known_corruption:
      series: VXNCLS
      date: '2010-04-27'
      fact: 현재 vintage 17.81 = 직전 거래일 복사값(같은 날 VIX 17.47→22.81 급등, 2014 vintage 21.30)
      handling: 수정하지 않는다. 공시만. 급등 정보를 지우므로 거짓 채택 쪽으로는 편향되지 않는다
    alfred_trap: alfredgraph 는 없는 빈티지에 200 을 주며 최신본으로 조용히 폴백한다 — 응답 헤더 컬럼명 검증 후 fail-closed

  gate:
    per_cell: 쌍대 Brier(PB − 후보) 양방향 CI90 하한 > 0 (엄격) AND 증분 y-block(ℓ=13) 귀무 통과율 <= 0.10
    uncertainty: gate.uncertainty 동일 (stationary block ℓ=13 · B=2000 · seed 20260907 · [5,95])
    neg_control_draws: 120
    mde_required: true                      # 모든 셀에 1.645·se 병기
    direction_worse_flag_required: true     # ewma_significantly_worse 방향별 기록 — measured_zero 재분류 근거
    family:
      representative: family_p_yblock       # 종속조정 — 이 rung 의 대표값 (사전등록 시점 확정)
      also_reported: family_p_binomial      # 셀 독립 가정 참고값 — 종속 caveat 병기 의무
      rule: 집합 수준 발견 주장은 두 값 모두 <= 0.05 일 때만. 셀 채택은 per_cell 게이트가 정한다
      family_p_binomial_def: P(k >= k_obs | n = tested, p = 0.05)   # S.family_p_binomial
      family_p_yblock_def: |
        k_ci_obs = 양방향 고속 CI90 하한>0 인 (셀,블록) 쌍 수(untestable 제외).
        draw d=1..D: ℓ=13 블록 순열 인덱스를 하나 뽑아 모든 셀에 동일 적용 → k_null(d) 를 같은 규칙으로 계산.
        family_p_yblock = #{d : k_null(d) >= k_ci_obs} / D.
        관측·귀무에 동일 결정규칙(_adopt_increment_fast, b=400)을 쓴다. k_obs 와 k_ci_obs 를 모두 기록한다.
      family_null_draws: 200
      family_null_seed: 20260910
      unimplemented_tools_prohibited: [BH, Holm, Bonferroni, Romano-Wolf, MCS, Westfall-Young]
      no_retroactive_application: rung-1~4 판정과 publication.holdout_family_p(0.008361)에 소급 적용하지 않는다
    degeneracy: |
      degeneracy_guard 를 블록별 usable 마스크로 제한된 반창에서 실행 시점 계산.
      사건 수 미달 → untestable_by_construction (채점·family 분모 제외, 페일클로즈).
      국면 수 미달 → 채점하되 episode_thin 라벨, 채택 시 adopted_episode_thin · 배선 불가.
    reliability_report: Murphy(rel/res/unc) + 신뢰도 곡선 — 채택 셀 한정 보고 의무, 판정 다리 아님

  stopping:
    S0_licence_unresolved: 실행 거부(예산 미소모)
    S1_ledger_duplicate: 재실행 거부(exit 2) — 평가 예산 단일 사용
    S2_hash_mismatch: 중단 · revision append · 결과 전 개정으로만 재개
    S4_all_measured_zero: 정상 종료(부정 결과) — 이 예산으로 추가 rung 시작 금지
    S5_any_adopted: 루프 정지 · 사용자 질문 · 홀드아웃 자동 진입 금지
    S6_null_leak_ge_3: 검정 기계 점검 모드 — 모든 채택 보류 후 보고
    S9_forbidden_window_read: 즉시 중단 · 산출물 폐기 · 보고

  negative_result_protocol:
    artifacts: [ladder_rung5e_external_vol.json, vol_experiments.jsonl 1행, 판정서, 계약 result 1줄, DECISIONS]
    measured_zero_must_be_split: [powered_zero(ewma_significantly_worse=true), underpowered(|d|<mde)]
    threshold_proximity_disclosure: true
    prohibited_conclusions:
      - 옵션 정보는 무가치하다
      - 무료 정보집합이 소진됐다        # 미시험 형상 변환(반분산·부호점프·VRP)이 남아 있다
      - 표본외에서도 영이다              # 홀드아웃 미열람
      - champion 이 옳음이 증명됐다      # GFC 지배·기후 기준선 창 의존
      - 매매·자금 배분 함의
    contract_line_282_correction: |
      rung4_macro_blocks.result 의 '무료 정보집합 소진' 은 과장 — 정확히는 '봉인 아카이브 내
      미사용 계열 소진'. 기존 계열의 형상 변환(상방/하방 반분산·부호점프변동·VRP log(VIX/RV21))은
      새 바이트 0·라이선스 노출 0·커버리지 1008/1006 으로 미시험 상태다.

  evaluation_budget: 1                      # evaluations_spent 4→5 (최대 8)
  backtest_windows_opened: 0                # 설계창 재분석만
  holdout_slots_consumed: 0                 # 잔여 2슬롯 무접촉
  sealed_read: false
  targets_changed: false

  prohibitions_inherited:
    - post_hoc_target_addition
    - gate_threshold_relaxation
    - null_redesign_after_results
    - p_permutation_null_as_negative_control
    - champion_on_climatology_alone
    - automatic_holdout_consumption
    - automatic_sealed_disclosure
    - mutate_v8_v2
  prohibitions_added:
    post_hoc_block_addition: true           # 블록 3개 고정 — 결과 후 계열·블록 추가 금지
    post_hoc_lag_change: true               # lag_sessions=1 단일값 — 두 지연 비교 후 선택 금지
    full_window_standardization: true       # z 는 적합창 내부에서만
    edit_collected_values: true             # 2010-04-27 포함 — 수집본 무수정
```

---

## 부록 B — 실행 체크리스트 (순서 고정)

```
[ ] 0. §0 차단 조건 3건 해소 · 사용자 승인 V13-D9(C2) 원문 수신 · approvals.jsonl 영수증 append
[ ] 1. 공식 API(api.stlouisfed.org)로 VXNCLS·VXVCLS 1회 재수집 → 기존 fredgraph 바이트와 값 대사
       불일치는 revision_seq+1 · supersedes 로 append (덮어쓰기 금지)
[ ] 2. fred_market_signals.yaml series_ids 개정 + source_registry.yaml:84 endpoint 교정
       + licenses.generated.md 재생성 (inventory drift 해소)
[ ] 3. 이 설계서 + 부록 A YAML 을 **결과 전 커밋** → 커밋 해시를 rung5e_external_vol_blocks.prereg_commit 에 기입
[ ] 4. 러너 작성 tools/v13_vol_rung5e_external.py
       - tools/v13_vol_rung4_macro.py 구조 복제 (build_blocks 만 교체)
       - 외부 스토어 어댑터: vol_indices.jsonl 을 dict 행으로 읽어 _series_by_date 에 그대로 투입
       - 원장 단일사용 가드(EXPERIMENT_LABEL 중복 시 exit 2) · 패널 2014-12-31 절단 단언
       - family_p_yblock 계산기 추가 (D=200, seed 20260910, 공유 순열)
[ ] 5. 실행: PYTHONUTF8=1 python tools/v13_vol_rung5e_external.py
[ ] 6. 결과 무관 원장 append (evaluation_index 5) · 계약 evaluations_spent 4→5
[ ] 7. 판정서 작성 (§7.1) · DECISIONS V13-D10 · 계약 result 1줄
[ ] 8. 라이브 카드·배선 변경 없음 확인 (이 rung 은 표시층을 건드리지 않는다)
```

**인코딩 주의**: Windows cp949 콘솔에서 한글 산출 스크립트가 `UnicodeEncodeError` 로 죽는다.
모든 실행에 `PYTHONUTF8=1` (또는 `PYTHONIOENCODING=utf-8`)을 붙인다. 이 실패를 "데이터 없음"으로
오독하지 않도록 러너는 종료코드를 명시적으로 반환한다.

---

## 부록 C — 이 문서가 인용한 실측의 출처

| 주장 | 출처 (저장소 경로 · 행) |
|---|---|
| VXN/VXV 설계창 행수 1008/1006 · 776/1006 | `data/timeseries_v13/external/vol_indices.jsonl` 직접 집계 (2026-09-10) |
| corr(VXN,VIX)=0.9879 · corr(spread,VIX)=−0.3373 · VXV −0.675 · VXD 0.9969 | `data/timeseries_v13/external/feature_design_inputs.json` (content_hash `6cdbe71b…`, labels_touched=false) |
| fredgraph 스크랩 = 약관 위반 | `docs/DECISIONS.md` 12-6 (2026-08-31) |
| FRED 경유 CBOE = "더 나쁨"(AI/ML·store 금지 추가) | `docs/DECISIONS.md` 12-5 (2026-08-31) |
| CBOE ToU §2 명시적 금지 | `docs/DECISIONS.md` 12-1 |
| VXNCLS 계약 범위 밖 | `data/contracts/fred_market_signals.yaml` `series_ids` |
| 라이선스 대장 stale (확인일 2026-08-01) | `docs/generated/licenses.generated.md` 6행·17행 |
| V9_E6 VXN 스프레드 채택 실패 −0.019% | `docs/review/V12_S1_1_RECOMPUTE_VERDICT.md` 126행 |
| V9 자동 기각 한도 0.85 · 원시 Δlog(VXN) ρ=0.918 | `data/contracts/multivariate_timeseries_v9.yaml` 143·157행 |
| 게이트 산술·부트스트랩·적합기 | `tools/v13_vol_run.py` 19-21·61-89 · `tools/v13_vol_rung3_pb.py` 46-88 |
| rung-4 구조(27검정·예산 1·family) | `data/contracts/multivariate_timeseries_v13_vol.yaml` `rung4_macro_blocks` · `tools/v13_vol_rung4_macro.py` |
| 퇴화 가드 임계·설계창 실패 6셀 | 같은 계약 `degeneracy_guard` · `src/ai_fc/timeseries_v13/scoring.py:158` |
| 홀드아웃 3/9 통과 · family P 0.008361 | 같은 계약 `publication` · `data/timeseries_v13/ledgers/holdout_scorings.jsonl` |
| 예산 4/8 | `data/timeseries_v13/ledgers/vol_experiments.jsonl` 4행 |

**미검증 표기**: ALFRED 빈티지 대조 실측(§4.2·§4.5)은 선행 조사 세션의 측정이며 그 원자료는
세션 scratchpad 에만 있고 저장소에 커밋돼 있지 않다 — 실행 단계에서 §부록 B 1번(공식 API 재수집·대사)이
이 측정을 저장소 안에서 재현·고정해야 한다. 그 전까지 §4.2·§4.5 의 수치는 `[저장소 외 측정]` 이다.
