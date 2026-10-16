---
forecast_id: 2026-07-15_nvda-dc-beat-2026aug_r2
question_id: nvda-dc-beat-2026aug
question_snapshot: NVIDIA가 2026-08-26(예정) 발표하는 분기 실적에서 Data Center 부문 매출이, 발표 직전 시점의 애널리스트 컨센서스 추정치를 +5% 이상 상회할 확률은?
timestamp: 2026-07-15 11:12 KST
phase: P1
model: claude-opus-4-8
prompt_version: reasoning_core_v1
probability: 20
ci80: [10, 35]
window_end: null
snapshots: {}
market_implied: null
edge: null
sources_count: 149
method: p1-pipeline/2agents
cost_usd: 2.0104
ensemble_runs: [20]
divergence: null
---

## [0] 질문 검증
기한(2026-08-26 발표)·임계값(DC 매출 ≥ 컨센×1.05)·판정출처(NVIDIA IR + D-1 컨센 스냅샷) 명확. 다만 FY2027부터 보고체계 변경(Data Center/Edge 재분류, DC 내 Hyperscale·ACIE)으로 '컨센 집계 대상 = 발표 DC 정의'의 정합성이 판정 핵심 리스크. D-1 DC 전용 컨센 스냅샷을 반드시 별도 확보해야 함.

## [1] Outside View — base rate (anchor: 20%)
참조 클래스: NVIDIA Data Center 부문 분기 실적의 발표 직전 컨센서스 대비 서프라이즈 폭 분포 (특히 +5% 이상 상회 빈도)

- Q1 FY27(2026-05-20): 실제 DC $75.2B vs Visible Alpha 중앙 ~$72.8B → +3.3% (문턱 미달) [spglobal.com; sec.gov 8-K]
- Q1 FY26(2025-05-28): DC $39.1B vs Visible Alpha 컨센 $39.1B → 0% 정확 부합 (문턱 미달) [sec.gov; spglobal.com]
- Q2 FY26(2025-08-27): DC $41.1B, 컨센 ~$41B대와 대체로 부합~소폭 상회 → +5% 미달 추정 (컨센 정확치 NOT FOUND) [sec.gov 8-K q2fy26pr]

## [2] Inside View — 보정
| 증거 | 방향 | 조정 |
|---|---|---|
| SemiAnalysis 하반기 DC 매출 컨센 약 20% 상회 전망 [investing.com/yahoo, ~2026-07-01] | ↑ | +6%p |
| NVIDIA 가이던스 보수성(Q2 FY27 중국향 DC 컴퓨트 매출 0 가정) → 실제 상방 여지 [stocktitan, 2026-05-20] | ↑ | +4%p |
| 강세 전망(SemiAnalysis 등)이 이미 D-1 컨센을 끌어올려 서프라이즈 여력 상쇄 가능성 | ↓ | −4%p |
| 대수의 법칙: DC 기저 $75B+ → 5%=약 $4B 절대 서프라이즈 필요, %서프라이즈 구조적 압축 [intellectia.ai] | ↓ | −5%p |
| 가이던스 밀착형 컨센 수렴으로 최근 2개 분기 서프라이즈 0~+3.3%로 축소 | ↓ | −3%p |

## [3] 분해 트리
YES 성립 조건(AND): (A) 발표 DC 정의가 컨센 집계와 정합 [P≈0.85] AND (B) 실제 DC가 D-1 컨센을 +5% 이상 초과 [P≈0.22]. 결합 ≈ 0.85×0.22 ≈ 0.19. (B)는 절대금액 ~$4B 초과 달성이 필요하며 최근 실측 서프라이즈(0~+3.3%)로는 미달. 램프 초입 조기출하·중국 재개 등 상방 촉매가 있으나 컨센 선반영으로 부분 상쇄. 결합결과(19%)와 [2] 조정결과(약 18%)가 근접해 정합적.

## [4] Premortem — 이 예측이 크게 틀렸다면
1. Rubin/Blackwell 조기 램프 및 중국향 매출 예상외 재개로 DC가 가이던스를 $4B+ 초과 달성 → 대형 서프라이즈 실현
2. D-1 컨센이 강세 전망을 과소반영해 실제 대비 낮게 고정 → 상대적 +5% 초과 용이
3. 보고 재분류로 발표 DC(Hyperscale+ACIE 합산)가 컨센 집계보다 넓게 잡혀 명목상 큰 상회로 판정

## [5] 최종 출력
- **최종 확률: 20%** (80% CI: 10~35%)
- **핵심 근거**:
  1. 확인 가능한 최근 분기 DC 서프라이즈는 0~+3.3%로 모두 +5% 문턱 미달이며 컨센이 가이던스에 밀착 수렴하는 구조
  2. DC 기저가 $75B+로 커져 +5%=약 $4B 절대 서프라이즈가 필요해 %상회가 구조적으로 압축됨
  3. SemiAnalysis 등 강세 촉매는 존재하나 컨센에 선반영될수록 초과달성 여력을 오히려 낮춤
- **관찰 지표**:
  1. D-1(2026-08-25) DC 전용 컨센 중앙값 스냅샷 및 가이던스($91B ±2%, DC 함의 ~$84~85B) 대비 위치
  2. 2026-07~08월 하이퍼스케일러 capex 가이던스 업데이트 및 중국 수출규제(H20/컴퓨트 재개) 관련 정책 변화

> **P1 참고 의견 — 자금 결정의 단독 근거 아님** (P3 게이트: 해소 50문항+ & Brier < 0.18 통과 전).

## [미검증] 항목
- Q2 FY27(대상 분기) D-1 DC 전용 컨센 중앙값 미확보 (검색 한도) — NOT FOUND
- DC 가이드 $82~85B는 총매출 $91B×~90% 역산 추정치로 공식 수치 아님
- Q2 FY26 컨센 정확치 미확보로 'in-line' 판단은 추정
- FY2027 보고 재분류가 'Data Center' 정의에 미치는 정확한 영향 미확인
- SemiAnalysis +20% 전망은 IB/블로그급 출처로 단독 조정근거 아님

## 리서치 구성
general(출처 74), devil(출처 75) — 증거 부록: `2026-07-15_nvda-dc-beat-2026aug_r2_evidence.md`
