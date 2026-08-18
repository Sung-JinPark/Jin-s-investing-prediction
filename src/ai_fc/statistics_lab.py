from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ai_fc.quant import feed


LATEST_RELATIVE = Path("data/statistics/dotcom_statistics_latest.json")
ARCHIVE_RELATIVE = Path("data/statistics/archive")
CONTRACT_RELATIVE = Path("data/contracts/statistics_lab_v1.yaml")
IPO_REFERENCE_RELATIVE = Path("data/statistics/ipo/ipo_comparison_v1.json")
HMI_REFERENCE_RELATIVE = Path("data/statistics/reference/nahb_hmi_history_v1.json")
ICI_REFERENCE_RELATIVE = Path("data/statistics/reference/ici_weekly_equity_etf_flow_v1.json")
DOTCOM_START = date(1995, 1, 1)
DOTCOM_END = date(1999, 12, 31)
CURRENT_START = date(2023, 1, 1)
CURRENT_AXIS_END = date(2027, 12, 31)
COMPARISON_MONTHS = 59
FRED_ENDPOINT = "https://fred.stlouisfed.org/graph/fredgraph.csv"
Z1_ENDPOINT = "https://www.federalreserve.gov/releases/z1/current/z1_csv_files.zip"
SEC_IPO_ENDPOINT = "https://www.sec.gov/data-research/statistics-data-visualizations/initial-public-offerings-ipos"
ICI_ETF_ENDPOINT = "https://www.ici.org/research/stats/etf_flows"
NYU_RETURNS_ENDPOINT = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/histretSP.xlsx"
USER_AGENT = "JinsInvestingStatisticsLab/1.0 (+public research dashboard)"

FRED_SERIES: dict[str, dict[str, str]] = {
    "M2SL": {
        "title": "M2 money stock",
        "provider": "Board of Governors of the Federal Reserve System (US)",
        "unit": "billions_usd",
        "native_frequency": "monthly",
        "aggregation": "last",
    },
    "DABSHNO": {
        "title": "Households and nonprofit organizations; total currency and deposits including money market fund shares",
        "provider": "Board of Governors of the Federal Reserve System (US)",
        "unit": "millions_usd",
        "native_frequency": "quarterly_end_of_period",
        "aggregation": "last",
    },
    "BOGZ1LM153064475Q": {
        "title": "Households and nonprofit organizations; directly and indirectly held corporate equities",
        "provider": "Board of Governors of the Federal Reserve System (US)",
        "unit": "millions_usd",
        "native_frequency": "quarterly_end_of_period",
        "aggregation": "last",
    },
    "BOGZ1FL154022375A": {
        "title": "Households and nonprofit organizations; directly and indirectly held debt securities",
        "provider": "Board of Governors of the Federal Reserve System (US)",
        "unit": "millions_usd",
        "native_frequency": "annual_end_of_period",
        "aggregation": "last",
    },
    "NASDAQCOM": {
        "title": "NASDAQ Composite Index",
        "provider": "NASDAQ OMX Group via FRED",
        "unit": "index",
        "native_frequency": "daily_close",
        "aggregation": "last",
        "window_start": "1985-01-01",
    },
    "T10Y2Y": {
        "title": "10-year minus 2-year Treasury spread",
        "provider": "Federal Reserve Bank of St. Louis / U.S. Treasury",
        "unit": "percent",
        "native_frequency": "daily",
        "aggregation": "mean",
    },
    "FEDFUNDS": {
        "title": "Effective federal funds rate",
        "provider": "Board of Governors of the Federal Reserve System (US)",
        "unit": "percent",
        "native_frequency": "monthly",
        "aggregation": "last",
    },
    "TOTALSL": {
        "title": "Total consumer credit owned and securitized",
        "provider": "Board of Governors of the Federal Reserve System (US)",
        "unit": "millions_usd",
        "native_frequency": "monthly",
        "aggregation": "last",
    },
    "TDSP": {
        "title": "Household debt service ratio",
        "provider": "Board of Governors of the Federal Reserve System (US)",
        "unit": "percent",
        "native_frequency": "quarterly",
        "aggregation": "last",
    },
    "BOGZ1FL010000346Q": {
        "title": "Household debt service and principal payments as a percent of income",
        "provider": "Board of Governors of the Federal Reserve System (US)",
        "unit": "percent",
        "native_frequency": "quarterly",
        "aggregation": "last",
    },
    "DRTSCILM": {
        "title": "Banks tightening C&I standards, large and middle-market firms",
        "provider": "Board of Governors of the Federal Reserve System (US)",
        "unit": "percent",
        "native_frequency": "quarterly",
        "aggregation": "last",
    },
    "NCBEILQ027S": {
        "title": "Nonfinancial corporate equities, liability level",
        "provider": "Board of Governors of the Federal Reserve System (US)",
        "unit": "millions_usd",
        "native_frequency": "quarterly",
        "aggregation": "last",
    },
    "CPATAX": {
        "title": "Corporate profits after tax with IVA and CCAdj",
        "provider": "U.S. Bureau of Economic Analysis",
        "unit": "billions_usd_saar",
        "native_frequency": "quarterly",
        "aggregation": "last",
    },
    "UNRATE": {
        "title": "Civilian unemployment rate",
        "provider": "U.S. Bureau of Labor Statistics",
        "unit": "percent",
        "native_frequency": "monthly",
        "aggregation": "last",
    },
    "CPIAUCSL": {
        "title": "Consumer Price Index for All Urban Consumers",
        "provider": "U.S. Bureau of Labor Statistics",
        "unit": "index_1982_1984_100",
        "native_frequency": "monthly",
        "aggregation": "last",
    },
    "NFCI": {
        "title": "Chicago Fed National Financial Conditions Index",
        "provider": "Federal Reserve Bank of Chicago",
        "unit": "standard_deviation_index",
        "native_frequency": "weekly",
        "aggregation": "mean",
    },
    "BOGZ1LM893064105Q": {
        "title": "All sectors; corporate equities; market value",
        "provider": "Board of Governors of the Federal Reserve System (US)",
        "unit": "millions_usd",
        "native_frequency": "quarterly",
        "aggregation": "last",
    },
    "HQMCB10YR": {
        "title": "10-year high quality market corporate bond spot rate",
        "provider": "U.S. Department of the Treasury",
        "unit": "percent",
        "native_frequency": "monthly",
        "aggregation": "last",
    },
    "GS10": {
        "title": "Market yield on U.S. Treasury securities at 10-year constant maturity",
        "provider": "Board of Governors of the Federal Reserve System (US)",
        "unit": "percent",
        "native_frequency": "monthly",
        "aggregation": "last",
    },
    "DCOILWTICO": {
        "title": "Crude oil prices: West Texas Intermediate",
        "provider": "U.S. Energy Information Administration",
        "unit": "dollars_per_barrel",
        "native_frequency": "daily",
        "aggregation": "mean",
    },
    "WPU10260314": {
        "title": "Producer Price Index by Commodity: Copper Wire and Cable",
        "provider": "U.S. Bureau of Labor Statistics",
        "unit": "index_1982_100",
        "native_frequency": "monthly",
        "aggregation": "last",
    },
    "GACDFSA066MSFRBPHI": {
        "title": "Philadelphia Fed manufacturing current general activity diffusion index",
        "provider": "Federal Reserve Bank of Philadelphia",
        "unit": "diffusion_index",
        "native_frequency": "monthly",
        "aggregation": "last",
    },
}

DAILY_MARKET_SERIES: dict[str, dict[str, str]] = {
    "KOSPI_DAILY": {
        "symbol": "^KS11",
        "title": "KOSPI daily close",
        "provider": "Yahoo Finance chart API (underlying benchmark: Korea Exchange KOSPI)",
        "unit": "index",
        "native_frequency": "daily_close",
        "window_start": "2020-01-01",
        "window_end_exclusive": "2027-01-01",
        "source_url": "https://finance.yahoo.com/quote/%5EKS11/history/",
    },
    "KOSDAQ_DAILY": {
        "symbol": "^KQ11",
        "title": "KOSDAQ daily close",
        "provider": "Yahoo Finance chart API (underlying benchmark: Korea Exchange KOSDAQ)",
        "unit": "index",
        "native_frequency": "daily_close",
        "window_start": "2020-01-01",
        "window_end_exclusive": "2027-01-01",
        "source_url": "https://finance.yahoo.com/quote/%5EKQ11/history/",
    },
    "KRX_SEMICON_PROXY_DAILY": {
        "symbol": "091160.KS",
        "title": "KODEX Semiconductor ETF daily close",
        "provider": "Yahoo Finance chart API (ETF tracks the KRX Semiconductor Index)",
        "unit": "krw",
        "native_frequency": "daily_close",
        "window_start": "2020-01-01",
        "window_end_exclusive": "2027-01-01",
        "source_url": "https://finance.yahoo.com/quote/091160.KS/history/",
    },
    "TAIEX_DAILY": {
        "symbol": "^TWII",
        "title": "Taiwan Stock Exchange Capitalization Weighted Stock Index daily close",
        "provider": "Yahoo Finance chart API (underlying benchmark: Taiwan Stock Exchange TAIEX)",
        "unit": "index",
        "native_frequency": "daily_close",
        "window_start": "2020-01-01",
        "window_end_exclusive": "2027-01-01",
        "source_url": "https://finance.yahoo.com/quote/%5ETWII/history/",
    },
    "SOX_DAILY": {
        "symbol": "^SOX",
        "title": "PHLX Semiconductor Sector Index daily close",
        "provider": "Yahoo Finance chart API (underlying benchmark: Nasdaq PHLX SOX)",
        "unit": "index",
        "native_frequency": "daily_close",
        "window_start": "2020-01-01",
        "window_end_exclusive": "2027-01-01",
        "source_url": "https://finance.yahoo.com/quote/%5ESOX/history/",
    },
    "SP500_DAILY": {
        "symbol": "^GSPC",
        "title": "S&P 500 daily close",
        "provider": "Yahoo Finance chart API (underlying benchmark: S&P Dow Jones Indices)",
        "unit": "index",
        "native_frequency": "daily_close",
        "window_start": "1970-01-02",
        "window_end_exclusive": "2027-01-01",
        "source_url": "https://finance.yahoo.com/quote/%5EGSPC/history/",
    },
    "GOLD_DAILY": {
        "symbol": "GC=F",
        "title": "COMEX gold futures continuous contract daily close",
        "provider": "Yahoo Finance chart API (underlying market: COMEX gold futures)",
        "unit": "usd_per_troy_ounce",
        "native_frequency": "daily_close",
        "window_start": "2022-01-01",
        "window_end_exclusive": "2027-01-01",
        "source_url": "https://finance.yahoo.com/quote/GC%3DF/history/",
    },
}

SUPPLEMENTAL_SOURCES: dict[str, dict[str, str]] = {
    "SEC_IPO_QUARTERLY": {
        "title": "U.S. IPO counts and proceeds by issuer type",
        "provider": "U.S. Securities and Exchange Commission",
        "unit": "counts_and_millions_usd",
        "native_frequency": "quarterly",
        "source_url": "https://www.sec.gov/data-research/statistics-data-visualizations/initial-public-offerings-ipos",
        "request_url": SEC_IPO_ENDPOINT,
    },
    "ICI_WEEKLY_EQUITY_ETF_FLOW": {
        "title": "Estimated ETF net issuance",
        "provider": "Investment Company Institute",
        "unit": "millions_usd",
        "native_frequency": "weekly_estimate",
        "source_url": ICI_ETF_ENDPOINT,
        "request_url": ICI_ETF_ENDPOINT,
    },
    "NYU_SP500_ANNUAL_TOTAL_RETURN": {
        "title": "S&P 500 annual total returns including dividends",
        "provider": "Aswath Damodaran, NYU Stern School of Business",
        "unit": "percent_total_return",
        "native_frequency": "annual",
        "source_url": "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/histretSP.html",
        "request_url": NYU_RETURNS_ENDPOINT,
    },
}


class StatisticsLabError(ValueError):
    pass


def _validate_manual_reference_freshness(
    ipo_reference: dict[str, Any], hmi_reference: dict[str, Any], generated_at: str,
    ici_reference: dict[str, Any] | None = None,
) -> None:
    """Fail the weekly job instead of silently republishing stale manual cohorts."""
    collected = datetime.fromisoformat(generated_at.replace("Z", "+00:00")).date()
    checks = [
        ("IPO reviewed cohort", date.fromisoformat(str(ipo_reference["as_of"])), 14),
        ("NAHB HMI reference", date.fromisoformat(str(hmi_reference["as_of"])), 62),
    ]
    if ici_reference is not None:
        checks.append((
            "ICI weekly ETF reference", date.fromisoformat(str(ici_reference["as_of"])), 14,
        ))
    for label, observed, maximum_age in checks:
        age = (collected - observed).days
        if age < 0:
            raise StatisticsLabError(f"{label} is dated after collector time")
        if age > maximum_age:
            raise StatisticsLabError(
                f"{label} stale: {age} days > {maximum_age}; manual source review required"
            )


def _request(url: str, *, timeout: int = 45, attempts: int = 3) -> bytes:
    """Fetch one public source with bounded transient-error retries.

    The collector remains fail-closed: it never substitutes the prior snapshot
    or another provider.  Only network timeouts, connection failures, HTTP 429,
    and HTTP 5xx responses are retried; permanent HTTP errors fail immediately.
    """
    if attempts < 1:
        raise ValueError("request attempts must be positive")
    last_error: BaseException | None = None
    for attempt in range(attempts):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code != 429 and not 500 <= exc.code <= 599:
                raise
            last_error = exc
        except (TimeoutError, urllib.error.URLError, ConnectionError) as exc:
            last_error = exc
        if attempt + 1 < attempts:
            time.sleep(min(2 ** attempt, 8))
    raise StatisticsLabError(
        f"public source request failed after {attempts} attempts: {url}"
    ) from last_error


def _xlsx_sheet_rows(raw: bytes, sheet_name: str) -> list[list[Any]]:
    """Read values from one XLSX worksheet with only the standard library."""
    namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel_namespace = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    package_namespace = "http://schemas.openxmlformats.org/package/2006/relationships"
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            relationship_targets = {
                row.attrib["Id"]: row.attrib["Target"]
                for row in rels.findall(f"{{{package_namespace}}}Relationship")
            }
            sheet_target = None
            for sheet in workbook.findall(f".//{{{namespace}}}sheet"):
                if sheet.attrib.get("name") == sheet_name:
                    sheet_target = relationship_targets.get(
                        sheet.attrib.get(f"{{{rel_namespace}}}id", "")
                    )
                    break
            if not sheet_target:
                raise StatisticsLabError(f"XLSX worksheet missing: {sheet_name}")
            sheet_path = (
                f"xl/{sheet_target}" if not sheet_target.startswith("xl/") else sheet_target
            ).replace("xl/../", "")
            shared_strings: list[str] = []
            if "xl/sharedStrings.xml" in archive.namelist():
                shared = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                shared_strings = [
                    "".join(node.text or "" for node in item.findall(f".//{{{namespace}}}t"))
                    for item in shared.findall(f"{{{namespace}}}si")
                ]
            sheet_xml = ET.fromstring(archive.read(sheet_path))
    except (KeyError, ET.ParseError, zipfile.BadZipFile) as exc:
        raise StatisticsLabError("invalid XLSX source") from exc

    rows: list[list[Any]] = []
    for row in sheet_xml.findall(f".//{{{namespace}}}row"):
        values: dict[int, Any] = {}
        for cell in row.findall(f"{{{namespace}}}c"):
            reference = str(cell.attrib.get("r", "A1"))
            letters = "".join(ch for ch in reference if ch.isalpha())
            column = 0
            for letter in letters.upper():
                column = column * 26 + ord(letter) - 64
            column -= 1
            cell_type = cell.attrib.get("t")
            value_node = cell.find(f"{{{namespace}}}v")
            if cell_type == "inlineStr":
                value: Any = "".join(
                    node.text or "" for node in cell.findall(f".//{{{namespace}}}t")
                )
            elif value_node is None or value_node.text is None:
                value = None
            elif cell_type == "s":
                try:
                    value = shared_strings[int(value_node.text)]
                except (IndexError, ValueError) as exc:
                    raise StatisticsLabError("invalid XLSX shared string") from exc
            elif cell_type in {"str", "b"}:
                value = value_node.text
            else:
                try:
                    numeric = float(value_node.text)
                    value = int(numeric) if numeric.is_integer() else numeric
                except ValueError:
                    value = value_node.text
            values[column] = value
        if values:
            rows.append([values.get(index) for index in range(max(values) + 1)])
    if not rows:
        raise StatisticsLabError(f"XLSX worksheet empty: {sheet_name}")
    return rows


