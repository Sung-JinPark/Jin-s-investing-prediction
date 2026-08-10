# Scenario V5.2 Phase A — V5.1 Baseline Reproduction

Captured before V5.2 source changes on 2026-08-10 (Asia/Seoul).

## Repository state

- Repository root: `C:/workspace/ai-investing`
- Branch: `agent/l0-batch1-validation-review-260806`
- HEAD: `0fc2d870f096f501d2d514bbc7c265c03780fd10`
- Cached diff: empty
- Tracked working-tree diff: empty
- Preserved unrelated untracked roots:
  - `AI_INVESTING_SCENARIO_V4_PR3_DELIVERY_PACK_260807/`
  - `AI_INVESTING_SCENARIO_V5_1_FINAL_REVIEW_PACK_260807.zip`
  - `AI_INVESTING_SCENARIO_V5_1_FINAL_REVIEW_PACK_260807.zip.sha256`
  - `docs/audit/phase3_260807/`
  - `prompts/scenario_v4/`

Only one V5.1 final-review ZIP exists. Its SHA-256 is `3558b9f43cbe892934e1e4f6cca0ccf3f5cad875f1be4dc41f39155431827247`; there is no `(1)` duplicate to compare.

## V5.1 candidate identity

- Candidate: `scenario_v5_1_time_aligned_legacy_prior_v1`
- Status: `degraded`
- As-of: `2026-08-06`
- Knowledge cutoff: `2026-08-07T04:06:20+00:00`
- Source snapshot: `data/scenarios/nasdaq_latest.json`
- Source snapshot SHA-256: `d8754e6a7d1eed4aa46c17625b7ba1e7b1554a4e9799404128d64e3277be75bc`
- Model-content SHA-256: `b3302fcb9dbc54957a65a5df3d0933cd209da1b645ab1f2cb3898bae152fbe68`
- Build-receipt SHA-256: `5f1e75da1a99e488b4ca62b4160bd5a85820c726537f42ee0859487603c9a984`
- Path count: 40,000
- Seed: 42
- Numerical view count: 0
- Posterior status/iterations: `no_numerical_views` / 0
- Correction any-touch probability: 0.190425
- 2027 distinctness gate: false
- Strict candidate replay: PASS

## Proof that the July 2026 employment actual was absent

The July employment release became available at `2026-08-07T12:30:00+00:00`. The V5.1 knowledge cutoff is `2026-08-07T04:06:20+00:00`, which is 8 hours 23 minutes 40 seconds earlier.

The serialized candidate contains no match for `BLS`, `EMPSIT`, `2026-08-07T12:30`, `-23000`, `payroll_actual`, `labor_force_participation`, or `temporary_layoff`. Its nine evidence views all have `available_at` no later than 2026-08-03 and all have `used_numerically=false`.

Conclusion: the 2026-07 BLS actual release, revisions, unemployment rate, participation rate, employment-population ratio, layoffs, hours, and earnings were not available to and were not used by V5.1.

## Solver capability finding

`assemble_candidate_v5_1` creates a `(n_paths, 0)` matrix. If any evidence row is marked numerical it raises `ScenarioV51Error("no V5.1 numerical view condition adapter was approved")`. The entropy solver supports non-empty matrices in isolation, but V5.1 assembly does not construct numerical path-local conditions.

Therefore the V5.1 label “evidence-conditioned” describes its contract and blocking framework, not an actual numerical posterior update. V5.2 must replace this assembly limitation.

## Scenario probabilities and linearity

| Scenario | Probability | Paths | p50 linear-fit R² | p50 annualized daily vol | Actual member annualized daily vol |
|---|---:|---:|---:|---:|---:|
| S1 | 0.903700 | 36,148 | 0.999872 | 0.004946 | 0.185964 |
| S2 | 0.010125 | 405 | 0.914572 | 0.036606 | 0.183517 |
| S3 | 0.086175 | 3,447 | 0.533615 | 0.020085 | 0.181631 |

The dominant S1 pointwise p50 is nearly linear and has approximately 0.5% annualized day-to-day volatility, while its actual central member has approximately 18.6%. This is a statistical-median geometry effect, not evidence that simulated members are smooth.

## Why 10/2 appeared

- The rare S2 cohort contains only 405 of 40,000 paths (1.0125%).
- Its daily conditional pointwise p50 trough is 2026-10-01 at 24,804.02.
- The dashboard samples every five sessions; 2026-10-02 is one of those sampled coordinates.
- The first-touch timing distribution has `exact_date_forecast=false`.
- The CDF through 2026-10-02 is 0.142025; the conditional touch quantiles are p25 2026-09-01, p50 2026-09-16, p75 2026-10-05.

Conclusion: 10/2 was a chart sampling/selection coordinate near a rare-cohort pointwise-median trough, not a macro-event date forecast.

## Protected baseline

- Protected roots are defined by `src/ai_fc/scenario_v5/contracts.py`.
- Protected file count: 105
- Missing protected roots: none
- Protected manifest SHA-256: `2e2f879733f4f6bc8d350af9a683917161234dd4ba2f59cbf4a4fef463d712d4`
- Official snapshot SHA-256: `d8754e6a7d1eed4aa46c17625b7ba1e7b1554a4e9799404128d64e3277be75bc`
- Forecast/calibration ledger SHA-256: `aa180a76ca49ec59cc10a35d62c0ca3abafdb01f467a9111639e3259a5d7cd0e`
- Benchmark ledger SHA-256: `d0175707d623f0b7a0c1f4e4cdfd1732a57ecea418e9880e4b8fe6c4c79eb696`

## Gate A verdict

**PASS**

Official/protected paths, current candidate, source snapshot, and unrelated user changes are unambiguous. V5.2 may proceed without modifying or deleting any protected artifact.
