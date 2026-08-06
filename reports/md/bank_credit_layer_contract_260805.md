# CREDIT-LIQ-260805 정밀 계약·실행 설계서

작성일: 2026-08-06 KST  
기준 커밋: `d12c069`  
대상: 은행 신용·예대율·MMF 3개 `reference_only` 레이어  
현재 단계: **P0 정찰·계약 완료 / P1 구현 미착수**

> 이 문서는 진단용 데이터 레이어의 구현 계약이다. 사건확률, 목표가, 매매 신호 또는 투자자문을 만들지 않는다. `scenario_conditional`, `physical_event`와 산술 결합하지 않는다.

## 1. 결론

첨부 설계의 데이터 의미·파생 규칙·주기 분리 원칙은 타당하다. 다만 수집 경로는 그대로 승인할 수 없다.

- `TOTCI`, `TOTLL`, `DPSACBW027SBOG`, `MMMFFAQ027S`, `WRMFNS`의 의미·주기·단위는 공식 메타데이터와 일치한다.
- `WRMFSL`은 2021-02-01 이후 중단된 주간 SA 계열이므로 사용 금지가 맞다.
- LDR은 `100 × TOTLL / DPSACBW027SBOG`로 만드는 파생값이며 두 원천을 같은 수요일 관측일로 inner join 해야 한다.
- MMF 총자산은 분기, 소매 MMF는 주간이므로 한 배열·한 격자·한 선으로 합치면 안 된다.
- **신규 자동 수집은 FRED `fredgraph.csv`가 아니라 원생산자인 Federal Reserve Board의 H.8/H.6/Z.1 공식 다운로드를 사용한다.** 현재 FRED 약관은 FRED 콘텐츠의 소프트웨어·AI 연계 사용과 저장·아카이브를 제한한다. 기존 저장소의 `fred_market_signals: approved` 표시는 별도 거버넌스 감사 대상으로 남기되, 이 신규 레이어가 그 상태를 상속하면 안 된다.
- P1~P5는 이 문서의 소스 재경로를 사용자가 승인하기 전 착수하지 않는다.

판정: **P0 PASS WITH SOURCE-REROUTE GATE**.

## 2. 기존 구현 패턴 실측

| 요구 패턴 | 실측 위치 | 판정 및 적용 |
|---|---|---|
| 동일 as-of 불변 아카이브 | `src/ai_fc/cross_asset.py:1033-1093` | 기존 바이트와 비교하고, 내용이 다르면 승인된 correction 없이는 revision을 거부한다. 신규 공통 persist helper가 이 분기를 그대로 재사용해야 한다. |
| 승인 correction 조회 | `src/ai_fc/cross_asset.py:1020-1025`, `1056-1081` | `calibration/corrections.csv`의 approved 행을 요구한다. 신규 target table은 `bank_credit_snapshots`로 고정한다. |
| content-addressed receipt | `src/ai_fc/cross_asset.py:1256-1284` | 응답 본문 없이 request receipt의 `response_sha256` 집합으로 fingerprint를 만든다. 신규 레이어도 raw CSV/XML/ZIP을 커밋하지 않는다. |
| 과거 HY 폴백 | `src/ai_fc/realty_income.py:90-153` | 첨부의 `hy_history_receipt`라는 함수명은 실제 코드에 없다. 실제 구현은 `fetch_hy_event_history`이며, 현재 원천과 commit-pinned capture를 합치고 양쪽 SHA를 receipt에 남긴다. |
| 범용 FRED fetch | `src/ai_fc/realty_income.py:56-87`, `src/ai_fc/market_extensions.py:58-91` | `quant/feed.py`에는 범용 fetch가 없고 `fred_m2()`만 있다(`src/ai_fc/quant/feed.py:252-262`). 신규 레이어가 `quant.feed`에 존재하지 않는 인터페이스를 가정하면 안 된다. |
| transport fallback | `src/ai_fc/quant/feed.py:70-90` | Python → curl → DNS 보조 순서의 텍스트 transport를 재사용할 수 있다. 단, 허용된 Board endpoint에만 사용한다. |
| 확률공간 강제 | `src/ai_fc/cross_asset.py:624-627`, `844-848` | payload 생성과 validator 양쪽에서 `reference_only`를 강제한다. |
| 수치 미개입 가드 | `src/ai_fc/cross_asset.py:574-590`, `688-690` | `used_numerically=false`를 validator가 확인한다. LDR derivation만 내부 계산에 `true`, 확률 결합은 항상 `false`다. |
| 읽기 모델 확장점 | `src/ai_fc/read_model_contract.py:32-49`, `113-122`, `205-222` | `bank_credit`, `bank_ldr`, `money_market_funds` 세 key와 validator를 additive하게 추가한다. |
| 대시보드 로더 | `src/ai_fc/dashboard.py:296-305`, `460-481` | 스냅샷 loader를 호출하고 read model에 넣은 뒤 `assert_valid`를 통과시킨다. |
| 유동성 탭 확장점 | `src/ai_fc/dashboard_parts/dashboard.js:1214-1219`, `1294-1365`, `1549-1588` | 별도 최상위 메뉴를 늘리기보다 기존 `04 유동성` 안에 `은행 신용·유동성` 하위 공간을 추가한다. |

