<p align="center">
  <a href="https://sung-jinpark.github.io/Jin-s-investing-prediction/">
    <img src="docs/readme-hero.svg" width="100%" alt="Jin's Investing Prediction">
  </a>
</p>

<p align="center">
  <a href="https://github.com/Sung-JinPark/Jin-s-investing-prediction/actions/workflows/verify.yml"><img src="https://github.com/Sung-JinPark/Jin-s-investing-prediction/actions/workflows/verify.yml/badge.svg?branch=main" alt="Verify"></a>
  <a href="https://github.com/Sung-JinPark/Jin-s-investing-prediction/actions/workflows/pages.yml"><img src="https://github.com/Sung-JinPark/Jin-s-investing-prediction/actions/workflows/pages.yml/badge.svg?branch=main" alt="Pages"></a>
  <img src="https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/research-only-FF6B35" alt="Research only">
</p>

# Jin's Investing Prediction

**최신 시장 지표와 이벤트, 구조 경로와 실제 기록, PIT 시계열 예측, 변동성 기준율, 닷컴 대비 과열도를 연결하는 투자 리서치 솔루션입니다.**

문서 기준: **2026-10-12** · 최신 `main`에 반영된 기능과 데이터 계약 기준

<p align="center">
  <a href="https://sung-jinpark.github.io/Jin-s-investing-prediction/#today"><strong>오늘</strong></a> ·
  <a href="https://sung-jinpark.github.io/Jin-s-investing-prediction/#future"><strong>미래 탐색</strong></a> ·
  <a href="https://sung-jinpark.github.io/Jin-s-investing-prediction/#statistics"><strong>통계 비교</strong></a> ·
  <a href="https://sung-jinpark.github.io/Jin-s-investing-prediction/#timeseries"><strong>시계열 예측</strong></a> ·
  <a href="https://sung-jinpark.github.io/Jin-s-investing-prediction/#records/data"><strong>기록</strong></a>
</p>

## 무엇을 보여주나요?

| 현재 시장 | 미래 전망 | 시계열 예측 | 변동성 기준율 | 닷컴 비교 | 검증 기록 |
|---|---|---|---|---|---|
| NASDAQ·VIX·공포탐욕·이벤트 실제/예상/이전 | 세 가지 시장 경로·단일 시나리오·기록 대비 실제 | 마지막 마감 세션 기준 1·5·21·63거래일 | VIX·실현변동성 5·21·63영업일 | 과열도·유동성·금리·신용·기업가치·IPO | 원천·시점·수정 이력·검증 성적 |

오늘 화면의 주요 숫자 카드는 해당 상세 화면으로 이어집니다. 경제지표·실적 일정에는 **실제·예상·이전 값**을 표시하고, CPI처럼 여러 지표가 있는 이벤트는 전월·전년·근원 지표를 함께 보여줍니다. 같은 주·같은 분류의 기업 실적은 한 카드로 묶어 표시합니다.

미래 전망은 연구 후보이며 공식 확률이나 매매 신호가 아닙니다. 세 경로는 현재 기준점만 공유하고 서로 다른 역사 군집·특징·국면 전환 규칙을 사용합니다.

단일 시나리오와 기록 대비 실제 그래프는 과거 조정의 굴곡을 반영한 **주간 구조 경로를 우선 표시**합니다. 일별 중앙값은 구조 경로가 없는 기록의 대체 표시이며, 과거에 남긴 전망과 이후 실제 가격을 대조합니다. 구조 경로는 특정 하락일이나 저점 거래일을 예측하지 않습니다. V5.2의 조정 관측 창과 연말·연구 지평은 기준일에 맞춰 순차적으로 이동하며, 화면의 기간은 해당 전망의 메타데이터를 따릅니다.

시계열 예측은 별도 shadow 연구모델입니다. **V8**은 PIT 다변량 회귀와 분포 보정으로 NASDAQ의 1·5·21·63거래일 분위수·상승확률을 산출하며, 봉인 Gate 통과 모델의 전진 예측·만기 결과를 누적합니다. Research Gate와 운영 신선도 Gate를 모두 통과할 때만 참고 의견으로 표시하며 기존 미래전망·공식 확률과 결합하지 않습니다. 2019년 이후 평가창은 완전한 미열람 표본이 아니므로 별도 전진 검증을 계속합니다. 이전 V5의 **HOLD** 판정도 보존합니다. [V8 계약](data/contracts/multivariate_timeseries_v8.yaml) · [V5 봉인 결과](docs/timeseries_v5/GATE_RESULT_20260824.md)

**V8 일일 표시**는 동결 모델을 사용해 마지막 마감 미국 세션 기준의 전망을 별도 원장에 기록합니다. 아카이브 미확정 입력을 원 발표처 자료로 보완한 경우에는 **잠정**으로 표시하고, 확정 시 기존 행을 보존한 새 revision을 추가합니다. 해소·채점·라이브 전진 검증은 **주간 shadow 원장**만 사용합니다. 검증 화면의 100점 환산 성적과 오차 그래프는 공개 검증 지표를 읽기 쉽게 표시한 것이며, 모델 확률을 바꾸지 않습니다. [일일 표시 정책](data/contracts/multivariate_timeseries_v8.yaml) · [성적 표시 기준](docs/design/timeseries_score100_261006.md)

