# Ledger accumulation audit

- Generated: `2026-10-10T07:22:07+00:00`
- Latest completed NYSE day: `2026-10-09`
- Result: accumulating 43 · frozen 2 · stalled 9 · inactive 5 · violation 0 · planned 3

| Ledger | Cadence | Files / rows | Latest | Status | Finding |
|---|---:|---:|---:|---:|---|
| `forecast_records` | event | 66 | 2026-09-14 | **accumulating** | — |
| `forecast_evidence` | event | 30 | 2026-09-14 | **accumulating** | — |
| `ml_market_history` | weekly | 1 | 2026-09-26 | **stalled** | — |
| `method_changes` | event | 1 | — | **accumulating** | — |
| `calibration_ledger` | event | 1 / 16 | 2026-09-14 | **accumulating** | — |
| `corrections_ledger` | event | 1 / 23 | — | **accumulating** | — |
| `benchmark_ledger` | event | 1 / 16 | — | **accumulating** | — |
| `cost_ledger` | event | 1 / 53 | — | **accumulating** | — |
| `provider_shadow_ledger` | event | 1 / 0 | — | **accumulating** | — |
| `scenario_archive` | trading_daily | 50 | 2026-10-09 | **stalled** | missing trading days: 2026-08-04, 2026-08-05, 2026-09-03, 2026-09-16, 2026-09-17, 2026-09-21, 2026-09-22, 2026-10-02, 2026-10-05 |
| `scenario_latest` | trading_daily | 1 | 2026-10-09 | **accumulating** | — |
| `cross_asset_archive` | trading_daily | 47 | 2026-10-09 | **stalled** | missing trading days: 2026-08-04, 2026-08-25, 2026-09-03, 2026-09-16, 2026-09-17, 2026-09-21, 2026-09-22, 2026-10-02, 2026-10-06 |
| `cross_asset_latest` | trading_daily | 1 | 2026-10-09 | **accumulating** | — |
| `cross_asset_path_tracking` | trading_daily | 1 / 3 | — | **frozen** | — |
| `cross_asset_path_tracking_v2` | trading_daily | 1 / 120 | 2026-10-09 | **accumulating** | — |
| `scenario_band_calibration` | trading_daily | 1 / 780 | 2026-10-09 | **accumulating** | — |
| `market_event_calendar` | event | 1 / 58 | 2026-09-28 | **accumulating** | — |
| `signal_archive` | weekly | 13 | 2026-10-09 | **accumulating** | — |
| `liquidity_archive` | weekly | 11 | 2026-10-09 | **accumulating** | — |
| `rate_event_archive` | monthly | 42 | 2026-10-09 | **accumulating** | — |
| `realty_rate_sensitivity_archive` | monthly | 42 | 2026-10-09 | **accumulating** | — |
| `realty_dividends` | monthly | 1 / 345 | 2026-10-01 | **accumulating** | — |
| `realty_o_entry_cohort_archive` | monthly | 3 | 2026-09-30 | **accumulating** | — |
| `ai_capital_archives` | monthly | 6 | 2026-08-04 | **stalled** | — |
| `dualdb_model_runs` | weekly | 0 | — | **inactive** | — |
| `source_monitoring` | trading_daily | 63 | 2026-10-09 | **stalled** | missing trading days: 2026-08-25, 2026-08-27, 2026-08-28 |
| `source_monitoring_status` | trading_daily | 1 | 2026-10-09 | **accumulating** | — |
| `ipo_reference_batch_receipts` | weekly | 4 | 2026-08-19 | **stalled** | — |
| `ipo_reference_batch_status` | weekly | 1 | 2026-10-09 | **accumulating** | — |
| `ipo_edgar_candidates` | weekly | 1 | 2026-09-28 | **stalled** | — |
| `ipo_ai_classification_decisions` | biweekly | 1 | 2026-09-28 | **accumulating** | — |
| `statistics_alert_notify_state` | event | 1 | 2026-10-09 | **accumulating** | — |
| `timeseries_raw_receipts` | trading_daily | 1 | — | **accumulating** | — |
| `timeseries_observation_facts` | trading_daily | 1 | — | **accumulating** | — |
| `timeseries_event_facts` | event | 0 | — | **inactive** | — |
| `timeseries_event_raw_receipts` | event | 0 | — | **inactive** | — |
| `timeseries_shadow_forecasts` | trading_daily | 1 | 2026-10-09 | **accumulating** | — |
| `timeseries_shadow_resolutions` | trading_daily | 0 | — | **inactive** | — |
| `timeseries_shadow_corrections` | event | 0 | — | **inactive** | — |
| `timeseries_model_runs` | weekly | 9 | — | **accumulating** | — |
| `timeseries_backtest_runs` | monthly | 4 | — | **accumulating** | — |
| `raw_receipts` | event | 0 | — | **planned** | — |
| `quarantine` | event | 0 | — | **planned** | — |
| `bitemporal_facts` | event | 0 | — | **planned** | — |
| `forecast_timestamp_proof` | weekly | 1 | 2026-10-10 | **accumulating** | — |
| `research_pack` | monthly | 4 | — | **accumulating** | — |
| `scenario_v5_2_distinctness_shadow` | trading_daily | 1 | — | **accumulating** | — |
| `scenario_v5_2_sensitivity_grid` | event | 1 | — | **accumulating** | — |
| `timeseries_v8_sealed_evaluations` | event | 1 | — | **accumulating** | — |
| `timeseries_v8_shadow_forecasts` | weekly | 1 | — | **stalled** | — |
| `timeseries_v8_shadow_resolutions` | weekly | 1 | — | **accumulating** | — |
| `timeseries_v8_holdout_scorings` | event | 1 | — | **accumulating** | — |
| `timeseries_v8_development_experiments` | event | 1 | — | **accumulating** | — |
| `timeseries_v13_vol_experiments` | event | 1 | 2026-09-10 | **accumulating** | — |
| `timeseries_v13_holdout_scorings` | event | 1 | — | **accumulating** | — |
| `timeseries_v13_approvals` | event | 1 | 2026-09-09 | **accumulating** | — |
| `timeseries_v13_vol_live` | trading_daily | 1 | 2026-10-09 | **accumulating** | — |
| `timeseries_v13_exog_vxn_observations` | event | 1 | 2014-12-31 | **accumulating** | — |
| `timeseries_v13_exog_raw_receipts` | event | 1 | 2026-09-10 | **accumulating** | — |
| `timeseries_v13_vol_live_resolutions` | trading_daily | 1 | 2026-10-08 | **stalled** | — |
| `timeseries_v13_vol_ladder_results` | event | 6 | — | **accumulating** | — |
| `timeseries_v13_vol_coefficients` | event | 1 | — | **frozen** | — |

## Interpretation

`frozen` is a deliberately retired ledger whose bytes remain immutable. `stalled` is an operational warning, not an immutable-record violation. `planned` means the layer is registered before first ingestion. Existing file hash changes and schema failures are `violation` and fail the check gate.
