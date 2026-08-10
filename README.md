<h1 align="center">Jin's Investing Prediction</h1>

<p align="center"><strong>시장 전망을 그래프로 보고, 근거와 결과까지 확인하는 투자 리서치 솔루션</strong></p>

<p align="center">
<a href="https://sung-jinpark.github.io/Jin-s-investing-prediction/"><strong>라이브 대시보드</strong></a> ·
<a href="https://sung-jinpark.github.io/Jin-s-investing-prediction/#future">미래 전망 바로 보기</a> ·
<a href="forecasts/2026/">공개 예측 기록</a>
</p>

<p align="center">
<a href="https://github.com/Sung-JinPark/Jin-s-investing-prediction/actions/workflows/verify.yml"><img src="https://github.com/Sung-JinPark/Jin-s-investing-prediction/actions/workflows/verify.yml/badge.svg" alt="verify"></a>
<img src="https://img.shields.io/badge/python-3.12-blue" alt="Python 3.12">
<img src="https://img.shields.io/badge/forecast-research%20candidate-informational" alt="Research candidate">
</p>

## 한눈에 보는 기능

| 화면 | 바로 알 수 있는 것 |
|---|---|
| **오늘** | 현재 시장 상태와 다시 확인할 핵심 질문 |
| **미래 전망** | 다음 1개월·3개월·2026·2027의 세 가지 NASDAQ 경로 |
| **자산 비교** | NASDAQ·Bitcoin·Realty Income의 움직임 차이 |
| **유동성** | 시장 자금 흐름과 NASDAQ·Bitcoin 수익률의 동행 구간 |
| **기록과 검증** | 예측이 언제, 왜 바뀌었고 실제로 맞았는지 |
| **데이터와 신뢰** | 출처, 기준일, 누락 데이터와 검증 상태 |

대시보드는 정적 읽기 전용 사이트입니다. 웹페이지에서 주문을 내거나 예측 원장을 수정하지 않습니다.

## 미래 전망 그래프 읽는 법

세 시나리오는 같은 모델을 색만 바꾼 선이 아닙니다. 서로 다른 역사 데이터 군집을 사용합니다.

| 경로 | 주로 보는 데이터 | 화면에서의 의미 |
|---|---|---|
| **S1 확장** | 닷컴 가격 국면, 성장 지표, 정책 완화 | 상승이 이어지는 경우의 경로 |
| **S2 균형** | 현대 시장, 거시 지표, 회복 국면 | 횡보와 완만한 회복 경로 |
| **S3 스트레스** | 긴축, 금리 부담, 금융여건 악화 | 큰 조정과 회복 지연 경로 |

그래프에서는 세 경로를 하나의 로그 스케일에 겹쳐 보여줍니다.

- **굵은 선**: 해당 군집의 날짜별 중앙값(p50)
- **가는 점선**: 실제 모의 경로 중 중심에 가까운 사례
- **회색 영역**: 전체 혼합 전망의 중심 범위
- **경로 가중치**: 역사 군집을 섞는 연구 가중치이며, 상승·중립·하락의 보정된 발생확률은 아닙니다.

닷컴 유사도 강도 `0.60`은 S1에만 적용되고 S2·S3에는 적용되지 않습니다. 기존 시나리오별 DB, 가중치, 고용 성장위험과 금리 정책완화의 분리 구조는 유지됩니다.

## 숫자를 쉽게 해석하는 원칙

대시보드는 복잡한 모델명을 먼저 보여주지 않습니다. 고객 화면에서는 다음 순서로 설명합니다.

1. **숫자** — 현재 산출값
2. **뜻** — 무엇을 측정하는지
3. **주의점** — 확률인지, 참고 지표인지, 아직 검증 중인지

예를 들어 고용 약화는 성장 위험을 높일 수 있지만, 금리 부담 완화는 기술주 가치평가에 반대 방향으로 작용할 수 있습니다. 두 효과는 따로 계산하고 화면에서도 따로 설명합니다.

## Bitcoin·Realty Income·유동성

- NASDAQ과 Realty Income은 2001년 3월 이후 실제 가격을 사용합니다.
- Bitcoin은 2009년 이전 실측 가격이 없으므로 현대 민감도를 적용한 참고 경로만 표시합니다.
- 자산 가격은 시작값을 `100`으로 맞춰 방향과 회복 속도를 비교합니다.
- 유동성 화면의 `0`은 최근 1년 평균입니다. 양수는 평균보다 많은 자금, 음수는 적은 자금을 뜻합니다.
- 유동성과 가격이 함께 움직여도 인과관계나 상승 보장을 뜻하지 않습니다.

## 예측 기록을 신뢰할 수 있는 이유

- 공개된 예측은 기존 파일을 고치지 않고 새 회차로 추가합니다.
- 결과가 나온 모든 회차를 Brier 점수로 채점합니다.
- 당시 공개되지 않은 데이터는 예측에 사용할 수 없습니다.
- 공식 예측과 연구 후보, 참고 지표를 분리해 표시합니다.
- 데이터가 없으면 임의 숫자를 만들지 않고 `산출 전` 또는 `수집 전`으로 표시합니다.

다음 명령으로 공개 기록의 해시와 Git 이력을 직접 검증할 수 있습니다.

```bash
git clone https://github.com/Sung-JinPark/Jin-s-investing-prediction.git
cd Jin-s-investing-prediction
python tools/verify_track_record.py
```

## 개발자 빠른 시작

```bash
uv sync

# 전체 검증
uv run pytest -q

# 로컬 대시보드
cd src
python -m ai_fc dashboard --serve --host 127.0.0.1
```

주요 명령:

```bash
uv run ai-fc due               # 갱신·판정 대상 확인
uv run ai-fc sync --check      # 원장과 파생 인덱스 검증
uv run ai-fc scenario          # NASDAQ 연구 경로 갱신
uv run ai-fc cross-asset       # 교차자산 지도 갱신
uv run ai-fc market-extensions # 유동성·시장 신호 갱신
```

## 저장소 구조

| 경로 | 역할 |
|---|---|
| `questions/` | 무엇을 언제 어떤 기준으로 판정할지 정의 |
| `forecasts/` | 공개된 예측 회차와 근거 |
| `calibration/` | 결과·점수·벤치마크 원장 |
| `data/` | 시장 데이터와 연구 후보 산출물 |
| `src/ai_fc/` | 예측·검증·대시보드 엔진 |
| `docs/` | 설계, 감사 결과와 알려진 한계 |
| `reports/reviews/` | 현재 및 과거 검토 패키지 |

자세한 기술 문서는 [아키텍처](docs/ARCHITECTURE.md), [모델 레지스트리](docs/MODEL_REGISTRY.md), [알려진 한계](docs/KNOWN_LIMITS.md)에서 확인할 수 있습니다.

---

> 본 저장소와 대시보드는 투자 자문, 매매 권유 또는 수익 보장 서비스가 아닙니다. 연구 후보와 과거 사례는 미래 성과를 보장하지 않습니다.
