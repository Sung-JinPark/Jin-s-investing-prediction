import json
from pathlib import Path

import pytest

from ai_fc.timeseries_v7_r5.e0_nesting import (
    E0_CONTRACT,
    canonical_json,
    load_e0_matrix,
    prove_e0_nesting,
)


ROOT = Path(__file__).resolve().parents[3]
REGISTERED = ROOT / (
    "data/timeseries_v7_r4/generated/e0_sample_matrices/"
    "eb64d41e8a1ae3f6a9107bd02e4e2b6ccaeb9726b8d55befa5bac0633f47067b.json"
)


def test_registered_r4_e0_matrix_replays_and_nests_exactly() -> None:
    matrix = load_e0_matrix(REGISTERED)
    proof = prove_e0_nesting(matrix, lambda coordinate: coordinate.values)
    assert matrix.matrix_hash == "eb64d41e8a1ae3f6a9107bd02e4e2b6ccaeb9726b8d55befa5bac0633f47067b"
    assert proof["max_abs_error"] == 0.0
    assert proof["nesting_test_pass"] is True
    assert proof["row_use_counters"]["outer_rows_used"] == 0


def test_nesting_harness_rejects_non_degenerate_candidate() -> None:
    matrix = load_e0_matrix(REGISTERED)
    with pytest.raises(ValueError, match="does not nest E0"):
        prove_e0_nesting(matrix, lambda coordinate: (
            coordinate.values[0] + 1e-6, *coordinate.values[1:]
        ))


def test_loader_rejects_quarantined_path_before_content(tmp_path: Path) -> None:
    path = tmp_path / "quarantine" / "candidate.json"
    path.parent.mkdir()
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="quarantined"):
        load_e0_matrix(path)


def test_loader_rejects_matrix_hash_mutation(tmp_path: Path) -> None:
    payload = json.loads(REGISTERED.read_text(encoding="utf-8"))
    payload["contract"] = dict(E0_CONTRACT)
    payload["coordinates"][0]["sample_set"]["values"][0] += 0.1
    path = tmp_path / "changed.json"
    path.write_bytes(canonical_json(payload))
    with pytest.raises(ValueError, match="content hash mismatch"):
        load_e0_matrix(path)
