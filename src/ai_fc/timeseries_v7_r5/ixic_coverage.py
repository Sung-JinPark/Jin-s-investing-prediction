"""Audit the official NASDAQ Composite increment used by R5."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_coverage(*, predecessor: Path, current: Path, receipt: Path) -> dict[str, Any]:
    before, after = _read_jsonl(predecessor), _read_jsonl(current)
    evidence = json.loads(receipt.read_text(encoding="utf-8"))
    if not before or not after:
        raise ValueError("NASDAQCOM observation ledgers must be non-empty")
    for row in after:
        if row.get("series_id") != "NASDAQCOM" or row.get("source") != "FRED":
            raise ValueError("R5 market rows must be official FRED NASDAQCOM observations")
        if not row.get("raw_sha256") or not row.get("available_at"):
            raise ValueError("R5 market rows require raw and availability lineage")
    predecessor_dates = {row["date"] for row in before}
    incremental = [row for row in after if row["date"] not in predecessor_dates]
    if evidence.get("freshness_pass") is not True or evidence.get("missing_completed_sessions") != 0:
        raise ValueError("NASDAQCOM source is not current through the last completed XNAS session")
    latest = max(row["date"] for row in after)
    if latest != evidence["target_completed_xnas_session"]:
        raise ValueError("latest official observation does not equal the last completed XNAS session")
    return {
        "schema": "r5_a3_ixic_coverage_v1",
        "symbol_mapping": {"research_target": "^IXIC", "official_series": "NASDAQCOM"},
        "data_grade": "reconstructed_market_archive",
        "source": "FRED",
        "predecessor_rows": len(before),
        "current_rows": len(after),
        "incremental_rows": len(incremental),
        "incremental_dates": [row["date"] for row in incremental],
        "latest_observation_session": latest,
        "target_completed_xnas_session": evidence["target_completed_xnas_session"],
        "missing_completed_sessions": 0,
        "freshness_pass": True,
        "predecessor_sha256": _sha256(predecessor),
        "current_sha256": _sha256(current),
        "receipt_sha256": _sha256(receipt),
        "raw_sha256": evidence["raw_sha256"],
        "row_use_counters": {"outer_rows_used": 0},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predecessor", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build_coverage(predecessor=args.predecessor, current=args.current, receipt=args.receipt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
