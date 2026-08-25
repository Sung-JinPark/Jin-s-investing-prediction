"""Public, credential-free V6 market archive collection and immutable materialization."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import urllib.request
import zipfile
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable
from xml.etree import ElementTree

import pyarrow as pa
import pyarrow.parquet as pq

from .object_store import LocalContentAddressedStore


class PublicArchiveError(RuntimeError):
    pass


@dataclass(frozen=True)
class PublicSeriesSpec:
    source_id: str
    series_id: str
    uri: str
    value_column: str
    frequency: str
    unit: str
    publication_delay_days: int
    data_grade: str = "reconstructed_official_archive"
    parser_kind: str = "csv"


FRED_GRAPH = "https://fred.stlouisfed.org/graph/fredgraph.csv"
CBOE_DAILY = "https://cdn.cboe.com/api/global/us_indices/daily_prices"
PUBLIC_SERIES: tuple[PublicSeriesSpec, ...] = (
    PublicSeriesSpec("fred_alfred", "NASDAQCOM", f"{FRED_GRAPH}?id=NASDAQCOM&cosd=1995-01-01", "NASDAQCOM", "daily", "index_points", 1),
    PublicSeriesSpec("cboe_vix", "VIX", f"{CBOE_DAILY}/VIX_History.csv", "CLOSE", "daily", "index_points", 1),
    PublicSeriesSpec("cboe_vix9d", "VIX9D", f"{CBOE_DAILY}/VIX9D_History.csv", "CLOSE", "daily", "index_points", 1),
    PublicSeriesSpec("cboe_vix3m", "VIX3M", f"{CBOE_DAILY}/VIX3M_History.csv", "CLOSE", "daily", "index_points", 1),
    PublicSeriesSpec("cboe_vvix", "VVIX", f"{CBOE_DAILY}/VVIX_History.csv", "VVIX", "daily", "index_points", 1),
    PublicSeriesSpec("cboe_skew", "SKEW", f"{CBOE_DAILY}/SKEW_History.csv", "SKEW", "daily", "index_points", 1),
    PublicSeriesSpec("ofr_fsi", "OFR_FSI", "https://www.financialresearch.gov/financial-stress-index/data/fsi.csv", "OFR FSI", "daily", "index_points", 2),
    PublicSeriesSpec("fed_ebp", "EBP", "https://www.federalreserve.gov/econres/notes/feds-notes/ebp_csv.csv", "ebp", "monthly", "percentage_point", 45),
    PublicSeriesSpec("nyfed_cmdi", "CMDI", "https://www.newyorkfed.org/medialibrary/research/interactives/data/cmdi/cmdi_interactive_data.xlsx", "Market CMDI", "monthly", "index_points", 45, parser_kind="cmdi_xlsx"),
    PublicSeriesSpec("cftc_tff", "CFTC_NASDAQ_LEV_NET_PCT_OI", "https://publicreporting.cftc.gov/resource/gpe5-46if.csv?$limit=50000&$where=upper(contract_market_name)%20like%20%27%25NASDAQ%25%27&$order=report_date_as_yyyy_mm_dd", "leveraged_net_pct_oi", "weekly", "percentage_point", 3, parser_kind="cftc_nasdaq"),
    PublicSeriesSpec("fred_alfred", "DGS2", f"{FRED_GRAPH}?id=DGS2&cosd=1995-01-01", "DGS2", "daily", "percentage_point", 1),
    PublicSeriesSpec("fred_alfred", "T10Y2Y", f"{FRED_GRAPH}?id=T10Y2Y&cosd=1995-01-01", "T10Y2Y", "daily", "percentage_point", 1),
    PublicSeriesSpec("fed_h10", "DTWEXBGS", f"{FRED_GRAPH}?id=DTWEXBGS&cosd=2006-01-01", "DTWEXBGS", "daily", "index_points", 1),
    PublicSeriesSpec("chicago_fed_nfci", "NFCI", f"{FRED_GRAPH}?id=NFCI&cosd=1995-01-01", "NFCI", "weekly", "index_points", 4),
    PublicSeriesSpec("fred_alfred", "DFF", f"{FRED_GRAPH}?id=DFF&cosd=1995-01-01", "DFF", "daily", "percentage_point", 1),
    PublicSeriesSpec("fed_h41", "WALCL", f"{FRED_GRAPH}?id=WALCL&cosd=2002-01-01", "WALCL", "weekly", "million_usd", 4),
    PublicSeriesSpec("treasury_dts", "WTREGEN", f"{FRED_GRAPH}?id=WTREGEN&cosd=2002-01-01", "WTREGEN", "weekly", "million_usd", 4),
    PublicSeriesSpec("nyfed_markets", "RRPONTSYD", f"{FRED_GRAPH}?id=RRPONTSYD&cosd=2003-01-01", "RRPONTSYD", "daily", "billion_usd", 1),
    PublicSeriesSpec("fred_alfred", "M2SL", f"{FRED_GRAPH}?id=M2SL&cosd=1995-01-01", "M2SL", "monthly", "billion_usd", 45),
    PublicSeriesSpec("fred_alfred", "PAYEMS", f"{FRED_GRAPH}?id=PAYEMS&cosd=1995-01-01", "PAYEMS", "monthly", "thousand_persons", 45),
    PublicSeriesSpec("fred_alfred", "UNRATE", f"{FRED_GRAPH}?id=UNRATE&cosd=1995-01-01", "UNRATE", "monthly", "percentage_point", 45),
    PublicSeriesSpec("fred_alfred", "INDPRO", f"{FRED_GRAPH}?id=INDPRO&cosd=1995-01-01", "INDPRO", "monthly", "index_points", 45),
    PublicSeriesSpec("fred_alfred", "CPIAUCSL", f"{FRED_GRAPH}?id=CPIAUCSL&cosd=1995-01-01", "CPIAUCSL", "monthly", "index_points", 45),
)


Fetcher = Callable[[str], tuple[bytes, str]]


def default_fetcher(uri: str) -> tuple[bytes, str]:
    request = urllib.request.Request(uri, headers={"User-Agent": "ai-investing-v6-research/1.0", "Accept-Encoding": "identity"})
    with urllib.request.urlopen(request, timeout=60) as response:
        body = response.read(100_000_001)
        if len(body) > 100_000_000:
            raise PublicArchiveError("public response exceeds byte budget")
        return body, response.headers.get("Content-Type", "text/csv")


def parse_public_csv(spec: PublicSeriesSpec, body: bytes) -> list[dict]:
    rows = csv.DictReader(io.StringIO(body.decode("utf-8-sig", errors="strict")))
    output: list[dict] = []
    for raw in rows:
        date_value = raw.get("observation_date") or raw.get("DATE") or raw.get("Date") or raw.get("date")
        value_raw = raw.get(spec.value_column)
        if not date_value or value_raw in {None, "", ".", "NA"}:
            continue
        try:
            if "/" in date_value:
                day = datetime.strptime(date_value[:10], "%m/%d/%Y").replace(tzinfo=timezone.utc)
            else:
                day = datetime.fromisoformat(date_value[:10]).replace(tzinfo=timezone.utc)
            value = float(str(value_raw).replace(",", ""))
        except (ValueError, TypeError):
            continue
        observation_time = day.replace(hour=21)
        available_at = observation_time + timedelta(days=spec.publication_delay_days)
        output.append({
            "source_id": spec.source_id,
            "series_id": spec.series_id,
            "observation_time": observation_time,
            "available_at": available_at,
            "value_numeric": value,
            "unit": spec.unit,
            "data_grade": spec.data_grade,
        })
    if len(output) < 100:
        raise PublicArchiveError(f"insufficient parsed rows for {spec.series_id}: {len(output)}")
    return output


def _xlsx_first_sheet_rows(body: bytes) -> list[dict[str, object]]:
    """Read the first XLSX worksheet with the standard library only.

    The production lock intentionally does not add an Excel runtime dependency.
    This small reader supports the scalar/string cell types used by the NY Fed
    CMDI workbook and rejects malformed packages instead of guessing.
    """

    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall(f"{namespace}si"):
                shared.append("".join(node.text or "" for node in item.iter(f"{namespace}t")))
        sheet_names = sorted(
            name for name in archive.namelist()
            if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
        )
        if not sheet_names:
            raise PublicArchiveError("xlsx contains no worksheets")
        root = ElementTree.fromstring(archive.read(sheet_names[0]))

    matrix: list[list[object]] = []
    for row in root.iter(f"{namespace}row"):
        values: list[object] = []
        for cell in row.findall(f"{namespace}c"):
            reference = cell.attrib.get("r", "A1")
            letters = "".join(char for char in reference if char.isalpha())
            column = 0
            for char in letters:
                column = column * 26 + ord(char.upper()) - 64
            while len(values) < column:
                values.append(None)
            kind = cell.attrib.get("t")
            value_node = cell.find(f"{namespace}v")
            inline = cell.find(f"{namespace}is")
            raw = value_node.text if value_node is not None else None
            if kind == "s" and raw is not None:
                value: object = shared[int(raw)]
            elif kind == "inlineStr" and inline is not None:
                value = "".join(node.text or "" for node in inline.iter(f"{namespace}t"))
            elif raw is None:
                value = None
            else:
                try:
                    value = float(raw)
                except ValueError:
                    value = raw
            values[column - 1] = value
        matrix.append(values)
    if not matrix:
        raise PublicArchiveError("xlsx worksheet is empty")
    headers = [str(value).strip() if value is not None else "" for value in matrix[0]]
    return [
        {header: row[index] if index < len(row) else None for index, header in enumerate(headers) if header}
        for row in matrix[1:]
    ]


def _excel_serial_date(value: object) -> datetime:
    if isinstance(value, (int, float)):
        return datetime(1899, 12, 30, tzinfo=timezone.utc) + timedelta(days=float(value))
    return datetime.fromisoformat(str(value)[:10]).replace(tzinfo=timezone.utc)


def parse_cmdi_xlsx(spec: PublicSeriesSpec, body: bytes) -> list[dict]:
    output: list[dict] = []
    for raw in _xlsx_first_sheet_rows(body):
        if raw.get("eow_friday") is None or raw.get(spec.value_column) is None:
            continue
        try:
            day = _excel_serial_date(raw["eow_friday"])
            value = float(raw[spec.value_column])
        except (TypeError, ValueError):
            continue
        observation_time = day.replace(hour=21)
        output.append({
            "source_id": spec.source_id,
            "series_id": spec.series_id,
            "observation_time": observation_time,
            "available_at": observation_time + timedelta(days=spec.publication_delay_days),
            "value_numeric": value,
            "unit": spec.unit,
            "data_grade": spec.data_grade,
        })
    if len(output) < 100:
        raise PublicArchiveError(f"insufficient parsed rows for {spec.series_id}: {len(output)}")
    return output


def parse_cftc_nasdaq(spec: PublicSeriesSpec, body: bytes) -> list[dict]:
    grouped: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for raw in csv.DictReader(io.StringIO(body.decode("utf-8-sig", errors="strict"))):
        day = str(raw.get("report_date_as_yyyy_mm_dd") or "")[:10]
        try:
            open_interest = float(raw["open_interest_all"])
            leveraged_net = float(raw["lev_money_positions_long"]) - float(raw["lev_money_positions_short"])
        except (KeyError, TypeError, ValueError):
            continue
        if day:
            grouped[day][0] += leveraged_net
            grouped[day][1] += open_interest
    output: list[dict] = []
    for date_value, (net, open_interest) in sorted(grouped.items()):
        if open_interest <= 0:
            continue
        day = datetime.fromisoformat(date_value).replace(tzinfo=timezone.utc)
        observation_time = day.replace(hour=21)
        output.append({
            "source_id": spec.source_id,
            "series_id": spec.series_id,
            "observation_time": observation_time,
            "available_at": observation_time + timedelta(days=spec.publication_delay_days),
            "value_numeric": 100.0 * net / open_interest,
            "unit": spec.unit,
            "data_grade": spec.data_grade,
        })
    if len(output) < 100:
        raise PublicArchiveError(f"insufficient parsed rows for {spec.series_id}: {len(output)}")
    return output


def parse_public_response(spec: PublicSeriesSpec, body: bytes) -> list[dict]:
    if spec.parser_kind == "csv":
        return parse_public_csv(spec, body)
    if spec.parser_kind == "cmdi_xlsx":
        return parse_cmdi_xlsx(spec, body)
    if spec.parser_kind == "cftc_nasdaq":
        return parse_cftc_nasdaq(spec, body)
    raise PublicArchiveError(f"unsupported parser kind: {spec.parser_kind}")


def collect_public_archives(
    root: Path, *, specs: Iterable[PublicSeriesSpec] = PUBLIC_SERIES,
    fetcher: Fetcher = default_fetcher, collected_at: datetime | None = None,
) -> dict:
    collected_at = collected_at or datetime.now(timezone.utc)
    object_store = LocalContentAddressedStore(root / "outputs/timeseries_v6/private_store/raw")
    partition_root = root / "outputs/timeseries_v6/private_store/observations"
    receipts: list[dict] = []
    partitions: list[dict] = []
    for spec in specs:
        body, media_type = fetcher(spec.uri)
        metadata = object_store.put(body, license_class="public_access_private_raw")
        parsed = parse_public_response(spec, body)
        for row in parsed:
            row["raw_object_sha256"] = metadata.object_sha256
            identity = "|".join((spec.source_id, spec.series_id, row["observation_time"].isoformat(), repr(row["value_numeric"]), metadata.object_sha256))
            row["observation_version_id"] = "tsv6-observation-" + hashlib.sha256(identity.encode()).hexdigest()[:24]
        table = pa.Table.from_pylist(parsed)
        semantic_hash = hashlib.sha256(table.to_pydict().__repr__().encode()).hexdigest()
        destination = partition_root / f"source_id={spec.source_id}" / f"series_id={spec.series_id}" / f"{semantic_hash}.parquet"
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            pq.write_table(table, destination, compression="zstd")
        partition_sha = hashlib.sha256(destination.read_bytes()).hexdigest()
        receipt_id = "tsv6-receipt-" + hashlib.sha256(f"{spec.source_id}|{spec.series_id}|{metadata.object_sha256}".encode()).hexdigest()[:24]
        receipts.append({
            "receipt_id": receipt_id, "source_id": spec.source_id, "series_id": spec.series_id,
            "source_uri": spec.uri, "object": metadata.as_dict(), "media_type": media_type,
            "collected_at": collected_at.isoformat(), "observation_count": len(parsed),
        })
        partitions.append({"source_id": spec.source_id, "series_id": spec.series_id, "path": destination.relative_to(root).as_posix(), "sha256": partition_sha, "row_count": len(parsed), "data_grade": spec.data_grade})
    manifest_core = {"schema_version": 1, "collected_at": collected_at.isoformat(), "receipts": receipts, "partitions": partitions}
    manifest_core["content_hash"] = hashlib.sha256(json.dumps(manifest_core, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return manifest_core
