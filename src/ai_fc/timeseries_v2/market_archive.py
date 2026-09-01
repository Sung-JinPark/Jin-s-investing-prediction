"""Official reconstructed market archives with raw-first append-only lineage.

Historical market closes and yields are exact observations but are not ALFRED
vintages.  They are therefore stored as ``reconstructed_market_archive`` and
never described as native PIT.  A conservative post-close ``available_at`` is
used for rolling-origin alignment.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .contracts import LEDGER_RELATIVE, PARQUET_RELATIVE, RAW_RELATIVE, canonical_hash
from ..fred_api import FredApiError


ARCHIVE_RECEIPTS = LEDGER_RELATIVE / "market_raw_receipts.jsonl"
ARCHIVE_FACTS = LEDGER_RELATIVE / "market_observations.jsonl"
PARSER_VERSION = "official-market-archive-v2.1"


class MarketArchiveError(RuntimeError):
    """Official archive collection or append-only validation failed."""


class MarketRawReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    receipt_id: str
    source_id: str
    source_uri: str
    retrieved_at: str
    http_status: int
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_path: str
    request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_type: str
    redistribution: Literal["repository_raw_allowed", "private_locator_only"]


class MarketObservationV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    observation_id: str
    source_id: str
    series_id: str
    observation_time: str
    value: float
    unit: str
    available_at: str
    data_grade: Literal["native_pit", "reconstructed_market_archive", "captured_forward"]
    vintage_start: str
    vintage_end: str | None = None
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_id: str
    revision_seq: int = Field(ge=1)
    supersedes: str | None = None
    parser_version: str

    @field_validator("value")
    @classmethod
    def finite_value(cls, value: float) -> float:
        if not (-1e300 < value < 1e300):
            raise ValueError("market observation must be finite")
        return value


def _append_jsonl(path: Path, rows: Iterable[dict[str, Any]], *, identity: str) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: set[str] = set()
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line:
                existing.add(str(json.loads(line)[identity]))
    pending = [row for row in rows if str(row[identity]) not in existing]
    if not pending:
        return 0
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for row in pending:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return len(pending)


def _request_fingerprint(url: str) -> str:
    redacted = re.sub(r"(?i)(api_key|token|key)=[^&]+", r"\1=REDACTED", url)
    return hashlib.sha256(redacted.encode("utf-8")).hexdigest()


def persist_market_raw(
    root: Path, *, source_id: str, source_uri: str, payload: bytes,
    retrieved_at: str, http_status: int = 200, content_type: str = "text/csv",
    redistribution: Literal["repository_raw_allowed", "private_locator_only"] = "repository_raw_allowed",
) -> MarketRawReceipt:
    digest = hashlib.sha256(payload).hexdigest()
    fingerprint = _request_fingerprint(source_uri)
    receipt_seed = {
        "source_id": source_id, "source_uri": re.sub(r"(?i)(api_key|token|key)=[^&]+", r"\1=REDACTED", source_uri),
        "retrieved_at": retrieved_at, "raw_sha256": digest, "request_fingerprint": fingerprint,
    }
    receipt_id = f"market-receipt-{canonical_hash(receipt_seed)[:24]}"
    if redistribution == "repository_raw_allowed":
        relative = RAW_RELATIVE / "market" / source_id / f"{digest}.gz"
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            temporary = target.with_suffix(".tmp")
            with temporary.open("wb") as raw_handle:
                with gzip.GzipFile(filename="", mode="wb", fileobj=raw_handle, mtime=0) as zipped:
                    zipped.write(payload)
            os.replace(temporary, target)
        raw_path = relative.as_posix()
    else:
        raw_path = f"private://timeseries-v2/{source_id}/{digest}"
    receipt = MarketRawReceipt(
        receipt_id=receipt_id,
        source_id=source_id,
        source_uri=receipt_seed["source_uri"],
        retrieved_at=retrieved_at,
        http_status=http_status,
        raw_sha256=digest,
        raw_path=raw_path,
        request_fingerprint=fingerprint,
        content_type=content_type,
        redistribution=redistribution,
    )
    _append_jsonl(
        root / ARCHIVE_RECEIPTS, [receipt.model_dump(mode="json")], identity="receipt_id",
    )
    return receipt


def _fetch(url: str, *, timeout: int = 120) -> tuple[int, bytes, str]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "AI-Investing-Research/2.0 contact=repository-maintainer"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return int(response.status), response.read(), response.headers.get_content_type()


def _market_available_at(day: str) -> str:
    local = datetime.combine(date.fromisoformat(day), time(16, 15), tzinfo=ZoneInfo("America/New_York"))
    return local.astimezone(timezone.utc).isoformat(timespec="seconds")


def _treasury_available_at(day: str) -> str:
    local = datetime.combine(date.fromisoformat(day), time(18, 0), tzinfo=ZoneInfo("America/New_York"))
    return local.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_fred_graph_csv(payload: bytes, *, series_id: str) -> list[tuple[str, float]]:
    text = payload.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    rows: list[tuple[str, float]] = []
    for row in reader:
        day = str(row.get("observation_date") or row.get("DATE") or "").strip()
        raw = str(row.get(series_id) or row.get("VALUE") or "").strip()
        if not day or raw in {"", "."}:
            continue
        rows.append((day, float(raw)))
    return rows


def parse_cboe_vix_csv(payload: bytes) -> list[tuple[str, float]]:
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
    rows: list[tuple[str, float]] = []
    for row in reader:
        raw_day = str(row.get("DATE") or row.get("Date") or "").strip()
        raw_close = str(row.get("CLOSE") or row.get("Close") or "").strip()
        if not raw_day or not raw_close:
            continue
        parsed = datetime.strptime(raw_day, "%m/%d/%Y").date().isoformat()
        rows.append((parsed, float(raw_close)))
    return rows


def parse_treasury_xml(payload: bytes) -> list[tuple[str, float, float]]:
    root = ET.fromstring(payload)
    output: list[tuple[str, float, float]] = []
    for properties in root.findall(".//{*}properties"):
        values = {node.tag.split("}")[-1]: (node.text or "").strip() for node in properties}
        raw_day = values.get("NEW_DATE") or values.get("Date") or values.get("date")
        two = values.get("BC_2YEAR") or values.get("BC_2_YEAR")
        ten = values.get("BC_10YEAR") or values.get("BC_10_YEAR")
        if not raw_day or not two or not ten:
            continue
        day = datetime.fromisoformat(raw_day.replace("Z", "+00:00")).date().isoformat()
        output.append((day, float(two), float(ten)))
    return output


def parse_fed_ebp_csv(payload: bytes) -> list[tuple[str, float]]:
    """Parse the Fed's revision-prone monthly excess bond premium release."""
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
    rows: list[tuple[str, float]] = []
    for row in reader:
        raw_day = str(row.get("date") or "").strip()
        raw_value = str(row.get("ebp") or "").strip()
        if not raw_day or raw_value in {"", "."}:
            continue
        day = datetime.strptime(raw_day, "%m/%d/%Y").date().isoformat()
        rows.append((day, float(raw_value)))
    return rows


