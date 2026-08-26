from __future__ import annotations

import hashlib
import importlib.util
import json
import stat
import sys
import zipfile
from pathlib import Path

import pandas as pd
import pytest


TOOL_PATH = Path(__file__).parents[3] / "tools" / "audit_v7_alfred_pit.py"
SPEC = importlib.util.spec_from_file_location("audit_v7_alfred_pit", TOOL_PATH)
assert SPEC and SPEC.loader
AUDIT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = AUDIT
SPEC.loader.exec_module(AUDIT)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_review_fixture(path: Path, *, payload: bytes = b'{"ok":true}\n') -> None:
    payload_name = "EVIDENCE/payload.json"
    manifest_json = {
        "schema_version": 1,
        "file_count_excluding_manifest": 1,
        "files": [{"path": payload_name, "bytes": len(payload), "sha256": _sha(payload)}],
    }
    manifest_bytes = (json.dumps(manifest_json, sort_keys=True) + "\n").encode()
    sha_manifest = (
        f"{_sha(payload)}  {payload_name}\n"
        f"{_sha(manifest_bytes)}  MANIFEST.json\n"
    ).encode()
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(payload_name, payload)
        archive.writestr("MANIFEST.json", manifest_bytes)
        archive.writestr("MANIFEST.sha256", sha_manifest)


def test_clean_pack_manifest_and_extraction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pack = tmp_path / "clean.zip"
    _write_review_fixture(pack)
    monkeypatch.setattr(AUDIT, "EXPECTED_PACK_SHA256", AUDIT.sha256_file(pack))
    destination = tmp_path / "out"
    result = AUDIT.verify_and_extract_pack(pack, destination)
    assert result["manifest_pass"] is True
    assert result["manifest_line_count"] == 2
    assert (destination / "EVIDENCE/payload.json").read_bytes() == b'{"ok":true}\n'


@pytest.mark.parametrize("unsafe_name", ["../escape.txt", "/absolute.txt", "C:/drive.txt"])
def test_zip_path_traversal_and_windows_bypass_are_blocked(
    tmp_path: Path, unsafe_name: str,
) -> None:
    pack = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(pack, "w") as archive:
        archive.writestr(unsafe_name, "bad")
    with zipfile.ZipFile(pack) as archive:
        with pytest.raises(AUDIT.AuditInputError):
            AUDIT.inspect_zip_safety(archive)


def test_windows_backslash_path_is_blocked_before_zip_normalization() -> None:
    with pytest.raises(AUDIT.AuditInputError, match="unsafe ZIP path syntax"):
        AUDIT.normalize_zip_name("folder\\escape.txt")


def test_duplicate_casefolded_zip_path_is_blocked(tmp_path: Path) -> None:
    pack = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(pack, "w") as archive:
        archive.writestr("A/value.json", "one")
        archive.writestr("a/value.json", "two")
    with zipfile.ZipFile(pack) as archive:
        with pytest.raises(AUDIT.AuditInputError, match="duplicate normalized"):
            AUDIT.inspect_zip_safety(archive)


def test_zip_symlink_is_blocked(tmp_path: Path) -> None:
    pack = tmp_path / "symlink.zip"
    info = zipfile.ZipInfo("link")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(pack, "w") as archive:
        archive.writestr(info, "../../target")
    with zipfile.ZipFile(pack) as archive:
        with pytest.raises(AUDIT.AuditInputError, match="symlink"):
            AUDIT.inspect_zip_safety(archive)


