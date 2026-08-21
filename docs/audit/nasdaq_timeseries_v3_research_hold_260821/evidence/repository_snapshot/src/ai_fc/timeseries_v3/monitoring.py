"""Sample-aware forward monitoring against the frozen comparator."""

from __future__ import annotations

import numpy as np

from .calibration import wilson_interval


def source_freshness(
    *, observed_at: str, expected_next_release: str, knowledge_cutoff: str,
    grace_hours: float,
) -> dict[str, object]:
    """Calendar-aware freshness; no universal daily 48-hour rule is applied."""
    from datetime import datetime, timedelta

    observed = datetime.fromisoformat(observed_at)
    expected = datetime.fromisoformat(expected_next_release)
    cutoff = datetime.fromisoformat(knowledge_cutoff)
    deadline = expected + timedelta(hours=float(grace_hours))
    stale = cutoff > deadline
    return {
        "status": "stale" if stale else "fresh",
        "observed_at": observed.isoformat(),
        "expected_next_release": expected.isoformat(),
        "deadline": deadline.isoformat(),
        "age_hours": (cutoff - observed).total_seconds() / 3600.0,
    }


def operational_monitor(
    model_crps: np.ndarray, baseline_crps: np.ndarray, coverage_hits: np.ndarray, *,
    target_coverage: float = 0.80, minimum_hard_gate_origins: int = 30,
    ewma_lambda: float = 0.85, severe_ratio: float = 1.10, severe_weeks: int = 8,
) -> dict[str, object]:
    model = np.asarray(model_crps, dtype=float)
    baseline = np.asarray(baseline_crps, dtype=float)
    hits = np.asarray(coverage_hits, dtype=bool)
    if not (len(model) == len(baseline) == len(hits)):
        raise ValueError("monitor arrays must align")
    ratios = model / np.maximum(baseline, 1e-12)
    ewma = np.empty(len(ratios))
    for index, value in enumerate(ratios):
        ewma[index] = value if index == 0 else ewma_lambda * ewma[index - 1] + (1 - ewma_lambda) * value
    severe = len(ewma) >= severe_weeks and bool(np.all(ewma[-severe_weeks:] > severe_ratio))
    if len(hits) < minimum_hard_gate_origins:
        return {
            "status": "provisional_monitor_only", "origin_count": len(hits),
            "ewma_crps_ratio": None if not len(ewma) else float(ewma[-1]), "severe_alarm": severe,
        }
    interval = wilson_interval(int(hits.sum()), len(hits))
    return {
        "status": "hard_monitor", "origin_count": len(hits),
        "coverage": float(hits.mean()), "coverage_wilson90": list(interval),
        "target_coverage_in_interval": interval[0] <= target_coverage <= interval[1],
        "ewma_crps_ratio": float(ewma[-1]), "severe_alarm": severe,
        "comparator": "fixed_anchor_ensemble_v3",
    }
