import pytest

from ai_fc.timeseries_v7_r4.learned_regime import fit_temporal_regimes


def _export(count=80):
    origins = [f"2020-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(count)]
    return {
        "source_store": "authoritative_postgresql",
        "five_role_plan": {
            "role_origins": {"calibration": origins},
            "role_hashes": {"calibration": "fixed"},
        },
        "feature_rows": [
            {
                "origin_session": origin,
                "origin_cutoff_at": origin + "T21:00:00+00:00",
                "max_available_at": origin + "T20:00:00+00:00",
                "pit_pass": True,
                "vix_level": float(i % 11),
                "rv_21": float((i * 3) % 13),
                "future_return": 999.0,
                "crisis_name": "forbidden",
            }
            for i, origin in enumerate(origins)
        ],
    }


def test_temporal_regimes_use_named_structural_pooling_weights():
    family = fit_temporal_regimes(
        _export(), 5, minimum_regime_count=60, minimum_train_size=20
    )
    assert family["fit_role"] == "calibration_temporal_cross_fit"
    assert family["state_available_at_origin"] is True
    assert family["filtered_feature_count"] == 2
    assert family["forbidden_prediction_features"] == []
    assert family["partial_pooling_applied"] is True
    assert set(family["pooling_weights"]) == set(family["declared_regimes"])
    assert all(0 < weight <= 1 for weight in family["pooling_weights"].values())
    assert any(weight < 1 for weight in family["pooling_weights"].values())
    assert all(sum(row.values()) == pytest.approx(1) for row in family["regime_probabilities"])


def test_temporal_regimes_reject_non_pit_and_non_postgresql_exports():
    export = _export()
    export["source_store"] = "sqlite"
    with pytest.raises(ValueError, match="PostgreSQL"):
        fit_temporal_regimes(export, 1, minimum_train_size=20)
    export = _export()
    export["feature_rows"][30]["max_available_at"] = "2099-01-01T00:00:00+00:00"
    with pytest.raises(ValueError, match="available_at"):
        fit_temporal_regimes(export, 1, minimum_train_size=20)