def _current_facts(root: Path) -> list[MarketObservationV2]:
    path = root / ARCHIVE_FACTS
    if not path.is_file():
        return []
    return [
        MarketObservationV2.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines() if line
    ]


def _append_observations(
    root: Path, *, source_id: str, series_id: str, unit: str,
    values: Iterable[tuple[str, float]], receipt: MarketRawReceipt,
    available_at: Callable[[str], str],
    data_grade: Literal["reconstructed_market_archive", "captured_forward"] = "reconstructed_market_archive",
) -> dict[str, int]:
    existing = _current_facts(root)
    latest: dict[tuple[str, str], MarketObservationV2] = {}
    for row in existing:
        key = (row.series_id, row.observation_time)
        if key not in latest or row.revision_seq > latest[key].revision_seq:
            latest[key] = row
    pending: list[MarketObservationV2] = []
    unchanged = 0
    for day, value in sorted(values):
        key = (series_id, day)
        prior = latest.get(key)
        if prior is not None and prior.value == float(value) and prior.unit == unit:
            unchanged += 1
            continue
        revision = 1 if prior is None else prior.revision_seq + 1
        seed = {
            "source_id": source_id, "series_id": series_id, "observation_time": day,
            "value": float(value), "unit": unit, "receipt_id": receipt.receipt_id,
            "revision_seq": revision, "supersedes": None if prior is None else prior.observation_id,
        }
        row_available_at = (
            available_at(day)
            if prior is None and data_grade == "reconstructed_market_archive"
            else receipt.retrieved_at
        )
        row = MarketObservationV2(
            observation_id=f"market-observation-{canonical_hash(seed)[:24]}",
            source_id=source_id,
            series_id=series_id,
            observation_time=day,
            value=float(value),
            unit=unit,
            available_at=row_available_at,
            data_grade=data_grade,
            vintage_start=receipt.retrieved_at,
            raw_sha256=receipt.raw_sha256,
            receipt_id=receipt.receipt_id,
            revision_seq=revision,
            supersedes=None if prior is None else prior.observation_id,
            parser_version=PARSER_VERSION,
        )
        pending.append(row)
        latest[key] = row
    appended = _append_jsonl(
        root / ARCHIVE_FACTS,
        [row.model_dump(mode="json") for row in pending],
        identity="observation_id",
    )
    return {"appended": appended, "unchanged": unchanged, "received": appended + unchanged}