### P0에서 바로잡은 두 가지 명명 오류

1. `hy_history_receipt`는 실재 함수가 아니다. `realty_income.fetch_hy_event_history()`가 정본이다.
2. `quant.feed`에는 임의 FRED ID를 받는 공개 함수가 없다. 신규 provider를 설계하지 않고 `quant.feed.<generic_fred>`를 호출하면 런타임 오류가 난다.

## 3. 공식 시리즈·원생산자 매핑

FRED ID는 사용자와 UI가 아는 의미 식별자로 유지하되, 자동 수집은 Board native code를 사용한다.

| 공개 의미 ID | 공식 정의 | Board native code / 원천 | 관측 주기·단위 | 구현 상태 |
|---|---|---|---|---|
| `TOTCI` | Commercial and Industrial Loans, All Commercial Banks | `H8/H8/B1023NCBA` | Weekly, Ending Wednesday · $B · SA | 사용 |
| `TOTLL` | Loans and Leases in Bank Credit, All Commercial Banks | `H8/H8/B1020NCBA` | Weekly, Ending Wednesday · $B · SA | 사용 |
| `DPSACBW027SBOG` | Deposits, All Commercial Banks | `H8/H8/B1058NCBA` | Weekly, Ending Wednesday · $B · SA | 사용 |
| `MMMFFAQ027S` | Money Market Funds; Total Financial Assets, Level | `FL634090005`, Z.1 `S123.s` line 1 | Quarterly, EOP · Board table $B, FRED 표현 $MM · NSA | Board 값을 $B로 보존 |
| `WRMFNS` | Retail Money Market Funds | `H6/H6_M2/MMFGB_N.WM` | Weekly, Ending Monday · $B · NSA | 사용 |
| `WRMFSL` | Retail Money Market Funds, SA | `H6/H6_M2/MMFGB.WM` | Weekly, Ending Monday · $B · SA · 2021-02-01 중단 | 사용 금지 |
| 기관 MMF | H.6 institutional MMF | `H6/H6_MEMO/MMFIN_N.WM` | Weekly · NSA · 2021-02-01 중단 | 현재계열 아님, D-1에서 제외 권고 |

공식 근거:

- H.8 설명·발표 주기: https://www.federalreserve.gov/releases/H8/about.htm
- H.8 DDP와 native code: https://www.federalreserve.gov/datadownload/choose.aspx?rel=h8
- H.6 설명·주간 NSA 범위: https://www.federalreserve.gov/releases/h6/about.htm
- H.6 native series 목록: https://www.federalreserve.gov/datadownload/Choose.aspx?rel=h6
- Z.1 current release·CSV: https://www.federalreserve.gov/releases/z1/current/
- Z.1 MMF table: https://www.federalreserve.gov/releases/z1/current/html/S123_s.htm
- Board 재사용 고지: https://www.federalreserve.gov/disclaimer.htm
- FRED 이용약관: https://fred.stlouisfed.org/legal/terms/

## 4. 소스 거버넌스 수정안

