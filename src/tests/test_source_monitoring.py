from __future__ import annotations

import json
from datetime import date, datetime, timezone

from ai_fc.source_monitoring import collect_defillama_health


def _contract(tmp_path) -> None:
    path = tmp_path / "data/contracts/defillama_stablecoins.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "endpoint: https://stablecoins.test/all\n"
        "enabled: false\n"
        "license_status: review_required\n",
        encoding="utf-8")


def _response(days: int = 365) -> str:
    return json.dumps([
        {
            "date": str(1_700_000_000 + index * 86_400),
            "totalCirculating": {"peggedUSD": 100 + index},
            "totalCirculatingUSD": {"peggedUSD": 100 + index},
        }
        for index in range(days)
    ])


def test_monitor_records_health_metadata_without_raw_values(tmp_path) -> None:
    _contract(tmp_path)
    fetcher = lambda _url, **_kwargs: _response()  # noqa: E731
    path, status, changed = collect_defillama_health(
        tmp_path, asof=date(2026, 8, 3),
        now=datetime(2026, 8, 3, tzinfo=timezone.utc), fetch_text=fetcher)
    receipt = json.loads(
        (tmp_path / "data/source_monitoring/defillama_stablecoins/2026-08-03.json")
        .read_text(encoding="utf-8"))
    assert path.name == "defillama_stablecoins_status.json"
    assert changed is True
    assert status["consecutive_successful_days"] == 1
    assert status["activation_eligible"] is False
    assert receipt["raw_values_redistributed"] is False
    assert "totalCirculatingUSD" not in receipt


def test_monitor_counts_consecutive_days_and_is_same_day_idempotent(tmp_path) -> None:
    _contract(tmp_path)
    fetcher = lambda _url, **_kwargs: _response()  # noqa: E731
    collect_defillama_health(tmp_path, asof=date(2026, 8, 2), fetch_text=fetcher)
    _, status, _ = collect_defillama_health(
        tmp_path, asof=date(2026, 8, 3), fetch_text=fetcher)
    _, retry, changed = collect_defillama_health(
        tmp_path, asof=date(2026, 8, 3), fetch_text=fetcher)
    assert status["consecutive_successful_days"] == 2
    assert retry == status
    assert changed is False
