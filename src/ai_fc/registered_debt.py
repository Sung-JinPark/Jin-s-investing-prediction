"""Registered debt offerings reconstructed from SEC filing-fee exhibits.

Headline figures for "AI-related debt" cannot be reproduced from any official
source: no taxonomy marks a bond as AI-related, and the circulating totals come
from privately chosen issuer lists.  What *is* reproducible is the registered
debt each named issuer actually sold, taken from the EX-FILING FEES exhibit that
every 424B/FWP prospectus has carried in inline XBRL since 2022.

This module therefore fixes the issuer list explicitly, sums only tranches the
filer itself typed as ``Debt``, and records what the method cannot see - notably
144A and private placements, which never produce a 424B and are structurally
invisible here.  The result is a downward-biased floor, and it is labelled as one.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .market_extensions import MarketExtensionError, _persist_json

# Frozen issuer list.  Changing it changes the meaning of the totals, so it is
# recorded in the payload and any change must be a deliberate, visible edit.
REGISTERED_DEBT_ISSUERS: dict[str, str] = {
    "MSFT": "0000789019",
    "GOOGL": "0001652044",
    "AMZN": "0001018724",
    "META": "0001326801",
    "ORCL": "0001341439",
}

PROSPECTUS_FORMS = ("424B2", "424B3", "424B5", "FWP")
# data/ai_buildout, not data/ai_capital_cycle: the latter is a protected root
# of the V5.2 scenario candidate and rejects new files between rebuilds.
OFFERINGS_LEDGER = Path("data/ai_buildout/registered_debt_offerings.jsonl")
DEBT_LATEST = Path("data/ai_buildout/registered_debt_latest.json")
DEBT_ARCHIVE = Path("data/ai_buildout/registered_debt_archive")

_SEC_RATE_LIMIT_SECONDS = 0.15


def _user_agent() -> str:
    return os.getenv(
        "AI_FC_SEC_USER_AGENT",
        "Jin Investing Prediction research Sung-JinPark@users.noreply.github.com",
    )


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(
        url, headers={"User-Agent": _user_agent(), "Accept-Encoding": "identity"})
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = response.read()
    time.sleep(_SEC_RATE_LIMIT_SECONDS)
    return payload


def _local_name(tag: str) -> str:
    return tag.split("}")[-1]


def parse_filing_fees(raw: bytes) -> dict[str, Any]:
    """Total the debt tranches a filing-fee exhibit declares.

    Facts are grouped by ``contextRef``: each offering row shares one context,
    so a row's security type and its amount can be paired without guessing.
    ``TtlOfferingAmt`` is only trusted when every typed row in the filing is
    debt; otherwise the debt rows are summed on their own so equity or
    convertible tranches never inflate the total.
    """
    root = ET.fromstring(raw)
    by_context: dict[str, dict[str, list[str]]] = {}
    totals: list[float] = []
    for element in root.iter():
        name = _local_name(element.tag)
        text = (element.text or "").strip()
        if not text:
            continue
        if name == "TtlOfferingAmt":
            try:
                totals.append(float(text))
            except ValueError:
                continue
            continue
        if name not in ("OfferingSctyTp", "MaxAggtOfferingPric", "AmtSctiesRegd"):
            continue
        context = element.attrib.get("contextRef", "")
        by_context.setdefault(context, {}).setdefault(name, []).append(text)

    security_types: set[str] = set()
    debt_amount = 0.0
    debt_rows = 0
    for facts in by_context.values():
        types = facts.get("OfferingSctyTp") or []
        security_types.update(types)
        if not any(value.strip().lower() == "debt" for value in types):
            continue
        amounts = facts.get("MaxAggtOfferingPric") or facts.get("AmtSctiesRegd") or []
        for amount in amounts:
            try:
                debt_amount += float(amount)
            except ValueError:
                continue
            debt_rows += 1

    all_debt = bool(security_types) and security_types <= {"Debt", "debt"}
    if all_debt and len(totals) == 1:
        return {
            "debt_amount_usd": totals[0],
            "basis": "total_offering_amount_all_rows_typed_debt",
            "security_types": sorted(security_types),
            "debt_rows": debt_rows,
        }
    return {
        "debt_amount_usd": debt_amount,
        "basis": "sum_of_debt_typed_rows",
        "security_types": sorted(security_types),
        "debt_rows": debt_rows,
    }


def _filing_index(cik: str, accession: str) -> str:
    plain = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{plain}/index.json"


def _fee_exhibit_url(cik: str, accession: str, index_payload: dict[str, Any]) -> str | None:
    plain = accession.replace("-", "")
    items = ((index_payload.get("directory") or {}).get("item")) or []
    for item in items:
        name = str(item.get("name", ""))
        if name.endswith("_htm.xml") and "exfilingfees" in name.lower():
            return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{plain}/{name}"
    return None


def collect_registered_debt(
    *, start: date, end: date,
    fetcher: Callable[[str], bytes] | None = None,
    issuers: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Return one row per prospectus that registered debt in the window."""
    fetch = fetcher or _fetch
    roster = issuers or REGISTERED_DEBT_ISSUERS
    rows: list[dict[str, Any]] = []
    for symbol, cik in roster.items():
        submissions = json.loads(
            fetch(f"https://data.sec.gov/submissions/CIK{cik}.json").decode("utf-8"))
        recent = (submissions.get("filings") or {}).get("recent") or {}
        forms = recent.get("form") or []
        filed = recent.get("filingDate") or []
        accessions = recent.get("accessionNumber") or []
        for form, filing_date, accession in zip(forms, filed, accessions):
            if form not in PROSPECTUS_FORMS:
                continue
            try:
                observed = date.fromisoformat(str(filing_date))
            except ValueError:
                continue
            if not start <= observed <= end:
                continue
            index_url = _filing_index(cik, str(accession))
            try:
                index_payload = json.loads(fetch(index_url).decode("utf-8"))
            except (OSError, ValueError):
                continue
            exhibit = _fee_exhibit_url(cik, str(accession), index_payload)
            if exhibit is None:
                # Filings before the 2022 inline-XBRL requirement, and free
                # writing prospectuses that carry no fee table, have nothing
                # machine-readable to read.  Recorded as skipped, never as zero.
                rows.append({
                    "company": symbol, "cik": cik, "accession": str(accession),
                    "form": form, "filing_date": str(filing_date),
                    "status": "no_filing_fee_exhibit", "debt_amount_usd": None,
                })
                continue
            raw = fetch(exhibit)
            parsed = parse_filing_fees(raw)
            rows.append({
                "company": symbol, "cik": cik, "accession": str(accession),
                "form": form, "filing_date": str(filing_date),
                "status": "parsed",
                "debt_amount_usd": parsed["debt_amount_usd"],
                "basis": parsed["basis"],
                "security_types": parsed["security_types"],
                "debt_rows": parsed["debt_rows"],
                "source_url": exhibit,
                "source_fingerprint": hashlib.sha256(raw).hexdigest(),
            })
    rows.sort(key=lambda row: (row["filing_date"], row["company"], row["accession"]))
    return rows


