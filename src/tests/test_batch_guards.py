"""Failures found by the 2026-11-05 batch audit, kept from coming back."""
import re
from pathlib import Path

from ai_fc import ai_capital_cycle, registered_debt, segment_filing_inventory, statistics_lab
from ai_fc.sec_contact import SEC_CONTACT, sec_user_agent

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


def test_v8_daily_installs_the_calendar_its_freshness_check_needs():
    # Missing since 2026-10-26: every run died on ModuleNotFoundError and the display stayed at 10-23.
    text = (WORKFLOWS / "timeseries-v8-daily.yml").read_text(encoding="utf-8")
    installs = [line for line in text.splitlines() if "pip install" in line]
    assert len(installs) >= 2
    assert all("exchange-calendars" in line for line in installs)


def test_every_workflow_running_a_calendar_command_installs_the_calendar():
    pattern = re.compile(r"ai_fc (timeseries-v8-daily|timeseries-daily6m|daily6m|trendlines-refresh)\b")
    for path in WORKFLOWS.glob("*.yml"):
        text = path.read_text(encoding="utf-8")
        if not pattern.search(text):
            continue
        installs = [line for line in text.splitlines() if "pip install" in line]
        assert any("exchange-calendars" in line or "timeseries-v5" in line for line in installs), path.name


def test_sec_clients_share_the_designated_contact(monkeypatch):
    monkeypatch.delenv("AI_FC_SEC_USER_AGENT", raising=False)
    for module in (ai_capital_cycle, registered_debt, segment_filing_inventory):
        assert SEC_CONTACT in module._user_agent()
    assert SEC_CONTACT in statistics_lab.DEFAULT_USER_AGENT
    monkeypatch.setenv("AI_FC_SEC_USER_AGENT", "Other/1.0 (a@example.org)")
    assert sec_user_agent() == "Other/1.0 (a@example.org)"


def test_the_address_sec_refuses_is_not_sent_to_sec():
    # The bots' commit identity may keep it; only SEC clients must not declare it.
    source = "Sung-JinPark@users.noreply.github.com"
    assert source not in (WORKFLOWS / "ai-regime-refresh.yml").read_text(encoding="utf-8")
    for path in (ROOT / "src" / "ai_fc").rglob("*.py"):
        assert source not in path.read_text(encoding="utf-8"), path


def _collector(url_log):
    def collect(root, *, retrieved_at, fetcher, volume_start_year):
        status, payload, _ = fetcher("https://fred.stlouisfed.org/graph/fredgraph.csv?id=NASDAQ100&cosd=1995-01-01")
        url_log.append((status, payload))
        assert fetcher("https://cdn.cboe.com/x.csv") == (200, b"passthrough", "text/csv")
        return {"sources": {}, "ok": False, "failures": [{"source_id": "fred_nasdaq100", "reason": "HTTP 451"}]}
    return collect


def test_v4_refuses_the_scrape_and_appends_through_the_official_api(monkeypatch, tmp_path):
    from ai_fc import timeseries_v4_official_transport as T

    refused, persisted, appended = [], [], []
    monkeypatch.setattr(T, "collect_v4_sources", _collector(refused))
    monkeypatch.setattr(T, "observations_csv", lambda series, observation_start, fetch_text: "observation_date,NASDAQ100\n2026-11-04,100.5\n")
    monkeypatch.setattr(T, "persist_raw", lambda root, **kwargs: persisted.append(kwargs) or "receipt")
    monkeypatch.setattr(T, "_all_observations", lambda root: [])
    monkeypatch.setattr(T, "append_observations", lambda root, parsed, receipt, observation_cache: appended.append(parsed) or {"appended": 1})
    monkeypatch.setattr(T, "verify_v4_source_store", lambda root: {"ok": True})
    result = T.collect_v4_official(tmp_path, fetcher=lambda url: (200, b"passthrough", "text/csv"))
    assert refused[0][0] == 451
    assert result["ok"] is True and result["failures"] == []
    assert persisted[0]["source_id"] == "fred_api_nasdaq100" and "api_key" not in persisted[0]["source_uri"]
    assert appended[0][0].series_id == "NASDAQ100" and float(appended[0][0].value) == 100.5


def test_v4_api_failure_stays_visible_and_other_failures_of_that_source_are_kept(monkeypatch, tmp_path):
    from ai_fc import timeseries_v4_official_transport as T
    from ai_fc.fred_api import FredApiError

    def collect(root, *, retrieved_at, fetcher, volume_start_year):
        return {"sources": {}, "failures": [{"source_id": "fred_nasdaq100", "reason": "parser produced zero observations"}]}

    def no_key(series, observation_start, fetch_text):
        raise FredApiError("FRED_API_KEY가 필요합니다")
    monkeypatch.setattr(T, "collect_v4_sources", collect)
    monkeypatch.setattr(T, "observations_csv", no_key)
    monkeypatch.setattr(T, "verify_v4_source_store", lambda root: {"ok": True})
    result = T.collect_v4_official(tmp_path, fetcher=lambda url: (200, b"", "text/plain"))
    assert result["ok"] is False
    assert [row["source_id"] for row in result["failures"]] == ["fred_nasdaq100", "fred_api_nasdaq100"]


def test_v4_workflow_gives_the_collect_step_the_api_key():
    text = (WORKFLOWS / "timeseries-v4-data-refresh.yml").read_text(encoding="utf-8")
    step = text[text.index("Collect public archives raw-first"):text.index("Verify raw hashes")]
    assert "FRED_API_KEY: ${{ secrets.FRED_API_KEY }}" in step
