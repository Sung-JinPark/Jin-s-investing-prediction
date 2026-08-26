import pytest
import json

from ai_fc.timeseries_v7_r4.g1_candidate_funnel import screen_g1_candidates
from ai_fc.timeseries_v7_r4.g1_candidate_funnel import run_g1_screen_from_export
from ai_fc.timeseries_v7_r4.g1_candidate_funnel import _quantile_crps


def _candidate(name, score, *, exposure=None):
    return {
        "candidate_id": name,
        "hypothesis": {"model": name, "mechanism": "direct_horizon"},
        "exposure": exposure or {"features": ["returns"], "horizons": [1, 5, 21, 63]},
        "smoke_crps": score,
        "inner_crps": score,
        "robust_inner_crps": score,
        "full_nested_crps": score,
    }


def test_bounded_funnel_zeroes_underperformers_and_records_lineage_hashes():
    candidates = [_candidate("good", .08), _candidate("bad", .12)]

    report = screen_g1_candidates(
        candidates,
        e0_crps=.10,
        budgets={"smoke": 2, "inner_screen": 2, "robust_inner": 1,
                 "full_nested": 1, "qualification": 1},
        generation_hash="a" * 64,
    )

    assert report["candidate_counts"] == {
        "smoke": 2, "inner_screen": 2, "robust_inner": 1,
        "full_nested": 1, "qualification": 1,
    }
    rows = {row["candidate_id"]: row for row in report["candidates"]}
    assert rows["bad"]["weight"] == 0.0
    assert rows["good"]["weight"] > 0.0
    assert len(rows["good"]["hypothesis_hash"]) == 64
    assert len(rows["good"]["exposure_hash"]) == 64


def test_funnel_rejects_budget_over_contract_and_nonfinite_scores():
    with pytest.raises(ValueError, match="funnel budget"):
        screen_g1_candidates([], e0_crps=.1,
                             budgets={"smoke": 161}, generation_hash="a" * 64)
    with pytest.raises(ValueError, match="finite"):
        screen_g1_candidates([_candidate("bad", float("nan"))], e0_crps=.1,
                             generation_hash="a" * 64)


def test_export_screen_executes_every_r4_family_and_never_exposes_outer(tmp_path, monkeypatch):
    snapshot = {
        "schema": "r4_credential_free_pit_export_v1",
        "source_store": "authoritative_postgresql", "snapshot_hash": "c" * 64,
        "as_of": "2026-01-10T00:00:00+00:00", "calendar_version": "xnas-v1",
        "five_role_plan": {
            "schema": "r4_five_role_origin_plan_v1", "plan_hash": "b" * 64,
            "role_order": ["train", "selection", "stacking", "calibration", "outer"],
            "role_counts": {"train": 4, "selection": 2, "stacking": 1,
                            "calibration": 1, "outer": 0},
            "role_hashes": {role: role[0] * 64 for role in
                            ("train", "selection", "stacking", "calibration", "outer")},
            "role_origins": {
                "train": [f"2026-01-{day:02d}" for day in range(1, 5)],
                "selection": ["2026-01-05", "2026-01-06"],
                "stacking": ["2026-01-07"], "calibration": ["2026-01-08"],
                "outer": [],
            },
            "outer_exposed_during_screen": False,
            "excluded_count": 1,
            "interval_overlap_count": 0,
            "purge_unit": "xnas_sessions",
            "purge_sessions": 63,
            "embargo_sessions": 5,
        },
        "feature_rows": [
            {"origin_session": f"2026-01-{day:02d}",
             "origin_cutoff_at": f"2026-01-{day:02d}T00:00:00+00:00",
             "max_available_at": f"2026-01-{day:02d}T00:00:00+00:00",
             "pit_pass": True,
             **{name: float(day) for name in (
                 "ret_1", "momentum_5", "momentum_21", "momentum_63", "rv_5",
                 "rv_21", "rv_63", "vix_level", "term_level", "dff_level",
             )}} for day in range(1, 9)
        ],
        "labels": [
            {"origin_session": f"2026-01-{day:02d}", "horizon_sessions": horizon,
             "mature_at": f"2026-01-{day:02d}T12:00:00+00:00", "value": day / 1000}
            for day in range(1, 9) for horizon in (1, 5, 21, 63)
        ],
    }
    source = tmp_path / "snapshot.json"
    source.write_text(json.dumps(snapshot), encoding="utf-8")
    seen = []

    def fake_execute(family, train_rows, score_rows_by_role, as_of):
        seen.append(family)
        assert all(row["available_at"] <= as_of for row in train_rows)
        assert len(train_rows) == 4
        counts = {role: len(rows) * 4 for role, rows in score_rows_by_role.items()}
        return ({role: 0.02 + len(seen) / 1000 for role in score_rows_by_role},
                counts,
                {"score": "distribution_crps", "frozen_coordinates": True,
                 "optimizer_convergence": {"enforced": True, "method": "test"},
                 "predictive_distribution_hash": family[0].lower() * 64,
                 "score_rows": sum(counts.values())})

    monkeypatch.setattr(
        "ai_fc.timeseries_v7_r4.g1_candidate_funnel._execute_family", fake_execute,
    )
    report = run_g1_screen_from_export(
        source, e0_crps=.03, e0_artifact_sha256="e" * 64,
        evaluation_origin_grid_hash="f" * 64, generation_hash="a" * 64,
    )

    assert seen == ["E1", "E2", "E3", "E4"]
    assert report["candidate_families"] == ["E1", "E2", "E3", "E4"]
    assert report["source"]["outer_rows_used"] == 0
    assert report["source"]["legacy_precomputed_score_rows_used"] == 0
    assert report["five_role_receipt"]["plan_hash"] == "b" * 64
    assert report["five_role_receipt"]["role_counts"]["train"] == 4
    assert report["five_role_receipt"]["excluded_count"] == 1
    assert report["five_role_receipt"]["interval_overlap_count"] == 0
    assert report["five_role_receipt"]["purge_unit"] == "xnas_sessions"
    assert report["source"]["five_role_receipt"] == report["five_role_receipt"]
    assert report["source"]["score_metric"] == "distribution_crps"
    assert report["source"]["e0_mean_crps"] == pytest.approx(0.03)
    assert report["source"]["frozen_candidate_coordinates_preserved"] is True
    assert report["source"]["optimizer_convergence_required"] is True
    assert {item["family"] for item in report["score_receipts"]} == {
        "E1", "E2", "E3", "E4",
    }
    assert all(item["metric"] == "crps" for item in report["score_receipts"])
    assert all(len(item["predictive_distribution_hash"]) == 64
               for item in report["score_receipts"])
    assert all(item["score_rows"] > 0 for item in report["score_receipts"])
    assert report["source"]["train_rows"] == 4
    assert all(row["score_kind"] == "distribution_crps"
               for row in report["candidates"])


def test_quantile_crps_uses_the_stored_distribution_not_only_the_median():
    narrow = _quantile_crps(0.0, {0.1: -0.1, 0.5: 0.0, 0.9: 0.1})
    wide = _quantile_crps(0.0, {0.1: -1.0, 0.5: 0.0, 0.9: 1.0})

    assert narrow > 0.0
    assert wide > narrow
