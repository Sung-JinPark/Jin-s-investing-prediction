"""분류 관문 배선 — U2a: daily6m-sources-refresh 구조·bash 실행·보호 파일 편집 영수증 형식.

U2b(PR-2): timeseries-v2-refresh 구조(§8.3-1), 영수증 핀(§8.3-4), U1 사이드카 단계 존재(§8.3-6 — 머지 순서
U2a → U1 → U2b 를 기계로 강제), 비라이터 mts-ingest-triage 구조·fetch 단계 bash 실행(§8.3-7).
네트워크·저장소 쓰기 없음(bash 실행은 tmp_path 작업 폴더, gh·python 은 셸 함수 스텁).
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import shutil
import subprocess
import sys
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


# --- U2b (PR-2) -----------------------------------------------------------------------------------

V2_REFRESH = ROOT / ".github/workflows/timeseries-v2-refresh.yml"
TRIAGE_WORKFLOW = ROOT / ".github/workflows/mts-ingest-triage.yml"
U1_MONITOR = ROOT / ".github/workflows/mts-coherence-monitor.yml"
OPS_ALERT = ROOT / ".github/workflows/ops-failure-alert.yml"
POLICY = ROOT / "data/mts_research/contracts/ingest_triage_policy_v1.json"
V7_BASELINE = ROOT / "data/timeseries_v7/manifests/protected_v6_baseline.json"
V7_BASELINE_SHA256 = "06f8396d4522be95494add1e2183e4cbbca3e60a82c60265181f5cf315048fb7"
U1_CRONS = {"15 12 * * 2-6", "45 18 * * 2-6"}


def _yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _on(document: dict) -> dict:
    # PyYAML 은 YAML 1.1 규칙으로 `on:` 키를 True 로 읽는다
    return document.get(True) or document.get("on") or {}


def _v2_steps() -> list[dict]:
    return _yaml(V2_REFRESH)["jobs"]["refresh"]["steps"]


def _named(steps: list[dict], name: str) -> dict:
    return next(step for step in steps if step.get("name") == name)


def _lf_sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def _lf_sha256(path: Path) -> str:
    return _lf_sha256_bytes(path.read_bytes())


def test_v2_refresh_preserves_market_report_and_gates_verify_and_monitor():
    """§8.3-1: market 보고 tee + 즉시 보존, prepare 컷오프, verify·monitor 관문, 관문 결과 업로드."""
    text = V2_REFRESH.read_text(encoding="utf-8")
    assert "continue-on-error" not in text
    assert "--kind v2_refresh" not in text  # market 분류는 이 run 밖(mts-ingest-triage)
    assert text.count('[ "${{ github.event_name }}" = "pull_request" ]') == 2
    steps = _v2_steps()
    market = next(step for step in steps if step.get("id") == "market_refresh")
    assert market["name"] == "Append official reconstructed market archives"
    assert market["shell"] == "bash"
    assert "python -m ai_fc timeseries-v2-refresh | tee .tmp/v2-refresh-report.json" in market["run"]
    keep = steps[steps.index(market) + 1]
    assert keep["uses"] == "actions/upload-artifact@v4" and "if" not in keep
    assert keep["with"]["name"] == "v2-refresh-market-report"
    assert keep["with"]["path"] == ".tmp/v2-refresh-report.json"
    assert keep["with"]["include-hidden-files"] is True
    assert keep["with"]["if-no-files-found"] == "error"
    assert keep["with"]["retention-days"] == 14
    assert keep["with"]["overwrite"] is True  # 리뷰 N2: 재시도가 1차 시도 artifact 와 409 로 충돌하지 않게
    checkpoint = next(step for step in steps if step.get("id") == "checkpoint")
    assert steps.index(keep) < steps.index(checkpoint)

    prepare = _named(steps, "Prepare origin-specific DFM caches before verification")
    assert prepare["shell"] == "bash"
    assert "python -m ai_fc timeseries-v2-prepare | tee .tmp/v2-prepare.json" in prepare["run"]
    assert 'echo "V2_PREPARE_CUTOFF=$cutoff" >> "$GITHUB_ENV"' in prepare["run"]
    assert 'test -n "$cutoff"' in prepare["run"]

    monitor = _named(steps, "Re-evaluate the frozen winner on the first Saturday")
    assert (f"{GATE} --kind v2_monitor --wrap-stderr-last-line --out .tmp/v2-monitor-triage.json "
            "-- python -m ai_fc timeseries-v2-monitor-backtest --path-count 20000") in monitor["run"]

    verify = _named(steps, "Verify V2 and run focused regression tests")
    assert verify["shell"] == "bash"
    gate_line = (f'{GATE} --kind v2_verify --now "$V2_PREPARE_CUTOFF" --wrap-stdout .tmp/v2-verify-report.json '
                 "--out .tmp/v2-verify-triage.json -- python -m ai_fc timeseries-v2-verify")
    assert gate_line in verify["run"]
    assert verify["run"].index(gate_line) < verify["run"].index("pytest src/tests/test_multivariate_timeseries_v2.py")
    assert steps.index(prepare) < steps.index(monitor) < steps.index(verify)

    last = steps[-1]
    assert last["name"] == "Preserve ingest-triage gate classifications"
    assert last["if"] == "${{ always() }}" and last["uses"] == "actions/upload-artifact@v4"
    # 리뷰 N7: 분류 결과와 원입력(verify 원보고·monitor 마지막 줄)을 함께 보존한다.
    assert last["with"]["path"].split() == [".tmp/v2-*-triage.json", ".tmp/v2-verify-report.json",
                                            ".tmp/v2-monitor-triage.json.input.json"]
    assert last["with"]["overwrite"] is True
    assert last["with"]["include-hidden-files"] is True
    assert last["with"]["if-no-files-found"] == "ignore"
    for step in steps:
        if str(step.get("uses", "")).startswith("actions/upload-artifact@"):
            assert step["with"]["include-hidden-files"] is True, step.get("name")


@pytest.mark.parametrize("mode, expected_exit", [("ok", 0), ("crash", 1)])
def test_v2_prepare_step_exports_its_own_cutoff(tmp_path, mode, expected_exit):
    """prepare 단계 본문을 실제 bash(-eo pipefail)로 실행: 출력 JSON 의 knowledge_cutoff 를 GITHUB_ENV 로 내보내고,
    prepare 가 실패하면 tee 뒤에서도 단계가 실패한다(pipefail)."""
    bash = _bash()
    if bash is None:
        pytest.skip("workflow shell unavailable")
    step = _named(_v2_steps(), "Prepare origin-specific DFM caches before verification")
    real = Path(sys.executable).as_posix()
    stub = (
        'python() {\n'
        '  if [ "$1" = "-m" ]; then\n'
        '    if [ "$STUB_MODE" = "crash" ]; then echo "boom" >&2; return 1; fi\n'
        '    echo \'{"schema_version": 2, "knowledge_cutoff": "2026-11-10T23:52:49+00:00", "status": "ready"}\'\n'
        '    return 0\n'
        '  fi\n'
        f'  "{real}" "$@"\n'
        '}\n'
    )
    env_file = tmp_path / "github_env"
    env_file.write_text("", encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    env = {"STUB_MODE": mode, "GITHUB_ENV": str(env_file), "PATH": os.environ["PATH"]}
    if os.name == "nt":
        env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows")
    result = subprocess.run([bash, "--noprofile", "--norc", "-eo", "pipefail", "-c", stub + step["run"]],
                            cwd=work, env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == expected_exit, result.stderr
    lines = env_file.read_text(encoding="utf-8").splitlines()
    if expected_exit == 0:
        assert lines == ["V2_PREPARE_CUTOFF=2026-11-10T23:52:49+00:00"]
    else:
        assert lines == []


def test_protected_edit_receipt_pins_current_bytes():
    """§8.3-4: pin=true 경로는 경로별 마지막 영수증 after.sha256 == 현재 LF 바이트. 다시 고치면 새 항목 append."""
    edits = _receipts()["edits"]
    pinned = sorted({edit["path"] for edit in edits if edit["pin"]})
    assert pinned == [".github/workflows/timeseries-v2-refresh.yml"]
    for path in pinned:
        chain = [edit for edit in edits if edit["path"] == path]
        assert all(edit["pin"] is True for edit in chain), path
        for prior, edit in zip(chain, chain[1:]):
            assert edit["before"]["sha256"] == prior["after"]["sha256"], (path, edit["edit_id"])
        assert chain[-1]["after"]["sha256"] == _lf_sha256(ROOT / path), (
            f"{path} 가 마지막 편집 영수증과 다르다 — 보호 파일을 고쳤다면 영수증에 새 항목을 append 하라")
    v2 = next(edit for edit in edits if edit["path"] == ".github/workflows/timeseries-v2-refresh.yml")
    assert v2["edit_id"] == "u2b-20261111-timeseries-v2-refresh"
    assert v2["before"]["sha256"] == "f5473a4fb02a6b4f46f96e948348346181104ce291b47e32a96892ffade8edaa"
    assert v2["before"]["git_blob"] == "9f5320b3acf2af1e1c4e90933428e56dffeac26f"
    assert v2["after"]["sha256"] != v2["before"]["sha256"]
    assert v2["v7_baseline"]["drift_measured"] == {"at": "2026-11-11", "changed": 162, "added": 11566, "removed": 204}
    assert any("2026-12-05" in effect and "workbook" in effect for effect in v2["changed_effects"])
    assert any("mts-ingest-triage" in effect for effect in v2["changed_effects"])
    # V7 기준선은 재생성하지 않는다 — 동결 증거 파일 바이트 무변경.
    assert _lf_sha256(V7_BASELINE) == V7_BASELINE_SHA256
    git = shutil.which("git")
    if git is None:
        return
    for edit in edits:
        commit = edit["before"].get("git_commit")
        probe = subprocess.run([git, "cat-file", "-e", f"{commit}^{{commit}}"], cwd=ROOT, capture_output=True)
        if probe.returncode != 0:
            continue  # 얕은 clone 등 — 이력 대조는 커밋이 있을 때만
        shown = subprocess.run([git, "show", f"{commit}:{edit['path']}"], cwd=ROOT, capture_output=True, check=True)
        assert _lf_sha256_bytes(shown.stdout) == edit["before"]["sha256"], edit["edit_id"]


def test_u1_monitor_appends_fed_ebp_sidecar():
    """§8.3-6 (B3): FED_EBP known_stall 의 보완 원장 append 는 U1 감시 워크플로가 맡는다 — 머지 순서 강제."""
    assert U1_MONITOR.is_file()
    document = _yaml(U1_MONITOR)
    steps = document["jobs"]["monitor"]["steps"]
    sidecar = next(step for step in steps
                   if "python -m ai_fc.mts_research.cli fed-ebp-sidecar --append" in step.get("run", ""))
    chains = next(step for step in steps if step.get("id") == "chains")
    commit = next(step for step in steps if "git push" in step.get("run", ""))
    assert steps.index(sidecar) < steps.index(chains) < steps.index(commit)
    assert sidecar["if"] == "${{ !cancelled() }}"
    assert '"fed_ebp_v1.jsonl"' in chains["run"]
    assert "data/mts_research/ledgers/fed_ebp_v1.jsonl" in commit["run"]
    assert '[ -f "$f" ]' in commit["run"]
    assert "|fed_ebp_v1)" in commit["run"]
    crons = {entry["cron"] for entry in _on(document)["schedule"]}
    # 정책 v1 의 96h 지연 창은 이 예약표에서 나왔다 — 예약을 바꾸면 정책 v2(새 파일)가 필요하다.
    assert crons == U1_CRONS
    rule = json.loads(POLICY.read_text(encoding="utf-8"))["known_stalls"]["fed_ebp_sealed_parser_iso_dates"]
    assert rule["compensator_max_lag_hours"] == 96
    assert "12:15/18:45" in rule["compensator_max_lag_basis"]


def test_ingest_triage_workflow_is_a_watched_non_writer():
    """§8.3-7: mts-ingest-triage 는 v2-refresh 완료를 듣는 비라이터이고 ops 감시 대상이다."""
    text = TRIAGE_WORKFLOW.read_text(encoding="utf-8")
    for forbidden in ("git push", "git commit", "continue-on-error", "secrets."):
        assert forbidden not in text, forbidden
    assert "timeseries" + "_v14" not in text and "timeseries" + "-v14" not in text
    document = _yaml(TRIAGE_WORKFLOW)
    assert document["name"] == "mts-ingest-triage"
    on = _on(document)
    assert set(on) == {"workflow_run", "workflow_dispatch"}
    assert on["workflow_run"]["workflows"] == ["timeseries-v2-refresh"]
    assert on["workflow_run"]["types"] == ["completed"]
    assert on["workflow_dispatch"]["inputs"]["run_id"]["required"] is True
    assert document["permissions"] == {"contents": "read", "actions": "read"}
    job = document["jobs"]["classify"]
    for clause in ("github.event_name == 'workflow_dispatch'", "github.event.workflow_run.event != 'pull_request'",
                   "github.event.workflow_run.head_branch == 'main'",
                   "github.event.workflow_run.conclusion != 'cancelled'",
                   "github.event.workflow_run.conclusion != 'skipped'"):
        assert clause in job["if"], clause
    steps = job["steps"]
    setup = next(step for step in steps if str(step.get("uses", "")).startswith("actions/setup-python@"))
    upstream = next(step for step in _v2_steps() if str(step.get("uses", "")).startswith("actions/setup-python@"))
    assert setup["with"]["python-version"] == upstream["with"]["python-version"] == "3.12.16"
    install = next(step for step in steps if "pip install" in step.get("run", ""))
    upstream_install = next(step for step in _v2_steps() if "pip install" in step.get("run", ""))
    for pin in ('"numpy==2.5.4"', '"scipy==1.18.1"', '"pandas==2.3.3"', '".[pit,timeseries]"'):
        assert pin in install["run"] and pin in upstream_install["run"], pin
    classify = _named(steps, "Classify hidden market refresh failures")
    assert classify["if"] == "${{ steps.fetch.outputs.present == 'true' }}"
    assert (f"{GATE} --kind v2_refresh --report .tmp/upstream/v2-refresh-report.json "
            "--out .tmp/v2-refresh-triage.json") in classify["run"]
    upload = steps[-1]
    assert upload["uses"] == "actions/upload-artifact@v4" and upload["if"] == "${{ always() }}"
    assert upload["with"]["include-hidden-files"] is True
    assert upload["with"]["path"] == ".tmp/v2-refresh-triage.json"
    assert upload["with"]["overwrite"] is True
    fetch = next(step for step in steps if step.get("id") == "fetch")
    assert fetch["shell"] == "bash" and "v2-refresh-market-report" in fetch["run"]
    # 상류 보고 artifact 이름·파일이 v2-refresh 의 보존 단계와 같다.
    keep = _named(_v2_steps(), "Preserve the market refresh report for out-of-run triage")
    assert keep["with"]["name"] == "v2-refresh-market-report"
    assert Path(keep["with"]["path"]).name == "v2-refresh-report.json"
    alert = _on(_yaml(OPS_ALERT))
    assert "mts-ingest-triage" in alert["workflow_run"]["workflows"]
    name = ".github/workflows/mts-ingest-triage.yml"
    assert not [glob for glob in PROTECTED_GLOBS if fnmatch.fnmatch(name, glob)]


@pytest.mark.parametrize("artifact, conclusion, expected_exit, present, marker", [
    ("v2-refresh-market-report", "success", 0, "true", None),
    ("", "failure", 0, "false", "::notice title=ingest-triage v2_refresh::"),
    ("", "success", 1, None, "::error title=ingest-triage v2_refresh::"),
    ("other-artifact", "dispatch", 1, None, "::error title=ingest-triage v2_refresh::"),
    # 리뷰 N6: 상류가 뒤 단계에서 실패했어도 보고가 보존됐으면 내려받아 분류한다.
    ("v2-refresh-market-report", "failure", 0, "true", None),
])
def test_ingest_triage_fetch_step_bash(tmp_path, artifact, conclusion, expected_exit, present, marker):
    """§8.3-7 fetch 단계 본문을 실제 bash 로 실행 — gh 를 셸 함수 스텁으로 바꾼다(네트워크 없음)."""
    bash = _bash()
    if bash is None:
        pytest.skip("workflow shell unavailable")
    fetch = next(step for step in _yaml(TRIAGE_WORKFLOW)["jobs"]["classify"]["steps"] if step.get("id") == "fetch")
    stub = (
        'gh() {\n'
        '  echo "$*" >> "$GH_CALLS"\n'
        '  case "$1" in\n'
        '    api) if [ -n "$STUB_ARTIFACT" ]; then printf "%s\\n" "$STUB_ARTIFACT"; fi; return 0 ;;\n'
        '    run) mkdir -p .tmp/upstream && echo \'{"market": {}}\' > .tmp/upstream/v2-refresh-report.json; return 0 ;;\n'
        '  esac\n'
        '  return 9\n'
        '}\n'
    )
    output = tmp_path / "github_output"
    output.write_text("", encoding="utf-8")
    calls = tmp_path / "calls"
    work = tmp_path / "work"
    work.mkdir()
    env = {"STUB_ARTIFACT": artifact, "UPSTREAM_CONCLUSION": conclusion, "RUN_ID": "123",
           "GITHUB_REPOSITORY": "owner/repo", "GITHUB_OUTPUT": str(output), "GH_CALLS": str(calls),
           "PATH": os.environ["PATH"]}
    result = subprocess.run([bash, "--noprofile", "--norc", "-eo", "pipefail", "-c", stub + fetch["run"]],
                            cwd=work, env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == expected_exit, result.stderr
    lines = output.read_text(encoding="utf-8").splitlines()
    assert lines == ([f"present={present}"] if present else [])
    if marker:
        assert marker in result.stdout
    recorded = calls.read_text(encoding="utf-8")
    assert "api repos/owner/repo/actions/runs/123/artifacts" in recorded
    downloaded = "run download 123 --repo owner/repo -n v2-refresh-market-report -D .tmp/upstream" in recorded
    assert downloaded is (present == "true")
    if present == "true":
        assert (work / ".tmp/upstream/v2-refresh-report.json").is_file()


@pytest.mark.parametrize("run_id", ["", "12;rm -rf x", "abc", "-1"])
def test_ingest_triage_fetch_rejects_malformed_run_id(tmp_path, run_id):
    """리뷰 N8: dispatch 입력 run_id 는 양의 정수만 — gh 를 부르기 전에 exit 2."""
    bash = _bash()
    if bash is None:
        pytest.skip("workflow shell unavailable")
    fetch = next(step for step in _yaml(TRIAGE_WORKFLOW)["jobs"]["classify"]["steps"] if step.get("id") == "fetch")
    stub = 'gh() { echo "$*" >> "$GH_CALLS"; return 0; }\n'
    output = tmp_path / "github_output"
    output.write_text("", encoding="utf-8")
    calls = tmp_path / "calls"
    env = {"UPSTREAM_CONCLUSION": "dispatch", "RUN_ID": run_id, "GITHUB_REPOSITORY": "owner/repo",
           "GITHUB_OUTPUT": str(output), "GH_CALLS": str(calls), "PATH": os.environ["PATH"]}
    result = subprocess.run([bash, "--noprofile", "--norc", "-eo", "pipefail", "-c", stub + fetch["run"]],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 2, result.stderr
    assert "::error title=ingest-triage v2_refresh::run_id must be a positive integer" in result.stdout
    assert not calls.exists()
    assert output.read_text(encoding="utf-8") == ""


def _bash_env(tmp_path: Path, **extra: str) -> dict:
    env = {"PATH": os.environ["PATH"], **extra}
    if os.name == "nt":
        env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows")
    return env


@pytest.mark.parametrize("mode, expected_exit", [("ok", 0), ("crash", 1)])
def test_v2_market_step_tees_report_and_fails_under_pipefail(tmp_path, mode, expected_exit):
    """리뷰 N6: market 단계 본문을 실제 bash(-eo pipefail)로 실행 — 보고는 파일로 남고, refresh 가 실패하면
    tee 뒤에서도 단계가 실패한다(종전 `bash -e` 였다면 tee 의 0 이 실패를 삼킨다)."""
    bash = _bash()
    if bash is None:
        pytest.skip("workflow shell unavailable")
    market = next(step for step in _v2_steps() if step.get("id") == "market_refresh")
    stub = (
        'python() {\n'
        '  if [ "$STUB_MODE" = "crash" ]; then echo "boom" >&2; return 1; fi\n'
        '  echo \'{"market": {"retrieved_at": "2026-11-11T08:31:00+00:00", "failures": []}}\'\n'
        '}\n'
    )
    work = tmp_path / "work"
    work.mkdir()
    result = subprocess.run([bash, "--noprofile", "--norc", "-eo", "pipefail", "-c", stub + market["run"]],
                            cwd=work, env=_bash_env(tmp_path, STUB_MODE=mode), capture_output=True, text=True,
                            timeout=60)
    assert result.returncode == expected_exit, result.stderr
    report = work / ".tmp/v2-refresh-report.json"
    if expected_exit == 0:
        assert json.loads(report.read_text(encoding="utf-8"))["market"]["failures"] == []
    else:
        assert report.read_text(encoding="utf-8") == ""


@pytest.mark.parametrize("gate_rc, expected_exit, pytest_ran", [(0, 0, True), (1, 1, False), (3, 3, False)])
def test_v2_verify_gate_failure_stops_before_regression_tests(tmp_path, gate_rc, expected_exit, pytest_ran):
    """리뷰 N6: verify 단계에서 관문이 1·3 이면 회귀 pytest 전에 단계가 멈추고, 0 이면 pytest 까지 간다.
    관문에는 prepare 가 내보낸 V2_PREPARE_CUTOFF 가 --now 로 전달된다."""
    bash = _bash()
    if bash is None:
        pytest.skip("workflow shell unavailable")
    verify = _named(_v2_steps(), "Verify V2 and run focused regression tests")
    calls = tmp_path / "calls"
    stub = (
        'python() { echo "python $*" >> "$CALLS"; return "$STUB_GATE_RC"; }\n'
        'pytest() { echo "pytest $*" >> "$CALLS"; return 0; }\n'
    )
    work = tmp_path / "work"
    work.mkdir()
    env = _bash_env(tmp_path, STUB_GATE_RC=str(gate_rc), CALLS=str(calls),
                    V2_PREPARE_CUTOFF="2026-11-10T23:52:49+00:00")
    result = subprocess.run([bash, "--noprofile", "--norc", "-eo", "pipefail", "-c", stub + verify["run"]],
                            cwd=work, env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == expected_exit, result.stderr
    recorded = calls.read_text(encoding="utf-8").splitlines()
    assert recorded[0].startswith("python -m ai_fc.mts_research.triage_gate --kind v2_verify "
                                  "--now 2026-11-10T23:52:49+00:00 ")
    assert any(line.startswith("pytest ") for line in recorded) is pytest_ran
