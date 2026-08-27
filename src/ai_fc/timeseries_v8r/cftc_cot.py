"""Official CFTC TFF collection with conservative point-in-time availability."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import gzip
import hashlib
import json
from pathlib import Path
from typing import Iterable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


DATASET = "gpe5-46if"
ENDPOINT = f"https://publicreporting.cftc.gov/resource/{DATASET}.json"
MARKETS = {
    "209742": "CFTC_NQ_LEV_NET_SHARE",
    "13874A": "CFTC_ES_LEV_NET_SHARE",
    "1170E1": "CFTC_VIX_LEV_NET_SHARE",
}
NEW_YORK = ZoneInfo("America/New_York")


def release_timestamp(report_date: date) -> datetime:
    """Return the contract-fixed Friday 15:30 ET availability timestamp."""
    # Holiday weeks can move the positions-as-of date to Monday or Wednesday.
    # Preserve that source date and bind availability to the same week's Friday.
    if report_date.weekday() not in (0, 1, 2):
        raise ValueError("CFTC TFF report date must be Monday, Tuesday, or Wednesday")
    days_to_friday = 4 - report_date.weekday()
    local = datetime.combine(
        report_date + timedelta(days=days_to_friday), time(15, 30), NEW_YORK
    )
    return local.astimezone(timezone.utc)


def build_query_url(*, limit: int = 50_000, offset: int = 0,
                    start_date: date | None = None) -> str:
    if limit <= 0 or offset < 0:
        raise ValueError("invalid pagination")
    codes = ",".join(f"'{code}'" for code in MARKETS)
    where = f"cftc_contract_market_code in({codes})"
    if start_date is not None:
        where += f" AND report_date_as_yyyy_mm_dd >= '{start_date.isoformat()}T00:00:00.000'"
    params = {
        "$where": where,
        "$order": "report_date_as_yyyy_mm_dd,cftc_contract_market_code,id",
        "$limit": str(limit),
        "$offset": str(offset),
    }
    return ENDPOINT + "?" + urlencode(params)


def fetch_official_rows(*, limit: int = 50_000,
                        start_date: date | None = None) -> tuple[bytes, list[dict[str, str]], str]:
    url = build_query_url(limit=limit, start_date=start_date)
    request = Request(url, headers={"User-Agent": "AI-Investing-V8R-Research/1.0"})
    with urlopen(request, timeout=90) as response:  # noqa: S310 - fixed HTTPS endpoint
        raw = response.read()
        if response.status != 200:
            raise RuntimeError(f"CFTC HTTP status {response.status}")
    rows = json.loads(raw)
    if not isinstance(rows, list):
        raise ValueError("CFTC response must be a JSON array")
    if len(rows) >= limit:
        raise RuntimeError("CFTC result reached page limit; pagination is required")
    return raw, rows, url


def _number(row: Mapping[str, str], field: str) -> float:
    try:
        return float(row[field])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"missing or invalid CFTC field: {field}") from exc


def row_to_fact(row: Mapping[str, str], *, receipt_sha256: str,
                supersedes_fact_id: str | None = None) -> dict[str, object]:
    code = str(row.get("cftc_contract_market_code", "")).strip()
    if code not in MARKETS:
        raise ValueError(f"unexpected CFTC market code: {code}")
    report_day = datetime.fromisoformat(str(row["report_date_as_yyyy_mm_dd"])).date()
    available_at = release_timestamp(report_day)
    open_interest = _number(row, "open_interest_all")
    if open_interest <= 0:
        raise ValueError("open_interest_all must be positive")
    value = (_number(row, "lev_money_positions_long")
             - _number(row, "lev_money_positions_short")) / open_interest
    identity = {
        "series_id": MARKETS[code],
        "observed_at": report_day.isoformat(),
        "available_at": available_at.isoformat().replace("+00:00", "Z"),
        "value": round(value, 12),
        "source_row_id": str(row["id"]),
        "receipt_sha256": receipt_sha256,
    }
    fact_id = hashlib.sha256(json.dumps(
        identity, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    return {
        "schema": "v8r_observation_fact_v1",
        "fact_id": fact_id,
        **identity,
        "source_id": "cftc_cot",
        "data_grade": "native_release_archive",
        "unit": "fraction_of_open_interest",
        "probability_unit": None,
        "market_code": code,
        "market_name": str(row.get("market_and_exchange_names", "")),
        "revision": 1 if supersedes_fact_id is None else 2,
        "supersedes": supersedes_fact_id,
        "publication_rule": "Weekly report-date positions available same-week Friday 15:30 America/New_York",
    }


def materialize_facts(rows: Iterable[Mapping[str, str]], *, receipt_sha256: str,
                      existing: Iterable[Mapping[str, object]] = ()) -> tuple[list[dict[str, object]], int]:
    latest: dict[tuple[str, str], Mapping[str, object]] = {}
    exact: set[tuple[str, str, float]] = set()
    for fact in existing:
        key = (str(fact["series_id"]), str(fact["observed_at"]))
        latest[key] = fact
        exact.add((key[0], key[1], float(fact["value"])))
    appended: list[dict[str, object]] = []
    duplicate_count = 0
    for row in rows:
        preliminary = row_to_fact(row, receipt_sha256=receipt_sha256)
        key = (str(preliminary["series_id"]), str(preliminary["observed_at"]))
        value_key = (key[0], key[1], float(preliminary["value"]))
        if value_key in exact:
            duplicate_count += 1
            continue
        prior = latest.get(key)
        fact = row_to_fact(
            row,
            receipt_sha256=receipt_sha256,
            supersedes_fact_id=str(prior["fact_id"]) if prior else None,
        )
        if prior:
            fact["revision"] = int(prior.get("revision", 1)) + 1
        latest[key] = fact
        exact.add(value_key)
        appended.append(fact)
    appended.sort(key=lambda fact: (str(fact["observed_at"]), str(fact["series_id"])))
    return appended, duplicate_count


def collect_to_repository(repo_root: str | Path) -> dict[str, object]:
    root = Path(repo_root)
    cursor_path = root / "data" / "timeseries_v8r" / "cursors" / "cftc_cot.json"
    start_date: date | None = None
    if cursor_path.exists():
        cursor = json.loads(cursor_path.read_text(encoding="utf-8"))
        last_report = date.fromisoformat(str(cursor["last_report_date"]))
        # Re-read a short official correction window without re-fetching full history.
        start_date = last_report - timedelta(days=14)
    raw, rows, url = fetch_official_rows(start_date=start_date)
    raw_sha = hashlib.sha256(raw).hexdigest()
    raw_dir = root / "data" / "timeseries_v8r" / "raw" / "cftc_cot"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"{raw_sha}.json.gz"
    if not raw_path.exists():
        raw_path.write_bytes(gzip.compress(raw, mtime=0))

    facts_path = root / "data" / "timeseries_v8r" / "facts" / "cftc_cot.jsonl"
    existing: list[dict[str, object]] = []
    if facts_path.exists():
        existing = [json.loads(line) for line in facts_path.read_text(encoding="utf-8").splitlines()
                    if line.strip()]
    appended, duplicate_count = materialize_facts(
        rows, receipt_sha256=raw_sha, existing=existing
    )
    facts_path.parent.mkdir(parents=True, exist_ok=True)
    if appended:
        with facts_path.open("a", encoding="utf-8", newline="\n") as handle:
            for fact in appended:
                handle.write(json.dumps(fact, ensure_ascii=False, sort_keys=True,
                                        separators=(",", ":")) + "\n")

    receipt = {
        "schema": "v8r_collection_receipt_v1",
        "source_id": "cftc_cot",
        "dataset": DATASET,
        "endpoint": ENDPOINT,
        "request_url": url,
        "raw_sha256": raw_sha,
        "raw_bytes": len(raw),
        "response_rows": len(rows),
        "appended_facts": len(appended),
        "duplicate_rows": duplicate_count,
        "market_codes": sorted(MARKETS),
        "collected_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "credentials_used": False,
        "incremental_start_date": start_date.isoformat() if start_date else None,
    }
    receipt_dir = root / "data" / "timeseries_v8r" / "receipts" / "cftc_cot"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_body = json.dumps(receipt, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":")).encode("utf-8")
    receipt_sha = hashlib.sha256(receipt_body).hexdigest()
    receipt_path = receipt_dir / f"{receipt_sha}.json"
    if not receipt_path.exists():
        receipt_path.write_bytes(receipt_body + b"\n")
    receipt["receipt_sha256"] = receipt_sha
    receipt["receipt_path"] = str(receipt_path.relative_to(root)).replace("\\", "/")
    report_dates = [
        datetime.fromisoformat(str(row["report_date_as_yyyy_mm_dd"])).date()
        for row in rows
    ]
    if report_dates:
        cursor_path.parent.mkdir(parents=True, exist_ok=True)
        cursor_payload = {
            "schema": "v8r_incremental_cursor_v1",
            "source_id": "cftc_cot",
            "last_report_date": max(report_dates).isoformat(),
            "correction_window_days": 14,
            "last_receipt_sha256": receipt_sha,
            "updated_at": receipt["collected_at"],
        }
        cursor_path.write_text(
            json.dumps(cursor_payload, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
    return receipt


def verify_repository_collection(repo_root: str | Path) -> dict[str, object]:
    """Independently verify stored raw objects, receipts, and PIT facts."""
    root = Path(repo_root)
    base = root / "data" / "timeseries_v8r"
    raw_dir = base / "raw" / "cftc_cot"
    receipt_dir = base / "receipts" / "cftc_cot"
    facts_path = base / "facts" / "cftc_cot.jsonl"
    cursor_path = base / "cursors" / "cftc_cot.json"

    raw_hashes: set[str] = set()
    raw_checks: list[dict[str, object]] = []
    for path in sorted(raw_dir.glob("*.json.gz")):
        payload = gzip.decompress(path.read_bytes())
        actual = hashlib.sha256(payload).hexdigest()
        matches = actual == path.stem.removesuffix(".json")
        raw_checks.append({
            "path": str(path.relative_to(root)).replace("\\", "/"),
            "raw_sha256": actual,
            "hash_matches_filename": matches,
            "uncompressed_bytes": len(payload),
        })
        if matches:
            raw_hashes.add(actual)

    receipts: list[dict[str, object]] = []
    receipt_hashes: set[str] = set()
    receipt_raw_hashes: set[str] = set()
    for path in sorted(receipt_dir.glob("*.json")):
        raw_bytes = path.read_bytes()
        logical = raw_bytes.rstrip(b"\r\n")
        actual = hashlib.sha256(logical).hexdigest()
        payload = json.loads(logical)
        matches = actual == path.stem
        receipts.append({
            "path": str(path.relative_to(root)).replace("\\", "/"),
            "receipt_sha256": actual,
            "hash_matches_filename": matches,
            "raw_sha256": payload.get("raw_sha256"),
            "response_rows": payload.get("response_rows"),
            "appended_facts": payload.get("appended_facts"),
            "duplicate_rows": payload.get("duplicate_rows"),
        })
        if matches:
            receipt_hashes.add(actual)
        if payload.get("raw_sha256") in raw_hashes:
            receipt_raw_hashes.add(str(payload["raw_sha256"]))

    facts = [
        json.loads(line)
        for line in facts_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    fact_ids: set[str] = set()
    identities: set[tuple[str, str, float]] = set()
    duplicate_fact_ids = 0
    duplicate_identities = 0
    pit_violations = 0
    lineage_violations = 0
    unit_violations = 0
    series_counts = {series: 0 for series in MARKETS.values()}
    observed_dates: list[date] = []
    for fact in facts:
        fact_id = str(fact["fact_id"])
        if fact_id in fact_ids:
            duplicate_fact_ids += 1
        fact_ids.add(fact_id)
        identity = (
            str(fact["series_id"]),
            str(fact["observed_at"]),
            float(fact["value"]),
        )
        if identity in identities:
            duplicate_identities += 1
        identities.add(identity)
        series_id = str(fact["series_id"])
        if series_id in series_counts:
            series_counts[series_id] += 1
        observed = date.fromisoformat(str(fact["observed_at"]))
        observed_dates.append(observed)
        expected = release_timestamp(observed).isoformat().replace("+00:00", "Z")
        if str(fact["available_at"]) != expected:
            pit_violations += 1
        # The current fact schema uses receipt_sha256 as the content-addressed
        # raw-object receipt key. At least one immutable collection receipt must
        # attest that same raw object.
        raw_receipt_key = str(fact["receipt_sha256"])
        if raw_receipt_key not in receipt_raw_hashes:
            lineage_violations += 1
        if fact.get("unit") != "fraction_of_open_interest":
            unit_violations += 1

    cursor = json.loads(cursor_path.read_text(encoding="utf-8"))
    checks = {
        "raw_hashes_valid": bool(raw_checks) and all(
            item["hash_matches_filename"] for item in raw_checks
        ),
        "receipt_hashes_valid": bool(receipts) and all(
            item["hash_matches_filename"] for item in receipts
        ),
        "fact_count_positive": len(facts) > 0,
        "all_three_series_present": all(count > 0 for count in series_counts.values()),
        "duplicate_fact_ids_zero": duplicate_fact_ids == 0,
        "duplicate_identities_zero": duplicate_identities == 0,
        "pit_violations_zero": pit_violations == 0,
        "lineage_violations_zero": lineage_violations == 0,
        "unit_violations_zero": unit_violations == 0,
        "cursor_source_matches": cursor.get("source_id") == "cftc_cot",
    }
    return {
        "schema": "v8r_cftc_collection_verification_v1",
        "source_id": "cftc_cot",
        "verified_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "fact_count": len(facts),
        "series_counts": series_counts,
        "observed_date_min": min(observed_dates).isoformat() if observed_dates else None,
        "observed_date_max": max(observed_dates).isoformat() if observed_dates else None,
        "raw_object_count": len(raw_checks),
        "receipt_count": len(receipts),
        "duplicate_fact_ids": duplicate_fact_ids,
        "duplicate_identities": duplicate_identities,
        "pit_violations": pit_violations,
        "lineage_violations": lineage_violations,
        "unit_violations": unit_violations,
        "cursor": cursor,
        "raw_objects": raw_checks,
        "receipts": receipts,
        "checks": checks,
        "pass": all(checks.values()),
    }
