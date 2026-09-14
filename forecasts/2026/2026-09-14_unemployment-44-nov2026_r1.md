---
forecast_id: 2026-09-14_unemployment-44-nov2026_r1
question_id: unemployment-44-nov2026
question_snapshot: 2026-12-04 발표되는 11월분 고용보고서에서 실업률(U-3) 최초 공표치가 4.4% 이상일 확률은?
timestamp: 2026-09-14 10:42 KST
phase: P1
model: claude-opus-4-8
provider: anthropic
model_snapshot: claude-opus-4-8
provider_version: reasoning_core_v1_1
prompt_version: reasoning_core_v1_1
probability: 20
ci80: [10, 35]
window_end: null
snapshots: {}
market_implied: null
edge: null
research_status: ok
sources_count: 126
method: p1-pipeline/2agents
cost_usd: 1.45
ensemble_runs: [20]
divergence: null
shadow_extremized: 8
digest_hash: null
digest_inputs: null
pipeline_tier: standard
registered_tier: lite
ml_divergence_pp: null
divergence_note: null
divergence_class: null
research_quality:
  sources: {t1: 5, t2: 0, t3: 3, t4: 0, unknown: 2}
  n_urls: 10
  primary_ratio: 0.5
---

## [0] 질문 검증
기한(2026-12-04 발표)·임계값(U-3 최초 공표치 ≥4.4%)·판정출처(BLS empsit) 모두 명확하여 해소가능. 최초 공표치 기준이므로 사후 개정 무관, 소수 첫째 자리 반올림 기준.

## [1] Outside View — base rate (anchor: 15%)
참조 클래스: 저실업(4% 초반) 안정 국면에서 3개월 만에 실업률이 +0.3%p 이상 상승하는 사건 (8월 4.1% → 11월 ≥4.4%)

- 비침체 안정기 3개월 실업률 변화폭은 통상 ±0.1~0.2%p 이내, +0.3%p 이상 급등은 저빈도 (research general, 원계열 도수 NOT FOUND)
- 2023~2024 완만 상승기: 3.4%→4.3% 상승에 약 15개월 소요, 3개월 단위로는 대부분 +0.1~0.2%p (research general)
- 급등(3개월 +0.3%p 이상)은 코로나·GFC 등 충격기 집중. 2024년엔 반년 +0.6p 발동 사례도 있어 냉각기엔 3틱 상승이 드물지 않음 (devil)

## [2] Inside View — 보정
| 증거 | 방향 | 조정 |
|---|---|---|
| Fed 3월 SEP Q4 4.4%, SPF Q1 4.5%, CBO 2026 정점 4.6% — 공식 전망이 임계값 정면 지지 (devil, fredblog/philadelphiafed/CBO) | ↑ | +5%p |
| 구조적 고용 둔화: 12개월 평균 3.1만 증가·연방고용 33.6만 감소·정보/금융 감원 (research general, devil) | ↑ | +4%p |
| 반올림 지렛대(4.1%=실제 4.05~4.14) + 셧다운·가구조사 변동성 상방 꼬리 (devil) | ↑ | +3%p |
| 최근 3개월 방향 하락/횡보(4.2→4.1→4.1) + 8월 고용 16.2만 서프라이즈·상향수정 (research general) | ↓ | −4%p |
| 참가율 하락(구직 포기)이 오히려 실업률 억제, Fed 6월 SEP Q4 4.3%로 하향 (research general) | ↓ | −3%p |

## [3] 분해 트리
YES 성립 = 11월 U-3(반올림) ≥4.4%. 필요조건: (1) 실질 실업률이 8월 4.1%대(4.05~4.14)에서 3개월간 약 +0.25~0.35%p 상승 P≈0.20, 및 (2) 그 상승이 4.35% 이상으로 반올림 도달. 남은 3개 보고서(9·10·11월)에 걸쳐 냉각이 가속되고 노동공급 반등이 실업률을 밀어올려야 함. 두 조건 결합 시 ~20% 수준으로 [2] 보정 결과와 정합.

## [4] Premortem — 이 예측이 크게 틀렸다면
1. 노동공급(이민정책發 위축)이 반등하며 노동력이 급증, 인위적 저점이 빠르게 해소되어 실업률 급등
2. AI·화이트칼라 해고가 광범위해지고 8월 강세가 대폭 하향 수정되어 냉각 신호가 현실화
3. 가을 예산·셧다운 교란 및 가구조사 대형 스윙의 역방향 반동으로 노이즈가 상방으로 튐

## [5] 최종 출력
- **최종 확률: 20%** (80% CI: 10~35%)
- **핵심 근거**:
  1. 출발값 4.1%에서 3개월 +0.3%p 상승은 역사적 저빈도이고 최근 방향은 하락/횡보 (research general)
  2. 다만 공식 전망(Fed 4.4/SPF 4.5/CBO 4.6)이 임계값을 지지하고 근원 고용 냉각·반올림 지렛대가 상방 꼬리를 키움 (devil)
  3. 순수 추세 외삽만으로 15% 아래는 부적절, 상방 리스크 반영해 20%로 조정
- **관찰 지표**:
  1. 9월분(10/2)·10월분(11월초) U-3 실측 — 4.2% 이상 상승 시 상방, 4.1% 이하 유지 시 하방
  2. 월간 노동력·참가율 변화 및 비농업 고용 상향/하향 수정 폭 (노동공급 반등 여부)

> **P1 참고 의견 — 자금 결정의 단독 근거 아님** (P3 게이트: 해소 50문항+ & Brier < 0.18 통과 전).

## [미검증] 항목
- 2026년 6월 FOMC SEP 실업률 중앙값 정확 수치 미확인 (3월 4.4%만 확인, 6월 4.3% 하향은 research general 인용이나 원문 미확인)
- 2026 BLS 공식 릴리스 스케줄 PDF 원문 미확인 (관행 기반 12/4 추정)
- 비침체기 3개월 +0.3%p 상승 구체 월별 도수 NOT FOUND
- 임계 z: 중심추정 ~4.15%, 3개월 누적 σ~0.2%p 가정 시 z≈1.25 — σ 출처는 정성 추정으로 미검증

## 리서치 구성
general(출처 63), devil(출처 63) — 증거 부록: `2026-09-14_unemployment-44-nov2026_r1_evidence.md`
