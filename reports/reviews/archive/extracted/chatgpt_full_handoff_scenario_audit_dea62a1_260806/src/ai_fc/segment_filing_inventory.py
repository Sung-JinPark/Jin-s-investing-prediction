"""SEC filing-accession inventory for the deferred L1-1 segment extractor.

This round stops at accession metadata.  It does not parse, infer, or publish a
single segment value, so the coverage gate remains blocked by construction.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .ai_capital_cycle import CIKS

LATEST = Path("data/ai_capital_cycle/segment_filing_accessions_latest.json")
ARCHIVE = Path("data/ai_capital_cycle/segment_filing_accessions_archive")
FORMS = {"10-Q", "10-K"}
ROWS_PER_COMPANY = 12


class SegmentInventoryError(ValueError):
    """SEC inventory or append-only persistence violation."""


def _user_agent() -> str:
    return os.getenv(
        "AI_FC_SEC_USER_AGENT",
        "Jin Investing Prediction research Sung-JinPark@users.noreply.github.com",
    )


def _fetch_submissions(cik: str) -> tuple[dict[str, Any], dict[str, Any]]:
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    request = urllib.request.Request(
        url, headers={"User-Agent": _user_agent(), "Accept-Encoding": "identity"})
    with urllib.request.urlopen(request, timeout=90) as response:
        raw = response.read()
    payload = json.loads(raw)
    if str(payload.get("cik", "")).zfill(10) != cik:
        raise SegmentInventoryError(f"SEC submissions CIK mismatch for {cik}")
    return payload, {
        "source": "sec_edgar_submissions", "request_url": url,
        "response_sha256": hashlib.sha256(raw).hexdigest(),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "revision_vintage": "sec_filing_native",
    }


def _committed_companyfacts_fallback(
    root: Path, symbol: str, cik: str, error: Exception,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Recover only already-audited accessions when SEC submissions is unavailable."""
    path = root / "data/ai_capital_cycle/company_capex_quarterly_latest.json"
    raw = path.read_bytes()
    records = json.loads(raw).get("records") or []
    by_accession = {}
    for row in records:
        if row.get("company") != symbol or row.get("form") not in FORMS or not row.get("accession"):
            continue
        accession = str(row["accession"])
        current = by_accession.get(accession)
        if current is None or str(row.get("available_at") or "") > str(
                current.get("available_at") or ""):
            by_accession[accession] = row
    selected = sorted(
        by_accession.values(), key=lambda row: str(row.get("available_at") or ""),
        reverse=True,
    )
    recent = {key: [] for key in (
        "accessionNumber", "filingDate", "reportDate", "form", "primaryDocument")}
    for row in selected:
        recent["accessionNumber"].append(row["accession"])
        recent["filingDate"].append(row.get("available_at") or row.get("observation_period"))
        recent["reportDate"].append(row.get("observation_period"))
        recent["form"].append(row["form"])
        recent["primaryDocument"].append(None)
    return ({"cik": int(cik), "filings": {"recent": recent}}, {
        "source": "committed_sec_companyfacts_fallback",
        "request_url": path.relative_to(root).as_posix(),
        "response_sha256": hashlib.sha256(raw).hexdigest(),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "revision_vintage": "committed_filing_native_accessions",
        "upstream_status": "sec_submissions_unavailable",
        "upstream_error": type(error).__name__,
    })


def _filing_rows(
    symbol: str, cik: str, payload: dict[str, Any], *, asof: date,
) -> list[dict[str, Any]]:
    recent = ((payload.get("filings") or {}).get("recent") or {})
    fields = ("accessionNumber", "filingDate", "reportDate", "form", "primaryDocument")
    columns = {field: list(recent.get(field) or []) for field in fields}
    lengths = {len(values) for values in columns.values()}
    if len(lengths) != 1:
        raise SegmentInventoryError(f"SEC recent filing arrays mismatch for {symbol}")
    rows = []
    for values in zip(*(columns[field] for field in fields), strict=True):
        row = dict(zip(fields, values, strict=True))
        if row["form"] not in FORMS or not row["filingDate"]:
            continue
        filing_day = date.fromisoformat(str(row["filingDate"]))
        if filing_day > asof:
            continue
        accession = str(row["accessionNumber"])
        compact = accession.replace("-", "")
        rows.append({
            "company": symbol, "cik": cik, "form": row["form"],
            "filing_date": filing_day.isoformat(),
            "report_date": row["reportDate"] or None,
            "accession": accession, "primary_document": row["primaryDocument"],
            "filing_index_url": (
                f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{compact}/"
                f"{accession}-index.html"),
            "inventory_scope": "accession_only",
            "segment_extraction_status": "not_started",
            "segment_rows": [],
        })
        if len(rows) == ROWS_PER_COMPANY:
            break
    return rows


