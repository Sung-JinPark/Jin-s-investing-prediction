from __future__ import annotations

import hashlib
import html
import io
import json
import math
import urllib.error
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from ai_fc.authoritative_statistics import (
    append_normalized_observations,
    load_authoritative_source_policy,
    persist_raw_artifact,
    read_normalized_observations,
    read_raw_artifact_receipts,
    read_raw_receipt_corrections,
)
from ai_fc.statistics_lab import (
    DAILY_MARKET_SERIES,
    FRED_ENDPOINT,
    FRED_SERIES,
    IPO_REFERENCE_CHART_IDS,
    StatisticsLabError,
    _fetch_fred,
    _fetch_supplemental,
    _parse_fred_csv,
    _parse_ici_weekly_html,
    _parse_nyu_returns_xlsx,
    _parse_sec_ipo_xlsx,
    _parse_z1,
    _persist_authoritative_inputs,
    _request,
    _validate_manual_reference_freshness,
    build_statistics_lab,
    load_ipo_reference,
    load_hmi_reference,
    load_statistics_lab,
    refresh_statistics_lab,
    statistics_dashboard_projection,
    validate_ipo_reference,
    validate_statistics_lab,
)


class _Response:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


def test_public_request_retries_only_transient_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []
    sleeps: list[int] = []

    def flaky(*_args: object, **_kwargs: object) -> _Response:
        calls.append(1)
        if len(calls) < 3:
            raise TimeoutError("transient read timeout")
        return _Response(b"current-source")

    monkeypatch.setattr("ai_fc.statistics_lab.urllib.request.urlopen", flaky)
    monkeypatch.setattr("ai_fc.statistics_lab.time.sleep", sleeps.append)
    assert _request("https://example.test/source", timeout=1) == b"current-source"
    assert len(calls) == 3
    assert sleeps == [1, 2]


def test_public_request_does_not_retry_permanent_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def missing(*_args: object, **_kwargs: object) -> _Response:
        calls.append(1)
        raise urllib.error.HTTPError(
            "https://example.test/missing", 404, "not found", {}, None,
        )

    monkeypatch.setattr("ai_fc.statistics_lab.urllib.request.urlopen", missing)
    with pytest.raises(urllib.error.HTTPError):
        _request("https://example.test/missing", timeout=1)
    assert len(calls) == 1


def test_sec_fetch_returns_the_exact_download_uri_for_raw_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    download = "https://www.sec.gov/files/dera/data/sec-stats-ipos-2026.xlsx"
    sec_header = [f"field-{index}" for index in range(13)]
    sec_row = [
        "2026:Q2", 109, 97, 12, 52, 56, 1, 115718,
        109876.5, 5841.5, 104734.1, 8958, 2025.8,
    ]
    workbook = _xlsx_fixture("Stats Table", [sec_header, sec_row])

    def fetch(url: str, *, timeout: int) -> bytes:
        del timeout
        if url.endswith("initial-public-offerings-ipos"):
            return f'<a href="{download}">download</a>'.encode()
        assert url == download
        return workbook

    monkeypatch.setattr("ai_fc.statistics_lab._request", fetch)
    rows, raw, source_uri = _fetch_supplemental("SEC_IPO_QUARTERLY")
    assert rows[0]["period_label"] == "2026:Q2"
    assert raw == workbook
    assert source_uri == download


def test_public_request_stays_fail_closed_after_retry_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def unavailable(*_args: object, **_kwargs: object) -> _Response:
        calls.append(1)
        raise urllib.error.URLError("temporary DNS failure")

    monkeypatch.setattr("ai_fc.statistics_lab.urllib.request.urlopen", unavailable)
    monkeypatch.setattr("ai_fc.statistics_lab.time.sleep", lambda _seconds: None)
    with pytest.raises(StatisticsLabError, match="failed after 3 attempts"):
        _request("https://example.test/source", timeout=1)
    assert len(calls) == 3


def test_fred_fetch_uses_same_url_transport_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, int]] = []

    def fetched(url: str, *, timeout: int) -> str:
        seen.append((url, timeout))
        return "observation_date,M2SL\n2026-07-01,22000.5\n"

    monkeypatch.setattr(
        "ai_fc.statistics_lab.feed.get_with_curl_fallback", fetched,
    )
    rows, raw = _fetch_fred("M2SL")
    assert seen == [(f"{FRED_ENDPOINT}?id=M2SL&cosd=1995-01-01", 45)]
    assert rows == [{"date": "2026-07-01", "value": 22000.5}]
    assert raw == b"observation_date,M2SL\n2026-07-01,22000.5\n"


def _rows(series_id: str) -> list[dict[str, float | str]]:
    rows = []
    start = date(1985, 1, 1) if series_id == "NASDAQCOM" else date(1995, 1, 1)
    if series_id in {"SP500", "CBBTCUSD", "NASDAQSOX", "SPASTT01KRM661N"}:
        start = date(2020, 1, 1)
    end = date(2027, 1, 1)
    months = (end.year - start.year) * 12 + end.month - start.month
    for offset in range(0, months):
        year = start.year + (start.month - 1 + offset) // 12
        month = (start.month - 1 + offset) % 12 + 1
        if series_id in {
            "DABSHNO", "BOGZ1LM153064475Q", "BOGZ1LM893064105Q",
            "MMMFFAQ027S", "CDCABSHNO", "TSDABSHNO", "FGDSLAQ027S",
            "BOGZ1FL153064235Q",
        } and month not in {1, 4, 7, 10}:
            continue
        if series_id == "BOGZ1FL154022375A" and month != 1:
            continue
        baseline = {
            "M2SL": 4000.0,
            "MMMFFAQ027S": 2_000_000.0,
            "CDCABSHNO": 3_000_000.0,
            "TSDABSHNO": 8_000_000.0,
            "FGDSLAQ027S": 15_000_000.0,
            "BOGZ1FL153064235Q": 2_000_000.0,
            "IQ12260": 80.0,
            "DABSHNO": 8_000_000.0,
            "BOGZ1LM153064475Q": 9_000_000.0,
            "BOGZ1FL154022375A": 6_000_000.0,
            "NASDAQCOM": 900.0,
            "T10Y2Y": 0.5,
            "FEDFUNDS": 5.0,
            "TOTALSL": 1_000_000.0,
            "TDSP": 12.0,
            "BOGZ1FL010000346Q": 12.0,
            "DRTSCILM": 5.0,
            "NCBEILQ027S": 8_000_000.0,
            "CPATAX": 600.0,
            "UNRATE": 4.0,
            "CPIAUCSL": 160.0,
            "NFCI": -0.3,
            "BOGZ1LM893064105Q": 20_000_000.0,
            "HQMCB10YR": 6.0,
            "GS10": 5.0,
            "DCOILWTICO": 50.0,
            "WPU10260314": 100.0,
            "GACDFSA066MSFRBPHI": 5.0,
            "SP500": 3200.0,
            "CBBTCUSD": 9000.0,
            "NASDAQSOX": 1800.0,
            "SPASTT01KRM661N": 100.0,
            "HOUST": 1400.0,
        }[series_id]
        growth = 1.0 + offset * (0.001 if series_id not in {"T10Y2Y", "FEDFUNDS", "TDSP", "BOGZ1FL010000346Q", "DRTSCILM", "UNRATE", "NFCI", "HQMCB10YR", "GS10", "GACDFSA066MSFRBPHI"} else 0.0)
        value = baseline * growth
        if series_id == "T10Y2Y":
            value = ((offset % 30) - 12) / 10
        elif series_id == "DRTSCILM":
            value = ((offset % 20) - 6) * 2.0
        elif series_id == "UNRATE":
            value = 3.5 + (offset % 18) / 10.0
        elif series_id == "NFCI":
            value = ((offset % 24) - 14) / 10.0
        elif series_id == "GACDFSA066MSFRBPHI":
            value = ((offset % 30) - 15) * 1.5
        rows.append({"date": date(year, month, 1).isoformat(), "value": value})
    return rows


