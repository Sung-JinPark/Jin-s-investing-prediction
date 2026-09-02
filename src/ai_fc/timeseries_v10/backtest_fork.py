"""V8 development walk-forward evaluator (design/holdout windows only).

This clones the V2 weekly-origin evaluation loop, layers the preregistered
V8 distribution calibration on top, and never sees any date past the
structural development truncation.  Neutral configuration reproduces the V2
evaluation exactly — same seeds, same generator order, same scores.
"""

from __future__ import annotations

import math
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

from ai_fc.timeseries_v8.contracts import TimeSeriesV8ContractError
from .model_fork import (
    HORIZONS,
    DistributionConfigV8,
    bounded_location_shift,
    cramer_distance,
    fhs_horizon_samples,
    mixture_cdf_at,
    mixture_cdf_at_k,
    mixture_crps,
    mixture_quantile_function,
    mixture_quantile_function_k,
    mixture_quantiles,
    recalibration_levels,
    recalibration_levels_pav,
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
    emit_forecast: bool = False,
    state_series: np.ndarray | None = None,
    state_series_alt: np.ndarray | None = None,
) -> tuple[list[OriginScore], dict[str, Any]]:
    if outer_end < outer_start:
        raise TimeSeriesV8ContractError("evaluation window end precedes its start")
    # V10: 비퇴화 knob은 상태 시계열을 요구한다 — 조용한 무상태 실행 금지.
    if not config.is_v10_degenerate() and state_series is None and (
        config.w1_kappa is not None or config.w3_blend_gamma is not None
        or int(config.w4_recal_layers) > 1
    ):
        raise TimeSeriesV8ContractError("V10 state-dependent knobs require a state series")
    active_state = state_series
    if config.w1_state == "rv63_over_rv504" and state_series_alt is not None:
        active_state = state_series_alt
    origins = [
        pair for pair in _weekly_forecast_origins(dates, outer_start=outer_start, horizon=63)
        if dates[pair[0]] <= outer_end
    ]
    scores: list[OriginScore] = []
    cramer_rows: dict[int, list[float]] = {h: [] for h in HORIZONS}
    pit_history: dict[int, list[tuple[int, float, float]]] = {h: [] for h in HORIZONS}
    origin_states: list[float] = []
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
        # V10: 원점 상태 (trailing-only — PIT 안전). 상태 없으면 1.0(중립).
        state_now = (
            float(active_state[as_of_index]) if active_state is not None else 1.0
        )
        origin_states.append(state_now)
        # W4b 층 판정: 지금까지 관측된 원점 상태의 러닝 중앙값 기준 (expanding — PIT 안전).
        if len(origin_states) >= 2:
            current_layer = 1 if state_now >= float(np.median(origin_states[:-1])) else 0
        else:
            current_layer = 0
        for horizon in HORIZONS:
            samples = log_paths[:, horizon - 1]
            if horizon in config.fhs_horizons:
                # B5: the reported marginal at this horizon comes from the
                # deterministic FHS reconstruction; the engine paths remain
                # the source of path-level metrics and the ensemble history.
                samples = fhs_horizon_samples(
                    training_endog[:, 0],
                    horizon=horizon,
                    ewma_lambda=ewma_lambda,
                    vol_projection=config.fhs_vol_projection,
                    unconditional_window_sessions=config.unconditional_window_sessions,
                    mu_hat_window_sessions=config.mu_hat_window_sessions,
                    tilt_omega=config.fhs_tilt_omega,
                    tilt_cap_sigma=config.fhs_tilt_cap_sigma,
                    engine_mean=float(np.mean(log_paths[:, horizon - 1])),
                    state_values=(
                        active_state[:forecast_start] if active_state is not None else None
                    ),
                    state_now=state_now,
                    kappa=config.w1_kappa,
                )
            actual_daily = endog[forecast_start: forecast_start + horizon, 0]
            actual = float(np.sum(actual_daily))
            baselines = _baseline_samples_v2(
                training_endog[:, 0], horizon=horizon, count=path_count, rng=rng,
            )
            model_only_crps = sample_crps(samples, actual)
            weight = float(config.blend_weight_by_horizon.get(horizon, 1.0))
            # W3 (V10): 상태의존 블렌드 — FHS 지평(정적 w<1)에만, γ=None이면 원본 그대로.
            if config.w3_blend_gamma is not None and weight < 1.0:
                weight = float(np.clip(
                    0.75 + float(config.w3_blend_gamma) * (state_now - 1.0), 0.5, 0.9,
                ))
            historical_samples = baselines["historical_simulation"]
            # W2 (V10): K성분 혼합은 FHS 지평에서 2성분 경로를 통째 대체한다.
            k_mixture_active = (
                config.w2_mix_weights is not None and horizon in config.fhs_horizons
            )
            if weight < 1.0 or collect_cramer_audit:
                distance = cramer_distance(samples, historical_samples)
                cramer_rows[horizon].append(distance)
            else:
                distance = 0.0
            # W4b (V10): 층화 재보정 — 성숙 PIT를 그 원점의 층으로 나눠 적합하되,
            # 활성 층 표본이 부족하면 결합 이력으로 폴백(보수적, 선언된 규칙).
            matured_all = [
                (value, layer_state) for index, value, layer_state in pit_history[horizon]
                if index + PIT_MATURITY_SESSIONS <= as_of_index
            ]
            matured_pits = [value for value, _layer_state in matured_all]
            if int(config.w4_recal_layers) > 1 and len(origin_states) >= 2:
                split = float(np.median(origin_states[:-1]))
                layered = [
                    value for value, layer_state in matured_all
                    if (1 if layer_state >= split else 0) == current_layer
                ]
                if len(layered) >= int(pit_min_matured):
                    matured_pits = layered
            recalibration_active = (
                config.pit_recalibration_shrinkage is not None
                and len(matured_pits) >= int(pit_min_matured)
            )
            recal_map = (
                recalibration_levels_pav if config.w4_recal_map == "isotonic_pav"
                else recalibration_levels
            )
            mixture_sets = [samples, historical_samples, baselines["block_bootstrap"]]
            mixture_weights = (
                list(config.w2_mix_weights) if config.w2_mix_weights is not None else None
            )
            if recalibration_active:
                # B4: remap the final (post-blend) distribution through the
                # inverse empirical PIT map of matured past forecasts.  PITs
                # themselves are always taken from the pre-recalibration
                # distribution below, so the map is never fitted on its own
                # output.
                midpoints = (np.arange(len(samples)) + 0.5) / len(samples)
                remapped_levels = recal_map(
                    np.asarray(matured_pits, dtype=float),
                    target_levels=midpoints,
                    shrinkage=float(config.pit_recalibration_shrinkage),
                )
                if k_mixture_active:
                    final_samples = mixture_quantile_function_k(
                        mixture_sets, mixture_weights, levels=remapped_levels,
                    )
                else:
                    final_samples = mixture_quantile_function(
                        samples, historical_samples, weight=weight, levels=remapped_levels,
                    )
                model_crps = sample_crps(final_samples, actual)
                quantiles = np.quantile(final_samples, (0.10, 0.25, 0.50, 0.75, 0.90))
                recalibrated_counts[horizon] += 1
            elif k_mixture_active:
                # W2 사전 채점: K성분 혼합 표본의 경험 CRPS (2성분 정확식 경로는
                # 퇴화 시에만 사용 — E8 교훈의 Cramér 사전 계산은 등록 단계 스크린용).
                midpoints = (np.arange(len(samples)) + 0.5) / len(samples)
                final_samples = mixture_quantile_function_k(
                    mixture_sets, mixture_weights, levels=midpoints,
                )
                model_crps = sample_crps(final_samples, actual)
                quantiles = np.quantile(final_samples, (0.10, 0.25, 0.50, 0.75, 0.90))
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
            if k_mixture_active:
                pit_value = mixture_cdf_at_k(mixture_sets, mixture_weights, value=actual)
            else:
                pit_value = mixture_cdf_at(
                    samples, historical_samples, weight=weight, value=actual,
                )
            pit_history[horizon].append((as_of_index, pit_value, state_now))
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
    if emit_forecast:
        summary["shadow_forecast"] = _final_session_forecast(
            dates=dates, endog=endog, exog=exog,
            endog_names=endog_names, exog_names=exog_names,
            model_id=model_id, model_version=model_version, config=config,
            path_count=path_count,
            expanding_history=expanding_history, rolling_history=rolling_history,
            pit_history=pit_history, pit_min_matured=pit_min_matured,
        )
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


