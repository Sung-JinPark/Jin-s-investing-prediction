"""Contract-grid compiler for quantile histogram boosting."""

from __future__ import annotations

import itertools


COORDINATES = ("learning_rate", "max_leaf_nodes", "max_iter", "min_samples_leaf", "l2_regularization")


def compile_grid(specification: dict) -> list[dict]:
    values = [specification[name] for name in COORDINATES]
    return [dict(zip(COORDINATES, row)) for row in itertools.product(*values)]


def verify_estimator_params(specification: dict, parameters: dict) -> None:
    for name in COORDINATES:
        if parameters.get(name) not in specification[name]:
            raise ValueError(f"off-grid runtime coordinate: {name}={parameters.get(name)}")
