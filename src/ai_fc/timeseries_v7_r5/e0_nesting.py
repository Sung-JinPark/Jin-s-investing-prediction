"""Content-addressed E0 matrix loader and reusable nesting proof harness."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


E0_CONTRACT = {
    "contract_id": "E0_exact_empirical_anchor_v1",
    "algorithm": "exact_empirical_anchor",
    "input": "matured_direct_horizon_training_labels",
    "eligibility": "available_at_on_or_before_as_of",
    "sampling": "none",
}


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


@dataclass(frozen=True)
class E0Coordinate:
    origin_session: str
    horizon_sessions: int
    values: tuple[float, ...]
    sample_set_hash: str


@dataclass(frozen=True)
class E0Matrix:
    matrix_hash: str
    coordinates: tuple[E0Coordinate, ...]


def load_e0_matrix(path: Path) -> E0Matrix:
    if "quarantine" in {part.lower() for part in path.parts}:
        raise ValueError("quarantined E0 artifacts cannot enter R5")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("artifact_type") != "e0_sample_matrix" or payload.get("contract") != E0_CONTRACT:
        raise ValueError("artifact is not the exact empirical E0 contract")
    claimed = payload.get("matrix_hash")
    hash_payload = dict(payload)
    hash_payload.pop("matrix_hash", None)
    if claimed != _sha(hash_payload):
        raise ValueError("E0 matrix content hash mismatch")
    coordinates: list[E0Coordinate] = []
    seen: set[tuple[str, int]] = set()
    for row in payload.get("coordinates", []):
        sample = row["sample_set"]
        if sample.get("distribution") != "E0_empirical_samples_v1" or int(sample.get("seed", -1)) != 0:
            raise ValueError("E0 coordinate is reconstructed or resampled")
        key = (str(row["origin_session"]), int(row["horizon_sessions"]))
        if key in seen:
            raise ValueError("duplicate E0 coordinate")
        seen.add(key)
        values = tuple(float(value) for value in sample["values"])
        if not values or not all(math.isfinite(value) for value in values):
            raise ValueError("E0 values must be finite and non-empty")
        receipt = {
            "distribution": sample["distribution"], "origin_session": sample["origin_session"],
            "horizon_sessions": int(sample["horizon_sessions"]), "seed": int(sample["seed"]),
            "values": values,
        }
        if sample.get("sample_set_hash") != _sha(receipt):
            raise ValueError("E0 coordinate sample hash mismatch")
        stage_hashes = row.get("stage_sample_set_hashes", {})
        if set(stage_hashes.values()) != {sample["sample_set_hash"]}:
            raise ValueError("E0 stage identity changed")
        coordinates.append(E0Coordinate(*key, values, sample["sample_set_hash"]))
    if not coordinates:
        raise ValueError("E0 matrix has no coordinates")
    return E0Matrix(str(claimed), tuple(coordinates))


CandidateFactory = Callable[[E0Coordinate], Iterable[float]]


def prove_e0_nesting(matrix: E0Matrix, candidate_factory: CandidateFactory,
                     *, tolerance: float = 1e-12) -> dict[str, object]:
    if tolerance < 0 or not math.isfinite(tolerance):
        raise ValueError("nesting tolerance must be finite and non-negative")
    maximum = 0.0
    value_count = 0
    for coordinate in matrix.coordinates:
        candidate = tuple(float(value) for value in candidate_factory(coordinate))
        if len(candidate) != len(coordinate.values):
            raise ValueError("candidate and E0 sample counts differ")
        for expected, observed in zip(coordinate.values, candidate, strict=True):
            error = abs(expected - observed)
            maximum = max(maximum, error)
            value_count += 1
    if maximum > tolerance:
        raise ValueError(f"candidate does not nest E0: max_abs_error={maximum}")
    return {
        "schema": "r5_e0_nesting_proof_v1", "matrix_hash": matrix.matrix_hash,
        "coordinate_count": len(matrix.coordinates), "value_count": value_count,
        "tolerance": tolerance, "max_abs_error": maximum, "nesting_test_pass": True,
        "row_use_counters": {"outer_rows_used": 0},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    matrix = load_e0_matrix(args.matrix)
    proof = prove_e0_nesting(matrix, lambda coordinate: coordinate.values)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_json(proof) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
