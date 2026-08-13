from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import statistics
import time
import urllib.error
import urllib.request
import zipfile
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable


LATEST_RELATIVE = Path("data/statistics/dotcom_statistics_latest.json")
ARCHIVE_RELATIVE = Path("data/statistics/archive")
CONTRACT_RELATIVE = Path("data/contracts/statistics_lab_v1.yaml")
IPO_REFERENCE_RELATIVE = Path("data/statistics/ipo/ipo_comparison_v1.json")
HMI_REFERENCE_RELATIVE = Path("data/statistics/reference/nahb_hmi_history_v1.json")
DOTCOM_START = date(1995, 1, 1)
DOTCOM_END = date(1999, 12, 31)
CURRENT_START = date(2023, 1, 1)
CURRENT_AXIS_END = date(2027, 12, 31)
COMPARISON_MONTHS = 59
FRED_ENDPOINT = "https://fred.stlouisfed.org/graph/fredgraph.csv"
Z1_ENDPOINT = "https://www.federalreserve.gov/releases/z1/current/z1_csv_files.zip"
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
    "NASDAQCOM": {
        "title": "NASDAQ Composite Index",
        "provider": "NASDAQ OMX Group via FRED",
        "unit": "index",
        "native_frequency": "daily_close",
        "aggregation": "last",
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
    "SPASTT01KRM661N": {
        "title": "Financial market share prices for Korea",
        "provider": "OECD Main Economic Indicators via FRED",
        "unit": "index_2015_100",
        "native_frequency": "monthly",
        "aggregation": "last",
    },
}


class StatisticsLabError(ValueError):
    pass


