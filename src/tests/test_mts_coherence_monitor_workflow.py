"""U1 — mts-coherence-monitor 워크플로 구조·3곳 등록·커밋 허용 목록·!cancelled() 커밋 (읽기 전용)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from test_mts_research_protected_glob_names import _protected

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/mts-coherence-monitor.yml"
ALLOWLIST = {
    "data/mts_research/ledgers/coherence_daily.jsonl",
    "data/mts_research/derived/coherence_monitor_latest.json",
    "data/mts_research/ledgers/v8_xnas_label_diagnostics.jsonl",
    "data/mts_research/derived/v8_xnas_label_summary.json",
    "data/mts_research/ledgers/v8_live_monitor.jsonl",
    "data/mts_research/derived/v8_live_monitor.json",
    "data/mts_research/ledgers/fed_ebp_v1.jsonl",          # U2 §7.7 교차 명세 — 사이드카 원장
}


def _doc() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _on(doc: dict) -> dict:
    return doc.get("on", doc.get(True))


def _steps() -> list[dict]:
    return _doc()["jobs"]["monitor"]["steps"]


def _index(needle: str) -> int:
    hits = [i for i, step in enumerate(_steps()) if needle in str(step.get("run", ""))]
    assert len(hits) == 1, needle
    return hits[0]


def test_triggers_and_concurrency() -> None:
    doc = _doc()
    assert doc["name"] == "mts-coherence-monitor"
    on = _on(doc)
    assert set(on) == {"schedule", "workflow_dispatch"}
    assert [item["cron"] for item in on["schedule"]] == ["15 12 * * 2-6", "45 18 * * 2-6"]
    assert doc["concurrency"] == {"group": "mts-coherence-monitor", "cancel-in-progress": False}


def test_step_order() -> None:
    coherence = _index("coherence-monitor --append --catch-up")
    xnas = _index("v8-xnas-labels --append")
    live = _index("v8-live-monitor --append")
    sidecar = _index("python -m ai_fc.mts_research.cli fed-ebp-sidecar --append")
    chains = _index("read_chain")
    commit = _index("git push")
    assert coherence < xnas < live < sidecar < chains < commit


def test_later_steps_run_unless_cancelled_and_commit_needs_chain_check() -> None:
    steps = _steps()
    first = _index("coherence-monitor --append --catch-up")
    for step in steps[first + 1:]:
        if "run" in step:
            assert "!cancelled()" in str(step.get("if", "")), step.get("name")
    commit = steps[_index("git push")]
    assert "steps.chains.outcome == 'success'" in commit["if"]
    chains = steps[_index("read_chain")]
    assert chains.get("id") == "chains"
    for name in ("coherence_daily.jsonl", "v8_xnas_label_diagnostics.jsonl", "v8_live_monitor.jsonl",
                 "fed_ebp_v1.jsonl"):
        assert name in chains["run"]


def test_every_install_brings_the_xnas_calendar() -> None:
    installs = [line for line in WORKFLOW.read_text(encoding="utf-8").splitlines() if "pip install" in line]
    assert installs and all("exchange-calendars" in line for line in installs)


def test_no_failure_swallowing_secrets_or_forbidden_strings() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "continue-on-error" not in text
    for line in text.splitlines():
        if "|| true" in line:
            assert "grep -Ev" in line, line
    assert "timeseries_v14" not in text and "timeseries-v14" not in text
    assert "secrets." not in text
    # 사람 전용 적용 verb 는 예약 실행에 없다
    assert "apply-verdict" not in text


def test_commit_allowlist_is_exact_and_guarded() -> None:
    commit = _steps()[_index("git push")]["run"]
    match = re.search(r'allow="([^"]+)"', commit)
    assert match and set(match.group(1).split()) == ALLOWLIST
    assert '[ -f "$f" ]' in commit
    assert "fed_ebp_v1" in commit.split("grep -Ev", 1)[1]
    assert commit.index("git pull --rebase origin main") < commit.index("git push")


def test_registered_in_pages_verify_and_failure_alert() -> None:
    for name in ("pages.yml", "verify.yml"):
        doc = yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))
        assert "mts-coherence-monitor" in _on(doc)["workflow_run"]["workflows"], name
    alert = yaml.safe_load((ROOT / ".github/workflows/ops-failure-alert.yml").read_text(encoding="utf-8"))
    assert "mts-coherence-monitor" in _on(alert)["workflow_run"]["workflows"]


def test_file_name_outside_protected_globs() -> None:
    assert _protected(".github/workflows/mts-coherence-monitor.yml") == []


def test_live_summary_reads_report_keys() -> None:
    live = _steps()[_index("v8-live-monitor --append")]["run"]
    assert 'd.get("report")' in live
    assert "--if-stale" in live
