"""U2a 분류 관문 배선 — daily6m-sources-refresh 구조·bash 실행·보호 파일 편집 영수증 형식.

U2b(별도 PR)가 timeseries-v2-refresh·mts-ingest-triage 구조, 영수증 핀, U1 사이드카 단계 존재 검사를 덧붙인다.
네트워크·저장소 쓰기 없음(bash 실행은 tmp_path 작업 폴더).
"""

from __future__ import annotations

import fnmatch
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/daily6m-sources-refresh.yml"
RECEIPTS = ROOT / "data/mts_research/contracts/protected_workflow_edit_receipts_v1.json"
INSTRUCTION = "네가 나머지 작업 다 완료시켜.  네가 최적의 선택을 내려서 u1~u7까지 다 진행시켜"
GATE = "python -m ai_fc.mts_research.triage_gate"
PROTECTED_GLOBS = (".github/workflows/timeseries*.yml", "tools/*timeseries*", "tools/*scenario*", "tools/*v6*",
                   "src/tests/test_multivariate_timeseries*.py")


def _doc() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _step(job: str, name: str) -> dict:
    return next(step for step in _doc()["jobs"][job]["steps"] if step.get("name") == name)


def _bash() -> str | None:
    bash = str(Path("C:/Program Files/Git/bin/bash.exe")) if os.name == "nt" else shutil.which("bash")
    return bash if bash and Path(bash).is_file() else None


@pytest.mark.parametrize("mode, expected_exit", [("ok", 0), ("partial", 0), ("bare1", 1), ("crash", 2)])
def test_capture_step_records_exit_code_and_defers_only_a_reported_partial(tmp_path, mode, expected_exit):
    """capture 본문을 python 스텁 함수로 실제 bash 에서 실행한다: rc 0 / 1+보고 / 1−보고 / 2."""
    bash = _bash()
    if bash is None:
        pytest.skip("workflow shell unavailable")
    step = _step("capture", "Capture official completed-session sources without ledger writes")
    assert step["shell"] == "bash" and "continue-on-error" not in step
    stub = (
        'python() {\n'
        '  case "$STUB_MODE" in\n'
        '    ok) return 0 ;;\n'
        '    partial) mkdir -p .tmp && echo "{}" > .tmp/daily6m-sources-capture-report.json; return 1 ;;\n'
        '    bare1) return 1 ;;\n'
        '    crash) return 2 ;;\n'
        '  esac\n'
        '}\n'
    )
    output = tmp_path / "github_output"
    output.write_text("", encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    result = subprocess.run([bash, "--noprofile", "--norc", "-eo", "pipefail", "-c", stub + step["run"]],
                            cwd=work, env={"STUB_MODE": mode, "GITHUB_OUTPUT": str(output), "PATH": os.environ["PATH"]},
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == expected_exit, result.stderr
    code = {"ok": 0, "partial": 1, "bare1": 1, "crash": 2}[mode]
    assert output.read_text(encoding="utf-8").splitlines() == [f"exit_code={code}"]
    if expected_exit:
        assert "::error title=daily6m capture::" in result.stdout


def test_daily6m_sources_workflow_classifies_instead_of_swallowing():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "continue-on-error" not in text
    capture = _step("capture", "Classify an incomplete capture after preserving its public evidence")
    assert "always()" in capture["if"] and "steps.capture.outputs.exit_code != '0'" in capture["if"]
    assert "steps.bundle.outputs.bundle_ready != 'true'" in capture["if"]
    assert f"{GATE} --kind daily6m_sources --history receipts_ledger" in capture["run"]
    assert "--report .tmp/daily6m-sources-capture-report.json" in capture["run"]
    assert "--out .tmp/daily6m-sources-capture-triage.json" in capture["run"]
    publish_steps = _doc()["jobs"]["publish"]["steps"]
    last = publish_steps[-1]
    assert last["name"] == "Classify a partial source checkpoint after preserving valid appends"
    assert last["if"] == "${{ always() && steps.decision.outputs.status == 'partial' }}"
    assert f"{GATE} --kind daily6m_sources --history receipts_ledger --report .tmp/daily6m-sources-report.json" in last["run"]
    for step in (capture, last):
        lines = [line.strip() for line in step["run"].splitlines()]
        # 조용한 성공·무조건 실패 단독 줄 없음 — 종료코드는 관문(분류)이 정한다.
        assert "exit 0" not in lines
        assert lines.count("exit 1") <= 1 and ("exit 1" not in lines or "if [" in step["run"])
    for job in _doc()["jobs"].values():
        for step in job["steps"]:
            if str(step.get("uses", "")).startswith("actions/upload-artifact@"):
                assert step["with"]["include-hidden-files"] is True


def test_reused_daily6m_workflow_is_not_edited_here():
    """보호 glob 의 timeseries-daily6m.yml 은 재사용 호출만 한다 — 분류는 재사용 워크플로 안에서 끝난다."""
    text = (ROOT / ".github/workflows/timeseries-daily6m.yml").read_text(encoding="utf-8")
    assert "daily6m-sources-refresh.yml" in text
    assert "triage_gate" not in text


def _receipts() -> dict:
    return json.loads(RECEIPTS.read_text(encoding="utf-8"))


def test_edit_receipts_have_approval_and_pin_fields():
    payload = _receipts()
    assert payload["schema_version"] == "mts_protected_edit_receipts_v1"
    edits = payload["edits"]
    assert edits and len({edit["edit_id"] for edit in edits}) == len(edits)
    for edit in edits:
        assert type(edit["pin"]) is bool
        approval = edit["approval"]
        assert approval["approval_form"] == "delegated_bundle_instruction"
        assert approval["literal_template_match"] is False
        assert approval["approval_text"] == INSTRUCTION  # 원문 공백 2칸 그대로
        assert approval["template_text"] and approval["template_text"] != INSTRUCTION
        upper = datetime.fromisoformat(approval["instructed_at_upper_bound"].replace("Z", "+00:00"))
        assert upper == datetime(2026, 11, 11, 9, 3, 44, tzinfo=timezone.utc)
        assert edit["v7_baseline"]["action"] == "not_regenerated"
        assert len(edit["before"]["sha256"]) == 64 and len(edit["after"]["sha256"]) == 64


def test_receipts_record_scenario_edit_without_pin():
    scenario = [edit for edit in _receipts()["edits"] if edit["path"] == "src/ai_fc/scenario.py"]
    assert len(scenario) == 1 and scenario[0]["pin"] is False
    assert scenario[0]["before"]["git_commit"] == "4950e8a5"


def test_u2a_file_names_avoid_protected_globs():
    owned = [
        "src/ai_fc/mts_research/triage_gate.py",
        "src/tests/test_mts_research_triage_gate.py",
        "src/tests/test_mts_research_triage_wiring.py",
        "src/tests/test_nyse_holidays_revision.py",
        "data/mts_research/contracts/ingest_triage_policy_v1.json",
        "data/mts_research/contracts/protected_workflow_edit_receipts_v1.json",
        ".github/workflows/daily6m-sources-refresh.yml",
    ]
    assert not [(name, glob) for name in owned for glob in PROTECTED_GLOBS if fnmatch.fnmatch(name, glob)]
    for name in owned:
        assert (ROOT / name).is_file(), name
        if not name.startswith("src/tests/"):  # 테스트 파일은 금지 문자열을 검사 대상으로 담는다
            assert "timeseries" + "_v14" not in (ROOT / name).read_text(encoding="utf-8")
