"""Common distribution component interface and immutable forecast value object."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np


QUANTILES = (0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99)


@dataclass(frozen=True)
class ComponentForecast:
    component_id: str
    horizon_samples: dict[int, np.ndarray]
    quantiles: dict[int, dict[float, float]]
    data_cutoff: str
    feature_hash: str
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_samples(
        cls, component_id: str, horizon_samples: dict[int, np.ndarray], *,
        data_cutoff: str, feature_hash: str, warnings: tuple[str, ...] = (),
    ) -> "ComponentForecast":
        clean: dict[int, np.ndarray] = {}
        quantiles: dict[int, dict[float, float]] = {}
        for horizon, samples in horizon_samples.items():
            array = np.asarray(samples, dtype=float).reshape(-1)
            if array.size == 0 or not np.isfinite(array).all():
                raise ValueError(f"invalid component samples at horizon {horizon}")
            clean[int(horizon)] = array
            values = np.quantile(array, QUANTILES)
            quantiles[int(horizon)] = {
                float(level): float(value) for level, value in zip(QUANTILES, values, strict=True)
            }
        return cls(component_id, clean, quantiles, data_cutoff, feature_hash, warnings)


class DistributionComponent(Protocol):
    component_id: str

    def fit(self, train_snapshot, horizons: tuple[int, ...]): ...

    def predict(self, origin_snapshot, horizons: tuple[int, ...]) -> ComponentForecast: ...
