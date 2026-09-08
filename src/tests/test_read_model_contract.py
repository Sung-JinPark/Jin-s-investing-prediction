from ai_fc.read_model_contract import LEGACY_KEYS, V2_KEYS, schema, validate


def _minimal_model() -> dict:
    model = {key: value_type() for key, value_type in {**LEGACY_KEYS, **V2_KEYS}.items()}
    model["era_analog"] = {
        "status": "empty",
        "probability_space": "reference_only",
        "unit": "log10(index/100)",
        "series": [],
    }
    model["cross_asset"] = {
        "status": "blocked",
        "probability_space": "scenario_conditional",
        "unit": "index_100",
        "history": {},
        "forecast": {},
    }
    for key in ("scenario_tracker", "liquidity", "ai_regime"):
        model[key] = {
            "status": "blocked", "probability_space": "reference_only", "asof": None,
        }
    model["timeseries"] = {
        "schema_version": 1,
        "status": "validation_pending",
        "model_id": "shadow.mf_dfm_ridge_varx_v1",
        "model_version": 1,
        "probability_space": "research_timeseries_conditional",
        "combined_with_existing_models": False,
        "numbers_visible": False,
        "horizons": {},
        "path": {},
        "backtest": {"gate_pass": False, "reasons": ["pending"]},
    }
    return model


def test_read_model_contract_rejects_removed_legacy_key() -> None:
    model = _minimal_model()
    model.pop("scenario_history")
    assert "missing read-model key: scenario_history" in validate(model)


def test_read_model_contract_rejects_probability_space_drift() -> None:
    model = _minimal_model()
    model["era_analog"]["probability_space"] = "scenario_conditional"
    assert any("reference_only" in error for error in validate(model))


def test_json_schema_lists_all_additive_and_legacy_keys() -> None:
    contract = schema()
    assert set(LEGACY_KEYS) | set(V2_KEYS) <= set(contract["required"])
    assert contract["properties"]["era_analog"]["properties"]["probability_space"] == {
        "const": "reference_only"
    }
    assert contract["properties"]["cross_asset"]["properties"]["probability_space"] == {
        "enum": ["scenario_conditional", "reference_only"]
    }
    assert contract["properties"]["era_analog"]["properties"]["series"][
        "items"]["required"] == ["id", "overlay_start", "model_anchor"]


def test_read_model_contract_rejects_cross_asset_semantic_drift() -> None:
    model = _minimal_model()
    model["cross_asset"].pop("status")
    model["cross_asset"]["probability_space"] = "physical_event"
    assert any("cross_asset" in error for error in validate(model))


def test_read_model_contract_rejects_new_reference_space_drift() -> None:
    model = _minimal_model()
    model["liquidity"]["probability_space"] = "scenario_conditional"
    assert "liquidity probability_space must be reference_only" in validate(model)


def test_timeseries_shadow_cannot_silently_combine_or_show_failed_gate_numbers() -> None:
    model = _minimal_model()
    model["timeseries"]["combined_with_existing_models"] = True
    model["timeseries"]["horizons"] = {"1": {"probability_up": 0.5}}
    errors = validate(model)
    assert "timeseries must remain isolated from existing probability spaces" in errors
    assert "timeseries validation-pending surface must hide numbers" in errors


def _v8_visible_timeseries() -> dict:
    return {
        "schema_version": 1,
        "status": "shadow_live",
        "display_state": "research_reference",
        "model_id": "shadow.mf_dfm_varx_calibrated_v8",
        "model_version": 8,
        "probability_space": "research_timeseries_v8_conditional",
        "combined_with_existing_models": False,
        "numbers_visible": True,
        "gate": {"sealed_gate_pass": True, "operational_pass": True, "reasons": []},
        "publication": {"reference_opinion_only": True},
        "horizons": {"1": {"probability_up": 0.5}},
    }


def test_timeseries_v8_visible_surface_passes_when_both_gates_hold() -> None:
    model = _minimal_model()
    model["timeseries"] = _v8_visible_timeseries()
    assert not [error for error in validate(model) if "timeseries" in error]


def test_timeseries_v8_cannot_show_numbers_past_a_failed_operational_gate() -> None:
    model = _minimal_model()
    model["timeseries"] = _v8_visible_timeseries()
    model["timeseries"]["gate"]["operational_pass"] = False
    assert "timeseries V8 visibility must equal both Gate decisions" in validate(model)


def test_timeseries_v8_must_keep_its_space_and_reference_opinion_status() -> None:
    model = _minimal_model()
    model["timeseries"] = _v8_visible_timeseries()
    model["timeseries"]["probability_space"] = "research_timeseries_v2_conditional"
    model["timeseries"]["publication"]["reference_opinion_only"] = False
    model["timeseries"]["display_state"] = "customer_default"
    errors = validate(model)
    assert "timeseries V8 probability space mismatch" in errors
    assert "timeseries V8 must keep reference-opinion-only status" in errors
    assert "timeseries V8 visible surface must declare research_reference" in errors


def test_timeseries_v8_hidden_surface_must_not_leak_history_or_freshness() -> None:
    model = _minimal_model()
    model["timeseries"] = _v8_visible_timeseries()
    model["timeseries"]["numbers_visible"] = False
    model["timeseries"]["status"] = "shadow_operational_hold"
    model["timeseries"]["gate"]["operational_pass"] = False
    model["timeseries"]["horizons"] = {}
    model["timeseries"]["history"] = {"index": [1.0]}
    model["timeseries"]["freshness_summary"] = [{"group": "VIX"}]
    errors = validate(model)
    assert "timeseries V8 hidden surface must not carry history or freshness numbers" in errors


