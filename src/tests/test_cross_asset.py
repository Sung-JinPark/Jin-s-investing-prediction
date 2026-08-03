from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest

from ai_fc.cross_asset import CrossAssetError, build_cross_asset, validate_cross_asset


def _months(start_year: int, start_month: int, count: int) -> list[date]:
    out = []
    for offset in range(count):
        total = start_year * 12 + start_month - 1 + offset
        out.append(date(total // 12, total % 12 + 1, 1))
    return out


def _price_path(count: int, drift: float, wave: float) -> list[float]:
    returns = drift + wave * np.sin(np.arange(count - 1) / 9)
    return [100.0, *list(100 * np.exp(np.cumsum(returns)))]


def _fixture() -> dict:
    history_dates = _months(2000, 12, 61)
    current_dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(320)]
    nasdaq = _price_path(320, 0.0004, 0.009)
    bitcoin = _price_path(320, 0.0007, 0.016)
    realty = _price_path(320, 0.00025, 0.004)
    return build_cross_asset(
        history_dates=history_dates,
        history_nasdaq=list(np.linspace(100, 72, 61)),
        history_o_price=list(np.linspace(100, 180, 61)),
        history_o_adjusted=list(np.linspace(100, 245, 61)),
        current_dates=current_dates,
        current_nasdaq=nasdaq,
        current_bitcoin=bitcoin,
        current_o_adjusted=realty,
        anchors={"nasdaq": 25000, "bitcoin": 65000, "realty_income": 60},
        generated_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
    )


def test_cross_asset_keeps_history_and_conditional_paths_separate() -> None:
    model = _fixture()
    assert model["probability_space"] == "scenario_conditional"
    assert model["history"]["bitcoin"]["status"] == "not_available"
    assert model["history"]["summary"]["nasdaq_price_pct"] == pytest.approx(-28.0)
    assert model["history"]["summary"]["realty_income_total_return_pct"] == pytest.approx(145.0)
    assert model["forecast"]["weights"]["status"] == "not_estimated"
    assert set(model["forecast"]["scenarios"]) == {
        "deleveraging", "easing_rotation", "soft_landing"
    }
    assert all(
        len(path) == 13
        for scenario in model["forecast"]["scenarios"].values()
        for path in scenario["paths"].values()
    )


def test_easing_rotation_allows_divergence_after_initial_shock() -> None:
    paths = _fixture()["forecast"]["scenarios"]["easing_rotation"]["paths"]
    assert paths["bitcoin"][3] < 100
    assert paths["bitcoin"][-1] > paths["nasdaq"][-1]
    assert paths["realty_income"][-1] > 100


def test_cross_asset_validator_rejects_path_length_drift() -> None:
    model = _fixture()
    model["forecast"]["scenarios"]["soft_landing"]["paths"]["bitcoin"].pop()
    with pytest.raises(CrossAssetError, match="length"):
        validate_cross_asset(model)
