# Source authority mapping

## 1. 등록 정책

`data/contracts/authoritative_statistics_sources.yaml`에는 22개 원천이 등록되어 있다.

- numeric 허용 16: ALFRED, FRED, Federal Reserve Board, BLS, BEA, Census, Treasury FiscalData, New York Fed, SEC, CFTC, FINRA, Nasdaq, NYSE, HKEX, SSE, CME Group.
- insight-only 6: Yahoo cross-check, Reuters, Ritter IPO research, Renaissance Capital, MacroMicro, user-supplied review.

등록만으로 숫자 사용이 허용되는 것은 아니다. 활성 payload는 source id, 허용 domain, raw receipt, raw hash, normalized observation, cutoff를 모두 통과해야 한다.

## 2. 이번 통계 snapshot에서 실제 사용한 원천

| policy source | 역할 | 활성 logical series | receipts | unique raw | 판정 |
|---|---|---:|---:|---:|---|
| `fred_market_signals` | Federal Reserve Bank of St. Louis 공개 배포 CSV | 28 | 84 | 28 | PASS; current-release vintage 제한 |
| `sec_edgar` | SEC IPO quarterly workbook | 1 | 3 | 1 | PASS; exact workbook URI 정정 완료 |
| `federal_reserve_board` | Federal Reserve Z.1 ZIP | 1 | 3 | 1 | PASS |
| **합계** |  | **30** | **90** | **30** | **PASS WITH VINTAGE LIMITATION** |

## 3. 활성 30개 logical series

### FRED 공개 배포 28개

| series id | upstream 의미 | 웹 사용 범주 |
|---|---|---|
| `M2SL` | 미국 M2 | 유동성 |
| `MMMFFAQ027S` | money market fund assets | 유동성 |
| `DABSHNO` | 가계·비영리 현금·예금·MMF | 유동성·가계 |
| `BOGZ1LM153064475Q` | 가계 보유 corporate equities | 가계 자산 |
| `BOGZ1FL154022375A` | 가계 보유 debt securities | 가계 자산 |
| `NASDAQCOM` | Nasdaq Composite | 시장·유동성 비교 |
| `T10Y2Y` | 10년-2년 국채 금리차 | 금리 |
| `FEDFUNDS` | effective federal funds rate | 금리 |
| `TOTALSL` | 총 소비자신용 | 신용 |
| `TDSP` | household debt-service ratio | 등록됐으나 현재 22개 차트의 직접 source id는 아님 |
| `BOGZ1FL010000346Q` | 가계 원리금 부담 | 신용 |
| `DRTSCILM` | 은행 C&I 대출기준 강화 | 신용 |
| `NCBEILQ027S` | 비금융기업 equity liability | 기업가치 대용치 |
| `CPATAX` | 세후 기업이익 | 기업가치·이익 |
| `UNRATE` | 실업률 | 경기 |
| `CPIAUCSL` | CPI | 물가 |
| `NFCI` | Chicago Fed NFCI | 금융여건 |
| `BOGZ1LM893064105Q` | 미국 전체 corporate equity market value | 자금 지도 |
| `HQMCB10YR` | 10년 high-quality corporate bond spot rate | 신용 |
| `GS10` | 10년 국채금리 | 신용 비교 |
| `DCOILWTICO` | WTI | 물가 선행 비교 |
| `WPU10260314` | copper wire/cable PPI | 물가 선행 비교 |
| `GACDFSA066MSFRBPHI` | Philadelphia Fed 제조업 확산지수 | 경기 |
| `SP500` | S&P 500 | 자금 지도 |
| `CBBTCUSD` | Coinbase BTC/USD | 자금 지도 |
| `NASDAQSOX` | PHLX Semiconductor Index | 반도체 사이클 |
| `SPASTT01KRM661N` | OECD Korea share-price index | 한국·반도체 비교 |
| `HOUST` | Census housing starts | 경기 |

FRED가 공식 공개 distributor라는 사실과 upstream 원자료 생산자가 누구인지는 구분해야 한다. 예를 들어 Nasdaq, S&P, Coinbase 지표는 FRED가 공개 배포하지만 원 지표 소유자는 각 제공자다.

### SEC 1개 logical series → 10개 normalized subseries

`SEC_IPO_QUARTERLY`는 total/us/non-us/corporate/SPAC/fund count와 total/corporate/SPAC/fund proceeds의 10개 subseries로 정규화된다.

### Federal Reserve Board 1개

`FL663067003`: Z.1의 household margin loans and broker receivables.

## 4. 22개 게시 차트의 source coverage

각 차트의 `source_ids`는 위 30개 logical series 중 하나 이상을 가리킨다. 현재 22개 id:

1. `sec_ipo_issuer_mix_h1`
2. `m2_nasdaq`
3. `nasdaq_per_m2`
4. `nasdaq_per_household_liquid_assets`
5. `liquidity_position_map`
6. `yield_curve`
7. `policy_rate`
8. `valuation_proxy`
9. `margin_credit_proxy`
10. `consumer_credit_growth`
11. `loan_standards`
12. `profit_growth`
13. `household_debt_service`
14. `unemployment_rate`
15. `inflation_rate`
16. `financial_conditions`
17. `rate_cycle_since_first_cut`
18. `corporate_bond_pressure`
19. `inflation_lead_panel`
20. `korea_semiconductor_cycle`
21. `housing_manufacturing_warning`
22. `household_balance_sheet_trend_gap`

## 5. 연구·사설 원천 처리

Reuters, MacroMicro, Ritter, Renaissance, Yahoo cross-check 및 사용자 제공 이미지는 가설·표현·검토 관점에만 사용할 수 있다. 최신 통계 payload는 이를 숫자 source로 게시하지 않으며 다음을 명시한다.

- `reports_and_media: insight_only`
- `raw_required_before_derive: true`
- `published_chart_sources: authoritative_only`
- `Yahoo_Finance: disabled_for_statistics_numeric_input`

판정: **PASS**.
