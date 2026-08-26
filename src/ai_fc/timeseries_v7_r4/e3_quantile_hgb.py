"""E3 point-in-time direct-horizon quantile histogram gradient boosting."""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor


CANONICAL_HORIZONS = (1, 5, 21, 63)


@dataclass(frozen=True)
class E3Contract:
    horizons: tuple[int, ...] = CANONICAL_HORIZONS
    quantiles: tuple[float, ...] = (0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99)
    learning_rate: tuple[float, ...] = (0.03, 0.07)
    max_leaf_nodes: tuple[int, ...] = (7, 15)
    max_iter: tuple[int, ...] = (100, 200)
    min_samples_leaf: tuple[int, ...] = (30, 60)
    l2_regularization: tuple[float, ...] = (0.0, 1.0)
    min_training_rows: int = 250
    selection_fraction: float = 0.2

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "E3Contract":
        result = cls(
            horizons=tuple(int(v) for v in value.get("horizons", CANONICAL_HORIZONS)),
            quantiles=tuple(float(v) for v in value.get("quantiles", cls.quantiles)),
            learning_rate=tuple(float(v) for v in value.get("learning_rate", cls.learning_rate)),
            max_leaf_nodes=tuple(int(v) for v in value.get("max_leaf_nodes", cls.max_leaf_nodes)),
            max_iter=tuple(int(v) for v in value.get("max_iter", cls.max_iter)),
            min_samples_leaf=tuple(int(v) for v in value.get(
                "min_samples_leaf", cls.min_samples_leaf,
            )),
            l2_regularization=tuple(float(v) for v in value.get(
                "l2_regularization", cls.l2_regularization,
            )),
            min_training_rows=int(value.get("min_training_rows", cls.min_training_rows)),
            selection_fraction=float(value.get("selection_fraction", cls.selection_fraction)),
        )
        result.validate()
        return result

    def validate(self) -> None:
        if self.horizons != CANONICAL_HORIZONS:
            raise ValueError("E3 direct horizons must be exactly 1, 5, 21, 63")
        if (not self.quantiles or tuple(sorted(set(self.quantiles))) != self.quantiles
                or any(not 0.0 < q < 1.0 for q in self.quantiles)):
            raise ValueError("quantiles must be unique, increasing probabilities inside (0, 1)")
        grids = (self.learning_rate, self.max_leaf_nodes, self.max_iter,
                 self.min_samples_leaf, self.l2_regularization)
        if any(not grid or len(set(grid)) != len(grid) for grid in grids):
            raise ValueError("E3 candidate coordinate grids must be nonempty and unique")
        if (any(not np.isfinite(v) or v <= 0.0 for v in self.learning_rate)
                or any(v < 2 for v in self.max_leaf_nodes)
                or any(v < 1 for v in self.max_iter)
                or any(v < 1 for v in self.min_samples_leaf)
                or any(not np.isfinite(v) or v < 0.0 for v in self.l2_regularization)):
            raise ValueError("invalid E3 candidate coordinate")
        if self.min_training_rows < 8 or not 0.0 < self.selection_fraction < 0.5:
            raise ValueError("invalid E3 training/selection contract")

    def candidate_coordinates(self) -> tuple[tuple[float, int, int, int, float], ...]:
        return tuple(itertools.product(
            self.learning_rate, self.max_leaf_nodes, self.max_iter,
            self.min_samples_leaf, self.l2_regularization,
        ))


def repair_quantile_crossing(quantiles: Sequence[float], values: Sequence[float]) -> tuple[float, ...]:
    """Project estimates onto their monotone cone with deterministic unit-weight PAVA."""
    if len(quantiles) != len(values) or tuple(sorted(quantiles)) != tuple(quantiles):
        raise ValueError("ordered quantiles and equally sized values are required")
    if not np.isfinite(np.asarray(values, dtype=float)).all():
        raise ValueError("quantile estimates must be finite")
    blocks: list[list[float]] = []  # mean, weight
    for value in values:
        blocks.append([float(value), 1.0])
        while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0]:
            right = blocks.pop()
            left = blocks.pop()
            weight = left[1] + right[1]
            blocks.append([(left[0] * left[1] + right[0] * right[1]) / weight, weight])
    return tuple(value for mean, weight in blocks for value in [mean] * int(weight))


