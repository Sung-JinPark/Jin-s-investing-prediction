# Review artifacts

This is the single repository location for review packages and frozen handoff material. Market-data ZIP files under `dualdb/data/raw/` are source data and do not belong here.

## Structure

- `current/scenario_v4/`: current V4 PR3 document delivery bundle.
- `current/scenario_v5/`: V5 delivery ZIP and SHA-256 sidecar.
- `current/scenario_v5_1/`: V5.1 final-review ZIP and SHA-256 sidecar.
- `current/scenario_v5_2/`: V5.2 final-review ZIP and SHA-256 sidecar.
- `current/scenario_v5_3/`: V5.3 UI remediation summary pack and the independently recomputable acceptance evidence pack, each with a SHA-256 sidecar.
- `archive/packages/`: historical public review ZIPs.
- `archive/extracted/`: frozen extracted snapshots retained for review provenance.
- `archive/local_only/`: ignored local-only review notes and ZIPs; never included in the public index.
- `INDEX.json`: deterministic inventory, SHA-256, ZIP CRC status, and sidecar verification for public review ZIPs.

## Maintenance

Generate the scenario packages with their registered builders, then rebuild and verify the index:

```powershell
$env:PYTHONPATH='src'
python scripts/build_scenario_v5_3_ui_review_pack.py
python scripts/build_scenario_v5_3_acceptance_evidence_pack.py
python scripts/build_review_index.py
python scripts/build_review_index.py --check
```

Do not place mutable model inputs, official snapshots, ledgers, or raw source-data archives in this tree.
