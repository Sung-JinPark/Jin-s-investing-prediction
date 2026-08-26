import pytest
import json

from ai_fc.timeseries_v7_r4.g1_candidate_funnel import screen_g1_candidates
from ai_fc.timeseries_v7_r4.g1_candidate_funnel import run_g1_screen_from_export


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

    def fake_execute(family, train_rows, score_rows, as_of):
        seen.append(family)
        assert all(row["available_at"] <= as_of for row in train_rows)
        return 0.02 + len(seen) / 1000, len(score_rows) * 4

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
    assert report["five_role_validation_proof"] is True