@dataclass(frozen=True)
class E3Model:
    horizons: tuple[int, ...]
    quantiles: tuple[float, ...]
    estimators: Mapping[tuple[int, float], HistGradientBoostingRegressor]
    diagnostics: Mapping[str, Any]

    def predict(self, features: Sequence[float]) -> dict[int, dict[float, float]]:
        values = np.asarray(features, dtype=float)
        if values.ndim != 1 or not len(values) or not np.isfinite(values).all():
            raise ValueError("finite one-dimensional features are required")
        result: dict[int, dict[float, float]] = {}
        for horizon in self.horizons:
            raw = tuple(float(self.estimators[(horizon, q)].predict(values[None, :])[0])
                        for q in self.quantiles)
            repaired = repair_quantile_crossing(self.quantiles, raw)
            result[horizon] = dict(zip(self.quantiles, repaired, strict=True))
        return result


def _pinball(actual: np.ndarray, predicted: np.ndarray, quantile: float) -> float:
    error = actual - predicted
    return float(np.maximum(quantile * error, (quantile - 1.0) * error).mean())


def fit_e3_quantile_hgb(*, rows: Iterable[Mapping[str, Any]], as_of: str,
                        contract: E3Contract) -> E3Model:
    """Select and fit every contract quantile directly using PIT-eligible rows."""
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
    x = np.asarray([row["features"] for row in eligible], dtype=float)
    if x.ndim != 2 or x.shape[1] == 0 or not np.isfinite(x).all():
        raise ValueError("finite rectangular feature rows are required")

    validation_rows = max(1, int(np.ceil(len(x) * contract.selection_fraction)))
    split = len(x) - validation_rows
    coordinates = contract.candidate_coordinates()
    estimators: dict[tuple[int, float], HistGradientBoostingRegressor] = {}
    selected: dict[str, tuple[float, int, int, int, float]] = {}
    for horizon in contract.horizons:
        try:
            target = np.asarray([row["targets"][str(horizon)] for row in eligible], dtype=float)
        except (KeyError, TypeError) as error:
            raise ValueError(f"missing direct target for horizon {horizon}") from error
        if not np.isfinite(target).all():
            raise ValueError("direct targets must be finite signed fractions")
        for quantile in contract.quantiles:
            best_coordinate = min(coordinates, key=lambda coordinate: _candidate_loss(
                coordinate, quantile, x[:split], target[:split], x[split:], target[split:],
            ))
            estimator = _estimator(best_coordinate, quantile)
            estimator.fit(x, target)
            estimators[(horizon, quantile)] = estimator
            selected[f"{horizon}:{quantile:g}"] = best_coordinate

    coordinate_list = list(coordinates)
    diagnostics = {
        "as_of": as_of, "eligible_rows": len(eligible),
        "excluded_post_as_of_rows": excluded,
        "contract_candidate_coordinates": coordinate_list,
        "runtime_candidate_coordinates": coordinate_list,
        "selected_coordinates": selected,
        "quantile_estimation": {f"{q:g}": "direct" for q in contract.quantiles},
        "crossing_repair": "deterministic_unit_weight_pava_at_prediction_boundary",
    }
    return E3Model(contract.horizons, contract.quantiles, estimators, diagnostics)


def _estimator(coordinate: tuple[float, int, int, int, float],
               quantile: float) -> HistGradientBoostingRegressor:
    learning_rate, max_leaf_nodes, max_iter, min_samples_leaf, l2 = coordinate
    return HistGradientBoostingRegressor(
        loss="quantile", quantile=quantile, learning_rate=learning_rate,
        max_leaf_nodes=max_leaf_nodes, max_iter=max_iter,
        min_samples_leaf=min_samples_leaf, l2_regularization=l2,
        early_stopping=False, random_state=0,
    )


def _candidate_loss(coordinate: tuple[float, int, int, int, float], quantile: float,
                    train_x: np.ndarray, train_y: np.ndarray,
                    validation_x: np.ndarray, validation_y: np.ndarray) -> float:
    estimator = _estimator(coordinate, quantile)
    estimator.fit(train_x, train_y)
    return _pinball(validation_y, estimator.predict(validation_x), quantile)