### 4.1 FRED direct collector를 차단하는 이유

현재 FRED 약관은 다음을 제한한다.

- FRED 서비스/콘텐츠를 소프트웨어 또는 AI 시스템과 연계해 사용하는 행위
- FRED 콘텐츠의 저장, 캐시, 아카이브 또는 데이터베이스 편입
- 스크립트·봇·스크레이퍼를 이용한 데이터 수집

따라서 `fredgraph.csv`에서 시계열을 받아 JSON archive와 공개 대시보드에 적층하는 첨부안은 새 레이어의 활성 계약으로 승인할 수 없다. FRED 페이지는 P0 메타데이터 대조와 사람이 보는 citation에만 사용하고, 수집기는 Board 원천으로 전환한다.

### 4.2 승인 가능한 source chain

```text
Federal Reserve Board H.8 DDP/XML ─┐
Federal Reserve Board H.6 DDP/XML ─┼─> receipt(SHA256 only) ─> normalized observations
Federal Reserve Board Z.1 CSV ZIP ─┘                                  │
                                                                     ├─> credit
                                                                     ├─> ldr
                                                                     └─> mmf
```

Board 웹사이트의 Board-produced 정보는 별도 표시가 없는 한 public domain이며 Board citation을 요구한다. 사진·그래픽·제3자 자료는 제외한다. 신규 contract는 이를 `public_domain_with_attribution`으로 기록한다.

### 4.3 endpoint 수명 리스크

Board는 2026년 11월 둘째 주에 DDP Build Your Package 기능을 제거할 예정이라고 공지했다. 따라서 endpoint를 한 URL로 영구 고정하면 안 된다.

- 단기 primary: Board preformatted DDP package
- 중기 primary: release page의 Board XML/SDMX 또는 Z.1 current CSV ZIP
- fallback: 이전 활성 snapshot을 `stale`로 유지
- 금지: FRED로 자동 전환, 임의 값, 선형 보간, commit-pinned FRED raw capture
- 운영 게이트: 2026-11 전환 전 Board XML parser를 fixture로 검증

## 5. 파일·모듈 설계

### 5.1 신규 파일

| 파일 | 역할 |
|---|---|
| `data/contracts/fed_board_bank_credit.yaml` | H.8/H.6/Z.1 source, native code, 권리, PIT, fallback 계약 |
| `src/ai_fc/bank_credit.py` | fetch 결과 정규화, credit/LDR/MMF builder, validator, persist, loader |
| `src/tests/test_bank_credit.py` | 계산·권리·불변성·결측·주기 테스트 |
| `data/bank_credit/credit_latest.json` | C&I·총대출 스냅샷 |
| `data/bank_credit/ldr_latest.json` | 총대출/예금 파생 스냅샷 |
| `data/bank_credit/mmf_latest.json` | 주간 소매·분기 총자산 분리 스냅샷 |
| `data/bank_credit/archive/<layer>_<asof>.json` | 불변 r1 아카이브 |
| `data/bank_credit/receipts/<asof>_<fingerprint>.json` | raw 없는 content-addressed receipt bundle |

### 5.2 수정 파일

| 파일 | 변경 |
|---|---|
| `src/ai_fc/read_model_contract.py` | 3개 key·validator·금지 필드 검사 추가 |
| `src/ai_fc/dashboard.py` | 세 loader와 public projection 추가 |
| `src/ai_fc/dashboard_parts/dashboard.js` | 유동성 탭 내부 3개 패널, 접근성·주기 라벨·공식 표시 |
| `src/ai_fc/dashboard_parts/dashboard.css` | 기존 light/mistral tone 안에서 패널·범례·반응형 스타일 |
| `src/ai_fc/cli.py` | 승인 후 `bank-credit` refresh/check 명령 추가 |
| `data/source_registry.yaml` | source contract 활성화가 승인된 Phase에서만 등록 |
| `data/contracts/ledger_registry.yaml` | 세 latest/archive/receipt 원장을 append-only로 등록 |
| `data/method_changes.jsonl` | 구현 완료 시 method event 1건만 append |
| `docs/generated/read_model_v2.schema.json` | inventory 명령으로 재생성 |
| `docs/generated/inventory.generated.md` | inventory 명령으로 재생성 |

