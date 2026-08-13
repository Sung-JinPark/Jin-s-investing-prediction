from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_fc.multi_year_stress import (
    MultiYearStressError,
    build_multi_year_stress,
    validate_multi_year_stress,
)


ROOT = Path(__file__).resolve().parents[2]


def _cross_asset() -> dict:
    return json.loads(
        (ROOT / "data/cross_asset/cross_asset_latest.json").read_text(encoding="utf-8")
    )


def test_multi_year_stress_separates_observed_and_counterfactual_layers() -> None:
    payload = build_multi_year_stress(_cross_asset())
    validate_multi_year_stress(payload)
    assert payload["probability_space"] == "reference_only"
    assert payload["model_use"] is False
    assert payload["official_forecast_input"] is False
    assert payload["sample_frame"] == {
        "selection": "four named U.S. multi-year decline episodes requested for stress comparison",
        "n": 4,
        "exhaustive_base_rate": False,
        "universal_year_2_or_3_rule": False,
        "warning": "선택 사례 4개는 확률 표본이 아니며 2~3년차 낙폭 확대를 일반 법칙으로 만들지 않습니다.",
    }
    assert payload["dotcom_observed_assets"]["bitcoin"]["status"] == "not_available"
    assert payload["dotcom_observed_assets"]["nasdaq_price_index"][-1] < 40
    assert payload["dotcom_observed_assets"]["realty_income_total_return_proxy_index"][-1] > 200
    bitcoin = payload["ai_bust_counterfactual"]["bitcoin_sensitivity"]
    assert bitcoin["high"]["index"][-1] < bitcoin["center"]["index"][-1] < bitcoin["low"]["index"][-1]
    assert payload["ai_bust_counterfactual"]["beta_observations"] == 126


def test_multi_year_stress_rejects_bitcoin_as_observed() -> None:
    payload = build_multi_year_stress(_cross_asset())
    payload["dotcom_observed_assets"]["bitcoin"] = {"status": "ok", "values": [100, 80]}
    with pytest.raises(MultiYearStressError, match="must remain unavailable"):
        validate_multi_year_stress(payload)


def test_multi_year_stress_is_added_to_the_btc_realty_category() -> None:
    script = (ROOT / "src/ai_fc/dashboard_parts/dashboard.js").read_text(encoding="utf-8")
    contract = (ROOT / "data/contracts/multi_year_bubble_stress_v1.yaml").read_text(encoding="utf-8")
    assert "DATA.multi_year_stress?.presentation_html" in script
    payload = build_multi_year_stress(_cross_asset())
    assert "가정 스트레스 · 발생확률 아님" in payload["presentation_html"]
    assert "NASDAQ과 Realty Income 실측" in payload["presentation_html"]
    assert "universal_year_2_or_3_rule: false" in contract
    assert "stress paths must not feed Scenario V5.2" in contract