# FRED-hosted series go through the official API (DECISIONS 12-6): the old
# fredgraph.csv scrape is a terms-of-use violation AND was observed serving
# observations ~10 days behind the API (NASDAQCOM stuck at 8/19 while the API
# carried 8/28), which starved the V8 operational freshness gate.  The "url"
# recorded here and on receipts is the KEYLESS public form; the key only ever
# rides the transport inside ai_fc.fred_api.
MARKET_ARCHIVE_SPECS: dict[str, dict[str, str]] = {
    "NASDAQCOM": {
        "source_id": "fred_nasdaqcom_archive",
        "fred_observation_start": "1995-01-01",
        "url": "https://api.stlouisfed.org/fred/series/observations?series_id=NASDAQCOM&file_type=json&observation_start=1995-01-01",
    },
    "VIX": {
        "source_id": "cboe_vix_archive",
        "url": "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv",
    },
    "TREASURY": {
        "source_id": "us_treasury_yield_archive",
        "url": "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value={year}",
    },
    "DTWEXB": {
        "source_id": "federal_reserve_h10_broad_archive",
        "fred_observation_start": "1995-01-01",
        "url": "https://api.stlouisfed.org/fred/series/observations?series_id=DTWEXB&file_type=json&observation_start=1995-01-01",
    },
    "DTWEXBGS": {
        "source_id": "federal_reserve_h10_broad_goods_services_archive",
        "fred_observation_start": "2006-01-01",
        "url": "https://api.stlouisfed.org/fred/series/observations?series_id=DTWEXBGS&file_type=json&observation_start=2006-01-01",
    },
    "FED_EBP": {
        "source_id": "federal_reserve_excess_bond_premium",
        "url": "https://www.federalreserve.gov/econres/notes/feds-notes/ebp_csv.csv",
    },
}


def collect_official_market_archives(
    root: Path, *, retrieved_at: str | None = None,
    fetcher: Callable[[str], tuple[int, bytes, str]] = _fetch,
    collection_mode: Literal["bootstrap_reconstruction", "forward_refresh"] = "forward_refresh",
) -> dict[str, Any]:
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    data_grade: Literal["reconstructed_market_archive", "captured_forward"] = (
        "reconstructed_market_archive" if collection_mode == "bootstrap_reconstruction"
        else "captured_forward"
    )
    result: dict[str, Any] = {"retrieved_at": retrieved, "series": {}, "failures": []}
    for key, spec in MARKET_ARCHIVE_SPECS.items():
        try:
            if key == "TREASURY":
                aggregate = {"DGS2": {"appended": 0, "unchanged": 0, "received": 0},
                             "DGS10": {"appended": 0, "unchanged": 0, "received": 0}}
                current_year = datetime.fromisoformat(retrieved).year
                first_year = 1990 if collection_mode == "bootstrap_reconstruction" else current_year - 1
                for year in range(first_year, current_year + 1):
                    url = spec["url"].format(year=year)
                    status, payload, content_type = fetcher(url)
                    if status != 200:
                        raise MarketArchiveError(f"TREASURY {year} returned HTTP {status}")
                    receipt = persist_market_raw(
                        root, source_id=spec["source_id"], source_uri=url, payload=payload,
                        retrieved_at=retrieved, http_status=status, content_type=content_type,
                    )
                    rows = parse_treasury_xml(payload)
                    for series_id, values in (
                        ("DGS2", ((day, two) for day, two, _ in rows)),
                        ("DGS10", ((day, ten) for day, _, ten in rows)),
                    ):
                        outcome = _append_observations(
                            root, source_id=spec["source_id"], series_id=series_id,
                            unit="percentage_point", values=values, receipt=receipt,
                            available_at=_treasury_available_at,
                            data_grade=data_grade,
                        )
                        for field in aggregate[series_id]:
                            aggregate[series_id][field] += outcome[field]
                result["series"].update(aggregate)
                continue
            if "fred_observation_start" in spec and fetcher is _fetch:
                # Official FRED API transport; the keyed URL never leaves
                # fred_api and the receipt records the keyless public URL.
                from ..fred_api import observations_csv

                status, content_type = 200, "text/csv"
                payload = observations_csv(
                    key, observation_start=spec["fred_observation_start"],
                ).encode("utf-8")
            else:
                status, payload, content_type = fetcher(spec["url"])
            if status != 200:
                raise MarketArchiveError(f"{key} returned HTTP {status}")
            receipt = persist_market_raw(
                root, source_id=spec["source_id"], source_uri=spec["url"], payload=payload,
                retrieved_at=retrieved, http_status=status, content_type=content_type,
            )
            if key == "VIX":
                rows = parse_cboe_vix_csv(payload)
                result["series"]["VIX"] = _append_observations(
                    root, source_id=spec["source_id"], series_id="VIX", unit="index",
                    values=rows, receipt=receipt, available_at=_market_available_at,
                    data_grade=data_grade,
                )
            elif key == "FED_EBP":
                rows = parse_fed_ebp_csv(payload)
                # The Fed notes that the complete EBP history may be revised.
                # A downloaded historical row therefore becomes knowable only
                # when this repository captured it; it is never backdated as PIT.
                result["series"]["FED_EBP"] = _append_observations(
                    root, source_id=spec["source_id"], series_id="FED_EBP",
                    unit="percentage_point", values=rows, receipt=receipt,
                    available_at=_market_available_at, data_grade="captured_forward",
                )
            else:
                rows = parse_fred_graph_csv(payload, series_id=key)
                result["series"][key] = _append_observations(
                    root, source_id=spec["source_id"], series_id=key,
                    unit="index", values=rows, receipt=receipt, available_at=_market_available_at,
                    data_grade=data_grade,
                )
        except (OSError, ValueError, ET.ParseError, MarketArchiveError, FredApiError) as exc:
            result["failures"].append({"series": key, "reason": str(exc)})
    result["ok"] = not result["failures"]
    return result


