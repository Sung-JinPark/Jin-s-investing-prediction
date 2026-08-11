# Scenario-specific database clustering audit

## Assignment and labeling boundary

The three scenario databases are not randomly mixed and paths are never reclassified by their simulated result. Deterministic k-medoids sees only origin-state features. Its assignment hash is frozen before forward returns or drawdowns are read. Whole clusters are then labeled from their forward-outcome distributions. This is a historical supervised cluster-labeling step, not an exact-date forecast or an individual-origin cherry-pick.

| Scenario | Source group | Origins / selected | Medoid | Median 126d | Median 252d | Median horizon | Median horizon MDD | Current similarity |
|---|---|---:|---|---:|---:|---:|---:|---:|
| S1 | expansion_and_easing_episode_db | 193 / 167 | 2024-05-16 | 0.1165 | 0.2562 | 0.3357 | -0.2432 | 0.7005 |
| S2 | non_crisis_soft_landing_episode_db | 99 / 16 | 2004-09-02 | 0.0740 | 0.1625 | 0.2366 | -0.1259 | 0.3355 |
| S3 | tightening_and_financial_stress_episode_db | 128 / 29 | 2000-11-16 | -0.1604 | -0.2359 | -0.3886 | -0.5163 | 0.2652 |

Posterior scenario probabilities are S1 74.88%, S2 13.83%, and S3 11.29%. The severe S3 distribution is intentionally low-probability because the current state has low similarity to the selected stress cluster. Complete feature medians, every cluster outcome summary, assignment hashes, sampling ESS, and pairwise 2027 distribution distances are in `SCENARIO_CLUSTER_AUDIT.json`.
