"""R5 E2' exact-E0-nested conditional rescaling candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from ai_fc.timeseries_v7_r4.cross_fit_calibration import CalibrationCase, cross_fit_quantiles
from ai_fc.timeseries_v7_r4.e0_empirical_samples import empirical_crps
from ai_fc.timeseries_v7_r4.empirical_mixture import empirical_mixture_crps, optimize_empirical_mixture

from .conditional_scale_selection import _eligible, canonical_json
from .e0_nesting import load_e0_matrix, prove_e0_nesting
from .fhs_har_first_light import (
    E0_FLOORS,
    HORIZONS,
    _label_inputs,
    _load_runtime,
    _mixture_quantiles,
    _sample_hash,
    _scale,
    stationary_bootstrap_mean,
)


LAMBDAS = (0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5)


def rescale_e0_samples(e0: Iterable[float], *, sigma_hat: float, exponent: float) -> np.ndarray:
    values = np.asarray(tuple(e0), dtype=np.float64)
    if (values.ndim != 1 or len(values) < 2 or not np.isfinite(values).all()
            or not math.isfinite(sigma_hat) or sigma_hat <= 0 or exponent not in LAMBDAS):
        raise ValueError("finite E0, positive scale, and preregistered exponent are required")
    if exponent == 0.0:
        return values.copy()
    center = float(np.mean(values))
    base_scale = float(np.std(values, ddof=1))
    if base_scale <= 0:
        raise ValueError("E0 dispersion must be positive")
    return center + (values - center) * (sigma_hat / base_scale) ** exponent


def _candidate_cases(*, role: str, origins: list[str], horizon: int, exponent: float,
                     runtime: dict[str, Any], grouped: dict[int, list[dict[str, Any]]],
                     lookup: dict[tuple[str, int], dict[str, Any]],
                     matrix_rows: list[dict[str, Any]]) -> tuple[list[np.ndarray], list[np.ndarray], list[float]]:
    e0_forecasts: list[np.ndarray] = []
    candidate_forecasts: list[np.ndarray] = []
    actuals: list[float] = []
    for origin in origins:
        label = lookup.get((origin, horizon))
        if label is None:
            raise ValueError(f"missing {role} label {origin}:h{horizon}")
        e0 = _eligible(grouped, origin, horizon)
        sigma_hat = _scale(runtime, origin, horizon)
        candidate = rescale_e0_samples(e0, sigma_hat=sigma_hat, exponent=exponent)
        e0_forecasts.append(e0)
        candidate_forecasts.append(candidate)
        actuals.append(float(label["value"]))
        matrix_rows.append({
            "role": role, "origin_session": origin, "horizon_sessions": horizon,
            "family": "E2_prime_E0_rescale", "factorization": {
                "e0_center": float(np.mean(e0)), "e0_scale": float(np.std(e0, ddof=1)),
                "sigma_hat": sigma_hat, "lambda": exponent,
            },
            "sample_hash": _sample_hash(candidate, origin=origin, horizon=horizon,
                                         family="E2_prime_E0_rescale"),
            "e0_sample_hash": _sample_hash(e0, origin=origin, horizon=horizon, family="E0"),
        })
    return e0_forecasts, candidate_forecasts, actuals


def _paired_summary(provisional: list[dict[str, Any]], *, horizon: int) -> dict[str, Any]:
    differences = np.asarray([row["paired_advantage"] for row in provisional], dtype=np.float64)
    boot = stationary_bootstrap_mean(differences, mean_block_length=2 * horizon,
                                     replications=2000, seed=20260827 + 100 + horizon)
    e0_mean = float(np.mean([row["e0_crps"] for row in provisional]))
    mean_advantage = float(np.mean(differences))
    mde_crps = float((1.6448536269514722 + 0.8416212335729143) * np.std(boot, ddof=1))
    return {
        "calibration_e0_mean_crps": e0_mean,
        "calibration_stacked_mean_crps": float(np.mean([row["stacked_crps"] for row in provisional])),
        "paired_mean_advantage": mean_advantage, "paired_skill": mean_advantage / e0_mean,
        "stationary_bootstrap": {"replications": 2000, "mean_block_length": 2 * horizon,
                                  "ci90": [float(np.quantile(boot, 0.05)),
                                           float(np.quantile(boot, 0.95))]},
        "mde_crps": mde_crps, "mde_skill": mde_crps / e0_mean,
    }


def run_e0_rescale(export_path: Path, *, m5_dir: Path, registered_e0_matrix: Path,
                   output_dir: Path) -> dict[str, Any]:
    raw = export_path.read_bytes()
    export = json.loads(raw)
    plan, roles = export["five_role_plan"], export["five_role_plan"]["role_origins"]
    if plan.get("outer_exposed_during_screen") is not False:
        raise ValueError("outer role must remain sealed")
    runtime = _load_runtime(export, m5_dir)
    grouped, lookup = _label_inputs(export)

    selection_rows: list[dict[str, Any]] = []
    selected: dict[int, float] = {}
    for horizon in HORIZONS:
        for origin in roles["selection"]:
            label = lookup[(origin, horizon)]
            e0 = _eligible(grouped, origin, horizon)
            sigma_hat = _scale(runtime, origin, horizon)
            for exponent in LAMBDAS:
                candidate = rescale_e0_samples(e0, sigma_hat=sigma_hat, exponent=exponent)
                selection_rows.append({"origin_session": origin, "horizon": horizon,
                                       "lambda": exponent, "crps": empirical_crps(candidate, float(label["value"])),
                                       "role": "selection"})
        frame = pd.DataFrame([row for row in selection_rows if row["horizon"] == horizon])
        selected[horizon] = float(frame.groupby("lambda")["crps"].mean().idxmin())

    matrix_rows: list[dict[str, Any]] = []
    score_rows: list[dict[str, Any]] = []
    horizon_summary: dict[str, Any] = {}
    for horizon in HORIZONS:
        exponent = selected[horizon]
        e0_stack, candidate_stack, stack_actuals = _candidate_cases(
            role="stacking", origins=list(roles["stacking"]), horizon=horizon,
            exponent=exponent, runtime=runtime, grouped=grouped, lookup=lookup,
            matrix_rows=matrix_rows,
        )
        fitted = optimize_empirical_mixture([e0_stack, candidate_stack], stack_actuals,
                                            e0_floor=E0_FLOORS[horizon])
        weights = (float(fitted.weights[0]), float(fitted.weights[1]))
        e0_cal, candidate_cal, cal_actuals = _candidate_cases(
            role="calibration", origins=list(roles["calibration"]), horizon=horizon,
            exponent=exponent, runtime=runtime, grouped=grouped, lookup=lookup,
            matrix_rows=matrix_rows,
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
            "selected_lambda": exponent,
            "weights": {"E0": weights[0], "E2_prime": weights[1]},
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
        lambda coordinate: rescale_e0_samples(coordinate.values, sigma_hat=1.0, exponent=0.0),
        tolerance=1e-12,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(selection_rows).to_parquet(output_dir / "selection_lambda_scores.parquet", index=False)
    pd.DataFrame(score_rows).to_parquet(output_dir / "calibration_paired_scores.parquet", index=False)
    with (output_dir / "factorized_sample_matrix.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for row in matrix_rows:
            handle.write(canonical_json(row).decode("utf-8") + "\n")
    summary = {
        "schema": "r5_e2_prime_e0_rescale_v1", "family": "E2_prime_E0_rescale",
        "lambda_grid": list(LAMBDAS), "horizons": horizon_summary,
        "nesting_proof": nesting, "role_hashes": plan["role_hashes"],
        "sample_matrix": {"format": "exact_factorized_matrix_v1",
                          "coordinate_count": len(matrix_rows)},
        "row_use_counters": {"selection_rows_used": len(roles["selection"]) * 4,
                             "stacking_rows_used": len(roles["stacking"]) * 4,
                             "calibration_rows_used": len(roles["calibration"]) * 4,
                             "outer_rows_used": 0},
        "input_sha256": hashlib.sha256(raw).hexdigest(),
    }
    (output_dir / "e0_rescale_summary.json").write_bytes(canonical_json(summary) + b"\n")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", type=Path, required=True)
    parser.add_argument("--m5-dir", type=Path, required=True)
    parser.add_argument("--registered-e0-matrix", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    run_e0_rescale(args.export, m5_dir=args.m5_dir,
                   registered_e0_matrix=args.registered_e0_matrix,
                   output_dir=args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
