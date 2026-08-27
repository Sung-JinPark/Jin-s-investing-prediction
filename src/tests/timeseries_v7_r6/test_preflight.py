import json
from pathlib import Path

from ai_fc.timeseries_v7_r6.preflight import run_preflight


ROOT = Path(__file__).resolve().parents[3]


def test_preflight_uses_only_content_bound_calibration(tmp_path: Path) -> None:
    result = run_preflight(ROOT, tmp_path)
    assert result["status"] == "PASS"
    assert result["calibration"]["rows"] == 2536
    assert result["calibration"]["origin_count"] == 634
    assert result["calibration"]["role_hash_match"] is True
    assert result["row_use_counters"]["outer_rows_used"] == 0
    assert result["proof_boundary"]["row_level_origin_cutoff_fields_in_derived_artifact"] is False
    assert json.loads((tmp_path / "pit_preflight.json").read_text())["status"] == "PASS"
