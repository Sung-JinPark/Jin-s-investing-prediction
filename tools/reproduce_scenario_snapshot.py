"""Reproduce a serialized NASDAQ GBM partition from its public snapshot only.

This verifier does not fetch prices.  It uses the snapshot's anchor, exact-enough
serialized daily log-return parameters, seed, horizon, barriers and trading-day
calendar.  It proves that reviewers can reproduce S1/S2/S3 weights and the daily
quantile table without the private working SQLite index.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_fc.scenario_shadow.legacy_reproduction import reproduce_legacy_snapshot


def verify(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    reproduction = reproduce_legacy_snapshot(payload)
    verification = reproduction.verification
    expected_probabilities = [payload["paths"][key]["prob"] for key in ("S1", "S2", "S3")]
    reproduced_probabilities = [
        reproduction.probability_percent[key] for key in ("S1", "S2", "S3")
    ]
    result: dict[str, object] = {
        "snapshot_id": payload.get("snapshot_id"),
        "probabilities_expected": expected_probabilities,
        "probabilities_reproduced": reproduced_probabilities,
        "member_counts": reproduction.counts,
        "future_matrix_shape": list(reproduction.future_daily.shape),
        "weekly_matrix_shape": list(reproduction.sampled_weekly.shape),
        "quantile_cells_checked": verification["quantile_cells_checked"],
        "quantile_mismatches": verification["quantile_mismatches"],
        "retained_member_mismatches": verification["retained_member_mismatches"],
        "passed": verification["passed"],
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "snapshot", nargs="?", type=Path,
        default=Path("data/scenarios/nasdaq_latest.json"),
    )
    args = parser.parse_args()
    result = verify(args.snapshot)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
