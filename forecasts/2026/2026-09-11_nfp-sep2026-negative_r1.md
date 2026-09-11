---
forecast_id: 2026-09-11_nfp-sep2026-negative_r1
question_id: nfp-sep2026-negative
question_snapshot: 2026-10-02 발표되는 9월분 고용보고서에서 NFP 최초 공표치가 0 미만(마이너스)일 확률은?
timestamp: 2026-09-11 10:34 KST
phase: P1
model: claude-opus-4-8
provider: anthropic
model_snapshot: claude-opus-4-8
provider_version: reasoning_core_v1_1
prompt_version: reasoning_core_v1_1
probability: 25
ci80: [12, 42]
window_end: null
snapshots: {}
market_implied: null
edge: null
research_status: ok_low_primary
sources_count: 134
method: p1-pipeline/2agents
cost_usd: 2.1144
ensemble_runs: [25]
divergence: null
shadow_extremized: 13
digest_hash: null
digest_inputs: null
pipeline_tier: standard
registered_tier: lite
ml_divergence_pp: null
divergence_note: null
divergence_class: null
research_quality:
  sources: {t1: 6, t2: 1, t3: 8, t4: 0, unknown: 9}
  n_urls: 24
  primary_ratio: 0.292
---

## [0] 질문 검증
기한(2026-10-02 08:30 ET), 임계값(최초 공표치<0), 판정출처(BLS empsit) 모두 명확. 정확히 0은 NO. 단 FY2027 셧다운 시 발표 지연으로 판정 무산 리스크 존재(별도 기록).

## [1] Outside View — base rate (anchor: 27%)
참조 클래스: 저성장·고변동 노동시장 레짐에서 월간 NFP 최초 공표치가 마이너스로 인쇄될 확률 (2026년 미국)

- 2026년 관측 개월 중 초판 마이너스 최소 2회(2월 -92K, 7월 -23K) → 최근 7~8개 중 25~30% [source: bls.gov empsit, JEC]
- 정상 확장기 초판 마이너스 비율 통상 <10% [일반 매크로 통념, 미검증]
- 2025-12월분 초판 +48K가 -17K로 하향 등 0 부근 변동성 사례 [source: tradingeconomics.com, 2026]

## [2] Inside View — 보정
| 증거 | 방향 | 조정 |
|---|---|---|
| 8월 초판 +162K 강한 반등, 5개월 최대폭·모멘텀 존재 [source: bls.gov empsit, 2026-09-04] | ↓ | −5%p |
| 8월 증가분 음식·주점(+59K)·지방정부교육(+42K) 편중 → 계절조정 페이백/평균회귀 위험 [source: babypips.com, 2026-09-04] | ↑ | +4%p |
| 12개월 평균 +31K로 손익분기 근접, 하방 노이즈만으로 마이너스 진입 용이 [source: fedratecalc.com, 2026-09-04] | ↑ | +3%p |
| 레이오프 속도 4년 최저(Challenger)·실업률 4.1% 견조로 순감소 조합 드묾 [source: cnbc.com, 2026-09-03] | ↓ | −4%p |

## [3] 분해 트리
마이너스 인쇄 성립 경로(OR): (A) 기저추세가 0 부근이라 계절조정 노이즈만으로 부호 전환 (~15%), (B) 8월 편중 급증분 페이백 + 정보·연방·제조 감소 누적 (~10%), (C) TPS 명부 이탈 등 구조적 축소 반영 (~5%). 상호 부분중첩 감안 결합 ≈24~26%. [2] 조정 결과(25%)와 정합.

## [4] Premortem — 이 예측이 크게 틀렸다면
1. 8월 급증 섹터의 계절조정 페이백이 예상보다 커 헤드라인을 -20~-50K로 끌어내림
2. AI發 정보·연방정부·제조 감소가 누적되어 저채용 환경에서 순감소 전환
3. 초기 사업체조사 응답률 저조로 초판 하방편향(7월 -23K 유사 패턴 재현)

## [5] 최종 출력
- **최종 확률: 25%** (80% CI: 12~42%)
- **핵심 근거**:
  1. 2026년 초판 마이너스 base rate 25~30%로 정상기 대비 현저히 높은 약체 레짐
  2. 직전 8월 +162K 강세 반등과 레이오프 4년 최저가 하방을 부분 상쇄
  3. 9월 공식 컨센서스 NOT FOUND로 중심추정 불확실 → CI 확대 필요
- **관찰 지표**:
  1. 9월분 공식 컨센서스 확정치(플러스 폭이 +10K 이하로 낮으면 YES 확률 상향)
  2. 9월 ADP·주간 신규실업청구 추이 및 Challenger 9월치(악화 시 상향)

> **P1 참고 의견 — 자금 결정의 단독 근거 아님** (P3 게이트: 해소 50문항+ & Brier < 0.18 통과 전).

## [미검증] 항목
- 9월분 공식 컨센서스 NOT FOUND — 8월분 컨센(+53~56K)을 참고 대용, 산포 큼
- FY2027 셧다운 확정 여부 NOT FOUND — 발표 지연 시 판정 무산 리스크
- 9월 ADP·주간 실업청구·Challenger 9월치 NOT FOUND
- 임계 z: 중심추정 +40K 가정, NFP 서프라이즈 σ≈70K 가정 시 z=|0-40|/70≈0.57 (<0.7, 사구간 내). z·σ 출처는 일반 매크로 추정으로 미검증

## 리서치 구성
general(출처 68), devil(출처 66) — 증거 부록: `2026-09-11_nfp-sep2026-negative_r1_evidence.md`
