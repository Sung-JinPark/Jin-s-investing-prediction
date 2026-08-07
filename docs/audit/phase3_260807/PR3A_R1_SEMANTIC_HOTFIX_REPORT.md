# 1. Scope

PR3A-R1 only: retire the misidentified PR2 candidate, enforce evidence-backed model identity, stop its CLI/loader/UI exposure, and preserve official artifacts.

# 2. Input and Source Hashes

- Official snapshot: `7526638e1b11a04e91112a673fbbca91c00ceb4c00cb1211774532f05d796f9c`
- Retired PR2 artifact before/after move: `cd2bb86b37b2e9cbe6c5c370e3bbd3cc6f21a8953727732c8b4fc27590ee70ca`

# 3. Git/Worktree State

- Branch: `codex/scenario-v4-pr3-remediation`
- Base: PR2 merge `0c14900fec2f1276e799df09f68c8270fd5d9646`
- Dedicated linked worktree: `C:/workspace/ai-investing-pr3`

# 4. Current Behavior

The PR2 artifact was active at `data/scenarios/shadow/rcfhs_sb_v1_latest.json`, declared `rcfhs-sb-v1`, copied legacy GBM model metadata, and could be rebuilt by the old CLI. The dashboard could label it `official`.

# 5. Changes

1. Moved the exact PR2 bytes into `data/scenarios/shadow/archive/rcfhs_sb_v1_misidentified_20260807_cd2bb86b.json` and added a retirement receipt.
2. Replaced `scenario_v4_shadow.py` with a no-write compatibility boundary. It exposes no active candidate and rejects rebuilds.
3. Added `scenario_shadow/contracts.py` with evidence-backed RCFHS identity gates and explicit fraction validation.
4. Changed the old CLI to exit 2 with a retirement reason and zero writes.
5. Removed incorrect active PR2 RCFHS/official dashboard strings.
6. Generalized the read-model schema boundary for future schema-v2 candidates.

# 6. Files and Symbols

- `src/ai_fc/scenario_v4_shadow.py`: `load_shadow`, `refresh_shadow`, `validate_shadow_payload`
- `src/ai_fc/scenario_shadow/contracts.py`: `validate_model_identity`, `validate_candidate_payload`
- `src/ai_fc/cli.py`: `cmd_scenario_v4_shadow`
- `src/ai_fc/dashboard_parts/dashboard.js`: shadow control labels
- `src/ai_fc/read_model_contract.py`: `scenario_v4_shadow` schema
- `src/tests/test_scenario_v4_shadow.py`: R1 behavioral tests

# 7. Data/Probability Semantics

No probability was recalculated or relabelled. The old artifact is audit-only. A name containing `rcfhs` now requires all preregistered capabilities plus implementation, test, and input-lineage evidence. A shadow promotion state containing `official` or `champion` is rejected.

# 8. Tests and Commands

| Command | Result |
| --- | --- |
| `python -m pytest src/tests/test_scenario_v4_shadow.py -q` | 7 passed |
| `python -m pytest src/tests/test_dashboard.py src/tests/test_dashboard_js_geometry.py src/tests/test_read_model_contract.py -q` | 39 passed |
| `$env:PYTHONPATH='src'; python -m ai_fc scenario-v4-shadow` | expected exit 2; no artifact written |
| First manual CLI without `PYTHONPATH` | environment invocation error; rerun corrected |

# 9. Invariants

- Official snapshot SHA unchanged.
- Retired bytes/hash preserved exactly.
- Old active latest absent.
- CLI artifact writes: zero.
- Ledger/archive history outside the new shadow audit archive: unchanged.

# 10. Failures and Classification

No code or data gate failure. The initial direct module invocation without `PYTHONPATH=src` was an environment-command issue, not a code failure.

# 11. Remaining Risks

No active diagnostic exists until R2. The dashboard therefore remains official-only, which is the safe R1 behavior.

# 12. Gate Decision

**PASS. R2 may start.**

# 13. Git Diff Summary

R1 adds the contract package and receipt/tests, edits the compatibility adapter, CLI, read-model schema, and two dashboard labels, and records the old artifact as an exact archive move.

# 14. Rollback

Rollback requires restoring the source changes and moving the exact archived bytes back to the old latest path. It must not alter the official snapshot, ledger, or historical scenario archive. No rollback was performed.