### 5.3 구현 경계

- HTTP transport만 `quant.feed.get_with_curl_fallback`을 재사용한다.
- 파서·series mapping·권리 메타는 `bank_credit.py` 내부 또는 contract-driven helper로 둔다.
- `realty_income.fetch_fred_series`를 import하지 않는다. Realty Income 도메인에 은행 레이어를 결합하는 역의존을 만들지 않는다.
- H.8의 TOTCI/TOTLL/Deposits는 한 Board package를 1회 가져와 세 series로 분기한다. TOTLL을 P1과 P2에서 두 번 fetch하지 않는다.
- 세 payload는 같은 `run_id`와 H.8 receipt fingerprint를 공유한다.

## 6. 스냅샷 계약 v1.1

첨부 스키마에 PIT·주기 혼재·권리 메타를 additive하게 보강한다.

```jsonc
{
  "schema_version": 1,
  "layer": "credit | ldr | mmf",
  "status": "ok | partial | stale | blocked",
  "asof": "latest observation date represented by this layer",
  "generated_at": "ISO-8601 UTC",
  "run_id": "bank-credit:<generated date>:<source fingerprint prefix>",
  "probability_space": "reference_only",
  "combined_with_probability": false,
  "source_vintage": "captured_current",
  "historical_use": "current_vintage_descriptive_not_native_pit",
  "anchors": {},
  "series": {},
  "diagnostics": {},
  "receipts": [],
  "sources": [],
  "limitations": [],
  "snapshot_id": "<layer>:<asof>:r1",
  "revision": 1
}
```

### 6.1 날짜 의미

- `asof`: 해당 레이어에 포함된 가장 최근 관측기간. build 날짜가 아니다.
- `generated_at`: 이 저장소가 payload를 생성한 시각.
- 각 series는 `observation_asof`, `available_at`, `frequency`, `unit`, `seasonal_adjustment`를 별도로 가진다.
- H.8 관측 수요일과 공개 금요일을 구분한다. `available_at`은 실제 Board release 시각이고 수요일로 backdate하지 않는다.
- MMF top-level `asof`는 최신 주간 소매 관측일로 둘 수 있으나, 분기 총자산의 `observation_asof`를 별도로 화면에 고정 표기한다.

### 6.2 금지 필드

validator는 payload 전체를 재귀적으로 검사해 아래 key를 거부한다.

`target_price`, `expected_return`, `event_probability`, `probability`, `score`, `weights`, `signal`, `buy`, `sell`, `recommendation`

허용되는 `probability_space` 값은 오직 `reference_only`다.

## 7. 계산 계약

### 7.1 Credit

- 원천: TOTCI, TOTLL 주간 level.
- YoY: 관측일 `t`와 정확히 364일 전의 동일 요일 관측을 date-key로 join한다. 전년도 관측이 없으면 `null`; 단순 배열 `[-52]`로 당기지 않는다.
- 26주 방향: 최신값과 182일 전 exact-week 값을 비교한다. 결측이면 방향도 `null`.
- `z_since_2000`: 2000-01-01 이후 current-vintage level의 전체 표본 z-score. `n`, `mean`, `std_ddof=1`, `basis=current_vintage_descriptive`를 함께 기록한다.
- “과열·긴축·완화” 같은 판정은 만들지 않는다.

### 7.2 LDR

```text
aggregate_ldr_pct(t) = 100 × TOTLL(t) / DPSACBW027SBOG(t)
```

- 양 series를 exact date inner join한다.
- 0 또는 음수 분모는 해당 주 `null` + `invalid_denominator`.
- 원천 두 배열과 계산 배열을 모두 보존하되 같은 labels를 공유한다.
- 명칭은 `aggregate loan-to-deposit proxy`로 고정한다. 개별은행 규제 LDR이나 건전성 임계값으로 부르지 않는다.
- `derivation.used_numerically=true`는 LDR 자체 계산에만 적용한다.
- `derivation.combined_with_probability=false`와 top-level `combined_with_probability=false`를 모두 강제한다.

