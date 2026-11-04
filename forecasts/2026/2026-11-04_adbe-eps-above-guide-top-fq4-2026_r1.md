---
forecast_id: 2026-11-04_adbe-eps-above-guide-top-fq4-2026_r1
question_id: adbe-eps-above-guide-top-fq4-2026
question_snapshot: Adobe가 FQ4 2026 실적에서 보고하는 non-GAAP 희석 EPS가, 회사가 직전 분기(FQ3 2026) 실적 발표에서 제시한 FQ4 non-GAAP EPS 가이던스 범위의 상단을 초과할 확률은?
timestamp: 2026-11-04 19:14 KST
phase: P1
model: claude-opus-4-8
provider: anthropic
model_snapshot: claude-opus-4-8
provider_version: reasoning_core_v1_1
prompt_version: reasoning_core_v1_1
probability: 38
ci80: [25, 55]
window_end: null
snapshots: {}
market_implied: null
edge: null
research_status: ok_low_primary
sources_count: 151
method: p1-pipeline/2agents
cost_usd: 2.9582
ensemble_runs: [38]
divergence: null
shadow_extremized: 30
digest_hash: null
digest_inputs: null
pipeline_tier: standard
registered_tier: standard
ml_divergence_pp: null
divergence_note: null
divergence_class: null
research_quality:
  sources: {t1: 1, t2: 0, t3: 6, t4: 0, unknown: 7}
  n_urls: 14
  primary_ratio: 0.071
---

## [0] 질문 검증
기한(2026-12-09 발표, 12-18 내)·임계값(G_high=$6.35, 엄격 부등호, 경계값 NO)·판정기준(최초 공시 non-GAAP 희석 EPS > 가이던스 상단)이 모두 명확. EPS 가이던스는 범위($6.30–6.35)로 제시되어 void 조건 미해당. 해소가능.

## [1] Outside View — base rate (anchor: 45%)
참조 클래스: 미국 메가캡 소프트웨어 기업이 직전 분기에 제시한 자사 non-GAAP EPS 가이던스 '범위 상단'을 실제치가 초과하는 사례(컨센서스 상회가 아닌 자사 가이던스 상단 초과 기준)

- Adobe FQ3 2026: 가이던스 상단 $6.10 → 실제 $6.13, 상단 +$0.03 초과(YES) [source: alphaspread.com Q3 2026]
- 자사 가이던스 상단 초과 빈도는 '컨센서스 상회' 빈도보다 구조적으로 현저히 낮음 — 경영진이 상단을 달성가능-공격적 수준에 설정하므로 범위 내 상단 근처 착지가 흔함 [devil 보고, 미검증]
- FQ2/FQ1 2026은 컨센서스 상회만 확정, 가이던스 상단 대비 쌍은 NOT FOUND — 공시 확정 상단초과 사례는 FQ3 2026 1건뿐 [source: 리서치 §2]

## [2] Inside View — 보정
| 증거 | 방향 | 조정 |
|---|---|---|
| Q4 컨센서스 EPS ≈ $6.32–6.33으로 가이던스 상단 $6.35보다 낮음 → 시장조차 상단 초과를 기본 시나리오로 보지 않음 [source: benzinga.com 2026-09-11] | ↓ | −8%p |
| 경영진이 Q4 FX 역풍을 유일한 증분 리스크로 명시 ('FX가 4분기 실적 압박') [source: investing.com Q3 2026 transcript] | ↓ | −4%p |
| 가이던스 범위가 매우 좁고($0.05) 직전 분기도 상단 +$0.03 초과, FQ3 중 ~9.5M주 자사주 매입으로 분모 축소 EPS 상방 [source: alphaspread.com; finance.yahoo.com] | ↑ | +6%p |
| AI-first ARR $650M(+150%+ YoY)·Q4가 계절적으로 가장 강한 분기 [source: investing.com] | ↑ | +3%p |
| Topaz Labs 인수 종결 + CEO 교체(12/1) 관련 일회성 비용/회계 변동 불확실성 [source: tickeron.com 2026-10] | ↓ | −2%p |
| 프리모템: 가이던스 상단 근처 '범위 내 착지(NO)'가 구조적으로 가장 흔한 결과이며 경계값=NO 규칙이 YES 난이도를 높임 [devil 보고] | ↓ | −2%p |

## [3] 분해 트리
YES = (A > $6.35). 필요조건 결합: (1) 영업 호조로 중심추정 $6.32–6.33을 $6.35 초과로 끌어올림(P≈0.42) AND (2) FX·인수·세율 악재가 상단 초과 마진을 잠식하지 않음(P≈0.9 조건부). 결합 ≈ 0.38. [2]의 조정 결과(38%)와 정합.

## [4] Premortem — 이 예측이 크게 틀렸다면
1. 컨센서스($6.32–6.33)가 정확해 실제치가 상단 미달 또는 상단에 '딱 착지'($6.35=NO)로 끝남
2. FX 달러 강세 재개로 매출·마진 동시 압박, 좁은 초과 마진이 쉽게 소멸
3. AI 추론 인프라·마케팅 등 non-GAAP에서 조정되지 않는 비용 증가로 영업레버리지 둔화

## [5] 최종 출력
- **최종 확률: 38%** (80% CI: 25~55%)
- **핵심 근거**:
  1. Adobe는 보수적 가이던스·반복 상단 소폭 초과 패턴(직전 FQ3 +$0.03)과 자사주 매입·강한 Q4 계절성이 순풍
  2. 그러나 컨센서스 $6.32–6.33이 상단 $6.35보다 낮고 FX 역풍이 명시돼, 시장은 상단 초과를 기본 시나리오로 보지 않음
  3. 초과 마진이 얇고 경계값=NO 규칙 탓에 '범위 내 상단 근처 착지' 시나리오가 확률을 깎음
- **관찰 지표**:
  1. FQ4 컨센서스 EPS 추정치의 상향/하향 흐름(컨센이 $6.35 넘어서면 YES 확률 상승)
  2. 달러 지수(DXY) 및 EUR/USD 등 Q4 환율 추세 — FX 역풍 강도

> **P1 참고 의견 — 자금 결정의 단독 근거 아님** (P3 게이트: 해소 50문항+ & Brier < 0.18 통과 전).

## [미검증] 항목
- FY2025 이전 분기 '가이던스 상단 vs 실제' 쌍은 웹서치 한도 소진으로 NOT FOUND — 상단 초과 베이스레이트가 단일 확정 사례(FQ3 2026)에 크게 의존
- FQ2/FQ1 2026 가이던스 상단 정확값 NOT FOUND
- 데블스 보고의 역사적 '상단 미달 착지 빈도' 및 sandbagging 패턴은 모두 미검증 정성 논거
- 임계 z: 중심 $6.325, 임계 $6.35, 차 $0.025, σ 추정 ~$0.06 → z≈0.4 (<0.7, 사구간) — 확률을 사구간 밖으로 밀지 않고 정직 확률 유지, 기록용

## 리서치 구성
general(출처 76), devil(출처 75) — 증거 부록: `2026-11-04_adbe-eps-above-guide-top-fq4-2026_r1_evidence.md`
