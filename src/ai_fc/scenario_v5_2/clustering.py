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


def _macro_tightening_rows(
    dates: list[str], levels: np.ndarray,
    series: dict[str, tuple[list[str], np.ndarray]], horizon: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index in range(200, len(levels) - horizon, 21):
        session = dates[index]
        lag_session = dates[index - 63]
        rate_change = _asof_value(series, "DFF", session) \
            - _asof_value(series, "DFF", lag_session)
        two_year_change = _asof_value(series, "DGS2", session) \
            - _asof_value(series, "DGS2", lag_session)
        # Pre-outcome screen only: a tightening candidate enters before clustering
        # when either the policy rate or the two-year yield has risen materially.
        if not (rate_change > .10 or two_year_change > .25):
            continue
        macro_features = np.concatenate((
            _price_features(levels, index),
            np.asarray([
                rate_change,
                two_year_change,
                _asof_value(series, "T10Y2Y", session),
                _asof_value(series, "DGS10", session),
                _asof_value(series, "VIXCLS", session),
                _asof_value(series, "NFCI", session),
            ], dtype=float),
        ))
        rows.append({
            "index": index,
            "date": session,
            "features": macro_features,
            "outcomes": _outcomes(levels, index, horizon),
        })
    if len(rows) < 60:
        raise ScenarioClusterError("macro tightening pool has fewer than 60 origins")
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
    modern_rows: list[dict[str, Any]], modern_labels: np.ndarray,
    modern_growth_cluster: int, modern_dates: list[str], modern_levels: np.ndarray,
    horizon: int, count: int, seed: int, dotcom_share: float,
    allow_shadow_cap_exceed: bool = False,
) -> tuple[np.ndarray, dict[str, Any]]:
    if not 0.0 <= dotcom_share <= 1.0 \
            or (dotcom_share > .60 and not allow_shadow_cap_exceed):
        raise ScenarioClusterError("active S1 dotcom generator share exceeds 0.60 cap")
    phase_contract = (
        ("acceleration", 63), ("correction", 21), ("reacceleration", 42),
    )
    pools: dict[str, dict[str, tuple[np.ndarray, list[str]]]] = {
        "dotcom": {}, "modern_growth": {},
    }
    for phase, length in phase_contract:
        pools["dotcom"][phase] = _phase_pool(
            dotcom_rows, dotcom_labels, dotcom_cluster, dotcom_dates,
            dotcom_levels, phase=phase, length=length,
        )
        pools["modern_growth"][phase] = _phase_pool(
            modern_rows, modern_labels, modern_growth_cluster, modern_dates,
            modern_levels, phase=phase, length=length,
        )
    source_rng = np.random.default_rng(seed + 10007)
    block_rngs = {
        "dotcom": np.random.default_rng(seed + 10009),
        "modern_growth": np.random.default_rng(seed + 10037),
    }
    sampled = np.empty((count, horizon), dtype=float)
    source_sessions = {"dotcom": 0, "modern_growth": 0}
    source_blocks = {"dotcom": 0, "modern_growth": 0}
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
                source = "dotcom" if source_rng.random() < dotcom_share else "modern_growth"
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
            "modern_growth": seed + 10037,
        },
        "forced_endpoint": False,
        "forced_turning_date": False,
        "phase_boundaries_are_generator_structure_not_exact_date_forecasts": True,
    }


