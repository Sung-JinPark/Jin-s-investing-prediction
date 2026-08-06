# Ledger accumulation audit

- Generated: `2026-08-06T04:39:41+00:00`
- Latest completed NYSE day: `2026-08-05`
- Result: accumulating 22 · frozen 1 · stalled 5 · inactive 1 · violation 0 · planned 3

| Ledger | Cadence | Files / rows | Latest | Status | Finding |
|---|---:|---:|---:|---:|---|
| `forecast_records` | event | 22 | 2026-08-03 | **accumulating** | — |
| `forecast_evidence` | event | 17 | 2026-08-03 | **accumulating** | — |
| `ml_market_history` | weekly | 1 | 2026-08-03 | **accumulating** | — |
| `method_changes` | event | 1 | — | **accumulating** | — |
| `calibration_ledger` | event | 1 / 6 | 2026-07-31 | **accumulating** | — |
| `corrections_ledger` | event | 1 / 19 | — | **accumulating** | — |
| `benchmark_ledger` | event | 1 / 6 | — | **accumulating** | — |
| `cost_ledger` | event | 1 / 5 | — | **accumulating** | — |
| `provider_shadow_ledger` | event | 1 / 0 | — | **accumulating** | — |
| `scenario_archive` | trading_daily | 10 | 2026-08-03 | **stalled** | — |
| `scenario_latest` | trading_daily | 1 | 2026-08-03 | **stalled** | — |
| `cross_asset_archive` | trading_daily | 8 | 2026-08-03 | **stalled** | — |
| `cross_asset_latest` | trading_daily | 1 | 2026-08-03 | **stalled** | — |
| `cross_asset_path_tracking` | trading_daily | 1 / 3 | — | **frozen** | — |
| `cross_asset_path_tracking_v2` | trading_daily | 1 / 3 | 2026-08-03 | **stalled** | — |
| `scenario_band_calibration` | trading_daily | 1 / 0 | — | **accumulating** | — |
| `market_event_calendar` | event | 1 / 53 | 2026-08-04 | **accumulating** | — |
| `signal_archive` | weekly | 3 | 2026-07-31 | **accumulating** | — |
| `liquidity_archive` | weekly | 1 | 2026-07-31 | **accumulating** | — |
| `rate_event_archive` | monthly | 3 | 2026-08-03 | **accumulating** | — |
| `realty_rate_sensitivity_archive` | monthly | 3 | 2026-08-03 | **accumulating** | — |
| `realty_dividends` | monthly | 1 / 343 | 2026-08-03 | **accumulating** | — |
| `realty_o_entry_cohort_archive` | monthly | 1 | 2026-07-30 | **accumulating** | — |
| `ai_capital_archives` | monthly | 6 | 2026-08-04 | **accumulating** | — |
| `dualdb_model_runs` | weekly | 0 | — | **inactive** | — |
| `source_monitoring` | trading_daily | 3 | 2026-08-05 | **accumulating** | — |
| `source_monitoring_status` | trading_daily | 1 | 2026-08-05 | **accumulating** | — |
| `raw_receipts` | event | 0 | — | **planned** | — |
| `quarantine` | event | 0 | — | **planned** | — |
| `bitemporal_facts` | event | 0 | — | **planned** | — |
| `forecast_timestamp_proof` | weekly | 1 | 2026-08-06 | **accumulating** | — |
| `research_pack` | monthly | 2 | — | **accumulating** | — |

## Interpretation

`frozen` is a deliberately retired ledger whose bytes remain immutable. `stalled` is an operational warning, not an immutable-record violation. `planned` means the layer is registered before first ingestion. Existing file hash changes and schema failures are `violation` and fail the check gate.
