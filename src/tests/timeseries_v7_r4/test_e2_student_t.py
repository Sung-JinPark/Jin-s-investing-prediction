from __future__ import annotations

import numpy as np
import pytest

from ai_fc.timeseries_v7_r4.e2_student_t import (
    E2Contract, _cross_fitted_residuals, fit_e2_student_t,
)


def _rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index in range(36):
        x = (index - 18) / 9.0
        noise = (0.02 + 0.025 * abs(x)) * ((index % 5) - 2)
        rows.append({
            "origin_session": f"2025-{index // 28 + 1:02d}-{index % 28 + 1:02d}",
            "available_at": f"2025-{index // 28 + 1:02d}-{index % 28 + 1:02d}T20:00:00Z",
            "features": [x, x * x],
            "targets": {str(h): 0.03 * x + noise * h ** 0.5 for h in (1, 5, 21, 63)},
        })
    return rows


def test_e2_uses_contract_grid_and_joint_student_t_likelihood() -> None:
    contract = E2Contract.from_mapping({
        "horizons": [1, 5, 21, 63], "degrees_of_freedom": [3, 8],
        "alpha_grid": [0.01, 0.1], "cross_fit_folds": 4, "min_training_rows": 20,
    })
    model = fit_e2_student_t(
        rows=_rows(), as_of="2025-03-01T00:00:00Z", contract=contract,
    )

    assert model.diagnostics["searched_grid"] == {
        "degrees_of_freedom": [3.0, 8.0], "alpha": [0.01, 0.1],
    }
    assert model.diagnostics["objective"] == (
        "student_t_nll_plus_horizon_crps_plus_stability_penalty"
    )
    assert set(model.location_coefficients) == {1, 5, 21, 63}
    assert all(model.predict([0.2, 0.04])[h]["scale"] > 0 for h in model.horizons)


def test_e2_scale_initialization_uses_only_cross_fitted_residuals() -> None:
    model = fit_e2_student_t(
        rows=_rows(), as_of="2025-03-01T00:00:00Z",
        contract=E2Contract.from_mapping({"cross_fit_folds": 3, "min_training_rows": 20}),
    )

    evidence = model.diagnostics["scale_residual_evidence"]
    assert evidence["kind"] == "cross_fitted"
    assert evidence["folds"] == 3
    assert evidence["row_count"] == (36 - 20) * 4
    assert evidence["temporal_scheme"] == "expanding"
    assert len(evidence["sha256"]) == 64


def test_e2_preserves_point_in_time_and_rejects_invalid_contract() -> None:
    rows = _rows() + [{
        "origin_session": "2025-03-02", "available_at": "2025-03-02T20:00:00Z",
        "features": [999.0, 999.0], "targets": {str(h): 999.0 for h in (1, 5, 21, 63)},
    }]
    model = fit_e2_student_t(
        rows=rows, as_of="2025-03-01T00:00:00Z", contract=E2Contract(),
    )
    assert model.diagnostics["excluded_post_as_of_rows"] == 1
    with pytest.raises(ValueError, match="degrees_of_freedom"):
        E2Contract.from_mapping({"degrees_of_freedom": [2]})


def test_e2_cross_fit_is_expanding_and_never_trains_on_future_rows() -> None:
    design = np.column_stack((np.ones(30), np.arange(30, dtype=float)))
    target = np.r_[np.arange(20, dtype=float), np.arange(10, dtype=float) + 1000.0]
    residuals = _cross_fitted_residuals(design, target, folds=3, alpha=0.0,
                                        min_training_rows=8)

    # A future regime shift cannot alter residuals generated for earlier validation rows.
    baseline = _cross_fitted_residuals(design, np.arange(30, dtype=float), folds=3,
                                       alpha=0.0, min_training_rows=8)
    assert residuals[8:20] == pytest.approx(baseline[8:20])
    assert np.isnan(residuals[:8]).all()


def test_e2_objective_includes_contract_crps_and_stability_penalty() -> None:
    contract = E2Contract.from_mapping({
        "crps_weight": 0.4, "stability_weight": 0.2,
        "cross_fit_folds": 3, "min_training_rows": 20,
    })
    model = fit_e2_student_t(rows=_rows(), as_of="2025-03-01T00:00:00Z",
                             contract=contract)

    assert model.diagnostics["objective"] == (
        "student_t_nll_plus_horizon_crps_plus_stability_penalty"
    )
    assert model.diagnostics["objective_weights"] == {
        "crps": 0.4, "stability": 0.2,
    }
    assert set(model.diagnostics["selected_crps"]) == {1, 5, 21, 63}
