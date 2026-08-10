---
forecast_id: 2026-07-08_nvda-dc-beat-2026aug_r1
question_id: nvda-dc-beat-2026aug
question_snapshot: "NVIDIA가 2026-08-26(예정) 발표하는 분기 실적(Q2 FY2027)에서 Data Center 부문 매출이, 발표 직전(D-1) 시점의 애널리스트 컨센서스 추정치를 +5% 이상 상회할 확률은?"
timestamp: 2026-07-08 09:55 KST
phase: P0
model: claude-fable-5 (Claude Code)
prompt_version: reasoning_core_v1
probability: 11
ci80: [5, 20]
window_end: null
snapshots:
  consensus_total_revenue_now: "$91.7B (2026-06-30~07-08 시점 집계, Investing.com/nextearningsdate)"
  implied_dc_consensus_proxy: "$84.4B [미검증 — 자체계산: 총매출 컨센 $91.7B x 최근 2분기 DC비중 92.2%. 판정용 스냅샷은 D-1에 별도 채취]"
  company_guidance: "$91.0B ±2% (2026-05-20 제시, 중국향 DC컴퓨트 매출 0 가정)"
  reference_price: null
market_implied: null
edge: null
sources_count: 44
research_agent_tool_uses: 41
---

## [0] 질문 검증

기한(2026-08-26 발표일), 임계값(+5%), 판정기준(D-1 컨센 스냅샷 x 1.05 vs 발표 DC매출) 모두 명확 — 진행.
주의사항 1건: **DC 전용 컨센서스가 현재 공개 집계에서 확인 불가(NOT FOUND)**. 본 예측은 총매출 컨센 x DC비중의 프록시($84.4B)로 허들을 추정했으며, 실제 판정은 registry 조항대로 D-1 시점 스냅샷으로 한다. 프록시와 실제 스냅샷의 괴리는 premortem #1에 반영.

## [1] Outside View — base rate (anchor: 12%)

참조 클래스: "가이던스 앵커 시대(대형화 이후)의 NVDA 분기 실적 vs 컨센서스, +5% 이상 상회"

| base rate | 값 | 표본 |
|---|---|---|
| 총매출 +5% 이상 비트 | 2/9 ≈ 22% | 최근 9분기 (Q1 FY25~Q1 FY27). 단 2건 모두 2024년 |
| 총매출 +5% 이상 비트 (최근 레짐) | 0/6 | 최근 6분기 — 최대 +3.5%, 서프라이즈 폭이 3%대로 수렴 |
| DC매출 +5% 이상 비트 | 0/3 | 컨센 확인 가능 최근 3분기: −0.5%(미스), +3.1%, +3.3%. 마지막 +5% 초과는 2024-11 (+6.9%) |

매출 규모 확대($30B→$90B대)와 가이던스 앵커링으로 서프라이즈 폭이 구조적으로 압축된 최근 레짐에 가중치. Laplace 보정 (0+1)/(6+2)=12.5%와 장기 22%를 절충하되 최근 레짐 우선 → **anchor 12%**.

## [2] Inside View — 보정 (12% → 9%)

| 증거 | 방향 | 조정 | 근거 |
|---|---|---|---|
| 공급 제약 = 저분산: CoWoS 2027년까지 선점·수요가 공급 40~50% 초과, HBM3E 완판. 해당 분기(5~7월)는 예측 시점에 이미 ~95% 경과 — 출하량이 사실상 확정된 상태에서 회사가 중간에 가이던스 제시 | ↓ | −4%p | 매출 ≈ 공급능력이라 tail 서프라이즈가 구조적으로 어려움 |
| 컨센서스가 이미 가이던스 중간값($91.0B) 위($91.7B)로 상향 — 허들 자체가 올라감 | ↓ | −2%p | +5% DC비트에는 총매출 ~$95.5B(가이던스 상단 +3%) 필요 |
| 중국 매출 0 가정의 상방 옵션: H200 조건부 허용됐으나 중국 정부 보이콧·통관 불허(2026-01) 중 — 해제 시 순수 상방 | ↑ | +2%p | 발생확률 낮으나 비대칭 상방 |
| AI 하드웨어 수요 극단 강도: MU 컨센 +15.7% 비트·사상최고 마진(2026-06-24), 하이퍼스케일러 캐펙스 $725B(+77% YoY) 상향 사이클 | ↑ | +1%p | 다만 NVDA는 공급이 병목이라 수요 신호의 전이 제한적 |

SemiAnalysis "H2 FY2027 DC컴퓨트 컨센 +20% 상회" 주장(2026-06-30)은 **이번 분기(Q2)가 아닌 8월~1월(Q3·Q4) 대상**이라 이번 판정에 직접 적용 불가 — 차기 재예측(r2)의 핵심 변수로 이월. Inside view 결과: **9%**.

## [3] 분해 트리 (disjunctive)

