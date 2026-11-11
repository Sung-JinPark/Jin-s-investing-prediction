---
forecast_id: 2026-11-09_fedfunds-upper-hold-2026ye_r1
question_id: fedfunds-upper-hold-2026ye
question_snapshot: 2026-12-31 시점 FOMC 성명서 기준 연방기금금리 목표범위 상단이 3.75% 이하로 유지될 확률은?
timestamp: 2026-11-09 14:53 KST
phase: P1
model: claude-opus-4-8
provider: anthropic
model_snapshot: claude-opus-4-8
provider_version: reasoning_core_v1_1
prompt_version: reasoning_core_v1_1
probability: 4
ci80: [2, 9]
window_end: null
snapshots: {}
market_implied: null
edge: null
research_status: ok_low_primary
sources_count: 152
method: p1-pipeline/2agents
cost_usd: 2.3889
ensemble_runs: [4]
divergence: null
shadow_extremized: 1
digest_hash: b87035d004cdafd338a2f39a71593cf70b6267e96b172de4e510610733168731
digest_inputs: {ml_run_ts: '2026-11-07T10:32:38', context_run_ts: '2026-11-05T19:20:59', ml_history_file: data/ml_history/, market: null}
pipeline_tier: standard
registered_tier: lite
ml_divergence_pp: null
divergence_note: null
divergence_class: null
research_quality:
  sources: {t1: 1, t2: 1, t3: 4, t4: 1, unknown: 12}
  n_urls: 19
  primary_ratio: 0.105
---

## [0] 질문 검증
기한(2026-12-31)·임계값(목표범위 상단 ≤3.75%)·판정출처(Fed 공식 성명서) 모두 명확. 현재 상단 4.00%이므로 YES 성립=12월 FOMC(12/8–9 추정) 25bp 인하 필수. 해소가능 질문.

## [1] Outside View — base rate (anchor: 6%)
참조 클래스: 현재 정책금리 상단이 임계치보다 25bp 높고, 시장이 인하가 아닌 동결~인상을 가격화하며 직전 회의 반대표마저 인상 방향인 상황에서 '단일 회의 내 매파→비둘기 180° 선회(인하)'가 발생할 빈도

- 12월 FOMC 인상확률 시장가격 74~81%, 인하 가격반영 ≈0% [source: rateprobability.com 2026-11-08; fool.com 2026-11-08; centralbank.watch]
- 9월 SEP 중앙값 연말 4.1%=추가 1회 인상 시사, 10/28 반대표 2명(Cook·Hammack) 모두 인상 방향 [source: cmelitegroup.com 2026-11-04; am.jpmorgan.com 2026-10-28]
- 역사적 매파→비둘기 급반전(2018.12→2019, 1998 LTCM 긴급인하, 2020.3)은 모두 외생적 금융위기 동반 — 위기 부재 시 6주 내 선회 기저율 매우 낮음 [source: devil 보고서 선례]

## [2] Inside View — 보정
| 증거 | 방향 | 조정 |
|---|---|---|
| 시장 12월 인상 74~81%, 인하 가격반영 ≈0% — YES 조건과 정반대 [source: rateprobability.com/fool.com 2026-11-08] | ↓ | −2%p |
| 9월 SEP 연말 중앙값 4.1%+10/28 반대표 2명 모두 인상 방향 → 위원회 무게중심 인상 [source: am.jpmorgan.com 2026-10-28; cmelitegroup.com 2026-11-04] | ↓ | −1%p |
| Warsh '위기 시 돌변' 성향+금융스트레스발 인상기대 후퇴(84→74%)+선거 후 정치충격 → 급성 위기→12월 인하 꼬리위험 [source: cnbc.com 2026-10-28; fxstreet.com 2026-11-09; aol.com 2026-11-08] | ↑ | +1%p |

## [3] 분해 트리
YES = (12월 회의가 12/31 이전 개최=거의 확실) AND (해당 회의에서 25bp 인하 결정). 인하 결정 경로 ≈ P(외생적 금융/신용 위기 또는 고용 급랭 발생)×P(그 충격에 Fed가 인하로 대응) ≈ 0.08×0.5 ≈ 4%. 홀드(상단 4.00%)·인상(4.25%)은 모두 NO. 결합결과 ~4%는 [2] 조정결과(4%)와 일치.

## [4] Premortem — 이 예측이 크게 틀렸다면
1. 11/18 공개 10월 지표 및 11월 고용/CPI가 급랭으로 나와 비둘기 피벗 촉발 (현재 NOT FOUND, 꼬리위험)
2. 지역은행·사모신용발 급성 신용이벤트 발생 → 비상 인하 (1998·2020 선례)
3. 선거 후 관세 철회·물가 하락 기류가 예상보다 빠르게 인하 명분 제공 [source: aol.com 2026-11-08]

## [5] 최종 출력
- **최종 확률: 4%** (80% CI: 2~9%)
- **핵심 근거**:
  1. 현재 상단 이미 4.00%로 임계치 초과 — YES는 '추가 인하' 전제로만 성립 [source: cnbc.com 2026-10-28, 교차검증]
  2. 시장·SEP·반대표 모두 인상 방향을 가리켜 인하 전환은 6주 만의 180° 선회로 외생적 위기 필요
  3. 데블스 애드버킷도 방향은 NO 인정하되 꼬리위험으로 YES 3~7% 유지 권고
- **관찰 지표**:
  1. CME FedWatch 12월 인하 확률(현재 ≈0%)이 유의하게 상승하는지
  2. 11/18 10월 지표 및 11월 고용/CPI의 급랭 서프라이즈 또는 급성 금융·신용 스트레스 발생 여부

> **P1 참고 의견 — 자금 결정의 단독 근거 아님** (P3 게이트: 해소 50문항+ & Brier < 0.18 통과 전).

## [미검증] 항목
- 12월 FOMC 공식 일정 본문 확인 실패(12/8–9 추정) [NOT FOUND]
- 11월 고용·CPI 급랭 데이터 미확인 [NOT FOUND]
- 인상확률 수치는 시장가격·일부 저급 출처 기반
- (a) 전제 개정 취약성: 현재 상단 4.00%·10월 동결은 공시 확정이라 개정 위험 낮음; 단 11월 고용/CPI 초판치가 개정되면 인하 명분 평가가 바뀔 수 있음
- (b) 컨센서스: 명시적 '인하확률' 컨센서스는 ≈0%로 존재, 대신 '인상확률 74~81%' 중심추정 사용, 산포 넓음(84→74% 변동)
- (c) 임계 z: 이진 정책결정이라 연속 σ 정의 곤란 — z 계산 비적용, 대신 레짐 기저율·시장가격으로 저확률 산정

## 리서치 구성
general(출처 77), devil(출처 75) — 증거 부록: `2026-11-09_fedfunds-upper-hold-2026ye_r1_evidence.md`
