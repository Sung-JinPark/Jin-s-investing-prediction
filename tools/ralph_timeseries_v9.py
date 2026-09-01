"""V9 gate-loop harness: next / record / status (tools/v9_gate_loop.sh ADAPT point).

The queue is the contract's preregistered experiment list — nothing is
invented at runtime.  `next` emits {"label", "config"} for the first unrun
preregistered experiment (empty output when the queue is drained), `record`
verifies the ledger actually gained the labelled row, and `status` prints a
"champion" line only when a design row satisfies the preregistered proxy.
No holdout or sealed verb exists here by construction.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_fc.timeseries_v8.artifact import read_ledger  # noqa: E402  (read-only)
from ai_fc.timeseries_v9.contracts import (  # noqa: E402
    EXPERIMENT_LEDGER_RELATIVE,
    load_contract_v9,
)

PREREGISTERED_CONFIGS = {
    "V9_E0_identity_no_new_features": {"features": []},
    "V9_E1_m2sl_liquidity": {"features": ["F1_m2sl_liquidity"]},
}


def _ledger_labels() -> set[str]:
    return {
        str(row.get("experiment_label"))
        for row in read_ledger(ROOT, EXPERIMENT_LEDGER_RELATIVE)
        if row.get("window_role") == "design"
    }


def cmd_next() -> int:
    contract = load_contract_v9(ROOT)
    queue = list(contract["development_protocol"]["preregistered_first_experiments"])
    done = _ledger_labels()
    for label in queue:
        if label in done:
            continue
        if label not in PREREGISTERED_CONFIGS:
            print(f"unmapped preregistered experiment: {label}", file=sys.stderr)
            return 1
        print(json.dumps({"label": label, "config": PREREGISTERED_CONFIGS[label]},
                         ensure_ascii=False))
        return 0
    return 0  # queue drained: empty stdout tells the loop to stop exploring


def cmd_record(label: str) -> int:
    if label not in _ledger_labels():
        print(f"no design ledger row recorded for label {label}", file=sys.stderr)
        return 1
    print(f"recorded {label}")
    return 0


def cmd_status() -> int:
    from ai_fc.timeseries_v9.pipeline import design_champion
    champion = design_champion(ROOT)
    if champion is not None:
        print(f"champion: {champion.get('experiment_label')} ({champion.get('experiment_id')})")
    else:
        print("no champion yet")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: ralph_timeseries_v9.py next|record --label X|status", file=sys.stderr)
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
