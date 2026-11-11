"""U2a 워크플로 분류 관문 ``triage_gate`` — 종료코드·주석·요약·신호 매핑·무네트워크.

감싸는 명령은 ``sys.executable -c`` 로 만든 가짜 스크립트다. 네트워크·저장소 쓰기 없음(--out 은 tmp_path).
"""

from __future__ import annotations

import json
import os
import signal
import sys
from pathlib import Path

import pytest

from ai_fc.mts_research import ingest_triage as triage
from ai_fc.mts_research import triage_gate as gate
from ai_fc.mts_research.ingest_triage import load_fact_index

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "mts_ingest_triage"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _script(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def _stdout_script(payload: dict, rc: int) -> list[str]:
    text = json.dumps(payload)
    return _script(f"import sys; sys.stdout.write({text!r}); sys.exit({rc})")


def _stderr_script(line: str, rc: int) -> list[str]:
    return _script(f"import sys; sys.stderr.write('noise\\n' + {line!r} + '\\n\\n'); sys.exit({rc})")


@pytest.fixture(scope="module")
def fact_index():
    """실제 ALFRED 사실 원장 투영 (읽기 전용, 약 30초 — 모듈당 1회)."""
    return load_fact_index(ROOT)


def _run(argv: list[str]) -> int:
    return gate.main(["--root", str(ROOT), *argv])


def test_wrapped_success_exits_zero_without_classifying(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("분류가 호출되면 안 된다")

    monkeypatch.setattr(triage, "run_cli", forbidden)
    out = tmp_path / "gate.json"
    code = _run(["--kind", "v2_verify", "--now", "2026-11-10T23:52:49+00:00",
                 "--wrap-stdout", str(tmp_path / "verify.json"), "--out", str(out), "--",
                 *_stdout_script({"ok": True, "errors": []}, 0)])
    assert code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["gate"] == "command_ok" and payload["wrapped_exit_code"] == 0


def test_verify_rc1_boundary_is_pending_then_fail_after_boundary(tmp_path, monkeypatch, fact_index, capsys):
    monkeypatch.setattr(triage, "load_fact_index", lambda root: fact_index)
    report = _fixture("v2_verify_42926210670")["report"]
    out = tmp_path / "verify-triage.json"
    code = _run(["--kind", "v2_verify", "--now", "2026-11-10T23:52:49+00:00",
                 "--wrap-stdout", str(tmp_path / "verify.json"), "--out", str(out), "--",
                 *_stdout_script(report, 1)])
    assert code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["status"] == "pending_date_boundary"
    assert payload["gate"]["schema"] == "mts_triage_gate_v1" and payload["gate"]["wrapped_exit_code"] == 1
    assert payload["gate"]["mode"] == "wrap_stdout"
    printed = capsys.readouterr().out
    assert '"dfm_missing_evaluation_cutoffs"' in printed  # 감싼 명령의 stdout 을 로그에 그대로 다시 보인다
    assert "\n::notice title=ingest-triage v2_verify::" in "\n" + printed
    late = _run(["--kind", "v2_verify", "--now", "2026-11-11T06:00:00Z",
                 "--wrap-stdout", str(tmp_path / "verify2.json"), "--out", str(tmp_path / "late.json"), "--",
                 *_stdout_script(report, 1)])
    assert late == 1


@pytest.mark.parametrize("rc, expected", [(2, 2), (137, 137)])
def test_wrapped_other_exit_codes_pass_through_unclassified(tmp_path, monkeypatch, rc, expected):
    monkeypatch.setattr(triage, "run_cli", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no classify")))
    out = tmp_path / "gate.json"
    code = _run(["--kind", "v2_verify", "--now", "2026-11-10T23:52:49+00:00",
                 "--wrap-stdout", str(tmp_path / "verify.json"), "--out", str(out), "--",
                 *_stdout_script({}, rc)])
    assert code == expected
    assert json.loads(out.read_text(encoding="utf-8"))["gate"] == "command_failed_unclassified"


def test_exit_from_returncode_maps_signals():
    assert gate._exit_from_returncode(-9) == 137
    assert gate._exit_from_returncode(-15) == 143
    assert gate._exit_from_returncode(3) == 3
    assert gate._exit_from_returncode(0) == 0


@pytest.mark.skipif(os.name == "nt", reason="POSIX 신호 — Windows 에서는 순수 함수 검사만")
def test_signal_termination_is_128_plus_n(tmp_path):
    code = _run(["--kind", "v2_monitor", "--wrap-stderr-last-line", "--out", str(tmp_path / "m.json"), "--",
                 *_script(f"import os, signal; os.kill(os.getpid(), signal.SIGTERM)")])
    assert code == 128 + int(signal.SIGTERM)


def test_monitor_by_design_last_line_is_zero_and_other_line_is_one(tmp_path):
    out = tmp_path / "monitor.json"
    stop = "시계열 연구모델 중단: sealed evaluation failed; monitoring cannot reopen it"
    code = _run(["--kind", "v2_monitor", "--wrap-stderr-last-line", "--out", str(out), "--",
                 *_stderr_script(stop, 1)])
    assert code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["status"] == "by_design_notice" and payload["gate"]["mode"] == "wrap_stderr_last_line"
    assert json.loads((tmp_path / "monitor.json.input.json").read_text(encoding="utf-8")) == {"log_line": stop}
    other = _run(["--kind", "v2_monitor", "--wrap-stderr-last-line", "--out", str(tmp_path / "m2.json"), "--",
                  *_stderr_script("Traceback: KeyError 'x'", 1)])
    assert other == 1


def test_monitor_silent_exit_one_fails_instead_of_by_design(tmp_path, capsys):
    """U2b 리뷰 N3: stderr 무출력 exit 1 은 설계상 종료 문구를 확인할 수 없으므로 by_design 으로 숨기지 않는다."""
    out = tmp_path / "monitor.json"
    code = _run(["--kind", "v2_monitor", "--wrap-stderr-last-line", "--out", str(out), "--",
                 *_script("import sys; sys.exit(1)")])
    assert code == 1
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["gate"] == "command_failed_without_stderr" and payload["status"] == "fail"
    assert not (tmp_path / "monitor.json.input.json").exists()
    assert "::error title=ingest-triage v2_monitor::" in capsys.readouterr().out


def test_report_mode_v2_refresh_known_stall_annotation_and_summary(tmp_path, monkeypatch, capsys):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    out = tmp_path / "refresh.json"
    code = _run(["--kind", "v2_refresh", "--report", str(FIXTURES / "v2_refresh_market_42950811442.json"),
                 "--out", str(out)])
    assert code == 0
    printed = capsys.readouterr().out.splitlines()
    assert any(line.startswith("::warning title=ingest-triage v2_refresh::") for line in printed)
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["status"] == "known_stall" and payload["gate"]["mode"] == "report"
    assert payload["gate"]["wrapped_command"] is None and payload["notice"] == "참고 의견, 매매 신호 아님"
    text = summary.read_text(encoding="utf-8")
    assert "### ingest-triage v2_refresh: known_stall" in text
    assert not list(tmp_path.glob("*.tmp")), "원자적 쓰기 — .tmp 잔여 없음"


def test_report_mode_daily6m_receipts_history(tmp_path):
    raw = tmp_path / "report.json"
    raw.write_text(json.dumps(_fixture("daily6m_sources_42950808534")["report"]), encoding="utf-8")
    out = tmp_path / "d6m.json"
    code = _run(["--kind", "daily6m_sources", "--history", "receipts_ledger", "--report", str(raw), "--out", str(out)])
    assert code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["status"] == "transport_pending" and payload["workflow_wired"] is True
    assert payload["evidence"]["history_provider"] == "daily6m_receipts_session_anchored_v1"


@pytest.mark.parametrize("argv", [
    ["--kind", "v2_verify", "--report", "x.json", "--wrap-stdout", "y.json", "--", "python"],
    ["--kind", "v2_verify", "--now", "", "--report", "x.json"],
    ["--kind", "v2_verify", "--now", "   ", "--wrap-stdout", "y.json", "--", "python"],
    ["--kind", "v2_refresh", "--wrap-stdout", "y.json", "--", "python"],
    ["--kind", "v2_refresh", "--wrap-stderr-last-line", "--", "python"],
    ["--kind", "v2_verify", "--wrap-stderr-last-line", "--", "python"],
    ["--kind", "v2_monitor", "--wrap-stdout", "y.json", "--", "python"],
    ["--kind", "v2_verify", "--history", "receipts_ledger", "--report", "x.json"],
    ["--kind", "v2_verify", "--wrap-stdout", "y.json"],
    ["--kind", "v2_verify", "--report", "x.json", "--", "python"],
    ["--kind", "v2_verify"],
    ["--kind", "nope", "--report", "x.json"],
])
def test_invalid_argument_combinations_are_exit_2(tmp_path, argv):
    assert gate.main([*argv[:2], "--out", str(tmp_path / "o.json"), *argv[2:]]) == 2
    assert not (tmp_path / "o.json").exists()


def test_missing_report_file_is_exit_2_with_error_annotation(tmp_path, capsys):
    code = _run(["--kind", "daily6m_sources", "--report", str(tmp_path / "absent.json"), "--out", str(tmp_path / "o.json")])
    assert code == 2
    assert any(line.startswith("::error title=ingest-triage daily6m_sources::")
               for line in capsys.readouterr().out.splitlines())


def test_root_defaults_to_config_root(tmp_path, monkeypatch):
    from ai_fc import config

    seen = {}

    def fake(root, args):
        seen["root"] = root
        return 0, {"status": "ok", "github_annotations": [], "reasons": []}

    monkeypatch.setattr(config, "ROOT", tmp_path / "configured")
    monkeypatch.setattr(triage, "run_cli", fake)
    assert gate.main(["--kind", "v2_refresh", "--report", "x.json", "--out", str(tmp_path / "o.json")]) == 0
    assert seen["root"] == tmp_path / "configured"


def test_gate_module_has_no_network_client_and_no_v14_string():
    source = (ROOT / "src/ai_fc/mts_research/triage_gate.py").read_text(encoding="utf-8")
    for needle in ("urllib", "requests", "http.client", "httpx", "socket", "timeseries_v14", "shell=True"):
        assert needle not in source
