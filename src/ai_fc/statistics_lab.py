from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from bisect import bisect_left, bisect_right
from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ai_fc import fred_api
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
IPO_REFERENCE_CHART_IDS = (
    "internet_vs_ai_core_ipos",
    "technology_ipo_count",
    "technology_ipo_first_day_return",
    "technology_ipo_price_to_sales",
    "technology_ipo_profitable_share",
    "all_ipo_negative_earnings_share",
    "dotcom_internet_ipo_breadth",
)
Z1_ENDPOINT = "https://www.federalreserve.gov/releases/z1/current/z1_csv_files.zip"
SEC_IPO_ENDPOINT = "https://www.sec.gov/data-research/statistics-data-visualizations/initial-public-offerings-ipos"
ICI_ETF_ENDPOINT = "https://www.ici.org/research/stats/etf_flows"
NYU_RETURNS_ENDPOINT = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/histretSP.xlsx"
#: SEC는 자동 접근 클라이언트에 **연락처를 밝힌** User-Agent를 요구하고, 연락처가
#: 없으면 403을 돌려준다(실측 2026-08-31 — 이 워크플로가 8/22부터 멈춰 있던 원인).
#: 우회가 아니라 SEC가 문서로 지시한 준수 방법이다.  주소는 저장소 소유자가 지정했고
#: `ipo_edgar_watch`가 이미 같은 주소를 쓴다.  형제 모듈
#: (`ai_capital_cycle`·`segment_filing_inventory`)과 같은 환경변수로 교체할 수 있다.
SEC_CONTACT = "91ssjj@gmail.com"
DEFAULT_USER_AGENT = f"JinsInvestingStatisticsLab/1.0 ({SEC_CONTACT})"


def _user_agent() -> str:
    """연락처를 포함한 UA를 돌려준다.

    연락처 없는 값으로 덮어쓰면 SEC가 다시 403을 주므로, 환경변수로 교체하더라도
    `@`가 있어야 한다 — `official_sources.edgar_companyfacts_request`가 같은 불변식을
    이미 강제하고 있다.
    """
    agent = os.getenv("AI_FC_SEC_USER_AGENT", DEFAULT_USER_AGENT)
    if "@" not in agent:
        raise StatisticsLabError(
            "SEC 요청에는 연락처를 포함한 User-Agent가 필요합니다 "
            "(AI_FC_SEC_USER_AGENT에 연락 가능한 주소를 넣으세요)"
        )
    return agent

