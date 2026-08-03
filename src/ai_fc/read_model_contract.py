"""Additive dashboard read-model v2 contract without a runtime JSON Schema dependency."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .cross_asset import CrossAssetError, validate_cross_asset
from .ai_capital_cycle import validate_ai_regime
from .market_extensions import (
    MarketExtensionError,
    validate_liquidity,
    validate_scenario_tracker,
)


LEGACY_KEYS = {
    "meta": dict,
    "scenario": dict,
    "scenario_history": list,
    "questions": list,
    "forecast_history": dict,
    "resolutions": dict,
    "ml_runs": list,
    "market_runs": list,
    "calibration": dict,
    "due": list,
}

V2_KEYS = {
    "trust": dict,
    "arena": list,
    "receipts": list,
    "asof_index": list,
    "clusters": list,
    "corrections": list,
    "probability_semantics": dict,
    "changelog": list,
    "era_analog": dict,
    "cross_asset": dict,
    "scenario_tracker": dict,
    "liquidity": dict,
    "ai_regime": dict,
}


def schema() -> dict[str, Any]:
    types = {dict: "object", list: "array"}
    properties = {
        key: {"type": types[value_type]}
        for key, value_type in {**LEGACY_KEYS, **V2_KEYS}.items()
    }
    properties["era_analog"] = {
        "type": "object",
        "required": ["status", "probability_space", "unit", "series"],
        "properties": {
            "status": {"enum": ["ok", "empty", "blocked"]},
            "probability_space": {"const": "reference_only"},
            "unit": {"const": "log10(index/100)"},
            "series": {"type": "array"},
        },
    }
    properties["cross_asset"] = {
        "type": "object",
        "required": ["probability_space", "unit", "history", "forecast"],
        "properties": {
            "status": {"enum": ["ok", "blocked"]},
            "probability_space": {"const": "scenario_conditional"},
            "unit": {"const": "index_100"},
            "history": {"type": "object"},
            "forecast": {"type": "object"},
        },
    }
    for key in ("scenario_tracker", "liquidity", "ai_regime"):
        properties[key] = {
            "type": "object",
            "required": ["status", "probability_space"],
            "properties": {
                "status": {"type": "string"},
                "probability_space": {"const": "reference_only"},
                "asof": {"type": ["string", "null"]},
            },
        }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://jin-investing.local/schemas/read-model-v2.json",
        "title": "Jin's Investing Prediction read-model v2",
        "type": "object",
        "required": list(LEGACY_KEYS) + list(V2_KEYS),
        "properties": properties,
        "additionalProperties": True,
    }


def validate(model: dict[str, Any]) -> list[str]:
    errors = []
    for key, value_type in {**LEGACY_KEYS, **V2_KEYS}.items():
        if key not in model:
            errors.append(f"missing read-model key: {key}")
        elif not isinstance(model[key], value_type):
            errors.append(
                f"read-model key {key} must be {value_type.__name__}, "
                f"got {type(model[key]).__name__}"
            )
    era = model.get("era_analog")
    if isinstance(era, dict):
        if era.get("probability_space") != "reference_only":
            errors.append("era_analog probability_space must be reference_only")
        if era.get("unit") != "log10(index/100)":
            errors.append("era_analog unit must be log10(index/100)")
        if not isinstance(era.get("series"), list):
            errors.append("era_analog series must be a list")
    cross_asset = model.get("cross_asset")
    if isinstance(cross_asset, dict):
        if cross_asset.get("status") != "blocked":
            try:
                validate_cross_asset(cross_asset)
            except (CrossAssetError, TypeError, ValueError) as exc:
                errors.append(f"cross_asset contract violation: {exc}")
    reference_validators = {
        "scenario_tracker": validate_scenario_tracker,
        "liquidity": validate_liquidity,
        "ai_regime": validate_ai_regime,
    }
    for key, validator in reference_validators.items():
        payload = model.get(key)
        if not isinstance(payload, dict):
            continue
        if payload.get("probability_space") != "reference_only":
            errors.append(f"{key} probability_space must be reference_only")
            continue
        if payload.get("status") == "blocked":
            continue
        try:
            validator(payload)
        except (MarketExtensionError, KeyError, TypeError, ValueError) as exc:
            errors.append(f"{key} contract violation: {exc}")
    return errors


def assert_valid(model: dict[str, Any]) -> None:
    errors = validate(model)
    if errors:
        raise ValueError("; ".join(errors))


def write_schema(root: Path) -> Path:
    target = root / "docs" / "generated" / "read_model_v2.schema.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(schema(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return target
