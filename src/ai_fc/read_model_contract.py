"""Additive dashboard read-model v2 contract without a runtime JSON Schema dependency."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


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
            "probability_space": {"const": "scenario_conditional"},
            "unit": {"const": "index_100"},
            "history": {"type": "object"},
            "forecast": {"type": "object"},
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
        if cross_asset.get("probability_space") != "scenario_conditional":
            errors.append("cross_asset probability_space must be scenario_conditional")
        if cross_asset.get("unit") != "index_100":
            errors.append("cross_asset unit must be index_100")
        if not isinstance(cross_asset.get("history"), dict):
            errors.append("cross_asset history must be an object")
        if not isinstance(cross_asset.get("forecast"), dict):
            errors.append("cross_asset forecast must be an object")
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
