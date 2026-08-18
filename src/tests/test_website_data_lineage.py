from __future__ import annotations

from pathlib import Path

import yaml

from ai_fc import dashboard


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "data/contracts/website_data_lineage_v1.yaml"

REQUIRED_SURFACES = {
    "official_question_forecasts",
    "champion",
    "scenario_v5_2_default",
    "scenario_v4_shadow",
    "cross_asset",
    "realty_income",
    "bitcoin",
    "liquidity",
    "era_analog",
    "multi_year_stress",
    "scenario_tracker",
    "calendar",
    "ai_regime",
    "band_calibration",
    "display_promotion",
}

REQUIRED_SURFACE_FIELDS = {
    "routes",
    "publication_class",
    "probability_space",
    "official_forecast_write",
    "numeric_input_policy",
    "source_artifacts",
    "payload_locations",
    "artifact_gate",
}


def _contract() -> dict:
    payload = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_lineage_contract_covers_every_dashboard_market_surface() -> None:
    contract = _contract()
    surfaces = contract["surfaces"]
    assert REQUIRED_SURFACES <= set(surfaces)

    known_payloads = set(contract["payload_artifacts"])
    for surface_id in REQUIRED_SURFACES:
        surface = surfaces[surface_id]
        assert REQUIRED_SURFACE_FIELDS <= set(surface), surface_id
        assert surface["routes"], surface_id
        assert surface["source_artifacts"], surface_id
        assert surface["payload_locations"], surface_id
        assert surface["publication_class"] in contract["publication_classes"], surface_id
        for location in surface["payload_locations"]:
            assert location["artifact"] in known_payloads, (surface_id, location)
            assert location["key"], (surface_id, location)
            assert location["materialization"], (surface_id, location)


def test_declared_source_artifacts_exist_and_generated_payload_names_match_code() -> None:
    contract = _contract()
    payloads = contract["payload_artifacts"]
    assert Path(payloads["dashboard_base"]["public_file"]).name == "data.json"
    assert Path(payloads["future_deferred"]["public_file"]).name == dashboard.FUTURE_PATHS_FILENAME
    assert Path(payloads["statistics_deferred"]["public_file"]).name == dashboard.STATISTICS_DATA_FILENAME
    assert payloads["future_deferred"]["contract_id"] == "future_paths_v1"
    assert payloads["statistics_deferred"]["contract_id"] == "statistics_route_v1"

    for surface_id, surface in contract["surfaces"].items():
        for relative in surface["source_artifacts"]:
            assert (ROOT / relative).exists(), (surface_id, relative)


def test_future_deferred_lineage_matches_dashboard_split_contract() -> None:
    contract = _contract()
    surfaces = contract["surfaces"]
    deferred_root_keys = {
        location["key"].split(".", 1)[0]
        for surface in surfaces.values()
        for location in surface["payload_locations"]
        if location["artifact"] == "future_deferred"
    }
    assert deferred_root_keys == set(dashboard.FUTURE_DEFERRED_KEYS)

    assert surfaces["scenario_v5_2_default"]["routes"][0] == "#future"
    assert "#future/champion" in surfaces["champion"]["routes"]
    assert surfaces["scenario_v5_2_default"]["display_role"] == (
        "customer_default_research_candidate"
    )
    assert surfaces["scenario_v5_2_default"]["publication_class"] == (
        "research_reference_proxy"
    )
    assert surfaces["scenario_v5_2_default"]["official_forecast_write"] is False


def test_official_and_reference_numeric_policies_are_not_conflated() -> None:
    contract = _contract()
    classes = contract["publication_classes"]
    assert classes["official_numeric_statistics"]["may_write_official_forecast"] is False
    assert classes["canonical_forecast_ledger"]["may_write_official_forecast"] is True
    assert classes["research_reference_proxy"]["may_write_official_forecast"] is False

    for surface_id, surface in contract["surfaces"].items():
        if surface["publication_class"] == "research_reference_proxy":
            assert surface["official_forecast_write"] is False, surface_id
            assert surface["probability_space"] in {"reference_only", "scenario_conditional"}

    statistics = contract["statistics"]
    assert statistics["publication_class"] == "official_numeric_statistics"
    assert statistics["official_forecast_input"] is False
    assert statistics["observation_through_field"] == "observation_through"
    assert statistics["knowledge_cutoff_field"] == "knowledge_cutoff"


def test_observation_coverage_and_knowledge_cutoff_have_distinct_meanings() -> None:
    semantics = _contract()["time_semantics"]
    assert "not when the value became knowable" in semantics["observation_through"]["meaning"]
    assert "available_at" in semantics["knowledge_cutoff"]["meaning"]
    assert "Build timestamp only" in semantics["generated_at"]["meaning"]
    assert "compatibility alias" in semantics["as_of"]["meaning"]
    assert (
        "available_at_lte_knowledge_cutoff_for_every_numerically_used_observation"
        in semantics["invariants"]
    )
