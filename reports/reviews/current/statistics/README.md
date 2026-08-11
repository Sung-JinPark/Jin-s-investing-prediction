# Dot-com Statistics Lab review evidence

Generated: 2026-08-11 KST

## Acceptance result

- UI route: `#statistics`
- Comparison window: dot-com `1997-01-01` and current `2023-01-01`, aligned by elapsed calendar month without endpoint forcing
- Charts: 9
- Latest public-source check: `2026-08-10`
- Use boundary: `reference_only`, `model_use=false`, `official_forecast_input=false`
- Refresh cadence: Saturday 00:20 UTC; each source retains its native daily, monthly, or quarterly frequency
- Full source tests: 423 passed
- DualDB tests: 54 passed
- Statistics/dashboard evidence tests: 36 passed; raw JUnit XML included
- Protected manifest: unchanged, SHA-256 `47e056f2b85389f7a07de2f0d4ac029dfada9274ebb9d44fd2f451720021938a`

## Included evidence

- `dotcom_statistics_latest.json`: dashboard data snapshot with source hashes and caveats
- `statistics_lab_v1.yaml`: source, alignment, vintage, exclusion, and model-use contract
- `dotcom_statistics_sources_20260811.md`: source research and definitions
- `statistics-refresh.yml`: weekly collection workflow
- `statistics_dashboard_pytest.xml`: targeted test log
- `statistics_1280.png`, `statistics_1280_full.png`, `statistics_390.png`: desktop and mobile render checks

## Source and interpretation controls

The collection layer uses FRED-hosted Federal Reserve/BEA data plus the Federal Reserve Z.1 table. FINRA margin statistics, Moody's series, and paid forward-P/E histories are excluded because the repository has no redistribution permission. The valuation chart is explicitly labelled a broad market-value-to-after-tax-profit proxy, not an official NASDAQ forward P/E. Z.1 broker receivables are labelled a margin-credit proxy, not FINRA margin debt.

Historical observations are reconstructed from the latest public release. They are not represented as native point-in-time vintages and are not eligible for forecast-model input.