### 7.3 MMF

```jsonc
"series": {
  "weekly_retail": {
    "public_id": "WRMFNS",
    "native_code": "H6/H6_M2/MMFGB_N.WM",
    "frequency": "weekly_ending_monday",
    "unit": "billions_usd",
    "labels": [], "values": [], "yoy_pct": []
  },
  "quarterly_total": {
    "public_id": "MMMFFAQ027S",
    "native_code": "FL634090005",
    "frequency": "quarterly_end_of_period",
    "unit": "billions_usd",
    "labels": [], "values": [], "yoy_pct": []
  }
}
```

- Board Z.1의 $B 값을 정본으로 저장한다. FRED의 $MM 표현과 교차 대조할 때만 1,000 배 scale을 확인한다.
- weekly는 364일 전 exact date, quarterly는 동일 quarter 1년 전과 비교한다.
- 분기 series를 주간 labels로 forward-fill/보간하지 않는다.
- 서로 다른 두 series를 한 z-score나 합계로 결합하지 않는다.
- 2026-07-28 H.6의 IRA/Keogh netting 방법 변경은 `methodology_breaks`에 기록한다. 새 current release가 전 이력을 재작성할 수 있으므로 과거 current-vintage를 native PIT로 표시하지 않는다.

## 8. 영속성·정정·receipt

### 8.1 불변 비교

비교용 payload에서는 `generated_at`, `run_id`, receipt의 fetch 시각만 제거하고 데이터·계약·진단은 모두 비교한다.

1. 같은 asof·같은 비교 payload: 기존 archive byte를 latest에 재사용.
2. 같은 asof·다른 payload·approved correction 없음: 실패.
3. approved correction 있음: `r+1`, `correction_id`, `supersedes`를 갖는 새 파일 append.
4. 기존 archive overwrite: 항상 실패.

### 8.2 correction key

- `target_table=bank_credit_snapshots`
- `target_key=<layer>:<asof>`
- 한 correction으로 세 레이어를 동시에 바꾸지 않는다. 영향받은 layer별 행을 등록한다.

### 8.3 receipt 최소 필드

`source`, `release`, `native_series_codes`, `request_url`, `response_sha256`, `fetched_at`, `available_at`, `revision_vintage`, `coverage_start`, `coverage_end`, `content_type`, `parser_version`

금지: response body, CSV row, ZIP binary, base64, HTML snippet.

## 9. 읽기 모델·UI 설계

### 9.1 payload 예산

현재 정적 `data.json`은 약 308,921 bytes이며 기존 320KB 게이트까지 여유가 약 11KB뿐이다. 세 전체 이력을 그대로 넣으면 게이트를 넘는다.

공개 projection은 다음으로 제한한다.

- credit/LDR: 최근 156주 labels 1개를 공유하고 4개 numeric arrays만 포함
- MMF weekly: 최근 156주
- MMF quarterly: 최근 40분기
- 2000년 이후 전체 이력은 z·백분위·n 등 집계 진단만 공개
- raw observations와 receipts 원장은 `data.json`에 넣지 않고 receipt summary만 넣음

P4 직전 두 안의 실제 bytes를 측정한다.

- A안: compact projection을 `data.json`에 포함하고 320KB 이하 유지
- B안: 초과하면 `bank_credit.json`을 별도 정적 payload로 생성해 탭 최초 활성화 때 lazy fetch. 별도 파일도 40KB 상한과 schema test를 둔다.

### 9.2 정보 구조

기존 `04 유동성` 탭 안에서 두 개의 subview를 제공한다.

1. `시장 유동성`: 기존 Tide Map 유지
2. `은행 신용`: 신규 3개 패널

신규 top-level 탭을 만들지 않는 이유는 정보 구조 팽창과 모바일 탭 과밀을 피하기 위해서다.

### 9.3 패널

