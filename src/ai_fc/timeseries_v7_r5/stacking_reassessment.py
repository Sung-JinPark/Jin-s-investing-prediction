"""R5 S1 preregistered candidate stacking and calibration reassessment."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

from ai_fc.timeseries_v7_r4.cross_fit_calibration import CalibrationCase, cross_fit_quantiles
from ai_fc.timeseries_v7_r4.e0_empirical_samples import empirical_crps
from ai_fc.timeseries_v7_r4.empirical_mixture import empirical_mixture_crps, optimize_empirical_mixture

from .conditional_scale_selection import _eligible, canonical_json
from .e0_nesting import load_e0_matrix, prove_e0_nesting
from .e0_rescale import _paired_summary, rescale_e0_samples
from .event_multiplier import event_flags, event_multiplier_samples, load_event_calendar
from .fhs_har_first_light import (
    E0_FLOORS,
    HORIZONS,
    QUANTILE_GRID,
    _label_inputs,
    _load_runtime,
    _scale,
    e1_fhs_samples,
)
from .t_tail_blend import t_tail_blend_samples


F_DELTA_GRID = (0.0, 0.05, 0.10, 0.15, 0.20)
FAMILY_NAMES = ("E0", "E1_prime", "E2_prime", "E3_prime", "E4_prime", "F_location")


def fit_ar1(train_returns: Iterable[float]) -> tuple[float, float]:
    values = np.asarray(tuple(train_returns), dtype=np.float64)
    if values.ndim != 1 or len(values) < 500 or not np.isfinite(values).all():
        raise ValueError("AR1 requires at least 500 finite train-only daily returns")
    design = np.column_stack((np.ones(len(values) - 1), values[:-1]))
    intercept, phi = np.linalg.lstsq(design, values[1:], rcond=None)[0]
    return float(intercept), float(np.clip(phi, -0.99, 0.99))


def ar1_horizon_location(last_return: float, *, intercept: float, phi: float,
                         horizon: int) -> float:
    if horizon not in HORIZONS or not all(math.isfinite(v) for v in (last_return, intercept, phi)):
        raise ValueError("finite AR1 inputs and registered horizon are required")
    current = float(last_return)
    total = 0.0
    for _ in range(horizon):
        current = intercept + phi * current
        total += current
    return total


def f_location_samples(e0: Iterable[float], *, forecast_location: float, delta: float) -> np.ndarray:
    values = np.asarray(tuple(e0), dtype=np.float64)
    if (values.ndim != 1 or not len(values) or not np.isfinite(values).all()
            or not math.isfinite(forecast_location) or delta not in F_DELTA_GRID):
        raise ValueError("finite E0 and preregistered F-tier delta are required")
    if delta == 0.0:
        return values.copy()
    return values + delta * forecast_location


def mixture_quantiles(models: Sequence[np.ndarray], weights: Sequence[float]) -> tuple[float, ...]:
    if len(models) != len(weights) or not models:
        raise ValueError("model samples and weights must be aligned")
    checked = [np.asarray(values, dtype=np.float64) for values in models]
    mass = np.asarray(weights, dtype=np.float64)
    if (not np.isfinite(mass).all() or np.any(mass < 0) or
            not np.isclose(mass.sum(), 1.0, atol=1e-10)):
        raise ValueError("mixture weights must be nonnegative and sum to one")
    values = np.concatenate(checked)
    masses = np.concatenate([np.full(len(values_i), weight / len(values_i))
                             for values_i, weight in zip(checked, mass, strict=True)])
    order = np.argsort(values, kind="mergesort")
    values, cumulative = values[order], np.cumsum(masses[order])
    return tuple(float(values[min(int(np.searchsorted(cumulative, probability, side="left")),
                                  len(values) - 1)]) for probability in QUANTILE_GRID)


def _read_summary(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_models(*, origin: str, horizon: int, label: dict[str, Any],
                  runtime: dict[str, Any], grouped: dict[int, list[dict[str, Any]]],
                  events: list[dict[str, str]], params: dict[str, Any]) -> list[np.ndarray]:
    e0 = _eligible(grouped, origin, horizon)
    sigma_hat = _scale(runtime, origin, horizon)
    pool = runtime["pools"][horizon]
    e1 = e1_fhs_samples(e0, center=pool["center"], sigma_hat=sigma_hat,
                        standardized_residuals=pool["z"])
    e2 = rescale_e0_samples(e0, sigma_hat=sigma_hat, exponent=params["lambda"][horizon])
    flags = event_flags(events, origin=origin, label_end=str(label["label_end_session"]))
    e3 = event_multiplier_samples(e0, flags=flags, gammas=params["gammas"][horizon])
    e4 = t_tail_blend_samples(e0, sigma_hat=sigma_hat,
                              degrees_of_freedom=params["df"][horizon],
                              pi=params["pi"][horizon])
    index = runtime["index"][origin]
    location = ar1_horizon_location(runtime["returns"][index], intercept=params["ar1"][0],
                                    phi=params["ar1"][1], horizon=horizon)
    f_location = f_location_samples(e0, forecast_location=location,
                                    delta=params["f_delta"][horizon])
    return [e0, e1, e2, e3, e4, f_location]


def run_stacking_reassessment(export_path: Path, *, m5_dir: Path, m2_summary: Path,
                              m3_summary: Path, m4_summary: Path, calendar_path: Path,
                              registered_e0_matrix: Path, output_dir: Path) -> dict[str, Any]:
    raw = export_path.read_bytes()
    export = json.loads(raw)
    plan, roles = export["five_role_plan"], export["five_role_plan"]["role_origins"]
    if plan.get("outer_exposed_during_screen") is not False:
        raise ValueError("outer role must remain sealed")
    runtime = _load_runtime(export, m5_dir)
    grouped, lookup = _label_inputs(export)
    events = load_event_calendar(calendar_path)
    m2, m3, m4 = (_read_summary(path) for path in (m2_summary, m3_summary, m4_summary))
    train_end = runtime["index"][max(roles["train"])]
    ar1 = fit_ar1(runtime["returns"][1:train_end + 1])
    params: dict[str, Any] = {
        "lambda": {h: float(m2["horizons"][str(h)]["selected_lambda"]) for h in HORIZONS},
        "gammas": {h: tuple(float(m3["horizons"][str(h)]["gammas"][kind])
                             for kind in ("fomc", "cpi", "nfp")) for h in HORIZONS},
        "df": {h: float(m4["horizons"][str(h)]["degrees_of_freedom"]) for h in HORIZONS},
        "pi": {h: float(m4["horizons"][str(h)]["selected_pi"]) for h in HORIZONS},
        "ar1": ar1, "f_delta": {},
    }

    selection_rows: list[dict[str, Any]] = []
    for horizon in HORIZONS:
        for origin in roles["selection"]:
            label = lookup[(origin, horizon)]
            e0 = _eligible(grouped, origin, horizon)
            index = runtime["index"][origin]
            location = ar1_horizon_location(runtime["returns"][index], intercept=ar1[0],
                                            phi=ar1[1], horizon=horizon)
            for delta in F_DELTA_GRID:
                candidate = f_location_samples(e0, forecast_location=location, delta=delta)
                selection_rows.append({"role": "selection", "origin_session": origin,
                                       "horizon": horizon, "delta": delta,
                                       "crps": empirical_crps(candidate, float(label["value"]))})
        frame = pd.DataFrame(row for row in selection_rows if row["horizon"] == horizon)
        params["f_delta"][horizon] = float(frame.groupby("delta")["crps"].mean().idxmin())

    score_rows: list[dict[str, Any]] = []
    horizons: dict[str, Any] = {}
    for horizon in HORIZONS:
        stack_models: list[list[np.ndarray]] = [[] for _ in FAMILY_NAMES]
        stack_actuals: list[float] = []
        for origin in roles["stacking"]:
            label = lookup[(origin, horizon)]
            models = _build_models(origin=origin, horizon=horizon, label=label, runtime=runtime,
                                   grouped=grouped, events=events, params=params)
            for target, values in zip(stack_models, models, strict=True):
                target.append(values)
            stack_actuals.append(float(label["value"]))
        fitted = optimize_empirical_mixture(stack_models, stack_actuals,
                                            e0_floor=E0_FLOORS[horizon])
        weights = tuple(float(value) for value in fitted.weights)

        calibration_models: list[list[np.ndarray]] = [[] for _ in FAMILY_NAMES]
        calibration_actuals: list[float] = []
        cases: list[CalibrationCase] = []
        provisional: list[dict[str, Any]] = []
        for origin in roles["calibration"]:
            label = lookup[(origin, horizon)]
            models = _build_models(origin=origin, horizon=horizon, label=label, runtime=runtime,
                                   grouped=grouped, events=events, params=params)
            actual = float(label["value"])
            component_scores = [empirical_crps(values, actual) for values in models]
            for target, values in zip(calibration_models, models, strict=True):
                target.append(values)
            calibration_actuals.append(actual)
            mixture_score = empirical_mixture_crps([[values] for values in models], [actual], weights)
            quantiles = mixture_quantiles(models, weights)
            cases.append(CalibrationCase(origin, "calibration", quantiles, actual))
            provisional.append({
                "origin_session": origin, "horizon": horizon, "role": "calibration",
                "actual": actual, "e0_crps": component_scores[0],
                "stacked_crps": mixture_score,
                "paired_advantage": component_scores[0] - mixture_score,
                **{f"{name}_crps": score for name, score in
                   zip(FAMILY_NAMES[1:], component_scores[1:], strict=True)},
            })
        calibrated = cross_fit_quantiles(cases)
        for row in provisional:
            quantiles = calibrated[row["origin_session"]]
            row.update({"p10": quantiles[1], "p25": quantiles[4], "p50": quantiles[9],
                        "p75": quantiles[14], "p90": quantiles[17]})
            score_rows.append(row)

        component_diagnostics: dict[str, Any] = {}
        for name in FAMILY_NAMES[1:]:
            advantages = np.asarray([row["e0_crps"] - row[f"{name}_crps"]
                                     for row in provisional], dtype=np.float64)
            e0_mean = float(np.mean([row["e0_crps"] for row in provisional]))
            component_diagnostics[name] = {
                "calibration_mean_advantage": float(np.mean(advantages)),
                "calibration_skill": float(np.mean(advantages) / e0_mean),
                "positive_oos_advantage": bool(float(np.mean(advantages)) > 1e-12),
                "final_weight": weights[FAMILY_NAMES.index(name)],
            }
        horizons[str(horizon)] = {
            "weights": dict(zip(FAMILY_NAMES, weights, strict=True)),
            "e0_floor": E0_FLOORS[horizon], "stacking_crps": fitted.crps,
            "stacking_e0_only_fallback": fitted.used_e0_only_fallback,
            "component_diagnostics": component_diagnostics,
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
        lambda coordinate: f_location_samples(coordinate.values, forecast_location=99.0, delta=0.0),
        tolerance=1e-12,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(selection_rows).to_parquet(output_dir / "f_location_selection_scores.parquet",
                                            index=False)
    pd.DataFrame(score_rows).to_parquet(output_dir / "calibration_paired_scores.parquet", index=False)
    summary = {
        "schema": "r5_s1_stacking_reassessment_v1", "families": list(FAMILY_NAMES),
        "f_tier": {"approved": True, "delta_grid": list(F_DELTA_GRID),
                   "selected_delta": {str(h): params["f_delta"][h] for h in HORIZONS},
                   "ar1_fit_role": "train", "ar1_intercept": ar1[0], "ar1_phi": ar1[1],
                   "nesting_proof": nesting},
        "horizons": horizons, "role_hashes": plan["role_hashes"],
        "row_use_counters": {"train_rows_used": train_end,
                             "selection_rows_used": len(roles["selection"]) * 4,
                             "stacking_rows_used": len(roles["stacking"]) * 4,
                             "calibration_rows_used": len(roles["calibration"]) * 4,
                             "outer_rows_used": 0},
        "input_sha256": hashlib.sha256(raw).hexdigest(),
        "method": {"weight_fit_role": "stacking", "qualification_role": "calibration",
                   "empirical_mixture_crps": "exact including cross-model distances",
                   "stationary_bootstrap_replications": 2000, "mean_block_length": "2*h"},
    }
    (output_dir / "stacking_summary.json").write_bytes(canonical_json(summary) + b"\n")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", type=Path, required=True)
    parser.add_argument("--m5-dir", type=Path, required=True)
    parser.add_argument("--m2-summary", type=Path, required=True)
    parser.add_argument("--m3-summary", type=Path, required=True)
    parser.add_argument("--m4-summary", type=Path, required=True)
    parser.add_argument("--calendar", type=Path, required=True)
    parser.add_argument("--registered-e0-matrix", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    run_stacking_reassessment(args.export, m5_dir=args.m5_dir,
                              m2_summary=args.m2_summary, m3_summary=args.m3_summary,
                              m4_summary=args.m4_summary, calendar_path=args.calendar,
                              registered_e0_matrix=args.registered_e0_matrix,
                              output_dir=args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
