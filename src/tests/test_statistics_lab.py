from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import date
from pathlib import Path

from ai_fc.statistics_lab import (
    FRED_SERIES,
    _parse_fred_csv,
    _parse_z1,
    build_statistics_lab,
    load_ipo_reference,
    load_statistics_lab,
    refresh_statistics_lab,
    statistics_dashboard_projection,
    validate_ipo_reference,
    validate_statistics_lab,
)


def _rows(series_id: str) -> list[dict[str, float | str]]:
    rows = []
    start = date(1995, 1, 1)
    for offset in range(0, 32 * 12):
        year = start.year + (start.month - 1 + offset) // 12
        month = (start.month - 1 + offset) % 12 + 1
        baseline = {
            "M2SL": 4000.0,
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
        }[series_id]
        growth = 1.0 + offset * (0.001 if series_id not in {"T10Y2Y", "FEDFUNDS", "TDSP", "BOGZ1FL010000346Q", "DRTSCILM", "UNRATE", "NFCI"} else 0.0)
        value = baseline * growth
        if series_id == "T10Y2Y":
            value = ((offset % 30) - 12) / 10
        elif series_id == "DRTSCILM":
            value = ((offset % 20) - 6) * 2.0
        elif series_id == "UNRATE":
            value = 3.5 + (offset % 18) / 10.0
        elif series_id == "NFCI":
            value = ((offset % 24) - 14) / 10.0
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


def _payload_inputs() -> tuple[dict, dict]:
    rows = {series_id: _rows(series_id) for series_id in FRED_SERIES}
    z1 = _z1_bytes()
    rows["FL663067003"] = _parse_z1(z1)
    receipts = {
        series_id: {"raw_sha256": hashlib.sha256(series_id.encode()).hexdigest()}
        for series_id in rows
    }
    return rows, receipts


def _repo_ipo_reference() -> dict:
    root = Path(__file__).resolve().parents[2]
    return load_ipo_reference(root)


def _install_ipo_reference(root: Path) -> None:
    target = root / "data/statistics/ipo/ipo_comparison_v1.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(_repo_ipo_reference(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def test_parsers_reject_missing_and_preserve_explicit_values() -> None:
    parsed = _parse_fred_csv(
        b"observation_date,M2SL\n2026-01-01,22000\n2026-02-01,.\n", "M2SL"
    )
    assert parsed == [{"date": "2026-01-01", "value": 22000.0}]
    assert _parse_z1(_z1_bytes())[0]["date"] == "1995-01-01"


