from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from ai_fc.ai_capital_cycle import (
    CIKS,
    build_ai_capital_cycle,
    build_capital_intensity,
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

def _annual_facts() -> tuple[dict, dict]:
    """Annual, year-to-date and quarterly facts sharing one period end.

    The year-to-date and quarterly rows exist so the tests can prove the
    annual layer does not divide an annual numerator by a shorter-duration
    denominator, which is the failure mode the D1 rows cannot rule out.
    """
    companyfacts, receipts = {}, {}
    for symbol, cik in CIKS.items():
        capex = {"units": {"USD": [
            {"start": "2025-01-01", "end": "2025-12-31", "val": 60_000,
             "form": "10-K", "filed": "2026-02-05", "fy": 2025, "fp": "FY", "accn": "a-annual"},
            {"start": "2025-10-01", "end": "2025-12-31", "val": 20_000,
             "form": "10-K", "filed": "2026-02-05", "fy": 2025, "fp": "Q4", "accn": "a-quarter"},
            {"start": "2024-01-01", "end": "2024-12-31", "val": 30_000,
             "form": "10-K", "filed": "2025-02-05", "fy": 2024, "fp": "FY", "accn": "a-prior"},
        ]}}
        operating = {"units": {"USD": [
            {"start": "2025-01-01", "end": "2025-12-31", "val": 100_000,
             "form": "10-K", "filed": "2026-02-05", "fy": 2025, "fp": "FY", "accn": "o-annual"},
            {"start": "2025-07-01", "end": "2025-12-31", "val": 55_000,
             "form": "10-K", "filed": "2026-02-05", "fy": 2025, "fp": "H2", "accn": "o-half"},
            {"start": "2024-01-01", "end": "2024-12-31", "val": 90_000,
             "form": "10-K", "filed": "2025-02-05", "fy": 2024, "fp": "FY", "accn": "o-prior"},
        ]}}
        depreciation = {"units": {"USD": [
            {"start": "2025-01-01", "end": "2025-12-31", "val": 20_000,
             "form": "10-K", "filed": "2026-02-05", "fy": 2025, "fp": "FY", "accn": "d-annual"},
        ]}}
        finance_lease = {"units": {"USD": [
            {"end": "2025-12-31", "val": 42_000, "form": "10-K",
             "filed": "2026-02-05", "accn": "l-latest"},
            {"end": "2024-12-31", "val": 11_000, "form": "10-K",
             "filed": "2025-02-05", "accn": "l-prior"},
        ]}}
        operating_lease = {"units": {"USD": [
            {"end": "2025-12-31", "val": 33_000, "form": "10-K",
             "filed": "2026-02-05", "accn": "ol-latest"},
        ]}}
        companyfacts[symbol] = {"cik": int(cik), "facts": {"us-gaap": {
            "PaymentsToAcquirePropertyPlantAndEquipment": capex,
            "NetCashProvidedByUsedInOperatingActivities": operating,
            "DepreciationDepletionAndAmortization": depreciation,
            "FinanceLeaseLiabilityPaymentsDue": finance_lease,
            "LesseeOperatingLeaseLiabilityPaymentsDue": operating_lease,
        }}}
        receipts[symbol] = {
            "request_url": f"https://data.sec.gov/{cik}",
            "response_sha256": symbol.lower(), "fetched_at": "2026-08-31T00:00:00Z",
        }
    return companyfacts, receipts


def _intensity(asof: date = date(2026, 8, 31)) -> dict:
    facts, receipts = _annual_facts()
    return build_capital_intensity(
        contract=_contract(), tag_chains=_chains(), companyfacts=facts,
        receipts=receipts, asof=asof,
        generated_at=datetime(2026, 8, 31, tzinfo=timezone.utc))


def test_capital_intensity_uses_only_full_year_durations() -> None:
    payload = _intensity()
    company = payload["companies"][0]
    latest = company["annual"][-1]
    assert latest["fiscal_year"] == 2025
    # The annual capex fact, not the quarterly one that shares its period end.
    assert latest["capex"] == 60_000
    assert latest["operating_cashflow"] == 100_000
    assert latest["accessions"]["capex"] == "a-annual"
    assert latest["accessions"]["operating_cashflow"] == "o-annual"
    assert latest["capex_to_operating_cashflow"] == pytest.approx(0.6)
    assert latest["capex_to_depreciation"] == pytest.approx(3.0)
    assert latest["free_cash_flow"] == pytest.approx(40_000)


def test_capital_intensity_reports_undiscounted_lease_obligations() -> None:
    company = _intensity()["companies"][0]
    finance = company["lease_obligations"]["finance_lease_payments_due"]
    assert finance["value"] == 42_000
    assert finance["period_end"] == "2025-12-31"
    assert finance["taxonomy_tag"] == "FinanceLeaseLiabilityPaymentsDue"
    assert company["lease_obligations"]["operating_lease_payments_due"]["value"] == 33_000
    # A tag the filer never used stays explicitly absent rather than zero.
    assert company["lease_obligations"]["finance_lease_liability"] is None


def test_capital_intensity_excludes_facts_filed_after_the_cutoff() -> None:
    payload = _intensity(asof=date(2025, 6, 30))
    company = payload["companies"][0]
    assert [row["fiscal_year"] for row in company["annual"]] == [2024]
    assert company["lease_obligations"]["finance_lease_payments_due"]["value"] == 11_000


def test_capital_intensity_refuses_to_attribute_spending_to_ai() -> None:
    payload = _intensity()
    assert payload["probability_space"] == "reference_only"
    assert payload["model_use"] is False
    assert payload["official_forecast_input"] is False
    assert payload["ai_attribution"] == "not_inferred"
    assert payload["gate"] == "D2"
