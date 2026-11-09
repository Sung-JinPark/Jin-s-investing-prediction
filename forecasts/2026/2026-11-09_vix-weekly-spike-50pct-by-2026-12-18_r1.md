---
forecast_id: 2026-11-09_vix-weekly-spike-50pct-by-2026-12-18_r1
question_id: vix-weekly-spike-50pct-by-2026-12-18
question_snapshot: 2026-09-14 주부터 2026-12-18까지, VIX 주간 종가 상승률이 50% 이상인 주가 1회 이상 발생할 확률은?
timestamp: 2026-11-09 14:19 KST
phase: P1
model: claude-opus-4-8
provider: anthropic
model_snapshot: claude-opus-4-8
provider_version: reasoning_core_v1_1
prompt_version: reasoning_core_v1_1
probability: 20
ci80: [10, 35]
window_end: null
snapshots: {(확정 필요 스냅샷 없음): NOT FOUND}
market_implied: null
edge: null
research_status: ok_low_primary
sources_count: 144
method: p1-pipeline/2agents
cost_usd: 2.3457
ensemble_runs: [20]
divergence: null
shadow_extremized: 8
digest_hash: b87035d004cdafd338a2f39a71593cf70b6267e96b172de4e510610733168731
digest_inputs: {ml_run_ts: '2026-11-07T10:32:38', context_run_ts: '2026-11-05T19:20:59', ml_history_file: data/ml_history/, market: null}
pipeline_tier: standard
registered_tier: lite
ml_divergence_pp: null
divergence_note: null
divergence_class: null
research_quality:
  sources: {t1: 1, t2: 0, t3: 1, t4: 1, unknown: 14}
  n_urls: 17
  primary_ratio: 0.059
---

## [0] 질문 검증
기한(2026-09-14주~12-18)·임계값(주간 금→금 종가 +50.0% 이상 1회)·판정출처(CBOE/FRED VIXCLS) 모두 명확. 해소가능. 오늘(2026-11-09) 기준 W1~W8(9/18~11/6)은 경과했고 잔여는 6주(11/13·11/20·11/27·12/4·12/11·12/18).

## [1] Outside View — base rate (anchor: 10%)
참조 클래스: 임의의 6주 창에서 VIX 주간 종가(Fri/Fri)가 최소 1회 +50% 이상 상승할 확률 (단, 현재는 11/5 역대 3위 일간 급등 직후의 활성 변동성 레짐)

- VIX 주간 Fri/Fri +50% 급등은 희귀·군집형: 1990년 이후 1일 +50% 급등조차 10회에 불과 [source: tradingview/benzinga 2026-11-07]
- 역사적 대형 주간 급등은 거의 전부 저베이스(VIX 12~16)에서 발생 (2015-08·2018-02 Volmageddon·2020-03·2024-08) [source: civolatility 2025; qz.com 2026-11-06]
- 무조건부로 임의 6주 창 발생률 대략 5~10% 수준 추정(주간 σ≈14.7%에서 ln1.5=+0.405는 약 2.8σ, 팻테일 보정) [오픈웨이트 VIX GBM σ 0.1468]
- 2026 VIX 연평균 18.16의 구조적 저변동 레짐이나 11/5 쇼크로 현재 활성화 [source: macrotrends 2026-11-05]

## [2] Inside View — 보정
| 증거 | 방향 | 조정 |
|---|---|---|
| 11/5 VIX +69.66%(역대 3위 일간)·VVIX 134.99(2007년 이후 최대)로 활성 변동성 군집 레짐 진입, 조건부 재발률 상승 [source: benzinga/thestreet 2026-11-06] | ↑ | +8%p |
| 잔여 창 마지막 주(W14, 12/14~18)가 12월 FOMC·쿼드러플위칭과 겹치고 11/10 CPI 등 촉매 다수 [source: 리서치 캘린더, 2024-12-18 FOMC 선례] | ↑ | +4%p |
| 11월 말 산타랠리로 VIX가 14~16으로 되돌림 시 저베이스에서 +50% 성립이 용이해지는 역설(저베이스+촉매=전형 구성) | ↑ | +3%p |
| 현재 베이스 ≈25에서 즉시 +50%는 ≈38 요구(52주 최고 35.30·2026 피크 31.05 상회)로 단기 성립 난이도 높음 [source: macrotrends/investing 2026-11] | ↓ | −3%p |
| 쇼크 후 되돌림이 기본값(11/6 이미 -9.01%), '한 달 내 반등' 패턴 및 홀리데이 저변동 [source: benzinga 2026-11-07] | ↓ | −2%p |
| 프리모템: 연말 변동성 소진·급락 시나리오 과대평가 위험 반영 | ↓ | −1%p |
| 프리모템: vol clustering 2차 하락 레그로 특정 금요일 저점→다음 금요일 고점 발생 과소평가 위험 보정 | ↑ | +1%p |

