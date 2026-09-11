# 증거 부록 — 2026-09-11_nvda-rev-miss-fq3-2027_r1

> 리서치 서브에이전트 보고서 원문. 불변 — 수정 금지.


> 출처 등급 분포 (WS7): T1 1 · T2 1 · T3 4 · T4 1 · 미등재 7 — primary_ratio(T1+T2) **14%**


---

## [general] (출처 68개, $1.13)

조사를 종합합니다. (웹 검색 도구의 호출 한도에 걸려 일부 base rate 재확인은 제한되었으며, 해당 항목은 명시합니다.)

---

# 리서치 보고서: NVDA Q3 FY2027 매출 컨센서스 하회(-1% 초과) 확률 판정용

## 0. 질문 구조 요약
- **YES 조건**: R < C × 0.99 (최초 8-K Ex-99.1 공시 총매출 R이, 발표 직전 스냅샷 컨센서스 C의 0.99배 미만). 즉 **컨센서스를 1% 초과 하회**하면 YES.
- 판정일 기한 2026-11-25. 스냅샷 규칙은 상방 문항(ge6pct)과 공유.

## 1. 판정 기준값·스냅샷 후보 (C 및 관련 앵커)

**NVIDIA 자체 Q3 FY27 가이던스 (공식, 최상위 등급):**
- 
NVIDIA는 Q3 매출을 $108.0십억 ±2%로 예상하며, 이는 $105.84십억~$110.16십억 범위를 의미
한다. [source: stockmarkethours.org / NVIDIA 8-K, 2026-08-26]
- 
이 아웃룩은 중국 데이터센터 컴퓨트 매출을 포함하지 않는다고 가정
. [source: webull.com, 2026-08-26]

**컨센서스 후보(스냅샷 대상, C):**
- 
Q3 FY27(10월 분기) 컨센서스 매출은 $103.8십억
 (yfinance, 41개 애널리스트, 8/24 기준). [source: rexshares.com, 2026-08-26]
- 
가이던스 발표 시점 애널리스트들은 $104.2십억 가이던스를 기대
(LSEG, CNBC 집계). [source: cnbc.com, 2026-08-26]
- 발표 후 상향: 
NVIDIA의 매출 예상치는 108.45십억, 다음 실적 발표는 2026년 11월 25일
. [source: investing.com, 2026-08-26]

→ **C는 발표 직전 스냅샷 시 $104B~$110B 범위로 상향 이동 중**이며, NVIDIA 가이던스 중앙값($108B)에 수렴/근접. C×0.99 임계값은 대략 **$103B~$109B** 구간이 된다.

## 2. Base rate (매출의 컨센서스 대비 방향/폭)

최근 분기 실제 매출 vs 컨센서스(모두 **상회**):
- 
Q3 FY26: 매출 $57.0십억 vs 컨센서스 $55.2십억, 3.3% 상회
. [source: futurumgroup.com, 2025-11-25]
- 
Q1 FY27: 매출 $81.62십억 vs 애널리스트 추정 $78.84십억, 3.5% 상회
. [source: yahoo/finance, 2026-05-20]
- 
Q2 FY27: 매출 $96.22십억 vs LSEG 컨센서스 $92.17십억, 약 $4.05십억 상회
 (≈+4.4%). [source: webull.com, 2026-08-26]
- 장기 추세: 
NVIDIA는 지난 24개 분기 중 22개 분기에서 월가 컨센서스(EPS)를 상회
. [source: fool.com, 2026-08-25]

자체 가이던스 대비도 지속적 상회: 
Q2 FY27 매출 $96.221십억은 이전 $91.0십억 가이던스 중앙값을 $5.221십억 상회
. [source: stockmarkethours.org, 2026-08-26]

→ **매출을 1% 초과 하회한 사례는 최근 3년(FY24~FY27) 실질적으로 전무.** 대규모 매출 미스는 2022년 게이밍/암호화폐 붕괴기(FY23 상반기)에 국한되며, 이번 세션 검색 한도로 해당 수치 재확인은 **NOT FOUND**(추가 검증 권고). 결론적으로 **base rate상 >1% 하회 빈도는 ≈0~1/24 (약 4% 이하)**.

## 3. 최신 상태·이벤트 캘린더
- **직전 분기(Q2 FY27) 실적**: 
매출 $96.22십억, 전년比 106% 증가, 컨센서스 $92.17십억 상회, 비GAAP EPS $2.22
. [source: webull.com, 2026-08-26]
- **발표일**: 
NVDA 실적 발표일은 2026-11-25 장 마감 후(확정)
. [source: tipranks.com, 2026-08-26] (단, Wall Street Horizon은 11/17로 예측 표기 — 
NVDA 다음 실적일 2026-11-17 장마감 후로 확정 표기
 [source: wallstreethorizon.com] — **날짜 이견 존재**, 다수 소스는 11/25.)
