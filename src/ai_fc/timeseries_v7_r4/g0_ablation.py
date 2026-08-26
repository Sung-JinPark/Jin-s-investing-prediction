"""G0 E0-only benchmark and no-regret component ablation.

The input score rows are frozen evaluation coordinates produced by the PIT
pipeline.  This module never re-qualifies, refits, or changes their sample set.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import zipfile
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from .integrity import canonical_json, sha256_bytes
from .e0_empirical_samples import E0_EXACT_EMPIRICAL_CONTRACT, EvaluationPath, fit_exact_empirical_anchor


DEFAULT_STRESS_WINDOWS = {
    "gfc": ("2007-07-01", "2009-06-30"),
    "rebound_2009": ("2009-03-01", "2010-03-31"),
    "pandemic": ("2020-02-01", "2020-06-30"),
    "rebound_2020": ("2020-04-01", "2021-03-31"),
    "tightening_2022": ("2022-01-01", "2022-12-31"),
    "bull_2023": ("2023-01-01", "2023-12-31"),
}


def _skill(rows: list[Mapping[str, Any]], score_column: str) -> dict[str, Any]:
    score = sum(float(row[score_column]) for row in rows)
    reference = sum(abs(float(row["actual"])) for row in rows)
    if not rows or not math.isfinite(score) or reference <= 0:
        raise ValueError("finite non-empty score rows with a positive reference are required")
    return {"count": len(rows), "mean_crps": score / len(rows),
            "reference_mean_crps": reference / len(rows),
            "skill": 1.0 - score / reference}


def generate_g0_ablation(
    score_rows: Iterable[Mapping[str, Any]], *,
    component_columns: Mapping[str, str],
    stress_windows: Mapping[str, tuple[str, str]],
    qualify: Callable[[], Mapping[str, Any]],
) -> dict[str, Any]:
    """Qualify once, then record exact E0 skill, stress, and no-regret weights."""
    qualification = dict(qualify())
    if qualification.get("qualified") is not True:
        raise ValueError("qualification failed before G0")
    rows = [dict(row) for row in score_rows]
    required = {"origin_session", "horizon", "actual", "baseline_crps"}
    if not rows or any(not required.issubset(row) for row in rows):
        raise ValueError("complete G0 score rows are required")
    if any(column not in row for row in rows for column in component_columns.values()):
        raise ValueError("complete component score columns are required")

    horizons = sorted({int(row["horizon"]) for row in rows})
    e0_skill = []
    for horizon in horizons:
        selected = [row for row in rows if int(row["horizon"]) == horizon]
        e0_skill.append({"horizon_sessions": horizon,
                         **_skill(selected, "baseline_crps")})

    stress = []
    for suite, (start, end) in sorted(stress_windows.items()):
        for horizon in horizons:
            selected = [row for row in rows if int(row["horizon"]) == horizon
                        and start <= str(row["origin_session"]) <= end]
            if selected:
                stress.append({"suite": suite, "horizon_sessions": horizon,
                               **_skill(selected, "baseline_crps")})

    ablations: dict[str, Any] = {}
    for name, column in sorted(component_columns.items()):
        e0_total = sum(float(row["baseline_crps"]) for row in rows)
        candidate_total = sum(float(row[column]) for row in rows)
        gain = 1.0 - candidate_total / e0_total if e0_total > 0 else float("nan")
        ablations[name] = {
            "mean_crps": candidate_total / len(rows),
            "skill_vs_e0": gain,
            "destructive": not math.isfinite(gain) or gain <= 0.0,
            "weight": min(1.0, gain) if math.isfinite(gain) and gain > 0.0 else 0.0,
        }

    sample_hash = sha256_bytes(canonical_json([
        {key: row[key] for key in sorted(row)} for row in sorted(
            rows, key=lambda row: (str(row["origin_session"]), int(row["horizon"])),
        )
    ]))
    return {
        "schema": "g0_exact_e0_ablation_v1",
        "qualification_count": 1,
        "qualification_evidence": qualification,
        "sample_set_hash": sample_hash,
        "e0_only_skill": e0_skill,
        "e0_only_stress": stress,
        "component_ablations": ablations,
    }


def replay_exact_e0_grid(
    labels: Iterable[Mapping[str, Any]], *,
    evaluation_origins: Iterable[str],
    r4_snapshot_hash: str,
    qualify: Callable[[], Mapping[str, Any]],
    five_role_validation_proof: bool,
    component_scores: Mapping[str, Mapping[tuple[str, int], float]] | None = None,
    stress_windows: Mapping[str, tuple[str, str]] = DEFAULT_STRESS_WINDOWS,
) -> dict[str, Any]:
    """Replay E0 from direct labels; no predecessor score is an input."""
    qualification = dict(qualify())
    if qualification.get("qualified") is not True:
        raise ValueError("qualification failed before G0")
    if not five_role_validation_proof:
        raise ValueError("five-role validation proof is required")
    if len(r4_snapshot_hash) != 64:
        raise ValueError("a content-addressed R4 snapshot is required")
    source_labels = [dict(row) for row in labels]
    required = {"origin_session", "horizon_sessions", "label_end_session", "mature_at", "value"}
    if not source_labels or any(not required.issubset(row) for row in source_labels):
        raise ValueError("complete PostgreSQL direct-horizon labels are required")
    origins = sorted(set(map(str, evaluation_origins)))
    origin_set = set(origins)
    rows: list[dict[str, Any]] = []
    identities: list[dict[str, Any]] = []
    identity_failures = 0
    for label in source_labels:
        origin = str(label["origin_session"])
        horizon = int(label["horizon_sessions"])
        if origin not in origin_set or horizon not in (1, 5, 21, 63):
            continue
        samples = fit_exact_empirical_anchor(
            origin_session=origin, horizon_sessions=horizon,
            labels=({"origin_session": item["origin_session"],
                     "horizon_sessions": item["horizon_sessions"],
                     "available_at": item["mature_at"], "value": item["value"]}
                    for item in source_labels),
        )
        path = EvaluationPath.bind(samples)
        artifacts = (path.score(actual=float(label["value"])), path.stacking_input(),
                     path.calibration_input(), path.forecast())
        hashes = {item.stage: item.sample_set_hash for item in artifacts}
        if len(set(hashes.values())) != 1:
            identity_failures += 1
        row = {"origin_session": origin, "horizon": horizon,
               "actual": float(label["value"]), "baseline_crps": artifacts[0].value}
        for name, scores in (component_scores or {}).items():
            row[name] = float(scores.get((origin, horizon), artifacts[0].value))
        rows.append(row)
        identities.append({"origin_session": origin, "horizon_sessions": horizon,
                           "sample_set_hashes": hashes, "sample_count": len(samples.values)})
    if not rows:
        raise ValueError("the frozen origin grid has no matured labels")
    report = generate_g0_ablation(
        rows, component_columns={name: name for name in (component_scores or {})},
        stress_windows=stress_windows, qualify=lambda: qualification,
    )
    report.update({
        "comparator_contract": dict(E0_EXACT_EMPIRICAL_CONTRACT),
        "source": {"r4_snapshot_hash": r4_snapshot_hash,
                   "origin_count": len({row["origin_session"] for row in rows}),
                   "coordinate_count": len(rows), "store": "postgresql"},
        "exact_replay_count": len(rows), "sample_identity_failures": identity_failures,
        "approximate_baseline_rows_used": 0,
        "five_role_validation_proof": True,
        "coordinate_sample_identity": identities,
    })
    return report


def _read_real_pack(path: Path, nested_member: str, expected_sha256: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("declared evidence pack hash mismatch")
    with zipfile.ZipFile(io.BytesIO(raw)) as outer:
        nested = outer.read(nested_member)
    with zipfile.ZipFile(io.BytesIO(nested)) as evidence:
        prefix = "EVIDENCE/outputs/timeseries_v7/open_data_runs/v7-alfred-20260825T083047Z/"
        rows = pd.read_parquet(io.BytesIO(evidence.read(prefix + "scores.parquet"))).to_dict("records")
        qualification = json.loads(evidence.read(
            "EVIDENCE/data/timeseries_v7/gates/v7-alfred-20260825T083047Z/data_quality_gate.json"
        ))
        qualification["qualified"] = (
            qualification.get("state") == "READY"
            and qualification.get("train_allowed") is True
        )
    return rows, qualification


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pack", type=Path)
    parser.add_argument("--nested-member", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    rows, qualification = _read_real_pack(args.pack, args.nested_member, args.sha256)
    report = generate_g0_ablation(
        rows, component_columns={"legacy_e2_mixture": "model_crps"},
        stress_windows=DEFAULT_STRESS_WINDOWS, qualify=lambda: qualification,
    )
    report.update({"source_pack_sha256": args.sha256,
                   "nested_member": args.nested_member})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_json(report) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
