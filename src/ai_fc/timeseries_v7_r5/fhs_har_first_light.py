"""R5 E1' FHS conditional-scale first-light on frozen five-role evidence."""

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
from ai_fc.timeseries_v7_r4.empirical_mixture import (
    empirical_mixture_crps,
    optimize_empirical_mixture,
)

from .conditional_scale_selection import (
    GarchTFit,
    HarFit,
    _eligible,
    _ewma_paths,
    _forecast_source,
    _garch_variance_path,
    _rv_features,
    canonical_json,
)
from .e0_nesting import load_e0_matrix, prove_e0_nesting


HORIZONS = (1, 5, 21, 63)
E0_FLOORS = {1: 0.20, 5: 0.25, 21: 0.40, 63: 0.50}
EXPECTED_SKILL_RANGES = {1: (0.01, 0.04), 5: (0.01, 0.03), 21: (0.0, 0.02), 63: (0.0, 0.0)}
QUANTILE_GRID = np.linspace(0.05, 0.95, 19)


def e1_fhs_samples(e0: Iterable[float], *, center: float, sigma_hat: float,
                   standardized_residuals: Iterable[float], degenerate_to_e0: bool = False) -> np.ndarray:
    """Generate E1' samples; the registered boundary returns byte-identical E0 values."""
    baseline = np.asarray(tuple(e0), dtype=np.float64)
    if baseline.ndim != 1 or not len(baseline) or not np.isfinite(baseline).all():
        raise ValueError("finite E0 samples are required")
    if degenerate_to_e0:
        return baseline.copy()
    residuals = np.asarray(tuple(standardized_residuals), dtype=np.float64)
    if (residuals.ndim != 1 or not len(residuals) or not np.isfinite(residuals).all()
            or not math.isfinite(center) or not math.isfinite(sigma_hat) or sigma_hat <= 0):
        raise ValueError("finite center, positive scale, and residual pool are required")
    return center + sigma_hat * residuals


def stationary_bootstrap_mean(values: Iterable[float], *, mean_block_length: int,
                              replications: int = 2000, seed: int = 20260827) -> np.ndarray:
    """Politis-Romano stationary bootstrap means with deterministic circular continuation."""
    observed = np.asarray(tuple(values), dtype=np.float64)
    if (observed.ndim != 1 or len(observed) < 2 or not np.isfinite(observed).all()
            or mean_block_length < 1 or replications < 1):
        raise ValueError("valid paired differences and bootstrap controls are required")
    rng = np.random.default_rng(seed)
    restart_probability = 1.0 / min(mean_block_length, len(observed))
    means = np.empty(replications, dtype=np.float64)
    for replicate in range(replications):
        index = int(rng.integers(0, len(observed)))
        total = 0.0
        for _ in range(len(observed)):
            total += observed[index]
            if rng.random() < restart_probability:
                index = int(rng.integers(0, len(observed)))
            else:
                index = (index + 1) % len(observed)
        means[replicate] = total / len(observed)
    return means


def _sample_hash(values: np.ndarray, *, origin: str, horizon: int, family: str) -> str:
    metadata = canonical_json({"origin_session": origin, "horizon_sessions": horizon,
                               "family": family, "dtype": "float64-le", "count": len(values)})
    canonical_values = np.asarray(values, dtype="<f8")
    return hashlib.sha256(metadata + b"\0" + canonical_values.tobytes(order="C")).hexdigest()


def _mixture_quantiles(e0: np.ndarray, e1: np.ndarray, weights: tuple[float, float]) -> tuple[float, ...]:
    values = np.concatenate((e0, e1))
    masses = np.concatenate((np.full(len(e0), weights[0] / len(e0)),
                             np.full(len(e1), weights[1] / len(e1))))
    order = np.argsort(values, kind="mergesort")
    values, cumulative = values[order], np.cumsum(masses[order])
    return tuple(float(values[min(int(np.searchsorted(cumulative, q, side="left")), len(values) - 1)])
                 for q in QUANTILE_GRID)


