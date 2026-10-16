# Historical price comparison

The frozen observation cutoff is **2026-10-15**, as of 2026-10-16 09:00 KST.
This folder contains separate research artifacts and changes no model, official
forecast, snapshot, database, or ledger.

## Reproduce offline

From the repository root, run these commands in order:

```powershell
python reports/research/shanghai_2007_kospi_2026/prices/consolidate.py --offline
python reports/research/shanghai_2007_kospi_2026/prices/analytics.py
```

`consolidate.py` reads retained historical HTML/text snapshots and the official
SSE extracts in `../china/`. It writes `prices.csv` and `source_manifest.json`.
`analytics.py` uses only Python's standard library and writes `analytics.json`
and `chart_ready.csv`. No network access is required for those commands.

`acquire.py` is the initial public-document acquisition helper. Running it is a
refresh operation and must be followed by `consolidate.py`; its intermediate
Yahoo observations do not replace the final choice of official Chinese data.

## Source choices and limits

- SSE Composite and SSE A Share daily closes for 2005–2008 come from official
  SSE statistical yearbooks. Their PDF page references are retained per row.
  Yahoo's matching histories are independent crosschecks, with maximum observed
  difference 0.01 index point across 1,942 pairs.
- KOSPI historical closes come from Yahoo through 2026-10-14. The 2026-10-15
  close of 5,554.22 extends that series from Investing's historical table;
  overlapping closes agree, and a dated Yonhap report and official KOFIA display
  independently support the last close. See `../korea/` for those documents.
- Yahoo's static KRW=X and CNY=X histories provide local currency units per USD.
  USD translation uses exact observed dates without filling missing values.
  FX quote times differ from equity close times and are not specified by Yahoo.
- MSCI WORLD observations remain in the canonical file for auditability, but
  conflicting same-date public snapshots leave this benchmark unverified.
  World returns and world-relative returns are **null** in the analytics.
- Raw files retain out-of-window observations. The manifest records every
  observation excluded from the canonical file and the reason, including raw
  FX observations dated 2026-10-16. No interpolation or silent clipping occurs.
- These are retrospectively retrieved source vintages. They are not certified
  point-in-time forecast inputs, and original provider publication timestamps
  are generally unavailable.

## Fixed methods

The primary comparison aligns January 2006–October 2007 with January
2025–October 2026 by a fixed 19-calendar-year shift. Both stop at the same
calendar counterpart of October 15. Each index is rebased from its first actual
close in the selected window. Historical 2008 outcomes are separate; Korean
observations are never extended.

Weekly correlations use logarithmic returns between adjacent observed calendar
weeks, with no missing-week fill. The final week is partial at the fixed cutoff.
Monthly sensitivity starts are October 2005, January 2006 and April 2006, paired
with the corresponding 2024/2025 dates; the incomplete final month is excluded.
Trading-session sensitivities use exactly 253 and 505 closes for 252 and 504
returns. Volatility uses sample standard deviation of actual daily log returns
times sqrt(252). Drawdowns are negative fractions from prior observed closes.

All prices are **closes**, so the peaks differ from the intraday highs marked
in the user's screenshots. Return, volatility and drawdown fields are fractions;
`rebased_100` is a display index. Correlations are descriptive and do not establish
causality, a crash base rate, a future peak date, or a forecast probability.

The public function `usd_global_comparison(local, fx, world,
benchmark_verified=False)` suppresses benchmark-relative numbers by default.
Its optional verified flag exists for known benchmark fixtures and future
independent verification; the retained MSCI series is not verified.
