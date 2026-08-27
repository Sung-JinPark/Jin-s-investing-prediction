from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = ROOT / "data" / "timeseries_v8r" / "contracts" / "data_sources"


def test_all_tier_a_b_contract_drafts_exist_without_collection():
    expected = {
        "fred_vix", "cboe_volatility", "cftc_cot", "treasury_fiscaldata",
        "sec_edgar_companyfacts", "finra_margin", "ici_fund_flows",
        "policy_uncertainty_epu", "naaim_exposure", "aaii_sentiment",
        "ken_french_factors",
    }
    rows = [yaml.safe_load(path.read_text(encoding="utf-8"))
            for path in sorted(CONTRACTS.glob("*.yaml"))]
    assert {row["source_id"] for row in rows} == expected
    assert all(row["schema"] == "v8r_source_contract_draft_v1" for row in rows)
    assert all(row["collection_allowed"] is False for row in rows)
    assert all(row["license_check"]["url"].startswith("https://") for row in rows)
    assert all(row["license_check"]["checked_at"] for row in rows)
    assert all(row["available_at_formula"] for row in rows)
    assert all(row["incremental_cursor"] for row in rows)
    assert all(row["receipt"] for row in rows)


def test_unresolved_terms_are_explicit_and_no_collected_artifact_exists():
    rows = [yaml.safe_load(path.read_text(encoding="utf-8"))
            for path in sorted(CONTRACTS.glob("*.yaml"))]
    unresolved = {row["source_id"] for row in rows
                  if row["draft_status"] in {
                      "open_question", "blocked_pending_legal_review",
                      "blocked_pending_permission", "blocked_pending_access_and_license",
                      "reference_only_open_question",
                  }}
    assert {
        "fred_vix", "cboe_volatility", "treasury_fiscaldata", "finra_margin",
        "ici_fund_flows", "policy_uncertainty_epu", "naaim_exposure",
        "aaii_sentiment", "ken_french_factors",
    } <= unresolved
    data_root = ROOT / "data" / "timeseries_v8r"
    assert not (data_root / "facts").exists()
    assert not (data_root / "receipts").exists()
    assert not (data_root / "raw").exists()
