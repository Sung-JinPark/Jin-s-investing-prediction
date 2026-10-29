from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ai_fc.statistics_freshness import (
    audit_statistics_freshness, build_indicator_freshness, load_source_checks,
)

ROOT = Path(__file__).resolve().parents[2]
NOW = "2026-10-29T01:42:00+00:00"


def fixture(*, frequency="quarterly", observed="2026-04-01", sid="Q"):
    source = {"series_id": sid, "native_frequency": frequency,
              "latest_observation": observed, "available_at": "2026-10-28T12:00:00+00:00"}
    chart = {"id": "c", "source_ids": [sid], "series": [
        {"label": "현재", "points": [{"date": observed, "value": 1.0}]}]}
    payload = {"sources": [source], "charts": [chart]}
    contract = {"indicators": [{"id": "i", "chart": "c", "current_series": "현재"}]}
    return payload, contract


def report_row(payload, contract, **kwargs):
    return build_indicator_freshness(payload, contract=contract, checked_at=NOW, **kwargs)["indicators"][0]


def test_quarter_start_is_a_quarter_and_successful_unchanged_check_is_current():
    payload, contract = fixture()
    before = copy.deepcopy(payload)
    row = report_row(payload, contract)
    assert row["period_label"] == "2026년 2분기"
    assert row["status"] == "current"
    assert row["latest_observation"] == "2026-04-01"
    assert payload == before


def test_known_household_release_lag_does_not_substitute_newer_definition():
    payload, contract = fixture(observed="2026-01-01", sid="BOGZ1FL010000346Q")
    row = report_row(payload, contract)
    assert row["period_label"] == "2026년 1분기"
    assert row["status"] == "current"


def test_monthly_aggregation_exposes_last_week_separately():
    payload, contract = fixture(frequency="weekly", observed="2026-10-23", sid="NFCI")
    payload["charts"][0]["series"][0]["points"][-1]["date"] = "2026-10-01"
    row = report_row(payload, contract)
    assert row["period_label"] == "2026-10 월평균"
    assert row["source_observation_through"] == "2026-10-23"


def test_unemployment_release_first_friday_is_not_prematurely_overdue():
    payload, contract = fixture(frequency="monthly", observed="2026-09-01", sid="UNRATE")
    payload["sources"][0]["available_at"] = "2026-11-05T12:00:00+00:00"
    report = build_indicator_freshness(payload, contract=contract, checked_at="2026-11-05T13:00:00+00:00")
    assert report["indicators"][0]["status"] == "current"


@pytest.mark.parametrize("changed,expected", [
    ({"refresh_status": "verified_cache_waiting_source"}, "source_waiting"),
    ({"available_at": "2026-10-20T12:00:00+00:00"}, "check_overdue"),
    ({"latest_observation": "2025-01-01"}, "observation_overdue"),
    ({"available_at": None}, "unverified"),
    ({"available_at": "2026-10-30T12:00:00+00:00"}, "unverified"),
    ({"native_frequency": "unknown"}, "unverified"),
])
def test_failures_and_delays_cannot_be_called_current(changed, expected):
    payload, contract = fixture()
    payload["sources"][0].update(changed)
    assert report_row(payload, contract)["status"] == expected


def test_all_dependencies_must_have_recent_successful_checks():
    payload, contract = fixture()
    payload["sources"].append(dict(payload["sources"][0], series_id="other",
                                   available_at="2026-10-20T00:00:00+00:00"))
    payload["charts"][0]["source_ids"].append("other")
    row = report_row(payload, contract)
    assert row["status"] == "check_overdue"
    assert row["last_successful_check"] == "2026-10-20T00:00:00+00:00"


def test_source_check_clock_does_not_advance_retained_cache_or_available_at():
    payload, contract = fixture()
    payload["sources"][0]["available_at"] = "2026-10-01T00:00:00+00:00"
    row = report_row(payload, contract, source_checks={"Q": "2026-10-28T23:00:00+00:00"})
    assert row["status"] == "current"
    assert payload["sources"][0]["available_at"] == "2026-10-01T00:00:00+00:00"
    payload["sources"][0]["refresh_status"] = "verified_cache_waiting_source"
    assert report_row(payload, contract, source_checks={"Q": NOW})["status"] == "source_waiting"


