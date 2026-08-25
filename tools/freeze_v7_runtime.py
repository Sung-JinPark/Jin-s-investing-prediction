#!/usr/bin/env python3
"""Freeze and probe the deterministic V7 replay runtime."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ai_fc.timeseries_v7.runtime import (  # noqa: E402
    canonical_json_bytes,
    deterministic_probe,
    live_environment_report,
    runtime_identity,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    probe = sub.add_parser("probe")
    probe.add_argument("--json", action="store_true")
    freeze = sub.add_parser("freeze")
    freeze.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    lock = REPO / "locks/timeseries_v7/requirements.replay.lock"
    dockerfile = REPO / "containers/timeseries_v7/Dockerfile.replay"
    if args.command == "probe":
        report = {
            "runtime": runtime_identity(lock, dockerfile),
            "live": live_environment_report(),
            "probe": deterministic_probe(),
        }
        body = canonical_json_bytes(report)
        sys.stdout.buffer.write(body)
        return 0
    report = runtime_identity(lock, dockerfile)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(body, encoding="utf-8", newline="\n")
    os.replace(temporary, args.output)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
