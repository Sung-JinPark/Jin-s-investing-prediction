# Scenario V5 Diff and Rollback

## Scope

All V5 outputs are additive research-candidate artifacts. The official `data/scenarios/nasdaq_latest.json`, its archive, forecast/calibration ledgers, and registered source stores are protected by before/after SHA-256 manifests.

## Rollback

1. Remove the V5 candidate files under `data/scenarios/candidates/`.
2. Remove the V5 contracts under `data/contracts/scenario_v5_*.yaml`.
3. Revert the additive `scenario_v5` Python package, CLI hooks, read-model key, and dashboard V5 block.
4. Rebuild the dashboard; the existing official legacy scenario remains the fallback.

No ledger rollback or data migration is required. Do not delete or rewrite official history.
