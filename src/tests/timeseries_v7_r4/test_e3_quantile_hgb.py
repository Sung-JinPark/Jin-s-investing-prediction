from __future__ import annotations

import itertools

import pytest

from ai_fc.timeseries_v7_r4.e3_quantile_hgb import (
    E3Contract,
    fit_e3_quantile_hgb,
    repair_quantile_crossing,
)


def _rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index in range(48):
        x = (index - 24) / 12.0
        rows.append({
            "origin_session": f"2024-{index // 28 + 1:02d}-{index % 28 + 1:02d}",
            "available_at": f"2024-{index // 28 + 1:02d}-{index % 28 + 1:02d}T20:00:00Z",
            "features": [x, x * x],
            "targets": {str(h): x * h / 100.0 + (index % 4 - 1.5) / 100.0
                        for h in (1, 5, 21, 63)},
        })
    return rows


def test_e3_searches_exact_contract_coordinates_and_direct_quantiles() -> None:
    contract = E3Contract.from_mapping({
        "horizons": [1, 5, 21, 63], "quantiles": [0.1, 0.5, 0.9],
        "learning_rate": [0.03, 0.07], "max_leaf_nodes": [7],
        "max_iter": [20], "min_samples_leaf": [5],
        "l2_regularization": [0.0, 1.0], "min_training_rows": 24,
        "selection_fraction": 0.25,
    })
    model = fit_e3_quantile_hgb(
        rows=_rows(), as_of="2024-03-01T00:00:00Z", contract=contract,
    )

    expected = list(itertools.product((0.03, 0.07), (7,), (20,), (5,), (0.0, 1.0)))
    assert model.diagnostics["runtime_candidate_coordinates"] == expected
    assert model.diagnostics["contract_candidate_coordinates"] == expected
    assert model.diagnostics["quantile_estimation"] == {
        "0.1": "direct", "0.5": "direct", "0.9": "direct",
    }
    assert set(model.estimators) == {(h, q) for h in contract.horizons
                                    for q in contract.quantiles}


def test_e3_crossing_repair_is_deterministic_and_monotone() -> None:
    first = repair_quantile_crossing((0.1, 0.5, 0.9), (0.4, -0.2, 0.3))
    second = repair_quantile_crossing((0.1, 0.5, 0.9), (0.4, -0.2, 0.3))
    assert first == second == pytest.approx((0.1, 0.1, 0.3))
    assert list(first) == sorted(first)


def test_e3_excludes_post_as_of_rows() -> None:
    rows = _rows()
    rows.append({"origin_session": "2024-02-29", "available_at": "2025-01-01T00:00:00Z",
                 "features": [999.0, 999.0],
                 "targets": {str(h): 999.0 for h in (1, 5, 21, 63)}})
    model = fit_e3_quantile_hgb(
        rows=rows, as_of="2024-03-01T00:00:00Z",
        contract=E3Contract.from_mapping({
            "quantiles": [0.5], "learning_rate": [0.03], "max_leaf_nodes": [7],
            "max_iter": [10], "min_samples_leaf": [5], "l2_regularization": [0.0],
            "min_training_rows": 24,
        }),
    )
    assert model.diagnostics["excluded_post_as_of_rows"] == 1