- **FY28 전망**: 
CFO Kress는 FY2028 매출 성장률 약 70%를 예상(애널리스트 기대 44%), 단 공급제약적 전망이라 언급
. [source: cnbc.com, 2026-08-26]

## 4. 순풍(YES=하회 방향) 요인
- **컨센서스가 가이던스 중앙값 이상으로 상향**: C가 $108B+로 오르면 임계값(C×0.99≈$107B)이 가이던스 중앙값에 근접해, 소폭의 실적 부진만으로도 YES 가능.
- **공급제약·메모리 비용**: 
경영진이 FY28 70% 성장을 전망했으나 메모리 비용과 공급제약이 완전한 수요 충족을 제한한다고 경고
. [source: investing.com, 2026-08-26] Vera Rubin 램프 초기 및 
Q3 성장은 주로 ACIE 고객이 견인하고 하이퍼스케일 재가속은 Q4로 예상
되어 Q3 시퀀셜 상승폭 리스크. [source: webull.com]
- **중국 매출 제외**로 상방 버퍼 축소(가이던스에 China 미포함).

## 5. 역풍(NO=상회/부합 방향) 요인
- **강력한 beat 기록**: 최근 매 분기 매출을 3.3~4.5% 상회, 24개 분기 중 22개 상회(§2).
- **수요 초과·품절 상태**: 
"Blackwell 판매가 폭발적이고 클라우드 GPU가 품절"
(Jensen Huang). [source: nvidianews, Q3 FY26]
- **가이던스 상회 관행**: 자체 중앙값을 매번 $5B 내외 상회(§2). 임계값이 $103.8B 컨센서스 기준이면 $102.8B로, 가이던스 하단($105.84B)보다도 낮아 YES 성립이 매우 어려움.

## 6. 종합 판정 포인트
- **핵심 변수 = 스냅샷 C의 위치**. C가 $103.8B 부근(구 컨센서스)이면 임계값 $102.8B로 YES 가능성 극히 낮음. C가 $108B+로 상향되면 임계값이 가이던스 중앙값에 근접해 YES 확률이 다소 상승하나, 과거 매출이 가이던스 중앙값을 하회한 전례가 거의 없음.
- Base rate + 최신 수요/공급 여건상 **>1% 하회 확률은 낮음(대략 한 자릿수~10%대 초반)**으로 평가됨.

**미확인/주의**: ① 발표 직전 최종 스냅샷 C값(11월 실시간) — 판정일 전 재확인 필수. ② 발표일 11/25 vs 11/17 이견. ③ 2022년 대규모 매출 미스 수치 = 본 세션 **NOT FOUND**(추가 검증 요).

---

## [devil] (출처 67개, $0.65)

# ★데블스 애드버킷 보고서: NVIDIA Q3 FY2027 총매출 "1% 이상 미스(R<0.99C)" 확률

## 0. 형성될 컨센서스 결론(내가 반박할 대상)
LLM/시장이 도달할 기본값은 "**미스 확률 극히 낮음(대략 5~10%)**"이다. 근거는 자명해 보인다: 
NVIDIA reported revenue of $96.22 billion for fiscal Q2 2027, 5.7% above the company's own guide, and revenue beat consensus by +4.5%
 [source: rexshares.com, 2026-08-26]. 나는 이 "미스 없음" 결론이 **과신**임을 논증한다.

---

## 1. 반대 방향 증거·데이터

**(A) 임계값 1%는 NVIDIA 가이던스 밴드(±2%)보다 작다 — 미스는 산술적으로 쉽다.**
Q3 가이던스는 
The company expects third-quarter revenue of $108.0 billion, plus or minus 2%, compared with analysts' average estimate of $104.19 billion, according to data compiled by LSEG
 [source: virginiabusiness.com, 2026-08-27]. 가이드 하단은 **$105.84B**(−2%)이다. 만약 판정 스냅샷 컨센서스 C가 가이드에 수렴해 $108B 부근이면, 0.99×C ≈ **$106.9B**. 즉 NVIDIA가 **자기 가이드 밴드 하단(−2%)에 착지하기만 해도 YES**가 성립한다. 임계선이 밴드 폭보다 좁다는 점이 핵심 — "미스"는 극단 시나리오가 아니라 밴드 내부 사건이다.

**(B) 공급(HBM/메모리) 병목이 상방이 아니라 하방 리스크다.**
수요가 아니라 공급이 매출을 캡(cap)할 수 있다. 경영진 스스로 
"Memory scarcity today is being driven in large part by the AI buildout itself," and Nvidia said it expects gross margin to decline and bottom out in the fourth quarter of fiscal 2027, in the range of 71% to 72%, partially due to memory prices
 [source: cnbc.com, 2026-08-26]. 업계 데이터도 