def summarize_registered_debt(
    rows: list[dict[str, Any]], *, start: date, end: date,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    made_at = (generated_at or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    # Every rostered issuer appears even with no filings, so a zero reads as a
    # measured zero rather than as a silently missing issuer.
    by_company: dict[str, dict[str, Any]] = {
        symbol: {
            "company": symbol, "cik": cik, "debt_amount_usd": 0.0,
            "filings_parsed": 0, "filings_skipped": 0,
        }
        for symbol, cik in REGISTERED_DEBT_ISSUERS.items()
    }
    for row in rows:
        entry = by_company.setdefault(row["company"], {
            "company": row["company"], "cik": row["cik"],
            "debt_amount_usd": 0.0, "filings_parsed": 0, "filings_skipped": 0,
        })
        if row["status"] == "parsed" and row.get("debt_amount_usd"):
            entry["debt_amount_usd"] += float(row["debt_amount_usd"])
            entry["filings_parsed"] += 1
        elif row["status"] != "parsed":
            entry["filings_skipped"] += 1
    for entry in by_company.values():
        if entry["filings_parsed"] == 0 and entry["filings_skipped"] > 0:
            # The issuer filed prospectuses this window but none carried a
            # machine-readable fee table, so its total is unmeasured, not zero.
            entry["coverage"] = "no_machine_readable_fee_table_in_window"
        elif entry["filings_parsed"] == 0:
            entry["coverage"] = "no_registered_prospectus_in_window"
        else:
            entry["coverage"] = "measured"
    companies = [by_company[key] for key in sorted(by_company)]
    return {
        "schema_version": 1,
        "dataset_id": "registered_debt_offerings_v1",
        "generated_at": made_at,
        "asof": end.isoformat(),
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "gate": "D2",
        "probability_space": "reference_only",
        "model_use": False,
        "official_forecast_input": False,
        "issuer_list_frozen": {symbol: cik for symbol, cik in REGISTERED_DEBT_ISSUERS.items()},
        "companies": companies,
        "total_debt_amount_usd": sum(row["debt_amount_usd"] for row in companies),
        "ai_attribution": "not_inferred",
        "measured_issuers": [
            row["company"] for row in companies if row["coverage"] == "measured"
        ],
        "unmeasured_issuers": [
            row["company"] for row in companies if row["coverage"] != "measured"
        ],
        "coverage_limits": [
            "144A 및 사모 발행은 424B를 남기지 않으므로 구조적으로 보이지 않는다 — 이 합계는 하한이다.",
            "EX-FILING FEES 인라인 XBRL은 2022년부터 의무이므로 그 이전 발행은 집계되지 않는다.",
            "발행사 리스트는 사전 고정값이며, 어떤 공식 분류도 채권을 AI 목적으로 표시하지 않는다.",
            "일부 발행사(예: Amazon)는 424B에 기계판독 가능한 수수료 표를 첨부하지 않아 발행액이 "
            "집계되지 않는다. 이 경우 coverage 필드가 unmeasured로 표시되며 0으로 읽으면 안 된다.",
            "따라서 발행사 간 합계 비교는 measured 커버리지를 가진 발행사끼리만 유효하다.",
        ],
    }


def refresh_registered_debt(
    root: Path, *, start: date, end: date,
    fetcher: Callable[[str], bytes] | None = None,
    issuers: dict[str, str] | None = None,
) -> dict[str, Any]:
    rows = collect_registered_debt(
        start=start, end=end, fetcher=fetcher, issuers=issuers)
    ledger = root / OFFERINGS_LEDGER
    ledger.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, dict[str, Any]] = {}
    if ledger.is_file():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            if line:
                prior = json.loads(line)
                existing[str(prior["accession"])] = prior
    appended = 0
    with ledger.open("a", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            key = str(row["accession"])
            prior = existing.get(key)
            if prior is not None:
                if prior != row:
                    raise MarketExtensionError(
                        f"append-only conflict for registered debt filing {key}")
                continue
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")) + "\n")
            existing[key] = row
            appended += 1
    summary = summarize_registered_debt(list(existing.values()), start=start, end=end)
    path, payload, changed = _persist_json(root, DEBT_LATEST, DEBT_ARCHIVE, summary)
    return {
        "path": path, "summary": payload, "changed": changed,
        "rows_appended": appended, "rows_total": len(existing),
    }
