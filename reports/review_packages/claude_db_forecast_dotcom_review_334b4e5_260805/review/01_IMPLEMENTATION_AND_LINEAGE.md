# 구현 및 데이터 계보 지도

## 1. 변경 구조

```text
역사 DB / 기존 스냅샷
├─ data/ml_history/*.jsonl
│  ├─ 선택 혁신시대 위상
│  └─ 다중시대 조정 깊이 중앙값
│        ↓
│  scenario_structure.py
│        ↓ additive only
│  scenario.schema v3 / structural_forecast
│        ↓
│  미래 분포 차트의 연도별 굵은 구조선
│  (기존 quantile fan·S1/S2/S3 비중은 유지)
│
├─ Yahoo ^IXIC 월간 실측 2001-03..2006-03
├─ Yahoo O 월간 종가·수정종가 실측
└─ cross-asset r5의 현대 BTC beta 감사값
         ↓
   cross_asset.py schema v4
         ↓
   NASDAQ/O 실측 + BTC 네 반사실 민감도
         ↓
   자산 전이 탭 (reference_only)
```

## 2. NASDAQ 구조 경로 파일 책임

| 파일 | 책임 |
|---|---|
| `data/contracts/scenario_structural_forecast.yaml` | DB 입력·캘리브레이션·금지 규칙 사전 등록 |
| `src/ai_fc/scenario_structure.py` | 위상 정렬, cross-era median, 연도별 detrend, 강도 이분 탐색, 진단 |
| `src/ai_fc/scenario.py` | schema v3 직렬화·검증·legacy v2 호환·additive migration |
| `data/scenarios/archive/2026-08-03_CORR-260805-014.json` | 불변 r4 산출물 |
| `data/scenarios/nasdaq_latest.json` | 공개 최신 snapshot |
| `dashboard.js/css` | 구조선·연도 분할·근거/위험창 표시 |
| `test_scenario.py`, `test_dashboard_js_geometry.py` | 결정성·legacy·차트 경로 선택 회귀 |

### 보존해야 하는 기존 값

- 20,000 GBM 경로와 seed 42
- quantile table과 p10–p90 fan
- S1/S2/S3 조건부 비중
- 기존 year-segment 시작·종점
- `physical_event` 확률의 별도 공간

구조 경로는 위 값들을 재추정하지 않고 표시용 굵은 경로만 추가한다.

## 3. 교차자산 파일 책임

| 파일 | 책임 |
|---|---|
| `data/contracts/cross_asset_dotcom_counterfactual.yaml` | 2001-03 anchor·관측자산·BTC 산식·가드레일 |
| `src/ai_fc/cross_asset.py` | schema v4, 실측 window, beta cases, legacy 2/3 검증, migration |
| `data/cross_asset/archive/2026-08-03_CORR-260805-015.json` | 불변 r6 산출물 |
| `data/cross_asset/cross_asset_latest.json` | 공개 최신 snapshot |
| `read_model_contract.py` | legacy `scenario_conditional`와 v4 `reference_only` 허용 |
| `dashboard.js` | 실측·반사실 4선 차트, case switch, 고정 고지 |
| `test_cross_asset.py` | 61개월·산식·자산 동일성·확률 부재·불변 archive 회귀 |

### r6 계보

```text
cross-asset:2026-08-03:r5
  ├─ beta_audit 고정
  ├─ Realty Income sensitivity 감사 문맥 고정
  └─ current diagnostics 고정
            +
Yahoo monthly ^IXIC / O 2001-03..2006-03 재취득
            ↓
CORR-260805-015
            ↓
cross-asset:2026-08-03:r6 (schema 4, reference_only)
```

현재 O 금리·신용 민감도는 `used_numerically=false`다. O 그래프를 만드는 입력은 실측
월간 가격·수정종가뿐이다.

## 4. UI 의미론

### 미래 분포 탭

- 구조선: 역사 DB 조건부 표시 경로
- 팬: 기존 GBM 조건부 분포
- 등록 질문 확률: 별도 physical-event 박스
- 연도: 2026과 2027을 따로 탐색
- 2027 지평: 2027-08-04까지만, 9~12월 생성 금지

### 자산 전이 탭

- `NASDAQ`, `O 가격`, `O 총수익 proxy`: 실선/관측 계열
- `Bitcoin 반사실`: 파란 점선/합성 계열
- case 버튼은 Bitcoin beta만 바꾼다.
- `실측 + BTC 반사실`과 `NASDAQ·O 실측만` 보기 분리
- 구형 `AI 조정 후 완화·순환` 기본 경로는 공개 UI에서 제거

## 5. 변경·배포 원장

- `calibration/corrections.csv`
  - `CORR-260805-014`: NASDAQ structural forecast
  - `CORR-260805-015`: dotcom counterfactual cross asset
- `data/method_changes.jsonl`
  - `method:dotcom-counterfactual-v1:2026-08-05`
- 생성 inventory는 후속 커밋 `334b4e5`에서 갱신했다.