FORECAST_GRID_LEVELS = tuple((index + 0.5) / 200.0 for index in range(200))


def _final_session_forecast(
    *,
    dates: tuple[str, ...],
    endog: np.ndarray,
    exog: np.ndarray,
    endog_names: tuple[str, ...],
    exog_names: tuple[str, ...],
    model_id: str,
    model_version: int,
    config: DistributionConfigV8,
    path_count: int,
    expanding_history: list[float],
    rolling_history: list[float],
    pit_history: dict[int, list[tuple[int, float, float]]],
    pit_min_matured: int,
) -> dict[str, Any]:
    """The prospective distribution at the latest completed session.

    This mirrors one iteration of the walk-forward loop with the warmed
    ensemble and PIT state, minus scoring: the origin's labels do not exist
    yet.  Everything stored is a deterministic function of the training
    window, so a same-day replay reproduces the identical forecast.
    """
    as_of_index = len(dates) - 1
    forecast_start = len(dates)
    training_endog = endog[:forecast_start]
    training_exog = exog[:forecast_start]
    expanding = select_ridge_varx_v2(
        training_endog, training_exog,
        endog_names=endog_names, exog_names=exog_names,
    )
    rolling = select_ridge_varx_v2(
        training_endog, training_exog,
        endog_names=endog_names, exog_names=exog_names,
        train_start=max(0, forecast_start - 2520),
    )
    weight_left, weight_right, _ = ensemble_weights(expanding_history, rolling_history)
    as_of = dates[as_of_index]
    seed = deterministic_seed(model_id, model_version, as_of)
    combined_residuals = np.vstack((expanding.residuals, rolling.residuals))
    block_length, ewma_lambda, _ = select_distribution_parameters_v2(
        combined_residuals, seed=seed,
    )
    step_scale = volatility_term_structure(
        combined_residuals, decay=ewma_lambda, phi=config.phi, horizon=63,
        unconditional_window_sessions=config.unconditional_window_sessions,
    ) if config.phi is not None else None
    simulated = simulate_calibrated_paths_v8(
        (expanding, rolling), weights=(weight_left, weight_right),
        endog_history=training_endog, exog_last=training_exog[-1], anchor=1.0,
        path_count=path_count, horizon=63, block_length=block_length,
        ewma_lambda=ewma_lambda, seed=seed, step_scale=step_scale,
    )
    raw_cum = np.cumsum(simulated["log_returns"], axis=1)
    shift = bounded_location_shift(
        raw_cum, training_returns=training_endog[:, 0],
        omega_by_horizon=config.omega_by_horizon, sigma_cap=config.sigma_cap,
        mu_hat_window_sessions=config.mu_hat_window_sessions,
    )
    log_paths = np.log(np.exp(raw_cum + np.cumsum(shift)[None, :]))
    rng = np.random.default_rng(seed + 1)
    levels = np.asarray(FORECAST_GRID_LEVELS, dtype=float)
    horizons_payload: dict[str, Any] = {}
    recalibrated: dict[str, int] = {}
    for horizon in HORIZONS:
        samples = log_paths[:, horizon - 1]
        if horizon in config.fhs_horizons:
            samples = fhs_horizon_samples(
                training_endog[:, 0], horizon=horizon, ewma_lambda=ewma_lambda,
                vol_projection=config.fhs_vol_projection,
                unconditional_window_sessions=config.unconditional_window_sessions,
                mu_hat_window_sessions=config.mu_hat_window_sessions,
                tilt_omega=config.fhs_tilt_omega,
                tilt_cap_sigma=config.fhs_tilt_cap_sigma,
                engine_mean=float(np.mean(log_paths[:, horizon - 1])),
            )
        baselines = _baseline_samples_v2(
            training_endog[:, 0], horizon=horizon, count=path_count, rng=rng,
        )
        historical_samples = baselines["historical_simulation"]
        weight = float(config.blend_weight_by_horizon.get(horizon, 1.0))
        matured_pits = [
            value for index, value, _origin_state in pit_history[horizon]
            if index + PIT_MATURITY_SESSIONS <= as_of_index
        ]
        recal_active = (
            config.pit_recalibration_shrinkage is not None
            and len(matured_pits) >= int(pit_min_matured)
        )
        if recal_active:
            remapped = recalibration_levels(
                np.asarray(matured_pits, dtype=float), target_levels=levels,
                shrinkage=float(config.pit_recalibration_shrinkage),
            )
            grid = mixture_quantile_function(
                samples, historical_samples, weight=weight, levels=remapped,
            )
        else:
            grid = mixture_quantile_function(
                samples, historical_samples, weight=weight, levels=levels,
            )
        grid = np.maximum.accumulate(np.asarray(grid, dtype=float))
        baseline_grid = np.quantile(historical_samples, levels)
        horizons_payload[str(horizon)] = {
            "quantile_grid": [float(v) for v in grid],
            "baseline_quantile_grid": [float(v) for v in baseline_grid],
            "p_up": float(np.mean(grid > 0.0)),
            "blend_weight": weight,
            "recalibrated": bool(recal_active),
            "matured_pit_count": len(matured_pits),
        }
        recalibrated[str(horizon)] = int(recal_active)
    return {
        "origin": as_of,
        "grid_levels_count": len(FORECAST_GRID_LEVELS),
        "ensemble_weights": {"expanding": float(weight_left), "rolling": float(weight_right)},
        "block_length": int(block_length),
        "ewma_lambda": float(ewma_lambda),
        "horizons": horizons_payload,
        "recalibrated": recalibrated,
    }


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
        # Proxy revision 1: the CI-safety margin is expressed as a noise
        # ceiling plus the projection of the paired CI to the full 2007+
        # window, instead of a fixed design-CI bound calibrated on E0-era
        # noise (see the contract's revision_history).
        mean = paired.get("mean")
        ci_lower = paired["ci90"]["lower"]
        se = (
            (float(ci_upper) - float(ci_lower)) / (2.0 * 1.645)
            if np.isfinite(ci_upper) and np.isfinite(ci_lower) else float("nan")
        )
        record(
            "paired_se", se,
            np.isfinite(se) and se <= float(proxy["design_paired_se_max"]),
        )
        reference = float(proxy["projection_reference_origins"])
        projected = (
            float(mean) + 1.645 * se * math.sqrt(float(paired["origin_count"]) / reference)
            if mean is not None and np.isfinite(se) else float("nan")
        )
        record(
            "projected_full_window_ci90_upper", projected,
            np.isfinite(projected)
            and projected <= float(proxy["projected_full_window_ci90_upper_max"]),
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
