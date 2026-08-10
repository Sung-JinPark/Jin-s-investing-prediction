# Phase D — Scenario-specific database clusters

Gate: **PASS**

Each scenario has 3,000 paths from a different historical database cohort. S1 uses the selected dotcom expansion price-state cluster, S2 the selected 2016-2026 modern general-market baseline cluster, and S3 the selected 1990-2026 tightening/financial-stress cluster. Deterministic k-medoids uses only features observable at each historical origin. Forward returns and drawdowns are withheld until assignments are frozen, then used only to label and select whole clusters. No individual origin is chosen by its forward result.

Selected 252-session median returns are S1 0.2801, S2 0.1889, and S3 -0.4751. Selected medoids are 1999-10-14, 2019-01-22, and 2000-07-07. Assignment hashes and complete inventories are in `SCENARIO_CLUSTER_AUDIT.json`. No endpoint or turning date is forced.

General-history raw SHA-256: `193e84ada6cbcbcab519c98cd8cd523a158b32ad02531ed3deb1b729f539e7cc`. Dotcom daily raw SHA-256: `d03689edc3bd36da3d634276043fb5a532793c0bf342d1450aa9cd34e34322e0`. Macro-cluster raw SHA-256: `7d7c85b3c6bece1226395a86e79d32a4b333f416f99e18592a516a6135e2b25e`. Seed: `520807`. Main p50 is the pointwise weighted median with no artificial wiggle. Seven actual members plus an actual dotted medoid carry path texture.
