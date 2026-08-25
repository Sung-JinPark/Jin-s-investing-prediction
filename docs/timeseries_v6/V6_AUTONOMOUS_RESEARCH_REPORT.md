# NASDAQ V6 Autonomous Research Flywheel — Final Report

## Outcome

Engineering completion is **PASS** and model publication remains **HOLD**. The autonomous Atlas loop collected the expanded public archive, materialized a PIT-auditable research dataset, evaluated only the preregistered E1–E7 candidates, recorded E8–E10 as ineligible with zero weight, produced a sealed pseudo-OOS run, reproduced that run byte-for-byte, and applied the unchanged Gate.

The system did not force a passing result. `numbers_visible=false` remains in force and no official forecast, Scenario V5.2 probability, or customer-facing time-series number was written.

## Data foundation

- Registry: 37 declared sources.
- Materialized archive: 15 source IDs, 23 required series, 91,147 observations.
- Active required-series coverage: 23/23 (100%).
- Research origins: 1,572 weekly XNAS origins from 1996-04-04 through 2026-05-15.
- Feature matrix: 78 features with explicit source ID and data grade.
- Dataset hash: `841aee4d7b0ea04ec7c273a456a59727de63df644eb2361ad85f6703acf47e0f`.
- PIT leakage count: 0; receipt/observation and feature-provenance rates: 100%.

The 37-source registry is not misreported as 37 fully materialized model inputs. Sources not used by the active research profile remain separately classified. Reconstructed official archives are labeled `reconstructed_official_archive`, never `native_pit`.

## Frozen candidate execution

E1–E7 were evaluated on their preregistered grids. A deterministic minimum-effective-sample rebalance corrected the E5 implementation failure without changing the candidate grid or minimum sample requirement. E1–E7 experiment identities now include estimator implementation versions, so corrected code cannot reuse an older result.

E8, E9, and E10 remained ineligible and had weight zero:

- E8: 0/60 resolved independent events.
- E9: no licensed physical calibration history/receipt.
- E10: no checkpoint and license receipt.

Selected sealed candidates were E3 for 1 day and E1 for 5, 21, and 63 days. The sealed run is `tsv6-sealed-46d58750db2abe8b40cec159` with 1,540 score rows.

## Deterministic replay

The first sealed execution exposed a numerical-runtime defect: host BLAS thread settings were not part of the worker contract, so E1 refits could differ slightly across processes. The correction fixed `MKL_NUM_THREADS`, `NUMEXPR_NUM_THREADS`, `OMP_NUM_THREADS`, and `OPENBLAS_NUM_THREADS` to 1 and `PYTHONHASHSEED` to 0 before numerical imports. It also added implementation versioning to experiment and sealed-run identities.

The corrected sealed run and independent replay both produced score SHA-256 `3338d152acd168f4b003530dc5f3bc5431dceb63ab1d2d4cd68dd55babd9bd8b`. Exact replay therefore passes.

## Unchanged research Gate

| Horizon | CRPS improvement | p10–p90 coverage | p25–p75 coverage |
|---:|---:|---:|---:|
| 1 | 3.29% | 79.74% | 49.61% |
| 5 | 3.50% | 77.40% | 44.68% |
| 21 | 1.27% | 81.56% | 46.75% |
| 63 | 0.58% | 79.74% | 47.01% |

The 21/63-day mean CRPS improvement is 0.93%, below the frozen 2% minimum. The paired stationary-bootstrap 90% CI is approximately `[-0.000621, -0.000146]`, but the model also fails the extreme-Q4 and required crisis-regime coverage/sample conditions. The 5-day p25–p75 coverage is below its allowed lower bound.

Operational freshness also remains HOLD because the captured DTWEXBGS, OFR FSI, and M2SL series exceed their source-specific age/session rules. A stale value is not silently reused as a fresh forecast input.

## Autonomous loop record

The final Atlas run executed versioned E2–E7 selection, sealed evaluation, exact replay, independent Gate, and the V6 regression suite as dependency-ordered tasks. All ten final tasks succeeded on their first attempt. Earlier failed E5 attempts are retained in the Atlas history and experiment ledger instead of being deleted.

## Validation and protection

- V6 suite: 135 passed, 1 skipped.
- Existing repository suite: 617 effective passes using the repository's two existing dependency environments.
- Total: 752 passed, 1 skipped, 0 code failures.
- Protected V1–V5/scenario/official scope: 5,107 files, added/removed/changed = 0/0/0.
- Protected before/after hash: `f5a58e3ea684a73bd3afe3850463efa728e102b1e7f202616a305d2fb88719b2`.
- Workbook: 8 rendered and visually reviewed sheets; formula-error matches = 0.
- Secret scan: the user-provided FRED key is absent from repository and review artifacts.

## Honest limitations

- This run is `research_pseudo_oos`, not a live prospective track record.
- The private raw/Parquet store is not redistributed in the ZIP; the pack contains receipts, hashes, lineage, code, summaries, and derived audit views.
- Research Gate and operational freshness Gate remain HOLD, so the website must continue to show validation status rather than predictions.
- No model threshold, candidate grid, evaluation period, or publication rule was weakened after seeing results.