def _parse_sec_ipo_xlsx(raw: bytes) -> list[dict[str, Any]]:
    rows = _xlsx_sheet_rows(raw, "Stats Table")
    result: list[dict[str, Any]] = []
    for row in rows[1:]:
        period = str(row[0]) if row else ""
        if ":Q" not in period or len(row) < 13:
            continue
        try:
            year_text, quarter_text = period.split(":Q", 1)
            quarter = int(quarter_text)
            observed = date(int(year_text), quarter * 3, 1)
            fields = [float(row[index]) for index in range(1, 13)]
        except (TypeError, ValueError) as exc:
            raise StatisticsLabError("invalid SEC IPO quarterly row") from exc
        result.append({
            "date": observed.isoformat(),
            "period_label": period,
            "total_count": int(fields[0]),
            "us_count": int(fields[1]),
            "non_us_count": int(fields[2]),
            "corporate_count": int(fields[3]),
            "spac_count": int(fields[4]),
            "fund_count": int(fields[5]),
            "total_proceeds_mn": fields[6],
            "corporate_proceeds_mn": fields[9],
            "spac_proceeds_mn": fields[10],
            "fund_proceeds_mn": fields[11],
        })
    if not result:
        raise StatisticsLabError("SEC IPO quarterly statistics are empty")
    return result


def _parse_nyu_returns_xlsx(raw: bytes) -> list[dict[str, Any]]:
    rows = _xlsx_sheet_rows(raw, "Returns by year")
    result: list[dict[str, Any]] = []
    for row in rows:
        if len(row) < 2 or not isinstance(row[0], (int, float)):
            continue
        year = int(row[0])
        if not 1928 <= year <= date.today().year or not isinstance(row[1], (int, float)):
            continue
        value = float(row[1]) * 100.0
        if math.isfinite(value):
            result.append({"date": f"{year}-12-31", "value": value})
    if len(result) < 50:
        raise StatisticsLabError("NYU annual S&P 500 return history is incomplete")
    return result


