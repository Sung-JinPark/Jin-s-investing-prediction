from __future__ import annotations

from datetime import date, datetime, timezone

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
