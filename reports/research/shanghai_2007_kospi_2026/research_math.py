"""Small, offline, explicit-unit calculations for the research report."""
from __future__ import annotations

import math


def valuation_return(eps_change: float, pe_change: float, *, unit: str) -> float:
    if unit != "fraction":
        raise ValueError("EPS and P/E changes require explicit fraction unit")
    if not all(math.isfinite(x) and x > -1 for x in (eps_change, pe_change)):
        raise ValueError("positive EPS and P/E are required; change must exceed -1")
    return (1 + eps_change) * (1 + pe_change) - 1


def implied_pe_change(eps_change: float, target_return: float, *, unit: str) -> float:
    if unit != "fraction":
        raise ValueError("explicit fraction unit required")
    if not all(math.isfinite(x) and x > -1 for x in (eps_change, target_return)):
        raise ValueError("positive endpoint values required")
    return (1 + target_return) / (1 + eps_change) - 1


def path_risks(origin: float, future_closes: list[float], *, unit: str) -> dict:
    if unit != "index_points" or not math.isfinite(origin) or origin <= 0 or not future_closes:
        raise ValueError("positive origin, future observations, explicit index_points required")
    if any(not math.isfinite(p) or p <= 0 for p in future_closes):
        raise ValueError("future closes must all be finite and positive")
    peak = origin
    mdd = 0.0
    for price in future_closes:
        peak = max(peak, price)
        mdd = min(mdd, price / peak - 1)
    worst_origin_return = min(p / origin - 1 for p in future_closes)
    return {"end_return_fraction": future_closes[-1] / origin - 1,
            "worst_origin_return_fraction": worst_origin_return,
            "max_drawdown_fraction": mdd,
            "additional_20pct_loss_event": worst_origin_return <= -0.20 + 1e-12}


def profit_concentration(total: float, excluding: float, total_growth: float,
                         excluding_growth: float, *, unit: str) -> dict:
    if unit != "same_currency_and_scale;growth_fraction":
        raise ValueError("explicit compatible currency/scale and growth_fraction required")
    if not all(math.isfinite(x) for x in (total, excluding, total_growth, excluding_growth)):
        raise ValueError("non-finite data")
    if not 0 < excluding < total or min(total_growth, excluding_growth) <= -1:
        raise ValueError("positive comparable profits required")
    prior_total = total / (1 + total_growth)
    prior_excluding = excluding / (1 + excluding_growth)
    increment = total - prior_total
    leading_increment = (total - excluding) - (prior_total - prior_excluding)
    return {"current_leaders_share_fraction": (total - excluding) / total,
            "previous_leaders_share_fraction": (prior_total - prior_excluding) / prior_total,
            "leaders_increment_share_fraction": leading_increment / increment if increment else None,
            "note": "Prior values inferred from rounded reported growth; approximate, not index return contribution"}
