# Scenario-specific database clustering audit

## Assignment and labeling boundary

The three scenario databases are not randomly mixed and paths are never reclassified by their simulated result. Deterministic k-medoids sees only origin-state features. Its assignment hash is frozen before forward returns or drawdowns are read. Whole clusters are then labeled from their forward-outcome distributions. This is a historical supervised cluster-labeling step, not an exact-date forecast or an individual-origin cherry-pick.

| Scenario | Source group | Origins / selected | Medoid | Median 126d | Median 252d | Median horizon | Median horizon MDD | Current similarity |
|---|---|---:|---|---:|---:|---:|---:|---:|
| S1 | dotcom_expansion_cycle_db | 94 / 63 | 1999-10-14 | 0.1381 | 0.2801 | 0.3961 | -0.2955 | 0.8652 |
| S2 | balanced_soft_landing_macro_db | 119 / 99 | 2015-03-19 | 0.0667 | 0.1286 | 0.2133 | -0.1733 | 0.4669 |
| S3 | tightening_financial_stress_macro_db | 162 / 7 | 2000-07-07 | -0.2473 | -0.4751 | -0.5102 | -0.6671 | 0.2576 |

Posterior scenario probabilities are S1 62.98%, S2 32.24%, and S3 4.78%. The severe S3 distribution is intentionally low-probability because the current state has low similarity to the selected stress cluster. Complete feature medians, every cluster outcome summary, assignment hashes, sampling ESS, and pairwise 2027 distribution distances are in `SCENARIO_CLUSTER_AUDIT.json`.