**V13-VOL**은 동결된 지속성 모델로 VIX·실현변동성 이벤트의 기준율을 제공합니다. 홀드아웃은 9셀 중 3셀(VIX 25 이상·21영업일, 실현변동성·5/21영업일)만 통과했으며 나머지 6셀의 숫자는 표시하지 않습니다. 통과 셀도 신선도·계수 무결성·라이브 검증 상태에 따라 보류할 수 있습니다. AI 질문 예측과 정의·지평·출처를 구분하며 자동 합산하거나 매매 신호로 사용하지 않습니다. [V13-VOL 계약·셀별 표시 정책](data/contracts/multivariate_timeseries_v13_vol.yaml)

**닷컴 대비 과열도 v4**는 통계페이지의 같은 자료에서 매일 다시 계산해 메인 카드와 통계 상단에 함께 표시합니다. 100%는 닷컴 비교 구간의 극단 수준이며, 확률이 아닙니다. 부문별 중앙값을 다시 중앙값으로 집계하고 100% 초과도 그대로 표시합니다. 입력 14종 중 9종이 분기·연간 계열이라 대표값은 발표 사이에 그대로일 수 있고, 지표마다 자료 기준월을 함께 표시합니다. IPO 부문은 최근 12개월 운영기업 IPO 건수에 출처가 확인된 시대 핵심 ADR 상장과 해외 대형 IPO(상장지 불문, 총공모 임계 이상)를 가산하며 SPAC은 제외하고, 상장 대기 기업(DeepSeek 등)은 표시만 합니다. [과열도 v4 계약](data/contracts/dotcom_overheat_index_v4.yaml)

**상·하방 추세선**은 미래탐색의 마지막 카테고리에서 7개 자산의 확정 일봉과 지지·저항 경계를 표시합니다. 선형·로그축을 따로 검수하며 선의 미래 연장은 가격 예측이 아닙니다. 원본·정정·이탈 기록은 별도 append-only 원장에 보존합니다. 현재 승인된 무료 OHLC 정본이 없어 7개 모두 미산출이며, 종가나 다른 상품으로 대체하지 않습니다. [추세선 계약](data/contracts/trendlines_v1.yaml) · [구현·원천·운영 안내](docs/design/trendlines_implementation_261013.md)

## 숫자가 화면에 도착하는 과정

```mermaid
flowchart LR
    A["FRED · Fed · BLS · BEA · SEC"] --> B["원문 + SHA 영수증"]
    B --> C["Append-only 관측 DB"]
    C --> D["Excel 감사본"]
    C --> E["통계 장표"]
    C --> F["연구 전망 입력 게이트"]
    C --> T["V8 PIT 다변량 회귀 + 분포 보정"]
    C --> V["V13-VOL 변동성 지속성 기준율"]
    E --> H["닷컴 과열도 v3"]
    E --> G["GitHub Pages"]
    H --> G
    F --> G
    T --> G
    V --> G
    R["학술 · 리서치"] -. "별도 참고 통계" .-> E
    M["고용 컨센서스 · 시장 금리확률"] -. "출처·available_at 기록" .-> F
```

- 자동 갱신 통계는 등록된 공식·1차 원천과 원문 영수증으로 계산합니다.
- 공식 대체 DB가 없는 학술·리서치 수치는 **참고 통계**로 분리하며 공식 통계 원장에 섞지 않습니다.
- 고용 컨센서스와 시장 금리확률은 출처와 `available_at`을 남긴 연구 후보 입력으로 사용할 수 있지만, 공식 확률이나 챔피언 승격을 뜻하지 않습니다.
- 수정치는 기존 행을 바꾸지 않고 `revision + supersedes`로 추가합니다.
- 과거 전망 입력은 `available_at ≤ as_of`를 만족해야 합니다.
- 확률은 `[0, 1]` 분수로 저장하고 화면·보고서에서만 퍼센트로 변환합니다.
- 검증 화면은 행 평균과 문항 등가중 점수를 병기하며, P3 게이트 미결 상태를 통과로 표시하지 않습니다.
- Excel은 사람이 보는 감사본이며 정본은 append-only 관측 원장입니다.

## 갱신 주기

| 화면·자료 | 갱신 방식 |
|---|---|
| NASDAQ·VIX·공포탐욕 | 마지막 마감 미국 세션 기준으로 갱신하며 KST 오전 8시 최신성을 목표로 합니다. 원천 게시·실행이 늦으면 화면에 지연 상태를 표시합니다. |
| 통계·닷컴 과열도·Excel 감사본 | 매일 **15:20 KST** 수집 예약 → 원장 추가 → 같은 스냅샷으로 재계산 → Pages 자동 배포 |
| V8 일일 시계열 표시 | 시장 지표·PIT 아카이브 갱신 완료에 연동하고 별도 예약 실행으로 보완합니다. 일일 표시와 주간 검증 표본은 분리합니다. |
| V13-VOL 기준율 | PIT 아카이브 갱신과 별도 예약에 연동하며 동결 계수로 산출하고 만기 결과를 누적합니다. |
| 경제지표·실적 컨센서스 | 시장 지표 갱신 시 함께 확인하고 값이 바뀌면 출처와 함께 이벤트 원장에 추가합니다. |

