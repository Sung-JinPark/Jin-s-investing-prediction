"""One-shot frozen-grid R4 core qualification and Gate-deficit routing."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from .integrity import canonical_json, sha256_bytes
from .router import GateDeficitRouter


GATE_NAMES = (
    "long_skill_below_threshold", "h21_skill_negative", "h63_skill_negative",
    "paired_ci_upper_positive", "coverage80_fail", "coverage50_low",
    "coverage50_high",
    "balanced_direction_low", "brier_worse_than_base_rate",
    "extreme_q4_coverage_low", "catastrophic_underperformance_high",
    "historical_stress_fail",
)


class QualificationAlreadyConsumed(RuntimeError):
    """The sealed qualification evidence for this generation already exists."""


def _balanced_accuracy(actual: np.ndarray, probability: np.ndarray) -> float:
    truth = actual > 0
    predicted = probability >= 0.5
    rates = [float(np.mean(predicted[truth] == value)) for value in (True, False)
             if np.any(truth == value)]
    return float(np.mean(rates))


def _ci_upper(rows: list[dict[str, Any]]) -> float:
    # Weekly origins overlap at long horizons.  A fixed 13-week moving-block
    # jackknife keeps the comparison dependence-aware and deterministic.
    by_origin: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        if int(row["horizon"]) in (21, 63):
            by_origin[str(row["origin_session"])].append(
                float(row["model_crps"]) - float(row["baseline_crps"]))
    values = np.asarray([np.mean(by_origin[key]) for key in sorted(by_origin)], float)
    mean = float(np.mean(values))
    if len(values) < 2:
        return mean
    centered = values - mean
    lag = min(13, len(values) - 1)
    variance = float(np.dot(centered, centered) / len(values))
    for offset in range(1, lag + 1):
        covariance = float(np.dot(centered[offset:], centered[:-offset]) / len(values))
        variance += 2 * (1 - offset / (lag + 1)) * covariance
    return mean + 1.96 * np.sqrt(max(variance, 0.0) / len(values))


def _stress(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], float, bool]:
    windows = {
        "gfc": ("2007-07-01", "2009-03-31"),
        "rebound_2009": ("2009-04-01", "2010-03-31"),
        "pandemic": ("2020-02-01", "2020-05-31"),
        "rebound_2020": ("2020-06-01", "2021-03-31"),
        "tightening_2022": ("2022-01-01", "2022-12-31"),
        "bull_2023": ("2023-01-01", "2023-12-31"),
    }
    result: dict[str, Any] = {}
    degradations: list[float] = []
    passes: list[bool] = []
    for name, (start, end) in windows.items():
        subset = [row for row in rows if start <= str(row["origin_session"]) <= end]
        if not subset:
            continue
        coverage = float(np.mean([row["p10"] <= row["actual"] <= row["p90"]
                                  for row in subset]))
        baseline = float(np.mean([row["baseline_crps"] for row in subset]))
        degradation = float(np.mean([row["model_crps"] for row in subset]) / baseline - 1)
        coverage_pass = coverage >= 0.65
        result[name] = {"count": len(subset), "coverage80": coverage,
                        "coverage_pass_0_65": coverage_pass,
                        "crps_degradation": degradation}
        degradations.append(degradation)
        passes.append(coverage_pass)
    return result, max(degradations, default=float("inf")), bool(passes and all(passes))


def compute_gate_evidence(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    values = list(rows)
    actual = np.asarray([row["actual"] for row in values], float)
    probability = np.asarray([row["probability_up"] for row in values], float)
    skills: dict[str, float] = {}
    for horizon in (1, 5, 21, 63):
        selected = [row for row in values if int(row["horizon"]) == horizon]
        skills[str(horizon)] = 1 - float(np.mean([row["model_crps"] for row in selected])) / float(
            np.mean([row["baseline_crps"] for row in selected]))
    coverage80 = float(np.mean([row["p10"] <= row["actual"] <= row["p90"] for row in values]))
    coverage50 = float(np.mean([row["p25"] <= row["actual"] <= row["p75"] for row in values]))
    brier = float(np.mean((probability - (actual > 0)) ** 2))
    base_probability = float(np.mean(actual > 0))
    base_brier = float(np.mean((base_probability - (actual > 0)) ** 2))
    cutoff = float(np.quantile(np.abs(actual), 0.75))
    extreme = [row for row in values if abs(float(row["actual"])) >= cutoff]
    stress, catastrophic, stress_pass = _stress(values)
    metrics = {
        "score_rows": len(values),
        "origin_count": len({row["origin_session"] for row in values}),
        "skills_by_horizon": skills,
        "long_horizon_mean_crps_skill": float(np.mean([skills["21"], skills["63"]])),
        "paired_ci_upper": _ci_upper(values), "coverage80": coverage80,
        "coverage50": coverage50,
        "balanced_direction_accuracy": _balanced_accuracy(actual, probability),
        "brier": brier, "base_rate_brier": base_brier,
        "extreme_q4_coverage": float(np.mean(
            [row["p10"] <= row["actual"] <= row["p90"] for row in extreme])),
        "catastrophic_underperformance": catastrophic,
        "historical_stress": stress,
    }
    checks = {
        "long_skill_below_threshold": metrics["long_horizon_mean_crps_skill"] < 0.02,
        "h21_skill_negative": skills["21"] < 0,
        "h63_skill_negative": skills["63"] < 0,
        "paired_ci_upper_positive": metrics["paired_ci_upper"] > 0,
        "coverage80_fail": not 0.76 <= coverage80 <= 0.84,
        "coverage50_low": coverage50 < 0.45,
        "coverage50_high": coverage50 > 0.55,
        "balanced_direction_low": metrics["balanced_direction_accuracy"] < 0.52,
        "brier_worse_than_base_rate": brier >= base_brier,
        "extreme_q4_coverage_low": metrics["extreme_q4_coverage"] < 0.60,
        "catastrophic_underperformance_high": catastrophic > 0.10,
        "historical_stress_fail": not stress_pass,
    }
    checks = {name: bool(value) for name, value in checks.items()}
    return {"metrics": metrics, "gate_deficit_vector": [name for name in GATE_NAMES if checks[name]],
            "gate_results": {name: {"deficit": checks[name]} for name in GATE_NAMES}}


def qualify_once(rows: Iterable[dict[str, Any]], *, checkpoint_dir: Path,
                 generation_key: str, identity: dict[str, str],
                 screening_qualification_rows: int, router_path: Path) -> dict[str, Any]:
    if screening_qualification_rows != 0:
        raise ValueError("screening must use zero qualification rows")
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = checkpoint_dir / f"{sha256_bytes(canonical_json({'generation': generation_key, 'identity': identity}))}.json"
    if checkpoint.exists():
        raise QualificationAlreadyConsumed(generation_key)
    evidence = compute_gate_evidence(rows)
    deficits = evidence["gate_deficit_vector"]
    routed = GateDeficitRouter.from_yaml(router_path).route(
        deficits, dataset_snapshot_hash=identity["r4_snapshot_hash"],
        code_hash=identity["g2_artifact_sha256"], runtime_hash=identity["g1_artifact_sha256"])
    result = {
        "schema": "r4_core_qualification_v1", "identity": identity,
        "qualification_count": 1, "screening_qualification_rows": 0,
        **evidence, "decision": "PASS" if not deficits else "HOLD_RESEARCH_GATE",
        "reason": None if not deficits else "RESEARCH_GATE_FAILED_REPLAN",
        "process_exit_code": 0,
        "routed_tasks": [task.__dict__ for task in routed],
    }
    checkpoint.write_bytes(canonical_json(result) + b"\n")
    return result
