"""Fixed ex-ante anchor distribution; never selects the winner after resolution."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .contracts import canonical_hash
from .interfaces import ComponentForecast


def _endpoint_windows(returns: np.ndarray, horizon: int) -> np.ndarray:
    values = np.asarray(returns, dtype=float)
    if values.size < horizon + 2:
        raise ValueError("insufficient history for baseline endpoint windows")
    cumulative = np.concatenate(([0.0], np.cumsum(values)))
    return cumulative[horizon:] - cumulative[:-horizon]


def historical_simulation(returns: np.ndarray, horizon: int, count: int, rng: np.random.Generator) -> np.ndarray:
    endpoints = _endpoint_windows(returns, horizon)
    return rng.choice(endpoints, size=count, replace=True)


def filtered_historical_simulation(
    returns: np.ndarray, state_history: np.ndarray, origin_state: np.ndarray, *,
    horizon: int, count: int, neighbors: int, rng: np.random.Generator,
) -> np.ndarray:
    states = np.asarray(state_history, dtype=float)
    target = np.asarray(origin_state, dtype=float)
    endpoints = _endpoint_windows(returns, horizon)
    usable = min(endpoints.size, states.shape[0] - horizon)
    if usable < 20:
        return historical_simulation(returns, horizon, count, rng)
    states = states[:usable]
    endpoints = endpoints[:usable]
    median = np.nanmedian(states, axis=0)
    scale = np.nanmedian(np.abs(states - median), axis=0)
    scale = np.where(scale > 1e-12, scale, 1.0)
    distances = np.nanmean(((states - target) / scale) ** 2, axis=1)
    keep = np.argsort(np.nan_to_num(distances, nan=np.inf))[: max(20, min(neighbors, usable))]
    weights = np.exp(-0.5 * distances[keep])
    if not np.isfinite(weights).all() or weights.sum() <= 0:
        weights = np.ones(keep.size)
    weights /= weights.sum()
    return rng.choice(endpoints[keep], size=count, replace=True, p=weights)


def stationary_block_paths(
    returns: np.ndarray, *, horizon: int, count: int, mean_block: int,
    rng: np.random.Generator,
) -> np.ndarray:
    values = np.asarray(returns, dtype=float)
    if values.size < mean_block + horizon:
        raise ValueError("insufficient return history for stationary bootstrap")
    output = np.empty((count, horizon), dtype=float)
    restart = 1.0 / float(mean_block)
    indexes = rng.integers(0, values.size, size=count)
    for step in range(horizon):
        if step:
            fresh = rng.random(count) < restart
            indexes = np.where(fresh, rng.integers(0, values.size, size=count), (indexes + 1) % values.size)
        output[:, step] = values[indexes]
    return output


@dataclass(frozen=True)
class FixedAnchorDistribution:
    weights: dict[str, float]
    sample_count: int = 4000
    filtered_neighbors: int = 504
    block_length: int = 21
    component_id: str = "fixed_anchor_ensemble_v3"

    def __post_init__(self) -> None:
        expected = {"historical_simulation", "filtered_historical_simulation", "stationary_block_bootstrap"}
        if set(self.weights) != expected or abs(sum(self.weights.values()) - 1.0) > 1e-12:
            raise ValueError("fixed anchor has an invalid component inventory or weights")

    def predict(
        self, *, returns: np.ndarray, state_history: np.ndarray, origin_state: np.ndarray,
        horizons: tuple[int, ...], seed: int, data_cutoff: str,
    ) -> ComponentForecast:
        rng = np.random.default_rng(seed)
        samples: dict[int, np.ndarray] = {}
        for horizon in horizons:
            pieces: list[np.ndarray] = []
            counts: list[int] = []
            remaining = self.sample_count
            items = list(self.weights.items())
            for index, (name, weight) in enumerate(items):
                count = remaining if index == len(items) - 1 else int(round(self.sample_count * weight))
                remaining -= count
                counts.append(count)
                if name == "historical_simulation":
                    piece = historical_simulation(returns, horizon, count, rng)
                elif name == "filtered_historical_simulation":
                    piece = filtered_historical_simulation(
                        returns, state_history, origin_state, horizon=horizon, count=count,
                        neighbors=self.filtered_neighbors, rng=rng,
                    )
                else:
                    paths = stationary_block_paths(
                        returns, horizon=horizon, count=count, mean_block=self.block_length, rng=rng,
                    )
                    piece = paths.sum(axis=1)
                pieces.append(piece)
            joined = np.concatenate(pieces)
            samples[int(horizon)] = joined[rng.permutation(joined.size)]
        feature_hash = canonical_hash({"weights": self.weights, "cutoff": data_cutoff, "state": origin_state.tolist()})
        return ComponentForecast.from_samples(
            self.component_id, samples, data_cutoff=data_cutoff, feature_hash=feature_hash,
        )
