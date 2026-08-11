"""Deterministic, scenario-specific database clustering for V5.2.

Clustering uses only state variables observable at each historical origin.
Forward returns and drawdowns are withheld until after assignments are frozen;
they are used only to label whole clusters as upside, baseline, or downside.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import math
from typing import Any

import numpy as np


PRICE_FEATURES = (
    "annualized_volatility_20d",
    "annualized_volatility_60d",
    "return_60d",
    "drawdown_60d",
    "distance_from_200d_mean",
)
MACRO_FEATURES = (
    *PRICE_FEATURES,
    "fed_funds_change_63d_pp",
    "two_year_yield_change_63d_pp",
    "ten_two_curve_pp",
    "ten_year_yield_pp",
    "vix_level",
    "nfci_z_score",
)
SCENARIO_FEATURES = {
    "S1": (
        *PRICE_FEATURES,
        "fed_funds_change_63d_pp",
        "two_year_yield_change_63d_pp",
        "nfci_z_score",
    ),
    "S2": (
        *PRICE_FEATURES,
        "fed_funds_change_63d_pp",
        "ten_two_curve_pp",
        "ten_year_yield_pp",
        "vix_level",
        "nfci_z_score",
    ),
    "S3": MACRO_FEATURES,
}
SCENARIO_MACRO_REGIMES = ("easing_expansion", "balanced_soft_landing", "tightening_stress")
OUTCOME_FIELDS = (
    "forward_return_126d",
    "forward_return_252d",
    "forward_return_horizon",
    "maximum_drawdown_252d",
    "maximum_drawdown_horizon",
)


class ScenarioClusterError(RuntimeError):
    """A fail-closed scenario-cluster construction error."""


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScenarioClusterError(f"{name} must be a non-boolean number")
    result = float(value)
    if not math.isfinite(result):
        raise ScenarioClusterError(f"{name} must be finite")
    return result


def _price_features(levels: np.ndarray, index: int) -> np.ndarray:
    if index < 200:
        raise ScenarioClusterError("price state requires a 200-session lookback")
    returns = np.diff(np.log(levels[index - 60:index + 1]))
    window = levels[index - 60:index + 1]
    return np.asarray([
        returns[-20:].std(ddof=1) * math.sqrt(252.0),
        returns.std(ddof=1) * math.sqrt(252.0),
        levels[index] / levels[index - 60] - 1.0,
        (window / np.maximum.accumulate(window) - 1.0).min(),
        levels[index] / levels[index - 199:index + 1].mean() - 1.0,
    ], dtype=float)


def _outcomes(levels: np.ndarray, index: int, horizon: int) -> np.ndarray:
    future = levels[index:index + horizon + 1]
    first_year = future[:253]
    return np.asarray([
        levels[index + 126] / levels[index] - 1.0,
        levels[index + 252] / levels[index] - 1.0,
        levels[index + horizon] / levels[index] - 1.0,
        (first_year / np.maximum.accumulate(first_year) - 1.0).min(),
        (future / np.maximum.accumulate(future) - 1.0).min(),
    ], dtype=float)


def _price_rows(
    dates: list[str], levels: np.ndarray, horizon: int, *, step: int = 21,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index in range(200, len(levels) - horizon, step):
        rows.append({
            "index": index,
            "date": dates[index],
            "features": _price_features(levels, index),
            "outcomes": _outcomes(levels, index, horizon),
        })
    if len(rows) < 30:
        raise ScenarioClusterError("price cluster pool has fewer than 30 origins")
    return rows


def _robust_scale(features: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    center = np.median(features, axis=0)
    q25, q75 = np.quantile(features, [.25, .75], axis=0)
    scale = np.maximum((q75 - q25) / 1.349, 1e-8)
    return center, scale, (features - center) / scale


def deterministic_k_medoids(
    features: np.ndarray, cluster_count: int,
) -> tuple[np.ndarray, list[int], np.ndarray, np.ndarray]:
    """Cluster without randomness, outcomes, or user-entered labels."""
    if features.ndim != 2 or len(features) < cluster_count * 2:
        raise ScenarioClusterError("insufficient feature matrix for k-medoids")
    if not np.isfinite(features).all():
        raise ScenarioClusterError("cluster features contain non-finite values")
    center, scale, standardized = _robust_scale(features)
    medoids = [int(np.argmin(np.square(standardized).sum(axis=1)))]
    while len(medoids) < cluster_count:
        distance = np.min(np.stack([
            np.square(standardized - standardized[index]).sum(axis=1)
            for index in medoids
        ]), axis=0)
        distance[medoids] = -1.0
        medoids.append(int(np.argmax(distance)))
    for _ in range(50):
        distances = np.stack([
            np.square(standardized - standardized[index]).sum(axis=1)
            for index in medoids
        ], axis=1)
        labels = np.argmin(distances, axis=1)
        updated: list[int] = []
        for cluster in range(cluster_count):
            members = np.flatnonzero(labels == cluster)
            if not members.size:
                raise ScenarioClusterError("deterministic k-medoids produced an empty cluster")
            local = standardized[members]
            pairwise = np.square(local[:, None, :] - local[None, :, :]).sum(axis=2)
            updated.append(int(members[np.argmin(pairwise.sum(axis=1))]))
        if updated == medoids:
            break
        medoids = updated
    final_distances = np.stack([
        np.square(standardized - standardized[index]).sum(axis=1)
        for index in medoids
    ], axis=1)
    labels = np.argmin(final_distances, axis=1)
    return labels, medoids, center, scale


def _cluster_audit(
    rows: list[dict[str, Any]], labels: np.ndarray, medoids: list[int],
    feature_names: tuple[str, ...],
) -> list[dict[str, Any]]:
    features = np.asarray([row["features"] for row in rows], dtype=float)
    outcomes = np.asarray([row["outcomes"] for row in rows], dtype=float)
    result: list[dict[str, Any]] = []
    for cluster, medoid in enumerate(medoids):
        members = np.flatnonzero(labels == cluster)
        cluster_outcomes = outcomes[members]
        result.append({
            "cluster_id": int(cluster),
            "origin_count": int(len(members)),
            "medoid_date": rows[medoid]["date"],
            "feature_medians": {
                name: float(value)
                for name, value in zip(
                    feature_names, np.median(features[members], axis=0), strict=True
                )
            },
            "outcome_medians": {
                name: float(value)
                for name, value in zip(
                    OUTCOME_FIELDS, np.median(cluster_outcomes, axis=0), strict=True
                )
            },
            "forward_252d_iqr": [
                float(value) for value in np.quantile(cluster_outcomes[:, 1], [.25, .75])
            ],
        })
    return result


def _assignment_hash(rows: list[dict[str, Any]], labels: np.ndarray) -> str:
    payload = [[row["date"], int(label)] for row, label in zip(rows, labels, strict=True)]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def _asof_value(series: dict[str, tuple[list[str], np.ndarray]], name: str, session: str) -> float:
    dates, values = series[name]
    index = bisect.bisect_right(dates, session) - 1
    if index < 0:
        raise ScenarioClusterError(f"no as-of value for {name} at {session}")
    if dates[index] > session:
        raise ScenarioClusterError(f"future as-of join for {name} at {session}")
    return float(values[index])


def _macro_source(
    manifest: dict[str, Any],
) -> tuple[list[str], np.ndarray, dict[str, tuple[list[str], np.ndarray]]]:
    parsed: dict[str, tuple[list[str], np.ndarray]] = {}
    for name in ("NASDAQCOM", "DFF", "DGS2", "DGS10", "T10Y2Y", "VIXCLS", "NFCI"):
        rows = manifest.get("series", {}).get(name, [])
        dates = [str(row["date"]) for row in rows]
        values = np.asarray([_finite(row["value"], f"{name}.{row['date']}") for row in rows])
        if not dates or dates != sorted(set(dates)) or not np.isfinite(values).all():
            raise ScenarioClusterError(f"invalid normalized macro series: {name}")
        parsed[name] = (dates, values)
    price_dates, price_levels = parsed["NASDAQCOM"]
    if price_dates[-1] != "2026-08-04" or float(price_levels.min()) <= 0:
        raise ScenarioClusterError("macro Nasdaq history is not aligned to its cutoff")
    return price_dates, price_levels, parsed


def _macro_regime_rows(
    dates: list[str], levels: np.ndarray,
    series: dict[str, tuple[list[str], np.ndarray]], horizon: int, *, regime: str,
) -> list[dict[str, Any]]:
    """Build mutually exclusive, origin-time macro cohorts.

    The screens use only values available at each historical origin.  Forward
    outcomes stay hidden until deterministic clustering is complete.  Easing,
    balanced, and tightening rows are deliberately disjoint so the three
    scenario generators cannot silently reuse the same origin episodes.
    """
    if regime not in SCENARIO_MACRO_REGIMES:
        raise ScenarioClusterError(f"unknown macro regime: {regime}")
    rows: list[dict[str, Any]] = []
    for index in range(200, len(levels) - horizon, 21):
        session = dates[index]
        lag_session = dates[index - 63]
        rate_change = _asof_value(series, "DFF", session) \
            - _asof_value(series, "DFF", lag_session)
        two_year_change = _asof_value(series, "DGS2", session) \
            - _asof_value(series, "DGS2", lag_session)
        vix = _asof_value(series, "VIXCLS", session)
        nfci = _asof_value(series, "NFCI", session)
        easing_signal = rate_change < -.10 or two_year_change < -.25
        tightening = rate_change > .10 or two_year_change > .25
        # Conflicting rate signals are conservatively routed to tightening,
        # never duplicated into the upside easing library.
        easing = easing_signal and not tightening and nfci < .75
        balanced = (
            not easing and not tightening
            and 12.0 <= vix <= 32.0 and nfci < .75
        )
        eligible = {
            "easing_expansion": easing,
            "balanced_soft_landing": balanced,
            "tightening_stress": tightening,
        }[regime]
        if not eligible:
            continue
        macro_features = np.concatenate((
            _price_features(levels, index),
            np.asarray([
                rate_change,
                two_year_change,
                _asof_value(series, "T10Y2Y", session),
                _asof_value(series, "DGS10", session),
                vix,
                nfci,
            ], dtype=float),
        ))
        rows.append({
            "index": index,
            "date": session,
            "regime": regime,
            "features": macro_features,
            "outcomes": _outcomes(levels, index, horizon),
        })
    if len(rows) < 60:
        raise ScenarioClusterError(f"macro {regime} pool has fewer than 60 origins")
    return rows


def _current_macro_features(
    dates: list[str], levels: np.ndarray,
    series: dict[str, tuple[list[str], np.ndarray]],
) -> np.ndarray:
    index = len(levels) - 1
    session, lag_session = dates[index], dates[index - 63]
    return np.concatenate((
        _price_features(levels, index),
        np.asarray([
            _asof_value(series, "DFF", session) - _asof_value(series, "DFF", lag_session),
            _asof_value(series, "DGS2", session) - _asof_value(series, "DGS2", lag_session),
            _asof_value(series, "T10Y2Y", session),
            _asof_value(series, "DGS10", session),
            _asof_value(series, "VIXCLS", session),
            _asof_value(series, "NFCI", session),
        ], dtype=float),
    ))


def _scenario_feature_subset(values: np.ndarray, scenario: str) -> np.ndarray:
    names = SCENARIO_FEATURES.get(scenario)
    if names is None:
        raise ScenarioClusterError(f"unknown feature schema: {scenario}")
    indexes = [MACRO_FEATURES.index(name) for name in names]
    return values[np.asarray(indexes, dtype=int)]


def _episode_rows(
    dates: list[str], levels: np.ndarray,
    series: dict[str, tuple[list[str], np.ndarray]], horizon: int,
    *, scenario: str, episodes: list[dict[str, Any]], step: int = 10,
) -> list[dict[str, Any]]:
    """Build scenario-specific rows only inside preregistered episode windows."""
    if scenario not in SCENARIO_FEATURES:
        raise ScenarioClusterError(f"unknown episode scenario: {scenario}")
    rows: list[dict[str, Any]] = []
    for index in range(200, len(levels) - horizon, step):
        session = dates[index]
        episode = next(
            (row for row in episodes if str(row["start"]) <= session <= str(row["end"])),
            None,
        )
        if episode is None:
            continue
        lag_session = dates[index - 63]
        full = np.concatenate((
            _price_features(levels, index),
            np.asarray([
                _asof_value(series, "DFF", session)
                - _asof_value(series, "DFF", lag_session),
                _asof_value(series, "DGS2", session)
                - _asof_value(series, "DGS2", lag_session),
                _asof_value(series, "T10Y2Y", session),
                _asof_value(series, "DGS10", session),
                _asof_value(series, "VIXCLS", session),
                _asof_value(series, "NFCI", session),
            ], dtype=float),
        ))
        rows.append({
            "index": index,
            "date": session,
            "scenario": scenario,
            "episode_id": str(episode["id"]),
            "episode_group": str(episode["group"]),
            "features": _scenario_feature_subset(full, scenario),
            "outcomes": _outcomes(levels, index, horizon),
        })
    if len(rows) < 30:
        raise ScenarioClusterError(
            f"{scenario} preregistered episode pool has fewer than 30 origins"
        )
    return rows


def _select_cluster(
    scenario: str, audits: list[dict[str, Any]], minimum_origins: int,
) -> int:
    eligible = [row for row in audits if row["origin_count"] >= minimum_origins]
    if not eligible:
        raise ScenarioClusterError(
            f"{scenario} has no cluster with at least {minimum_origins} origins"
        )
    if scenario == "S1":
        selected = max(eligible, key=lambda row: (
            .35 * row["outcome_medians"]["forward_return_126d"]
            + .65 * row["outcome_medians"]["forward_return_252d"]
            + .20 * row["outcome_medians"]["maximum_drawdown_252d"]
        ))
    elif scenario == "S2":
        eligible = [
            row for row in eligible
            if .05 < row["outcome_medians"]["forward_return_252d"] < .35
        ]
        if not eligible:
            raise ScenarioClusterError(
                f"S2 has no moderate cluster with at least {minimum_origins} origins"
            )
        selected = min(eligible, key=lambda row: (
            abs(row["outcome_medians"]["forward_return_126d"]),
            -row["origin_count"],
        ))
    elif scenario == "S3":
        selected = min(eligible, key=lambda row: (
            .35 * row["outcome_medians"]["forward_return_126d"]
            + .65 * row["outcome_medians"]["forward_return_252d"]
            + .30 * row["outcome_medians"]["maximum_drawdown_252d"]
        ))
    else:
        raise ScenarioClusterError(f"unknown scenario: {scenario}")
    return int(selected["cluster_id"])


def _stationary_residuals(
    residual_pool: np.ndarray, horizon: int, count: int,
    rng: np.random.Generator, restart_probability: float,
) -> np.ndarray:
    indexes = rng.integers(0, len(residual_pool), size=count)
    sampled = np.empty((count, horizon), dtype=float)
    for column in range(horizon):
        if column:
            restart = rng.random(count) < restart_probability
            indexes = np.where(
                restart, rng.integers(0, len(residual_pool), size=count),
                (indexes + 1) % len(residual_pool),
            )
        sampled[:, column] = residual_pool[indexes]
    return sampled


def _sample_cluster_paths(
    rows: list[dict[str, Any]], labels: np.ndarray, selected_cluster: int,
    source_levels: np.ndarray, current_features: np.ndarray,
    center: np.ndarray, scale: np.ndarray, horizon: int, count: int,
    rng: np.random.Generator, residual_scale: float, restart_probability: float,
) -> tuple[np.ndarray, dict[str, Any]]:
    members = np.flatnonzero(labels == selected_cluster)
    selected_features = np.asarray([rows[index]["features"] for index in members])
    standardized = (selected_features - center) / scale
    current = (current_features - center) / scale
    distances = np.linalg.norm(standardized - current[None, :], axis=1)
    similarity = np.exp(-.50 * (distances - float(distances.min())))
    similarity /= similarity.sum()
    probabilities = .50 / len(members) + .50 * similarity
    probabilities /= probabilities.sum()
    choices = rng.choice(len(members), size=count, replace=True, p=probabilities)
    source_returns = np.diff(np.log(source_levels))
    base = np.vstack([
        source_returns[
            rows[int(members[choice])]["index"]:
            rows[int(members[choice])]["index"] + horizon
        ]
        for choice in choices
    ])
    rolling_mean = np.convolve(source_returns, np.ones(20) / 20.0, mode="same")
    residual_pool = source_returns - rolling_mean
    residual_q01, residual_q99 = np.quantile(residual_pool, [.01, .99])
    residual_pool = np.clip(residual_pool, residual_q01, residual_q99)
    residuals = _stationary_residuals(
        residual_pool, horizon, count, rng, restart_probability
    )
    sampled = base + residual_scale * residuals
    counts = np.bincount(choices, minlength=len(members))
    top = np.argsort(counts, kind="stable")[-10:][::-1]
    return sampled, {
        "selected_origin_count": int(len(members)),
        "simulation_path_count": int(count),
        "episode_sampling_ess": float(1.0 / np.square(probabilities).sum()),
        "maximum_episode_probability": float(probabilities.max()),
        "current_to_selected_medoid_distance": float(distances.min()),
        "current_state_similarity": float(math.exp(
            -float(distances.min()) / math.sqrt(len(current_features))
        )),
        "residual_scale": residual_scale,
        "residual_policy": "winsorized_source_residuals_p01_p99",
        "residual_trim_bounds": [float(residual_q01), float(residual_q99)],
        "sampled_origin_count": int(np.count_nonzero(counts)),
        "top_sampled_origins": [
            {"date": rows[int(members[index])]["date"], "count": int(counts[index])}
            for index in top
        ],
        "forced_endpoint": False,
        "forced_turning_date": False,
    }


def _conditional_block_pool(
    rows: list[dict[str, Any]], labels: np.ndarray, selected_cluster: int,
    source_dates: list[str], source_levels: np.ndarray, *, length: int,
    lower_quantile: float, upper_quantile: float,
) -> tuple[np.ndarray, list[str]]:
    """Return realized blocks inside a preregistered cluster quantile slice."""
    if not 0.0 <= lower_quantile < upper_quantile <= 1.0:
        raise ScenarioClusterError("invalid conditional block quantiles")
    members = np.flatnonzero(labels == selected_cluster)
    source_returns = np.diff(np.log(source_levels))
    blocks: list[np.ndarray] = []
    starts: list[str] = []
    for member in members:
        origin = int(rows[int(member)]["index"])
        for offset in range(0, 253 - length + 1, 21):
            start, stop = origin + offset, origin + offset + length
            if stop <= len(source_returns):
                blocks.append(source_returns[start:stop])
                starts.append(source_dates[start])
    if len(blocks) < 12:
        raise ScenarioClusterError("conditional block library has fewer than 12 blocks")
    matrix = np.vstack(blocks)
    cumulative = matrix.sum(axis=1)
    lower, upper = np.quantile(cumulative, [lower_quantile, upper_quantile])
    selected = np.flatnonzero((cumulative >= lower) & (cumulative <= upper))
    if len(selected) < 8:
        raise ScenarioClusterError("conditional block slice has fewer than 8 blocks")
    return matrix[selected], [starts[int(index)] for index in selected]


def _sample_balanced_regime_paths(
    *, rows: list[dict[str, Any]], labels: np.ndarray, selected_cluster: int,
    source_dates: list[str], source_levels: np.ndarray, horizon: int,
    count: int, seed: int, shadow_amplitude_scale: float = 1.0,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Generate S2 from a neutral drift/mean-reversion/normalization cycle."""
    phase_contract = (
        ("steady_drift", 42, .30, .65),
        ("mean_reversion", 21, .00, .40),
        ("normalization", 42, .35, .70),
    )
    pools: dict[str, tuple[np.ndarray, list[str]]] = {}
    for phase, length, lower, upper in phase_contract:
        pools[phase] = _conditional_block_pool(
            rows, labels, selected_cluster, source_dates, source_levels,
            length=length, lower_quantile=lower, upper_quantile=upper,
        )
    rng = np.random.default_rng(seed + 20011)
    sampled = np.empty((count, horizon), dtype=float)
    origin_counts: dict[str, int] = {}
    provenance: list[list[Any]] = []
    for row in range(count):
        cursor = 0
        cycle = 0
        while cursor < horizon:
            for phase, registered_length, _, _ in phase_contract:
                if cursor >= horizon:
                    break
                pool, starts = pools[phase]
                choice = int(rng.integers(0, len(pool)))
                length = min(registered_length, horizon - cursor)
                sampled[row, cursor:cursor + length] = (
                    pool[choice, :length] * shadow_amplitude_scale
                )
                start = starts[choice]
                origin_counts[start] = origin_counts.get(start, 0) + 1
                provenance.append([row, cycle, phase, length, start])
                cursor += length
            cycle += 1
    probabilities = np.asarray(list(origin_counts.values()), dtype=float)
    probabilities /= probabilities.sum()
    return sampled, {
        "generator": "balanced_soft_landing_phase_sampler_v2",
        "phase_cycle": [
            {"phase": phase, "sessions": length, "return_quantiles": [lower, upper]}
            for phase, length, lower, upper in phase_contract
        ],
        "unique_source_origins": len(origin_counts),
        "episode_sampling_ess": float(1.0 / np.square(probabilities).sum()),
        "maximum_episode_probability": float(probabilities.max()),
        "block_provenance_sha256": hashlib.sha256(
            json.dumps(provenance, separators=(",", ":")).encode()
        ).hexdigest(),
        "residual_scale": shadow_amplitude_scale,
        "residual_policy": "independent_full_realized_balanced_blocks",
        "forced_endpoint": False,
        "forced_turning_date": False,
    }


