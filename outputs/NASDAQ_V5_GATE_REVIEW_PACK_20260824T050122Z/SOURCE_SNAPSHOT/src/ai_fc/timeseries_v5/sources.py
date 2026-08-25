"""Public Core/Challenger registry, robust HTTP retrieval and parsers."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, replace
from datetime import datetime, time as daytime, timezone
from datetime import timedelta
from typing import Callable, Iterable
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET

from .identifiers import content_hash, stable_id
from .lineage import ParsedObservation, RawReceipt, build_versions, make_outcome


@dataclass(frozen=True)
class SourceSpec:
    source_id: str; provider: str; url: str; parser: str; authority_class: str; grade: str; cadence: str; redistribution: str; required_core: bool = False; method: str = "GET"; request_json: dict | None = None; required_secret: str | None = None


CBOE_BASE = "https://cdn.cboe.com/api/global/us_indices/daily_prices"
SOURCE_REGISTRY: dict[str, SourceSpec] = {
    "cboe_vix": SourceSpec("cboe_vix", "Cboe", f"{CBOE_BASE}/VIX_History.csv", "cboe_index", "core_market", "reconstructed_market_archive", "daily", "private_object_only", True),
    "cboe_vix9d": SourceSpec("cboe_vix9d", "Cboe", f"{CBOE_BASE}/VIX9D_History.csv", "cboe_index", "core_market", "reconstructed_market_archive", "daily", "private_object_only"),
    "cboe_vix3m": SourceSpec("cboe_vix3m", "Cboe", f"{CBOE_BASE}/VIX3M_History.csv", "cboe_index", "core_market", "reconstructed_market_archive", "daily", "private_object_only"),
    "cboe_vvix": SourceSpec("cboe_vvix", "Cboe", f"{CBOE_BASE}/VVIX_History.csv", "cboe_index", "core_market", "reconstructed_market_archive", "daily", "private_object_only"),
    "cboe_skew": SourceSpec("cboe_skew", "Cboe", f"{CBOE_BASE}/SKEW_History.csv", "cboe_index", "core_market", "reconstructed_market_archive", "daily", "private_object_only"),
    "ofr_fsi": SourceSpec("ofr_fsi", "Office of Financial Research", "https://www.financialresearch.gov/financial-stress-index/data/fsi.csv", "wide_csv", "official_reconstructed", "reconstructed_official_archive", "daily_t_plus_2", "repository_raw_allowed"),
    "fed_ebp": SourceSpec("fed_ebp", "Federal Reserve Board staff", "https://www.federalreserve.gov/econres/notes/feds-notes/ebp_csv.csv", "wide_csv", "official_research_reconstructed", "reconstructed_official_archive", "monthly", "repository_raw_allowed"),
    "nyfed_cmdi": SourceSpec("nyfed_cmdi", "Federal Reserve Bank of New York", "https://www.newyorkfed.org/medialibrary/research/interactives/data/cmdi/cmdi_interactive_data.xlsx", "xlsx", "official_research_reconstructed", "reconstructed_official_archive", "monthly", "repository_raw_allowed"),
    "chicago_fed_nfci": SourceSpec("chicago_fed_nfci", "Federal Reserve Bank of Chicago via FRED", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=NFCI", "fred_csv", "official_current_archive", "reconstructed_official_archive", "weekly", "private_object_only"),
    "fred_nasdaqcom": SourceSpec("fred_nasdaqcom", "Nasdaq via FRED", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=NASDAQCOM&cosd=1995-01-01", "fred_csv", "core_market", "reconstructed_market_archive", "daily", "private_object_only", True),
    "fred_h10_dollar": SourceSpec("fred_h10_dollar", "Federal Reserve H.10 via FRED", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DTWEXBGS&cosd=2006-01-01", "fred_csv", "core_market", "reconstructed_market_archive", "daily", "private_object_only", True),
    "treasury_dts": SourceSpec("treasury_dts", "U.S. Treasury Fiscal Data", "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/operating_cash_balance?sort=-record_date&page[size]=10000", "fiscal_json", "official", "reconstructed_official_archive", "daily", "repository_raw_allowed"),
    "treasury_yield_curve": SourceSpec("treasury_yield_curve", "U.S. Treasury", "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value=2026", "treasury_xml", "official", "reconstructed_official_archive", "daily", "repository_raw_allowed", True),
    "treasury_real_yield_curve": SourceSpec("treasury_real_yield_curve", "U.S. Treasury", "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?data=daily_treasury_real_yield_curve&field_tdr_date_value=2026", "treasury_xml", "official", "reconstructed_official_archive", "daily", "repository_raw_allowed"),
    "nyfed_reference_rates": SourceSpec("nyfed_reference_rates", "Federal Reserve Bank of New York", "https://markets.newyorkfed.org/api/rates/all/latest.json", "nyfed_json", "official", "captured_forward", "daily", "repository_raw_allowed"),
    "fed_h41_walcl": SourceSpec("fed_h41_walcl", "Federal Reserve H.4.1 via FRED", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=WALCL&cosd=2006-01-01", "fred_csv", "official_current_archive", "reconstructed_official_archive", "weekly", "private_object_only"),
    "fred_tga": SourceSpec("fred_tga", "U.S. Treasury via FRED", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=WTREGEN&cosd=2006-01-01", "fred_csv", "official_current_archive", "reconstructed_official_archive", "weekly", "private_object_only"),
    "nyfed_rrp": SourceSpec("nyfed_rrp", "Federal Reserve Bank of New York via FRED", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=RRPONTSYD&cosd=2006-01-01", "fred_csv", "official_current_archive", "reconstructed_official_archive", "daily", "private_object_only"),
    "cftc_tff": SourceSpec("cftc_tff", "Commodity Futures Trading Commission", "https://www.cftc.gov/files/dea/history/fut_fin_txt_2026.zip", "zip_csv", "official", "reconstructed_official_archive", "weekly", "repository_raw_allowed"),
    "finra_otc": SourceSpec("finra_otc", "FINRA", "https://api.finra.org/data/group/otcmarket/name/weeklysummary", "finra_json", "self_regulatory", "reconstructed_official_archive", "weekly", "private_object_only", False, "POST", {"limit": 5000, "offset": 0, "fields": ["summaryStartDate", "initialPublishedDate", "lastUpdateDate", "totalWeeklyTradeCount", "totalWeeklyShareQuantity", "totalNotionalSum", "tierIdentifier", "summaryTypeCode"], "compareFilters": [{"compareType": "equal", "fieldName": "summaryTypeCode", "fieldValue": "ATS_W_VOL_STATS"}]}),
    "sec_companyfacts": SourceSpec("sec_companyfacts", "SEC EDGAR", "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json", "sec_json", "official", "reconstructed_official_archive", "daily", "repository_raw_allowed"),
    "fed_fama_french": SourceSpec("fed_fama_french", "Kenneth French Data Library", "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_daily_CSV.zip", "fama_french_zip", "academic", "reconstructed_official_archive", "monthly", "private_object_only"),
    "eia_crude_oil": SourceSpec("eia_crude_oil", "U.S. Energy Information Administration", "https://api.eia.gov/v2/petroleum/pri/spt/data/?api_key={EIA_API_KEY}&frequency=daily&data[0]=value&facets[series][]=RWTC&sort[0][column]=period&sort[0][direction]=asc&offset=0&length=5000", "eia_json", "official", "reconstructed_official_archive", "daily", "repository_raw_allowed", False, "GET", None, "EIA_API_KEY"),
    "philadelphia_spf": SourceSpec("philadelphia_spf", "Federal Reserve Bank of Philadelphia", "https://www.philadelphiafed.org/-/media/FRBP/Assets/Surveys-And-Data/survey-of-professional-forecasters/historical-data/meanLevel.xlsx?sc_lang=en", "xlsx", "official_survey", "reconstructed_official_archive", "quarterly", "repository_raw_allowed"),
}

SECRET_QUERY_KEYS = {"api_key", "apikey", "key", "token", "access_token"}


def sanitized_uri(url: str) -> str:
    parsed = urllib.parse.urlsplit(url); pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    safe = [(key, "REDACTED" if key.lower() in SECRET_QUERY_KEYS else value) for key, value in pairs]
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(safe), parsed.fragment))


class HttpClient:
    def __init__(self, *, timeout: float = 45.0, attempts: int = 4, max_bytes: int = 100_000_000, user_agent: str = "ai-investing-research/5.0 contact=repository-owner"):
        self.timeout = timeout; self.attempts = attempts; self.max_bytes = max_bytes; self.user_agent = user_agent

    def get(self, url: str, *, headers: dict[str, str] | None = None) -> tuple[int, bytes, dict[str, str]]:
        request_headers = {"User-Agent": self.user_agent, "Accept-Encoding": "identity", **(headers or {})}; last: Exception | None = None
        for attempt in range(self.attempts):
            try:
                request = urllib.request.Request(url, headers=request_headers)
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    length = int(response.headers.get("Content-Length", "0") or 0)
                    if length > self.max_bytes: raise ValueError("response exceeds configured size limit")
                    body = response.read(self.max_bytes + 1)
                    if len(body) > self.max_bytes: raise ValueError("response exceeds configured size limit")
                    return int(response.status), body, {key.lower(): value for key, value in response.headers.items()}
            except urllib.error.HTTPError as exc:
                if exc.code not in {429, 500, 502, 503, 504}: raise
                last = exc; retry_after = float(exc.headers.get("Retry-After", "0") or 0)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = exc; retry_after = 0.0
            if attempt + 1 < self.attempts: time.sleep(max(retry_after, min(8.0, (2**attempt) + random.random())))
        raise RuntimeError(f"HTTP retrieval failed after {self.attempts} attempts: {type(last).__name__}")

    def post_json(self, url: str, payload: dict, *, headers: dict[str, str] | None = None) -> tuple[int, bytes, dict[str, str]]:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        request_headers = {"User-Agent": self.user_agent, "Accept-Encoding": "identity", "Accept": "application/json", "Content-Type": "application/json", **(headers or {})}
        request = urllib.request.Request(url, data=body, headers=request_headers, method="POST")
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            content = response.read(self.max_bytes + 1)
            if len(content) > self.max_bytes: raise ValueError("response exceeds configured size limit")
            return int(response.status), content, {key.lower(): value for key, value in response.headers.items()}


def _timestamp(day: str, hour: int = 16, minute: int = 15) -> datetime:
    value = datetime.fromisoformat(day).date(); return datetime.combine(value, daytime(hour, minute), tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)


def _available_at(spec: SourceSpec, day: str) -> datetime:
    base = _timestamp(day, 18, 0)
    if spec.source_id == "cftc_tff":
        return base + timedelta(days=6)  # conservative archive reconstruction; normal publication is Friday.
    if spec.source_id == "nyfed_cmdi":
        return base + timedelta(days=35)  # weekly components are released only in a later monthly vintage.
    if spec.source_id == "ofr_fsi":
        candidate = base
        added = 0
        while added < 2:
            candidate += timedelta(days=1)
            if candidate.weekday() < 5: added += 1
        return candidate
    return base


def _date(value: str) -> str | None:
    text = value.strip()
    if re.fullmatch(r"\d{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    for pattern in (r"(\d{4})-(\d{2})-(\d{2})", r"(\d{1,2})/(\d{1,2})/(\d{4})", r"(\d{1,2})/(\d{1,2})/(\d{2})"):
        match = re.fullmatch(pattern, text)
        if match:
            parts = [int(item) for item in match.groups()]
            if pattern.startswith("(\\d{4}"): year, month, day = parts
            else:
                month, day, year = parts; year += 2000 if year < 100 and year < 70 else 1900 if year < 100 else 0
            return f"{year:04d}-{month:02d}-{day:02d}"
    return None


def parse_csv(spec: SourceSpec, body: bytes) -> list[ParsedObservation]:
    text = body.decode("utf-8-sig", errors="replace"); rows = list(csv.DictReader(io.StringIO(text)))
    if not rows: return []
    date_candidates = ("DATE", "Date", "date", "Record Date", "record_date", "observation_date", "Report_Date_as_YYYY-MM-DD", "Report_Date_as_MM_DD_YYYY", "summaryStartDate", "weekStartDate")
    date_key = next((key for key in date_candidates if key in rows[0]), None)
    if date_key is None: raise ValueError("CSV date column not recognized")
    output: list[ParsedObservation] = []
    for row in rows:
        if spec.source_id == "cftc_tff":
            market = str(row.get("Market_and_Exchange_Names") or "").upper()
            if not any(token in market for token in ("NASDAQ", "VIX", "S&P 500")):
                continue
        day = _date(str(row.get(date_key, "")))
        if day is None: continue
        dimensions: dict[str, str] = {}
        for dimension_key, dimension_value in row.items():
            if dimension_key == date_key or dimension_value is None or dimension_value == "": continue
            try: float(str(dimension_value).replace(",", ""))
            except ValueError: dimensions[dimension_key] = str(dimension_value)[:160]
        numeric = []
        for key, raw in row.items():
            if key == date_key or raw in {None, "", ".", "NA", "N/A"}: continue
            try: numeric.append((key, float(str(raw).replace(",", ""))))
            except ValueError: continue
        if spec.parser in {"cboe_index", "fred_csv"}:
            preferred = next(((key, value) for key, value in numeric if key.upper() in {"CLOSE", spec.source_id.removeprefix("cboe_").upper(), "NASDAQCOM", "DTWEXBGS", "NFCI", "WALCL", "WTREGEN", "RRPONTSYD"}), numeric[-1:] and numeric[-1])
            numeric = [] if not preferred else [preferred]
        for key, value in numeric:
            series = spec.source_id.removeprefix("cboe_").upper() if spec.parser == "cboe_index" and key.upper() == "CLOSE" else re.sub(r"[^A-Z0-9]+", "_", key.upper()).strip("_")
            output.append(ParsedObservation(series_id=series, observation_time=_timestamp(day, 16, 0), value=value, unit="index_level" if spec.parser in {"cboe_index", "fred_csv"} else "provider_native", available_at=_available_at(spec, day), data_grade=spec.grade, dimensions={"source_field": key, **dimensions}))
    return output


def parse_treasury_xml(spec: SourceSpec, body: bytes) -> list[ParsedObservation]:
    root = ET.fromstring(body); output: list[ParsedObservation] = []
    for entry in root.findall(".//{http://www.w3.org/2005/Atom}entry"):
        properties = entry.find(".//{http://schemas.microsoft.com/ado/2007/08/dataservices/metadata}properties")
        if properties is None: continue
        values = {node.tag.rsplit("}", 1)[-1]: node.text for node in list(properties)}
        day = _date(str(values.get("NEW_DATE") or "")[:10])
        if day is None: continue
        for key, raw in values.items():
            if key in {"Id", "NEW_DATE"} or raw in {None, ""}: continue
            try: value = float(str(raw))
            except ValueError: continue
            output.append(ParsedObservation(series_id=f"TREASURY_{key}", observation_time=_timestamp(day, 16, 0), value=value, unit="percentage_point", available_at=_available_at(spec, day), data_grade=spec.grade, dimensions={"source_field": key}))
    return output


def parse_fama_french_zip(spec: SourceSpec, body: bytes) -> list[ParsedObservation]:
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        name = next((value for value in archive.namelist() if value.lower().endswith(".csv")), None)
        if name is None: return []
        lines = archive.read(name).decode("utf-8-sig", errors="replace").splitlines()
    header = next((index for index, line in enumerate(lines) if "Mkt-RF" in line and "SMB" in line), None)
    if header is None: raise ValueError("Fama-French header not found")
    output: list[ParsedObservation] = []
    for values in csv.reader(lines[header + 1:]):
        if not values or _date(values[0].strip()) is None: continue
        day = _date(values[0].strip()); assert day is not None
        for key, raw in zip(("MKT_RF", "SMB", "HML", "RF"), values[1:5], strict=False):
            try: value = float(raw) / 100.0
            except ValueError: continue
            output.append(ParsedObservation(series_id=f"FF_{key}", observation_time=_timestamp(day, 16, 0), value=value, unit="signed_fraction", available_at=_available_at(spec, day), data_grade=spec.grade, dimensions={"source_field": key}))
    return output


def parse_json(spec: SourceSpec, body: bytes) -> list[ParsedObservation]:
    payload = json.loads(body); output: list[ParsedObservation] = []
    rows: Iterable[dict]
    if spec.parser == "fiscal_json": rows = payload.get("data", [])
    elif spec.parser == "nyfed_json": rows = payload.get("refRates", payload.get("data", []))
    elif spec.parser == "finra_json": rows = payload if isinstance(payload, list) else payload.get("data", [])
    elif spec.parser == "eia_json": rows = payload.get("response", {}).get("data", [])
    else: return []
    for row in rows:
        if not isinstance(row, dict): continue
        date_value = next((str(row[key]) for key in ("record_date", "effectiveDate", "summaryStartDate", "weekStartDate", "weekEndDate", "date", "period") if row.get(key)), "")
        day = _date(date_value[:10])
        if day is None: continue
        dimensions: dict[str, str] = {}
        for dimension_key, dimension_value in row.items():
            if dimension_key.lower().endswith("date") or dimension_key in {"record_date", "initialPublishedDate", "lastUpdateDate"} or dimension_value is None or dimension_value == "":
                continue
            try: float(str(dimension_value).replace(",", ""))
            except (TypeError, ValueError): dimensions[dimension_key] = str(dimension_value)[:160]
        for key, raw in row.items():
            if key.lower().endswith("date") or key in {"record_date"}: continue
            try: value = float(str(raw).replace(",", ""))
            except (TypeError, ValueError): continue
            series = f"{spec.source_id.upper()}_{re.sub(r'[^A-Z0-9]+', '_', key.upper()).strip('_')}"
            publication = next((str(row[key]) for key in ("initialPublishedDate", "lastUpdateDate") if row.get(key)), None)
            publication_day = _date(publication[:10]) if publication else None
            available_at = _timestamp(publication_day, 18, 0) if publication_day else _available_at(spec, day)
            output.append(ParsedObservation(series_id=series, observation_time=_timestamp(day, 16, 0), value=value, unit="provider_native", available_at=available_at, data_grade=spec.grade, dimensions={"source_field": key, **dimensions}))
    return output


def _xlsx_sheets(body: bytes) -> list[tuple[str, list[list[object]]]]:
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            tree = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(node.text or "" for node in item.iter() if node.tag.endswith("}t")) for item in tree.findall("{*}si")]
        date_styles: set[int] = set()
        if "xl/styles.xml" in archive.namelist():
            styles = ET.fromstring(archive.read("xl/styles.xml"))
            custom = {int(node.attrib["numFmtId"]): node.attrib.get("formatCode", "") for node in styles.findall(".//{*}numFmt")}
            cell_xfs = styles.find("{*}cellXfs")
            if cell_xfs is not None:
                for index, node in enumerate(list(cell_xfs)):
                    number = int(node.attrib.get("numFmtId", "0")); code = custom.get(number, "")
                    if number in {14, 15, 16, 17, 22, 45, 46, 47} or re.search(r"[dmy]", code, re.I): date_styles.add(index)
        workbook = ET.fromstring(archive.read("xl/workbook.xml")); relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        target_by_id = {item.attrib.get("Id"): item.attrib.get("Target") for item in relationships.findall("{*}Relationship")}
        output: list[tuple[str, list[list[object]]]] = []
        for sheet_info in workbook.findall(".//{*}sheet"):
            relationship_id = sheet_info.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"); target = target_by_id.get(relationship_id)
            if not target: continue
            path = str(target).lstrip("/"); path = path if path.startswith("xl/") else f"xl/{path}"
            sheet = ET.fromstring(archive.read(path)); rows: list[list[object]] = []
            for row in sheet.findall(".//{*}row"):
                cells: dict[int, object] = {}
                for cell in row.findall("{*}c"):
                    match = re.match(r"[A-Z]+", str(cell.attrib.get("r") or "A1"))
                    if not match: continue
                    index = 0
                    for letter in match.group(0): index = index * 26 + ord(letter) - 64
                    value_node = cell.find("{*}v")
                    if cell.attrib.get("t") == "inlineStr": value: object = "".join(node.text or "" for node in cell.iter() if node.tag.endswith("}t"))
                    elif value_node is None: value = ""
                    elif cell.attrib.get("t") == "s": value = shared[int(value_node.text or 0)]
                    else:
                        raw = value_node.text or ""
                        try:
                            numeric = float(raw)
                            if int(cell.attrib.get("s", "0")) in date_styles:
                                value = datetime(1899, 12, 30) + timedelta(days=numeric)
                            else: value = numeric
                        except ValueError: value = raw
                    cells[index - 1] = value
                if cells: rows.append([cells.get(index, "") for index in range(max(cells) + 1)])
            output.append((str(sheet_info.attrib.get("name") or "Sheet"), rows))
        return output


def parse_xlsx(spec: SourceSpec, body: bytes) -> list[ParsedObservation]:
    output: list[ParsedObservation] = []
    for sheet_name, rows in _xlsx_sheets(body):
        if len(rows) < 2: continue
        header_index = next((index for index, row in enumerate(rows[:30]) if any(str(value).lower() in {"date", "year", "quarter", "eow_friday"} for value in row)), 0)
        headers = [str(value).strip() or f"column_{index}" for index, value in enumerate(rows[header_index])]
        for row in rows[header_index + 1:]:
            values = dict(zip(headers, row, strict=False)); lower = {key.lower(): key for key in headers}
            if "year" in lower and "quarter" in lower:
                try:
                    year = int(float(values[lower["year"]])); quarter = int(float(values[lower["quarter"]]))
                except (TypeError, ValueError): continue
                day = f"{year:04d}-{1 + (quarter - 1) * 3:02d}-01"
                available_day = (datetime(year, quarter * 3, 1) + timedelta(days=62)).replace(day=1) - timedelta(days=1)
                available_at = _timestamp(available_day.date().isoformat(), 18, 0)
            else:
                date_key = next((lower[key] for key in ("date", "observation_date", "eow_friday") if key in lower), None)
                raw_date = values.get(date_key) if date_key else None
                if isinstance(raw_date, datetime): day = raw_date.date().isoformat()
                else: day = _date(str(raw_date)[:10]) if raw_date is not None else None
                if day is None: continue
                available_at = _available_at(spec, day)
            for key, raw in values.items():
                if key.lower() in {"date", "observation_date", "eow_friday", "year", "quarter"}: continue
                try: value = float(raw)
                except (TypeError, ValueError): continue
                series = re.sub(r"[^A-Z0-9]+", "_", f"{sheet_name}_{key}".upper()).strip("_")
                output.append(ParsedObservation(series_id=series, observation_time=_timestamp(day, 16, 0), value=value, unit="provider_native", available_at=available_at, data_grade=spec.grade, dimensions={"sheet": sheet_name, "source_field": key}))
    return output


def parse_body(spec: SourceSpec, body: bytes) -> list[ParsedObservation]:
    if spec.parser in {"cboe_index", "wide_csv", "fred_csv"}: return parse_csv(spec, body)
    if spec.parser in {"fiscal_json", "nyfed_json", "finra_json", "sec_json", "eia_json"}: return parse_json(spec, body)
    if spec.parser == "zip_csv":
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            names = [name for name in archive.namelist() if name.lower().endswith(('.csv', '.txt'))]
            if not names: return []
            nested = SourceSpec(**{**spec.__dict__, "parser": "wide_csv"})
            return parse_csv(nested, archive.read(names[0]))
    if spec.parser == "xlsx": return parse_xlsx(spec, body)
    if spec.parser == "treasury_xml": return parse_treasury_xml(spec, body)
    if spec.parser == "fama_french_zip": return parse_fama_french_zip(spec, body)
    raise ValueError(f"unknown parser: {spec.parser}")


def expanded_source_specs(spec: SourceSpec, *, current_year: int | None = None) -> list[SourceSpec]:
    """Expand official annual archives while keeping one logical source_id."""
    year = current_year or datetime.now(timezone.utc).year
    if spec.source_id in {"treasury_yield_curve", "treasury_real_yield_curve"}:
        data_name = "daily_treasury_real_yield_curve" if spec.source_id == "treasury_real_yield_curve" else "daily_treasury_yield_curve"
        return [replace(spec, url=f"https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?data={data_name}&field_tdr_date_value={value}") for value in range(2007, year + 1)]
    if spec.source_id == "cftc_tff":
        return [replace(spec, url=f"https://www.cftc.gov/files/dea/history/fut_fin_txt_{value}.zip") for value in range(2010, year + 1)]
    return [spec]


def collect_source(spec: SourceSpec, *, run_id: str, control, objects, client: HttpClient, retrieved_at: datetime | None = None) -> dict:
    retrieved = retrieved_at or datetime.now(timezone.utc); safe_url = sanitized_uri(spec.url)
    if spec.required_secret:
        import os
        secret = os.environ.get(spec.required_secret)
        if not secret: raise RuntimeError(f"required collector secret unavailable:{spec.required_secret}")
        request_url = spec.url.replace("{" + spec.required_secret + "}", urllib.parse.quote(secret, safe=""))
    else: request_url = spec.url
    if spec.method == "POST": status, body, headers = client.post_json(request_url, spec.request_json or {})
    else: status, body, headers = client.get(request_url)
    raw = objects.put_raw(spec.source_id, body, content_type=headers.get("content-type", "application/octet-stream"), metadata={"provider": spec.provider, "redistribution": spec.redistribution})
    receipt_core = {"run_id": run_id, "source_id": spec.source_id, "raw_sha256": raw["sha256"], "raw_uri": raw["uri"], "source_uri": safe_url, "request_fingerprint": content_hash({"url": safe_url, "method": spec.method, "body": spec.request_json}), "retrieved_at": retrieved, "http_status": status, "content_type": raw["content_type"], "schema_fingerprint": hashlib.sha256(body[:65536]).hexdigest(), "etag": headers.get("etag"), "last_modified": headers.get("last-modified")}
    receipt = RawReceipt(receipt_id=stable_id("receipt", receipt_core), **receipt_core); control.append("raw_receipts", receipt.model_dump(mode="json"), identity="receipt_id")
    try:
        parsed = parse_body(spec, body); versions, links, terminal = build_versions(source_id=spec.source_id, receipt=receipt, parsed=parsed, prior_rows=control.rows("observations"), created_at=retrieved)
        control.append_bundle([
            ("observations", [row.model_dump(mode="json") for row in versions], "observation_id"),
            ("receipt_fact_links", links, "link_id"),
        ])
        outcome = make_outcome(receipt.receipt_id, terminal, parser_version="v5.1", fact_count=len(versions), reason="parser intentionally stores raw only" if not parsed else None, created_at=retrieved)
    except (ValueError, KeyError, csv.Error, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        outcome = make_outcome(receipt.receipt_id, "parse_failed", parser_version="v5.1", fact_count=0, reason=f"{type(exc).__name__}:{exc}", created_at=retrieved)
    control.append("parse_outcomes", outcome.model_dump(mode="json"), identity="outcome_id")
    return {"source_id": spec.source_id, "receipt_id": receipt.receipt_id, "outcome": outcome.outcome, "facts": outcome.fact_count, "raw_sha256": receipt.raw_sha256}
