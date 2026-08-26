"""Credential-free acceptance using the Supervisor-provided PIT review pack."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_fc.timeseries_v7_r4.data_pit_qualification import qualify_evidence_pack
from ai_fc.timeseries_v7_r4.open_data_challenger import OpenDataChallengerContract


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--pack-sha256", required=True)
    parser.add_argument("--nested-member", required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    contract = OpenDataChallengerContract.from_path(args.contract)
    pit = qualify_evidence_pack(
        args.pack,
        nested_member=args.nested_member,
        expected_sha256=args.pack_sha256,
    )

    result = {
        "schema_version": 1,
        "authoritative_pack_sha256": pit["source_pack_sha256"],
        "authoritative_pack_qualified": pit["qualified"],
        "all_weights_zero": all(source.weight == 0.0 for source in contract.sources),
        "frozen_v7_coordinates_unchanged": contract.frozen_v7_coordinates_unchanged,
        "official_gate_eligible": any(source.official_gate_eligible for source in contract.sources),
        "pit_and_terms_receipts_complete": all(source.pit_grade and source.license_receipt and source.terms_receipt for source in contract.sources),
        "pit_violations": pit["pit_violations"],
        "receipt_count": pit["receipt_count"],
        "receipt_terminal_outcome_rate": pit["receipt_terminal_outcome_rate"],
        "run_id": pit["run_id"],
        "source_count": len(contract.sources),
        "v8_proposal_required": contract.v8_proposal_required,
    }
    if not (result["all_weights_zero"] and not result["official_gate_eligible"] and result["pit_and_terms_receipts_complete"] and result["pit_violations"] == 0):
        raise ValueError("open-data challenger acceptance failed")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
