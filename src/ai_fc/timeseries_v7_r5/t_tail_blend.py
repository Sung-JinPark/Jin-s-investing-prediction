"""R5 E4' exact-E0-nested Student-t tail blend candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from scipy.stats import t as student_t

from ai_fc.timeseries_v7_r4.cross_fit_calibration import CalibrationCase, cross_fit_quantiles
from ai_fc.timeseries_v7_r4.e0_empirical_samples import empirical_crps
from ai_fc.timeseries_v7_r4.empirical_mixture import empirical_mixture_crps, optimize_empirical_mixture

from .conditional_scale_selection import _eligible, canonical_json
from .e0_nesting import load_e0_matrix, prove_e0_nesting
from .e0_rescale import _paired_summary
from .fhs_har_first_light import (
    E0_FLOORS,
    HORIZONS,
    _label_inputs,
    _load_runtime,
    _mixture_quantiles,
    _sample_hash,
    _scale,
)


# Frozen before reading selection results.  The df grid is the R4 S-2 E2
# contract; pi is the R5 blueprint's bounded [0, 0.3] screen.
DEGREES_OF_FREEDOM = (3.0, 5.0, 8.0, 12.0)
PI_GRID = (0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30)


def fit_student_df(standardized_residuals: Iterable[float]) -> float:
    values = np.asarray(tuple(standardized_residuals), dtype=np.float64)
    if values.ndim != 1 or len(values) < 100 or not np.isfinite(values).all():
        raise ValueError("at least 100 finite train-only standardized residuals are required")
    scores = {
        df: float(-np.mean(student_t.logpdf(values, df)))
        for df in DEGREES_OF_FREEDOM
    }
    return min(scores, key=scores.get)


def t_tail_blend_samples(e0: Iterable[float], *, sigma_hat: float, degrees_of_freedom: float,
                         pi: float) -> np.ndarray:
    """Return empirical quantile blend; pi=0 is byte-exact E0."""
    values = np.asarray(tuple(e0), dtype=np.float64)
    if (values.ndim != 1 or len(values) < 2 or not np.isfinite(values).all()
            or not math.isfinite(sigma_hat) or sigma_hat <= 0
            or degrees_of_freedom not in DEGREES_OF_FREEDOM or pi not in PI_GRID):
        raise ValueError("finite E0 and preregistered scale, df, and pi are required")
    if pi == 0.0:
        return values.copy()
    probabilities = (np.arange(len(values), dtype=float) + 0.5) / len(values)
    empirical = np.sort(values, kind="mergesort")
    variance_correction = math.sqrt((degrees_of_freedom - 2.0) / degrees_of_freedom)
    tail = (float(np.mean(values)) + sigma_hat * variance_correction
            * student_t.ppf(probabilities, degrees_of_freedom))
    blended = (1.0 - pi) * empirical + pi * tail
    if not np.isfinite(blended).all():
        raise ValueError("Student-t blend produced non-finite samples")
    return blended


def _role_cases(*, role: str, origins: list[str], horizon: int, pi: float, df: float,
                runtime: dict[str, Any], grouped: dict[int, list[dict[str, Any]]],
                lookup: dict[tuple[str, int], dict[str, Any]],
                matrix_rows: list[dict[str, Any]]) -> tuple[list[np.ndarray], list[np.ndarray], list[float]]:
    e0_rows: list[np.ndarray] = []
    candidate_rows: list[np.ndarray] = []
    actuals: list[float] = []
    for origin in origins:
        label = lookup.get((origin, horizon))
        if label is None:
            raise ValueError(f"missing {role} label {origin}:h{horizon}")
        e0 = _eligible(grouped, origin, horizon)
        sigma_hat = _scale(runtime, origin, horizon)
        candidate = t_tail_blend_samples(e0, sigma_hat=sigma_hat,
                                          degrees_of_freedom=df, pi=pi)
        e0_rows.append(e0)
        candidate_rows.append(candidate)
        actuals.append(float(label["value"]))
        matrix_rows.append({
            "role": role, "origin_session": origin, "horizon_sessions": horizon,
            "family": "E4_prime_t_tail_blend",
            "factorization": {"sigma_hat": sigma_hat, "degrees_of_freedom": df, "pi": pi,
                              "variance_correction": math.sqrt((df - 2.0) / df)},
            "sample_hash": _sample_hash(candidate, origin=origin, horizon=horizon,
                                        family="E4_prime_t_tail_blend"),
            "e0_sample_hash": _sample_hash(e0, origin=origin, horizon=horizon, family="E0"),
        })
    return e0_rows, candidate_rows, actuals


def run_t_tail_blend(export_path: Path, *, m5_dir: Path, registered_e0_matrix: Path,
                     output_dir: Path) -> dict[str, Any]:
    raw = export_path.read_bytes()
    export = json.loads(raw)
    plan, roles = export["five_role_plan"], export["five_role_plan"]["role_origins"]
    if plan.get("outer_exposed_during_screen") is not False:
        raise ValueError("outer role must remain sealed")
    runtime = _load_runtime(export, m5_dir)
    grouped, lookup = _label_inputs(export)

    selected_df = {h: fit_student_df(runtime["pools"][h]["z"]) for h in HORIZONS}
    selection_rows: list[dict[str, Any]] = []
    selected_pi: dict[int, float] = {}
    for horizon in HORIZONS:
        for origin in roles["selection"]:
            actual = float(lookup[(origin, horizon)]["value"])
            e0 = _eligible(grouped, origin, horizon)
            sigma_hat = _scale(runtime, origin, horizon)
            for pi in PI_GRID:
                candidate = t_tail_blend_samples(
                    e0, sigma_hat=sigma_hat, degrees_of_freedom=selected_df[horizon], pi=pi,
                )
                selection_rows.append({"role": "selection", "origin_session": origin,
                                       "horizon": horizon, "pi": pi,
                                       "crps": empirical_crps(candidate, actual)})
        frame = pd.DataFrame(row for row in selection_rows if row["horizon"] == horizon)
        selected_pi[horizon] = float(frame.groupby("pi")["crps"].mean().idxmin())

    matrix_rows: list[dict[str, Any]] = []
    score_rows: list[dict[str, Any]] = []
    horizon_summary: dict[str, Any] = {}
    for horizon in HORIZONS:
        pi, df = selected_pi[horizon], selected_df[horizon]
        e0_stack, candidate_stack, stack_actuals = _role_cases(
            role="stacking", origins=list(roles["stacking"]), horizon=horizon, pi=pi, df=df,
            runtime=runtime, grouped=grouped, lookup=lookup, matrix_rows=matrix_rows,
        )
        fitted = optimize_empirical_mixture([e0_stack, candidate_stack], stack_actuals,
                                            e0_floor=E0_FLOORS[horizon])
        weights = (float(fitted.weights[0]), float(fitted.weights[1]))
        e0_cal, candidate_cal, cal_actuals = _role_cases(
            role="calibration", origins=list(roles["calibration"]), horizon=horizon, pi=pi, df=df,
            runtime=runtime, grouped=grouped, lookup=lookup, matrix_rows=matrix_rows,
        )
        cases: list[CalibrationCase] = []
        provisional: list[dict[str, Any]] = []
        for origin, e0, candidate, actual in zip(roles["calibration"], e0_cal, candidate_cal,
                                                 cal_actuals, strict=True):
            e0_score = empirical_crps(e0, actual)
            candidate_score = empirical_crps(candidate, actual)
            stacked_score = empirical_mixture_crps([[e0], [candidate]], [actual], weights)
            cases.append(CalibrationCase(origin, "calibration",
                                         _mixture_quantiles(e0, candidate, weights), actual))
            provisional.append({"origin_session": origin, "horizon": horizon,
                                "role": "calibration", "actual": actual,
                                "e0_crps": e0_score, "candidate_crps": candidate_score,
                                "stacked_crps": stacked_score,
                                "paired_advantage": e0_score - stacked_score,
                                "e0_weight": weights[0], "candidate_weight": weights[1]})
        calibrated = cross_fit_quantiles(cases)
        for row in provisional:
            quantiles = calibrated[row["origin_session"]]
            row.update({"p10": quantiles[1], "p25": quantiles[4], "p50": quantiles[9],
                        "p75": quantiles[14], "p90": quantiles[17]})
            score_rows.append(row)
        horizon_summary[str(horizon)] = {
            "degrees_of_freedom": df, "df_fit_role": "train",
            "selected_pi": pi, "pi_selection_role": "selection",
            "weights": {"E0": weights[0], "E4_prime": weights[1]},
            "e0_floor": E0_FLOORS[horizon], "stacking_crps": fitted.crps,
            "stacking_e0_only_fallback": fitted.used_e0_only_fallback,
            **_paired_summary(provisional, horizon=horizon),
            "cross_fit_calibration": {
                "fit_role": "calibration_temporal_cross_fit",
                "evaluation_role": "calibration_cross_fit_holdout",
                "case_count": len(provisional),
                "coverage80": float(np.mean([row["p10"] <= row["actual"] <= row["p90"]
                                               for row in provisional])),
                "coverage50": float(np.mean([row["p25"] <= row["actual"] <= row["p75"]
                                               for row in provisional])),
            },
        }

    nesting = prove_e0_nesting(
        load_e0_matrix(registered_e0_matrix),
        lambda coordinate: t_tail_blend_samples(
            coordinate.values, sigma_hat=1.0, degrees_of_freedom=3.0, pi=0.0,
        ), tolerance=1e-12,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(selection_rows).to_parquet(output_dir / "selection_pi_scores.parquet", index=False)
    pd.DataFrame(score_rows).to_parquet(output_dir / "calibration_paired_scores.parquet", index=False)
    with (output_dir / "factorized_sample_matrix.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for row in matrix_rows:
            handle.write(canonical_json(row).decode("utf-8") + "\n")
    summary = {
        "schema": "r5_e4_prime_t_tail_blend_v1", "family": "E4_prime_t_tail_blend",
        "degrees_of_freedom_grid": list(DEGREES_OF_FREEDOM), "pi_grid": list(PI_GRID),
        "horizons": horizon_summary, "nesting_proof": nesting,
        "role_hashes": plan["role_hashes"],
        "sample_matrix": {"format": "exact_factorized_matrix_v1",
                          "coordinate_count": len(matrix_rows)},
        "row_use_counters": {"train_rows_used": sum(len(runtime["pools"][h]["z"])
                                                       for h in HORIZONS),
                             "selection_rows_used": len(roles["selection"]) * 4,
                             "stacking_rows_used": len(roles["stacking"]) * 4,
                             "calibration_rows_used": len(roles["calibration"]) * 4,
                             "outer_rows_used": 0},
        "input_sha256": hashlib.sha256(raw).hexdigest(),
    }
    (output_dir / "t_tail_blend_summary.json").write_bytes(canonical_json(summary) + b"\n")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", type=Path, required=True)
    parser.add_argument("--m5-dir", type=Path, required=True)
    parser.add_argument("--registered-e0-matrix", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    run_t_tail_blend(args.export, m5_dir=args.m5_dir,
                     registered_e0_matrix=args.registered_e0_matrix,
                     output_dir=args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