def _z1_bytes() -> bytes:
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w") as archive:
        lines = ["date,FL663067003.Q"]
        for year in range(1995, 2027):
            for quarter in range(1, 5):
                lines.append(f"{year}:Q{quarter},{100000 + (year - 1995) * 10000 + quarter}")
        archive.writestr("csv/F4_6_s.csv", "\n".join(lines) + "\n")
    return target.getvalue()


def _xlsx_fixture(sheet_name: str, rows: list[list[object]]) -> bytes:
    def column_name(index: int) -> str:
        result = ""
        while index:
            index, remainder = divmod(index - 1, 26)
            result = chr(65 + remainder) + result
        return result

    sheet_rows = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for column_index, value in enumerate(row, start=1):
            ref = f"{column_name(column_index)}{row_index}"
            if isinstance(value, str):
                cells.append(
                    f'<c r="{ref}" t="inlineStr"><is><t>{html.escape(value)}</t></is></c>'
                )
            else:
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
            f'<sheet name="{html.escape(sheet_name)}" sheetId="1" r:id="rId1"/>'
            '</sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
            + "".join(sheet_rows) + '</sheetData></worksheet>',
        )
    return target.getvalue()


def _payload_inputs() -> tuple[dict, dict]:
    rows = {series_id: _rows(series_id) for series_id in FRED_SERIES}
    market_rows = {series_id: [] for series_id in DAILY_MARKET_SERIES}
    market_values = {
        "KOSPI_DAILY": 2200.0,
        "TAIEX_DAILY": 12_000.0,
        "SOX_DAILY": 1800.0,
        "SP500_DAILY": 3200.0,
        "GOLD_FUTURES_DAILY": 1600.0,
        "BTCUSD_DAILY": 9000.0,
    }
    observed = date(2020, 1, 1)
    session = 0
    while observed <= date(2026, 12, 30):
        if observed.weekday() < 5:
            common = math.sin(session * 0.17) * 0.008 + math.cos(session * 0.047) * 0.003
            returns = {
                "KOSPI_DAILY": 0.0005 + common,
                "TAIEX_DAILY": 0.0005 + common * 0.93 + math.sin(session * 0.07) * 0.002,
                "SOX_DAILY": 0.0007 + common * 1.35 + math.cos(session * 0.13) * 0.005,
                "SP500_DAILY": 0.0004 + common * 0.78,
                "GOLD_FUTURES_DAILY": 0.0002 + common * 0.35,
                "BTCUSD_DAILY": 0.0008 + common * 1.9 + math.sin(session * 0.19) * 0.007,
            }
            for series_id, daily_return in returns.items():
                market_values[series_id] *= math.exp(daily_return)
                market_rows[series_id].append({
                    "date": observed.isoformat(), "value": market_values[series_id],
                })
            session += 1
        observed = date.fromordinal(observed.toordinal() + 1)
    rows.update(market_rows)
    rows["SEC_IPO_QUARTERLY"] = [
        {"date": "2025-03-01", "period_label": "2025:Q1", "total_count": 84, "us_count": 45, "non_us_count": 39, "corporate_count": 63, "spac_count": 20, "fund_count": 1, "total_proceeds_mn": 11867.2, "corporate_proceeds_mn": 8814.8, "spac_proceeds_mn": 3052.0, "fund_proceeds_mn": 0.4},
        {"date": "2025-06-01", "period_label": "2025:Q2", "total_count": 96, "us_count": 59, "non_us_count": 37, "corporate_count": 48, "spac_count": 46, "fund_count": 2, "total_proceeds_mn": 15808.4, "corporate_proceeds_mn": 7029.6, "spac_proceeds_mn": 8722.5, "fund_proceeds_mn": 56.3},
        {"date": "2026-03-01", "period_label": "2026:Q1", "total_count": 99, "us_count": 81, "non_us_count": 18, "corporate_count": 36, "spac_count": 62, "fund_count": 1, "total_proceeds_mn": 22181.5, "corporate_proceeds_mn": 10055.9, "spac_proceeds_mn": 11810.2, "fund_proceeds_mn": 315.4},
        {"date": "2026-06-01", "period_label": "2026:Q2", "total_count": 109, "us_count": 97, "non_us_count": 12, "corporate_count": 52, "spac_count": 56, "fund_count": 1, "total_proceeds_mn": 115718.0, "corporate_proceeds_mn": 104734.1, "spac_proceeds_mn": 8958.0, "fund_proceeds_mn": 2025.8},
    ]
    rows["ICI_WEEKLY_EQUITY_ETF_FLOW"] = [
        {"date": f"2026-07-{day:02d}", "value": value, "domestic": domestic, "world": value - domestic}
        for day, value, domestic in ((8, 52517, 49661), (15, 15687, 5582), (22, 20835, 14178), (29, 40529, 36325))
    ] + [{"date": "2026-08-05", "value": 29803, "domestic": 19619, "world": 10184}]
    rows["NYU_SP500_ANNUAL_TOTAL_RETURN"] = [
        {
            "date": f"{year}-12-31",
            "value": 25.0 if year % 8 in {0, 1} else (12.0 if year % 8 == 2 else 6.0),
        }
        for year in range(1950, 2026)
    ]
    z1 = _z1_bytes()
    rows["FL663067003"] = _parse_z1(z1)
    receipts = {
        series_id: {"raw_sha256": hashlib.sha256(series_id.encode()).hexdigest()}
        for series_id in rows
    }
    for series_id in DAILY_MARKET_SERIES:
        receipts[series_id].update({
            "request_url": f"https://query1.finance.yahoo.com/v8/finance/chart/{series_id}",
            "data_quality": {"status": "ok"},
        })
    return rows, receipts