## [3] 분해 트리
OR 구조: P(잔여 6주 중 1회 이상 +50% 주간). 경로A=고베이스 유지(~25)에서 추가 쇼크로 ~38 돌파(낮음, 주당 ~2%) · 경로B=11월 말 저베이스(14~16) 되돌림 후 12월 FOMC/CPI 쇼크로 +50%(중간, 가장 현실적) · 경로C=2차 하락 레그 군집(중간). 경과 8주는 미발생(11/6 +32.03%, 10/30≈19.4 역산) [source: riotimesonline 2026-11-09]. 6주 OR 결합 ≈ 18~22%.

## [4] Premortem — 이 예측이 크게 틀렸다면
1. 변동성 군집을 과소평가 — 2차 레그가 특정 금요일 저점/다음 금요일 고점을 만들어 +50% 성립
2. 11월 말 저베이스 리셋 후 12/18 FOMC+쿼드위칭에서 깨끗한 저베이스발 +50% 주간 성립
3. 반대로 쇼크가 빠르게 소진되고 연말 산타랠리로 VIX 급락, 6주 내내 미발생(확률 과대평가)

## [5] 최종 출력
- **최종 확률: 20%** (80% CI: 10~35%)
- **핵심 근거**:
  1. 경과 8주 미발생 확정적 정황(11/6 주간 +32%, 임계 미달)으로 결과는 잔여 6주 신규 스파이크에 전적으로 의존 [source: riotimesonline 2026-11-09]
  2. 활성 변동성 레짐+FOMC/쿼드위칭 촉매는 상승 요인이나, +50% 주간은 희귀·저베이스 조건부라 현재 고베이스(~25)에서 즉시 성립은 어려움
  3. 핵심 함정: 되돌림(저베이스)이 오히려 +50% 성립을 쉽게 하는 역설 — 단 되돌림+신규쇼크 '2단계' 모두 필요해 확률 제약
- **관찰 지표**:
  1. 향후 금요일 VIX 종가 레벨(되돌림 여부): 15~16대로 떨어지면 +50% 임계가 22~24로 낮아져 YES 확률 급등
  2. 12/18 FOMC·CPI 전후 주간 금→금 변동률 실측 (CBOE/FRED VIXCLS)

> **P1 참고 의견 — 자금 결정의 단독 근거 아님** (P3 게이트: 해소 50문항+ & Brier < 0.18 통과 전).

## [미검증] 항목
- 9월 각 금요일(W1~W6) VIX 종가 1차 교차검증 미완 — W1~W8 '미발생'은 정황근거 기반
- 10/30 금요일 종가 ≈19.4는 11/6 +32.03% 보도로부터 역산값(공식 종가 미확인)
- VIX 주간 종가 +50% 역사적 연간 빈도 정량치 NOT FOUND — 6주 base rate는 σ기반 추정
- 컨센서스 부재: VIX 주간 스파이크 빈도에 공표 컨센서스 없음, 레짐 기저율+GBM σ로 대체하여 CI를 넓게 설정
- 임계 z: 중심추정(베이스~25에서 반등 분포) 대비 +50% 임계는 로그 기준 약 2.8σ(주간 σ0.1468)지만 레짐·되돌림 불확실로 사실상 산포 매우 큼

## 리서치 구성
general(출처 72), devil(출처 72) — 증거 부록: `2026-11-09_vix-weekly-spike-50pct-by-2026-12-18_r1_evidence.md`
