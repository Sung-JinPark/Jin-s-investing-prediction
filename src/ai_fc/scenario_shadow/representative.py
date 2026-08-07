"""Deterministic multi-metric selection of an actual ensemble member."""

from __future__ import annotations

import hashlib
import math
from typing import Any

import numpy as np


SELECTION_RULE_VERSION = "actual-central-multimetric-v1"


class RepresentativeSelectionError(ValueError):
    """No actual cohort row can satisfy the representative gate."""


def _midrank_percentiles(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="stable")
    sorted_values = values[order]
    result = np.empty(len(values), dtype=float)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and sorted_values[end] == sorted_values[start]:
            end += 1
        result[order[start:end]] = ((start + end - 1) / 2.0 + 0.5) / len(values) * 100.0
        start = end
    return result


def _longest_true_run(values: np.ndarray) -> np.ndarray:
    current = np.zeros(values.shape[0], dtype=int)
    longest = np.zeros(values.shape[0], dtype=int)
    for column in range(values.shape[1]):
        current = np.where(values[:, column], current + 1, 0)
        longest = np.maximum(longest, current)
    return longest


def _autocorrelation(values: np.ndarray, lag: int) -> float | None:
    if len(values) <= lag:
        return None
    left = values[:-lag]
    right = values[lag:]
    if float(np.std(left)) == 0.0 or float(np.std(right)) == 0.0:
        return None
    return float(np.corrcoef(left, right)[0, 1])


