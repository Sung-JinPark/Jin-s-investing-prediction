"""Separated historical qualification and prospective active-regime gates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


HISTORICAL_SUITES = {"gfc", "pandemic", "tightening_2022", "rebound_2009", "rebound_2020", "bull_2023", "absolute_return_q4", "high_volatility_q4"}


@dataclass(frozen=True)
class RegimeScore:
    count: int
    coverage_80: float


def evaluate_historical_stress(scores: Mapping[str, RegimeScore], *, minimum_count: int = 20, minimum_coverage: float = 0.65) -> dict[str, object]:
    rows = {}
    for name in sorted(HISTORICAL_SUITES):
        score = scores.get(name)
        passed = score is not None and score.count >= minimum_count and score.coverage_80 >= minimum_coverage
        rows[name] = {"present": score is not None, "count": 0 if score is None else score.count, "pass": passed}
    return {"suites": rows, "pass": all(row["pass"] for row in rows.values())}


def evaluate_prospective_regimes(scores: Mapping[str, RegimeScore], *, binding_minimum: int = 20, minimum_coverage: float = 0.65) -> dict[str, object]:
    rows = {}
    for name, score in sorted(scores.items()):
        if score.count < binding_minimum:
            rows[name] = {"count": score.count, "decision": "not_applicable", "pass": True}
        else:
            passed = score.coverage_80 >= minimum_coverage
            rows[name] = {"count": score.count, "decision": "pass" if passed else "fail", "pass": passed}
    return {"regimes": rows, "pass": all(row["pass"] for row in rows.values())}
