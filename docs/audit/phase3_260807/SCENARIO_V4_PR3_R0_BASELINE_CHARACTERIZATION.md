# 1. Executive Verdict

**R0 gate: PASS WITH ONE PRECISION WARNING.** The current PR2 implementation is a Legacy GBM actual-member display diagnostic, not RCFHS-SB. The independent replay confirms the material PR2 audit claims and provides sufficient file/symbol/test mapping to begin R1.

The warning is narrow: replay from serialized GBM parameters differs from the published integer weekly global `p75` fan at one of 52 points by one index point. The 1,764 published daily quantile cells, scenario counts/probabilities, and all nine retained actual-member sample paths reproduce exactly. This does not invalidate the R0 defect characterization, but R2 must use explicit tolerances and preserve the daily exact-replay gate.

# 2. Repository and Git Baseline

| Item | Value |
| --- | --- |
| Root | `C:/workspace/ai-investing-pr3` |
| Worktree | dedicated linked worktree |
| Branch | `codex/scenario-v4-pr3-remediation` |
| HEAD/base | `0c14900fec2f1276e799df09f68c8270fd5d9646` |
| PR2 merge ancestor | yes, exit 0 |
| Initial tracked diff | none |
| Initial protected manifest | 112 files, SHA-256 `ca969fd197f650d19d30658da41af833e78877178b5eabcd888eee5df06190b1` |

The previous L0 branch was not modified. The hash-valid PR3 delivery pack was placed in canonical repository-relative paths in this dedicated PR2-based worktree. `AGENTS.md` was absent at the PR2 base and was created as an exact copy of `AGENTS_SCENARIO_V4_PR3_TEMPLATE_260807.md`, SHA-256 `5e0b67c825d5428ce4cfb1a8f0e39aecb550f152b9c09596dc4199631c67f562`.

# 3. Required Document Verification

All required documents were present and read completely:

- `AGENTS.md`
- `AGENTS_SCENARIO_V4_PR3_TEMPLATE_260807.md`
- `prompts/scenario_v4/AI_INVESTING_SCENARIO_V4_MODEL_DECISION_260806.md`
- `prompts/scenario_v4/AI_INVESTING_SCENARIO_V4_CODEX_MASTER_PROMPT_260806.md`
- `prompts/scenario_v4/AI_INVESTING_SCENARIO_V4_CODEX_LAUNCHER_260806.md`
- `docs/audit/phase3_260807/AI_INVESTING_SCENARIO_V4_PR2_DEEP_AUDIT_260807.md`
- `docs/audit/phase3_260807/AI_INVESTING_SCENARIO_V4_PR2_DEFECT_REGISTER_260807.csv`
- `docs/audit/phase3_260807/AI_INVESTING_SCENARIO_V4_PR2_AUDIT_METRICS_260807.json`
- `prompts/scenario_v4/AI_INVESTING_SCENARIO_V4_PR3_REMEDIATION_MASTER_PROMPT_260807.md`
- `prompts/scenario_v4/AI_INVESTING_SCENARIO_V4_PR3_CODEX_BATCH_COMMANDS_260807.md`
- `AI_INVESTING_SCENARIO_V4_PR3_README_260807.md`
- `MANIFEST_SHA256.json`

The delivery manifest contains ten entries; all ten sizes and hashes passed. No conflict was found between `AGENTS.md` and the PR3 template because the template is the source of the newly created root file. The user's later authorization permits sequential R0–R4 execution and final push, while the quantitative, artifact, PIT, and promotion gates remain unchanged.

# 4. Current Model Identity

**Decision: CONFIRMED.**

`src/ai_fc/scenario_v4_shadow.py::build_shadow_payload` validates and repackages `data/scenarios/nasdaq_latest.json`. `SHADOW_VERSION` says `rcfhs-sb-v1`, but the source method is `gbm-daily-252d-v2-lookup+db-structural-v2` and the implementation contains none of the required RCFHS components:

- no approved PIT history;
- no observable regime engine or state-conditioned drift;
- no EWMA/GARCH filter;
- no standardized empirical residual pool;
- no stationary block bootstrap or residual date lineage;
- no continuous RCFHS recursion or adaptive simulation;
- no rolling-origin validation.

The artifact therefore cannot use RCFHS, official, or champion identity. Its valid interpretation is **Legacy GBM Actual-Member Display Diagnostic**.

# 5. Legacy Snapshot Reproduction

**Decision: CONFIRMED with the weekly p75 precision warning.**

| Parameter | Replayed value |
| --- | ---: |
| seed | 42 |
| paths | 20,000 |
| horizon | 252 sessions |
| daily log-return mean | 0.000811282145 |
| daily log-return sigma | 0.01168922722 |
| anchor | 25,913.9 |
| ATH | 27,093.9 |
| reference price | 26,206.89 |
| classification date | 2026-12-31 |