def select_actual_representative_path(
    *,
    future_daily: np.ndarray,
    sampled_weekly: np.ndarray,
    mask: np.ndarray,
    trading_days: tuple[str, ...],
) -> dict[str, Any]:
    global_indexes = np.flatnonzero(mask)
    if len(global_indexes) < 1:
        raise RepresentativeSelectionError("scenario cohort is empty")
    daily = np.column_stack(
        (sampled_weekly[global_indexes, 0], future_daily[global_indexes])
    )
    weekly = sampled_weekly[global_indexes]
    daily_returns = np.diff(np.log(daily), axis=1)
    weekly_returns = np.diff(np.log(weekly), axis=1)
    running_high = np.maximum.accumulate(daily, axis=1)
    drawdowns = 1.0 - daily / running_high
    underwater = drawdowns > 1e-15
    cumulative = np.concatenate(
        (np.zeros((len(global_indexes), 1)), np.cumsum(daily_returns, axis=1)),
        axis=1,
    )
    rolling_five = cumulative[:, 5:] - cumulative[:, :-5]

    metrics = {
        "terminal_return": daily[:, -1] / daily[:, 0] - 1.0,
        "annualized_daily_volatility": np.std(daily_returns, axis=1, ddof=1)
        * math.sqrt(252.0),
        "annualized_weekly_volatility": np.std(weekly_returns, axis=1, ddof=1)
        * math.sqrt(52.0),
        "maximum_drawdown": np.max(drawdowns, axis=1),
        "time_under_water_sessions": np.sum(underwater, axis=1).astype(float),
        "longest_underwater_sessions": _longest_true_run(underwater).astype(float),
        "down_day_fraction": np.mean(daily_returns < 0.0, axis=1),
        "down_week_count": np.sum(weekly_returns < 0.0, axis=1).astype(float),
        "weekly_direction_change_count": np.sum(
            np.sign(weekly_returns[:, 1:]) != np.sign(weekly_returns[:, :-1]), axis=1
        ).astype(float),
        "largest_1day_loss": np.maximum(0.0, -np.min(daily_returns, axis=1)),
        "largest_5day_loss": np.maximum(0.0, -np.min(rolling_five, axis=1)),
    }
    percentiles = {name: _midrank_percentiles(values) for name, values in metrics.items()}

    gate = (
        (percentiles["terminal_return"] >= 35.0)
        & (percentiles["terminal_return"] <= 65.0)
        & (percentiles["annualized_daily_volatility"] >= 10.0)
        & (percentiles["annualized_daily_volatility"] <= 90.0)
        & (percentiles["maximum_drawdown"] >= 10.0)
        & (percentiles["maximum_drawdown"] <= 90.0)
        & (percentiles["time_under_water_sessions"] >= 10.0)
        & (percentiles["time_under_water_sessions"] <= 90.0)
        & (percentiles["weekly_direction_change_count"] >= 10.0)
        & (percentiles["weekly_direction_change_count"] <= 90.0)
    )
    relaxed_terminal_gate = False
    if not bool(gate.any()):
        relaxed_terminal_gate = True
        gate = (
            (percentiles["terminal_return"] >= 25.0)
            & (percentiles["terminal_return"] <= 75.0)
            & (percentiles["annualized_daily_volatility"] >= 10.0)
            & (percentiles["annualized_daily_volatility"] <= 90.0)
            & (percentiles["maximum_drawdown"] >= 10.0)
            & (percentiles["maximum_drawdown"] <= 90.0)
            & (percentiles["time_under_water_sessions"] >= 10.0)
            & (percentiles["time_under_water_sessions"] <= 90.0)
            & (percentiles["weekly_direction_change_count"] >= 10.0)
            & (percentiles["weekly_direction_change_count"] <= 90.0)
        )
    if not bool(gate.any()):
        raise RepresentativeSelectionError("no actual path satisfies centrality gates")

    normalized_log = np.log(weekly / weekly[:, :1])
    median_trajectory = np.median(normalized_log, axis=0)
    trajectory_distance = np.mean(np.abs(normalized_log - median_trajectory), axis=1)
    scores = trajectory_distance.copy()
    score_weights = {
        "terminal_return": 0.50,
        "annualized_daily_volatility": 0.75,
        "maximum_drawdown": 0.75,
        "time_under_water_sessions": 0.50,
        "weekly_direction_change_count": 0.50,
    }
    excluded_zero_iqr: list[str] = []
    for name, weight in score_weights.items():
        values = metrics[name]
        q25, q75 = np.percentile(values, (25, 75))
        iqr = float(q75 - q25)
        if iqr == 0.0:
            excluded_zero_iqr.append(name)
            continue
        scores += weight * np.abs(values - np.median(values)) / iqr

    candidate_locals = np.flatnonzero(gate)
    local_index = min(
        candidate_locals,
        key=lambda local: (float(scores[local]), int(global_indexes[local])),
    )
    global_index = int(global_indexes[local_index])
    selected_daily = np.ascontiguousarray(daily[local_index], dtype=np.float64)
    selected_weekly = weekly[local_index]

    max_drawdown_index = int(np.argmax(drawdowns[local_index]))
    peak_index = int(np.argmax(selected_daily[: max_drawdown_index + 1]))
    recovery_index: int | None = None
    peak_value = selected_daily[peak_index]
    for index in range(max_drawdown_index + 1, len(selected_daily)):
        if selected_daily[index] >= peak_value:
            recovery_index = index
            break
    selected_daily_returns = daily_returns[local_index]
    selected_weekly_returns = weekly_returns[local_index]

    metric_values = {name: float(values[local_index]) for name, values in metrics.items()}
    metric_values.update(
        {
            "weekly_return_autocorrelation_lag1": _autocorrelation(
                selected_weekly_returns, 1
            ),
            "squared_daily_return_autocorrelation_lag1": _autocorrelation(
                selected_daily_returns**2, 1
            ),
            "squared_daily_return_autocorrelation_lag5": _autocorrelation(
                selected_daily_returns**2, 5
            ),
        }
    )
    metric_percentiles = {
        name: float(values[local_index]) for name, values in percentiles.items()
    }
    max_drawdown_date = (
        trading_days[max_drawdown_index - 1] if max_drawdown_index > 0 else None
    )
    recovery_date = (
        trading_days[recovery_index - 1]
        if recovery_index is not None and recovery_index > 0
        else None
    )

    return {
        "path_id": f"legacy-gbm-global-{global_index}",
        "original_global_path_index": global_index,
        "scenario_local_index": int(local_index),
        "path_sha256": hashlib.sha256(selected_daily.tobytes(order="C")).hexdigest(),
        "selection_rule_version": SELECTION_RULE_VERSION,
        "selection_score": float(scores[local_index]),
        "candidate_gate_status": "pass",
        "relaxed_terminal_gate": relaxed_terminal_gate,
        "candidate_count": int(gate.sum()),
        "excluded_zero_iqr_metrics": excluded_zero_iqr,
        "metric_values": metric_values,
        "metric_percentiles": metric_percentiles,
        "terminal_percentile": metric_percentiles["terminal_return"],
        "max_drawdown_date": max_drawdown_date,
        "recovery_date_or_none": recovery_date,
        "weekly_values": [int(round(float(value))) for value in selected_weekly],
    }
