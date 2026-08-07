"""Scenario V5.1 runtime, evidence, timing, and model-risk hardening.

This module is deliberately additive.  It never writes the official scenario,
forecast ledgers, calibration data, or an archive.  V5 remains reproducible as
the shadow baseline while V5.1 makes every stale/endogenous input fail closed.
"""

from __future__ import annotations

import json
import math
import platform
import re
import subprocess
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from scipy.stats import energy_distance, wasserstein_distance

from .contracts import canonical_hash, file_hash, load_contracts
from .engine import build_conditional_outputs, entropy_pool, reproduce_legacy_prior
from .evidence import build_evidence_registry, event_states


CANDIDATE_ID = "scenario_v5_1_time_aligned_legacy_prior_v1"
CANDIDATE_RELATIVE = (
    "data/scenarios/candidates/"
    "scenario_v5_1_time_aligned_legacy_prior_v1_latest.json"
)
TIME_ALIGNMENT_STATUSES = {
    "CURRENT_REFORECAST",
    "SURVIVAL_CONDITIONED",
    "REALIZED_TRUE",
    "REALIZED_FALSE",
    "BLOCKED_NEEDS_REFORECAST",
    "REFERENCE_ONLY_STALE",
}
DIRECT_QUESTION_BY_CONDITION = {
    "max_close": "nasdaq-ath-eoy-2026",
    "min_close": "nasdaq-corr10-augoct-2026",
    "classification_close": "nasdaq-eoy-above-jul9-2026",
}
ORIGINAL_HORIZON_START = {
    "nasdaq-ath-eoy-2026": "2026-07-10",
    "nasdaq-corr10-augoct-2026": "2026-08-01",
    "nasdaq-eoy-above-jul9-2026": "2026-07-10",
}
ENDOGENOUS_QUESTIONS = {
    "nasdaq-ath-eoy-2026": "v4-report-derived forecast from the same scenario/report family",
    "nasdaq-eoy-above-jul9-2026": "v4-report-derived from V4 path weights",
}


class ScenarioV51Error(RuntimeError):
    """Raised when a V5.1 fail-closed gate rejects an artifact."""


def _git_state(root: Path) -> dict[str, Any]:
    def run(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=root, check=True, text=True,
            capture_output=True, encoding="utf-8", errors="replace",
        ).stdout.strip()

    status = run("status", "--porcelain")
    return {
        "head": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
        "dirty": bool(status),
        "status_entries": len(status.splitlines()) if status else 0,
        "python": platform.python_version(),
    }


def _aware(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"timezone required: {value}")
    return parsed


def _question_id(row: dict[str, Any]) -> str | None:
    condition = str(row.get("condition", ""))
    for prefix, question_id in DIRECT_QUESTION_BY_CONDITION.items():
        if condition.startswith(prefix):
            return question_id
    text = " ".join(str(row.get(key, "")) for key in ("source_path", "condition", "source_id"))
    for question_id in ORIGINAL_HORIZON_START:
        if question_id in text:
            return question_id
    return None


def _source_anchor(root: Path, row: dict[str, Any]) -> float | None:
    path = root / str(row.get("source_path", ""))
    if not path.is_file():
        return None
    match = re.search(r'current:\s*["\']?([0-9,]+(?:\.[0-9]+)?)', path.read_text(encoding="utf-8"))
    return float(match.group(1).replace(",", "")) if match else None


def validate_approved_report_view(payload: dict[str, Any]) -> list[str]:
    """Return every strict approved-report schema violation."""
    required = {
        "view_id", "origin_type", "publisher", "report_id", "title", "published_at",
        "available_at", "retrieved_at", "source_path", "source_sha256", "content_sha256",
        "target_asset", "horizon_start", "horizon_end", "view_kind", "condition", "unit",
        "probability_space", "assumptions", "risk_factors", "source_model",
        "human_approval_receipt", "dependency_cluster_id", "duplicate_cluster_id",
        "historical_reliability_status", "used_numerically",
    }
    errors = [f"missing {key}" for key in sorted(required - payload.keys())]
    if payload.get("used_numerically") is not True:
        errors.append("approved report view must explicitly request numerical use")
    if payload.get("probability_space") != "physical_event":
        errors.append("approved report view must be calibrated to physical_event")
    if "target" not in payload and "distribution_parameters" not in payload:
        errors.append("target or distribution_parameters required")
    if "confidence" not in payload and "tolerance" not in payload:
        errors.append("confidence or tolerance required")
    if not payload.get("human_approval_receipt"):
        errors.append("human approval receipt required")
    if payload.get("unit") == "fraction" and "target" in payload:
        value = payload.get("target")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            errors.append("target must be a finite non-boolean number")
        elif not 0 <= float(value) <= 1:
            errors.append("fraction target outside [0,1]")
    try:
        for field in ("published_at", "available_at", "retrieved_at"):
            _aware(str(payload.get(field)))
    except (TypeError, ValueError):
        errors.append("published/available/retrieved timestamps must be timezone-aware ISO timestamps")
    return errors


