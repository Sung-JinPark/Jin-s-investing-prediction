import json
from pathlib import Path

import pytest

from ai_fc.timeseries_v7_r5.ixic_coverage import build_coverage


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _row(day: str, value: float) -> dict:
    return {
        "series_id": "NASDAQCOM", "date": day, "value": value, "source": "FRED",
        "available_at": "2026-08-27T00:00:00+00:00", "raw_sha256": "a" * 64,
    }


def test_ixic_coverage_accepts_official_increment_through_completed_session(tmp_path: Path) -> None:
    before, after, receipt = tmp_path / "before.jsonl", tmp_path / "after.jsonl", tmp_path / "receipt.json"
    _write_jsonl(before, [_row("2026-08-24", 1.0)])
    _write_jsonl(after, [_row("2026-08-24", 1.0), _row("2026-08-25", 2.0)])
    receipt.write_text(json.dumps({
        "freshness_pass": True, "missing_completed_sessions": 0,
        "target_completed_xnas_session": "2026-08-25", "raw_sha256": "a" * 64,
    }), encoding="utf-8")
    result = build_coverage(predecessor=before, current=after, receipt=receipt)
    assert result["incremental_rows"] == 1
    assert result["incremental_dates"] == ["2026-08-25"]
    assert result["freshness_pass"] is True
    assert result["row_use_counters"]["outer_rows_used"] == 0


def test_ixic_coverage_rejects_stale_receipt(tmp_path: Path) -> None:
    before, after, receipt = tmp_path / "before.jsonl", tmp_path / "after.jsonl", tmp_path / "receipt.json"
    _write_jsonl(before, [_row("2026-08-24", 1.0)])
    _write_jsonl(after, [_row("2026-08-24", 1.0)])
    receipt.write_text(json.dumps({
        "freshness_pass": False, "missing_completed_sessions": 1,
        "target_completed_xnas_session": "2026-08-25", "raw_sha256": "a" * 64,
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="not current"):
        build_coverage(predecessor=before, current=after, receipt=receipt)


def test_ixic_coverage_rejects_nonofficial_market_rows(tmp_path: Path) -> None:
    before, after, receipt = tmp_path / "before.jsonl", tmp_path / "after.jsonl", tmp_path / "receipt.json"
    _write_jsonl(before, [_row("2026-08-24", 1.0)])
    bad = _row("2026-08-25", 2.0)
    bad["source"] = "unofficial"
    _write_jsonl(after, [bad])
    receipt.write_text(json.dumps({
        "freshness_pass": True, "missing_completed_sessions": 0,
        "target_completed_xnas_session": "2026-08-25", "raw_sha256": "a" * 64,
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="official FRED"):
        build_coverage(predecessor=before, current=after, receipt=receipt)