def _load_runtime(export: dict[str, Any], m5_dir: Path) -> dict[str, Any]:
    frame = pd.DataFrame(export["feature_rows"])[["origin_session", "price"]].copy()
    frame = frame.sort_values("origin_session").reset_index(drop=True)
    prices = frame["price"].to_numpy(dtype=float)
    returns = np.zeros(len(prices), dtype=float)
    returns[1:] = np.diff(np.log(prices))
    models = json.loads((m5_dir / "conditional_scale_models.json").read_text(encoding="utf-8"))
    summary = json.loads((m5_dir / "selection_summary.json").read_text(encoding="utf-8"))
    pool_receipt = json.loads((m5_dir / "standardized_residual_pool.json").read_text(encoding="utf-8"))
    har: dict[tuple[int, float], HarFit] = {}
    for key, value in models["har"].items():
        horizon = int(key.split(":", 1)[0].removeprefix("h"))
        alpha = float(key.split("alpha=", 1)[1])
        har[(horizon, alpha)] = HarFit(horizon, alpha, tuple(value["coefficients"]),
                                       float(value["residual_variance"]))
    garch = GarchTFit(**{key: float(value) for key, value in models["garch_t"].items()})
    pools = {int(horizon): {
        "center": float(value["center"]),
        "z": np.asarray([row["z"] for row in value["rows"]], dtype=np.float64),
        "source": str(value["selected_source"]),
    } for horizon, value in pool_receipt["pools"].items()}
    if {str(h): pools[h]["source"] for h in HORIZONS} != summary["selected_sources"]:
        raise ValueError("selected scale source and residual pool receipt differ")
    return {
        "frame": frame, "returns": returns,
        "index": {value: index for index, value in enumerate(frame["origin_session"])},
        "har": har, "ewma": _ewma_paths(returns), "garch": garch,
        "garch_path": _garch_variance_path(returns, garch), "pools": pools,
    }


def _scale(runtime: dict[str, Any], origin: str, horizon: int) -> float:
    index = runtime["index"][origin]
    return _forecast_source(
        runtime["pools"][horizon]["source"], horizon=horizon, index=index,
        feature=_rv_features(runtime["returns"], index), har=runtime["har"],
        ewma=runtime["ewma"], returns=runtime["returns"],
        garch_path=runtime["garch_path"], garch=runtime["garch"],
    )


def _label_inputs(export: dict[str, Any]) -> tuple[dict[int, list[dict[str, Any]]], dict[tuple[str, int], dict[str, Any]]]:
    grouped = {horizon: [] for horizon in HORIZONS}
    lookup: dict[tuple[str, int], dict[str, Any]] = {}
    for row in export["labels"]:
        horizon = int(row["horizon_sessions"])
        if horizon in grouped:
            grouped[horizon].append(row)
            lookup[(str(row["origin_session"]), horizon)] = row
    return grouped, lookup


def _role_cases(*, role: str, origins: list[str], horizon: int, runtime: dict[str, Any],
                grouped: dict[int, list[dict[str, Any]]], lookup: dict[tuple[str, int], dict[str, Any]],
                matrix_rows: list[dict[str, Any]]) -> tuple[list[np.ndarray], list[np.ndarray], list[float]]:
    e0_forecasts: list[np.ndarray] = []
    e1_forecasts: list[np.ndarray] = []
    actuals: list[float] = []
    pool = runtime["pools"][horizon]
    pool_hash = hashlib.sha256(np.asarray(pool["z"], dtype="<f8").tobytes()).hexdigest()
    for origin in origins:
        label = lookup.get((origin, horizon))
        if label is None:
            raise ValueError(f"missing {role} label {origin}:h{horizon}")
        e0 = _eligible(grouped, origin, horizon)
        sigma_hat = _scale(runtime, origin, horizon)
        e1 = e1_fhs_samples(e0, center=pool["center"], sigma_hat=sigma_hat,
                            standardized_residuals=pool["z"])
        e0_forecasts.append(e0)
        e1_forecasts.append(e1)
        actuals.append(float(label["value"]))
        matrix_rows.append({
            "role": role, "origin_session": origin, "horizon_sessions": horizon,
            "family": "E1_prime_FHS_HAR", "factorization": {
                "center": pool["center"], "sigma_hat": sigma_hat,
                "standardized_residual_pool_sha256": pool_hash,
                "standardized_residual_count": len(pool["z"]),
            },
            "sample_hash": _sample_hash(e1, origin=origin, horizon=horizon, family="E1_prime_FHS_HAR"),
            "e0_sample_hash": _sample_hash(e0, origin=origin, horizon=horizon, family="E0"),
        })
    return e0_forecasts, e1_forecasts, actuals


