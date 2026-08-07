"""Exact, read-only reproduction of the official legacy GBM scenario matrix."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np


QUANTILES = (
    (5, "p05"),
    (10, "p10"),
    (25, "p25"),
    (50, "p50"),
    (75, "p75"),
    (90, "p90"),
    (95, "p95"),
)
SCENARIO_KEYS = ("S1", "S2", "S3")


class LegacyReproductionError(ValueError):
    """The official snapshot cannot be reproduced exactly enough for use."""


@dataclass(frozen=True)
class LegacyGBMReproduction:
    future_daily: np.ndarray
    sampled_weekly: np.ndarray
    trading_days: tuple[str, ...]
    week_dates: tuple[str, ...]
    masks: dict[str, np.ndarray]
    counts: dict[str, int]
    probability_percent: dict[str, int]
    verification: dict[str, Any]


def _round_probabilities(
    masks: tuple[np.ndarray, ...],
) -> tuple[list[int], dict[str, Any]]:
    raw = [float(mask.mean() * 100.0) for mask in masks]
    independently_rounded = [int(round(value)) for value in raw]
    rounded = independently_rounded.copy()
    adjustment_index = int(np.argmax(raw))
    residual = 100 - sum(rounded)
    rounded[adjustment_index] += residual
    return rounded, {
        "method": "nearest_integer_then_largest_share_receives_residual",
        "raw_percent": dict(zip(SCENARIO_KEYS, raw, strict=True)),
        "independently_rounded_percent": dict(
            zip(SCENARIO_KEYS, independently_rounded, strict=True)
        ),
        "residual_percentage_points": residual,
        "adjusted_scenario": SCENARIO_KEYS[adjustment_index],
        "final_percent": dict(zip(SCENARIO_KEYS, rounded, strict=True)),
    }


def _rounded_daily_quantiles(future: np.ndarray) -> dict[str, list[int]]:
    return {
        key: [
            int(round(float(value) / 10.0) * 10)
            for value in np.percentile(future, percentile, axis=0)
        ]
        for percentile, key in QUANTILES
    }


def reproduce_legacy_snapshot(
    snapshot: Mapping[str, Any],
    *,
    seed_override: int | None = None,
    require_exact: bool = True,
) -> LegacyGBMReproduction:
    model = snapshot["model"]
    parameters = model["gbm_parameters"]
    n_paths = int(model["n_paths"])
    horizon = int(model["horizon_business_days"])
    seed = int(model["seed"] if seed_override is None else seed_override)
    mu = float(parameters["mu_daily_log_return"])
    sigma = float(parameters["sigma_daily_log_return"])
    anchor = float(snapshot["anchor"])

    rng = np.random.default_rng(seed)
    shocks = rng.standard_normal((n_paths, horizon))
    ratios = np.exp(np.cumsum(mu - sigma**2 / 2.0 + sigma * shocks, axis=1))
    future = anchor * ratios

    trading_days = tuple(snapshot["quantile_table"]["trading_days"])
    if len(trading_days) != horizon:
        raise LegacyReproductionError("trading-day calendar length mismatch")
    classification_index = trading_days.index(model["classification_date"])
    classification = future[:, : classification_index + 1]
    s1 = (classification > float(snapshot["ath"])).any(axis=1)
    s2 = ~s1 & (classification[:, -1] > float(snapshot["reference_price"]))
    s3 = ~(s1 | s2)
    masks = {"S1": s1, "S2": s2, "S3": s3}
    if not np.all(s1.astype(int) + s2.astype(int) + s3.astype(int) == 1):
        raise LegacyReproductionError("scenario partition is not exhaustive and disjoint")

    graph_indexes = list(range(4, horizon, 5))
    if graph_indexes[-1] != horizon - 1:
        graph_indexes.append(horizon - 1)
    week_dates = tuple(snapshot["week_dates"])
    sampled = np.empty((n_paths, len(graph_indexes) + 1), dtype=np.float64)
    sampled[:, 0] = anchor
    for column, index in enumerate(graph_indexes, start=1):
        sampled[:, column] = future[:, index]
    if sampled.shape[1] != len(week_dates):
        raise LegacyReproductionError("weekly sample calendar length mismatch")

    counts = {key: int(mask.sum()) for key, mask in masks.items()}
    probabilities, probability_rounding = _round_probabilities(
        tuple(masks[key] for key in SCENARIO_KEYS)
    )
    probability_percent = dict(zip(SCENARIO_KEYS, probabilities, strict=True))
    expected_probabilities = {
        key: int(snapshot["paths"][key]["prob"]) for key in SCENARIO_KEYS
    }
    reproduced_quantiles = _rounded_daily_quantiles(future)
    expected_quantiles = snapshot["quantile_table"]["quantiles"]
    mismatch_count = sum(
        left != right
        for key in expected_quantiles
        for left, right in zip(expected_quantiles[key], reproduced_quantiles[key])
    )

    retained_member_mismatches = 0
    for key in SCENARIO_KEYS:
        for row in snapshot["path_realism"][key]["sample_paths"]:
            path_index = int(row["path_index"])
            actual = [int(round(float(value))) for value in sampled[path_index]]
            retained_member_mismatches += sum(
                left != right for left, right in zip(actual, row["values"])
            )

    verification = {
        "seed": seed,
        "seed_matches_snapshot": seed == int(model["seed"]),
        "expected_counts": {
            key: int(snapshot["path_realism"][key]["sample_count"])
            for key in SCENARIO_KEYS
        },
        "reproduced_counts": counts,
        "expected_probability_percent": expected_probabilities,
        "reproduced_probability_percent": probability_percent,
        "probability_percent_rounding_receipt": probability_rounding,
        "quantile_cells_checked": len(expected_quantiles) * horizon,
        "quantile_mismatches": mismatch_count,
        "retained_member_cells_checked": sum(
            len(row["values"])
            for key in SCENARIO_KEYS
            for row in snapshot["path_realism"][key]["sample_paths"]
        ),
        "retained_member_mismatches": retained_member_mismatches,
        "passed": (
            seed == int(model["seed"])
            and counts
            == {
                key: int(snapshot["path_realism"][key]["sample_count"])
                for key in SCENARIO_KEYS
            }
            and probability_percent == expected_probabilities
            and mismatch_count == 0
            and retained_member_mismatches == 0
        ),
    }
    if require_exact and not verification["passed"]:
        raise LegacyReproductionError(
            f"legacy reproduction failed: {verification}"
        )

    return LegacyGBMReproduction(
        future_daily=future,
        sampled_weekly=sampled,
        trading_days=trading_days,
        week_dates=week_dates,
        masks=masks,
        counts=counts,
        probability_percent=probability_percent,
        verification=verification,
    )