def _validate_manual_reference_freshness(
    ipo_reference: dict[str, Any], hmi_reference: dict[str, Any], generated_at: str,
) -> None:
    """Fail the weekly job instead of silently republishing stale manual cohorts."""
    collected = datetime.fromisoformat(generated_at.replace("Z", "+00:00")).date()
    checks = (
        ("IPO reviewed cohort", date.fromisoformat(str(ipo_reference["as_of"])), 14),
        ("NAHB HMI reference", date.fromisoformat(str(hmi_reference["as_of"])), 62),
    )
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
    url = f"{FRED_ENDPOINT}?id={series_id}&cosd=1995-01-01"
    raw = _request(url)
    return _parse_fred_csv(raw, series_id), raw


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
    listed_watch = qualitative.get("listed_ai_beneficiary_watchlist") or {}
    if listed_watch.get("semantics") != (
        "existing_listed_ai_beneficiaries_included_in_qualitative_capital_map_not_added_to_ipo_counts"
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
    watch_members = [*listed_members, *global_chip_members]
    watch_source_ids = {str(member.get("source_id", "")) for member in watch_members}
    classification_source_id = str(global_chip_watch.get("classification_source_id", ""))
    if not watch_source_ids.issubset(source_ids) or classification_source_id not in source_ids:
        raise StatisticsLabError("AI capital watchlist source unknown")
    if any(not member.get("name") or not member.get("role") for member in watch_members):
        raise StatisticsLabError("AI capital watchlist member identity/role missing")
    if any(not member.get("listing_date") for member in global_chip_members):
        raise StatisticsLabError("global AI chip IPO listing date missing")
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
        (series for series in comparison["series"] if series.get("label") == "현재 AI 영향력 포함 집계"), None
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
        "actual_us_ai_related_ipos_plus_explicit_existing_listed_ai_beneficiaries_not_an_ipo_count"
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


def build_statistics_lab(
    source_rows: dict[str, list[dict[str, Any]]], *, generated_at: str,
    receipts: dict[str, dict[str, Any]],
    ipo_reference: dict[str, Any] | None = None,
    hmi_reference: dict[str, Any] | None = None,
) -> dict[str, Any]:
    missing = sorted((set(FRED_SERIES) | {"FL663067003"}) - set(source_rows))
    if missing:
        raise StatisticsLabError(f"missing source series: {missing}")
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
    kospi_nasdaq_relative = _ratio(monthly["SPASTT01KRM661N"], monthly["NASDAQCOM"])
    dot_kospi_relative, cur_kospi_relative = _cycle_series(
        kospi_nasdaq_relative, comparison_months, indexed=True,
    )
    kospi_lead_diagnostics = [
        _lead_correlation(monthly["SPASTT01KRM661N"], monthly["NASDAQCOM"], lead)
        for lead in range(4)
    ]
    dot_hmi: list[dict[str, Any]] = []
    cur_hmi: list[dict[str, Any]] = []
    if hmi_reference is not None:
        hmi_rows = [
            {"date": str(row["date"]), "value": float(row["value"]) - 50.0}
            for row in hmi_reference["rows"]
        ]
        dot_hmi, cur_hmi = _cycle_series(hmi_rows, comparison_months)

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
               "닷컴기와 현재 사이클의 정책금리 수준을 비교합니다.",
               "월평균 정책금리이며 시장의 미래 인하확률과는 다른 통계입니다.",
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
        _chart("kospi_nasdaq_relative_lead", "KOSPI/NASDAQ 상대강도 · AI 경기 선행 후보", "economy", "cycle_start_100",
               "KOSPI를 NASDAQ으로 나눈 상대강도를 각 사이클 시작월=100으로 맞춥니다. KOSPI 월수익률과 같은 달·향후 1~3개월 NASDAQ 월수익률의 상관도 함께 점검합니다.",
               "상대강도 하락은 한국 주식의 선행 약세 후보일 뿐 인과관계나 확정 신호가 아닙니다. 환율·거래시간·국가위험이 섞이며, 네 시차를 모두 공개해 사후 최적 시차 선택을 막습니다.",
               [_series("닷컴 KOSPI/NASDAQ", "dotcom", dot_kospi_relative, "#8d2943"), _series("현재 KOSPI/NASDAQ", "current", cur_kospi_relative, "#28756a")], ["SPASTT01KRM661N", "NASDAQCOM"]),
    ]

    kospi_chart = charts[-1]
    kospi_chart["lead_diagnostics"] = kospi_lead_diagnostics
    kospi_chart["detail_rows"] = [
        {
            "period": "동행" if row["lead_months"] == 0 else f"{row['lead_months']}개월 선행",
            "label": f"KOSPI(t) ↔ NASDAQ(t+{row['lead_months']}) 월수익률",
            "value": (
                f"상관 {row['correlation']:+.2f} · n={row['observations']}"
                if row["correlation"] is not None else f"산출 불가 · n={row['observations']}"
            ),
        }
        for row in kospi_lead_diagnostics
    ]
    kospi_chart["research_context"] = [
        {
            "provider": "KRX",
            "finding": "KOSPI is a market-capitalization-weighted benchmark; electrical/electronic equipment is a large disclosed sector.",
            "url": "https://global.krx.co.kr/contents/GLB/03/0301/0301040000/GLB0301040000.jsp",
        },
        {
            "provider": "Bank of Korea",
            "finding": "Semiconductor export value must be separated into volume and price effects when reading the Korean cycle.",
            "url": "https://www.bok.or.kr/portal/bbs/B0000347/view.do?menuNo=201106&nttId=10094959",
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
            "금리가 높을수록 미래 이익의 할인 부담과 기업 조달비용이 커지는 방향입니다."
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
        "kospi_nasdaq_relative_lead": (
            f"현재 KOSPI/NASDAQ 상대강도는 사이클 시작 대비 {cur_kospi_relative[-1]['value']:.0f}입니다. "
            f"월수익률 상관은 동행 {kospi_lead_diagnostics[0]['correlation']:+.2f}, "
            f"KOSPI 1개월 선행 {kospi_lead_diagnostics[1]['correlation']:+.2f}, "
            f"3개월 선행 {kospi_lead_diagnostics[3]['correlation']:+.2f}로 약합니다. "
            "현재는 선행 하락 경고가 아니며, 상대강도 고점 이탈을 반도체 경기 자료와 함께 볼 때만 조기 경고 후보입니다."
        ),
    }
    if hmi_reference is not None:
        chart_insights["housing_manufacturing_warning"] = (
            f"현재 HMI는 중립선보다 {cur_hmi[-1]['value']:+.0f}p, 제조업 확산지수는 {cur_philly[-1]['value']:+.1f}입니다. "
            "둘 다 0 아래로 내려가고 하락이 이어질 때 주택과 제조업의 동시 냉각 경고가 강해집니다."
        )
    for chart in charts:
        chart["insight"] = chart_insights[chart["id"]]
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
            if spec.get("scale"):
                chart["scale"] = str(spec["scale"])
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
        listed_watch = qualitative.get("listed_ai_beneficiary_watchlist") or {}
        global_chip_watch = qualitative.get("global_ai_chip_completed_ipos") or {}
        private_total_bn = sum(float(row["valuation_bn"]) for row in private_watch.get("members") or [])
        latest_equity = total_equity_by_year.get(2026) or float(monthly["BOGZ1LM893064105Q"][-1]["value"])
        private_ratio = private_total_bn * 1000.0 / latest_equity * 100.0
        quality_chart = _chart(
            "ipo_market_absorption", "IPO와 AI 자본시장 흡수 강도", "ipo", "percent_of_us_corporate_equity_value",
            "한 해 IPO들의 첫 거래 종가 기준 상장 후 시가총액 합계를 미국 기업주식 총가치로 나눠, 건수보다 자금 규모를 비교합니다.",
            "분모는 지수 시가총액이 아니라 비상장·밀접보유분도 포함한 Fed의 미국 기업주식 총가치입니다. 비상장사·기존 상장 수혜주·중국 및 홍콩 IPO는 서로 다른 계층으로 표시하며 미국 실제 IPO선에는 합산하지 않습니다.",
            [_series("닷컴 실제 IPO", "dotcom", dot_absorption, "#c70039"), _series("현재 실제 IPO", "current", cur_absorption, "#ff6a1a"), _series("OpenAI+Anthropic 비상장 감시점", "current", [{"period": 40, "date": private_watch.get("as_of", "2026-05-28"), "value": private_ratio}], "#28756a")],
            [
                value_table.get("source_id"), "BOGZ1LM893064105Q",
                *[row["source_id"] for row in private_watch.get("members") or []],
                *[row["source_id"] for row in listed_watch.get("members") or []],
                *[row["source_id"] for row in global_chip_watch.get("members") or []],
                global_chip_watch.get("classification_source_id"),
            ],
        )
        quality_chart["insight"] = (
            f"1999년 전체 IPO 첫 거래 시가총액은 $652B, 2025년은 $442B입니다. "
            f"OpenAI와 Anthropic의 최근 비상장 평가액 합계 $1.817T는 현재 미국 기업주식 총가치의 약 {private_ratio:.1f}%지만, 이는 잠재 공급 감시선이지 완료된 IPO가 아닙니다."
        )
        quality_chart["detail_rows"] = [
            {"period": "1999", "label": "전체 비교가능 IPO", "value": "$652B · 실제 상장"},
            {"period": "2025", "label": "전체 비교가능 IPO", "value": "$442B · 실제 상장"},
            {"period": "2026", "label": "OpenAI + Anthropic", "value": "$1.817T · 비상장 평가액"},
            {"period": "질적 포함", "label": "SK하이닉스", "value": "기존 상장 · HBM·AI 메모리 핵심 수혜"},
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
        source_meta.append({
            "series_id": series_id,
            **spec,
            "source_url": f"https://fred.stlouisfed.org/series/{series_id}",
            "request_url": f"{FRED_ENDPOINT}?id={series_id}&cosd=1995-01-01",
            "available_at": generated_at,
            "latest_observation": rows[-1]["date"],
            "row_count": len(rows),
            "raw_sha256": receipts[series_id]["raw_sha256"],
            "vintage": "current_release_reconstructed",
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


def validate_statistics_lab(payload: dict[str, Any]) -> None:
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
            if max(periods) > COMPARISON_MONTHS:
                raise StatisticsLabError(f"chart {chart['id']} exceeds the five-year axis")
    sources = payload.get("sources")
    if not isinstance(sources, list) or len(sources) < len(FRED_SERIES) + 1:
        raise StatisticsLabError("statistics source registry incomplete")
    source_ids = [str(row.get("series_id")) for row in sources]
    if len(source_ids) != len(set(source_ids)):
        raise StatisticsLabError("statistics source ids must be unique")
    known_sources = set(source_ids)
    try:
        generated_at = datetime.fromisoformat(str(payload["generated_at"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError) as exc:
        raise StatisticsLabError("statistics generated_at invalid") from exc
    for row in sources:
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
    z1_fetcher: Callable[[str], bytes] | None = None,
    now: datetime | None = None,
) -> tuple[Path, dict[str, Any], bool]:
    generated_at = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    source_rows: dict[str, list[dict[str, Any]]] = {}
    receipts: dict[str, dict[str, Any]] = {}
    for series_id in FRED_SERIES:
        rows, raw = fred_fetcher(series_id)
        source_rows[series_id] = rows
        receipts[series_id] = {"raw_sha256": hashlib.sha256(raw).hexdigest()}
    fetch_z1 = z1_fetcher or (lambda url: _request(url, timeout=60))
    z1_raw = fetch_z1(Z1_ENDPOINT)
    source_rows["FL663067003"] = _parse_z1(z1_raw)
    receipts["FL663067003"] = {"raw_sha256": hashlib.sha256(z1_raw).hexdigest()}
    ipo_reference = load_ipo_reference(root)
    hmi_reference = load_hmi_reference(root)
    _validate_manual_reference_freshness(ipo_reference, hmi_reference, generated_at)
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
    public_source_keys = {
        "series_id", "title", "provider", "source_url", "request_url", "latest_observation",
        "available_at", "row_count", "vintage", "raw_sha256",
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
            if key not in {"series", "range"}
        }
        chart_view["series"] = []
        for series in chart["series"]:
            points = series.get("points") or []
            if len(points) > 18:
                stride = math.ceil((len(points) - 1) / 17)
                display_points = points[::stride]
                if display_points[-1] is not points[-1]:
                    display_points.append(points[-1])
            else:
                display_points = points
            chart_view["series"].append({
                "label": series["label"],
                "era": series["era"],
                "color": series["color"],
                "latest_date": points[-1].get("date") if points else None,
                "points": [
                    {"period": point["period"], "value": point["value"]}
                    for point in display_points
                ],
            })
        projected["charts"].append(chart_view)
    validate_statistics_lab(projected)
    return projected
