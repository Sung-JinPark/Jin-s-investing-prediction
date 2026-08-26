import hashlib
import json
from pathlib import Path

from ai_fc.timeseries_v7_r4.g3_stress_tail_path import build_g3_generation


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_g3_generation_binds_frozen_coordinates_roles_and_weights(tmp_path: Path) -> None:
    repo = Path(__file__).parents[3]
    output = tmp_path / "g3"
    summary = build_g3_generation(repo=repo, output_dir=output)

    assert summary["schema"] == "r4_g3_stress_tail_path_v1"
    assert summary["generation_id"].startswith("G3-")
    assert summary["frozen_evaluation"] == {
        "comparator": "E0", "horizons": [1, 5, 21, 63],
        "weekly_origins": True, "origin_count": 1025, "score_rows": 4082,
        "evaluation_coordinate_grid_hash":
            "1f2403b7b15c100741a29816304056c2ad7b91cd777b29534a96a567068fa7e8",
    }
    expected = {
        f"R4-S4-{number:03d}":
            f"outputs/timeseries_v7_r4/R4-S4-{number:03d}/r4_calibration/acceptance_summary.json"
        for number in range(1, 6)
    }
    assert set(summary["mechanism_artifacts"]) == set(expected)
    for task, relative in expected.items():
        assert summary["mechanism_artifacts"][task] == {
            "path": relative, "sha256": _sha256(repo / relative)
        }
    assert summary["stacking_evaluation_role"] == "calibration_cross_fit_holdout"
    assert summary["calibration_role_hash"] == "0f96b564e45155f90819c050f6435e964f8707989a67b5ba1f3da897c7b95fa2"
    assert summary["row_use_counters"] == {
        "legacy_review_pack_score_rows_used": 0,
        "qualification_score_rows_used": 0,
        "outer_rows_used": 0,
    }
    assert all((c["weight"] > 0) == (c["oos_stacking_advantage"] > 0)
               for c in summary["components"])
    assert abs(summary["e0_anchor_weight"] + sum(c["weight"] for c in summary["components"]) - 1) < 1e-12
    assert summary["prior_sealed_result_mutated"] is False
    assert summary["decision"] == "HOLD_RESEARCH_GATE"
    assert summary["research_gate_pass"] is False
    assert (output / "acceptance_summary.json").is_file()
    score_path = repo / summary["score_matrix_path"] if not Path(summary["score_matrix_path"]).is_absolute() else Path(summary["score_matrix_path"])
    assert score_path.is_file()
    assert summary["score_matrix_sha256"] == _sha256(score_path)
