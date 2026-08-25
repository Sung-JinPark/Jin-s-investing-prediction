from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_fc.timeseries_v6.isolation import (
    IsolationError,
    compare_manifests,
    create_protected_manifest,
    is_v6_write_allowed,
    validate_v6_write_paths,
)


def test_manifest_is_deterministic_and_detects_protected_change(tmp_path: Path) -> None:
    target = tmp_path / "data/timeseries_v5/archive.json"
    target.parent.mkdir(parents=True)
    target.write_text('{"status":"hold"}\n', encoding="utf-8")

    first = create_protected_manifest(tmp_path)
    second = create_protected_manifest(tmp_path)
    assert first == second
    assert first["file_count"] == 1
    assert compare_manifests(first, second)["pass"] is True

    target.write_text('{"status":"pass"}\n', encoding="utf-8")
    changed = compare_manifests(first, create_protected_manifest(tmp_path))
    assert changed["pass"] is False
    assert changed["changed"] == ["data/timeseries_v5/archive.json"]


def test_v6_write_allowlist_is_closed_and_path_safe() -> None:
    expected = validate_v6_write_paths(
        [
            "src/ai_fc/timeseries_v6/isolation.py",
            "data/timeseries_v6/manifests/baseline.json",
            "outputs/timeseries_v6/task_results/V6-P0-002/result.json",
        ]
    )
    assert expected == sorted(expected)
    assert is_v6_write_allowed("data/timeseries_v6/a.json")
    assert not is_v6_write_allowed("data/timeseries_v5/a.json")
    with pytest.raises(IsolationError, match="allowlist"):
        validate_v6_write_paths(["README.md"])
    with pytest.raises(IsolationError, match="unsafe"):
        validate_v6_write_paths(["data/timeseries_v6/../../data/timeseries_v5/a"])


def test_manifest_payload_is_json_serializable(tmp_path: Path) -> None:
    path = tmp_path / "data/scenarios/value.bin"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"abc")
    payload = create_protected_manifest(tmp_path)
    assert json.loads(json.dumps(payload))["content_hash"] == payload["content_hash"]