def read_market_observations(root: Path, *, knowledge_cutoff: str | None = None) -> list[MarketObservationV2]:
    rows = _current_facts(root)
    if knowledge_cutoff is not None:
        cutoff = datetime.fromisoformat(knowledge_cutoff)
        rows = [row for row in rows if datetime.fromisoformat(row.available_at) <= cutoff]
    latest: dict[tuple[str, str], MarketObservationV2] = {}
    for row in rows:
        key = (row.series_id, row.observation_time)
        if key not in latest or row.revision_seq > latest[key].revision_seq:
            latest[key] = row
    return sorted(latest.values(), key=lambda row: (row.series_id, row.observation_time))


def verify_market_lineage(root: Path) -> dict[str, Any]:
    receipts_path = root / ARCHIVE_RECEIPTS
    receipts = [] if not receipts_path.is_file() else [
        MarketRawReceipt.model_validate_json(line)
        for line in receipts_path.read_text(encoding="utf-8").splitlines() if line
    ]
    receipt_index = {row.receipt_id: row for row in receipts}
    errors: list[str] = []
    for receipt in receipts:
        if receipt.redistribution == "repository_raw_allowed":
            path = root / receipt.raw_path
            if not path.is_file():
                errors.append(f"missing raw {receipt.receipt_id}")
            else:
                with gzip.open(path, "rb") as handle:
                    digest = hashlib.sha256(handle.read()).hexdigest()
                if digest != receipt.raw_sha256:
                    errors.append(f"raw hash mismatch {receipt.receipt_id}")
    facts = _current_facts(root)
    for fact in facts:
        receipt = receipt_index.get(fact.receipt_id)
        if receipt is None:
            errors.append(f"orphan fact {fact.observation_id}")
        elif receipt.raw_sha256 != fact.raw_sha256:
            errors.append(f"receipt hash mismatch {fact.observation_id}")
        if fact.data_grade not in {"reconstructed_market_archive", "captured_forward"}:
            errors.append(f"invalid market data grade {fact.observation_id}")
    return {
        "ok": not errors,
        "errors": errors,
        "receipts": len(receipts),
        "facts": len(facts),
        "receipt_linkage": 1.0 if not facts else (len(facts) - sum(error.startswith("orphan fact") for error in errors)) / len(facts),
    }


def export_market_parquet(root: Path) -> dict[str, Any]:
    """Deterministic derived training view; JSONL remains canonical."""
    try:
        import pyarrow as pa  # type: ignore
        import pyarrow.parquet as pq  # type: ignore
    except ImportError as exc:  # pragma: no cover - optional PIT dependency
        raise MarketArchiveError("install ai-fc[pit] for V2 Parquet views") from exc
    rows = [row.model_dump(mode="json") for row in read_market_observations(root)]
    target = root / PARQUET_RELATIVE / "market_observations.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp.parquet")
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, temporary, compression="zstd", use_dictionary=True)
    os.replace(temporary, target)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    manifest = {
        "schema_version": 2, "path": target.relative_to(root).as_posix(),
        "rows": len(rows), "sha256": digest,
        "canonical_ledger": ARCHIVE_FACTS.as_posix(),
    }
    manifest_path = root / PARQUET_RELATIVE / "market_observations.manifest.json"
    temporary_manifest = manifest_path.with_suffix(".tmp")
    temporary_manifest.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary_manifest, manifest_path)
    return manifest
