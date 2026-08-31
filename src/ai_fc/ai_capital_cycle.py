"""AI capital-cycle D0–D2 collector and coverage gate.

The SEC Companyfacts API is entity-wide and cannot establish cloud/AI segment
revenue by itself.  This module collects auditable standardized facts, publishes
the resulting disclosure-coverage report, and intentionally blocks D3 map
coordinates until filing-level segment extraction clears the 60% gate.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .market_extensions import MarketExtensionError, _persist_json

CIKS = {
    "MSFT": "0000789019", "AMZN": "0001018724",
    "GOOGL": "0001652044", "META": "0001326801",
}
MODEL_PATH = Path("data/ai_capital_cycle/regime_model.yaml")
CONTRACT_PATH = Path("data/contracts/ai_capital_cycle.yaml")
TAG_CHAIN_PATH = Path("data/contracts/sec_tag_chains.yaml")
CAPEX_LATEST = Path("data/ai_capital_cycle/company_capex_quarterly_latest.json")
CAPEX_ARCHIVE = Path("data/ai_capital_cycle/company_capex_archive")
COVERAGE_LATEST = Path("data/ai_capital_cycle/coverage_latest.json")
COVERAGE_ARCHIVE = Path("data/ai_capital_cycle/coverage_archive")
REGIME_LATEST = Path("data/ai_capital_cycle/ai_regime_latest.json")
REGIME_ARCHIVE = Path("data/ai_capital_cycle/regime_archive")
# Outside data/ai_capital_cycle on purpose: that directory is a protected
# root of the V5.2 scenario candidate, where new files are forbidden between
# candidate rebuilds. Derived build-out views live in their own directory.
INTENSITY_LATEST = Path("data/ai_buildout/capital_intensity_latest.json")
INTENSITY_ARCHIVE = Path("data/ai_buildout/capital_intensity_archive")

# Undiscounted future lease payments.  Data-centre capacity is increasingly
# taken through leases rather than bond issuance, so a debt-only view of the
# build-out understates it; these tags exist for all four issuers.
LEASE_TAGS = {
    "finance_lease_payments_due": "FinanceLeaseLiabilityPaymentsDue",
    "operating_lease_payments_due": "LesseeOperatingLeaseLiabilityPaymentsDue",
    "finance_lease_liability": "FinanceLeaseLiability",
    "operating_lease_liability": "OperatingLeaseLiability",
}
ANNUAL_MIN_DAYS = 330
ANNUAL_MAX_DAYS = 400


def _user_agent() -> str:
    return os.getenv(
        "AI_FC_SEC_USER_AGENT",
        "Jin Investing Prediction research Sung-JinPark@users.noreply.github.com",
    )


def _fetch_companyfacts(cik: str) -> tuple[dict[str, Any], dict[str, Any]]:
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    request = urllib.request.Request(
        url, headers={"User-Agent": _user_agent(), "Accept-Encoding": "identity"})
    with urllib.request.urlopen(request, timeout=90) as response:
        raw = response.read()
    payload = json.loads(raw)
    if str(payload.get("cik", "")).zfill(10) != cik:
        raise MarketExtensionError(f"SEC companyfacts CIK mismatch for {cik}")
    return payload, {
        "source": "sec_edgar", "request_url": url,
        "response_sha256": hashlib.sha256(raw).hexdigest(),
        "fetched_at": fetched_at, "revision_vintage": "sec_filing_native",
    }


def _quarterly_rows(symbol: str, cik: str, metric: str, tag: str,
                    node: dict[str, Any], receipt: dict[str, Any], *, asof: date
                    ) -> list[dict[str, Any]]:
    units = node.get("units") or {}
    # Companyfacts can expose the same concept in several units.  The D1
    # contract is USD-only; accepting the first arbitrary unit would silently
    # mix currencies or shares with dollars.
    candidates = units.get("USD") or []
    rows = []
    for fact in candidates:
        if fact.get("form") not in ("10-Q", "10-K") or not fact.get("filed"):
            continue
        end = fact.get("end")
        if not end or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", end):
            continue
        try:
            filing_date = date.fromisoformat(str(fact["filed"]))
            period_end = date.fromisoformat(end)
        except ValueError:
            continue
        if filing_date > asof or period_end > asof:
            continue
        rows.append({
            "company": symbol, "cik": cik, "metric": metric, "taxonomy_tag": tag,
            "observation_period": end, "value": fact.get("val"), "unit": "USD",
            "form": fact.get("form"), "fiscal_year": fact.get("fy"),
            "fiscal_period": fact.get("fp"), "frame": fact.get("frame"),
            "accession": fact.get("accn"), "available_at": fact["filed"],
            "source_url": receipt["request_url"],
            "source_fingerprint": receipt["response_sha256"],
            "revision_vintage": "sec_filing_native",
            "value_status": "reported",
            "reporting_basis": "standalone_or_ytd_as_filed_no_quarterization",
        })
    rows.sort(key=lambda row: (row["observation_period"], row["available_at"], row.get("accession") or ""))
    # Keep the latest filing revision for each period and cap the static D1 layer.
    latest_by_period = {row["observation_period"]: row for row in rows}
    return list(latest_by_period.values())[-8:]


def _legacy_tag_groups(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Translate the original global contract for backwards-compatible tests."""
    return {
        "capex": {"tags": contract["capex_tag_fallbacks"],
                  "absence_status": "tag_missing"},
        "operating_cashflow": {
            "tags": contract["operating_cashflow_tag_fallbacks"],
            "absence_status": "tag_missing",
        },
        "depreciation_amortization": {
            "tags": contract["depreciation_tag_fallbacks"],
            "absence_status": "tag_missing",
        },
        "debt_issued": {"tags": contract["debt_issued_tag_fallbacks"],
                        "absence_status": "not_disclosed"},
    }


