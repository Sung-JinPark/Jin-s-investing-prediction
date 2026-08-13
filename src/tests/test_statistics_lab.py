from __future__ import annotations

import hashlib
import io
import json
import urllib.error
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from ai_fc.statistics_lab import (
    FRED_SERIES,
    StatisticsLabError,
    _parse_fred_csv,
    _parse_z1,
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


def _rows(series_id: str) -> list[dict[str, float | str]]:
    rows = []
    start = date(1995, 1, 1)
    for offset in range(0, 32 * 12):
        year = start.year + (start.month - 1 + offset) // 12
        month = (start.month - 1 + offset) % 12 + 1
        if series_id in {"DABSHNO", "BOGZ1LM893064105Q"} and month not in {1, 4, 7, 10}:
            continue
        baseline = {
            "M2SL": 4000.0,
            "DABSHNO": 8_000_000.0,
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
            "SPASTT01KRM661N": 100.0,
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


def test_parsers_reject_missing_and_preserve_explicit_values() -> None:
    parsed = _parse_fred_csv(
        b"observation_date,M2SL\n2026-01-01,22000\n2026-02-01,.\n", "M2SL"
    )
    assert parsed == [{"date": "2026-01-01", "value": 22000.0}]
    assert _parse_z1(_z1_bytes())[0]["date"] == "1995-01-01"


def test_manual_reference_staleness_stops_weekly_republication() -> None:
    ipo = _repo_ipo_reference()
    hmi = _repo_hmi_reference()
    _validate_manual_reference_freshness(ipo, hmi, "2026-08-13T00:00:00+00:00")
    with pytest.raises(StatisticsLabError, match="IPO reviewed cohort stale"):
        _validate_manual_reference_freshness(ipo, hmi, "2026-09-01T00:00:00+00:00")


def test_build_statistics_lab_has_reference_only_distinct_charts() -> None:
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
    assert len(payload["charts"]) == 28
    assert all(chart["insight"] for chart in payload["charts"])
    assert {chart["id"] for chart in payload["charts"]} >= {
        "m2_nasdaq", "nasdaq_per_m2", "nasdaq_per_household_liquid_assets",
        "yield_curve", "valuation_proxy", "margin_credit_proxy",
        "household_debt_service", "unemployment_rate", "inflation_rate",
        "financial_conditions",
        "internet_vs_ai_core_ipos", "technology_ipo_count",
        "technology_ipo_first_day_return", "technology_ipo_price_to_sales",
        "technology_ipo_profitable_share", "all_ipo_negative_earnings_share",
        "ipo_market_absorption", "small_issuer_ipo_share", "global_ai_capital_map",
        "rate_cycle_since_first_cut", "corporate_bond_pressure",
        "inflation_lead_panel", "housing_manufacturing_warning",
        "kospi_nasdaq_relative_lead",
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
    assert "SK하이닉스(기존 상장)" in ipo_chart["detail_rows"][-1]["label"]
    assert ipo_chart["detail_rows"][0]["label"] == "Arm · Klaviyo"
    capital_map = next(chart for chart in payload["charts"] if chart["id"] == "global_ai_capital_map")
    assert capital_map["series"][0]["points"] == [
        {"period": 12, "date": "2024-12-31", "value": 2},
        {"period": 24, "date": "2025-12-31", "value": 2},
    ]
    assert capital_map["series"][1]["points"] == [
        {"period": 36, "date": "2026-08-13", "value": 1}
    ]
    assert "SK하이닉스" in capital_map["insight"]
    absorption = next(chart for chart in payload["charts"] if chart["id"] == "ipo_market_absorption")
    assert any(row["period"] == "질적 포함" and row["label"] == "SK하이닉스" for row in absorption["detail_rows"])
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
    kospi = next(chart for chart in payload["charts"] if chart["id"] == "kospi_nasdaq_relative_lead")
    assert kospi["source_ids"] == ["SPASTT01KRM661N", "NASDAQCOM"]
    assert [row["lead_months"] for row in kospi["lead_diagnostics"]] == [0, 1, 2, 3]
    assert all(row["observations"] > 300 for row in kospi["lead_diagnostics"])
    assert len(kospi["detail_rows"]) == 4
    assert "사후 최적 시차 선택" in kospi["caveat"]
    for chart in payload["charts"]:
        dotcom = [row for row in chart["series"] if row["era"] == "dotcom"]
        current = [row for row in chart["series"] if row["era"] == "current"]
        if dotcom:
            assert max(point["period"] for row in dotcom for point in row["points"]) <= 59
        if current:
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


def test_refresh_is_append_only_for_changed_weekly_snapshot(tmp_path: Path) -> None:
    rows, _ = _payload_inputs()
    _install_ipo_reference(tmp_path)

    def fred_fetcher(series_id: str):
        raw = f"fixture:{series_id}".encode()
        return rows[series_id], raw

    z1 = _z1_bytes()
    path, payload, changed = refresh_statistics_lab(
        tmp_path, fred_fetcher=fred_fetcher, z1_fetcher=lambda _url: z1,
        now=datetime(2026, 12, 31, tzinfo=timezone.utc),
    )
    assert changed is True
    assert path.is_file()
    archives = list((tmp_path / "data/statistics/archive").glob("*.json"))
    assert len(archives) == 1
    _, second, changed_again = refresh_statistics_lab(
        tmp_path, fred_fetcher=fred_fetcher, z1_fetcher=lambda _url: z1,
        now=datetime(2026, 12, 31, tzinfo=timezone.utc),
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
    assert 'data-stat-scale="${useLog?\'log1p\':\'linear\'}"' in script
    assert "unit==='percent_of_us_corporate_equity_value'" in script
    assert "unit==='percentage_point_change'" in script
    assert "unit==='neutral_line_distance'" in script
    assert "닷컴과 지금, 숫자로 나란히 보기" in script
    assert 'cron: "20 0 * * 6"' in workflow
    assert "python -m ai_fc statistics-refresh" in workflow
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
    assert all(len(source["raw_sha256"]) == 64 for source in projected["sources"])
    for raw_chart, view_chart in zip(payload["charts"], projected["charts"]):
        for raw_series, view_series in zip(raw_chart["series"], view_chart["series"]):
            assert len(view_series["points"]) <= 18
            assert view_series["points"][0]["period"] == raw_series["points"][0]["period"]
            assert view_series["points"][-1]["period"] == raw_series["points"][-1]["period"]


def test_ipo_reference_is_actual_only_and_sec_auditable() -> None:
    payload = _repo_ipo_reference()
    validate_ipo_reference(payload)
    assert payload["coverage"]["current_axis_end"] == 2027
    assert payload["coverage"]["current_line_policy"] == "actual_observations_only_no_forecast_extension"
    assert len(payload["sources"]) == 24
    assert all(source["raw_sha256"] for source in payload["sources"])
    fred_sources = [source for source in payload["sources"] if source["series_id"] in FRED_SERIES]
    assert all("fredgraph.csv?id=" in source["request_url"] for source in fred_sources)
    sec_sources = [source for source in payload["sources"] if source["series_id"].startswith("SEC_")]
    assert len(sec_sources) == 6
    assert all("sec.gov/Archives/edgar/data" in source["source_url"] for source in sec_sources)
    broad = payload["ai_broad_cohort"]
    assert [row["year"] for row in broad] == [2023, 2024, 2025, 2026]
    assert [len(row["issuers"]) for row in broad] == [2, 5, 10, 5]
    assert all(2 <= issuer["dependency_tier"] <= 5 for row in broad for issuer in row["issuers"])
    assert [sum(issuer["core_member"] for issuer in row["issuers"]) for row in broad] == [0, 2, 3, 1]
    qualitative = payload["qualitative_ipo"]
    assert qualitative["listed_ai_beneficiary_watchlist"]["members"][0]["name"] == "SK hynix"
    assert qualitative["listed_ai_beneficiary_watchlist"]["members"][0]["count_period"] == 2026
    assert qualitative["influence_inclusive_count"]["semantics"].endswith("not_an_ipo_count")
    assert [row["name"] for row in qualitative["global_ai_chip_completed_ipos"]["members"]] == [
        "Horizon Robotics", "Black Sesame International", "Moore Threads", "MetaX Integrated Circuits"
    ]


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
        if row["label"] == "현재 AI 영향력 포함 집계"
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
