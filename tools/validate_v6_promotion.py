#!/usr/bin/env python3
"""Validate a V6 manual promotion receipt; performs no publication action."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_fc.timeseries_v6.publication import PromotionError, load_and_validate_decision


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--decision", type=Path, required=True)
    parser.add_argument("--contract-hash", required=True)
    parser.add_argument("--candidate-bundle-hash", required=True)
    parser.add_argument("--gate-decision-hash", required=True)
    parser.add_argument("--trusted-owner", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = load_and_validate_decision(
            args.decision,
            expected_contract_hash=args.contract_hash,
            expected_candidate_bundle_hash=args.candidate_bundle_hash,
            expected_gate_decision_hash=args.gate_decision_hash,
            trusted_owner_ids=set(args.trusted_owner),
        )
    except (PromotionError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}), file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "validated", "decision_id": receipt["decision_id"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
