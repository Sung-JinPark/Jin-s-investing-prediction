from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_fc.timeseries_v5.baseline_audit import (
    _atomic_json,
    compare_protected_manifests,
    compute_score_audit,
    create_protected_manifest,
    reproduce_v4_baseline,
)


ROOT = Path(__file__).resolve().parents[3]
REVIEW_PACK = (
    ROOT
    / "outputs/019fd9ee-deb0-7d63-bef4-8f11a569d7dc"
    / "NASDAQ_MULTIVARIATE_TIMESERIES_V4_REVIEW_PACK_260822.zip"
)


def test_audit_json_writer_is_platform_independent_lf(tmp_path):
    artifact = tmp_path / "audit.json"
    _atomic_json(artifact, {"status": "passed", "items": [1, 2]})
    payload = artifact.read_bytes()
    assert payload.endswith(b"\n")
    assert b"\r\n" not in payload


def test_score_audit_rejects_duplicate_or_incomplete_origin_horizon_grid():
    rows = []
    for origin in ("2020-01-03", "2020-01-10"):
        for horizon in (1, 5, 21, 63):
            rows.append(
                {
                    "origin": origin,
                    "horizon": horizon,
                    "actual": 0.01,
                    "model_crps": 0.009,
                    "baseline_crps": 0.010,
                    "p10": -0.02,
                    "p90": 0.03,
                    "baseline_p10": -0.02,
                    "baseline_p90": 0.03,
                    "quantiles": {"0.1": -0.02, "0.5": 0.0, "0.9": 0.03},
                    "stress_regime": "normal",
                }
            )
    audit = compute_score_audit(rows, expected_horizons=(1, 5, 21, 63))
    assert audit["score_count"] == 8
    assert audit["duplicate_origin_horizon_count"] == 0
    assert audit["missing_origin_horizon_count"] == 0
    assert audit["quantile_monotonicity_violations"] == 0

    with pytest.raises(ValueError, match="duplicate origin/horizon"):
        compute_score_audit(rows + [rows[0]], expected_horizons=(1, 5, 21, 63))
    with pytest.raises(ValueError, match="incomplete origin/horizon"):
        compute_score_audit(rows[:-1], expected_horizons=(1, 5, 21, 63))


def test_protected_manifest_is_deterministic_and_detects_mutation(tmp_path):
    protected = tmp_path / "data/timeseries_v4"
    protected.mkdir(parents=True)
    sample = protected / "sealed.json"
    sample.write_text('{"status":"hold"}\n', encoding="utf-8")
    first = create_protected_manifest(tmp_path, protected_roots=("data/timeseries_v4",))
    second = create_protected_manifest(tmp_path, protected_roots=("data/timeseries_v4",))
    assert first["manifest_sha256"] == second["manifest_sha256"]
    sample.write_text('{"status":"pass"}\n', encoding="utf-8")
    changed = create_protected_manifest(tmp_path, protected_roots=("data/timeseries_v4",))
    comparison = compare_protected_manifests(first, changed)
    assert comparison["unchanged"] is False
    assert comparison["changed"] == ["data/timeseries_v4/sealed.json"]


def test_repository_v4_baseline_is_independently_reproduced_without_promotion():
    protected_before = create_protected_manifest(ROOT)
    result = reproduce_v4_baseline(ROOT, review_pack=REVIEW_PACK)
    assert result["reproduction_pass"] is True
    assert result["benchmark_status"] == "shadow_gate_hold"
    assert result["v4_run"]["score_audit"]["score_count"] == 3_852
    assert result["v4_run"]["score_audit"]["origin_count"] == 963
    assert result["v4_run"]["score_audit"]["duplicate_origin_horizon_count"] == 0
    assert result["v4_run"]["score_audit"]["quantile_monotonicity_violations"] == 0
    assert result["v4_run"]["score_audit"]["horizons"]["21"]["improvement"] == pytest.approx(
        0.0028784508084850812
    )
    assert result["v4_run"]["score_audit"]["horizons"]["63"]["improvement"] == pytest.approx(
        0.016945097002685507
    )
    assert result["v4_run"]["score_audit"]["long_horizon_mean_improvement"] == pytest.approx(
        0.009911773905585295
    )
    lineage = result["v4_source_lineage"]
    assert lineage["receipt_count"] == 72
    assert lineage["observation_count"] == 113_615
    assert lineage["receipts_without_fact_link"] == 37
    assert lineage["receipts_without_explicit_terminal_outcome"] == 72
    assert lineage["revision_seq_distribution"] == {"1": 113_615}
    assert lineage["available_after_1600_et_count"] == 57_973
    assert lineage["fed_event_identity"]["independent_snapshot_count"] == 2
    assert lineage["nfp_consensus"]["pre_release_snapshot_proven"] is False
    assert result["pack_comparison"]["mismatches"] == []
    assert result["review_pack"]["manifest_errors"] == []
    assert result["review_pack"]["zip_sha256"] == (
        "58911b7b042c34e25075a8933350c8d2699b26e6795d4c80d29d42f1454f1f2c"
    )
    assert compare_protected_manifests(protected_before, create_protected_manifest(ROOT))["unchanged"] is True
    # The object must stay serializable as the machine-readable audit artifact.
    json.dumps(result, ensure_ascii=False, sort_keys=True)


def test_v4_reproducer_does_not_reference_credentials_or_collection_clients():
    source = (ROOT / "src/ai_fc/timeseries_v5/baseline_audit.py").read_text(encoding="utf-8")
    for forbidden in (
        "FRED_API_KEY",
        "BLS_API_KEY",
        "BEA_API_KEY",
        "CME_API_KEY",
        "GH_TOKEN",
        "GITHUB_TOKEN",
        ".secrets",
        "urllib.request",
        "requests.get",
        "httpx.",
    ):
        assert forbidden not in source
