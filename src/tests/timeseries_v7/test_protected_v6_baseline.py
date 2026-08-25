from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_fc.timeseries_v7 import protection


def _seed(root: Path) -> tuple[Path, Path]:
    data = root / "data/timeseries_v6/sealed/run.json"
    source = root / "src/ai_fc/timeseries_v6/model.py"
    data.parent.mkdir(parents=True)
    source.parent.mkdir(parents=True)
    data.write_text('{"status":"hold"}\n', encoding="utf-8")
    source.write_text("MODEL_ID = 'v6'\n", encoding="utf-8")
    return data, source


def test_snapshot_is_deterministic_and_categorized(tmp_path: Path) -> None:
    _seed(tmp_path)
    first = protection.build_protected_snapshot(tmp_path)
    second = protection.build_protected_snapshot(tmp_path)
    assert first == second
    assert first["file_count"] == 2
    assert first["protected_hash"] == second["protected_hash"]
    assert first["category_counts"] == {"predecessor_data": 1, "predecessor_source": 1}


def test_added_removed_and_changed_files_are_detected(tmp_path: Path) -> None:
    data, source = _seed(tmp_path)
    before = protection.build_protected_snapshot(tmp_path)
    data.write_text('{"status":"pass"}\n', encoding="utf-8")
    source.unlink()
    added = tmp_path / "data/timeseries_v6/new.json"
    added.write_text("{}\n", encoding="utf-8")
    after = protection.build_protected_snapshot(tmp_path)
    result = protection.compare_snapshots(before, after)
    assert result["pass"] is False
    assert result["changed"] == ["data/timeseries_v6/sealed/run.json"]
    assert result["removed"] == ["src/ai_fc/timeseries_v6/model.py"]
    assert result["added"] == ["data/timeseries_v6/new.json"]


def test_cache_files_are_not_part_of_protected_hash(tmp_path: Path) -> None:
    _seed(tmp_path)
    before = protection.build_protected_snapshot(tmp_path)
    cache = tmp_path / "src/ai_fc/timeseries_v6/__pycache__/model.pyc"
    cache.parent.mkdir()
    cache.write_bytes(b"generated")
    after = protection.build_protected_snapshot(tmp_path)
    assert protection.compare_snapshots(before, after)["pass"] is True


def test_baseline_create_and_strict_verify(tmp_path: Path) -> None:
    _seed(tmp_path)
    baseline_path = tmp_path / "data/timeseries_v7/manifests/baseline.json"
    baseline = protection.create_baseline(tmp_path, baseline_path)
    physical = protection.sha256_file(baseline_path)
    result = protection.verify_baseline(
        tmp_path, baseline_path, expected_physical_sha256=physical
    )
    assert result["pass"] is True
    assert result["file_count"] == 2
    assert baseline["snapshot"]["protected_hash"] == result["actual_hash"]


def test_baseline_cannot_be_silently_overwritten(tmp_path: Path) -> None:
    _seed(tmp_path)
    baseline_path = tmp_path / "data/timeseries_v7/manifests/baseline.json"
    protection.create_baseline(tmp_path, baseline_path)
    with pytest.raises(protection.ProtectedScopeError, match="already exists"):
        protection.create_baseline(tmp_path, baseline_path)


def test_task_envelope_baseline_sha_is_enforced(tmp_path: Path) -> None:
    _seed(tmp_path)
    baseline_path = tmp_path / "data/timeseries_v7/manifests/baseline.json"
    protection.create_baseline(tmp_path, baseline_path)
    with pytest.raises(protection.ProtectedScopeError, match="task envelope"):
        protection.verify_baseline(
            tmp_path, baseline_path, expected_physical_sha256="0" * 64
        )


def test_logical_baseline_tamper_is_detected(tmp_path: Path) -> None:
    _seed(tmp_path)
    baseline_path = tmp_path / "data/timeseries_v7/manifests/baseline.json"
    protection.create_baseline(tmp_path, baseline_path)
    value = json.loads(baseline_path.read_text(encoding="utf-8"))
    value["v6_status"] = "research_gate_pass"
    baseline_path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(protection.ProtectedScopeError, match="logical content hash"):
        protection.load_baseline(baseline_path)


def test_scope_contract_change_is_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed(tmp_path)
    baseline_path = tmp_path / "data/timeseries_v7/manifests/baseline.json"
    protection.create_baseline(tmp_path, baseline_path)
    monkeypatch.setattr(
        protection,
        "ROOT_SPECS",
        protection.ROOT_SPECS + (("unexpected", "new/protected/root"),),
    )
    with pytest.raises(protection.ProtectedScopeError, match="scope differs"):
        protection.load_baseline(baseline_path)
