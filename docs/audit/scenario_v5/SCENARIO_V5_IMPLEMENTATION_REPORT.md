# Scenario V5 Implementation Report

## Result

Built an evidence-conditioned research candidate without mutating the official snapshot. The candidate honestly retains the reproduced legacy GBM prior because the long-history store lacks the approved row-level PIT/vintage/hash contract required for RCFHS.

## Identity and governance

- Candidate: `scenario_v5_evidence_conditioned_legacy_prior_v1`
- Prior: `legacy_gbm_reproduced_v1`
- Label: `RESEARCH CANDIDATE - NOT OFFICIAL - NOT CHAMPION`
- Dirty-worktree review-only: `True`
- Protected inputs unchanged: `True`
- Candidate verification: `True`

## Evidence separation

- Numerical physical views: `3`
- Reference/blocked views: `6`
- Risk-neutral options are reference-only and are not translated into physical probabilities.
- No approved event-impact mapping exists; every event price jump is exactly zero.

## Posterior and scenarios

- Overall ESS: `15128.57`
- Solver/gates pass: `True`
- S1/S2/S3 probabilities: `0.660965` / `0.040054` / `0.298981`
- Same-shape gate pass: `True`
- Representatives are actual simulated member paths selected by deterministic centrality gates.

## Promotion

Promotion remains blocked pending rolling-origin validation and explicit human approval.

## Required model-risk questions

### 1. What actually entered the legacy graph numerically?

The official snapshot used its stored 252-session GBM parameters, seed 42, and fixed anchor/ATH/reference thresholds. Its structural display then reused one calendar-shape template across S1/S2/S3. It did not numerically ingest the forecast ledger, option views, or unapproved report prose.

### 2. Why did CPI/FOMC/NVDA/report content not enter legacy paths?

No approved point-in-time surprise-to-^IXIC impact mapping existed. Report views also had no approved structured records, so prose-to-number conversion was prohibited.

### 3. Which path metrics receive each numerical EvidenceView?

- `registered:2026-07-10_nasdaq-ath-eoy-2026_r1` -> `max_close_through_classification_date > snapshot_ath`; target `0.6200`, posterior `0.660965`
- `registered:2026-07-20_nasdaq-corr10-augoct-2026_r2` -> `min_close_2026-08-01_through_2026-10-31 <= snapshot_corr10`; target `0.5700`, posterior `0.529909`
- `registered:2026-07-10_nasdaq-eoy-above-jul9-2026_r1` -> `classification_close > snapshot_reference_price`; target `0.6300`, posterior `0.607796`

### 4. Why are some views reference-only?

- `registered:2026-07-20_nfp-jul2026-below100k_r1`: `physical_event`; valid event-state probability; excluded from price paths because no approved surprise-to-index-impact mapping exists
- `registered:2026-07-15_nvda-dc-beat-2026aug_r2`: `physical_event`; valid event-state probability; excluded from price paths because no approved surprise-to-index-impact mapping exists
- `registered:2026-07-08_fomc-2026-10-28-hike_r1`: `physical_event`; valid event-state probability; excluded from price paths because no approved surprise-to-index-impact mapping exists
- `market:2026-08-03T09:33:58+00:00:1:fomc-2026-10-28-hike`: `reference_only`; event probability has no approved surprise-to-index-impact mapping
- `market:2026-08-03T09:33:58+00:00:2:nasdaq-eoy-above-jul9-2026`: `risk_neutral_terminal`; risk-neutral measure has no approved physical-probability calibration
- `market:2026-08-03T09:33:58+00:00:3:nasdaq-ath-eoy-2026`: `risk_neutral_terminal`; risk-neutral measure has no approved physical-probability calibration

### 5. How was risk-neutral information handled?

QQQ option-derived probabilities remain `risk_neutral_terminal`; they are displayed and hashed but never averaged with physical forecasts or used as entropy constraints.

### 6. What proves the scenarios no longer share one residual?

- S1/S2: weekly return corr `0.036329`, turning overlap `0.256410`, normalized distance `0.136749`
- S1/S3: weekly return corr `-0.130607`, turning overlap `0.225000`, normalized distance `0.223113`
- S2/S3: weekly return corr `-0.028752`, turning overlap `0.351351`, normalized distance `0.099425`

The same-shape gate is `True` and all three representatives have distinct member path IDs.

### 7. What is each representative's residual/event/regime lineage?

- S1 member `16989`; S2 member `12563`; S3 member `4550`.
- Residual lineage: each is its own seed-42 GBM simulation row, chosen by exact weighted L1 medoid centrality plus registered realism penalties.
- Event lineage: every unmapped event has `J_t=0`; event forecasts are state-only.
- Regime lineage: no blocked AI/liquidity/cross-asset state is used numerically.

### 8. Does 2027 continuously inherit the 2026 state?

Yes. The artifact contains one ordered anchor plus 252-session path with no calendar-year reset; 2027-01-04 is the next stored session after 2026-12-31.

### 9. How did posterior scenario weights differ from 83/2/15?

S1 `0.660965` (-0.169035), S2 `0.040054` (+0.020054), S3 `0.298981` (+0.148981) versus legacy displayed fractions 0.83/0.02/0.15.

### 10. Which report cluster tilted the posterior?

None. No approved report view exists, so report-cluster numerical strength and posterior tilt are exactly zero. Proposed report files are structurally blocked.

### 11. Are ESS and view conflicts safe?

Overall ESS is `15128.57`; maximum path weight is `0.00014989` and top-1% share is `0.029978`. All three view residuals are inside their declared tolerances.

### 12. Is the official artifact unchanged?

Yes. Official SHA-256 remains `7526638e1b11a04e91112a673fbbca91c00ceb4c00cb1211774532f05d796f9c` and the full protected manifest comparison is `True`.

### 13. Why does this remain a research candidate?

The repository lacks enough approved PIT rolling origins with row-level response hashes, vintages, and available_at timestamps. No OOS scores were fabricated; promotion requires rolling-origin evidence and explicit human approval.

## 2027 representative realism

- S1: annualized daily vol `0.188012`, maximum drawdown `-0.127327`, weekly down count `20`, direction changes `24`
- S2: annualized daily vol `0.183821`, maximum drawdown `-0.106190`, weekly down count `25`, direction changes `25`
- S3: annualized daily vol `0.182296`, maximum drawdown `-0.174410`, weekly down count `25`, direction changes `25`
