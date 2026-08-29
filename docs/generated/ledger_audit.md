# Ledger accumulation audit

- Generated: `2026-08-29T08:00:14+00:00`
- Latest completed NYSE day: `2026-08-28`
- Result: accumulating 25 · frozen 1 · stalled 11 · inactive 5 · violation 0 · planned 3

| Ledger | Cadence | Files / rows | Latest | Status | Finding |
|---|---:|---:|---:|---:|---|
| `forecast_records` | event | 24 | 2026-08-22 | **accumulating** | — |
| `forecast_evidence` | event | 19 | 2026-08-22 | **accumulating** | — |
| `ml_market_history` | weekly | 1 | 2026-08-22 | **accumulating** | — |
| `method_changes` | event | 1 | — | **accumulating** | — |
| `calibration_ledger` | event | 1 / 6 | 2026-07-31 | **accumulating** | — |
| `corrections_ledger` | event | 1 / 20 | — | **accumulating** | — |
| `benchmark_ledger` | event | 1 / 6 | — | **accumulating** | — |
| `cost_ledger` | event | 1 / 14 | — | **accumulating** | — |
| `provider_shadow_ledger` | event | 1 / 0 | — | **accumulating** | — |
| `scenario_archive` | trading_daily | 26 | 2026-08-27 | **stalled** | missing trading days: 2026-08-04, 2026-08-05 |
| `scenario_latest` | trading_daily | 1 | 2026-08-27 | **stalled** | — |
| `cross_asset_archive` | trading_daily | 24 | 2026-08-27 | **stalled** | missing trading days: 2026-08-04, 2026-08-25 |
| `cross_asset_latest` | trading_daily | 1 | 2026-08-27 | **stalled** | — |
| `cross_asset_path_tracking` | trading_daily | 1 / 3 | — | **frozen** | — |
| `cross_asset_path_tracking_v2` | trading_daily | 1 / 51 | 2026-08-27 | **stalled** | — |
| `scenario_band_calibration` | trading_daily | 1 / 136 | 2026-08-27 | **stalled** | — |
| `market_event_calendar` | event | 1 / 53 | 2026-08-04 | **accumulating** | — |
| `signal_archive` | weekly | 7 | 2026-08-28 | **accumulating** | — |
| `liquidity_archive` | weekly | 5 | 2026-08-28 | **accumulating** | — |
| `rate_event_archive` | monthly | 19 | 2026-08-27 | **accumulating** | — |
| `realty_rate_sensitivity_archive` | monthly | 19 | 2026-08-27 | **accumulating** | — |
| `realty_dividends` | monthly | 1 / 343 | 2026-08-03 | **accumulating** | — |
| `realty_o_entry_cohort_archive` | monthly | 1 | 2026-07-30 | **accumulating** | — |
| `ai_capital_archives` | monthly | 6 | 2026-08-04 | **accumulating** | — |
| `dualdb_model_runs` | weekly | 0 | — | **inactive** | — |
| `source_monitoring` | trading_daily | 22 | 2026-08-26 | **stalled** | missing trading days: 2026-08-25 |
| `source_monitoring_status` | trading_daily | 1 | 2026-08-26 | **stalled** | — |
| `ipo_reference_batch_receipts` | weekly | 4 | — | **stalled** | — |
| `ipo_reference_batch_status` | weekly | 1 | — | **stalled** | — |
| `timeseries_raw_receipts` | trading_daily | 1 | — | **accumulating** | — |
| `timeseries_observation_facts` | trading_daily | 1 | — | **accumulating** | — |
| `timeseries_event_facts` | event | 0 | — | **inactive** | — |
| `timeseries_event_raw_receipts` | event | 0 | — | **inactive** | — |
| `timeseries_shadow_forecasts` | trading_daily | 1 | — | **stalled** | — |
| `timeseries_shadow_resolutions` | trading_daily | 0 | — | **inactive** | — |
| `timeseries_shadow_corrections` | event | 0 | — | **inactive** | — |
| `timeseries_model_runs` | weekly | 2 | — | **accumulating** | — |
| `timeseries_backtest_runs` | monthly | 2 | — | **accumulating** | — |
| `raw_receipts` | event | 0 | — | **planned** | — |
| `quarantine` | event | 0 | — | **planned** | — |
| `bitemporal_facts` | event | 0 | — | **planned** | — |
| `forecast_timestamp_proof` | weekly | 1 | 2026-08-29 | **accumulating** | — |
| `research_pack` | monthly | 2 | — | **accumulating** | — |
| `scenario_v5_2_distinctness_shadow` | trading_daily | 1 | — | **accumulating** | — |
| `scenario_v5_2_sensitivity_grid` | event | 1 | — | **accumulating** | — |

## Interpretation

`frozen` is a deliberately retired ledger whose bytes remain immutable. `stalled` is an operational warning, not an immutable-record violation. `planned` means the layer is registered before first ingestion. Existing file hash changes and schema failures are `violation` and fail the check gate.
