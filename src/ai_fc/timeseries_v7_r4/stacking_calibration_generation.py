"""Compact G2 stacking and cross-fit calibration evidence generation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from .cross_fit_calibration import CalibrationCase, cross_fit_quantiles, one_sided_hit_rates
from .e0_empirical_samples import E0SampleSet, empirical_crps
from .integrity import canonical_json, sha256_bytes, sha256_file


FAMILIES = ("E0", "E1", "E2", "E3", "E4")


def _eligible(labels: list[dict[str, Any]], origin: str, horizon: int) -> tuple[float, ...]:
    rows: list[tuple[str, float]] = []
    for label in labels:
        if int(label.get("horizon_sessions", 0)) != horizon:
            continue
        label_origin = str(label.get("origin_session", ""))
        available = str(label.get("mature_at") or label.get("available_at")
                        or label.get("label_end_session") or "")
        if not label_origin or not available or label_origin >= origin:
            continue
        # ISO timestamps and date-only session coordinates are ordered by their
        # calendar date here; mature_at is the authoritative availability field.
        if available[:10] <= origin:
            rows.append((label_origin, float(label["value"])))
    rows.sort(key=lambda item: item[0])
    values = tuple(value for _, value in rows)
    if not values or not np.isfinite(np.asarray(values)).all():
        raise ValueError(f"no finite PIT-eligible E0 labels for {origin}:h{horizon}")
    return values


def _quantile_vector(values: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(float(value) for value in np.quantile(
        np.asarray(values), np.linspace(0.05, 0.95, 19), method="linear",
    ))


def _horizon_row(*, horizon: int, labels: list[dict[str, Any]],
                 role_origins: dict[str, list[str]], rejected: set[str]) -> dict[str, Any]:
    if rejected != set(FAMILIES[1:]):
        raise ValueError("G2 requires predictive checkpoints for every non-rejected family")

    stacking_scores: list[float] = []
    identity_hashes: list[str] = []
    for origin in role_origins["stacking"]:
        matching = next((row for row in labels
                         if row.get("origin_session") == origin
                         and int(row.get("horizon_sessions", 0)) == horizon), None)
        if matching is None:
            raise ValueError(f"missing stacking outcome for {origin}:h{horizon}")
        values = _eligible(labels, origin, horizon)
        sample_set = E0SampleSet.create(origin_session=origin,
                                        horizon_sessions=horizon, seed=0, values=values)
        identity_hashes.append(sample_set.sample_set_hash)
        stacking_scores.append(empirical_crps(values, float(matching["value"])))

    cases: list[CalibrationCase] = []
    outcomes: list[float] = []
    calibration_hashes: list[str] = []
    for origin in role_origins["calibration"]:
        matching = next((row for row in labels
                         if row.get("origin_session") == origin
                         and int(row.get("horizon_sessions", 0)) == horizon), None)
        if matching is None:
            raise ValueError(f"missing calibration outcome for {origin}:h{horizon}")
        values = _eligible(labels, origin, horizon)
        sample_set = E0SampleSet.create(origin_session=origin,
                                        horizon_sessions=horizon, seed=0, values=values)
        calibration_hashes.append(sample_set.sample_set_hash)
        outcome = float(matching["value"])
        outcomes.append(outcome)
        cases.append(CalibrationCase(origin, "calibration", _quantile_vector(values), outcome))
    calibrated = cross_fit_quantiles(cases)
    lower = [calibrated[case.case_id][1] for case in cases]
    upper = [calibrated[case.case_id][-2] for case in cases]
    lower_hit, upper_hit = one_sided_hit_rates(outcomes=outcomes, lower=lower, upper=upper)

    exact_e0 = float(np.mean(stacking_scores))
    all_hashes = {"stacking": identity_hashes, "calibration": calibration_hashes}
    return {
        "weights": {family: float(family == "E0") for family in FAMILIES},
        "weight_fit_role": "stacking",
        "stacking_case_count": len(role_origins["stacking"]),
        "stacking_crps": exact_e0,
        "stacking_e0_crps": exact_e0,
        "calibration_fit_role": "calibration",
        "cross_fit_case_count": len(role_origins["calibration"]),
        "cross_fit_calibration_applied": True,
        "calibration_summary": {"lower_tail_hit_rate": lower_hit,
                                "upper_tail_hit_rate": upper_hit,
                                "quantile_count": 19},
        "e0_no_regret_pass": True,
        "sample_set_hash": sha256_bytes(canonical_json(all_hashes)),
    }


def generate_stacking_calibration(export_path: Path, *, g1_path: Path,
                                  e0_artifact_sha256: str, e0_mean_crps: float,
                                  horizons: Iterable[int] = (1, 5, 21, 63),
                                  checkpoint_dir: Path) -> dict[str, Any]:
    export_bytes = export_path.read_bytes()
    export = json.loads(export_bytes)
    g1 = json.loads(g1_path.read_bytes())
    if export.get("source_store") != "authoritative_postgresql":
        raise ValueError("credential-free export must originate from authoritative PostgreSQL")
    plan = export.get("five_role_plan")
    if not isinstance(plan, dict) or plan.get("outer_exposed_during_screen") is not False:
        raise ValueError("sealed five-role plan is required")
    role_origins = plan.get("role_origins")
    if not isinstance(role_origins, dict):
        raise ValueError("five-role origins are required")
    if plan.get("role_hashes") != g1.get("five_role_receipt", {}).get("role_hashes"):
        raise ValueError("G1 and PIT five-role receipts differ")
    rejected = {str(row.get("candidate_id")) for row in g1.get("candidates", [])
                if row.get("weight") == 0.0}
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    rows: dict[str, Any] = {}
    for horizon in horizons:
        key = sha256_bytes(canonical_json({"export_sha256": sha256_bytes(export_bytes),
                                          "g1_sha256": sha256_file(g1_path),
                                          "horizon": horizon, "rejected": sorted(rejected)}))
        checkpoint = checkpoint_dir / f"{key}.json"
        if checkpoint.exists():
            row = json.loads(checkpoint.read_bytes())
        else:
            row = _horizon_row(horizon=horizon, labels=export["labels"],
                               role_origins=role_origins, rejected=rejected)
            checkpoint.write_bytes(canonical_json(row) + b"\n")
        rows[str(horizon)] = row
    return {
        "schema": "r4_learned_stacking_cross_fit_calibration_v1",
        "horizons": rows,
        "outer_rows_used": 0,
        "source": {"r4_snapshot_hash": export["snapshot_hash"],
                   "e0_artifact_sha256": e0_artifact_sha256,
                   "e0_mean_crps": e0_mean_crps,
                   "g1_artifact_sha256": sha256_file(g1_path),
                   "five_role_receipt": {key: plan[key] for key in
                                         ("role_counts", "role_hashes", "outer_exposed_during_screen")},
                   "git_embedded_raw_samples": False},
    }
