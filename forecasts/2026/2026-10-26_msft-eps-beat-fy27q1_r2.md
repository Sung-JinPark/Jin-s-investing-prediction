---
forecast_id: 2026-10-26_msft-eps-beat-fy27q1_r2
question_id: msft-eps-beat-fy27q1
question_snapshot: Microsoft가 2026-10-28(장후 추정) 발표하는 FY2027 Q1 실적에서 EPS가 발표 직전 컨센서스를 상회할 확률은?
timestamp: 2026-10-26 13:36 KST
phase: P1
model: claude-opus-4-8
provider: anthropic
model_snapshot: claude-opus-4-8
provider_version: reasoning_core_v1_1
prompt_version: reasoning_core_v1_1
probability: 75
ci80: [64, 86]
window_end: null
snapshots: {}
market_implied: null
edge: null
research_status: ok_low_primary
sources_count: 149
method: p1-pipeline/2agents
cost_usd: 2.3337
ensemble_runs: [75]
divergence: null
shadow_extremized: 87
digest_hash: 7a71851ddfeff67f078d6a23b100ce73893c9bf2bd94d05024239256699deae4
digest_inputs: {ml_run_ts: '2026-10-26T09:37:05', context_run_ts: null, ml_history_file: data/ml_history/, market: null}
pipeline_tier: standard
registered_tier: lite
ml_divergence_pp: null
divergence_note: null
divergence_class: null
research_quality:
  sources: {t1: 0, t2: 0, t3: 3, t4: 0, unknown: 9}
  n_urls: 12
  primary_ratio: 0.0
---

## [0] 질문 검증
기한(2026-10-28 장후)·판정기준(발표 EPS > D-3 컨센 스냅샷, 동률 NO) 명확. 단 D-3 정확 컨센 스냅샷 값은 NOT FOUND($4.71~4.72 추정)로 추론 전제에 불확실성 존재. 해소가능 형태로 진행.

## [1] Outside View — base rate (anchor: 82%)
참조 클래스: 대형 메가캡 테크(MSFT 포함)의 분기 EPS 컨센서스 상회 여부

- MSFT 최근 8개 분기 EPS 컨센 상회 = 8/8 (100%) [source: marketbeat.com, 2026-10-19]
- 데블스 측: MSFT 연속 EPS 비트 기록은 5분기로 과거 미스 존재, 영구적 비트 아님 [source: 247wallst.com, 2026-09경]
- 직전 분기 FY2026 Q4 실제 $4.74 vs 컨센 $4.24, +$0.50 대폭 상회 [source: marketbeat.com, 2026-10-19]

## [2] Inside View — 보정
| 증거 | 방향 | 조정 |
|---|---|---|
| 9월 분기 매출 가이던스 $89.85B~$90.95B(중간 $90.4B)·Azure 45%cc로 컨센 상회 제시, 용량 초과 수요 [source: indmoney.com, 2026-08경] | ↑ | +4%p |
| OpenAI 지분법 손실이 구조적 EPS 드래그(보고 31% vs 실질 22% 성장), 적자 가속 시 비선형 하회 경로 [source: simplywall.st, 2026-08경] | ↓ | −5%p |
| 직전 비트의 약 2/3가 Anthropic 지분 평가이익 32억($0.33) 등 일회성, 역평가 시 EPS 역풍 [source: indmoney.com, 2026-08경] | ↓ | −4%p |
| 연 $1,900억 데이터센터 지출의 가속 감가상각 램프·총마진 67%로 하락, 컨센 상향으로 허들 상승 [source: tradingkey.com, indmoney.com, 2026] | ↓ | −2%p |

## [3] 분해 트리
YES = (영업이익 기반 코어 비트) OR (영업외 투자평가이익 플러스). 코어 매출·마진 비트 확률 ~0.75(가이던스 상향·수요초과), 영업외 변동성은 양방향. AND 조건인 '동률 아님'은 사실상 충족(상회폭 통상 수십센트). 결합 시 ~0.73~0.77. [2] 조정 결과(75%)와 정합.

## [4] Premortem — 이 예측이 크게 틀렸다면
1. OpenAI 지분법 손실이 컨센 반영분보다 크게 확대되어 영업외에서 EPS 수십센트 삭감
2. 전분기 EPS를 떠받친 투자평가이익이 역평가로 전환되며 일회성 버퍼 소멸
3. FY2027 capex 회계 분류 변경으로 애널리스트 비용/감가상각 모델이 어긋나 양방향 큰 이탈

## [5] 최종 출력
- **최종 확률: 75%** (80% CI: 64~86%)
- **핵심 근거**:
  1. 최근 8/8 분기 EPS 상회라는 압도적 base rate와 매출 가이던스 상향·Azure 수요 초과가 코어 비트를 지지
  2. 단 직전 비트의 2/3가 일회성 투자이익이고 OpenAI 지분법 손실·감가상각 램프가 하방 비대칭 요인
  3. D-3 컨센 스냅샷 정확값 미확인으로 허들 수준 불확실 → 확신을 극단화하지 않음
- **관찰 지표**:
  1. D-3 공식 컨센 EPS 스냅샷 확정값($4.72 이상으로 상향 이동 시 허들 상승)
  2. 발표 당일 OpenAI/Anthropic 지분법 손익 및 투자평가 항목의 분기 반영 방향

> **P1 참고 의견 — 자금 결정의 단독 근거 아님** (P3 게이트: 해소 50문항+ & Brier < 0.18 통과 전).

## [미검증] 항목
- D-3 발표 직전 마지막 컨센 EPS 스냅샷 정확값 NOT FOUND($4.71~4.72 추정)
- OpenAI 분기 지분법 손실 반영액 구체 수치 NOT FOUND
- FY2027 capex 회계변경의 EPS 순효과 NOT FOUND
- (c) 임계 z: 컨센 대비 EPS 서프라이즈 분포의 σ 출처 부재로 z 정량화 불가 — 질문 구조상 동률/소폭 비트 구간 리스크 기록

## 리서치 구성
general(출처 74), devil(출처 75) — 증거 부록: `2026-10-26_msft-eps-beat-fy27q1_r2_evidence.md`
