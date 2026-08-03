# Realty Income 조건부 경로 v2 구현 보고서

작성일: 2026-08-04 KST
시장 기준일: 2026-08-03
범위: Realty Income(O) 경로·관련 데이터 계층·시장전망 UI·Scenario Tracker S8/S9
확률 공간: `scenario_conditional` 또는 `reference_only`; 투자 자문이 아님

## 결론

`o_offset`을 제거하고 O 가격 경로를 다음 감사 가능 식으로 교체했다.

```text
O(m) = 100
     + (NASDAQ(m) - 100) × β_regime
     + β_rate × Δ10Y_scenario(m) / 100
     + β_credit × ΔHY_scenario(m) / 100
     + 0
```

마지막 `0`은 v2에서 고정한 가격 carry다. O 미래선은 가격 경로이므로 현금배당을 포함하지
않는다. Bitcoin의 기존 offset은 이번 범위에서 변경하지 않았다.

실데이터에서 156주 유의성 게이트를 통과한 민감도는 다음과 같다.

| 항목 | 측정값(+100bp당 O 가격 효과) | 10–90% block-bootstrap CI | n | 경로 사용값 | 상태 |
|---|---:|---:|---:|---:|---|
| 장기금리 `DGS10` | -8.372% | -10.646% ~ -6.259% | 156 | -8.372% | eligible |
| HY OAS `BAMLH0A0HYM2` | -6.062% | -7.841% ~ -4.362% | 156 | -6.062% | eligible |

CI가 0을 가로지르거나 표본이 156주보다 적으면 사용값은 자동으로 0이 된다. 현재
FRED HY OAS 공개창은 약 3년이므로 신용 계수는 최소 표본 경계에 정확히 걸려 있다.

## 최신 조건부 경로

단위는 현재가=100인 12개월 가격 sensitivity index다.

| 시나리오 | Δ10Y M+12 | ΔHY M+12 | NASDAQ M+12 | O M+12 |
|---|---:|---:|---:|---:|
| 동반 디레버리징 | -80bp | +150bp | 82.0 | 89.1 |
| AI 조정 후 완화·순환 | -150bp | -50bp | 91.0 | 111.3 |
| 소프트랜딩·자산 순환 | +20bp | 0bp | 112.0 | 96.6 |
| 금리가 안 내려오는 붕괴 | +40bp | +200bp | 82.0 | 76.0 |

따라서 “AI 버블 붕괴 시 O가 오른다”는 무조건 명제가 아니다. 장기금리가 내려가고 신용이
진정되는 완화·순환에서만 O가 100 위로 간다. 신용경색이 남는 디레버리징과 금리 고착
경로에서는 약세가 유지된다.

## 과거 사건과 현재 조건

- 닷컴 완화기(2001-01-03~2003-06-25): O 가격 +50.2%, O 총수익 proxy +79.1%,
  NASDAQ -38.8%, DGS10 -176bp.
- 2005년 O 가격 -14.5%를 같은 민감도의 역방향 반례로 UI에 고정했다.
- Realty Income 2005 연차보고서의 주당 지급배당은 2001~2005년 1.121 → 1.151 →
  1.181 → 1.241 → 1.346달러로 매년 증가했다. Yahoo ex-date 연도 합계도 1.089631 →
  1.117250 → 1.144864 → 1.209786 → 1.312014달러로 같은 증가 방향이다. 공식 표는
  지급연도, Yahoo는 ex-date 기준이라 연간 합계의 정확한 일치는 주장하지 않는다.
- 2020 급성위기: O 가격 -45.6%, NASDAQ -30.1%. 완만한 닷컴 붕괴와 급성 유동성
  위기를 같은 사건으로 보지 않는다.