def _metric_contract(
    symbol: str, metric: str, *, contract: dict[str, Any], tag_chains: dict[str, Any] | None,
) -> tuple[list[str], str, int]:
    legacy = _legacy_tag_groups(contract)[metric]
    if not tag_chains:
        return list(legacy["tags"]), str(legacy["absence_status"]), 400
    company = ((tag_chains.get("companies") or {}).get(symbol) or {})
    row = company.get(metric) or {}
    tags = list(row.get("tags") or legacy["tags"])
    absence = str(row.get("absence_status") or legacy["absence_status"])
    if absence not in {"tag_missing", "not_disclosed"}:
        raise MarketExtensionError(
            f"invalid absence_status for {symbol}.{metric}: {absence}")
    max_age = int(tag_chains.get("recency_guard_days", 400))
    if max_age < 1:
        raise MarketExtensionError("SEC tag recency_guard_days must be positive")
    return tags, absence, max_age


def _select_metric_tag(
    symbol: str, cik: str, metric: str, facts: dict[str, Any],
    receipt: dict[str, Any], *, fallbacks: list[str], absence_status: str,
    max_age_days: int, asof: date,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Select the first fresh USD tag and retain an auditable failure state."""
    us_gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    stale: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    checked: list[dict[str, Any]] = []
    for priority, tag in enumerate(fallbacks, start=1):
        node = us_gaap.get(tag)
        if not isinstance(node, dict):
            checked.append({"tag": tag, "priority": priority, "status": "absent"})
            continue
        units = sorted((node.get("units") or {}).keys())
        if "USD" not in units:
            detail = {"tag": tag, "priority": priority,
                      "status": "unit_unsupported", "units_found": units}
            unsupported.append(detail)
            checked.append(detail)
            continue
        rows = _quarterly_rows(
            symbol, cik, metric, tag, node, receipt, asof=asof)
        if not rows:
            checked.append({"tag": tag, "priority": priority,
                            "status": "no_pit_eligible_facts"})
            continue
        max_period = max(date.fromisoformat(row["observation_period"]) for row in rows)
        age_days = (asof - max_period).days
        if age_days > max_age_days:
            detail = {
                "tag": tag, "priority": priority, "status": "tag_stale",
                "max_period": max_period.isoformat(), "age_days": age_days,
            }
            stale.append(detail)
            checked.append(detail)
            continue
        checked.append({
            "tag": tag, "priority": priority, "status": "collected",
            "max_period": max_period.isoformat(), "age_days": age_days,
        })
        return rows, {
            "status": "collected", "taxonomy_tag": tag,
            "fallbacks_checked": fallbacks, "tag_checks": checked,
            "max_period": max_period.isoformat(), "recency_days": age_days,
            "recency_guard_days": max_age_days, "unit": "USD",
            "coverage_eligible": True,
        }
    if stale:
        failure, status = stale[0], "tag_stale"
    elif unsupported:
        failure, status = unsupported[0], "unit_unsupported"
    else:
        failure, status = {}, absence_status
    return [], {
        "status": status, "taxonomy_tag": failure.get("tag"),
        "fallbacks_checked": fallbacks, "tag_checks": checked,
        "max_period": failure.get("max_period"),
        "recency_days": failure.get("age_days"),
        "recency_guard_days": max_age_days,
        "units_found": failure.get("units_found", []),
        "coverage_eligible": False,
    }


def _annual_duration_facts(
    node: dict[str, Any] | None, *, asof: date,
) -> dict[int, dict[str, Any]]:
    """Return the latest-filed full-year fact per fiscal year.

    Companyfacts mixes quarterly, year-to-date and annual durations under one
    tag, and the stored D1 rows keep only the period end.  Deriving a ratio
    from those rows could silently divide an annual numerator by a quarterly
    denominator, so this layer re-reads the source and keeps only facts whose
    own start and end span a full year.
    """
    result: dict[int, dict[str, Any]] = {}
    for fact in ((node or {}).get("units") or {}).get("USD") or []:
        start, end, filed = fact.get("start"), fact.get("end"), fact.get("filed")
        if not start or not end or not filed or fact.get("form") != "10-K":
            continue
        try:
            start_date = date.fromisoformat(str(start))
            end_date = date.fromisoformat(str(end))
            filed_date = date.fromisoformat(str(filed))
        except ValueError:
            continue
        if filed_date > asof or end_date > asof:
            continue
        span = (end_date - start_date).days
        if not ANNUAL_MIN_DAYS <= span <= ANNUAL_MAX_DAYS:
            continue
        value = fact.get("val")
        if not isinstance(value, (int, float)):
            continue
        year = end_date.year if end_date.month >= 6 else end_date.year - 1
        prior = result.get(year)
        if prior is None or str(filed) > str(prior["filed"]):
            result[year] = {
                "value": float(value), "start": start, "end": end, "filed": filed,
                "accession": fact.get("accn"), "fiscal_year": fact.get("fy"),
            }
    return result


def _latest_instant_fact(
    node: dict[str, Any] | None, *, asof: date,
) -> dict[str, Any] | None:
    """Return the most recent point-in-time balance disclosed on or before asof."""
    best: dict[str, Any] | None = None
    for fact in ((node or {}).get("units") or {}).get("USD") or []:
        if fact.get("start") or fact.get("form") not in ("10-K", "10-Q"):
            continue
        end, filed = fact.get("end"), fact.get("filed")
        if not end or not filed:
            continue
        try:
            end_date = date.fromisoformat(str(end))
            filed_date = date.fromisoformat(str(filed))
        except ValueError:
            continue
        if filed_date > asof or end_date > asof:
            continue
        value = fact.get("val")
        if not isinstance(value, (int, float)):
            continue
        if best is None or (str(end), str(filed)) > (str(best["end"]), str(best["filed"])):
            best = {
                "value": float(value), "end": end, "filed": filed,
                "accession": fact.get("accn"),
            }
    return best


def _first_available_tag(
    us_gaap: dict[str, Any], tags: list[str], *, asof: date,
) -> tuple[str | None, dict[int, dict[str, Any]]]:
    for tag in tags:
        annual = _annual_duration_facts(us_gaap.get(tag), asof=asof)
        if annual:
            return tag, annual
    return None, {}


def build_capital_intensity(
    *, contract: dict[str, Any], companyfacts: dict[str, dict[str, Any]],
    receipts: dict[str, dict[str, Any]], asof: date,
    generated_at: datetime | None = None,
    tag_chains: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive annual capital-intensity ratios and lease obligations.

    Every number is a ratio of two facts the issuer filed itself.  Nothing is
    attributed to AI: no filing separates AI spending from the rest of capital
    expenditure, so these stay whole-company measures and the payload says so
    instead of implying a split that the disclosures do not support.
    """
    made_at = (generated_at or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    companies = []
    for symbol, cik in CIKS.items():
        us_gaap = (companyfacts[symbol].get("facts") or {}).get("us-gaap") or {}
        receipt = receipts[symbol]
        resolved: dict[str, tuple[str | None, dict[int, dict[str, Any]]]] = {}
        for metric in ("capex", "operating_cashflow", "depreciation_amortization"):
            tags, _absence, _max_age = _metric_contract(
                symbol, metric, contract=contract, tag_chains=tag_chains)
            resolved[metric] = _first_available_tag(us_gaap, tags, asof=asof)
        capex_tag, capex_rows = resolved["capex"]
        ocf_tag, ocf_rows = resolved["operating_cashflow"]
        dna_tag, dna_rows = resolved["depreciation_amortization"]
        years = sorted(set(capex_rows) & set(ocf_rows))[-6:]
        annual = []
        for year in years:
            capex = capex_rows[year]["value"]
            operating = ocf_rows[year]["value"]
            depreciation = dna_rows.get(year, {}).get("value")
            annual.append({
                "fiscal_year": year,
                "period_end": capex_rows[year]["end"],
                "available_at": max(capex_rows[year]["filed"], ocf_rows[year]["filed"]),
                "capex": capex,
                "operating_cashflow": operating,
                "depreciation_amortization": depreciation,
                "free_cash_flow": operating - capex,
                "capex_to_operating_cashflow": (capex / operating) if operating else None,
                "capex_to_depreciation": (capex / depreciation) if depreciation else None,
                "accessions": {
                    "capex": capex_rows[year].get("accession"),
                    "operating_cashflow": ocf_rows[year].get("accession"),
                    "depreciation_amortization": dna_rows.get(year, {}).get("accession"),
                },
            })
        leases = {}
        for name, tag in LEASE_TAGS.items():
            fact = _latest_instant_fact(us_gaap.get(tag), asof=asof)
            leases[name] = None if fact is None else {
                "taxonomy_tag": tag, "value": fact["value"],
                "period_end": fact["end"], "available_at": fact["filed"],
                "accession": fact.get("accession"),
            }
        companies.append({
            "company": symbol, "cik": cik,
            "tags": {
                "capex": capex_tag, "operating_cashflow": ocf_tag,
                "depreciation_amortization": dna_tag,
            },
            "annual": annual,
            "lease_obligations": leases,
            "source_url": receipt["request_url"],
            "source_fingerprint": receipt["response_sha256"],
        })
    return {
        "schema_version": 1,
        "dataset_id": "ai_capital_intensity_v1",
        "asof": asof.isoformat(),
        "generated_at": made_at,
        "gate": "D2",
        "probability_space": "reference_only",
        "model_use": False,
        "official_forecast_input": False,
        "companies": companies,
        "receipts": list(receipts.values()),
        "semantics": (
            "Entity-wide annual figures as filed. Ratios divide two facts from "
            "the same fiscal year of the same filer, and full-year duration is "
            "verified against each fact's own start and end dates."
        ),
        "ai_attribution": "not_inferred",
        "caveat": (
            "\uc5b4\ub5a4 \uacf5\uc2dc\ub3c4 AI \ubaa9\uc801 \uc9c0\ucd9c\uc744 "
            "\ubcc4\ub3c4\ub85c \uad6c\ubd84\ud558\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4. "
            "\uc774 \uc218\uce58\ub294 \uc804\uc0ac \uae30\uc900\uc774\uba70 AI "
            "\ud22c\uc790\uc561\uc73c\ub85c \ud574\uc11d\ud560 \uc218 "
            "\uc5c6\uc2b5\ub2c8\ub2e4. \ub9ac\uc2a4 \ubd80\ucc44\ub294 "
            "\ubbf8\ud560\uc778 \ubbf8\ub798 \uc9c0\uae09\uc561\uc774\ub77c "
            "\ucc44\uad8c \uc794\uc561\uacfc \ub2e8\uc21c \ud569\uc0b0\ud560 "
            "\uc218 \uc5c6\uc2b5\ub2c8\ub2e4."
        ),
    }


def validate_regime_model(model: dict[str, Any]) -> dict[str, Any]:
    if model.get("probability_space") != "reference_only":
        raise MarketExtensionError("AI regime model must be reference_only")
    robust = model.get("robust_z") or {}
    if robust.get("company_window_quarters") != 20 or robust.get("macro_window_years") != 10:
        raise MarketExtensionError("AI regime robust-z windows drifted")
    if robust.get("winsor_z_bounds") != [-3, 3]:
        raise MarketExtensionError("AI regime winsor bounds drifted")
    if model.get("percentile", {}).get("start") != date(2010, 1, 1):
        raise MarketExtensionError("AI regime percentile start drifted")
    return model


def build_ai_capital_cycle(*, model: dict[str, Any], contract: dict[str, Any],
                           companyfacts: dict[str, dict[str, Any]],
                           receipts: dict[str, dict[str, Any]],
                           asof: date, generated_at: datetime | None = None,
                           tag_chains: dict[str, Any] | None = None,
                           ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    validate_regime_model(model)
    metric_names = tuple(_legacy_tag_groups(contract))
    records = []
    company_rows = []
    for symbol, cik in CIKS.items():
        facts, receipt = companyfacts[symbol], receipts[symbol]
        metrics = {}
        for metric in metric_names:
            fallbacks, absence_status, max_age = _metric_contract(
                symbol, metric, contract=contract, tag_chains=tag_chains)
            metric_rows, metric_state = _select_metric_tag(
                symbol, cik, metric, facts, receipt, fallbacks=fallbacks,
                absence_status=absence_status, max_age_days=max_age, asof=asof)
            metrics[metric] = metric_state
            records.extend(metric_rows)
        # Companyfacts intentionally excludes issuer-specific segment dimensions.
        eligible_weight = 2.0
        reported_weight = 0.0
        company_rows.append({
            "company": symbol, "cik": cik, "metrics": metrics,
            "segment_revenue": "requires_filing_level_dimension_extraction",
            "explicit_ai_revenue": "not_inferred",
            "coverage_numerator": reported_weight,
            "coverage_denominator": eligible_weight,
            "partial_contribution": 0.0,
            "disclosure_coverage": 0.0,
            "coverage_formula_version": "2026-08-03.v1",
        })
    made_at = (generated_at or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    common = {
        "schema_version": 1, "asof": asof.isoformat(), "generated_at": made_at,
        "probability_space": "reference_only", "model_version": model["model_version"],
    }
    capex = {
        **common, "status": "partial", "records": records,
        "receipts": list(receipts.values()),
        "semantics": "SEC facts preserved as filed; cumulative YTD values are not silently quarterized",
    }
    overall = sum(row["disclosure_coverage"] for row in company_rows) / len(company_rows)
    coverage = {
        **common, "gate": "D2", "status": "insufficient",
        "coverage": overall, "coverage_threshold": float(model["coverage_gate"]),
        "companies": company_rows,
        "reason": "회사별 cloud/AI segment 수익을 filing dimension으로 아직 분리하지 못했습니다.",
        "next_gate": "D3 blocked until filing-level segment extraction reaches 60% coverage",
    }
    regime = {
        **common, "status": "blocked", "coverage": overall,
        "coverage_threshold": float(model["coverage_gate"]),
        "reason": "데이터 커버리지 부족",
        "map_render_allowed": False, "coordinates": None, "trail": [],
        "company_coverage": [
            {"company": row["company"], "coverage": row["disclosure_coverage"],
             "status": "filing_segment_extraction_pending"}
            for row in company_rows
        ],
        "backfill_vintage_label": model["map"]["backfill_vintage_label"],
        "warning": "coverage 60% 미만에서는 레짐 좌표·확률·fan을 표시하지 않습니다.",
    }
    return capex, coverage, regime


def validate_ai_regime(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("probability_space") != "reference_only":
        raise MarketExtensionError("ai_regime must be reference_only")
    if float(payload.get("coverage") or 0) < float(payload.get("coverage_threshold") or .6):
        if payload.get("status") != "blocked" or payload.get("map_render_allowed") is not False:
            raise MarketExtensionError("AI regime coverage gate must block the map")
        if payload.get("coordinates") is not None or payload.get("trail"):
            raise MarketExtensionError("AI regime coordinates escaped the coverage gate")
    return payload


def refresh_ai_capital_cycle(root: Path, *, asof: date | None = None) -> dict[str, Any]:
    model = yaml.safe_load((root / MODEL_PATH).read_text(encoding="utf-8"))
    contract = yaml.safe_load((root / CONTRACT_PATH).read_text(encoding="utf-8"))
    tag_chains = yaml.safe_load((root / TAG_CHAIN_PATH).read_text(encoding="utf-8"))
    facts, receipts = {}, {}
    for symbol, cik in CIKS.items():
        facts[symbol], receipts[symbol] = _fetch_companyfacts(cik)
    cutoff = asof or date.today()
    capex, coverage, regime = build_ai_capital_cycle(
        model=model, contract=contract, tag_chains=tag_chains,
        companyfacts=facts, receipts=receipts, asof=cutoff)
    # Same fetch, one more derived view: no additional SEC requests.
    intensity = build_capital_intensity(
        contract=contract, tag_chains=tag_chains,
        companyfacts=facts, receipts=receipts, asof=cutoff)
    capex_result = _persist_json(root, CAPEX_LATEST, CAPEX_ARCHIVE, capex)
    coverage_result = _persist_json(root, COVERAGE_LATEST, COVERAGE_ARCHIVE, coverage)
    regime_result = _persist_json(root, REGIME_LATEST, REGIME_ARCHIVE, regime)
    intensity_result = _persist_json(root, INTENSITY_LATEST, INTENSITY_ARCHIVE, intensity)
    return {
        "capex_path": capex_result[0], "capex": capex_result[1],
        "coverage_path": coverage_result[0], "coverage": coverage_result[1],
        "regime_path": regime_result[0], "regime": regime_result[1],
        "intensity_path": intensity_result[0], "intensity": intensity_result[1],
        "changed": any(
            result[2] for result in
            (capex_result, coverage_result, regime_result, intensity_result)
        ),
    }


def load_ai_regime(root: Path) -> dict[str, Any]:
    try:
        return validate_ai_regime(json.loads((root / REGIME_LATEST).read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        return {
            "schema_version": 1, "status": "blocked", "asof": None,
            "probability_space": "reference_only", "coverage": 0,
            "coverage_threshold": .6, "map_render_allowed": False,
            "coordinates": None, "trail": [],
            "reason": f"데이터 커버리지 부족: {type(exc).__name__}",
        }
