from __future__ import annotations

import json

from ai_fc.timeseries_v7_r4.stacking_calibration_generation import generate_stacking_calibration


def test_generation_uses_disjoint_roles_and_keeps_only_compact_hashes(tmp_path):
    origins = [f"2026-01-{day:02d}" for day in range(1, 9)]
    labels = [
        {"origin_session": origin, "horizon_sessions": 1,
         "label_end_session": origin, "mature_at": origin + "T00:00:00Z",
         "value": index / 100.0}
        for index, origin in enumerate(origins)
    ]
    export = {
        "schema": "r4_credential_free_pit_export_v1",
        "source_store": "authoritative_postgresql",
        "snapshot_hash": "a" * 64,
        "labels": labels,
        "five_role_plan": {
            "role_counts": {"train": 2, "selection": 1, "stacking": 2,
                            "calibration": 2, "outer": 1},
            "role_hashes": {role: role[0] * 64 for role in
                            ("train", "selection", "stacking", "calibration", "outer")},
            "role_origins": {"train": origins[:2], "selection": origins[2:3],
                             "stacking": origins[3:5], "calibration": origins[5:7],
                             "outer": origins[7:]},
            "outer_exposed_during_screen": False,
        },
    }
    export_path = tmp_path / "export.json"
    export_path.write_text(json.dumps(export))
    g1_path = tmp_path / "g1.json"
    g1_path.write_text(json.dumps({
        "candidates": [{"candidate_id": family, "weight": 0.0}
                       for family in ("E1", "E2", "E3", "E4")],
        "five_role_receipt": export["five_role_plan"],
    }))

    result = generate_stacking_calibration(
        export_path, g1_path=g1_path, e0_artifact_sha256="b" * 64,
        e0_mean_crps=0.0187453537909802, horizons=(1,),
        checkpoint_dir=tmp_path / "checkpoints",
    )

    row = result["horizons"]["1"]
    assert row["weights"] == {"E0": 1.0, "E1": 0.0, "E2": 0.0, "E3": 0.0, "E4": 0.0}
    assert row["weight_fit_role"] == "stacking"
    assert row["calibration_fit_role"] == "calibration"
    assert row["cross_fit_calibration_applied"] is True
    assert row["stacking_crps"] <= row["stacking_e0_crps"] + 1e-12
    assert len(row["sample_set_hash"]) == 64
    encoded = json.dumps(result)
    assert "predictive_samples" not in encoded
    assert '"values"' not in encoded
    assert result["outer_rows_used"] == 0
