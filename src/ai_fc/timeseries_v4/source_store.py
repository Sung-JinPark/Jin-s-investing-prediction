"""Raw-first, append-only source store for the V4 research candidate.

The store is deliberately isolated from the V1/V2/V3 ledgers.  Historical
market and official forecast archives are exact reconstructions, not ALFRED
vintages.  Every fact therefore carries an explicit data grade and a
conservative availability timestamp.
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
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Literal
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator


STORE_RELATIVE = Path("data/timeseries_v4")
RAW_RELATIVE = STORE_RELATIVE / "raw"
LEDGER_RELATIVE = STORE_RELATIVE / "ledgers"
RECEIPTS_RELATIVE = LEDGER_RELATIVE / "raw_receipts.jsonl"
OBSERVATIONS_RELATIVE = LEDGER_RELATIVE / "observations.jsonl"
PARSER_VERSION = "timeseries-v4-source-store-1.0"


class V4SourceError(RuntimeError):
    """V4 source collection or lineage validation failed."""


class V4RawReceipt(BaseModel):
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


class V4Observation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    observation_id: str
    source_id: str
    series_id: str
    observation_time: str
    value: float
    unit: str
    available_at: str
    data_grade: Literal[
        "reconstructed_market_archive",
        "reconstructed_official_forecast_archive",
        "captured_forward",
        "licensed_historical",
    ]
    dimensions: dict[str, str] = Field(default_factory=dict)
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_id: str
    revision_seq: int = Field(ge=1)
    supersedes: str | None = None
    parser_version: str

    @field_validator("value")
    @classmethod
    def finite(cls, value: float) -> float:
        if not (-1e300 < float(value) < 1e300):
            raise ValueError("observation must be finite")
        return float(value)


@dataclass(frozen=True)
class ParsedValue:
    series_id: str
    observation_time: str
    value: float
    unit: str
    available_at: str
    data_grade: str
    dimensions: dict[str, str]


def canonical_hash(value: Any) -> str:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


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


def _redact_url(url: str) -> str:
    return re.sub(r"(?i)(api_key|token|key)=([^&]+)", r"\1=REDACTED", url)


def _fetch(url: str, *, timeout: int = 180) -> tuple[int, bytes, str]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "AI-Investing-Research/4.0 contact=repository-maintainer"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return int(response.status), response.read(), response.headers.get_content_type()


def persist_raw(
    root: Path,
    *,
    source_id: str,
    source_uri: str,
    payload: bytes,
    retrieved_at: str,
    http_status: int = 200,
    content_type: str = "application/octet-stream",
    redistribution: Literal["repository_raw_allowed", "private_locator_only"] = "repository_raw_allowed",
) -> V4RawReceipt:
    digest = hashlib.sha256(payload).hexdigest()
    redacted = _redact_url(source_uri)
    fingerprint = hashlib.sha256(redacted.encode("utf-8")).hexdigest()
    seed = {
        "source_id": source_id,
        "source_uri": redacted,
        "retrieved_at": retrieved_at,
        "raw_sha256": digest,
        "request_fingerprint": fingerprint,
    }
    receipt_id = f"v4-receipt-{canonical_hash(seed)[:24]}"
    if redistribution == "repository_raw_allowed":
        relative = RAW_RELATIVE / source_id / f"{digest}.gz"
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
        raw_path = f"private://timeseries-v4/{source_id}/{digest}"
    receipt = V4RawReceipt(
        receipt_id=receipt_id,
        source_id=source_id,
        source_uri=redacted,
        retrieved_at=retrieved_at,
        http_status=http_status,
        raw_sha256=digest,
        raw_path=raw_path,
        request_fingerprint=fingerprint,
        content_type=content_type,
        redistribution=redistribution,
    )
    _append_jsonl(root / RECEIPTS_RELATIVE, [receipt.model_dump(mode="json")], identity="receipt_id")
    return receipt


def _all_observations(root: Path) -> list[V4Observation]:
    path = root / OBSERVATIONS_RELATIVE
    if not path.is_file():
        return []
    return [V4Observation.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def append_observations(
    root: Path,
    values: Iterable[ParsedValue],
    receipt: V4RawReceipt,
    *,
    observation_cache: list[V4Observation] | None = None,
) -> dict[str, int]:
    latest: dict[tuple[str, str, str], V4Observation] = {}
    existing_rows = _all_observations(root) if observation_cache is None else observation_cache
    for row in existing_rows:
        key = (row.series_id, row.observation_time, canonical_hash(row.dimensions))
        if key not in latest or row.revision_seq > latest[key].revision_seq:
            latest[key] = row
    pending: list[V4Observation] = []
    unchanged = 0
    for item in values:
        dimensions = {str(key): str(value) for key, value in sorted(item.dimensions.items())}
        key = (item.series_id, item.observation_time, canonical_hash(dimensions))
        prior = latest.get(key)
        if prior is not None and prior.value == float(item.value) and prior.unit == item.unit:
            unchanged += 1
            continue
        revision_seq = 1 if prior is None else prior.revision_seq + 1
        seed = {
            "series_id": item.series_id,
            "observation_time": item.observation_time,
            "dimensions": dimensions,
            "value": float(item.value),
            "unit": item.unit,
            "receipt_id": receipt.receipt_id,
            "revision_seq": revision_seq,
        }
        row = V4Observation(
            observation_id=f"v4-observation-{canonical_hash(seed)[:24]}",
            source_id=receipt.source_id,
            series_id=item.series_id,
            observation_time=item.observation_time,
            value=float(item.value),
            unit=item.unit,
            available_at=item.available_at,
            data_grade=item.data_grade,
            dimensions=dimensions,
            raw_sha256=receipt.raw_sha256,
            receipt_id=receipt.receipt_id,
            revision_seq=revision_seq,
            supersedes=None if prior is None else prior.observation_id,
            parser_version=PARSER_VERSION,
        )
        pending.append(row)
        latest[key] = row
    appended = _append_jsonl(
        root / OBSERVATIONS_RELATIVE,
        [row.model_dump(mode="json") for row in pending],
        identity="observation_id",
    )
    if observation_cache is not None:
        observation_cache.extend(pending)
    return {"appended": appended, "unchanged": unchanged, "received": appended + unchanged}


def _ny_available(day: str, hour: int, minute: int = 0) -> str:
    local = datetime.combine(date.fromisoformat(day), time(hour, minute), tzinfo=ZoneInfo("America/New_York"))
    return local.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_cboe_index(payload: bytes, *, series_id: str) -> list[ParsedValue]:
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
    output: list[ParsedValue] = []
    for row in reader:
        raw_day = str(row.get("DATE") or row.get("Date") or "").strip()
        raw_close = str(row.get("CLOSE") or row.get("Close") or row.get(series_id) or "").strip()
        if not raw_day or raw_close in {"", "."}:
            continue
        day = datetime.strptime(raw_day, "%m/%d/%Y").date().isoformat()
        output.append(ParsedValue(
            series_id, day, float(raw_close), "index", _ny_available(day, 16, 15),
            "reconstructed_market_archive", {},
        ))
    return output


def parse_fred_graph(payload: bytes, *, series_id: str) -> list[ParsedValue]:
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
    output: list[ParsedValue] = []
    for row in reader:
        day = str(row.get("observation_date") or row.get("DATE") or "").strip()
        raw = str(row.get(series_id) or row.get("VALUE") or "").strip()
        if not day or raw in {"", "."}:
            continue
        output.append(ParsedValue(
            series_id, day, float(raw), "index", _ny_available(day, 16, 15),
            "reconstructed_market_archive", {},
        ))
    return output


def parse_cboe_market_volume(payload: bytes) -> list[ParsedValue]:
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
    by_day: dict[str, dict[str, float]] = {}
    for row in reader:
        day = str(row.get("Day") or "").strip()
        if not day:
            continue
        bucket = by_day.setdefault(day, {"total": 0.0, "tape_c": 0.0, "off": 0.0, "trades": 0.0})
        total = float(row.get("Total Notional") or 0.0)
        bucket["total"] += total
        bucket["tape_c"] += float(row.get("Tape C Notional") or 0.0)
        bucket["trades"] += float(row.get("Total Trade Count") or 0.0)
        if "FINRA" in str(row.get("Market Participant") or "").upper():
            bucket["off"] += total
    output: list[ParsedValue] = []
    for day, values in sorted(by_day.items()):
        if values["total"] <= 0:
            continue
        available = _ny_available(day, 23, 0)
        common = (available, "reconstructed_market_archive", {})
        output.extend([
            ParsedValue("US_EQ_TOTAL_NOTIONAL", day, values["total"], "usd", *common),
            ParsedValue("US_EQ_TAPE_C_NOTIONAL_SHARE", day, values["tape_c"] / values["total"], "fraction", *common),
            ParsedValue("US_EQ_OFF_EXCHANGE_NOTIONAL_SHARE", day, values["off"] / values["total"], "fraction", *common),
            ParsedValue("US_EQ_TOTAL_TRADES", day, values["trades"], "count", *common),
        ])
    return output


_NOWCAST_NAMES = {
    "CPI Inflation": "CLEVELAND_CPI_NOWCAST",
    "Core CPI Inflation": "CLEVELAND_CORE_CPI_NOWCAST",
    "PCE Inflation": "CLEVELAND_PCE_NOWCAST",
    "Core PCE Inflation": "CLEVELAND_CORE_PCE_NOWCAST",
}


def parse_cleveland_nowcast(payload: bytes, *, frequency: str) -> list[ParsedValue]:
    panels = json.loads(payload.decode("utf-8-sig"))
    output: list[ParsedValue] = []
    for panel in panels:
        target = str(panel.get("chart", {}).get("subcaption") or "")
        match = re.fullmatch(r"(\d{4})-(\d{1,2})(?:-(\d{1,2}))?", target)
        quarter_match = re.fullmatch(r"(\d{4}):Q([1-4])", target)
        if match:
            target_year, target_month = int(match.group(1)), int(match.group(2))
        elif quarter_match:
            target_year, target_month = int(quarter_match.group(1)), int(quarter_match.group(2)) * 3
        else:
            continue
        categories = panel.get("categories", [{}])[0].get("category", [])
        for dataset in panel.get("dataset", []):
            series_id = _NOWCAST_NAMES.get(str(dataset.get("seriesname")))
            if series_id is None:
                continue
            for category, point in zip(categories, dataset.get("data", [])):
                label = str(category.get("label") or "")
                day_match = re.fullmatch(r"(\d{2})/(\d{2})", label)
                raw_value = str(point.get("value") or "").strip()
                if day_match is None or raw_value in {"", "."}:
                    continue
                month, day_num = int(day_match.group(1)), int(day_match.group(2))
                year = target_year - 1 if month > target_month else target_year
                try:
                    as_of = date(year, month, day_num).isoformat()
                except ValueError:
                    continue
                output.append(ParsedValue(
                    series_id, as_of, float(raw_value), "percentage_point",
                    _ny_available(as_of, 10, 30),
                    "reconstructed_official_forecast_archive",
                    {"target_period": target, "frequency": frequency},
                ))
    return output


def _xlsx_rows(payload: bytes) -> list[list[Any]]:
    """Read the first XLSX worksheet using only the standard library."""
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            tree = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in tree.findall("{*}si"):
                shared.append("".join(node.text or "" for node in item.iter() if node.tag.endswith("}t")))
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        first = workbook.find(".//{*}sheet")
        if first is None:
            return []
        relationship_id = first.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        target = None
        for relationship in relationships.findall("{*}Relationship"):
            if relationship.attrib.get("Id") == relationship_id:
                target = relationship.attrib.get("Target")
                break
        if target is None:
            return []
        target = target.lstrip("/")
        sheet_path = target if target.startswith("xl/") else f"xl/{target}"
        sheet = ET.fromstring(archive.read(sheet_path))
        rows: list[list[Any]] = []
        for row in sheet.findall(".//{*}row"):
            cells: dict[int, Any] = {}
            for cell in row.findall("{*}c"):
                reference = str(cell.attrib.get("r") or "A1")
                letters = re.match(r"[A-Z]+", reference)
                if letters is None:
                    continue
                index = 0
                for letter in letters.group(0):
                    index = index * 26 + ord(letter) - 64
                index -= 1
                value_node = cell.find("{*}v")
                if cell.attrib.get("t") == "inlineStr":
                    value = "".join(node.text or "" for node in cell.iter() if node.tag.endswith("}t"))
                elif value_node is None:
                    value = None
                elif cell.attrib.get("t") == "s":
                    value = shared[int(value_node.text or 0)]
                else:
                    raw = value_node.text or ""
                    try:
                        value = float(raw)
                    except ValueError:
                        value = raw
                cells[index] = value
            if cells:
                width = max(cells) + 1
                rows.append([cells.get(index) for index in range(width)])
        return rows


def parse_spf_release_dates(payload: bytes) -> dict[tuple[int, int], str]:
    text = payload.decode("utf-8-sig")
    output: dict[tuple[int, int], str] = {}
    current_year: int | None = None
    pattern = re.compile(r"^\s*(?:(\d{4})\s+)?Q([1-4]).*?(\d{1,2}/\d{1,2}/\d{2,4})\*?\*?\*?\s*$")
    for line in text.splitlines():
        match = pattern.match(line)
        if match is None:
            continue
        if match.group(1):
            current_year = int(match.group(1))
        if current_year is None:
            continue
        quarter = int(match.group(2))
        release = datetime.strptime(match.group(3), "%m/%d/%y" if len(match.group(3).split("/")[-1]) == 2 else "%m/%d/%Y").date()
        output[(current_year, quarter)] = release.isoformat()
    return output


def parse_spf_workbook(
    payload: bytes,
    *,
    family: str,
    release_dates: dict[tuple[int, int], str],
    statistic: str,
) -> list[ParsedValue]:
    rows = _xlsx_rows(payload)
    if not rows:
        return []
    header_index = 0
    for index, row in enumerate(rows):
        first = str(row[0] if row else "").strip().upper()
        if first in {"YEAR", "SURVEY_DATE(T)"}:
            header_index = index
            break
    headers = [str(value or "").strip() for value in rows[header_index]]
    output: list[ParsedValue] = []
    dispersion_layout = bool(headers and headers[0].upper() == "SURVEY_DATE(T)")
    for row in rows[header_index + 1:]:
        if not row:
            continue
        if dispersion_layout:
            match = re.fullmatch(r"(\d{4})Q([1-4])", str(row[0] or "").strip().upper())
            if match is None:
                continue
            year, quarter = int(match.group(1)), int(match.group(2))
            data_start = 1
        else:
            if len(row) < 2:
                continue
            try:
                year, quarter = int(float(row[0])), int(float(row[1]))
            except (TypeError, ValueError):
                continue
            data_start = 2
        release_day = release_dates.get((year, quarter))
        if release_day is None:
            continue
        for index, raw_value in enumerate(row[data_start:], start=data_start):
            if index >= len(headers) or raw_value in {None, "", "#N/A"}:
                continue
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                continue
            field = re.sub(r"[^A-Z0-9]+", "_", headers[index].upper()).strip("_")
            output.append(ParsedValue(
                f"SPF_{family}_{statistic}_{field}",
                release_day,
                value,
                "percentage_point" if family != "EMP" else "thousand_jobs",
                _ny_available(release_day, 18, 0),
                "reconstructed_official_forecast_archive",
                {"survey_year": str(year), "survey_quarter": str(quarter)},
            ))
    return output


CBOE_INDEX_SOURCES = {
    "VIX9D": "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX9D_History.csv",
    "VIX3M": "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX3M_History.csv",
    "VVIX": "https://cdn.cboe.com/api/global/us_indices/daily_prices/VVIX_History.csv",
    "SKEW": "https://cdn.cboe.com/api/global/us_indices/daily_prices/SKEW_History.csv",
}

SPF_RELEASE_URL = "https://www.philadelphiafed.org/-/media/FRBP/Assets/Surveys-And-Data/survey-of-professional-forecasters/spf-release-dates.txt"
SPF_SOURCES = {
    ("RECESS", "MEAN"): "Mean_RECESS_Level.xlsx",
    ("EMP", "MEAN"): "Mean_EMP_Level.xlsx",
    ("EMP", "DISPERSION"): "Dispersion_EMP.xlsx",
    ("CPI", "MEAN"): "Mean_CPI_Level.xlsx",
    ("CPI", "DISPERSION"): "Dispersion_CPI.xlsx",
    ("UNEMP", "MEAN"): "Mean_UNEMP_Level.xlsx",
    ("UNEMP", "DISPERSION"): "Dispersion_UNEMP.xlsx",
}
SPF_BASE = "https://www.philadelphiafed.org/-/media/FRBP/Assets/Surveys-And-Data/survey-of-professional-forecasters/data-files/files"
CLEVELAND_SOURCES = {
    "month": "https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_month.json?sc_lang=en",
    "quarter": "https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_quarter.json?sc_lang=en",
    "year": "https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_year.json?sc_lang=en",
}


def collect_v4_sources(
    root: Path,
    *,
    retrieved_at: str | None = None,
    fetcher: Callable[[str], tuple[int, bytes, str]] = _fetch,
    volume_start_year: int = 2009,
) -> dict[str, Any]:
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    result: dict[str, Any] = {"retrieved_at": retrieved, "sources": {}, "failures": []}
    observation_cache = _all_observations(root)

    def collect(source_id: str, url: str, parser: Callable[[bytes], list[ParsedValue]], *, redistribution: str = "repository_raw_allowed") -> None:
        try:
            status, payload, content_type = fetcher(url)
            if status != 200:
                raise V4SourceError(f"HTTP {status}")
            receipt = persist_raw(
                root, source_id=source_id, source_uri=url, payload=payload,
                retrieved_at=retrieved, http_status=status, content_type=content_type,
                redistribution=redistribution,
            )
            parsed = parser(payload)
            if not parsed:
                raise V4SourceError("parser produced zero observations")
            result["sources"][source_id] = append_observations(
                root, parsed, receipt, observation_cache=observation_cache,
            )
        except (OSError, ValueError, KeyError, json.JSONDecodeError, ET.ParseError, zipfile.BadZipFile, V4SourceError) as exc:
            result["failures"].append({"source_id": source_id, "reason": str(exc)})

    for series_id, url in CBOE_INDEX_SOURCES.items():
        collect(f"cboe_{series_id.lower()}", url, lambda payload, sid=series_id: parse_cboe_index(payload, series_id=sid))

    collect(
        "fred_nasdaq100",
        "https://fred.stlouisfed.org/graph/fredgraph.csv?id=NASDAQ100&cosd=1995-01-01",
        lambda payload: parse_fred_graph(payload, series_id="NASDAQ100"),
        redistribution="private_locator_only",
    )

    current_year = datetime.fromisoformat(retrieved).year
    for year in range(volume_start_year, current_year + 1):
        url = f"https://cdn.cboe.com/resources/us/equities/market-statistics/historical-market-volume/market_history_{year}.csv"
        collect(f"cboe_us_equity_volume_{year}", url, parse_cboe_market_volume)

    for frequency, url in CLEVELAND_SOURCES.items():
        collect(
            f"cleveland_fed_inflation_nowcast_{frequency}", url,
            lambda payload, freq=frequency: parse_cleveland_nowcast(payload, frequency=freq),
        )

    try:
        status, release_payload, release_type = fetcher(SPF_RELEASE_URL)
        if status != 200:
            raise V4SourceError(f"SPF release dates HTTP {status}")
        release_receipt = persist_raw(
            root, source_id="philadelphia_fed_spf_release_dates", source_uri=SPF_RELEASE_URL,
            payload=release_payload, retrieved_at=retrieved, http_status=status, content_type=release_type,
        )
        release_dates = parse_spf_release_dates(release_payload)
        result["sources"][release_receipt.source_id] = {"release_dates": len(release_dates), "appended": 0, "unchanged": 0, "received": 0}
        for (family, statistic), filename in SPF_SOURCES.items():
            url = f"{SPF_BASE}/{filename}"
            collect(
                f"philadelphia_fed_spf_{family.lower()}_{statistic.lower()}", url,
                lambda payload, fam=family, stat=statistic: parse_spf_workbook(
                    payload, family=fam, release_dates=release_dates, statistic=stat,
                ),
            )
    except (OSError, ValueError, V4SourceError) as exc:
        result["failures"].append({"source_id": "philadelphia_fed_spf_release_dates", "reason": str(exc)})

    result["ok"] = not result["failures"]
    result["repository_event_snapshots"] = import_repository_event_snapshots(
        root, retrieved_at=retrieved, observation_cache=observation_cache,
    )
    result["lineage"] = verify_v4_source_store(root)
    return result


def import_repository_event_snapshots(
    root: Path,
    *,
    retrieved_at: str,
    observation_cache: list[V4Observation] | None = None,
) -> dict[str, Any]:
    """Bridge already-captured jobs/Fed-rate snapshots into the isolated V4 store.

    These are allowed research inputs but remain an insufficient-history event
    overlay.  They are never relabelled as official CME history.
    """
    result: dict[str, Any] = {"sources": {}, "failures": []}
    rate_path = root / "data/normalized/rates/fed_rate_monitor_pre_post_jobs_20260807.json"
    if rate_path.is_file():
        try:
            payload = rate_path.read_bytes()
            document = json.loads(payload.decode("utf-8"))
            receipt = persist_raw(
                root,
                source_id="repository_captured_fed_rate_probability_snapshot",
                source_uri=str(document.get("source_url") or rate_path.as_posix()),
                payload=payload,
                retrieved_at=retrieved_at,
                content_type="application/json",
            )
            values: list[ParsedValue] = []
            for snapshot_name, snapshot in document.get("snapshots", {}).items():
                observation_time = str(snapshot.get("as_of") or "")[:10]
                available_at = str(snapshot.get("available_at") or "")
                for meeting, probabilities in snapshot.get("meetings", {}).items():
                    entropy = 0.0
                    expected_midpoint = 0.0
                    for target_range, probability in probabilities.items():
                        number = float(probability)
                        if number > 0:
                            import math
                            entropy -= number * math.log(number)
                        low, high = (float(part) for part in target_range.split("-"))
                        expected_midpoint += number * (low + high) / 2.0
                        values.append(ParsedValue(
                            "FED_RATE_TARGET_PROBABILITY", observation_time, number, "fraction",
                            available_at, "captured_forward",
                            {"snapshot": snapshot_name, "meeting": str(meeting), "target_range": str(target_range), "provider": "Investing.com / CME futures-derived"},
                        ))
                    values.extend([
                        ParsedValue(
                            "FED_RATE_PATH_ENTROPY", observation_time, entropy, "nat", available_at,
                            "captured_forward", {"snapshot": snapshot_name, "meeting": str(meeting)},
                        ),
                        ParsedValue(
                            "FED_RATE_EXPECTED_TARGET_MIDPOINT", observation_time, expected_midpoint,
                            "percentage_point", available_at, "captured_forward",
                            {"snapshot": snapshot_name, "meeting": str(meeting)},
                        ),
                    ])
            result["sources"][receipt.source_id] = append_observations(
                root, values, receipt, observation_cache=observation_cache,
            )
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            result["failures"].append({"source_id": "repository_captured_fed_rate_probability_snapshot", "reason": str(exc)})

    jobs_path = root / "data/normalized/macro/bls_empsit_2026_07_20260807.json"
    if jobs_path.is_file():
        try:
            payload = jobs_path.read_bytes()
            document = json.loads(payload.decode("utf-8"))
            receipt = persist_raw(
                root,
                source_id="repository_captured_jobs_release_and_consensus",
                source_uri=str(document.get("source_url") or jobs_path.as_posix()),
                payload=payload,
                retrieved_at=retrieved_at,
                content_type="application/json",
            )
            observation_time = str(document.get("published_at") or "")[:10]
            available_at = str(document.get("available_at") or "")
            actual = document.get("actual", {})
            values = [
                ParsedValue("BLS_NFP_ACTUAL", observation_time, float(actual["nonfarm_payroll_change"]), "persons", available_at, "captured_forward", {}),
                ParsedValue("BLS_UNEMPLOYMENT_ACTUAL", observation_time, float(actual["unemployment_rate"]), "fraction", available_at, "captured_forward", {}),
                ParsedValue("BLS_PARTICIPATION_ACTUAL", observation_time, float(actual["labor_force_participation_rate"]), "fraction", available_at, "captured_forward", {}),
            ]
            consensus = document.get("consensus", {})
            if consensus.get("nonfarm_payroll_change") is not None:
                values.append(ParsedValue(
                    "NFP_CONSENSUS", observation_time, float(consensus["nonfarm_payroll_change"]),
                    "persons", available_at, "captured_forward",
                    {"provider": "Kiplinger", "status": "secondary_research_source"},
                ))
            result["sources"][receipt.source_id] = append_observations(
                root, values, receipt, observation_cache=observation_cache,
            )
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            result["failures"].append({"source_id": "repository_captured_jobs_release_and_consensus", "reason": str(exc)})
    result["ok"] = not result["failures"]
    return result


def read_v4_observations(root: Path, *, knowledge_cutoff: str | None = None) -> list[V4Observation]:
    rows = _all_observations(root)
    if knowledge_cutoff is not None:
        cutoff = datetime.fromisoformat(knowledge_cutoff)
        rows = [row for row in rows if datetime.fromisoformat(row.available_at) <= cutoff]
    latest: dict[tuple[str, str, str], V4Observation] = {}
    for row in rows:
        key = (row.series_id, row.observation_time, canonical_hash(row.dimensions))
        if key not in latest or row.revision_seq > latest[key].revision_seq:
            latest[key] = row
    return sorted(latest.values(), key=lambda row: (row.series_id, row.observation_time, canonical_hash(row.dimensions)))


def verify_v4_source_store(root: Path) -> dict[str, Any]:
    receipt_path = root / RECEIPTS_RELATIVE
    receipts = [] if not receipt_path.is_file() else [
        V4RawReceipt.model_validate_json(line)
        for line in receipt_path.read_text(encoding="utf-8").splitlines() if line
    ]
    receipt_index = {row.receipt_id: row for row in receipts}
    errors: list[str] = []
    for receipt in receipts:
        if receipt.redistribution != "repository_raw_allowed":
            continue
        path = root / receipt.raw_path
        if not path.is_file():
            errors.append(f"missing raw {receipt.receipt_id}")
            continue
        with gzip.open(path, "rb") as handle:
            if hashlib.sha256(handle.read()).hexdigest() != receipt.raw_sha256:
                errors.append(f"raw hash mismatch {receipt.receipt_id}")
    facts = _all_observations(root)
    for fact in facts:
        receipt = receipt_index.get(fact.receipt_id)
        if receipt is None:
            errors.append(f"orphan observation {fact.observation_id}")
        elif receipt.raw_sha256 != fact.raw_sha256 or receipt.source_id != fact.source_id:
            errors.append(f"receipt mismatch {fact.observation_id}")
        if datetime.fromisoformat(fact.available_at).date() < date.fromisoformat(fact.observation_time):
            errors.append(f"available_at before observation {fact.observation_id}")
    return {
        "ok": not errors,
        "errors": errors,
        "receipts": len(receipts),
        "observations": len(facts),
        "series": sorted({row.series_id for row in facts}),
        "receipt_linkage": 1.0 if not facts else (len(facts) - sum(error.startswith("orphan") for error in errors)) / len(facts),
    }


def export_v4_parquet(root: Path) -> dict[str, Any]:
    try:
        import pyarrow as pa  # type: ignore
        import pyarrow.parquet as pq  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise V4SourceError("install ai-fc[pit] for the V4 Parquet view") from exc
    rows = [row.model_dump(mode="json") for row in read_v4_observations(root)]
    target = root / STORE_RELATIVE / "parquet/observations.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp.parquet")
    pq.write_table(pa.Table.from_pylist(rows), temporary, compression="zstd", use_dictionary=True)
    os.replace(temporary, target)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    manifest = {"path": target.relative_to(root).as_posix(), "rows": len(rows), "sha256": digest}
    manifest_path = target.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return manifest
