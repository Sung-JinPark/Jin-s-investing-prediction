import json
from pathlib import Path

import yaml


ROOT = Path(__file__).parents[2]
CONTRACT_PATHS = (
    ROOT / "data/contracts/finra_margin_statistics_d0.yaml",
    ROOT / "data/contracts/fred_nfci_d0.yaml",
    ROOT / "data/contracts/cftc_cot_bitcoin_d0.yaml",
)
FOLLOWUP_PATHS = (
    ROOT / "data/contracts/fed_z1_margin_proxy_d0.yaml",
    ROOT / "data/contracts/fred_stlfsi4_d0.yaml",
)


def _contracts() -> list[dict]:
    return [yaml.safe_load(path.read_text(encoding="utf-8")) for path in CONTRACT_PATHS]


def _followups() -> list[dict]:
    return [yaml.safe_load(path.read_text(encoding="utf-8")) for path in FOLLOWUP_PATHS]


def _all_contracts() -> list[dict]:
    return _contracts() + _followups()


def test_s0_selects_exactly_three_p1_d0_contracts() -> None:
    contracts = _contracts()
    assert len(contracts) == 3
    assert {item["source_id"] for item in contracts} == {
        "finra_margin_statistics",
        "fred_nfci",
        "cftc_cot_bitcoin",
    }
    assert {item["batch_id"] for item in contracts} == {"s0_260804_p1"}
    assert all(item["stage"] == "D0" and item["priority"] == "P1" for item in contracts)


def test_s0_contracts_are_disabled_and_have_no_collectors() -> None:
    contracts = _all_contracts()
    assert all(item["enabled"] is False for item in contracts)
    assert all(item["model_use"] == "prohibited" for item in contracts)
    assert all(item["collector_status"] == "prohibited_until_d0_pass" for item in contracts)
    assert all(item["registry_status"] == "not_registered_until_d0_pass" for item in contracts)
    assert all(item["storage_policy"]["mode"] == "append_only_after_activation" for item in contracts)
    assert all(item["storage_policy"]["historical_backfill_vintage"] == "reconstructed" for item in contracts)

    registry_text = (ROOT / "data/source_registry.yaml").read_text(encoding="utf-8")
    source_code = "\n".join(
        path.read_text(encoding="utf-8") for path in (ROOT / "src/ai_fc").rglob("*.py")
    )
    for source_id in (item["source_id"] for item in contracts):
        assert source_id not in registry_text
        assert source_id not in source_code


def test_s0_followup_keeps_exactly_three_parallel_d0_monitors() -> None:
    by_id = {item["source_id"]: item for item in _all_contracts()}
    monitoring = {source_id for source_id, item in by_id.items() if item["d0"]["status"] == "monitoring"}

    assert monitoring == {"cftc_cot_bitcoin", "fed_z1_margin_proxy", "fred_stlfsi4"}
    assert by_id["finra_margin_statistics"]["d0"]["status"] == "blocked_legal_terms"
    assert by_id["fred_nfci"]["d0"]["status"] == "legal_review_required"
    assert all(item["batch_id"] == "s0_260805_d0_followup" for item in _followups())
    assert all(item["d0"]["fetch_allowed"] is True for item in _followups())
    assert all(item["d0"]["initial_observation"]["raw_payload_committed"] is False for item in _followups())


def test_z1_proxy_is_direct_board_data_and_cannot_masquerade_as_finra() -> None:
    z1 = {item["source_id"]: item for item in _followups()}["fed_z1_margin_proxy"]

    assert z1["series_id"] == "FL663067003"
    assert z1["table_id"] == "L.216" and z1["table_line"] == 36
    assert z1["endpoint"].startswith("https://www.federalreserve.gov/")
    assert z1["license"]["status"] == "public_domain_with_attribution"
    assert "never the quarter end" in z1["point_in_time"]["available_at"]
    assert z1["replacement_policy"]["role"] == "proxy_not_finra_margin_debt"
    assert "FINRA grants written permission" in z1["replacement_policy"]["resolution"]
    assert "must never be labelled" in z1["replacement_policy"]["comparability_warning"]


def test_stlfsi4_d0_is_ephemeral_and_rights_gated_before_activation() -> None:
    stl = {item["source_id"]: item for item in _followups()}["fred_stlfsi4"]

    assert stl["series_id"] == "STLFSI4"
    assert stl["d0"]["fetch_scope"] == "ephemeral_schema_and_release_monitor_only"
    assert stl["license"]["status"] == "copyrighted_citation_required_activation_review"
    assert stl["license"]["database_creation"] == "prohibited_pending_source_specific_clarification"
    assert stl["license"]["predictive_analytics_use"] == "prohibited_pending_source_specific_clarification"
    assert "following Wednesday" in stl["point_in_time"]["available_at"]
    assert "committing raw payloads" in stl["activation_gate"][0]


def test_finra_and_nfci_are_legal_gated_before_fetch() -> None:
    by_id = {item["source_id"]: item for item in _contracts()}
    finra = by_id["finra_margin_statistics"]
    nfci = by_id["fred_nfci"]

    assert finra["d0"]["status"] == "blocked_legal_terms"
    assert finra["d0"]["fetch_allowed"] is False
    assert finra["license"]["predictive_analytics_use"] == "prohibited_without_written_permission"
    assert finra["point_in_time"]["revision_vintage"] == "reconstructed"

    assert nfci["d0"]["status"] == "legal_review_required"
    assert nfci["d0"]["fetch_allowed"] is False
    assert nfci["license"]["predictive_analytics_use"] == "prohibited_pending_written_clarification"
    assert "blanket status" in nfci["fallback"]


def test_cftc_bitcoin_contract_pins_tff_dataset_and_pit_availability() -> None:
    cftc = {item["source_id"]: item for item in _contracts()}["cftc_cot_bitcoin"]
    assert cftc["dataset_id"] == "gpe5-46if"
    assert cftc["contract_market_code"] == "133741"
    assert cftc["query"]["where"] == "cftc_contract_market_code='133741'"
    assert cftc["d0"]["status"] == "monitoring"
    assert cftc["d0"]["initial_observation"]["http_status"] == 200
    assert cftc["d0"]["initial_observation"]["raw_payload_committed"] is False
    assert "asset_mgr_positions_long" in cftc["schema"]["required_fields"]
    assert "asset_mgr_positions_long_all" not in cftc["schema"]["required_fields"]
    assert "Friday release timestamp" in cftc["point_in_time"]["available_at"]
    assert "never Tuesday" in cftc["point_in_time"]["available_at"]


def test_u0_audit_releases_u1_gate_only_with_complete_capture_set() -> None:
    report = (ROOT / "reports/md/UX_AUDIT_260805.md").read_text(encoding="utf-8")
    assert "상태: **PASS — U1 승인 해제**" in report
    assert "전 라우트별 1280/390 스크린샷 | PASS" in report
    assert "**U1 승인: 해제.**" in report

    capture_dir = ROOT / "reports/screenshots/ux_audit_260805"
    manifest = json.loads((capture_dir / "capture_results.json").read_text(encoding="utf-8"))
    assert manifest["expected"] == manifest["captured"] == 30
    assert manifest["failed"] == 0
    assert {item["viewport"] for item in manifest["results"]} == {"1280", "390"}
    assert len({item["route"] for item in manifest["results"]}) == 15
    assert all(item["status"] == "captured" for item in manifest["results"])
    assert all((capture_dir / item["file"]).is_file() for item in manifest["results"])