The generated future matrix is `20,000 × 252`, SHA-256 `de810442b5e1a6d4f9c589b2d34a2cab3040397fd89928990d055254356756c9`. The partition is mutually exclusive and exhaustive:

| Scenario | Members | Reproduced probability |
| --- | ---: | ---: |
| S1 | 16,702 | 83% |
| S2 | 302 | 2% |
| S3 | 2,996 | 15% |

`python tools/reproduce_scenario_snapshot.py` checked 1,764 daily quantile cells with zero mismatches. The nine retained 25/50/75 member paths also replay with zero integer-cell mismatches. The weekly full-pool fan has one one-point mismatch in `p75`; all other 363 weekly quantile cells match.

Official snapshot SHA-256: `7526638e1b11a04e91112a673fbbca91c00ceb4c00cb1211774532f05d796f9c`.

# 6. Scenario Path Realism

**Decision: CONFIRMED.** The PR2 actual-member lines are materially less template-correlated than the legacy structural paths, but the difference is random GBM realization rather than scenario-conditioned dynamics.

Full-horizon weekly return correlations:

| Family | S1–S2 | S1–S3 | S2–S3 |
| --- | ---: | ---: | ---: |
| Legacy structural | 0.994736 | 0.978369 | 0.992797 |
| PR2 actual member | 0.150419 | 0.053082 | -0.016978 |

2027 slice (`2027-01-08` through `2027-08-04`):

| Family/scenario | Ann. weekly vol | MDD | Down periods | Sign changes | Longest underwater |
| --- | ---: | ---: | ---: | ---: | ---: |
| Legacy S1 | 8.54% | 7.83% | 5 | 3 | 9 |
| Legacy S2 | 8.54% | 7.95% | 5 | 3 | 9 |
| Legacy S3 | 8.54% | 7.99% | 5 | 3 | 9 |
| PR2 S1 | 20.00% | 7.01% | 13 | 21 | 19 |
| PR2 S2 | 16.17% | 6.90% | 10 | 11 | 6 |
| PR2 S3 | 16.90% | 8.47% | 15 | 15 | 9 |

Legacy 2027 correlations are 0.999998/0.999998/0.999998; PR2 actual-member correlations are -0.029120/0.212968/-0.385212.

# 7. Conditional Fan Validity

**Decision: CONFIRMED DEFECT.** `src/ai_fc/scenario_v4_shadow.py::_scenario_conditional_fans` selects the retained terminal 25/50/75-percentile actual paths. These are not pointwise conditional quantiles.

| Scenario | p25 > p50 | p50 > p75 | Any crossing | Ratio |
| --- | ---: | ---: | ---: | ---: |
| S1 | 16 | 5 | 19/52 | 36.54% |
| S2 | 26 | 3 | 28/52 | 53.85% |
| S3 | 20 | 8 | 27/52 | 51.92% |

These arrays must not be rendered as a quantile fan.

# 8. Full Ensemble Reconstruction

**Decision: CONFIRMED for all published audit gates; raw-float equivalence to the historical in-memory matrix is not provable.**

The full matrix, scenario masks, retained member paths, and weekly pointwise scenario quantiles are deterministically reconstructable from the official snapshot. Reconstructed conditional quantile hashes:

| Scenario | Shape | SHA-256 | Monotonicity violations |
| --- | --- | --- | ---: |
| S1 | 7 × 52 | `46cc8244169bb651604f73b7f6342b01310ad398c4fbd22d3f9bfec83e9a2398` | 0 |
| S2 | 7 × 52 | `2b65e69bface717387b1895d9193e1fe5f07157a9b32f3797ccc27eb099b310e` | 0 |
| S3 | 7 × 52 | `8c5228a6562d869053881aa317bb7b5b3599c6de96ae093d8284cb3814e757ec` | 0 |

Because S1/S2/S3 partition the full matrix, concatenating their actual samples reproduces the unconditional joint distribution. Mixture quantiles must be computed from samples, not by averaging scenario quantiles.

# 9. Sample-Size Gate

**Decision: CONFIRMED.** Applying the preregistered gates:

- S1 `n=16,702`: representative, p50, p25/p75, p10/p90, p05/p95 allowed.
- S2 `n=302`: representative and p50 only; every interval band is blocked.
- S3 `n=2,996`: representative, p50, p25/p75, p10/p90, p05/p95 allowed.

The PR2 S2 p25/p75 paths are therefore doubly invalid: they are terminal-rank members rather than pointwise quantiles and fail the `n >= 500` gate.

# 10. Representative-Path Centrality

**Decision: CONFIRMED DEFECT.** The selection is `nearest_terminal_median_continuous_path`, not a medoid or multi-metric central actual member. All three are actual global matrix rows:

