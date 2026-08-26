"""Deterministic, bounded screening for G1 direct-horizon challengers."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any

from .integrity import canonical_json, sha256_bytes


FUNNEL_BUDGETS = {
    "smoke": 160,
    "inner_screen": 48,
    "robust_inner": 12,
    "full_nested": 4,
    "qualification": 1,
}

_SCORE_COLUMNS = {
    "smoke": "smoke_crps",
    "inner_screen": "inner_crps",
    "robust_inner": "robust_inner_crps",
    "full_nested": "full_nested_crps",
}


def _sha256(value: Any, field: str) -> str:
    exact = str(value)
    if len(exact) != 64 or any(char not in "0123456789abcdef" for char in exact):
        raise ValueError(f"{field} must be a lowercase SHA-256 hash")
    return exact


def _budgets(overrides: Mapping[str, int] | None) -> dict[str, int]:
    result = dict(FUNNEL_BUDGETS)
    for stage, value in (overrides or {}).items():
        if stage not in result or isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("valid candidate funnel budget is required")
        if value < 0 or value > FUNNEL_BUDGETS[stage]:
            raise ValueError("candidate funnel budget exceeds the frozen contract")
        result[stage] = value
    ordered = list(result.values())
    if any(right > left for left, right in zip(ordered, ordered[1:])):
        raise ValueError("candidate funnel budgets must be non-increasing")
    return result


def screen_g1_candidates(
    candidates: Iterable[Mapping[str, Any]], *, e0_crps: float,
    generation_hash: str, budgets: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Run each candidate through the frozen funnel without changing its evidence.

    Every stage selects only from its predecessor and sorts on that stage's
    precomputed out-of-sample CRPS.  The function does not fit, re-score, or
    re-select observations, so frozen research coordinates remain untouched.
    """
    generation_hash = _sha256(generation_hash, "generation_hash")
    limits = _budgets(budgets)
    baseline = float(e0_crps)
    if not math.isfinite(baseline) or baseline <= 0.0:
        raise ValueError("finite positive E0 CRPS is required")

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in candidates:
        candidate_id = str(source.get("candidate_id", ""))
        hypothesis = source.get("hypothesis")
        exposure = source.get("exposure")
        if not candidate_id or candidate_id in seen:
            raise ValueError("unique candidate_id is required")
        if not isinstance(hypothesis, Mapping) or not hypothesis:
            raise ValueError("explicit candidate hypothesis is required")
        if not isinstance(exposure, Mapping) or not exposure:
            raise ValueError("explicit candidate exposure is required")
        scores = {}
        for stage, column in _SCORE_COLUMNS.items():
            score = float(source.get(column, float("nan")))
            if not math.isfinite(score) or score < 0.0:
                raise ValueError(f"finite non-negative {column} is required")
            scores[stage] = score
        seen.add(candidate_id)
        normalized.append({
            "candidate_id": candidate_id,
            "hypothesis_hash": sha256_bytes(canonical_json(dict(hypothesis))),
            "exposure_hash": sha256_bytes(canonical_json(dict(exposure))),
            "scores": scores,
            "deepest_stage": None,
            "weight": 0.0,
        })

    selected = sorted(normalized, key=lambda row: row["candidate_id"])
    counts: dict[str, int] = {}
    for stage in _SCORE_COLUMNS:
        selected = sorted(selected, key=lambda row: (row["scores"][stage], row["candidate_id"]))[
            : limits[stage]
        ]
        counts[stage] = len(selected)
        for row in selected:
            row["deepest_stage"] = stage
    qualified = selected[:limits["qualification"]]
    counts["qualification"] = len(qualified)
    qualified_ids = {row["candidate_id"] for row in qualified}
    for row in normalized:
        final_score = row["scores"]["full_nested"]
        if row["candidate_id"] in qualified_ids and final_score < baseline:
            row["weight"] = min(1.0, 1.0 - final_score / baseline)
            row["deepest_stage"] = "qualification"

    return {
        "schema": "g1_bounded_candidate_funnel_v1",
        "generation_hash": generation_hash,
        "funnel_budgets": limits,
        "candidate_counts": counts,
        "candidates": sorted(normalized, key=lambda row: row["candidate_id"]),
    }
