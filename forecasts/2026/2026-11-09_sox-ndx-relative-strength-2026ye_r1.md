---
forecast_id: 2026-11-09_sox-ndx-relative-strength-2026ye_r1
question_id: sox-ndx-relative-strength-2026ye
question_snapshot: 2026-12-31 종가 기준, (NASDAQSOX ÷ NASDAQ100)을 2026-08-28 = 100으로 정규화한 값이 95 이하일 확률은?
timestamp: 2026-11-09 15:12 KST
phase: P1
model: claude-opus-4-8
provider: anthropic
model_snapshot: claude-opus-4-8
provider_version: reasoning_core_v1_1
prompt_version: reasoning_core_v1_1
probability: 91
ci80: [80, 97]
window_end: null
snapshots: {없음: NOT FOUND}
market_implied: null
edge: null
research_status: ok_low_primary
sources_count: 145
method: p1-pipeline/2agents
cost_usd: 3.1211
ensemble_runs: [91]
divergence: null
shadow_extremized: 98
digest_hash: b87035d004cdafd338a2f39a71593cf70b6267e96b172de4e510610733168731
digest_inputs: {ml_run_ts: '2026-11-07T10:32:38', context_run_ts: '2026-11-05T19:20:59', ml_history_file: data/ml_history/, market: null}
pipeline_tier: standard
registered_tier: lite
ml_divergence_pp: null
divergence_note: null
divergence_class: null
research_quality:
  sources: {t1: 2, t2: 0, t3: 4, t4: 0, unknown: 9}
  n_urls: 15
  primary_ratio: 0.133
---

## [0] 질문 검증
기한(2026-12-31 종가)·임계값(정규화 비율 ≤95.0)·판정출처(FRED NASDAQSOX, NASDAQ100)가 모두 명확. 재작성 불필요. 현재 비율이 이미 95를 크게 하회하는 상태인지가 핵심.

## [1] Outside View — base rate (anchor: 82%)
참조 클래스: 급락 국면에서 고베타 섹터지수(SOX)가 벤치마크(NDX) 대비 4개월 창에서 상대 수익률 격차를 유지/확대하는 사례 + 이미 큰 버퍼가 형성된 상태에서 임계 복귀 여부

- SOX 3Y 베타 2.06, 5Y 2.41 — 하락장에서 NDX를 큰 폭 언더퍼폼하는 것이 통계적 기본값 [iShares SOXX 2026-09-30; Yahoo 2026-11-09]
- 현재 정규화 비율 추정 ≈74~84 (SOX 8/28 대비 −18.1%, NDX는 동기간 상승) — 이미 95를 큰 폭 하회 [nasdaqomx·FRED 2026-11-06]
- 비율을 95 위로 되돌리려면 8주 내 SOX의 NDX 대비 +24~28%p 상대 아웃퍼폼 필요 — 분기 단위로도 희소 [devil 보고서]

## [2] Inside View — 보정
| 증거 | 방향 | 조정 |
|---|---|---|
| 현재 비율 ≈74~84로 임계(95) 대비 11~21p 버퍼가 이미 존재; 플립하려면 SOX가 NDX 대비 +24~28%p 상대반등 필요 [devil·general 민감도표] | ↑ | +12%p |
| SOX 베타 2.41·11/6 하루 +4.21% 반등·누적 숏 $320억에 따른 숏스퀴즈 연료 — V자 상대반등 꼬리위험 [Yahoo/stockanalysis 2026-11] | ↓ | −2%p |
| 프리모템: 11월 하순 NVDA 등 반도체 실적 AI capex 재확인이 과매도 반전 촉매가 될 수 있음 [general 캘린더] | ↓ | −1%p |

## [3] 분해 트리
YES ⟺ (SOX수익배수 ≤ 0.95×NDX수익배수) on 12/31. 현재 상태: SOX −18.1% vs NDX 소폭 상승 → 비율≈78. 12/31까지 NO로 뒤집히려면 (A) SOX가 NDX 대비 약 +25%p 상대 아웃퍼폼 AND (B) 그 반등이 분기말까지 지속 — 두 조건 AND. P(A)≈0.08, P(B|A)≈0.9 → P(NO)≈0.07~0.10 → P(YES)≈0.90~0.93. [2] 조정결과(91%)와 일치.

## [4] Premortem — 이 예측이 크게 틀렸다면
1. 11월말 반도체 실적 호조 + 과매도·대규모 숏 환매로 SOX가 8주 내 V자 상대반등(+25%p)하며 비율 95 복귀
2. NDX가 반도체 비중으로 동반 급락해 분모가 함께 빠지면 비율이 상승해 95에 근접(그러나 방향상 완충 효과는 제한적)
3. 현재 비율 추정의 전제인 NDX_2026-08-28 종가가 미확인 — 실제 기준값이 예상보다 크게 높으면 현재 비율이 더 낮아져 오히려 YES 강화(역방향 리스크)

## [5] 최종 출력
- **최종 확률: 91%** (80% CI: 80~97%)
- **핵심 근거**:
  1. 현재 정규화 비율이 이미 약 74~84로 임계(95)를 큰 폭 하회 — YES 조건이 현 시점 사실상 충족 상태 [general·devil]
  2. NO로 뒤집히려면 8주 내 SOX의 NDX 대비 +24~28%p 상대 아웃퍼폼이 필요하며 이는 역사적으로 희소
  3. SOX 고베타·숏스퀴즈·실적 촉매가 꼬리위험을 제공하나 요구 반등폭이 너무 커 확률 낮음
- **관찰 지표**:
  1. 주간 SOX−NDX 상대 수익률 스프레드(특히 11월말 NVDA 실적 전후 누적 상대반등폭이 +15%p 이상인지)
  2. FRED NASDAQSOX·NASDAQ100 일별 종가로 산출한 실시간 정규화 비율이 90을 상회하는지

> **P1 참고 의견 — 자금 결정의 단독 근거 아님** (P3 게이트: 해소 50문항+ & Brier < 0.18 통과 전).

## [미검증] 항목
- NDX 2026-08-28 종가가 교차검증되지 않음 — 현재 비율 추정(74~84)은 NDX_0828≈24,000~27,000 가정에 의존 [general·devil 공통 미확정]
- (a) 전제 개정 취약성: 판정은 최초 공표 종가로 고정되나, 현재 비율 추정의 전제인 NDX_0828 미확정 — 다만 NDX 역대최고가 31,224(10/6)여서 어떤 값이든 비율<95는 견고
- (b) 컨센서스: 공표 컨센서스 없음(market-regime). 대체 중심추정은 현재 실측 비율≈78(SOX 실측·NDX 추정)이며 산포는 NDX_0828 불확실성으로 ±5p
- (c) 임계 z: 임계 95, 중심추정 ≈78, 분기말 비율 σ는 SOX 주간σ0.0609·8주 누적 상대변동 기준 약 10~12p → z≈(95−78)/11≈1.5 (사구간 밖, 고신뢰). z·σ 출처는 오픈웨이트 GBM 주간σ 결합 추정

## 리서치 구성
general(출처 72), devil(출처 73) — 증거 부록: `2026-11-09_sox-ndx-relative-strength-2026ye_r1_evidence.md`
