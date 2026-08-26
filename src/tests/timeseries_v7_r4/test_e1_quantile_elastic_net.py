from __future__ import annotations

import numpy as np
import pytest

from ai_fc.timeseries_v7_r4.e1_quantile_elastic_net import (
    E1Contract,
    fit_e1_direct_quantile_elastic_net,
)


def _rows() -> list[dict[str, object]]:
    rows = []
    for index in range(24):
        x = float(index - 12) / 12.0
        rows.append({
            "origin_session": f"2025-01-{index + 1:02d}",
            "available_at": f"2025-01-{index + 1:02d}T20:00:00Z",
            "features": [x, x * x],
            "targets": {str(h): x * h / 100.0 for h in (1, 5, 21, 63)},
        })
    return rows


def test_e1_fits_direct_contract_horizons_and_quantiles() -> None:
    contract = E1Contract.from_mapping({
        "horizons": [1, 5, 21, 63], "quantiles": [0.1, 0.5, 0.9],
        "alpha": 0.002, "l1_ratio": 0.6, "correction_bound_k": 0.75,
        "stability_subsamples": 4, "stability_min_sign_agreement": 0.5,
        "min_training_rows": 12,
    })
    model = fit_e1_direct_quantile_elastic_net(
        rows=_rows(), as_of="2025-02-01T00:00:00Z", e0_scale=0.2,
        contract=contract,
    )

    assert model.horizons == (1, 5, 21, 63)
    assert model.quantiles == (0.1, 0.5, 0.9)
    assert set(model.coefficients) == {(h, q) for h in model.horizons for q in model.quantiles}
    assert model.diagnostics["hyperparameters"]["alpha"] == 0.002


def test_e1_correction_is_bounded_and_reports_stability() -> None:
    contract = E1Contract.from_mapping({
        "horizons": [1, 5, 21, 63], "quantiles": [0.5], "alpha": 0.001,
        "l1_ratio": 0.5, "correction_bound_k": 0.25,
        "stability_subsamples": 3, "stability_min_sign_agreement": 0.4,
        "min_training_rows": 12,
    })
    model = fit_e1_direct_quantile_elastic_net(
        rows=_rows(), as_of="2025-02-01T00:00:00Z", e0_scale=0.08,
        contract=contract,
    )
    prediction = model.predict_corrections([100.0, 10000.0])
    assert abs(prediction[1][0.5]) <= 0.02
    assert model.diagnostics["correction_bound"] == pytest.approx(0.02)
    assert 0.0 <= model.diagnostics["minimum_sign_agreement"] <= 1.0
    assert isinstance(model.diagnostics["stable"], bool)


def test_e1_rejects_post_as_of_rows_instead_of_leaking_them() -> None:
    rows = _rows()
    rows.append({
        "origin_session": "2025-01-31", "available_at": "2025-03-01T00:00:00Z",
        "features": [999.0, 999.0], "targets": {str(h): 999.0 for h in (1, 5, 21, 63)},
    })
    model = fit_e1_direct_quantile_elastic_net(
        rows=rows, as_of="2025-02-01T00:00:00Z", e0_scale=0.1,
        contract=E1Contract.from_mapping({"horizons": [1, 5, 21, 63]}),
    )
    assert model.diagnostics["eligible_rows"] == 24
    assert model.diagnostics["excluded_post_as_of_rows"] == 1


def test_e1_contract_requires_canonical_direct_targets() -> None:
    with pytest.raises(ValueError, match="exactly 1, 5, 21, 63"):
        E1Contract.from_mapping({"horizons": [1, 5, 21]})
