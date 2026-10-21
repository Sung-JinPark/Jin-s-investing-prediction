"""Calibration transport preserves the source rows without enlarging first paint."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from ai_fc import dashboard


@pytest.fixture
def model() -> dict:
    return {
        "meta": {"generated": "2026-10-21T05:00:00Z"},
        "band_calibration": {
            "status": "accumulating",
            "probability_space": "scenario_conditional",
            "source_path": "data/scenarios/band_calibration.csv",
            "observations": 2,
            "minimum_observations": 60,
            "gate_pass": False,
            "latest_asof": "2026-10-20",
            "rows": [
                {"asof": "2026-10-19", "p50": "25970.000", "actual_close": 26348.35,
                 "inside_p10_p90": True, "new_audit_column": "한글·원문", "missing": None},
                {"actual_close": 0, "asof": "2026-10-20", "p50": "0.000",
                 "inside_p10_p90": False, "new_audit_column": "second"},
            ],
        },
    }


def test_split_preserves_every_row_column_order_value_and_gate(model: dict) -> None:
    original = copy.deepcopy(model)
    base, payload = dashboard.split_band_calibration_rows(model)
    assert model == original
    assert payload["contract_id"] == "band_calibration_archive_v1"
    assert payload["data"]["band_calibration"] == original["band_calibration"]
    summary = base["band_calibration"]
    assert "rows" not in summary
    assert {key: value for key, value in summary.items() if key != "rows_archived"} == {
        key: value for key, value in original["band_calibration"].items() if key != "rows"
    }
    assert summary["rows_archived"]["reason"] == "data_json_size_budget"
    assert dashboard.DATA_JSON_BUDGET_BYTES == 900_000


@pytest.mark.parametrize("mode", ["pages", "embed"])
def test_writers_publish_a_matching_lossless_archive(
    model: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str,
) -> None:
    original = copy.deepcopy(model)
    monkeypatch.setattr(dashboard, "build_read_model", lambda *_args: model)
    monkeypatch.setattr(dashboard, "_write_og_image", lambda *_args: None)
    if mode == "pages":
        output = tmp_path / "site"
        dashboard.write_pages(None, output, tmp_path)
        base = json.loads((output / "data.json").read_text(encoding="utf-8"))
    else:
        html_path = dashboard.write_dashboard(None, tmp_path)
        output = html_path.parent
        html = html_path.read_text(encoding="utf-8")
        base = json.loads(html.split("window.__DATA__ = ", 1)[1].split("</script>", 1)[0].rstrip(";"))
    metadata = base["band_calibration"]["rows_archived"]
    archive_path = output / metadata["full_payload"]
    assert archive_path == output / dashboard.BAND_CALIBRATION_FILENAME
    assert metadata["url"] == archive_path.name
    raw = archive_path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == metadata["payload_sha256"]
    assert len(raw) == metadata["payload_bytes"] <= dashboard.BAND_CALIBRATION_BUDGET_BYTES
    archive = json.loads(raw)
    assert archive["contract_id"] == metadata["contract_id"] == "band_calibration_archive_v1"
    assert archive["data"]["band_calibration"] == original["band_calibration"]
    rows = archive["data"]["band_calibration"]["rows"]
    assert len(rows) == metadata["row_count"] == 2
    assert [list(row) for row in rows] == [list(row) for row in original["band_calibration"]["rows"]]
    assert base["band_calibration"]["gate_pass"] is False
    assert metadata["reason"] == ("embed_size_budget" if mode == "embed" else "data_json_size_budget")
    assert model == original


@pytest.mark.parametrize("band", [None, {"status": "unavailable", "gate_pass": False}])
def test_missing_rows_preserve_state_without_a_broken_archive(
    tmp_path: Path, band: dict | None,
) -> None:
    original = {} if band is None else {"band_calibration": band}
    base, payload = dashboard.split_band_calibration_rows(original)
    assert base is original
    assert payload is None
    assert dashboard._compact_embed_band_calibration(original) is original
    stale = tmp_path / dashboard.BAND_CALIBRATION_FILENAME
    stale.write_text("stale public artifact", encoding="utf-8")
    dashboard._write_band_calibration_sidecar(payload, tmp_path)
    assert not stale.exists()


def test_archive_budget_fails_before_writing_outputs(
    model: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dashboard, "build_read_model", lambda *_args: model)
    monkeypatch.setattr(dashboard, "BAND_CALIBRATION_BUDGET_BYTES", 10)
    original = copy.deepcopy(model)
    with pytest.raises(ValueError, match="band calibration archive budget exceeded"):
        dashboard.write_pages(None, tmp_path / "site", tmp_path)
    assert not (tmp_path / "site").exists()
    assert model == original
