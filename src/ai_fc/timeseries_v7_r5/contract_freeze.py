"""Recompute the frozen R4 role and evaluation-coordinate identities for R5."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROLE_ORDER = ("train", "selection", "stacking", "calibration", "outer")
EXPECTED_ROLE_HASHES = {
    "train": "2a7a8a0fec76a8eb89c665e8f01c84b65a4d9d5adf895f3b78852e39b7ab1c0c",
    "selection": "083263e2e2821d44de6fc7c6380065dde74e1f769721c32e2986be02564bf291",
    "stacking": "b862f54a09549b1472b0b5a6c6c5872aa7c7027675a7ace5468b627a20936f37",
    "calibration": "0f96b564e45155f90819c050f6435e964f8707989a67b5ba1f3da897c7b95fa2",
    "outer": "19e28f81dc9cf1f7935c10717d21c9e9fac15d01968b6bfb4f1f02c0332babfd",
}
EXPECTED_GRID_HASH = "1f2403b7b15c100741a29816304056c2ad7b91cd777b29534a96a567068fa7e8"


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def verify_frozen_identities(*, export: dict[str, Any], g0: dict[str, Any],
                             g3: dict[str, Any]) -> dict[str, Any]:
    plan = export["five_role_plan"]
    role_origins = plan["role_origins"]
    if tuple(plan["role_order"]) != ROLE_ORDER:
        raise ValueError("five-role order changed")
    recomputed_roles = {role: digest(role_origins[role]) for role in ROLE_ORDER}
    if recomputed_roles != EXPECTED_ROLE_HASHES:
        raise ValueError("recomputed role hashes differ from the frozen R4 values")
    if plan["role_hashes"] != recomputed_roles:
        raise ValueError("authoritative export role hashes do not match their origin lists")
    if g3["role_hashes"] != recomputed_roles:
        raise ValueError("G3 role hashes differ from the authoritative export")

    coordinates = sorted([
        [str(row["origin_session"]), int(row["horizon_sessions"])]
        for row in g0["coordinate_sample_identity"]
    ])
    if len(coordinates) != len({(row[0], row[1]) for row in coordinates}):
        raise ValueError("evaluation coordinates are not unique")
    grid_hash = digest(coordinates)
    if grid_hash != EXPECTED_GRID_HASH:
        raise ValueError("recomputed evaluation grid hash changed")
    if g0["source"]["evaluation_coordinate_grid_hash"] != grid_hash:
        raise ValueError("G0 grid receipt does not match coordinate metadata")
    if g3["frozen_evaluation"]["evaluation_coordinate_grid_hash"] != grid_hash:
        raise ValueError("G3 grid receipt does not match G0")

    return {
        "schema": "r5_a2_frozen_identity_v1",
        "role_order": list(ROLE_ORDER),
        "role_counts": {role: len(role_origins[role]) for role in ROLE_ORDER},
        "role_hashes_recomputed": recomputed_roles,
        "role_hashes_match": True,
        "evaluation_coordinate_grid_hash_recomputed": grid_hash,
        "evaluation_coordinate_grid_hash_match": True,
        "evaluation_coordinate_count": len(coordinates),
        "evaluation_origin_count": len({row[0] for row in coordinates}),
        "coordinate_metadata_only": True,
        "outer_outcomes_read": 0,
        "row_use_counters": {"outer_rows_used": 0},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", type=Path, required=True)
    parser.add_argument("--g0", type=Path, required=True)
    parser.add_argument("--g3", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = verify_frozen_identities(
        export=json.loads(args.export.read_text(encoding="utf-8")),
        g0=json.loads(args.g0.read_text(encoding="utf-8")),
        g3=json.loads(args.g3.read_text(encoding="utf-8")),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_json(result) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
