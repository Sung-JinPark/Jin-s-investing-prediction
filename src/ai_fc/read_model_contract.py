"""Additive dashboard read-model v2 contract without a runtime JSON Schema dependency."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .cross_asset import CrossAssetError, validate_cross_asset
from .ai_capital_cycle import validate_ai_regime
from .scenario import ScenarioError, validate_scenario
from .scenario_v4_shadow import ScenarioV4ShadowError, validate_shadow_payload
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
    "o_entry_cohort": dict,
    "method_changes": list,
    "calendar_events": list,
    "scenario_v5": dict,
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
            "series": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["id", "overlay_start", "model_anchor"],
                    "properties": {
                        "id": {"type": "string"},
                        "overlay_start": {"type": "string"},
                        "model_anchor": {"type": "string"},
                    },
                },
            },
        },
    }
    properties["cross_asset"] = {
        "type": "object",
        "required": ["probability_space", "unit", "history", "forecast"],
        "properties": {
            "status": {"enum": ["ok", "blocked"]},
            "probability_space": {"enum": ["scenario_conditional", "reference_only"]},
            "unit": {"const": "index_100"},
            "history": {"type": "object"},
            "forecast": {"type": "object"},
        },
    }
    properties["scenario"] = {
        "type": "object",
        "required": ["schema_version", "asof", "quantile_table", "horizon_coverage"],
        "properties": {
            "schema_version": {"enum": [2, 3]},
            "quantile_table": {
                "type": "object",
                "required": [
                    "probability_space", "basis", "trading_days", "quantiles",
                    "prob_above_anchor", "prob_above_ath", "per_scenario_p50",
                ],
                "properties": {
                    "probability_space": {"const": "scenario_conditional"},
                    "probability_label": {"const": "model_conditional"},
                },
            },
            "horizon_coverage": {
                "type": "object",
                "required": ["status", "basis", "gate", "buckets"],
                "properties": {"buckets": {"type": "array"}},
            },
        },
    }
    properties["scenario_v5"] = {
        "type": "object",
        "required": ["schema_version", "status", "candidate_id"],
        "properties": {
            "schema_version": {"const": 1},
            "status": {"enum": ["ok", "degraded", "unavailable"]},
            "candidate_id": {
                "const": "scenario_v5_evidence_conditioned_legacy_prior_v1"
            },
        },
    }
    properties["scenario_v4_shadow"] = {
        "type": ["object", "null"],
        "properties": {
            "version": {"const": "rcfhs-sb-v1"},
            "status": {"const": "shadow_only"},
            "dashboard_toggle_default": {"const": "off"},
            "promotion_state": {"const": "blocked_pending_rolling_origin_validation"},
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
    properties["o_entry_cohort"] = {
        "type": "object",
        "required": ["status", "probability_space", "entry_state_rules_registered"],
        "properties": {
            "status": {"enum": ["ok", "blocked"]},
            "probability_space": {"const": "reference_only"},
            "entry_state_rules_registered": {"const": False},
        },
    }
    properties["calendar_events"] = {
        "type": "array",
        "items": {
            "type": "object",
            "required": [
                "event_id", "kind", "date", "status", "title", "source_url"
            ],
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
        else:
            for row in era["series"]:
                if not isinstance(row, dict):
                    continue
                if not row.get("overlay_start") or not row.get("model_anchor"):
                    errors.append(
                        "era_analog series must consume overlay_start and model_anchor")
                    break
    cross_asset = model.get("cross_asset")
    if isinstance(cross_asset, dict):
        if cross_asset.get("status") != "blocked":
            try:
                validate_cross_asset(cross_asset)
            except (CrossAssetError, TypeError, ValueError) as exc:
                errors.append(f"cross_asset contract violation: {exc}")
    scenario = model.get("scenario")
    if isinstance(scenario, dict):
        try:
            validate_scenario(scenario)
        except (ScenarioError, KeyError, TypeError, ValueError) as exc:
            errors.append(f"scenario contract violation: {exc}")
        coverage = scenario.get("horizon_coverage")
        if not isinstance(coverage, dict) or not isinstance(coverage.get("buckets"), list):
            errors.append("scenario horizon_coverage must contain buckets")
        else:
            for bucket in coverage["buckets"]:
                observations = bucket.get("observations")
                minimum = bucket.get("minimum_observations")
                rate = bucket.get("inside_p10_p90_rate_pct")
                if not isinstance(observations, int) or not isinstance(minimum, int):
                    errors.append("horizon_coverage observations and gate must be integers")
                    break
                if observations < minimum and rate is not None:
                    errors.append("horizon_coverage must hide hit rates below the gate")
                    break
    scenario_v5 = model.get("scenario_v5")
    if isinstance(scenario_v5, dict) and scenario_v5.get("status") in {"ok", "degraded"}:
        if scenario_v5.get("banner") != "RESEARCH CANDIDATE - NOT OFFICIAL - NOT CHAMPION":
            errors.append("scenario_v5 research-candidate banner is required")
        identity = scenario_v5.get("identity") or {}
        if identity.get("prior_engine") != "legacy_gbm_reproduced_v1":
            errors.append("scenario_v5 must disclose the legacy reproduced prior")
        if identity.get("is_rcfhs") is not False:
            errors.append("scenario_v5 cannot claim RCFHS")
        conditional = scenario_v5.get("conditional_distribution") or {}
        scenarios = conditional.get("scenarios") or {}
        probabilities = [
            scenarios.get(key, {}).get("probability") for key in ("S1", "S2", "S3")
        ]
        if (not all(isinstance(value, (int, float)) and 0 <= value <= 1
                    for value in probabilities)
                or abs(sum(probabilities) - 1.0) > 1e-10):
            errors.append("scenario_v5 probabilities must be fractions summing to one")
        same_shape = conditional.get("same_shape_diagnostics") or {}
        if (conditional.get("representative_lines_visible")
                is not bool(same_shape.get("gate_pass"))):
            errors.append("scenario_v5 same-shape visibility gate mismatch")
    scenario_v4_shadow = model.get("scenario_v4_shadow")
    if scenario_v4_shadow is not None:
        if not isinstance(scenario_v4_shadow, dict):
            errors.append("scenario_v4_shadow must be an object or null")
        else:
            try:
                validate_shadow_payload(scenario_v4_shadow)
            except (ScenarioV4ShadowError, KeyError, TypeError, ValueError) as exc:
                errors.append(f"scenario_v4_shadow contract violation: {exc}")
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
    cohort = model.get("o_entry_cohort")
    if isinstance(cohort, dict) and cohort.get("status") != "blocked":
        if cohort.get("probability_space") != "reference_only":
            errors.append("o_entry_cohort must remain reference_only")
        if cohort.get("entry_state_rules_registered") is not False:
            errors.append("o_entry_cohort cannot expose entry-state rules in L2-2")
        if not isinstance(cohort.get("summary"), list) or not cohort["summary"]:
            errors.append("o_entry_cohort public summary required")
        if "entries" in cohort:
            errors.append("o_entry_cohort raw entries must not enter data.json")
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
