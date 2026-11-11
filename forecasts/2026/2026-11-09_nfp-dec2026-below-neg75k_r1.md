---
forecast_id: 2026-11-09_nfp-dec2026-below-neg75k_r1
question_id: nfp-dec2026-below-neg75k
question_snapshot: 2027년 1월 초 발표되는 2026년 12월분 고용상황 보고서에서 비농업 신규고용(NFP) 최초 공표치가 −75,000 이하일 확률은?
timestamp: 2026-11-09 15:35 KST
phase: P1
model: claude-opus-4-8
provider: anthropic
model_snapshot: claude-opus-4-8
provider_version: reasoning_core_v1_1
prompt_version: reasoning_core_v1_1
probability: 11
ci80: [4, 22]
window_end: null
snapshots: {없음: NOT FOUND}
market_implied: null
edge: null
research_status: ok
sources_count: 147
method: p1-pipeline/2agents
cost_usd: 2.5038
ensemble_runs: [11]
divergence: null
shadow_extremized: 3
digest_hash: b87035d004cdafd338a2f39a71593cf70b6267e96b172de4e510610733168731
digest_inputs: {ml_run_ts: '2026-11-07T10:32:38', context_run_ts: '2026-11-05T19:20:59', ml_history_file: data/ml_history/, market: null}
pipeline_tier: standard
registered_tier: standard
ml_divergence_pp: null
divergence_note: null
divergence_class: null
research_quality:
  sources: {t1: 7, t2: 0, t3: 4, t4: 0, unknown: 1}
  n_urls: 12
  primary_ratio: 0.583
---

## [0] 질문 검증
기한(2027-01-08경)·임계(≤−75,000)·판정기준(12월분 최초 공표치, 당일 릴리스 스냅샷) 모두 명확. 셧다운 등 일정 변경 시 실제 발표일 기준 판정 명시됨. 해소가능 질문.

## [1] Outside View — base rate (anchor: 7%)
참조 클래스: 비침체 국면 미국 월별 NFP 최초 공표치가 ≤ −75,000 으로 인쇄되는 빈도

- 2010~2019 확장기 전체에서 음수 최초 공표는 2010년 9월(센서스 임시인력 해제, 약 −95k) 사실상 1건 — 월 발생률 <1% [source: devil 보고서 §3, bls.gov/ces]
- 2025~2026 약세 구간에서도 최저 월간치 +29k(2026-09)로 양수 유지, ≤−75k 0건 [source: cnbc.com 2026-10-02]
- 침체 전환·대형 일회성 충격(허리케인·대규모 파업·셧다운) 동반 시에만 ≤−75k 관측 — general 보고서 §2 (정량 신규출처 NOT FOUND)

## [2] Inside View — 보정
| 증거 | 방향 | 조정 |
|---|---|---|
| 직전 12M 평균 +31~45k, 2025 평균 +15k, 9월 +29k로 '스톨 스피드' 근접 — 추가 소폭 악화만으로 음수 전환 여력 [source: devil §1(b), bls.gov/ces] | ↑ | +4%p |
| 12월 연말 소매 계절조정 민감도 + 연방/금융 부문 구조적 감원 중첩 리스크 [source: devil §1(c)(d)] | ↑ | +2%p |
| 10월분 +165k 반등·실업률 4.1%로 침체적 붕괴 부재, −75k는 10월 대비 약 −240k 2개월 스윙 요구 [source: bls.gov/news.release/empsit.nr0.htm 2026-11-06] | ↓ | −3%p |
| 프리모템: 컨센서스가 꼬리위험을 과소평가할 소지 + 최초 공표치 ±130k 진폭 변동성 반영 [source: devil §1(a)] | ↑ | +1%p |

## [3] 분해 트리
YES(≤−75k) 성립 경로는 대체로 conjunctive: ① 민간 추세 바닥근접(이미 충족, ~0.7) AND ② 12월 중대형 감원·연방 인력감축 반영(~0.3) AND ③ 계절조정이 약한 원계열을 음수로 증폭(~0.3) 또는 ④ 셧다운성 수집교란(~0.2). 단일 월 −75k 도달에는 최소 2~3요소 중첩 필요 → 0.7×0.3×(0.3+0.2 보정) ≈ 0.08~0.12. [2] 조정 결과(11%)와 정합.

## [4] Premortem — 이 예측이 크게 틀렸다면
1. 실제로 12월 대규모 구조조정/연방감원이 수만명 단위로 반영되고 계절조정이 음수를 증폭해 YES 실현 — 2010년 9월형 일회성 충격 재현
2. 11월→12월 노동시장이 10월 +165k 수준으로 회복 지속되어 양수 유지, 확률 과대추정
3. 셧다운으로 발표 지연·수집 교란 발생 시 저집계 프린트가 하방 바이어스로 작용

## [5] 최종 출력
- **최종 확률: 11%** (80% CI: 4~22%)
- **핵심 근거**:
  1. 비침체 국면 ≤−75k 기저발생률은 사실상 0에 수렴 — 2025~2026 약세기에도 최저 +29k 양수 유지
  2. 다만 추세 모멘텀(+15~45k)이 0 근접해 꼬리위험이 평시보다 상향, 10월 +165k 반등이 상한을 제한
  3. 컨센서스·9~12월 정확치 다수 NOT FOUND로 불확실성 높아 CI 확대
- **관찰 지표**:
  1. 11월분 NFP 최초치(2026-12-05경) — 양수 유지 시 하향, 0 근처/음수 시 상향
  2. 12월 Challenger 감원·연방 인력감축 발표 및 셧다운/발표지연 여부

> **P1 참고 의견 — 자금 결정의 단독 근거 아님** (P3 게이트: 해소 50문항+ & Brier < 0.18 통과 전).

## [미검증] 항목
- 12월분 컨센서스: 발표 직전 집계로 현 시점 미존재(NOT FOUND)
- 2027-01 발표일 공식 BLS 일정 확정치 NOT FOUND
- 정량 base rate 3건 신규 1차출처 확인 실패(general 보고서)
- 중심추정 및 σ는 2026년 월별 프린트 분포 기반 추정치(z≈1.9, 임계가 중심에서 1σ 이상 이탈) — 정식 서베이 출처 아님

## 리서치 구성
general(출처 73), devil(출처 74) — 증거 부록: `2026-11-09_nfp-dec2026-below-neg75k_r1_evidence.md`