def build_inventory(
    *, asof: date, submissions: dict[str, tuple[dict[str, Any], dict[str, Any]]],
) -> dict[str, Any]:
    companies = {}
    receipts = []
    for symbol, cik in CIKS.items():
        payload, receipt = submissions[symbol]
        rows = _filing_rows(symbol, cik, payload, asof=asof)
        companies[symbol] = {
            "cik": cik, "filing_count": len(rows), "filings": rows,
            "segment_extraction_status": "not_started",
        }
        receipts.append(deepcopy(receipt))
    result = {
        "schema_version": 1, "asof": asof.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "accession_inventory_complete" if all(
            row["filing_count"] == ROWS_PER_COMPANY for row in companies.values())
        else "partial",
        "probability_space": "reference_only", "scope": "L1-1_preparation_only",
        "companies": companies, "receipts": receipts,
        "coverage_gate_effect": "none_segment_values_not_extracted",
        "warning": "최근 12개 10-Q/K accession 목록만 보존하며 세그먼트 수치는 추출하지 않았습니다.",
    }
    validate_inventory(result)
    return result


def validate_inventory(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("probability_space") != "reference_only":
        raise SegmentInventoryError("segment inventory must be reference_only")
    if set(payload.get("companies") or {}) != set(CIKS):
        raise SegmentInventoryError("segment inventory requires exactly four companies")
    for symbol, company in payload["companies"].items():
        rows = company.get("filings") or []
        if len(rows) > ROWS_PER_COMPANY:
            raise SegmentInventoryError(f"too many filings for {symbol}")
        if company.get("segment_extraction_status") != "not_started":
            raise SegmentInventoryError("L1-1 extraction started outside approved scope")
        for row in rows:
            if row.get("form") not in FORMS or row.get("segment_rows") != []:
                raise SegmentInventoryError("accession inventory cannot contain segment values")
    return payload


def _semantic(payload: dict[str, Any]) -> str:
    value = deepcopy(payload)
    value.pop("generated_at", None)
    for receipt in value.get("receipts") or []:
        receipt.pop("fetched_at", None)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def persist_inventory(root: Path, payload: dict[str, Any]) -> tuple[Path, bool]:
    validate_inventory(payload)
    latest = root / LATEST
    archive = root / ARCHIVE / f"{payload['asof']}.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    archive.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if payload.get("status") != "accession_inventory_complete":
        if latest.exists():
            existing = json.loads(latest.read_text(encoding="utf-8"))
            if _semantic(existing) == _semantic(payload):
                return latest, False
        latest.write_text(serialized, encoding="utf-8", newline="\n")
        return latest, True
    if archive.exists():
        existing = json.loads(archive.read_text(encoding="utf-8"))
        if _semantic(existing) != _semantic(payload):
            raise SegmentInventoryError(f"immutable accession inventory conflict: {archive}")
        prior = archive.read_text(encoding="utf-8")
        changed = not latest.exists() or latest.read_text(encoding="utf-8") != prior
        if changed:
            latest.write_text(prior, encoding="utf-8", newline="\n")
        return latest, changed
    archive.write_text(serialized, encoding="utf-8", newline="\n")
    latest.write_text(serialized, encoding="utf-8", newline="\n")
    return latest, True


def refresh_inventory(root: Path, asof: date | None = None) -> tuple[Path, dict[str, Any], bool]:
    cutoff = asof or date.today()
    submissions = {}
    for symbol, cik in CIKS.items():
        try:
            submissions[symbol] = _fetch_submissions(cik)
        except Exception as exc:  # noqa: BLE001 - explicit, audited partial fallback
            submissions[symbol] = _committed_companyfacts_fallback(
                root, symbol, cik, exc)
    payload = build_inventory(asof=cutoff, submissions=submissions)
    path, changed = persist_inventory(root, payload)
    return path, payload, changed
