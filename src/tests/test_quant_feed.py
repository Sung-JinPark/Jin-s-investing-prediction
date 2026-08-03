from __future__ import annotations

import json
from datetime import date

import pytest

from ai_fc.quant import feed


def _raw(*, timestamps=None, closes=None, adjusted=None) -> str:
    indicators = {"quote": [{"close": closes or [100.0, 101.0]}]}
    if adjusted is not None:
        indicators["adjclose"] = [{"adjclose": adjusted}]
    return json.dumps({
        "chart": {"result": [{
            "timestamp": timestamps or [1_700_000_000, 1_700_086_400],
            "indicators": indicators,
        }]}
    })


def test_yahoo_empty_adjusted_array_falls_back_to_close(monkeypatch) -> None:
    monkeypatch.setattr(feed, "_get", lambda _url: _raw(adjusted=[]))
    result = feed.yahoo_price_series_detail("O", date(2023, 1, 1), date(2023, 2, 1), "1d")
    assert result.adjusted == result.closes
    assert result.data_quality["status"] == "fallback_close"
    assert result.data_quality["adjusted_fallback"] is True


def test_yahoo_nonpositive_close_is_dropped_and_counted(monkeypatch) -> None:
    monkeypatch.setattr(
        feed, "_get", lambda _url: _raw(closes=[100.0, 0.0], adjusted=[99.0, 0.0]))
    result = feed.yahoo_price_series_detail("O", date(2023, 1, 1), date(2023, 2, 1), "1d")
    assert result.closes == [100.0]
    assert result.data_quality["dropped_rows"] == 1
    assert result.data_quality["status"] == "degraded"


def test_yahoo_length_mismatch_raises_instead_of_zip_truncation(monkeypatch) -> None:
    monkeypatch.setattr(
        feed, "_get", lambda _url: _raw(
            timestamps=[1_700_000_000, 1_700_086_400], closes=[100.0], adjusted=[99.0]))
    with pytest.raises(ValueError, match="timestamp/close length mismatch"):
        feed.yahoo_price_series_detail("O", date(2023, 1, 1), date(2023, 2, 1), "1d")


def test_get_rejects_zero_retry_configuration() -> None:
    with pytest.raises(RuntimeError, match="not attempted"):
        feed._get("https://example.invalid", retries=0)
