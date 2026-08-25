from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import warnings
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "tools/audit_v5_gate.py"
SPEC = importlib.util.spec_from_file_location("audit_v5_gate", TOOL)
assert SPEC and SPEC.loader
audit = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = audit
SPEC.loader.exec_module(audit)


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _minimal_pack_tree(root: Path, *, cache: bool = False) -> Path:
    pack = root / "pack"
    pack.mkdir()
    rows = []
    sha_lines = []
    for index in range(audit.EXPECTED_MANIFEST_ENTRIES):
        relative = f"content/file-{index:03d}.txt"
        if cache and index == 0:
            relative = "SOURCE_SNAPSHOT/src/ai_fc/x/__pycache__/x.pyc"
        payload = f"row-{index}".encode()
        path = pack / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        digest = _digest(payload)
        rows.append({"path": relative, "bytes": len(payload), "sha256": digest})
        sha_lines.append(f"{digest}  {relative}")
    (pack / "MANIFEST.json").write_text(json.dumps(rows), encoding="utf-8")
    (pack / "MANIFEST.sha256").write_text("\n".join(sha_lines) + "\n", encoding="utf-8")
    return pack


def _inspection() -> dict:
    return {"unsafe_paths": [], "duplicate_paths": [], "members": []}


def _source_registry(keys: list[str]) -> str:
    body = ",\n".join(f"    {key!r}: SourceSpec()" for key in keys)
    return "SOURCE_REGISTRY: dict[str, object] = {\n" + body + "\n}\n"


def test_clean_manifest_fixture_passes(tmp_path: Path) -> None:
    pack = _minimal_pack_tree(tmp_path)
    result = audit.verify_pack_integrity(pack, _inspection())
    assert result["pass"] is True
    assert result["entry_count"] == 119
    assert result["failures"] == []


def test_tampered_manifest_file_is_detected(tmp_path: Path) -> None:
    pack = _minimal_pack_tree(tmp_path)
    (pack / "content/file-010.txt").write_text("tampered", encoding="utf-8")
    result = audit.verify_pack_integrity(pack, _inspection())
    assert result["pass"] is False
    assert any(row["reason"] in {"sha256 mismatch", "byte size mismatch"} for row in result["failures"])


