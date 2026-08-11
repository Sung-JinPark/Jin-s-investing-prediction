# Scenario-specific database clustering audit

## Assignment and labeling boundary

The three scenario databases are not randomly mixed and paths are never reclassified by their simulated result. Deterministic k-medoids sees only origin-state features. Its assignment hash is frozen before forward returns or drawdowns are read. Whole clusters are then labeled from their forward-outcome distributions. This is a historical supervised cluster-labeling step, not an exact-date forecast or an individual-origin cherry-pick.

| Scenario | Source group | Origins / selected | Medoid | Median 126d | Median 252d | Median horizon | Median horizon MDD | Current similarity |
|---|---|---:|---|---:|---:|---:|---:|---:|
| S1 | dotcom_price_state_db | 94 / 63 | 1999-10-14 | 0.1381 | 0.2801 | 0.3915 | -0.2955 | 0.8652 |
| S2 | modern_general_market_state_db | 100 / 16 | 2019-01-22 | 0.0161 | 0.1889 | 0.2716 | -0.2220 | 0.3712 |
| S3 | macro_tightening_financial_conditions_db | 162 / 7 | 2000-07-07 | -0.2473 | -0.4751 | -0.5116 | -0.6671 | 0.2576 |

Posterior scenario probabilities are S1 79.91%, S2 14.42%, and S3 5.67%. The severe S3 distribution is intentionally low-probability because the current state has low similarity to the selected stress cluster. Complete feature medians, every cluster outcome summary, assignment hashes, sampling ESS, and pairwise 2027 distribution distances are in `SCENARIO_CLUSTER_AUDIT.json`.
