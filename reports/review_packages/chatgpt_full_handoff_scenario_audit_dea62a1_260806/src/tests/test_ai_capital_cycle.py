from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from ai_fc.ai_capital_cycle import (
    CIKS,
    build_ai_capital_cycle,
    validate_ai_regime,
    validate_regime_model,
)
from ai_fc.market_extensions import MarketExtensionError


def _model() -> dict:
    return {
        "model_version": "test.v1", "probability_space": "reference_only",
        "coverage_gate": .6,
        "robust_z": {"company_window_quarters": 20, "macro_window_years": 10,
                     "winsor_z_bounds": [-3, 3]},
        "percentile": {"start": date(2010, 1, 1)},
        "map": {"backfill_vintage_label": "reconstructed"},
    }


def _contract() -> dict:
    return {
        "capex_tag_fallbacks": ["PaymentsToAcquirePropertyPlantAndEquipment"],
        "operating_cashflow_tag_fallbacks": ["NetCashProvidedByUsedInOperatingActivities"],
        "depreciation_tag_fallbacks": ["DepreciationDepletionAndAmortization"],
        "debt_issued_tag_fallbacks": ["ProceedsFromIssuanceOfLongTermDebt"],
    }


def _facts() -> tuple[dict, dict]:
    companyfacts, receipts = {}, {}
    for symbol, cik in CIKS.items():
        nodes = {}
        for tag in (
            "PaymentsToAcquirePropertyPlantAndEquipment",
            "NetCashProvidedByUsedInOperatingActivities",
        ):
            nodes[tag] = {"units": {"USD": [{
                "end": "2026-06-30", "val": 1_000_000, "form": "10-Q",
                "filed": "2026-07-25", "fy": 2026, "fp": "Q2", "accn": "x",
            }]}}
        companyfacts[symbol] = {"cik": int(cik), "facts": {"us-gaap": nodes}}
        receipts[symbol] = {
            "request_url": f"https://data.sec.gov/{cik}",
            "response_sha256": symbol.lower(), "fetched_at": "2026-08-03T00:00:00Z",
        }
    return companyfacts, receipts


def _chains() -> dict:
    metrics = {
        "capex": {
            "tags": ["PaymentsToAcquireProductiveAssets",
                     "PaymentsToAcquirePropertyPlantAndEquipment"],
            "absence_status": "tag_missing",
        },
        "operating_cashflow": {
            "tags": ["NetCashProvidedByUsedInOperatingActivities"],
            "absence_status": "tag_missing",
        },
        "depreciation_amortization": {
            "tags": ["DepreciationDepletionAndAmortization"],
            "absence_status": "tag_missing",
        },
        "debt_issued": {
            "tags": ["ProceedsFromIssuanceOfLongTermDebt"],
            "absence_status": "not_disclosed",
        },
    }
    return {
        "recency_guard_days": 400,
        "companies": {symbol: metrics for symbol in CIKS},
    }


def _company(coverage: dict, symbol: str) -> dict:
    return next(row for row in coverage["companies"] if row["company"] == symbol)


def test_d2_coverage_blocks_map_without_segment_disclosures() -> None:
    facts, receipts = _facts()
    capex, coverage, regime = build_ai_capital_cycle(
        model=_model(), contract=_contract(), companyfacts=facts, receipts=receipts,
        asof=date(2026, 8, 3), generated_at=datetime(2026, 8, 3, tzinfo=timezone.utc))
    assert capex["records"]
    assert coverage["coverage"] == 0
    assert coverage["status"] == "insufficient"
    assert regime["status"] == "blocked"
    assert regime["coordinates"] is None and regime["trail"] == []
    validate_ai_regime(regime)


def test_regime_model_constants_are_preregistered() -> None:
    assert validate_regime_model(_model())["robust_z"]["winsor_z_bounds"] == [-3, 3]
    drifted = _model()
    drifted["robust_z"]["company_window_quarters"] = 16
    with pytest.raises(MarketExtensionError, match="windows drifted"):
        validate_regime_model(drifted)


def test_coverage_gate_rejects_hidden_coordinates() -> None:
    payload = {
        "probability_space": "reference_only", "coverage": .2,
        "coverage_threshold": .6, "status": "blocked", "map_render_allowed": False,
        "coordinates": {"x": 1, "y": 1}, "trail": [],
    }
    with pytest.raises(MarketExtensionError, match="coordinates escaped"):
        validate_ai_regime(payload)


def test_d1_excludes_facts_not_available_by_asof() -> None:
    facts, receipts = _facts()
    for payload in facts.values():
        payload["facts"]["us-gaap"]["PaymentsToAcquirePropertyPlantAndEquipment"][
            "units"
        ]["USD"].append({
            "end": "2026-09-30", "val": 9_999_999, "form": "10-Q",
            "filed": "2026-10-25", "fy": 2026, "fp": "Q3", "accn": "future",
        })
    capex, _, _ = build_ai_capital_cycle(
        model=_model(), contract=_contract(), companyfacts=facts, receipts=receipts,
        asof=date(2026, 8, 3), generated_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
    )
    assert all(row["available_at"] <= "2026-08-03" for row in capex["records"])
    assert all(row["accession"] != "future" for row in capex["records"])