def _repo_ipo_reference() -> dict:
    root = Path(__file__).resolve().parents[2]
    return load_ipo_reference(root)


def _repo_hmi_reference() -> dict:
    root = Path(__file__).resolve().parents[2]
    return load_hmi_reference(root)


def _install_ipo_reference(root: Path) -> None:
    ipo_fixture = json.loads(json.dumps(_repo_ipo_reference()))
    ipo_fixture["as_of"] = "2026-12-31"
    ipo_fixture["classification"]["reviewed_through"] = "2026-12-31"
    target = root / "data/statistics/ipo/ipo_comparison_v1.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(ipo_fixture, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    hmi_fixture = json.loads(json.dumps(_repo_hmi_reference()))
    hmi_fixture["as_of"] = "2026-12-31"
    hmi_target = root / "data/statistics/reference/nahb_hmi_history_v1.json"
    hmi_target.parent.mkdir(parents=True, exist_ok=True)
    hmi_target.write_text(
        json.dumps(hmi_fixture, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    repo_root = Path(__file__).resolve().parents[2]
    ici_fixture = json.loads(
        (repo_root / "data/statistics/reference/ici_weekly_equity_etf_flow_v1.json")
        .read_text(encoding="utf-8")
    )
    ici_fixture["as_of"] = "2026-12-31"
    ici_target = root / "data/statistics/reference/ici_weekly_equity_etf_flow_v1.json"
    ici_target.write_text(
        json.dumps(ici_fixture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )


def test_parsers_reject_missing_and_preserve_explicit_values() -> None:
    parsed = _parse_fred_csv(
        b"observation_date,M2SL\n2026-01-01,22000\n2026-02-01,.\n", "M2SL"
    )
    assert parsed == [{"date": "2026-01-01", "value": 22000.0}]
    assert _parse_z1(_z1_bytes())[0]["date"] == "1995-01-01"


def test_public_supplemental_parsers_preserve_source_definitions() -> None:
    sec_header = [f"field-{index}" for index in range(13)]
    sec_row = ["2026:Q2", 109, 97, 12, 52, 56, 1, 115718, 109876.5, 5841.5, 104734.1, 8958, 2025.8]
    sec = _parse_sec_ipo_xlsx(_xlsx_fixture("Stats Table", [sec_header, sec_row]))
    assert sec == [{
        "date": "2026-06-01", "period_label": "2026:Q2", "total_count": 109,
        "us_count": 97, "non_us_count": 12, "corporate_count": 52,
        "spac_count": 56, "fund_count": 1, "total_proceeds_mn": 115718.0,
        "corporate_proceeds_mn": 104734.1, "spac_proceeds_mn": 8958.0,
        "fund_proceeds_mn": 2025.8,
    }]
    nyu_rows = [["Year", "S&P 500 (includes dividends)"]] + [
        [year, 0.20 if year % 2 else -0.05] for year in range(1928, 2026)
    ]
    nyu = _parse_nyu_returns_xlsx(_xlsx_fixture("Returns by year", nyu_rows))
    assert nyu[0] == {"date": "1928-12-31", "value": -5.0}
    assert nyu[-1] == {"date": "2025-12-31", "value": 20.0}
    ici = _parse_ici_weekly_html(b"""
      <h2>ETF Estimated Net Issuance</h2><table>
      <tr><th></th><th>8/5/2026</th><th>7/29/2026</th><th>7/22/2026</th></tr>
      <tr><td>Equity</td><td>29,803</td><td>40,529</td><td>20,835</td></tr>
      <tr><td>Domestic</td><td>19,619</td><td>36,325</td><td>14,178</td></tr>
      <tr><td>World</td><td>10,184</td><td>4,204</td><td>6,657</td></tr>
      </table>
    """)
    assert ici[-1] == {
        "date": "2026-08-05", "value": 29803.0,
        "domestic": 19619.0, "world": 10184.0,
    }


def test_manual_reference_staleness_stops_weekly_republication() -> None:
    ipo = _repo_ipo_reference()
    hmi = _repo_hmi_reference()
    _validate_manual_reference_freshness(ipo, hmi, "2026-08-13T00:00:00+00:00")
    with pytest.raises(StatisticsLabError, match="IPO reviewed cohort stale"):
        _validate_manual_reference_freshness(ipo, hmi, "2026-09-01T00:00:00+00:00")


def _legacy_build_statistics_lab_contract() -> None:
    rows, receipts = _payload_inputs()
    payload = build_statistics_lab(
        rows,
        generated_at="2026-12-31T00:00:00+00:00",
        receipts=receipts,
        ipo_reference=_repo_ipo_reference(),
        hmi_reference=_repo_hmi_reference(),
    )
    validate_statistics_lab(payload)
    assert payload["probability_space"] == "reference_only"
    assert payload["model_use"] is False
    assert payload["official_forecast_input"] is False
    assert payload["cycle_alignment"] == {
        "dotcom_start": "1995-01-01",
        "dotcom_end": "1999-12-31",
        "current_start": "2023-01-01",
        "current_axis_end": "2027-12-31",
        "comparison_months": 59,
        "current_observed_through": "2026-12-01",
        "current_line_policy": "actual_observations_only_no_forecast_extension",
        "forecast_extension": False,
        "endpoint_forcing": False,
    }
    assert len(payload["charts"]) == 32
    assert all(chart["insight"] for chart in payload["charts"])
    assert all(chart["conclusion"] for chart in payload["charts"])
    assert {chart["id"] for chart in payload["charts"]} >= {
        "m2_nasdaq", "nasdaq_per_m2", "nasdaq_per_household_liquid_assets",
        "liquidity_position_map",
        "yield_curve", "valuation_proxy", "margin_credit_proxy",
        "household_debt_service", "unemployment_rate", "inflation_rate",
        "financial_conditions",
        "internet_vs_ai_core_ipos", "technology_ipo_count",
        "technology_ipo_first_day_return", "technology_ipo_price_to_sales",
        "technology_ipo_profitable_share", "all_ipo_negative_earnings_share",
        "ipo_market_absorption", "small_issuer_ipo_share",
        "dotcom_internet_ipo_breadth",
        "sec_ipo_issuer_mix_h1", "sp500_after_two_twenty_percent_years",
        "household_balance_sheet_trend_gap",
        "rate_cycle_since_first_cut", "corporate_bond_pressure",
        "inflation_lead_panel", "housing_manufacturing_warning",
        "kospi_external_semiconductor_pulse",
    }
    assert {chart["id"] for chart in payload["charts"]}.isdisjoint({
        "ici_weekly_equity_etf_flow",
        "negative_then_strong_quarter_followthrough",
        "gold_vs_us_m2",
        "nasdaq_tech_cycle_milestones",
        "kospi_market_breadth_2026_daily",
    })
    by_id = {chart["id"]: chart for chart in payload["charts"]}
    assert by_id["m2_nasdaq"]["scale"] == "log1p"
    liquidity_map = by_id["liquidity_position_map"]
    assert liquidity_map["chart_type"] == "liquidity_bars"
    assert liquidity_map["source_ids"] == [
        "BOGZ1LM893064105Q", "M2SL", "MMMFFAQ027S",
        "SP500_DAILY", "GOLD_FUTURES_DAILY", "BTCUSD_DAILY",
    ]
    assert [panel["title"] for panel in liquidity_map["liquidity_panels"]] == [
        "현재 규모", "최근 12개월 방향",
    ]
    assert [panel["mode"] for panel in liquidity_map["liquidity_panels"]] == [
        "positive", "diverging",
    ]
    assert all(chart["scope_note"].startswith("*") for chart in payload["charts"])
    assert liquidity_map["scope_note"] == "*미국 자금 기준 · 금·비트코인은 달러 시세"
    sec_mix = by_id["sec_ipo_issuer_mix_h1"]
    assert sec_mix["chart_type"] == "stacked_bar"
    assert sec_mix["show_bar_values"] is True
    assert "AI 기업만의 통계가 아닙니다" in sec_mix["reading_guide"]
    household_trend = by_id["household_balance_sheet_trend_gap"]["trend_baseline"]
    assert household_trend == {
        "start": "2009-01-01",
        "end": "2019-12-31",
        "method": "ordinary_least_squares_on_levels",
        "training_observations": {
            "corporate_equities": 44,
            "cash_and_deposits": 44,
            "debt_securities": 11,
        },
    }
    ipo_chart = next(chart for chart in payload["charts"] if chart["id"] == "internet_vs_ai_core_ipos")
    assert ipo_chart["scale"] == "log1p"
    assert ipo_chart["series"][0]["points"][-1]["value"] == 273
    assert ipo_chart["series"][1]["points"][-1] == {
        "period": 36, "date": "2026-08-12", "value": 5
    }
    assert ipo_chart["series"][2]["points"][-1] == {
        "period": 36, "date": "2026-08-12", "value": 6
    }
    assert ipo_chart["series"][3]["points"][-1] == {
        "period": 36, "date": "2026-08-12", "value": 1
    }
    assert "SK hynix SKHY(NASDAQ ADS)" in ipo_chart["detail_rows"][-2]["label"]
    assert "Montage Technology MONT" in ipo_chart["detail_rows"][-1]["label"]
    assert ipo_chart["detail_rows"][0]["label"] == "Arm · Klaviyo"
    assert all(chart["id"] != "global_ai_capital_map" for chart in payload["charts"])
    dotcom_profile = next(
        chart for chart in payload["charts"]
        if chart["id"] == "dotcom_internet_ipo_breadth"
    )
    assert dotcom_profile["chart_type"] == "profile_cards"
    assert [group["title"] for group in dotcom_profile["profile_groups"]] == [
        "시장에 얼마나 퍼졌나",
        "상장사가 얼마나 초기였나",
        "투자자가 얼마나 몰렸나",
    ]
    assert [
        metric["value"]
        for group in dotcom_profile["profile_groups"]
        for metric in group["metrics"]
    ] == [60, 40, 81, 57, 90]
    absorption = next(chart for chart in payload["charts"] if chart["id"] == "ipo_market_absorption")
    assert absorption["series"][2]["marker_radius"] == 10
    assert any(row["period"] == "NASDAQ ADS" and row["label"] == "SK hynix SKHY" for row in absorption["detail_rows"])
    assert any(row["period"] == "중국 메모리 NASDAQ" and "MONT" in row["label"] for row in absorption["detail_rows"])
    assert any(row["period"] == "글로벌 IPO" for row in absorption["detail_rows"])
    assert [len(row["issuers"]) for row in _repo_ipo_reference()["ai_broad_cohort"]] == [2, 5, 10, 5]
    assert payload["ipo_comparison"]["classification"]["ai_broad_limit"].startswith(
        "This is a reviewed market-narrative"
    )
    assert payload["ipo_comparison"]["classification"]["ai_core_limit"].startswith("This is a conservative")
    valuation = next(chart for chart in payload["charts"] if chart["id"] == "valuation_proxy")
    assert "대용치" in valuation["title"]
    assert {row["era"] for row in valuation["series"]} == {"dotcom", "current"}
    household_cash = next(
        chart for chart in payload["charts"] if chart["id"] == "nasdaq_per_household_liquid_assets"
    )
    assert household_cash["source_ids"] == ["NASDAQCOM", "DABSHNO"]
    assert "M2와 합산하면 예금이 중복 계산" in household_cash["caveat"]
    assert {row["era"] for row in household_cash["series"]} == {"dotcom", "current"}
    assert all(
        point["period"] % 3 == 0
        for series in household_cash["series"]
        for point in series["points"]
    )
    assert "같은 경과월의 닷컴 지수" in household_cash["insight"]
    pulse = next(
        chart for chart in payload["charts"]
        if chart["id"] == "kospi_external_semiconductor_pulse"
    )
    assert pulse["source_ids"] == ["KOSPI_DAILY", "TAIEX_DAILY", "SOX_DAILY"]
    assert pulse["unit"] == "percent_20d_log_return"
    assert pulse["axis_type"] == "calendar_day_of_year"
    assert [row["label"] for row in pulse["series"]] == [
        "KOSPI 20일", "대만 TAIEX 20일", "전일 SOX 20일",
    ]
    pulse_diagnostic = pulse["external_pulse_diagnostics"]
    assert pulse_diagnostic["sox_strictly_prior_us_close"]["observations"] > 1000
    assert pulse_diagnostic["sox_conditional_quintiles"]["training_highest_quintile"]["observations"] > 100
    assert pulse_diagnostic["time_warping"] is False
    assert pulse_diagnostic["optimized_lag"] is False
    assert pulse_diagnostic["forecast_extension"] is False
    policy_rate = next(chart for chart in payload["charts"] if chart["id"] == "policy_rate")
    assert policy_rate["source_validation"]["source_id"] == "FEDFUNDS"
    assert policy_rate["source_validation"]["observations"] == 60
    assert policy_rate["source_validation"]["interpolation"] is False
    assert policy_rate["source_validation"]["perfect_rectangle"] is False
    for chart in payload["charts"]:
        dotcom = [row for row in chart["series"] if row["era"] == "dotcom"]
        current = [row for row in chart["series"] if row["era"] == "current"]
        if dotcom:
            assert max(point["period"] for row in dotcom for point in row["points"]) <= 59
        if current and int(chart.get("max_period", 59)) == 59:
            assert max(point["period"] for row in current for point in row["points"]) < 59
    invalid = json.loads(json.dumps(payload))
    invalid["cycle_alignment"]["forecast_extension"] = True
    try:
        validate_statistics_lab(invalid)
    except Exception as exc:
        assert "alignment contract" in str(exc)
    else:
        raise AssertionError("forecast extension must be rejected")

    future_leak = json.loads(json.dumps(payload))
    future_leak["sources"][0]["latest_observation"] = "2027-01-01"
    with pytest.raises(StatisticsLabError, match="future-data leakage"):
        validate_statistics_lab(future_leak)

    invalid_liquidity = json.loads(json.dumps(payload))
    next(
        chart for chart in invalid_liquidity["charts"]
        if chart["id"] == "liquidity_position_map"
    )["chart_type"] = "pie"
    with pytest.raises(StatisticsLabError, match="liquidity position map"):
        validate_statistics_lab(invalid_liquidity)

    incomplete_session_rows = json.loads(json.dumps(rows))
    incomplete_session_rows["KOSPI_DAILY"].append({
        "date": "2026-12-31", "value": 7000.0,
    })
    with pytest.raises(StatisticsLabError, match="incomplete session"):
        build_statistics_lab(
            incomplete_session_rows,
            generated_at="2026-12-31T00:00:00+00:00",
            receipts=receipts,
            ipo_reference=_repo_ipo_reference(),
            hmi_reference=_repo_hmi_reference(),
        )


def test_build_statistics_lab_uses_authoritative_numeric_sources_only() -> None:
    rows, receipts = _payload_inputs()
    payload = build_statistics_lab(
        rows,
        generated_at="2026-12-31T00:00:00+00:00",
        receipts=receipts,
        ipo_reference=_repo_ipo_reference(),
        hmi_reference=_repo_hmi_reference(),
    )
    validate_statistics_lab(payload)
    assert len(payload["charts"]) == 22
    assert payload["numeric_source_policy"] == {
        "reports_and_media": "insight_only",
        "raw_required_before_derive": True,
        "published_chart_sources": "authoritative_only",
    }
    by_id = {chart["id"]: chart for chart in payload["charts"]}
    assert "technology_ipo_count" not in by_id
    assert "sp500_after_two_twenty_percent_years" not in by_id
    assert "kospi_external_semiconductor_pulse" not in by_id
    assert by_id["liquidity_position_map"]["source_ids"] == [
        "BOGZ1LM893064105Q", "FGDSLAQ027S", "TSDABSHNO", "CDCABSHNO",
        "M2SL", "MMMFFAQ027S", "BOGZ1FL153064235Q", "SP500",
        "NASDAQCOM", "CBBTCUSD", "IQ12260",
    ]
    assert by_id["korea_semiconductor_cycle"]["source_ids"] == [
        "SPASTT01KRM661N", "NASDAQSOX",
    ]
    assert by_id["housing_manufacturing_warning"]["source_ids"] == [
        "HOUST", "GACDFSA066MSFRBPHI",
    ]
    assert all(source["numeric_input_allowed"] is True for source in payload["sources"])
    assert all(source["usage_role"] == "numeric_input" for source in payload["sources"])
    assert all(
        chart["metric_source_ids"] == chart["source_ids"]
        and chart["research_context_source_ids"] == []
        for chart in payload["charts"]
    )
    assert all(
        chart["insight"].strip() != chart["conclusion"].strip()
        for chart in payload["charts"]
    )
    assert "현재" in by_id["inflation_rate"]["conclusion"]
    assert "시장" in by_id["liquidity_position_map"]["conclusion"]


def test_ipo_reference_statistics_use_sec_denominator_and_stay_separate() -> None:
    rows, receipts = _payload_inputs()
    rows["SEC_IPO_QUARTERLY"].extend([
        {
            "date": "2025-09-01", "period_label": "2025:Q3",
            "total_count": 100, "us_count": 70, "non_us_count": 30,
            "corporate_count": 76, "spac_count": 23, "fund_count": 1,
            "total_proceeds_mn": 18000.0,
            "corporate_proceeds_mn": 15084.0,
            "spac_proceeds_mn": 2800.0, "fund_proceeds_mn": 116.0,
        },
        {
            "date": "2025-12-01", "period_label": "2025:Q4",
            "total_count": 75, "us_count": 55, "non_us_count": 20,
            "corporate_count": 40, "spac_count": 34, "fund_count": 1,
            "total_proceeds_mn": 15000.0,
            "corporate_proceeds_mn": 12362.4,
            "spac_proceeds_mn": 2500.0, "fund_proceeds_mn": 137.6,
        },
    ])
    payload = build_statistics_lab(
        rows,
        generated_at="2026-12-31T00:00:00+00:00",
        receipts=receipts,
        ipo_reference=_repo_ipo_reference(),
    )
    assert len(payload["charts"]) == 22
    assert "dotcom_internet_ipo_breadth" not in {
        chart["id"] for chart in payload["charts"]
    }
    reference = payload["reference_statistics"]
    assert reference["placement"] == "below_authoritative_statistics"
    assert reference["official_numeric_ledger"] is False
    assert [chart["id"] for chart in reference["charts"]] == list(
        IPO_REFERENCE_CHART_IDS
    )
    assert reference["batch_refresh"]["current_only_update"] is True
    assert reference["batch_refresh"]["historical_era"] == (
        "frozen_cited_publication_vintage"
    )
    chart = reference["charts"][-1]
    metrics = [
        metric
        for group in chart["profile_groups"]
        for metric in group["metrics"]
    ]
    assert len(metrics) == 5
    assert all(len(metric["comparisons"]) == 2 for metric in metrics)
    assert [metric["comparisons"][0]["value"] for metric in metrics] == [
        60, 40, 81, 57, 90,
    ]
    assert [metric["comparisons"][1]["value"] for metric in metrics] == [
        1.3, 4.1, 66.7, 33.3, 18.6,
    ]
    assert all(
        metric["comparisons"][1]["label"] == "2025 AI 핵심 · n=3"
        for metric in metrics
    )
    assert all(
        chart["insight"].strip() != chart["conclusion"].strip()
        for chart in reference["charts"]
    )
    overlay = chart["reference_contract"]["official_overlay"]
    assert overlay["corporate_count"] == 227
    assert overlay["corporate_proceeds_mn"] == 43290.8
    assert overlay["refresh_mode"] == "weekly_official_ledger_projection"
    assert all(
        "source_url" not in source and "request_url" not in source
        for source in reference["sources"]
    )

    source_reference = _repo_ipo_reference()
    source_charts = {
        chart["id"]: chart for chart in source_reference["charts"]
    }
    for reference_chart in reference["charts"]:
        historical = [
            series for series in reference_chart["series"]
            if series["era"] == "dotcom"
        ]
        source_historical = [
            series for series in source_charts[reference_chart["id"]]["series"]
            if series["era"] == "dotcom"
        ]
        assert historical == source_historical
        assert reference_chart["reference_batch"] == {
            "historical_era": "frozen_cited_publication_vintage",
            "current_era": "weekly_reviewed_batch",
            "current_only_update": True,
            "forecast_extension": False,
            "reviewed_through": source_reference["as_of"],
        }


def _append_official_persistence_batch(
    root: Path, *, raw_tag: str, fetched_at: str, m2_value: float = 100.0,
):
    source_rows: dict[str, list[dict[str, object]]] = {
        series_id: [{"date": "2026-01-01", "value": 100.0}]
        for series_id in FRED_SERIES
    }
    source_rows["M2SL"] = [{"date": "2026-01-01", "value": m2_value}]
    source_rows["FL663067003"] = [
        {"date": "2026-01-01", "value": 50.0},
    ]
    source_rows["SEC_IPO_QUARTERLY"] = [{
        "date": "2026-03-31",
        "period_label": "2026:Q1",
        "total_count": 10,
        "us_count": 8,
        "non_us_count": 2,
        "corporate_count": 6,
        "spac_count": 3,
        "fund_count": 1,
        "total_proceeds_mn": 1000.0,
        "corporate_proceeds_mn": 700.0,
        "spac_proceeds_mn": 200.0,
        "fund_proceeds_mn": 100.0,
    }]
    series_ids = [*FRED_SERIES, "FL663067003", "SEC_IPO_QUARTERLY"]
    raw_payloads = {
        series_id: f"{raw_tag}:{series_id}".encode()
        for series_id in series_ids
    }
    receipts = {series_id: {} for series_id in series_ids}
    candidates = _persist_authoritative_inputs(
        root,
        source_rows=source_rows,
        raw_payloads=raw_payloads,
        receipts=receipts,
        fetched_at=fetched_at,
    )
    policy = load_authoritative_source_policy(
        Path(__file__).resolve().parents[2]
        / "data/contracts/authoritative_statistics_sources.yaml"
    )
    appended = append_normalized_observations(
        root / "data/statistics/official_store", policy, candidates,
    )
    return candidates, appended


def test_new_raw_receipt_with_same_semantics_does_not_create_revision(
    tmp_path: Path,
) -> None:
    first, appended = _append_official_persistence_batch(
        tmp_path, raw_tag="first", fetched_at="2026-04-01T00:00:00+00:00",
    )
    assert first == appended
    store = tmp_path / "data/statistics/official_store"
    observation_count = len(read_normalized_observations(store))
    receipt_count = len(read_raw_artifact_receipts(store))

    second, second_appended = _append_official_persistence_batch(
        tmp_path, raw_tag="different-response-bytes",
        fetched_at="2026-04-08T00:00:00+00:00",
    )

    assert second == []
    assert second_appended == []
    assert len(read_normalized_observations(store)) == observation_count
    assert len(read_raw_artifact_receipts(store)) == receipt_count * 2


def test_changed_value_creates_explicit_superseding_revision(tmp_path: Path) -> None:
    _append_official_persistence_batch(
        tmp_path, raw_tag="first", fetched_at="2026-04-01T00:00:00+00:00",
    )
    store = tmp_path / "data/statistics/official_store"
    prior = next(
        row for row in read_normalized_observations(store)
        if row.source_id == "fred_market_signals" and row.series_id == "M2SL"
    )

    candidates, appended = _append_official_persistence_batch(
        tmp_path, raw_tag="value-revision", fetched_at="2026-04-08T00:00:00+00:00",
        m2_value=101.0,
    )

    assert candidates == appended
    assert len(candidates) == 1
    revision = candidates[0]
    assert revision.series_id == "M2SL"
    assert revision.value == "101"
    assert revision.revision_seq == 1
    assert revision.supersedes_observation_id == prior.observation_id


def test_changed_unit_creates_explicit_superseding_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _append_official_persistence_batch(
        tmp_path, raw_tag="first", fetched_at="2026-04-01T00:00:00+00:00",
    )
    store = tmp_path / "data/statistics/official_store"
    prior = next(
        row for row in read_normalized_observations(store)
        if row.source_id == "fred_market_signals" and row.series_id == "M2SL"
    )
    monkeypatch.setitem(FRED_SERIES["M2SL"], "unit", "millions_usd")

    candidates, appended = _append_official_persistence_batch(
        tmp_path, raw_tag="unit-revision", fetched_at="2026-04-08T00:00:00+00:00",
    )

    assert candidates == appended
    assert len(candidates) == 1
    revision = candidates[0]
    assert revision.series_id == "M2SL"
    assert revision.unit == "millions_usd"
    assert revision.transformation_id == "identity"
    assert revision.revision_seq == 1
    assert revision.supersedes_observation_id == prior.observation_id


def test_refresh_is_append_only_for_changed_weekly_snapshot(tmp_path: Path) -> None:
    rows, _ = _payload_inputs()
    _install_ipo_reference(tmp_path)

    def fred_fetcher(series_id: str):
        raw = f"fixture:{series_id}".encode()
        return rows[series_id], raw

    def market_fetcher(series_id: str, _start: date, _end: date):
        return rows[series_id], {
            "raw_sha256": hashlib.sha256(f"fixture:{series_id}".encode()).hexdigest(),
            "request_url": f"https://example.test/{series_id}",
            "data_quality": {"status": "ok"},
        }

    def supplemental_fetcher(series_id: str):
        raw = f"supplemental-fixture:{series_id}".encode()
        return (
            rows[series_id], raw,
            "https://www.sec.gov/files/dera/data/sec-stats-ipos-2026.xlsx",
        )

    z1 = _z1_bytes()
    policy = load_authoritative_source_policy(
        Path(__file__).resolve().parents[2]
        / "data/contracts/authoritative_statistics_sources.yaml"
    )
    sec_fields = [
        f"SEC_IPO_QUARTERLY.{field}"
        for field in (
            "total_count", "us_count", "non_us_count", "corporate_count",
            "spac_count", "fund_count", "total_proceeds_mn",
            "corporate_proceeds_mn", "spac_proceeds_mn", "fund_proceeds_mn",
        )
    ]
    persist_raw_artifact(
        tmp_path / "data/statistics/official_store",
        policy,
        source_id="sec_edgar",
        payload=b"supplemental-fixture:SEC_IPO_QUARTERLY",
        source_uri="https://www.sec.gov/data-research/statistics-data-visualizations/initial-public-offerings-ipos",
        fetched_at="2026-12-30T00:00:00+00:00",
        http_status=200,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        series_ids=sec_fields,
    )
    path, payload, changed = refresh_statistics_lab(
        tmp_path, fred_fetcher=fred_fetcher, market_fetcher=market_fetcher,
        supplemental_fetcher=supplemental_fetcher,
        z1_fetcher=lambda _url: z1,
        now=datetime(2026, 12, 31, tzinfo=timezone.utc),
    )
    assert changed is True
    assert path.is_file()
    archives = list((tmp_path / "data/statistics/archive").glob("*.json"))
    assert len(archives) == 1
    _, second, changed_again = refresh_statistics_lab(
        tmp_path, fred_fetcher=fred_fetcher, market_fetcher=market_fetcher,
        supplemental_fetcher=supplemental_fetcher,
        z1_fetcher=lambda _url: z1,
        now=datetime(2026, 12, 31, tzinfo=timezone.utc),
    )
    assert changed_again is False
    assert second["as_of"] == payload["as_of"]
    assert len(list((tmp_path / "data/statistics/archive").glob("*.json"))) == 1
    refresh_statistics_lab(
        tmp_path, fred_fetcher=fred_fetcher, market_fetcher=market_fetcher,
        supplemental_fetcher=supplemental_fetcher,
        z1_fetcher=lambda _url: z1,
        now=datetime(2027, 1, 7, tzinfo=timezone.utc),
    )
    corrections = read_raw_receipt_corrections(
        tmp_path / "data/statistics/official_store"
    )
    assert len(corrections) == 1
    loaded = load_statistics_lab(tmp_path)
    assert json.loads(path.read_text(encoding="utf-8"))["dataset_id"] == loaded["dataset_id"]


def test_dashboard_statistics_route_and_weekly_workflow_are_wired() -> None:
    root = Path(__file__).resolve().parents[2]
    script = (root / "src/ai_fc/dashboard_parts/dashboard.js").read_text(encoding="utf-8")
    styles = (root / "src/ai_fc/dashboard_parts/dashboard.css").read_text(encoding="utf-8")
    template = (root / "src/ai_fc/dashboard_template.html").read_text(encoding="utf-8")
    workflow = (root / ".github/workflows/statistics-refresh.yml").read_text(encoding="utf-8")
    assert 'href="#statistics" data-v="statistics"' in template
    assert "function renderStatistics" in script
    assert "function statisticsChartSvg" in script
    assert "function statisticsProfileCards" in script
    assert "function statisticsProfileRows" in script
    assert 'data-era="${esc(row.era||\'reference\')}"' in script
    assert '.statistics-profile-row[data-era="current"]>i span' in styles
    assert "stats.reference_statistics" in script
    assert "data-stat-reference-section" in script
    assert "IPO 참고 통계" in script
    assert "${referenceCharts.length}개 비교" in script
    assert "referenceSection.hidden=active!=='all'&&active!=='ipo'" in script
    assert "const applyStatCategory=(key,sync)=>{" in script
    assert "history.replaceState(null,'',active==='all'?'#statistics':'#statistics/'+active)" in script
    assert ".statistics-reference>header h2" in styles
    assert "function statisticsLiquidityBars" in script
    assert "is-diverging" in script
    assert "--bar-left" in script
    assert "--bar-width" in script
    assert "statistics-scope-note" in script
    assert "function statisticsSourceFooter" not in script
    assert "statistics-card-sources" not in script
    assert "사용한 데이터 출처" not in script
    assert "chart.chart_type==='profile_cards'" in script
    assert "chart.chart_type==='liquidity_bars'" in script
    assert ".statistics-card.is-liquidity-map{grid-column:1/-1}" in styles
    assert ".statistics-liquidity-map{padding:18px;display:grid;grid-template-columns:repeat(2" in styles
    assert ".statistics-liquidity-map{padding:10px;grid-template-columns:1fr" in styles
    assert '<div class="statistics-now"><strong>현재 결론</strong><p>' in script
    assert '<span>현재 결론</span>' not in script
    assert 'data-forecast-extension="false"' in script
    assert "AI 선은 최신 실제 관측에서 멈추며" not in script
    assert "지금 시장의 위치를 살펴봅니다" in script
    assert "${esc(chart.description)}" not in script
    assert "닷컴 1995~1999" in script
    assert "한눈에 보는 의미" in script
    assert "해석할 때 주의" not in script
    assert "esc(chart.caveat)" not in script
    assert "IPO·상장" in script
    assert "statistics-detail-rows" not in script
    assert "percent_20d_log_return" in script
    assert "변동성·날짜 조정 없음" in script
    assert "비트코인 로그수익률 변동성 맞춤" not in script
    assert 'data-stat-scale="${useLog?\'log1p\':\'linear\'}"' in script
    assert "chart.axis_type==='calendar_day_of_year'" in script
    assert "chart.observed_end_label" in script
    assert "unit==='percent_of_us_corporate_equity_value'" in script
    assert "unit==='percentage_point_change'" in script
    assert "unit==='neutral_line_distance'" in script
    assert "닷컴과 지금, 숫자로 나란히 보기" in script
    assert 'cron: "20 0 * * 6"' in workflow
    assert "python -m ai_fc ipo-reference-batch" in workflow
    assert "python -m ai_fc statistics-refresh" in workflow
    assert "data/statistics/ipo/reference_batch_receipts" in workflow
    assert "python -m ai_fc inventory" in workflow
    assert "docs/generated/inventory.generated.md" in workflow


def test_dashboard_projection_preserves_endpoints_with_compact_coordinates(tmp_path: Path) -> None:
    rows, receipts = _payload_inputs()
    payload = build_statistics_lab(
        rows,
        generated_at="2026-12-31T00:00:00+00:00",
        receipts=receipts,
        ipo_reference=_repo_ipo_reference(),
        hmi_reference=_repo_hmi_reference(),
    )
    latest = tmp_path / "data/statistics/dotcom_statistics_latest.json"
    latest.parent.mkdir(parents=True)
    latest.write_text(json.dumps(payload), encoding="utf-8")
    projected = statistics_dashboard_projection(tmp_path)
    assert all("range" not in chart for chart in projected["charts"])
    assert all("raw_sha256" not in source for source in projected["sources"])
    assert all("native_frequency" in source for source in projected["sources"] if source["series_id"] in FRED_SERIES)
    assert all("latest_observation" in source for source in projected["sources"] if source["series_id"] in FRED_SERIES)
    assert all(len(source["raw_sha256"]) == 64 for source in payload["sources"])
    for raw_chart, view_chart in zip(payload["charts"], projected["charts"]):
        for raw_series, view_series in zip(raw_chart["series"], view_chart["series"]):
            if raw_chart.get("axis_type") == "calendar_day_of_year":
                assert len(view_series["points"]) == len(raw_series["points"])
            else:
                assert len(view_series["points"]) <= int(
                    raw_chart.get("projection_max_points", 14)
                )
            assert view_series["points"][0]["period"] == raw_series["points"][0]["period"]
            assert view_series["points"][-1]["period"] == raw_series["points"][-1]["period"]
    pulse = next(
        chart for chart in projected["charts"]
        if chart["id"] == "korea_semiconductor_cycle"
    )
    assert pulse["source_ids"] == ["SPASTT01KRM661N", "NASDAQSOX"]
    assert len(pulse["series"]) == 2


def test_ipo_reference_is_actual_only_and_sec_auditable() -> None:
    payload = _repo_ipo_reference()
    validate_ipo_reference(payload)
    assert payload["coverage"]["current_axis_end"] == 2027
    assert payload["coverage"]["current_line_policy"] == "actual_observations_only_no_forecast_extension"
    assert len(payload["sources"]) == 27
    assert all(source["raw_sha256"] for source in payload["sources"])
    fred_sources = [source for source in payload["sources"] if source["series_id"] in FRED_SERIES]
    assert all("fredgraph.csv?id=" in source["request_url"] for source in fred_sources)
    sec_sources = [source for source in payload["sources"] if source["series_id"].startswith("SEC_")]
    assert len(sec_sources) == 7
    assert all("sec.gov/Archives/edgar/data" in source["source_url"] for source in sec_sources)
    broad = payload["ai_broad_cohort"]
    assert [row["year"] for row in broad] == [2023, 2024, 2025, 2026]
    assert [len(row["issuers"]) for row in broad] == [2, 5, 10, 5]
    assert all(2 <= issuer["dependency_tier"] <= 5 for row in broad for issuer in row["issuers"])
    assert [sum(issuer["core_member"] for issuer in row["issuers"]) for row in broad] == [0, 2, 3, 1]
    qualitative = payload["qualitative_ipo"]
    assert qualitative["listed_ai_beneficiary_watchlist"]["members"][0]["name"] == "SK hynix"
    assert qualitative["listed_ai_beneficiary_watchlist"]["members"][0]["count_period"] == 2026
    assert "nasdaq_ads_listing_events" in qualitative["influence_inclusive_count"]["semantics"]
    assert [row["ticker"] for row in qualitative["nasdaq_memory_market_events"]["members"]] == ["MONT", "SKHY"]
    assert [row["name"] for row in qualitative["global_ai_chip_completed_ipos"]["members"]] == [
        "Horizon Robotics", "Black Sesame International", "Moore Threads", "MetaX Integrated Circuits"
    ]
    sensitivity = qualitative["reported_frontier_ai_ipo_sensitivity"]
    assert sensitivity["semantics"].endswith("not_a_completed_offering_or_base_case")
    assert sum(row["headline_ipo_valuation_bn"] for row in sensitivity["members"]) == 3000
    assert sensitivity["float_sensitivity"][1] == {
        "float_percent": 5, "gross_offering_value_bn": 150,
    }


def test_published_fedfunds_dotcom_path_is_monthly_and_not_a_rectangle() -> None:
    root = Path(__file__).resolve().parents[2]
    payload = json.loads(
        (root / "data/statistics/dotcom_statistics_latest.json").read_text(encoding="utf-8")
    )
    chart = next(row for row in payload["charts"] if row["id"] == "policy_rate")
    points = next(row for row in chart["series"] if row["era"] == "dotcom")["points"]
    assert len(points) == 60
    assert len({float(row["value"]) for row in points}) > 30
    assert chart["source_validation"]["minimum"] == {
        "period": 48, "date": "1999-01-01", "value": 4.63,
    }
    assert chart["source_validation"]["maximum"] == {
        "period": 3, "date": "1995-04-01", "value": 6.05,
    }
    assert chart["source_validation"]["interpolation"] is False
    assert chart["source_validation"]["perfect_rectangle"] is False


def test_ipo_broad_cohort_rejects_count_drift_and_minimal_ai_usage() -> None:
    payload = _repo_ipo_reference()
    invalid_count = json.loads(json.dumps(payload))
    invalid_count["ai_broad_cohort"][0]["issuers"].pop()
    with pytest.raises(StatisticsLabError, match="does not reconcile"):
        validate_ipo_reference(invalid_count)

    invalid_influence = json.loads(json.dumps(payload))
    comparison = next(
        chart for chart in invalid_influence["charts"]
        if chart["id"] == "internet_vs_ai_core_ipos"
    )
    next(
        row for row in comparison["series"]
        if row["label"] == "현재 AI IPO·NASDAQ ADS 영향 포함"
    )["points"][-1]["value"] = 7
    with pytest.raises(StatisticsLabError, match="influence-inclusive"):
        validate_ipo_reference(invalid_influence)

    invalid_tier = json.loads(json.dumps(payload))
    invalid_tier["ai_broad_cohort"][0]["issuers"][0]["dependency_tier"] = 1
    with pytest.raises(StatisticsLabError, match="dependency tier invalid"):
        validate_ipo_reference(invalid_tier)

    invalid_core = json.loads(json.dumps(payload))
    invalid_core["ai_broad_cohort"][1]["issuers"][0]["core_member"] = False
    with pytest.raises(StatisticsLabError, match="marked broad-cohort members"):
        validate_ipo_reference(invalid_core)

    invalid_watch = json.loads(json.dumps(payload))
    invalid_watch["qualitative_ipo"]["listed_ai_beneficiary_watchlist"]["semantics"] = "ipo_count"
    with pytest.raises(StatisticsLabError, match="listed AI beneficiary watchlist semantics invalid"):
        validate_ipo_reference(invalid_watch)