def ipo_fixture():
    payload, contract = fixture(frequency="monthly", observed="2025-12-01", sid="RITTER_IPOALL_MONTHLY")
    payload["sources"][0].update(revision_cadence="author_revises_roughly_annually",
                                  raw_sha256="a" * 64, available_at="2026-10-06T00:00:00+00:00")
    contract["indicators"][0]["id"] = "ipo_count_operating_12m"
    payload["charts"][0]["series"].append({"provisional": True, "points": [{"date": "2026-09-01", "value": 218}]})
    status = {"checked_at": "2026-10-28T12:00:00+00:00",
              "ritter": {"status": "current", "raw_sha256": "a" * 64}, "nasdaq": {"status": "current"}}
    return payload, contract, status


def test_annual_ipo_release_check_and_provisional_series_stay_separate():
    payload, contract, status = ipo_fixture()
    report = build_indicator_freshness(payload, contract=contract, checked_at=NOW, ipo_status=status)
    row = report["indicators"][0]
    assert report["status"] == "ok"
    assert row["period_label"] == "2025-12 확정 · 최근 12개월 합"
    assert row["last_successful_check"] == status["checked_at"]
    assert row["provisional_through"] == "2026-09-01" and row["provisional_value"] == 218
    assert payload["charts"][0]["series"][0]["points"][-1]["value"] == 1.0


def test_wrong_ipo_hash_and_failed_provisional_source_are_reported():
    payload, contract, status = ipo_fixture()
    status["ritter"]["raw_sha256"] = "b" * 64
    status["nasdaq"]["status"] = "stale"
    report = build_indicator_freshness(payload, contract=contract, checked_at=NOW, ipo_status=status)
    assert report["indicators"][0]["status"] == "check_overdue"
    assert report["auxiliary_issues"] == ["ipo_nasdaq_source_waiting"]
    assert report["status"] == "attention"


def test_shipped_snapshot_all_fourteen_are_checked_against_current_source_receipts():
    # CI runs after a real acquisition, including deliberately retained partial
    # releases. Health failures belong to the post-publication strict audit;
    # neither a frozen past clock nor a current-only test may block persistence.
    report = audit_statistics_freshness(ROOT, now=datetime.now(timezone.utc))
    assert len(report["indicators"]) == 14
    assert len({row["id"] for row in report["indicators"]}) == 14
    assert all(row["sources"] and row["last_successful_check"] for row in report["indicators"])


def test_recent_metadata_without_receipt_is_not_verified():
    payload, contract = fixture()
    assert report_row(payload, contract, source_checks={})["status"] == "unverified"
    payload, contract, status = ipo_fixture()
    assert report_row(payload, contract, source_checks={}, ipo_status=status)["status"] == "unverified"


@pytest.mark.parametrize("endpoint", ["bad-date", "2026-11-01"])
def test_invalid_or_future_chart_endpoint_cannot_be_current(endpoint):
    payload, contract = fixture()
    payload["charts"][0]["series"][0]["points"][-1]["date"] = endpoint
    assert report_row(payload, contract)["status"] == "unverified"


def test_chart_cannot_lag_all_its_successfully_updated_sources():
    payload, contract = fixture()
    payload["charts"][0]["series"][0]["points"][-1]["date"] = "2026-01-01"
    assert report_row(payload, contract)["status"] == "observation_overdue"


def test_theme_source_failure_and_nonindicator_source_failure_remain_visible():
    payload, contract, status = ipo_fixture()
    payload["source_refresh"] = {"waiting_series": ["C30_POWER"]}
    theme = {"checked_at": NOW, "venues": {"hk": {"status": "stale"}},
             "summary": {"pending_overdue": 1}}
    report = build_indicator_freshness(payload, contract=contract, checked_at=NOW,
                                       ipo_status=status, theme_status=theme)
    assert report["auxiliary_issues"] == ["source_waiting:C30_POWER", "ipo_theme_venue_waiting:hk",
                                          "ipo_theme_review_overdue"]
    assert report["status"] == "attention"


