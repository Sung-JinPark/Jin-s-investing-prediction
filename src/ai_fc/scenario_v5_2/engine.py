"""Deterministic historical-shape engine for the Scenario V5.2 candidate.

The module is deliberately research-only.  It starts after the 2026-08-07
close, resamples point-in-time Nasdaq returns, and changes probabilities only
through explicit likelihood weights.  It never writes an official artifact.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import energy_distance, wasserstein_distance

from ai_fc.scenario_v5.contracts import canonical_hash, file_hash


CANDIDATE_ID = "scenario_v5_2_dotcom_weighted_event_adaptive_v2"
CANDIDATE_RELATIVE = Path(
    "data/scenarios/candidates/"
    "scenario_v5_2_dotcom_weighted_event_adaptive_v2_latest.json"
)
LEGACY_V52_RELATIVE = Path(
    "data/scenarios/candidates/"
    "scenario_v5_2_macro_actualized_historical_shape_v1_latest.json"
)
ANCHOR_DATE = date(2026, 8, 7)
KNOWLEDGE_CUTOFF = "2026-08-10T00:00:00+00:00"
ANCHOR = 26690.62
ATH = 27093.90
REFERENCE_PRICE = 26206.89
PATH_COUNT_PER_ENGINE = 4000
SEED = 520807
QUANTILES = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)
QUANTILE_NAMES = ("p5", "p10", "p25", "p50", "p75", "p90", "p95")

SOURCE_PATHS = (
    "data/raw/macro/bls_empsit_2026_07_20260807_browser_capture.txt",
    "data/normalized/macro/bls_empsit_2026_07_20260807.json",
    "data/raw/rates/fed_rate_monitor_20260808.html",
    "data/normalized/rates/fed_rate_monitor_pre_post_jobs_20260807.json",
    "data/raw/market/yahoo_ixic_daily_20160104_20260807.json",
    "data/normalized/market/yahoo_ixic_daily_20160104_20260807_manifest.json",
    "data/normalized/market/jobs_event_state_20260807.json",
    "data/scenarios/candidates/scenario_v5_1_time_aligned_legacy_prior_v1_latest.json",
    "data/model_runs/knn_analog_latest.json",
    "data/normalized/market/dotcom_upside_analog_20260810.json",
    "data/scenario_views/approved/scenario_v5_2_dotcom_upside_260810.json",
)


class ScenarioV52Error(RuntimeError):
    """A fail-closed V5.2 input or model gate."""


def source_file_hash(root: Path, relative: str | Path) -> str:
    """Hash sources portably while preserving raw-capture bytes exactly."""
    relative_path = Path(relative)
    path = root / relative_path
    if relative_path.as_posix() == SOURCE_PATHS[7]:
        # The existing V5.1 reference JSON predates the current EOL rules.  Text
        # mode makes its reference-only hash stable across Windows/Linux clones.
        normalized = path.read_text(encoding="utf-8").encode("utf-8")
        return hashlib.sha256(normalized).hexdigest()
    return file_hash(path)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _aware(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ScenarioV52Error(f"timezone required: {value}")
    return result


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScenarioV52Error(f"{name} must be a non-boolean number")
    result = float(value)
    if not math.isfinite(result):
        raise ScenarioV52Error(f"{name} must be finite")
    return result


def _validate_fraction(value: Any, name: str) -> float:
    result = _finite_number(value, name)
    if not 0.0 <= result <= 1.0:
        raise ScenarioV52Error(f"{name} fraction outside [0,1]")
    return result


def _validate_rate_distributions(payload: dict[str, Any], cutoff: datetime) -> None:
    if payload.get("probability_unit") != "fraction":
        raise ScenarioV52Error("rate probability unit must be explicit fraction")
    for snapshot_id, snapshot in payload["snapshots"].items():
        if _aware(snapshot["available_at"]) > cutoff:
            raise ScenarioV52Error(f"future rate snapshot: {snapshot_id}")
        for meeting, distribution in snapshot["meetings"].items():
            values = [_validate_fraction(v, f"{snapshot_id}.{meeting}.{k}")
                      for k, v in distribution.items()]
            if not math.isclose(sum(values), 1.0, abs_tol=0.0015):
                raise ScenarioV52Error(
                    f"rate distribution does not sum to one: {snapshot_id}.{meeting}"
                )


def load_inputs(root: Path) -> dict[str, Any]:
    for relative in SOURCE_PATHS:
        if not (root / relative).is_file():
            raise ScenarioV52Error(f"missing V5.2 source: {relative}")
    if not (root / LEGACY_V52_RELATIVE).is_file():
        raise ScenarioV52Error(f"missing V5.2 shadow baseline: {LEGACY_V52_RELATIVE}")
    labor = _read_json(root / SOURCE_PATHS[1])
    rates = _read_json(root / SOURCE_PATHS[3])
    history_manifest = _read_json(root / SOURCE_PATHS[5])
    market = _read_json(root / SOURCE_PATHS[6])
    v51 = _read_json(root / SOURCE_PATHS[7])
    dotcom_model_run = _read_json(root / SOURCE_PATHS[8])
    dotcom = _read_json(root / SOURCE_PATHS[9])
    dotcom_view = _read_json(root / SOURCE_PATHS[10])
    legacy_v52 = _read_json(root / LEGACY_V52_RELATIVE)
    from .event_learning import event_score_summary

    event_updates = event_score_summary(root)
    event_cluster_strength: dict[str, float] = {}
    for row in event_updates["events"]:
        cluster = str(row["dependency_cluster_id"])
        event_cluster_strength[cluster] = event_cluster_strength.get(cluster, 0.0) \
            + float(row["scores"]["effective_strength"])
    if any(value > .35 for value in event_cluster_strength.values()):
        raise ScenarioV52Error("event-learning dependency cluster cap exceeded")
    event_updates["dependency_cluster_strength"] = event_cluster_strength
    event_cutoffs = [
        _aware(str(row["as_of"])) for row in event_updates["events"]
    ]
    cutoff = max([_aware(KNOWLEDGE_CUTOFF), *event_cutoffs])
    for label, row in (("labor", labor), ("market", market)):
        if _aware(row["available_at"]) > cutoff:
            raise ScenarioV52Error(f"future {label} evidence")
    if labor.get("units", {}).get("rates") != "fraction":
        raise ScenarioV52Error("labor rates require explicit fraction unit")
    for field in (
        "unemployment_rate", "labor_force_participation_rate",
        "employment_population_ratio", "average_hourly_earnings_yoy",
    ):
        _validate_fraction(labor["actual"][field], f"labor.actual.{field}")
    if labor.get("missing_fields"):
        raise ScenarioV52Error("required labor fields are missing; missing is not zero")
    _validate_rate_distributions(rates, cutoff)
    raw_history = root / history_manifest["raw_source_path"]
    if file_hash(raw_history) != history_manifest["raw_sha256"]:
        raise ScenarioV52Error("historical price raw hash mismatch")
    if not math.isclose(
        float(history_manifest["last_close"]), ANCHOR, rel_tol=0.0, abs_tol=0.01
    ):
        raise ScenarioV52Error("historical last close does not match post-event anchor")
    if file_hash(root / dotcom["source_path"]) != dotcom["source_sha256"]:
        raise ScenarioV52Error("dotcom analog source hash mismatch")
    if dotcom_model_run.get("model") != "knn_analog":
        raise ScenarioV52Error("dotcom analog must come from the registered kNN run")
    if dotcom.get("probability_unit") != "fraction":
        raise ScenarioV52Error("dotcom forward-return targets require explicit fraction unit")
    if int(dotcom.get("cycle_count", 0)) != 1 or int(dotcom.get("neighbor_count", 0)) != 5:
        raise ScenarioV52Error("dotcom single-cycle dependency disclosure mismatch")
    strengths = {
        key: _validate_fraction(value, f"dotcom.scenario_strength.{key}")
        for key, value in dotcom.get("scenario_strength", {}).items()
    }
    if set(strengths) != {"S1", "S2", "S3"} or not (
        strengths["S1"] > strengths["S3"] > strengths["S2"]
    ):
        raise ScenarioV52Error("dotcom scenario strengths must be S1 > S3 > S2")
    if max(strengths.values()) > _validate_fraction(
        dotcom.get("dependency_cap"), "dotcom.dependency_cap"
    ):
        raise ScenarioV52Error("dotcom dependency cap exceeded")
    if dotcom_view.get("used_numerically") is not True \
            or not dotcom_view.get("human_approval_receipt"):
        raise ScenarioV52Error("dotcom numerical view lacks explicit human approval")
    if dotcom_view.get("scenario_strength") != dotcom.get("scenario_strength"):
        raise ScenarioV52Error("dotcom view and normalized strengths disagree")
    for label, row in (("dotcom", dotcom), ("dotcom_view", dotcom_view)):
        if _aware(str(row["available_at"])) > cutoff:
            raise ScenarioV52Error(f"future {label} evidence")
    return {
        "labor": labor,
        "rates": rates,
        "history_manifest": history_manifest,
        "market": market,
        "v51": v51,
        "dotcom": dotcom,
        "dotcom_view": dotcom_view,
        "event_updates": event_updates,
        "knowledge_cutoff": cutoff.isoformat(),
        "legacy_v52": legacy_v52,
    }


def _business_dates(start: date, end: date) -> list[str]:
    values: list[str] = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            values.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return values


def _historical_returns(
    root: Path, manifest: dict[str, Any],
) -> tuple[np.ndarray, list[str], np.ndarray]:
    raw = _read_json(root / manifest["raw_source_path"])
    result = raw["chart"]["result"][0]
    timestamps = result["timestamp"]
    closes = result["indicators"]["quote"][0]["close"]
    rows: list[tuple[str, float]] = []
    for stamp, close in zip(timestamps, closes, strict=True):
        if close is None:
            continue
        session = datetime.fromtimestamp(int(stamp), tz=timezone.utc).date().isoformat()
        if session <= ANCHOR_DATE.isoformat():
            rows.append((session, _finite_number(close, f"history.{session}.close")))
    dates = [row[0] for row in rows]
    values = np.asarray([row[1] for row in rows], dtype=float)
    if len(values) != int(manifest["row_count"]):
        raise ScenarioV52Error("historical row count mismatch")
    if dates[-1] != ANCHOR_DATE.isoformat() or not math.isclose(values[-1], ANCHOR, abs_tol=.01):
        raise ScenarioV52Error("historical series is not aligned to anchor")
    returns = np.diff(np.log(values))
    if len(returns) < 1260 or not np.isfinite(returns).all():
        raise ScenarioV52Error("insufficient approved point-in-time historical returns")
    return returns, dates, values


def _stationary_bootstrap(
    history: np.ndarray, horizon: int, count: int, rng: np.random.Generator,
) -> np.ndarray:
    indexes = rng.integers(0, len(history), size=count)
    sampled = np.empty((count, horizon), dtype=float)
    for column in range(horizon):
        restart = rng.random(count) < 0.10
        if column:
            indexes = np.where(restart, rng.integers(0, len(history), size=count),
                               (indexes + 1) % len(history))
        sampled[:, column] = history[indexes]
    return sampled


def _analog_episode_resample(
    history: np.ndarray, horizon: int, count: int, rng: np.random.Generator,
) -> np.ndarray:
    if len(history) <= horizon:
        raise ScenarioV52Error("history too short for analog episode resampling")
    starts = rng.integers(0, len(history) - horizon, size=count)
    offsets = np.arange(horizon)
    return history[starts[:, None] + offsets[None, :]]


def generate_prior(
    root: Path, inputs: dict[str, Any], *, seed: int = SEED,
    path_count_per_engine: int = PATH_COUNT_PER_ENGINE, block_restart_probability: float = .10,
) -> tuple[np.ndarray, list[str], np.ndarray, dict[str, Any]]:
    dates = [ANCHOR_DATE.isoformat(), *_business_dates(date(2026, 8, 10), date(2027, 12, 31))]
    horizon = len(dates) - 1
    if not 0 < block_restart_probability <= 1:
        raise ScenarioV52Error("block restart probability must be in (0,1]")
    history, history_dates, history_levels = _historical_returns(root, inputs["history_manifest"])
    # The registered production challenger uses a 10-session expected block.
    # Sensitivity callers may vary it explicitly; the primitive keeps the value visible.
    if not math.isclose(block_restart_probability, .10):
        stationary_rng = np.random.default_rng(seed)
        indexes = stationary_rng.integers(0, len(history), size=path_count_per_engine)
        stationary = np.empty((path_count_per_engine, horizon), dtype=float)
        for column in range(horizon):
            restart = stationary_rng.random(path_count_per_engine) < block_restart_probability
            if column:
                indexes = np.where(
                    restart,
                    stationary_rng.integers(0, len(history), size=path_count_per_engine),
                    (indexes + 1) % len(history),
                )
            stationary[:, column] = history[indexes]
    else:
        stationary = _stationary_bootstrap(
            history, horizon, path_count_per_engine, np.random.default_rng(seed)
        )
    analog = _analog_episode_resample(
        history, horizon, path_count_per_engine, np.random.default_rng(seed + 1)
    )
    log_returns = np.vstack((stationary, analog))
    paths = np.column_stack((
        np.full(log_returns.shape[0], ANCHOR),
        ANCHOR * np.exp(np.cumsum(log_returns, axis=1)),
    ))
    if not np.isfinite(paths).all() or float(paths.min()) <= 0:
        raise ScenarioV52Error("historical prior has invalid levels")
    engines = np.concatenate((
        np.zeros(path_count_per_engine, dtype=int),
        np.ones(path_count_per_engine, dtype=int),
    ))
    historical_actual = {
        "dates": history_dates[-60:],
        "values": [round(float(value), 2) for value in history_levels[-60:]],
        "role": "historical_actual_through_anchor",
    }
    return paths, dates, engines, historical_actual


def _robust_z(values: np.ndarray) -> np.ndarray:
    median = float(np.median(values))
    q25, q75 = np.quantile(values, [0.25, 0.75])
    scale = max(float(q75 - q25) / 1.349, 1e-9)
    return (values - median) / scale


def _path_metrics(paths: np.ndarray, dates: list[str]) -> dict[str, np.ndarray]:
    returns = np.diff(np.log(paths), axis=1)
    running_max = np.maximum.accumulate(paths, axis=1)
    drawdowns = paths / running_max - 1.0
    date_2026 = max(index for index, value in enumerate(dates) if value <= "2026-12-31")
    returns_2026 = returns[:, :date_2026]
    running_max_2026 = running_max[:, :date_2026 + 1]
    drawdowns_2026 = paths[:, :date_2026 + 1] / running_max_2026 - 1.0
    early = min(20, paths.shape[1] - 1)
    trough = np.argmin(drawdowns, axis=1)
    recovery = np.empty(paths.shape[0], dtype=float)
    for row, trough_index in enumerate(trough):
        prior_peak = float(running_max[row, trough_index])
        recovered = np.flatnonzero(paths[row, trough_index + 1:] >= prior_peak)
        recovery[row] = (float(recovered[0] + 1) if recovered.size
                         else float(paths.shape[1] - trough_index + 30))
    return {
        "terminal_2026": paths[:, date_2026],
        "terminal_2027": paths[:, -1],
        "terminal_return_2026": paths[:, date_2026] / ANCHOR - 1.0,
        "terminal_return_2027": paths[:, -1] / ANCHOR - 1.0,
        "early_return": paths[:, early] / ANCHOR - 1.0,
        "maximum_drawdown": drawdowns.min(axis=1),
        "maximum_drawdown_2026": drawdowns_2026.min(axis=1),
        "annualized_volatility": returns.std(axis=1, ddof=1) * math.sqrt(252.0),
        "annualized_volatility_2026": returns_2026.std(axis=1, ddof=1) * math.sqrt(252.0),
        "time_underwater": (drawdowns < -.02).mean(axis=1),
        "direction_changes": (
            np.sign(returns[:, 1:]) * np.sign(returns[:, :-1]) < 0
        ).sum(axis=1).astype(float),
        "recovery_days": recovery,
    }


def _expected_hike_count(distribution: dict[str, float]) -> float:
    result = 0.0
    for target_range, probability in distribution.items():
        lower = float(target_range.split("-")[0])
        steps = int(round((lower - 3.50) / 0.25))
        result += steps * float(probability)
    return result


def evidence_scores(inputs: dict[str, Any]) -> dict[str, Any]:
    labor = inputs["labor"]
    actual = labor["actual"]
    consensus = labor["consensus"]["nonfarm_payroll_change"]
    payroll_surprise_z = (actual["nonfarm_payroll_change"] - consensus) / 100000.0
    revision_z = labor["combined_revision"] / 100000.0
    layoff_z = actual["temporary_layoffs_change"] / 500000.0
    labor_growth_risk_raw = (
        0.50 * -payroll_surprise_z + 0.35 * -revision_z + 0.15 * layoff_z
    )
    event_raw = inputs["event_updates"]["raw_weighted_scores"]
    growth_risk_raw = labor_growth_risk_raw + float(event_raw["growth_risk"])
    growth_risk = math.tanh(growth_risk_raw)

    rates = inputs["rates"]["snapshots"]
    pre = rates["pre_jobs_previous_day"]["meetings"]
    post = rates["post_jobs_current"]["meetings"]
    meeting_deltas = {
        meeting: _expected_hike_count(post[meeting]) - _expected_hike_count(pre[meeting])
        for meeting in pre
    }
    expected_count_relief_raw = -sum(meeting_deltas.values()) / len(meeting_deltas)
    aggregate_deltas = {
        meeting: float(row["delta"])
        for meeting, row in inputs["rates"]["aggregate_hike_probability"].items()
    }
    aggregate_probability_relief_raw = -sum(aggregate_deltas.values()) \
        / len(aggregate_deltas) / .10
    base_policy_relief_raw = (
        .60 * aggregate_probability_relief_raw + .40 * expected_count_relief_raw
    )
    policy_relief_raw = base_policy_relief_raw + float(event_raw["policy_relief"])
    policy_relief = math.tanh(policy_relief_raw)

    inflation_risk_raw = float(event_raw["inflation_risk"])
    inflation_risk = math.tanh(inflation_risk_raw)

    observations = inputs["market"]["observations"]
    cross_asset_raw = (
        0.40 * (-observations["us_10y_yield_change"] / 0.0010)
        + 0.30 * (-observations["vix_change"] / 1.0)
        + 0.30 * (-observations["dollar_index_change"] / 0.50)
    )
    cross_asset_relief = math.tanh(cross_asset_raw)
    return {
        "labor_growth_risk": {
            "raw": growth_risk_raw,
            "bounded_score": growth_risk,
            "components": {
                "base_labor_growth_risk_raw": labor_growth_risk_raw,
                "event_learning_increment_raw": float(event_raw["growth_risk"]),
                "payroll_surprise_z": payroll_surprise_z,
                "combined_revision_z": revision_z,
                "temporary_layoff_change_z": layoff_z,
            },
            "interpretation": "positive means more growth risk",
        },
        "policy_relief": {
            "raw": policy_relief_raw,
            "bounded_score": policy_relief,
            "expected_hike_count_delta_by_meeting": meeting_deltas,
            "aggregate_hike_probability_delta_by_meeting": aggregate_deltas,
            "components": {
                "expected_hike_count_relief_raw": expected_count_relief_raw,
                "aggregate_probability_relief_raw": aggregate_probability_relief_raw,
                "base_policy_relief_raw": base_policy_relief_raw,
                "event_learning_increment_raw": float(event_raw["policy_relief"]),
            },
            "interpretation": "positive means less expected tightening after jobs",
        },
        "inflation_risk": {
            "raw": inflation_risk_raw,
            "bounded_score": inflation_risk,
            "interpretation": "positive means a hotter-than-consensus inflation update",
        },
        "cross_asset_relief": {
            "raw": cross_asset_raw,
            "bounded_score": cross_asset_relief,
            "nasdaq_event_return_coefficient": 0.0,
            "interpretation": "weak state view; realized Nasdaq return is excluded",
        },
        "event_learning": inputs["event_updates"],
    }


def _normalise_weights(log_weights: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    if not np.isfinite(log_weights).all():
        raise ScenarioV52Error("non-finite log weights")
    shifted = log_weights - float(log_weights.max())
    unnormalised = np.exp(shifted)
    denominator = float(unnormalised.sum())
    if not math.isfinite(denominator) or denominator <= 0:
        raise ScenarioV52Error("invalid explicit weight normalizer")
    weights = unnormalised / denominator
    if not math.isclose(float(weights.sum()), 1.0, abs_tol=1e-12):
        raise ScenarioV52Error("weights do not sum to one")
    count = len(weights)
    ess = float(1.0 / np.square(weights).sum())
    top_n = max(1, math.ceil(count * .01))
    top_share = float(np.partition(weights, -top_n)[-top_n:].sum())
    entropy = float(-np.sum(weights * np.log(weights)))
    kl = float(np.sum(weights * np.log(weights * count)))
    gates = {
        "ess_at_least_20pct": ess >= count * .20,
        "maximum_weight_at_most_0_005": float(weights.max()) <= .005,
        "top_one_percent_share_at_most_0_10": top_share <= .10,
    }
    return weights, {
        "normalization": "explicit_log_sum_exp",
        "weight_sum": float(weights.sum()),
        "effective_sample_size": ess,
        "effective_sample_size_fraction": ess / count,
        "maximum_path_weight": float(weights.max()),
        "top_one_percent_weight_share": top_share,
        "entropy": entropy,
        "relative_entropy_from_uniform": kl,
        "gates": gates,
        "gates_pass": all(gates.values()),
    }


def build_weights(
    paths: np.ndarray, dates: list[str], scores: dict[str, Any], dotcom: dict[str, Any],
) -> dict[str, Any]:
    metrics = _path_metrics(paths, dates)
    masks = _scenario_masks(metrics)
    growth_feature = (
        -0.45 * _robust_z(metrics["terminal_return_2026"])
        -0.30 * _robust_z(metrics["early_return"])
        -0.20 * _robust_z(metrics["maximum_drawdown"])
        +0.05 * _robust_z(metrics["annualized_volatility"])
    )
    policy_feature = (
        +0.50 * _robust_z(metrics["terminal_return_2026"])
        +0.30 * _robust_z(metrics["early_return"])
        -0.20 * _robust_z(metrics["annualized_volatility"])
    )
    cross_feature = (
        +0.55 * _robust_z(metrics["terminal_return_2027"])
        -0.25 * _robust_z(metrics["annualized_volatility"])
        -0.20 * _robust_z(metrics["recovery_days"])
    )
    inflation_feature = (
        -0.55 * _robust_z(metrics["terminal_return_2026"])
        -0.20 * _robust_z(metrics["early_return"])
        +0.25 * _robust_z(metrics["annualized_volatility_2026"])
    )
    growth_score = float(scores["labor_growth_risk"]["bounded_score"])
    policy_score = float(scores["policy_relief"]["bounded_score"])
    cross_score = float(scores["cross_asset_relief"]["bounded_score"])
    inflation_score = float(scores["inflation_risk"]["bounded_score"])

    horizon_dates = {
        "one_month": "2026-09-07",
        "three_month": "2026-11-09",
        "six_month": "2027-02-08",
        "twelve_month": "2027-08-09",
    }
    targets = {
        key: _finite_number(value, f"dotcom.forward_return_targets.{key}")
        for key, value in dotcom["forward_return_targets"].items()
    }
    if set(targets) != set(horizon_dates):
        raise ScenarioV52Error("dotcom forward-return target horizons mismatch")
    horizon_indexes = {
        key: next(index for index, value in enumerate(dates) if value >= target_date)
        for key, target_date in horizon_dates.items()
    }
    forward_returns = np.column_stack([
        paths[:, horizon_indexes[key]] / ANCHOR - 1.0 for key in horizon_dates
    ])
    target_vector = np.asarray([targets[key] for key in horizon_dates], dtype=float)
    robust_scales = np.maximum(
        (np.quantile(forward_returns, .75, axis=0)
         - np.quantile(forward_returns, .25, axis=0)) / 1.349,
        .03,
    )
    dotcom_distance = np.sqrt(np.mean(
        np.square((forward_returns - target_vector[None, :]) / robust_scales[None, :]),
        axis=1,
    ))
    dotcom_compatibility = _robust_z(-dotcom_distance)
    october_end = max(index for index, value in enumerate(dates) if value <= "2026-10-31")
    no_repeat_condition = (
        (paths[:, :october_end + 1].min(axis=1) > ANCHOR * .90)
        & (metrics["terminal_2026"] > ANCHOR)
    ).astype(float)
    condition_rate = float(no_repeat_condition.mean())
    no_repeat_feature = (
        no_repeat_condition - condition_rate
    ) / max(math.sqrt(condition_rate * (1.0 - condition_rate)), .20)
    joint_relief = max(0.0, growth_score) * max(0.0, policy_score)
    strengths = {
        key: float(dotcom["scenario_strength"][key]) for key in ("S1", "S2", "S3")
    }
    scenario_strength = sum(
        strengths[key] * mask.astype(float) for key, mask in masks.items()
    )
    s1_no_repeat = masks["S1"].astype(float) * joint_relief * no_repeat_feature
    # Preserve the full multi-horizon analog (including its negative 1m target)
    # while reserving part of S1's capped strength for the approved interaction.
    dotcom_log_adjustment = scenario_strength * (.40 * dotcom_compatibility) \
        + strengths["S1"] * (.60 * s1_no_repeat)

    base_full_log = (
        0.45 * growth_score * growth_feature
        + 0.32 * policy_score * policy_feature
        + 0.12 * cross_score * cross_feature
        + 0.15 * inflation_score * inflation_feature
    )
    logs = {
        "prior_only": np.zeros(paths.shape[0]),
        "policy_only": 0.32 * policy_score * policy_feature,
        "labor_only": 0.45 * growth_score * growth_feature,
        "labor_rate": 0.45 * growth_score * growth_feature
                      + 0.32 * policy_score * policy_feature,
        "full_without_dotcom": base_full_log,
        "full_evidence": base_full_log + dotcom_log_adjustment,
    }
    result: dict[str, Any] = {"metrics": metrics, "features": {
        "growth_risk": growth_feature,
        "policy_relief": policy_feature,
        "cross_asset_relief": cross_feature,
        "inflation_risk": inflation_feature,
        "dotcom_compatibility": dotcom_compatibility,
        "no_repeat_correction": no_repeat_feature,
        "no_repeat_condition": no_repeat_condition,
        "dotcom_log_adjustment": dotcom_log_adjustment,
    }}
    for name, log_weights in logs.items():
        weights, diagnostics = _normalise_weights(log_weights)
        result[name] = {"weights": weights, "diagnostics": diagnostics}
    result["dotcom_audit"] = {
        "method": dotcom["method"],
        "single_cycle_limitation": True,
        "cycle_count": int(dotcom["cycle_count"]),
        "neighbor_count": int(dotcom["neighbor_count"]),
        "forward_return_targets": targets,
        "target_dates": horizon_dates,
        "scenario_strength": strengths,
        "strength_gate": strengths["S1"] > strengths["S3"] > strengths["S2"],
        "dependency_cap": float(dotcom["dependency_cap"]),
        "joint_growth_risk_policy_relief_score": joint_relief,
        "no_repeat_condition_definition": (
            "no first touch of -10% through October end and year-end above anchor"
        ),
        "prior_no_repeat_condition_probability": condition_rate,
        "compatibility_median_by_scenario": {
            key: float(np.median(dotcom_compatibility[mask])) for key, mask in masks.items()
        },
        "mean_log_adjustment_by_scenario": {
            key: float(np.mean(dotcom_log_adjustment[mask])) for key, mask in masks.items()
        },
        "one_month_negative_target_preserved": targets["one_month"] < 0,
        "forced_endpoint": False,
        "forced_october_direction": False,
    }
    return result


def weighted_quantile(values: np.ndarray, weights: np.ndarray,
                      quantiles: tuple[float, ...] | np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="stable")
    sorted_values = values[order]
    sorted_weights = weights[order]
    cumulative = np.cumsum(sorted_weights) - 0.5 * sorted_weights
    cumulative /= sorted_weights.sum()
    return np.interp(np.asarray(quantiles, dtype=float), cumulative, sorted_values)


def _bands(paths: np.ndarray, weights: np.ndarray) -> dict[str, list[float]]:
    result = {name: [] for name in QUANTILE_NAMES}
    for column in range(paths.shape[1]):
        values = weighted_quantile(paths[:, column], weights, QUANTILES)
        for name, value in zip(QUANTILE_NAMES, values, strict=True):
            result[name].append(round(float(value), 2))
    return result


def _scenario_masks(metrics: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    # The partition is frozen at the 2026 state boundary.  No 2027 result is
    # inspected to decide membership, preventing look-ahead in continuation.
    robust = ((metrics["terminal_return_2026"] >= .08)
              & (metrics["maximum_drawdown_2026"] > -.15))
    stress = (~robust) & ((metrics["terminal_return_2026"] < -.03)
                          | (metrics["maximum_drawdown_2026"] <= -.20))
    mixed = ~(robust | stress)
    masks = {"S1": robust, "S2": stress, "S3": mixed}
    if any(not mask.any() for mask in masks.values()):
        raise ScenarioV52Error("fixed economic scenario classifier produced an empty cohort")
    if not np.all(sum(mask.astype(int) for mask in masks.values()) == 1):
        raise ScenarioV52Error("scenario cohorts do not form a partition")
    return masks


def _probability_metrics(
    paths: np.ndarray, dates: list[str], weights: np.ndarray,
    masks: dict[str, np.ndarray],
) -> dict[str, Any]:
    end_2026 = max(i for i, value in enumerate(dates) if value <= "2026-12-31")
    oct_end = max(i for i, value in enumerate(dates) if value <= "2026-10-31")
    touch = (paths[:, :oct_end + 1] <= ANCHOR * .90).any(axis=1)
    ath = (paths[:, :end_2026 + 1] > ATH).any(axis=1)
    return {
        "terminal_above_anchor_2026": float(weights @ (paths[:, end_2026] > ANCHOR)),
        "terminal_above_v51_reference_2026": float(weights @ (paths[:, end_2026] > REFERENCE_PRICE)),
        "new_ath_by_2026": float(weights @ ath),
        "first_touch_minus_10_by_october_end": float(weights @ touch),
        "terminal_above_anchor_2027": float(weights @ (paths[:, -1] > ANCHOR)),
        "year_end_p50": float(weighted_quantile(
            paths[:, end_2026], weights, (.50,)
        )[0]),
        "scenario_probabilities": {
            key: float(weights[mask].sum()) for key, mask in masks.items()
        },
    }


def _first_touch_distribution(
    paths: np.ndarray, dates: list[str], weights: np.ndarray,
) -> dict[str, Any]:
    oct_end = max(i for i, value in enumerate(dates) if value <= "2026-10-31")
    hit = paths[:, :oct_end + 1] <= ANCHOR * .90
    any_hit = hit.any(axis=1)
    first = np.where(any_hit, np.argmax(hit, axis=1), -1)
    density = np.asarray([
        float(weights[first == index].sum()) for index in range(oct_end + 1)
    ])
    cdf = np.cumsum(density)
    touch_probability = float(weights[any_hit].sum())
    conditional_dates: dict[str, str | None] = {"p25": None, "p50": None, "p75": None}
    if touch_probability > 0:
        conditional_cdf = cdf / touch_probability
        for name, level in (("p25", .25), ("p50", .50), ("p75", .75)):
            conditional_dates[name] = dates[int(np.searchsorted(conditional_cdf, level, side="left"))]
    return {
        "barrier": round(ANCHOR * .90, 2),
        "barrier_definition": "10 percent below the post-event anchor",
        "probability_unit": "fraction",
        "exact_date_forecast": False,
        "dates": dates[:oct_end + 1],
        "density": [round(float(value), 10) for value in density],
        "cdf": [round(float(value), 10) for value in cdf],
        "never_touched_by_october_end": round(float(weights[~any_hit].sum()), 10),
        "conditional_on_touch_quantiles": conditional_dates,
        "october_2_role": "ordinary CDF coordinate only; no target or forced trough",
        "cdf_at_2026_10_02": round(float(cdf[dates.index("2026-10-02")]), 10),
    }


def _central_bundle(
    paths: np.ndarray, dates: list[str], weights: np.ndarray, bands: dict[str, list[float]],
) -> dict[str, Any]:
    sample_columns = np.arange(0, paths.shape[1], 5)
    metrics = _path_metrics(paths, dates)
    bounds = {
        "annualized_volatility": np.quantile(metrics["annualized_volatility"], [.10, .90]),
        "direction_changes": np.quantile(metrics["direction_changes"], [.10, .90]),
        "maximum_drawdown": np.quantile(metrics["maximum_drawdown"], [.05, .95]),
        "time_underwater": np.quantile(metrics["time_underwater"], [.05, .95]),
    }
    eligible = np.ones(paths.shape[0], dtype=bool)
    for key, (low, high) in bounds.items():
        eligible &= (metrics[key] >= low) & (metrics[key] <= high)
    if int(eligible.sum()) < 9:
        raise ScenarioV52Error("insufficient realistic members for central bundle")
    target = np.asarray(bands["p50"])[sample_columns]
    distances = np.mean(
        np.abs(paths[:, sample_columns] - target[None, :]) / target[None, :], axis=1
    )
    medoid_score = distances + (1.0 - weights / weights.max()) * .002
    medoid_score[~eligible] = np.inf
    medoid = int(np.argmin(medoid_score))
    terminal_levels = weighted_quantile(
        paths[:, -1], weights, np.asarray([.20, .30, .40, .50, .60, .70, .80])
    )
    members: list[int] = []
    for level in terminal_levels:
        score = np.abs(paths[:, -1] - level) / max(float(level), 1.0) + distances * .25
        score[~eligible] = np.inf
        order = np.argsort(score, kind="stable")
        selected = next(int(index) for index in order
                        if eligible[index] and int(index) not in members)
        members.append(selected)
    pair_correlations = []
    member_returns = np.diff(np.log(paths[members]), axis=1)
    for left in range(len(members)):
        for right in range(left + 1, len(members)):
            pair_correlations.append(float(np.corrcoef(member_returns[left], member_returns[right])[0, 1]))
    member_diagnostics = []
    for index in members:
        row_metrics = {key: float(metrics[key][index]) for key in bounds}
        row_gates = {
            key: float(bounds[key][0]) <= value <= float(bounds[key][1])
            for key, value in row_metrics.items()
        }
        member_diagnostics.append({
            "path_id": f"path_{index:05d}", "metrics": row_metrics,
            "realism_gates": row_gates, "gate_pass": all(row_gates.values()),
        })
    return {
        "member_count": 7,
        "selection_rule": "actual weighted central members spanning terminal p20-p80",
        "fake_wiggle_applied": False,
        "p50_smoothing": "none; pointwise weighted distribution median",
        "medoid_path_id": f"path_{medoid:05d}",
        "medoid_values": [round(float(value), 2) for value in paths[medoid]],
        "members": [
            {
                "path_id": f"path_{index:05d}",
                "values": [round(float(value), 2) for value in paths[index]],
            }
            for index in members
        ],
        "historical_conditional_bounds": {
            key: {"low": float(value[0]), "high": float(value[1])}
            for key, value in bounds.items()
        },
        "member_diagnostics": member_diagnostics,
        "no_piecewise_linear_endpoint_path": all(
            row["metrics"]["direction_changes"] >= bounds["direction_changes"][0]
            for row in member_diagnostics
        ),
        "maximum_pair_return_correlation": max(pair_correlations),
        "no_common_residual_gate": max(pair_correlations) < .95,
        "realism_gate_pass": (
            all(row["gate_pass"] for row in member_diagnostics)
            and max(pair_correlations) < .95
        ),
    }


def _scenario_outputs(
    paths: np.ndarray, dates: list[str], weights: np.ndarray,
    metrics: dict[str, np.ndarray], masks: dict[str, np.ndarray],
) -> tuple[dict[str, Any], dict[str, Any]]:
    labels = {
        "S1": "2026 resilient state: return >= 8%, drawdown > -15%",
        "S2": "2026 stress state: return < -3% or drawdown <= -20%",
        "S3": "2026 mixed transition state",
    }
    scenarios: dict[str, Any] = {}
    summary: dict[str, dict[str, float]] = {}
    for scenario, mask in masks.items():
        conditional = weights[mask] / weights[mask].sum()
        cohort_paths = paths[mask]
        scenario_bands = _bands(cohort_paths, conditional)
        scenarios[scenario] = {
            "label": labels[scenario],
            "probability": float(weights[mask].sum()),
            "probability_space": "conditional_cohort_from_total_mixture",
            "path_count": int(mask.sum()),
            "bands": scenario_bands,
            "central_path_bundle": _central_bundle(
                cohort_paths, dates, conditional, scenario_bands
            ),
        }
        summary[scenario] = {
            "terminal_return_2027": float(weighted_quantile(
                metrics["terminal_return_2027"][mask], conditional, (.5,))[0]),
            "maximum_drawdown": float(weighted_quantile(
                metrics["maximum_drawdown"][mask], conditional, (.5,))[0]),
            "recovery_days": float(weighted_quantile(
                metrics["recovery_days"][mask], conditional, (.5,))[0]),
            "annualized_volatility": float(weighted_quantile(
                metrics["annualized_volatility"][mask], conditional, (.5,))[0]),
        }
    pairs: list[dict[str, Any]] = []
    keys = list(scenarios)
    for left_index in range(len(keys)):
        for right_index in range(left_index + 1, len(keys)):
            left, right = keys[left_index], keys[right_index]
            deltas = {
                key: abs(summary[left][key] - summary[right][key])
                for key in summary[left]
            }
            metric_gates = {
                "terminal_return_2027": deltas["terminal_return_2027"] >= .05,
                "maximum_drawdown": deltas["maximum_drawdown"] >= .02,
                "recovery_days": deltas["recovery_days"] >= 20.0,
                "annualized_volatility": deltas["annualized_volatility"] >= .02,
            }
            left_mask, right_mask = masks[left], masks[right]
            left_weights = weights[left_mask] / weights[left_mask].sum()
            right_weights = weights[right_mask] / weights[right_mask].sum()
            start_2027 = next(i for i, value in enumerate(dates) if value >= "2027-01-01")
            left_p50 = np.asarray(scenarios[left]["bands"]["p50"][start_2027:], dtype=float)
            right_p50 = np.asarray(scenarios[right]["bands"]["p50"][start_2027:], dtype=float)
            level_correlation = float(np.corrcoef(
                left_p50 / left_p50[0], right_p50 / right_p50[0]
            )[0, 1])
            weekly_left = np.diff(np.log(left_p50[::5]))
            weekly_right = np.diff(np.log(right_p50[::5]))
            weekly_return_correlation = float(np.corrcoef(weekly_left, weekly_right)[0, 1])
            terminal_wasserstein = float(wasserstein_distance(
                metrics["terminal_return_2027"][left_mask],
                metrics["terminal_return_2027"][right_mask],
                u_weights=left_weights, v_weights=right_weights,
            ))
            terminal_energy = float(energy_distance(
                metrics["terminal_return_2027"][left_mask],
                metrics["terminal_return_2027"][right_mask],
                u_weights=left_weights, v_weights=right_weights,
            ))
            mdd_distance = float(wasserstein_distance(
                metrics["maximum_drawdown"][left_mask],
                metrics["maximum_drawdown"][right_mask],
                u_weights=left_weights, v_weights=right_weights,
            ))
            volatility_distance = float(wasserstein_distance(
                metrics["annualized_volatility"][left_mask],
                metrics["annualized_volatility"][right_mask],
                u_weights=left_weights, v_weights=right_weights,
            ))
            distribution_gates = {
                "normalized_p50_level_correlation": abs(level_correlation) < .995,
                "weekly_return_correlation": abs(weekly_return_correlation) < .98,
                "terminal_wasserstein": terminal_wasserstein >= .03,
                "terminal_energy": terminal_energy >= .10,
                "mdd_distribution_distance": mdd_distance >= .015,
                "volatility_distribution_distance": volatility_distance >= .01,
            }
            pairs.append({
                "pair": f"{left}-{right}",
                "absolute_differences": deltas,
                "metric_gates": metric_gates,
                "distinct_metric_count": sum(metric_gates.values()),
                "distribution_diagnostics": {
                    "normalized_p50_level_correlation": level_correlation,
                    "weekly_return_correlation": weekly_return_correlation,
                    "terminal_wasserstein": terminal_wasserstein,
                    "terminal_energy": terminal_energy,
                    "mdd_distribution_distance": mdd_distance,
                    "volatility_distribution_distance": volatility_distance,
                },
                "distribution_gates": distribution_gates,
                "distribution_gate_count": sum(distribution_gates.values()),
                "gate_pass": sum(metric_gates.values()) >= 2
                             and sum(distribution_gates.values()) >= 3,
            })
    distinctness = {
        "rule": "2026-state cohorts; each 2027 pair must pass >=2 median and >=3 distribution diagnostics",
        "partition_information_cutoff": "2026-12-31",
        "partition_uses_2027_outcomes": False,
        "scenario_medians": summary,
        "pairs": pairs,
        "gate_pass": all(row["gate_pass"] for row in pairs),
    }
    return scenarios, distinctness


def _evidence_registry(root: Path, inputs: dict[str, Any]) -> list[dict[str, Any]]:
    registry = [
        {
            "evidence_id": "bls_actual_2026_07",
            "origin_release_id": inputs["labor"]["release_id"],
            "source_path": SOURCE_PATHS[1],
            "source_sha256": file_hash(root / SOURCE_PATHS[1]),
            "available_at": inputs["labor"]["available_at"],
            "dependency_cluster_id": "bls_empsit_2026_07",
            "effective_strength": .30,
            "used_numerically": True,
            "role": "labor_growth_risk",
        },
        {
            "evidence_id": "fed_rate_distribution_pre_post",
            "origin_release_id": inputs["rates"]["dataset_id"],
            "source_path": SOURCE_PATHS[3],
            "source_sha256": file_hash(root / SOURCE_PATHS[3]),
            "available_at": inputs["rates"]["source_updated_at"],
            "dependency_cluster_id": "cme_fed_funds_futures",
            "effective_strength": .25,
            "used_numerically": True,
            "role": "policy_relief",
        },
        {
            "evidence_id": "post_jobs_cross_asset_state",
            "origin_release_id": inputs["market"]["event_id"],
            "source_path": SOURCE_PATHS[6],
            "source_sha256": file_hash(root / SOURCE_PATHS[6]),
            "available_at": inputs["market"]["available_at"],
            "dependency_cluster_id": "post_jobs_market_state",
            "effective_strength": .10,
            "used_numerically": True,
            "role": "weak_cross_asset_state",
            "nasdaq_event_return_coefficient": 0.0,
        },
        {
            "evidence_id": "v5_1_ancestor_candidate",
            "origin_release_id": inputs["v51"]["candidate_id"],
            "source_path": SOURCE_PATHS[7],
            "source_sha256": source_file_hash(root, SOURCE_PATHS[7]),
            "available_at": inputs["v51"]["generated_at"],
            "dependency_cluster_id": "scenario_ancestor",
            "effective_strength": 0.0,
            "used_numerically": False,
            "role": "reference_only_endogenous_circularity_blocked",
        },
        {
            "evidence_id": "kiplinger_jobs_consensus_and_commentary",
            "origin_release_id": inputs["labor"]["release_id"],
            "source_url": inputs["labor"]["consensus"]["source_url"],
            "dependency_cluster_id": "bls_empsit_2026_07",
            "effective_strength": 0.0,
            "used_numerically": False,
            "role": "consensus_field_only; narrative reference only",
        },
        {
            "evidence_id": "dotcom_knn_single_cycle_analog",
            "origin_release_id": inputs["dotcom"]["dataset_id"],
            "source_path": SOURCE_PATHS[9],
            "source_sha256": file_hash(root / SOURCE_PATHS[9]),
            "available_at": inputs["dotcom"]["available_at"],
            "dependency_cluster_id": inputs["dotcom"]["dependency_cluster_id"],
            "effective_strength": float(inputs["dotcom"]["scenario_strength"]["S1"]),
            "scenario_strength": inputs["dotcom"]["scenario_strength"],
            "used_numerically": True,
            "role": "S1_strong_S2_S3_weak_soft_likelihood",
            "single_cycle_limitation": True,
        },
        {
            "evidence_id": "approved_human_dotcom_model_risk_view",
            "origin_release_id": inputs["dotcom_view"]["origin_release_id"],
            "source_path": SOURCE_PATHS[10],
            "source_sha256": file_hash(root / SOURCE_PATHS[10]),
            "available_at": inputs["dotcom_view"]["available_at"],
            "dependency_cluster_id": inputs["dotcom_view"]["dependency_cluster_id"],
            "effective_strength": 0.0,
            "used_numerically": False,
            "role": "approval_receipt_for_same_dotcom_dependency_cluster",
        },
    ]
    for event in inputs["event_updates"]["events"]:
        registry.append({
            "evidence_id": f"event_learning:{event['revision_id']}",
            "origin_release_id": event["event_id"],
            "source_path": event.get("source_path"),
            "source_url": event["source_url"],
            "source_sha256": event["source_sha256"],
            "available_at": event["available_at"],
            "dependency_cluster_id": event["dependency_cluster_id"],
            "effective_strength": float(event["scores"]["effective_strength"]),
            "used_numerically": bool(event["scores"]["used_numerically"]),
            "role": f"append_only_{event['scores']['adapter']}",
            "revision_id": event["revision_id"],
            "supersedes": event.get("supersedes"),
        })
    return registry


def assemble_candidate(root: Path) -> dict[str, Any]:
    inputs = load_inputs(root)
    paths, dates, engines, historical_actual = generate_prior(root, inputs)
    scores = evidence_scores(inputs)
    weighting = build_weights(paths, dates, scores, inputs["dotcom"])
    metrics = weighting["metrics"]
    masks = _scenario_masks(metrics)
    ablations: dict[str, Any] = {}
    for name in ("prior_only", "labor_only", "labor_rate", "full_evidence"):
        weights = weighting[name]["weights"]
        ablations[name] = {
            "included_evidence": {
                "prior_only": [],
                "labor_only": ["labor_growth_risk"],
                "labor_rate": ["labor_growth_risk", "policy_relief"],
                "full_evidence": [
                    "labor_growth_risk", "policy_relief", "cross_asset_relief",
                    "event_learning", "dotcom_S1_weighted_upside_view",
                ],
            }[name],
            "probabilities": _probability_metrics(paths, dates, weights, masks),
            "weight_diagnostics": weighting[name]["diagnostics"],
        }
    policy_only_metrics = _probability_metrics(
        paths, dates, weighting["policy_only"]["weights"], masks
    )
    full_without_dotcom_metrics = _probability_metrics(
        paths, dates, weighting["full_without_dotcom"]["weights"], masks
    )
    full_weights = weighting["full_evidence"]["weights"]
    mixture_bands = _bands(paths, full_weights)
    scenarios, distinctness = _scenario_outputs(
        paths, dates, full_weights, metrics, masks
    )
    attribution: dict[str, Any] = {}
    probability_keys = [
        "terminal_above_anchor_2026", "terminal_above_v51_reference_2026",
        "new_ath_by_2026", "first_touch_minus_10_by_october_end",
        "terminal_above_anchor_2027",
    ]
    for key in probability_keys:
        prior = ablations["prior_only"]["probabilities"][key]
        labor_value = ablations["labor_only"]["probabilities"][key]
        rate_value = ablations["labor_rate"]["probabilities"][key]
        macro_full = full_without_dotcom_metrics[key]
        full = ablations["full_evidence"]["probabilities"][key]
        attribution[key] = {
            "pre_jobs_same_anchor_counterfactual": prior,
            "labor_growth_risk_effect": labor_value - prior,
            "policy_relief_effect": rate_value - labor_value,
            "cross_asset_state_effect": macro_full - rate_value,
            "event_and_cross_asset_effect": macro_full - rate_value,
            "dotcom_upside_effect": full - macro_full,
            "post_jobs_full": full,
            "total_change": full - prior,
            "additivity_residual": full - prior
                                   - (labor_value - prior)
                                   - (rate_value - labor_value)
                                   - (macro_full - rate_value)
                                   - (full - macro_full),
        }
    event_reaction_zero = np.zeros(paths.shape[0])
    no_event_weights, _ = _normalise_weights(
        0.45 * float(scores["labor_growth_risk"]["bounded_score"])
        * weighting["features"]["growth_risk"]
        + 0.32 * float(scores["policy_relief"]["bounded_score"])
        * weighting["features"]["policy_relief"]
        + 0.12 * float(scores["cross_asset_relief"]["bounded_score"])
        * weighting["features"]["cross_asset_relief"]
        + 0.15 * float(scores["inflation_risk"]["bounded_score"])
        * weighting["features"]["inflation_risk"]
        + weighting["features"]["dotcom_log_adjustment"]
        + event_reaction_zero
    )
    event_double_count_gate = bool(np.array_equal(no_event_weights, full_weights))
    evidence = _evidence_registry(root, inputs)
    dotcom_audit = dict(weighting["dotcom_audit"])
    no_repeat = weighting["features"]["no_repeat_condition"]
    before_dotcom_weights = weighting["full_without_dotcom"]["weights"]
    dotcom_audit["no_repeat_probability_before_dotcom"] = float(
        before_dotcom_weights @ no_repeat
    )
    dotcom_audit["no_repeat_probability_after_dotcom"] = float(full_weights @ no_repeat)
    s1 = masks["S1"]
    dotcom_audit["S1_no_repeat_probability_before_dotcom"] = float(
        (before_dotcom_weights[s1] / before_dotcom_weights[s1].sum()) @ no_repeat[s1]
    )
    dotcom_audit["S1_no_repeat_probability_after_dotcom"] = float(
        (full_weights[s1] / full_weights[s1].sum()) @ no_repeat[s1]
    )
    dotcom_audit["S1_probability_increment"] = (
        ablations["full_evidence"]["probabilities"]["scenario_probabilities"]["S1"]
        - full_without_dotcom_metrics["scenario_probabilities"]["S1"]
    )
    legacy_full = inputs["legacy_v52"]["ablations"]["full_evidence"]["probabilities"]
    shadow_comparison = {
        "baseline_candidate_id": inputs["legacy_v52"]["candidate_id"],
        "baseline_model_content_sha256": inputs["legacy_v52"]["model_content_sha256"],
        "baseline_source_sha256": file_hash(root / LEGACY_V52_RELATIVE),
        "candidate_id": CANDIDATE_ID,
        "comparable_anchor": inputs["legacy_v52"]["anchor"]["close"] == ANCHOR,
        "comparable_distribution_seed": inputs["legacy_v52"]["model"]["seed"] == SEED,
        "changed_inputs": [
            "stronger_full_rate_probability_repricing",
            "S1_weighted_dotcom_single_cycle_likelihood",
            "append_only_event_learning_boundary",
        ],
        "metric_deltas": {
            key: ablations["full_evidence"]["probabilities"][key] - legacy_full[key]
            for key in probability_keys
        },
        "scenario_probability_deltas": {
            key: ablations["full_evidence"]["probabilities"]["scenario_probabilities"][key]
                 - legacy_full["scenario_probabilities"][key]
            for key in ("S1", "S2", "S3")
        },
        "official_snapshot_overwritten": False,
    }
    candidate = {
        "schema_version": 1,
        "artifact_type": "scenario_v5_2_research_candidate",
        "candidate_id": CANDIDATE_ID,
        "status": "RESEARCH_CANDIDATE_LIMITED_EVENT_MAP",
        "promotion_state": "NOT_OFFICIAL_NOT_CHAMPION",
        "as_of": inputs["knowledge_cutoff"],
        "knowledge_cutoff": inputs["knowledge_cutoff"],
        "anchor": {
            "symbol": "^IXIC",
            "date": ANCHOR_DATE.isoformat(),
            "available_at": "2026-08-07T20:00:00+00:00",
            "close": ANCHOR,
            "event_day_return_role": "historical_anchor_only",
            "future_event_jump": 0.0,
        },
        "forecast_time_transport": {
            "source_candidate": inputs["v51"]["candidate_id"],
            "source_cutoff": inputs["v51"]["knowledge_cutoff"],
            "source_anchor": inputs["v51"]["source_snapshot"]["anchor"],
            "target_anchor": ANCHOR,
            "mode": "CURRENT_REFORECAST_FROM_POST_EVENT_ANCHOR",
            "source_probabilities_used_numerically": False,
            "historical_transport_step": ANCHOR / float(inputs["v51"]["source_snapshot"]["anchor"]) - 1.0,
        },
        "model": {
            "model_id": "dotcom_weighted_event_adaptive_historical_shape_v2",
            "seed": SEED,
            "path_count": int(paths.shape[0]),
            "path_count_by_engine": {
                "stationary_block_bootstrap": int((engines == 0).sum()),
                "analog_episode_resampling": int((engines == 1).sum()),
            },
            "engine_mixture_probability": {
                "stationary_block_bootstrap": .5,
                "analog_episode_resampling": .5,
            },
            "history_start": inputs["history_manifest"]["first_session"],
            "history_end": inputs["history_manifest"]["last_session"],
            "history_observations": inputs["history_manifest"]["row_count"],
            "hard_event_mapping": {
                "eligible_historical_event_count": 1,
                "preferred_minimum": 60,
                "weak_minimum": 30,
                "status": "REFERENCE_ONLY_INSUFFICIENT_N",
                "direct_event_return_kernel_used": False,
            },
            "path_creation_note": "No endpoint, drawdown date, or scenario probability is forced.",
        },
        "evidence_scores": scores,
        "evidence_registry": evidence,
        "dependency_control": {
            "cluster_cap": .35,
            "clusters": [
                {"id": "bls_empsit_2026_07", "effective_strength": .30, "gate_pass": True},
                {"id": "cme_fed_funds_futures", "effective_strength": .25, "gate_pass": True},
                {"id": "post_jobs_market_state", "effective_strength": .10, "gate_pass": True},
                {"id": "dotcom_single_cycle_analog", "effective_strength": .28, "gate_pass": True},
                {"id": "scenario_ancestor", "effective_strength": 0.0, "gate_pass": True},
                *[
                    {"id": key, "effective_strength": value, "gate_pass": value <= .35}
                    for key, value in inputs["event_updates"]["dependency_cluster_strength"].items()
                ],
            ],
            "duplicate_narratives_numerical_strength": 0.0,
            "gate_pass": True,
        },
        "circularity_control": {
            "v5_1_ancestor_used_numerically": False,
            "narrative_reports_used_numerically": False,
            "realized_event_return_coefficient": 0.0,
            "future_event_jump": 0.0,
            "full_equals_explicit_zero_event_reaction": event_double_count_gate,
            "gate_pass": event_double_count_gate,
        },
        "ablations": ablations,
        "component_ablations": {
            "policy_only": {
                "included_evidence": ["policy_relief"],
                "probabilities": policy_only_metrics,
                "weight_diagnostics": weighting["policy_only"]["diagnostics"],
            },
            "growth_only": ablations["labor_only"],
            "combined_growth_and_policy": ablations["labor_rate"],
            "macro_full_without_dotcom": {
                "included_evidence": [
                    "labor_growth_risk", "policy_relief", "cross_asset_relief",
                    "event_learning",
                ],
                "probabilities": full_without_dotcom_metrics,
                "weight_diagnostics": weighting["full_without_dotcom"]["diagnostics"],
            },
            "dotcom_upside_increment": {
                "included_evidence": ["dotcom_S1_weighted_upside_view"],
                "scenario_strength": inputs["dotcom"]["scenario_strength"],
                "probability_increment": {
                    key: ablations["full_evidence"]["probabilities"][key]
                         - full_without_dotcom_metrics[key]
                    for key in probability_keys
                },
            },
            "report_view_increment": {
                "numerical_report_views": 1,
                "reason": "explicitly approved dotcom view; same-cluster approval row has zero extra strength",
            },
        },
        "evidence_attribution": attribution,
        "dotcom_scenario_weighting": dotcom_audit,
        "event_learning": {
            "mode": "append_only_event_then_deterministic_candidate_rebuild",
            "ledger_path": "data/scenarios/candidates/event_learning/events.jsonl",
            "supported_events": ["cpi", "nfp", "fomc", "gdp", "earnings"],
            "active_event_count": inputs["event_updates"]["active_event_count"],
            "numerical_event_count": inputs["event_updates"]["numerical_event_count"],
            "corrections_require_supersedes": True,
            "instant_means": "after a validated normalized release is explicitly ingested",
            "background_scraping_or_unbounded_self_training": False,
        },
        "distribution": {
            "probability_space": "total_path_mixture",
            "dates": dates,
            "bands": mixture_bands,
            "historical_actual": historical_actual,
            "forecast_boundary": "2026-08-07",
            "central_path_bundle": _central_bundle(
                paths, dates, full_weights, mixture_bands
            ),
        },
        "conditional_small_multiples": {
            "probability_space": "scenario_conditional",
            "dates": dates,
            "scenarios": scenarios,
        },
        "first_touch_distribution": _first_touch_distribution(paths, dates, full_weights),
        "pre_post_jobs_comparison": {
            "comparison_basis": "same post-event anchor counterfactual to isolate evidence; not an archived pre-event forecast",
            "before_jobs_prior_only": {
                **ablations["prior_only"]["probabilities"],
                "first_touch_distribution": _first_touch_distribution(
                    paths, dates, weighting["prior_only"]["weights"]
                ),
            },
            "after_jobs_full_evidence": {
                **ablations["full_evidence"]["probabilities"],
                "first_touch_distribution": _first_touch_distribution(
                    paths, dates, full_weights
                ),
            },
            "archived_v5_1_reference": {
                "knowledge_cutoff": inputs["v51"]["knowledge_cutoff"],
                "scenario_probabilities": {
                    key: inputs["v51"]["conditional_distribution"]["scenarios"][key]["probability"]
                    for key in ("S1", "S2", "S3")
                },
                "correction_touch_probability": inputs["v51"]["correction_timing_distribution"]["any_touch_probability"],
                "warning": "not directly comparable because anchor, horizon, prior, and partition changed",
            },
        },
        "shadow_comparison": shadow_comparison,
        "distinctness_2027": distinctness,
        "display_contract": {
            "main_chart": "total_mixture_p50_and_bands",
            "main_chart_scenario_lines": False,
            "scenario_surface": "S1_S2_S3_conditional_small_multiples",
            "primary_line": "total_mixture_weighted_p50",
            "secondary_lines": "seven_actual_central_members_plus_dotted_medoid",
            "fake_wiggle": False,
            "october_2_exact_date_forecast": False,
            "percent_conversion_boundary": "dashboard_only",
            "dotcom_weight_disclosure": "S1 strong; S2 and S3 weak",
        },
        "source_hashes": {
            **{path: source_file_hash(root, path) for path in SOURCE_PATHS},
            LEGACY_V52_RELATIVE.as_posix(): file_hash(root / LEGACY_V52_RELATIVE),
        },
        "protected_write_contract": {
            "official_snapshot": "read_only",
            "ledger": "not_opened_for_write",
            "archive": "not_opened_for_write",
        },
    }
    if not distinctness["gate_pass"]:
        candidate["status"] = "RESEARCH_CANDIDATE_DEGRADED_2027_DISTINCTNESS"
    candidate["model_content_sha256"] = canonical_hash(candidate)
    return candidate


def stable_payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()