- 신용: TOTCI/TOTLL level 토글, YoY 토글, 최신 관측일·공개시각·26주 사실 방향.
- 예대율: aggregate LDR 한 선, TOTLL/Deposits 보조선 토글, 계산식 고정 표시.
- MMF: 주간 소매와 분기 총자산을 동일 y축 선 두 개로 연결하지 않는다. 상하 소형 차트 또는 분리 lane으로 표시한다.
- 공통 배지: `REFERENCE ONLY · 확률/목표가/매매신호 아님`.
- 공통 고지: `현재 빈티지의 기술 통계이며 당시 이용 가능했던 PIT 백테스트가 아닙니다.`
- 금지 문구: 과열, 적정, 위험, 버블, 매수, 매도, 목표가, 상승확률.
- 접근성: tab/tabpanel ARIA, 키보드 토글, chart summary table, `aria-live=polite`, 390px 가로 스크롤 위치 표시.

## 10. 단계별 실행 순서와 게이트

| 단계 | 작업 | 완료 게이트 | 현재 상태 |
|---|---|---|---|
| P0 | 코드 패턴·시리즈·권리·endpoint 정찰, 본 계약 작성 | 5개 시리즈와 WRMFSL 실측, source route 결정 | **완료, source-reroute 승인 대기** |
| P0.5 | Board source contract + DDP/XML fixture + D0 transport probe | 권리·schema·native code·release timing 테스트 | 미착수 |
| P1 | Credit builder/validator/persist | credit schema·YoY·receipt·immutability | 금지 |
| P2 | LDR exact-date derivation | 양 원천 재현·inner join·분모 가드 | 금지 |
| P3 | MMF mixed-frequency builder | 주기·단위 분리·WRMFSL 0참조·method break | 금지 |
| P4 | read model·UI·generated docs | 확률 분리·금지문구 0·payload 예산·모바일 | 금지 |
| P5 | O/시나리오 참고 증거 연결 | 로직/확률 변화 0, reference link만 | 사용자 별도 승인 전 금지 |

Phase 전환 규칙: 각 단계 결과를 커밋하기 전에 테스트 표와 미충족 항목을 보고한다. 미충족을 완료로 표시하지 않는다.

## 11. 테스트 설계

### P0.5 source/contract

- `test_bank_credit_contract_uses_board_endpoints_not_fredgraph`
- `test_bank_credit_native_codes_are_exact`
- `test_board_license_is_public_domain_with_attribution`
- `test_fred_terms_are_not_inherited_as_activation_approval`
- `test_h8_release_date_is_available_at_not_observation_date`
- `test_ddp_retirement_has_xml_migration_gate`

### P1 credit

- `test_credit_schema_is_reference_only`
- `test_credit_forbids_probability_and_signal_fields_recursively`
- `test_weekly_yoy_uses_exact_364_day_match`
- `test_weekly_yoy_missing_prior_week_stays_null`
- `test_receipt_contains_hash_not_raw_payload`
- `test_same_asof_same_payload_is_byte_identical`
- `test_same_asof_changed_payload_requires_approved_correction`

### P2 LDR

- `test_ldr_recomputes_from_totll_and_deposits`
- `test_ldr_uses_exact_common_wednesday_inner_join`
- `test_ldr_does_not_interpolate_misaligned_week`
- `test_ldr_zero_denominator_is_null`
- `test_ldr_combined_with_probability_is_false`

### P3 MMF

- `test_mmf_weekly_and_quarterly_series_are_separate`
- `test_mmf_units_are_billions_after_board_normalization`
- `test_mmf_quarterly_yoy_uses_same_quarter_prior_year`
- `test_mmf_never_references_wrmfsl`
- `test_mmf_does_not_publish_current_institutional_weekly_series`
- `test_mmf_records_2026_h6_methodology_break`

### P4 read model/UI

- `test_read_model_requires_three_reference_only_layers`
- `test_bank_credit_public_projection_excludes_raw_history_and_receipts`
- `test_bank_credit_ui_displays_reference_only_badge`
- `test_bank_credit_ui_has_no_judgment_or_trading_terms`
- `test_mmf_frequency_labels_are_visible`
- `test_ldr_formula_and_source_toggles_are_visible`
- `test_bank_credit_mobile_chart_has_scroll_affordance`
- `test_data_json_remains_at_or_below_320kb`
- 기존 전체 테스트 회귀 0건

## 12. 사용자 결정 항목과 권고

