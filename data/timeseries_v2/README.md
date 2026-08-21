# NASDAQ multivariate time-series V2 store

This directory is additive research state for `shadow.mf_dfm_ridge_varx_v2`.

- `raw/`: content-addressed official market archive responses.
- `ledgers/`: append-only receipts, observations, forecasts, resolutions, and the one-time sealed evaluation.
- `dfm_cache/`: origin-specific ALFRED PIT factor fits keyed by contract/cutoff/input hash.
- `models/` and `runs/`: derived fits and evaluation evidence.
- `workbooks/`: eight-sheet human review exports; JSONL remains canonical.

Market history is labelled `reconstructed_market_archive`, never native PIT. V2 cannot write official forecasts, mutate Scenario V5.2, or auto-promote itself.

The Federal Reserve EBP file can revise its full history. Its raw file and SHA
are retained, but observations become usable only from this repository's
capture time (`captured_forward`); historical rows are not backdated into the
2007+ sealed evaluation.