HBM sold out through 2026, with NVIDIA cutting gaming GPU production 30-40% in H1 2026 due to GDDR7 constraints
 [source: introl.com, 2026-01-03]. 이미 감산이 진행 중이며, 램프 중인 Rubin/신제품 수율·메모리 조달이 어긋나면 매출은 수요가 아니라 부품에 의해 결정된다.

**(C) 상향 리비전 모멘텀 둔화.**

The pace of upward revisions has moderated since last quarter, and B-series revenue expectations have declined by ~5% since March
 [source: spglobal.com, 2026-08]. 최고 성장 국면의 정점 신호가 축적되면 애널리스트가 **가이드 위로 컨센서스를 밀어 올릴 때**(예: C를 $109~110B로) 단순 가이드 부합 프린트도 −1% 미스로 뒤집힌다.

---

## 2. "이 예측이 크게 틀렸다"고 가정할 때 가장 그럴듯한 경로
가장 개연성 높은 YES 경로는 **드라마틱한 수요 붕괴가 아니라 "컨센서스 인플레이션 + 공급 캡"의 협공**이다:
1. 가이드($108B, 컨센서스 대비 상회)에 흥분한 애널리스트들이 스냅샷 C를 **$108~110B로 상향**.
2. 메모리/HBM 조달 차질 또는 Rubin 램프 지연으로 실제 출하가 **가이드 중하단($106~107B)**에 착지.
3. R($106.5B) < 0.99×C($108.5B→$107.4B) → **YES**.
이 경로는 "역성장"이 필요 없다. YoY +100% 성장 유지하면서도 성립한다. 즉 판정은 **절대 성장률이 아니라 상대적 컨센서스 대비 3~4% 언더슈트**만 요구한다.

---

## 3. 반대 방향 역사적 선례 (결정적)
"NVIDIA는 자기 가이드를 안 빗나간다"는 명제는 거짓이다. 직접 선례:

NVIDIA Announces Preliminary Financial Results for Second Quarter Fiscal 2023 — preliminary second quarter revenue of $6.70 billion versus outlook of $8.10 billion, shortfall versus outlook primarily driven by weaker Gaming revenue
 [source: SEC 8-K, sec.gov, FY2022]. 이는 자기 가이드 대비 **약 −17%**의 대형 미스다. 또 2022년: 
Nvidia says gaming market conditions are 'challenging,' Q3 forecast misses
 [source: cnbc.com, 2022-08-25]. 그리고 FY2019 Q4엔 
quarterly revenue of $2.21 billion, down 24 percent from a year ago
 [source: SEC 8-K, sec.gov]. **수요 세그먼트가 순식간에 반전한 전례가 반복적으로 존재**한다 — 당시엔 게이밍/크립토, 이번엔 하이퍼스케일 캡엑스가 후보다.

---

## 4. 반대의 반대 (컨센서스가 옳을 최강 근거 1개)
가장 강력한 NO 근거: **자기 가이드 초과의 압도적 연속성.** 
That is the fourteenth consecutive quarter above the company's own outlook, and the guide was $108.0B for Q3 FY27
 [source: rexshares.com, 2026-08-26]. 14분기 연속, 통상 +4~5% 초과이며 
Huang said "demand is accelerating," and guided fiscal 2028 revenue growth of 70%, well above the 44% expected by analysts
 [source: fortune.com, 2026-08-26]. 이 구조적 초과 달성 관성이 유지되면 R은 오히려 **C를 상회**해 YES는 물론 경계값에도 못 미친다. 2022년식 붕괴는 재고·크립토 요인이었고, 현재 백로그·계약형 하이퍼스케일 수요는 성격이 다르다.

---

## 5. 판정용 확정 수치 요약
- Q3 FY27 회사 가이드: **$108.0B ±2%** (밴드 $105.84B~$110.16B) [source: virginiabusiness.com, 2026-08-27]
- 가이드 발표 시점 Q3 사전 컨센서스: 
$104.2B (LSEG/Visible Alpha)
 — **주의: 이는 8월 가이드 이전 값이며, 11월 판정 스냅샷 C는 상향 revised될 가능성 높음** [source: stocksmarts.substack.com, 2026-09]
- 최종 스냅샷 C(발표 직전) 실측값: **NOT FOUND** (2026-11 예정; 상방 문항과 공유)
- 판정 소스: SEC EDGAR 8-K Ex-99.1 (CIK 0001045810), Q2 실측도 동일 양식 확인됨.

**데블스 애드버킷 결론:** "미스 확률 극소"는 과신이다. 임계값(1%)이 가이드 밴드(2%)보다 좁고, 공급 병목·컨센서스 인플레이션·역사적 대형 미스 선례가 겹친다. YES 확률을 시장 기본값보다 **상향 조정**할 것을 권고한다.