def build_clustered_prior(
    general_dates: list[str], general_levels: np.ndarray,
    dotcom_manifest: dict[str, Any], macro_manifest: dict[str, Any],
    *, horizon: int, count_per_scenario: int, seed: int,
    restart_probability: float, anchor: float, weight_contract: dict[str, Any],
    generator_dotcom_share: float | None = None,
    residual_scale_override: float | None = None,
    allow_shadow_cap_exceed: bool = False,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    if count_per_scenario < 20:
        raise ScenarioClusterError("at least 20 paths per scenario are required")
    dotcom_dates = [str(row["date"]) for row in dotcom_manifest["rows"]]
    dotcom_levels = np.asarray([
        _finite(row["close"], f"dotcom.{row['date']}")
        for row in dotcom_manifest["rows"]
    ])
    macro_dates, macro_levels, macro_series = _macro_source(macro_manifest)
    current_price_features = _price_features(general_levels, len(general_levels) - 1)
    current_macro_features = _current_macro_features(
        macro_dates, macro_levels, macro_series
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
            "source_group": "dotcom_price_state_db",
            "dates": dotcom_dates,
            "levels": dotcom_levels,
            "rows": _price_rows(dotcom_dates, dotcom_levels, horizon),
            "features": PRICE_FEATURES,
            "clusters": 5,
            "current": current_price_features,
            "residual_scale": float(generators["S1"]["residual_policy"]["scale"]),
            "minimum_origins": int(generators["S1"]["selected_cluster_minimum_origins"]),
            "selection_rule": "maximum cluster-level growth score",
        },
        "S2": {
            "source_group": "modern_general_market_state_db",
            "dates": general_dates,
            "levels": general_levels,
            "rows": _price_rows(general_dates, general_levels, horizon),
            "features": PRICE_FEATURES,
            "clusters": 5,
            "current": current_price_features,
            "residual_scale": float(generators["S2"]["residual_policy"]["scale"]),
            "minimum_origins": int(generators["S2"]["selected_cluster_minimum_origins"]),
            "selection_rule": (
                "minimum absolute cluster-level 126d return among moderate "
                "positive 252d clusters; n>=10"
            ),
        },
        "S3": {
            "source_group": "macro_tightening_financial_conditions_db",
            "dates": macro_dates,
            "levels": macro_levels,
            "rows": _macro_tightening_rows(
                macro_dates, macro_levels, macro_series, horizon
            ),
            "features": MACRO_FEATURES,
            "clusters": 4,
            "current": current_macro_features,
            "residual_scale": float(generators["S3"]["residual_policy"]["scale"]),
            "minimum_origins": int(generators["S3"]["selected_cluster_minimum_origins"]),
            "selection_rule": "minimum cluster-level stress score; n>=5",
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
    modern_growth_cluster = _select_cluster(
        "S1", cluster_state["S2"]["clusters"],
        int(configurations["S1"]["minimum_origins"]),
    )
    log_return_blocks: list[np.ndarray] = []
    engine_blocks: list[np.ndarray] = []
    for offset, scenario in enumerate(("S1", "S2", "S3")):
        state = cluster_state[scenario]
        config = state["config"]
        if scenario == "S1":
            sampled, sampling = _sample_phase_preserving_s1(
                dotcom_rows=state["rows"], dotcom_labels=state["labels"],
                dotcom_cluster=state["selected"], dotcom_dates=dotcom_dates,
                dotcom_levels=dotcom_levels,
                modern_rows=cluster_state["S2"]["rows"],
                modern_labels=cluster_state["S2"]["labels"],
                modern_growth_cluster=modern_growth_cluster,
                modern_dates=general_dates, modern_levels=general_levels,
                horizon=horizon, count=count_per_scenario, seed=seed,
                dotcom_share=active_b,
                allow_shadow_cap_exceed=allow_shadow_cap_exceed,
            )
            sampling.update({
                "selected_origin_count": int(
                    audit_scenarios[scenario]["selected_cluster"]["origin_count"]
                ),
                "simulation_path_count": count_per_scenario,
                "auxiliary_modern_growth_cluster_id": modern_growth_cluster,
            })
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
                "current_to_selected_medoid_distance": float(distances.min()),
                "current_state_similarity": float(math.exp(
                    -float(distances.min()) / math.sqrt(len(config["current"]))
                )),
                "sampled_origin_count": int(sampling["unique_source_origins"]),
            })
        else:
            residual_scale = (
                float(residual_scale_override)
                if residual_scale_override is not None
                else float(config["residual_scale"])
            )
            sampled, sampling = _sample_cluster_paths(
                state["rows"], state["labels"], state["selected"],
                config["levels"], config["current"], state["center"],
                state["scale"], horizon, count_per_scenario,
                np.random.default_rng(seed + offset * 101), residual_scale,
                restart_probability,
            )
        audit_scenarios[scenario]["sampling"] = sampling
        log_return_blocks.append(sampled)
        engine_blocks.append(np.full(count_per_scenario, scenario_index[scenario], dtype=int))
    medians = {
        scenario: row["selected_cluster"]["outcome_medians"]
        for scenario, row in audit_scenarios.items()
    }
    label_gates = {
        "S1_positive_252d": medians["S1"]["forward_return_252d"] > .15,
        "S2_sideways_126d": abs(medians["S2"]["forward_return_126d"]) < .05,
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
        "macro_tightening_pre_screen": (
            "DFF 63-session change > 0.10pp OR DGS2 change > 0.25pp"
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
        "modern_growth_auxiliary_cluster_id": modern_growth_cluster,
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
            "S2/S3 remain report-only below requested promotion origin counts; "
            "overlapping origins and forward-outcome pooling are not used to inflate n"
        ),
        "gate_pass": all(label_gates.values()),
    }
    return paths, engines, audit
