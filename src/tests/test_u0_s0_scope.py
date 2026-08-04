from pathlib import Path

import yaml


ROOT = Path(__file__).parents[2]
CONTRACT_PATHS = (
    ROOT / "data/contracts/finra_margin_statistics_d0.yaml",
    ROOT / "data/contracts/fred_nfci_d0.yaml",
    ROOT / "data/contracts/cftc_cot_bitcoin_d0.yaml",
)


def _contracts() -> list[dict]:
    return [yaml.safe_load(path.read_text(encoding="utf-8")) for path in CONTRACT_PATHS]


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
    contracts = _contracts()
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


def test_u0_audit_keeps_u1_gate_closed_without_full_screenshot_set() -> None:
    report = (ROOT / "reports/md/UX_AUDIT_260805.md").read_text(encoding="utf-8")
    assert "상태: **PARTIAL — U1 승인 차단**" in report
    assert "전 라우트별 1280/390 스크린샷 | **PARTIAL**" in report
    assert "**U1 승인: 차단.**" in report
    assert "UI 코드 무변경" in report
