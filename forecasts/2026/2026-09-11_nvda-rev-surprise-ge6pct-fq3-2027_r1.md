---
forecast_id: 2026-09-11_nvda-rev-surprise-ge6pct-fq3-2027_r1
question_id: nvda-rev-surprise-ge6pct-fq3-2027
question_snapshot: NVIDIA가 Q3 FY2027 실적에서 보고하는 연결 총매출이, 발표 직전 스냅샷된 컨센서스의 1.06배 이상일 확률은?
timestamp: 2026-09-11 11:28 KST
phase: P1
model: claude-opus-4-8
provider: anthropic
model_snapshot: claude-opus-4-8
provider_version: reasoning_core_v1_1
prompt_version: reasoning_core_v1_1
probability: 13
ci80: [6, 28]
window_end: null
snapshots: {}
market_implied: null
edge: null
research_status: ok_low_primary
sources_count: 138
method: p1-pipeline/2agents
cost_usd: 2.753
ensemble_runs: [13]
divergence: null
shadow_extremized: 4
digest_hash: null
digest_inputs: null
pipeline_tier: standard
registered_tier: standard
ml_divergence_pp: null
divergence_note: null
divergence_class: null
research_quality:
  sources: {t1: 1, t2: 0, t3: 5, t4: 0, unknown: 8}
  n_urls: 14
  primary_ratio: 0.071
---

## [0] 질문 검증
기한(2026-11-25 발표)·임계값(R≥C×1.06)·판정출처(SEC EDGAR 8-K Ex-99.1 손익 최상단 매출)가 명확. 컨센서스 스냅샷 C는 발표 직전 중앙값으로 고정. 해소가능 형태이며 추가 확인 불필요.

## [1] Outside View — base rate (anchor: 15%)
참조 클래스: NVIDIA 분기 연결매출의 컨센서스 대비 서프라이즈가 +6% 이상인 사건 (분기 실적 발표)

- 최근 확인 6개 분기 매출 서프라이즈 +0.9%~+4.68%, ≥6% 도달 0/6 [source: chartmill.com; investing.com; futurumgroup.com]
- 최근 4개 분기 평균 매출 서프라이즈 +0.9% [source: chartmill.com]
- 2023~24 AI 램프기: Sep2023 +12.4%, Dec2023 +7.19%, Mar2024 +5.66% — 신제품 램프 분기에 6%+ 다수 발생 [source: benzinga.com]

## [2] Inside View — 보정
| 증거 | 방향 | 조정 |
|---|---|---|
| 최근 6개 분기 서프라이즈 3~5%대로 압축, ≥6% 0/6 [source: chartmill.com; investing.com] | ↓ | −4%p |
| 컨센서스가 이미 가이던스($108B) 상단 부근($108.45~108.89B)에 형성 → +6% 문턱 높음 [source: investing.com; seekingalpha.com] | ↓ | −3%p |
| 中國 매출 가이던스에 0 반영 + 공급 언락 시 Rubin 램프 인플렉션 → 우측 꼬리 가능 [source: investing.com/Reuters; finance.yahoo.com] | ↑ | +6%p |
| 회사가 메모리 원가·공급 제약으로 '수요 전량 충족 불가' 경고, 가이드가 공급 한도에 맞춰짐 → 상방 캡 [source: investing.com 2026-08-26] | ↓ | −2%p |
| 프리모템: 中國 H200 재개 실제 여부 NOT FOUND(최대 스윙요인)이나 미실현 가능성이 더 크고 컨센 상향 표류가 임계선을 높임 — 순 소폭 상방만 반영 | ↑ | +1%p |

## [3] 분해 트리
YES 성립 = (R이 가이던스 중값 대비 약 +7% 초과 착지) AND (C가 발표 전 크게 상향 표류하지 않음). 서프라이즈 ≥6% 확률 ~15%, 그중 임계선 상승 상쇄 고려 시 하향. 트리거는 OR 구조(中國재개 OR 공급언락 OR 컨센 경직) 중 하나만 강하게 터져도 가능하나 각 개별 확률 낮음. 결합 추정 ~12~13%로 [2] 조정치와 정합.

## [4] Premortem — 이 예측이 크게 틀렸다면
1. 中國 데이터센터 칩(H200/H20) 판매가 분기 중 재개되어 가이던스 미반영분이 R에 그대로 얹힘 → 6%+ 초과
2. Rubin/Blackwell 공급 병목(HBM·CoWoS)이 예상보다 풀려 '눌러둔' 가이드를 대폭 초과 출하
3. 컨센서스 C가 가이드에서 거의 못 올라 임계선이 낮게 고정되어 동일 서프라이즈로도 YES 근접

## [5] 최종 출력
- **최종 확률: 13%** (80% CI: 6~28%)
- **핵심 근거**:
  1. 최근 6개 분기 매출 서프라이즈 전부 6% 미만(0/6), 최대 +4.68% — 기저율이 강하게 NO 지지 [source: chartmill.com; investing.com]
  2. 컨센서스가 가이던스 상단에 형성되어 +6% 초과 장벽이 구조적으로 높음 [source: investing.com]
  3. 中國 재개·공급 언락·Rubin 램프 등 우측 꼬리 벡터가 존재해 완전 배제는 불가(2023~24 선례) [source: investing.com/Reuters; benzinga.com]
- **관찰 지표**:
  1. 발표 전 中國 H200/H20 데이터센터 출하 재개 여부 및 규모 (가이던스 미반영 상방)
  2. 발표 직전 컨센서스 스냅샷 C의 최종값과 상향 표류 정도 (임계선 $114~115B 근처 변동)

> **P1 참고 의견 — 자금 결정의 단독 근거 아님** (P3 게이트: 해소 50문항+ & Brier < 0.18 통과 전).

## [미검증] 항목
- 최종 스냅샷 컨센서스 C 값 미확정 (현재 후보 $108.45~108.89B, 발표 임박 시 상향 가능)
- 발표 시점 中國 H200 실제 출하 상태 NOT FOUND
- Q3 FY26 실제 매출 확정치 NOT FOUND (역산 추정 ≈$56.8~57.0B)
- 2023 AI붐 초기 대형 서프라이즈 수치 일부는 저신뢰 출처(benzinga) — 단독 근거 아님

## 리서치 구성
general(출처 67), devil(출처 71) — 증거 부록: `2026-09-11_nvda-rev-surprise-ge6pct-fq3-2027_r1_evidence.md`
