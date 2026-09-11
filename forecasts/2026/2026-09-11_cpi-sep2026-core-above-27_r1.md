---
forecast_id: 2026-09-11_cpi-sep2026-core-above-27_r1
question_id: cpi-sep2026-core-above-27
question_snapshot: 2026-10-14 발표되는 9월분 CPI에서 근원 CPI-U 전년동월비가 2.7% 이상일 확률은?
timestamp: 2026-09-11 10:42 KST
phase: P1
model: claude-opus-4-8
provider: anthropic
model_snapshot: claude-opus-4-8
provider_version: reasoning_core_v1_1
prompt_version: reasoning_core_v1_1
probability: 12
ci80: [5, 25]
window_end: null
snapshots: {}
market_implied: null
edge: null
research_status: ok_low_primary
sources_count: 119
method: p1-pipeline/2agents
cost_usd: 2.3095
ensemble_runs: [12]
divergence: null
shadow_extremized: 3
digest_hash: null
digest_inputs: null
pipeline_tier: standard
registered_tier: lite
ml_divergence_pp: null
divergence_note: null
divergence_class: null
research_quality:
  sources: {t1: 2, t2: 1, t3: 5, t4: 0, unknown: 5}
  n_urls: 13
  primary_ratio: 0.231
---

## [0] 질문 검증
기한(2026-10-14), 임계값(core CPI-U YoY ≥ 2.7%), 판정기준(최초 공표치, 소수 첫째 자리, BLS 보도자료) 모두 명확. 해소가능한 질문.

## [1] Outside View — base rate (anchor: 15%)
참조 클래스: 단월 근원 CPI YoY가 직전월 대비 0.3%p 이상 급반등하여 특정 임계선을 상회하는 사건 (디스인플레이션 국면).

- 2026년 core YoY 흐름: 5월 2.9%→6월 2.6%→7월 2.5%→8월 컨센 2.4%, 단월 변동폭 통상 ±0.1~0.3pp [tradingeconomics, 2026-07-14]
- FactSet: 최근 12개월 CPI YoY가 컨센 상회 1회·일치 4회·하회 7회 → 하방 편향 [FactSet, 2026-09-10]
- 단월 0.3pp 이상 급등은 역사적으로 드묾, 4개월 연속 둔화 추세 [리서치 종합]

## [2] Inside View — 보정
| 증거 | 방향 | 조정 |
|---|---|---|
| 5→6→7→8월 4개월 연속 둔화(2.9→2.4%), 2.7% 재돌파에 단월 0.3pp+ 급반등 필요(역사적 희소) [tradingeconomics] | ↓ | −5%p |
| 8월 PPI core +4.6% YoY(7월 4.2%)로 가속, 에너지 재점화·관세 2차 전가로 근원재 상방 리스크 [Yahoo Finance, 2026-09-10] | ↑ | +3%p |
| 프리모템: 2025년 9월 base(MoM) NOT FOUND — 낮은 기저 탈락 시 YoY 자동 상승 + 반올림 임계(2.65~2.74) 위험 [devil 보고] | ↓ | −1%p |

## [3] 분해 트리
YES 성립 = (8월 실측이 2.5%+로 확정) AND/OR (9월 MoM 정상~가속) AND (2025년 9월 base 탈락 기여). 각 조건: 8월 2.5%+ 확률 ~35%, 9월 MoM 가속 ~30%, 낮은 base 기여 불확실. 세 요인 중 2개 이상 중첩 시 2.65%+ 반올림으로 YES. 결합 확률 대략 10~14%, [2] 조정치(12%)와 정합.

## [4] Premortem — 이 예측이 크게 틀렸다면
1. 8월 공식치가 예측시장 모달(2.4%)보다 높은 2.5~2.6%로 확정되어 출발점이 높음
2. 관세 2차 전가로 9월 core goods MoM 가속 + OER 둔화 지연
3. 2025년 9월 낮은 기저 탈락으로 YoY 자동 상승 + 반올림 임계 근접

## [5] 최종 출력
- **최종 확률: 12%** (80% CI: 5~25%)
- **핵심 근거**:
  1. core YoY 4개월 연속 둔화(2.9→2.4%), 2.7%까지 단월 0.3pp+ 급반등 필요 — 역사적 희소
  2. 최근 12개월 컨센 하회 7회로 하방 편향, shelter 냉각 지속
  3. PPI core +4.6% 가속·관세 전가 시차가 상방 리스크로 잔존하나 단월 반전엔 부족
- **관찰 지표**:
  1. 9/11 발표 8월분 BLS core CPI YoY 공식 확정치 (2.5%+면 YES 확률 상향)
  2. 2025년 9월 core CPI MoM base 값 (낮으면 YoY 상방 압력)

> **P1 참고 의견 — 자금 결정의 단독 근거 아님** (P3 게이트: 해소 50문항+ & Brier < 0.18 통과 전).

## [미검증] 항목
- 9월분 core YoY 컨센서스 NOT FOUND — 중심추정은 8월 컨센 2.4% + 둔화추세로 대체, 산포 크므로 CI 확대
- 2025년 9월 core CPI base(MoM/index) NOT FOUND — 기저효과 방향 불확실
- 8월분 BLS 공식 확정치 발표 직전 미확보(예측시장 저등급 2.4% 단서만 존재)
- z ≈ 1.5~1.7 (임계 2.7 vs 중심 ~2.45, σ 가정 0.15pp) — 사구간 밖, 극단화 아님. σ는 월별 변동폭 기반 추정치[미검증]
- 2021~22 transitory 오판 선례는 본 세션 출처 재확인 NOT FOUND

## 리서치 구성
general(출처 66), devil(출처 53) — 증거 부록: `2026-09-11_cpi-sep2026-core-above-27_r1_evidence.md`
