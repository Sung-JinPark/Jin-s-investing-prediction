import copy
import json
from pathlib import Path

from ai_fc.timeseries_v7_r6.governance import protected_manifest, verify_inputs


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "data/timeseries_v7_r6/contracts/r6_sharpen_tilt_shadow_v1.json"


def test_registered_inputs_are_content_bound_without_outer() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    result = verify_inputs(ROOT, contract)
    assert result["all_matched"] is True
    assert result["outer_rows_used"] == 0
    assert all(item["role"] != "outer" for item in result["inputs"])


def test_input_hash_drift_fails_closed() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    changed = copy.deepcopy(contract)
    changed["input_artifacts"]["r5_calibration_scores"]["sha256"] = "0" * 64
    assert verify_inputs(ROOT, changed)["all_matched"] is False


def test_protected_manifest_is_deterministic() -> None:
    first = protected_manifest(ROOT)
    second = protected_manifest(ROOT)
    assert first == second
    assert first["entry_count"] > 0