def _parse_ici_weekly_html(raw: bytes) -> list[dict[str, Any]]:
    text = raw.decode("utf-8", errors="replace")
    # The public release exposes a stable accessible table. Parse only the
    # header dates and Equity/Domestic/World rows; no proprietary chart pixels.
    import re

    table_match = re.search(
        r"ETF Estimated Net Issuance.*?<table[^>]*>(.*?)</table>", text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if table_match is None:
        raise StatisticsLabError("ICI ETF issuance table missing")
    table = table_match.group(1)
    row_html = re.findall(r"<tr[^>]*>(.*?)</tr>", table, flags=re.IGNORECASE | re.DOTALL)
    parsed_rows: list[list[str]] = []
    for html in row_html:
        cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", html, flags=re.IGNORECASE | re.DOTALL)
        parsed_rows.append([
            re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", cell)).strip()
            for cell in cells
        ])
    header = next((
        row for row in parsed_rows
        if row and sum(bool(re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", cell)) for cell in row) >= 3
    ), None)
    equity = next((row for row in parsed_rows if row and row[0].strip() == "Equity"), None)
    domestic = next((row for row in parsed_rows if row and row[0].strip() == "Domestic"), None)
    world = next((row for row in parsed_rows if row and row[0].strip() == "World"), None)
    if not header or not equity or not domestic or not world:
        raise StatisticsLabError("ICI ETF issuance rows missing")

    def number(value: str) -> float:
        cleaned = value.replace(",", "").replace("−", "-").strip()
        return float(cleaned)

    result = []
    for index, label in enumerate(header[1:], start=1):
        try:
            observed = datetime.strptime(label, "%m/%d/%Y").date()
            result.append({
                "date": observed.isoformat(),
                "value": number(equity[index]),
                "domestic": number(domestic[index]),
                "world": number(world[index]),
            })
        except (IndexError, ValueError) as exc:
            raise StatisticsLabError("invalid ICI ETF issuance value") from exc
    result.sort(key=lambda row: row["date"])
    return result


def _fetch_supplemental(series_id: str) -> tuple[list[dict[str, Any]], bytes]:
    if series_id == "SEC_IPO_QUARTERLY":
        import re

        page = _request(SEC_IPO_ENDPOINT, timeout=60).decode("utf-8", errors="replace")
        match = re.search(r'href="([^"]*sec-stats-ipos-\d+\.xlsx)"', page)
        if match is None:
            raise StatisticsLabError("SEC IPO statistics download link missing")
        download_url = urllib.parse.urljoin(SEC_IPO_ENDPOINT, match.group(1))
        raw = _request(download_url, timeout=60)
        return _parse_sec_ipo_xlsx(raw), raw
    if series_id == "ICI_WEEKLY_EQUITY_ETF_FLOW":
        raise StatisticsLabError(
            "ICI blocks unattended access in this runtime; use the reviewed local reference"
        )
    if series_id == "NYU_SP500_ANNUAL_TOTAL_RETURN":
        raw = _request(NYU_RETURNS_ENDPOINT, timeout=60)
        return _parse_nyu_returns_xlsx(raw), raw
    raise StatisticsLabError(f"unknown supplemental statistics source: {series_id}")


def _parse_fred_csv(raw: bytes, series_id: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    rows: list[dict[str, Any]] = []
    for row in reader:
        value = row.get(series_id)
        if value in (None, "", "."):
            continue
        try:
            parsed = float(value)
            observed = date.fromisoformat(str(row["observation_date"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise StatisticsLabError(f"invalid FRED row for {series_id}") from exc
        if math.isfinite(parsed):
            rows.append({"date": observed.isoformat(), "value": parsed})
    if not rows:
        raise StatisticsLabError(f"FRED series {series_id} is empty")
    return rows


def _fetch_fred(series_id: str) -> tuple[list[dict[str, Any]], bytes]:
    start = FRED_SERIES.get(series_id, {}).get("window_start", "1995-01-01")
    url = f"{FRED_ENDPOINT}?id={series_id}&cosd={start}"
    # GitHub-hosted runners intermittently leave Python's TLS read waiting on
    # FRED.  Reuse the repository's audited same-URL curl/public-DNS transport
    # fallback.  Decoding and re-encoding UTF-8 is byte-preserving for FRED CSV
    # and the exact bytes are still hashed in the source receipt.
    raw = feed.get_with_curl_fallback(url, timeout=45).encode("utf-8")
    return _parse_fred_csv(raw, series_id), raw


def _fetch_daily_market(
    series_id: str, start: date, end_exclusive: date,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch an explicitly bounded daily close series with a raw-response receipt."""
    try:
        spec = DAILY_MARKET_SERIES[series_id]
    except KeyError as exc:
        raise StatisticsLabError(f"unknown daily market series: {series_id}") from exc
    result = feed.yahoo_price_series_detail(
        spec["symbol"], start, end_exclusive, interval="1d",
    )
    rows = [
        {"date": observed.isoformat(), "value": float(value)}
        for observed, value in zip(result.dates, result.closes, strict=True)
        if start <= observed < end_exclusive
    ]
    if not rows:
        raise StatisticsLabError(f"daily market series {series_id} is empty")
    return rows, {
        "raw_sha256": result.receipt["response_sha256"],
        "request_url": result.receipt["request_url"],
        "data_quality": result.data_quality,
    }


def _parse_z1(raw: bytes) -> list[dict[str, Any]]:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        try:
            text = archive.read("csv/F4_6_s.csv").decode("utf-8-sig")
        except KeyError as exc:
            raise StatisticsLabError("Z.1 F4_6_s.csv missing") from exc
    reader = csv.DictReader(io.StringIO(text))
    field = "FL663067003.Q"
    rows = []
    for row in reader:
        value = row.get(field)
        period = row.get("date", "")
        if not value or not period or ":Q" not in period:
            continue
        try:
            year_text, quarter_text = period.split(":Q", 1)
            month = (int(quarter_text) - 1) * 3 + 1
            parsed = float(value)
            observed = date(int(year_text), month, 1)
        except (TypeError, ValueError) as exc:
            raise StatisticsLabError("invalid Z.1 margin-credit row") from exc
        if observed >= date(1995, 1, 1) and math.isfinite(parsed):
            rows.append({"date": observed.isoformat(), "value": parsed})
    if not rows:
        raise StatisticsLabError("Z.1 FL663067003.Q is empty")
    return rows


def _month_key(value: str) -> tuple[int, int]:
    observed = date.fromisoformat(value)
    return observed.year, observed.month


def _month_offset(value: str, start: date) -> int:
    observed = date.fromisoformat(value)
    return (observed.year - start.year) * 12 + observed.month - start.month


def _monthly(rows: list[dict[str, Any]], aggregation: str) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[_month_key(row["date"])].append(row)
    result = []
    for (year, month), values in sorted(grouped.items()):
        values.sort(key=lambda item: item["date"])
        number = (
            sum(float(item["value"]) for item in values) / len(values)
            if aggregation == "mean"
            else float(values[-1]["value"])
        )
        result.append({"date": date(year, month, 1).isoformat(), "value": number})
    return result


def _calendar_year_index(
    rows: list[dict[str, Any]], year: int,
) -> list[dict[str, Any]]:
    """Normalize actual daily closes to first observed close=100 on a day-of-year axis."""
    selected = [
        row for row in sorted(rows, key=lambda item: item["date"])
        if date.fromisoformat(str(row["date"])).year == year
    ]
    if not selected:
        raise StatisticsLabError(f"daily market path for {year} is empty")
    base = float(selected[0]["value"])
    if not math.isfinite(base) or base <= 0:
        raise StatisticsLabError(f"daily market path for {year} has invalid base")
    start = date(year, 1, 1)
    result = []
    for row in selected:
        observed = date.fromisoformat(str(row["date"]))
        value = float(row["value"])
        if not math.isfinite(value) or value <= 0:
            raise StatisticsLabError(f"daily market path for {year} has invalid close")
        result.append({
            "period": (observed - start).days,
            "date": observed.isoformat(),
            "value": value / base * 100.0,
        })
    return result


def _positive_daily_rows(rows: list[dict[str, Any]]) -> list[tuple[date, float]]:
    result: list[tuple[date, float]] = []
    for row in sorted(rows, key=lambda item: item["date"]):
        observed = date.fromisoformat(str(row["date"]))
        value = float(row["value"])
        if not math.isfinite(value) or value <= 0:
            raise StatisticsLabError("daily market comparison cannot use non-positive closes")
        result.append((observed, value))
    if len(result) < 3:
        raise StatisticsLabError("daily market comparison needs at least three observations")
    return result


def _correlation(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or len(left) < 3:
        raise StatisticsLabError("daily market correlation sample invalid")
    if statistics.stdev(left) <= 0 or statistics.stdev(right) <= 0:
        raise StatisticsLabError("daily market correlation variance invalid")
    return float(statistics.correlation(left, right))


def _rolling_sums(values: list[float], sessions: int) -> list[float]:
    if sessions < 2 or len(values) < sessions:
        raise StatisticsLabError("rolling market window invalid")
    return [sum(values[index - sessions + 1:index + 1]) for index in range(sessions - 1, len(values))]


def _aligned_log_returns(
    base_rows: list[dict[str, Any]], candidate_rows: list[dict[str, Any]], *,
    candidate_close: str,
) -> list[dict[str, Any]]:
    """Align candidate returns without moving or optimizing dates.

    ``same_or_prior`` is used for markets whose close is already observable by
    the KOSPI close. ``strictly_prior`` is used for the U.S. session so a KOSPI
    return on day D only sees the U.S. close dated before D.
    """
    base = _positive_daily_rows(base_rows)
    candidate = _positive_daily_rows(candidate_rows)
    candidate_dates = [row[0] for row in candidate]
    candidate_values = [row[1] for row in candidate]
    aligned: list[dict[str, Any]] = []
    for (base_date_0, base_value_0), (base_date_1, base_value_1) in zip(
        base, base[1:], strict=False,
    ):
        if candidate_close == "strictly_prior":
            candidate_index_0 = bisect_left(candidate_dates, base_date_0) - 1
            candidate_index_1 = bisect_left(candidate_dates, base_date_1) - 1
        elif candidate_close == "same_or_prior":
            candidate_index_0 = bisect_right(candidate_dates, base_date_0) - 1
            candidate_index_1 = bisect_right(candidate_dates, base_date_1) - 1
        else:
            raise StatisticsLabError("daily market close policy invalid")
        if candidate_index_0 < 0 or candidate_index_1 <= candidate_index_0:
            continue
        aligned.append({
            "date": base_date_1.isoformat(),
            "base_return": math.log(base_value_1 / base_value_0),
            "candidate_return": math.log(
                candidate_values[candidate_index_1] / candidate_values[candidate_index_0]
            ),
        })
    if len(aligned) < 20:
        raise StatisticsLabError("daily market aligned sample too small")
    return aligned


def _aligned_return_diagnostic(
    aligned: list[dict[str, Any]], *, sessions: int = 20,
) -> dict[str, Any]:
    base_returns = [float(row["base_return"]) for row in aligned]
    candidate_returns = [float(row["candidate_return"]) for row in aligned]
    direction_matches = sum(
        (left >= 0) == (right >= 0)
        for left, right in zip(base_returns, candidate_returns, strict=True)
    )
    return {
        "sample_start": aligned[0]["date"],
        "sample_end": aligned[-1]["date"],
        "observations": len(aligned),
        "daily_log_return_correlation": round(_correlation(base_returns, candidate_returns), 4),
        "rolling_20_session_correlation": round(_correlation(
            _rolling_sums(base_returns, sessions),
            _rolling_sums(candidate_returns, sessions),
        ), 4),
        "direction_agreement": round(direction_matches / len(aligned), 4),
    }


def _sox_quintile_diagnostic(aligned: list[dict[str, Any]]) -> dict[str, Any]:
    training = [row for row in aligned if str(row["date"]) < "2026-01-01"]
    if len(training) < 100:
        raise StatisticsLabError("SOX conditional training sample too small")
    sorted_candidate = sorted(float(row["candidate_return"]) for row in training)
    cuts = [sorted_candidate[int(len(sorted_candidate) * rank / 5)] for rank in range(1, 5)]

    def bucket(value: float) -> int:
        return sum(value > cut for cut in cuts)

    def summarize(rows: list[dict[str, Any]], bucket_index: int) -> dict[str, Any]:
        values = [
            float(row["base_return"]) for row in rows
            if bucket(float(row["candidate_return"])) == bucket_index
        ]
        if not values:
            raise StatisticsLabError("SOX conditional bucket empty")
        return {
            "observations": len(values),
            "mean_next_kospi_log_return_pct": round(statistics.mean(values) * 100.0, 3),
            "positive_share": round(sum(value > 0 for value in values) / len(values), 4),
        }

    current = [row for row in aligned if str(row["date"]) >= "2026-01-01"]
    return {
        "training_window": f"{training[0]['date']}_to_{training[-1]['date']}",
        "quintile_cut_log_return_pct": [round(value * 100.0, 3) for value in cuts],
        "training_lowest_quintile": summarize(training, 0),
        "training_highest_quintile": summarize(training, 4),
        "current_highest_quintile": summarize(current, 4),
        "interpretation": "descriptive_conditional_frequency_not_probability_or_causation",
    }


def _session_log_return_points(
    rows: list[dict[str, Any]], *, year: int, sessions: int = 20,
) -> list[dict[str, Any]]:
    selected = _positive_daily_rows(rows)
    start = date(year, 1, 1)
    result = []
    for index in range(sessions, len(selected)):
        observed, value = selected[index]
        if observed.year != year:
            continue
        prior_value = selected[index - sessions][1]
        result.append({
            "period": (observed - start).days,
            "date": observed.isoformat(),
            "value": math.log(value / prior_value) * 100.0,
        })
    if not result:
        raise StatisticsLabError("daily market rolling return path empty")
    return result


def _prior_close_log_return_points(
    base_rows: list[dict[str, Any]], candidate_rows: list[dict[str, Any]], *,
    year: int, sessions: int = 20,
) -> list[dict[str, Any]]:
    base = _positive_daily_rows(base_rows)
    candidate = _positive_daily_rows(candidate_rows)
    candidate_dates = [row[0] for row in candidate]
    candidate_values = [row[1] for row in candidate]
    mapped: list[tuple[date, float]] = []
    for observed, _value in base:
        candidate_index = bisect_left(candidate_dates, observed) - 1
        if candidate_index >= 0:
            mapped.append((observed, candidate_values[candidate_index]))
    start = date(year, 1, 1)
    result = []
    for index in range(sessions, len(mapped)):
        observed, value = mapped[index]
        if observed.year != year:
            continue
        result.append({
            "period": (observed - start).days,
            "date": observed.isoformat(),
            "value": math.log(value / mapped[index - sessions][1]) * 100.0,
        })
    if not result:
        raise StatisticsLabError("prior-close rolling return path empty")
    return result


def _indexed(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not points or float(points[0]["value"]) == 0:
        return []
    base = float(points[0]["value"])
    return [{**row, "value": float(row["value"]) / base * 100.0} for row in points]


def _yoy(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {_month_key(row["date"]): float(row["value"]) for row in points}
    result = []
    for row in points:
        observed = date.fromisoformat(row["date"])
        prior = by_key.get((observed.year - 1, observed.month))
        if prior not in (None, 0):
            result.append({**row, "value": (float(row["value"]) / prior - 1.0) * 100.0})
    return result


def _window(points: list[dict[str, Any]], start: date, months: int) -> list[dict[str, Any]]:
    selected = []
    for row in points:
        offset = _month_offset(row["date"], start)
        if 0 <= offset <= months:
            selected.append({"period": offset, "date": row["date"], "value": float(row["value"])})
    return selected


def _cycle_series(
    points: list[dict[str, Any]], months: int, *, indexed: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    dotcom = _window(points, DOTCOM_START, months)
    current = _window(points, CURRENT_START, months)
    if indexed:
        dotcom = [{"period": row["period"], **value} for row, value in zip(dotcom, _indexed(dotcom))]
        current = [{"period": row["period"], **value} for row, value in zip(current, _indexed(current))]
    return dotcom, current


def _ratio(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> list[dict[str, Any]]:
    right_by_month = {_month_key(row["date"]): float(row["value"]) for row in right}
    result = []
    for row in left:
        divisor = right_by_month.get(_month_key(row["date"]))
        if divisor not in (None, 0):
            result.append({"date": row["date"], "value": float(row["value"]) / divisor})
    return result


def _shift_months(points: list[dict[str, Any]], months: int) -> list[dict[str, Any]]:
    shifted = []
    for row in points:
        observed = date.fromisoformat(row["date"])
        absolute = observed.year * 12 + observed.month - 1 + months
        shifted.append({
            **row,
            "date": date(absolute // 12, absolute % 12 + 1, 1).isoformat(),
        })
    return shifted


def _annual_last(points: list[dict[str, Any]]) -> dict[int, float]:
    result: dict[int, tuple[str, float]] = {}
    for row in points:
        observed = date.fromisoformat(row["date"])
        if observed.year not in result or row["date"] > result[observed.year][0]:
            result[observed.year] = (row["date"], float(row["value"]))
    return {year: value for year, (_, value) in result.items()}


def _monthly_log_returns(points: list[dict[str, Any]]) -> dict[tuple[int, int], float]:
    """Return month-keyed log changes without filling or extrapolating gaps."""
    result: dict[tuple[int, int], float] = {}
    previous: dict[str, Any] | None = None
    for row in sorted(points, key=lambda item: item["date"]):
        value = float(row["value"])
        if value <= 0:
            previous = None
            continue
        if previous is not None:
            prior_value = float(previous["value"])
            prior_date = date.fromisoformat(str(previous["date"]))
            observed = date.fromisoformat(str(row["date"]))
            expected = prior_date.year * 12 + prior_date.month
            actual = observed.year * 12 + observed.month - 1
            if prior_value > 0 and actual == expected:
                result[(observed.year, observed.month)] = math.log(value / prior_value)
        previous = row
    return result


def _annual_index_points(
    points: list[dict[str, Any]], *, start_year: int, end_year: int,
) -> list[dict[str, Any]]:
    annual = _annual_last(points)
    base = annual.get(start_year)
    if base is None or base <= 0:
        raise StatisticsLabError("annual index base is unavailable")
    return [
        {
            "period": year - start_year,
            "date": f"{year}-12-31",
            "value": annual[year] / base * 100.0,
        }
        for year in range(start_year, end_year + 1)
        if year in annual
    ]


def _normalized_monthly_pair(
    left: list[dict[str, Any]], right: list[dict[str, Any]], *, start: date,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    left_by_month = {_month_key(row["date"]): float(row["value"]) for row in left}
    right_by_month = {_month_key(row["date"]): float(row["value"]) for row in right}
    months = sorted(
        key for key in set(left_by_month) & set(right_by_month)
        if key >= (start.year, start.month)
    )
    if len(months) < 3:
        raise StatisticsLabError("normalized monthly comparison is incomplete")
    left_base, right_base = left_by_month[months[0]], right_by_month[months[0]]
    left_points, right_points = [], []
    for year, month in months:
        observed = date(year, month, 1)
        period = _month_offset(observed.isoformat(), start)
        left_points.append({
            "period": period, "date": observed.isoformat(),
            "value": left_by_month[(year, month)] / left_base * 100.0,
        })
        right_points.append({
            "period": period, "date": observed.isoformat(),
            "value": right_by_month[(year, month)] / right_base * 100.0,
        })
    return left_points, right_points


def _trend_gap_points(
    points: list[dict[str, Any]], *, start: date = date(2009, 1, 1),
    trend_end: date = date(2019, 12, 31), minimum_training: int = 20,
) -> list[dict[str, Any]]:
    selected = [
        row for row in sorted(points, key=lambda item: item["date"])
        if date.fromisoformat(str(row["date"])) >= start
    ]
    training = [
        row for row in selected
        if date.fromisoformat(str(row["date"])) <= trend_end
    ]
    if len(training) < minimum_training:
        raise StatisticsLabError("household trend baseline is incomplete")

    def quarter_index(value: str) -> int:
        observed = date.fromisoformat(value)
        return (observed.year - start.year) * 4 + (observed.month - 1) // 3

    x = [float(quarter_index(str(row["date"]))) for row in training]
    y = [float(row["value"]) for row in training]
    slope, intercept = statistics.linear_regression(x, y)
    result = []
    for row in selected:
        period = quarter_index(str(row["date"]))
        trend = intercept + slope * period
        if trend <= 0:
            raise StatisticsLabError("household trend baseline became non-positive")
        result.append({
            "period": period,
            "date": str(row["date"]),
            "value": (float(row["value"]) / trend - 1.0) * 100.0,
        })
    return result


def _two_consecutive_twenty_percent_events(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[list[Any]]]:
    annual = {int(str(row["date"])[:4]): float(row["value"]) for row in rows}
    starts = [
        year for year in sorted(annual)
        if year >= 1950
        and annual.get(year, -math.inf) >= 20.0
        and annual.get(year + 1, -math.inf) >= 20.0
        and year + 2 in annual
    ]
    if len(starts) < 5:
        raise StatisticsLabError("consecutive 20-percent annual return sample too small")

    def points(offset: int) -> list[dict[str, Any]]:
        return [
            {
                "period": index,
                "date": f"{year + offset}-12-31",
                "value": annual[year + offset],
            }
            for index, year in enumerate(starts)
        ]

    ticks = [[index, f"{year}–{year + 1}"] for index, year in enumerate(starts)]
    return points(0), points(1), points(2), ticks


def _quarterly_followthrough_events(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[list[Any]], dict[str, Any]]:
    closes: dict[tuple[int, int], tuple[date, float]] = {}
    for observed, value in _positive_daily_rows(rows):
        key = (observed.year, (observed.month - 1) // 3 + 1)
        if key not in closes or observed > closes[key][0]:
            closes[key] = (observed, value)
    keys = sorted(closes)
    returns: list[tuple[tuple[int, int], float]] = []
    for previous, current in zip(keys, keys[1:], strict=False):
        expected = (previous[0] + (1 if previous[1] == 4 else 0), previous[1] % 4 + 1)
        if current != expected:
            continue
        returns.append((current, (closes[current][1] / closes[previous][1] - 1.0) * 100.0))
    by_key = dict(returns)
    events: list[tuple[tuple[int, int], float, float]] = []
    for index in range(1, len(returns) - 2):
        key, current_return = returns[index]
        previous_return = returns[index - 1][1]
        next_key, next_return = returns[index + 1]
        second_key, _ = returns[index + 2]
        if previous_return < 0.0 and current_return > 10.0:
            first_close = closes[key][1]
            second_close = closes[second_key][1]
            events.append((key, next_return, (second_close / first_close - 1.0) * 100.0))
    if len(events) < 5:
        raise StatisticsLabError("quarterly follow-through event sample too small")
    next_points = [
        {"period": index, "date": f"{year}-{quarter * 3:02d}-01", "value": next_return}
        for index, ((year, quarter), next_return, _) in enumerate(events)
    ]
    two_points = [
        {"period": index, "date": f"{year}-{quarter * 3:02d}-01", "value": two_return}
        for index, ((year, quarter), _, two_return) in enumerate(events)
    ]
    ticks = [
        [index, f"{year}Q{quarter}"] for index, ((year, quarter), _, _) in enumerate(events)
        if index in {0, len(events) // 3, 2 * len(events) // 3, len(events) - 1}
    ]
    diagnostics = {
        "event_count": len(events),
        "next_quarter_average": statistics.mean(row[1] for row in events),
        "next_quarter_positive": sum(row[1] > 0 for row in events),
        "two_quarter_average": statistics.mean(row[2] for row in events),
        "two_quarter_positive": sum(row[2] > 0 for row in events),
        "return_type": "price_return_excluding_dividends",
        "event_rule": "previous_calendar_quarter_below_0_and_current_above_10_percent",
    }
    return next_points, two_points, ticks, diagnostics


def _lead_correlation(
    leader: list[dict[str, Any]], follower: list[dict[str, Any]], lead_months: int,
) -> dict[str, Any]:
    """Correlate leader return at t with follower return at t+lead_months."""
    if lead_months < 0:
        raise StatisticsLabError("lead months cannot be negative")
    left = _monthly_log_returns(leader)
    right = _monthly_log_returns(follower)
    pairs: list[tuple[float, float]] = []
    for (year, month), value in left.items():
        absolute = year * 12 + month - 1 + lead_months
        peer = right.get((absolute // 12, absolute % 12 + 1))
        if peer is not None:
            pairs.append((value, peer))
    correlation = statistics.correlation(
        [row[0] for row in pairs], [row[1] for row in pairs]
    ) if len(pairs) >= 3 else None
    return {
        "lead_months": lead_months,
        "observations": len(pairs),
        "correlation": round(float(correlation), 4) if correlation is not None else None,
    }


def _event_change(
    points: list[dict[str, Any]], *, base_month: date, event_month: date, months: int,
) -> list[dict[str, Any]]:
    by_month = {_month_key(row["date"]): float(row["value"]) for row in points}
    base = by_month.get((base_month.year, base_month.month))
    if base is None:
        return []
    result = []
    for row in points:
        offset = _month_offset(row["date"], event_month)
        if 0 <= offset <= months:
            result.append({"period": offset, "date": row["date"], "value": float(row["value"]) - base})
    return result


def _chart(
    chart_id: str, title: str, category: str, unit: str, description: str,
    caveat: str, series: list[dict[str, Any]], source_ids: list[str],
) -> dict[str, Any]:
    values = [float(point["value"]) for row in series for point in row["points"]]
    if not values:
        raise StatisticsLabError(f"chart {chart_id} has no values")
    return {
        "id": chart_id,
        "title": title,
        "category": category,
        "unit": unit,
        "description": description,
        "caveat": caveat,
        "series": series,
        "source_ids": source_ids,
        "range": {"minimum": min(values), "maximum": max(values)},
    }


def _series(label: str, era: str, points: list[dict[str, Any]], color: str) -> dict[str, Any]:
    return {"label": label, "era": era, "color": color, "points": points}


def validate_ipo_reference(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != 1 or payload.get("status") != "active_reference_only":
        raise StatisticsLabError("IPO reference schema/status invalid")
    if payload.get("probability_space") != "reference_only":
        raise StatisticsLabError("IPO reference must be reference_only")
    if payload.get("model_use") is not False or payload.get("official_forecast_input") is not False:
        raise StatisticsLabError("IPO reference cannot feed model or official forecast")
    coverage = payload.get("coverage") or {}
    if coverage.get("current_line_policy") != "actual_observations_only_no_forecast_extension":
        raise StatisticsLabError("IPO reference cannot contain forecast extension")
    charts = payload.get("charts")
    sources = payload.get("sources")
    if not isinstance(charts, list) or len(charts) < 4:
        raise StatisticsLabError("IPO reference requires at least four charts")
    if not isinstance(sources, list) or len(sources) < 2:
        raise StatisticsLabError("IPO reference source registry incomplete")
    source_ids = {str(row.get("series_id")) for row in sources}
    if len(source_ids) != len(sources):
        raise StatisticsLabError("IPO reference source ids must be unique")
    for source in sources:
        digest = str(source.get("raw_sha256", ""))
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise StatisticsLabError(f"IPO source {source.get('series_id')} hash invalid")
    broad_cohort = payload.get("ai_broad_cohort")
    expected_years = [int(year) for year in coverage.get("current_years") or []]
    if not isinstance(broad_cohort, list) or [row.get("year") for row in broad_cohort] != expected_years:
        raise StatisticsLabError("IPO broad cohort years must match current coverage")
    broad_counts: dict[int, int] = {}
    core_member_counts: dict[int, int] = {}
    broad_tickers: set[str] = set()
    for year_row in broad_cohort:
        year = int(year_row["year"])
        issuers = year_row.get("issuers")
        if not isinstance(issuers, list) or not issuers:
            raise StatisticsLabError(f"IPO broad cohort {year} issuers missing")
        broad_counts[year] = len(issuers)
        core_member_counts[year] = 0
        for issuer in issuers:
            ticker = str(issuer.get("ticker", "")).strip()
            tier = issuer.get("dependency_tier")
            evidence_source_id = str(issuer.get("evidence_source_id", ""))
            core_member = issuer.get("core_member")
            if not ticker or ticker in broad_tickers:
                raise StatisticsLabError("IPO broad cohort tickers must be non-empty and unique")
            if not isinstance(tier, int) or not 2 <= tier <= 5:
                raise StatisticsLabError(f"IPO broad cohort {ticker} dependency tier invalid")
            if evidence_source_id not in source_ids:
                raise StatisticsLabError(f"IPO broad cohort {ticker} evidence source unknown")
            if not isinstance(core_member, bool):
                raise StatisticsLabError(f"IPO broad cohort {ticker} core membership must be explicit")
            if core_member:
                core_member_counts[year] += 1
            broad_tickers.add(ticker)
    qualitative = payload.get("qualitative_ipo") or {}
    ipo_sensitivity = qualitative.get("reported_frontier_ai_ipo_sensitivity") or {}
    if ipo_sensitivity.get("semantics") != (
        "headline_ipo_valuation_sensitivity_not_a_completed_offering_or_base_case"
    ):
        raise StatisticsLabError("frontier AI IPO sensitivity semantics invalid")
    sensitivity_members = ipo_sensitivity.get("members") or []
    if not sensitivity_members or any(
        str(row.get("source_id", "")) not in source_ids
        or float(row.get("headline_ipo_valuation_bn", 0)) <= 0
        for row in sensitivity_members
    ):
        raise StatisticsLabError("frontier AI IPO sensitivity evidence invalid")
    sensitivity_total = sum(float(row["headline_ipo_valuation_bn"]) for row in sensitivity_members)
    for row in ipo_sensitivity.get("float_sensitivity") or []:
        expected = sensitivity_total * float(row["float_percent"]) / 100.0
        if not math.isclose(float(row["gross_offering_value_bn"]), expected, abs_tol=1e-9):
            raise StatisticsLabError("frontier AI IPO float sensitivity does not reconcile")
    listed_watch = qualitative.get("listed_ai_beneficiary_watchlist") or {}
    if listed_watch.get("semantics") != (
        "ai_beneficiary_with_new_nasdaq_ads_offering_included_only_in_influence_inclusive_listing_event_count_because_adrs_are_outside_ritter_traditional_ipo_definition"
    ):
        raise StatisticsLabError("listed AI beneficiary watchlist semantics invalid")
    listed_members = listed_watch.get("members") or []
    if not listed_members:
        raise StatisticsLabError("listed AI beneficiary watchlist missing")
    global_chip_watch = qualitative.get("global_ai_chip_completed_ipos") or {}
    if global_chip_watch.get("semantics") != (
        "completed_china_and_hong_kong_ai_chip_ipo_watchlist_kept_separate_from_us_ritter_counts"
    ):
        raise StatisticsLabError("global AI chip IPO watchlist semantics invalid")
    global_chip_members = global_chip_watch.get("members") or []
    if not global_chip_members:
        raise StatisticsLabError("global AI chip IPO watchlist missing")
    nasdaq_memory_watch = qualitative.get("nasdaq_memory_market_events") or {}
    if nasdaq_memory_watch.get("semantics") != (
        "verified_nasdaq_memory_semiconductor_listing_events_not_a_same_definition_time_series"
    ):
        raise StatisticsLabError("Nasdaq memory market-event semantics invalid")
    nasdaq_memory_members = nasdaq_memory_watch.get("members") or []
    if not nasdaq_memory_members:
        raise StatisticsLabError("Nasdaq memory market-event watchlist missing")
    watch_members = [*listed_members, *global_chip_members, *nasdaq_memory_members]
    watch_source_ids = {str(member.get("source_id", "")) for member in watch_members}
    classification_source_id = str(global_chip_watch.get("classification_source_id", ""))
    if not watch_source_ids.issubset(source_ids) or classification_source_id not in source_ids:
        raise StatisticsLabError("AI capital watchlist source unknown")
    if any(not member.get("name") or not member.get("role") for member in watch_members):
        raise StatisticsLabError("AI capital watchlist member identity/role missing")
    if any(not member.get("listing_date") for member in [*global_chip_members, *nasdaq_memory_members]):
        raise StatisticsLabError("global AI chip or Nasdaq memory listing date missing")
    chart_ids: set[str] = set()
    for chart in charts:
        chart_id = str(chart.get("id", ""))
        if not chart_id or chart_id in chart_ids:
            raise StatisticsLabError("IPO chart ids must be non-empty and unique")
        chart_ids.add(chart_id)
        if not chart.get("insight") or not chart.get("caveat"):
            raise StatisticsLabError(f"IPO chart {chart_id} missing insight/caveat")
        if not set(chart.get("source_ids") or []).issubset(source_ids):
            raise StatisticsLabError(f"IPO chart {chart_id} has unknown source")
        for series in chart.get("series") or []:
            periods = [int(point["period"]) for point in series.get("points") or []]
            values = [float(point["value"]) for point in series.get("points") or []]
            if not periods or periods != sorted(set(periods)) or max(periods) > COMPARISON_MONTHS:
                raise StatisticsLabError(f"IPO chart {chart_id} periods invalid")
            if not all(math.isfinite(value) and value >= 0 for value in values if chart.get("unit") == "count"):
                raise StatisticsLabError(f"IPO chart {chart_id} count invalid")
    comparison = next((chart for chart in charts if chart.get("id") == "internet_vs_ai_core_ipos"), None)
    if comparison is None:
        raise StatisticsLabError("IPO broad/core comparison chart missing")
    broad_series = next(
        (series for series in comparison["series"] if series.get("label") == "현재 광의 AI 연관 IPO"), None
    )
    influence_series = next(
        (series for series in comparison["series"] if series.get("label") == "현재 AI IPO·NASDAQ ADS 영향 포함"), None
    )
    core_series = next(
        (series for series in comparison["series"] if series.get("label") == "현재 AI 핵심 최소치"), None
    )
    if broad_series is None or influence_series is None or core_series is None:
        raise StatisticsLabError("IPO broad/influence/core comparison series missing")
    broad_points = {int(point["date"][:4]): int(point["value"]) for point in broad_series["points"]}
    core_points = {int(point["date"][:4]): int(point["value"]) for point in core_series["points"]}
    influence_points = {
        int(point["date"][:4]): int(point["value"]) for point in influence_series["points"]
    }
    influence_contract = qualitative.get("influence_inclusive_count") or {}
    if influence_contract.get("semantics") != (
        "actual_us_ai_related_traditional_ipos_plus_explicit_nasdaq_ads_listing_events_outside_ritter_definition"
    ):
        raise StatisticsLabError("AI influence-inclusive count semantics invalid")
    expected_influence = dict(broad_counts)
    for member in listed_members:
        period = int(member.get("count_period", 0))
        if period not in expected_influence:
            raise StatisticsLabError("listed AI beneficiary count period invalid")
        expected_influence[period] += 1
    if broad_points != broad_counts:
        raise StatisticsLabError("IPO broad series does not reconcile to reviewed issuer cohort")
    if core_points != core_member_counts:
        raise StatisticsLabError("IPO core minimum must reconcile to marked broad-cohort members")
    if influence_points != expected_influence:
        raise StatisticsLabError("AI influence-inclusive series does not reconcile")


def load_ipo_reference(root: Path) -> dict[str, Any]:
    path = root / IPO_REFERENCE_RELATIVE
    if not path.is_file():
        raise StatisticsLabError(f"IPO reference missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StatisticsLabError("IPO reference cannot be read") from exc
    validate_ipo_reference(payload)
    return payload


def load_hmi_reference(root: Path) -> dict[str, Any]:
    path = root / HMI_REFERENCE_RELATIVE
    if not path.is_file():
        raise StatisticsLabError(f"HMI reference missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StatisticsLabError("HMI reference cannot be read") from exc
    if (
        payload.get("schema_version") != 1
        or payload.get("probability_space") != "reference_only"
        or payload.get("model_use") is not False
        or payload.get("official_forecast_input") is not False
    ):
        raise StatisticsLabError("HMI reference semantic contract invalid")
    rows = payload.get("rows") or []
    if not rows or any(not row.get("date") or not math.isfinite(float(row.get("value"))) for row in rows):
        raise StatisticsLabError("HMI reference rows invalid")
    source = payload.get("source") or {}
    digest = str(source.get("raw_sha256", ""))
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise StatisticsLabError("HMI source hash invalid")
    return payload


def load_ici_reference(root: Path) -> dict[str, Any]:
    path = root / ICI_REFERENCE_RELATIVE
    if not path.is_file():
        raise StatisticsLabError(f"ICI ETF reference missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StatisticsLabError("ICI ETF reference cannot be read") from exc
    if (
        payload.get("schema_version") != 1
        or payload.get("probability_space") != "reference_only"
        or payload.get("model_use") is not False
        or payload.get("official_forecast_input") is not False
    ):
        raise StatisticsLabError("ICI ETF reference semantic contract invalid")
    rows = payload.get("rows") or []
    required = {"date", "value", "domestic", "world"}
    if len(rows) != 5 or any(
        not required.issubset(row)
        or not all(math.isfinite(float(row[key])) for key in required - {"date"})
        for row in rows
    ):
        raise StatisticsLabError("ICI ETF reference rows invalid")
    if [row["date"] for row in rows] != sorted({row["date"] for row in rows}):
        raise StatisticsLabError("ICI ETF reference dates invalid")
    source = payload.get("source") or {}
    digest = str(source.get("raw_sha256", ""))
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise StatisticsLabError("ICI ETF source hash invalid")
    return payload


def build_statistics_lab(
    source_rows: dict[str, list[dict[str, Any]]], *, generated_at: str,
    receipts: dict[str, dict[str, Any]],
    ipo_reference: dict[str, Any] | None = None,
    hmi_reference: dict[str, Any] | None = None,
) -> dict[str, Any]:
    required_sources = (
        set(FRED_SERIES) | set(DAILY_MARKET_SERIES) | set(SUPPLEMENTAL_SOURCES)
        | {"FL663067003"}
    )
    missing = sorted(required_sources - set(source_rows))
    if missing:
        raise StatisticsLabError(f"missing source series: {missing}")
    generated_date = datetime.fromisoformat(generated_at.replace("Z", "+00:00")).date()
    latest_kospi_date = max(
        date.fromisoformat(str(row["date"]))
        for row in source_rows["KOSPI_DAILY"]
    )
    if latest_kospi_date >= generated_date:
        raise StatisticsLabError(
            "KOSPI daily path must stop before collector date to exclude an incomplete session"
        )
    monthly = {
        key: _monthly(rows, FRED_SERIES[key]["aggregation"])
        for key, rows in source_rows.items() if key in FRED_SERIES
    }
    monthly["FL663067003"] = _monthly(source_rows["FL663067003"], "last")
    latest_current = max(date.fromisoformat(row["date"]) for row in monthly["NASDAQCOM"])
    comparison_months = COMPARISON_MONTHS

    dot_nasdaq, cur_nasdaq = _cycle_series(monthly["NASDAQCOM"], comparison_months, indexed=True)
    dot_m2, cur_m2 = _cycle_series(monthly["M2SL"], comparison_months, indexed=True)
    dot_liq, cur_liq = _cycle_series(
        _ratio(monthly["NASDAQCOM"], monthly["M2SL"]), comparison_months, indexed=True
    )
    dot_household_cash, cur_household_cash = _cycle_series(
        _ratio(monthly["NASDAQCOM"], monthly["DABSHNO"]), comparison_months, indexed=True
    )
    dot_curve, cur_curve = _cycle_series(monthly["T10Y2Y"], comparison_months)
    dot_funds, cur_funds = _cycle_series(monthly["FEDFUNDS"], comparison_months)

    valuation = _ratio(monthly["NCBEILQ027S"], monthly["CPATAX"])
    valuation = [{**row, "value": float(row["value"]) / 1000.0} for row in valuation]
    dot_value, cur_value = _cycle_series(valuation, comparison_months)
    dot_margin, cur_margin = _cycle_series(monthly["FL663067003"], comparison_months, indexed=True)
    credit_growth = _yoy(monthly["TOTALSL"])
    dot_credit, cur_credit = _cycle_series(credit_growth, comparison_months)
    dot_standards, cur_standards = _cycle_series(monthly["DRTSCILM"], comparison_months)
    profit_growth = _yoy(monthly["CPATAX"])
    dot_profit, cur_profit = _cycle_series(profit_growth, comparison_months)
    dot_debt_service, cur_debt_service = _cycle_series(
        monthly["BOGZ1FL010000346Q"], comparison_months
    )
    dot_unemployment, cur_unemployment = _cycle_series(monthly["UNRATE"], comparison_months)
    inflation = _yoy(monthly["CPIAUCSL"])
    dot_inflation, cur_inflation = _cycle_series(inflation, comparison_months)
    dot_financial_conditions, cur_financial_conditions = _cycle_series(
        monthly["NFCI"], comparison_months
    )

    dot_rate_cycle = _event_change(
        monthly["FEDFUNDS"], base_month=date(1995, 6, 1),
        event_month=date(1995, 7, 1), months=comparison_months,
    )
    cur_rate_cycle = _event_change(
        monthly["FEDFUNDS"], base_month=date(2024, 8, 1),
        event_month=date(2024, 9, 1), months=comparison_months,
    )
    corporate_spread = []
    treasury_by_month = {_month_key(row["date"]): float(row["value"]) for row in monthly["GS10"]}
    for row in monthly["HQMCB10YR"]:
        treasury = treasury_by_month.get(_month_key(row["date"]))
        if treasury is not None:
            corporate_spread.append({"date": row["date"], "value": float(row["value"]) - treasury})
    dot_corp_yield, cur_corp_yield = _cycle_series(monthly["HQMCB10YR"], comparison_months)
    dot_corp_spread, cur_corp_spread = _cycle_series(corporate_spread, comparison_months)

    inflation_lead_aligned = _shift_months(inflation, -2)
    oil_lead = _yoy(monthly["DCOILWTICO"])
    copper_lead = _yoy(monthly["WPU10260314"])
    dot_inflation_lead, cur_inflation_lead = _cycle_series(inflation_lead_aligned, comparison_months)
    dot_oil, cur_oil = _cycle_series(oil_lead, comparison_months)
    dot_copper, cur_copper = _cycle_series(copper_lead, comparison_months)

    dot_philly, cur_philly = _cycle_series(monthly["GACDFSA066MSFRBPHI"], comparison_months)
    kospi_2026 = _calendar_year_index(source_rows["KOSPI_DAILY"], 2026)
    kosdaq_2026 = _calendar_year_index(source_rows["KOSDAQ_DAILY"], 2026)
    semicon_2026 = _calendar_year_index(source_rows["KRX_SEMICON_PROXY_DAILY"], 2026)
    kospi_20d = _session_log_return_points(source_rows["KOSPI_DAILY"], year=2026)
    taiex_20d = _session_log_return_points(source_rows["TAIEX_DAILY"], year=2026)
    sox_prior_20d = _prior_close_log_return_points(
        source_rows["KOSPI_DAILY"], source_rows["SOX_DAILY"], year=2026,
    )
    kosdaq_aligned = _aligned_log_returns(
        source_rows["KOSPI_DAILY"], source_rows["KOSDAQ_DAILY"],
        candidate_close="same_or_prior",
    )
    semicon_aligned = _aligned_log_returns(
        source_rows["KOSPI_DAILY"], source_rows["KRX_SEMICON_PROXY_DAILY"],
        candidate_close="same_or_prior",
    )
    taiex_aligned = _aligned_log_returns(
        source_rows["KOSPI_DAILY"], source_rows["TAIEX_DAILY"],
        candidate_close="same_or_prior",
    )
    sox_aligned = _aligned_log_returns(
        source_rows["KOSPI_DAILY"], source_rows["SOX_DAILY"],
        candidate_close="strictly_prior",
    )
    market_breadth_diagnostics = {
        "measurement_window": "2020_to_last_completed_session",
        "kosdaq": _aligned_return_diagnostic(kosdaq_aligned),
        "semiconductor_proxy": _aligned_return_diagnostic(semicon_aligned),
        "normalization": "each_series_first_2026_close_equals_100",
        "time_warping": False,
        "optimized_lag": False,
        "forecast_extension": False,
    }
    external_pulse_diagnostics = {
        "measurement_window": "2020_to_last_completed_session",
        "taiex_same_or_prior_close": _aligned_return_diagnostic(taiex_aligned),
        "sox_strictly_prior_us_close": _aligned_return_diagnostic(sox_aligned),
        "sox_conditional_quintiles": _sox_quintile_diagnostic(sox_aligned),
        "display_window_sessions": 20,
        "time_warping": False,
        "optimized_lag": False,
        "forecast_extension": False,
    }
    dot_hmi: list[dict[str, Any]] = []
    cur_hmi: list[dict[str, Any]] = []
    if hmi_reference is not None:
        hmi_rows = [
            {"date": str(row["date"]), "value": float(row["value"]) - 50.0}
            for row in hmi_reference["rows"]
        ]
        dot_hmi, cur_hmi = _cycle_series(hmi_rows, comparison_months)

    tech_cycle = _annual_index_points(
        monthly["NASDAQCOM"], start_year=1985, end_year=latest_current.year,
    )
    gold_monthly = _monthly(source_rows["GOLD_DAILY"], "last")
    gold_index, m2_gold_index = _normalized_monthly_pair(
        gold_monthly, monthly["M2SL"], start=CURRENT_START,
    )
    equity_gap = _trend_gap_points(monthly["BOGZ1LM153064475Q"])
    cash_gap = _trend_gap_points(monthly["DABSHNO"])
    debt_gap = _trend_gap_points(
        monthly["BOGZ1FL154022375A"], minimum_training=8,
    )
    first_year, second_year, third_year, annual_event_ticks = (
        _two_consecutive_twenty_percent_events(
            source_rows["NYU_SP500_ANNUAL_TOTAL_RETURN"]
        )
    )
    quarter_next, quarter_two, quarter_ticks, quarter_diagnostics = (
        _quarterly_followthrough_events(source_rows["SP500_DAILY"])
    )

    sec_rows = source_rows["SEC_IPO_QUARTERLY"]
    sec_by_period = {str(row["period_label"]): row for row in sec_rows}

    def sec_half(year: int, field: str) -> float:
        try:
            return sum(float(sec_by_period[f"{year}:Q{quarter}"][field]) for quarter in (1, 2))
        except KeyError as exc:
            raise StatisticsLabError(f"SEC IPO H1 field unavailable: {year} {field}") from exc

    sec_ticks = [[0, "2025 상반기"], [1, "2026 상반기"]]
    sec_corporate = [
        {"period": index, "date": f"{year}-06-30", "value": sec_half(year, "corporate_count")}
        for index, year in enumerate((2025, 2026))
    ]
    sec_spac = [
        {"period": index, "date": f"{year}-06-30", "value": sec_half(year, "spac_count")}
        for index, year in enumerate((2025, 2026))
    ]
    sec_fund = [
        {"period": index, "date": f"{year}-06-30", "value": sec_half(year, "fund_count")}
        for index, year in enumerate((2025, 2026))
    ]
    sec_2025_proceeds = sec_half(2025, "total_proceeds_mn") / 1000.0
    sec_2026_proceeds = sec_half(2026, "total_proceeds_mn") / 1000.0
    sec_2026_corporate_proceeds = sec_half(2026, "corporate_proceeds_mn") / 1000.0

    ici_rows = source_rows["ICI_WEEKLY_EQUITY_ETF_FLOW"]
    ici_ticks = [
        [index, date.fromisoformat(str(row["date"])).strftime("%m/%d")]
        for index, row in enumerate(ici_rows)
    ]
    ici_equity = [
        {"period": index, "date": str(row["date"]), "value": float(row["value"]) / 1000.0}
        for index, row in enumerate(ici_rows)
    ]
    ici_domestic = [
        {"period": index, "date": str(row["date"]), "value": float(row["domestic"]) / 1000.0}
        for index, row in enumerate(ici_rows)
    ]
    ici_world = [
        {"period": index, "date": str(row["date"]), "value": float(row["world"]) / 1000.0}
        for index, row in enumerate(ici_rows)
    ]

    charts = [
        _chart("m2_nasdaq", "M2와 NASDAQ의 상승 속도", "liquidity", "cycle_start_100",
               "각 사이클 시작월을 100으로 맞춰 유동성과 주가의 누적 속도를 비교합니다.",
               "M2 정의는 2020년에 바뀌었으며, 두 선의 동행은 인과관계를 뜻하지 않습니다.",
               [_series("닷컴 NASDAQ", "dotcom", dot_nasdaq, "#d42b20"), _series("닷컴 M2", "dotcom", dot_m2, "#755d35"), _series("현재 NASDAQ", "current", cur_nasdaq, "#ff6a1a"), _series("현재 M2", "current", cur_m2, "#1c7262")], ["NASDAQCOM", "M2SL"]),
        _chart("nasdaq_per_m2", "M2 한 단위 대비 NASDAQ", "liquidity", "cycle_start_100",
               "NASDAQ을 M2로 나눈 비율의 사이클 시작 대비 변화를 봅니다.",
               "가격과 통화량의 단순 비율이며 적정가치나 매수·매도 신호가 아닙니다.",
               [_series("닷컴", "dotcom", dot_liq, "#c70039"), _series("현재", "current", cur_liq, "#ff7b00")], ["NASDAQCOM", "M2SL"]),
        _chart("nasdaq_per_household_liquid_assets", "가계 현금성 자산 한 단위 대비 NASDAQ", "liquidity", "cycle_start_100",
               "NASDAQ을 가계·비영리단체가 보유한 현금·입출금예금·정기·저축예금·머니마켓펀드 지분 합계로 나눈 비율의 사이클 시작 대비 변화를 봅니다.",
               "Fed Z.1 분기 말 잔액이며 비영리단체가 포함됩니다. 모든 현금성 자산이 주식 매수 대기자금은 아니며, M2와 합산하면 예금이 중복 계산되므로 별도 분모로 사용합니다.",
               [_series("닷컴", "dotcom", dot_household_cash, "#7a3248"), _series("현재", "current", cur_household_cash, "#e46b20")], ["NASDAQCOM", "DABSHNO"]),
        _chart("yield_curve", "10년−2년 장단기 금리차", "rates", "percent",
               "침체 경계로 자주 보는 10년물과 2년물 금리차를 같은 경과월에 겹칩니다.",
               "역전 해소 자체가 즉시 주가 상승이나 침체 종료를 보장하지 않습니다.",
               [_series("닷컴", "dotcom", dot_curve, "#8d2943"), _series("현재", "current", cur_curve, "#28756a")], ["T10Y2Y"]),
        _chart("policy_rate", "연방기금금리 경로", "rates", "percent",
               "FRED의 월평균 실효 연방기금금리 원자료를 보간 없이 연결해 닷컴기와 현재 수준을 비교합니다.",
               "목표금리 변경 때문에 계단형 구간은 있지만 완전한 ㅁ자 데이터가 아닙니다. 월평균 실효금리이며 시장의 미래 인하확률과도 다릅니다.",
               [_series("닷컴", "dotcom", dot_funds, "#8d2943"), _series("현재", "current", cur_funds, "#28756a")], ["FEDFUNDS"]),
        _chart("valuation_proxy", "기업가치 ÷ 세후이익 PER 대용치", "valuation", "multiple",
               "비금융기업 주식가치를 BEA 세후 기업이익으로 나눈 공개자료 기반 대용치입니다.",
               "NASDAQ 구성종목의 공식 trailing/forward P/E가 아니며 분모는 연율 기업이익입니다.",
               [_series("닷컴", "dotcom", dot_value, "#c70039"), _series("현재", "current", cur_value, "#ff7b00")], ["NCBEILQ027S", "CPATAX"]),
        _chart("margin_credit_proxy", "증권담보 신용대출 대용치", "credit", "cycle_start_100",
               "Fed Z.1의 가계가 브로커에 진 마진대출·기타 미수금을 사이클 시작=100으로 비교합니다.",
               "FINRA 월별 margin debt가 아닌 분기별 광의 대용치이며 최신 릴리스가 과거를 수정할 수 있습니다.",
               [_series("닷컴", "dotcom", dot_margin, "#c70039"), _series("현재", "current", cur_margin, "#ff7b00")], ["FL663067003"]),
        _chart("consumer_credit_growth", "소비자신용 증가율", "credit", "percent_yoy",
               "총 소비자신용의 전년동월 대비 증가율로 당시와 현재의 레버리지 속도를 비교합니다.",
               "주택담보대출은 제외되고, 잔액 증가가 곧 주식투자 신용 증가를 뜻하지 않습니다.",
               [_series("닷컴", "dotcom", dot_credit, "#8d2943"), _series("현재", "current", cur_credit, "#28756a")], ["TOTALSL"]),
        _chart("loan_standards", "은행 기업대출 심사 강화 비율", "credit", "net_percent",
               "대형·중견기업 C&I 대출기준을 강화한 은행의 순비율을 비교합니다.",
               "분기 설문이며 양수는 순강화, 음수는 순완화를 뜻합니다.",
               [_series("닷컴", "dotcom", dot_standards, "#8d2943"), _series("현재", "current", cur_standards, "#28756a")], ["DRTSCILM"]),
        _chart("profit_growth", "세후 기업이익 증가율", "valuation", "percent_yoy",
               "밸류에이션 분모인 세후 기업이익이 실제로 얼마나 성장했는지 비교합니다.",
               "전체 미국 기업이익 통계로 NASDAQ 기술기업만의 이익은 아닙니다.",
               [_series("닷컴", "dotcom", dot_profit, "#8d2943"), _series("현재", "current", cur_profit, "#28756a")], ["CPATAX"]),
        _chart("household_debt_service", "가계 원리금 상환 부담", "credit", "percent",
               "가계가 가처분소득 중 원리금 상환에 쓰는 비율을 닷컴기와 현재로 비교합니다.",
               "Fed Z.1 분기 추정치이며 최신 릴리스가 과거값과 분류를 수정할 수 있습니다.",
               [_series("닷컴", "dotcom", dot_debt_service, "#8d2943"), _series("현재", "current", cur_debt_service, "#28756a")], ["BOGZ1FL010000346Q"]),
        _chart("unemployment_rate", "실업률", "economy", "percent",
               "공식 U-3 실업률로 고용시장의 냉각 정도를 닷컴기와 현재 같은 경과월에 비교합니다.",
               "월별 가계조사 지표이며 취업 포기자와 불완전취업을 모두 포함하는 광의 실업률은 아닙니다.",
               [_series("닷컴", "dotcom", dot_unemployment, "#8d2943"), _series("현재", "current", cur_unemployment, "#28756a")], ["UNRATE"]),
        _chart("inflation_rate", "소비자물가 상승률", "economy", "percent_yoy",
               "도시소비자 CPI의 전년동월 대비 상승률로 물가 압력이 얼마나 다른지 비교합니다.",
               "전체 CPI이며 근원물가나 개인별 체감물가와는 다를 수 있습니다.",
               [_series("닷컴", "dotcom", dot_inflation, "#8d2943"), _series("현재", "current", cur_inflation, "#28756a")], ["CPIAUCSL"]),
        _chart("financial_conditions", "금융여건지수", "rates", "standard_deviation_index",
               "자금시장·채권·주식·은행 변수를 합친 Chicago Fed NFCI로 금융환경의 긴축 정도를 비교합니다.",
               "0보다 높으면 역사 평균보다 긴축적, 낮으면 완화적이라는 뜻이며 주가 방향을 단독 예측하지 않습니다.",
               [_series("닷컴", "dotcom", dot_financial_conditions, "#8d2943"), _series("현재", "current", cur_financial_conditions, "#28756a")], ["NFCI"]),
        _chart("rate_cycle_since_first_cut", "첫 금리 인하 뒤 재긴축 거리", "rates", "percentage_point_change",
               "1995년 7월과 2024년 9월 첫 인하를 0개월로 맞추고, 인하 직전 정책금리 대비 변화를 비교합니다.",
               "현재선은 실제 월평균 금리에서 멈춥니다. 같은 수준으로 복귀했다고 버블 붕괴가 자동 발생하는 것은 아닙니다.",
               [_series("1995 인하 사이클", "dotcom", dot_rate_cycle, "#8d2943"), _series("2024 인하 사이클", "current", cur_rate_cycle, "#28756a")], ["FEDFUNDS"]),
        _chart("corporate_bond_pressure", "회사채 금리와 국채 대비 부담", "rates", "percent",
               "10년 고품질 회사채 금리와 10년 국채 대비 스프레드를 겹쳐 기업 조달비용의 급등 여부를 봅니다.",
               "AAA·AA·A 중심의 고품질 회사채 곡선이라 투기등급 신용스트레스를 직접 보여주지 않습니다.",
               [_series("닷컴 회사채 10년", "dotcom", dot_corp_yield, "#9b1c31"), _series("닷컴 스프레드", "dotcom", dot_corp_spread, "#d47f52"), _series("현재 회사채 10년", "current", cur_corp_yield, "#166a5b"), _series("현재 스프레드", "current", cur_corp_spread, "#4aa18d")], ["HQMCB10YR", "GS10"]),
        _chart("inflation_lead_panel", "유가·구리 2개월 선행과 CPI", "economy", "percent_yoy",
               "WTI·구리 전년비와 그로부터 두 달 뒤의 CPI 전년비를 같은 x축에 맞춰 보는 물가 압력 감시판입니다.",
               "미래 원자재값을 그리지 않기 위해 CPI 날짜만 두 달 앞당겨 정렬했습니다. 이는 예측모형이 아니며 환율·임금·주거비와 전가율에 따라 관계가 달라집니다.",
               [_series("닷컴 2개월 뒤 CPI", "dotcom", dot_inflation_lead, "#8d2943"), _series("닷컴 WTI", "dotcom", dot_oil, "#c46d24"), _series("닷컴 구리", "dotcom", dot_copper, "#8c6b43"), _series("현재 2개월 뒤 CPI", "current", cur_inflation_lead, "#28756a"), _series("현재 WTI", "current", cur_oil, "#f07822"), _series("현재 구리", "current", cur_copper, "#5aa68f")], ["CPIAUCSL", "DCOILWTICO", "WPU10260314"]),
        _chart("kospi_market_breadth_2026_daily", "KOSPI 상승은 시장 전체로 퍼졌나", "economy", "year_start_100",
               "2026년 첫 실제 종가를 100으로 맞춰 KOSPI·KOSDAQ·국내 반도체의 누적 경로를 비교합니다. 세 선은 변동성이나 날짜를 조정하지 않은 실제 일봉입니다.",
               "KODEX 반도체는 KRX 반도체 지수를 추종하는 거래 가능한 대용치입니다. 지수 구성 중복 때문에 이 장표는 예측이 아니라 국내 상승의 폭과 쏠림을 진단합니다.",
               [_series("KOSPI", "current", kospi_2026, "#11110f"), _series("KOSDAQ", "current", kosdaq_2026, "#2f6fbb"), _series("KRX 반도체 대용치", "current", semicon_2026, "#e05d26")], ["KOSPI_DAILY", "KOSDAQ_DAILY", "KRX_SEMICON_PROXY_DAILY"]),
        _chart("kospi_external_semiconductor_pulse", "한국장과 글로벌 반도체 20일 충격", "economy", "percent_20d_log_return",
               "KOSPI와 대만 TAIEX의 실제 20거래일 로그수익률, 한국장 당일에는 이미 알려진 전일 미국 SOX 종가의 20거래일 로그수익률을 함께 봅니다.",
               "SOX는 한국 날짜보다 엄격히 이전인 미국 종가만 사용합니다. 상관과 조건부 빈도는 동행 진단이며 인과관계·확정 확률·매매 신호가 아닙니다.",
               [_series("KOSPI 20일", "current", kospi_20d, "#11110f"), _series("대만 TAIEX 20일", "current", taiex_20d, "#28756a"), _series("전일 SOX 20일", "current", sox_prior_20d, "#e05d26")], ["KOSPI_DAILY", "TAIEX_DAILY", "SOX_DAILY"]),
    ]

    breadth_chart, pulse_chart = charts[-2:]
    for chart in (breadth_chart, pulse_chart):
        chart["axis_type"] = "calendar_day_of_year"
        chart["max_period"] = 364
        chart["projection_max_points"] = 366
        chart["observed_end_label"] = "마지막 완료 거래일"
    breadth_chart["display_unit"] = "실제 일봉 · 시작=100"
    breadth_chart["market_breadth_diagnostics"] = market_breadth_diagnostics
    breadth_chart["research_context"] = [
        {
            "provider": "KRX",
            "finding": "KOSPI is the market-cap-weighted main-board benchmark; KOSDAQ is the technology and growth-company market.",
            "url": "https://global.krx.co.kr/contents/GLB/02/0201/0201010301/GLB0201010301.jsp",
        },
        {
            "provider": "Samsung Asset Management",
            "finding": "KODEX Semiconductor tracks the market-cap-weighted KRX Semiconductor Index.",
            "url": "https://m.samsungfund.com/etf/product/view.do?id=2ETF07",
        },
    ]
    pulse_chart["display_unit"] = "20거래일 로그수익률"
    pulse_chart["external_pulse_diagnostics"] = external_pulse_diagnostics
    pulse_chart["research_context"] = [
        {
            "provider": "Nasdaq",
            "finding": "SOX measures the largest U.S.-listed semiconductor companies under a published methodology.",
            "url": "https://indexes.nasdaqomx.com/docs/methodology_SOX.pdf",
        },
        {
            "provider": "TWSE",
            "finding": "TAIEX is the Taiwan Stock Exchange capitalization-weighted market benchmark.",
            "url": "https://twse-regulation.twse.com.tw/m/en/LawContent.aspx?FID=FL047579",
        },
    ]

    if hmi_reference is not None:
        charts.append(_chart(
            "housing_manufacturing_warning", "주택·제조업 경기 경고판", "economy", "neutral_line_distance",
            "NAHB 주택시장지수는 50을 뺀 값, Philadelphia Fed 제조업 확산지수는 0 기준으로 맞춰 냉각 폭을 비교합니다.",
            "Philadelphia Fed 지수는 전국 ISM PMI의 공개 대체 지표이며, 두 지표만으로 침체 확률을 계산하지 않습니다.",
            [_series("닷컴 HMI−50", "dotcom", dot_hmi, "#8d2943"), _series("닷컴 제조업 확산", "dotcom", dot_philly, "#d47f52"), _series("현재 HMI−50", "current", cur_hmi, "#28756a"), _series("현재 제조업 확산", "current", cur_philly, "#4aa18d")],
            ["NAHB_HMI", "GACDFSA066MSFRBPHI"],
        ))

    supplemental_charts = [
        _chart(
            "nasdaq_tech_cycle_milestones", "기술 사이클과 IPO 이정표", "ipo",
            "cycle_start_100",
            "1985년 말 NASDAQ을 100으로 맞추고 주요 기술기업 IPO와 시장 전환점을 실제 연말 종가 위에 놓습니다.",
            "연말 종가라 사건일 수익률은 아니며, 이정표가 지수 움직임의 단독 원인이라는 뜻도 아닙니다.",
            [_series("NASDAQ", "historical", tech_cycle, "#d94b24")], ["NASDAQCOM"],
        ),
        _chart(
            "sec_ipo_issuer_mix_h1", "미국 IPO 구성: 기업 vs SPAC", "ipo", "count",
            "SEC의 같은 상반기 기준으로 일반 기업, SPAC, 펀드 IPO 건수를 분리합니다.",
            "SEC 분류는 AI 기업만이 아니라 미국 IPO 전체이며 2026년은 상반기까지만 포함합니다.",
            [
                _series("일반 기업", "current", sec_corporate, "#d94b24"),
                _series("SPAC", "current", sec_spac, "#6956a8"),
                _series("펀드", "current", sec_fund, "#28756a"),
            ],
            ["SEC_IPO_QUARTERLY"],
        ),
        _chart(
            "sp500_after_two_twenty_percent_years", "2년 연속 20% 상승 뒤 3년 차", "economy",
            "percent",
            "S&P 500 배당 포함 연간수익률이 두 해 연속 20% 이상이었던 모든 중첩 사례와 다음 해를 비교합니다.",
            "서로 겹치는 연도 조합을 각각 사건으로 세며, 작은 역사표본을 미래 확률로 해석하지 않습니다.",
            [
                _series("첫해", "historical", first_year, "#b8aa92"),
                _series("둘째 해", "historical", second_year, "#d94b24"),
                _series("다음 해", "historical", third_year, "#28756a"),
            ],
            ["NYU_SP500_ANNUAL_TOTAL_RETURN"],
        ),
        _chart(
            "gold_vs_us_m2", "금과 미국 M2의 실제 경로", "liquidity", "cycle_start_100",
            "2023년 첫 공통 월을 100으로 맞춰 금 선물 종가와 미국 M2를 비교합니다.",
            "첨부 장표의 글로벌 유동성 모델이 아닌 공개 대체지표이며, 금 선물과 M2의 동행은 인과나 목표가격을 뜻하지 않습니다.",
            [
                _series("금", "current", gold_index, "#b58b2a"),
                _series("미국 M2", "current", m2_gold_index, "#28756a"),
            ],
            ["GOLD_DAILY", "M2SL"],
        ),
        _chart(
            "ici_weekly_equity_etf_flow", "주식 ETF 자금 유입", "liquidity", "billions_usd",
            "ICI가 공개한 최근 5주 주식 ETF 순발행 추정치를 미국 주식과 해외 주식으로 나눕니다.",
            "주간치는 업계 추정치여서 수정될 수 있고 실제 월간 순발행과 다를 수 있습니다.",
            [
                _series("주식 전체", "current", ici_equity, "#11110f"),
                _series("미국 주식", "current", ici_domestic, "#d94b24"),
                _series("해외 주식", "current", ici_world, "#28756a"),
            ],
            ["ICI_WEEKLY_EQUITY_ETF_FLOW"],
        ),
        _chart(
            "negative_then_strong_quarter_followthrough", "급반등 분기 뒤의 흐름", "economy",
            "percent",
            "S&P 500이 마이너스 분기 다음 분기에 10% 넘게 반등한 역사 사례의 이후 1개·2개 분기 가격수익률을 봅니다.",
            "Yahoo 종가 기반 가격수익률이라 배당을 제외하며, Carson·FactSet의 배당 포함 표와 숫자가 같을 필요는 없습니다.",
            [
                _series("다음 분기", "historical", quarter_next, "#d94b24"),
                _series("두 분기 누적", "historical", quarter_two, "#28756a"),
            ],
            ["SP500_DAILY"],
        ),
        _chart(
            "household_balance_sheet_trend_gap", "가계 주식·현금·채권의 추세 이탈", "credit",
            "percent_vs_trend",
            "2009~2019 분기 선형추세를 각 항목에 따로 적합해 실제 잔액이 추세보다 얼마나 위·아래인지 비교합니다.",
            "가계에는 비영리단체가 포함되고 주식은 시장가격 변동의 영향을 크게 받으며, 선형추세는 구조적 적정수준이 아닙니다.",
            [
                _series("주식", "current", equity_gap, "#11110f"),
                _series("현금성 자산", "current", cash_gap, "#b58b2a"),
                _series("채권", "current", debt_gap, "#28756a"),
            ],
            ["BOGZ1LM153064475Q", "DABSHNO", "BOGZ1FL154022375A"],
        ),
    ]
    tech_chart, sec_chart, annual_chart, gold_chart, ici_chart, quarter_chart, household_chart = (
        supplemental_charts
    )
    tech_chart.update({
        "axis_type": "calendar_year",
        "max_period": int(tech_cycle[-1]["period"]),
        "projection_max_points": 18,
        "x_ticks": [[0, "1985"], [10, "1995"], [15, "2000"], [23, "2008"], [35, "2020"], [int(tech_cycle[-1]["period"]), str(latest_current.year)]],
        "events": [
            {"period": 10, "label": "Netscape IPO"},
            {"period": 12, "label": "Amazon IPO"},
            {"period": 15, "label": "닷컴 정점"},
            {"period": 19, "label": "Google IPO"},
            {"period": 27, "label": "Meta IPO"},
        ],
    })
    for chart in (sec_chart, annual_chart, ici_chart, quarter_chart):
        chart["chart_type"] = "grouped_bar"
    sec_chart.update({"axis_type": "categorical", "max_period": 1, "x_ticks": sec_ticks})
    annual_chart.update({
        "axis_type": "categorical", "max_period": len(annual_event_ticks) - 1,
        "x_ticks": annual_event_ticks,
    })
    gold_chart.update({
        "axis_type": "elapsed_month", "max_period": max(int(row["period"]) for row in gold_index),
        "x_ticks": [[0, "2023"], [12, "2024"], [24, "2025"], [36, "2026"]],
    })
    ici_chart.update({
        "axis_type": "categorical", "max_period": len(ici_rows) - 1, "x_ticks": ici_ticks,
    })
    quarter_chart.update({
        "axis_type": "categorical", "max_period": len(quarter_next) - 1,
        "x_ticks": quarter_ticks, "event_diagnostics": quarter_diagnostics,
    })
    household_chart.update({
        "axis_type": "calendar_quarter", "max_period": max(int(row["period"]) for row in equity_gap),
        "x_ticks": [[0, "2009"], [16, "2013"], [32, "2017"], [48, "2021"], [64, "2025"]],
    })
    charts.extend(supplemental_charts)

    def chart_last(chart_index: int, series_index: int) -> float:
        return float(charts[chart_index]["series"][series_index]["points"][-1]["value"])

    household_cash_current = cur_household_cash[-1]
    household_cash_dotcom_same_period = next(
        point for point in reversed(dot_household_cash)
        if int(point["period"]) <= int(household_cash_current["period"])
    )

    chart_insights = {
        "m2_nasdaq": (
            f"같은 경과월에 현재 NASDAQ은 시작 대비 {chart_last(0, 2):.0f}, M2는 {chart_last(0, 3):.0f}입니다. "
            f"닷컴 당시 NASDAQ {chart_last(0, 0):.0f}, M2 {chart_last(0, 1):.0f}와 비교해 주가가 유동성보다 얼마나 앞섰는지 봅니다."
        ),
        "nasdaq_per_m2": (
            f"현재 유동성 대비 NASDAQ 지수는 {chart_last(1, 1):.0f}, 닷컴 당시 같은 구간은 {chart_last(1, 0):.0f}입니다. "
            "100보다 높을수록 통화량 증가보다 주가 상승이 더 빨랐다는 뜻입니다."
        ),
        "nasdaq_per_household_liquid_assets": (
            f"현재 가계 현금성 자산 대비 NASDAQ 지수는 {float(household_cash_current['value']):.0f}, "
            f"같은 경과월의 닷컴 지수는 {float(household_cash_dotcom_same_period['value']):.0f}입니다. "
            "100보다 높을수록 실제 가계 현금·예금·MMF 증가보다 주가 상승이 더 빨랐다는 뜻입니다."
        ),
        "yield_curve": (
            f"현재 장단기 금리차는 {chart_last(3, 1):+.1f}%p, 닷컴 당시 같은 구간은 {chart_last(3, 0):+.1f}%p입니다. "
            "0 아래는 금리 역전, 0 위는 정상 기울기이며 경기 방향을 단독으로 확정하지는 않습니다."
        ),
        "policy_rate": (
            f"현재 정책금리는 {chart_last(4, 1):.1f}%, 닷컴 당시 같은 구간은 {chart_last(4, 0):.1f}%입니다. "
            "1995~1999 실측은 6.05% 고점에서 4.63%까지 내린 뒤 5.42%로 재상승해 계단처럼 보이지만 완전한 사각형은 아닙니다."
        ),
        "valuation_proxy": (
            f"현재 기업가치/세후이익 대용치는 {chart_last(5, 1):.1f}배, 닷컴 당시 같은 구간은 {chart_last(5, 0):.1f}배입니다. "
            "높을수록 이익에 비해 시장가치가 비싸다는 뜻이지만 NASDAQ 공식 PER은 아닙니다."
        ),
        "margin_credit_proxy": (
            f"현재 증권담보 신용 대용치는 시작 대비 {chart_last(6, 1):.0f}, 닷컴 당시에는 {chart_last(6, 0):.0f}입니다. "
            "상승 속도가 빠를수록 레버리지 확대와 가격 충격 민감도가 커질 가능성을 뜻합니다."
        ),
        "consumer_credit_growth": (
            f"현재 소비자신용 증가율은 {chart_last(7, 1):+.1f}%, 닷컴 당시 같은 구간은 {chart_last(7, 0):+.1f}%입니다. "
            "빠른 증가는 소비를 지지할 수 있지만 동시에 가계 부채 부담도 키웁니다."
        ),
        "loan_standards": (
            f"현재 대출기준 강화 응답은 {chart_last(8, 1):+.1f}%, 닷컴 당시 같은 구간은 {chart_last(8, 0):+.1f}%입니다. "
            "양수와 상승은 더 많은 은행이 대출을 조인다는 뜻이고, 음수는 완화 쪽입니다."
        ),
        "profit_growth": (
            f"현재 세후 기업이익 증가율은 {chart_last(9, 1):+.1f}%, 닷컴 당시 같은 구간은 {chart_last(9, 0):+.1f}%입니다. "
            "이익이 늘면 밸류에이션을 지지하지만 주가가 이익보다 빨리 오르면 부담은 다시 커집니다."
        ),
        "household_debt_service": (
            f"현재 가계 원리금 부담은 가처분소득의 {chart_last(10, 1):.1f}%, 닷컴 당시 같은 구간은 {chart_last(10, 0):.1f}%입니다. "
            "높을수록 금리와 부채가 소비 여력을 더 많이 잠식한다는 뜻입니다."
        ),
        "unemployment_rate": (
            f"현재 실업률은 {chart_last(11, 1):.1f}%, 닷컴 당시 같은 구간은 {chart_last(11, 0):.1f}%입니다. "
            "상승하면 고용 냉각 신호지만 금리 인하 기대와 성장 둔화를 함께 봐야 합니다."
        ),
        "inflation_rate": (
            f"현재 CPI 상승률은 {chart_last(12, 1):+.1f}%, 닷컴 당시 같은 구간은 {chart_last(12, 0):+.1f}%입니다. "
            "낮아지면 금리 부담 완화 여지가 커지지만 수요 둔화가 원인인지도 확인해야 합니다."
        ),
        "financial_conditions": (
            f"현재 NFCI는 {chart_last(13, 1):+.2f}, 닷컴 당시 같은 구간은 {chart_last(13, 0):+.2f}입니다. "
            "0 아래는 평균보다 완화적, 0 위는 긴축적이어서 시장이 받는 자금 압력을 직관적으로 보여줍니다."
        ),
        "rate_cycle_since_first_cut": (
            f"현재 첫 인하 직전 대비 정책금리는 {cur_rate_cycle[-1]['value']:+.2f}%p, "
            f"1995년 사이클 같은 경과월은 {dot_rate_cycle[min(len(dot_rate_cycle)-1, len(cur_rate_cycle)-1)]['value']:+.2f}%p입니다. "
            "닷컴 붕괴 전에는 재긴축이 나타났지만 현재의 동일 트리거 여부는 실제선이 0으로 복귀하는지 따로 봐야 합니다."
        ),
        "corporate_bond_pressure": (
            f"현재 고품질 회사채 10년 금리는 {cur_corp_yield[-1]['value']:.2f}%, 국채 대비 스프레드는 {cur_corp_spread[-1]['value']:.2f}%p입니다. "
            "금리와 스프레드가 함께 급등하면 기업의 할인율과 신용비용이 동시에 악화되는 경고입니다."
        ),
        "inflation_lead_panel": (
            f"최근 CPI는 {cur_inflation[-1]['value']:+.1f}%이고, WTI는 {cur_oil[-1]['value']:+.1f}%, 구리는 {cur_copper[-1]['value']:+.1f}%입니다. "
            "원자재가 함께 오르면 향후 물가 상방 압력, 엇갈리면 전가율과 주거·서비스 물가를 더 확인해야 합니다."
        ),
        "kospi_market_breadth_2026_daily": (
            f"2026년 KOSPI는 {kospi_2026[-1]['value'] - 100:+.1f}%인데 KOSDAQ은 "
            f"{kosdaq_2026[-1]['value'] - 100:+.1f}%입니다. 반도체 대용치는 "
            f"{semicon_2026[-1]['value'] - 100:+.1f}%로 KOSPI보다 "
            f"{(semicon_2026[-1]['value'] / kospi_2026[-1]['value'] - 1.0) * 100:+.1f}% 앞서, "
            "현재 상승은 국내 시장 전체보다 대형 반도체에 집중돼 있습니다."
        ),
        "kospi_external_semiconductor_pulse": (
            f"2020년 이후 20거래일 수익률 상관은 KOSPI–TAIEX "
            f"{external_pulse_diagnostics['taiex_same_or_prior_close']['rolling_20_session_correlation']:+.2f}, "
            f"KOSPI–전일 SOX {external_pulse_diagnostics['sox_strictly_prior_us_close']['rolling_20_session_correlation']:+.2f}입니다. "
            "세 선이 함께 약해지면 글로벌 반도체 사이클 둔화, KOSPI만 약하면 한국 고유 위험을 우선 확인합니다."
        ),
        "nasdaq_tech_cycle_milestones": (
            f"1985년 말 100이던 NASDAQ은 최근 연말 기준 {tech_cycle[-1]['value']:.0f}입니다. "
            "Netscape 같은 상징적 소형 IPO, 대형 기술기업 상장, 지수 정점은 한 줄의 순서가 아니라 서로 겹쳐 진행됐습니다."
        ),
        "sec_ipo_issuer_mix_h1": (
            f"2026년 상반기는 일반 기업 {int(sum(row['value'] for row in sec_corporate[1:]))}건, "
            f"SPAC {int(sum(row['value'] for row in sec_spac[1:]))}건입니다. 총 공모액은 ${sec_2025_proceeds:.1f}B에서 "
            f"${sec_2026_proceeds:.1f}B로 늘었고, 이 중 일반 기업이 ${sec_2026_corporate_proceeds:.1f}B여서 건수보다 대형 거래 집중도가 더 크게 뛰었습니다."
        ),
        "sp500_after_two_twenty_percent_years": (
            f"역사상 {len(third_year)}개 중첩 사례에서 3년 차 평균은 {statistics.mean(row['value'] for row in third_year):+.1f}%, "
            f"중앙값은 {statistics.median(row['value'] for row in third_year):+.1f}%였습니다. 연속 강세 뒤에도 결과 폭이 커서 평균만으로 다음 해를 단정할 수 없습니다."
        ),
        "gold_vs_us_m2": (
            f"2023년 초 100 기준 최근 금은 {gold_index[-1]['value']:.0f}, 미국 M2는 {m2_gold_index[-1]['value']:.0f}입니다. "
            "금이 M2보다 빠르면 통화량 외에도 실질금리·달러·안전자산 수요가 가격에 더 강하게 작용했을 가능성을 봅니다."
        ),
        "ici_weekly_equity_etf_flow": (
            f"최근 5주 주식 ETF 순유입 추정 합계는 ${sum(row['value'] for row in ici_equity):.1f}B이며, "
            f"미국 주식 ${sum(row['value'] for row in ici_domestic):.1f}B, 해외 주식 ${sum(row['value'] for row in ici_world):.1f}B입니다. 유입이 넓게 이어지는지 한 주 급증인지 구분합니다."
        ),
        "negative_then_strong_quarter_followthrough": (
            f"동일 규칙의 {quarter_diagnostics['event_count']}개 가격수익률 사례에서 다음 분기 평균은 "
            f"{quarter_diagnostics['next_quarter_average']:+.1f}%({quarter_diagnostics['next_quarter_positive']}/{quarter_diagnostics['event_count']}회 상승), "
            f"두 분기 누적 평균은 {quarter_diagnostics['two_quarter_average']:+.1f}%였습니다. 반등 뒤 추가 상승이 많았지만 손실 사례도 남습니다."
        ),
        "household_balance_sheet_trend_gap": (
            f"최근 값은 2009~2019 추세 대비 주식 {equity_gap[-1]['value']:+.0f}%, 현금성 자산 {cash_gap[-1]['value']:+.0f}%, "
            f"보유 채권 {debt_gap[-1]['value']:+.0f}%입니다. 세 자산 중 어느 항목이 장기추세에서 가장 크게 벗어났는지 비교합니다."
        ),
    }
    if hmi_reference is not None:
        chart_insights["housing_manufacturing_warning"] = (
            f"현재 HMI는 중립선보다 {cur_hmi[-1]['value']:+.0f}p, 제조업 확산지수는 {cur_philly[-1]['value']:+.1f}입니다. "
            "둘 다 0 아래로 내려가고 하락이 이어질 때 주택과 제조업의 동시 냉각 경고가 강해집니다."
        )
    for chart in charts:
        chart["insight"] = chart_insights[chart["id"]]
    policy_rate_chart = next(chart for chart in charts if chart["id"] == "policy_rate")
    dotcom_policy_points = policy_rate_chart["series"][0]["points"]
    policy_rate_chart["source_validation"] = {
        "source_id": "FEDFUNDS",
        "period": "1995-01-01_to_1999-12-01",
        "observations": len(dotcom_policy_points),
        "interpolation": False,
        "perfect_rectangle": False,
        "minimum": min(dotcom_policy_points, key=lambda row: float(row["value"])),
        "maximum": max(dotcom_policy_points, key=lambda row: float(row["value"])),
    }
    if ipo_reference is not None:
        validate_ipo_reference(ipo_reference)
        ipo_charts = []
        for spec in ipo_reference["charts"]:
            chart = _chart(
                str(spec["id"]), str(spec["title"]), str(spec["category"]),
                str(spec["unit"]), str(spec["description"]), str(spec["caveat"]),
                spec["series"], list(spec["source_ids"]),
            )
            chart["insight"] = str(spec["insight"])
            for optional in (
                "scale", "chart_type", "axis_type", "max_period", "x_ticks",
            ):
                if optional in spec:
                    chart[optional] = spec[optional]
            if spec.get("detail_rows"):
                chart["detail_rows"] = spec["detail_rows"]
            ipo_charts.append(chart)
        qualitative = ipo_reference.get("qualitative_ipo") or {}
        value_table = qualitative.get("all_ipo_first_close_market_value_bn") or {}
        total_equity_by_year = _annual_last(monthly["BOGZ1LM893064105Q"])

        def absorption_points(values: dict[str, Any], years: list[int]) -> list[dict[str, Any]]:
            points = []
            for index, year in enumerate(years):
                denominator = total_equity_by_year.get(year)
                numerator = values.get(str(year))
                if denominator and numerator is not None:
                    points.append({
                        "period": index * 12,
                        "date": f"{year}-12-31",
                        "value": float(numerator) * 1000.0 / denominator * 100.0,
                    })
            return points

        dot_absorption = absorption_points(value_table.get("dotcom") or {}, list(range(1995, 2000)))
        cur_absorption = absorption_points(value_table.get("current") or {}, list(range(2023, 2027)))
        private_watch = qualitative.get("private_frontier_ai_watchlist") or {}
        ipo_sensitivity = qualitative.get("reported_frontier_ai_ipo_sensitivity") or {}
        listed_watch = qualitative.get("listed_ai_beneficiary_watchlist") or {}
        global_chip_watch = qualitative.get("global_ai_chip_completed_ipos") or {}
        nasdaq_memory_watch = qualitative.get("nasdaq_memory_market_events") or {}
        private_total_bn = sum(float(row["valuation_bn"]) for row in private_watch.get("members") or [])
        latest_equity = total_equity_by_year.get(2026) or float(monthly["BOGZ1LM893064105Q"][-1]["value"])
        private_ratio = private_total_bn * 1000.0 / latest_equity * 100.0
        sensitivity_total_bn = sum(
            float(row["headline_ipo_valuation_bn"])
            for row in ipo_sensitivity.get("members") or []
        )
        sensitivity_ratio = sensitivity_total_bn * 1000.0 / latest_equity * 100.0
        quality_series = [
            _series("닷컴 실제 IPO", "dotcom", dot_absorption, "#c70039"),
            _series("현재 실제 IPO", "current", cur_absorption, "#ff6a1a"),
            _series("OpenAI+Anthropic 비상장 감시점", "current", [{"period": 40, "date": private_watch.get("as_of", "2026-05-28"), "value": private_ratio}], "#28756a"),
        ]
        if sensitivity_total_bn > 0:
            quality_series.append(_series(
                "상장가치 헤드라인 민감도", "scenario",
                [{"period": 44, "date": ipo_sensitivity.get("as_of", "2026-08-18"), "value": sensitivity_ratio}],
                "#6b3fa0",
            ))
        quality_chart = _chart(
            "ipo_market_absorption", "IPO와 AI 자본시장 흡수 강도", "ipo", "percent_of_us_corporate_equity_value",
            "한 해 IPO들의 첫 거래 종가 기준 상장 후 시가총액 합계를 미국 기업주식 총가치로 나눠, 건수보다 자금 규모를 비교합니다.",
            "분모는 지수 시가총액이 아니라 비상장·밀접보유분도 포함한 Fed의 미국 기업주식 총가치입니다. OpenAI·Anthropic은 비상장 감시점이며 SKHY ADS와 중국·홍콩 상장 사건은 Ritter식 미국 실제 IPO선에 합산하지 않습니다.",
            quality_series,
            [
                value_table.get("source_id"), "BOGZ1LM893064105Q",
                *[row["source_id"] for row in private_watch.get("members") or []],
                *[row["source_id"] for row in ipo_sensitivity.get("members") or []],
                *[row["source_id"] for row in listed_watch.get("members") or []],
                *[row["source_id"] for row in global_chip_watch.get("members") or []],
                *[row["source_id"] for row in nasdaq_memory_watch.get("members") or []],
                global_chip_watch.get("classification_source_id"),
            ],
        )
        quality_chart["series"][2]["marker_radius"] = 10
        quality_chart["series"][2]["marker_emphasis"] = "private_frontier_watchlist"
        if len(quality_chart["series"]) > 3:
            quality_chart["series"][3]["marker_radius"] = 10
            quality_chart["series"][3]["marker_emphasis"] = "reported_ipo_valuation_sensitivity"
        quality_chart["insight"] = (
            f"1999년 전체 IPO 첫 거래 시가총액은 $652B, 2025년은 $442B입니다. "
            "OpenAI와 Anthropic의 최근 비상장 평가액 합계 $1.817T와 $3.0T 상장가치 헤드라인은 각각 감시점과 민감도일 뿐 완료된 IPO가 아닙니다. "
            "$3.0T 가치에서 5%를 판다는 가정의 총매각 규모는 $150B이며 신주와 구주를 구분하지 않습니다."
        )
        quality_chart["scenario_sensitivity"] = ipo_sensitivity
        quality_chart["detail_rows"] = [
            {"period": "1999", "label": "전체 비교가능 IPO", "value": "$652B · 실제 상장"},
            {"period": "2025", "label": "전체 비교가능 IPO", "value": "$442B · 실제 상장"},
            {"period": "2026", "label": "OpenAI + Anthropic", "value": "$1.817T · 비상장 평가액"},
            {"period": "NASDAQ ADS", "label": "SK hynix SKHY", "value": "2026-07-10 거래 개시 · HBM 핵심 · Ritter 전통 IPO 밖"},
            {"period": "중국 메모리 NASDAQ", "label": "Montage Technology MONT", "value": "2013-09-26 · 서버용 메모리 인터페이스 · 역사 맥락"},
            {"period": "글로벌 IPO", "label": "Horizon · Black Sesame · Moore Threads · MetaX", "value": "중국·홍콩 AI 칩 상장 완료 · 별도 집계"},
        ]

        small_table = qualitative.get("small_issuer_sales_below_100m") or {}
        def share_points(values: dict[str, Any], years: list[int]) -> list[dict[str, Any]]:
            result = []
            for index, year in enumerate(years):
                row = values.get(str(year)) or {}
                if row.get("total"):
                    result.append({"period": index * 12, "date": f"{year}-12-31", "value": float(row["small"]) / float(row["total"]) * 100.0})
            return result
        small_chart = _chart(
            "small_issuer_ipo_share", "저매출 IPO 확산 비중", "ipo", "percent",
            "상장 전 최근 12개월 매출이 2024년 구매력 기준 1억 달러 미만인 기업이 전체 비교가능 IPO에서 차지하는 비중입니다.",
            "소형주는 거래규모가 아니라 물가조정 매출 기준입니다. 2023년은 전체 표본이 54건으로 작아 비중 하나만으로 과열을 단정할 수 없습니다.",
            [_series("닷컴 저매출 IPO", "dotcom", share_points(small_table.get("dotcom") or {}, list(range(1995, 2000))), "#8d2943"), _series("현재 저매출 IPO", "current", share_points(small_table.get("current") or {}, list(range(2023, 2026))), "#28756a")],
            [small_table.get("source_id")],
        )
        small_chart["insight"] = "저매출 IPO 비중은 1999년 77%까지 높아졌지만 2025년은 39%입니다. 현재는 대형 AI 비상장사 집중은 크지만 닷컴 말기의 소형·저매출 상장 확산과는 아직 다릅니다."
        small_chart["detail_rows"] = [
            {"period": "1999", "label": "저매출 365 / 전체 476", "value": "77%"},
            {"period": "2023", "label": "저매출 37 / 전체 54", "value": "69% · 작은 표본"},
            {"period": "2025", "label": "저매출 35 / 전체 90", "value": "39%"},
        ]
        ipo_charts.extend([quality_chart, small_chart])
        charts = ipo_charts + charts

    source_meta = []
    for series_id, spec in FRED_SERIES.items():
        rows = source_rows[series_id]
        fred_start = spec.get("window_start", "1995-01-01")
        source_meta.append({
            "series_id": series_id,
            **spec,
            "source_url": f"https://fred.stlouisfed.org/series/{series_id}",
            "request_url": f"{FRED_ENDPOINT}?id={series_id}&cosd={fred_start}",
            "available_at": generated_at,
            "latest_observation": rows[-1]["date"],
            "row_count": len(rows),
            "raw_sha256": receipts[series_id]["raw_sha256"],
            "vintage": "current_release_reconstructed",
        })
    for series_id, spec in DAILY_MARKET_SERIES.items():
        rows = source_rows[series_id]
        receipt = receipts[series_id]
        source_meta.append({
            "series_id": series_id,
            "title": spec["title"],
            "provider": spec["provider"],
            "unit": spec["unit"],
            "native_frequency": spec["native_frequency"],
            "source_url": spec["source_url"],
            "request_url": receipt["request_url"],
            "available_at": generated_at,
            "latest_observation": rows[-1]["date"],
            "row_count": len(rows),
            "raw_sha256": receipt["raw_sha256"],
            "vintage": "yahoo_current_chart_response",
            "data_quality": receipt.get("data_quality"),
            "window_start": spec["window_start"],
            "window_end_exclusive": spec["window_end_exclusive"],
        })
    for series_id, spec in SUPPLEMENTAL_SOURCES.items():
        rows = source_rows[series_id]
        receipt = receipts[series_id]
        source_meta.append({
            "series_id": series_id,
            "title": spec["title"],
            "provider": spec["provider"],
            "unit": spec["unit"],
            "native_frequency": spec["native_frequency"],
            "source_url": spec["source_url"],
            "request_url": spec["request_url"],
            "available_at": receipt.get("available_at", generated_at),
            "latest_observation": max(str(row["date"]) for row in rows),
            "row_count": len(rows),
            "raw_sha256": receipt["raw_sha256"],
            "vintage": receipt.get("vintage", "current_public_release_reconstructed"),
        })
    z1_rows = source_rows["FL663067003"]
    source_meta.append({
        "series_id": "FL663067003",
        "title": "Household margin loans and other receivables due to brokers",
        "provider": "Board of Governors of the Federal Reserve System (US)",
        "unit": "millions_usd",
        "native_frequency": "quarterly",
        "source_url": "https://www.federalreserve.gov/releases/z1/current/",
        "request_url": Z1_ENDPOINT,
        "available_at": generated_at,
        "latest_observation": z1_rows[-1]["date"],
        "row_count": len(z1_rows),
        "raw_sha256": receipts["FL663067003"]["raw_sha256"],
        "vintage": "current_release_reconstructed",
        "proxy_warning": "not_FINRA_monthly_margin_debt",
    })
    if ipo_reference is not None:
        source_meta.extend(ipo_reference["sources"])
    if hmi_reference is not None:
        source_meta.append(hmi_reference["source"])
    payload = {
        "schema_version": 1,
        "dataset_id": "dotcom_statistics_lab_v1",
        "status": "ok",
        "probability_space": "reference_only",
        "model_use": False,
        "official_forecast_input": False,
        "generated_at": generated_at,
        "as_of": max(row["latest_observation"] for row in source_meta),
        "cycle_alignment": {
            "dotcom_start": DOTCOM_START.isoformat(),
            "dotcom_end": DOTCOM_END.isoformat(),
            "current_start": CURRENT_START.isoformat(),
            "current_axis_end": CURRENT_AXIS_END.isoformat(),
            "comparison_months": comparison_months,
            "current_observed_through": latest_current.isoformat(),
            "current_line_policy": "actual_observations_only_no_forecast_extension",
            "forecast_extension": False,
            "endpoint_forcing": False,
        },
        "charts": charts,
        "sources": source_meta,
        "ipo_comparison": {
            "status": ipo_reference["status"],
            "as_of": ipo_reference["as_of"],
            "coverage": ipo_reference["coverage"],
            "classification": ipo_reference["classification"],
        } if ipo_reference is not None else None,
        "vintage_warning": "latest-release reconstructed history; not native point-in-time vintages",
        "refresh_policy": {
            "check_cadence": "weekly",
            "native_frequencies_preserved": True,
            "schedule": "Saturday 00:20 UTC",
        },
        "excluded_sources": {
            "FINRA_margin_statistics": "permission required; not fetched or redistributed",
            "Moodys_Baa_spread": "proprietary redistribution restriction",
            "paid_forward_PE": "not reproducible under public redistribution rights",
        },
    }
    validate_statistics_lab(payload)
    return payload


def validate_statistics_lab(payload: dict[str, Any], *, projected: bool = False) -> None:
    if payload.get("schema_version") != 1 or payload.get("status") != "ok":
        raise StatisticsLabError("statistics lab schema/status invalid")
    if payload.get("probability_space") != "reference_only":
        raise StatisticsLabError("statistics lab must be reference_only")
    if payload.get("model_use") is not False or payload.get("official_forecast_input") is not False:
        raise StatisticsLabError("statistics lab cannot feed model or official forecast")
    alignment = payload.get("cycle_alignment") or {}
    expected_alignment = {
        "dotcom_start": DOTCOM_START.isoformat(),
        "dotcom_end": DOTCOM_END.isoformat(),
        "current_start": CURRENT_START.isoformat(),
        "current_axis_end": CURRENT_AXIS_END.isoformat(),
        "comparison_months": COMPARISON_MONTHS,
        "current_line_policy": "actual_observations_only_no_forecast_extension",
        "forecast_extension": False,
        "endpoint_forcing": False,
    }
    if any(alignment.get(key) != value for key, value in expected_alignment.items()):
        raise StatisticsLabError("statistics cycle alignment contract invalid")
    charts = payload.get("charts")
    if not isinstance(charts, list) or len(charts) < 8:
        raise StatisticsLabError("statistics lab requires at least eight charts")
    ids = [row.get("id") for row in charts]
    if len(ids) != len(set(ids)):
        raise StatisticsLabError("statistics chart ids must be unique")
    for chart in charts:
        if not chart.get("insight") or not chart.get("caveat") or not chart.get("source_ids"):
            raise StatisticsLabError(f"chart {chart.get('id')} missing insight/caveat/source")
        for series in chart.get("series", []):
            periods = [int(point["period"]) for point in series.get("points", [])]
            values = [float(point["value"]) for point in series.get("points", [])]
            if not periods or periods != sorted(set(periods)):
                raise StatisticsLabError(f"chart {chart['id']} periods invalid")
            if not all(math.isfinite(value) for value in values):
                raise StatisticsLabError(f"chart {chart['id']} has non-finite values")
            period_limit = int(chart.get("max_period", COMPARISON_MONTHS))
            if max(periods) > period_limit:
                raise StatisticsLabError(
                    f"chart {chart['id']} exceeds its declared period axis"
                )
    sources = payload.get("sources")
    minimum_sources = (
        len(FRED_SERIES) + len(DAILY_MARKET_SERIES) + len(SUPPLEMENTAL_SOURCES) + 1
    )
    if not isinstance(sources, list) or len(sources) < minimum_sources:
        raise StatisticsLabError("statistics source registry incomplete")
    source_ids = [str(row.get("series_id")) for row in sources]
    if len(source_ids) != len(set(source_ids)):
        raise StatisticsLabError("statistics source ids must be unique")
    known_sources = set(source_ids)
    if not set(DAILY_MARKET_SERIES).issubset(known_sources):
        raise StatisticsLabError("daily market source registry incomplete")
    if not set(SUPPLEMENTAL_SOURCES).issubset(known_sources):
        raise StatisticsLabError("supplemental public source registry incomplete")
    try:
        generated_at = datetime.fromisoformat(str(payload["generated_at"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError) as exc:
        raise StatisticsLabError("statistics generated_at invalid") from exc
    for row in sources:
        if projected:
            continue
        digest = str(row.get("raw_sha256", ""))
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise StatisticsLabError(f"source {row.get('series_id')} hash invalid")
        try:
            latest_observation = date.fromisoformat(str(row["latest_observation"]))
            available_at = datetime.fromisoformat(
                str(row["available_at"]).replace("Z", "+00:00")
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise StatisticsLabError(f"source {row.get('series_id')} timestamp invalid") from exc
        if latest_observation > generated_at.date() or available_at > generated_at:
            raise StatisticsLabError(f"source {row.get('series_id')} future-data leakage")
    for chart in charts:
        if not set(chart.get("source_ids") or []).issubset(known_sources):
            raise StatisticsLabError(f"chart {chart.get('id')} has unknown source")
    breadth = next(
        (chart for chart in charts if chart.get("id") == "kospi_market_breadth_2026_daily"),
        None,
    )
    pulse = next(
        (chart for chart in charts if chart.get("id") == "kospi_external_semiconductor_pulse"),
        None,
    )
    if breadth is None or pulse is None:
        raise StatisticsLabError("KOSPI breadth and external pulse charts required")
    if breadth.get("source_ids") != [
        "KOSPI_DAILY", "KOSDAQ_DAILY", "KRX_SEMICON_PROXY_DAILY",
    ]:
        raise StatisticsLabError("KOSPI breadth sources invalid")
    if pulse.get("source_ids") != ["KOSPI_DAILY", "TAIEX_DAILY", "SOX_DAILY"]:
        raise StatisticsLabError("KOSPI external pulse sources invalid")
    for chart, diagnostics_key in (
        (breadth, "market_breadth_diagnostics"),
        (pulse, "external_pulse_diagnostics"),
    ):
        diagnostics = chart.get(diagnostics_key) or {}
        if diagnostics.get("time_warping") is not False:
            raise StatisticsLabError("daily market chart cannot warp time")
        if diagnostics.get("optimized_lag") is not False:
            raise StatisticsLabError("daily market chart cannot optimize lag")
        if diagnostics.get("forecast_extension") is not False:
            raise StatisticsLabError("daily market chart cannot contain forecast extension")
        if chart.get("axis_type") != "calendar_day_of_year" or chart.get("max_period") != 364:
            raise StatisticsLabError("daily market chart calendar axis invalid")
    sox_diagnostic = (pulse.get("external_pulse_diagnostics") or {}).get(
        "sox_strictly_prior_us_close"
    ) or {}
    if int(sox_diagnostic.get("observations", 0)) < 20:
        raise StatisticsLabError("SOX prior-close diagnostic sample too small")


def _semantic_snapshot(value: Any) -> Any:
    """Remove collector-clock metadata before deciding whether data changed."""
    if isinstance(value, dict):
        return {
            key: _semantic_snapshot(item)
            for key, item in value.items()
            if key not in {"generated_at", "available_at"}
        }
    if isinstance(value, list):
        return [_semantic_snapshot(item) for item in value]
    return value


def refresh_statistics_lab(
    root: Path, *,
    fred_fetcher: Callable[[str], tuple[list[dict[str, Any]], bytes]] = _fetch_fred,
    market_fetcher: Callable[
        [str, date, date], tuple[list[dict[str, Any]], dict[str, Any]]
    ] = _fetch_daily_market,
    supplemental_fetcher: Callable[
        [str], tuple[list[dict[str, Any]], bytes]
    ] = _fetch_supplemental,
    z1_fetcher: Callable[[str], bytes] | None = None,
    now: datetime | None = None,
) -> tuple[Path, dict[str, Any], bool]:
    generated_time = now or datetime.now(timezone.utc)
    generated_at = generated_time.isoformat(timespec="seconds")
    source_rows: dict[str, list[dict[str, Any]]] = {}
    receipts: dict[str, dict[str, Any]] = {}
    for series_id in FRED_SERIES:
        rows, raw = fred_fetcher(series_id)
        source_rows[series_id] = rows
        receipts[series_id] = {"raw_sha256": hashlib.sha256(raw).hexdigest()}
    for series_id, spec in DAILY_MARKET_SERIES.items():
        start = date.fromisoformat(spec["window_start"])
        fixed_end = date.fromisoformat(spec["window_end_exclusive"])
        end_exclusive = fixed_end
        end_exclusive = min(fixed_end, generated_time.date())
        if end_exclusive <= start:
            raise StatisticsLabError(f"daily market window unavailable: {series_id}")
        rows, receipt = market_fetcher(series_id, start, end_exclusive)
        bounded_rows = [
            row for row in rows
            if start <= date.fromisoformat(str(row["date"])) < end_exclusive
        ]
        if not bounded_rows:
            raise StatisticsLabError(f"daily market series empty after bounds: {series_id}")
        source_rows[series_id] = bounded_rows
        receipts[series_id] = receipt
    for series_id in SUPPLEMENTAL_SOURCES:
        if series_id == "ICI_WEEKLY_EQUITY_ETF_FLOW":
            ici_reference = load_ici_reference(root)
            source_rows[series_id] = ici_reference["rows"]
            receipts[series_id] = {
                "raw_sha256": ici_reference["source"]["raw_sha256"],
                "available_at": ici_reference["source"]["available_at"],
                "vintage": ici_reference["source"]["vintage"],
            }
            continue
        rows, raw = supplemental_fetcher(series_id)
        source_rows[series_id] = rows
        receipts[series_id] = {"raw_sha256": hashlib.sha256(raw).hexdigest()}
    fetch_z1 = z1_fetcher or (lambda url: _request(url, timeout=60))
    z1_raw = fetch_z1(Z1_ENDPOINT)
    source_rows["FL663067003"] = _parse_z1(z1_raw)
    receipts["FL663067003"] = {"raw_sha256": hashlib.sha256(z1_raw).hexdigest()}
    ipo_reference = load_ipo_reference(root)
    hmi_reference = load_hmi_reference(root)
    ici_reference = load_ici_reference(root)
    _validate_manual_reference_freshness(
        ipo_reference, hmi_reference, generated_at, ici_reference,
    )
    payload = build_statistics_lab(
        source_rows,
        generated_at=generated_at,
        receipts=receipts,
        ipo_reference=ipo_reference,
        hmi_reference=hmi_reference,
    )

    latest = root / LATEST_RELATIVE
    latest.parent.mkdir(parents=True, exist_ok=True)
    previous = None
    if latest.is_file():
        try:
            previous = json.loads(latest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = None
    previous_semantic = _semantic_snapshot(previous or {})
    current_semantic = _semantic_snapshot(payload)
    changed = previous_semantic != current_semantic
    if previous is not None and not changed:
        validate_statistics_lab(previous)
        return latest, previous, False
    latest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    if changed:
        archive_dir = root / ARCHIVE_RELATIVE
        archive_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.fromisoformat(generated_at).strftime("%Y%m%dT%H%M%SZ")
        archive = archive_dir / f"dotcom_statistics_{stamp}.json"
        if archive.exists():
            raise StatisticsLabError(f"append-only archive already exists: {archive}")
        archive.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return latest, payload, changed


def load_statistics_lab(root: Path) -> dict[str, Any]:
    path = root / LATEST_RELATIVE
    if not path.is_file():
        return {
            "schema_version": 1,
            "dataset_id": "dotcom_statistics_lab_v1",
            "status": "blocked",
            "probability_space": "reference_only",
            "model_use": False,
            "official_forecast_input": False,
            "generated_at": None,
            "as_of": None,
            "charts": [],
            "sources": [],
            "vintage_warning": "statistics database has not been refreshed",
            "refresh_policy": {"check_cadence": "weekly", "native_frequencies_preserved": True},
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    validate_statistics_lab(payload)
    return payload


def statistics_dashboard_projection(root: Path) -> dict[str, Any]:
    """Return customer-facing meaning with compact chart coordinates."""
    payload = load_statistics_lab(root)
    if payload.get("status") != "ok":
        return payload
    projected = {
        key: value for key, value in payload.items()
        if key not in {"charts", "ipo_comparison"}
    }
    projected["display_projection"] = True
    public_source_keys = {
        "series_id", "title", "provider", "source_url",
    }
    projected["sources"] = [
        {key: value for key, value in source.items() if key in public_source_keys}
        for source in payload["sources"]
    ]
    projected["charts"] = []
    for chart in payload["charts"]:
        # The browser derives chart bounds from the projected coordinates. Keeping
        # the stored audit range in the embedded payload duplicates those values.
        chart_view = {
            key: value for key, value in chart.items()
            if key not in {
                "series", "range", "detail_rows", "research_context",
                "market_breadth_diagnostics", "external_pulse_diagnostics",
                "comparison_transform", "source_validation",
                "scenario_sensitivity", "event_diagnostics",
            }
        }
        for diagnostics_key in (
            "market_breadth_diagnostics", "external_pulse_diagnostics",
        ):
            if diagnostics_key in chart:
                diagnostics = chart[diagnostics_key]
                chart_view[diagnostics_key] = {
                    key: diagnostics[key]
                    for key in ("time_warping", "optimized_lag", "forecast_extension")
                }
                if diagnostics_key == "external_pulse_diagnostics":
                    chart_view[diagnostics_key]["sox_strictly_prior_us_close"] = {
                        "observations": diagnostics["sox_strictly_prior_us_close"]["observations"],
                    }
        chart_view["series"] = []
        for series in chart["series"]:
            points = series.get("points") or []
            projection_max_points = max(2, int(chart.get("projection_max_points", 14)))
            if len(points) > projection_max_points:
                stride = math.ceil((len(points) - 1) / (projection_max_points - 1))
                display_points = points[::stride]
                if display_points[-1] is not points[-1]:
                    display_points.append(points[-1])
            else:
                display_points = points
            series_view = {
                "label": series["label"],
                "era": series["era"],
                "color": series["color"],
                "latest_date": points[-1].get("date") if points else None,
                "points": [
                    {
                        key: value for key, value in point.items()
                        if key in {"period", "value", "marker_radius"}
                    }
                    for point in display_points
                ],
            }
            for optional in ("marker_radius", "marker_emphasis"):
                if optional in series:
                    series_view[optional] = series[optional]
            chart_view["series"].append(series_view)
        projected["charts"].append(chart_view)
    validate_statistics_lab(projected, projected=True)
    return projected
