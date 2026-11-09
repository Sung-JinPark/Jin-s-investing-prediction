---
forecast_id: 2026-11-09_avgo-eps-surprise-ge5pct-fq4-2026_r1
question_id: avgo-eps-surprise-ge5pct-fq4-2026
question_snapshot: Broadcom이 FQ4 2026 실적에서 보고하는 non-GAAP 희석 EPS가, 발표 직전 스냅샷된 컨센서스의 1.05배 이상일 확률은?
timestamp: 2026-11-09 13:55 KST
phase: P1
model: claude-opus-4-8
provider: anthropic
model_snapshot: claude-opus-4-8
provider_version: reasoning_core_v1_1
prompt_version: reasoning_core_v1_1
probability: 17
ci80: [10, 30]
window_end: null
snapshots: {}
market_implied: null
edge: null
research_status: ok
sources_count: 149
method: p1-pipeline/2agents
cost_usd: 2.3024
ensemble_runs: [17]
divergence: null
shadow_extremized: 6
digest_hash: b87035d004cdafd338a2f39a71593cf70b6267e96b172de4e510610733168731
digest_inputs: {ml_run_ts: '2026-11-07T10:32:38', context_run_ts: '2026-11-05T19:20:59', ml_history_file: data/ml_history/, market: null}
pipeline_tier: standard
registered_tier: standard
ml_divergence_pp: null
divergence_note: null
divergence_class: null
research_quality:
  sources: {t1: 2, t2: 0, t3: 1, t4: 0, unknown: 3}
  n_urls: 6
  primary_ratio: 0.333
---

## [0] 질문 검증
기한(FQ4 2026 실적, ≈2026-12-10~11 발표, 2026-12-18 이전)·임계값(A≥C×1.05)·판정기준(8-K Ex-99.1 non-GAAP 희석 EPS vs 정의 정합 컨센 중앙값)이 명확. 경계값은 YES, 0개 제공사면 void. 해소가능.

## [1] Outside View — base rate (anchor: 20%)
참조 클래스: 대형 반도체·규율형 가이던스 기업의 분기 non-GAAP EPS 서프라이즈가 +5% 이상인 비율 (특히 Broadcom처럼 가이던스를 타이트하게 제시하고 셀사이드가 가이던스에 수렴하는 성숙주)

- 대형주 셀사이드 추정은 발표 직전 가이던스에 수렴해 서프라이즈 폭이 통상 1~3%로 압축됨 — +5% 이상 비트는 꼬리 사건 [general/devil 리서치 정성 판단, 수치 NOT FOUND]
- AVGO는 '꾸준히 소폭 비트' 패턴 (예: Q1 FY25 non-GAAP EPS $1.60으로 컨센 상회, 폭은 작음) [source: GuruFocus 2025-03]
- AI 사이클 초기 반도체는 간헐적으로 두 자릿수% 매출 상회로 EPS가 ×1.05 초과한 분기 존재 [devil 리서치, 구체수치 NOT FOUND]

## [2] Inside View — 보정
| 증거 | 방향 | 조정 |
|---|---|---|
| AI XPU/네트워킹 수주 풀인·신규 커스텀 실리콘 램프가 보수적 가이던스를 크게 상회하면 EPS 레버리지(증분마진·자사주 희석감소)로 증폭 [devil 리서치] | ↑ | +5%p |
| 성숙 대형주 특성상 셀사이드가 발표 직전 추정을 가이던스에 밀착시켜 서프라이즈 폭이 구조적으로 1~3%로 압축 [general/devil 리서치] | ↓ | −6%p |
| [프리모템] 정의 정합성 규칙이 C를 '회사 기준 그 EPS'를 가장 정밀 추정한 중앙값으로 고정 → 분모가 정확해져 ×1.05 초과가 더 어려워짐 [devil §6] | ↓ | −2%p |

## [3] 분해 트리
YES = (매출이 가이던스를 유의미 상회) AND (그 상회가 EPS에서 ≥5%로 증폭) AND (정합 컨센 C가 낮지 않게 형성). 매출 유의 상회 확률 ~35%, 그 중 EPS +5% 증폭 전환 ~45%, C가 보수적이어서 문턱 완화 보정 ~1.1배 → 0.35×0.45×1.1 ≈ 0.17. [2]의 조정 결과(17%)와 정합.

## [4] Premortem — 이 예측이 크게 틀렸다면
1. AI 대형 고객(제3·4 고객) 물량 조기 인식 + 공격적 자사주 매입으로 희석주식수 급감 → 매출 소폭 상회가 EPS 두 자릿수 초반% 상회로 증폭되어 예상외 YES
2. 정합 제공사 축소로 C가 보수적으로 고정되며 ×1.05 문턱이 동반 하향 → NO 예측이 틀림
3. 반대로 가이던스가 이미 AI 낙관 선반영 → 컨센이 가이던스 상회 형성 → 실제치 가이던스 부합해도 미스 처리, NO 쪽이 더 견고

## [5] 최종 출력
- **최종 확률: 17%** (80% CI: 10~30%)
- **핵심 근거**:
  1. Broadcom은 규율형 가이던스+셀사이드 수렴으로 서프라이즈 폭이 1~3%에 압축되어 ≥5% 비트는 구조적 꼬리 사건
  2. 정의 정합성 판정규칙이 C를 회사 기준에 정밀 정렬시켜 분모가 정확해지므로 ×1.05 초과가 더 어려움
  3. 다만 AI XPU 비선형 업사이드+EPS 레버리지가 간헐적 대형 비트를 만들 수 있어 확률을 0으로 볼 수 없음
- **관찰 지표**:
  1. FQ4 2026 발표 전 정합 제공사별 non-GAAP EPS 컨센서스 중앙값(C)과 Q3 FY26 대비 가이던스 갭
  2. Q4 FY26 AI 반도체 매출 가이던스 및 발표 시 매출 vs 가이던스 상회폭·자사주 매입에 따른 희석주식수 변화

> **P1 참고 의견 — 자금 결정의 단독 근거 아님** (P3 게이트: 해소 50문항+ & Brier < 0.18 통과 전).

## [미검증] 항목
- Q3 FY26 non-GAAP 희석 EPS 실제치 및 정합성 검증 기준치 미확보 (NOT FOUND)
- FQ4 2026 non-GAAP EPS 컨센서스(C) 및 제공사별 정합성 미확보 (NOT FOUND)
- 최근 8개 분기 EPS surprise% 시계열 미확보 — base rate는 정성 추정 (NOT FOUND)
- FQ4 2026 실적발표 확정일 미확보 (≈2026-12-10~11 추정)
- (a)전제 개정 취약성: C 스냅샷은 발표 직전 고정이나 정합 제공사 식별이 바뀌면 중앙값이 이동해 결론 뒤집힐 수 있음
- (b)컨센서스 존재: 셀사이드 컨센 존재(판정용 정합 집계)하나 본 세션 수치 미확보 — 중심추정은 '가이던스 밀착 컨센' 가정, 산포 큼
- (c)임계 z: 임계 +5% 비트, 서프라이즈 σ 추정 ~3%p(정성) → z≈1.67로 사구간 밖, 정보성 있는 질문 (σ 출처는 정성 추정, NOT FOUND)

## 리서치 구성
general(출처 74), devil(출처 75) — 증거 부록: `2026-11-09_avgo-eps-surprise-ge5pct-fq4-2026_r1_evidence.md`