- 2026-08-03 TTM 배당수익률은 5.11%, DGS10 대비 spread는 +0.36%p다. 현재
  계산된 2000년 이후 spread percentile은 0.3%ile이며, 이는 현재가가 닷컴 직후와 같은
  저평가 출발점이라는 근거가 약함을 뜻한다. 과거 배당 데이터는 최초 저장소 수집시각을
  `available_at`으로 기록하므로 당시 실시간 vintage로 오인하면 안 된다.
- O는 현재 `S&P 500 member since 2015-04`로 표시해 2001년과 패시브 수급 구조가
  다름을 분리했다.

## 데이터 계층과 보존 정책

| 파일 | 역할 | 보존 규칙 |
|---|---|---|
| `data/contracts/cross_asset_macro_assumptions.yaml` | 4개 시나리오 Δ10Y·ΔHY 사전 등록 | 변경 시 새 rules version |
| `data/realty_income/dividends.csv` | O 배당 ex-date·금액·최초 수집시각 | append-only; 과거 삽입·금액 변경 차단 |
| `data/realty_income/sec_annual_dividend_reference.yaml` | 공식 2001–2005 지급배당 교차 기준 | PDF SHA-256·페이지·기준 차이 기록 |
| `data/realty_income/rate_sensitivity_latest.json` | beta·CI·yield spread·배당 모니터 | 기준일 archive 불변 |
| `data/rate_events/registry.yaml` | 사전 등록 사건 6건 | 임의 사건 추가 금지 |
| `data/rate_events/event_study_latest.json` | 사건별 O·NASDAQ·IYR·금리 변화 | 기준일 archive 불변 |
| `data/cross_asset/archive/2026-08-03.json` | 4개 조건부 경로 | 새 스냅샷; 과거 archive 미수정 |
| `data/signals/archive/2026-07-31_CORR-260804-004.json` | S1–S9 tracker revision | 승인 correction만 허용 |

`WILLREITIND`는 D0에서 HTTP 404로 사용할 수 없었다. 계약에 따라 IYR의 파생 총수익
대조선으로 축소했고, Yahoo·ICE 원시 시계열은 재배포하지 않는다. `BAMLH0A0HYM2`의
과거 사건 구간은 현재 공개창에서 확보되지 않아 `history_unavailable_under_current_3y_window`로
명시한다.

## UI와 추적기

- 시장전망 03 탭에 “닷컴 때 왜 올랐나”, “2026년은 같은 조건인가”, “조건 4개 중 n개
  충족” 카드 3개를 추가했다.
- 시나리오 버튼은 4개이며 각 선택에 M+12 Δ10Y·ΔHY와 `사전 등록 가정` 배지를 표시한다.
- 고정 문구는 “O 미래선은 가격 경로이며 배당 미포함. 닷컴형 상승은 조건부 결과였다.”다.
- S8은 DGS10 4주 변화, S9는 최근 12개 O 배당 이벤트의 감액 여부를 본다.
- 2026-07-31 기준 S8은 +26bp로 `rates_stay_high_support`, S9는 최근 배당 0.271,
  감액 0건으로 `easing_rotation_support`다. C1~C4는 2/4 충족이며 확률로 변환하지 않는다.

## 검증 게이트

| 게이트 | 결과 |
|---|---|
| 4개 시나리오 키·M0~M12 길이 | 통과 |
| macro 가정 M0/M3/M6/M12·M0=0 | 통과 |
| beta CI 부호 교차·n<156 시 0 | 단위 테스트 통과 |
| deleveraging 초기 O<100 유지 | 통과 |
| 배당 append-only 충돌 차단 | 통과 |
| rate-event registry 정확히 6건 | 통과 |
| Tracker S1–S9·8KB 예산 | 7,495 bytes, 통과 |
| 기존 스냅샷 불변 | 새 2026-08-03 snapshot 및 승인 tracker revision 사용 |

실행 명령은 `python -m ai_fc cross-asset --force`, `python -m ai_fc market-extensions`,
`pytest -q`, `python -m ai_fc dashboard --pages-out ../_site`다.
