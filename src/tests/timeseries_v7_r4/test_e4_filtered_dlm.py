from __future__ import annotations

import pytest

from ai_fc.timeseries_v7_r4.e4_filtered_dlm import E4Contract, fit_e4_filtered_dlm


def _rows() -> list[dict[str, object]]:
    rows = []
    for index in range(12):
        feature = 1.0 + index / 10.0
        rows.append({
            "origin_session": f"2024-01-{index + 1:02d}",
            "available_at": f"2024-01-{index + 2:02d}T00:00:00Z",
            "features": [feature],
            "targets": {str(h): feature * h / 100.0 for h in (1, 5, 21, 63)},
        })
    return rows


def test_e4_uses_transition_and_only_filtered_state() -> None:
    contract = E4Contract(
        state_transition=0.5, process_variance=0.001,
        observation_variance=0.01, initial_covariance=1.0,
        min_training_rows=4,
    )
    rows = _rows()
    baseline = fit_e4_filtered_dlm(rows=rows, as_of="2024-02-01T00:00:00Z", contract=contract)
    changed_future = _rows()
    changed_future[-1]["targets"] = {str(h): 999.0 for h in (1, 5, 21, 63)}
    rerun = fit_e4_filtered_dlm(
        rows=changed_future, as_of="2024-02-01T00:00:00Z", contract=contract,
    )

    # The receipt for an origin is produced from the transitioned prior before
    # its target update; changing that target cannot rewrite its own forecast.
    for horizon in contract.horizons:
        assert baseline.oos_receipts[-1]["forecasts"][str(horizon)] == pytest.approx(
            rerun.oos_receipts[-1]["forecasts"][str(horizon)]
        )
    assert baseline.diagnostics["state_estimate"] == "kalman_filtered_not_smoothed"
    assert baseline.diagnostics["state_transition"] == 0.5
    assert {receipt["horizon_sessions"] for receipt in baseline.direct_horizon_receipts} == {
        1, 5, 21, 63,
    }


def test_e4_excludes_post_as_of_and_requires_direct_targets() -> None:
    rows = _rows()
    rows.append({
        "origin_session": "2024-01-31", "available_at": "2025-01-01T00:00:00Z",
        "features": [999.0], "targets": {str(h): 999.0 for h in (1, 5, 21, 63)},
    })
    model = fit_e4_filtered_dlm(
        rows=rows, as_of="2024-02-01T00:00:00Z",
        contract=E4Contract(min_training_rows=4),
    )
    assert model.diagnostics["excluded_post_as_of_rows"] == 1
    assert len(model.direct_horizon_receipts) == len(_rows()) * 4

    del rows[0]["targets"]["21"]
    with pytest.raises(ValueError, match="direct target for horizon 21"):
        fit_e4_filtered_dlm(
            rows=rows, as_of="2024-02-01T00:00:00Z",
            contract=E4Contract(min_training_rows=4),
        )