def test_stale_tag_is_marked_and_excluded_from_collection_coverage() -> None:
    facts, receipts = _facts()
    stale = facts["AMZN"]["facts"]["us-gaap"].pop(
        "PaymentsToAcquirePropertyPlantAndEquipment")
    stale["units"]["USD"][0].update(
        {"end": "2024-06-28", "filed": "2024-07-25"})
    facts["AMZN"]["facts"]["us-gaap"]["PaymentsToAcquireProductiveAssets"] = stale
    capex, coverage, _ = build_ai_capital_cycle(
        model=_model(), contract=_contract(), tag_chains=_chains(),
        companyfacts=facts, receipts=receipts, asof=date(2026, 8, 3),
        generated_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
    )
    state = _company(coverage, "AMZN")["metrics"]["capex"]
    assert state["status"] == "tag_stale"
    assert state["coverage_eligible"] is False
    assert not [row for row in capex["records"]
                if row["company"] == "AMZN" and row["metric"] == "capex"]


def test_company_tag_chain_uses_first_fresh_amzn_capex_tag() -> None:
    facts, receipts = _facts()
    nodes = facts["AMZN"]["facts"]["us-gaap"]
    fresh = nodes["PaymentsToAcquirePropertyPlantAndEquipment"]
    nodes["PaymentsToAcquireProductiveAssets"] = fresh
    nodes["PaymentsToAcquirePropertyPlantAndEquipment"] = {
        "units": {"USD": [{
            "end": "2017-03-31", "val": 1, "form": "10-Q",
            "filed": "2017-04-25", "fy": 2017, "fp": "Q1", "accn": "old",
        }]},
    }
    capex, coverage, _ = build_ai_capital_cycle(
        model=_model(), contract=_contract(), tag_chains=_chains(),
        companyfacts=facts, receipts=receipts, asof=date(2026, 8, 3),
        generated_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
    )
    state = _company(coverage, "AMZN")["metrics"]["capex"]
    assert state["taxonomy_tag"] == "PaymentsToAcquireProductiveAssets"
    assert state["max_period"] == "2026-06-30"
    assert {row["taxonomy_tag"] for row in capex["records"]
            if row["company"] == "AMZN" and row["metric"] == "capex"} == {
                "PaymentsToAcquireProductiveAssets"
            }


def test_missing_metric_states_distinguish_tag_mapping_from_nondisclosure() -> None:
    facts, receipts = _facts()
    facts["MSFT"]["facts"]["us-gaap"] = {}
    _, coverage, _ = build_ai_capital_cycle(
        model=_model(), contract=_contract(), tag_chains=_chains(),
        companyfacts=facts, receipts=receipts, asof=date(2026, 8, 3),
        generated_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
    )
    metrics = _company(coverage, "MSFT")["metrics"]
    assert metrics["depreciation_amortization"]["status"] == "tag_missing"
    assert metrics["debt_issued"]["status"] == "not_disclosed"


@pytest.mark.parametrize(("age_days", "expected"), [(399, "collected"), (401, "tag_stale")])
def test_recency_guard_boundary(age_days: int, expected: str) -> None:
    asof = date(2026, 8, 3)
    facts, receipts = _facts()
    fact = facts["AMZN"]["facts"]["us-gaap"][
        "PaymentsToAcquirePropertyPlantAndEquipment"]["units"]["USD"][0]
    end = asof - timedelta(days=age_days)
    fact.update({"end": end.isoformat(), "filed": end.isoformat()})
    chains = _chains()
    chains["companies"]["AMZN"]["capex"]["tags"] = [
        "PaymentsToAcquirePropertyPlantAndEquipment"]
    _, coverage, _ = build_ai_capital_cycle(
        model=_model(), contract=_contract(), tag_chains=chains,
        companyfacts=facts, receipts=receipts, asof=asof,
        generated_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
    )
    assert _company(coverage, "AMZN")["metrics"]["capex"]["status"] == expected


def test_non_usd_companyfact_is_quarantined() -> None:
    facts, receipts = _facts()
    node = facts["AMZN"]["facts"]["us-gaap"].pop(
        "PaymentsToAcquirePropertyPlantAndEquipment")
    node["units"] = {"EUR": node["units"]["USD"]}
    facts["AMZN"]["facts"]["us-gaap"]["PaymentsToAcquireProductiveAssets"] = node
    _, coverage, _ = build_ai_capital_cycle(
        model=_model(), contract=_contract(), tag_chains=_chains(),
        companyfacts=facts, receipts=receipts, asof=date(2026, 8, 3),
        generated_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
    )
    state = _company(coverage, "AMZN")["metrics"]["capex"]
    assert state["status"] == "unit_unsupported"
    assert state["units_found"] == ["EUR"]
    assert state["coverage_eligible"] is False