def _sample_stress_regime_paths(
    *, rows: list[dict[str, Any]], labels: np.ndarray, selected_cluster: int,
    source_dates: list[str], source_levels: np.ndarray, horizon: int,
    count: int, seed: int, shadow_amplitude_scale: float = 1.0,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Generate S3 from tightening drawdown, failed-relief, and persistence blocks."""
    phase_contract = (
        ("drawdown", 42, .10, .45),
        ("failed_relief", 42, .70, 1.00),
        ("stress_persistence", 42, .30, .60),
    )
    pools: dict[str, tuple[np.ndarray, list[str]]] = {}
    for phase, length, lower, upper in phase_contract:
        pools[phase] = _conditional_block_pool(
            rows, labels, selected_cluster, source_dates, source_levels,
            length=length, lower_quantile=lower, upper_quantile=upper,
        )
    rng = np.random.default_rng(seed + 30011)
    sampled = np.empty((count, horizon), dtype=float)
    origin_counts: dict[str, int] = {}
    phase_counts = {phase: 0 for phase, *_ in phase_contract}
    provenance: list[list[Any]] = []
    for row in range(count):
        cursor = 0
        cycle = 0
        while cursor < horizon:
            for phase, registered_length, _, _ in phase_contract:
                if cursor >= horizon:
                    break
                pool, starts = pools[phase]
                choice = int(rng.integers(0, len(pool)))
                length = min(registered_length, horizon - cursor)
                sampled[row, cursor:cursor + length] = (
                    pool[choice, :length] * shadow_amplitude_scale
                )
                start = starts[choice]
                origin_counts[start] = origin_counts.get(start, 0) + 1
                phase_counts[phase] += 1
                provenance.append([row, cycle, phase, length, start])
                cursor += length
            cycle += 1
    probabilities = np.asarray(list(origin_counts.values()), dtype=float)
    probabilities /= probabilities.sum()
    return sampled, {
        "generator": "tightening_stress_phase_sampler_v2",
        "phase_cycle": [
            {"phase": phase, "sessions": length, "return_quantiles": [lower, upper]}
            for phase, length, lower, upper in phase_contract
        ],
        "phase_block_counts": phase_counts,
        "unique_source_origins": len(origin_counts),
        "episode_sampling_ess": float(1.0 / np.square(probabilities).sum()),
        "maximum_episode_probability": float(probabilities.max()),
        "block_provenance_sha256": hashlib.sha256(
            json.dumps(provenance, separators=(",", ":")).encode()
        ).hexdigest(),
        "residual_scale": shadow_amplitude_scale,
        "residual_policy": "independent_full_realized_tightening_stress_blocks",
        "forced_endpoint": False,
        "forced_turning_date": False,
    }


def _phase_pool(
    rows: list[dict[str, Any]], labels: np.ndarray, selected_cluster: int,
    source_dates: list[str], source_levels: np.ndarray, *, phase: str, length: int,
) -> tuple[np.ndarray, list[str]]:
    """Build a preregistered historical phase-block library after labels freeze."""
    members = np.flatnonzero(labels == selected_cluster)
    source_returns = np.diff(np.log(source_levels))
    blocks: list[np.ndarray] = []
    starts: list[str] = []
    for member in members:
        origin = int(rows[int(member)]["index"])
        for offset in range(0, 253 - length + 1, 21):
            start = origin + offset
            stop = start + length
            if stop <= len(source_returns):
                blocks.append(source_returns[start:stop])
                starts.append(source_dates[start])
    if len(blocks) < 12:
        raise ScenarioClusterError(f"insufficient {phase} phase blocks")
    matrix = np.vstack(blocks)
    cumulative = matrix.sum(axis=1)
    if phase == "acceleration":
        keep = cumulative >= np.quantile(cumulative, .60)
    elif phase == "correction":
        keep = (cumulative < 0.0) & (cumulative <= np.quantile(cumulative, .40))
        if int(keep.sum()) < 8:
            keep = cumulative <= np.quantile(cumulative, .25)
    elif phase == "reacceleration":
        keep = cumulative >= np.quantile(cumulative, .55)
    else:
        raise ScenarioClusterError(f"unknown phase: {phase}")
    selected = np.flatnonzero(keep)
    if len(selected) < 8:
        raise ScenarioClusterError(f"{phase} phase library has fewer than 8 blocks")
    return matrix[selected], [starts[int(index)] for index in selected]


def _sample_phase_preserving_s1(
    *, dotcom_rows: list[dict[str, Any]], dotcom_labels: np.ndarray,
    dotcom_cluster: int, dotcom_dates: list[str], dotcom_levels: np.ndarray,
    easing_rows: list[dict[str, Any]], easing_labels: np.ndarray,
    easing_growth_cluster: int, easing_dates: list[str], easing_levels: np.ndarray,
    horizon: int, count: int, seed: int, dotcom_share: float,
    allow_shadow_cap_exceed: bool = False,
) -> tuple[np.ndarray, dict[str, Any]]:
    if not 0.0 <= dotcom_share <= 1.0 \
            or (dotcom_share > .60 and not allow_shadow_cap_exceed):
        raise ScenarioClusterError("active S1 dotcom generator share exceeds 0.60 cap")
    phase_contract = (
        ("acceleration", 42), ("correction", 10), ("reacceleration", 74),
    )
    pools: dict[str, dict[str, tuple[np.ndarray, list[str]]]] = {
        "dotcom": {}, "easing_macro": {},
    }
    for phase, length in phase_contract:
        pools["dotcom"][phase] = _phase_pool(
            dotcom_rows, dotcom_labels, dotcom_cluster, dotcom_dates,
            dotcom_levels, phase=phase, length=length,
        )
        pools["easing_macro"][phase] = _phase_pool(
            easing_rows, easing_labels, easing_growth_cluster, easing_dates,
            easing_levels, phase=phase, length=length,
        )
    source_rng = np.random.default_rng(seed + 10007)
    block_rngs = {
        "dotcom": np.random.default_rng(seed + 10009),
        "easing_macro": np.random.default_rng(seed + 10037),
    }
    sampled = np.empty((count, horizon), dtype=float)
    source_sessions = {"dotcom": 0, "easing_macro": 0}
    source_blocks = {"dotcom": 0, "easing_macro": 0}
    phase_blocks = {phase: 0 for phase, _ in phase_contract}
    origin_counts: dict[str, int] = {}
    provenance_rows: list[list[Any]] = []
    samples: list[dict[str, Any]] = []
    for row in range(count):
        cursor = 0
        cycle = 0
        while cursor < horizon:
            for phase, registered_length in phase_contract:
                if cursor >= horizon:
                    break
                length = min(registered_length, horizon - cursor)
                source = "dotcom" if source_rng.random() < dotcom_share else "easing_macro"
                pool, start_dates = pools[source][phase]
                choice = int(block_rngs[source].integers(0, len(pool)))
                sampled[row, cursor:cursor + length] = pool[choice, :length]
                start_date = start_dates[choice]
                source_sessions[source] += length
                source_blocks[source] += 1
                phase_blocks[phase] += 1
                origin_key = f"{source}:{start_date}"
                origin_counts[origin_key] = origin_counts.get(origin_key, 0) + 1
                provenance_rows.append([row, cycle, phase, length, source, start_date])
                if len(samples) < 18:
                    samples.append({
                        "path_index": row, "cycle": cycle, "phase": phase,
                        "sessions": length, "source": source,
                        "source_start_date": start_date,
                    })
                cursor += length
            cycle += 1
    total_sessions = sum(source_sessions.values())
    total_blocks = sum(source_blocks.values())
    block_probabilities = np.asarray(list(origin_counts.values()), dtype=float) / total_blocks
    digest = hashlib.sha256(
        json.dumps(provenance_rows, separators=(",", ":")).encode()
    ).hexdigest()
    return sampled, {
        "generator": "phase_preserving_historical_block_sampler_v1",
        "phase_cycle": [
            {"phase": phase, "sessions": length} for phase, length in phase_contract
        ],
        "generator_dotcom_block_share_B": dotcom_share,
        "above_cap_shadow_only": dotcom_share > .60,
        "realized_dotcom_session_share": source_sessions["dotcom"] / total_sessions,
        "source_session_counts": source_sessions,
        "source_block_counts": source_blocks,
        "phase_block_counts": phase_blocks,
        "unique_source_origins": len(origin_counts),
        "episode_sampling_ess": float(1.0 / np.square(block_probabilities).sum()),
        "maximum_episode_probability": float(block_probabilities.max()),
        "top_source_origins": [
            {"source_origin": key, "block_count": value}
            for key, value in sorted(
                origin_counts.items(), key=lambda item: (-item[1], item[0])
            )[:12]
        ],
        "block_provenance_sha256": digest,
        "block_provenance_sample": samples,
        "residual_scale": 1.0,
        "residual_policy": "full_realized_returns_inside_phase_blocks",
        "block_selection_seed_streams": {
            "source": seed + 10007,
            "dotcom": seed + 10009,
            "easing_macro": seed + 10037,
        },
        "forced_endpoint": False,
        "forced_turning_date": False,
        "phase_boundaries_are_generator_structure_not_exact_date_forecasts": True,
    }


def _runs(labels: list[str]) -> list[tuple[str, int, int]]:
    result: list[tuple[str, int, int]] = []
    start = 0
    for index in range(1, len(labels) + 1):
        if index == len(labels) or labels[index] != labels[start]:
            result.append((labels[start], start, index))
            start = index
    return result


def _merge_short_phase_runs(labels: list[str], minimum: int) -> list[str]:
    labels = list(labels)
    for _ in range(20):
        runs = _runs(labels)
        short = next((row for row in runs if row[2] - row[1] < minimum), None)
        if short is None or len(runs) == 1:
            break
        index = runs.index(short)
        neighbors = []
        if index:
            neighbors.append(runs[index - 1])
        if index + 1 < len(runs):
            neighbors.append(runs[index + 1])
        target = max(neighbors, key=lambda row: row[2] - row[1])[0]
        labels[short[1]:short[2]] = [target] * (short[2] - short[1])
    return labels


def _phase_labels(scenario: str, returns: np.ndarray) -> list[str]:
    if len(returns) < 12:
        raise ScenarioClusterError("episode is too short for phase extraction")
    rolling = np.convolve(returns, np.ones(10), mode="full")[:len(returns)]
    rolling[:9] = np.cumsum(returns[:9])
    lower, upper = np.quantile(rolling, [.30, .70])
    labels: list[str] = []
    adverse_seen = False
    relief_seen = False
    for value in rolling:
        if scenario == "S1":
            if value <= lower:
                label = "correction"
                adverse_seen = True
            else:
                label = "reacceleration" if adverse_seen else "acceleration"
        elif scenario == "S2":
            if value <= lower:
                label = "mean_reversion"
                adverse_seen = True
            elif value >= upper and adverse_seen:
                label = "normalization"
            else:
                label = "steady_drift"
        elif scenario == "S3":
            if value >= upper:
                label = "failed_relief"
                relief_seen = True
            elif value <= lower:
                label = "stress_persistence" if relief_seen else "drawdown"
            else:
                label = "stress_persistence" if relief_seen else "drawdown"
        else:
            raise ScenarioClusterError(f"unknown phase scenario: {scenario}")
        labels.append(label)
    return _merge_short_phase_runs(labels, 3)


def _episode_segment_library(
    *, scenario: str, episodes: list[dict[str, Any]], source_dates: list[str],
    source_levels: np.ndarray, maximum_segment_sessions: int,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    source_returns = np.diff(np.log(source_levels))
    phases = {
        "S1": ("acceleration", "correction", "reacceleration"),
        "S2": ("steady_drift", "mean_reversion", "normalization"),
        "S3": ("drawdown", "failed_relief", "stress_persistence"),
    }[scenario]
    library: dict[str, list[dict[str, Any]]] = {phase: [] for phase in phases}
    episode_kernels: list[dict[str, Any]] = []
    for episode in episodes:
        indexes = [
            index for index, session in enumerate(source_dates[:-1])
            if str(episode["start"]) <= session <= str(episode["end"])
        ]
        if len(indexes) < 12 or indexes != list(range(indexes[0], indexes[-1] + 1)):
            raise ScenarioClusterError(f"episode coverage is incomplete: {episode['id']}")
        values = source_returns[indexes].copy()
        # S2 transports the episode's realized deviations, not its historical
        # endpoint.  This keeps the observed sideways/mean-reversion geometry
        # while avoiding a hidden bullish drift imported from a later outcome.
        # No path endpoint is set: recombined observed deviations still have a
        # full distribution of terminal values.
        if scenario == "S2":
            values -= float(values.mean())
        labels = _phase_labels(scenario, values)
        for phase, start, stop in _runs(labels):
            cursor = start
            while cursor < stop:
                end = min(stop, cursor + maximum_segment_sessions)
                if end - cursor >= 3:
                    absolute_start = indexes[0] + cursor
                    library[phase].append({
                        "returns": values[cursor:end].copy(),
                        "duration": end - cursor,
                        "episode_id": str(episode["id"]),
                        "episode_group": str(episode["group"]),
                        "start_date": source_dates[absolute_start],
                        "end_date": source_dates[absolute_start + end - cursor - 1],
                    })
                cursor = end
        episode_levels = np.exp(np.r_[0.0, np.cumsum(values)])
        drawdowns = episode_levels / np.maximum.accumulate(episode_levels) - 1.0
        trough = int(np.argmin(drawdowns))
        prior_peak = float(np.max(episode_levels[:trough + 1]))
        recovered = np.flatnonzero(episode_levels[trough:] >= prior_peak)
        episode_kernels.append({
            "episode_id": str(episode["id"]),
            "maximum_drawdown": float(drawdowns.min()),
            "time_to_trough": trough,
            "recovery_or_censor_duration": int(recovered[0]) if recovered.size
            else len(episode_levels) - trough - 1,
            "recovery_censored": not bool(recovered.size),
        })
    missing = [phase for phase, rows in library.items() if len(rows) < 3]
    if missing:
        raise ScenarioClusterError(f"insufficient empirical phase segments: {missing}")
    return library, episode_kernels


def _kernel_summary_from_paths(log_returns: np.ndarray) -> dict[str, float]:
    levels = np.exp(np.c_[np.zeros(len(log_returns)), np.cumsum(log_returns, axis=1)])
    running = np.maximum.accumulate(levels, axis=1)
    drawdowns = levels / running - 1.0
    maximum = drawdowns.min(axis=1)
    troughs = drawdowns.argmin(axis=1)
    recovery: list[int] = []
    for row, trough in zip(levels, troughs, strict=True):
        peak = float(np.max(row[:trough + 1]))
        hits = np.flatnonzero(row[trough:] >= peak)
        recovery.append(int(hits[0]) if hits.size else len(row) - int(trough) - 1)
    return {
        "maximum_drawdown_median": float(np.median(maximum)),
        "time_to_trough_median": float(np.median(troughs)),
        "recovery_or_censor_duration_median": float(np.median(recovery)),
    }


def _empirical_distribution(values: list[float]) -> dict[str, float]:
    array = np.asarray(values, dtype=float)
    return {
        "p05": float(np.quantile(array, .05)),
        "p50": float(np.median(array)),
        "p95": float(np.quantile(array, .95)),
    }


def _sample_empirical_episode_paths(
    *, scenario: str, episodes: list[dict[str, Any]], source_dates: list[str],
    source_levels: np.ndarray, horizon: int, count: int, seed: int,
    structural_adapter: dict[str, Any], dotcom_share: float = 0.0,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Sample variable-length observed segments without a fixed phase template."""
    library, episode_kernels = _episode_segment_library(
        scenario=scenario,
        episodes=episodes,
        source_dates=source_dates,
        source_levels=source_levels,
        maximum_segment_sessions=84,
    )
    rng = np.random.default_rng(seed + {"S1": 41003, "S2": 42013, "S3": 43019}[scenario])
    phase_names = tuple(library)
    empirical_phase_counts = np.asarray([len(library[name]) for name in phase_names], dtype=float)
    phase_probabilities = empirical_phase_counts / empirical_phase_counts.sum()
    phase_index = {name: index for index, name in enumerate(phase_names)}
    transition_counts = np.zeros((len(phase_names), len(phase_names)), dtype=float)
    for episode in episodes:
        sequence = sorted(
            [
                (row["start_date"], phase)
                for phase, rows in library.items() for row in rows
                if row["episode_id"] == episode["id"]
            ],
            key=lambda row: row[0],
        )
        for (_, left), (_, right) in zip(sequence, sequence[1:]):
            transition_counts[phase_index[left], phase_index[right]] += 1.0
    transition_probabilities = np.empty_like(transition_counts)
    for index, counts in enumerate(transition_counts):
        transition_probabilities[index] = (
            counts / counts.sum() if counts.sum() else phase_probabilities
        )
    current_start_phase = {
        "S1": "acceleration", "S2": "steady_drift", "S3": "drawdown",
    }[scenario]
    start_probabilities = phase_probabilities * .30
    start_probabilities[phase_index[current_start_phase]] += .70
    sampled = np.empty((count, horizon), dtype=float)
    provenance: list[list[Any]] = []
    origin_counts: dict[str, int] = {}
    sampled_durations: dict[str, list[int]] = {name: [] for name in phase_names}
    group_sessions: dict[str, int] = {}
    group_blocks: dict[str, int] = {}
    phase_blocks: dict[str, int] = {name: 0 for name in phase_names}
    phase_sequences: list[str] = []
    adverse_starts: list[int] = []
    adverse_durations: list[int] = []
    group_multipliers = structural_adapter["episode_group_weight_multipliers"][scenario]
    duration_tilts = structural_adapter["phase_duration_selection_tilts"][scenario]
    adverse_phase = {"S1": "correction", "S2": "mean_reversion", "S3": "drawdown"}[scenario]
    for path_index in range(count):
        cursor = 0
        sequence: list[str] = []
        first_adverse: int | None = None
        first_adverse_duration: int | None = None
        phase = str(rng.choice(phase_names, p=start_probabilities))
        while cursor < horizon:
            candidates = library[phase]
            durations = np.asarray([row["duration"] for row in candidates], dtype=float)
            median_duration = max(float(np.median(durations)), 1.0)
            weights = np.asarray([
                float(group_multipliers.get(str(row["episode_group"]), 1.0))
                * math.exp(float(duration_tilts.get(phase, 0.0))
                           * (float(row["duration"]) / median_duration - 1.0))
                for row in candidates
            ], dtype=float)
            if scenario == "S1":
                dotcom = np.asarray([
                    str(row["episode_group"]) == "dotcom" for row in candidates
                ])
                if dotcom.any() and (~dotcom).any():
                    weights[dotcom] *= dotcom_share / float(weights[dotcom].sum())
                    weights[~dotcom] *= (1.0 - dotcom_share) / float(weights[~dotcom].sum())
            if not np.isfinite(weights).all() or float(weights.sum()) <= 0:
                raise ScenarioClusterError("invalid empirical episode selection weights")
            probabilities = weights / float(weights.sum())
            choice = int(rng.choice(len(candidates), p=probabilities))
            row = candidates[choice]
            length = min(int(row["duration"]), horizon - cursor)
            sampled[path_index, cursor:cursor + length] = row["returns"][:length]
            sequence.append(phase)
            sampled_durations[phase].append(length)
            group = str(row["episode_group"])
            group_sessions[group] = group_sessions.get(group, 0) + length
            group_blocks[group] = group_blocks.get(group, 0) + 1
            phase_blocks[phase] += 1
            if phase == adverse_phase and first_adverse is None:
                first_adverse, first_adverse_duration = cursor, length
            origin = f"{row['episode_id']}:{row['start_date']}"
            origin_counts[origin] = origin_counts.get(origin, 0) + 1
            provenance.append([
                path_index, len(sequence) - 1, phase, length,
                row["episode_id"], row["episode_group"], row["start_date"], row["end_date"],
            ])
            cursor += length
            phase = str(rng.choice(
                phase_names, p=transition_probabilities[phase_index[phase]]
            ))
        phase_sequences.append(">".join(sequence[:8]))
        adverse_starts.append(horizon if first_adverse is None else first_adverse)
        adverse_durations.append(0 if first_adverse_duration is None else first_adverse_duration)
    probabilities = np.asarray(list(origin_counts.values()), dtype=float)
    probabilities /= probabilities.sum()
    empirical_durations = {
        phase: [int(row["duration"]) for row in rows]
        for phase, rows in library.items()
    }
    duration_audit = {
        phase: {
            "empirical": {
                "count": len(empirical_durations[phase]),
                "minimum": min(empirical_durations[phase]),
                "p50": float(np.median(empirical_durations[phase])),
                "maximum": max(empirical_durations[phase]),
                "variance": float(np.var(empirical_durations[phase])),
            },
            "sampled": {
                "count": len(sampled_durations[phase]),
                "p50": float(np.median(sampled_durations[phase])),
                "variance": float(np.var(sampled_durations[phase])),
            },
        }
        for phase in phase_names
    }
    generated_kernel = _kernel_summary_from_paths(sampled[:, :min(252, horizon)])
    empirical_kernel = {
        "maximum_drawdown": _empirical_distribution([
            row["maximum_drawdown"] for row in episode_kernels
        ]),
        "time_to_trough": _empirical_distribution([
            row["time_to_trough"] for row in episode_kernels
        ]),
        "recovery_or_censor_duration": _empirical_distribution([
            row["recovery_or_censor_duration"] for row in episode_kernels
        ]),
    }
    kernel_checks = {
        metric: bounds["p05"] <= generated_kernel[f"{metric}_median"] <= bounds["p95"]
        for metric, bounds in empirical_kernel.items()
    }
    residual_payload = [
        [phase, row["episode_id"], row["start_date"], row["duration"],
         [round(float(value), 12) for value in row["returns"]]]
        for phase, rows in library.items() for row in rows
    ]
    return sampled, {
        "generator": f"{scenario.lower()}_empirical_variable_episode_sampler_v3",
        "fixed_phase_template": False,
        "phase_sampling": "empirical_occurrence_distribution_with_observed_duration_segments",
        "phase_transition_policy": "empirical_with_current_state_start_no_fixed_cycle",
        "current_state_start_phase": current_start_phase,
        "current_state_start_probability": 0.70,
        "empirical_transition_counts": {
            left: {
                right: int(transition_counts[phase_index[left], phase_index[right]])
                for right in phase_names
            }
            for left in phase_names
        },
        "phase_names": list(phase_names),
        "phase_duration_distribution": duration_audit,
        "phase_cycle": [
            {
                "phase": phase,
                "duration_source": "empirical_distribution",
                "minimum_sessions": duration_audit[phase]["empirical"]["minimum"],
                "median_sessions": duration_audit[phase]["empirical"]["p50"],
                "maximum_sessions": duration_audit[phase]["empirical"]["maximum"],
            }
            for phase in phase_names
        ],
        "phase_repetition_gate": {
            "first_adverse_phase_start_variance": float(np.var(adverse_starts)),
            "adverse_phase_duration_variance": float(np.var(adverse_durations)),
            "unique_phase_sequence_count": len(set(phase_sequences)),
            "gate_pass": (
                float(np.var(adverse_starts)) >= 1.0
                and float(np.var(adverse_durations)) >= 1.0
                and len(set(phase_sequences)) >= 3
            ),
        },
        "episode_ids": [str(row["id"]) for row in episodes],
        "episode_count": len(episodes),
        "drift_transport": (
            "episode_native_mean_removed_shape_only" if scenario == "S2"
            else "native_observed_log_returns"
        ),
        "episode_group_weight_multipliers": group_multipliers,
        "source_session_counts": group_sessions,
        "source_block_counts": group_blocks,
        "phase_block_counts": phase_blocks,
        "realized_dotcom_session_share": (
            group_sessions.get("dotcom", 0) / max(sum(group_sessions.values()), 1)
            if scenario == "S1" else 0.0
        ),
        "phase_duration_selection_tilts": duration_tilts,
        "structural_event_update_applied": structural_adapter["structural_update_applied"],
        "probability_only_event_update": False,
        "unique_source_origins": len(origin_counts),
        "episode_sampling_ess": float(1.0 / np.square(probabilities).sum()),
        "maximum_episode_probability": float(probabilities.max()),
        "block_provenance_sha256": hashlib.sha256(
            json.dumps(provenance, separators=(",", ":")).encode()
        ).hexdigest(),
        "block_provenance_sample": [
            {
                "path_index": row[0], "segment_index": row[1], "phase": row[2],
                "sessions": row[3], "episode_id": row[4], "episode_group": row[5],
                "source_start_date": row[6], "source_end_date": row[7],
            }
            for row in provenance[:18]
        ],
        "residual_pool_sha256": hashlib.sha256(
            json.dumps(residual_payload, separators=(",", ":")).encode()
        ).hexdigest(),
        "residual_scale": 1.0,
        "residual_policy": f"{scenario}_observed_episode_segments_only_no_cross_pool",
        "kernel_audit": {
            "empirical_episode_count": len(episode_kernels),
            "empirical": empirical_kernel,
            "generated": generated_kernel,
            "checks": kernel_checks,
            "gate_pass": all(kernel_checks.values()),
            "failure_action": "report_only_and_promotion_blocked",
        },
        "forced_endpoint": False,
        "forced_turning_date": False,
    }


def build_clustered_prior(
    general_dates: list[str], general_levels: np.ndarray,
    dotcom_manifest: dict[str, Any], macro_manifest: dict[str, Any],
    *, horizon: int, count_per_scenario: int, seed: int,
    restart_probability: float, anchor: float, weight_contract: dict[str, Any],
    generator_dotcom_share: float | None = None,
    residual_scale_override: float | None = None,
    allow_shadow_cap_exceed: bool = False,
    separation_contract: dict[str, Any] | None = None,
    structural_adapter: dict[str, Any] | None = None,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    if count_per_scenario < 20:
        raise ScenarioClusterError("at least 20 paths per scenario are required")
    if separation_contract is None or structural_adapter is None:
        raise ScenarioClusterError("complete-separation contract and adapter are required")
    if residual_scale_override is not None \
            and not math.isclose(float(residual_scale_override), 1.0):
        raise ScenarioClusterError(
            "complete-separation residual pools cannot be amplitude-rescaled"
        )
    macro_dates, macro_levels, macro_series = _macro_source(macro_manifest)
    current_macro_full = _current_macro_features(
        macro_dates, macro_levels, macro_series
    )
    episode_contracts = separation_contract.get("episode_libraries", {})
    feature_contracts = separation_contract.get("scenario_feature_schemas", {})
    if set(episode_contracts) != {"S1", "S2", "S3"}:
        raise ScenarioClusterError("complete-separation episode libraries are incomplete")
    for scenario, names in SCENARIO_FEATURES.items():
        if tuple(feature_contracts.get(scenario, {}).get("active_coordinates", [])) != names:
            raise ScenarioClusterError(f"{scenario} code and contract feature schemas differ")
    scenario_rows = {
        scenario: _episode_rows(
            macro_dates, macro_levels, macro_series, horizon,
            scenario=scenario,
            episodes=list(episode_contracts[scenario]["episodes"]),
        )
        for scenario in ("S1", "S2", "S3")
    }
    macro_origin_sets = {
        scenario: {row["date"] for row in rows}
        for scenario, rows in scenario_rows.items()
    }
    macro_origin_overlaps = {
        f"{left}__{right}": len(macro_origin_sets[left] & macro_origin_sets[right])
        for left, right in (
            ("S1", "S2"), ("S1", "S3"), ("S2", "S3"),
        )
    }
    if any(macro_origin_overlaps.values()):
        raise ScenarioClusterError(
            f"scenario macro cohorts overlap: {macro_origin_overlaps}"
        )
    generators = weight_contract.get("scenario_generators", {})
    spaces = weight_contract.get("weight_spaces", {})
    if set(generators) != {"S1", "S2", "S3"}:
        raise ScenarioClusterError("weight contract must define S1/S2/S3 generators")
    active_b = float(
        spaces.get("B_generator_dotcom_block_share", {}).get("active", -1)
        if generator_dotcom_share is None else generator_dotcom_share
    )
    cap_b = float(spaces.get("B_generator_dotcom_block_share", {}).get("cap", -1))
    if not 0.0 <= active_b <= 1.0 or not math.isclose(cap_b, .60) \
            or (active_b > cap_b and not allow_shadow_cap_exceed):
        raise ScenarioClusterError("active B generator share exceeds the 0.60 cap")
    configurations = {
        "S1": {
            "source_group": episode_contracts["S1"]["source_group"],
            "dates": macro_dates,
            "levels": macro_levels,
            "rows": scenario_rows["S1"],
            "features": SCENARIO_FEATURES["S1"],
            "clusters": 5,
            "current": _scenario_feature_subset(current_macro_full, "S1"),
            "residual_scale": float(generators["S1"]["residual_policy"]["scale"]),
            "minimum_origins": int(generators["S1"]["selected_cluster_minimum_origins"]),
            "selection_rule": "maximum cluster-level expansion score",
        },
        "S2": {
            "source_group": episode_contracts["S2"]["source_group"],
            "dates": macro_dates,
            "levels": macro_levels,
            "rows": scenario_rows["S2"],
            "features": SCENARIO_FEATURES["S2"],
            "clusters": 4,
            "current": _scenario_feature_subset(current_macro_full, "S2"),
            "residual_scale": float(generators["S2"]["residual_policy"]["scale"]),
            "minimum_origins": int(generators["S2"]["selected_cluster_minimum_origins"]),
            "selection_rule": (
                "minimum absolute cluster-level 126d return among moderate "
                "positive 252d clusters"
            ),
        },
        "S3": {
            "source_group": episode_contracts["S3"]["source_group"],
            "dates": macro_dates,
            "levels": macro_levels,
            "rows": scenario_rows["S3"],
            "features": SCENARIO_FEATURES["S3"],
            "clusters": 4,
            "current": _scenario_feature_subset(current_macro_full, "S3"),
            "residual_scale": float(generators["S3"]["residual_policy"]["scale"]),
            "minimum_origins": int(generators["S3"]["selected_cluster_minimum_origins"]),
            "selection_rule": "minimum cluster-level stress score",
        },
    }
    audit_scenarios: dict[str, Any] = {}
    cluster_state: dict[str, dict[str, Any]] = {}
    scenario_index = {"S1": 0, "S2": 1, "S3": 2}
    for scenario, config in configurations.items():
        rows = config["rows"]
        features = np.asarray([row["features"] for row in rows])
        labels, medoids, center, scale = deterministic_k_medoids(
            features, int(config["clusters"])
        )
        clusters = _cluster_audit(rows, labels, medoids, config["features"])
        selected = _select_cluster(scenario, clusters, int(config["minimum_origins"]))
        selected_audit = next(row for row in clusters if row["cluster_id"] == selected)
        cluster_state[scenario] = {
            "rows": rows, "labels": labels, "center": center, "scale": scale,
            "selected": selected, "config": config, "clusters": clusters,
        }
        audit_scenarios[scenario] = {
            "source_group": config["source_group"],
            "feature_names": list(config["features"]),
            "origin_count": len(rows),
            "cluster_count": int(config["clusters"]),
            "selected_cluster_id": selected,
            "selected_cluster": selected_audit,
            "selection_rule": config["selection_rule"],
            "selected_cluster_minimum_origins": int(config["minimum_origins"]),
            "requested_promotion_minimum_origins": int(
                generators[scenario]["requested_promotion_minimum_origins"]
            ),
            "cluster_assignments_sha256": _assignment_hash(rows, labels),
            "clustering_uses_forward_outcomes": False,
            "outcomes_used_after_assignment_for_cluster_label_only": True,
            "cluster_inventory": clusters,
        }
    log_return_blocks: list[np.ndarray] = []
    engine_blocks: list[np.ndarray] = []
    for offset, scenario in enumerate(("S1", "S2", "S3")):
        state = cluster_state[scenario]
        config = state["config"]
        sampled, sampling = _sample_empirical_episode_paths(
            scenario=scenario,
            episodes=list(episode_contracts[scenario]["episodes"]),
            source_dates=macro_dates,
            source_levels=macro_levels,
            horizon=horizon,
            count=count_per_scenario,
            seed=seed,
            structural_adapter=structural_adapter,
            dotcom_share=active_b if scenario == "S1" else 0.0,
        )
        members = np.flatnonzero(state["labels"] == state["selected"])
        selected_features = np.asarray([
            state["rows"][int(index)]["features"] for index in members
        ])
        distances = np.linalg.norm(
            (selected_features - state["center"]) / state["scale"]
            - (config["current"] - state["center"])[None, :] / state["scale"],
            axis=1,
        )
        sampling.update({
            "selected_origin_count": int(
                audit_scenarios[scenario]["selected_cluster"]["origin_count"]
            ),
            "simulation_path_count": count_per_scenario,
            "sampled_origin_count": int(sampling["unique_source_origins"]),
            "current_state_similarity": float(math.exp(
                -float(distances.min()) / math.sqrt(len(config["current"]))
            )),
        })
        audit_scenarios[scenario]["sampling"] = sampling
        log_return_blocks.append(sampled)
        engine_blocks.append(np.full(count_per_scenario, scenario_index[scenario], dtype=int))
    medians = {
        scenario: row["selected_cluster"]["outcome_medians"]
        for scenario, row in audit_scenarios.items()
    }
    label_gates = {
        "S1_positive_252d": medians["S1"]["forward_return_252d"] > .15,
        "S2_moderate_126d": abs(medians["S2"]["forward_return_126d"]) < .08,
        "S2_moderate_252d": .05 < medians["S2"]["forward_return_252d"] < .35,
        "S3_negative_252d": medians["S3"]["forward_return_252d"] < -.15,
        "S3_stress_drawdown": medians["S3"]["maximum_drawdown_252d"] < -.30,
        "ordered_252d": (
            medians["S1"]["forward_return_252d"]
            > medians["S2"]["forward_return_252d"]
            > medians["S3"]["forward_return_252d"]
        ),
    }
    if not all(label_gates.values()):
        raise ScenarioClusterError(f"scenario cluster label gate failed: {label_gates}")
    log_returns = np.vstack(log_return_blocks)
    paths = np.column_stack((
        np.full(log_returns.shape[0], anchor),
        anchor * np.exp(np.cumsum(log_returns, axis=1)),
    ))
    if not np.isfinite(paths).all() or float(paths.min()) <= 0:
        raise ScenarioClusterError("clustered scenario prior has invalid levels")
    engines = np.concatenate(engine_blocks)
    base_scores = {}
    for scenario, row in audit_scenarios.items():
        selected = row["selected_cluster"]
        smoothed_prevalence = (
            (selected["origin_count"] + 5.0)
            / (row["origin_count"] + row["cluster_count"] * 5.0)
        )
        similarity = row["sampling"]["current_state_similarity"]
        base_scores[scenario] = math.sqrt(smoothed_prevalence) * similarity
        row["smoothed_cluster_prevalence"] = smoothed_prevalence
        row["base_scenario_score"] = base_scores[scenario]
    audit = {
        "method": "deterministic_k_medoids_then_cluster_level_outcome_labeling",
        "observation_spacing_sessions": 21,
        "cluster_assignment_information_set": "origin_state_features_only",
        "forward_outcome_use": "cluster_labeling_after_assignments_are_frozen",
        "individual_origin_outcome_selection": False,
        "episode_library_policy": (
            "preregistered non-overlapping historical intervals; scenario-specific "
            "feature schemas; outcomes withheld until assignments freeze"
        ),
        "macro_asof_join": "backward_only; source_date <= state_date",
        "scenario_path_count": count_per_scenario,
        "generator_weight_contract_id": weight_contract["contract_id"],
        "A_evidence_strength": float(
            spaces["A_evidence_strength"]["active"]
        ),
        "B_generator_dotcom_block_share": active_b,
        "B_above_cap_shadow_only": active_b > cap_b,
        "C_mixture_probability": "derived_after_evidence_weighting",
        "macro_regime_cohort_origin_counts": {
            key: len(value) for key, value in macro_origin_sets.items()
        },
        "macro_regime_cohort_origin_overlap": macro_origin_overlaps,
        "macro_regime_cohorts_disjoint": not any(macro_origin_overlaps.values()),
        "episode_interval_overlap_count": 0,
        "episode_ids_by_scenario": {
            scenario: [str(row["id"]) for row in episode_contracts[scenario]["episodes"]]
            for scenario in ("S1", "S2", "S3")
        },
        "feature_schemas_by_scenario": {
            scenario: list(SCENARIO_FEATURES[scenario])
            for scenario in ("S1", "S2", "S3")
        },
        "feature_schemas_distinct": len({
            tuple(SCENARIO_FEATURES[scenario]) for scenario in ("S1", "S2", "S3")
        }) == 3,
        "residual_pool_hashes_unique": len({
            row["sampling"]["residual_pool_sha256"]
            for row in audit_scenarios.values()
        }) == 3,
        "fixed_phase_template_prohibited": True,
        "fixed_phase_template_active": False,
        "phase_repetition_gates_pass": all(
            row["sampling"]["phase_repetition_gate"]["gate_pass"]
            for row in audit_scenarios.values()
        ),
        "kernel_gates_pass": all(
            row["sampling"]["kernel_audit"]["gate_pass"]
            for row in audit_scenarios.values()
        ),
        "structural_event_adapter": structural_adapter,
        "base_scenario_scores": base_scores,
        "scenarios": audit_scenarios,
        "label_gates": label_gates,
        "promotion_sample_gates": {
            scenario: (
                row["selected_cluster"]["origin_count"]
                >= row["requested_promotion_minimum_origins"]
            ) for scenario, row in audit_scenarios.items()
        },
        "promotion_sample_gate_pass": all(
            row["selected_cluster"]["origin_count"]
            >= row["requested_promotion_minimum_origins"]
            for row in audit_scenarios.values()
        ),
        "research_sample_exception": (
            "promotion origin minimum not met for "
            + ", ".join(
                f"{scenario}={row['selected_cluster']['origin_count']}/"
                f"{row['requested_promotion_minimum_origins']}"
                for scenario, row in audit_scenarios.items()
                if row["selected_cluster"]["origin_count"]
                < row["requested_promotion_minimum_origins"]
            )
            + "; overlapping origins and forward-outcome pooling are not used to inflate n"
        ),
        "promotion_structural_gate_pass": (
            all(
                row["selected_cluster"]["origin_count"]
                >= row["requested_promotion_minimum_origins"]
                for row in audit_scenarios.values()
            )
            and all(
                row["sampling"]["kernel_audit"]["gate_pass"]
                for row in audit_scenarios.values()
            )
        ),
        "gate_pass": all(label_gates.values()),
    }
    return paths, engines, audit
