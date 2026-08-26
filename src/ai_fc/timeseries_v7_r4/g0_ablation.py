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