매일 확인해도 새 발표가 없는 월·분기 자료는 값이 유지됩니다. 수집·생성 시각과 실제 관측일을 구분하고, 역사·학술 참고 자료는 등록된 출판 빈티지와 검토 절차를 보존합니다. 예약 시각은 실행·배포 완료를 보장하는 시각이 아닙니다.

## 현재 통계 구성

- **유동성** — M2, MMF, 가계 현금성 자산, S&P 500, NASDAQ, Bitcoin
- **금리·신용** — 장단기 금리차, 정책금리, 회사채 부담, 대출기준, 가계부채
- **경기·물가** — 실업률, CPI, WTI, 구리, Census 주택착공, 제조업 확산
- **기업가치** — 기업주식 가치, 세후이익, 기업이익 증가율
- **자본시장** — SEC 공식 IPO 구성 + 운영기업·시대 핵심 ADR의 최근 12개월 IPO 건수 + 기술 IPO 첫날 수익률·P/S·흑자/적자 비중·AI 핵심 IPO 비교
- **한국·반도체** — OECD 한국 주가지수와 Nasdaq SOX 공식 배포 계열

현재선은 마지막 실제 관측에서 멈추며 미래 값을 임의로 이어 붙이지 않습니다.

## 데이터 계약

| 계약 | 위치 |
|---|---|
| 닷컴 대비 과열도 v4 | [`dotcom_overheat_index_v4.yaml`](data/contracts/dotcom_overheat_index_v4.yaml) |
| 아침 시장 지표 최신성 | [`morning_freshness_v1.yaml`](data/contracts/morning_freshness_v1.yaml) |
| 이벤트 실제·예상·이전 값 원장 | [`event_consensus.jsonl`](data/calendar/event_consensus.jsonl) |
| 공식 숫자 원천 허용목록 | [`authoritative_statistics_sources.yaml`](data/contracts/authoritative_statistics_sources.yaml) |
| 웹 장표·전망 계보 | [`website_data_lineage_v1.yaml`](data/contracts/website_data_lineage_v1.yaml) |
| 누적 관측 DB | [`normalized_observations.jsonl`](data/statistics/official_store/ledgers/normalized_observations.jsonl) |
| 원문·수집 영수증 | [`raw/`](data/statistics/official_store/raw/) · [`raw_receipts.jsonl`](data/statistics/official_store/ledgers/raw_receipts.jsonl) |
| 영수증 정정 이력 | [`raw_receipt_corrections.jsonl`](data/statistics/official_store/ledgers/raw_receipt_corrections.jsonl) |
| 시계열 V1 / V2 사전등록 | [`multivariate_timeseries_v1.yaml`](data/contracts/multivariate_timeseries_v1.yaml) · [`multivariate_timeseries_v2.yaml`](data/contracts/multivariate_timeseries_v2.yaml) |
| 시계열 PIT / V2 원장 | [`data/timeseries/`](data/timeseries/) · [`data/timeseries_v2/`](data/timeseries_v2/) |
| 시계열 V4 원천·Gate | [`multivariate_timeseries_v4.yaml`](data/contracts/multivariate_timeseries_v4.yaml) · [`data/timeseries_v4/`](data/timeseries_v4/) |
| 시계열 V5 직접분포·공개 DB | [`multivariate_timeseries_v5.yaml`](data/contracts/multivariate_timeseries_v5.yaml) · [`V5 아키텍처`](docs/timeseries_v5/ARCHITECTURE.md) · [`데이터 카탈로그`](docs/timeseries_v5/DATA_CATALOG.md) |
| 시계열 V8 계약·shadow 원장 | [`multivariate_timeseries_v8.yaml`](data/contracts/multivariate_timeseries_v8.yaml) · [`data/timeseries_v8/`](data/timeseries_v8/) |
| V13-VOL 계약·동결 계수·라이브 원장 | [`multivariate_timeseries_v13_vol.yaml`](data/contracts/multivariate_timeseries_v13_vol.yaml) · [`data/timeseries_v13/`](data/timeseries_v13/) |
| P3 게이트·검증 기준과 실행 기록 | [`P3 문서 인덱스`](docs/p3_gate_path/00_README_INDEX.md) · [`실행 결과`](docs/p3_gate_path/00_EXECUTION_REPORT.md) |

---

<p align="center">
  <strong>Evidence first. Scenario aware. Auditable by design.</strong><br>
  정보 제공 목적의 투자 리서치 시스템이며 자동매매·주문 실행·수익 보장 서비스가 아닙니다.
</p>
