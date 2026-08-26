"""E4 point-in-time direct-horizon filtered dynamic linear model."""

from __future__ import annotations

from dataclasses import dataclass
import itertools
from typing import Any, Iterable, Mapping, Sequence

import numpy as np


CANONICAL_HORIZONS = (1, 5, 21, 63)


@dataclass(frozen=True)
class E4Contract:
    horizons: tuple[int, ...] = CANONICAL_HORIZONS
    state_order: tuple[int, ...] = (1, 2)
    process_variance_scale: tuple[float, ...] = (0.01, 0.1, 1.0)
    observation_variance_scale: tuple[float, ...] = (0.5, 1.0, 2.0)
    state_transition: float = 1.0
    process_variance: float = 1e-5
    observation_variance: float = 1e-3
    initial_covariance: float = 10.0
    min_training_rows: int = 250

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "E4Contract":
        result = cls(
            horizons=tuple(int(item) for item in value.get("horizons", CANONICAL_HORIZONS)),
            state_order=tuple(int(item) for item in value.get("state_order", (1, 2))),
            process_variance_scale=tuple(float(item) for item in value.get(
                "process_variance_scale", (0.01, 0.1, 1.0),
            )),
            observation_variance_scale=tuple(float(item) for item in value.get(
                "observation_variance_scale", (0.5, 1.0, 2.0),
            )),
            state_transition=float(value.get("state_transition", 1.0)),
            process_variance=float(value.get("process_variance", 1e-5)),
            observation_variance=float(value.get("observation_variance", 1e-3)),
            initial_covariance=float(value.get("initial_covariance", 10.0)),
            min_training_rows=int(value.get("min_training_rows", 250)),
        )
        result.validate()
        return result

    def validate(self) -> None:
        if self.horizons != CANONICAL_HORIZONS:
            raise ValueError("E4 direct horizons must be exactly 1, 5, 21, 63")
        if (self.state_order != (1, 2)
                or self.process_variance_scale != (0.01, 0.1, 1.0)
                or self.observation_variance_scale != (0.5, 1.0, 2.0)):
            raise ValueError("E4 frozen research coordinates changed")
        coordinates = np.asarray([
            self.state_transition, self.process_variance,
            self.observation_variance, self.initial_covariance,
        ])
        if not np.isfinite(coordinates).all() or self.state_transition < 0.0:
            raise ValueError("invalid E4 state transition contract")
        if (self.process_variance < 0.0 or self.observation_variance <= 0.0
                or self.initial_covariance <= 0.0 or self.min_training_rows < 2):
            raise ValueError("invalid E4 variance or training contract")

    def candidate_coordinates(self) -> tuple[tuple[int, float, float], ...]:
        return tuple(itertools.product(
            self.state_order, self.process_variance_scale, self.observation_variance_scale,
        ))


@dataclass(frozen=True)
class E4Model:
    contract: E4Contract
    filtered_states: Mapping[int, np.ndarray]
    filtered_covariances: Mapping[int, np.ndarray]
    oos_receipts: tuple[Mapping[str, Any], ...]
    direct_horizon_receipts: tuple[Mapping[str, Any], ...]
    diagnostics: Mapping[str, Any]

    def predict(self, features: Sequence[float]) -> dict[int, float]:
        x = _features(features)
        result = {}
        for horizon in self.contract.horizons:
            state = self.contract.state_transition * self.filtered_states[horizon]
            if state.shape != x.shape:
                raise ValueError("prediction feature width differs from fitted E4 state")
            result[horizon] = float(x @ state)
        return result


def fit_e4_filtered_dlm(*, rows: Iterable[Mapping[str, Any]], as_of: str,
                        contract: E4Contract) -> E4Model:
    """Run a causal Kalman filter independently for each direct horizon."""
    contract.validate()
    if not as_of:
        raise ValueError("explicit as_of is required")
    eligible = []
    excluded = 0
    for row in rows:
        available_at = row.get("available_at")
        if available_at is None:
            raise ValueError("each training row requires explicit available_at")
        if str(available_at) > as_of:
            excluded += 1
        else:
            eligible.append(row)
    eligible.sort(key=lambda row: (str(row["available_at"]), str(row.get("origin_session", ""))))
    if len(eligible) < contract.min_training_rows:
        raise ValueError("insufficient point-in-time eligible training rows")

    width = len(_features(eligible[0].get("features")))
    states = {horizon: np.zeros(width, dtype=float) for horizon in contract.horizons}
    covariances = {
        horizon: np.eye(width, dtype=float) * contract.initial_covariance
        for horizon in contract.horizons
    }
    grouped_receipts: list[Mapping[str, Any]] = []
    direct_receipts: list[Mapping[str, Any]] = []
    identity = np.eye(width, dtype=float)
    transition = contract.state_transition

    for row in eligible:
        x = _features(row.get("features"))
        if len(x) != width:
            raise ValueError("finite rectangular feature rows are required")
        origin = str(row.get("origin_session", ""))
        if not origin:
            raise ValueError("each training row requires origin_session")
        forecasts: dict[str, float] = {}
        for horizon in contract.horizons:
            try:
                actual = float(row["targets"][str(horizon)])
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(f"missing direct target for horizon {horizon}") from error
            if not np.isfinite(actual):
                raise ValueError("direct targets must be finite signed fractions")

            # Forecast from t|t-1, then update to t|t. There is deliberately no
            # backward pass: later observations cannot alter this receipt.
            prior_state = transition * states[horizon]
            prior_covariance = (
                transition * transition * covariances[horizon]
                + identity * contract.process_variance
            )
            forecast = float(x @ prior_state)
            innovation_variance = float(x @ prior_covariance @ x + contract.observation_variance)
            gain = prior_covariance @ x / innovation_variance
            posterior_state = prior_state + gain * (actual - forecast)
            residual_operator = identity - np.outer(gain, x)
            posterior_covariance = (
                residual_operator @ prior_covariance @ residual_operator.T
                + np.outer(gain, gain) * contract.observation_variance
            )
            states[horizon] = posterior_state
            covariances[horizon] = posterior_covariance
            forecasts[str(horizon)] = forecast
            direct_receipts.append({
                "origin_session": origin,
                "available_at": str(row["available_at"]),
                "horizon_sessions": horizon,
                "forecast": forecast,
                "actual": actual,
                "state_basis": "transitioned_filtered_prior",
            })
        grouped_receipts.append({
            "origin_session": origin, "available_at": str(row["available_at"]),
            "forecasts": forecasts,
        })

    diagnostics = {
        "as_of": as_of,
        "eligible_rows": len(eligible),
        "excluded_post_as_of_rows": excluded,
        "state_transition": transition,
        "state_estimate": "kalman_filtered_not_smoothed",
        "receipt_timing": "transition_predict_then_observation_update",
        "target_estimation": {str(horizon): "direct" for horizon in contract.horizons},
        "contract_candidate_coordinates": list(contract.candidate_coordinates()),
        "runtime_candidate_coordinates": list(contract.candidate_coordinates()),
    }
    return E4Model(
        contract, states, covariances, tuple(grouped_receipts),
        tuple(direct_receipts), diagnostics,
    )


def _features(value: Any) -> np.ndarray:
    features = np.asarray(value, dtype=float)
    if features.ndim != 1 or not len(features) or not np.isfinite(features).all():
        raise ValueError("finite one-dimensional features are required")
    return features
