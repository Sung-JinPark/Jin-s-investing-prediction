"""Origin-available, cross-fitted full historical return trajectories."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Sequence

SCHEMA = "r4_full_analog_trajectories_v1"
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


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode()


def sample_analog_trajectories(feature_rows: list[dict], target_origin: str, *,
                               trajectory_length: int = 63,
                               minimum_spacing_sessions: int = 63) -> dict:
    """Select disjoint actual paths whose complete outcomes predate ``target_origin``.

    Selection is a deterministic temporal cross-fit: candidates are restricted to
    prices available at their own cutoff and completed before the target origin.
    No endpoint or missing-session interpolation is performed.
    """
    if trajectory_length != 63 or minimum_spacing_sessions < trajectory_length:
        raise ValueError("63-session trajectories require spacing of at least 63 sessions")
    rows = sorted((row for row in feature_rows
                   if str(row.get("origin_session", "")) < target_origin),
                  key=lambda row: str(row["origin_session"]))
    valid = []
    for row in rows:
        price = row.get("price")
        if (row.get("pit_pass") is not True or not isinstance(price, (int, float))
                or not math.isfinite(float(price)) or float(price) <= 0
                or _time(str(row["max_available_at"])) > _time(str(row["origin_cutoff_at"]))):
            continue
        valid.append(row)
    paths = []
    last_start = -minimum_spacing_sessions
    for start in range(0, len(valid) - trajectory_length):
        if start - last_start < minimum_spacing_sessions:
            continue
        window = valid[start:start + trajectory_length + 1]
        returns = [float(window[index + 1]["price"]) / float(window[index]["price"]) - 1.0
                   for index in range(trajectory_length)]
        identity = hashlib.sha256(_canonical({"start": window[0]["origin_session"],
            "end": window[-1]["origin_session"], "returns": returns})).hexdigest()
        paths.append({"trajectory_id": identity, "start_index": start,
                      "start_session": window[0]["origin_session"],
                      "end_session": window[-1]["origin_session"], "returns": returns})
        last_start = start
    identities = [path["trajectory_id"] for path in paths]
    drawdowns, touches, recoveries = [], 0, 0
    for path in paths:
        wealth = peak = 1.0
        minimum = 0.0
        touched = False
        recovered = False
        for value in path["returns"]:
            wealth *= 1.0 + value
            peak = max(peak, wealth)
            minimum = min(minimum, wealth / peak - 1.0)
            if wealth / peak - 1.0 <= -0.05:
                touched = True
            elif touched and wealth >= peak * 0.99:
                recovered = True
        drawdowns.append(minimum)
        touches += int(touched)
        recoveries += int(recovered)
    return {"trajectory_length": trajectory_length, "minimum_spacing_sessions": minimum_spacing_sessions,
            "temporal_spacing_rule": "start_index_distance_gte_63_xnas_sessions",
            "actual_contiguous_returns": True, "endpoint_interpolation_used": False,
            "origin_available_cross_fit": True, "target_origin": target_origin,
            "trajectory_count": len(paths), "duplicate_count": len(paths) - len(set(identities)),
            "trajectory_set_sha256": hashlib.sha256(_canonical(paths)).hexdigest(),
            "maximum_drawdown": float(min(drawdowns, default=0.0)),
            "first_touch_rate": float(touches / len(paths)) if paths else 0.0,
            "recovery_rate": float(recoveries / touches) if touches else 0.0,
            "trajectories": paths}


def acceptance(review_pack: Path, nested_member: str, authoritative_export: Path,
               output_dir: Path) -> dict:
    if hashlib.sha256(review_pack.read_bytes()).hexdigest() != REVIEW_PACK_HASH:
        raise ValueError("review-pack hash mismatch")
    with zipfile.ZipFile(review_pack) as archive:
        archive.getinfo(nested_member)
    export_bytes = authoritative_export.read_bytes()
    export = json.loads(export_bytes)
    plan = export.get("five_role_plan") or {}
    if (export.get("source_store") != "authoritative_postgresql"
            or export.get("snapshot_hash") != SNAPSHOT_HASH):
        raise ValueError("authoritative PostgreSQL R4 snapshot identity mismatch")
    if plan.get("role_hashes") != ROLE_HASHES:
        raise ValueError("frozen five-role coordinates changed")
    calibration = list((plan.get("role_origins") or {}).get("calibration", []))
    if len(calibration) != 634:
        raise ValueError("calibration role must contain exactly 634 origins")
    target = calibration[-1]
    key = hashlib.sha256(export_bytes + f"|h63|{SCHEMA}".encode()).hexdigest()
    checkpoint = output_dir / "checkpoints" / f"h63-{key}.json"
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    if checkpoint.exists():
        report = json.loads(checkpoint.read_text(encoding="utf-8"))
    else:
        report = sample_analog_trajectories(export["feature_rows"], target)
        checkpoint.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    if report["trajectory_count"] <= 0:
        raise ValueError("authoritative evidence produced no eligible trajectories")
    counters = {"calibration_fit_rows": 1, "train_fit_rows": 0, "selection_fit_rows": 0,
                "stacking_fit_rows": 0, "legacy_review_pack_score_rows_used": 0,
                "qualification_score_rows_used": 0, "outer_rows_used": 0,
                "outer_origin_intersection": 0}
    source = {"source_store": "authoritative_postgresql", "r4_snapshot_hash": SNAPSHOT_HASH,
              "r4_snapshot_artifact_sha256": hashlib.sha256(export_bytes).hexdigest(),
              "g2_artifact_sha256": G2_HASH, "calibration_role_hash": ROLE_HASHES["calibration"],
              "role_hashes": ROLE_HASHES, "row_use_counters": counters}
    summary = {**{key: value for key, value in report.items() if key != "trajectories"},
               "schema_version": 1, "schema": SCHEMA, "source": source,
               "role_hashes": ROLE_HASHES, "row_use_counters": counters,
               "diagnostics_sha256": hashlib.sha256(_canonical({key: report[key] for key in
                   ("maximum_drawdown", "first_touch_rate", "recovery_rate")})).hexdigest(),
               "checkpoint": str(checkpoint)}
    output_dir.mkdir(parents=True, exist_ok=True)
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
