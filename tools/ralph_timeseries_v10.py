"""V10 게이트 루프 하네스: next / record / status (v10_gate_loop.sh ADAPT 지점).

큐 = 계약 preregistered_first_experiments — 런타임 발명 0.  이 파일에는 개발 반복
밖의 어떤 평가 verb도 존재하지 않는다 (루프 PRE-FLIGHT grep 대조 대상).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_fc.timeseries_v8.artifact import read_ledger  # noqa: E402  (read-only)
from ai_fc.timeseries_v10.pipeline import (  # noqa: E402
    EXPERIMENT_CONFIGS,
    EXPERIMENT_LEDGER_RELATIVE,
    best_dual_improvement,
    design_champion,
    load_contract_v10,
)


def _done_labels() -> set[str]:
    return {
        str(row.get("experiment_label"))
        for row in read_ledger(ROOT, EXPERIMENT_LEDGER_RELATIVE)
    }


def cmd_next() -> int:
    contract = load_contract_v10(ROOT)
    queue = list(contract["development_protocol"]["preregistered_first_experiments"])
    done = _done_labels()
    for label in queue:
        if label in done:
            continue
        print(json.dumps(
            {"label": label, "config": EXPERIMENT_CONFIGS.get(label, {})},
            ensure_ascii=False, default=list,
        ))
        return 0
    return 0  # 큐 소진 — 빈 stdout이 루프에 탐색 종료를 알린다


def cmd_record(label: str) -> int:
    if label not in _done_labels():
        print(f"no ledger row recorded for label {label}", file=sys.stderr)
        return 1
    rows = read_ledger(ROOT, EXPERIMENT_LEDGER_RELATIVE)
    row = next(r for r in rows if r.get("experiment_label") == label)
    if row.get("gate_margin") is None:
        print(f"gate_margin diagnostics missing for {label}", file=sys.stderr)
        return 1
    print(f"recorded {label}")
    return 0


def cmd_status() -> int:
    champion = design_champion(ROOT)
    rows = read_ledger(ROOT, EXPERIMENT_LEDGER_RELATIVE)
    best = best_dual_improvement(ROOT)
    print(f"experiments: {len(rows)} | best_dual_improvement: {best:.4f}")
    if champion is not None:
        print(f"champion: {champion.get('experiment_label')} ({champion.get('experiment_id')})")
    else:
        print("no champion yet")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: ralph_timeseries_v10.py next|record --label X|status", file=sys.stderr)
        return 2
    verb = sys.argv[1]
    if verb == "next":
        return cmd_next()
    if verb == "record":
        if len(sys.argv) != 4 or sys.argv[2] != "--label":
            print("usage: record --label X", file=sys.stderr)
            return 2
        return cmd_record(sys.argv[3])
    if verb == "status":
        return cmd_status()
    print(f"unknown verb: {verb}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
