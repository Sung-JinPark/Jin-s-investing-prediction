"""PIT-safe HAR, EWMA, and Student-t GARCH scale-source selection for R5."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import gammaln


HORIZONS = (1, 5, 21, 63)
HAR_ALPHAS = (0.0, 1e-4, 1e-3)
EWMA_ALPHAS = (0.94, 0.97)


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rv_features(returns: np.ndarray, index: int) -> np.ndarray:
    if index < 21:
        raise ValueError("at least 21 return observations are required")
    values = []
    for window in (1, 5, 21):
        rv = 252.0 / window * float(np.sum(returns[index - window + 1:index + 1] ** 2))
        values.append(math.log(max(rv, 1e-14)))
    return np.asarray([1.0, *values], dtype=float)


@dataclass(frozen=True)
class HarFit:
    horizon: int
    alpha: float
    coefficients: tuple[float, ...]
    residual_variance: float

    def forecast(self, feature: np.ndarray) -> float:
        log_variance = float(feature @ np.asarray(self.coefficients)) + self.residual_variance / 2.0
        return math.sqrt(max(math.exp(log_variance), 1e-14))


def fit_har(features: np.ndarray, targets: np.ndarray, *, horizon: int, alpha: float) -> HarFit:
    if len(features) != len(targets) or len(targets) < 100:
        raise ValueError("HAR requires at least 100 aligned research_train rows")
    penalty = np.diag([0.0, 1.0, 1.0, 1.0]) * alpha
    coefficients = np.linalg.solve(features.T @ features + penalty, features.T @ np.log(targets))
    residuals = np.log(targets) - features @ coefficients
    return HarFit(horizon, alpha, tuple(float(value) for value in coefficients),
                  float(np.mean(residuals ** 2)))


@dataclass(frozen=True)
class GarchTFit:
    omega: float
    alpha: float
    beta: float
    degrees_of_freedom: float
    initial_variance: float


def fit_garch_t(returns: np.ndarray) -> GarchTFit:
    scaled = np.asarray(returns, dtype=float) * 100.0
    if len(scaled) < 500 or not np.isfinite(scaled).all():
        raise ValueError("GARCH-t requires at least 500 finite research_train returns")
    initial_variance = float(np.var(scaled, ddof=1))

    def objective(theta: np.ndarray) -> float:
        omega, alpha, beta, nu = (float(value) for value in theta)
        if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 0.999 or nu <= 2.0:
            return 1e100
        variance = initial_variance
        loss = 0.0
        constant = gammaln((nu + 1.0) / 2.0) - gammaln(nu / 2.0) - 0.5 * math.log((nu - 2.0) * math.pi)
        for value in scaled:
            variance = max(variance, 1e-12)
            z2 = value * value / variance
            loss -= constant - 0.5 * math.log(variance) - (nu + 1.0) / 2.0 * math.log1p(z2 / (nu - 2.0))
            variance = omega + alpha * value * value + beta * variance
        return float(loss)

    result = minimize(
        objective,
        np.asarray([initial_variance * 0.02, 0.07, 0.90, 8.0]),
        method="SLSQP",
        bounds=[(1e-10, initial_variance * 2.0), (1e-6, 0.4), (0.05, 0.998), (2.1, 30.0)],
        constraints={"type": "ineq", "fun": lambda theta: 0.999 - theta[1] - theta[2]},
        options={"maxiter": 1000, "ftol": 1e-9},
    )
    if not result.success or not np.isfinite(result.fun):
        raise RuntimeError(f"GARCH-t MLE failed: {result.message}")
    omega, alpha, beta, nu = (float(value) for value in result.x)
    return GarchTFit(omega, alpha, beta, nu, initial_variance)


def _garch_variance_path(returns: np.ndarray, fit: GarchTFit) -> np.ndarray:
    scaled = np.asarray(returns, dtype=float) * 100.0
    values = np.empty(len(scaled), dtype=float)
    variance = fit.initial_variance
    for index, value in enumerate(scaled):
        values[index] = variance
        variance = fit.omega + fit.alpha * value * value + fit.beta * variance
    return values


def _garch_scale(returns: np.ndarray, variances: np.ndarray, index: int,
                 horizon: int, fit: GarchTFit) -> float:
    value = returns[index] * 100.0
    next_variance = fit.omega + fit.alpha * value * value + fit.beta * variances[index]
    persistence = fit.alpha + fit.beta
    long_run = fit.omega / (1.0 - persistence)
    total = horizon * long_run + (next_variance - long_run) * (1.0 - persistence ** horizon) / (1.0 - persistence)
    return math.sqrt(max(total, 1e-12) / 10000.0)


def _ewma_paths(returns: np.ndarray) -> dict[float, np.ndarray]:
    result: dict[float, np.ndarray] = {}
    seed = float(np.var(returns[: min(252, len(returns))], ddof=1))
    for alpha in EWMA_ALPHAS:
        path = np.empty(len(returns), dtype=float)
        variance = seed
        for index, value in enumerate(returns):
            variance = alpha * variance + (1.0 - alpha) * value * value
            path[index] = variance
        result[alpha] = path
    return result


def _crps_scaled(sorted_samples: np.ndarray, actual: float, target_scale: float) -> float:
    mean = float(np.mean(sorted_samples))
    base_scale = float(np.std(sorted_samples, ddof=1))
    if base_scale <= 0 or target_scale <= 0:
        raise ValueError("scale forecasts and empirical dispersion must be positive")
    ratio = target_scale / base_scale
    candidate = mean + ratio * (sorted_samples - mean)
    count = len(candidate)
    coefficients = 2 * np.arange(1, count + 1) - count - 1
    return float(np.mean(np.abs(candidate - actual)) - np.sum(coefficients * candidate) / (count * count))


def _eligible(labels: dict[int, list[dict[str, Any]]], origin: str, horizon: int) -> np.ndarray:
    values = [float(row["value"]) for row in labels[horizon]
              if row["origin_session"] < origin and str(row["mature_at"])[:10] <= origin]
    if not values:
        raise ValueError(f"no mature E0 labels at {origin}:h{horizon}")
    return np.sort(np.asarray(values, dtype=float))


def _forecast_source(source: str, *, horizon: int, index: int, feature: np.ndarray,
                     har: dict[tuple[int, float], HarFit], ewma: dict[float, np.ndarray],
                     returns: np.ndarray, garch_path: np.ndarray, garch: GarchTFit) -> float:
    if source.startswith("har_"):
        return har[(horizon, float(source.removeprefix("har_")))].forecast(feature)
    if source.startswith("ewma_"):
        return math.sqrt(float(ewma[float(source.removeprefix("ewma_"))][index]) * horizon)
    if source == "garch_t":
        return _garch_scale(returns, garch_path, index, horizon, garch)
    raise ValueError(f"unknown scale source: {source}")


def _mature_training_labels(label_lookup: dict[tuple[str, int], dict[str, Any]],
                            train_origins: set[str], horizon: int) -> list[dict[str, Any]]:
    """Return only labels observable by the final frozen training origin."""
    cutoff = max(train_origins)
    return [label_lookup[(origin, horizon)] for origin in sorted(train_origins)
            if (origin, horizon) in label_lookup
            and str(label_lookup[(origin, horizon)]["mature_at"])[:10] <= cutoff]


def run_scale_selection(export_path: Path, output_dir: Path) -> dict[str, Any]:
    raw = export_path.read_bytes()
    export = json.loads(raw)
    plan = export["five_role_plan"]
    train_origins = set(plan["role_origins"]["train"])
    selection_origins = set(plan["role_origins"]["selection"])
    outer_origins = set(plan["role_origins"]["outer"])
    if train_origins & selection_origins or outer_origins & (train_origins | selection_origins):
        raise ValueError("five-role origins overlap")

    frame = pd.DataFrame(export["feature_rows"])[["origin_session", "price", "origin_cutoff_at"]].copy()
    frame = frame.sort_values("origin_session").reset_index(drop=True)
    prices = frame["price"].to_numpy(dtype=float)
    returns = np.zeros(len(prices), dtype=float)
    returns[1:] = np.diff(np.log(prices))
    index_by_origin = {value: index for index, value in enumerate(frame["origin_session"])}
    labels_by_horizon = {horizon: [] for horizon in HORIZONS}
    label_lookup: dict[tuple[str, int], dict[str, Any]] = {}
    for row in export["labels"]:
        horizon = int(row["horizon_sessions"])
        if horizon in labels_by_horizon:
            labels_by_horizon[horizon].append(row)
            label_lookup[(row["origin_session"], horizon)] = row

    har: dict[tuple[int, float], HarFit] = {}
    for horizon in HORIZONS:
        features, targets = [], []
        for origin in sorted(train_origins):
            index = index_by_origin[origin]
            if index < 21 or index + horizon >= len(returns):
                continue
            label = label_lookup.get((origin, horizon))
            if label is None or str(label["mature_at"])[:10] > max(train_origins):
                continue
            features.append(_rv_features(returns, index))
            targets.append(max(float(np.sum(returns[index + 1:index + horizon + 1] ** 2)), 1e-14))
        feature_array, target_array = np.asarray(features), np.asarray(targets)
        for alpha in HAR_ALPHAS:
            har[(horizon, alpha)] = fit_har(feature_array, target_array, horizon=horizon, alpha=alpha)

    train_indices = [index_by_origin[origin] for origin in sorted(train_origins)]
    garch = fit_garch_t(returns[min(train_indices):max(train_indices) + 1])
    garch_path = _garch_variance_path(returns, garch)
    ewma = _ewma_paths(returns)
    sources = tuple([f"har_{alpha}" for alpha in HAR_ALPHAS]
                    + [f"ewma_{alpha}" for alpha in EWMA_ALPHAS] + ["garch_t"])

    score_rows: list[dict[str, Any]] = []
    for origin in sorted(selection_origins):
        index = index_by_origin[origin]
        feature = _rv_features(returns, index)
        for horizon in HORIZONS:
            actual_row = label_lookup.get((origin, horizon))
            if actual_row is None:
                raise ValueError(f"missing selection label {origin}:h{horizon}")
            e0 = _eligible(labels_by_horizon, origin, horizon)
            for source in sources:
                scale = _forecast_source(source, horizon=horizon, index=index, feature=feature,
                                         har=har, ewma=ewma, returns=returns,
                                         garch_path=garch_path, garch=garch)
                score_rows.append({
                    "origin_session": origin, "horizon_sessions": horizon, "source": source,
                    "sigma_hat": scale, "actual": float(actual_row["value"]),
                    "crps": _crps_scaled(e0, float(actual_row["value"]), scale),
                    "role": "selection",
                })
    scores = pd.DataFrame(score_rows)
    means = scores.groupby(["horizon_sessions", "source"], sort=True)["crps"].mean()
    selected = {str(horizon): str(means.loc[horizon].idxmin()) for horizon in HORIZONS}

    pools: dict[str, Any] = {}
    for horizon in HORIZONS:
        source = selected[str(horizon)]
        mature_labels = _mature_training_labels(label_lookup, train_origins, horizon)
        training_values = [float(label["value"]) for label in mature_labels]
        center = float(np.mean(training_values))
        mature_by_origin = {str(label["origin_session"]): label for label in mature_labels}
        residual_rows = []
        for origin in sorted(train_origins):
            label = mature_by_origin.get(origin)
            index = index_by_origin[origin]
            if label is None or index < 21:
                continue
            scale = _forecast_source(source, horizon=horizon, index=index,
                                     feature=_rv_features(returns, index), har=har, ewma=ewma,
                                     returns=returns, garch_path=garch_path, garch=garch)
            residual_rows.append({"origin_session": origin, "z": (float(label["value"]) - center) / scale})
        pools[str(horizon)] = {"selected_source": source, "center": center, "rows": residual_rows}

    output_dir.mkdir(parents=True, exist_ok=True)
    scores.to_parquet(output_dir / "selection_scale_scores.parquet", index=False)
    model_receipt = {
        "schema": "r5_conditional_scale_models_v1",
        "har": {f"h{horizon}:alpha={alpha}": {
            "coefficients": list(fit.coefficients), "residual_variance": fit.residual_variance,
        } for (horizon, alpha), fit in har.items()},
        "ewma_alphas": list(EWMA_ALPHAS),
        "garch_t": garch.__dict__,
        "fit_role": "train", "selection_role": "selection",
        "input_sha256": hashlib.sha256(raw).hexdigest(),
        "role_hashes": plan["role_hashes"],
    }
    (output_dir / "conditional_scale_models.json").write_bytes(canonical_json(model_receipt) + b"\n")
    (output_dir / "standardized_residual_pool.json").write_bytes(canonical_json({
        "schema": "r5_frozen_standardized_residual_pool_v1", "pools": pools,
        "fit_role": "train", "selected_on_role": "selection",
    }) + b"\n")
    summary = {
        "schema": "r5_m5_scale_selection_v1", "selected_sources": selected,
        "mean_crps": {str(horizon): {source: float(means.loc[(horizon, source)]) for source in sources}
                      for horizon in HORIZONS},
        "source_families": ["HAR-direct", "EWMA", "GARCH(1,1)-t"],
        "train_origin_count": len(train_origins), "selection_origin_count": len(selection_origins),
        "selection_score_rows": len(score_rows), "pit_violations": 0,
        "standardized_pool_rows": {horizon: len(value["rows"]) for horizon, value in pools.items()},
        "row_use_counters": {"train_rows_used": len(train_origins) * len(HORIZONS),
                             "selection_rows_used": len(selection_origins) * len(HORIZONS),
                             "stacking_rows_used": 0, "calibration_rows_used": 0,
                             "outer_rows_used": 0},
    }
    (output_dir / "selection_summary.json").write_bytes(canonical_json(summary) + b"\n")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    run_scale_selection(args.export, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
