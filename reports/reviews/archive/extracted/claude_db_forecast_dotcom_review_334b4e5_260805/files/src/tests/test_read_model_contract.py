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
