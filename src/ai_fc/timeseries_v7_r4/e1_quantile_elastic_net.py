"""E1 point-in-time direct-horizon quantile elastic-net correction expert."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
from scipy.optimize import minimize


CANONICAL_HORIZONS = (1, 5, 21, 63)


@dataclass(frozen=True)
class E1Contract:
    horizons: tuple[int, ...] = CANONICAL_HORIZONS
    quantiles: tuple[float, ...] = (0.1, 0.25, 0.5, 0.75, 0.9)
    alpha: float = 0.01
    l1_ratio: float = 0.5
    correction_bound_k: float = 1.0
    stability_subsamples: int = 4
    stability_min_sign_agreement: float = 0.6
    min_training_rows: int = 12

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "E1Contract":
        result = cls(
            horizons=tuple(int(v) for v in value.get("horizons", CANONICAL_HORIZONS)),
            quantiles=tuple(float(v) for v in value.get("quantiles", cls.quantiles)),
            alpha=float(value.get("alpha", cls.alpha)),
            l1_ratio=float(value.get("l1_ratio", cls.l1_ratio)),
            correction_bound_k=float(value.get("correction_bound_k", cls.correction_bound_k)),
            stability_subsamples=int(value.get("stability_subsamples", cls.stability_subsamples)),
            stability_min_sign_agreement=float(value.get(
                "stability_min_sign_agreement", cls.stability_min_sign_agreement,
            )),
            min_training_rows=int(value.get("min_training_rows", cls.min_training_rows)),
        )
        result.validate()
        return result

    def validate(self) -> None:
        if self.horizons != CANONICAL_HORIZONS:
            raise ValueError("E1 direct horizons must be exactly 1, 5, 21, 63")
        if not self.quantiles or any(not 0.0 < q < 1.0 for q in self.quantiles):
            raise ValueError("quantiles must be unique probabilities inside (0, 1)")
        if tuple(sorted(set(self.quantiles))) != self.quantiles:
            raise ValueError("quantiles must be strictly increasing")
        if self.alpha < 0.0 or not 0.0 <= self.l1_ratio <= 1.0:
            raise ValueError("alpha and l1_ratio are outside the elastic-net contract")
        if self.correction_bound_k <= 0.0:
            raise ValueError("correction_bound_k must be positive")
        if self.stability_subsamples < 2 or not 0.0 <= self.stability_min_sign_agreement <= 1.0:
            raise ValueError("invalid stability contract")
        if self.min_training_rows < 4:
            raise ValueError("min_training_rows must be at least four")


@dataclass(frozen=True)
class E1Model:
    horizons: tuple[int, ...]
    quantiles: tuple[float, ...]
    coefficients: Mapping[tuple[int, float], tuple[float, ...]]
    intercepts: Mapping[tuple[int, float], float]
    feature_center: tuple[float, ...]
    feature_scale: tuple[float, ...]
    correction_bound: float
    diagnostics: Mapping[str, Any]

    def predict_corrections(self, features: Sequence[float]) -> dict[int, dict[float, float]]:
        values = np.asarray(features, dtype=float)
        if values.shape != (len(self.feature_center),) or not np.isfinite(values).all():
            raise ValueError("finite features with the fitted width are required")
        standardized = (values - np.asarray(self.feature_center)) / np.asarray(self.feature_scale)
        result: dict[int, dict[float, float]] = {}
        for horizon in self.horizons:
            raw = np.asarray([
                self.intercepts[(horizon, q)]
                + np.dot(self.coefficients[(horizon, q)], standardized)
                for q in self.quantiles
            ])
            # Crossing protection is a display/prediction-boundary projection; no
            # stored training label or fitted coefficient is rewritten.
            bounded = np.clip(np.maximum.accumulate(raw), -self.correction_bound,
                              self.correction_bound)
            result[horizon] = {q: float(v) for q, v in zip(self.quantiles, bounded, strict=True)}
        return result


def _fit(x: np.ndarray, y: np.ndarray, quantile: float,
         alpha: float, l1_ratio: float) -> tuple[float, np.ndarray]:
    initial = np.r_[float(np.quantile(y, quantile)), np.zeros(x.shape[1])]

    def objective(parameters: np.ndarray) -> tuple[float, np.ndarray]:
        residual = y - parameters[0] - x @ parameters[1:]
        loss = np.where(residual >= 0.0, quantile * residual,
                        (quantile - 1.0) * residual).mean()
        weights = parameters[1:]
        penalty = alpha * (l1_ratio * np.abs(weights).sum()
                           + 0.5 * (1.0 - l1_ratio) * np.dot(weights, weights))
        derivative = np.where(residual > 0.0, -quantile,
                              np.where(residual < 0.0, 1.0 - quantile, 0.0))
        gradient = np.r_[derivative.mean(), x.T @ derivative / len(y)]
        gradient[1:] += alpha * (l1_ratio * np.sign(weights)
                                 + (1.0 - l1_ratio) * weights)
        return float(loss + penalty), gradient

    fitted = minimize(objective, initial, jac=True, method="L-BFGS-B",
                      options={"maxiter": 500, "ftol": 1e-12})
    if not fitted.success or not np.isfinite(fitted.x).all():
        raise RuntimeError(f"E1 quantile optimization failed: {fitted.message}")
    return float(fitted.x[0]), np.asarray(fitted.x[1:], dtype=float)


def fit_e1_direct_quantile_elastic_net(*, rows: Iterable[Mapping[str, Any]],
                                       as_of: str, e0_scale: float,
                                       contract: E1Contract) -> E1Model:
    """Fit all direct targets using only rows available at the frozen ``as_of``."""
    contract.validate()
    if not as_of or not np.isfinite(e0_scale) or e0_scale <= 0.0:
        raise ValueError("a positive E0 scale and explicit as_of are required")
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

    x = np.asarray([row["features"] for row in eligible], dtype=float)
    if x.ndim != 2 or x.shape[1] == 0 or not np.isfinite(x).all():
        raise ValueError("finite rectangular feature rows are required")
    center = np.median(x, axis=0)
    scale = np.quantile(x, 0.75, axis=0) - np.quantile(x, 0.25, axis=0)
    scale = np.where(scale > 1e-12, scale, 1.0)
    standardized = (x - center) / scale

    coefficients: dict[tuple[int, float], tuple[float, ...]] = {}
    intercepts: dict[tuple[int, float], float] = {}
    stability: list[float] = []
    for horizon in contract.horizons:
        try:
            y = np.asarray([row["targets"][str(horizon)] for row in eligible], dtype=float)
        except (KeyError, TypeError) as error:
            raise ValueError(f"missing direct target for horizon {horizon}") from error
        if not np.isfinite(y).all():
            raise ValueError("direct targets must be finite fractions")
        for quantile in contract.quantiles:
            intercept, weights = _fit(standardized, y, quantile,
                                      contract.alpha, contract.l1_ratio)
            key = (horizon, quantile)
            intercepts[key] = intercept
            coefficients[key] = tuple(float(v) for v in weights)
            signs = []
            for subset in np.array_split(np.arange(len(y)), contract.stability_subsamples):
                keep = np.setdiff1d(np.arange(len(y)), subset)
                _, subset_weights = _fit(standardized[keep], y[keep], quantile,
                                         contract.alpha, contract.l1_ratio)
                signs.append(np.sign(subset_weights))
            sign_array = np.asarray(signs)
            majority = np.sign(sign_array.sum(axis=0))
            agreement = np.mean(sign_array == majority, axis=0)
            stability.append(float(np.mean(agreement)))

    minimum_stability = min(stability)
    hyperparameters = {
        "alpha": contract.alpha, "l1_ratio": contract.l1_ratio,
        "quantiles": list(contract.quantiles), "horizons": list(contract.horizons),
        "correction_bound_k": contract.correction_bound_k,
        "stability_subsamples": contract.stability_subsamples,
        "stability_min_sign_agreement": contract.stability_min_sign_agreement,
        "min_training_rows": contract.min_training_rows,
    }
    bound = contract.correction_bound_k * e0_scale
    diagnostics = {
        "eligible_rows": len(eligible), "excluded_post_as_of_rows": excluded,
        "as_of": as_of, "e0_scale": e0_scale, "correction_bound": bound,
        "minimum_sign_agreement": minimum_stability,
        "stable": minimum_stability >= contract.stability_min_sign_agreement,
        "hyperparameters": hyperparameters,
    }
    return E1Model(contract.horizons, contract.quantiles, coefficients, intercepts,
                   tuple(center), tuple(scale), bound, diagnostics)
