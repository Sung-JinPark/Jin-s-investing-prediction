"""E2 point-in-time Student-t location-scale distributional regression."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
from scipy.optimize import minimize
from scipy.special import gammaln


CANONICAL_HORIZONS = (1, 5, 21, 63)


@dataclass(frozen=True)
class E2Contract:
    horizons: tuple[int, ...] = CANONICAL_HORIZONS
    degrees_of_freedom: tuple[float, ...] = (3.0, 5.0, 8.0, 12.0)
    alpha_grid: tuple[float, ...] = (0.01, 0.1, 1.0)
    cross_fit_folds: int = 5
    min_training_rows: int = 20

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "E2Contract":
        result = cls(
            horizons=tuple(int(v) for v in value.get("horizons", CANONICAL_HORIZONS)),
            degrees_of_freedom=tuple(float(v) for v in value.get(
                "degrees_of_freedom", cls.degrees_of_freedom,
            )),
            alpha_grid=tuple(float(v) for v in value.get("alpha_grid", cls.alpha_grid)),
            cross_fit_folds=int(value.get("cross_fit_folds", cls.cross_fit_folds)),
            min_training_rows=int(value.get("min_training_rows", cls.min_training_rows)),
        )
        result.validate()
        return result

    def validate(self) -> None:
        if self.horizons != CANONICAL_HORIZONS:
            raise ValueError("E2 direct horizons must be exactly 1, 5, 21, 63")
        if (not self.degrees_of_freedom
                or any(not np.isfinite(v) or v <= 2.0 for v in self.degrees_of_freedom)):
            raise ValueError("degrees_of_freedom must be finite and greater than two")
        if len(set(self.degrees_of_freedom)) != len(self.degrees_of_freedom):
            raise ValueError("degrees_of_freedom grid must be unique")
        if not self.alpha_grid or any(not np.isfinite(v) or v < 0.0 for v in self.alpha_grid):
            raise ValueError("alpha_grid must contain finite nonnegative values")
        if len(set(self.alpha_grid)) != len(self.alpha_grid):
            raise ValueError("alpha_grid must be unique")
        if self.cross_fit_folds < 2:
            raise ValueError("cross_fit_folds must be at least two")
        if self.min_training_rows < 8 or self.cross_fit_folds >= self.min_training_rows:
            raise ValueError("invalid min_training_rows/cross_fit_folds contract")


@dataclass(frozen=True)
class E2Model:
    horizons: tuple[int, ...]
    degrees_of_freedom: Mapping[int, float]
    alpha: Mapping[int, float]
    location_coefficients: Mapping[int, tuple[float, ...]]
    log_scale_coefficients: Mapping[int, tuple[float, ...]]
    feature_center: tuple[float, ...]
    feature_scale: tuple[float, ...]
    diagnostics: Mapping[str, Any]

    def predict(self, features: Sequence[float]) -> dict[int, dict[str, float]]:
        values = np.asarray(features, dtype=float)
        if values.shape != (len(self.feature_center),) or not np.isfinite(values).all():
            raise ValueError("finite features with the fitted width are required")
        x = (values - np.asarray(self.feature_center)) / np.asarray(self.feature_scale)
        design = np.r_[1.0, x]
        return {
            horizon: {
                "location": float(design @ self.location_coefficients[horizon]),
                "scale": float(np.exp(np.clip(
                    design @ self.log_scale_coefficients[horizon], -30.0, 30.0,
                ))),
                "degrees_of_freedom": self.degrees_of_freedom[horizon],
            }
            for horizon in self.horizons
        }


def _ridge(design: np.ndarray, target: np.ndarray, alpha: float) -> np.ndarray:
    penalty = np.eye(design.shape[1]) * alpha
    penalty[0, 0] = 0.0
    return np.linalg.solve(design.T @ design + penalty, design.T @ target)


def _cross_fitted_residuals(design: np.ndarray, target: np.ndarray, folds: int,
                            alpha: float) -> np.ndarray:
    residuals = np.empty(len(target), dtype=float)
    indices = np.arange(len(target))
    for held_out in np.array_split(indices, folds):
        train = np.setdiff1d(indices, held_out, assume_unique=True)
        coefficients = _ridge(design[train], target[train], alpha)
        residuals[held_out] = target[held_out] - design[held_out] @ coefficients
    return residuals


def _joint_fit(design: np.ndarray, target: np.ndarray, residuals: np.ndarray,
               degrees_of_freedom: float, alpha: float) -> tuple[np.ndarray, np.ndarray, float]:
    width = design.shape[1]
    location = _ridge(design, target, alpha)
    floor = max(float(np.median(np.abs(residuals))) * 1e-3, 1e-10)
    log_scale_target = np.log(np.maximum(np.abs(residuals), floor))
    log_scale = _ridge(design, log_scale_target, alpha)
    initial = np.r_[location, log_scale]
    constant = (gammaln((degrees_of_freedom + 1.0) / 2.0)
                - gammaln(degrees_of_freedom / 2.0)
                - 0.5 * np.log(degrees_of_freedom * np.pi))

    def objective(parameters: np.ndarray) -> tuple[float, np.ndarray]:
        loc = design @ parameters[:width]
        log_s = design @ parameters[width:]
        scale = np.exp(log_s)
        standardized = (target - loc) / scale
        nll = -constant + log_s + 0.5 * (degrees_of_freedom + 1.0) * np.log1p(
            standardized * standardized / degrees_of_freedom
        )
        denominator = degrees_of_freedom + standardized * standardized
        location_derivative = -(degrees_of_freedom + 1.0) * standardized / (
            scale * denominator
        )
        scale_derivative = 1.0 - (degrees_of_freedom + 1.0) * (
            standardized * standardized / denominator
        )
        gradient = np.r_[design.T @ location_derivative, design.T @ scale_derivative] / len(target)
        gradient[1:width] += alpha * parameters[1:width]
        gradient[width + 1:] += alpha * parameters[width + 1:]
        penalty = 0.5 * alpha * (
            np.dot(parameters[1:width], parameters[1:width])
            + np.dot(parameters[width + 1:], parameters[width + 1:])
        )
        return float(nll.mean() + penalty), gradient

    bounds = [(None, None)] * width + [(-30.0, 30.0)] * width
    fitted = minimize(objective, initial, jac=True, method="L-BFGS-B", bounds=bounds,
                      options={"maxiter": 5000, "ftol": 1e-12})
    if not fitted.success or not np.isfinite(fitted.x).all():
        raise RuntimeError(f"E2 Student-t optimization failed: {fitted.message}")
    return fitted.x[:width], fitted.x[width:], float(fitted.fun)


def fit_e2_student_t(*, rows: Iterable[Mapping[str, Any]], as_of: str,
                     contract: E2Contract) -> E2Model:
    """Fit direct horizons without using rows unavailable at ``as_of``."""
    contract.validate()
    if not as_of:
        raise ValueError("explicit as_of is required")
    eligible: list[Mapping[str, Any]] = []
    excluded = 0
    for row in rows:
        available_at = row.get("available_at")
        if available_at is None:
            raise ValueError("each training row requires explicit available_at")
        if str(available_at) > as_of:
            excluded += 1
        else:
            eligible.append(row)
    eligible.sort(key=lambda row: (str(row.get("origin_session", "")), str(row["available_at"])))
    if len(eligible) < contract.min_training_rows:
        raise ValueError("insufficient point-in-time eligible training rows")

    features = np.asarray([row["features"] for row in eligible], dtype=float)
    if features.ndim != 2 or features.shape[1] == 0 or not np.isfinite(features).all():
        raise ValueError("finite rectangular feature rows are required")
    center = np.median(features, axis=0)
    feature_scale = np.quantile(features, 0.75, axis=0) - np.quantile(features, 0.25, axis=0)
    feature_scale = np.where(feature_scale > 1e-12, feature_scale, 1.0)
    design = np.column_stack((np.ones(len(features)), (features - center) / feature_scale))

    locations: dict[int, tuple[float, ...]] = {}
    scales: dict[int, tuple[float, ...]] = {}
    selected_df: dict[int, float] = {}
    selected_alpha: dict[int, float] = {}
    selected_nll: dict[int, float] = {}
    evidence: list[dict[str, Any]] = []
    for horizon in contract.horizons:
        try:
            target = np.asarray([row["targets"][str(horizon)] for row in eligible], dtype=float)
        except (KeyError, TypeError) as error:
            raise ValueError(f"missing direct target for horizon {horizon}") from error
        if not np.isfinite(target).all():
            raise ValueError("direct targets must be finite fractions")
        residuals = _cross_fitted_residuals(
            design, target, contract.cross_fit_folds, min(contract.alpha_grid),
        )
        evidence.extend({"horizon": horizon, "row": index, "residual": float(value)}
                        for index, value in enumerate(residuals))
        candidates = []
        for df in contract.degrees_of_freedom:
            for alpha in contract.alpha_grid:
                loc, log_scale, nll = _joint_fit(design, target, residuals, df, alpha)
                candidates.append((nll, df, alpha, loc, log_scale))
        nll, df, alpha, loc, log_scale = min(candidates, key=lambda item: item[0])
        locations[horizon] = tuple(float(v) for v in loc)
        scales[horizon] = tuple(float(v) for v in log_scale)
        selected_df[horizon], selected_alpha[horizon], selected_nll[horizon] = df, alpha, nll

    evidence_bytes = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    diagnostics = {
        "objective": "joint_location_scale_student_t_nll",
        "searched_grid": {
            "degrees_of_freedom": list(contract.degrees_of_freedom),
            "alpha": list(contract.alpha_grid),
        },
        "selected_nll": selected_nll,
        "eligible_rows": len(eligible),
        "excluded_post_as_of_rows": excluded,
        "as_of": as_of,
        "scale_residual_evidence": {
            "kind": "cross_fitted", "folds": contract.cross_fit_folds,
            "row_count": len(evidence), "sha256": hashlib.sha256(evidence_bytes).hexdigest(),
        },
    }
    return E2Model(contract.horizons, selected_df, selected_alpha, locations, scales,
                   tuple(center), tuple(feature_scale), diagnostics)