| Scenario | Global row | Terminal percentile | Notable risk percentiles |
| --- | ---: | ---: | --- |
| S1 | 13,853 | 50.00 | weekly volatility 92.61p; sign changes 98.11p |
| S2 | 18,673 | 49.83 | MDD 91.23p; longest underwater 91.72p; 5-day loss 86.26p |
| S3 | 1,674 | 50.02 | daily volatility 99.98p; 1-day loss 99.32p |

S3 is extreme beyond the 99th percentile in two core metrics. R2 must retain actual-row identity but replace terminal-only selection with a deterministic multi-metric central selector.

# 11. Dashboard State Consistency

**Decision: CONFIRMED DEFECT.**

- `dashboard.js::drawFlow` reads `sc.fan`; active references to `scenario_conditional_fans`: zero.
- `shadowButton.onclick` changes visible text to `RCFHS-SB v1 official` when active.
- `renderFlow` computes structural metadata once from official data; the toggle swaps `sc` and repaints only the chart.
- In diagnostic mode, `flowDisplayPath(sc,key)` and baseline fallback can both use `sc.paths[key]`, creating duplicate display and baseline lines.
- There are no scenario-specific small multiples.

# 12. Determinism and Canonical Hash

**Decision: CONFIRMED DEFECT.** Tests ran in a disposable temporary root.

- Canonical model content is identical after removing `generated_at`.
- Full payloads differ because `generated_at` changes.
- First refresh: `changed=true`.
- Second identical refresh: `changed=true`.
- File SHA changes on the second refresh.
- After mutating the current official source id, `load_shadow` still returns the stale candidate.

Canonical content and receipt metadata must be separated. Source id/SHA/asof must be validated at load time.

# 13. Immutable Artifact Verification

At R0 end, no application, dashboard, official snapshot, shadow artifact, ledger, archive, probability, calibration, or resolution file was modified. Only documents and R0 audit artifacts were added. Official SHA remains `7526638e1b11a04e91112a673fbbca91c00ceb4c00cb1211774532f05d796f9c`.

# 14. PR3A-R1 to R4 Implementation Map

The exact defect-to-file mapping is in `SCENARIO_V4_PR3_R0_IMPLEMENTATION_MAP.csv`.

- R1: retire and isolate the misidentified candidate; enforce identity capability gates; remove active RCFHS/official exposure.
- R2: reusable exact GBM reproduction; pointwise conditional quantiles and sample gates; multi-metric actual representative; deterministic persistence and stale-source validation.
- R3: state-driven official/diagnostic view model; D=100 representative comparison; conditional small multiples; separate unconditional panel; no duplicate baseline.
- R4: relative-path/size/SHA manifest, evidence receipts, verifier, and ZIP SHA.
- PR3B-D0 remains blocked until an approved immutable NASDAQ PIT history exists.

# 15. Risks and Unknowns

1. One weekly global p75 cell differs by one point under serialized-parameter replay; R2 must keep the exact daily quantile gate and document integer display tolerance.
2. True RCFHS remains blocked by missing approved PIT history and is outside PR3A.
3. The old artifact is currently active and mislabeled; R1 is a semantic safety priority.
4. Dashboard behavior is contract-tested, but final R3 visual QA depends on locally renderable HTML/browser tooling.

# 16. Exact Commands and Test Results

| Command | Exit | Result | Classification |
| --- | ---: | --- | --- |
| `uv run python tools/reproduce_scenario_snapshot.py` | 1 | `uv` executable missing | BLOCKED_BY_ENVIRONMENT |
| `python tools/reproduce_scenario_snapshot.py` | 0 | 83/2/15, 1,764 cells, mismatch 0 | PASS |
| `python -m pytest src/tests/test_scenario.py src/tests/test_scenario_v4_shadow.py -q` | 0 | 18 passed | PASS |
| `python -m pytest src/tests/test_dashboard.py src/tests/test_dashboard_js_geometry.py src/tests/test_read_model_contract.py -q` | 0 | 39 passed | PASS |
| Inline NumPy reconstruction and audit metrics | 0 | matrix/count/fan/centrality/UI/determinism metrics recorded | PASS |

Environment: Python 3.12.10, pytest 9.0.3, NumPy 2.4.3, SciPy 1.17.1, python-frontmatter installed. No dependency was installed or changed.

# 17. R0 Gate Decision

| Gate | Result |
| --- | --- |
| Required docs and hashes | PASS |
| PR2 baseline and source map | PASS |
| Official SHA | PASS |
| Legacy replay/counts/1,764 cells | PASS |
| Path realism | PASS |
| Fan crossing | PASS |
| Full ensemble reconstruction | PASS WITH PRECISION WARNING |
| Sample gate | PASS |
| Representative centrality | PASS |
| Dashboard mismatch | PASS |
| Deterministic no-op defect | PASS |
| Official/ledger/archive mutations | PASS — zero |
| R1–R4 implementation map | PASS |
| Targeted tests | PASS |

**Final decision: PASS. R1 may start.**
