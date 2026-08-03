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


def test_yahoo_dividends_filters_invalid_events(monkeypatch) -> None:
    raw = json.dumps({"chart": {"result": [{"events": {"dividends": {
        "a": {"date": 1_700_000_000, "amount": 0.25},
        "b": {"date": 1_700_086_400, "amount": 0},
        "c": {"date": None, "amount": 0.25},
    }}}]}})
    monkeypatch.setattr(feed, "_get", lambda _url: raw)
    result = feed.yahoo_dividends("O", date(2023, 1, 1), date(2024, 1, 1))
    assert result.amounts == [0.25]
    assert result.receipt["response_sha256"]


def test_curl_fallback_preserves_source_response(monkeypatch) -> None:
    monkeypatch.setattr(feed, "_python_path_blocked", False)

    def timeout(*_args, **_kwargs):
        raise TimeoutError

    monkeypatch.setattr(feed, "_get", timeout)

    class Result:
        returncode = 0
        stdout = b"DATE,VALUE\n2026-07-31,1.25\n"

    monkeypatch.setattr(feed.subprocess, "run", lambda *args, **kwargs: Result())
    text = feed.get_with_curl_fallback("https://fred.test/series.csv", timeout=1)
    assert text == "DATE,VALUE\n2026-07-31,1.25\n"
    assert feed._python_path_blocked is True


def test_curl_fallback_uses_public_dns_for_same_https_url(monkeypatch) -> None:
    monkeypatch.setattr(feed, "_python_path_blocked", True)
    monkeypatch.setattr(feed, "_resolve_via_public_dns", lambda _host: "203.0.113.7")
    commands = []

    class Result:
        def __init__(self, returncode, stdout=b""):
            self.returncode = returncode
            self.stdout = stdout

    def run(command, **_kwargs):
        commands.append(command)
        return Result(0, b"ok") if "--resolve" in command else Result(6)

    monkeypatch.setattr(feed.subprocess, "run", run)
    text = feed.get_with_curl_fallback("https://fred.test/series.csv", timeout=1)
    assert text == "ok"
    assert commands[-1][-1] == "https://fred.test/series.csv"
    assert "fred.test:443:203.0.113.7" in commands[-1]
