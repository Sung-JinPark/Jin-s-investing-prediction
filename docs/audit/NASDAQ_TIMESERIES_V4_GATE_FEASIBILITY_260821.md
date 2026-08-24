# NASDAQ Time-Series V4 Gate Feasibility Audit

Date: 2026-08-21
Branch: `codex/timeseries-v4-gate`
Decision: **HOLD — no candidate passed the unchanged joint research gate**

## Implemented V4 data layer

The requested source archives were fetched and materialized into the isolated
V4 store instead of remaining a design-only source list.

- 72 append-only raw receipts, 35 unique content-addressed raw gzip blobs.
- 113,615 normalized observations across 97 series; receipt linkage 100%.
- 38 years of Cboe SKEW, 20 years of VVIX, VIX3M from 2009, and VIX9D from 2011.
- NASDAQ-100 daily archive from 1995 and Cboe US equity notional, Tape C share,
  off-exchange share, and trade count from 2009.
- Cleveland Fed daily CPI/core CPI/PCE/core PCE nowcast archive from 2012.
- Philadelphia Fed SPF employment, CPI, unemployment, recession means and
  dispersion releases, explicitly aligned by public release date.
- Captured jobs consensus/actual and Fed-rate probability snapshots were
  retained with their original provider and availability metadata.

The canonical path is raw -> receipt -> append-only observation JSONL ->
Parquet training view -> Excel audit view. The Parquet view has 113,615 rows,
SHA-256 `5ea619dbe1382638db4aaf6c24e20dea11432c28d168fd382712890dee1c3b34`.
FRED/Nasdaq content marked internal-only is represented by a private raw
locator and SHA rather than being republished.

## Actual numerical use

V4 replays the exact 4,000-sample V3 distribution at all 963 weekly origins.
At each origin it computes a trailing-2,520-session absolute-anomaly percentile
from 20 preregistered V4 features. Depending on historical availability, 11 to
20 features enter each origin. The distributional calibrator classified 322
origins low, 363 medium, 79 high, and used fixed-comparator-only handling for
199 early origins lacking the complete VIX term block.

The captured Fed-rate and employment-event histories were not discarded:
they remain in the feature store and audit workbook. Their observed histories
are 6 Fed-rate path snapshots and 1 jobs consensus event. Because both are
below the preregistered 60-event minimum, their coefficient weight is exactly
zero; backfilling them with present-day values would violate PIT integrity.

## Integrity boundary

- V2 and V3 code, contracts, ledgers, snapshots, forecasts, and published UI were not changed.
- Customer forecast numbers remain hidden.
- The fixed V3 anchor ensemble remained the comparator.
- Historical results are labelled research pseudo-OOS. The 2019–2026 period is not relabelled as a never-observed sealed holdout because it was already disclosed during the V2 audit.
- No crisis date, future actual, revised macro value, row-wise oracle, threshold reduction, or silent fallback was used.

## Unchanged joint gate

- Mean 21/63-session CRPS improvement versus the fixed comparator: at least 2%.
- Both 21 and 63-session improvements positive.
- Overlap-aware paired 90% CI upper bound at or below zero.
- Neither realised-sign side may underperform the comparator by more than 5%.
- Absolute-move Q4 p10–p90 coverage at least 65% and no worse than the comparator.
- 2008, 2020, 2022, and rebound p10–p90 coverage at least 70%.
- PIT leakage zero, lineage complete, deterministic replay.

## Diagnostic candidate frontier

The table records deterministic research diagnostics over 963 weekly origins. Values are not production artifacts and are not customer forecasts.

| Candidate | Mean 21/63 CRPS improvement | Q4 coverage 21/63 | 2020 coverage 21/63 | Gate result |
|---|---:|---:|---:|---|
| V3 frozen result | 1.39% | 32.8% / 35.7% | failed | FAIL |
| Recent empirical, volatility-scaled | 2.68% | 29.5% / 32.0% | 44.4% / 33.3% | FAIL |
| Sequential PIT recalibration | 2.37% | 28.2% / 29.0% | 44.4% / 33.3% | FAIL |
| Regime empirical mixture | 2.40% | 28.2% / 32.0% | 22.2% / 22.2% | FAIL |
| Ex-ante mixture-of-experts selector | 2.18% | 29.0% / 27.8% | 44.4% / 22.2% | FAIL |
| Risk-conditioned symmetric tail | about 1.6% | 61.0% / 53.9% | 55.6% / 22.2% | FAIL |
| Directional risk + drawdown rebound, minimum-mass tails | -0.18% | 75.5% / 68.0% | 77.8% / 77.8% | FAIL |
| Same tail design with Cboe VIX9D/VIX3M term features | -0.99% | 72.6% / 65.1% | 77.8% / 100.0% | FAIL |
| Annual nonlinear quantile challenger | -13.79% at full weight | 20.3% / 12.9% | 11.1% / 0.0% | FAIL |

The development-only envelope candidate initially produced a 2.57% mean improvement with development crisis coverage above the thresholds. Its later-period robustness check fell to roughly flat mean improvement and materially missed extreme coverage. It was therefore rejected rather than promoted.

## Finding

The frontier is a real sharpness-versus-coverage conflict, not a software Gate defect. With the now-ingested state vector, distributions sharp enough to improve CRPS do not identify enough of the realised extreme-move quartile. Tail expansions that satisfy every crisis coverage cell move enough probability mass to make CRPS worse than the fixed comparator.

The 2020 cell is especially restrictive: it has only nine weekly origins per horizon and includes a 21-session loss near 33% followed by 63-session gains as large as roughly 37%. A date-free model needs either stronger pre-event market-implied information or very wide tails. The current VIX level/change and the added official Cboe term-structure diagnostic improve classification, but not enough to satisfy both objectives.

## Frozen V4 result

Run `tsv4-research-bd2ac04e8f0a985d22628a2a` produced:

- 21-session CRPS improvement: 0.29%.
- 63-session CRPS improvement: 1.69%.
- Mean long-horizon improvement: 0.99%, below the unchanged 2% requirement.
- Paired overlap-aware 90% loss-difference CI: [-0.000882, -0.000113].
- Q4 and stress coverage Gates remain failed.
- Status: `shadow_gate_hold`; customer forecast numbers remain hidden.

The model content hash is
`a22782051c21fd5f3ded735ae8edf03cb2837efc8886ad528e1ebd35799115eb`.
The audit workbook contains eight sheets and has SHA-256
`afee626deaaaae58ca3ce42dcde89801ed9c8b7daef461549ffc2890157075b5`.
Workbook formula/error scan matched zero error cells. The Observations sheet is
a series-level reconciliation view; the complete 113,615-row ledger remains the
canonical JSONL/Parquet dataset.

## Required next version or forward evidence

A valid next attempt must use a new model version and be frozen before new forward outcomes resolve. The V4 sources are now present, so the remaining work is not another static backfill:

1. Accumulate at least 60 captured-forward CPI/NFP/FOMC consensus and Fed-rate
   probability vectors, or acquire a licensed historical archive with receipts.
2. Train downside and rebound components separately under a new frozen contract.
3. Run true forward-shadow scoring after freeze; do not reuse the disclosed
   2007-2026 history as a new sealed holdout.
4. Keep the weekly raw-first refresh workflow active so newly released official
   nowcasts, surveys, market closes and revisions append automatically.

Until the unchanged Gate passes on a newly preregistered model or forward
evidence, the correct state is `shadow_gate_hold`, not a manufactured PASS.
