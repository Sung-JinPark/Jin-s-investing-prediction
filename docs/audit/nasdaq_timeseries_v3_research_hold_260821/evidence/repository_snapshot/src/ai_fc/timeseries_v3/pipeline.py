"""End-to-end V3 research pipeline over the immutable V2 PIT read models."""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from .backtest import (
    OriginScore, empirical_crps, evaluate_research_gate, pinball_loss,
    tail_weighted_crps,
)
from .baselines import FixedAnchorDistribution, _endpoint_windows
from .contracts import (
    LATEST_RELATIVE, LEDGER_RELATIVE, MODEL_ID, MODEL_VERSION, MODELS_RELATIVE,
    RUNS_RELATIVE, canonical_hash, frozen_hash, load_contract_v3, model_code_hash,
    verify_v2_benchmark,
)
from .interfaces import ComponentForecast
from .models.direct_location import AnalogQuantileModel, DirectHorizonModel
from .models.regime_mixture import REGIMES, SoftRegimeModel, mix_regime_residuals
from .models.volatility_tail import HorizonScaleModel, downside_semivariance
from .path_reconciler import (
    endpoint_errors, gaussian_copula_endpoints, path_duplicate_fraction, stochastic_bridge_paths,
)
from .stacking import StackedDistribution, constrained_loss_weights
from .targets import HORIZONS


FEATURES_RELATIVE = Path("data/timeseries_v2/parquet/features_C1.parquet")
MARKET_RELATIVE = Path("data/timeseries_v2/parquet/market_observations.parquet")


