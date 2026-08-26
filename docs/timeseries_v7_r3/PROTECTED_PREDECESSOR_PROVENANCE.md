# V7R3-P0-002 Protected Predecessor Provenance

- Baseline created: `2026-08-24T23:34:13.244574+00:00`
- Predecessor HEAD: `24f748fb30c70878586282de09d231b23f66bdba`
- Decision: `formal_append_only_correction`
- Exact restoration: **not required**
- Next task started: **false**

## File findings

| Path | Baseline SHA-256 | Current SHA-256 | Classification | Git provenance |
|---|---|---|---|---|
| `src/ai_fc/timeseries_v6/source_coverage.py` | `7961e3233f40…` | `5fbabdd67742…` | trailing_blank_line_only | 3ce82b95 |
| `src/tests/timeseries_v6/test_v6_research_dataset.py` | `ca987996412a…` | `bfe1bf724285…` | public_ci_private_archive_skip | 24f748fb, 3ce82b95 |
| `src/tests/timeseries_v6/test_v6_research_verify.py` | `9a4438722830…` | `ab6c6d95da6e…` | public_ci_private_archive_skip | 24f748fb, 3ce82b95 |
| `src/tests/timeseries_v7/test_v6_gate_audit.py` | `067b54104cbb…` | `13dc08f1c375…` | trailing_blank_line_only | 3ce82b95 |

## Decision boundary

The four differences are committed, attributable changes made after the frozen baseline. Two are trailing blank-line normalization; two make missing private Parquet archives explicit skips in public CI. P0-003 must append a superseding baseline correction. This task does not alter the baseline or start P0-003.
