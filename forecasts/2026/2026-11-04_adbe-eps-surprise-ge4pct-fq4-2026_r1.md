---
forecast_id: 2026-11-04_adbe-eps-surprise-ge4pct-fq4-2026_r1
question_id: adbe-eps-surprise-ge4pct-fq4-2026
question_snapshot: Adobe가 FQ4 2026 실적에서 보고하는 non-GAAP 희석 EPS가, 발표 직전 스냅샷된 컨센서스의 1.04배 이상일 확률은?
timestamp: 2026-11-04 19:33 KST
phase: P1
model: claude-opus-4-8
provider: anthropic
model_snapshot: claude-opus-4-8
provider_version: reasoning_core_v1_1
prompt_version: reasoning_core_v1_1
probability: 14
ci80: [7, 26]
window_end: null
snapshots: {}
market_implied: null
edge: null
research_status: ok_low_primary
sources_count: 149
method: p1-pipeline/2agents
cost_usd: 3.9472
ensemble_runs: [14]
divergence: null
shadow_extremized: 4
digest_hash: null
digest_inputs: null
pipeline_tier: standard
registered_tier: standard
ml_divergence_pp: null
divergence_note: null
divergence_class: null
research_quality:
  sources: {t1: 0, t2: 0, t3: 6, t4: 0, unknown: 1}
  n_urls: 7
  primary_ratio: 0.0
---

## [0] 질문 검증
기한(2026-12 중순, 12-18 이전)·임계값(A ≥ C×1.04)·판정기준(8-K Ex-99.1 non-GAAP 희석 EPS, 고정 18% 세율 정의)이 명확. C는 발표 직전 예측파일 스냅샷으로 고정. 해소가능 형태. 단, C 수치는 현재 NOT FOUND로 발표 전 스냅샷 필요.

## [1] Outside View — base rate (anchor: 12%)
참조 클래스: Adobe 분기 non-GAAP 희석 EPS가 발표 직전 컨센서스를 +4.0% 이상 상회한 사건 (최근 7개 분기 실측)

- 최근 7개 분기 non-GAAP EPS 서프라이즈 0/7이 +4% 도달, 범위 +0.8%~+3.22% [source: drillr.ai, marketbeat, zacks, investing.com 2024-2026]
- 직전 Q3 FY26 +0.82% 상회 ($6.13 vs $6.08) [source: marketbeat.com 2026-09-10]
- Q4 계절성 유일 확인치 Q4'24 +3.09%로 범위 상단 [source: drillr.ai]
- 문턱 근접(+3%대) 3회: Q1'25 +3.22%, Q1'26 +3.1%, Q4'24 +3.09% [source: devil 보고]

## [2] Inside View — 보정
| 증거 | 방향 | 조정 |
|---|---|---|
| 최근 2년 내 +3%대 문턱 근접 3회(Q1'25·Q1'26·Q4'24) — 분포가 0이 아닌 경계 몰림 [source: devil 보고 §4] | ↑ | +4%p |
| AI 경쟁 공포로 애널리스트가 Q4 추정을 가이던스 하단에 눌러 C가 낮게 스냅샷되면 평소 비트가 문턱 돌파 [source: devil 보고 §2a] | ↑ | +3%p |
| 비트 폭 추세적 축소(Q3'26 +0.82%로 급감), 성숙기업화·가이던스 정밀도 상승 [source: marketbeat 2026-09-10] | ↓ | −3%p |
| 프리모템: C 채택규칙이 '가이던스 정합'을 요구 → 가이던스 정렬 C 대비 +4%는 기계적으로 어려움 [source: general/devil §5] | ↓ | −2%p |

## [3] 분해 트리
YES = (A가 가이던스 대비 큰 비트) AND/OR (C가 낮게 스냅샷). 경로1: 회사 EPS가 가이던스 상단 초과(+3%대, 과거 상한) ≈ 낮음(~15%). 경로2: C가 가이던스 중앙~하단 아래로 형성되어 평소 비트로 문턱 돌파 ≈ 중간(~20%). 두 경로 중 하나로 충분(OR). 그러나 C가 가이던스 정합으로 묶여 둘 다 제약. 결합 ≈ 14%, [2] 조정 결과와 정합.

## [4] Premortem — 이 예측이 크게 틀렸다면
1. AI 디레이팅 공포로 C가 가이던스 하단 밑으로 눌려 분모가 작아짐 → 평소 +2~3% 비트가 1.04배 돌파
2. 고정 18% 세율·자사주 매입·FX 테일윈드가 겹쳐 영업 비트가 세후 희석없이 EPS +4%대로 점프
3. Q4 계절적 최강 분기 + 엔터프라이즈 연말 딜/AI 모네타이제이션 비선형 인플렉션으로 과거 밴드 돌파

## [5] 최종 출력
- **최종 확률: 14%** (80% CI: 7~26%)
- **핵심 근거**:
  1. 최근 7개 분기 non-GAAP EPS 서프라이즈 0/7이 +4% 도달 — 구조적으로 소폭 비트 패턴 [source: devil 보고 §1]
  2. C가 가이던스 정합 규칙으로 묶여 +4% 바(≈$6.58)는 가이던스 상단($6.35)보다도 +3.6% 높아 희귀 [source: general 보고 §5]
  3. 다만 +3%대 문턱 근접 3회 분포 + C 저형성 위험으로 순수 base rate(≈0)보다 상향 [source: devil 보고 §2,4]
- **관찰 지표**:
  1. 발표 직전 스냅샷될 Q4 FY26 non-GAAP EPS 컨센서스 C 값과 그 짝 매출 추정의 가이던스($6.8~6.85B) 정합 위치 (C가 가이던스 하단 밑이면 YES 확률 급등)
  2. 12월 발표 시 실제 non-GAAP EPS가 가이던스 상단($6.35) 초과 폭 및 자사주 매입에 의한 주식수 감소 규모

> **P1 참고 의견 — 자금 결정의 단독 근거 아님** (P3 게이트: 해소 50문항+ & Brier < 0.18 통과 전).

## [미검증] 항목
- Q4 FY26 실제 컨센서스 C 수치 NOT FOUND (레이트리밋으로 미확인) — 판정의 결정적 변수
- Q4 FY26 정확 발표일 NOT FOUND (추정 2026-12-09~중순)
- FY2020~2023 대형 비트 분포 NOT FOUND — 8분기 초과 구간 미검증
- 임계 z 계산 불가: C와 서프라이즈 σ 출처 미확정 (컨센 NOT FOUND로 CI 확대 적용)

## 리서치 구성
general(출처 75), devil(출처 74) — 증거 부록: `2026-11-04_adbe-eps-surprise-ge4pct-fq4-2026_r1_evidence.md`