def test_decompression_bomb_limits_are_enforced(tmp_path: Path) -> None:
    pack = tmp_path / "bomb.zip"
    with zipfile.ZipFile(pack, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("large.txt", b"0" * 2_000_000)
    limits = AUDIT.ZipLimits(max_entry_bytes=3_000_000, max_total_bytes=3_000_000, max_compression_ratio=10)
    with zipfile.ZipFile(pack) as archive:
        with pytest.raises(AUDIT.AuditInputError, match="compression ratio"):
            AUDIT.inspect_zip_safety(archive, limits)


def test_xnas_cutoff_fixture_reproduces_four_hour_mismatch() -> None:
    fixture = AUDIT.xnas_cutoff_semantic_fixture()
    assert fixture["matches"] is False
    assert fixture["difference_hours"] == 4.0


def test_runtime_static_findings_detect_all_required_mismatches(tmp_path: Path) -> None:
    pipeline_path = tmp_path / "SOURCE/src/ai_fc/timeseries_v7/open_data_pipeline.py"
    controller_path = tmp_path / "SOURCE/src/ai_fc/timeseries_v7/controller.py"
    contract_path = tmp_path / "SOURCE/data/contracts/multivariate_timeseries_v7.yaml"
    pipeline_path.parent.mkdir(parents=True, exist_ok=True)
    controller_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    pipeline_path.write_text(
        '''
def run_backtest():
    label_ends = []
    model = Ridge(alpha=1.0)
    samples = rng.standard_t(df=5, size=10)
    row = {"anchor_weight": anchor_floor}

def collect():
    request = {"output_type": 1}

def parse():
    available_at = f"{vintage}T23:59:59+00:00"

def materialize():
    cutoffs = {"origin_cutoff_at": target["available_at"]}
    snapshot["ALFRED_PAYEMS"] = source
    snapshot["payems_growth_21"] = log(snapshot["ALFRED_PAYEMS"]).diff(21)
    snapshot["max_available_at"] = values.max()

def cycle():
    stage("fixed_nonnegative_E0_floor_plus_E2")
    stage("none_first_generation_unmodified_distribution")
''',
        encoding="utf-8",
    )
    controller_path.write_text(
        'result = {"control_plane": "append_only_file_journal"}\n', encoding="utf-8"
    )
    contract_path.write_text(
        "algorithm: student_t_distributional_regression\n"
        "objective: joint_location_scale_student_t_nll\n"
        "degrees_of_freedom: [3, 5, 8, 12]\n",
        encoding="utf-8",
    )
    result = AUDIT.static_runtime_findings(tmp_path)
    assert result["canonical_xnas_cutoff_proof"] is False
    assert result["full_history_recollection_detected"] is True
    assert result["label_ends_loaded_in_eligibility"] is False
    assert result["five_role_nested_backtest_proof"] is False
    assert result["contract_e2_execution_match"] is False
    assert result["fixed_e0_e2_weights_detected"] is True
    assert result["learned_stacking_executed"] is False
    assert result["cross_fit_calibration_executed"] is False
    assert result["recurring_postgresql_lease_worker"] is False


def test_full_score_matrix_recalculation(tmp_path: Path) -> None:
    dates = [
        "2007-08-01", "2009-05-01", "2020-03-01", "2020-07-01",
        "2022-06-01", "2023-06-01", "2024-06-01",
    ]
    rows = []
    for horizon in (1, 5, 21, 63):
        for index, date in enumerate(dates):
            actual = 0.01 if index % 2 == 0 else -0.01
            rows.append(
                {
                    "origin_session": date,
                    "horizon": horizon,
                    "actual": actual,
                    "model_crps": 0.009 + horizon / 100_000,
                    "baseline_crps": 0.010 + horizon / 100_000,
                    "p10": -0.02,
                    "p25": -0.01,
                    "p50": actual / 2,
                    "p75": 0.01,
                    "p90": 0.02,
                    "probability_up": 0.7 if actual > 0 else 0.3,
                    "rv_21": 0.1 + index / 100,
                }
            )
    path = tmp_path / "scores.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)
    result = AUDIT.recompute_scores(path)
    assert result["score_rows"] == 28
    assert result["origin_count"] == 7
    assert set(result["horizon"]) == {"1", "5", "21", "63"}
    assert all(result["horizon"][key]["skill"] > 0 for key in result["horizon"])


def test_protected_manifest_detects_mutation(tmp_path: Path) -> None:
    target = tmp_path / "data/timeseries"
    target.mkdir(parents=True)
    file_path = target / "fact.json"
    file_path.write_text("one", encoding="utf-8")
    before = AUDIT.protected_manifest(tmp_path)
    file_path.write_text("two", encoding="utf-8")
    after = AUDIT.protected_manifest(tmp_path)
    comparison = AUDIT.compare_manifests(before, after)
    assert comparison["pass"] is False
    assert comparison["changed"] == ["data/timeseries/fact.json"]


def test_secret_scan_redacts_match_and_does_not_need_configured_key(tmp_path: Path) -> None:
    safe = tmp_path / "safe.json"
    safe.write_text('{"secret_name":"FRED_API_KEY"}', encoding="utf-8")
    assert AUDIT.secret_scan_tree(tmp_path)["secret_scan_pass"] is True
    unsafe = tmp_path / "unsafe.txt"
    synthetic_credential = "api_" + "key=" + ("z" * 32)
    unsafe.write_text(synthetic_credential, encoding="utf-8")
    result = AUDIT.secret_scan_tree(tmp_path)
    assert result["secret_scan_pass"] is False
    assert result["findings"][0]["value_redacted"] is True
    assert ("z" * 20) not in json.dumps(result)
