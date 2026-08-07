# 1. Scope

PR3A-R2 implements an honest `legacy_gbm_actual_member_v1` diagnostic. It does not implement, name, or promote RCFHS.

# 2. Input and Source Hashes

- Official source: `data/scenarios/nasdaq_latest.json`
- Snapshot id: `nasdaq-scenario:2026-08-03:r8`
- Source SHA-256: `7526638e1b11a04e91112a673fbbca91c00ceb4c00cb1211774532f05d796f9c`
- Reproduced matrix summary SHA-256: `de810442b5e1a6d4f9c589b2d34a2cab3040397fd89928990d055254356756c9`
- Config SHA-256: `693050dff6cd34e10d3bd9cfb8ec0041c6db24be21f740c948eabb388864a322`

# 3. Git/Worktree State

Dedicated `codex/scenario-v4-pr3-remediation` worktree based on PR2 merge `0c14900fec2f1276e799df09f68c8270fd5d9646`.

# 4. Current Behavior

The retired PR2 builder selected terminal-rank member paths, relabelled the global fan, trusted static guardrail booleans, rewrote on every refresh, and did not verify source freshness.

# 5. Changes

1. Added reusable exact legacy GBM reproduction.
2. Reconstructed the full `20,000 × 252` daily matrix and `20,000 × 52` weekly matrix.
3. Enforced exact counts, 1,764 daily quantile cells, and 468 retained-member cells.
4. Calculated true scenario pointwise conditional quantiles.
5. Enforced sample-size gates; S2 stores p50 only.
6. Selected deterministic actual members with central trajectory and robust risk metrics.
7. Separated official weights, candidate implied weights, joint unconditional distribution, and scenario conditional distributions.
8. Added canonical payload hashing, receipt separation, no-op refresh, source freshness validation, structured corruption status, atomic latest writes, and append-only archive/supersession receipts for changed candidates. Runtime Git revision/dirty state is preserved as metadata but excluded from canonical model content.
9. Added `scenario-legacy-actual-shadow` CLI and changed the reproduction tool to use the shared library.
10. Made the legacy percent replay's residual rounding adjustment explicit and auditable; candidate and official weights remain unmodified fractions.

# 6. Files and Symbols

- `scenario_shadow/legacy_reproduction.py::reproduce_legacy_snapshot`
- `scenario_shadow/representative.py::select_actual_representative_path`
- `scenario_shadow/legacy_actual_member.py::build_legacy_diagnostic_payload`
- `scenario_shadow/persistence.py::{canonical_payload_sha256,write_candidate,load_candidate}`
- `tools/reproduce_scenario_snapshot.py::verify`
- `cli.py::cmd_scenario_legacy_actual_shadow`

# 7. Data/Probability Semantics

Canonical weight unit is an explicit fraction:

- official: S1 0.83, S2 0.02, S3 0.15;
- reproduced partition: S1 0.8351, S2 0.0151, S3 0.1498.

The unconditional distribution is calculated directly from the full joint matrix. Conditional quantiles are calculated independently within each mask. No conditional-quantile weighted average is used.

# 8. Tests and Commands

| Command | Result |
| --- | --- |
| `python -m pytest src/tests/test_scenario_legacy_reproduction.py src/tests/test_scenario_legacy_actual_member.py -q` | 10 passed |
| `python -m pytest src/tests/test_scenario_shadow_persistence.py -q` | 9 passed |
| `python tools/reproduce_scenario_snapshot.py` | PASS; counts 16,702/302/2,996; 1,764 mismatch 0; retained mismatch 0 |
| `$env:PYTHONPATH='src'; python -m ai_fc.cli scenario-legacy-actual-shadow` | first `updated`, second `unchanged` |

# 9. Invariants

- Official snapshot SHA unchanged.
- Old retired artifact hash preserved.
- New latest is isolated under `data/scenarios/shadow`.
- Same source/config/seed canonical hash is stable.
- Second refresh leaves latest bytes unchanged.
- Source id/SHA/asof mismatch blocks display.
- Every representative is an exact cohort row.
- Every stored quantile series is monotone.

# 10. Failures and Classification

Two initial unit assertions compared binary floating-point values exactly: the implied-weight sum (`0.9999999999999999`) and the raw replay percent (`83.50999999999999`). Both were test numeric-tolerance defects and were corrected to `pytest.approx`. No model result was clipped or normalized. The separate legacy percent display replay records its required `-1` percentage-point largest-share rounding residual explicitly.

# 11. Remaining Risks

S1 and S3 representatives have a largest five-day loss above the 95th percentile, although all preregistered selection-gate metrics pass. R3 must disclose that a representative is an actual member and is not p50. True RCFHS remains unimplemented and data-blocked.

# 12. Gate Decision

**PASS. R3 may start.**

# 13. Git Diff Summary

Adds four scenario-shadow modules, three R2 test modules, a schema-v2 diagnostic artifact, shared reproduction integration, one CLI command, and R2 audit receipts. No official source file changed.

# 14. Rollback

Disable the new CLI and remove only `legacy_gbm_actual_member_v1_latest.json` plus new modules/tests. Do not restore the retired PR2 candidate as active and do not alter official, ledger, or archive history.
