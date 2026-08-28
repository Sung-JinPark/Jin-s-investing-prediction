"""V8 development walk-forward evaluator (design/holdout windows only).

This clones the V2 weekly-origin evaluation loop, layers the preregistered
V8 distribution calibration on top, and never sees any date past the
structural development truncation.  Neutral configuration reproduces the V2
evaluation exactly — same seeds, same generator order, same scores.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ai_fc.timeseries.backtest import (
    OriginScore,
    _stationary_bootstrap_mean_ci,
    sample_crps,
)
from ai_fc.timeseries.model import deterministic_seed, ensemble_weights
from ai_fc.timeseries_v2.backtest import (
    _baseline_samples_v2,
    _weekly_forecast_origins,
    summarize_backtest_v2,
)
from ai_fc.timeseries_v2.model import (
    select_distribution_parameters_v2,
    select_ridge_varx_v2,
)

from .contracts import TimeSeriesV8ContractError
from .model import (
    HORIZONS,
    DistributionConfigV8,
    bounded_location_shift,
    cramer_distance,
    mixture_cdf_at,
    mixture_crps,
    mixture_quantile_function,
    mixture_quantiles,
    recalibration_levels,
    simulate_calibrated_paths_v8,
    volatility_term_structure,
)

# Purge plus embargo, in sessions: a past origin's PIT may inform the current
# origin only after its longest target window has fully matured and cleared
# the embargo (evaluation.purge_sessions 63 + embargo_sessions 5).
PIT_MATURITY_SESSIONS = 68


def walk_forward_dev_backtest_v8(
    *,
    dates: tuple[str, ...],
    endog: np.ndarray,
    exog: np.ndarray,
    endog_names: tuple[str, ...],
    exog_names: tuple[str, ...],
    model_id: str,
    model_version: int,
    config: DistributionConfigV8,
    outer_start: str,
    outer_end: str,
    path_count: int = 2000,
    initial_expanding_crps: tuple[float, ...] | list[float] = (),
    initial_rolling_crps: tuple[float, ...] | list[float] = (),
    collect_cramer_audit: bool = True,
    pit_min_matured: int = 104,
) -> tuple[list[OriginScore], dict[str, Any]]:
    if outer_end < outer_start:
        raise TimeSeriesV8ContractError("evaluation window end precedes its start")
    origins = [
        pair for pair in _weekly_forecast_origins(dates, outer_start=outer_start, horizon=63)
        if dates[pair[0]] <= outer_end
    ]
    scores: list[OriginScore] = []
    cramer_rows: dict[int, list[float]] = {h: [] for h in HORIZONS}
    pit_history: dict[int, list[tuple[int, float]]] = {h: [] for h in HORIZONS}
    recalibrated_counts: dict[int, int] = {h: 0 for h in HORIZONS}
    expanding_history = [float(value) for value in initial_expanding_crps]
    rolling_history = [float(value) for value in initial_rolling_crps]
    if len(expanding_history) != len(rolling_history):
        raise ValueError("initial ensemble CRPS histories must have equal length")
    for as_of_index, forecast_start in origins:
        training_endog = endog[:forecast_start]
        training_exog = exog[:forecast_start]
        expanding = select_ridge_varx_v2(
            training_endog, training_exog,
            endog_names=endog_names, exog_names=exog_names,
        )
        rolling_start = max(0, forecast_start - 2520)
        rolling = select_ridge_varx_v2(
            training_endog, training_exog,
            endog_names=endog_names, exog_names=exog_names,
            train_start=rolling_start,
        )
        weight_left, weight_right, _ = ensemble_weights(expanding_history, rolling_history)
        as_of = dates[as_of_index]
        seed = deterministic_seed(model_id, model_version, as_of)
        combined_residuals = np.vstack((expanding.residuals, rolling.residuals))
        block_length, ewma_lambda, _ = select_distribution_parameters_v2(
            combined_residuals, seed=seed,
        )
        step_scale = volatility_term_structure(
            combined_residuals,
            decay=ewma_lambda,
            phi=config.phi,
            horizon=63,
            unconditional_window_sessions=config.unconditional_window_sessions,
        ) if config.phi is not None else None
        simulate_kwargs = dict(
            endog_history=training_endog,
            exog_last=training_exog[-1],
            anchor=1.0,
            path_count=path_count,
            horizon=63,
            block_length=block_length,
            ewma_lambda=ewma_lambda,
            step_scale=step_scale,
        )
        simulated = simulate_calibrated_paths_v8(
            (expanding, rolling), weights=(weight_left, weight_right),
            seed=seed, **simulate_kwargs,
        )
        expanding_only = simulate_calibrated_paths_v8(
            (expanding, rolling), weights=(1.0, 0.0),
            seed=seed + 2, **simulate_kwargs,
        )
        rolling_only = simulate_calibrated_paths_v8(
            (expanding, rolling), weights=(0.0, 1.0),
            seed=seed + 3, **simulate_kwargs,
        )
        raw_cum = np.cumsum(simulated["log_returns"], axis=1)
        shift = bounded_location_shift(
            raw_cum,
            training_returns=training_endog[:, 0],
            omega_by_horizon=config.omega_by_horizon,
            sigma_cap=config.sigma_cap,
            mu_hat_window_sessions=config.mu_hat_window_sessions,
        )
        cumulative_shift = np.cumsum(shift)
        # Keep the V2 exp/log round-trip so the neutral configuration is a
        # bit-for-bit identity with the V2 walk-forward evaluation.
        index_paths = np.exp(raw_cum + cumulative_shift[None, :])
        log_paths = np.log(index_paths)
        expanding_log_paths = np.log(np.exp(
            np.cumsum(expanding_only["log_returns"], axis=1) + cumulative_shift[None, :]
        ))
        rolling_log_paths = np.log(np.exp(
            np.cumsum(rolling_only["log_returns"], axis=1) + cumulative_shift[None, :]
        ))
        rng = np.random.default_rng(seed + 1)
        for horizon in HORIZONS:
            samples = log_paths[:, horizon - 1]
            actual_daily = endog[forecast_start: forecast_start + horizon, 0]
            actual = float(np.sum(actual_daily))
            baselines = _baseline_samples_v2(
                training_endog[:, 0], horizon=horizon, count=path_count, rng=rng,
            )
            model_only_crps = sample_crps(samples, actual)
            weight = float(config.blend_weight_by_horizon.get(horizon, 1.0))
            historical_samples = baselines["historical_simulation"]
            if weight < 1.0 or collect_cramer_audit:
                distance = cramer_distance(samples, historical_samples)
                cramer_rows[horizon].append(distance)
            else:
                distance = 0.0
            matured_pits = [
                value for index, value in pit_history[horizon]
                if index + PIT_MATURITY_SESSIONS <= as_of_index
            ]
            recalibration_active = (
                config.pit_recalibration_shrinkage is not None
                and len(matured_pits) >= int(pit_min_matured)
            )
            if recalibration_active:
                # B4: remap the final (post-blend) distribution through the
                # inverse empirical PIT map of matured past forecasts.  PITs
                # themselves are always taken from the pre-recalibration
                # distribution below, so the map is never fitted on its own
                # output.
                midpoints = (np.arange(len(samples)) + 0.5) / len(samples)
                remapped_levels = recalibration_levels(
                    np.asarray(matured_pits, dtype=float),
                    target_levels=midpoints,
                    shrinkage=float(config.pit_recalibration_shrinkage),
                )
                final_samples = mixture_quantile_function(
                    samples, historical_samples, weight=weight, levels=remapped_levels,
                )
                model_crps = sample_crps(final_samples, actual)
                quantiles = np.quantile(final_samples, (0.10, 0.25, 0.50, 0.75, 0.90))
                recalibrated_counts[horizon] += 1
            elif weight < 1.0:
                historical_crps = sample_crps(historical_samples, actual)
                model_crps = mixture_crps(
                    model_only_crps, historical_crps, weight=weight, distance=distance,
                )
                quantiles = mixture_quantiles(
                    samples, historical_samples, weight=weight,
                )
            else:
                model_crps = model_only_crps
                quantiles = np.quantile(samples, (0.10, 0.25, 0.50, 0.75, 0.90))
            pit_history[horizon].append((
                as_of_index,
                mixture_cdf_at(samples, historical_samples, weight=weight, value=actual),
            ))
            touch_actual = bool(np.min(np.exp(np.cumsum(actual_daily))) <= 0.90)
            touch_probability = float(
                np.mean(np.min(index_paths[:, :horizon], axis=1) <= 0.90)
            )
            row = OriginScore(
                date=as_of,
                horizon=horizon,
                actual_log_return=actual,
                model_crps=model_crps,
                baseline_crps={
                    name: sample_crps(values, actual) for name, values in baselines.items()
                },
                median=float(quantiles[2]),
                p10=float(quantiles[0]),
                p25=float(quantiles[1]),
                p75=float(quantiles[3]),
                p90=float(quantiles[4]),
                direction_correct=bool((quantiles[2] >= 0) == (actual >= 0)),
                first_touch_actual=touch_actual,
                first_touch_probability=touch_probability,
                expanding_crps=sample_crps(expanding_log_paths[:, horizon - 1], actual),
                rolling_crps=sample_crps(rolling_log_paths[:, horizon - 1], actual),
                block_length=block_length,
                ewma_lambda=ewma_lambda,
            )
            scores.append(row)
            if horizon == 21:
                expanding_history.append(row.expanding_crps)
                rolling_history.append(row.rolling_crps)
    summary = summarize_backtest_v2(scores, minimum_origins=1)
    summary["cramer_distance_mean"] = {
        str(horizon): (float(np.mean(rows)) if rows else None)
        for horizon, rows in cramer_rows.items()
    }
    summary["pit_recalibrated_origins"] = {
        str(horizon): count for horizon, count in recalibrated_counts.items()
    }
    summary["config"] = config.as_manifest()
    summary["window"] = {"outer_start": outer_start, "outer_end": outer_end}
    summary["origin_count_window"] = len(origins)
    return scores, summary


def paired_differences_vs_best(
    scores: list[OriginScore], *, horizons: tuple[int, ...] = (21, 63),
) -> dict[str, Any]:
    """Weekly-origin paired mean loss differences against the best baseline."""
    by_horizon_date = {
        horizon: {row.date: row for row in scores if row.horizon == horizon}
        for horizon in horizons
    }
    common_dates = sorted(set.intersection(*(set(rows) for rows in by_horizon_date.values())))
    best_names: dict[int, str] = {}
    for horizon in horizons:
        rows = list(by_horizon_date[horizon].values())
        names = sorted(rows[0].baseline_crps) if rows else []
        means = {
            name: float(np.mean([row.baseline_crps[name] for row in rows]))
            for name in names
        }
        if means:
            best_names[horizon] = min(means, key=means.get)
    differences = []
    for origin_date in common_dates:
        values = [
            float(
                by_horizon_date[horizon][origin_date].model_crps
                - by_horizon_date[horizon][origin_date].baseline_crps[best_names[horizon]]
            )
            for horizon in horizons
        ]
        differences.append(float(np.mean(values)))
    array = np.asarray(differences, dtype=float)
    ci_low, ci_high = _stationary_bootstrap_mean_ci(array, seed=19_960_107)
    return {
        "origin_count": len(differences),
        "mean": float(np.mean(array)) if len(array) else None,
        "ci90": {"lower": ci_low, "upper": ci_high},
        "best_baselines": {str(key): value for key, value in best_names.items()},
        "differences": differences,
    }


def dev_gate_proxy_report(
    summary: dict[str, Any], paired: dict[str, Any], *, proxy: dict[str, Any],
    window_role: str,
) -> dict[str, Any]:
    """Evaluate the preregistered dev-gate proxy for a design or holdout run."""
    if window_role not in ("design", "holdout"):
        raise TimeSeriesV8ContractError("window role must be design or holdout")
    checks: dict[str, dict[str, Any]] = {}

    def record(name: str, observed: Any, passed: bool) -> None:
        checks[name] = {"observed": observed, "pass": bool(passed)}

    horizons = summary.get("horizons", {})
    long_improvements = [
        float(horizons[str(h)]["crps_improvement_vs_best"])
        for h in (21, 63) if str(h) in horizons
    ]
    long_mean = float(np.mean(long_improvements)) if long_improvements else float("nan")
    ci_upper = paired["ci90"]["upper"]
    if window_role == "design":
        record(
            "long_horizon_mean_improvement", long_mean,
            np.isfinite(long_mean)
            and long_mean >= float(proxy["design_long_horizon_mean_crps_min_improvement"]),
        )
        record(
            "paired_ci90_upper", ci_upper,
            np.isfinite(ci_upper)
            and ci_upper <= float(proxy["design_paired_bootstrap_ci90_upper_max"]),
        )
        for h in (1, 5):
            metric = horizons.get(str(h))
            observed = None if not metric else float(metric["crps_improvement_vs_best"])
            record(
                f"short_horizon_h{h}", observed,
                observed is not None
                and observed >= -float(proxy["design_short_horizon_crps_max_underperformance"]),
            )
        low_wide, high_wide = (float(x) for x in proxy["design_p10_p90_coverage"])
        low_mid, high_mid = (float(x) for x in proxy["design_p25_p75_coverage"])
        for h in HORIZONS:
            metric = horizons.get(str(h))
            if not metric:
                record(f"coverage_h{h}", None, False)
                continue
            wide = float(metric["coverage_p10_p90"])
            mid = float(metric["coverage_p25_p75"])
            record(
                f"coverage_h{h}", {"p10_p90": wide, "p25_p75": mid},
                low_wide <= wide <= high_wide and low_mid <= mid <= high_mid,
            )
        gfc = (summary.get("regime_coverage") or {}).get("great_financial_crisis_2008") or {}
        gfc_cov = gfc.get("coverage_p10_p90")
        record(
            "gfc_regime_coverage", gfc_cov,
            gfc_cov is not None
            and float(gfc_cov) >= float(proxy["design_gfc_regime_p10_p90_minimum"]),
        )
    else:
        record(
            "holdout_long_horizon_mean_improvement", long_mean,
            np.isfinite(long_mean)
            and long_mean >= float(proxy["holdout_long_horizon_mean_crps_min_improvement"]),
        )
        record(
            "holdout_paired_ci90_upper", ci_upper,
            np.isfinite(ci_upper)
            and ci_upper <= float(proxy["holdout_paired_bootstrap_ci90_upper_max"]),
        )
    return {
        "window_role": window_role,
        "checks": checks,
        "pass": all(item["pass"] for item in checks.values()),
    }
