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
