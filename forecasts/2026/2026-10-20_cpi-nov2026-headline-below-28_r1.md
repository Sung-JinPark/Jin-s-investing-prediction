---
forecast_id: 2026-10-20_cpi-nov2026-headline-below-28_r1
question_id: cpi-nov2026-headline-below-28
question_snapshot: 2026-12-10 발표되는 11월분 CPI에서 헤드라인 CPI-U 전년동월비가 2.8% 미만일 확률은?
timestamp: 2026-10-20 10:06 KST
phase: P1
model: claude-opus-4-8
provider: anthropic
model_snapshot: claude-opus-4-8
provider_version: reasoning_core_v1_1
prompt_version: reasoning_core_v1_1
probability: 7
ci80: [2, 16]
window_end: null
snapshots: {}
market_implied: null
edge: null
research_status: ok_low_primary
sources_count: 149
method: p1-pipeline/2agents
cost_usd: 1.5109
ensemble_runs: [7]
divergence: null
shadow_extremized: 1
digest_hash: null
digest_inputs: null
pipeline_tier: standard
registered_tier: lite
ml_divergence_pp: null
divergence_note: null
divergence_class: null
research_quality:
  sources: {t1: 0, t2: 0, t3: 3, t4: 0, unknown: 2}
  n_urls: 5
  primary_ratio: 0.0
---

## [0] 질문 검증
기한(2026-12-10 11월분 CPI 발표)·임계값(headline CPI-U YoY < 2.8%, 즉 2.7% 이하)·판정출처(BLS 최초 공표치) 모두 명확. 해소가능. 다만 발표일 BLS 공식 스케줄 독립 재확인은 NOT FOUND이나 통상 11월분=12월 중순으로 정합적.

## [1] Outside View — base rate (anchor: 12%)
참조 클래스: 미국 헤드라인 CPI YoY가 상승/정체 국면에서 2개월 내 1.0%p 이상 급락하는 사건 (에너지 상승 모멘텀 동반 시)

- 9월분 실측 3.7%, 목표 2.7% 이하까지 -1.0%p 필요 [advisorperspectives.com, 2026-10-14]
- 추세: 7월 3.4%→8월 3.4%→9월 3.7% 상승 가속 [tradingeconomics.com]
- Trading Economics 모델 분기말 전망 ~3.4%로 2.8% 미만과 큰 괴리 [tradingeconomics.com]

## [2] Inside View — 보정
| 증거 | 방향 | 조정 |
|---|---|---|
| 출발점 3.7%, 월간 상승 절반 이상이 휘발유(+9.1% MoM)로 에너지 상승 모멘텀 — 2개월 내 -1.0%p 하락 반대 방향 [bloomberg.com, 2026-10-14] | ↓ | −5%p |
| 실측치가 컨센서스(3.6%)마저 상회하는 상방 서프라이즈 경향 + 금리인상 재부상 서사 [finance.yahoo.com, 2026-10-14] | ↓ | −4%p |
| 2025년 10/11월 셧다운 데이터 결측·왜곡으로 기저효과 반전 가능성 — YoY 산술 하락 여지(방향 NOT FOUND, 불확실성 상방 여지) [clevelandfed.org] | ↑ | +2%p |
| 프리모템: 수요 둔화·실업 급증 경기침체 시 디스인플레이션 급가속(에너지 월중 변동성 큼) 저확률 경로 반영 | ↑ | +2%p |

## [3] 분해 트리
YES 성립 조건(AND): (1) 10월 MoM 대폭 음전환 또는 완만 + (2) 11월 MoM 대폭 음전환 + (3) 2025년 11월 기저가 유리. 각 확률 대략 (1)~0.3, (2)~0.2, (3)~0.5 → 곱 ~0.03. 에너지 급락+근원 동반 둔화 동시 성립 필요로 매우 낮음. [2] 조정치(7%)는 분해 결과(~3%)보다 다소 높으나, 발표일까지 2개월 간 미지의 에너지·기저 충격 불확실성을 반영한 안전마진으로 7% 유지.

## [4] Premortem — 이 예측이 크게 틀렸다면
1. 에너지(유가) 10~11월 급락으로 MoM 연속 음전환 — 디스인플레이션 급가속
2. 2025년 11월 기저가 셧다운 왜곡으로 비정상 높아 기술적 YoY 급락
3. 근원 주거비 급둔화가 예상보다 빠르게 헤드라인 끌어내림

## [5] 최종 출력
- **최종 확률: 7%** (80% CI: 2~16%)
- **핵심 근거**:
  1. 9월 실측 3.7%로 목표(2.7% 이하)보다 +1.0%p 높고 추세가 상승 가속 국면
  2. 월간 상승 절반 이상이 휘발유인 에너지 역풍 + 모델 전망 ~3.4%
  3. 2개월 내 -1.0%p 급락은 에너지 붕괴/침체 등 저빈도 시나리오에서만 발생
- **관찰 지표**:
  1. 10월분 CPI(11월 중순 발표) MoM 및 YoY 값 — 음전환·급락 여부
  2. 유가·휘발유 10~11월 월중 경로 및 Cleveland Fed 나우캐스트 11월분

> **P1 참고 의견 — 자금 결정의 단독 근거 아님** (P3 게이트: 해소 50문항+ & Brier < 0.18 통과 전).

## [미검증] 항목
- 11월분 포인트 컨센서스 수치 NOT FOUND
- Cleveland Fed 나우캐스트 10/11월 구체치 NOT FOUND
- 2026-12-10 BLS 발표일 공식 스케줄 독립 재확인 NOT FOUND
- 2개월 -1.0%p 급락 정량 역사 빈도표 NOT FOUND
- 2025년 11월 기저값 및 셧다운 왜곡 방향·크기 NOT FOUND
- 전제 개정 취약성: 9월 3.7%·기저값 등 전제가 사후 개정 가능하나 판정은 최초 공표치 고정
- 컨센서스 존재 여부: 11월분 포인트 컨센 NOT FOUND, 대체로 모델 전망(~3.4%) 중심추정 사용, 산포 넓음 → CI 확대
- 임계 z: 중심추정 ~3.4~3.7%, 임계 2.8%, σ 약 0.3%p 가정 시 z≈2 이상으로 사구간 밖 — 경계 문제 아님

## 리서치 구성
general(출처 75), devil(출처 74) — 증거 부록: `2026-10-20_cpi-nov2026-headline-below-28_r1_evidence.md`
