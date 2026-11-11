"""워크플로 분류 관문 ``triage_gate`` — 단계 종료코드를 분류 결과로만 정한다 (U2a, 2026-11-11).

    python -m ai_fc.mts_research.triage_gate --kind K [--root R] [--now ISO] [--history receipts_ledger]
            (--report PATH | --wrap-stdout PATH -- CMD... | --wrap-stderr-last-line -- CMD...)
            --out PATH

- ``--report``: 이미 있는 보고 JSON 을 분류한다.
- ``--wrap-stdout``(v2_verify 만): 명령을 감싸 stdout 을 파일에 받고, 명령이 1 로 끝나면 그 파일을
  보고로 분류한다. ``--wrap-stderr-last-line``(v2_monitor 만): stderr 마지막 비어 있지 않은 줄을 분류한다.
- 감싼 명령이 0 이면 분류 없이 0, 0·1 이 아니면 분류 없이 그 코드를 그대로 낸다(더 엄격). 신호 종료
  (Popen returncode < 0)는 셸 관례대로 ``128 + n`` 이다.
- 종료코드: 0 = ok·notice·pending·by_design·known_stall, 1 = fail·escalate, 2 = 입력 오류, 3 = unexpected.
  조용한 성공은 없다 — exit 0 은 분류가 0 을 줄 때와 감싼 명령이 0 일 때뿐이다.

판정의 정본은 ``ingest_triage.run_cli`` 하나다(이 모듈은 하네스일 뿐). 진입점을 ``mts_research/cli.py``
의 verb 로 두지 않은 이유: ``--`` 뒤 명령 전달과 wrap 인자가 필요한 워크플로 하네스이고, 연구 도구가
아니다. 표시·게이트·예측과 연결하지 않는다(참고 의견, 매매 신호 아님). 네트워크 클라이언트 없음 —
subprocess 로 저장소 CLI 만 감싼다.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

GATE_SCHEMA = "mts_triage_gate_v1"
KINDS = ("v2_verify", "v2_refresh", "daily6m_sources", "v2_monitor")
WRAP_STDOUT_KINDS = ("v2_verify",)
WRAP_STDERR_KINDS = ("v2_monitor",)
HISTORY_KINDS = ("daily6m_sources",)
NOTICE = "참고 의견, 매매 신호 아님"


class GateUsageError(ValueError):
    """관문 인자 조합이 계약 밖 — exit 2."""


def _exit_from_returncode(code: int) -> int:
    """Popen returncode → 셸 종료코드. 신호 종료(-n)는 128+n — 음수는 러너에서 255 등으로 뭉개진다."""
    return 128 + (-code) if code < 0 else code


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m ai_fc.mts_research.triage_gate", add_help=True)
    parser.add_argument("--kind", required=True, choices=KINDS)
    parser.add_argument("--root", default=None, help="저장소 루트 (기본: ai_fc.config.ROOT)")
    parser.add_argument("--now", default=None, help="ISO8601 판정 시각 (비어 있으면 거부)")
    parser.add_argument("--history", default=None, choices=["receipts_ledger"])
    parser.add_argument("--report", default=None)
    parser.add_argument("--wrap-stdout", default=None, dest="wrap_stdout")
    parser.add_argument("--wrap-stderr-last-line", action="store_true", dest="wrap_stderr_last_line")
    parser.add_argument("--out", required=True)
    return parser


def _split(argv: Sequence[str]) -> tuple[list[str], list[str]]:
    items = list(argv)
    if "--" in items:
        index = items.index("--")
        return items[:index], items[index + 1:]
    return items, []


def _validate(args: argparse.Namespace, command: list[str]) -> str:
    """인자 조합 검증 → 모드(report·wrap_stdout·wrap_stderr_last_line). 위반은 GateUsageError."""
    modes = [name for name, on in (("report", args.report is not None),
                                   ("wrap_stdout", args.wrap_stdout is not None),
                                   ("wrap_stderr_last_line", args.wrap_stderr_last_line)) if on]
    if len(modes) != 1:
        raise GateUsageError("--report 와 wrap(--wrap-stdout·--wrap-stderr-last-line) 중 정확히 하나만 준다")
    mode = modes[0]
    if mode == "report" and command:
        raise GateUsageError("--report 모드에는 '--' 뒤 명령을 주지 않는다")
    if mode != "report" and not command:
        raise GateUsageError("wrap 모드에는 '--' 뒤 감쌀 명령이 필요하다")
    if mode == "wrap_stdout" and args.kind not in WRAP_STDOUT_KINDS:
        raise GateUsageError(f"--wrap-stdout 는 {WRAP_STDOUT_KINDS} 에만 허용한다: {args.kind}")
    if mode == "wrap_stderr_last_line" and args.kind not in WRAP_STDERR_KINDS:
        raise GateUsageError(f"--wrap-stderr-last-line 는 {WRAP_STDERR_KINDS} 에만 허용한다: {args.kind}")
    if args.now is not None and not args.now.strip():
        raise GateUsageError("--now 가 비어 있다(워크플로 env 미설정 의심)")
    if args.history is not None and args.kind not in HISTORY_KINDS:
        raise GateUsageError(f"--history 는 {HISTORY_KINDS} 에만 허용한다: {args.kind}")
    return mode


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _run_wrapped(command: list[str], stdout_path: Path | None) -> tuple[int, str | None]:
    """명령을 셸 없이 실행한다. stderr 는 줄 단위로 흘려보내며 마지막 비어 있지 않은 줄을 보관한다."""
    last: str | None = None
    handle = None
    try:
        if stdout_path is not None:
            stdout_path.parent.mkdir(parents=True, exist_ok=True)
            handle = stdout_path.open("wb")
        process = subprocess.Popen(command, stdout=handle, stderr=subprocess.PIPE, text=True,
                                   encoding="utf-8", errors="replace")
        assert process.stderr is not None
        for line in process.stderr:
            sys.stderr.write(line)
            sys.stderr.flush()
            if line.strip():
                last = line.rstrip("\r\n")
        code = process.wait()
    finally:
        if handle is not None:
            handle.close()
    if stdout_path is not None and stdout_path.is_file():
        # 기존 로그 가시성 유지 — 감싼 명령의 stdout 을 그대로 다시 보여 준다.
        text = stdout_path.read_text(encoding="utf-8", errors="replace")
        # 주석 줄이 줄 맨 앞에서 시작하도록 마지막 개행을 보장한다(없으면 JSON 뒤에 붙어 명령으로 안 읽힌다).
        sys.stdout.write(text if not text or text.endswith("\n") else text + "\n")
        sys.stdout.flush()
    return code, last


def _summary(kind: str, payload: dict[str, Any]) -> None:
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if not target:
        return
    lines = [f"### ingest-triage {kind}: {payload.get('status')}", ""]
    reasons = payload.get("reasons") or ([payload["error"]] if payload.get("error") else [])
    lines.extend(f"- {reason}" for reason in reasons)
    lines.append(f"- 지위: {NOTICE}")
    with open(target, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n\n")


def main(argv: Sequence[str] | None = None) -> int:
    from .. import config
    from . import ingest_triage

    gate_argv, command = _split(sys.argv[1:] if argv is None else argv)
    try:
        args = _parser().parse_args(gate_argv)
    except SystemExit as exc:  # argparse 오류·--help
        return int(exc.code or 0) if isinstance(exc.code, int) else 2
    try:
        mode = _validate(args, command)
    except GateUsageError as exc:
        print(f"::error title=ingest-triage gate::{exc}")
        return 2
    root = Path(args.root) if args.root else Path(config.ROOT)
    out = Path(args.out)
    gate: dict[str, Any] = {"schema": GATE_SCHEMA, "mode": mode,
                            "wrapped_command": command or None, "wrapped_exit_code": None}
    report = args.report
    if mode != "report":
        stdout_path = Path(args.wrap_stdout) if mode == "wrap_stdout" else None
        code, last_line = _run_wrapped(command, stdout_path)
        gate["wrapped_exit_code"] = code
        if code == 0:
            _write_json_atomic(out, {"gate": "command_ok", "wrapped_exit_code": 0, "kind": args.kind,
                                     "schema": GATE_SCHEMA, "mode": mode, "wrapped_command": command,
                                     "notice": NOTICE})
            return 0
        if code not in (0, 1):
            exit_code = _exit_from_returncode(code)
            print(f"::error title=ingest-triage gate::wrapped command exited {exit_code}")
            _write_json_atomic(out, {"gate": "command_failed_unclassified", "wrapped_exit_code": code,
                                     "exit_code": exit_code, "kind": args.kind, "schema": GATE_SCHEMA,
                                     "mode": mode, "wrapped_command": command, "notice": NOTICE})
            return exit_code
        if mode == "wrap_stdout":
            report = str(stdout_path)
        else:
            input_path = out.with_name(out.name + ".input.json")
            _write_json_atomic(input_path, {"log_line": last_line})
            report = str(input_path)
    namespace = argparse.Namespace(kind=args.kind, report=report, now=args.now, history=args.history,
                                   append=False, as_of=None)
    code, payload = ingest_triage.run_cli(root, namespace)
    payload = {**payload, "gate": gate}
    _write_json_atomic(out, payload)
    annotations = payload.get("github_annotations") or []
    if not annotations and payload.get("error"):
        annotations = [f"::error title=ingest-triage {args.kind}::"
                       f"{ingest_triage._escape_annotation(str(payload['error']))}"]
    for line in annotations:
        print(line)  # 줄 맨 앞에서 시작해야 GitHub 이 워크플로 명령으로 읽는다
    sys.stdout.flush()
    _summary(args.kind, payload)
    return int(code)


if __name__ == "__main__":
    sys.exit(main())
