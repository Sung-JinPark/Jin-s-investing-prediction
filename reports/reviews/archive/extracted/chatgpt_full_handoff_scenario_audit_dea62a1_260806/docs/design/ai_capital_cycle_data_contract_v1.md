# AI Capital Cycle 데이터 계약 v1

작성일: 2026-08-03
상태: Graph 2 구현 전 사전등록 계약

## 1. 공통 point-in-time 필드

모든 관측값은 `observation_period`, `available_at`, `source_url`,
`source_fingerprint`, `revision_vintage`, `value_status`를 보존한다. 당시 이용할 수 없던
최종 수정치를 과거 시점에 대입하지 않는다. FRED 거시계열은 `data/contracts/alfred.yaml`의
`realtime_start`/`realtime_end` vintage를 사용하며 final-vintage 대체를 금지한다.

`value_status`는 `reported`, `reconstructed`, `partial`, `missing`, `stale`,
`collection_failed` 중 하나다. 여러 정형 공시를 합쳐 과거 값을 복원하면 값 옆과 UI에
항상 `재구성(reconstructed backfill)`을 표시한다.

## 2. Disclosure coverage

기업-분기별 coverage는 아래처럼 계산한다.

```text
eligible_weight = Σ 사전등록 metric_weight
reported_weight = Σ metric_weight where value_status == reported
partial_weight  = Σ metric_weight × disclosed_fraction where value_status == partial
disclosure_coverage = (reported_weight + partial_weight) / eligible_weight
```

화면의 전체 기업 coverage는 기본적으로 같은 분기의 대상 회사(MSFT·AMZN·GOOGL·META)를
동일가중한다. 분모는 `canonical_segment_map`에 유효한 회사 수, 분자는 각 회사 coverage의
합이다. 시가총액 가중 보조값을 만들 경우 당시 이용 가능했던 시가총액과 별도
`coverage_aggregation_version`을 저장하며 동일가중 정본을 대체하지 않는다.

- 분모는 해당 분기에 `canonical_segment_map.yaml`에서 유효한 metric만 포함한다.
- `missing`과 `reconstructed`는 분자에 넣지 않는다. 재구성 값은 분석에는 쓸 수 있지만
  공시 충실도를 높이지 않는다.
- `partial`의 `disclosed_fraction`은 `[0,1]`이며 원문 근거가 없으면 0이다.
- 결과는 `coverage_formula_version=2026-08-03.v1`, 분자, 분모, partial 기여분을 함께 저장한다.
- 회사가 AI 매출을 분리하지 않으면 cloud/segment 매출을 AI 매출로 바꾸지 않는다.

## 3. Robust-z 사전등록 상수

- 분기 기업·수익화 지표: rolling 20분기, 최소 12분기
- 일간 funding 지표: rolling 756 거래일, 최소 504 거래일
- winsor 경계: 해당 rolling 창의 2.5/97.5 백분위
- robust z: `(x - rolling_median) / (1.4826 × rolling_MAD)`
- MAD가 0이거나 최소 표본 미달이면 `insufficient_data`; 0으로 대체하지 않는다.
- 조합 점수는 이용 가능한 component 가중치로 분모를 다시 계산하고 coverage를 별도 노출한다.

상수 변경은 과거 결과를 덮어쓰지 않고 `calibration/corrections.csv` 승인 행과 새 계약
버전을 요구한다.

## 4. Circular finance 사람 승인 게이트

LLM은 filing 문단에서 후보 관계를 분류할 수 있지만 원장에 사건을 확정할 수 없다.
후보는 `circular_finance_candidates.csv`에 issuer, counterparty, instrument, amount,
currency, 원문 URL/지문을 정형 필드로 남긴다. 금액이나 상대방이 공시에 없으면 비워 두며
LLM이 추정하지 않는다.

정본 편입에는 `calibration/approvals.csv`의 아래 형태가 필요하다.

```csv
approved_at,action,from_value,to_value,scope,status,reviewer,reason,commit
YYYY-MM-DD,circular_finance_event_approve,<candidate_id>,<event_id>,circular_finance_events,approved,<human>,<filing verification>,<commit>
```

승인 전 후보는 점수·차트·학습 데이터에 들어가지 않는다. 수정이나 철회도 새 승인 및
correction 행으로 append-only 처리한다.

## 5. Graph 1 연결 사전등록

Graph 2의 사분면과 Graph 1 경로 연결은
`data/ai_capital_cycle/regime_link_rules.yaml`을 따른다. 연결은 강화/약화 설명만 허용하며,
서로 다른 확률 공간을 결합하거나 확률·목표가격으로 표시하지 않는다. 결과를 본 뒤 규칙을
바꾸려면 기존 파일을 수정하지 않고 correction과 새 version을 추가한다.
