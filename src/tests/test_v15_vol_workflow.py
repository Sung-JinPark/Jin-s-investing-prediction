"""V15-VOL 워크플로 정적 검사 (명세 U5 §8.6) — 파일 읽기만."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github/workflows"
WORKFLOW = WORKFLOWS / "v15-vol-shadow.yml"
ALLOWED = (
    "data/timeseries_v15_vol/ledgers/arming.jsonl",
    "data/timeseries_v15_vol/ledgers/vol15_shadow.jsonl",
    "data/timeseries_v15_vol/ledgers/vol15_shadow_resolutions.jsonl",
    "docs/generated/inventory.generated.md",
)


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _doc() -> dict:
    return yaml.safe_load(_text())


def _on(doc: dict) -> dict:
    return doc.get("on") or doc.get(True)          # PyYAML 은 'on' 키를 True 로 읽는다


def _steps(doc: dict) -> list[dict]:
    return doc["jobs"]["shadow"]["steps"]


def test_name_triggers_and_checkout_main() -> None:
    doc = _doc()
    assert doc["name"] == "v15-vol-shadow"
    on = _on(doc)
    assert "schedule" in on and "workflow_dispatch" in on and "workflow_run" not in on
    checkout = next(s for s in _steps(doc) if str(s.get("uses", "")).startswith("actions/checkout"))
    assert checkout["with"]["ref"] == "main"


def test_commit_allow_list_and_guards() -> None:
    text = _text()
    commit = next(s for s in _steps(_doc()) if s.get("name", "").startswith("Commit"))
    run = commit["run"]
    allow = re.search(r'allow="([^"]+)"', run).group(1).split()
    assert tuple(allow) == ALLOWED
    assert '[ -f "$f" ]' in run and "unexpected=" in run and "grep -Ev" in run
    pattern = re.search(r"grep -Ev '([^']+)'", run).group(1)
    for path in ALLOWED:
        assert re.fullmatch(pattern, path), path
    assert not re.fullmatch(pattern, "data/timeseries_v13/ledgers/vol_live.jsonl")
    lines = text.splitlines()
    push = max(i for i, line in enumerate(lines) if line.strip() == "git push")
    assert any("pull --rebase" in line for line in lines[max(0, push - 10):push])
    assert "continue-on-error" not in text
    assert "exchange-calendars" in text


def test_arming_env_only_on_shadow_and_verify_steps() -> None:
    doc = _doc()
    assert "V15_VOL_ARMING_CONTEXT" not in (doc.get("env") or {})
    assert "V15_VOL_ARMING_CONTEXT" not in (doc["jobs"]["shadow"].get("env") or {})
    carrying = [s["name"] for s in _steps(doc) if "V15_VOL_ARMING_CONTEXT" in (s.get("env") or {})]
    assert len(carrying) == 2
    assert any("Derive shadow" in name for name in carrying) and any("Verify" in name for name in carrying)
    for step in _steps(doc):
        if "V15_VOL_ARMING_CONTEXT" in (step.get("env") or {}):
            assert step["env"]["V15_VOL_ARMING_CONTEXT"] == "main_scheduled_ci"


def test_verdict_and_v14_are_absent() -> None:
    text = _text()
    assert "timeseries-v15-vol-verdict" not in text
    for forbidden in ("timeseries" + "_v14", "timeseries" + "-v14"):
        assert forbidden not in text
    for verb in ("timeseries-v15-vol-shadow", "timeseries-v15-vol-resolve", "timeseries-v15-vol-verify"):
        assert verb in text


def test_registered_in_pages_verify_and_ops_alert() -> None:
    """새 데이터 라이터 3곳 등록(W2 공유 편집 뒤 초록)."""
    for name in ("pages.yml", "verify.yml"):
        text = (WORKFLOWS / name).read_text(encoding="utf-8")
        assert '"v15-vol-shadow"' in text, name
    ops = (WORKFLOWS / "ops-failure-alert.yml").read_text(encoding="utf-8")
    assert re.search(r"^\s*-\s*v15-vol-shadow\b", ops, re.M), "ops-failure-alert 감시 목록"