```
DC매출 ≥ 컨센 x 1.05 (≈$88.6B, 총매출 환산 ~$95.5B)
├─ Path A: 유기적 출하 상회 (중국 없이 가이던스 상단 +3% 초과 출하)
│    공급제약 하 최근 최대 비트 +3.5% → P ≈ 6%
├─ Path B: 중국 H200 매출 인식 서프라이즈
│    P(보이콧/통관 해제 + 분기 내 인식) ≈ 10% x P(그것만으로 +5% 도달) ≈ 40% → P ≈ 4%
└─ 보정: DC컨센 프록시의 노이즈(총매출 대비 DC 전용 추정의 분산) → +1%p
결합 (OR, 중복 제거): ≈ 6% + 4% − 0.2% + 1% ≈ 10.8% ≈ 11%
```

[2]의 9%와 [3]의 11%가 2%p 차이 — 원인은 [3]이 컨센 프록시 불확실성을 명시적 가산항으로 넣었기 때문. 분해 쪽이 구조를 더 반영하므로 11% 채택.

## [4] Premortem — 이 예측이 크게 틀렸다면

1. **허들 오추정**: D-1 실제 DC 컨센이 프록시($84.4B)보다 낮게 형성되면(애널리스트들이 DC를 보수적으로 잡는 경향) 실질 허들이 내려가 확률을 과소평가한 것 — 상방 오류.
2. **덩어리 매출 인식**: OpenAI 10GW 파트너십 첫 1GW가 2026 하반기 Vera Rubin 배치 예정 — 인식 시점이 분기 말에 걸치면 lumpy 서프라이즈 가능. Rubin은 Q3 출하 예정이지만 선행 시스템 매출 가능성 배제 못함 — 상방 오류.
3. **레짐 과신**: "공급제약=저분산" 논리는 2024년에도 있었으나 +5.4%, +5.8% 비트가 나왔음. 최근 6분기 표본은 작다 — 상방 오류.

세 원인 모두 상방 방향 → 최종 확률을 [3]의 11%에서 내리지 않고 유지. (하방 premortem: 컨센이 발표 직전 추가 상향되면 허들이 더 올라감 — 이는 이미 [2]에 반영.)

## [5] 최종 출력

- **최종 확률: 11%** (80% CI: 5~20%)
- **핵심 근거 3줄**:
  1. DC매출 +5% 컨센 상회는 최근 확인 가능한 3분기 중 0회, 총매출 기준으로도 최근 6분기 중 0회 — 가이던스 앵커 시대에 사라진 사건.
  2. CoWoS·HBM 완판 상태에서 분기가 이미 대부분 경과 — 출하량이 사실상 확정돼 tail 서프라이즈 여지가 구조적으로 작음.
  3. 상방은 중국 옵션(가이던스가 0 가정)과 컨센 프록시 불확실성이나, 합쳐도 ~5%p 기여에 그침.
- **관찰 지표 2개** (확률을 바꿀 수 있는 것):
  1. D-1로 갈수록 공개되는 DC 전용 컨센서스 — $83B 아래로 형성되면 허들 하락으로 확률 상향 (r2에서 재평가).
  2. 중국 H200 통관·보이콧 뉴스 및 7~8월 TSMC 월매출/Rubin 조기출하 보도 — 해제·가속 신호 시 확률 상향.
- **직전 대비**: 첫 회차 (r1).

> **P0 참고 의견 — 자금 결정의 단독 근거 아님** (P3 게이트: 해소 50문항+ & Brier < 0.18 통과 전).

## 출처 목록 (리서치 서브에이전트 수집, 총 44개 URL)

판정 핵심 출처만 발췌 (전체는 리서치 보고서 원문 참조):
- NVIDIA Q1 FY2027 보도자료 (가이던스 $91.0B±2%, 중국 0 가정): https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-first-quarter-fiscal-2027 (2026-05-20)
- 컨센서스 $91.7B: https://www.investing.com/news/stock-market-news/nvidia-stock-gains-as-semianalysis-sees-h2-data-center-revenue-20-above-consensus-4768392 (2026-06-30)
- 비트 이력: CNBC 실적 기사 시리즈 (2024-08-28 ~ 2026-05-20), S&P Global (2024-05, 2026-05), Motley Fool (2026-05-22)
- 공급 제약: https://newsletter.semianalysis.com/p/ai-capacity-constraints-cowos-and, https://www.fusionww.com/insights/blog/inside-the-ai-bottleneck-cowos-hbm-and-2-3nm-capacity-constraints-through-2027
- 중국 상황: https://modeldiplomat.com/story/us-chip-export-curbs-impact-nvidia-in-china (2026)
- OpenAI 10GW/Rubin: https://openai.com/index/openai-nvidia-systems-partnership/ (2025-09), https://nvidianews.nvidia.com/news/vera-rubin-full-production-agentic-ai-factory (2026-06)
- 하이퍼스케일러 캐펙스 $725B: https://www.tomshardware.com/tech-industry/big-tech/big-techs-ai-spending-plans-reach-725-billion (2026)
- MU 실적: https://www.globenewswire.com/news-release/2026/06/24/3317151/14450/en/micron-technology-inc-reports-record-results-for-the-third-quarter-of-fiscal-2026.html (2026-06-24)

[미검증] 항목: Q2 FY2027 DC 전용 컨센서스(NOT FOUND — 프록시 사용), 8/26 옵션 내재 변동폭 현재치(NOT FOUND), Seeking Alpha 하향 보고서 세부.
