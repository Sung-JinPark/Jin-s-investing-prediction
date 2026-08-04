"""시장 시나리오 스냅샷 — 결정론·스키마·fail-safe 계약."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from ai_fc import scenario


def _series() -> tuple[list[date], list[float]]:
    days: list[date] = []
    cursor = date(2025, 6, 2)
    while cursor <= date(2026, 7, 30):
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    x = np.arange(len(days), dtype=float)
    closes = 22_000 * np.exp(0.00045 * x) * (1 + 0.012 * np.sin(x / 13))
    return days, closes.tolist()


def _build() -> dict:
    days, closes = _series()
    return scenario.build_scenario(
        days, closes, n_paths=800, seed=7,
        generated_at=datetime(2026, 7, 31, tzinfo=timezone.utc))


def test_build_scenario_is_deterministic_and_partitioned() -> None:
    first = _build()
    second = _build()
    assert first == second
    assert first["asof"] == "2026-07-30"
    assert sum(first["paths"][key]["prob"] for key in ("S1", "S2", "S3")) == 100
    assert first["weeks"][0] == "7/30"
    assert first["week_dates"][-1] > "2027-07-01"
    assert len(first["risk"]) == len(first["weeks"])
    assert all(
        len(first["paths"][key]["values"]) == len(first["weeks"])
        for key in ("S1", "S2", "S3")
    )
    realism = first["path_realism"]
    assert realism["selection_rule"].endswith("lowest original path index")
    for key in ("S1", "S2", "S3"):
        row = realism[key]
        if row["status"] == "empty_scenario":
            assert row["sample_count"] == 0 and row["sample_paths"] == []
            continue
        assert [sample["terminal_percentile"] for sample in row["sample_paths"]] == [25, 50, 75]
        assert all(len(sample["values"]) == len(first["weeks"])
                   for sample in row["sample_paths"])
        assert 0 <= row["median_max_drawdown_pct"] <= row["p90_max_drawdown_pct"] <= 100
    assert first["anchor"] > 0 and first["corr10"] == pytest.approx(first["ath"] * 0.9, abs=0.01)
    event_calendar = first["event_calendar"]
    assert event_calendar[-1]["date"] == "2027-12-08"
    assert len([row for row in event_calendar if row["date"].startswith("2027-")]) == 8
    assert all(row["source_url"].startswith("https://") for row in event_calendar)
    assert not any("저점 중위" in row["label"] for row in event_calendar)
    assert all(row["chart_visible"] for row in event_calendar if row["date"] <= first["quantile_table"]["trading_days"][-1])
    assert first["fan"]["probability_space"] == "scenario_conditional"
    assert set(first["fan"]["quantiles"]) == {
        "p5", "p10", "p25", "p50", "p75", "p90", "p95"}
    assert all(len(values) == len(first["weeks"])
               for values in first["fan"]["quantiles"].values())
    table = first["quantile_table"]
    assert table["probability_space"] == "scenario_conditional"
    assert table["probability_label"] == "model_conditional"
    assert len(table["trading_days"]) == scenario.FORECAST_HORIZON
    assert table["trading_days"][0] == "2026-07-31"
    assert all(value % 10 == 0 for values in table["quantiles"].values() for value in values)
    for index in range(scenario.FORECAST_HORIZON):
        values = [table["quantiles"][key][index]
                  for key in ("p05", "p10", "p25", "p50", "p75", "p90", "p95")]
        assert values == sorted(values)
    assert first == json.loads(json.dumps(second, ensure_ascii=False, sort_keys=True))


def test_band_calibration_is_append_only_and_duplicate_safe(tmp_path: Path) -> None:
    payload = _build()
    _, persisted, _ = scenario._persist_scenario(tmp_path, payload)
    target = date.fromisoformat(persisted["quantile_table"]["trading_days"][0])
    actual = persisted["quantile_table"]["quantiles"]["p50"][0]
    assert scenario.append_band_calibration(tmp_path, asof=target, actual_close=actual)
    assert not scenario.append_band_calibration(tmp_path, asof=target, actual_close=actual)
    lines = (tmp_path / "data/scenarios/band_calibration.csv").read_text(
        encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert "inside_p10_p90" in lines[0]


def test_nyse_calendar_skips_weekends_and_registered_holidays() -> None:
    calendar = scenario.load_calendar_contract(Path(__file__).parents[2])
    days = scenario.future_trading_days(date(2026, 8, 27), 5, calendar)
    assert days[:2] == [date(2026, 8, 28), date(2026, 8, 31)]
    thanksgiving = scenario.future_trading_days(date(2026, 11, 25), 2, calendar)
    assert thanksgiving == [date(2026, 11, 27), date(2026, 11, 30)]


def test_validate_rejects_probability_or_length_drift() -> None:
    payload = _build()
    payload["paths"]["S1"]["prob"] += 1
    with pytest.raises(scenario.ScenarioError, match="sum to 100"):
        scenario.validate_scenario(payload)

    payload = _build()
    payload["risk"].pop()
    with pytest.raises(scenario.ScenarioError, match="risk length"):
        scenario.validate_scenario(payload)

    payload = _build()
    payload["quantile_table"]["quantiles"]["p10"][0] = (
        payload["quantile_table"]["quantiles"]["p25"][0] + 10)
    with pytest.raises(scenario.ScenarioError, match="must be monotonic"):
        scenario.validate_scenario(payload)

    payload = _build()
    payload["event_calendar"][1]["date"] = payload["event_calendar"][0]["date"]
    with pytest.raises(scenario.ScenarioError, match="ordered and unique"):
        scenario.validate_scenario(payload)

    payload = _build()
    payload["path_realism"]["S1"]["sample_paths"][0]["values"].pop()
    with pytest.raises(scenario.ScenarioError, match="sample length mismatch"):
        scenario.validate_scenario(payload)


def test_path_realism_recomputes_drawdowns_and_samples_deterministically() -> None:
    sampled = np.asarray([
        [100, 110, 100, 120], [100, 105, 95, 110],
        [100, 120, 108, 130], [100, 101, 90, 105],
        [100, 98, 94, 103], [100, 115, 103, 125],
    ], dtype=float)
    future = np.repeat(sampled[:, 1:], 2, axis=1)
    masks = {
        "S1": np.asarray([True, True, True, False, False, False]),
        "S2": np.asarray([False, False, False, True, True, True]),
        "S3": np.asarray([True, False, False, True, False, True]),
    }
    first = scenario._path_realism(sampled, future, masks, 100.0)
    second = scenario._path_realism(sampled, future, masks, 100.0)
    assert first == second
    expected = []
    for path in np.column_stack((np.full(3, 100.0), future[masks["S1"]])):
        expected.append(float(np.max(1 - path / np.maximum.accumulate(path)) * 100))
    assert first["S1"]["median_max_drawdown_pct"] == round(float(np.median(expected)), 1)
    assert len({sample["path_index"] for sample in first["S1"]["sample_paths"]}) == 3


def test_load_latest_uses_valid_file_and_fails_safe(tmp_path: Path) -> None:
    payload = _build()
    latest = tmp_path / scenario.LATEST_RELATIVE_PATH
    latest.parent.mkdir(parents=True)
    latest.write_text(json.dumps(payload), encoding="utf-8")
    assert scenario.load_latest_scenario(tmp_path, {})["asof"] == "2026-07-30"

    latest.write_text("{broken", encoding="utf-8")
    fallback = dict(payload)
    fallback.pop("schema_version")
    loaded = scenario.load_latest_scenario(tmp_path, fallback)
    assert loaded["fallback"] is True
    assert loaded["method"] == payload["method"]


def test_load_latest_recovers_newest_valid_archive(tmp_path: Path) -> None:
    payload = _build()
    latest = tmp_path / scenario.LATEST_RELATIVE_PATH
    latest.parent.mkdir(parents=True)
    latest.write_text("{broken", encoding="utf-8")
    archive = tmp_path / scenario.ARCHIVE_RELATIVE_DIR
    archive.mkdir(parents=True)
    older = deepcopy(payload)
    older["asof"] = "2026-07-29"
    (archive / "2026-07-29.json").write_text(json.dumps(older), encoding="utf-8")
    (archive / "2026-07-30.json").write_text(json.dumps(payload), encoding="utf-8")
    (archive / "2026-07-31.json").write_text("{broken", encoding="utf-8")

    recovered = scenario.load_latest_scenario(tmp_path, {})
    assert recovered["asof"] == "2026-07-30"
    assert recovered["recovered_from_archive"] is True
    assert "fallback" not in recovered


def test_history_is_compact_sorted_capped_and_skips_corruption(tmp_path: Path) -> None:
    payload = _build()
    archive = tmp_path / scenario.ARCHIVE_RELATIVE_DIR
    archive.mkdir(parents=True)
    for day in range(20, 31):
        row = deepcopy(payload)
        row["asof"] = f"2026-07-{day:02d}"
        row["anchor"] += day
        (archive / f"2026-07-{day:02d}.json").write_text(
            json.dumps(row), encoding="utf-8")
    (archive / "2026-07-29-broken.json").write_text("{broken", encoding="utf-8")
    latest = deepcopy(payload)
    latest["asof"] = "2026-07-31"

    history = scenario.load_scenario_history(tmp_path, latest, limit=4)
    # The synthetic 7/31 row reuses a 7/30 lookup calendar and is therefore
    # correctly rejected; history still returns the newest four valid vintages.
    assert [row["asof"] for row in history] == [
        "2026-07-27", "2026-07-28", "2026-07-29", "2026-07-30"]
    assert all("weeks" not in row and "events" not in row for row in history)
    assert set(history[-1]["paths"]["S1"]) == {"prob", "end"}


def test_history_limit_zero_returns_empty(tmp_path: Path) -> None:
    assert scenario.load_scenario_history(tmp_path, _build(), limit=0) == []


def test_refresh_skips_same_completed_market_day(tmp_path: Path, monkeypatch) -> None:
    days, closes = _series()
    contract = scenario.load_calendar_contract(Path(__file__).parents[2])
    contract_path = tmp_path / scenario.CALENDAR_RELATIVE_PATH
    contract_path.parent.mkdir(parents=True)
    import yaml
    contract_path.write_text(yaml.safe_dump(contract), encoding="utf-8")
    monkeypatch.setattr(
        scenario.feed, "yahoo_series",
        lambda *_args, **_kwargs: (days, closes),
    )
    path, first, changed = scenario.refresh_scenario(tmp_path, asof=days[-1])
    assert changed is True and path.exists()
    archive = tmp_path / scenario.ARCHIVE_RELATIVE_DIR / "2026-07-30.json"
    assert archive.exists()

    _, second, changed = scenario.refresh_scenario(tmp_path, asof=days[-1])
    assert changed is False
    assert second == first


def test_same_asof_archive_is_immutable_without_approved_revision(tmp_path: Path) -> None:
    payload = _build()
    path, persisted, changed = scenario._persist_scenario(tmp_path, payload)
    assert path.exists() and changed is True
    archive = tmp_path / scenario.ARCHIVE_RELATIVE_DIR / "2026-07-30.json"
    original = archive.read_bytes()
    drift = deepcopy(payload)
    drift["quantile_table"]["quantiles"]["p50"][0] += 10
    with pytest.raises(scenario.ScenarioError, match="approved correction required"):
        scenario._persist_scenario(tmp_path, drift)
    assert archive.read_bytes() == original
    assert persisted["revision"] == 1
