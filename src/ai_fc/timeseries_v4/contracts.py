"""V4 preregistration and immutable predecessor guards."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml


MODEL_ID = "shadow.nasdaq_pit_market_event_distribution_v4"
MODEL_VERSION = 4
CONTRACT_RELATIVE = Path("data/contracts/multivariate_timeseries_v4.yaml")


class V4ContractError(RuntimeError):
    """The V4 preregistration contract was violated."""


def canonical_hash(value: Any) -> str:
    def normalize(item: Any) -> Any:
        if isinstance(item, (date, datetime)):
            return item.isoformat()
        if isinstance(item, dict):
            return {str(key): normalize(child) for key, child in item.items()}
        if isinstance(item, (list, tuple)):
            return [normalize(child) for child in item]
        if hasattr(item, "item"):
            return item.item()
        return item

    return hashlib.sha256(
        json.dumps(normalize(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def load_v4_contract(root: Path) -> dict[str, Any]:
    payload = yaml.safe_load((root / CONTRACT_RELATIVE).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise V4ContractError("V4 contract must be a mapping")
    if payload.get("model_id") != MODEL_ID or payload.get("model_version") != MODEL_VERSION:
        raise V4ContractError("unexpected V4 identity")
    probability = payload.get("probability_contract", {})
    if probability.get("stored_unit") != "fraction" or probability.get("bounds") != [0.0, 1.0]:
        raise V4ContractError("V4 probability contract drifted")
    if probability.get("combine_with_official_forecasts") is not False:
        raise V4ContractError("V4 cannot combine with official forecasts")
    if probability.get("combine_with_scenario_v5_2") is not False:
        raise V4ContractError("V4 cannot combine with Scenario V5.2")
    if float(payload["research_gate"]["long_horizon_mean_crps_improvement_min"]) != 0.02:
        raise V4ContractError("V4 research gate was lowered")
    calibrator = payload.get("distributional_calibrator", {})
    if calibrator.get("predecessor_replay_required") is not True:
        raise V4ContractError("V4 must replay its predecessor distribution")
    if calibrator.get("anomaly_thresholds") != [0.80, 0.95]:
        raise V4ContractError("V4 anomaly thresholds drifted")
    if calibrator.get("centered_scale_by_band") != [0.85, 1.10, 1.60]:
        raise V4ContractError("V4 distribution scales drifted")
    if int(calibrator.get("captured_event_minimum", 0)) != 60:
        raise V4ContractError("V4 event-history minimum drifted")
    required = {
        "mutate_v1_v2_v3", "lower_gate", "row_wise_oracle", "future_actual",
        "silent_imputation", "official_forecast_write", "automatic_investment_execution",
    }
    if not all(payload.get("prohibitions", {}).get(key) is True for key in required):
        raise V4ContractError("a V4 model-risk prohibition was removed")
    return payload


def contract_hash(root: Path) -> str:
    return canonical_hash(load_v4_contract(root))
