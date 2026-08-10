# AI Investing Scenario Graph V4 — Model Decision Memo

## Decision

현재 저장소의 목표와 제약에 가장 적합한 Shadow challenger는 다음이다.

```text
Continuous-Horizon Regime-Conditioned Filtered Historical Simulation
with Stationary Block Bootstrap
RCFHS-SB v1
```

이 선택은 보편적으로 가장 정확한 금융예측 모델이라는 뜻이 아니다. 현재 시스템이 요구하는 다음 조건을 동시에 만족하는 최적의 균형안이라는 뜻이다.

- 252거래일 연속 경로
- fat-tail·변동성 군집·drawdown을 단순 GBM보다 현실적으로 표현
- S1/S2/S3 조건부 분포
- 실제 ensemble member 대표선
- point-in-time 재현성
- NumPy·SciPy만으로 구현 가능
- 모델·입력·seed·source residual lineage 감사 가능
- legacy snapshot과 official probability 보존

## Why not three separate hand-tuned scenario generators

S1에는 높은 drift, S3에는 음의 drift를 직접 주면 세 선은 쉽게 달라진다. 그러나 그 차이는 모델이 발견한 것이 아니라 개발자가 집어넣은 전제가 된다. 따라서 V4는 하나의 coherent joint generator에서 path를 만든 뒤 기존 S1/S2/S3 정의로 분류한다.

시나리오별 후속 분포가 여전히 비슷하면 `SCENARIO_DYNAMICS_OVERLAP_HIGH`를 표시해야 한다. 시각적 차이를 만들기 위한 noise, endpoint forcing, fixed correction dates는 금지한다.

## Statistical engine

1. state_t는 t까지의 trailing feature로 STRESS/RECOVERY/EXPANSION/RANGE를 계산한다.
2. next-day return r_(t+1)을 state_t와 정렬한다.
3. state drift를 강하게 global mean으로 shrink한다.
4. EWMA와 GARCH(1,1) 후보로 conditional volatility를 추정한다.
5. standardized empirical residual을 만든다.
6. current simulated regime에 맞는 historical residual start에서 geometric block을 뽑는다.
7. residual block을 연속 재표본화하며 D+252까지 price·variance·regime을 전달한다.
8. 기존 S1/S2/S3 rule로 path를 분류한다.
9. scenario별 quantile fan과 actual representative path를 계산한다.

## Visualization

기본은 three small multiples다.

- p10~p90 fan
- p25~p75 fan
- dashed p50 statistical summary
- solid actual representative path
- official weight와 shadow implied weight 분리
- D=100/shared-axis 기본
- 2026/2027은 같은 output의 slice

## Promotion policy

V4는 먼저 Shadow로 구현한다. rolling-origin CRPS/WIS, interval coverage, Energy/Variogram score, path realism, PIT 검증을 통과하기 전에는 champion으로 승격하지 않는다.
