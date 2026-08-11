# V5.2 call graph and coordinate audit

- `build_clustered_prior` freezes state-feature k-medoids assignments before cluster outcomes are read.
- S1/S2/S3 use separate feature schemas, registered non-overlapping episodes, empirical phase durations, transitions, and residual pools.
- Validated events change episode-group and duration-selection weights before path construction; the adapter is not probability-only.
- A changes post-generation likelihood, B changes S1 episode provenance, and C is derived by `build_weights`.
- `_central_bundle` selects actual simulated members; scenario path IDs use global pool indexes.
- The dashboard SVG allocates history 0.25 and forecast 0.75 in its actual X-coordinate function.
- The research route defaults to three months; one month, 2026, and 2027 remain selectable.
- October 2 remains an ordinary first-touch CDF coordinate, not an exact-date forecast.
