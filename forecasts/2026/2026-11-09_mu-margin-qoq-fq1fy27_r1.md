---
forecast_id: 2026-11-09_mu-margin-qoq-fq1fy27_r1
question_id: mu-margin-qoq-fq1fy27
question_snapshot: Micron이 FQ1 FY2027 실적 발표(2026년 12월 하순 예상)에서 보고하는 GAAP 총마진(%)이 직전 분기(FQ4 FY2026) 대비 하락할 확률은?
timestamp: 2026-11-09 15:07 KST
phase: P1
model: claude-opus-4-8
provider: anthropic
model_snapshot: claude-opus-4-8
provider_version: reasoning_core_v1_1
prompt_version: reasoning_core_v1_1
probability: 60
ci80: [46, 73]
window_end: null
snapshots: {}
market_implied: null
edge: null
research_status: ok_low_primary
sources_count: 146
method: p1-pipeline/2agents
cost_usd: 1.9214
ensemble_runs: [60]
divergence: null
shadow_extremized: 67
digest_hash: b87035d004cdafd338a2f39a71593cf70b6267e96b172de4e510610733168731
digest_inputs: {ml_run_ts: '2026-11-07T10:32:38', context_run_ts: '2026-11-05T19:20:59', ml_history_file: data/ml_history/, market: null}
pipeline_tier: standard
registered_tier: standard
ml_divergence_pp: null
divergence_note: null
divergence_class: null
research_quality:
  sources: {t1: 4, t2: 1, t3: 8, t4: 1, unknown: 9}
  n_urls: 23
  primary_ratio: 0.217
---

## [0] 질문 검증
기한(2026-12-31 내 FQ1 FY2027 발표)·임계값(FQ4 FY2026 GAAP GM 86.8%)·판정출처(Micron IR 보도자료) 모두 명확. 해소가능. 발표일 자체는 12/16~12/23 집계처별 불일치이나 기한 내 발표는 사실상 확실.

## [1] Outside View — base rate (anchor: 65%)
참조 클래스: 반도체 상승사이클 중 경영진이 차분기 GAAP 총마진을 순차 하락으로 명시 가이드하고 '바닥(floor)'이라 코멘트한 분기 → 실제 보고 총마진이 전분기 대비 하락하는가

- Micron 최근 6개 분기 GAAP GM 연속 순차 상승(FQ4-25 44.7% → FQ3-26 84.6% → FQ4-26 86.8%) [source: stocktitan.net/news/MU, 2026-09-30] — 순차하락 거의 없었음(상승국면)
- Micron의 GM 가이던스 상회 습관: FQ4-26 가이드 ~86%→실제 86.8%(+0.8%p), FQ3-26 가이드 ~81%→실제 84.6%(+3.6%p) [source: sec.gov a2026q3ex991, 2026-06-24] — 최근 beat 폭이 모두 가이던스 하락폭 0.85%p를 초과
- 사이클 피크/공급완화 시에만 순차하락 전환(FY2018 고점 ~61%) — 현재는 피크국면 아님 [source: stocktitan.net/articles, 2026-09-30]

## [2] Inside View — 보정
| 증거 | 방향 | 조정 |
|---|---|---|
| 회사 GAAP 가이던스 중앙값 ~85.95%로 전분기 86.8% 대비 -0.85%p 하락 명시 + CFO 'FQ1=연중 바닥' 반복 [source: sec.gov 8-K a2026q4ex991, 2026-09-30] | ↑ | +5%p |
| FQ1에 집중된 ~$10억 성과급 재고흡수·가동초기비용이 구조적 GAAP 원가 역풍으로 beat 폭을 과거보다 억제 [source: zerohedge.com, 2026-09-30] | ↑ | +5%p |
| 최근 2분기 연속 가이던스 상회폭(+0.8~3.6%p)이 하락폭 0.85%p를 초과 → 평소 beat만 재현돼도 86.8% 동률·상회 가능 [source: sec.gov a2026q3ex991; stocktitan, 2026-09-30] | ↓ | −10%p |
| DRAM/NAND ASP 급등 지속(FQ4 DRAM high-teens%, NAND ~+30%), 10~12월 현물가 추가 급등 시 ASP 레버리지가 원가역풍 압도 [source: finance.yahoo.com, 2026-10-02] | ↓ | −5%p |

