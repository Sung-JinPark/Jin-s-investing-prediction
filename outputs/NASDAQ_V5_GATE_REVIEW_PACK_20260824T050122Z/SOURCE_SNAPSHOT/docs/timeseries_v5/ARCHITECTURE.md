# NASDAQ V5 직접분포 연구모델

`shadow.nasdaq_pit_hybrid_distribution_v5`는 기존 미래전망과 분리된 연구용 시계열 모델이다. 공식 확률, Scenario V5.2, V1~V4 산출물을 읽을 수는 있지만 수정하거나 결합하지 않는다.

## 데이터 흐름

```text
공개 원천
  ├─ Core: Nasdaq/FRED, Cboe, Treasury, Fed/NY Fed, CFTC, FINRA
  └─ Challenger: OFR, CMDI, EBP, SEC, EIA, SPF, 학술자료
       ↓
content-addressed gzip 원문 (R2/private)
       ↓ SHA + 수집 영수증
append-only 관측 버전 (Neon/PostgreSQL)
       ↓ available_at ≤ origin_cutoff_at
PIT feature snapshot + 1/5/21/63일 직접 label
       ↓ nested rolling-origin, 63일 purge, 5일 embargo
location · scale · tail 분포 + 고정 anchor floor
       ↓
Research Gate + Operational Gate
  ├─ PASS: #timeseries 연구 숫자 표시
  └─ HOLD: 숫자 숨김, 실패 이유만 보존
```

## 원천 등급

- `native_pit`: 당시 공개시각과 빈티지가 증명된 관측.
- `captured_forward`: 도입 이후 실제 수집한 스냅숏.
- `reconstructed_market_archive`: 공식 시장 과거자료를 재구성한 연구 아카이브.
- `reconstructed_official_archive`: 공식기관이 현재 제공하는 재구성 과거자료. 과거 빈티지로 위장하지 않고 Challenger로만 사용한다.

Cboe·FINRA·컨센서스처럼 공개 접근과 재배포 권한이 다른 원문은 Git이나 사이트에 넣지 않는다. 공개 영역에는 영수증, SHA, 집계 파생치만 남긴다.

## 모델과 평가

- 대상: NASDAQ Composite 누적 로그수익률.
- 기간: 1·5·21·63 XNAS 거래일을 horizon별로 직접 학습한다.
- 후보: 고정 anchor, elastic-net, Student-t location/scale, 비선형 basis, 동적 선형, ex-ante regime, tail expert. 최대 12개 bundle을 outer 평가 전에 동결한다.
- 평가: V4와 동일한 963개 주간 원점의 `research_pseudo_oos`.
- 비교군: V3 fixed-anchor ensemble.
- 공개: 21·63일 평균 CRPS 2% 개선, 개별 개선, dependent-bootstrap CI, 방향·Q4·위기·coverage Gate를 모두 통과해야 한다.

Gate 기준은 성능에 맞춰 낮추지 않는다. 실패 실험도 append-only로 남긴다.

## 운영

- 거래일: 수집 → materialize → forecast → resolve.
- 주간: 계보 검사와 가벼운 재적합.
- 월간: 전체 nested backtest와 감사 Excel.
- object-store 사용량 80%: 신규 대용량 수집 HOLD. 기존 원문 삭제 금지.
- provider secret: collector job에만 전달. 모델·Codex worker에는 전달하지 않는다.

## 인터페이스

```text
python -m ai_fc timeseries-v5-collect
python -m ai_fc timeseries-v5-materialize
python -m ai_fc timeseries-v5-mature-labels
python -m ai_fc timeseries-v5-train
python -m ai_fc timeseries-v5-backtest
python -m ai_fc timeseries-v5-gate
python -m ai_fc timeseries-v5-forecast
python -m ai_fc timeseries-v5-resolve
python -m ai_fc timeseries-v5-verify
python -m ai_fc timeseries-v5-workbook
```

Atlas는 `tools/atlas_timeseries.py`의 `init/plan/run/worker/resume/status/pause/abort/reconcile/report`로 중단 가능한 실행을 제공한다.