def _v13_live_surface(tier: str = "t2_hidden_panel", holdout_status: str = "not_consumed") -> dict:
    cells = {name: {"p": 0.42, "band80": [0.38, 0.46], "model": "persistence_pb", "reliability": "good"}
             for name in ("vix25_h5", "vix25_h21", "vix25_h63", "vix30_h5", "vix30_h21", "vix30_h63",
                          "rv_h5", "rv_h21", "rv_h63")}
    return {
        "schema_version": 1, "status": "live", "display_state": "research_reference",
        "model_id": "event_probability.volatility_v13", "model_version": 13,
        "probability_space": "research_volatility_v13_base_rate", "probability_unit": "fraction",
        "combined_with_existing_models": False, "numbers_visible": True,
        "publication": {"display_tier": tier, "reference_opinion_only": True, "holdout_status": holdout_status,
                        "holdout_caveat_bold": tier == "t3_live_card" and holdout_status != "pass",
                        "trading_signal": False},
        "gate": {"design_gate_pass": True, "armed": True, "coefficients_pinned": True, "freshness_pass": True,
                 "holdout_status": holdout_status, "reasons": []},
        "cells": cells, "inputs": {"vix_close": 18.0},
    }


def _v13_errors(model: dict) -> list[str]:
    return [error for error in validate(model) if "timeseries_v13_vol" in error]


def test_timeseries_v13_vol_live_passes_when_all_gates_hold() -> None:
    model = _minimal_model()
    model["timeseries_v13_vol"] = _v13_live_surface()
    assert not _v13_errors(model)
    model["timeseries_v13_vol"] = _v13_live_surface(tier="t3_live_card", holdout_status="pass")
    assert not _v13_errors(model)


def test_timeseries_v13_vol_cannot_show_cells_past_a_failed_gate() -> None:
    model = _minimal_model()
    model["timeseries_v13_vol"] = _v13_live_surface()
    model["timeseries_v13_vol"]["gate"]["freshness_pass"] = False
    assert "timeseries_v13_vol numbers visible before all four gates pass" in validate(model)


def test_timeseries_v13_vol_hidden_surface_must_not_leak_cells() -> None:
    model = _minimal_model()
    model["timeseries_v13_vol"] = _v13_live_surface()
    model["timeseries_v13_vol"]["numbers_visible"] = False
    model["timeseries_v13_vol"]["status"] = "hold"
    assert "timeseries_v13_vol hidden surface must not carry cells" in validate(model)


def test_timeseries_v13_vol_t0_tier_forbids_numbers() -> None:
    model = _minimal_model()
    model["timeseries_v13_vol"] = _v13_live_surface(tier="t0_internal")
    assert "timeseries_v13_vol t0 tier must not carry numbers" in validate(model)


def test_timeseries_v13_vol_t3_without_holdout_requires_bold_caveat() -> None:
    model = _minimal_model()
    model["timeseries_v13_vol"] = _v13_live_surface(tier="t3_live_card")
    model["timeseries_v13_vol"]["publication"]["holdout_caveat_bold"] = False
    assert "timeseries_v13_vol live card without holdout pass must bold the caveat" in validate(model)


def test_timeseries_v13_vol_must_keep_space_and_reference_status_and_ladder() -> None:
    model = _minimal_model()
    model["timeseries_v13_vol"] = _v13_live_surface()
    model["timeseries_v13_vol"]["probability_space"] = "physical_event"
    model["timeseries_v13_vol"]["publication"]["reference_opinion_only"] = False
    model["timeseries_v13_vol"]["publication"]["trading_signal"] = True
    model["timeseries_v13_vol"]["publication"]["display_tier"] = "t4_capital_decision"
    model["timeseries_v13_vol"]["combined_with_existing_models"] = True
    errors = validate(model)
    assert "timeseries_v13_vol probability space mismatch" in errors
    assert "timeseries_v13_vol must keep reference-opinion-only status" in errors
    assert "timeseries_v13_vol must not be a trading signal" in errors
    assert "timeseries_v13_vol display tier outside the ladder" in errors
    assert "timeseries_v13_vol must remain isolated from existing probability spaces" in errors


def test_timeseries_v13_vol_cell_band_must_bracket_probability() -> None:
    model = _minimal_model()
    model["timeseries_v13_vol"] = _v13_live_surface()
    model["timeseries_v13_vol"]["cells"]["rv_h5"]["band80"] = [0.5, 0.46]
    assert "timeseries_v13_vol cell rv_h5 band/probability out of order" in validate(model)


def test_timeseries_v13_vol_visibility_status_and_display_state_and_malformed_cells() -> None:
    model = _minimal_model()
    model["timeseries_v13_vol"] = _v13_live_surface()
    model["timeseries_v13_vol"]["status"] = "hold"          # numbers_visible True 인데 status hold
    assert "timeseries_v13_vol visibility/status mismatch" in validate(model)
    model = _minimal_model()
    model["timeseries_v13_vol"] = _v13_live_surface()
    model["timeseries_v13_vol"]["display_state"] = "customer_default"
    assert "timeseries_v13_vol visible surface must declare research_reference" in validate(model)
    model = _minimal_model()
    model["timeseries_v13_vol"] = _v13_live_surface()
    model["timeseries_v13_vol"]["cells"]["rv_h5"] = {"p": "x"}
    assert "timeseries_v13_vol cell rv_h5 malformed" in validate(model)


def test_timeseries_v13_vol_numbers_hidden_after_holdout_failure() -> None:
    model = _minimal_model()
    model["timeseries_v13_vol"] = _v13_live_surface(tier="t3_live_card", holdout_status="fail")
    assert "timeseries_v13_vol numbers visible after holdout failure" in validate(model)