def test_build_statistics_lab_has_reference_only_distinct_charts() -> None:
    rows, receipts = _payload_inputs()
    payload = build_statistics_lab(
        rows,
        generated_at="2026-08-11T00:00:00+00:00",
        receipts=receipts,
        ipo_reference=_repo_ipo_reference(),
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
    assert len(payload["charts"]) == 19
    assert all(chart["insight"] for chart in payload["charts"])
    assert {chart["id"] for chart in payload["charts"]} >= {
        "m2_nasdaq", "yield_curve", "valuation_proxy", "margin_credit_proxy",
        "household_debt_service", "unemployment_rate", "inflation_rate",
        "financial_conditions",
        "internet_vs_ai_core_ipos", "technology_ipo_count",
        "technology_ipo_first_day_return", "technology_ipo_price_to_sales",
        "technology_ipo_profitable_share", "all_ipo_negative_earnings_share",
    }
    ipo_chart = next(chart for chart in payload["charts"] if chart["id"] == "internet_vs_ai_core_ipos")
    assert ipo_chart["series"][0]["points"][-1]["value"] == 273
    assert ipo_chart["series"][1]["points"][-1] == {
        "period": 36, "date": "2026-05-14", "value": 1
    }
    assert ipo_chart["detail_rows"][0]["label"] == "Astera Labs · Tempus AI"
    assert payload["ipo_comparison"]["classification"]["ai_core_limit"].startswith("This is a conservative")
    valuation = next(chart for chart in payload["charts"] if chart["id"] == "valuation_proxy")
    assert "대용치" in valuation["title"]
    assert {row["era"] for row in valuation["series"]} == {"dotcom", "current"}
    for chart in payload["charts"]:
        dotcom = [row for row in chart["series"] if row["era"] == "dotcom"]
        current = [row for row in chart["series"] if row["era"] == "current"]
        assert max(point["period"] for row in dotcom for point in row["points"]) <= 59
        assert max(point["period"] for row in current for point in row["points"]) < 59
    invalid = json.loads(json.dumps(payload))
    invalid["cycle_alignment"]["forecast_extension"] = True
    try:
        validate_statistics_lab(invalid)
    except Exception as exc:
        assert "alignment contract" in str(exc)
    else:
        raise AssertionError("forecast extension must be rejected")


def test_refresh_is_append_only_for_changed_weekly_snapshot(tmp_path: Path) -> None:
    rows, _ = _payload_inputs()
    _install_ipo_reference(tmp_path)

    def fred_fetcher(series_id: str):
        raw = f"fixture:{series_id}".encode()
        return rows[series_id], raw

    z1 = _z1_bytes()
    path, payload, changed = refresh_statistics_lab(
        tmp_path, fred_fetcher=fred_fetcher, z1_fetcher=lambda _url: z1
    )
    assert changed is True
    assert path.is_file()
    archives = list((tmp_path / "data/statistics/archive").glob("*.json"))
    assert len(archives) == 1
    _, second, changed_again = refresh_statistics_lab(
        tmp_path, fred_fetcher=fred_fetcher, z1_fetcher=lambda _url: z1
    )
    assert changed_again is False
    assert second["as_of"] == payload["as_of"]
    assert len(list((tmp_path / "data/statistics/archive").glob("*.json"))) == 1
    loaded = load_statistics_lab(tmp_path)
    assert json.loads(path.read_text(encoding="utf-8"))["dataset_id"] == loaded["dataset_id"]


def test_dashboard_statistics_route_and_weekly_workflow_are_wired() -> None:
    root = Path(__file__).resolve().parents[2]
    script = (root / "src/ai_fc/dashboard_parts/dashboard.js").read_text(encoding="utf-8")
    template = (root / "src/ai_fc/dashboard_template.html").read_text(encoding="utf-8")
    workflow = (root / ".github/workflows/statistics-refresh.yml").read_text(encoding="utf-8")
    assert 'href="#statistics" data-v="statistics"' in template
    assert "function renderStatistics" in script
    assert "function statisticsChartSvg" in script
    assert 'data-forecast-extension="false"' in script
    assert "AI 선은 최신 실제 관측에서 멈추며" in script
    assert "닷컴 1995~1999" in script
    assert "한눈에 보는 의미" in script
    assert "해석할 때 주의" in script
    assert "IPO·상장" in script
    assert "statistics-detail-rows" in script
    assert "닷컴과 지금, 숫자로 나란히 보기" in script
    assert 'cron: "20 0 * * 6"' in workflow
    assert "python -m ai_fc statistics-refresh" in workflow


def test_dashboard_projection_preserves_endpoints_with_compact_coordinates(tmp_path: Path) -> None:
    rows, receipts = _payload_inputs()
    payload = build_statistics_lab(
        rows,
        generated_at="2026-08-11T00:00:00+00:00",
        receipts=receipts,
        ipo_reference=_repo_ipo_reference(),
    )
    latest = tmp_path / "data/statistics/dotcom_statistics_latest.json"
    latest.parent.mkdir(parents=True)
    latest.write_text(json.dumps(payload), encoding="utf-8")
    projected = statistics_dashboard_projection(tmp_path)
    for raw_chart, view_chart in zip(payload["charts"], projected["charts"]):
        for raw_series, view_series in zip(raw_chart["series"], view_chart["series"]):
            assert len(view_series["points"]) <= 20
            assert view_series["points"][0]["period"] == raw_series["points"][0]["period"]
            assert view_series["points"][-1]["period"] == raw_series["points"][-1]["period"]


def test_ipo_reference_is_actual_only_and_sec_auditable() -> None:
    payload = _repo_ipo_reference()
    validate_ipo_reference(payload)
    assert payload["coverage"]["current_axis_end"] == 2027
    assert payload["coverage"]["current_line_policy"] == "actual_observations_only_no_forecast_extension"
    assert len(payload["sources"]) == 8
    assert all(source["raw_sha256"] for source in payload["sources"])
    sec_sources = [source for source in payload["sources"] if source["series_id"].startswith("SEC_")]
    assert len(sec_sources) == 6
    assert all("sec.gov/Archives/edgar/data" in source["source_url"] for source in sec_sources)
