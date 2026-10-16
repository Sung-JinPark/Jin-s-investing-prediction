# [종결 심사 + P5 설계서] NASDAQ MTS / V13-VOL P0~P4 — 2026-09-10

> 대상: `NASDAQ_MTS_P0_P4_CLOSURE_REVIEW_20260909`(100파일). 검토자: 외부 Claude(FACTS.json을 정본으로 재계산).
> 규율: 홀드아웃·봉인 미열람(팩에 없음) · 무수정 · 재계산·판정·설계만. 팩 외 사실은 `[팩 외 — 확인 필요]`.

## 0. 총평
P0~P4는 이 계보에서 가장 규율 있는 종결이다 — 잠정답·확신도·자기 오류(ERRATA 16건·CRITIQUE 18건)를 검토관보다 먼저 적었고, 판정 기계 자체를 진단(셀 종속·기후상수 정합·채점경로 괴리)했다. 아래 12문 판정 중 **번복 2·수정 4·승인 6**. 핵심 재해석 하나: 홀드아웃은 "3/9 부분 통과"가 아니라 **"3 통과 · 3 실패 · 3 판정불가"**로 읽어야 하며, 그 판정불가 라벨의 적법성은 오직 **가드의 사전등록 시점**에 달려 있다.

## 1. 12문 판정 (잠정답 대비)

| Q | 잠정답 | 판정 | 근거·수정 |
|---|---|---|---|
| RQ1 홀드아웃 기록 | 예(partial) | **수정** | 헤드라인을 "partial 3/9" → **"통과 3(rv_h5 .828·rv_h21 .600·vix25_h21 .446, 음성대조 ≤.08) / 실패 3(vix25_h5 G4 .125 근소·vix25_h63 G1·rv_h63 G4 .805) / 판정불가 3(vix30 전 지평: 2015–18 에피소드 3회, 사건 25·57·141)"**. 스킬 라벨 "당일 수준의 지속" 한정 동의. family P는 헤드라인에서 제거(RQ3) |
| RQ2 동결 기후 기준선 | A(유지) | **승인+개정** | 재채점용 슬롯 추가 소모는 결과 후 기준선 교체 = 위반 → 기각. 단 vix30_h5 G4 **1.000**·rv_h63 .805는 "동결 기후 대비 우위가 기저율 이동의 산물"임을 실증. **다음 계약부터** `rolling_climatology_pit`(확장창)을 **병기 기준선**으로 사전등록 — 현 판정 불변 |
| RQ3 종속 하 family P | C(참고값) | **수정** | 이항 .0084는 폐기하지 말되 **종속 조정 .0415와 나란히, 후자를 대표값**으로. 다음 슬롯(RQA-Q13)은 **9셀 결합 y-블록 순열(Westfall–Young min-P)**로 family 검정 사전등록 — 셀 상관 +0.255를 귀무 안에 보존 |
| RQ4 에피소드 가드 | A(옳은 교정) | **조건부** | `episode_thin`(runs<5)이 **홀드아웃 실행 커밋보다 앞서 사전등록**됐으면 판정불가 라벨 적법. 체인 문서는 rung-4 커밋(14:12)이 승인(14:16)보다 앞선 흠결을 자인 — 가드 자체의 선행성은 `[팩 외 — PREREG_CHAIN 시각 확인 필요]`. 미선행이면 "사후 진단, 공식 판정=fail 유지" |
| RQ5 G4=1.000 해석 | 예(약하게) | **승인** | 라벨 셔플이 기저율을 보존하므로 G1 마진 전부가 주변분포 효과 — "라벨 연관에서 오지 않는다"는 정확. 표현은 "이 셀의 G1 통과는 증거가 아니다"로 |
| RQ6 무료 정보집합 소진 | B(과장) | **번복(과장 확인)** | rung-4는 macro 0/27. **옵션 지수 형상(VVIX·SKEW·VIX3M·VIX9D)은 미검정** `[팩 외 — rung-4 피처 목록 확인]` — 문헌 사전확률 최고인 VVIX가 남았으므로 "소진" 표현 삭제 |
| RQ7 measured_zero 27/27 | B(정정) | **승인** | measured_zero = (사전 MDE < 기대효과) ∧ (사후 MDE 정합) 두 연언지 충족 셀만. 미충족은 `underpowered` |
| RQ8 우선순위 | C우선·D병행·A보류 | **수정** | C(전진 시간)+D 동의. 단 A를 전면 보류 말고 **VVIX 1슬롯만**(≤3회, $0) 허용 — 남은 최고 사전확률 검정 |
| RQ9 표시 정직성 | 예+구멍1 | **승인+구체화** | 구멍 = 카드가 통과/실패/판정불가를 구분 못함. **셀별 배지를 원장 파생(산문 금지)**으로 |
| RQ10 종결 시점 | T1 정본 | **승인+T7** | T7 추가: "라이브 전진 60원점 게이트를 통과 3셀 중 2셀 이상이 실패하면 종결" |
| RQ11 배선 | C | **승인** | 검증 셀에 질문을 맞춘다: rv_h5/h21 → "RV>θ within 5/21d", vix25_h21 → "VIX≥25 within 21d". `vix-25-90d`(h63)는 **미검증이라 배선 금지** |
| RQ12-1 PAV·ML게이트 | 유보 | **판정** | PAV(cross-fit isotonic)는 LLM 원장 보정이 아니므로 게이트 문면 밖 — 그러나 학습 단조맵이므로 **예외를 DECISIONS에 명문화**: (a) 판정(G1/G4)은 raw PB로만 (b) 표시 파생층 한정 (c) 파라미터 수·cross-fit 로그 (d) 해소 100+ 전 LLM 원장 적용 금지 재확인 |
| RQ12-2 기계판독 로드맵 | B | **승인** | 설계도 §2 손기록이 당일 낡은 것이 증거. `roadmap_status.py` 산출을 정본, 설계도 §2는 인용만 |
| RQA-Q14 예산 | 4/8 vs 5/8 | **4/8** | 진단(per-origin csv·종속·정합)은 설계창 **재채점**이지 새 백테스트 아님 — 예산 미소모. 단 "설계창을 다시 봤다"는 사실은 누적 채굴수에 +0(재분석)로 기록 |

