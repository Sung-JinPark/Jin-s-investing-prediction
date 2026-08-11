# Phase D — Independent multilayer database paths

Gate: **PASS**

Each scenario has 3,000 paths from a different historical regime layer and independent block provenance. The macro history is partitioned before clustering into easing 109, balanced 119, and tightening 162 origin dates; every pairwise overlap count is zero. S1 uses dotcom B=0.60 plus easing-macro B=0.40 in acceleration/correction/reacceleration phases. S2 uses balanced drift/mean-reversion/normalization phases. S3 uses tightening drawdown/failed-relief/stress-persistence phases. All use full realized historical blocks at scale 1.00. Deterministic k-medoids sees only information available at each origin. Forward returns and drawdowns are read only after assignments freeze and label whole clusters; no individual origin is selected by its forward result.

Selected 252-session median returns are S1 0.2801, S2 0.1286, and S3 -0.4751. Selected origin counts are 63/99/7. All three provenance hashes are unique. No endpoint or exact turning date is forced. PER/valuation is reference-only because a vintage-complete cross-era PIT history is unavailable.

General-history raw SHA-256: `193e84ada6cbcbcab519c98cd8cd523a158b32ad02531ed3deb1b729f539e7cc`. Dotcom daily raw SHA-256: `d03689edc3bd36da3d634276043fb5a532793c0bf342d1450aa9cd34e34322e0`. Macro-cluster raw SHA-256: `7d7c85b3c6bece1226395a86e79d32a4b333f416f99e18592a516a6135e2b25e`. Seed: `520807`. p50 is an unmodified pointwise weighted median; actual medoids carry path texture.
