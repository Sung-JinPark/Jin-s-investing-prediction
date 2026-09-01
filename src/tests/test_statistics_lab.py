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
    CENSUS_C30_SERIES,
    Z1_SERIES,
    FRED_SERIES,
    IPO_REFERENCE_CHART_IDS,
    StatisticsLabError,
    _fetch_fred,
    _fetch_supplemental,
    _parse_fred_csv,
    _parse_ici_weekly_html,
    _parse_nyu_returns_xlsx,
    _parse_sec_ipo_xlsx,
    _parse_census_c30,
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


def test_fred_fetch_uses_the_official_api_over_the_same_url_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """수집은 fredgraph.csv 스크랩이 아니라 공식 API 경로여야 한다.

    FRED 약관이 자동 수집을 API 경로로만 허용하기 때문이다 (DECISIONS 12-6).
    감사된 curl 폴백 전송과 45초 타임아웃은 종전 그대로 쓴다.
    """
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    seen: list[tuple[str, int]] = []

    def fetched(url: str, *, timeout: int) -> str:
        seen.append((url, timeout))
        return '{"observations": [{"date": "2026-07-01", "value": "22000.5"}]}'

    monkeypatch.setattr("ai_fc.quant.feed.get_with_curl_fallback", fetched)
    rows, raw = _fetch_fred("M2SL")

    assert len(seen) == 1
    url, timeout = seen[0]
    assert url.startswith("https://api.stlouisfed.org/fred/series/observations?")
    assert "series_id=M2SL" in url
    assert "observation_start=1995-01-01" in url
    assert "fredgraph.csv" not in url
    assert timeout == 45
    # 파서와 영수증 바이트는 종전 CSV 모양 그대로 유지된다.
    assert rows == [{"date": "2026-07-01", "value": 22000.5}]
    assert raw == b"observation_date,M2SL\n2026-07-01,22000.5\n"
    # 영수증 바이트에 키가 섞여 들어가면 안 된다.
    assert b"test-key" not in raw


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
            "T10Y3M": 0.6,
            "FEDFUNDS": 5.0,
            "TOTALSL": 1_000_000.0,
            "TDSP": 12.0,
            "BOGZ1FL010000346Q": 12.0,
            "DRTSCILM": 5.0,
            "NCBEILQ027S": 8_000_000.0,
            "CPATAX": 600.0,
            "W328RC1Q027SBEA": 480.0,
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
            "GDP": 20_000.0,
            "SPASTT01USM661N": 45.0,
            "GFDEBTN": 4_900_000.0,
            "Y034RC1Q027SBEA": 500.0,
            "Y001RC1Q027SBEA": 1_000.0,
        }[series_id]
        growth = 1.0 + offset * (0.001 if series_id not in {"T10Y2Y", "T10Y3M", "FEDFUNDS", "TDSP", "BOGZ1FL010000346Q", "DRTSCILM", "UNRATE", "NFCI", "HQMCB10YR", "GS10", "GACDFSA066MSFRBPHI"} else 0.0)
        value = baseline * growth
        if series_id == "T10Y2Y":
            value = ((offset % 30) - 12) / 10
        elif series_id == "T10Y3M":
            value = ((offset % 30) - 10) / 10
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
        for index, (series_id, spec) in enumerate(Z1_SERIES.items()):
            lines = [f"date,{spec['field']}"]
            base = 100000 * (index + 1)
            for year in range(1995, 2027):
                for quarter in range(1, 5):
                    lines.append(
                        f"{year}:Q{quarter},{base + (year - 1995) * 10000 + quarter}"
                    )
            archive.writestr(spec["member"], "\n".join(lines) + "\n")
    return target.getvalue()