## [3] 분해 트리
YES(하락) = P(FQ1 실제 GAAP GM < 86.8%). 핵심 분기점: 가이던스 85.95% 대비 beat 폭이 0.85%p를 넘느냐. (A) beat≤0.85%p → 86.8% 미만 유지 → YES. (B) beat>0.85%p → 86.8% 상회 → NO. 과거 beat 분포는 +0.8~3.6%p로 중앙값이 0.85%p 부근~초과 → 양방향 가능. 다만 이번엔 ~$10억 일회성 GAAP 원가가 beat 여력을 제약, floor 코멘트로 상방 억제. 종합 YES가 최빈이나 beat 습관이 결과를 사구간으로 끌어내림 → ~60%.

## [4] Premortem — 이 예측이 크게 틀렸다면
1. 10~12월 메모리 현물·계약가가 가이던스 가정 초과로 추가 급등, Micron under-ship으로 ASP 레버리지 극대화 → GAAP GM 87%+로 순차 상승(NO)
2. 회사의 체계적 보수 가이던스 + 2분기 연속 +200bp beat 전력이 이번에도 재현되어 86.8% 동률/상회(NO)
3. ~$10억 원가가 Non-GAAP엔 반영되나 GAAP 일회성 조정 방향이 유리하게 작동해 GAAP GM이 예상보다 높게 착지(NO)

## [5] 최종 출력
- **최종 확률: 60%** (80% CI: 46~73%)
- **핵심 근거**:
  1. 회사가 GAAP 총마진을 -0.85%p 하락으로 직접 가이드하고 CFO가 'FQ1=연중 바닥' 명시, ~$10억 구조적 원가 역풍 적시 → YES 방향 강력 [source: sec.gov 8-K, 2026-09-30]
  2. 그러나 Micron의 최근 beat 폭(+0.8~3.6%p)이 하락폭 0.85%p를 초과해 평소 beat만 재현돼도 86.8% 상회 가능 → NO 상당한 여지 [source: sec.gov a2026q3ex991]
  3. 임계가 가이던스·예상 착지점에서 1σ 이내(사구간)라 확률을 극단화하지 않고 60% 부근 유지
- **관찰 지표**:
  1. 2026Q4~2027Q1 DRAM/NAND 계약·현물 ASP 상승률(TrendForce 등) — 가이던스 가정 대비 추가 급등 시 NO 쪽
  2. 발표일(12/16~23) 실제 보고 GAAP 총마진치 및 Non-GAAP 대비 GAAP 조정 방향

> **P1 참고 의견 — 자금 결정의 단독 근거 아님** (P3 게이트: 해소 50문항+ & Brier < 0.18 통과 전).

## [미검증] 항목
- FQ1 FY2027 실제 GAAP 총마진 보고치: NOT FOUND(미발표)
- 공식 확정 발표일: NOT FOUND(집계처 12/16~12/23 불일치)
- 2026Q4~2027Q1 DRAM/NAND 분기 계약가 구체 상승률(TrendForce): NOT FOUND
- 정확한 GAAP 가이던스 소수점(85.x%): 매체 표기 상충, 정확값 NOT FOUND
- street 컨센서스(비회사) GAAP GM 추정 정확값: NOT FOUND — 회사 가이던스 ~85.95%를 중심추정으로 사용, beat 산포 ±1~2%p

## 리서치 구성
general(출처 73), devil(출처 73) — 증거 부록: `2026-11-09_mu-margin-qoq-fq1fy27_r1_evidence.md`