def run_first_light(export_path: Path, *, m5_dir: Path, registered_e0_matrix: Path,
                    output_dir: Path) -> dict[str, Any]:
    raw = export_path.read_bytes()
    export = json.loads(raw)
    plan = export["five_role_plan"]
    roles = plan["role_origins"]
    if plan.get("outer_exposed_during_screen") is not False:
        raise ValueError("outer role must remain sealed")
    if any(set(roles[left]) & set(roles[right]) for index, left in enumerate(roles)
           for right in list(roles)[index + 1:]):
        raise ValueError("five-role origins overlap")
    runtime = _load_runtime(export, m5_dir)
    grouped, lookup = _label_inputs(export)
    matrix_rows: list[dict[str, Any]] = []
    score_rows: list[dict[str, Any]] = []
    horizon_summary: dict[str, Any] = {}

    for horizon in HORIZONS:
        e0_stack, e1_stack, stacking_actuals = _role_cases(
            role="stacking", origins=list(roles["stacking"]), horizon=horizon,
            runtime=runtime, grouped=grouped, lookup=lookup, matrix_rows=matrix_rows,
        )
        fitted = optimize_empirical_mixture(
            [e0_stack, e1_stack], stacking_actuals, e0_floor=E0_FLOORS[horizon],
        )
        weights = (float(fitted.weights[0]), float(fitted.weights[1]))
        e0_cal, e1_cal, calibration_actuals = _role_cases(
            role="calibration", origins=list(roles["calibration"]), horizon=horizon,
            runtime=runtime, grouped=grouped, lookup=lookup, matrix_rows=matrix_rows,
        )
        calibration_cases: list[CalibrationCase] = []
        deltas: list[float] = []
        provisional: list[dict[str, Any]] = []
        for origin, e0, e1, actual in zip(roles["calibration"], e0_cal, e1_cal,
                                          calibration_actuals, strict=True):
            e0_score = empirical_crps(e0, actual)
            e1_score = empirical_crps(e1, actual)
            stacked_score = empirical_mixture_crps([[e0], [e1]], [actual], weights)
            quantiles = _mixture_quantiles(e0, e1, weights)
            calibration_cases.append(CalibrationCase(origin, "calibration", quantiles, actual))
            deltas.append(e0_score - stacked_score)
            provisional.append({
                "origin_session": origin, "horizon": horizon, "role": "calibration",
                "actual": actual, "e0_crps": e0_score, "e1_crps": e1_score,
                "stacked_crps": stacked_score, "paired_advantage": e0_score - stacked_score,
                "e0_weight": weights[0], "e1_weight": weights[1],
            })
        calibrated = cross_fit_quantiles(calibration_cases)
        calibrated_rows: list[tuple[float, tuple[float, ...]]] = []
        for row in provisional:
            quantiles = calibrated[row["origin_session"]]
            row.update({"p10": quantiles[1], "p25": quantiles[4], "p50": quantiles[9],
                        "p75": quantiles[14], "p90": quantiles[17]})
            score_rows.append(row)
            calibrated_rows.append((float(row["actual"]), quantiles))

        differences = np.asarray(deltas, dtype=np.float64)
        boot = stationary_bootstrap_mean(
            differences, mean_block_length=2 * horizon, replications=2000,
            seed=20260827 + horizon,
        )
        e0_mean = float(np.mean([row["e0_crps"] for row in provisional]))
        mean_advantage = float(np.mean(differences))
        mde_crps = float((1.6448536269514722 + 0.8416212335729143) * np.std(boot, ddof=1))
        mde_skill = mde_crps / e0_mean
        expected_range = EXPECTED_SKILL_RANGES[horizon]
        horizon_summary[str(horizon)] = {
            "weights": {"E0": weights[0], "E1_prime": weights[1]},
            "e0_floor": E0_FLOORS[horizon], "stacking_crps": fitted.crps,
            "stacking_e0_only_fallback": fitted.used_e0_only_fallback,
            "calibration_e0_mean_crps": e0_mean,
            "calibration_stacked_mean_crps": float(np.mean([row["stacked_crps"] for row in provisional])),
            "paired_mean_advantage": mean_advantage,
            "paired_skill": mean_advantage / e0_mean,
            "stationary_bootstrap": {"replications": 2000, "mean_block_length": 2 * horizon,
                                      "ci90": [float(np.quantile(boot, 0.05)),
                                               float(np.quantile(boot, 0.95))]},
            "mde_crps": mde_crps, "mde_skill": mde_skill,
            "expected_skill_range": list(expected_range),
            "mde_exceeds_expected_upper": bool(mde_skill > expected_range[1]),
            "mde_exceeds_long_gate_target": bool(horizon in (21, 63) and mde_skill > 0.02),
            "cross_fit_calibration": {
                "fit_role": "calibration_temporal_cross_fit",
                "evaluation_role": "calibration_cross_fit_holdout",
                "case_count": len(calibrated_rows),
                "coverage80": float(np.mean([q[1] <= actual <= q[17]
                                               for actual, q in calibrated_rows])),
                "coverage50": float(np.mean([q[4] <= actual <= q[14]
                                               for actual, q in calibrated_rows])),
            },
        }

    nesting = prove_e0_nesting(
        load_e0_matrix(registered_e0_matrix),
        lambda coordinate: e1_fhs_samples(
            coordinate.values, center=0.0, sigma_hat=1.0,
            standardized_residuals=(0.0,), degenerate_to_e0=True,
        ), tolerance=1e-12,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(score_rows).to_parquet(output_dir / "calibration_paired_scores.parquet", index=False)
    with (output_dir / "factorized_sample_matrix.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for row in matrix_rows:
            handle.write(canonical_json(row).decode("utf-8") + "\n")
    summary = {
        "schema": "r5_e1_prime_fhs_har_first_light_v1",
        "family": "E1_prime_FHS_HAR", "horizons": horizon_summary,
        "nesting_proof": nesting,
        "sample_matrix": {"format": "exact_factorized_matrix_v1",
                          "coordinate_count": len(matrix_rows),
                          "reconstruction": "center + sigma_hat * frozen_standardized_residual_pool"},
        "role_hashes": plan["role_hashes"],
        "row_use_counters": {"train_rows_used": len(roles["train"]) * 4,
                             "selection_rows_used": 0,
                             "stacking_rows_used": len(roles["stacking"]) * 4,
                             "calibration_rows_used": len(roles["calibration"]) * 4,
                             "outer_rows_used": 0},
        "input_sha256": hashlib.sha256(raw).hexdigest(),
        "d2_decision_required": any(row["mde_exceeds_long_gate_target"]
                                    for row in horizon_summary.values()),
    }
    (output_dir / "first_light_summary.json").write_bytes(canonical_json(summary) + b"\n")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", type=Path, required=True)
    parser.add_argument("--m5-dir", type=Path, required=True)
    parser.add_argument("--registered-e0-matrix", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    run_first_light(args.export, m5_dir=args.m5_dir,
                    registered_e0_matrix=args.registered_e0_matrix,
                    output_dir=args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