def _c30_bytes() -> bytes:
    """A C30-shaped workbook: title rows, a header row, newest month first.

    The data-centre column is deliberately left blank before 2014 so the
    fixture reproduces the real file's ragged history.
    """
    header = ["Date"]
    for spec in CENSUS_C30_SERIES.values():
        header.append(spec["column"])
    rows: list[list[object]] = [
        ["Value of Private Construction Put in Place"],
        ["(Millions of dollars.)"],
        [],
        header,
    ]
    months = [
        "jan", "feb", "mar", "apr", "may", "jun",
        "jul", "aug", "sep", "oct", "nov", "dec",
    ]
    for year in range(2026, 1992, -1):
        for index in range(11, -1, -1):
            if year == 2026 and index > 5:
                continue
            label = f"{months[index].capitalize()}-{year % 100:02d}"
            row: list[object] = [label]
            for offset, series_id in enumerate(CENSUS_C30_SERIES):
                if series_id == "C30_OFFICE_DATA_CENTER" and year < 2014:
                    row.append(None)
                else:
                    row.append(1000 + offset * 100 + (year - 1993) * 10 + index)
            rows.append(row)
    return _xlsx_fixture("Private NSA", rows)


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
            if value is None:
                # A blank cell, as a real workbook writes a missing observation.
                cells.append(f'<c r="{ref}"/>')
            elif isinstance(value, str):
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
    for z1_series_id in Z1_SERIES:
        rows[z1_series_id] = _parse_z1(z1, z1_series_id)
    c30 = _c30_bytes()
    for c30_series_id in CENSUS_C30_SERIES:
        rows[c30_series_id] = _parse_census_c30(c30, c30_series_id)
    receipts = {
        series_id: {"raw_sha256": hashlib.sha256(series_id.encode()).hexdigest()}
        for series_id in rows
    }
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
    assert len(payload["charts"]) == 26  # spx_per_federal_debt 추가로 25→26
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
    assert len(payload["charts"]) == 26  # spx_per_federal_debt 추가로 25→26
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
    for z1_series_id in Z1_SERIES:
        source_rows[z1_series_id] = [
            {"date": "2026-01-01", "value": 50.0},
        ]
    for c30_series_id in CENSUS_C30_SERIES:
        source_rows[c30_series_id] = [
            {"date": "2026-01-01", "value": 75.0},
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
    series_ids = [*FRED_SERIES, *Z1_SERIES, *CENSUS_C30_SERIES, "SEC_IPO_QUARTERLY"]
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


    def supplemental_fetcher(series_id: str):
        raw = f"supplemental-fixture:{series_id}".encode()
        return (
            rows[series_id], raw,
            "https://www.sec.gov/files/dera/data/sec-stats-ipos-2026.xlsx",
        )

    z1 = _z1_bytes()
    # Built once: zipfile stamps entry times, so a fresh call would change
    # the artifact hash and make an unchanged refresh look changed.
    c30 = _c30_bytes()
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
        tmp_path, fred_fetcher=fred_fetcher,
        supplemental_fetcher=supplemental_fetcher,
        z1_fetcher=lambda _url: z1,
        census_c30_fetcher=lambda _url: c30,
        now=datetime(2026, 12, 31, tzinfo=timezone.utc),
    )
    assert changed is True
    assert path.is_file()
    archives = list((tmp_path / "data/statistics/archive").glob("*.json"))
    assert len(archives) == 1
    _, second, changed_again = refresh_statistics_lab(
        tmp_path, fred_fetcher=fred_fetcher,
        supplemental_fetcher=supplemental_fetcher,
        z1_fetcher=lambda _url: z1,
        census_c30_fetcher=lambda _url: c30,
        now=datetime(2026, 12, 31, tzinfo=timezone.utc),
    )
    assert changed_again is False
    assert second["as_of"] == payload["as_of"]
    assert len(list((tmp_path / "data/statistics/archive").glob("*.json"))) == 1
    refresh_statistics_lab(
        tmp_path, fred_fetcher=fred_fetcher,
        supplemental_fetcher=supplemental_fetcher,
        z1_fetcher=lambda _url: z1,
        census_c30_fetcher=lambda _url: c30,
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
    assert "syncMidHash(active==='all'?'#statistics':'#statistics/'+active)" in script
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
    # 검수 결정: 대용치·명목 경고(caveat)는 화면에 도달해야 한다.
    # 카드마다 '이 수치의 한계' 접힘 블록으로 렌더한다.
    assert 'class="chart-method statistics-caveat"' in script
    assert "이 수치의 한계" in script
    assert "esc(chart.caveat)" in script
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
    # IPO 참고 원장은 FRED를 쓰지 않는다 — 여기서 all()로 FRED URL을 검사하면
    # 빈 리스트에 대한 공허참이 된다. 부재 자체를 단언하는 것이 올바른 검사다.
    fred_sources = [source for source in payload["sources"] if source["series_id"] in FRED_SERIES]
    assert fred_sources == [], "IPO 참고 원장에 FRED 원천이 섞이면 안 된다"
    # 키·비공식 경로 유출 검사는 원천 전체에 적용한다.
    assert not any("api_key" in str(source.get("request_url", "")) for source in payload["sources"])
    assert not any("fredgraph.csv" in str(source.get("request_url", "")) for source in payload["sources"])
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

def test_sec_user_agent_carries_a_contact(monkeypatch: pytest.MonkeyPatch) -> None:
    """연락처 없는 UA는 SEC가 403으로 막는다 — 이 워크플로가 9일간 멈춘 원인이다.

    SEC가 문서로 요구하는 준수 방법이므로 불변식으로 고정한다. 통과에 필요한 것이
    이메일 '형태'뿐이라 임의 문자열로도 SEC는 200을 주지만, 그것은 규제기관에 허위
    연락처를 신고하는 것이라 하지 않는다 — 그래서 기본값은 소유자가 지정한 실제
    주소이고, 교체하더라도 연락 가능한 주소여야 한다.
    """
    from ai_fc import statistics_lab

    monkeypatch.delenv("AI_FC_SEC_USER_AGENT", raising=False)
    assert "@" in statistics_lab._user_agent()
    assert statistics_lab.SEC_CONTACT in statistics_lab._user_agent()

    # 환경변수로 덮어쓰더라도 연락처가 없으면 조용히 403을 맞기 전에 실패한다.
    monkeypatch.setenv("AI_FC_SEC_USER_AGENT", "NoContactBot/1.0")
    with pytest.raises(statistics_lab.StatisticsLabError):
        statistics_lab._user_agent()

    # 정상 교체는 허용된다.
    monkeypatch.setenv("AI_FC_SEC_USER_AGENT", "Other/1.0 (someone@example.org)")
    assert statistics_lab._user_agent() == "Other/1.0 (someone@example.org)"


def test_spx_per_federal_debt_compares_both_eras_from_full_history_sources() -> None:
    """연방부채 대비 미국 주가 비율 차트가 두 시대를 같은 시작=100으로 비교한다.

    FRED SP500은 최근 10년만 제공해 닷컴 구간이 없으므로, 분자는 전 구간이 열린
    OECD 미국 주가지수(SPASTT01USM661N)여야 한다. 분모는 재무부 GFDEBTN.
    """
    rows, receipts = _payload_inputs()
    payload = build_statistics_lab(
        rows,
        generated_at="2026-12-31T00:00:00+00:00",
        receipts=receipts,
        ipo_reference=_repo_ipo_reference(),
        hmi_reference=_repo_hmi_reference(),
    )
    chart = next(row for row in payload["charts"] if row["id"] == "spx_per_federal_debt")

    assert chart["category"] == "liquidity"
    assert chart["unit"] == "cycle_start_100"
    assert chart["source_ids"] == ["SPASTT01USM661N", "GFDEBTN"]
    eras = {series["era"] for series in chart["series"]}
    assert eras == {"dotcom", "current"}, "닷컴·현재 두 시대가 모두 있어야 한다"
    for series in chart["series"]:
        points = series["points"]
        assert points, series["label"]
        assert abs(float(points[0]["value"]) - 100.0) < 1e-6, "시작=100 지수화"
    assert "S&P 500 종가가" in chart["caveat"], "OECD 월평균 대용임을 명시"
    assert "조 달러" in chart["conclusion"], "최근 연방부채 수준을 결론에 병기"

    registered = {source["series_id"] for source in payload["sources"]}
    assert {"SPASTT01USM661N", "GFDEBTN"} <= registered
    us_share = next(
        source for source in payload["sources"]
        if source["series_id"] == "SPASTT01USM661N"
    )
    assert "OECD" in us_share["provider"]
