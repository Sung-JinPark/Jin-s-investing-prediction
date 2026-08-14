from __future__ import annotations

import json
import re
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
    assert payload["dotcom_observed_assets"]["nasdaq_price_index"][-1] < 60
    assert payload["dotcom_observed_assets"]["realty_income_total_return_proxy_index"][-1] > 350
    bitcoin = payload["ai_bust_counterfactual"]["bitcoin_sensitivity"]
    assert bitcoin["high"]["index"][-1] < bitcoin["center"]["index"][-1] < bitcoin["low"]["index"][-1]
    assert payload["ai_bust_counterfactual"]["beta_observations"] == 126
    assert payload["historical_stress_composite"] == {
        "labels": ["시작", "1년", "2년", "3년", "4년", "5년"],
        "center_index": [100.0, 91.3, 74.2, 69.4, 85.9, 94.4],
        "q25_index": [100.0, 89.6, 67.3, 55.4, 65.4, 78.1],
        "q75_index": [100.0, 93.4, 82.2, 79.4, 95.6, 103.7],
        "observations_by_horizon": [4, 4, 4, 4, 4, 4],
        "method": "pointwise_median_and_linear_interquartile_quantiles_in_log_index_space",
    }
    assert payload["ai_bust_counterfactual"]["us_equity_stress_reference_index"] == [
        100.0, 91.3, 74.2, 69.4, 85.9, 94.4,
    ]
    rotation = payload["ai_bust_counterfactual"]["bitcoin_liquidity_rotation_assumption"]
    assert rotation["transfer_share"] == .35
    assert rotation["center_index"] == [100.0, 105.2, 118.2, 122.7, 122.7, 122.7]
    assert rotation["semantics"] == "user_directed_counterfactual_not_observed_not_estimated_not_probability"


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
    assert "역사 낙폭 범위와 BTC 조건부 경로" in payload["presentation_html"]
    assert payload["presentation_html"].count("<svg") == 2
    domains = re.findall(r'data-domain="([^"]+)"', payload["presentation_html"])
    assert len(domains) == 2
    assert len(set(domains)) == 1
    assert "선택 사례 4개 25~75% 범위" in payload["presentation_html"]
    assert "BTC 이동비중 15~50% 가정 범위" in payload["presentation_html"]
    assert "Realty Income" not in payload["presentation_html"]
    assert payload["dotcom_observed_assets"]["realty_income_total_return_proxy_index"][-1] > 350
    assert "universal_year_2_or_3_rule: false" in contract
    assert "stress paths must not feed Scenario V5.2" in contract
    assert "two adjacent panels" in contract
    assert "same log-scale value domain" in contract
    assert "stay out of the multi-year stress chart" in contract
