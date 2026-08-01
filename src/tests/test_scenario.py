"""시장 시나리오 스냅샷 — 결정론·스키마·fail-safe 계약."""

from __future__ import annotations

import json
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
    assert first["weeks"][0] == "7/30" and first["weeks"][-1] == "12/31"
    assert len(first["risk"]) == len(first["weeks"])
    assert all(
        len(first["paths"][key]["values"]) == len(first["weeks"])
        for key in ("S1", "S2", "S3")
    )
    assert first["anchor"] > 0 and first["corr10"] == pytest.approx(first["ath"] * 0.9, abs=0.01)


def test_validate_rejects_probability_or_length_drift() -> None:
    payload = _build()
    payload["paths"]["S1"]["prob"] += 1
    with pytest.raises(scenario.ScenarioError, match="sum to 100"):
        scenario.validate_scenario(payload)

    payload = _build()
    payload["risk"].pop()
    with pytest.raises(scenario.ScenarioError, match="risk length"):
        scenario.validate_scenario(payload)


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


def test_refresh_skips_same_completed_market_day(tmp_path: Path, monkeypatch) -> None:
    days, closes = _series()
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