def _deps():
    try:
        import pandas as pd  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("install ai-fc[timeseries,pit] for V3") from exc
    return pd


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _append_jsonl(path: Path, payload: dict[str, Any], identity: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if json.loads(line).get(identity) == payload.get(identity):
                return False
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return True


def load_v3_frame(root: Path):
    pd = _deps()
    frame = pd.read_parquet(root / FEATURES_RELATIVE).sort_index()
    market = pd.read_parquet(root / MARKET_RELATIVE)
    market = market.sort_values(["series_id", "observation_time", "revision_seq"])
    market = market.drop_duplicates(["series_id", "observation_time"], keep="last")
    vix = market.loc[market["series_id"] == "VIX", ["observation_time", "value"]].copy()
    vix.index = pd.to_datetime(vix.pop("observation_time"))
    vix = vix.rename(columns={"value": "vix_level"})
    frame = frame.join(vix, how="left")
    frame["vix_level"] = frame["vix_level"].ffill(limit=3)
    returns = frame["nasdaq_return"].to_numpy(dtype=float)
    log_index = np.cumsum(np.nan_to_num(returns, nan=0.0))
    index = np.exp(log_index)

    def rolling_sum(window: int):
        return frame["nasdaq_return"].rolling(window).sum()

    engineered = pd.DataFrame(index=frame.index)
    for window in (21, 63, 126):
        engineered[f"trend_{window}"] = rolling_sum(window)
    series = pd.Series(index, index=frame.index)
    for window in (21, 63, 252):
        engineered[f"drawdown_{window}"] = series / series.rolling(window).max() - 1.0
    for window in (5, 21, 63):
        engineered[f"realized_vol_{window}"] = frame["nasdaq_return"].rolling(window).std() * np.sqrt(252)
    engineered["downside_semivariance_21"] = downside_semivariance(returns, 21)
    engineered["vix_level"] = np.log(frame["vix_level"].where(frame["vix_level"] > 0))
    engineered["vix_change"] = frame["vix_change"]
    engineered["vol_of_vol_21"] = frame["vix_change"].rolling(21).std()
    engineered["dgs2_change_bps"] = frame["dgs2_change_bps"] / 100.0
    engineered["curve_change_bps"] = frame["curve_change_bps"] / 100.0
    engineered["dollar_change"] = frame["dollar_change"]
    # Existing V2 cache lacks named loading vectors.  V3 refuses to call its levels aligned;
    # only age/masks are retained until V3-native aligned caches exist.
    engineered["dfm_age_since_release"] = frame["dfm_age_since_release"]
    engineered["dfm_available"] = np.isfinite(frame["growth_factor"] * frame["inflation_factor"]).astype(float)
    return frame, engineered.replace([np.inf, -np.inf], np.nan), returns, index


def direct_targets_from_returns(returns: np.ndarray) -> dict[int, np.ndarray]:
    values = np.asarray(returns, dtype=float)
    cumulative = np.concatenate(([0.0], np.cumsum(values)))
    output: dict[int, np.ndarray] = {}
    for horizon in HORIZONS:
        target = np.full(values.size, np.nan)
        for index in range(values.size - horizon):
            target[index] = cumulative[index + horizon + 1] - cumulative[index + 1]
        output[horizon] = target
    return output


def _weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    order = np.argsort(values)
    values = values[order]
    weights = weights[order]
    return float(values[np.searchsorted(np.cumsum(weights), 0.5 * weights.sum())])


def rolling_anchor_statistics(
    returns: np.ndarray, states: np.ndarray, *, history_sessions: int, filtered_neighbors: int,
) -> tuple[dict[int, np.ndarray], dict[int, np.ndarray]]:
    count = len(returns)
    medians = {h: np.full(count, np.nan) for h in HORIZONS}
    scales = {h: np.full(count, np.nan) for h in HORIZONS}
    for origin in range(max(HORIZONS) + 252, count):
        start = max(0, origin + 1 - history_sessions)
        history = returns[start:origin + 1]
        state_history = states[start:origin + 1]
        target = states[origin]
        center = np.nanmedian(state_history, axis=0)
        spread = np.nanmedian(np.abs(state_history - center), axis=0)
        spread = np.where(spread > 1e-12, spread, 1.0)
        distances = np.nanmean(((state_history - target) / spread) ** 2, axis=1)
        for horizon in HORIZONS:
            if len(history) <= horizon + 20:
                continue
            endpoints = _endpoint_windows(history, horizon)
            usable = min(len(endpoints), len(distances) - horizon)
            endpoints = endpoints[:usable]
            local_distances = np.nan_to_num(distances[:usable], nan=np.inf)
            keep = np.argsort(local_distances)[:max(20, min(filtered_neighbors, usable))]
            weights = np.exp(-0.5 * local_distances[keep])
            if not np.isfinite(weights).all() or weights.sum() <= 0:
                weights = np.ones(len(keep))
            filtered_median = _weighted_median(endpoints[keep], weights)
            historical_median = float(np.median(endpoints))
            medians[horizon][origin] = 0.70 * historical_median + 0.30 * filtered_median
            scales[horizon][origin] = float(np.std(endpoints, ddof=1))
    return medians, scales


def _gaussian_crps(mean: np.ndarray, sigma: np.ndarray, actual: np.ndarray) -> np.ndarray:
    from scipy.special import erf

    sigma = np.maximum(np.asarray(sigma, dtype=float), 1e-8)
    z = (np.asarray(actual) - np.asarray(mean)) / sigma
    phi = np.exp(-0.5 * z * z) / np.sqrt(2 * np.pi)
    cdf = 0.5 * (1 + erf(z / np.sqrt(2)))
    return sigma * (z * (2 * cdf - 1) + 2 * phi - 1 / np.sqrt(np.pi))


def _select_origin_alpha(
    features: np.ndarray, residual_targets: dict[int, np.ndarray], anchor_scales: dict[int, np.ndarray],
    *, train_end: int, alphas: tuple[float, ...], bounds: dict[int, float],
) -> tuple[float, dict[str, float]]:
    internal_start = max(0, train_end - 504)
    split = max(internal_start + 252, train_end - 104)
    train_slice = slice(internal_start, split)
    validation = np.arange(split, train_end)
    scores: dict[float, float] = {}
    for alpha in alphas:
        model = DirectHorizonModel.fit(
            features[train_slice], {h: values[train_slice] for h, values in residual_targets.items()},
            alpha=alpha, correction_sigma_bounds=bounds,
        )
        design = np.column_stack((
            np.ones(len(validation)),
            (np.where(np.isfinite(features[validation]), features[validation], model.feature_median) - model.feature_median)
            / model.feature_scale,
        ))
        losses: list[float] = []
        for horizon in HORIZONS:
            predicted = design @ model.coefficients[horizon]
            actual = residual_targets[horizon][validation]
            sigma = np.maximum(anchor_scales[horizon][validation], 1e-8)
            mask = np.isfinite(predicted) & np.isfinite(actual) & np.isfinite(sigma)
            losses.extend(_gaussian_crps(predicted[mask], sigma[mask], actual[mask]).tolist())
        scores[float(alpha)] = float(np.mean(losses))
    selected = min(scores, key=scores.get)
    return selected, {str(key): value for key, value in scores.items()}


def _select_analog_neighbors(
    features: np.ndarray, targets: dict[int, np.ndarray], *, candidates: tuple[int, ...],
    validation_origins: int, purge_sessions: int, embargo_sessions: int,
) -> tuple[dict[int, int], dict[str, dict[str, float]]]:
    count = len(features)
    validation = np.linspace(
        max(300, count - validation_origins * 5), count - 1,
        num=min(validation_origins, max(1, (count - 300) // 5)), dtype=int,
    )
    losses: dict[int, dict[int, list[float]]] = {
        horizon: {candidate: [] for candidate in candidates} for horizon in HORIZONS
    }
    for row in validation:
        pool_end = row - purge_sessions - embargo_sessions
        if pool_end < max(candidates) + 20:
            continue
        pool = features[:pool_end]
        median = np.nanmedian(pool, axis=0)
        scale = np.nanpercentile(pool, 75, axis=0) - np.nanpercentile(pool, 25, axis=0)
        scale = np.where(scale > 1e-12, scale, 1.0)
        distances = np.mean(((np.where(np.isfinite(pool), pool, median) - features[row]) / scale) ** 2, axis=1)
        ordered = np.argsort(distances)
        for horizon in HORIZONS:
            actual = targets[horizon][row]
            if not np.isfinite(actual):
                continue
            for candidate in candidates:
                source = targets[horizon][:pool_end][ordered[:candidate]]
                source = source[np.isfinite(source)]
                if len(source) >= 20:
                    losses[horizon][candidate].append(empirical_crps(source, float(actual)))
    summary = {
        str(horizon): {
            str(candidate): (float(np.mean(values)) if values else float("inf"))
            for candidate, values in candidate_losses.items()
        }
        for horizon, candidate_losses in losses.items()
    }
    selected = {
        horizon: min(candidates, key=lambda candidate: summary[str(horizon)][str(candidate)])
        for horizon in HORIZONS
    }
    return selected, summary


def _stress_regime(day: str) -> str:
    if "2008-01-01" <= day <= "2009-03-31":
        return "great_financial_crisis_2008"
    if "2020-02-15" <= day <= "2020-04-30":
        return "pandemic_2020"
    if "2022-01-01" <= day <= "2022-12-31":
        return "tightening_2022"
    if "2009-04-01" <= day <= "2010-03-31" or "2020-05-01" <= day <= "2021-03-31":
        return "rebound"
    return "normal"


def _trend_regime(row: np.ndarray, names: list[str]) -> str:
    mapping = dict(zip(names, row, strict=True))
    trend = mapping.get("trend_63", 0.0)
    drawdown = mapping.get("drawdown_63", 0.0)
    if trend > 0.04 and drawdown > -0.08:
        return "bull"
    if trend < -0.04 or drawdown < -0.12:
        return "bear"
    return "range"


def _path_risk_audit(paths: np.ndarray) -> dict[str, Any]:
    daily = np.asarray(paths, dtype=float)
    cumulative = np.column_stack((np.zeros(len(daily)), np.cumsum(daily, axis=1)))
    running_peak = np.maximum.accumulate(cumulative, axis=1)
    drawdowns = cumulative - running_peak
    depths = -np.min(drawdowns, axis=1)
    durations = np.zeros(len(daily), dtype=int)
    current = np.zeros(len(daily), dtype=int)
    for day in range(1, drawdowns.shape[1]):
        current = np.where(drawdowns[:, day] < -1e-12, current + 1, 0)
        durations = np.maximum(durations, current)
    return {
        "max_drawdown_log_quantiles": {
            str(level): float(np.quantile(depths, level)) for level in (0.50, 0.75, 0.90, 0.95)
        },
        "max_drawdown_duration_sessions_quantiles": {
            str(level): float(np.quantile(durations, level)) for level in (0.50, 0.75, 0.90, 0.95)
        },
        "minus_10pct_first_touch_probability": float(np.mean(np.min(cumulative, axis=1) <= np.log(0.90))),
    }


def run_research_backtest(root: Path, *, sample_count: int | None = None, bootstrap_iterations: int = 1000) -> dict[str, Any]:
    contract = load_contract_v3(root)
    v2 = verify_v2_benchmark(root, contract)
    frame, engineered, returns, _ = load_v3_frame(root)
    feature_names = list(engineered.columns)
    features = engineered.to_numpy(dtype=float)
    ridge_columns = [feature_names.index(name) for name in contract["direct_location"]["ridge_features"]]
    ridge_features = features[:, ridge_columns]
    targets = direct_targets_from_returns(returns)
    medians, scales = rolling_anchor_statistics(
        returns, features, history_sessions=int(contract["baseline"]["history_sessions"]),
        filtered_neighbors=int(contract["baseline"]["filtered_neighbors"]),
    )
    residual_targets = {h: targets[h] - medians[h] for h in HORIZONS}
    bounds = {int(h): float(value) for h, value in contract["direct_location"]["bounded_correction_sigma"].items()}
    alphas = tuple(float(value) for value in contract["direct_location"]["ridge_alpha_grid"])
    anchor = FixedAnchorDistribution(
        weights={key: float(value) for key, value in contract["baseline"]["components"].items()},
        sample_count=int(sample_count or contract["baseline"]["sample_count"]),
        filtered_neighbors=int(contract["baseline"]["filtered_neighbors"]),
        block_length=int(contract["baseline"]["block_length"]),
    )
    dates = [item.date().isoformat() for item in frame.index]
    origin_indexes = [
        index for index, day in enumerate(dates)
        if day >= str(contract["evaluation"]["outer_start"])
        and index + max(HORIZONS) < len(dates)
        and frame.index[index].weekday() == 4
    ]
    component_history: dict[int, dict[str, list[float]]] = {
        h: {key: [] for key in ("anchor", "direct_location", "analog_quantile", "volatility_tail", "regime")}
        for h in HORIZONS
    }
    scores: list[OriginScore] = []
    weight_history: list[dict[str, Any]] = []
    alpha_history: list[dict[str, Any]] = []
    analog_selection_history: list[dict[str, Any]] = []
    analog_year_cache: dict[str, dict[int, int]] = {}
    seed_base = int(frozen_hash(contract)[:16], 16) % (2**32)
    for ordinal, origin in enumerate(origin_indexes):
        train_end = origin - int(contract["evaluation"]["purge_sessions"]) - int(contract["evaluation"]["embargo_sessions"])
        if train_end < 1000 or not np.isfinite(features[origin]).all():
            continue
        valid = np.isfinite(features[:train_end]).all(axis=1)
        valid &= np.logical_and.reduce([np.isfinite(residual_targets[h][:train_end]) for h in HORIZONS])
        selected_rows = np.flatnonzero(valid)
        if len(selected_rows) < 800:
            continue
        # Use a compact contiguous PIT-complete block so inner selection never observes future rows.
        start = selected_rows[-min(len(selected_rows), 2520)]
        local_features = ridge_features[start:train_end]
        local_targets = {h: values[start:train_end] for h, values in residual_targets.items()}
        local_scales = {h: values[start:train_end] for h, values in scales.items()}
        alpha, alpha_scores = _select_origin_alpha(
            local_features, local_targets, local_scales, train_end=len(local_features),
            alphas=alphas, bounds=bounds,
        )
        alpha_history.append({"origin": dates[origin], "alpha": alpha, "inner_crps": alpha_scores})
        direct = DirectHorizonModel.fit(
            local_features, local_targets, alpha=alpha, correction_sigma_bounds=bounds,
        )
        origin_seed = (seed_base + ordinal * 7919) % (2**32)
        anchor_forecast = anchor.predict(
            returns=returns[:origin + 1], state_history=features[:origin + 1],
            origin_state=features[origin], horizons=HORIZONS, seed=origin_seed,
            data_cutoff=dates[origin],
        )
        direct_samples = direct.predict_samples(ridge_features[origin], anchor_forecast.horizon_samples)
        direct_forecast = ComponentForecast.from_samples(
            "direct_location", direct_samples, data_cutoff=dates[origin],
            feature_hash=canonical_hash({"origin": dates[origin], "alpha": alpha}),
        )
        analog_settings = contract["direct_location"]["analog_quantile"]
        analog_names = list(analog_settings["distance_features"])
        analog_columns = [feature_names.index(name) for name in analog_names]
        analog_train_features = features[start:train_end, :][:, analog_columns]
        year = dates[origin][:4]
        if year not in analog_year_cache:
            selected_neighbors, neighbor_scores = _select_analog_neighbors(
                analog_train_features, {h: targets[h][start:train_end] for h in HORIZONS},
                candidates=tuple(int(value) for value in analog_settings["neighbor_candidates"]),
                validation_origins=int(analog_settings["internal_validation_origins"]),
                purge_sessions=int(analog_settings["internal_purge_sessions"]),
                embargo_sessions=int(analog_settings["internal_embargo_sessions"]),
            )
            analog_year_cache[year] = selected_neighbors
            analog_selection_history.append({
                "effective_from_origin": dates[origin], "neighbors_by_horizon": selected_neighbors,
                "inner_crps": neighbor_scores,
            })
        analog = AnalogQuantileModel.fit(
            analog_train_features, {h: targets[h][start:train_end] for h in HORIZONS},
            neighbors=analog_year_cache[year],
            conditional_weight=float(analog_settings["conditional_weight"]),
            correction_sigma_bounds=bounds,
        )
        analog_samples = analog.predict_samples(
            features[origin, analog_columns], anchor_forecast.horizon_samples,
            count=anchor.sample_count, rng=np.random.default_rng(origin_seed + 11),
        )
        analog_forecast = ComponentForecast.from_samples(
            "analog_quantile", analog_samples, data_cutoff=dates[origin],
            feature_hash=canonical_hash({"origin": dates[origin], "neighbors": analog.neighbors}),
        )
        scale_features = features[start:train_end]
        scale_model = HorizonScaleModel.fit(
            scale_features, {h: targets[h][start:train_end] for h in HORIZONS},
            {h: scales[h][start:train_end] for h in HORIZONS}, alpha=10.0,
        )
        tail_samples = scale_model.transform(direct_samples, features[origin])
        tail_forecast = ComponentForecast.from_samples(
            "volatility_tail", tail_samples, data_cutoff=dates[origin],
            feature_hash=canonical_hash({"origin": dates[origin], "scale": "horizon_specific"}),
        )
        regime_model = SoftRegimeModel.fit(features[start:train_end])
        probabilities = regime_model.probabilities(features[origin])
        train_labels = []
        for row in features[start:train_end]:
            row_probabilities = regime_model.probabilities(row)
            train_labels.append(max(row_probabilities, key=row_probabilities.get))
        regime_samples: dict[int, np.ndarray] = {}
        regime_rng = np.random.default_rng(origin_seed + 17)
        for horizon in HORIZONS:
            pools = {
                label: local_targets[horizon][np.array(train_labels) == label]
                for label in REGIMES
            }
            pools = {key: value[np.isfinite(value)] for key, value in pools.items() if np.isfinite(value).sum() >= 40}
            try:
                residuals = mix_regime_residuals(pools, probabilities, count=anchor.sample_count, rng=regime_rng)
                regime_samples[horizon] = np.median(direct_samples[horizon]) + residuals
            except ValueError:
                regime_samples[horizon] = direct_samples[horizon].copy()
        regime_forecast = ComponentForecast.from_samples(
            "regime", regime_samples, data_cutoff=dates[origin],
            feature_hash=canonical_hash({"origin": dates[origin], "probabilities": probabilities}),
        )
        forecasts = {
            "anchor": ComponentForecast.from_samples(
                "anchor", anchor_forecast.horizon_samples, data_cutoff=dates[origin],
                feature_hash=anchor_forecast.feature_hash,
            ),
            "direct_location": direct_forecast,
            "analog_quantile": analog_forecast,
            "volatility_tail": tail_forecast,
            "regime": regime_forecast,
        }
        weights_by_horizon: dict[int, dict[str, float]] = {}
        for horizon in HORIZONS:
            recent = {
                key: (float(np.mean(values[-52:])) if values else 1.0)
                for key, values in component_history[horizon].items()
            }
            weights_by_horizon[horizon] = constrained_loss_weights(
                recent, anchor="anchor", anchor_floor=float(contract["stacking"]["anchor_floor"]),
                previous=(weight_history[-1]["weights"].get(str(horizon)) if weight_history else None),
                stability_penalty=float(contract["stacking"]["stability_penalty"]),
                complexity_penalty=float(contract["stacking"]["complexity_penalty"]),
            )
        stack = StackedDistribution(weights_by_horizon, "anchor", float(contract["stacking"]["anchor_floor"]))
        final_samples = stack.combine(
            forecasts, count=anchor.sample_count, seed=origin_seed + 31,
            event_present=False, stale_components={"event", "market_implied"},
        )
        weight_history.append({
            "origin": dates[origin],
            "weights": {str(h): values for h, values in weights_by_horizon.items()},
            "event_weight_zero_reason": "no_backtested_60_event_pit_sample",
            "market_implied_weight_zero_reason": "physical_calibration_unavailable",
        })
        trend = _trend_regime(features[origin], feature_names)
        stress = _stress_regime(dates[origin])
        for horizon in HORIZONS:
            actual = float(targets[horizon][origin])
            baseline_values = anchor_forecast.horizon_samples[horizon]
            model_values = final_samples[horizon]
            baseline_loss = empirical_crps(baseline_values, actual)
            model_loss = empirical_crps(model_values, actual)
            quantile_levels = (0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99)
            quantiles = {
                str(level): float(np.quantile(model_values, level)) for level in quantile_levels
            }
            mean_pinball = float(np.mean([
                pinball_loss(level, quantiles[str(level)], actual) for level in quantile_levels
            ]))
            for name, forecast in forecasts.items():
                component_history[horizon][name].append(empirical_crps(forecast.horizon_samples[horizon], actual))
            scores.append(OriginScore(
                dates[origin], horizon, actual, model_loss, baseline_loss,
                float(np.quantile(model_values, 0.10)), float(np.quantile(model_values, 0.90)),
                float(np.quantile(baseline_values, 0.10)), float(np.quantile(baseline_values, 0.90)),
                trend, stress, "no_event",
                float(features[origin, feature_names.index("realized_vol_21")]),
                "core_fresh_optional_components_absent",
                float(np.mean(model_values <= actual)), float(np.mean(model_values > 0.0)),
                mean_pinball, tail_weighted_crps(model_values, actual), quantiles,
            ))
    if not scores:
        raise RuntimeError("V3 research backtest produced no origins")
    gate = evaluate_research_gate(
        scores, leakage_count=0, lineage_linkage=1.0,
        block_length=int(contract["evaluation"]["bootstrap_block_origins"]),
        bootstrap_iterations=bootstrap_iterations, seed=seed_base,
    )
    run_core = {
        "schema_version": 3, "model_id": MODEL_ID, "model_version": MODEL_VERSION,
        "contract_hash": frozen_hash(contract), "model_code_hash": model_code_hash(root),
        "v2_benchmark": v2, "data_cutoff": dates[-1],
        "origin_count": len({row.origin for row in scores}), "score_count": len(scores),
        "sample_count": anchor.sample_count, "research_gate": gate,
        "dfm_alignment": {
            "status": "blocked_missing_named_loading_vectors_in_v2_cache",
            "numerical_weight": 0.0,
            "reason": "V3 will not call inherited factor levels sign/scale aligned without named loadings",
        },
        "event_ablation": {"status": "unavailable", "pit_event_count": 0, "numerical_weight": 0.0},
        "market_implied_ablation": {"status": "unavailable", "calibrated_event_count": 0, "numerical_weight": 0.0},
        "analyst_ablation": {"status": "optional_not_activated", "numerical_weight": 0.0},
        "foundation_challengers": {"status": "not_evaluated", "numerical_weight": 0.0},
        "alpha_history_hash": canonical_hash(alpha_history),
        "analog_selection_history_hash": canonical_hash(analog_selection_history),
        "weight_history_hash": canonical_hash(weight_history),
        "component_mean_crps": {
            str(horizon): {
                key: float(np.mean(values)) if values else None
                for key, values in components.items()
            }
            for horizon, components in component_history.items()
        },
        "fixed_comparator": "fixed_anchor_ensemble_v3", "row_wise_oracle_used": False,
    }
    run_id = "tsv3-research-" + canonical_hash(run_core)[:24]
    payload = {
        **run_core, "run_id": run_id,
        "scores": [asdict(row) for row in scores],
        "alpha_history": alpha_history, "analog_selection_history": analog_selection_history,
        "weight_history": weight_history,
    }
    payload["content_hash"] = canonical_hash(payload)
    target = root / RUNS_RELATIVE / f"{run_id}.json"
    _atomic_json(target, payload)
    _atomic_json(root / RUNS_RELATIVE / "backtest_latest.json", {
        "schema_version": 3, "run_id": run_id, "path": target.relative_to(root).as_posix(),
        "content_hash": payload["content_hash"],
    })
    return payload


def build_latest_shadow(root: Path, backtest: dict[str, Any] | None = None) -> dict[str, Any]:
    contract = load_contract_v3(root)
    if backtest is None:
        pointer = json.loads((root / RUNS_RELATIVE / "backtest_latest.json").read_text(encoding="utf-8"))
        backtest = json.loads((root / pointer["path"]).read_text(encoding="utf-8"))
    frame, engineered, returns, index = load_v3_frame(root)
    feature_names = list(engineered.columns)
    features = engineered.to_numpy(dtype=float)
    usable = np.flatnonzero(np.isfinite(features).all(axis=1))
    origin = int(usable[-1])
    contract_hash = frozen_hash(contract)
    seed = int(canonical_hash({"model": MODEL_ID, "origin": str(frame.index[origin])})[:16], 16) % (2**32)
    anchor = FixedAnchorDistribution(
        weights={key: float(value) for key, value in contract["baseline"]["components"].items()},
        sample_count=int(contract["baseline"]["sample_count"]),
        filtered_neighbors=int(contract["baseline"]["filtered_neighbors"]),
        block_length=int(contract["baseline"]["block_length"]),
    )
    anchor_forecast = anchor.predict(
        returns=returns[:origin + 1], state_history=features[:origin + 1], origin_state=features[origin],
        horizons=HORIZONS, seed=seed, data_cutoff=frame.index[origin].date().isoformat(),
    )
    correlation_targets = direct_targets_from_returns(returns[:origin + 1])
    historical_matrix = np.column_stack([correlation_targets[h] for h in HORIZONS])
    historical_matrix = historical_matrix[np.isfinite(historical_matrix).all(axis=1)]
    correlation = np.corrcoef(historical_matrix.T)
    horizons, endpoints = gaussian_copula_endpoints(
        anchor_forecast.horizon_samples, correlation=correlation,
        count=anchor.sample_count, rng=np.random.default_rng(seed + 1),
    )
    paths = stochastic_bridge_paths(
        endpoints, horizons, returns[:origin + 1], rng=np.random.default_rng(seed + 2),
        block_length=10,
    )
    coherence = float(np.max(np.abs(endpoint_errors(paths, endpoints, horizons))))
    forecast_core = {
        "schema_version": 3, "forecast_id": "tsv3-forecast-" + canonical_hash({"origin": frame.index[origin].isoformat(), "run": backtest["run_id"]})[:24],
        "model_id": MODEL_ID, "model_version": MODEL_VERSION, "status": "shadow",
        "as_of": frame.index[origin].date().isoformat(), "knowledge_cutoff": frame.index[origin].date().isoformat(),
        "anchor": float(index[origin]), "target": "NASDAQCOM direct cumulative log return",
        "probability_unit": "fraction", "probability_space": contract["probability_contract"]["space"],
        "combined_with_official_forecasts": False, "combined_with_scenario_v5_2": False,
        "backtest_run_id": backtest["run_id"], "research_gate_pass": bool(backtest["research_gate"]["pass"]),
        "forward_shadow_stage": "stage_a_not_started", "customer_numbers_visible": False,
        "horizons": {
            str(h): {
                "median_log_return": float(np.median(endpoints[:, column])),
                "up_probability": float(np.mean(endpoints[:, column] > 0)),
                "quantiles": {
                    str(q): float(np.quantile(endpoints[:, column], q))
                    for q in (0.10, 0.25, 0.50, 0.75, 0.90)
                },
            }
            for column, h in enumerate(horizons)
        },
        "path_audit": {
            "path_count": len(paths), "endpoint_max_abs_error": coherence,
            "duplicate_fraction": path_duplicate_fraction(paths),
            "event_local_shocks_applied": 0,
            **_path_risk_audit(paths),
        },
        "missing_components": ["dfm_aligned", "event", "market_implied", "analyst", "foundation_challenger"],
        "feature_names": feature_names,
        "hashes": {"contract": contract_hash, "model_code": model_code_hash(root), "backtest": backtest["content_hash"]},
    }
    forecast_core["content_hash"] = canonical_hash(forecast_core)
    _append_jsonl(root / LEDGER_RELATIVE / "forecasts.jsonl", forecast_core, "forecast_id")
    latest = {
        "schema_version": 3, "model_id": MODEL_ID, "status": "shadow_validation_hold",
        "display_state": "validation_pending", "customer_numbers_visible": False,
        "forecast_id": forecast_core["forecast_id"], "as_of": forecast_core["as_of"],
        "research_gate": backtest["research_gate"],
        "forward_shadow": {
            "stage": "A", "required_sessions": int(contract["forward_shadow"]["stage_a_sessions"]),
            "captured_sessions": 0, "publication_allowed": False,
        },
        "footnote": "*미국 시장·미국 공식 거시자료 기준",
        "reason": "V3 research and forward-shadow gates are incomplete; no customer forecast numbers are published.",
        "content_hash": forecast_core["content_hash"],
    }
    _atomic_json(root / LATEST_RELATIVE, latest)
    return {"latest": latest, "forecast": forecast_core, "paths": paths, "endpoints": endpoints}


def verify_v3(root: Path) -> dict[str, Any]:
    contract = load_contract_v3(root)
    v2 = verify_v2_benchmark(root, contract)
    errors: list[str] = []
    pointer_path = root / RUNS_RELATIVE / "backtest_latest.json"
    backtest: dict[str, Any] | None = None
    if not pointer_path.is_file():
        errors.append("V3 backtest pointer is missing")
    else:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        artifact_path = root / str(pointer.get("path", ""))
        if not artifact_path.is_file():
            errors.append("V3 backtest artifact is missing")
        else:
            backtest = json.loads(artifact_path.read_text(encoding="utf-8"))
            expected_hash = str(backtest.get("content_hash", ""))
            body = dict(backtest)
            body.pop("content_hash", None)
            observed_hash = canonical_hash(body)
            if observed_hash != expected_hash or pointer.get("content_hash") != expected_hash:
                errors.append("V3 backtest content hash mismatch")
            if backtest.get("contract_hash") != frozen_hash(contract):
                errors.append("V3 backtest contract hash drifted")
            if backtest.get("model_code_hash") != model_code_hash(root):
                errors.append("V3 backtest model code hash drifted")
            if backtest.get("fixed_comparator") != contract["evaluation"]["baseline"]:
                errors.append("V3 fixed comparator drifted")
            if backtest.get("row_wise_oracle_used") is not False:
                errors.append("V3 used a prohibited row-wise oracle comparator")
            gate = backtest.get("research_gate") or {}
            if gate.get("pass") is False and not gate.get("reasons"):
                errors.append("failed V3 gate has no auditable reason")
    latest_path = root / LATEST_RELATIVE
    if latest_path.is_file():
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
        if latest.get("customer_numbers_visible") is not False:
            errors.append("V3 customer numbers became visible before forward gate")
        if latest.get("model_id") != MODEL_ID:
            errors.append("V3 latest pointer has the wrong model id")
        if backtest and latest.get("research_gate", {}).get("pass") != backtest.get("research_gate", {}).get("pass"):
            errors.append("V3 latest pointer does not match the latest research gate")
        if latest.get("forward_shadow", {}).get("publication_allowed") is not False:
            errors.append("V3 forward-shadow publication was enabled without approval")
        forecast_id = latest.get("forecast_id")
        ledger_path = root / LEDGER_RELATIVE / "forecasts.jsonl"
        ledger = [] if not ledger_path.is_file() else [
            json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line
        ]
        matches = [row for row in ledger if row.get("forecast_id") == forecast_id]
        if len(matches) != 1:
            errors.append("V3 latest forecast is not linked to exactly one ledger row")
        elif matches[0].get("content_hash") != latest.get("content_hash"):
            errors.append("V3 latest forecast content hash mismatch")
    return {
        "ok": not errors, "errors": errors, "model_id": MODEL_ID,
        "contract_hash": frozen_hash(contract), "model_code_hash": model_code_hash(root),
        "v2_benchmark": v2,
        "research_gate_pass": bool(backtest and backtest.get("research_gate", {}).get("pass")),
        "customer_numbers_visible": False if not latest_path.is_file() else bool(
            json.loads(latest_path.read_text(encoding="utf-8")).get("customer_numbers_visible")
        ),
    }
