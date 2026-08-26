"""Role-isolated asymmetric EVT screening on an authoritative R4 PIT export."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "r4_asymmetric_evt_v1"
SNAPSHOT_HASH = "cdddba1e32a4bdb3aebc98ec676c81744085a2a5952d4014807f0feb78140fc2"
G2_HASH = "3e19f5dc4360b0a74de41a7d4c54967597853b12c81689c57fbc34c281972523"
ROLE_HASHES = {
    "train": "2a7a8a0fec76a8eb89c665e8f01c84b65a4d9d5adf895f3b78852e39b7ab1c0c",
    "selection": "083263e2e2821d44de6fc7c6380065dde74e1f769721c32e2986be02564bf291",
    "stacking": "b862f54a09549b1472b0b5a6c6c5872aa7c7027675a7ace5468b627a20936f37",
    "calibration": "0f96b564e45155f90819c050f6435e964f8707989a67b5ba1f3da897c7b95fa2",
    "outer": "19e28f81dc9cf1f7935c10717d21c9e9fac15d01968b6bfb4f1f02c0332babfd",
}


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = probability * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def fit_tail(
    magnitudes: Iterable[float], *, side: str, minimum_exceedances: int = 30
) -> dict[str, Any]:
    """Fit one signed tail, shrinking sparse excesses explicitly to exponential E0."""
    observations = [float(value) for value in magnitudes if math.isfinite(float(value)) and value > 0]
    if not observations:
        raise ValueError(f"{side} tail has no finite positive magnitudes")
    threshold = _quantile(observations, 0.80) if len(observations) >= minimum_exceedances else 0.0
    excesses = [value - threshold for value in observations if value > threshold]
    sparse = len(excesses) < minimum_exceedances
    e0_scale = statistics.fmean(observations)
    fitted_scale = statistics.fmean(excesses) if excesses and not sparse else e0_scale
    # Method-of-moments GPD shape; the sparse guard fixes shape at E0's zero.
    if sparse or len(excesses) < 2:
        shape = 0.0
    else:
        mean = statistics.fmean(excesses)
        variance = statistics.pvariance(excesses)
        shape = max(-0.45, min(0.45, 0.5 * (1.0 - mean * mean / max(variance, 1e-15))))
    return {
        "side": side,
        "threshold": threshold,
        "exceedance_count": len(excesses),
        "minimum_exceedances": minimum_exceedances,
        "shrinkage_guard_to_e0": sparse,
        "reference_family": "E0_exponential" if sparse else "generalized_pareto",
        "shape": shape,
        "scale": max(fitted_scale, 1e-12),
    }


def build_family(
    horizon: int, values: Iterable[float], *, calibration_role_origin_count: int
) -> dict[str, Any]:
    observations = [float(value) for value in values if math.isfinite(float(value))]
    positive = [value for value in observations if value > 0]
    negative = [-value for value in observations if value < 0]
    positive_tail = fit_tail(positive, side="positive")
    negative_tail = fit_tail(negative, side="negative")
    absolute = [abs(value) for value in observations]
    q4 = _quantile(absolute, 0.75)
    extremes = [value for value in absolute if value >= q4]
    scale = max(statistics.fmean(absolute), 1e-12)
    tail_score = statistics.fmean([math.log(scale) + value / scale for value in extremes])
    return {
        "horizon": int(horizon),
        "calibration_role_origin_count": calibration_role_origin_count,
        "fit_role": "calibration_temporal_cross_fit",
        "state_available_at_origin": True,
        "positive_tail": positive_tail,
        "negative_tail": negative_tail,
        "extreme_q4_score": statistics.fmean([(value - q4) ** 2 for value in extremes]),
        "tail_score": tail_score,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def run(review_pack: Path, nested_member: str, authoritative_export: Path, output_dir: Path) -> dict[str, Any]:
    if _sha256(review_pack) != "9c57725beb833b3da8a67963f3dfe4399484396e3e21c308935c1e04a9110e28":
        raise ValueError("review-pack hash does not match the frozen input artifact")
    with zipfile.ZipFile(review_pack) as archive:
        if nested_member not in archive.namelist():
            raise ValueError("declared nested evidence member is absent")
    export = json.loads(authoritative_export.read_text(encoding="utf-8"))
    if export.get("snapshot_hash") != SNAPSHOT_HASH or export.get("source_store") != "authoritative_postgresql":
        raise ValueError("authoritative PostgreSQL PIT export identity mismatch")
    plan = export["five_role_plan"]
    if plan.get("role_hashes") != ROLE_HASHES:
        raise ValueError("frozen five-role coordinates changed")
    origins = set(plan["role_origins"]["calibration"])
    if len(origins) != 634:
        raise ValueError("calibration role must contain exactly 634 origins")
    features = {row["origin_session"]: row for row in export["feature_rows"]}
    snapshot_as_of = _parse_time(export["as_of"])
    by_horizon: dict[int, list[float]] = {1: [], 5: [], 21: [], 63: []}
    for label in export["labels"]:
        horizon = int(label["horizon_sessions"])
        origin = label["origin_session"]
        if horizon not in by_horizon or origin not in origins:
            continue
        feature = features[origin]
        if feature.get("pit_pass") is not True:
            raise ValueError(f"PIT failure at calibration origin {origin}")
        if _parse_time(feature["max_available_at"]) > _parse_time(feature["origin_cutoff_at"]):
            raise ValueError(f"future-data leakage at calibration origin {origin}")
        if _parse_time(label["mature_at"]) > snapshot_as_of:
            raise ValueError(f"unavailable outcome at calibration origin {origin}")
        by_horizon[horizon].append(float(label["value"]))
    families = []
    checkpoint_dir = output_dir / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    for horizon, values in by_horizon.items():
        if len(values) != 634:
            raise ValueError(f"h{horizon} has {len(values)} rather than 634 calibration outcomes")
        key_material = json.dumps({"schema": SCHEMA, "snapshot": SNAPSHOT_HASH, "role": ROLE_HASHES["calibration"], "horizon": horizon, "values": values}, separators=(",", ":"))
        key = hashlib.sha256(key_material.encode()).hexdigest()
        checkpoint = checkpoint_dir / f"h{horizon}-{key}.json"
        if checkpoint.exists():
            family = json.loads(checkpoint.read_text(encoding="utf-8"))
        else:
            family = build_family(horizon, values, calibration_role_origin_count=634)
            checkpoint.write_text(json.dumps(family, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        families.append(family)
    source = {
        "source_store": "authoritative_postgresql",
        "r4_snapshot_hash": SNAPSHOT_HASH,
        "g2_artifact_sha256": G2_HASH,
        "calibration_role_hash": ROLE_HASHES["calibration"],
        "role_hashes": ROLE_HASHES,
        "row_use_counters": {"legacy_review_pack_score_rows_used": 0, "qualification_score_rows_used": 0, "outer_rows_used": 0, "outer_origin_intersection": 0},
    }
    payload = {"schema": SCHEMA, "mechanism_screen_only": True, "promotion_claimed": False, "source": source, "families": families}
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "acceptance_summary.json").write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-pack", type=Path, required=True)
    parser.add_argument("--nested-member", required=True)
    parser.add_argument("--authoritative-export", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    run(args.review_pack, args.nested_member, args.authoritative_export, args.output_dir)


if __name__ == "__main__":
    main()
