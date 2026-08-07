# 1. Scope

PR3A-R3 implements a state-driven dashboard split between the unchanged official legacy view and the explicit `legacy_gbm_actual_member_v1` shadow diagnostic.

# 2. Input and Source Hashes

- Official source SHA-256: `7526638e1b11a04e91112a673fbbca91c00ceb4c00cb1211774532f05d796f9c`
- Diagnostic file SHA-256: `922a3c7c2200f2a55f360becdc29c0d190104bc70e1bf80a4de28cb08c843411`
- Diagnostic canonical SHA-256: `2b0895ccc58ec44b585305f0afa6b974aa15546d05676af0250e75044c68ed57`

# 3. Git/Worktree State

Dedicated `codex/scenario-v4-pr3-remediation` worktree based on PR2 merge `0c14900fec2f1276e799df09f68c8270fd5d9646`.

# 4. Current Behavior

Before R3, the PR2 toggle swapped only `sc`, retained official structural copy/cards/controls, used the global `sc.fan`, ignored conditional distributions, could duplicate the representative as baseline, and labelled active shadow as official.

# 5. Changes

1. Connected only a valid, fresh schema-v2 candidate through the dashboard read model.
2. Added a separate `scenario_v4_shadow_state` so stale/corrupt/missing states remain visible without exposing price data.
3. Added `buildScenarioChartViewModel` with explicit `official_legacy` and `legacy_actual_member_diagnostic` modes.
4. Preserved official legacy as the default.
5. Added diagnostic identity banner: `LEGACY GBM ACTUAL-MEMBER · SHADOW DIAGNOSTIC / NOT RCFHS · NOT OFFICIAL · NOT CHAMPION`.
6. Added a D=100 actual-member comparison using a common axis.
7. Added S1/S2/S3 conditional small multiples with p50, gated bands, and solid actual representative lines.
8. S2 displays p50 plus the explicit insufficient-sample reasons; it has no interval band.
9. Added a separate Legacy joint unconditional distribution panel.
10. Diagnostic mode hides the entire official structural/baseline/lookup/event-risk view instead of mixing candidate states.
11. Added ARIA labels, non-color status text, source/canonical receipts, and responsive styles.

# 6. Files and Symbols

- `scenario_v4_shadow.py::{load_shadow,load_shadow_state}`
- `dashboard.py::build_read_model`
- `read_model_contract.py::schema`
- `dashboard.js::{buildScenarioChartViewModel,diagnosticPanelMarkup,drawDiagnosticDistribution,drawDiagnosticPanels,renderFlow}`
- `dashboard.css`: Scenario PR3A diagnostic styles
- `test_scenario_shadow_dashboard.py`: view-model, source-state, semantics, gate, and layering tests

# 7. Data/Probability Semantics

Official weights are converted to percent only in display markup and remain comparison values. Candidate implied weights remain separately labelled. Conditional quantiles are sourced from `scenario_distributions`; the unconditional panel uses `unconditional_distribution`. The representative is explicitly described as an actual member, not p50.

# 8. Tests and Commands

| Command | Result |
| --- | --- |
| `node --check src/ai_fc/dashboard_parts/dashboard.js` | PASS |
| `python -m pytest src/tests/test_scenario_shadow_dashboard.py -q` | 13 passed |
| `python -m pytest src/tests/test_dashboard.py src/tests/test_dashboard_js_geometry.py src/tests/test_read_model_contract.py -q` | 39 passed |
| `python -m pytest ... test_scenario_v4_shadow.py` during integration | 46 combined passed |
| `schema()` contract inspection | PASS; generated schema excluded by the PR3A path allowlist |
| scoped `git diff --check` | PASS for implementation and generated R0-R3 evidence paths |

# 9. Invariants

- Official view remains initial/default.
- No old PR2 active RCFHS/official label remains.
- Diagnostic view has no structural baseline control or duplicate baseline series.
- S2 is p50-only.
- Stale source returns `display_allowed=false` and a disabled warning control.
- Official source, probabilities, ledger, and historical archive are unchanged.

# 10. Failures and Classification

No code/test failure. Visual browser capture is `BLOCKED_BY_ENVIRONMENT` because this repository has no existing screenshot harness and no dependency installation was authorized. Node syntax, pure view-model, DOM/SVG contract, and existing dashboard regression suites executed successfully as the prescribed fallback.

# 11. Remaining Risks

The diagnostic is still a legacy GBM baseline, not a predictive improvement. Wide/mobile appearance is covered by responsive CSS and DOM contracts but should receive human visual review before public rollout.

# 12. Gate Decision

**PASS. R4 may start.**

# 13. Git Diff Summary

R3 modifies dashboard data wiring, the schema source, JS, and CSS; adds thirteen focused dashboard tests and this report. The generated schema artifact remains unchanged because it is outside the PR3A path allowlist. It does not modify the official snapshot or its default scenario model.

# 14. Rollback

Remove the candidate/state keys and diagnostic-only UI helpers/styles while retaining R1 retirement safety. Official default remains independently usable. No rollback was performed.
