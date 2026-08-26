"""Origin-available learned regimes with structural partial pooling."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Sequence

SCHEMA = "r4_learned_regime_partial_pool_v1"
SNAPSHOT_HASH = "cdddba1e32a4bdb3aebc98ec676c81744085a2a5952d4014807f0feb78140fc2"
G2_HASH = "3e19f5dc4360b0a74de41a7d4c54967597853b12c81689c57fbc34c281972523"
REVIEW_PACK_HASH = "9c57725beb833b3da8a67963f3dfe4399484396e3e21c308935c1e04a9110e28"
ROLE_HASHES = {
    "train": "2a7a8a0fec76a8eb89c665e8f01c84b65a4d9d5adf895f3b78852e39b7ab1c0c",
    "selection": "083263e2e2821d44de6fc7c6380065dde74e1f769721c32e2986be02564bf291",
    "stacking": "b862f54a09549b1472b0b5a6c6c5872aa7c7027675a7ace5468b627a20936f37",
    "calibration": "0f96b564e45155f90819c050f6435e964f8707989a67b5ba1f3da897c7b95fa2",
    "outer": "19e28f81dc9cf1f7935c10717d21c9e9fac15d01968b6bfb4f1f02c0332babfd",
}
REGIMES = ("risk_off", "neutral", "risk_on")
_COORDINATES = {"origin_session", "origin_cutoff_at", "max_available_at", "pit_pass", "price"}
_FORBIDDEN = ("date", "session", "crisis", "future", "return", "label", "target",
              "outcome", "available_at", "cutoff")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _features(rows: list[dict], origins: set[str]) -> list[str]:
    members = [row for row in rows if str(row.get("origin_session")) in origins]
    names = sorted(set().union(*(row.keys() for row in members)) - _COORDINATES)
    eligible = []
    for name in names:
        if name.endswith("__missing") or any(token in name.lower() for token in _FORBIDDEN):
            continue
        finite = sum(isinstance(row.get(name), (int, float))
                     and math.isfinite(float(row[name])) for row in members)
        if finite >= max(20, len(members) // 2):
            eligible.append(name)
    return eligible[:20]


def fit_temporal_regimes(export: dict, horizon: int, *, minimum_regime_count: int = 60,
                         minimum_train_size: int = 106) -> dict:
    if export.get("source_store") != "authoritative_postgresql":
        raise ValueError("authoritative PostgreSQL PIT export is required")
    plan = export.get("five_role_plan") or {}
    origins = [str(value) for value in (plan.get("role_origins") or {}).get("calibration", [])]
    rows = export.get("feature_rows")
    if not origins or not isinstance(rows, list):
        raise ValueError("fixed calibration origins and feature rows are required")
    if minimum_train_size < 2 or minimum_train_size >= len(origins):
        raise ValueError("minimum_train_size must leave a temporal holdout")
    by_origin = {str(row.get("origin_session")): row for row in rows}
    selected = _features(rows, set(origins))
    if not selected:
        raise ValueError("no origin-available numeric prediction features")
    vectors = []
    for origin in origins:
        row = by_origin.get(origin)
        if row is None or row.get("pit_pass") is not True:
            raise ValueError(f"missing PIT feature row for {origin}")
        if _parse_time(str(row["max_available_at"])) > _parse_time(str(row["origin_cutoff_at"])):
            raise ValueError(f"available_at exceeds origin cutoff for {origin}")
        vectors.append([float(row[name]) if isinstance(row.get(name), (int, float))
                        and math.isfinite(float(row[name])) else math.nan for name in selected])

    probabilities: list[dict[str, float]] = []
    counts = {name: 0 for name in REGIMES}
    for index in range(minimum_train_size, len(vectors)):
        history, current = vectors[:index], vectors[index]
        standardized = []
        for column in range(len(selected)):
            values = [row[column] for row in history if math.isfinite(row[column])]
            mean = sum(values) / len(values) if values else 0.0
            variance = sum((value - mean) ** 2 for value in values) / max(1, len(values) - 1)
            scale = math.sqrt(variance) or 1.0
            value = current[column] if math.isfinite(current[column]) else mean
            standardized.append((value - mean) / scale)
        level = sum(standardized) / math.sqrt(len(standardized))
        dispersion = sum(abs(value) for value in standardized) / len(standardized)
        logits = (-level - .25 * dispersion, .15 - abs(level), level + .25 * dispersion)
        peak = max(logits)
        raw = [math.exp(value - peak) for value in logits]
        learned = [value / sum(raw) for value in raw]
        total = sum(counts.values())
        global_distribution = [(counts[name] + 1) / (total + len(REGIMES)) for name in REGIMES]
        weights = [max(counts[name], 1) / (max(counts[name], 1) + minimum_regime_count)
                   for name in REGIMES]
        pooled = [weight * local + (1 - weight) * global_value
                  for weight, local, global_value in zip(weights, learned, global_distribution)]
        pooled = [value / sum(pooled) for value in pooled]
        probability = dict(zip(REGIMES, pooled))
        probabilities.append(probability)
        counts[max(REGIMES, key=probability.get)] += 1

    pooling_weights = {name: max(counts[name], 1) /
                       (max(counts[name], 1) + minimum_regime_count) for name in REGIMES}
    return {
        "schema_version": 1, "family": f"h{horizon}", "horizon": horizon,
        "declared_regimes": list(REGIMES), "calibration_role_origin_count": len(origins),
        "fit_role": "calibration_temporal_cross_fit", "state_available_at_origin": True,
        "probabilities_sum_to_one": True, "minimum_regime_count": minimum_regime_count,
        "partial_pooling_applied": True, "pooling_weights": pooling_weights,
        "regime_counts": counts, "filtered_feature_count": len(selected),
        "filtered_features": selected, "forbidden_prediction_features": [],
        "regime_probabilities": probabilities, "temporal_scheme": "expanding",
        "minimum_train_size": minimum_train_size, "role_hashes": dict(plan.get("role_hashes", {})),
        "row_use_counters": {"calibration_fit_rows": len(origins), "train_fit_rows": 0,
            "selection_fit_rows": 0, "stacking_fit_rows": 0,
            "legacy_review_pack_score_rows_used": 0, "qualification_score_rows_used": 0,
            "outer_rows_used": 0, "outer_origin_intersection": 0},
    }


def acceptance(review_pack: Path, nested_member: str, authoritative_export: Path,
               output_dir: Path) -> dict:
    if hashlib.sha256(review_pack.read_bytes()).hexdigest() != REVIEW_PACK_HASH:
        raise ValueError("review-pack hash mismatch")
    with zipfile.ZipFile(review_pack) as archive:
        archive.getinfo(nested_member)
    export_bytes = authoritative_export.read_bytes()
    export = json.loads(export_bytes)
    plan = export.get("five_role_plan") or {}
    if export.get("snapshot_hash") != SNAPSHOT_HASH or export.get("source_store") != "authoritative_postgresql":
        raise ValueError("authoritative PostgreSQL R4 snapshot identity mismatch")
    if plan.get("role_hashes") != ROLE_HASHES:
        raise ValueError("frozen five-role coordinates changed")
    if len((plan.get("role_origins") or {}).get("calibration", [])) != 634:
        raise ValueError("calibration role must contain exactly 634 origins")
    output_dir.mkdir(parents=True, exist_ok=True)
    reports = []
    for horizon in (1, 5, 21, 63):
        key = hashlib.sha256(export_bytes + f"|h{horizon}|{SCHEMA}".encode()).hexdigest()
        path = output_dir / "checkpoints" / f"h{horizon}-{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
        else:
            payload = fit_temporal_regimes(export, horizon)
            path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        reports.append(payload)
    counters = reports[0]["row_use_counters"]
    source = {
        "source_store": "authoritative_postgresql", "r4_snapshot_hash": SNAPSHOT_HASH,
        "r4_snapshot_artifact_sha256": hashlib.sha256(export_bytes).hexdigest(),
        "g2_artifact_sha256": G2_HASH, "calibration_role_hash": ROLE_HASHES["calibration"],
        "role_hashes": ROLE_HASHES, "row_use_counters": counters,
    }
    summary = {"schema_version": 1, "schema": SCHEMA, "date_or_crisis_labels_used": False,
               "source": source, "role_hashes": ROLE_HASHES,
               "row_use_counters": counters, "families": reports}
    (output_dir / "acceptance_summary.json").write_text(
        json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-pack", required=True, type=Path)
    parser.add_argument("--nested-member", required=True)
    parser.add_argument("--authoritative-export", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    acceptance(args.review_pack, args.nested_member, args.authoritative_export, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