FRED_SERIES: dict[str, dict[str, str]] = {
    "M2SL": {
        "title": "M2 money stock",
        "provider": "Board of Governors of the Federal Reserve System (US)",
        "unit": "billions_usd",
        "native_frequency": "monthly",
        "aggregation": "last",
    },
    "MMMFFAQ027S": {
        "title": "Money market funds; total financial assets",
        "provider": "Board of Governors of the Federal Reserve System (US)",
        "unit": "millions_usd",
        "native_frequency": "quarterly_end_of_period",
        "aggregation": "last",
    },
    "CDCABSHNO": {
        "title": "Households and nonprofit organizations; checkable deposits and currency",
        "provider": "Board of Governors of the Federal Reserve System (US)",
        "unit": "millions_usd",
        "native_frequency": "quarterly_end_of_period",
        "aggregation": "last",
    },
    "TSDABSHNO": {
        "title": "Households and nonprofit organizations; time and savings deposits",
        "provider": "Board of Governors of the Federal Reserve System (US)",
        "unit": "millions_usd",
        "native_frequency": "quarterly_end_of_period",
        "aggregation": "last",
    },
    "FGDSLAQ027S": {
        "title": "Federal government; Treasury securities; liability level",
        "provider": "Board of Governors of the Federal Reserve System (US)",
        "unit": "millions_usd",
        "native_frequency": "quarterly_end_of_period",
        "aggregation": "last",
    },
    "BOGZ1FL153064235Q": {
        "title": "Households and nonprofit organizations; bond mutual fund shares",
        "provider": "Board of Governors of the Federal Reserve System (US)",
        "unit": "millions_usd",
        "native_frequency": "quarterly_end_of_period",
        "aggregation": "last",
    },
    "IQ12260": {
        "title": "Export price index: nonmonetary gold",
        "provider": "U.S. Bureau of Labor Statistics",
        "unit": "index_dec_2024_100",
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
    "SP500": {
        "title": "S&P 500 Index",
        "provider": "S&P Dow Jones Indices via Federal Reserve Bank of St. Louis",
        "unit": "index",
        "native_frequency": "daily_close",
        "aggregation": "last",
        "window_start": "2023-01-01",
    },
    "CBBTCUSD": {
        "title": "Coinbase Bitcoin U.S. dollar spot price",
        "provider": "Coinbase via Federal Reserve Bank of St. Louis",
        "unit": "dollars_per_bitcoin",
        "native_frequency": "daily_close",
        "aggregation": "last",
        "window_start": "2023-01-01",
    },
    "NASDAQSOX": {
        "title": "Nasdaq PHLX Semiconductor Index",
        "provider": "Nasdaq, Inc. via Federal Reserve Bank of St. Louis",
        "unit": "index",
        "native_frequency": "daily_close",
        "aggregation": "last",
        "window_start": "2020-01-01",
    },
    "SPASTT01KRM661N": {
        "title": "Korea share-price index",
        "provider": "OECD Main Economic Indicators via Federal Reserve Bank of St. Louis",
        "unit": "index_2015_100",
        "native_frequency": "monthly",
        "aggregation": "last",
        "window_start": "2020-01-01",
    },
    "HOUST": {
        "title": "Housing starts: total new privately owned housing units",
        "provider": "U.S. Census Bureau via Federal Reserve Bank of St. Louis",
        "unit": "thousands_saar",
        "native_frequency": "monthly",
        "aggregation": "last",
    },
    "GDP": {
        "title": "Gross domestic product",
        "provider": "U.S. Bureau of Economic Analysis via Federal Reserve Bank of St. Louis",
        "unit": "billions_usd_saar",
        "native_frequency": "quarterly",
        "aggregation": "last",
    },
    "Y034RC1Q027SBEA": {
        "title": "Private fixed investment: information processing equipment",
        "provider": "U.S. Bureau of Economic Analysis via Federal Reserve Bank of St. Louis",
        "unit": "billions_usd_saar",
        "native_frequency": "quarterly",
        "aggregation": "last",
    },
    "Y001RC1Q027SBEA": {
        "title": "Private fixed investment: intellectual property products",
        "provider": "U.S. Bureau of Economic Analysis via Federal Reserve Bank of St. Louis",
        "unit": "billions_usd_saar",
        "native_frequency": "quarterly",
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
        "window_start": "2023-01-01",
        "window_end_exclusive": "2027-01-01",
        "source_url": "https://finance.yahoo.com/quote/%5EGSPC/history/",
    },
    "GOLD_FUTURES_DAILY": {
        "symbol": "GC=F",
        "title": "COMEX gold futures front-month daily close",
        "provider": "Yahoo Finance chart API (underlying market: COMEX)",
        "unit": "dollars_per_troy_ounce",
        "native_frequency": "daily_close",
        "window_start": "2023-01-01",
        "window_end_exclusive": "2027-01-01",
        "source_url": "https://finance.yahoo.com/quote/GC%3DF/history/",
    },
    "BTCUSD_DAILY": {
        "symbol": "BTC-USD",
        "title": "Bitcoin U.S. dollar daily close",
        "provider": "Yahoo Finance chart API",
        "unit": "dollars_per_bitcoin",
        "native_frequency": "daily_close",
        "window_start": "2023-01-01",
        "window_end_exclusive": "2027-01-01",
        "source_url": "https://finance.yahoo.com/quote/BTC-USD/history/",
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
        request = urllib.request.Request(url, headers={"User-Agent": _user_agent()})
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


def _fetch_supplemental(
    series_id: str,
) -> tuple[list[dict[str, Any]], bytes] | tuple[list[dict[str, Any]], bytes, str]:
    if series_id == "SEC_IPO_QUARTERLY":
        import re

        page = _request(SEC_IPO_ENDPOINT, timeout=60).decode("utf-8", errors="replace")
        match = re.search(r'href="([^"]*sec-stats-ipos-\d+\.xlsx)"', page)
        if match is None:
            raise StatisticsLabError("SEC IPO statistics download link missing")
        download_url = urllib.parse.urljoin(SEC_IPO_ENDPOINT, match.group(1))
        raw = _request(download_url, timeout=60)
        return _parse_sec_ipo_xlsx(raw), raw, download_url
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
    # FRED 약관은 fredgraph.csv 같은 스크랩을 금지하고 API 경로만 허용한다
    # (DECISIONS 12-6).  observations_csv가 API JSON을 종전 CSV 모양으로
    # 렌더하므로 _parse_fred_csv는 그대로 둔다.  전송은 종전과 같은 감사된
    # curl 폴백을 재사용하며, 영수증에 남는 URL은 키가 없는 공개 URL이다.
    raw = fred_api.observations_csv(
        series_id, observation_start=start, timeout=45,
    ).encode("utf-8")
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


Z1_SERIES: dict[str, dict[str, str]] = {
    "FL663067003": {
        "member": "csv/F4_6_s.csv",
        "field": "FL663067003.Q",
        "title": "Household margin loans and other receivables due to brokers",
        "unit": "millions_usd",
        "proxy_warning": "not_FINRA_monthly_margin_debt",
    },
    "FL103163005": {
        "member": "csv/S11_1_s.csv",
        "field": "FL103163005.Q",
        "title": "Nonfinancial corporate business: debt securities outstanding",
        "unit": "millions_usd",
    },
    "FA103163005": {
        "member": "csv/S11_1_t.csv",
        "field": "FA103163005.Q",
        "title": "Nonfinancial corporate business: debt securities net issuance",
        "unit": "millions_usd_saar",
    },
}

Z1_PRIMARY_SERIES = "FL663067003"

CENSUS_C30_ENDPOINT = "https://www.census.gov/construction/c30/xls/privtime.xlsx"

# Value of private construction put in place, not seasonally adjusted.  The
# data-centre column starts in 2014 and therefore has no dot-com counterpart;
# it is collected for the ledger but is not drawn as a two-era chart line.
CENSUS_C30_SERIES: dict[str, dict[str, str]] = {
    "C30_MFG_COMPUTER_ELECTRONIC": {
        "column": "Computer/ electronic/ electrical",
        "title": "Private construction: computer, electronic and electrical manufacturing structures",
        "unit": "millions_usd",
    },
    "C30_POWER": {
        "column": "Power (inc. Gas and Oil)",
        "title": "Private construction: power structures",
        "unit": "millions_usd",
    },
    "C30_COMMUNICATION": {
        "column": "Communication",
        "title": "Private construction: communication structures",
        "unit": "millions_usd",
    },
    "C30_OFFICE_TOTAL": {
        "column": "Office",
        "title": "Private construction: office structures",
        "unit": "millions_usd",
    },
    "C30_OFFICE_DATA_CENTER": {
        "column": "Data center",
        "title": "Private construction: data centre structures",
        "unit": "millions_usd",
        "history_note": "series begins 2014-01; no dot-com era counterpart",
    },
}

CENSUS_C30_PRIMARY_SERIES = "C30_MFG_COMPUTER_ELECTRONIC"
CENSUS_C30_SHEET = "Private NSA"


def _c30_header_key(value: object) -> str:
    """Normalize a C30 header cell for exact matching.

    The workbook embeds carriage-return escapes and footnote digits in the
    header text, so raw equality would silently miss a column and hand back an
    empty series instead of failing.
    """
    text = "" if value is None else str(value)
    text = text.replace("_x000D_", " ").replace("\r", " ").replace("\n", " ")
    text = "".join(char for char in text if not char.isdigit())
    return " ".join(text.split()).strip().lower()


def _c30_month(value: object) -> str | None:
    """Parse a C30 period label such as ``Jun-26p`` into a first-of-month date."""
    text = "" if value is None else str(value).strip()
    match = re.fullmatch(r"([A-Za-z]{3})-(\d{2})([pr])?", text)
    if match is None:
        return None
    try:
        month = MONTH_ABBREVIATIONS.index(match.group(1).lower()) + 1
    except ValueError:
        return None
    year_part = int(match.group(2))
    year = 1900 + year_part if year_part >= 90 else 2000 + year_part
    return date(year, month, 1).isoformat()


MONTH_ABBREVIATIONS = [
    "jan", "feb", "mar", "apr", "may", "jun",
    "jul", "aug", "sep", "oct", "nov", "dec",
]


def _parse_census_c30(
    raw: bytes, series_id: str = CENSUS_C30_PRIMARY_SERIES,
) -> list[dict[str, Any]]:
    try:
        spec = CENSUS_C30_SERIES[series_id]
    except KeyError as exc:
        raise StatisticsLabError(f"unknown Census C30 series: {series_id}") from exc
    # The repository already reads XLSX with the standard library; reusing that
    # reader keeps the collector dependency-free and keeps the test fixtures
    # byte-compatible with the other workbook sources.
    grid = _xlsx_sheet_rows(raw, CENSUS_C30_SHEET)
    wanted = _c30_header_key(spec["column"])
    header_index = None
    column_index = None
    for row_index, row in enumerate(grid[:12]):
        keys = [_c30_header_key(cell) for cell in row]
        if "date" in keys and wanted in keys:
            header_index = row_index
            column_index = keys.index(wanted)
            break
    if header_index is None or column_index is None:
        raise StatisticsLabError(f"Census C30 column missing: {spec['column']}")
    rows: list[dict[str, Any]] = []
    for row in grid[header_index + 1:]:
        if not row:
            continue
        observed = _c30_month(row[0])
        if observed is None:
            continue
        if column_index >= len(row):
            continue
        value = row[column_index]
        if value in (None, "", "(NA)", "(S)", "(D)"):
            continue
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise StatisticsLabError(
                f"invalid Census C30 value for {series_id}: {observed}={value!r}"
            ) from exc
        if math.isfinite(parsed):
            rows.append({"date": observed, "value": parsed})
    if not rows:
        raise StatisticsLabError(f"Census C30 series {series_id} is empty")
    rows.sort(key=lambda item: item["date"])
    deduped: dict[str, dict[str, Any]] = {row["date"]: row for row in rows}
    return list(deduped.values())


def _parse_z1(raw: bytes, series_id: str = Z1_PRIMARY_SERIES) -> list[dict[str, Any]]:
    try:
        spec = Z1_SERIES[series_id]
    except KeyError as exc:
        raise StatisticsLabError(f"unknown Z.1 series: {series_id}") from exc
    member = spec["member"]
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        try:
            text = archive.read(member).decode("utf-8-sig")
        except KeyError as exc:
            raise StatisticsLabError(f"Z.1 {member} missing") from exc
    reader = csv.DictReader(io.StringIO(text))
    field = spec["field"]
    rows = []
    for row in reader:
        value = row.get(field)
        period = row.get("date", "")
        if not value or not period or ":Q" not in period:
            continue
        # "ND" is the Federal Reserve's documented no-data marker; skipping it is
        # not the same as tolerating a malformed number, which still fails closed.
        if value.strip() in {"ND", "NA"}:
            continue
        try:
            year_text, quarter_text = period.split(":Q", 1)
            month = (int(quarter_text) - 1) * 3 + 1
            parsed = float(value)
            observed = date(int(year_text), month, 1)
        except (TypeError, ValueError) as exc:
            raise StatisticsLabError(f"invalid Z.1 row for {field}: {period}={value!r}") from exc
        if observed >= date(1995, 1, 1) and math.isfinite(parsed):
            rows.append({"date": observed.isoformat(), "value": parsed})
    if not rows:
        raise StatisticsLabError(f"Z.1 {field} is empty")
    return rows


def _month_key(value: str) -> tuple[int, int]:
    observed = date.fromisoformat(value)
    return observed.year, observed.month


def _month_offset(value: str, start: date) -> int:
    observed = date.fromisoformat(value)
    return (observed.year - start.year) * 12 + observed.month - start.month


def _trailing_year_change(rows: list[dict[str, Any]]) -> float:
    """Return an actual-observation 12-month change without interpolation."""
    ordered = sorted(rows, key=lambda row: str(row["date"]))
    if len(ordered) < 2:
        raise StatisticsLabError("trailing-year change requires two observations")
    latest = date.fromisoformat(str(ordered[-1]["date"]))
    try:
        target = latest.replace(year=latest.year - 1)
    except ValueError:
        target = latest.replace(year=latest.year - 1, day=28)
    prior = next(
        (
            row for row in reversed(ordered[:-1])
            if date.fromisoformat(str(row["date"])) <= target
        ),
        None,
    )
    if prior is None:
        raise StatisticsLabError("trailing-year reference observation unavailable")
    current_value = float(ordered[-1]["value"])
    prior_value = float(prior["value"])
    if (
        not math.isfinite(current_value)
        or not math.isfinite(prior_value)
        or current_value <= 0
        or prior_value <= 0
    ):
        raise StatisticsLabError("trailing-year change requires positive finite values")
    return (current_value / prior_value - 1.0) * 100.0


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

    heat = next(
        (chart for chart in charts if chart.get("id") == "dotcom_internet_ipo_breadth"),
        None,
    )
    if heat is None or heat.get("chart_type") != "profile_cards":
        raise StatisticsLabError("IPO heat comparison profile missing")
    heat_metrics = [
        metric
        for group in heat.get("profile_groups") or []
        for metric in group.get("metrics") or []
    ]
    expected_heat = [
        ("IPO 건수", 60.0, 1.3),
        ("공모액", 40.0, 4.1),
        ("저매출 기업", 81.0, 66.7),
        ("신생 기업", 57.0, 33.3),
        ("첫날 평균 상승", 90.0, 18.6),
    ]
    if len(heat_metrics) != len(expected_heat):
        raise StatisticsLabError("IPO heat comparison must contain five metrics")
    for metric, (label, dotcom_value, current_value) in zip(
        heat_metrics, expected_heat, strict=True,
    ):
        rows = metric.get("comparisons") or []
        if (
            metric.get("label") != label
            or len(rows) != 2
            or [row.get("era") for row in rows] != ["dotcom", "current"]
            or [row.get("label") for row in rows]
            != ["1999 닷컴", "2025 AI 핵심 · n=3"]
            or not math.isclose(float(rows[0].get("value", math.nan)), dotcom_value)
            or not math.isclose(float(rows[1].get("value", math.nan)), current_value)
        ):
            raise StatisticsLabError(f"IPO heat comparison {label} invalid")
    heat_contract = heat.get("reference_contract") or {}
    cohort = heat_contract.get("current_cohort") or {}
    if (
        heat_contract.get("publication_class") != "reference_statistics"
        or heat_contract.get("official_numeric_ledger") is not False
        or cohort.get("n") != 3
        or float(cohort.get("proceeds_mn", 0)) != 1755.375
    ):
        raise StatisticsLabError("IPO heat reference contract invalid")


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


def _build_ipo_reference_statistics(
    ipo_reference: dict[str, Any], sec_rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Build separately governed IPO reference charts.

    Historical dot-com and technology-study rows retain their cited publication
    vintage.  Only the current-era rows are eligible for the weekly reviewed IPO
    batch.  The heat card's current count/proceeds denominators are additionally
    recalculated from the four SEC quarterly corporate-issuer observations.
    """
    validate_ipo_reference(ipo_reference)
    year = 2025
    annual_rows = {
        str(row.get("period_label")): row
        for row in sec_rows
        if str(row.get("period_label", "")).startswith(f"{year}:Q")
    }
    expected_periods = {f"{year}:Q{quarter}" for quarter in range(1, 5)}
    if set(annual_rows) != expected_periods:
        return None
    corporate_count = sum(
        float(annual_rows[period]["corporate_count"])
        for period in sorted(expected_periods)
    )
    corporate_proceeds_mn = sum(
        float(annual_rows[period]["corporate_proceeds_mn"])
        for period in sorted(expected_periods)
    )
    if corporate_count <= 0 or corporate_proceeds_mn <= 0:
        raise StatisticsLabError("SEC annual IPO denominator invalid")

    source_charts = {
        str(row.get("id")): row for row in ipo_reference["charts"]
    }
    missing_charts = [
        chart_id for chart_id in IPO_REFERENCE_CHART_IDS
        if chart_id not in source_charts
    ]
    if missing_charts:
        raise StatisticsLabError(
            f"IPO reference chart batch incomplete: {', '.join(missing_charts)}"
        )
    charts = [deepcopy(source_charts[chart_id]) for chart_id in IPO_REFERENCE_CHART_IDS]
    chart = next(
        row for row in ipo_reference["charts"]
        if row.get("id") == "dotcom_internet_ipo_breadth"
    )
    chart = next(row for row in charts if row["id"] == chart["id"])
    contract = chart["reference_contract"]
    cohort = contract["current_cohort"]
    cohort_count = float(cohort["n"])
    cohort_proceeds_mn = float(cohort["proceeds_mn"])
    count_share = round(cohort_count / corporate_count * 100.0, 1)
    proceeds_share = round(cohort_proceeds_mn / corporate_proceeds_mn * 100.0, 1)
    low_revenue_share = round(
        float(cohort["low_revenue_count"]) / cohort_count * 100.0, 1,
    )
    young_issuer_share = round(
        float(cohort["young_issuer_count"]) / cohort_count * 100.0, 1,
    )
    first_day_return = float(cohort["mean_first_day_return_percent"])
    current_values = [
        count_share, proceeds_share, low_revenue_share,
        young_issuer_share, first_day_return,
    ]
    metrics = [
        metric
        for group in chart["profile_groups"]
        for metric in group["metrics"]
    ]
    for metric, value in zip(metrics, current_values, strict=True):
        current = metric["comparisons"][1]
        current["value"] = value
        current["level"] = value
        current["display_value"] = (
            f"+{value:.1f}%" if metric["label"] == "첫날 평균 상승"
            else f"{value:.1f}%"
        )
    current_series = next(
        series for series in chart["series"] if series.get("era") == "current"
    )
    for point, value in zip(current_series["points"], current_values, strict=True):
        point["value"] = value
    contract["calculation_audit"].update({
        "ipo_share": (
            f"{cohort_count:.0f} / SEC {year} corporate IPO count "
            f"{corporate_count:.0f} = {count_share:.1f}%"
        ),
        "proceeds_share": (
            f"${cohort_proceeds_mn / 1000.0:.6f}bn / SEC {year} corporate proceeds "
            f"${corporate_proceeds_mn / 1000.0:.4f}bn = {proceeds_share:.1f}%"
        ),
    })
    contract["official_overlay"] = {
        "source_id": "SEC_IPO_QUARTERLY",
        "year": year,
        "quarter_count": 4,
        "corporate_count": int(corporate_count),
        "corporate_proceeds_mn": corporate_proceeds_mn,
        "refresh_mode": "weekly_official_ledger_projection",
    }
    chart["source_ids"] = [*chart["source_ids"], "SEC_IPO_QUARTERLY"]
    chart["research_context_source_ids"] = [
        "WILMERHALE_INTERNET_IPO_1999", "RITTER_IPO_UNDERPRICING_2025",
    ]
    chart["scope_note"] = "*미국 IPO 기준 · 참고 통계"
    chart["conclusion"] = (
        f"SEC 일반기업 IPO 기준 AI 핵심 비중은 건수 {count_share:.1f}%·공모액 "
        f"{proceeds_share:.1f}%로, IPO 폭은 1999년 인터넷 열기보다 낮습니다."
    )
    reference_conclusions = {
        "internet_vs_ai_core_ipos": (
            "IPO 수 기준 현재 AI 상장 붐은 닷컴 말기보다 훨씬 초기입니다. "
            "이 지표만으로 버블 붕괴가 임박했다고 보기는 어렵습니다."
        ),
        "technology_ipo_count": (
            "신규 기술기업 상장 공급은 닷컴 정점의 약 8% 수준이어서, "
            "IPO 폭만 보면 아직 말기 버블 단계와 거리가 있습니다."
        ),
        "technology_ipo_first_day_return": (
            "첫날 급등은 과열 신호지만 닷컴 정점의 절반 이하입니다. "
            "공모시장 전체가 극단적 열기에 들어갔다고 단정하기 어렵습니다."
        ),
        "technology_ipo_price_to_sales": (
            "신규 기술주의 가격 부담은 높지만 닷컴 정점보다 낮습니다. "
            "P/S 하나만으로 붕괴 직전이라고 판단할 수준은 아닙니다."
        ),
        "technology_ipo_profitable_share": (
            "현재 기술 IPO도 적자기업이 다수지만 닷컴 정점보다 이익 기반이 "
            "두꺼워 상장기업의 질은 상대적으로 낫습니다."
        ),
        "all_ipo_negative_earnings_share": (
            "적자 IPO가 절반을 넘는 점은 경계 신호지만, 닷컴 정점처럼 "
            "시장 전체가 적자 발행에 쏠린 상태는 아닙니다."
        ),
    }
    batch_contract = {
        "historical_era": "frozen_cited_publication_vintage",
        "current_era": "weekly_reviewed_batch",
        "current_only_update": True,
        "forecast_extension": False,
        "reviewed_through": ipo_reference["as_of"],
    }
    for reference_chart in charts:
        reference_chart["metric_source_ids"] = list(reference_chart["source_ids"])
        reference_chart["research_context_source_ids"] = list(
            reference_chart["source_ids"]
        )
        reference_chart["reference_batch"] = deepcopy(batch_contract)
        reference_chart.setdefault("scope_note", "*미국 IPO 기준 · 참고 통계")
        if reference_chart["id"] in reference_conclusions:
            reference_chart["conclusion"] = reference_conclusions[
                reference_chart["id"]
            ]
        reference_chart.setdefault("conclusion", reference_chart["insight"])

    used_source_ids = {
        source_id
        for reference_chart in charts
        for source_id in reference_chart["source_ids"]
        if source_id != "SEC_IPO_QUARTERLY"
    }
    source_rows = [
        {
            key: source[key]
            for key in (
                "series_id", "title", "provider", "native_frequency",
                "latest_observation", "authority_class", "usage_role", "update_mode",
            )
            if key in source
        }
        for source in ipo_reference["sources"]
        if source.get("series_id") in used_source_ids
    ]
    source_rows.append({
        "series_id": "SEC_IPO_QUARTERLY",
        "title": "U.S. IPO counts and proceeds by issuer type",
        "provider": "U.S. Securities and Exchange Commission",
        "native_frequency": "quarterly",
        "latest_observation": max(str(row["date"]) for row in sec_rows),
        "authority_class": "official_regulator",
        "usage_role": "refreshable_current_denominator",
        "update_mode": "weekly_official_ledger_projection",
    })
    result = {
        "schema_version": 1,
        "dataset_id": "ipo_reference_statistics_v1",
        "status": "ok",
        "label": "참고 통계",
        "probability_space": "reference_only",
        "model_use": False,
        "official_forecast_input": False,
        "official_numeric_ledger": False,
        "as_of": ipo_reference["as_of"],
        "placement": "below_authoritative_statistics",
        "charts": charts,
        "sources": source_rows,
        "update_contract": deepcopy(ipo_reference["reference_publication_contract"]),
        "batch_refresh": {
            **batch_contract,
            "chart_ids": list(IPO_REFERENCE_CHART_IDS),
            "official_denominator_through": max(str(row["date"]) for row in sec_rows),
            "academic_source_watch": "hash_checked_weekly_review_before_current_row_update",
        },
    }
    _validate_ipo_reference_statistics(result)
    return result


def _validate_ipo_reference_statistics(
    payload: dict[str, Any], *, allow_legacy_single: bool = False,
) -> None:
    if (
        payload.get("schema_version") != 1
        or payload.get("status") != "ok"
        or payload.get("probability_space") != "reference_only"
        or payload.get("model_use") is not False
        or payload.get("official_forecast_input") is not False
        or payload.get("official_numeric_ledger") is not False
        or payload.get("placement") != "below_authoritative_statistics"
    ):
        raise StatisticsLabError("IPO reference statistics boundary invalid")
    charts = payload.get("charts") or []
    chart_ids = [chart.get("id") for chart in charts]
    legacy_single = chart_ids == ["dotcom_internet_ipo_breadth"]
    if chart_ids != list(IPO_REFERENCE_CHART_IDS) and not (
        allow_legacy_single and legacy_single
    ):
        raise StatisticsLabError("IPO reference statistics chart selection invalid")
    chart = charts[-1]
    metrics = [
        metric
        for group in chart.get("profile_groups") or []
        for metric in group.get("metrics") or []
    ]
    if len(metrics) != 5 or any(
        len(metric.get("comparisons") or []) != 2 for metric in metrics
    ):
        raise StatisticsLabError("IPO reference statistics comparison bars invalid")
    if any(
        [row.get("era") for row in metric["comparisons"]]
        != ["dotcom", "current"]
        for metric in metrics
    ):
        raise StatisticsLabError("IPO reference statistics comparison order invalid")
    source_ids = {str(source.get("series_id")) for source in payload.get("sources") or []}
    for reference_chart in charts:
        if (
            str(reference_chart.get("insight", "")).strip()
            == str(reference_chart.get("conclusion", "")).strip()
        ):
            raise StatisticsLabError(
                "IPO reference insight and current conclusion must be distinct"
            )
        if not set(reference_chart.get("source_ids") or []).issubset(source_ids):
            raise StatisticsLabError("IPO reference statistics source registry invalid")
        if legacy_single:
            continue
        batch = reference_chart.get("reference_batch") or {}
        if (
            batch.get("historical_era") != "frozen_cited_publication_vintage"
            or batch.get("current_era") != "weekly_reviewed_batch"
            or batch.get("current_only_update") is not True
            or batch.get("forecast_extension") is not False
        ):
            raise StatisticsLabError("IPO reference statistics batch boundary invalid")
        eras = {
            str(series.get("era"))
            for series in reference_chart.get("series") or []
        }
        if eras != {"dotcom", "current"}:
            raise StatisticsLabError("IPO reference chart must compare dotcom and current eras")
    if not legacy_single:
        batch_refresh = payload.get("batch_refresh") or {}
        if (
            batch_refresh.get("chart_ids") != list(IPO_REFERENCE_CHART_IDS)
            or batch_refresh.get("current_only_update") is not True
            or batch_refresh.get("historical_era") != "frozen_cited_publication_vintage"
        ):
            raise StatisticsLabError("IPO reference batch manifest invalid")
    if any("source_url" in source or "request_url" in source for source in payload["sources"]):
        raise StatisticsLabError("IPO reference statistics projection exposes process URLs")


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


def _build_statistics_lab_legacy(
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
    dot_equities, cur_equities = _cycle_series(
        monthly["BOGZ1LM893064105Q"], comparison_months, indexed=True,
    )
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
    kospi_20d = _session_log_return_points(source_rows["KOSPI_DAILY"], year=2026)
    taiex_20d = _session_log_return_points(source_rows["TAIEX_DAILY"], year=2026)
    sox_prior_20d = _prior_close_log_return_points(
        source_rows["KOSPI_DAILY"], source_rows["SOX_DAILY"], year=2026,
    )
    taiex_aligned = _aligned_log_returns(
        source_rows["KOSPI_DAILY"], source_rows["TAIEX_DAILY"],
        candidate_close="same_or_prior",
    )
    sox_aligned = _aligned_log_returns(
        source_rows["KOSPI_DAILY"], source_rows["SOX_DAILY"],
        candidate_close="strictly_prior",
    )
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

    latest_m2_bn = float(monthly["M2SL"][-1]["value"])
    latest_mmf_bn = float(monthly["MMMFFAQ027S"][-1]["value"]) / 1000.0
    latest_equity_bn = float(monthly["BOGZ1LM893064105Q"][-1]["value"]) / 1000.0
    if min(latest_m2_bn, latest_mmf_bn, latest_equity_bn) <= 0:
        raise StatisticsLabError("liquidity scale map requires positive balances")
    equity_to_m2 = latest_equity_bn / latest_m2_bn * 100.0
    mmf_to_m2 = latest_mmf_bn / latest_m2_bn * 100.0
    liquidity_changes = {
        "S&P 500": _trailing_year_change(source_rows["SP500_DAILY"]),
        "금 선물": _trailing_year_change(source_rows["GOLD_FUTURES_DAILY"]),
        "비트코인": _trailing_year_change(source_rows["BTCUSD_DAILY"]),
        "미국 M2": _trailing_year_change(monthly["M2SL"]),
        "미국 MMF": _trailing_year_change(monthly["MMMFFAQ027S"]),
    }
    liquidity_point_dates = {
        "S&P 500": source_rows["SP500_DAILY"][-1]["date"],
        "금 선물": source_rows["GOLD_FUTURES_DAILY"][-1]["date"],
        "비트코인": source_rows["BTCUSD_DAILY"][-1]["date"],
        "미국 M2": monthly["M2SL"][-1]["date"],
        "미국 MMF": monthly["MMMFFAQ027S"][-1]["date"],
    }

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
        _chart(
            "liquidity_position_map", "자금 지도: 현재 규모와 12개월 방향", "liquidity", "percent",
            "미국 기업주식·M2·MMF의 상대 규모와 S&P 500·금·비트코인·M2·MMF의 최근 12개월 변화를 서로 다른 패널로 봅니다.",
            "M2와 MMF는 일부 중복되고, 시가·지수 상승은 같은 금액의 순유입을 뜻하지 않습니다. 따라서 하나의 시장점유율 파이로 합산하지 않습니다.",
            [_series(
                "12개월 변화", "current",
                [
                    {
                        "period": index,
                        "date": liquidity_point_dates[label],
                        "value": value,
                    }
                    for index, (label, value) in enumerate(liquidity_changes.items())
                ],
                "#28756a",
            )],
            [
                "BOGZ1LM893064105Q", "M2SL", "MMMFFAQ027S",
                "SP500_DAILY", "GOLD_FUTURES_DAILY", "BTCUSD_DAILY",
            ],
        ),
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
        _chart("margin_credit_proxy", "브로커 고객 신용과 미국 기업주식 시장가치", "credit", "cycle_start_100",
               "Fed Z.1의 브로커 고객 마진대출·기타 미수금과 미국 기업주식 시장가치를 각각 사이클 시작=100으로 비교합니다.",
               "FINRA 월별 margin debt나 S&P 500 지수가 아닌 연준 분기별 광의 대용치입니다. 최신 Z.1 릴리스는 과거값을 수정할 수 있습니다.",
               [_series("닷컴 고객 신용", "dotcom", dot_margin, "#c70039"), _series("닷컴 기업주식", "dotcom", dot_equities, "#7b6b55"), _series("현재 고객 신용", "current", cur_margin, "#ff7b00"), _series("현재 기업주식", "current", cur_equities, "#28756a")], ["FL663067003", "BOGZ1LM893064105Q"]),
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
        _chart("kospi_external_semiconductor_pulse", "한국장과 글로벌 반도체 20일 충격", "economy", "percent_20d_log_return",
               "KOSPI와 대만 TAIEX의 실제 20거래일 로그수익률, 한국장 당일에는 이미 알려진 전일 미국 SOX 종가의 20거래일 로그수익률을 함께 봅니다.",
               "SOX는 한국 날짜보다 엄격히 이전인 미국 종가만 사용합니다. 상관과 조건부 빈도는 동행 진단이며 인과관계·확정 확률·매매 신호가 아닙니다.",
               [_series("KOSPI 20일", "current", kospi_20d, "#11110f"), _series("대만 TAIEX 20일", "current", taiex_20d, "#28756a"), _series("전일 SOX 20일", "current", sox_prior_20d, "#e05d26")], ["KOSPI_DAILY", "TAIEX_DAILY", "SOX_DAILY"]),
    ]

    liquidity_chart = next(chart for chart in charts if chart["id"] == "liquidity_position_map")
    liquidity_chart.update({
        "chart_type": "liquidity_bars",
        "display_unit": "현재 규모 + 12개월 증감",
        "reading_guide": "왼쪽은 현재 잔액·시장가치, 오른쪽은 각 지표의 실제 최근 12개월 증감입니다.",
        "liquidity_panels": [
            {
                "id": "current_scale",
                "title": "현재 규모",
                "basis": "조 달러 · 서로 합산하지 않음",
                "mode": "positive",
                "metrics": [
                    {
                        "label": "미국 기업주식 시장가치",
                        "value": latest_equity_bn / 1000.0,
                        "display_value": f"${latest_equity_bn / 1000.0:.1f}T",
                    },
                    {
                        "label": "미국 M2",
                        "value": latest_m2_bn / 1000.0,
                        "display_value": f"${latest_m2_bn / 1000.0:.1f}T",
                    },
                    {
                        "label": "미국 MMF 총자산",
                        "value": latest_mmf_bn / 1000.0,
                        "display_value": f"${latest_mmf_bn / 1000.0:.1f}T",
                    },
                ],
            },
            {
                "id": "trailing_change",
                "title": "최근 12개월 방향",
                "basis": "가격·잔액 증감률",
                "mode": "diverging",
                "metrics": [
                    {
                        "label": label,
                        "value": value,
                        "display_value": f"{value:+.1f}%",
                    }
                    for label, value in liquidity_changes.items()
                ],
            },
        ],
    })
    pulse_chart = charts[-1]
    pulse_chart["axis_type"] = "calendar_day_of_year"
    pulse_chart["max_period"] = 364
    pulse_chart["projection_max_points"] = 366
    pulse_chart["observed_end_label"] = "마지막 완료 거래일"
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
            "sec_ipo_issuer_mix_h1", "미국 IPO 건수: 일반 기업과 SPAC", "ipo", "count",
            "SEC의 같은 상반기 기준 전체 IPO 건수를 일반 기업, SPAC, 펀드로 나눈 누적 막대입니다.",
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
            "household_balance_sheet_trend_gap", "가계 주식·현금·채권의 추세 이탈", "credit",
            "percent_vs_trend",
            "2009~2019 관측치에 항목별 선형추세를 따로 적합해 실제 잔액이 추세보다 얼마나 위·아래인지 비교합니다.",
            "주식·현금은 분기, 보유채권은 연간 관측치입니다. 가계에는 비영리단체가 포함되며 선형추세는 구조적 적정수준이 아닙니다.",
            [
                _series("주식", "current", equity_gap, "#11110f"),
                _series("현금성 자산", "current", cash_gap, "#b58b2a"),
                _series("채권", "current", debt_gap, "#28756a"),
            ],
            ["BOGZ1LM153064475Q", "DABSHNO", "BOGZ1FL154022375A"],
        ),
    ]
    sec_chart, annual_chart, household_chart = (
        supplemental_charts
    )
    for chart in (annual_chart,):
        chart["chart_type"] = "grouped_bar"
    sec_chart.update({
        "axis_type": "categorical", "chart_type": "stacked_bar",
        "display_unit": "IPO 건수 · 상반기",
        "reading_guide": "막대 한 개가 해당 상반기의 미국 전체 IPO입니다. 색 구간은 일반 기업·SPAC·펀드 건수이며 AI 기업만의 통계가 아닙니다.",
        "show_bar_values": True,
        "max_period": 1, "x_ticks": sec_ticks,
    })
    annual_chart.update({
        "axis_type": "categorical", "max_period": len(annual_event_ticks) - 1,
        "x_ticks": annual_event_ticks,
    })
    household_chart.update({
        "axis_type": "calendar_quarter", "max_period": max(int(row["period"]) for row in equity_gap),
        "display_unit": "2009~2019 추세 대비",
        "reading_guide": "0%는 2009~2019 선형추세와 같은 수준입니다. 주식·현금은 분기 44개, 보유채권은 연간 11개 관측치로 추세를 각각 따로 계산했습니다.",
        "trend_baseline": {
            "start": "2009-01-01", "end": "2019-12-31",
            "method": "ordinary_least_squares_on_levels",
            "training_observations": {
                "corporate_equities": 44,
                "cash_and_deposits": 44,
                "debt_securities": 11,
            },
        },
        "x_ticks": [[0, "2009"], [16, "2013"], [32, "2017"], [48, "2021"], [64, "2025"]],
    })
    next(chart for chart in charts if chart["id"] == "m2_nasdaq").update({
        "scale": "log1p", "display_unit": "시작=100 · 로그축",
    })
    charts.extend(supplemental_charts)

    def chart_last(chart_id: str, series_index: int) -> float:
        chart = next(row for row in charts if row["id"] == chart_id)
        return float(chart["series"][series_index]["points"][-1]["value"])

    household_cash_current = cur_household_cash[-1]
    household_cash_dotcom_same_period = next(
        point for point in reversed(dot_household_cash)
        if int(point["period"]) <= int(household_cash_current["period"])
    )

    chart_insights = {
        "m2_nasdaq": (
            f"같은 경과월에 현재 NASDAQ은 시작 대비 {chart_last('m2_nasdaq', 2):.0f}, M2는 {chart_last('m2_nasdaq', 3):.0f}입니다. "
            f"닷컴 당시 NASDAQ {chart_last('m2_nasdaq', 0):.0f}, M2 {chart_last('m2_nasdaq', 1):.0f}와 비교해 주가가 유동성보다 얼마나 앞섰는지 봅니다."
        ),
        "nasdaq_per_m2": (
            f"현재 유동성 대비 NASDAQ 지수는 {chart_last('nasdaq_per_m2', 1):.0f}, 닷컴 당시 같은 구간은 {chart_last('nasdaq_per_m2', 0):.0f}입니다. "
            "100보다 높을수록 통화량 증가보다 주가 상승이 더 빨랐다는 뜻입니다."
        ),
        "nasdaq_per_household_liquid_assets": (
            f"현재 가계 현금성 자산 대비 NASDAQ 지수는 {float(household_cash_current['value']):.0f}, "
            f"같은 경과월의 닷컴 지수는 {float(household_cash_dotcom_same_period['value']):.0f}입니다. "
            "100보다 높을수록 실제 가계 현금·예금·MMF 증가보다 주가 상승이 더 빨랐다는 뜻입니다."
        ),
        "liquidity_position_map": (
            f"미국 기업주식 시장가치는 M2의 {equity_to_m2 / 100.0:.1f}배, MMF 총자산은 M2의 {mmf_to_m2:.0f}%입니다. "
            f"최근 12개월 변화가 가장 큰 항목은 {max(liquidity_changes, key=liquidity_changes.get)} "
            f"{max(liquidity_changes.values()):+.1f}%로, 규모와 최근 방향을 분리해 봐야 합니다."
        ),
        "yield_curve": (
            f"현재 장단기 금리차는 {chart_last('yield_curve', 1):+.1f}%p, 닷컴 당시 같은 구간은 {chart_last('yield_curve', 0):+.1f}%p입니다. "
            "0 아래는 금리 역전, 0 위는 정상 기울기이며 경기 방향을 단독으로 확정하지는 않습니다."
        ),
        "policy_rate": (
            f"현재 정책금리는 {chart_last('policy_rate', 1):.1f}%, 닷컴 당시 같은 구간은 {chart_last('policy_rate', 0):.1f}%입니다. "
            "1995~1999 실측은 6.05% 고점에서 4.63%까지 내린 뒤 5.42%로 재상승해 계단처럼 보이지만 완전한 사각형은 아닙니다."
        ),
        "valuation_proxy": (
            f"현재 기업가치/세후이익 대용치는 {chart_last('valuation_proxy', 1):.1f}배, 닷컴 당시 같은 구간은 {chart_last('valuation_proxy', 0):.1f}배입니다. "
            "높을수록 이익에 비해 시장가치가 비싸다는 뜻이지만 NASDAQ 공식 PER은 아닙니다."
        ),
        "margin_credit_proxy": (
            f"현재 브로커 고객 신용 대용치는 시작 대비 {chart_last('margin_credit_proxy', 2):.0f}, 미국 기업주식은 {chart_last('margin_credit_proxy', 3):.0f}입니다. "
            f"닷컴 같은 구간은 각각 {chart_last('margin_credit_proxy', 0):.0f}, {chart_last('margin_credit_proxy', 1):.0f}였습니다."
        ),
        "consumer_credit_growth": (
            f"현재 소비자신용 증가율은 {chart_last('consumer_credit_growth', 1):+.1f}%, 닷컴 당시 같은 구간은 {chart_last('consumer_credit_growth', 0):+.1f}%입니다. "
            "빠른 증가는 소비를 지지할 수 있지만 동시에 가계 부채 부담도 키웁니다."
        ),
        "loan_standards": (
            f"현재 대출기준 강화 응답은 {chart_last('loan_standards', 1):+.1f}%, 닷컴 당시 같은 구간은 {chart_last('loan_standards', 0):+.1f}%입니다. "
            "양수와 상승은 더 많은 은행이 대출을 조인다는 뜻이고, 음수는 완화 쪽입니다."
        ),
        "profit_growth": (
            f"현재 세후 기업이익 증가율은 {chart_last('profit_growth', 1):+.1f}%, 닷컴 당시 같은 구간은 {chart_last('profit_growth', 0):+.1f}%입니다. "
            "이익이 늘면 밸류에이션을 지지하지만 주가가 이익보다 빨리 오르면 부담은 다시 커집니다."
        ),
        "household_debt_service": (
            f"현재 가계 원리금 부담은 가처분소득의 {chart_last('household_debt_service', 1):.1f}%, 닷컴 당시 같은 구간은 {chart_last('household_debt_service', 0):.1f}%입니다. "
            "높을수록 금리와 부채가 소비 여력을 더 많이 잠식한다는 뜻입니다."
        ),
        "unemployment_rate": (
            f"현재 실업률은 {chart_last('unemployment_rate', 1):.1f}%, 닷컴 당시 같은 구간은 {chart_last('unemployment_rate', 0):.1f}%입니다. "
            "상승하면 고용 냉각 신호지만 금리 인하 기대와 성장 둔화를 함께 봐야 합니다."
        ),
        "inflation_rate": (
            f"현재 CPI 상승률은 {chart_last('inflation_rate', 1):+.1f}%, 닷컴 당시 같은 구간은 {chart_last('inflation_rate', 0):+.1f}%입니다. "
            "낮아지면 금리 부담 완화 여지가 커지지만 수요 둔화가 원인인지도 확인해야 합니다."
        ),
        "financial_conditions": (
            f"현재 NFCI는 {chart_last('financial_conditions', 1):+.2f}, 닷컴 당시 같은 구간은 {chart_last('financial_conditions', 0):+.2f}입니다. "
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
        "kospi_external_semiconductor_pulse": (
            f"2020년 이후 20거래일 수익률 상관은 KOSPI–TAIEX "
            f"{external_pulse_diagnostics['taiex_same_or_prior_close']['rolling_20_session_correlation']:+.2f}, "
            f"KOSPI–전일 SOX {external_pulse_diagnostics['sox_strictly_prior_us_close']['rolling_20_session_correlation']:+.2f}입니다. "
            "세 선이 함께 약해지면 글로벌 반도체 사이클 둔화, KOSPI만 약하면 한국 고유 위험을 우선 확인합니다."
        ),
        "sec_ipo_issuer_mix_h1": (
            f"2026년 상반기는 일반 기업 {int(sum(row['value'] for row in sec_corporate[1:]))}건, "
            f"SPAC {int(sum(row['value'] for row in sec_spac[1:]))}건, 펀드 {int(sum(row['value'] for row in sec_fund[1:]))}건입니다. 총 공모액은 ${sec_2025_proceeds:.1f}B에서 "
            f"${sec_2026_proceeds:.1f}B로 늘었고, 이 중 일반 기업이 ${sec_2026_corporate_proceeds:.1f}B입니다. 건수와 조달액을 혼동하지 않아야 합니다."
        ),
        "sp500_after_two_twenty_percent_years": (
            f"역사상 {len(third_year)}개 중첩 사례에서 3년 차 평균은 {statistics.mean(row['value'] for row in third_year):+.1f}%, "
            f"중앙값은 {statistics.median(row['value'] for row in third_year):+.1f}%였습니다. 연속 강세 뒤에도 결과 폭이 커서 평균만으로 다음 해를 단정할 수 없습니다."
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
                "profile_groups",
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
                "대형 AI 상장 가정(실제 IPO 아님)", "scenario",
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
            "OpenAI와 Anthropic의 최근 비상장 평가액 합계 $1.817T와 보도된 $3.0T 상장가치 가정은 모두 완료된 IPO가 아닙니다. "
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

    chart_by_id = {str(chart["id"]): chart for chart in charts}
    scope_notes = {
        "internet_vs_ai_core_ipos": "*미국 상장 IPO 기준 · 한국 ADS 별도 포함",
        "technology_ipo_count": "*미국 IPO 기준",
        "technology_ipo_first_day_return": "*미국 IPO 기준",
        "technology_ipo_price_to_sales": "*미국 IPO 기준",
        "technology_ipo_profitable_share": "*미국 IPO 기준",
        "all_ipo_negative_earnings_share": "*미국 IPO 기준",
        "dotcom_internet_ipo_breadth": "*1999년 미국 IPO 기준",
        "ipo_market_absorption": "*미국 IPO·기업주식 기준 · 해외 사례 별도",
        "small_issuer_ipo_share": "*미국 IPO 기준",
        "m2_nasdaq": "*미국 통화·NASDAQ 기준",
        "nasdaq_per_m2": "*미국 통화·NASDAQ 기준",
        "nasdaq_per_household_liquid_assets": "*미국 가계·비영리 자산·NASDAQ 기준",
        "liquidity_position_map": "*미국 자금 기준 · 금·비트코인은 달러 시세",
        "yield_curve": "*미국 국채 기준",
        "policy_rate": "*미국 기준",
        "valuation_proxy": "*미국 기업 기준",
        "margin_credit_proxy": "*미국 가계·기업주식 기준",
        "consumer_credit_growth": "*미국 소비자신용 기준",
        "loan_standards": "*미국 기업대출 기준",
        "profit_growth": "*미국 기업 기준",
        "household_debt_service": "*미국 가계 기준",
        "unemployment_rate": "*미국 기준",
        "inflation_rate": "*미국 기준",
        "financial_conditions": "*미국 금융시장 기준",
        "rate_cycle_since_first_cut": "*미국 기준",
        "corporate_bond_pressure": "*미국 회사채·국채 기준",
        "inflation_lead_panel": "*미국 물가·WTI·구리 대용치 기준",
        "kospi_external_semiconductor_pulse": "*한국·대만·미국 시장 기준",
        "housing_manufacturing_warning": "*미국 기준 · 제조업은 필라델피아 권역",
        "sec_ipo_issuer_mix_h1": "*미국 IPO 시장 기준",
        "sp500_after_two_twenty_percent_years": "*미국 S&P 500 기준",
        "household_balance_sheet_trend_gap": "*미국 가계·비영리 자산 기준",
    }
    missing_scope_notes = set(chart_by_id) - set(scope_notes)
    if missing_scope_notes:
        raise StatisticsLabError(
            f"statistics scope notes missing: {sorted(missing_scope_notes)}"
        )
    for chart_id, chart in chart_by_id.items():
        chart["scope_note"] = scope_notes[chart_id]

    def latest_value(chart_id: str, series_index: int = -1) -> float:
        series = chart_by_id[chart_id]["series"][series_index]
        return float(series["points"][-1]["value"])

    curve_now = latest_value("yield_curve")
    standards_now = latest_value("loan_standards")
    inflation_now = latest_value("inflation_rate")
    conditions_now = latest_value("financial_conditions")
    hmi_now = latest_value("housing_manufacturing_warning", 2)
    manufacturing_now = latest_value("housing_manufacturing_warning", 3)
    semiconductor_pulse = [
        latest_value("kospi_external_semiconductor_pulse", index)
        for index in range(3)
    ]
    oil_now = latest_value("inflation_lead_panel", 4)
    copper_now = latest_value("inflation_lead_panel", 5)
    conclusions = {
        "internet_vs_ai_core_ipos": "IPO 수만 보면 현재 AI 상장 붐은 닷컴 말기보다 훨씬 초기여서, 이 지표만으로 버블 붕괴가 임박했다고 보기는 어렵습니다.",
        "technology_ipo_count": "신규 기술기업 상장 공급은 닷컴 정점의 약 8% 수준이므로, IPO 폭만 놓고 보면 말기 버블 단계와 거리가 있습니다.",
        "technology_ipo_first_day_return": "첫날 급등은 과열 신호지만 닷컴 정점의 절반 이하라, 공모시장 전체가 극단적 열기에 들어갔다고 단정하기 어렵습니다.",
        "technology_ipo_price_to_sales": "신규 기술주의 가격 부담은 높지만 닷컴 정점보다 낮아, P/S 하나만으로 붕괴 직전이라고 판단할 수준은 아닙니다.",
        "technology_ipo_profitable_share": "현재 기술 IPO도 적자기업이 다수지만 닷컴 정점보다 이익 기반이 두꺼워 기업 질은 상대적으로 낫습니다.",
        "all_ipo_negative_earnings_share": "적자 IPO가 절반을 넘는 점은 경계 신호지만, 닷컴 정점처럼 시장 전체가 적자 발행에 쏠린 상태는 아닙니다.",
        "dotcom_internet_ipo_breadth": "이 장표는 1999년의 역사적 과열 기준선이며, 현재 AI 시장의 붕괴 확률을 직접 계산하지 않습니다.",
        "ipo_market_absorption": "대형 AI IPO가 실제 실행되면 시장 흡수 부담이 클 수 있지만, 현재 평가액 헤드라인만으로 상장 시점이나 충격을 확정할 수 없습니다.",
        "small_issuer_ipo_share": "저매출 상장 확산은 닷컴 말기보다 제한적이어서, IPO 저변 기준으로는 아직 전면적 말기 과열로 보기 어렵습니다.",
        "m2_nasdaq": "NASDAQ이 유동성보다 빠르게 올랐지만 닷컴 당시 격차보다 작아, M2 기준으로는 말기 과열 신호가 덜 강합니다.",
        "nasdaq_per_m2": "M2 대비 NASDAQ 상승 속도는 닷컴 같은 시점보다 낮아, 통화량 하나로는 현재를 닷컴 정점과 같은 단계로 보기 어렵습니다.",
        "nasdaq_per_household_liquid_assets": "가계 현금성 자산 대비 NASDAQ은 닷컴 같은 시점과 비슷해, 가계 유동성 완충력만으로 주가 부담이 낮다고 보기는 어렵습니다.",
        "liquidity_position_map": (
            f"대기자금은 MMF에 M2의 {mmf_to_m2:.0f}% 규모로 쌓여 있지만, 최근 가격·잔액 변화만으로 금·비트코인·주식 중 실제 순유입 승자를 단정할 수는 없습니다."
        ),
        "yield_curve": (
            "장단기 금리차가 아직 역전돼 있어 경기 경계가 남아 있습니다."
            if curve_now < 0 else
            "장단기 금리차는 정상화됐지만, 역전 해소만으로 경기 둔화 위험이 사라졌다고 볼 수는 없습니다."
        ),
        "policy_rate": "현재는 금리 인하가 진행된 경로로, 닷컴 붕괴 전 재긴축 국면과 같은 정책 트리거는 아직 확인되지 않습니다.",
        "valuation_proxy": "시장가치의 이익 대비 부담은 높지만 닷컴 같은 시점보다 낮아, 광의 밸류에이션은 극단적 정점 아래입니다.",
        "margin_credit_proxy": "브로커 고객 신용이 기업주식 시장가치보다 더 빠르게 늘어날 때 레버리지 경고가 커지며, 현재는 두 속도를 함께 확인해야 합니다.",
        "consumer_credit_growth": "소비자신용 증가율이 닷컴 당시보다 낮아, 현재 상승장이 가계 신용 팽창에 크게 의존한다고 보기는 어렵습니다.",
        "loan_standards": (
            "은행 대출기준이 순강화 상태여서 기업 신용 경로는 경계가 필요합니다."
            if standards_now > 5 else
            "은행 대출기준은 대체로 중립이어서, 현재 기업 신용 경색 신호는 강하지 않습니다."
        ),
        "profit_growth": "기업이익 증가가 주가를 지지하고 있어, 현재 밸류에이션 상승에는 닷컴 말기보다 강한 이익 기반이 있습니다.",
        "household_debt_service": "가계 상환 부담은 닷컴 같은 시점과 비슷하지만 역사적 극단은 아니어서, 소비 붕괴를 단독으로 예고하지 않습니다.",
        "unemployment_rate": "실업률은 고용 냉각을 살필 구간이지만, 현재 수준만으로 침체나 시장 붕괴가 확인됐다고 보기는 어렵습니다.",
        "inflation_rate": (
            "물가가 3%를 웃돌아 추가 금리 완화의 제약이 남아 있습니다."
            if inflation_now >= 3 else
            "물가 압력은 완화됐지만 성장 둔화 여부를 함께 확인해야 합니다."
        ),
        "financial_conditions": (
            "금융여건은 평균보다 완화적이어서 위험자산을 지지하지만, 동시에 과열이 더 이어질 여지도 남깁니다."
            if conditions_now < 0 else
            "금융여건이 평균보다 긴축적이어서 위험자산의 자금 조달 부담이 커진 상태입니다."
        ),
        "rate_cycle_since_first_cut": "첫 인하 이후 정책금리가 출발점 아래에 있어, 1990년대 말의 재긴축 복귀 신호는 아직 작동하지 않았습니다.",
        "corporate_bond_pressure": "회사채 절대금리는 높지만 국채 대비 스프레드는 아직 억제돼 있어, 전면적 신용 스트레스보다는 높은 할인율 부담이 핵심입니다.",
        "inflation_lead_panel": (
            "유가와 구리가 함께 상승해 향후 CPI 재가속 위험을 무시하기 어렵습니다."
            if oil_now > 0 and copper_now > 0 else
            "유가와 구리 신호가 엇갈려 원자재발 물가 재가속 신호는 아직 일관되지 않습니다."
        ),
        "kospi_external_semiconductor_pulse": (
            "세 시장의 20일 흐름이 모두 양수여서 글로벌 반도체 공동 급락 경고는 현재 작동하지 않습니다."
            if all(value > 0 for value in semiconductor_pulse) else
            "한국·대만·미국 반도체 20일 흐름이 함께 약해져 글로벌 반도체 조정 경고를 우선 확인해야 합니다."
        ),
        "housing_manufacturing_warning": (
            "주택 심리는 약하지만 제조업은 확장 신호여서, 현재 경기침체 신호는 혼합 상태입니다."
            if hmi_now < 0 < manufacturing_now else
            "주택과 제조업 신호가 같은 방향으로 약해져 경기 둔화 경계가 커졌습니다."
        ),
        "sec_ipo_issuer_mix_h1": "SPAC 건수가 일반 기업을 웃돌아 IPO 창구는 열렸지만, 이것을 실물기업·AI기업 상장 확산으로 곧바로 해석하면 안 됩니다.",
        "sp500_after_two_twenty_percent_years": "역사적으로 3년 차 상승이 더 많았지만 표본이 작아, 연속 강세만으로 다음 해 상승이나 버블 지속을 확정할 수 없습니다.",
        "household_balance_sheet_trend_gap": "가계 현금도 추세보다 많아 유동성 고갈 상태는 아니지만, 주식 자산의 추세 이탈이 더 커 가격 조정 민감도는 높습니다.",
    }
    missing_conclusions = sorted(set(chart_by_id) - set(conclusions))
    if missing_conclusions:
        raise StatisticsLabError(
            f"customer conclusion missing for charts: {missing_conclusions}"
        )
    for chart_id, chart in chart_by_id.items():
        chart["conclusion"] = conclusions[chart_id]

    source_meta = []
    for series_id, spec in FRED_SERIES.items():
        rows = source_rows[series_id]
        fred_start = spec.get("window_start", "1995-01-01")
        source_meta.append({
            "series_id": series_id,
            **spec,
            "source_url": f"https://fred.stlouisfed.org/series/{series_id}",
            "request_url": fred_api.observations_public_url(
                series_id, observation_start=fred_start,
            ),
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
    for z1_series_id, z1_spec in Z1_SERIES.items():
        z1_rows = source_rows[z1_series_id]
        z1_meta = {
            "series_id": z1_series_id,
            "title": z1_spec["title"],
            "provider": "Board of Governors of the Federal Reserve System (US)",
            "unit": z1_spec["unit"],
            "native_frequency": "quarterly",
            "source_url": "https://www.federalreserve.gov/releases/z1/current/",
            "request_url": Z1_ENDPOINT,
            "available_at": generated_at,
            "latest_observation": z1_rows[-1]["date"],
            "row_count": len(z1_rows),
            "raw_sha256": receipts[z1_series_id]["raw_sha256"],
            "vintage": "current_release_reconstructed",
        }
        if z1_spec.get("proxy_warning"):
            z1_meta["proxy_warning"] = z1_spec["proxy_warning"]
        source_meta.append(z1_meta)
    if ipo_reference is not None:
        source_meta.extend(ipo_reference["sources"])
    if hmi_reference is not None:
        source_meta.append(hmi_reference["source"])
    observation_through = max(row["latest_observation"] for row in source_meta)
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


def build_statistics_lab(
    source_rows: dict[str, list[dict[str, Any]]], *, generated_at: str,
    receipts: dict[str, dict[str, Any]],
    ipo_reference: dict[str, Any] | None = None,
    hmi_reference: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build official charts and an explicitly separate reference-statistics layer.

    Research reports may still be catalogued outside this function to help frame an
    insight, but their numbers remain absent from the official ``charts`` and
    ``sources`` collections.  If a complete annual SEC denominator is available,
    ``ipo_reference`` produces a separately validated ``reference_statistics`` card.
    ``hmi_reference`` remains accepted for backwards-compatible callers and ignored.
    """
    del hmi_reference
    required_sources = (
        set(FRED_SERIES) | set(SUPPLEMENTAL_SOURCES) | set(Z1_SERIES)
        | set(CENSUS_C30_SERIES)
    )
    missing = sorted(required_sources - set(source_rows))
    if missing:
        raise StatisticsLabError(f"missing authoritative source series: {missing}")
    generated_time = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    monthly = {
        key: _monthly(source_rows[key], spec["aggregation"])
        for key, spec in FRED_SERIES.items()
    }
    for z1_series_id in Z1_SERIES:
        monthly[z1_series_id] = _monthly(source_rows[z1_series_id], "last")
    for c30_series_id in CENSUS_C30_SERIES:
        monthly[c30_series_id] = _monthly(source_rows[c30_series_id], "last")
    comparison_months = COMPARISON_MONTHS

    def cycles(rows: list[dict[str, Any]], *, indexed: bool = False):
        return _cycle_series(rows, comparison_months, indexed=indexed)

    dot_nasdaq, cur_nasdaq = cycles(monthly["NASDAQCOM"], indexed=True)
    dot_m2, cur_m2 = cycles(monthly["M2SL"], indexed=True)
    dot_nasdaq_m2, cur_nasdaq_m2 = cycles(
        _ratio(monthly["NASDAQCOM"], monthly["M2SL"]), indexed=True,
    )
    dot_nasdaq_cash, cur_nasdaq_cash = cycles(
        _ratio(monthly["NASDAQCOM"], monthly["DABSHNO"]), indexed=True,
    )
    dot_curve, cur_curve = cycles(monthly["T10Y2Y"])
    dot_funds, cur_funds = cycles(monthly["FEDFUNDS"])
    # Investment share of GDP, published as two definitions on purpose: the
    # narrow hardware measure (D1) and the broad measure that adds intellectual
    # property products (D5).  A single headline number is not publishable here
    # because the two definitions disagree about whether today exceeds 2000.
    equipment_share = [
        {"date": row["date"], "value": float(row["value"]) * 100.0}
        for row in _ratio(monthly["Y034RC1Q027SBEA"], monthly["GDP"])
    ]
    gdp_by_month = {_month_key(row["date"]): float(row["value"]) for row in monthly["GDP"]}
    ipp_by_month = {
        _month_key(row["date"]): float(row["value"]) for row in monthly["Y001RC1Q027SBEA"]
    }
    broad_share = []
    for row in monthly["Y034RC1Q027SBEA"]:
        key = _month_key(row["date"])
        denominator = gdp_by_month.get(key)
        intellectual_property = ipp_by_month.get(key)
        if denominator and intellectual_property is not None:
            broad_share.append({
                "date": row["date"],
                "value": (float(row["value"]) + intellectual_property) / denominator * 100.0,
            })
    dot_equipment_share, cur_equipment_share = cycles(equipment_share)
    dot_broad_share, cur_broad_share = cycles(broad_share)
    valuation = [
        {**row, "value": float(row["value"]) / 1000.0}
        for row in _ratio(monthly["NCBEILQ027S"], monthly["CPATAX"])
    ]
    dot_value, cur_value = cycles(valuation)
    dot_margin, cur_margin = cycles(monthly["FL663067003"], indexed=True)
    # Corporate bond stock and flow for nonfinancial business.  The flow is the
    # macro denominator the "AI-related issuance" headlines lack: no official
    # taxonomy marks a bond as AI-related, so only the whole-economy total is
    # reproducible from official data.
    bond_outstanding_tn = [
        {"date": row["date"], "value": float(row["value"]) / 1_000_000.0}
        for row in monthly["FL103163005"]
    ]
    bond_issuance_bn = [
        {"date": row["date"], "value": float(row["value"]) / 1_000.0}
        for row in monthly["FA103163005"]
    ]
    dot_bond_stock, cur_bond_stock = cycles(bond_outstanding_tn)
    dot_bond_flow, cur_bond_flow = cycles(bond_issuance_bn)
    # Physical build-out.  Chip-fab, power and communication structures all run
    # back to 1993 and therefore carry a dot-com line; the data-centre column
    # only starts in 2014, so it is reported in the conclusion text instead of
    # being drawn as a two-era series that would have no comparison.
    dot_fab, cur_fab = cycles(monthly["C30_MFG_COMPUTER_ELECTRONIC"], indexed=True)
    dot_power, cur_power = cycles(monthly["C30_POWER"], indexed=True)
    dot_comm, cur_comm = cycles(monthly["C30_COMMUNICATION"], indexed=True)
    data_centre_rows = monthly["C30_OFFICE_DATA_CENTER"]
    office_rows = {row["date"]: float(row["value"]) for row in monthly["C30_OFFICE_TOTAL"]}
    data_centre_latest = float(data_centre_rows[-1]["value"]) if data_centre_rows else 0.0
    data_centre_date = data_centre_rows[-1]["date"] if data_centre_rows else None
    office_latest = office_rows.get(data_centre_date or "", 0.0)
    data_centre_share = (
        data_centre_latest / office_latest * 100.0 if office_latest else 0.0
    )
    dot_equities, cur_equities = cycles(monthly["BOGZ1LM893064105Q"], indexed=True)
    dot_credit, cur_credit = cycles(_yoy(monthly["TOTALSL"]))
    dot_standards, cur_standards = cycles(monthly["DRTSCILM"])
    dot_profit, cur_profit = cycles(_yoy(monthly["CPATAX"]))
    dot_debt_service, cur_debt_service = cycles(monthly["BOGZ1FL010000346Q"])
    dot_unemployment, cur_unemployment = cycles(monthly["UNRATE"])
    inflation = _yoy(monthly["CPIAUCSL"])
    dot_inflation, cur_inflation = cycles(inflation)
    dot_nfci, cur_nfci = cycles(monthly["NFCI"])
    dot_rate_cycle = _event_change(
        monthly["FEDFUNDS"], base_month=date(1995, 6, 1),
        event_month=date(1995, 7, 1), months=comparison_months,
    )
    cur_rate_cycle = _event_change(
        monthly["FEDFUNDS"], base_month=date(2024, 8, 1),
        event_month=date(2024, 9, 1), months=comparison_months,
    )
    treasury = {_month_key(row["date"]): float(row["value"]) for row in monthly["GS10"]}
    corporate_spread = [
        {"date": row["date"], "value": float(row["value"]) - treasury[_month_key(row["date"])]}
        for row in monthly["HQMCB10YR"] if _month_key(row["date"]) in treasury
    ]
    dot_corp_yield, cur_corp_yield = cycles(monthly["HQMCB10YR"])
    dot_corp_spread, cur_corp_spread = cycles(corporate_spread)
    dot_cpi_lead, cur_cpi_lead = cycles(_shift_months(inflation, -2))
    dot_oil, cur_oil = cycles(_yoy(monthly["DCOILWTICO"]))
    dot_copper, cur_copper = cycles(_yoy(monthly["WPU10260314"]))
    dot_housing, cur_housing = cycles(_yoy(monthly["HOUST"]))
    dot_philly, cur_philly = cycles(monthly["GACDFSA066MSFRBPHI"])
    equity_gap = _trend_gap_points(monthly["BOGZ1LM153064475Q"])
    cash_gap = _trend_gap_points(monthly["DABSHNO"])
    debt_gap = _trend_gap_points(monthly["BOGZ1FL154022375A"], minimum_training=8)

    def current_index(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        selected = [row for row in rows if date.fromisoformat(str(row["date"])) >= CURRENT_START]
        if not selected or float(selected[0]["value"]) <= 0:
            raise StatisticsLabError("current indexed series is unavailable")
        base = float(selected[0]["value"])
        return [
            {
                "period": _month_offset(str(row["date"]), CURRENT_START),
                "date": str(row["date"]),
                "value": float(row["value"]) / base * 100.0,
            }
            for row in selected
            if _month_offset(str(row["date"]), CURRENT_START) <= comparison_months
        ]

    korea_index = current_index(monthly["SPASTT01KRM661N"])
    sox_index = current_index(monthly["NASDAQSOX"])

    def make(
        chart_id: str, title: str, category: str, unit: str,
        series: list[dict[str, Any]], source_ids: list[str], scope: str,
        insight: str,
    ) -> dict[str, Any]:
        chart = _chart(
            chart_id, title, category, unit, insight,
            "공식 원천의 실제 관측치만 사용하며 미래 구간을 연장하지 않습니다.",
            series, source_ids,
        )
        chart["scope_note"] = scope
        chart["insight"] = insight
        chart["conclusion"] = insight
        chart["metric_source_ids"] = list(source_ids)
        chart["research_context_source_ids"] = []
        return chart

    latest_m2_bn = float(monthly["M2SL"][-1]["value"])
    latest_mmf_bn = float(monthly["MMMFFAQ027S"][-1]["value"]) / 1000.0
    latest_equity_bn = float(monthly["BOGZ1LM893064105Q"][-1]["value"]) / 1000.0
    latest_cash_bn = float(monthly["CDCABSHNO"][-1]["value"]) / 1000.0
    latest_deposits_bn = float(monthly["TSDABSHNO"][-1]["value"]) / 1000.0
    latest_treasuries_bn = float(monthly["FGDSLAQ027S"][-1]["value"]) / 1000.0
    latest_bond_funds_bn = float(monthly["BOGZ1FL153064235Q"][-1]["value"]) / 1000.0
    changes = {
        "S&P 500": _trailing_year_change(source_rows["SP500"]),
        "NASDAQ": _trailing_year_change(source_rows["NASDAQCOM"]),
        "비트코인": _trailing_year_change(source_rows["CBBTCUSD"]),
        "금 가격지수": _trailing_year_change(monthly["IQ12260"]),
        "미국 연방정부 채권": _trailing_year_change(monthly["FGDSLAQ027S"]),
        "가계 예금": _trailing_year_change(monthly["TSDABSHNO"]),
        "가계 현금": _trailing_year_change(monthly["CDCABSHNO"]),
        "미국 MMF": _trailing_year_change(monthly["MMMFFAQ027S"]),
        "가계 채권펀드": _trailing_year_change(monthly["BOGZ1FL153064235Q"]),
    }
    change_dates = {
        "S&P 500": source_rows["SP500"][-1]["date"],
        "NASDAQ": source_rows["NASDAQCOM"][-1]["date"],
        "비트코인": source_rows["CBBTCUSD"][-1]["date"],
        "금 가격지수": monthly["IQ12260"][-1]["date"],
        "미국 연방정부 채권": monthly["FGDSLAQ027S"][-1]["date"],
        "가계 예금": monthly["TSDABSHNO"][-1]["date"],
        "가계 현금": monthly["CDCABSHNO"][-1]["date"],
        "미국 MMF": monthly["MMMFFAQ027S"][-1]["date"],
        "가계 채권펀드": monthly["BOGZ1FL153064235Q"][-1]["date"],
    }

    charts = [
        make("m2_nasdaq", "M2와 NASDAQ의 상승 속도", "liquidity", "cycle_start_100",
             [_series("닷컴 NASDAQ", "dotcom", dot_nasdaq, "#d42b20"), _series("닷컴 M2", "dotcom", dot_m2, "#755d35"), _series("현재 NASDAQ", "current", cur_nasdaq, "#ff6a1a"), _series("현재 M2", "current", cur_m2, "#1c7262")],
             ["NASDAQCOM", "M2SL"], "*미국 통화·NASDAQ 기준", "주가와 통화량의 누적 속도를 같은 시작점에서 비교합니다."),
        make("nasdaq_per_m2", "M2 한 단위 대비 NASDAQ", "liquidity", "cycle_start_100",
             [_series("닷컴", "dotcom", dot_nasdaq_m2, "#c70039"), _series("현재", "current", cur_nasdaq_m2, "#ff7b00")],
             ["NASDAQCOM", "M2SL"], "*미국 통화·NASDAQ 기준", "M2 증가보다 NASDAQ이 얼마나 빠르게 움직였는지 보여줍니다."),
        make("nasdaq_per_household_liquid_assets", "가계 현금성 자산 한 단위 대비 NASDAQ", "liquidity", "cycle_start_100",
             [_series("닷컴", "dotcom", dot_nasdaq_cash, "#7a3248"), _series("현재", "current", cur_nasdaq_cash, "#e46b20")],
             ["NASDAQCOM", "DABSHNO"], "*미국 가계·비영리 자산 기준", "가계 현금성 자산 대비 NASDAQ의 상대 속도를 비교합니다."),
        make("yield_curve", "10년−2년 장단기 금리차", "rates", "percent",
             [_series("닷컴", "dotcom", dot_curve, "#8d2943"), _series("현재", "current", cur_curve, "#28756a")],
             ["T10Y2Y"], "*미국 국채 기준", "금리차가 음수면 역전, 양수로 급히 복귀하면 성장 둔화 구간을 함께 점검합니다."),
        make("policy_rate", "연방기금금리 경로", "rates", "percent",
             [_series("닷컴", "dotcom", dot_funds, "#8d2943"), _series("현재", "current", cur_funds, "#28756a")],
             ["FEDFUNDS"], "*미국 기준", "월평균 실효금리의 실제 경로이며 시장의 미래 인하 확률은 아닙니다."),
        make("valuation_proxy", "기업가치 ÷ 세후이익 PER 대용치", "valuation", "multiple",
             [_series("닷컴", "dotcom", dot_value, "#c70039"), _series("현재", "current", cur_value, "#ff7b00")],
             ["NCBEILQ027S", "CPATAX"], "*미국 기업 기준", "기업주식 가치가 실제 세후이익보다 얼마나 빠른지 보는 공개자료 대용치입니다."),
        make("margin_credit_proxy", "브로커 고객 신용과 미국 기업주식", "credit", "cycle_start_100",
             [_series("닷컴 고객 신용", "dotcom", dot_margin, "#c70039"), _series("닷컴 기업주식", "dotcom", dot_equities, "#7b6b55"), _series("현재 고객 신용", "current", cur_margin, "#ff7b00"), _series("현재 기업주식", "current", cur_equities, "#28756a")],
             ["FL663067003", "BOGZ1LM893064105Q"], "*미국 가계·기업주식 기준", "신용과 주식가치가 함께 빨라질수록 레버리지 민감도가 커집니다."),
        make("consumer_credit_growth", "소비자신용 증가율", "credit", "percent_yoy",
             [_series("닷컴", "dotcom", dot_credit, "#8d2943"), _series("현재", "current", cur_credit, "#28756a")],
             ["TOTALSL"], "*미국 소비자신용 기준", "소비자신용의 전년 대비 증가 속도를 비교합니다."),
        make("loan_standards", "은행 기업대출 심사 강화 비율", "credit", "net_percent",
             [_series("닷컴", "dotcom", dot_standards, "#8d2943"), _series("현재", "current", cur_standards, "#28756a")],
             ["DRTSCILM"], "*미국 기업대출 기준", "양수가 높아질수록 더 많은 은행이 기업대출 문턱을 높인 상태입니다."),
        make("profit_growth", "세후 기업이익 증가율", "valuation", "percent_yoy",
             [_series("닷컴", "dotcom", dot_profit, "#8d2943"), _series("현재", "current", cur_profit, "#28756a")],
             ["CPATAX"], "*미국 기업 기준", "주가를 지탱하는 실제 기업이익의 증가 속도를 비교합니다."),
        make("household_debt_service", "가계 원리금 상환 부담", "credit", "percent",
             [_series("닷컴", "dotcom", dot_debt_service, "#8d2943"), _series("현재", "current", cur_debt_service, "#28756a")],
             ["BOGZ1FL010000346Q"], "*미국 가계 기준", "가처분소득에서 원리금 상환이 차지하는 비중입니다."),
        make("unemployment_rate", "실업률", "economy", "percent",
             [_series("닷컴", "dotcom", dot_unemployment, "#8d2943"), _series("현재", "current", cur_unemployment, "#28756a")],
             ["UNRATE"], "*미국 기준", "공식 U-3 실업률로 고용 냉각 정도를 비교합니다."),
        make("inflation_rate", "소비자물가 상승률", "economy", "percent_yoy",
             [_series("닷컴", "dotcom", dot_inflation, "#8d2943"), _series("현재", "current", cur_inflation, "#28756a")],
             ["CPIAUCSL"], "*미국 기준", "전체 CPI 전년비로 정책금리 부담의 배경을 비교합니다."),
        make("financial_conditions", "금융여건지수", "rates", "standard_deviation_index",
             [_series("닷컴", "dotcom", dot_nfci, "#8d2943"), _series("현재", "current", cur_nfci, "#28756a")],
             ["NFCI"], "*미국 금융시장 기준", "0 위는 역사 평균보다 긴축적, 0 아래는 완화적인 금융환경입니다."),
        make("rate_cycle_since_first_cut", "첫 금리 인하 뒤 재긴축 거리", "rates", "percentage_point_change",
             [_series("1995 인하 사이클", "dotcom", dot_rate_cycle, "#8d2943"), _series("2024 인하 사이클", "current", cur_rate_cycle, "#28756a")],
             ["FEDFUNDS"], "*미국 기준", "첫 인하 직전 수준에서 정책금리가 얼마나 이동했는지 비교합니다."),
        make("corporate_bond_pressure", "회사채 금리와 국채 대비 부담", "rates", "percent",
             [_series("닷컴 회사채", "dotcom", dot_corp_yield, "#9b1c31"), _series("닷컴 스프레드", "dotcom", dot_corp_spread, "#d47f52"), _series("현재 회사채", "current", cur_corp_yield, "#166a5b"), _series("현재 스프레드", "current", cur_corp_spread, "#4aa18d")],
             ["HQMCB10YR", "GS10"], "*미국 회사채·국채 기준", "회사채 금리와 국채 대비 차이가 함께 오르면 기업 자금조달 부담이 커집니다."),
        make("inflation_lead_panel", "유가·구리 2개월 선행과 CPI", "economy", "percent_yoy",
             [_series("닷컴 2개월 뒤 CPI", "dotcom", dot_cpi_lead, "#8d2943"), _series("닷컴 WTI", "dotcom", dot_oil, "#c46d24"), _series("닷컴 구리", "dotcom", dot_copper, "#8c6b43"), _series("현재 2개월 뒤 CPI", "current", cur_cpi_lead, "#28756a"), _series("현재 WTI", "current", cur_oil, "#f07822"), _series("현재 구리", "current", cur_copper, "#5aa68f")],
             ["CPIAUCSL", "DCOILWTICO", "WPU10260314"], "*미국 물가·원자재 기준", "유가와 구리가 함께 오르면 두 달 뒤 물가의 상방 위험을 추가 점검합니다."),
        make("korea_semiconductor_cycle", "한국 주가와 글로벌 반도체 사이클", "economy", "cycle_start_100",
             [_series("한국 주가", "current", korea_index, "#11110f"), _series("미국 반도체", "current", sox_index, "#e05d26")],
             ["SPASTT01KRM661N", "NASDAQSOX"], "*한국·미국 시장 기준", "2023년을 100으로 맞춰 한국 주가와 미국 반도체 지수의 실제 월별 속도를 봅니다."),
        make("investment_share_of_gdp", "설비·지식재산 투자의 GDP 비중", "economy", "percent",
             [_series("닷컴 장비", "dotcom", dot_equipment_share, "#8d2943"), _series("닷컴 장비+지식재산", "dotcom", dot_broad_share, "#d47f52"), _series("현재 장비", "current", cur_equipment_share, "#28756a"), _series("현재 장비+지식재산", "current", cur_broad_share, "#4aa18d")],
             ["Y034RC1Q027SBEA", "Y001RC1Q027SBEA", "GDP"], "*미국 명목 분기 연율 기준",
             "투자 규모를 경제 크기로 나눠 두 정의로 함께 봅니다. 장비만 보면 닷컴 정점보다 낮고, 소프트웨어·연구개발을 더하면 더 높습니다."),
        make("structures_buildout", "반도체·전력·통신 시설 건설", "economy", "cycle_start_100",
             [_series("닷컴 반도체시설", "dotcom", dot_fab, "#8d2943"), _series("닷컴 전력", "dotcom", dot_power, "#d47f52"), _series("닷컴 통신", "dotcom", dot_comm, "#b58b2a"), _series("현재 반도체시설", "current", cur_fab, "#28756a"), _series("현재 전력", "current", cur_power, "#4aa18d"), _series("현재 통신", "current", cur_comm, "#11110f")],
             ["C30_MFG_COMPUTER_ELECTRONIC", "C30_POWER", "C30_COMMUNICATION"], "*미국 민간 건설 기준",
             "설비가 실제로 지어지는 속도를 봅니다. 컴퓨터·전자 제조시설, 전력, 통신 세 축을 같은 시작점에서 비교합니다."),
        make("housing_manufacturing_warning", "주택·제조업 경기 경고판", "economy", "percent_yoy",
             [_series("닷컴 주택착공", "dotcom", dot_housing, "#8d2943"), _series("닷컴 제조업", "dotcom", dot_philly, "#d47f52"), _series("현재 주택착공", "current", cur_housing, "#28756a"), _series("현재 제조업", "current", cur_philly, "#4aa18d")],
             ["HOUST", "GACDFSA066MSFRBPHI"], "*미국 기준", "주택착공 증가율과 제조업 확산지수가 함께 약해지면 경기 냉각 신호가 강해집니다."),
        make("corporate_bond_issuance", "비금융기업 회사채 잔액과 순발행", "credit", "trillions_and_billions_usd",
             [_series("닷컴 잔액(조 달러)", "dotcom", dot_bond_stock, "#8d2943"), _series("닷컴 순발행(십억 달러)", "dotcom", dot_bond_flow, "#d47f52"), _series("현재 잔액(조 달러)", "current", cur_bond_stock, "#28756a"), _series("현재 순발행(십억 달러)", "current", cur_bond_flow, "#4aa18d")],
             ["FL103163005", "FA103163005"], "*미국 비금융기업 기준",
             "기업이 채권으로 조달한 잔액과 분기 순발행을 함께 봅니다. 공식 통계에 \"AI 채권\" 분류는 없으므로 경제 전체 규모만 재현할 수 있습니다."),
        make("household_balance_sheet_trend_gap", "가계 주식·현금·채권의 추세 이탈", "credit", "percent_vs_trend",
             [_series("주식", "current", equity_gap, "#11110f"), _series("현금성 자산", "current", cash_gap, "#b58b2a"), _series("채권", "current", debt_gap, "#28756a")],
             ["BOGZ1LM153064475Q", "DABSHNO", "BOGZ1FL154022375A"], "*미국 가계·비영리 자산 기준", "2009~2019 추세에서 주식·현금·채권이 얼마나 벗어났는지 비교합니다."),
    ]

    liquidity = make(
        "liquidity_position_map", "자금 지도: 현재 규모와 12개월 방향", "liquidity", "percent",
        [_series("12개월 변화", "current", [
            {"period": index, "date": change_dates[label], "value": value}
            for index, (label, value) in enumerate(changes.items())
        ], "#28756a")],
        [
            "BOGZ1LM893064105Q", "FGDSLAQ027S", "TSDABSHNO", "CDCABSHNO",
            "M2SL", "MMMFFAQ027S", "BOGZ1FL153064235Q", "SP500",
            "NASDAQCOM", "CBBTCUSD", "IQ12260",
        ],
        "*미국 기준 · 금은 공식 가격지수",
        "대표 주식·안전자산·현금성 자산의 규모와 최근 방향을 함께 봅니다. 항목 간 중복이 있어 합산하지 않습니다.",
    )
    liquidity.update({
        "chart_type": "liquidity_bars",
        "display_unit": "현재 규모 + 12개월 증감",
        "reading_guide": "규모와 방향은 단위가 달라 두 패널로 분리합니다.",
        "liquidity_panels": [
            {"id": "current_scale", "title": "현재 규모", "basis": "조 달러", "mode": "positive", "metrics": [
                {"label": "미국 기업주식", "value": latest_equity_bn / 1000.0, "display_value": f"${latest_equity_bn / 1000.0:.1f}T"},
                {"label": "미국 연방정부 채권", "value": latest_treasuries_bn / 1000.0, "display_value": f"${latest_treasuries_bn / 1000.0:.1f}T"},
                {"label": "가계 예금", "value": latest_deposits_bn / 1000.0, "display_value": f"${latest_deposits_bn / 1000.0:.1f}T"},
                {"label": "가계 현금", "value": latest_cash_bn / 1000.0, "display_value": f"${latest_cash_bn / 1000.0:.1f}T"},
                {"label": "미국 M2", "value": latest_m2_bn / 1000.0, "display_value": f"${latest_m2_bn / 1000.0:.1f}T"},
                {"label": "미국 MMF", "value": latest_mmf_bn / 1000.0, "display_value": f"${latest_mmf_bn / 1000.0:.1f}T"},
                {"label": "가계 채권펀드", "value": latest_bond_funds_bn / 1000.0, "display_value": f"${latest_bond_funds_bn / 1000.0:.1f}T"},
            ]},
            {"id": "trailing_change", "title": "최근 12개월 방향", "basis": "가격·잔액 증감률", "mode": "diverging", "metrics": [
                {"label": label, "value": value, "display_value": f"{value:+.1f}%"}
                for label, value in changes.items()
            ]},
        ],
    })
    charts.insert(3, liquidity)

    sec_rows = source_rows["SEC_IPO_QUARTERLY"]
    sec_by_period = {str(row["period_label"]): row for row in sec_rows}
    def half(year: int, field: str) -> float:
        return sum(float(sec_by_period[f"{year}:Q{quarter}"][field]) for quarter in (1, 2))
    sec_chart = make(
        "sec_ipo_issuer_mix_h1", "미국 IPO: 일반 기업·SPAC·펀드", "ipo", "count",
        [
            _series("일반 기업", "current", [{"period": i, "date": f"{year}-06-30", "value": half(year, "corporate_count")} for i, year in enumerate((2025, 2026))], "#d94b24"),
            _series("SPAC", "current", [{"period": i, "date": f"{year}-06-30", "value": half(year, "spac_count")} for i, year in enumerate((2025, 2026))], "#6956a8"),
            _series("펀드", "current", [{"period": i, "date": f"{year}-06-30", "value": half(year, "fund_count")} for i, year in enumerate((2025, 2026))], "#28756a"),
        ],
        ["SEC_IPO_QUARTERLY"], "*미국 SEC 기준", "상반기 전체 IPO를 발행 주체별로 나눠 상장시장 열기의 폭을 봅니다.",
    )
    sec_chart.update({"chart_type": "stacked_bar", "show_bar_values": True, "x_ticks": [[0, "2025 상반기"], [1, "2026 상반기"]], "max_period": 1})
    charts.insert(0, sec_chart)
    by_id = {chart["id"]: chart for chart in charts}
    by_id["m2_nasdaq"]["scale"] = "log1p"
    by_id["household_balance_sheet_trend_gap"]["trend_baseline"] = {
        "start": "2009-01-01", "end": "2019-12-31", "method": "ordinary_least_squares_on_levels",
        "training_observations": {"corporate_equities": 44, "cash_and_deposits": 44, "debt_securities": 11},
    }
    by_id["household_balance_sheet_trend_gap"]["max_period"] = max(
        int(point["period"])
        for series in by_id["household_balance_sheet_trend_gap"]["series"]
        for point in series["points"]
    )
    policy_points = by_id["policy_rate"]["series"][0]["points"]
    by_id["policy_rate"]["source_validation"] = {
        "source_id": "FEDFUNDS", "period": "1995-01-01_to_1999-12-01",
        "observations": len(policy_points), "interpolation": False,
        "perfect_rectangle": False, "minimum": min(policy_points, key=lambda row: float(row["value"])),
        "maximum": max(policy_points, key=lambda row: float(row["value"])),
    }

    def endpoint(rows: list[dict[str, Any]]) -> float:
        if not rows:
            raise StatisticsLabError("customer conclusion endpoint is unavailable")
        return float(rows[-1]["value"])

    corporate_h1 = half(2026, "corporate_count")
    spac_h1 = half(2026, "spac_count")
    top_direction_label, top_direction = max(
        changes.items(), key=lambda item: float(item[1]),
    )
    mmf_to_m2 = latest_mmf_bn / latest_m2_bn * 100.0
    curve_now = endpoint(cur_curve)
    standards_now = endpoint(cur_standards)
    inflation_now = endpoint(cur_inflation)
    conditions_now = endpoint(cur_nfci)
    oil_now = endpoint(cur_oil)
    copper_now = endpoint(cur_copper)
    housing_now = endpoint(cur_housing)
    manufacturing_now = endpoint(cur_philly)
    current_conclusions = {
        "sec_ipo_issuer_mix_h1": (
            f"2026년 상반기 SPAC {spac_h1:.0f}건이 일반 기업 {corporate_h1:.0f}건보다 "
            "많습니다. IPO 창구는 열렸지만 실물기업 상장 확산은 아직 제한적입니다."
        ),
        "m2_nasdaq": (
            f"현재 NASDAQ은 2023년 대비 {endpoint(cur_nasdaq) - 100.0:.0f}% 오른 반면 "
            f"M2는 {endpoint(cur_m2) - 100.0:.0f}% 증가했습니다. 유동성보다 주가가 "
            "훨씬 빠르지만 닷컴 정점의 격차보다는 작습니다."
        ),
        "nasdaq_per_m2": (
            f"현재 M2 대비 NASDAQ 속도지수는 {endpoint(cur_nasdaq_m2):.0f}로 닷컴의 "
            f"{endpoint(dot_nasdaq_m2):.0f}보다 낮습니다. 통화량 기준 과열은 높지만 "
            "닷컴 말기 수준에는 아직 못 미칩니다."
        ),
        "nasdaq_per_household_liquid_assets": (
            f"가계 현금성 자산 대비 NASDAQ 속도는 현재 {endpoint(cur_nasdaq_cash):.0f}, "
            f"닷컴 {endpoint(dot_nasdaq_cash):.0f}입니다. 가계 유동성 대비 주가 부담은 "
            "커졌지만 닷컴 정점보다는 낮습니다."
        ),
        "liquidity_position_map": (
            f"미국 MMF는 M2의 약 {mmf_to_m2:.0f}% 규모이고, 최근 12개월 방향은 "
            f"{top_direction_label} {top_direction:+.1f}%가 가장 강합니다. 위험자산 열기와 "
            "대기자금이 함께 남아 있는 시장입니다."
        ),
        "yield_curve": (
            f"10년−2년 금리차는 현재 {curve_now:+.2f}%p로 정상화됐습니다. 다만 역전 "
            "해소 직후에는 성장 둔화가 뒤따를 수 있어 경기 경계는 아직 남아 있습니다."
            if curve_now >= 0 else
            f"10년−2년 금리차가 현재 {curve_now:+.2f}%p로 역전돼 있어 경기 둔화 "
            "경고가 계속 작동하고 있습니다."
        ),
        "policy_rate": (
            f"현재 실효금리는 {endpoint(cur_funds):.2f}%로 닷컴 같은 시점의 "
            f"{endpoint(dot_funds):.2f}%보다 낮습니다. 지금은 재긴축보다 인하 경로에 "
            "가까워 닷컴 붕괴 전 정책 트리거와는 다릅니다."
        ),
        "valuation_proxy": (
            f"기업가치÷이익 대용치는 현재 {endpoint(cur_value):.1f}배로 닷컴의 "
            f"{endpoint(dot_value):.1f}배보다 낮습니다. 밸류에이션 부담은 높지만 "
            "광의 시장 전체가 닷컴 극단에 도달한 상태는 아닙니다."
        ),
        "margin_credit_proxy": (
            f"현재 고객 신용지수 {endpoint(cur_margin):.0f}이 기업주식지수 "
            f"{endpoint(cur_equities):.0f}보다 빠릅니다. 닷컴보다는 낮지만 레버리지 "
            "민감도가 다시 커지는 구간입니다."
        ),
        "consumer_credit_growth": (
            f"소비자신용 증가율은 현재 {endpoint(cur_credit):.1f}%로 닷컴의 "
            f"{endpoint(dot_credit):.1f}%보다 낮습니다. 현재 상승장이 가계 신용 "
            "팽창에 크게 의존하는 모습은 아닙니다."
        ),
        "loan_standards": (
            f"은행 대출기준 순강화 비율은 현재 {standards_now:.1f}%로 대체로 "
            "중립입니다. 기업 신용 경색 신호는 아직 강하지 않습니다."
            if standards_now <= 5 else
            f"은행 대출기준 순강화 비율이 {standards_now:.1f}%로 올라 기업 자금조달 "
            "경계가 필요한 상태입니다."
        ),
        "structures_buildout": (
            f"컴퓨터·전자 제조시설 건설은 현재 지수 {endpoint(cur_fab):.0f}로 닷컴 같은 시점의 "
            f"{endpoint(dot_fab):.0f}과 견줍니다. 전력은 {endpoint(cur_power):.0f}, 통신은 "
            f"{endpoint(cur_comm):.0f}입니다. "
            + (
                f"데이터센터 건설은 {data_centre_date} 기준 민간 오피스 건설의 "
                f"{data_centre_share:.0f}%를 차지하지만 2014년부터만 집계돼 닷컴 비교선이 없습니다."
                if data_centre_date else
                "데이터센터 계열은 2014년부터만 집계돼 닷컴 비교선이 없습니다."
            )
        ),
        "corporate_bond_issuance": (
            f"비금융기업 회사채 잔액은 현재 {endpoint(cur_bond_stock):.1f}조 달러로 닷컴 같은 시점의 "
            f"{endpoint(dot_bond_stock):.1f}조 달러보다 큽니다. 분기 순발행은 현재 "
            f"{endpoint(cur_bond_flow):.0f}십억 달러입니다. 이 총액에는 AI 목적 여부를 구분하는 공식 분류가 "
            "없으므로, 특정 기업군의 AI 조달액을 이 계열에서 뽑아낼 수는 없습니다."
        ),
        "investment_share_of_gdp": (
            f"설비 투자만 보면 현재 GDP의 {endpoint(cur_equipment_share):.2f}%로 닷컴 같은 시점의 "
            f"{endpoint(dot_equipment_share):.2f}%와 견줍니다. 소프트웨어·연구개발을 더하면 "
            f"{endpoint(cur_broad_share):.2f}%로 닷컴의 {endpoint(dot_broad_share):.2f}%를 넘습니다. "
            "정의에 따라 결론이 갈리므로 두 선을 함께 봐야 합니다."
        ),
        "profit_growth": (
            f"세후 기업이익은 현재 전년 대비 {endpoint(cur_profit):.1f}% 증가해 닷컴의 "
            f"{endpoint(dot_profit):.1f}%보다 강합니다. 높은 주가에 닷컴 말기보다 "
            "두꺼운 이익 기반이 붙어 있습니다."
        ),
        "household_debt_service": (
            f"가계 상환 부담은 현재 {endpoint(cur_debt_service):.1f}%로 닷컴의 "
            f"{endpoint(dot_debt_service):.1f}%와 비슷합니다. 소비 붕괴를 단독으로 "
            "예고하는 극단적 부담은 아닙니다."
        ),
        "unemployment_rate": (
            f"실업률은 현재 {endpoint(cur_unemployment):.1f}%로 닷컴 같은 시점의 "
            f"{endpoint(dot_unemployment):.1f}%와 비슷합니다. 고용은 냉각 점검 구간이지만 "
            "침체가 확인된 수준은 아닙니다."
        ),
        "inflation_rate": (
            f"소비자물가는 현재 {inflation_now:.1f}%로 3%를 웃돌아 추가 금리 인하의 "
            "제약이 남아 있습니다."
            if inflation_now >= 3 else
            f"소비자물가는 현재 {inflation_now:.1f}%로 완화됐습니다. 물가보다 성장 "
            "둔화가 정책의 핵심 변수가 된 구간입니다."
        ),
        "financial_conditions": (
            f"금융여건지수는 현재 {conditions_now:+.2f}로 평균보다 완화적입니다. "
            "위험자산을 지지하지만 상승 과열이 더 이어질 여지도 함께 남깁니다."
            if conditions_now < 0 else
            f"금융여건지수는 현재 {conditions_now:+.2f}로 평균보다 긴축적입니다. "
            "위험자산의 자금조달 부담이 커진 상태입니다."
        ),
        "rate_cycle_since_first_cut": (
            f"첫 인하 전보다 정책금리가 현재 {endpoint(cur_rate_cycle):+.2f}%p 낮습니다. "
            "1990년대 말처럼 금리를 다시 원점 이상으로 올린 재긴축 신호는 아직 없습니다."
        ),
        "corporate_bond_pressure": (
            f"회사채 금리는 현재 {endpoint(cur_corp_yield):.2f}%, 국채 대비 스프레드는 "
            f"{endpoint(cur_corp_spread):.2f}%p입니다. 전면적 신용 스트레스보다는 높은 "
            "절대금리 부담이 핵심입니다."
        ),
        "inflation_lead_panel": (
            f"유가 {oil_now:+.1f}%와 구리 {copper_now:+.1f}%가 함께 올라 향후 물가 "
            "재가속 위험을 무시하기 어렵습니다."
            if oil_now > 0 and copper_now > 0 else
            "유가와 구리 방향이 엇갈려 원자재발 물가 재가속 신호는 아직 일관되지 않습니다."
        ),
        "korea_semiconductor_cycle": (
            f"2023년 대비 한국 주가지수는 {endpoint(korea_index) - 100.0:.0f}%, 미국 "
            f"반도체는 {endpoint(sox_index) - 100.0:.0f}% 상승했습니다. 두 시장 모두 "
            "AI·반도체 사이클 의존도가 높아 글로벌 반도체 조정에 민감한 구간입니다."
        ),
        "housing_manufacturing_warning": (
            f"주택착공은 {housing_now:+.1f}%로 약하지만 제조업지수는 "
            f"{manufacturing_now:.1f}로 확장 신호입니다. 현재 침체 신호는 한 방향으로 "
            "모이지 않은 혼합 상태입니다."
            if housing_now < 0 < manufacturing_now else
            "주택과 제조업 신호가 같은 방향으로 약해져 경기 둔화 경계가 커졌습니다."
        ),
        "household_balance_sheet_trend_gap": (
            f"장기 추세 대비 주식은 {endpoint(equity_gap):+.0f}%, 현금은 "
            f"{endpoint(cash_gap):+.0f}%, 채권은 {endpoint(debt_gap):+.0f}%입니다. "
            "유동성 고갈은 아니지만 주식의 추세 이탈이 가장 커 조정 민감도가 높습니다."
        ),
    }
    missing_conclusions = sorted(set(by_id) - set(current_conclusions))
    if missing_conclusions:
        raise StatisticsLabError(
            f"customer conclusion missing for charts: {missing_conclusions}"
        )
    for chart_id, conclusion in current_conclusions.items():
        by_id[chart_id]["conclusion"] = conclusion

    source_meta: list[dict[str, Any]] = []
    for series_id, spec in FRED_SERIES.items():
        rows = source_rows[series_id]
        start = spec.get("window_start", "1995-01-01")
        source_meta.append({
            "series_id": series_id, **spec,
            "source_url": f"https://fred.stlouisfed.org/series/{series_id}",
            "request_url": fred_api.observations_public_url(
                series_id, observation_start=start,
            ),
            "authority_class": "authoritative_public_distributor",
            "policy_source_id": "fred_market_signals",
            "usage_role": "numeric_input", "numeric_input_allowed": True,
            "available_at": receipts[series_id].get("available_at", generated_at),
            "latest_observation": rows[-1]["date"], "row_count": len(rows),
            "raw_sha256": receipts[series_id]["raw_sha256"],
            "raw_path": receipts[series_id].get("raw_path"),
            "vintage": receipts[series_id].get("vintage", "current_release_reconstructed"),
        })
    sec_spec = SUPPLEMENTAL_SOURCES["SEC_IPO_QUARTERLY"]
    sec_receipt = receipts["SEC_IPO_QUARTERLY"]
    source_meta.append({
        "series_id": "SEC_IPO_QUARTERLY", **sec_spec,
        "authority_class": "official_regulator", "policy_source_id": "sec_edgar",
        "usage_role": "numeric_input",
        "numeric_input_allowed": True,
        "available_at": sec_receipt.get("available_at", generated_at),
        "latest_observation": max(str(row["date"]) for row in sec_rows),
        "row_count": len(sec_rows), "raw_sha256": sec_receipt["raw_sha256"],
        "raw_path": sec_receipt.get("raw_path"),
        "vintage": sec_receipt.get("vintage", "current_public_release_reconstructed"),
    })
    for z1_series_id, z1_spec in Z1_SERIES.items():
        z1_rows = source_rows[z1_series_id]
        z1_receipt = receipts[z1_series_id]
        z1_meta = {
            "series_id": z1_series_id, "title": z1_spec["title"],
            "provider": "Board of Governors of the Federal Reserve System (US)",
            "unit": z1_spec["unit"], "native_frequency": "quarterly",
            "source_url": "https://www.federalreserve.gov/releases/z1/current/",
            "request_url": Z1_ENDPOINT,
            "authority_class": "official_statistical_agency",
            "policy_source_id": "federal_reserve_board", "usage_role": "numeric_input",
            "numeric_input_allowed": True,
            "available_at": z1_receipt.get("available_at", generated_at),
            "latest_observation": z1_rows[-1]["date"], "row_count": len(z1_rows),
            "raw_sha256": z1_receipt["raw_sha256"],
            "raw_path": z1_receipt.get("raw_path"),
            "vintage": z1_receipt.get("vintage", "current_release_reconstructed"),
        }
        if z1_spec.get("proxy_warning"):
            z1_meta["proxy_warning"] = z1_spec["proxy_warning"]
        source_meta.append(z1_meta)
    for c30_series_id, c30_spec in CENSUS_C30_SERIES.items():
        c30_rows = source_rows[c30_series_id]
        c30_receipt = receipts[c30_series_id]
        c30_meta = {
            "series_id": c30_series_id, "title": c30_spec["title"],
            "provider": "U.S. Census Bureau",
            "unit": c30_spec["unit"], "native_frequency": "monthly",
            "source_url": "https://www.census.gov/construction/c30/c30index.html",
            "request_url": CENSUS_C30_ENDPOINT,
            "authority_class": "official_statistical_agency",
            "policy_source_id": "census", "usage_role": "numeric_input",
            "numeric_input_allowed": True,
            "available_at": c30_receipt.get("available_at", generated_at),
            "latest_observation": c30_rows[-1]["date"], "row_count": len(c30_rows),
            "raw_sha256": c30_receipt["raw_sha256"],
            "raw_path": c30_receipt.get("raw_path"),
            "vintage": c30_receipt.get("vintage", "current_release_reconstructed"),
        }
        if c30_spec.get("history_note"):
            c30_meta["history_note"] = c30_spec["history_note"]
        source_meta.append(c30_meta)
    observation_through = max(row["latest_observation"] for row in source_meta)
    payload = {
        "schema_version": 1, "dataset_id": "dotcom_statistics_lab_v1", "status": "ok",
        "probability_space": "reference_only", "model_use": False,
        "official_forecast_input": False, "generated_at": generated_at,
        "knowledge_cutoff": generated_at,
        "observation_through": observation_through,
        "as_of": observation_through,
        "cycle_alignment": {
            "dotcom_start": DOTCOM_START.isoformat(), "dotcom_end": DOTCOM_END.isoformat(),
            "current_start": CURRENT_START.isoformat(), "current_axis_end": CURRENT_AXIS_END.isoformat(),
            "comparison_months": comparison_months,
            "current_observed_through": monthly["NASDAQCOM"][-1]["date"],
            "current_line_policy": "actual_observations_only_no_forecast_extension",
            "forecast_extension": False, "endpoint_forcing": False,
        },
        "charts": charts, "sources": source_meta, "ipo_comparison": None,
        "numeric_source_policy": {
            "reports_and_media": "insight_only", "raw_required_before_derive": True,
            "published_chart_sources": "authoritative_only",
        },
        "vintage_warning": "latest-release reconstructed history; not valid as a historical point-in-time model input",
        "refresh_policy": {"check_cadence": "weekly", "native_frequencies_preserved": True, "schedule": "Saturday 00:20 UTC"},
        "excluded_sources": {
            "research_reports": "insight_only_not_numeric_input",
            "Yahoo_Finance": "disabled_for_statistics_numeric_input",
            "NYU_SP500_history": "insight_only_not_numeric_input",
            "manual_NAHB_snapshot": "replaced_by_Census_HOUST",
        },
    }
    if ipo_reference is not None:
        reference_statistics = _build_ipo_reference_statistics(
            ipo_reference, source_rows["SEC_IPO_QUARTERLY"],
        )
        if reference_statistics is not None:
            payload["reference_statistics"] = reference_statistics
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
        if (
            not chart.get("insight")
            or not chart.get("conclusion")
            or not chart.get("source_ids")
            or (not projected and not chart.get("caveat"))
        ):
            raise StatisticsLabError(
                f"chart {chart.get('id')} missing insight/conclusion/caveat/source"
            )
        if str(chart["insight"]).strip() == str(chart["conclusion"]).strip():
            raise StatisticsLabError(
                f"chart {chart.get('id')} insight and current conclusion must be distinct"
            )
        for series in chart.get("series", []):
            periods = [int(point["period"]) for point in series.get("points", [])]
            values = [float(point["value"]) for point in series.get("points", [])]
            if not periods or periods != sorted(set(periods)):
                raise StatisticsLabError(f"chart {chart['id']} periods invalid")
            if not all(math.isfinite(value) for value in values):
                raise StatisticsLabError(f"chart {chart['id']} has non-finite values")
            if chart.get("scale") == "log1p" and any(value < 0 for value in values):
                raise StatisticsLabError(f"chart {chart['id']} log1p values must be non-negative")
            period_limit = int(chart.get("max_period", COMPARISON_MONTHS))
            if max(periods) > period_limit:
                raise StatisticsLabError(
                    f"chart {chart['id']} exceeds its declared period axis"
                )
    sources = payload.get("sources")
    minimum_sources = len(FRED_SERIES) + len(SUPPLEMENTAL_SOURCES) + 1
    if not isinstance(sources, list) or len(sources) < minimum_sources:
        raise StatisticsLabError("statistics source registry incomplete")
    source_ids = [str(row.get("series_id")) for row in sources]
    if len(source_ids) != len(set(source_ids)):
        raise StatisticsLabError("statistics source ids must be unique")
    known_sources = set(source_ids)
    if not set(SUPPLEMENTAL_SOURCES).issubset(known_sources):
        raise StatisticsLabError("supplemental public source registry incomplete")
    from .authoritative_statistics import (
        SourcePolicyViolation,
        load_authoritative_source_policy,
        validate_numeric_metric_lineage,
    )
    policy = load_authoritative_source_policy(
        Path(__file__).resolve().parents[2]
        / "data/contracts/authoritative_statistics_sources.yaml"
    )
    policy_source_by_series = {
        str(row["series_id"]): str(row.get("policy_source_id") or "")
        for row in sources
    }
    try:
        generated_at = datetime.fromisoformat(str(payload["generated_at"]).replace("Z", "+00:00"))
        knowledge_cutoff = datetime.fromisoformat(
            str(payload["knowledge_cutoff"]).replace("Z", "+00:00")
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise StatisticsLabError("statistics generated_at/knowledge_cutoff invalid") from exc
    if (
        generated_at.tzinfo is None
        or knowledge_cutoff.tzinfo is None
        or knowledge_cutoff != generated_at
    ):
        raise StatisticsLabError("statistics knowledge_cutoff contract invalid")
    if payload.get("observation_through") != payload.get("as_of"):
        raise StatisticsLabError("statistics observation_through/as_of contract invalid")
    for row in sources:
        if row.get("usage_role") != "numeric_input":
            raise StatisticsLabError(f"source {row.get('series_id')} numeric role invalid")
        if row.get("numeric_input_allowed") is not True:
            raise StatisticsLabError(f"source {row.get('series_id')} is not approved for numbers")
        if row.get("authority_class") not in {
            "authoritative_public_distributor", "official_regulator",
            "official_statistical_agency",
        }:
            raise StatisticsLabError(f"source {row.get('series_id')} authority invalid")
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
        if latest_observation > knowledge_cutoff.date() or available_at > knowledge_cutoff:
            raise StatisticsLabError(f"source {row.get('series_id')} future-data leakage")
    for chart in charts:
        if not set(chart.get("source_ids") or []).issubset(known_sources):
            raise StatisticsLabError(f"chart {chart.get('id')} has unknown source")
        if chart.get("metric_source_ids") != chart.get("source_ids"):
            raise StatisticsLabError(f"chart {chart.get('id')} numeric lineage invalid")
        if chart.get("research_context_source_ids"):
            raise StatisticsLabError(
                f"chart {chart.get('id')} mixes research context into numeric lineage"
            )
        try:
            validate_numeric_metric_lineage(
                policy,
                metric_id=str(chart.get("id")),
                source_ids=list(dict.fromkeys(
                    policy_source_by_series[source_id] for source_id in chart["source_ids"]
                )),
            )
        except (KeyError, SourcePolicyViolation) as exc:
            raise StatisticsLabError(
                f"chart {chart.get('id')} failed authoritative source policy"
            ) from exc
        scope_note = str(chart.get("scope_note") or "")
        if (
            not scope_note.startswith("*")
            or len(scope_note) > 48
            or "출처" in scope_note
            or "http" in scope_note.lower()
        ):
            raise StatisticsLabError(
                f"chart {chart.get('id')} scope note must be a short market boundary"
            )
    by_id = {str(chart.get("id")): chart for chart in charts}
    for retired_id in (
        "ici_weekly_equity_etf_flow",
        "negative_then_strong_quarter_followthrough",
        "gold_vs_us_m2",
        "nasdaq_tech_cycle_milestones",
        "kospi_market_breadth_2026_daily",
    ):
        if retired_id in by_id:
            raise StatisticsLabError(f"retired customer chart still active: {retired_id}")
    for log_chart_id in ("m2_nasdaq",):
        if (by_id.get(log_chart_id) or {}).get("scale") != "log1p":
            raise StatisticsLabError(f"chart {log_chart_id} must use log1p display")
    sec_mix = by_id.get("sec_ipo_issuer_mix_h1") or {}
    if sec_mix.get("chart_type") != "stacked_bar":
        raise StatisticsLabError("SEC issuer mix must use a stacked count chart")
    if not projected:
        household_gap = by_id.get("household_balance_sheet_trend_gap") or {}
        trend_baseline = household_gap.get("trend_baseline") or {}
        if trend_baseline.get("training_observations") != {
            "corporate_equities": 44,
            "cash_and_deposits": 44,
            "debt_securities": 11,
        }:
            raise StatisticsLabError("household trend baseline frequencies invalid")
    pulse = by_id.get("korea_semiconductor_cycle") or {}
    if pulse.get("source_ids") != ["SPASTT01KRM661N", "NASDAQSOX"]:
        raise StatisticsLabError("Korea semiconductor cycle sources invalid")
    liquidity_map = by_id.get("liquidity_position_map") or {}
    if liquidity_map.get("chart_type") != "liquidity_bars":
        raise StatisticsLabError("liquidity position map must use dedicated bars")
    if liquidity_map.get("source_ids") != [
        "BOGZ1LM893064105Q", "FGDSLAQ027S", "TSDABSHNO", "CDCABSHNO",
        "M2SL", "MMMFFAQ027S", "BOGZ1FL153064235Q", "SP500",
        "NASDAQCOM", "CBBTCUSD", "IQ12260",
    ]:
        raise StatisticsLabError("liquidity position map sources invalid")
    liquidity_panels = liquidity_map.get("liquidity_panels") or []
    if [panel.get("mode") for panel in liquidity_panels] != [
        "positive", "diverging",
    ]:
        raise StatisticsLabError("liquidity position map panel modes invalid")
    if [panel.get("id") for panel in liquidity_panels] != [
        "current_scale", "trailing_change",
    ]:
        raise StatisticsLabError("liquidity position map panel order invalid")
    reference_statistics = payload.get("reference_statistics")
    if reference_statistics is not None:
        _validate_ipo_reference_statistics(
            reference_statistics, allow_legacy_single=not projected,
        )


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


def _persist_authoritative_inputs(
    root: Path, *, source_rows: dict[str, list[dict[str, Any]]],
    raw_payloads: dict[str, bytes], receipts: dict[str, dict[str, Any]],
    fetched_at: str, source_uris: dict[str, str] | None = None,
) -> list[Any]:
    """Persist raw bytes first and prepare only new/revised ledger observations."""
    from .authoritative_statistics import (
        NormalizedObservation,
        append_raw_receipt_correction,
        load_authoritative_source_policy,
        persist_raw_artifact,
        read_raw_artifact_receipts,
        read_raw_receipt_corrections,
        read_normalized_observations,
    )

    store_root = root / "data/statistics/official_store"
    policy_path = root / "data/contracts/authoritative_statistics_sources.yaml"
    if not policy_path.is_file():
        policy_path = (
            Path(__file__).resolve().parents[2]
            / "data/contracts/authoritative_statistics_sources.yaml"
        )
    policy = load_authoritative_source_policy(policy_path)
    source_policy: dict[str, tuple[str, str, str]] = {}
    for series_id, spec in FRED_SERIES.items():
        start = spec.get("window_start", "1995-01-01")
        source_policy[series_id] = (
            "fred_market_signals",
            fred_api.observations_public_url(
                series_id, observation_start=start,
            ),
            "text/csv",
        )
    source_policy["SEC_IPO_QUARTERLY"] = (
        "sec_edgar", SEC_IPO_ENDPOINT, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    for z1_series_id in Z1_SERIES:
        source_policy[z1_series_id] = (
            "federal_reserve_board", Z1_ENDPOINT, "application/zip",
        )
    for c30_series_id in CENSUS_C30_SERIES:
        source_policy[c30_series_id] = (
            "census", CENSUS_C30_ENDPOINT,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    receipt_models: dict[str, Any] = {}
    for series_id, raw in raw_payloads.items():
        policy_source_id, default_source_uri, media_type = source_policy[series_id]
        source_uri = (source_uris or {}).get(series_id, default_source_uri)
        declared_series = [series_id]
        if series_id == Z1_PRIMARY_SERIES:
            declared_series = list(Z1_SERIES)
        if series_id == CENSUS_C30_PRIMARY_SERIES:
            declared_series = list(CENSUS_C30_SERIES)
        if series_id == "SEC_IPO_QUARTERLY":
            declared_series = [
                f"SEC_IPO_QUARTERLY.{field}"
                for field in (
                    "total_count", "us_count", "non_us_count", "corporate_count",
                    "spac_count", "fund_count", "total_proceeds_mn",
                    "corporate_proceeds_mn", "spac_proceeds_mn", "fund_proceeds_mn",
                )
            ]
        receipt = persist_raw_artifact(
            store_root, policy, source_id=policy_source_id, payload=raw,
            source_uri=source_uri, fetched_at=fetched_at, http_status=200,
            media_type=media_type, series_ids=declared_series,
        )
        receipt_models[series_id] = receipt
        receipts[series_id].update({
            "raw_sha256": receipt.raw_sha256,
            "raw_path": f"data/statistics/official_store/{receipt.artifact_path}",
            "available_at": fetched_at,
            "receipt_id": receipt.receipt_id,
        })

    z1_receipt_model = receipt_models.get(Z1_PRIMARY_SERIES)
    if z1_receipt_model is not None:
        for z1_series_id in Z1_SERIES:
            if z1_series_id == Z1_PRIMARY_SERIES:
                continue
            receipt_models[z1_series_id] = z1_receipt_model
            receipts[z1_series_id].update(receipts[Z1_PRIMARY_SERIES])

    c30_receipt_model = receipt_models.get(CENSUS_C30_PRIMARY_SERIES)
    if c30_receipt_model is not None:
        for c30_series_id in CENSUS_C30_SERIES:
            if c30_series_id == CENSUS_C30_PRIMARY_SERIES:
                continue
            receipt_models[c30_series_id] = c30_receipt_model
            receipts[c30_series_id].update(receipts[CENSUS_C30_PRIMARY_SERIES])

    current_sec_receipt = receipt_models.get("SEC_IPO_QUARTERLY")
    if (
        current_sec_receipt is not None
        and current_sec_receipt.source_uri != SEC_IPO_ENDPOINT
    ):
        corrected_receipt_ids = {
            correction.supersedes_receipt_id
            for correction in read_raw_receipt_corrections(store_root)
        }
        for prior_receipt in read_raw_artifact_receipts(store_root):
            if (
                prior_receipt.source_id == "sec_edgar"
                and prior_receipt.source_uri == SEC_IPO_ENDPOINT
                and prior_receipt.raw_sha256 == current_sec_receipt.raw_sha256
                and prior_receipt.receipt_id != current_sec_receipt.receipt_id
                and prior_receipt.receipt_id not in corrected_receipt_ids
            ):
                append_raw_receipt_correction(
                    store_root,
                    supersedes_receipt_id=prior_receipt.receipt_id,
                    replacement_receipt_id=current_sec_receipt.receipt_id,
                    reason="replace SEC landing-page URI with the exact downloaded workbook URI",
                    corrected_at=fetched_at,
                )

    existing = read_normalized_observations(store_root)
    latest_by_key: dict[tuple[str, str, str], Any] = {}
    for row in existing:
        key = (row.source_id, row.series_id, row.observation_date)
        prior = latest_by_key.get(key)
        if prior is None or row.revision_seq > prior.revision_seq:
            latest_by_key[key] = row

    def semantic_type(unit: str) -> str:
        if "percent" in unit or unit in {"net_percent"}:
            return "rate"
        if "usd" in unit or "dollar" in unit:
            return "currency"
        if "count" in unit:
            return "count"
        if "index" in unit or unit in {"standard_deviation_index"}:
            return "index"
        if "ratio" in unit or "multiple" in unit:
            return "ratio"
        return "level"

    candidates: list[Any] = []
    vintage_date = datetime.fromisoformat(fetched_at.replace("Z", "+00:00")).date().isoformat()

    def add_candidate(
        *, policy_source_id: str, series_id: str, observed: str,
        value: Any, unit: str, raw_sha256: str,
    ) -> None:
        value_text = format(float(value), ".15g")
        key = (policy_source_id, series_id, observed)
        prior = latest_by_key.get(key)
        candidate_semantic_type = semantic_type(unit)
        if (
            prior is not None
            and prior.raw_value == value_text
            and prior.value == value_text
            and prior.raw_unit == unit
            and prior.unit == unit
            and prior.semantic_type == candidate_semantic_type
            and prior.transformation_id == "identity"
            and prior.transformation_formula is None
        ):
            # A new fetch remains preserved in the raw receipt ledger above, but
            # receipt identity is not an observation revision.  Only a change in
            # the normalized value, unit, or semantic transformation supersedes
            # the prior observation.
            return
        revision_seq = 0 if prior is None else prior.revision_seq + 1
        candidate = NormalizedObservation(
            source_id=policy_source_id, series_id=series_id,
            observation_date=observed, vintage_date=vintage_date,
            revision_seq=revision_seq, available_at=fetched_at, fetched_at=fetched_at,
            raw_value=value_text, value=value_text, raw_unit=unit, unit=unit,
            semantic_type=candidate_semantic_type, transformation_id="identity",
            parser_version="statistics-official-v1", raw_sha256=raw_sha256,
            supersedes_observation_id=None if prior is None else prior.observation_id,
        )
        candidates.append(candidate)
        latest_by_key[key] = candidate

    for series_id, spec in FRED_SERIES.items():
        receipt = receipt_models[series_id]
        for row in source_rows[series_id]:
            add_candidate(
                policy_source_id="fred_market_signals", series_id=series_id,
                observed=str(row["date"]), value=row["value"], unit=spec["unit"],
                raw_sha256=receipt.raw_sha256,
            )
    for z1_series_id, z1_spec in Z1_SERIES.items():
        z1_receipt = receipt_models[z1_series_id]
        for row in source_rows[z1_series_id]:
            add_candidate(
                policy_source_id="federal_reserve_board", series_id=z1_series_id,
                observed=str(row["date"]), value=row["value"], unit=z1_spec["unit"],
                raw_sha256=z1_receipt.raw_sha256,
            )
    for c30_series_id, c30_spec in CENSUS_C30_SERIES.items():
        c30_receipt = receipt_models[c30_series_id]
        for row in source_rows[c30_series_id]:
            add_candidate(
                policy_source_id="census", series_id=c30_series_id,
                observed=str(row["date"]), value=row["value"], unit=c30_spec["unit"],
                raw_sha256=c30_receipt.raw_sha256,
            )
    sec_receipt = receipt_models["SEC_IPO_QUARTERLY"]
    sec_units = {
        "total_count": "count", "us_count": "count", "non_us_count": "count",
        "corporate_count": "count", "spac_count": "count", "fund_count": "count",
        "total_proceeds_mn": "millions_usd", "corporate_proceeds_mn": "millions_usd",
        "spac_proceeds_mn": "millions_usd", "fund_proceeds_mn": "millions_usd",
    }
    for row in source_rows["SEC_IPO_QUARTERLY"]:
        for field, unit in sec_units.items():
            add_candidate(
                policy_source_id="sec_edgar", series_id=f"SEC_IPO_QUARTERLY.{field}",
                observed=str(row["date"]), value=row[field], unit=unit,
                raw_sha256=sec_receipt.raw_sha256,
            )
    return candidates


def _load_authoritative_current_rows(root: Path) -> dict[str, list[dict[str, Any]]]:
    """Rebuild the current read model exclusively from the append-only ledger."""
    from .authoritative_statistics import read_normalized_observations

    store_root = root / "data/statistics/official_store"
    observations = read_normalized_observations(store_root)
    latest: dict[tuple[str, str, str], Any] = {}
    for row in observations:
        key = (row.source_id, row.series_id, row.observation_date)
        prior = latest.get(key)
        if prior is None or row.revision_seq > prior.revision_seq:
            latest[key] = row

    rows: dict[str, list[dict[str, Any]]] = {series_id: [] for series_id in FRED_SERIES}
    for z1_series_id in Z1_SERIES:
        rows[z1_series_id] = []
    for c30_series_id in CENSUS_C30_SERIES:
        rows[c30_series_id] = []
    sec_by_date: dict[str, dict[str, Any]] = {}
    for row in latest.values():
        if row.source_id == "fred_market_signals" and row.series_id in FRED_SERIES:
            rows[row.series_id].append({
                "date": row.observation_date,
                "value": float(row.value),
            })
        elif row.source_id == "federal_reserve_board" and row.series_id in Z1_SERIES:
            rows[row.series_id].append({
                "date": row.observation_date,
                "value": float(row.value),
            })
        elif row.source_id == "census" and row.series_id in CENSUS_C30_SERIES:
            rows[row.series_id].append({
                "date": row.observation_date,
                "value": float(row.value),
            })
        elif row.source_id == "sec_edgar" and row.series_id.startswith("SEC_IPO_QUARTERLY."):
            field = row.series_id.split(".", 1)[1]
            observed = date.fromisoformat(row.observation_date)
            sec_row = sec_by_date.setdefault(row.observation_date, {
                "date": row.observation_date,
                "period_label": f"{observed.year}:Q{((observed.month - 1) // 3) + 1}",
            })
            sec_row[field] = float(row.value)

    rows["SEC_IPO_QUARTERLY"] = list(sec_by_date.values())
    required = [*FRED_SERIES, *Z1_SERIES, *CENSUS_C30_SERIES, "SEC_IPO_QUARTERLY"]
    missing = [series_id for series_id in required if not rows.get(series_id)]
    if missing:
        raise StatisticsLabError(
            "authoritative ledger current view is missing series: " + ", ".join(missing)
        )
    for series_rows in rows.values():
        series_rows.sort(key=lambda item: str(item["date"]))
    return rows


def refresh_statistics_lab(
    root: Path, *,
    fred_fetcher: Callable[[str], tuple[list[dict[str, Any]], bytes]] = _fetch_fred,
    market_fetcher: Callable[
        [str, date, date], tuple[list[dict[str, Any]], dict[str, Any]]
    ] = _fetch_daily_market,
    supplemental_fetcher: Callable[
        [str],
        tuple[list[dict[str, Any]], bytes]
        | tuple[list[dict[str, Any]], bytes, str],
    ] = _fetch_supplemental,
    z1_fetcher: Callable[[str], bytes] | None = None,
    census_c30_fetcher: Callable[[str], bytes] | None = None,
    now: datetime | None = None,
) -> tuple[Path, dict[str, Any], bool]:
    generated_time = now or datetime.now(timezone.utc)
    generated_at = generated_time.isoformat(timespec="seconds")
    source_rows: dict[str, list[dict[str, Any]]] = {}
    receipts: dict[str, dict[str, Any]] = {}
    raw_payloads: dict[str, bytes] = {}
    source_uris: dict[str, str] = {}
    for series_id in FRED_SERIES:
        rows, raw = fred_fetcher(series_id)
        source_rows[series_id] = rows
        receipts[series_id] = {"raw_sha256": hashlib.sha256(raw).hexdigest()}
        raw_payloads[series_id] = raw
    # ``market_fetcher`` is retained in the public signature for compatible
    # callers, but authoritative statistics no longer consume Yahoo/aggregator
    # chart responses.
    del market_fetcher
    for series_id in SUPPLEMENTAL_SOURCES:
        fetched = supplemental_fetcher(series_id)
        if len(fetched) == 3:
            rows, raw, resolved_source_uri = fetched
            source_uris[series_id] = resolved_source_uri
        else:
            rows, raw = fetched
        source_rows[series_id] = rows
        receipts[series_id] = {"raw_sha256": hashlib.sha256(raw).hexdigest()}
        raw_payloads[series_id] = raw
    fetch_z1 = z1_fetcher or (lambda url: _request(url, timeout=60))
    z1_raw = fetch_z1(Z1_ENDPOINT)
    z1_digest = hashlib.sha256(z1_raw).hexdigest()
    for z1_series_id in Z1_SERIES:
        source_rows[z1_series_id] = _parse_z1(z1_raw, z1_series_id)
        receipts[z1_series_id] = {"raw_sha256": z1_digest}
    # One archive, one raw artifact: the receipt declares every series it covers,
    # mirroring how the SEC IPO workbook declares its subseries.
    raw_payloads[Z1_PRIMARY_SERIES] = z1_raw
    fetch_c30 = census_c30_fetcher or (lambda url: _request(url, timeout=90))
    c30_raw = fetch_c30(CENSUS_C30_ENDPOINT)
    c30_digest = hashlib.sha256(c30_raw).hexdigest()
    for c30_series_id in CENSUS_C30_SERIES:
        source_rows[c30_series_id] = _parse_census_c30(c30_raw, c30_series_id)
        receipts[c30_series_id] = {"raw_sha256": c30_digest}
    raw_payloads[CENSUS_C30_PRIMARY_SERIES] = c30_raw
    pending_observations = _persist_authoritative_inputs(
        root, source_rows=source_rows, raw_payloads=raw_payloads,
        receipts=receipts, fetched_at=generated_at, source_uris=source_uris,
    )
    from .authoritative_statistics import (
        append_normalized_observations,
        load_authoritative_source_policy,
    )
    append_normalized_observations(
        root / "data/statistics/official_store",
        load_authoritative_source_policy(
            (root / "data/contracts/authoritative_statistics_sources.yaml")
            if (root / "data/contracts/authoritative_statistics_sources.yaml").is_file()
            else Path(__file__).resolve().parents[2]
            / "data/contracts/authoritative_statistics_sources.yaml"
        ),
        pending_observations,
    )
    canonical_rows = _load_authoritative_current_rows(root)
    payload = build_statistics_lab(
        canonical_rows,
        generated_at=generated_at,
        receipts=receipts,
        ipo_reference=(
            load_ipo_reference(root)
            if (root / IPO_REFERENCE_RELATIVE).is_file()
            else None
        ),
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
            "knowledge_cutoff": None,
            "observation_through": None,
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
        if key not in {"charts", "ipo_comparison", "reference_statistics"}
    }
    projected["display_projection"] = True
    public_source_keys = {
        "series_id", "title", "provider", "source_url",
        "native_frequency", "latest_observation", "authority_class",
        "usage_role", "numeric_input_allowed",
        "policy_source_id",
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
                "description", "caveat", "trend_baseline", "projection_max_points",
                "external_pulse_diagnostics",
                "comparison_transform", "source_validation",
                "scenario_sensitivity", "event_diagnostics",
            }
        }
        for diagnostics_key in ("external_pulse_diagnostics",):
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
    reference_statistics = payload.get("reference_statistics")
    if (root / IPO_REFERENCE_RELATIVE).is_file():
        canonical_rows = _load_authoritative_current_rows(root)
        reference_statistics = _build_ipo_reference_statistics(
            load_ipo_reference(root), canonical_rows["SEC_IPO_QUARTERLY"],
        )
    if reference_statistics is not None:
        projected["reference_statistics"] = deepcopy(reference_statistics)
        _validate_ipo_reference_statistics(projected["reference_statistics"])
    validate_statistics_lab(projected, projected=True)
    return projected
