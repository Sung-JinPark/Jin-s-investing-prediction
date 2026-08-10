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
    capex_result = _persist_json(root, CAPEX_LATEST, CAPEX_ARCHIVE, capex)
    coverage_result = _persist_json(root, COVERAGE_LATEST, COVERAGE_ARCHIVE, coverage)
    regime_result = _persist_json(root, REGIME_LATEST, REGIME_ARCHIVE, regime)
    return {
        "capex_path": capex_result[0], "capex": capex_result[1],
        "coverage_path": coverage_result[0], "coverage": coverage_result[1],
        "regime_path": regime_result[0], "regime": regime_result[1],
        "changed": any(result[2] for result in (capex_result, coverage_result, regime_result)),
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