| 결정 | 권고 | 근거 |
|---|---|---|
| D-0 신규 수집 경로 | **Board H.8/H.6/Z.1로 재경로 승인** | FRED direct archive는 현 약관과 충돌 |
| D-1 기관 MMF | **총자산+소매로 시작** | 확인된 H.6 주간 기관 NSA도 2021-02-01 중단. 현재 공식 계열을 추측해 추가하지 않음 |
| D-2 P5 연결 | **P4 후 보류** | 최소 3회 native snapshot과 stale/revision 동작을 본 뒤 참고 증거로만 연결 |
| D-3 z 시작점 | **2000-01-01** | 기존 진단과 비교 가능하고 모든 핵심 series가 충분한 표본 보유. `n` 병기 |
| D-4 갱신 | **source-aware cadence** | H.8 주간 금요일, H.6 월간 release 내 주간 관측, Z.1 분기. 토요일 job은 H.8만 매주 갱신하고 나머지는 release fingerprint가 바뀔 때만 갱신 |

## 13. 다음 실행용 Codex 프롬프트

> `reports/md/bank_credit_layer_contract_260805.md`를 정본으로 삼아 CREDIT-LIQ **P0.5만** 수행한다. P1 이후에는 착수하지 않는다.
>
> 1. `data/contracts/fed_board_bank_credit.yaml` 초안을 만든다. source는 FRED가 아니라 Federal Reserve Board H.8/H.6/Z.1이며 native code `B1023NCBA`, `B1020NCBA`, `B1058NCBA`, `MMFGB_N.WM`, `FL634090005`를 강제한다.
> 2. H.8 DDP/XML, H.6 DDP/XML, Z.1 CSV ZIP의 endpoint·content type·series code 존재·release timing만 ephemeral probe한다. raw payload를 커밋하지 않는다.
> 3. FRED URL을 collector endpoint 또는 fallback으로 등록하는 계약을 테스트로 거부한다.
> 4. 2026년 11월 DDP BYP 제거에 대비해 Board XML fixture parser 경로와 migration gate를 설계한다. 이번 단계에서는 production collector를 만들지 않는다.
> 5. `source_registry.yaml`과 `ledger_registry.yaml`에는 아직 등록하지 않는다. `enabled:false`, `collector_status:prohibited_until_p0_5_accept`, `model_use:prohibited`, `probability_space:reference_only`를 유지한다.
> 6. D-0~D-4의 사용자 승인 상태를 보고한다. 미승인 항목을 추정하지 않는다.
> 7. 테스트·보고서는 P0.5 범위만 작성하고 기존 전체 테스트를 깨지 않는다.
>
> 수용 기준: Board native source 3종의 transport/schema contract가 재현되고, FRED 자동수집·raw 저장·확률 결합이 테스트로 차단되어야 한다. 미충족이면 P1로 넘어가지 않는다.

## 14. P0 완료 보고

| 항목 | 결과 | 게이트 |
|---|---|---|
| 기존 불변 archive·receipt 패턴 | 실측 완료 | PASS |
| generic FRED fetch 위치 | 실제 위치 확인, 첨부 가정 수정 | PASS |
| 5개 시리즈 주기·단위 | 공식 페이지와 Board native code로 확인 | PASS |
| WRMFSL 중단 | 2021-02-01 중단 확인 | PASS |
| 기관 MMF 현재계열 | 확인 불가가 아니라 **확인된 H.6 주간 계열이 중단 상태** | D-1 제외 권고 |
| 활성 source route | FRED direct 불가, Board direct 대체안 설계 | 사용자 D-0 승인 대기 |
| P1 코드 | 작성하지 않음 | 범위 준수 |

OPEN QUESTIONS:

1. D-0: 신규 collector의 Board 원생산자 재경로를 승인할지.
2. D-1: 현재 공식 기관 MMF를 추가 탐색할지, 총·소매만으로 시작할지.
3. D-2: P4 후 O/시나리오 참고 링크를 승인할지.
4. D-3: z 기준을 2000-01-01로 고정할지.
5. D-4: source-aware cadence를 기존 토요일 workflow에 편입할지.

