# Phase D — Complete-separation empirical episode paths

Gate: **PASS WITH PROMOTION BLOCKS**

- 3,000 paths per scenario; only anchor and trading calendar are shared.
- Episode counts S1/S2/S3: 6/4/5; cross-scenario interval overlap: `0`.
- Feature schemas are scenario-native; residual-pool hashes unique: `True`.
- Phase durations and transitions are empirical; fixed template active: `False`.
- Selected origins S1/S2/S3: 167/16/29.
- Kernel gates S1/S2/S3: True/False/False. A failure reports and blocks promotion; it never edits a path.
- S2 transports observed deviations after removing each episode's native mean. No endpoint is forced.
- CAPE and SEC EPS-revision coordinates remain D0/reference-only; stale CAPE and the SEC capex panel are not substituted.
