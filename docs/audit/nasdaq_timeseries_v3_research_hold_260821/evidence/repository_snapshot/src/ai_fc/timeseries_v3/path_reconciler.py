"""Joint endpoint sampling and stochastic residual bridges for daily paths."""

from __future__ import annotations

import numpy as np


def nearest_correlation(matrix: np.ndarray) -> np.ndarray:
    values = np.asarray(matrix, dtype=float)
    values = (values + values.T) / 2
    eigenvalues, eigenvectors = np.linalg.eigh(values)
    values = eigenvectors @ np.diag(np.maximum(eigenvalues, 1e-6)) @ eigenvectors.T
    diagonal = np.sqrt(np.diag(values))
    return values / np.outer(diagonal, diagonal)


def gaussian_copula_endpoints(
    horizon_samples: dict[int, np.ndarray], *, correlation: np.ndarray,
    count: int, rng: np.random.Generator,
) -> tuple[tuple[int, ...], np.ndarray]:
    horizons = tuple(sorted(horizon_samples))
    correlation = nearest_correlation(correlation)
    normals = rng.multivariate_normal(np.zeros(len(horizons)), correlation, size=count)
    order = np.argsort(np.argsort(normals, axis=0), axis=0)
    joint = np.empty((count, len(horizons)))
    for column, horizon in enumerate(horizons):
        source = np.sort(np.asarray(horizon_samples[horizon], dtype=float))
        positions = np.minimum((order[:, column] * len(source) / count).astype(int), len(source) - 1)
        joint[:, column] = source[positions]
    return horizons, joint


def stochastic_bridge_paths(
    endpoints: np.ndarray, horizons: tuple[int, ...], historical_daily_returns: np.ndarray, *,
    rng: np.random.Generator, block_length: int = 10,
) -> np.ndarray:
    endpoints = np.asarray(endpoints, dtype=float)
    if endpoints.shape[1] != len(horizons) or tuple(sorted(horizons)) != horizons:
        raise ValueError("endpoint columns and ordered horizons must match")
    count = endpoints.shape[0]
    maximum = horizons[-1]
    history = np.asarray(historical_daily_returns, dtype=float)
    paths = np.empty((count, maximum))
    restart = 1.0 / block_length
    indexes = rng.integers(0, len(history), count)
    for day in range(maximum):
        if day:
            reset = rng.random(count) < restart
            indexes = np.where(reset, rng.integers(0, len(history), count), (indexes + 1) % len(history))
        paths[:, day] = history[indexes]
    start = 0
    previous_endpoint = np.zeros(count)
    for column, end in enumerate(horizons):
        target_increment = endpoints[:, column] - previous_endpoint
        segment = paths[:, start:end]
        raw_increment = segment.sum(axis=1)
        # Volatility-weighted bridge correction preserves stochastic shape instead of linearly interpolating levels.
        weights = np.abs(segment) + np.std(segment, axis=1, keepdims=True) * 0.10 + 1e-8
        weights /= weights.sum(axis=1, keepdims=True)
        segment += (target_increment - raw_increment)[:, None] * weights
        paths[:, start:end] = segment
        previous_endpoint = endpoints[:, column]
        start = end
    return paths


def endpoint_errors(paths: np.ndarray, endpoints: np.ndarray, horizons: tuple[int, ...]) -> np.ndarray:
    cumulative = np.cumsum(np.asarray(paths, dtype=float), axis=1)
    observed = np.column_stack([cumulative[:, horizon - 1] for horizon in horizons])
    return observed - np.asarray(endpoints, dtype=float)


def path_duplicate_fraction(paths: np.ndarray, decimals: int = 10) -> float:
    rounded = np.round(np.asarray(paths, dtype=float), decimals)
    unique = np.unique(rounded, axis=0).shape[0]
    return 1.0 - unique / len(rounded)
