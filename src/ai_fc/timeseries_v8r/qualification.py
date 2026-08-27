"""Pre-admission multiplicity, CSCV/PBO, and MDE utilities for V8R."""

from __future__ import annotations

from itertools import combinations
import math
from statistics import NormalDist
from typing import Mapping, Sequence


def benjamini_hochberg(
    p_values: Mapping[str, float], *, registry_attempts: int, q: float = 0.10
) -> dict[str, object]:
    """Apply BH using all registered attempts as the multiplicity denominator."""
    if not 0 < q < 1:
        raise ValueError("q must be in (0, 1)")
    if registry_attempts < len(p_values) or registry_attempts <= 0:
        raise ValueError("registry_attempts must cover every tested candidate")
    ordered = sorted((float(value), name) for name, value in p_values.items())
    if any(not 0 <= value <= 1 for value, _ in ordered):
        raise ValueError("p-values must be in [0, 1]")
    largest_rank = 0
    rows: list[dict[str, object]] = []
    for rank, (value, name) in enumerate(ordered, start=1):
        threshold = q * rank / registry_attempts
        passed_at_rank = value <= threshold
        if passed_at_rank:
            largest_rank = rank
        rows.append({"candidate_id": name, "p_value": value,
                     "rank": rank, "threshold": threshold,
                     "passed_at_rank": passed_at_rank})
    selected = [name for _, name in ordered[:largest_rank]]
    return {
        "schema": "v8r_bh_fdr_v1",
        "q": q,
        "registry_attempts": registry_attempts,
        "tested_candidates": len(ordered),
        "selected": selected,
        "rows": rows,
        "gate_formula_changed": False,
        "usage": "pre_admission_filter_only",
    }


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def cscv_pbo(performance_rows: Sequence[Sequence[float]], *, splits: int = 16) -> dict[str, object]:
    """Compute CSCV probability of backtest overfitting for strategy columns.

    Rows must already be ordered and restricted to the research role. The routine
    partitions contiguous rows into ``splits`` blocks and never reads outer data.
    """
    if splits != 16:
        raise ValueError("V8R contract fixes CSCV splits at S=16")
    if len(performance_rows) < splits * 2:
        raise ValueError("at least two observations per CSCV block are required")
    strategy_count = len(performance_rows[0])
    if strategy_count < 2 or any(len(row) != strategy_count for row in performance_rows):
        raise ValueError("performance matrix must be rectangular with >=2 strategies")
    if any(not math.isfinite(float(value)) for row in performance_rows for value in row):
        raise ValueError("performance matrix contains a non-finite value")
    block_size = len(performance_rows) // splits
    usable = block_size * splits
    blocks = [list(range(index * block_size, (index + 1) * block_size))
              for index in range(splits)]
    logits: list[float] = []
    selected_counts = [0] * strategy_count
    for train_blocks in combinations(range(splits), splits // 2):
        train_set = set(train_blocks)
        train_rows = [row for block in train_blocks for row in blocks[block]]
        test_rows = [row for block in range(splits) if block not in train_set
                     for row in blocks[block]]
        train_means = [
            _mean([float(performance_rows[row][column]) for row in train_rows])
            for column in range(strategy_count)
        ]
        selected = max(range(strategy_count), key=lambda column: (train_means[column], -column))
        selected_counts[selected] += 1
        test_means = [
            _mean([float(performance_rows[row][column]) for row in test_rows])
            for column in range(strategy_count)
        ]
        ordered = sorted(range(strategy_count), key=lambda column: (test_means[column], column))
        rank = ordered.index(selected) + 1
        relative_rank = (rank - 0.5) / strategy_count
        logits.append(math.log(relative_rank / (1.0 - relative_rank)))
    pbo = sum(value <= 0.0 for value in logits) / len(logits)
    return {
        "schema": "v8r_cscv_pbo_v1",
        "splits": splits,
        "usable_rows": usable,
        "discarded_tail_rows": len(performance_rows) - usable,
        "strategy_count": strategy_count,
        "combinations": len(logits),
        "pbo": pbo,
        "mean_logit": _mean(logits),
        "selected_counts": selected_counts,
        "outer_rows_used": 0,
    }


def horizon_mde(
    paired_advantages: Mapping[int, Sequence[float]], *,
    alpha: float = 0.05, power: float = 0.80,
    effective_n: Mapping[int, float] | None = None,
) -> dict[str, object]:
    """Report two-sided normal-approximation MDE for paired advantages."""
    if not 0 < alpha < 1 or not 0 < power < 1:
        raise ValueError("alpha and power must be in (0, 1)")
    normal = NormalDist()
    critical = normal.inv_cdf(1 - alpha / 2) + normal.inv_cdf(power)
    rows: dict[str, dict[str, float | int | str]] = {}
    for horizon, values in sorted(paired_advantages.items()):
        clean = [float(value) for value in values if math.isfinite(float(value))]
        if len(clean) < 3:
            raise ValueError(f"horizon {horizon}: at least three finite pairs required")
        mean = _mean(clean)
        variance = sum((value - mean) ** 2 for value in clean) / (len(clean) - 1)
        n_eff = float(effective_n[horizon]) if effective_n and horizon in effective_n else float(len(clean))
        if not 2 <= n_eff <= len(clean):
            raise ValueError(f"horizon {horizon}: invalid effective_n")
        mde = critical * math.sqrt(variance) / math.sqrt(n_eff)
        rows[str(horizon)] = {
            "horizon": horizon,
            "observations": len(clean),
            "effective_n": n_eff,
            "paired_mean_advantage": mean,
            "paired_sd": math.sqrt(variance),
            "mde_absolute": mde,
            "interpretation": "below_mde_is_underpowered_not_no_effect",
        }
    return {
        "schema": "v8r_horizon_mde_v1",
        "alpha": alpha,
        "power": power,
        "rows": rows,
        "outer_rows_used": 0,
    }