## 2. 부정·긍정의 정직한 요약
- **긍정**: 캠페인 최초로 **홀드아웃(2015–18)에서 표본외 스킬 3셀 확정** — 전부 단·중기(h5/h21)·지속성. 라이브 base rate 공급의 근거로 충분.
- **부정**: h63 전 셀 실패/판정불가(지속성 감쇠 + 기저율 이동), VIX30 사건 희소로 판정불가, macro 0/27. 프로그램 완성 조건(C0~C4) 중 **C0(기계 건전성)에 2건 흠결** — 동결 기후 기준선의 기저율 취약성, family P 종속 무시.

## 3. P5~P7 설계 (계약 YAML 이식 가능)

### P5 · 홀드아웃 결과 정식화 + 기계 수리 (1주, $0, 승인 1)
```yaml
p5_prereg:
  holdout_record: {pass: [rv_h5, rv_h21, vix25_h21], fail: [vix25_h5, vix25_h63, rv_h63], untestable: [vix30_h5, vix30_h21, vix30_h63], untestable_valid_iff: guard_commit_precedes_holdout_run}
  family_p: {headline: dependence_adjusted_0.0415, reference: binomial_0.0084, next_slot_method: joint_y_block_permutation_minP}
  baselines_next: [design_frozen_climatology, rolling_climatology_pit, persistence_pb]
  labels: {measured_zero_requires: [mde_pre_lt_expected, mde_post_consistent], else: underpowered}
  pav_exception: {judgment_uses_raw_pb: true, display_only: true, params_logged: true, decisions_entry: required}
  roadmap_state: {source: tools/roadmap_status.py, handwritten_state_forbidden: true}
```
정지: 가드 선행성 불충족 시 판정불가 3셀을 fail로 되돌리고 family P 재계산(3/9 유지, k_obs=3 불변).

### P6 · 배선 + 케이던스 (1~2주, $0, 승인 V13-D6·S7-D1)
- 배선: 통과 3셀만 → EXIT 질문 base rate **표시**(산술 결합 0). 카드 셀별 배지 = 원장 파생(pass/fail/untestable/live-forward-n).
- V8 섀도 정지 해소: 신선도 HOLD는 설계된 fail-closed — **원점 케이던스 일간 + 입력 신선도 파이프라인 점검**(NASDAQCOM·VIX 갱신 체인). 케이던스 변경은 모델 무변경 계약 좌표(S7-D1).
- 라이브 전진 게이트: 셀당 성숙 60원점, 미달 시 자동 강등·재무장 없음. **T7** 종결 트리거 등록.

### P7 · 잔여 $0 검정 1슬롯 + 옵션 데이터 조건부 (2~5주)
- **VVIX 형상 rung**(≤3회): logit[PB + β·VVIX_z], 9셀, 결합 y-블록 순열 family, BH q=.10, 병기 기준선 3종. 기대: vix25/vix30 h5·h21에서만 여지, 사전확률 채택 25~35%.
- CBOE QQQ 회신(발송 완료) → 구매는 VVIX rung 결과에 조건화(채택 0이면 "지수 형상은 PB에 흡수" 확정, 표면 데이터 기대가치 하향).
- 홀드아웃 2/3 슬롯: VVIX 채택 셀 존재 시에만, 결합 순열 family로 사전등록 후 1회.

## 4. 사용자 결정
| ID | 내용 | 권고 |
|---|---|---|
| P5-D1 | 가드 선행성 판정에 따른 판정불가 라벨 확정 | 체인 시각 확인 후 |
| P5-D2 | PAV 예외 DECISIONS 등재 | 승인 |
| V13-D6 | 통과 3셀 배선 | 승인(h63·VIX30 배선 금지) |
| S7-D1 | V8 섀도 일간 케이던스 | 승인 |
| P7-D1 | VVIX rung 1슬롯 | 승인(예산 3) |
| P7-D2 | CBOE 구매 | VVIX 결과 조건부 |

*끝. 판정·설계만 수행. 홀드아웃·봉인 미열람, 봉인 무수정, push·구매 없음.*
