<p align="center">
  <a href="https://sung-jinpark.github.io/Jin-s-investing-prediction/">
    <img src="docs/readme-hero.svg" width="100%" alt="Jin's Investing Prediction — evidence-conditioned market outlook">
  </a>
</p>

<p align="center">
  <a href="https://github.com/Sung-JinPark/Jin-s-investing-prediction/actions/workflows/verify.yml"><img src="https://github.com/Sung-JinPark/Jin-s-investing-prediction/actions/workflows/verify.yml/badge.svg?branch=main" alt="Verify"></a>
  <a href="https://github.com/Sung-JinPark/Jin-s-investing-prediction/actions/workflows/pages.yml"><img src="https://github.com/Sung-JinPark/Jin-s-investing-prediction/actions/workflows/pages.yml/badge.svg?branch=main" alt="Pages"></a>
  <img src="https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/use-research%20only-FF6B35" alt="Research only">
</p>

<p align="center">
  <a href="https://sung-jinpark.github.io/Jin-s-investing-prediction/"><strong>라이브 대시보드</strong></a>
  · <a href="https://sung-jinpark.github.io/Jin-s-investing-prediction/#future">세 가지 전망</a>
  · <a href="https://sung-jinpark.github.io/Jin-s-investing-prediction/#statistics">닷컴 비교 통계</a>
  · <a href="forecasts/2026/">공개 예측 기록</a>
</p>

# Jin's Investing Prediction

**시장 데이터에서 세 가지 미래 경로를 만들고, 왜 그런 전망이 나왔는지까지 보여주는 오픈 리서치 솔루션입니다.**

숫자만 던지는 예측기가 아닙니다. 현재 시장, 미래 시나리오, 닷컴버블 비교, 데이터 출처와 과거 예측 기록을 하나의 화면에서 연결합니다.

> 현재 세 경로는 <code>research candidate · degraded · 적격 사건 1/60</code>입니다. 공식 확률이나 매매 신호가 아니며, 기준 champion 모델과 분리되어 표시됩니다.

## 한눈에 보기

| **TODAY** | **FUTURE** | **STATISTICS** | **TRUST** |
|---|---|---|---|
| 지금 시장의 위치 | 상승·균형·스트레스 경로 | 닷컴과 AI 사이클 비교 | 출처·시점·예측 이력 |
| 핵심 신호만 요약 | 서로 다른 DB 레이어 | IPO·유동성·금리·밸류에이션 | 변경 기록과 검증 상태 |
| [오늘 보기](https://sung-jinpark.github.io/Jin-s-investing-prediction/#today) | [전망 보기](https://sung-jinpark.github.io/Jin-s-investing-prediction/#future) | [통계 보기](https://sung-jinpark.github.io/Jin-s-investing-prediction/#statistics) | [검증 보기](https://sung-jinpark.github.io/Jin-s-investing-prediction/#trust) |

## 데이터가 전망이 되는 과정

~~~mermaid
flowchart LR
    A["공개 시장·거시 데이터"] --> B["시점·출처 검증"]
    B --> C{"독립 시나리오 엔진"}
    C --> S1["S1 확장"]
    C --> S2["S2 균형"]
    C --> S3["S3 스트레스"]
    S1 --> D["한 화면의 전망 그래프"]
    S2 --> D
    S3 --> D
    D --> E["예측 기록·오차 검증"]
~~~

## 세 가지 경로, 세 가지 데이터 세계

| 경로 | 바라보는 시장 | 핵심 데이터 레이어 |
|---|---|---|
| **S1 확장** | AI 투자와 완화가 이어지는 국면 | 닷컴 확장 · 금리 완화 · AI 성장 |
| **S2 균형** | 성장과 부담이 맞서는 국면 | 연착륙 · 횡보 · 중립 거시 |
| **S3 스트레스** | 긴축과 성장 둔화가 겹치는 국면 | 닷컴 붕괴 · GFC · 신용·금리 스트레스 |

세 경로는 현재 지수 기준점과 거래일 달력만 공유합니다. 에피소드 DB, 특징 스키마, 잔차 풀과 국면 전환 구조는 서로 분리됩니다. 굵은 선은 조건부 중앙값, 점선은 실제 모의 경로, 음영은 경로 범위입니다.

## 닷컴버블과 지금을 같은 눈금으로

<code>Statistics Lab</code>은 1995~1999와 2023~현재를 같은 경과축에 맞춥니다.

- 유동성: M2, 현금성 자산, Fed 순유동성
- 자본시장: IPO 건수, 중소형 확산, 시장 흡수 강도
- 가격과 금리: PER, 장단기 금리차, 회사채 압력
- 경기와 물가: HMI, 제조업 확산, 유가·구리·CPI
- 한국시장 확산도: KOSPI·KOSDAQ·반도체 실제 일봉과 전일 SOX·대만 TAIEX 20일 충격

AI 현재선은 마지막 실제 관측에서 멈춥니다. 없는 미래 데이터를 예측선처럼 이어 붙이지 않습니다.

## 신뢰를 만드는 네 가지 규칙

| 원칙 | 시스템의 행동 |
|---|---|
| **Point in time** | 전망 기준시각 이후 공개된 데이터는 과거 예측에 사용하지 않습니다. |
| **Append only** | 예측·수정·방법 변경 이력을 지우거나 덮어쓰지 않습니다. |
| **Clear separation** | 연구 후보, 기준 모델, 역사 실측, 조건부 가정을 구분합니다. |
| **No fake data** | 데이터가 없으면 임의 숫자 대신 미산출 상태를 보여줍니다. |

## 60초 로컬 실행

~~~bash
uv sync
uv run pytest -q
uv run ai-fc dashboard --serve --host 127.0.0.1
~~~

주요 데이터 갱신:

~~~bash
uv run ai-fc scenario
uv run ai-fc cross-asset
uv run ai-fc market-extensions
uv run ai-fc statistics-refresh
~~~

## 프로젝트 지도

| 찾는 내용 | 위치 |
|---|---|
| 예측 질문과 공개 기록 | [questions/](questions/) · [forecasts/](forecasts/) |
| 시장·통계 데이터 | [data/](data/) |
| 모델과 대시보드 코드 | [src/ai_fc/](src/ai_fc/) |
| 아키텍처와 모델 설명 | [아키텍처](docs/ARCHITECTURE.md) · [모델 레지스트리](docs/MODEL_REGISTRY.md) |
| 한계와 검토 자료 | [알려진 한계](docs/KNOWN_LIMITS.md) · [reports/reviews/](reports/reviews/) |

---

<p align="center">
  <strong>Evidence first. Scenario aware. Fully auditable.</strong><br>
  정보 제공 목적의 투자 리서치 시스템이며 자동매매·주문 실행·수익 보장 서비스가 아닙니다.
</p>
