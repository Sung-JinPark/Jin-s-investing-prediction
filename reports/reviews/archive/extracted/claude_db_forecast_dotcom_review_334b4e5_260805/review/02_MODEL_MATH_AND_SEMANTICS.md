# 모델 산식·의미론 정밀 검토 포인트

## 1. NASDAQ DB 조건부 구조 경로

### 1.1 역사 형태 추출

미래 주차 `t`를 현재 AI 위상 이후의 fractional month로 변환하고, 선택된 혁신시대
`biotech2015`, `dotcom`, `japan1989`의 같은 위상 index ratio를 구한다.

```text
phase_month(t) = current_ai_phase + days(t) / 30.4375
analog_ratio(t) = median_e[ era_e(phase_month(t)) / era_e(current_ai_phase) ]
```

### 1.2 연도별 endpoint detrend

2026과 2027 각 segment에서 `analog_ratio`의 시작·끝을 잇는 기하 추세를 제거한다.
그 결과 시작·끝 잔차는 1이고 중간 굴곡만 남아야 한다.

```text
geometric_trend_i = start * (end/start)^(i/(n-1))
shape_residual_i = analog_ratio_i / geometric_trend_i
```

### 1.3 기존 조건부 종점과 결합

각 S 경로의 기존 segment 시작·끝을 잇는 기하 base에 residual의 strength 승을 곱한다.

```text
structural_path_i = scenario_geometric_base_i * shape_residual_i^strength
```

`strength`는 2026 S1 최대낙폭이 역사 DB의 correction-depth median `12.19%`에 맞도록
`[0,5]`에서 결정론적 이분 탐색한다. 동일 strength를 S2/S3와 2027에 재사용한다.

### 1.4 검토가 필요한 모델 위험

1. 선택된 세 혁신시대가 사후 성과에 의해 골라졌다면 selection leakage가 발생한다.
2. 2026 S1 하나로 strength를 맞춘 뒤 다른 시나리오/연도에 전이하는 외삽이 크다.
3. fan 분포와 구조선 생성 규칙이 다르므로 구조선이 fan의 중앙값처럼 읽히면 안 된다.
4. cross-era median은 소표본 3개이며 표준오차나 out-of-sample 검증이 없다.
5. 월간 위상을 주간 점에 선형 보간하므로 정확한 거래일 timing 근거가 없다.

## 2. 닷컴 5개년 교차자산 비교

### 2.1 관측 구간

- anchor: `2001-03`
- end: `2006-03`
- 월간 관측: 61개
- normalization: 첫 월 = 100
- 별도 dotcom peak 보조 anchor: `2000-03`

실측 전체 변화:

| 계열 | 2001-03→2006-03 |
|---|---:|
| NASDAQ | +27.1% |
| O 가격 | +82.7% |
| O 총수익 proxy | +151.5% |
| NASDAQ 2000-03 정점 기준 | -48.8% |

### 2.2 BTC 반사실 산식

```text
BTC_0 = 100
BTC_t = BTC_(t-1) × exp(beta_regime × log(NASDAQ_t/NASDAQ_(t-1)))
```

- NASDAQ 하락월: `downside_5y` beta
- NASDAQ 비하락월: `full_252d` beta
- 계산 입력은 직렬화된 NASDAQ index path이므로 snapshot에서 재현 가능해야 한다.

### 2.3 네 경우의 수

| case | 하락월 beta | 상승월 beta | 2006-03 BTC index |
|---|---:|---:|---:|
| `btc_low_beta` | 0.657 | 1.020 | 214.8 |
| `btc_regime_center` | 1.599 | 1.172 | 71.8 |
| `btc_high_beta` | 2.639 | 1.442 | 25.4 |
| `btc_full_beta` | 1.172 | 1.172 | 132.5 |

레짐 중심/고 beta 경로가 NASDAQ의 최종 상승에도 낮게 끝나는 이유는 하락월에 더 큰
beta가 적용되어 경로 의존 손실이 반복되기 때문이다.

### 2.4 검토가 필요한 모델 위험

1. 일간 beta를 월간 수익에 직접 적용하는 frequency mismatch.
2. 2026 현대 beta를 2001년 시장구조에 적용하는 regime transport risk.
3. downside beta는 최악 10% 일간 표본인데 모든 음(-)의 월에 적용한다.
4. p10/p90은 각각 추정된 beta marginal bounds이며 완전한 joint predictive band가 아니다.
5. 저 beta와 고 beta 경로의 pointwise min/max envelope는 confidence interval이 아니다.
6. BTC 자체 요인(반감기·규제·ETF·담보청산·스테이블코인)을 포함하지 않는다.

위 위험은 현재 결과를 폐기하는 자동 사유가 아니라, UI가 결과를 “2001년 BTC 역사”나
“향후 BTC 가격 전망”으로 오인시키지 못하도록 하는 핵심 의미론 게이트다.

## 3. 확률공간 분리

| 산출물 | 공간 | 허용 | 금지 |
|---|---|---|---|
| NASDAQ fan/S1-S3 | `scenario_conditional` | 모델 내부 조건부 분포 | physical-event와 산술 결합 |
| 조정 질문 | `physical_event` | 별도 등록 확률 박스 | 구조 경로 진폭 입력 |
| 혁신사이클·유동성·AI 레짐 | `reference_only` | 근거/상태 표시 | 가중치·경로 timing 입력 |
| 닷컴 교차자산 | `reference_only` | 역사/반사실 민감도 비교 | 사건확률·기대수익·시나리오 weight |

Claude는 어떤 UI 문자열·JSON 필드·테스트도 이 경계를 무너뜨리지 않는지 확인해야 한다.

