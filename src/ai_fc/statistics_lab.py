from __future__ import annotations

import csv
import hashlib
import io
import json
import math
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
}


class StatisticsLabError(ValueError):
    pass


def _request(url: str, *, timeout: int = 45) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


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
    core_series = next(
        (series for series in comparison["series"] if series.get("label") == "현재 AI 핵심 최소치"), None
    )
    if broad_series is None or core_series is None:
        raise StatisticsLabError("IPO broad/core comparison series missing")
    broad_points = {int(point["date"][:4]): int(point["value"]) for point in broad_series["points"]}
    core_points = {int(point["date"][:4]): int(point["value"]) for point in core_series["points"]}
    if broad_points != broad_counts:
        raise StatisticsLabError("IPO broad series does not reconcile to reviewed issuer cohort")
    if core_points != core_member_counts:
        raise StatisticsLabError("IPO core minimum must reconcile to marked broad-cohort members")


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


def build_statistics_lab(
    source_rows: dict[str, list[dict[str, Any]]], *, generated_at: str,
    receipts: dict[str, dict[str, Any]],
    ipo_reference: dict[str, Any] | None = None,
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

    charts = [
        _chart("m2_nasdaq", "M2와 NASDAQ의 상승 속도", "liquidity", "cycle_start_100",
               "각 사이클 시작월을 100으로 맞춰 유동성과 주가의 누적 속도를 비교합니다.",
               "M2 정의는 2020년에 바뀌었으며, 두 선의 동행은 인과관계를 뜻하지 않습니다.",
               [_series("닷컴 NASDAQ", "dotcom", dot_nasdaq, "#d42b20"), _series("닷컴 M2", "dotcom", dot_m2, "#755d35"), _series("현재 NASDAQ", "current", cur_nasdaq, "#ff6a1a"), _series("현재 M2", "current", cur_m2, "#1c7262")], ["NASDAQCOM", "M2SL"]),
        _chart("nasdaq_per_m2", "M2 한 단위 대비 NASDAQ", "liquidity", "cycle_start_100",
               "NASDAQ을 M2로 나눈 비율의 사이클 시작 대비 변화를 봅니다.",
               "가격과 통화량의 단순 비율이며 적정가치나 매수·매도 신호가 아닙니다.",
               [_series("닷컴", "dotcom", dot_liq, "#c70039"), _series("현재", "current", cur_liq, "#ff7b00")], ["NASDAQCOM", "M2SL"]),
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
    ]

    def chart_last(chart_index: int, series_index: int) -> float:
        return float(charts[chart_index]["series"][series_index]["points"][-1]["value"])

    chart_insights = {
        "m2_nasdaq": (
            f"같은 경과월에 현재 NASDAQ은 시작 대비 {chart_last(0, 2):.0f}, M2는 {chart_last(0, 3):.0f}입니다. "
            f"닷컴 당시 NASDAQ {chart_last(0, 0):.0f}, M2 {chart_last(0, 1):.0f}와 비교해 주가가 유동성보다 얼마나 앞섰는지 봅니다."
        ),
        "nasdaq_per_m2": (
            f"현재 유동성 대비 NASDAQ 지수는 {chart_last(1, 1):.0f}, 닷컴 당시 같은 구간은 {chart_last(1, 0):.0f}입니다. "
            "100보다 높을수록 통화량 증가보다 주가 상승이 더 빨랐다는 뜻입니다."
        ),
        "yield_curve": (
            f"현재 장단기 금리차는 {chart_last(2, 1):+.1f}%p, 닷컴 당시 같은 구간은 {chart_last(2, 0):+.1f}%p입니다. "
            "0 아래는 금리 역전, 0 위는 정상 기울기이며 경기 방향을 단독으로 확정하지는 않습니다."
        ),
        "policy_rate": (
            f"현재 정책금리는 {chart_last(3, 1):.1f}%, 닷컴 당시 같은 구간은 {chart_last(3, 0):.1f}%입니다. "
            "금리가 높을수록 미래 이익의 할인 부담과 기업 조달비용이 커지는 방향입니다."
        ),
        "valuation_proxy": (
            f"현재 기업가치/세후이익 대용치는 {chart_last(4, 1):.1f}배, 닷컴 당시 같은 구간은 {chart_last(4, 0):.1f}배입니다. "
            "높을수록 이익에 비해 시장가치가 비싸다는 뜻이지만 NASDAQ 공식 PER은 아닙니다."
        ),
        "margin_credit_proxy": (
            f"현재 증권담보 신용 대용치는 시작 대비 {chart_last(5, 1):.0f}, 닷컴 당시에는 {chart_last(5, 0):.0f}입니다. "
            "상승 속도가 빠를수록 레버리지 확대와 가격 충격 민감도가 커질 가능성을 뜻합니다."
        ),
        "consumer_credit_growth": (
            f"현재 소비자신용 증가율은 {chart_last(6, 1):+.1f}%, 닷컴 당시 같은 구간은 {chart_last(6, 0):+.1f}%입니다. "
            "빠른 증가는 소비를 지지할 수 있지만 동시에 가계 부채 부담도 키웁니다."
        ),
        "loan_standards": (
            f"현재 대출기준 강화 응답은 {chart_last(7, 1):+.1f}%, 닷컴 당시 같은 구간은 {chart_last(7, 0):+.1f}%입니다. "
            "양수와 상승은 더 많은 은행이 대출을 조인다는 뜻이고, 음수는 완화 쪽입니다."
        ),
        "profit_growth": (
            f"현재 세후 기업이익 증가율은 {chart_last(8, 1):+.1f}%, 닷컴 당시 같은 구간은 {chart_last(8, 0):+.1f}%입니다. "
            "이익이 늘면 밸류에이션을 지지하지만 주가가 이익보다 빨리 오르면 부담은 다시 커집니다."
        ),
        "household_debt_service": (
            f"현재 가계 원리금 부담은 가처분소득의 {chart_last(9, 1):.1f}%, 닷컴 당시 같은 구간은 {chart_last(9, 0):.1f}%입니다. "
            "높을수록 금리와 부채가 소비 여력을 더 많이 잠식한다는 뜻입니다."
        ),
        "unemployment_rate": (
            f"현재 실업률은 {chart_last(10, 1):.1f}%, 닷컴 당시 같은 구간은 {chart_last(10, 0):.1f}%입니다. "
            "상승하면 고용 냉각 신호지만 금리 인하 기대와 성장 둔화를 함께 봐야 합니다."
        ),
        "inflation_rate": (
            f"현재 CPI 상승률은 {chart_last(11, 1):+.1f}%, 닷컴 당시 같은 구간은 {chart_last(11, 0):+.1f}%입니다. "
            "낮아지면 금리 부담 완화 여지가 커지지만 수요 둔화가 원인인지도 확인해야 합니다."
        ),
        "financial_conditions": (
            f"현재 NFCI는 {chart_last(12, 1):+.2f}, 닷컴 당시 같은 구간은 {chart_last(12, 0):+.2f}입니다. "
            "0 아래는 평균보다 완화적, 0 위는 긴축적이어서 시장이 받는 자금 압력을 직관적으로 보여줍니다."
        ),
    }
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
        charts = ipo_charts + charts

    source_meta = []
    for series_id, spec in FRED_SERIES.items():
        rows = source_rows[series_id]
        source_meta.append({
            "series_id": series_id,
            **spec,
            "source_url": f"https://fred.stlouisfed.org/series/{series_id}",
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
        "available_at": generated_at,
        "latest_observation": z1_rows[-1]["date"],
        "row_count": len(z1_rows),
        "raw_sha256": receipts["FL663067003"]["raw_sha256"],
        "vintage": "current_release_reconstructed",
        "proxy_warning": "not_FINRA_monthly_margin_debt",
    })
    if ipo_reference is not None:
        source_meta.extend(ipo_reference["sources"])
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
    for row in sources:
        digest = str(row.get("raw_sha256", ""))
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise StatisticsLabError(f"source {row.get('series_id')} hash invalid")
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
) -> tuple[Path, dict[str, Any], bool]:
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
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
    payload = build_statistics_lab(
        source_rows,
        generated_at=generated_at,
        receipts=receipts,
        ipo_reference=load_ipo_reference(root),
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
        "series_id", "title", "provider", "source_url", "latest_observation",
        "row_count", "vintage", "raw_sha256",
    }
    projected["sources"] = [
        {key: value for key, value in source.items() if key in public_source_keys}
        for source in payload["sources"]
    ]
    projected["charts"] = []
    for chart in payload["charts"]:
        chart_view = {key: value for key, value in chart.items() if key != "series"}
        chart_view["series"] = []
        for series in chart["series"]:
            points = series.get("points") or []
            if len(points) > 20:
                stride = math.ceil((len(points) - 1) / 19)
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