def test_duplicate_zip_path_is_detected(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.zip"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("root/a.txt", "one")
            archive.writestr("root/a.txt", "two")
    result = audit.inspect_zip_members(path)
    assert result["duplicate_paths"] == [{"path": "root/a.txt", "collides_with": "root/a.txt"}]


@pytest.mark.parametrize("name", ["../escape.txt", "/absolute.txt", "C:/drive.txt"])
def test_path_traversal_and_absolute_paths_are_rejected(tmp_path: Path, name: str) -> None:
    path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(name, "bad")
    result = audit.inspect_zip_members(path)
    assert result["unsafe_paths"]
    destination = tmp_path / "extract"
    destination.mkdir()
    audit.safe_extract(path, destination, result)
    assert list(destination.rglob("*")) == []


def test_backslash_path_is_rejected_before_extraction() -> None:
    canonical, reason = audit.normalized_zip_name("root\\escape.txt")
    assert canonical is None
    assert "backslash" in str(reason)


def test_hgb_contract_runtime_mismatch_and_canonical_hash() -> None:
    contract = {"candidate_bundle": {"hgb_learning_rate": [0.03, 0.07], "hgb_max_leaf_nodes": [7, 15]}}
    source = """
def fit():
    return HistGradientBoostingRegressor(learning_rate=0.05, max_leaf_nodes=7)
"""
    result = audit.contract_runtime_diff(contract, source)
    assert result["exact_match"] is False
    assert len(result["contract"]["specs"]) == 4
    assert result["runtime"]["specs"] == [{"family": "quantile_hist_gradient_boosting", "learning_rate": 0.05, "max_leaf_nodes": 7}]
    assert result["contract_sha256"] != result["runtime_sha256"]
    assert audit.json_hash({"b": 1, "a": 2}) == audit.json_hash({"a": 2, "b": 1})


def test_contract_only_runtime_only_and_alias_sources_are_distinct() -> None:
    contract = {"source_blocks": {"market": {"sources": ["cboe_vix", "bls", "fed_h41"]}}}
    runtime = _source_registry(["cboe_vix", "fed_h41_walcl", "extra"])
    collection = {"results": [{"source_id": "cboe_vix", "receipt_id": "r1", "facts": 1}]}
    parquet = {"files": [{"source_id": "extra"}]}
    result = audit.source_registry_diff(contract, runtime, "cboe_vix", collection, parquet)
    assert result["contract_only"] == ["bls", "fed_h41"]
    assert result["runtime_only"] == ["extra", "fed_h41_walcl"]
    by_id = {row["source_id"]: row for row in result["rows"]}
    assert by_id["bls"]["declaration_status"] == "contract_only"
    assert by_id["extra"]["implementation_materialization_status"] == "materialized_but_not_declared"
    assert by_id["fed_h41"]["declaration_status"] == "alias_candidate"
    assert by_id["fed_h41_walcl"]["declaration_status"] == "alias_candidate"


def test_after_close_observation_maps_to_next_session() -> None:
    sessions = [
        {"session_date": "2026-08-20", "close_at": "2026-08-20T20:00:00Z"},
        {"session_date": "2026-08-21", "close_at": "2026-08-21T20:00:00Z"},
    ]
    after_close = datetime(2026, 8, 20, 20, 0, 1, tzinfo=timezone.utc)
    assert audit.first_eligible_session(after_close, sessions) == "2026-08-21"


def test_date_only_forward_fill_marks_global_feature_pit_unproven() -> None:
    features = '''
archive = path("data/timeseries_v4/parquet/observations.parquet")
wide = archive.pivot(index="observation_time", columns="series_id", values="value").reindex(frame.index).ffill(limit=5)
'''
    pipeline = 'pit_leakage_count = 0 if lineage["ok"] else 1\n'
    run = {"feature_metadata": {"feature_names": ["a", "b"]}, "source_lineage": {"ok": True}}
    result = audit.feature_pit_proof(features, pipeline, run)
    assert result["global_feature_pit_proof"] is False
    assert all(result["patterns"][key]["detected"] for key in ("observation_time_pivot", "date_only_reindex", "forward_fill", "v4_inherited", "lineage_derived_leakage_count"))


def test_approximate_comparator_is_not_claimed_exact() -> None:
    models = "def approximate_anchor_samples(p10, p90):\n    return p10, p90\n"
    pipeline = 'model_crps = float(row["baseline_crps"])\n'
    result = audit.comparator_identity(models, pipeline)
    assert result["gaussian_from_p10_p90"] is True
    assert result["copied_baseline_crps_on_anchor_fallback"] is True
    assert result["exact_comparator_identity"] is False


def test_selection_and_calibration_reuse_is_p0_condition() -> None:
    pipeline = "validation_rows = history[-52:]\nquantile_calibration = residuals\n"
    run = {"latest_selection_by_horizon": {str(h): {"calibration_origins": 52, "quantile_calibration": {str(q): 0 for q in range(9)}} for h in (1, 5, 21, 63)}}
    result = audit.validation_independence(pipeline, run)
    assert result["same_resolved_origins_reused"] is True
    assert result["selection_stacking_calibration_disjoint"] is False
    assert result["label_interval_purge_proof"] is False


def test_pre_open_freshness_distinguishes_completed_and_target_sessions() -> None:
    result = audit.freshness_boundary("2026-08-24T05:01:22Z", "2026-08-14", "2026-08-24")
    assert result["target_session_completed"] is False
    assert result["last_completed_xnas_session"] == "2026-08-21"
    assert result["completed_missing_count"] == 5
    assert result["calendar_target_count"] == 6
    assert result["pre_open_off_by_one_detected"] is True


def test_protected_manifest_detects_mutation(tmp_path: Path) -> None:
    protected = tmp_path / "data/timeseries_v5"
    protected.mkdir(parents=True)
    target = protected / "artifact.json"
    target.write_text("before", encoding="utf-8")
    before = audit.manifest_tree(tmp_path, ("data/timeseries_v5",))
    target.write_text("after", encoding="utf-8")
    after = audit.manifest_tree(tmp_path, ("data/timeseries_v5",))
    result = audit.compare_manifests(before, after)
    assert result["ok"] is False
    assert result["changed"] == ["data/timeseries_v5/artifact.json"]


def test_secret_string_in_output_is_detected_without_using_real_secret(tmp_path: Path) -> None:
    target = tmp_path / "result.json"
    target.write_text('{"api_key":"abcdefghijklmnop123456"}', encoding="utf-8")
    result = audit.scan_secret_texts([target])
    assert result["pass"] is False
    assert result["matches"][0]["redacted"] is True


def test_private_score_matrix_absence_is_explicit_unavailable() -> None:
    matrix = audit.reproducibility_matrix({"status": "fail"})
    assert matrix["row_level_score_recompute"] == "unavailable"
    assert matrix["origin_sample_recompute"] == "unavailable"
    assert matrix["summary_json_parse"] == "complete"


def test_all_thirty_catalog_findings_are_reconciled() -> None:
    detected = [{"id": "F-001", "status": "confirmed"}]
    rows = audit.reconcile_finding_catalog(detected)
    assert len(rows) == 30
    assert rows[0]["status"] == "confirmed"
    assert {row["id"] for row in rows} == {f"F-{value:03d}" for value in range(1, 31)}


def test_pyc_cache_is_packaging_warning_not_integrity_failure(tmp_path: Path) -> None:
    pack = _minimal_pack_tree(tmp_path, cache=True)
    result = audit.verify_pack_integrity(pack, _inspection())
    assert result["pass"] is True
    assert result["packaging_warnings"] == ["SOURCE_SNAPSHOT/src/ai_fc/x/__pycache__/x.pyc"]


def test_reported_arithmetic_is_recomputed_not_relabelled_as_complete() -> None:
    horizons = {
        str(h): {"baseline_crps": 2.0, "model_crps": 1.0, "improvement": 0.5}
        for h in (1, 5, 21, 63)
    }
    reported = {
        "backtest": {"origin_count": 963, "score_count": 3852, "run_id": audit.EXPECTED_RUN_ID, "research_gate": {"pass": False, "by_horizon": horizons, "long_horizon_mean_improvement": 0.5}},
        "verify": {"model_id": audit.EXPECTED_MODEL_ID, "contract_hash": "h", "lineage": {"receipt_count": 1, "observation_count": 2, "link_count": 2}},
        "public_run": {"run_id": audit.EXPECTED_RUN_ID, "contract_hash": "h", "source_lineage": {"receipt_count": 1, "observation_count": 2, "link_count": 2}},
        "latest": {"model_id": audit.EXPECTED_MODEL_ID, "backtest_run_id": audit.EXPECTED_RUN_ID, "research_gate": {"pass": False}, "operational_gate": {"pass": False}, "numbers_visible": False},
        "build_ui": {"static_build": {"numbers_visible": False, "operational_gate_pass": False}},
    }
    result = audit.recompute_evidence(reported)
    assert result["status"] == "partial"
    assert result["score_count_recomputed"] == 3852
    assert result["errors"] == []


def test_tool_returns_two_only_for_tool_execution_failure(tmp_path: Path) -> None:
    code = audit.command(["--pack", str(tmp_path / "missing.zip"), "--output", str(tmp_path / "out.json"), "--repo-root", str(tmp_path)])
    assert code == 2