def load_report_views_v5_1(root: Path, cutoff: datetime) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for folder in ("approved", "proposed"):
        base = root / "data/scenario_views" / folder
        if not base.is_dir():
            continue
        for path in sorted(base.glob("*.json")):
            row = json.loads(path.read_text(encoding="utf-8"))
            row["source_path"] = path.relative_to(root).as_posix()
            row["source_sha256"] = file_hash(path)
            errors = validate_approved_report_view(row) if folder == "approved" else []
            if folder == "proposed":
                row.update({
                    "approval_status": "proposed",
                    "used_numerically": False,
                    "blocked_reason": "proposed report views are never numerical inputs",
                })
            elif errors:
                row.update({
                    "approval_status": "blocked", "used_numerically": False,
                    "blocked_reason": "; ".join(errors),
                })
            elif _aware(row["available_at"]) > cutoff:
                row.update({
                    "approval_status": "blocked", "used_numerically": False,
                    "blocked_reason": "future available_at",
                })
            else:
                row["approval_status"] = "human_approved"
            rows.append(row)
    return rows


def _time_align_view(root: Path, row: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(row)
    question_id = _question_id(result)
    candidate_asof = date.fromisoformat(snapshot["asof"])
    original_start = date.fromisoformat(
        ORIGINAL_HORIZON_START.get(question_id or "", str(result.get("horizon_start", snapshot["asof"])))[:10]
    )
    original_end = date.fromisoformat(str(result.get("horizon_end", snapshot["model"]["classification_date"]))[:10])
    started = candidate_asof >= original_start
    ended = candidate_asof > original_end
    result.update({
        "question_id": question_id,
        "original_forecast_asof": str(result.get("available_at")),
        "original_horizon_start": original_start.isoformat(),
        "original_horizon_end": original_end.isoformat(),
        "candidate_asof": candidate_asof.isoformat(),
        "realized_segment": (
            {"start": original_start.isoformat(), "end": min(candidate_asof, original_end).isoformat(),
             "status": "observed_window_without_approved_realized_path_adapter"}
            if started else None
        ),
        "remaining_horizon": (
            {"start_exclusive": candidate_asof.isoformat(), "end": original_end.isoformat()}
            if not ended else None
        ),
        "transport_method": None,
        "transport_receipt": None,
        "transport_validated": False,
        "derived_from_model_ids": [],
        "derived_from_candidate_ids": [],
        "derived_from_report_ids": [],
        "derived_from_scenario_weights": False,
        "source_model_family": None,
        "source_prompt_version": None,
        "is_endogenous_to_current_model": False,
        "endogeneity_reason": None,
        "realized_segment_start": original_start.isoformat() if started else None,
        "realized_segment_end": min(candidate_asof, original_end).isoformat() if started else None,
        "realized_event_status": "UNRESOLVED_NO_APPROVED_REALIZED_PATH_ADAPTER" if started and not ended else ("WINDOW_ENDED_UNRESOLVED" if ended else "NOT_STARTED"),
        "remaining_horizon_start": candidate_asof.isoformat() if not ended else None,
        "remaining_horizon_end": original_end.isoformat() if not ended else None,
    })
    if result.get("origin_type") == "registered_forecast":
        result["source_model_family"] = "forecast_record:" + str(result.get("source_id"))
        result["source_prompt_version"] = "reasoning_core_v1"
    endogenous_registered = (
        question_id in ENDOGENOUS_QUESTIONS
        and result.get("origin_type") == "registered_forecast"
    )
    release_id = str(result.get("origin_release_id") or result.get("source_id") or "unknown")
    source_family = str(result.get("source_model_family") or result.get("origin_type") or "unknown")
    common_set = "scenario_v4_report" if endogenous_registered else str(result.get("dependency_cluster_id") or "unclustered")
    result["dependency_components"] = {
        "source_model": source_family,
        "source_report": "scenario_v4_report" if endogenous_registered else None,
        "common_evidence_set": common_set,
        "release_id": release_id,
    }
    result["dependency_cluster_id"] = f"common:{common_set}"
    if endogenous_registered:
        result.update({
            "is_endogenous_to_current_model": True,
            "endogeneity_reason": ENDOGENOUS_QUESTIONS[question_id],
            "derived_from_report_ids": ["scenario_v4_report"],
            "derived_from_scenario_weights": question_id == "nasdaq-eoy-above-jul9-2026",
            "time_alignment_status": "REFERENCE_ONLY_STALE",
            "numerical_status": "REFERENCE_ONLY_ENDOGENOUS",
            "used_numerically": False,
            "approval_status": "blocked",
            "blocked_reason": "self-conditioning blocker: " + ENDOGENOUS_QUESTIONS[question_id],
        })
    elif question_id == "nasdaq-corr10-augoct-2026" and started and not ended:
        result.update({
            "time_alignment_status": "BLOCKED_NEEDS_REFORECAST",
            "numerical_status": "BLOCKED_NEEDS_REFORECAST",
            "used_numerically": False,
            "approval_status": "blocked",
            "blocked_reason": "started-window unconditional probability has no approved survival transport",
        })
    elif ended:
        result.update({
            "time_alignment_status": "REFERENCE_ONLY_STALE",
            "numerical_status": "REFERENCE_ONLY_STALE",
            "used_numerically": False,
            "approval_status": "blocked",
            "blocked_reason": "forecast horizon ended before candidate as_of",
        })
    elif result.get("used_numerically"):
        result["time_alignment_status"] = "CURRENT_REFORECAST"
        result["numerical_status"] = "CURRENT_REFORECAST"
    else:
        result["time_alignment_status"] = "REFERENCE_ONLY_STALE"
        result["numerical_status"] = result.get("numerical_status", "REFERENCE_ONLY")

    source_anchor = _source_anchor(root, result)
    drift = None if source_anchor is None else float(snapshot["anchor"]) / source_anchor - 1.0
    sigma = float(snapshot["model"]["gbm_parameters"]["sigma_daily_log_return"])
    elapsed = max(int(np.busday_count(original_start, candidate_asof)), 1)
    standardized = None if drift is None else drift / max(sigma * math.sqrt(elapsed), 1e-12)
    threshold = float(snapshot["corr10"]) if question_id == "nasdaq-corr10-augoct-2026" else (float(snapshot["ath"]) if question_id == "nasdaq-ath-eoy-2026" else None)
    source_barrier_distance = None if source_anchor is None or threshold is None else threshold / source_anchor - 1.0
    candidate_barrier_distance = None if threshold is None else threshold / float(snapshot["anchor"]) - 1.0
    drift_gate_pass = (
        (standardized is None or abs(standardized) <= 2.0)
        and (source_barrier_distance is None
             or abs(candidate_barrier_distance - source_barrier_distance) <= 0.02)
    )
    result["state_drift"] = {
        "source_anchor": source_anchor,
        "candidate_anchor": float(snapshot["anchor"]),
        "return_drift": drift,
        "elapsed_trading_days": elapsed,
        "standardized_drift": standardized,
        "threshold_abs_z": 2.0,
        "gate_pass": drift_gate_pass,
        "spot_to_barrier_distance_at_forecast": source_barrier_distance,
        "spot_to_barrier_distance_at_candidate": candidate_barrier_distance,
        "spot_to_barrier_distance_shift": None if source_barrier_distance is None else candidate_barrier_distance - source_barrier_distance,
        "realized_volatility_shift": "UNAVAILABLE_NO_APPROVED_PIT_ADAPTER",
        "remaining_sessions": max(int(np.busday_count(candidate_asof, original_end + timedelta(days=1))), 0),
        "drawdown_shift": "UNAVAILABLE_NO_APPROVED_PIT_ADAPTER",
        "moving_average_distance_shift": "UNAVAILABLE_NO_APPROVED_PIT_ADAPTER",
        "regime_shift": "UNAVAILABLE_NO_APPROVED_PIT_ADAPTER",
    }
    if result.get("used_numerically") and result["state_drift"]["gate_pass"] is False:
        result.update({
            "time_alignment_status": "BLOCKED_NEEDS_REFORECAST",
            "numerical_status": "BLOCKED_STATE_DRIFT",
            "used_numerically": False,
            "approval_status": "blocked",
            "blocked_reason": "state drift exceeds registered threshold",
        })
    return result


def apply_dependency_cap(
    views: Iterable[dict[str, Any]], *, cluster_cap: float = 0.35,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Deduplicate views and cap total effective strength by dependency cluster."""
    selected: dict[tuple[Any, ...], dict[str, Any]] = {}
    duplicates: list[str] = []
    keys = ("origin_release_id", "dependency_cluster_id", "target_asset", "horizon_end", "view_kind")
    for source in views:
        row = deepcopy(source)
        key = tuple(row.get(name) for name in keys)
        previous = selected.get(key)
        if previous is not None:
            duplicates.append(str(previous.get("view_id")))
        selected[key] = row
    rows = list(selected.values())
    clusters: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        clusters.setdefault(str(row.get("dependency_cluster_id")), []).append(row)
    cluster_rows: list[dict[str, Any]] = []
    for cluster_id, members in sorted(clusters.items()):
        raw = sum(float((row.get("quality") or {}).get("effective_strength", 0.0)) for row in members)
        scale = min(1.0, cluster_cap / raw) if raw > 0 else 1.0
        for row in members:
            quality = row.setdefault("quality", {})
            strength = float(quality.get("effective_strength", 0.0))
            quality["pre_dependency_cap_strength"] = strength
            quality["effective_strength"] = strength * scale
            quality["dependency_cap_scale"] = scale
        capped = sum(float(row["quality"]["effective_strength"]) for row in members)
        cluster_rows.append({
            "dependency_cluster_id": cluster_id,
            "view_ids": [row.get("view_id") for row in members],
            "raw_strength": raw,
            "capped_strength": capped,
            "cap": cluster_cap,
            "cap_binding": scale < 1.0,
            "marginal_influence": None,
        })
    return rows, {
        "deduplication_keys": list(keys),
        "duplicates_removed": duplicates,
        "cluster_cap": cluster_cap,
        "clusters": cluster_rows,
        "effective_independent_view_count": sum(
            min(1.0, row["capped_strength"] / cluster_cap) for row in cluster_rows
        ) if cluster_cap > 0 else 0.0,
    }


def build_evidence_registry_v5_1(
    root: Path, snapshot: dict[str, Any], contracts: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cutoff = _aware(snapshot["generated_at"])
    legacy = build_evidence_registry(root, snapshot, contracts)
    # Replace weak legacy report parsing with the V5.1 strict contract.
    rows = [row for row in legacy if row.get("origin_type") != "strategist_report"]
    rows.extend(load_report_views_v5_1(root, cutoff))
    aligned = [_time_align_view(root, row, snapshot) for row in rows]
    numerical = [row for row in aligned if row.get("used_numerically")]
    capped, diagnostics = apply_dependency_cap(numerical)
    capped_by_id = {row["view_id"]: row for row in capped}
    result = [capped_by_id.get(row.get("view_id"), row) for row in aligned]
    diagnostics["views"] = [{
        "view_id": row.get("view_id"),
        "used_numerically": bool(row.get("used_numerically")),
        "status": row.get("numerical_status"),
        "dependency_cluster_id": row.get("dependency_cluster_id"),
        "marginal_influence": None,
    } for row in result]
    diagnostics["correlation_matrix"] = []
    diagnostics["correlation_matrix_status"] = "NOT_APPLICABLE_NO_APPROVED_NUMERICAL_VIEWS"
    diagnostics["leave_one_view_out"] = []
    diagnostics["leave_one_view_out_status"] = "NOT_APPLICABLE_NO_APPROVED_NUMERICAL_VIEWS"
    diagnostics["leave_one_cluster_out"] = []
    diagnostics["leave_one_cluster_out_status"] = "NOT_APPLICABLE_NO_APPROVED_NUMERICAL_VIEWS"
    return result, diagnostics


def _first_touch_distribution(
    paths: np.ndarray, dates: list[str], weights: np.ndarray, threshold: float,
) -> dict[str, Any]:
    window_indexes = [index for index, day in enumerate(dates) if day <= "2026-10-31"]
    if not window_indexes:
        raise ValueError("correction window is outside the model horizon")
    window_dates = [dates[index] for index in window_indexes]
    hit = paths[:, window_indexes] <= threshold
    any_hit = hit.any(axis=1)
    first = np.where(any_hit, hit.argmax(axis=1), -1)
    density = np.asarray([weights[first == index].sum() for index in range(len(window_dates))])
    cdf = np.cumsum(density)
    any_probability = float(weights[any_hit].sum())
    conditional_cdf = cdf / any_probability if any_probability > 0 else np.zeros_like(cdf)

    def qdate(level: float) -> str | None:
        if any_probability <= 0:
            return None
        return window_dates[min(int(np.searchsorted(conditional_cdf, level, side="left")), len(window_dates) - 1)]

    points = ["2026-08-31", "2026-09-15", "2026-09-29", "2026-10-02", "2026-10-15", "2026-10-30"]
    cdf_points = {}
    for target in points:
        valid = [index for index, day in enumerate(window_dates) if day <= target]
        cdf_points[target] = float(cdf[valid[-1]]) if valid else 0.0
    return {
        "schema_version": 1,
        "event": "first close at or below fixed -10% correction threshold",
        "threshold": threshold,
        "probability_space": "posterior_predictive_path_touch",
        "exact_date_forecast": False,
        "exact_date_disclaimer": "10/2 is a sampled trading-session coordinate, not an exact-date forecast.",
        "any_touch_probability": any_probability,
        "window_start": window_dates[0],
        "window_end": window_dates[-1],
        "dates": window_dates,
        "density": [float(value) for value in density],
        "cdf": [float(value) for value in cdf],
        "cdf_points": cdf_points,
        "conditional_on_touch_quantiles": {
            "p25": qdate(0.25), "p50": qdate(0.50), "p75": qdate(0.75),
        },
    }


def _longest_true_run(values: np.ndarray) -> int:
    best = current = 0
    for value in values:
        current = current + 1 if bool(value) else 0
        best = max(best, current)
    return best


def _path_metric_record(values: np.ndarray, p50: np.ndarray, p05: np.ndarray, p95: np.ndarray) -> dict[str, Any]:
    returns = np.diff(values) / values[:-1]
    log_returns = np.diff(np.log(values))
    weekly_values = values[::5]
    weekly_returns = np.diff(weekly_values) / weekly_values[:-1]
    five_day_returns = values[5:] / values[:-5] - 1.0
    drawdown = values / np.maximum.accumulate(values) - 1.0
    signs = np.sign(weekly_returns)
    return {
        "terminal_return": float(values[-1] / values[0] - 1.0),
        "annualized_daily_volatility": float(np.std(log_returns, ddof=1) * math.sqrt(252)),
        "annualized_weekly_volatility": float(np.std(np.diff(np.log(weekly_values)), ddof=1) * math.sqrt(52)),
        "maximum_drawdown": float(drawdown.min()),
        "longest_underwater_sessions": _longest_true_run(drawdown < 0),
        "underwater_share": float((drawdown < 0).mean()),
        "weekly_down_count": int((weekly_returns < 0).sum()),
        "weekly_direction_changes": int((signs[1:] * signs[:-1] < 0).sum()),
        "largest_one_day_loss": float(returns.min()),
        "largest_five_day_loss": float(five_day_returns.min()) if five_day_returns.size else None,
        "trajectory_distance_to_weighted_p50": float(np.mean(np.abs(np.log(values / p50)))),
        "share_below_p05_or_above_p95": float(((values < p05) | (values > p95)).mean()),
    }


def _representative_diagnostics(
    paths: np.ndarray, dates: list[str], snapshot: dict[str, Any], conditional: dict[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    class_index = max(index for index, day in enumerate(conditional["dates"])
                      if day <= snapshot["model"]["classification_date"])
    for key, row in conditional["scenarios"].items():
        values = np.asarray(row["representative_path_values"], dtype=float)
        p50 = np.asarray(row["bands"]["p50"], dtype=float)
        p05 = np.asarray(row["bands"]["p5"], dtype=float)
        p95 = np.asarray(row["bands"]["p95"], dtype=float)
        post_values = values[class_index:]
        result[key] = {
            "member_path_id": int(row["representative_path_id"]),
            "full_member_path_metrics": _path_metric_record(values, p50, p05, p95),
            "post_classification_member_metrics": _path_metric_record(
                post_values, p50[class_index:], p05[class_index:], p95[class_index:]),
            "tail_badge": "WARN" if float(((values < p05) | (values > p95)).mean()) > .10 else "PASS",
        }
    return result


def _distinctness_2027(
    paths: np.ndarray, dates: list[str], weights: np.ndarray,
    snapshot: dict[str, Any], conditional: dict[str, Any],
) -> dict[str, Any]:
    classification = snapshot["model"]["classification_date"]
    class_end = max(index for index, day in enumerate(dates) if day <= classification)
    hit_ath = (paths[:, :class_end + 1] > float(snapshot["ath"])).any(axis=1)
    above_ref = paths[:, class_end] > float(snapshot["reference_price"])
    masks = {"S1": hit_ath, "S2": ~hit_ath & above_ref, "S3": ~hit_ath & ~above_ref}
    indexes_2027 = [index + 1 for index, day in enumerate(dates) if day.startswith("2027-")]
    rows: dict[str, Any] = {}
    terminal_returns: dict[str, np.ndarray] = {}
    normalized_p50: dict[str, np.ndarray] = {}
    for key, mask in masks.items():
        member_indexes = np.flatnonzero(mask)
        member_weights = weights[member_indexes]
        member_weights = member_weights / member_weights.sum()
        start = paths[member_indexes, class_end]
        post_paths = paths[member_indexes, class_end:]
        terminal = post_paths[:, -1] / start - 1.0
        running = np.maximum.accumulate(post_paths, axis=1)
        max_dd = (post_paths / running - 1.0).min(axis=1)
        terminal_returns[key] = terminal
        p50 = np.asarray(conditional["scenarios"][key]["bands"]["p50"], dtype=float)
        segment = p50[indexes_2027] if indexes_2027 else p50[class_end + 1:]
        normalized_p50[key] = segment / segment[0]
        q = np.quantile(terminal, [0.05, 0.50, 0.95])
        rows[key] = {
            "post_classification_return_distribution": {
                "p05": float(q[0]), "p50": float(q[1]), "p95": float(q[2]),
                "mean": float(np.average(terminal, weights=member_weights)),
                "annualized_volatility": float(np.std(np.diff(np.log(post_paths), axis=1)) * math.sqrt(252)),
                "mean_maximum_drawdown": float(np.average(max_dd, weights=member_weights)),
                "count": int(member_indexes.size),
            },
            "p50_2027_return": float(segment[-1] / segment[0] - 1.0),
        }
    pairs = []
    keys = ("S1", "S2", "S3")
    for left_index, left in enumerate(keys):
        for right in keys[left_index + 1:]:
            corr = float(np.corrcoef(normalized_p50[left], normalized_p50[right])[0, 1])
            wasserstein = float(wasserstein_distance(terminal_returns[left], terminal_returns[right]))
            energy = float(energy_distance(terminal_returns[left], terminal_returns[right]))
            vol_diff = abs(float(np.std(terminal_returns[left])) - float(np.std(terminal_returns[right])))
            drawdown_diff = abs(rows[left]["post_classification_return_distribution"]["mean_maximum_drawdown"] - rows[right]["post_classification_return_distribution"]["mean_maximum_drawdown"])
            flagged = corr > 0.98 and wasserstein < 0.02 and energy < 0.02
            pairs.append({
                "pair": f"{left}/{right}",
                "normalized_p50_level_correlation": corr,
                "wasserstein_return_distance": wasserstein,
                "energy_return_distance": energy,
                "terminal_volatility_difference": vol_diff,
                "conditional_max_drawdown_difference": drawdown_diff,
                "distinctness_gate_pass": not flagged,
            })
    pass_gate = all(row["distinctness_gate_pass"] for row in pairs)
    return {
        "schema_version": 1,
        "period": "2027 continuation",
        "thresholds": {"maximum_correlation": 0.98, "minimum_wasserstein": 0.02, "minimum_energy": 0.02},
        "scenarios": rows,
        "pairs": pairs,
        "distinct_three_scenario_continuation_allowed": pass_gate,
        "gate_pass": pass_gate,
        "display_disclosure": (
            "2027: scenario-specific continuation validated"
            if pass_gate else
            "2026: scenario-specific conditional distribution; 2027: common-model continuation; scenario-specific starting level only"
        ),
    }


def _model_content(payload: dict[str, Any]) -> dict[str, Any]:
    value = deepcopy(payload)
    for key in ("generated_at", "model_content_sha256", "build_receipt", "build_receipt_sha256", "validation", "runtime_gate"):
        value.pop(key, None)
    return value


def _build_receipt_content(payload: dict[str, Any]) -> dict[str, Any]:
    value = deepcopy(payload)
    value.pop("build_receipt_sha256", None)
    return value


def _number(value: Any, label: str, errors: list[str], *, positive: bool = False,
            fraction: bool = False) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        errors.append(f"{label} must be a finite non-boolean number")
        return None
    number = float(value)
    if positive and number <= 0:
        errors.append(f"{label} must be positive")
    if fraction and not 0 <= number <= 1:
        errors.append(f"{label} must be in [0,1]")
    return number


def validate_candidate_v5_1(payload: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    errors: list[str] = []
    if payload.get("candidate_id") != CANDIDATE_ID:
        errors.append("candidate_id mismatch")
    if payload.get("identity", {}).get("is_rcfhs") is not False:
        errors.append("legacy-prior identity must not claim RCFHS")
    dates = payload.get("conditional_distribution", {}).get("dates", [])
    try:
        parsed_dates = [date.fromisoformat(day) for day in dates]
    except (TypeError, ValueError):
        parsed_dates = []
        errors.append("dates must be ISO dates")
    if not dates or len(dates) != len(set(dates)) or parsed_dates != sorted(parsed_dates):
        errors.append("dates must be non-empty, unique, and strictly sorted")
    scenarios = payload.get("conditional_distribution", {}).get("scenarios", {})
    probabilities = []
    total_paths = 0
    quantile_keys = ("p5", "p10", "p25", "p50", "p75", "p90", "p95")
    for key in ("S1", "S2", "S3"):
        row = scenarios.get(key, {})
        probability = _number(row.get("probability"), f"{key}.probability", errors, fraction=True)
        if probability is not None:
            probabilities.append(probability)
        count = _number(row.get("path_count"), f"{key}.path_count", errors, positive=True)
        if count is not None:
            total_paths += int(count)
        _number(row.get("weighted_effective_sample_size"), f"{key}.ess", errors, positive=True)
        ess_value = row.get("weighted_effective_sample_size")
        if isinstance(ess_value, (int, float)) and not isinstance(ess_value, bool):
            expected_visibility = {
                "p25_p75": float(ess_value) >= 500,
                "p10_p90": float(ess_value) >= 1000,
                "p05_p95": float(ess_value) >= 2000,
            }
            if row.get("band_visibility") != expected_visibility:
                errors.append(f"{key} ESS visibility mismatch")
        if row.get("probability_space") != "scenario_conditional":
            errors.append(f"{key} probability-space mismatch")
        member = row.get("representative_path_values", [])
        if len(member) != len(dates):
            errors.append(f"{key} representative length mismatch")
        for index, value in enumerate(member):
            _number(value, f"{key}.representative[{index}]", errors, positive=True)
        bands = row.get("bands", {})
        matrix = []
        for quantile in quantile_keys:
            values = bands.get(quantile, [])
            if len(values) != len(dates):
                errors.append(f"{key}.{quantile} length mismatch")
            checked = [_number(value, f"{key}.{quantile}[{index}]", errors, positive=True)
                       for index, value in enumerate(values)]
            matrix.append(checked)
        if all(len(values) == len(dates) for values in (bands.get(q, []) for q in quantile_keys)):
            numeric = np.asarray(matrix, dtype=float)
            if not np.all(np.diff(numeric, axis=0) >= -1e-10):
                errors.append(f"{key} quantiles are not monotone")
    if len(probabilities) == 3 and not math.isclose(sum(probabilities), 1.0, abs_tol=1e-10):
        errors.append("scenario probabilities do not sum to one")
    if total_paths != payload.get("prior", {}).get("path_count"):
        errors.append("scenario path counts do not equal prior path count")
    posterior = payload.get("posterior_diagnostics", {})
    _number(posterior.get("weight_sum"), "posterior.weight_sum", errors, positive=True)
    _number(posterior.get("effective_sample_size"), "posterior.ess", errors, positive=True)
    for fit in posterior.get("view_fit", []):
        residual = _number(fit.get("residual"), f"{fit.get('view_id')}.residual", errors)
        tolerance = _number(fit.get("tolerance"), f"{fit.get('view_id')}.tolerance", errors, positive=True)
        if residual is not None and tolerance is not None and abs(residual) > tolerance:
            errors.append(f"posterior residual exceeds tolerance: {fit.get('view_id')}")
    for row in payload.get("evidence_views", []):
        status = row.get("time_alignment_status")
        if status not in TIME_ALIGNMENT_STATUSES:
            errors.append(f"invalid time alignment status: {row.get('view_id')}")
        if row.get("used_numerically") and status in {"BLOCKED_NEEDS_REFORECAST", "REFERENCE_ONLY_STALE", "REALIZED_TRUE", "REALIZED_FALSE"}:
            errors.append(f"non-current view used numerically: {row.get('view_id')}")
        if row.get("used_numerically") and (row.get("is_endogenous_to_current_model") or not row.get("transport_validated") and status == "SURVIVAL_CONDITIONED"):
            errors.append(f"circular/unvalidated transported view used: {row.get('view_id')}")
        try:
            available = _aware(row.get("available_at"))
            cutoff = _aware(payload.get("knowledge_cutoff"))
            if available > cutoff:
                errors.append(f"future evidence available_at: {row.get('view_id')}")
        except (TypeError, ValueError):
            errors.append(f"naive/invalid evidence available_at: {row.get('view_id')}")
        if row.get("unit") == "fraction" and row.get("target") is not None:
            _number(row["target"], f"{row.get('view_id')}.target", errors, fraction=True)
    for event in payload.get("event_states", []):
        jump = _number(event.get("price_jump"), f"{event.get('event_id')}.price_jump", errors)
        if event.get("mapping_status") != "approved" and jump not in (None, 0.0):
            errors.append("unmapped event jump must equal zero")
    timing = payload.get("correction_timing_distribution", {})
    if timing.get("exact_date_forecast") is not False:
        errors.append("correction timing must explicitly reject exact-date semantics")
    if len(timing.get("dates", [])) != len(timing.get("density", [])) or len(timing.get("dates", [])) != len(timing.get("cdf", [])):
        errors.append("timing distribution length mismatch")
    if payload.get("distinctness_2027", {}).get("gate_pass") is False and payload.get("display_contract", {}).get("three_distinct_2027_paths") is not False:
        errors.append("failed 2027 distinctness gate must block three distinct paths")
    for cluster in posterior.get("dependency_diagnostics", {}).get("clusters", []):
        capped = _number(cluster.get("capped_strength"), "cluster.capped_strength", errors)
        cap = _number(cluster.get("cap"), "cluster.cap", errors, positive=True)
        if capped is not None and cap is not None and capped > cap + 1e-12:
            errors.append(f"dependency cluster strength cap exceeded: {cluster.get('dependency_cluster_id')}")
    expected_model_hash = canonical_hash(_model_content(payload))
    if payload.get("model_content_sha256") != expected_model_hash:
        errors.append("model_content_sha256 mismatch")
    receipt = payload.get("build_receipt", {})
    expected_receipt_hash = canonical_hash(_build_receipt_content(receipt))
    if payload.get("build_receipt_sha256") != expected_receipt_hash:
        errors.append("build_receipt_sha256 mismatch")
    if root is not None:
        source = payload.get("source_snapshot", {})
        snapshot_path = root / str(source.get("path", ""))
        if not snapshot_path.is_file() or file_hash(snapshot_path) != source.get("sha256"):
            errors.append("source snapshot hash changed")
        else:
            current = json.loads(snapshot_path.read_text(encoding="utf-8"))
            for key in ("asof", "snapshot_id", "revision"):
                if current.get(key) != source.get(key):
                    errors.append(f"source snapshot {key} changed")
        for row in payload.get("evidence_views", []):
            source_path = root / str(row.get("source_path", ""))
            if not source_path.is_file() or file_hash(source_path) != row.get("source_sha256"):
                errors.append(f"evidence source hash changed: {row.get('view_id')}")
        try:
            paths, _ = reproduce_legacy_prior(
                json.loads(snapshot_path.read_text(encoding="utf-8")),
                n_paths=int(payload["prior"]["path_count"]),
            )
            anchor = float(payload["source_snapshot"]["anchor"])
            for key in ("S1", "S2", "S3"):
                row = scenarios[key]
                path_id = int(row["representative_path_id"])
                expected = np.concatenate(([anchor], paths[path_id]))
                if not np.allclose(expected, row["representative_path_values"], atol=0.005):
                    errors.append(f"{key} representative replay mismatch")
        except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError):
            errors.append("representative replay failed")
    return {"ok": not errors, "errors": errors, "model_content_sha256": expected_model_hash}


def assemble_candidate_v5_1(root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    now = _aware(now)
    snapshot_path = root / "data/scenarios/nasdaq_latest.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    contracts = load_contracts(root)
    model_contract = contracts["scenario_v5_model"]
    paths, dates = reproduce_legacy_prior(snapshot, n_paths=int(model_contract["prior"]["path_count"]))
    evidence, dependency = build_evidence_registry_v5_1(root, snapshot, contracts)
    numerical = [row for row in evidence if row.get("used_numerically")]
    matrix = np.empty((paths.shape[0], 0), dtype=float)
    if numerical:
        raise ScenarioV51Error("no V5.1 numerical view condition adapter was approved")
    weights, posterior = entropy_pool(matrix, numerical, model_contract["entropy_pooling"])
    posterior.update({
        "weight_sum": float(weights.sum()),
        "effective_sample_size": float(1.0 / np.square(weights).sum()),
        "maximum_path_weight": float(weights.max()),
        "top_one_percent_weight_share": float(np.sort(weights)[-math.ceil(len(weights) * .01):].sum()),
        "view_fit": [],
        "gates": {"ess": True, "maximum_path_weight": True, "top_one_percent_share": True},
        "gates_pass": True,
        "dependency_diagnostics": dependency,
    })
    conditional = build_conditional_outputs(paths, dates, weights, snapshot, model_contract)
    distinctness = _distinctness_2027(paths, dates, weights, snapshot, conditional)
    timing = _first_touch_distribution(paths, dates, weights, float(snapshot["corr10"]))
    identity = deepcopy(model_contract["identity"])
    identity.update({
        "candidate_id": CANDIDATE_ID,
        "model_family": "v5_1_time_aligned_evidence_conditioned_joint_path_ensemble",
        "view_update_engine": "entropy_pooling_dependency_capped_v2",
        "promotion_state": "research_candidate_degraded_no_approved_numerical_views",
    })
    payload: dict[str, Any] = {
        "schema_version": 2,
        "status": "degraded",
        "candidate_id": CANDIDATE_ID,
        "display_name": "Scenario V5.1 · Time-Aligned Research Candidate",
        "banner": "RESEARCH CANDIDATE · NOT OFFICIAL · NO APPROVED NUMERICAL VIEWS",
        "asof": snapshot["asof"],
        "knowledge_cutoff": snapshot["generated_at"],
        "generated_at": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "identity": identity,
        "source_snapshot": {
            "path": snapshot_path.relative_to(root).as_posix(),
            "sha256": file_hash(snapshot_path),
            "asof": snapshot["asof"],
            "snapshot_id": snapshot.get("snapshot_id"),
            "revision": snapshot.get("revision"),
            "anchor": float(snapshot["anchor"]),
            "ath": float(snapshot["ath"]),
            "corr10": float(snapshot["corr10"]),
            "reference_price": float(snapshot["reference_price"]),
            "classification_date": snapshot["model"]["classification_date"],
        },
        "pit_integrity": {
            "strict_available_at": True,
            "future_data_used": False,
            "candidate_asof": snapshot["asof"],
            "knowledge_cutoff": snapshot["generated_at"],
            "numerical_view_count": len(numerical),
        },
        "prior": {
            "engine": identity["prior_engine"],
            "path_count": int(paths.shape[0]),
            "horizon_sessions": int(paths.shape[1]),
            "seed": int(snapshot["model"]["seed"]),
            "probability_space": "posterior_predictive_unconditional",
            "limitation": "legacy GBM prior retained; no approved PIT long-history V6 dataset exists",
        },
        "evidence_views": evidence,
        "event_states": event_states(snapshot, evidence, contracts["scenario_v5_event_impact"]),
        "posterior_diagnostics": posterior,
        "conditional_distribution": conditional,
        "correction_timing_distribution": timing,
        "representative_diagnostics": _representative_diagnostics(paths, dates, snapshot, conditional),
        "distinctness_2027": distinctness,
        "display_contract": {
            "primary_line": "conditional_weighted_p50",
            "primary_line_style": "thick_solid",
            "secondary_line": "one_actual_member",
            "secondary_line_style": "thin_dotted",
            "secondary_label": "ONE SIMULATED MEMBER / EXACT DATES ARE NOT FORECAST",
            "unconditional_fan_label": "posterior_predictive_unconditional",
            "risk_ribbon_label": "-10%선 누적 터치확률 저/중/고",
            "exclude_hidden_bands_from_scale": True,
            "three_distinct_2027_paths": bool(distinctness["gate_pass"]),
            "continuation_disclosure": distinctness["display_disclosure"],
        },
        "unused_adapters": {
            "liquidity": "NOT USED NUMERICALLY — no approved PIT adapter",
            "cross_asset": "NOT USED NUMERICALLY — no approved PIT adapter",
            "ai_capital_cycle": "NOT USED NUMERICALLY — no approved PIT adapter",
        },
        "promotion": {
            "state": "blocked_pending_shadow_validation_and_human_approval",
            "official_snapshot_mutated": False,
            "v6_promotion_allowed": False,
        },
    }
    payload["model_content_sha256"] = canonical_hash(_model_content(payload))
    receipt = {
        "artifact_type": "scenario_v5_1_research_candidate",
        "candidate_id": CANDIDATE_ID,
        "model_content_sha256": payload["model_content_sha256"],
        "generated_at": payload["generated_at"],
        "source_snapshot_sha256": payload["source_snapshot"]["sha256"],
        "build_context": _git_state(root),
    }
    payload["build_receipt"] = receipt
    payload["build_receipt_sha256"] = canonical_hash(_build_receipt_content(receipt))
    validation = validate_candidate_v5_1(payload, root)
    if not validation["ok"]:
        raise ScenarioV51Error("; ".join(validation["errors"]))
    payload["validation"] = {"ok": True, "errors": []}
    return payload


def build_candidate_v5_1(
    root: Path, *, force: bool = False, now: datetime | None = None,
) -> tuple[Path, dict[str, Any], bool]:
    target = root / CANDIDATE_RELATIVE
    payload = assemble_candidate_v5_1(root, now=now)
    if target.is_file() and not force:
        current = json.loads(target.read_text(encoding="utf-8"))
        if validate_candidate_v5_1(current, root)["ok"] and current.get("model_content_sha256") == payload["model_content_sha256"]:
            return target, current, False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target, payload, True


def _trading_day_age(asof: str, today: date) -> int:
    start = date.fromisoformat(asof)
    if today <= start:
        return 0
    return int(np.busday_count(start, today))


def load_current_candidate(
    root: Path, now: datetime, maximum_age_trading_days: int = 1,
) -> dict[str, Any]:
    """Load V5.1 with current-source, PIT, future-build, and staleness gates."""
    path = root / CANDIDATE_RELATIVE
    if not path.is_file():
        return {"status": "unavailable", "reason": "V5.1 candidate file is missing", "runtime_gate": {"display_eligible": False}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        validation = validate_candidate_v5_1(payload, root)
        reasons = list(validation["errors"])
        current = _aware(now).astimezone(timezone.utc)
        generated = _aware(payload["generated_at"]).astimezone(timezone.utc)
        if generated > current + timedelta(minutes=5):
            reasons.append("candidate build timestamp is in the future")
        age = _trading_day_age(payload["asof"], current.date())
        if age > maximum_age_trading_days:
            reasons.append(f"candidate is stale: {age} trading days old")
        cutoff = _aware(payload["knowledge_cutoff"])
        for row in payload.get("evidence_views", []):
            if _aware(row["available_at"]) > cutoff:
                reasons.append(f"evidence PIT violation: {row.get('view_id')}")
        result = deepcopy(payload)
        result["runtime_gate"] = {
            "display_eligible": not reasons,
            "maximum_age_trading_days": maximum_age_trading_days,
            "age_trading_days": age,
            "checked_at": current.isoformat(timespec="seconds"),
            "reasons": reasons,
        }
        if reasons:
            result["status"] = "stale_or_invalid"
            result["banner"] = "STALE/INVALID RESEARCH CANDIDATE — OFFICIAL FALLBACK ACTIVE"
        return result
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        return {"status": "unavailable", "reason": str(exc), "runtime_gate": {"display_eligible": False, "reasons": [str(exc)]}}


def verify_candidate_v5_1(root: Path, path: Path | None = None) -> dict[str, Any]:
    candidate_path = path or root / CANDIDATE_RELATIVE
    if not candidate_path.is_file():
        return {"ok": False, "errors": [f"candidate not found: {candidate_path}"]}
    payload = json.loads(candidate_path.read_text(encoding="utf-8"))
    result = validate_candidate_v5_1(payload, root)
    result["path"] = candidate_path.as_posix()
    return result
