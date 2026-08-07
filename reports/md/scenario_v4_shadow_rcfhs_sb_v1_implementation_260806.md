# Scenario Graph V4 Shadow - RCFHS-SB v1 Implementation Report

Date: 2026-08-06

## Scope

- Implemented a shadow-only Scenario Graph V4 candidate layer.
- Did not modify official `data/scenarios/nasdaq_latest.json`.
- Did not modify official probabilities, `calibration/ledger.csv`, or `data/scenarios/archive/`.
- Did not change legacy snapshot replay.
- Did not install dependencies.
- Did not commit, push, open a PR, or merge.

## Repository/Spec Differences

- `AGENTS.md`: NOT CONFIRMED. The file requested by the task is not present at repository root.
- `prompts/scenario_v4/AI_INVESTING_SCENARIO_V4_CODEX_MASTER_PROMPT_260806.md`: NOT CONFIRMED. The requested prompt file is not present in this checkout; `prompts/` currently contains only `reasoning_core_v1.md`.
- Section 0-28 / Batch A-E text: NOT CONFIRMED because the requested master prompt is absent.
- Compatibility choice: implemented the smallest additive shadow layer using the existing official scenario read model and dashboard flow.

## Implemented

- `src/ai_fc/scenario_v4_shadow.py`
  - Builds `rcfhs-sb-v1` from the current official scenario snapshot.
  - Writes only `data/scenarios/shadow/rcfhs_sb_v1_latest.json`.
  - Validates shadow-only status, default-off dashboard toggle, promotion block, and forbidden guardrail flags.
  - Uses the retained terminal-median `sample_paths` member as the representative line, preserving the "actual ensemble member" rule.
  - Separates per-scenario conditional fan samples from the official weighted mixture fan.
  - Emits overlap warnings when retained conditional sample bands overlap; no artificial separation is applied.

- `src/ai_fc/cli.py`
  - Added `python -m ai_fc scenario-v4-shadow`.

- `src/ai_fc/dashboard.py`
  - Adds optional `scenario_v4_shadow` to the read model.

- `src/ai_fc/read_model_contract.py`
  - Validates `scenario_v4_shadow` when present.

- `src/ai_fc/dashboard_parts/dashboard.js`
  - Adds explicit default-off `RCFHS-SB v1 shadow` toggle in the Future flow.

- `src/ai_fc/dashboard_parts/dashboard.css`
  - Adds compact styling for the V4 shadow toggle.

- `src/tests/test_scenario_v4_shadow.py`
  - Covers representative actual-member selection, fan-space separation, promotion block, and forbidden guardrail drift rejection.

## Blocked / NOT CONFIRMED

- Full scenario conditional p10/p90 fans: BLOCKED. The official snapshot does not serialize the full per-scenario member matrix. The shadow artifact therefore marks conditional fans as `coarse_member_sample_only` with `not_confirmed`.
- Rolling-origin validation: NOT CONFIRMED. No rolling-origin validation dataset or champion gate for RCFHS-SB v1 was found. Promotion remains `blocked_pending_rolling_origin_validation`.
- Exact Section 28 format: NOT CONFIRMED because the master prompt file is absent.

## Verification

- `python -m ai_fc scenario-v4-shadow`
- `python -m ai_fc dashboard`
- `python -m pytest src/tests/test_scenario.py src/tests/test_scenario_v4_shadow.py src/tests/test_read_model_contract.py src/tests/test_dashboard.py -q`

Result: 51 passed.

## Guardrail Result

- Existing L0 work: not mixed.
- Official latest/probabilities/ledger/archive: unchanged.
- Legacy snapshot replay: unchanged.
- New dependencies: none.
- Manual scenario-specific drift/noise: not introduced.
- Common residual: not introduced.
- Fixed dip date: not introduced.
- Endpoint forcing: not introduced.
- 2026 to 2027 calendar-year state reset: not introduced.
- Conditional fan and official weighted mixture fan: separated.
- Conditional overlap: warnings emitted, no artificial separation.
- Champion promotion before rolling-origin validation: blocked.