def test_raw_receipts_only_advance_matching_source_hash_and_series(tmp_path):
    from ai_fc.authoritative_statistics import RawArtifactMissing, load_authoritative_source_policy, persist_raw_artifact

    policy = load_authoritative_source_policy(ROOT / "data/contracts/authoritative_statistics_sources.yaml")
    receipt = persist_raw_artifact(
        tmp_path / "data/statistics/official_store", policy, source_id="fred_market_signals",
        payload=b"fixture", source_uri="https://api.stlouisfed.org/fred/series/observations?series_id=M2SL",
        fetched_at="2026-10-28T23:00:00+00:00", http_status=200, media_type="text/csv", series_ids=["M2SL"])
    source = {"series_id": "M2SL", "policy_source_id": "fred_market_signals", "raw_sha256": receipt.raw_sha256}
    assert load_source_checks(tmp_path, {"sources": [source]}) == {"M2SL": receipt.fetched_at}
    assert load_source_checks(tmp_path, {"sources": [dict(source, raw_sha256="b" * 64)]}) == {}
    assert load_source_checks(tmp_path, {"sources": [dict(source, policy_source_id="census")]}) == {}
    (tmp_path / "data/statistics/official_store" / receipt.artifact_path).write_bytes(b"tampered")
    with pytest.raises(RawArtifactMissing):
        load_source_checks(tmp_path, {"sources": [source]})


def test_ritter_dataset_check_requires_explicit_net_field_receipt(tmp_path):
    from ai_fc.authoritative_statistics import load_authoritative_source_policy, persist_raw_artifact

    policy = load_authoritative_source_policy(ROOT / "data/contracts/authoritative_statistics_sources.yaml")
    receipt = persist_raw_artifact(
        tmp_path / "data/statistics/official_store", policy, source_id="ritter_ipoall_monthly",
        payload=b"fixture workbook", source_uri="https://site.warrington.ufl.edu/ritter/files/IPOALL.xlsx",
        fetched_at=NOW, http_status=200, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        series_ids=["RITTER_IPOALL_MONTHLY.gross", "RITTER_IPOALL_MONTHLY.net"])
    source = {"series_id": "RITTER_IPOALL_MONTHLY", "policy_source_id": "ritter_ipoall_monthly",
              "raw_sha256": receipt.raw_sha256}
    assert load_source_checks(tmp_path, {"sources": [source]}) == {"RITTER_IPOALL_MONTHLY": NOW}


def test_cli_writes_report_before_strict_failure(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from ai_fc import cli, statistics_freshness

    payload, contract = fixture()
    payload["sources"][0]["refresh_status"] = "verified_cache_waiting_source"
    report = build_indicator_freshness(payload, contract=contract, checked_at=NOW)
    monkeypatch.setattr(statistics_freshness, "audit_statistics_freshness", lambda _: report)
    target = tmp_path / "freshness.json"
    result = CliRunner().invoke(cli.app, ["statistics-freshness", "--output", str(target), "--strict"])
    assert result.exit_code == 1
    assert json.loads(target.read_text(encoding="utf-8"))["issues"] == ["i"]
    assert "원천 응답 대기" in result.output


def test_naive_audit_time_is_rejected():
    payload, contract = fixture()
    with pytest.raises(ValueError, match="aware"):
        build_indicator_freshness(payload, contract=contract, checked_at=datetime(2026, 10, 29))


def test_cli_retains_machine_readable_artifact_on_missing_or_corrupt_input(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from ai_fc import cli, statistics_freshness

    def missing(_):
        raise FileNotFoundError("fixture missing, do not copy arbitrary source text")

    monkeypatch.setattr(statistics_freshness, "audit_statistics_freshness", missing)
    target = tmp_path / "failed-audit.json"
    result = CliRunner().invoke(cli.app, ["statistics-freshness", "--output", str(target), "--strict"])
    report = json.loads(target.read_text(encoding="utf-8"))
    assert result.exit_code == 1
    assert report["status"] == "error" and report["error_type"] == "FileNotFoundError"
    assert "fixture missing" not in target.read_text(encoding="utf-8")
