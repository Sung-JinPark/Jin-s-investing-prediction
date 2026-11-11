"""Design-window constants for the daily6m v2 shadow (2007-01-01..2014-12-31 only).

CLAUDE.md principle 5 numerical-model exception (dualdb spec v1.0 §8, DECISIONS 8-6):
deterministic numerical fits on historical data are allowed as base-rate reference,
never as calibration samples, and the window/candidate choices may indirectly embed
hindsight (disclosed as contract caveats).  No LLM is involved.

The archive reader returns latest revisions over the full history; rows with an
observation_time after the window end are *read and skipped* (used rows = 0).

The proxy replay ports the r1 scratch (`proxy_replay.py` + `anchor_variants.py`)
exactly, including its selection path through the sealed V2 stationary bootstrap
and its moving validation grid.  That selection differs from the registered live
selection (CRN pre-drawn bootstrap, anchored grid) — a contract caveat — but is kept
so the preregistered numbers reproduce bit for bit.
"""

from __future__ import annotations

import bisect
import calendar
import json
import math
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from .contracts import (
    CONSTANTS_RELATIVE, DESIGN_WINDOW, Daily6mV2ContractError, REPORT_RELATIVE, canonical_hash,
)

COLUMNS = ("nasdaq_return", "vix_change", "dgs2_change_bps", "curve_change_bps", "dollar_change")
SERIES = {"nasdaq_return": "NASDAQCOM", "vix_change": "VIX", "dgs2_change_bps": "DGS2",
          "curve_change_bps": "DGS10-DGS2", "dollar_change": "DTWEXB"}
GARCH_STARTS = ((0.05, 0.93), (0.08, 0.90), (0.12, 0.85))
GARCH_OPTIONS = {"xatol": 1e-7, "fatol": 1e-9, "maxiter": 4000}
HALF_WINDOW_SPLIT = "2011-01-03"
BLOCKS = (5, 10, 21)
LAMBDAS = (0.94, 0.97)
DEFAULT_SELECTION = (10, 0.97)
SELECTION_SEED = 20261111
SIM_STREAM = 7
FIRST_ORIGIN_INDEX = 499
ORIGIN_STEP = 5
REPLICATES = 8
PATHS = 10000
SLOW_EWMA = 0.996
ANCHOR_LEADS = (1, 5, 21, 63, 126)
MULTIPLIER_GRID = tuple(float(value) for value in np.round(np.arange(0.70, 1.6001, 0.05), 2))
V8_B1_DEV_RUNS = ("tsv8-exp-92d143bb7d6754e673c7", "tsv8-exp-b3d95536b64d0aa07e20")


# ---------------------------------------------------------------- panel
def design_panel(observations: Iterable[Any]) -> dict[str, Any]:
    """Five design-window change columns from archive observations.

    ``observations`` yields objects with series_id, observation_time, value
    (the V2 archive's MarketObservationV2).  Rows after the window end are
    skipped and counted; none are used.
    """
    start, end = DESIGN_WINDOW
    store: dict[str, dict[str, float]] = {}
    skipped = 0
    for row in observations:
        if str(row.observation_time) > end:
            skipped += 1
            continue
        store.setdefault(str(row.series_id), {})[str(row.observation_time)] = float(row.value)
    for series_id in ("NASDAQCOM", "VIX", "DGS2", "DGS10", "DTWEXB"):
        if not store.get(series_id):
            raise Daily6mV2ContractError("design window series missing: " + series_id)
    nasdaq, vix = store["NASDAQCOM"], store["VIX"]
    days = sorted(day for day in nasdaq if day in vix and start <= day <= end)

    def carrier(series_id: str):
        keys = sorted(store[series_id])
        values = [store[series_id][key] for key in keys]

        def at(day: str) -> float:
            position = bisect.bisect_right(keys, day) - 1
            if position < 0:
                raise Daily6mV2ContractError("design window carry has no prior observation: " + series_id)
            return values[position]
        return at

    two, ten, dollar = carrier("DGS2"), carrier("DGS10"), carrier("DTWEXB")
    levels = np.array([[nasdaq[day], vix[day], two(day), ten(day) - two(day), dollar(day)] for day in days])
    changes = np.column_stack((
        np.diff(np.log(levels[:, 0])), np.diff(np.log(levels[:, 1])), np.diff(levels[:, 2]) * 100,
        np.diff(levels[:, 3]) * 100, np.diff(np.log(levels[:, 4])),
    ))
    if any(day > end for day in days):
        raise Daily6mV2ContractError("design panel contains a post-window session")
    return {"dates": days[1:], "changes": changes, "post_window_rows_skipped": skipped, "post_window_rows_used": 0}


def load_design_panel(root: Path) -> dict[str, Any]:
    from ai_fc.timeseries_v2.market_archive import read_market_observations
    return design_panel(read_market_observations(root))


# ---------------------------------------------------------------- GARCH(1,1)
def garch_variance_targeting(series: np.ndarray) -> dict[str, float]:
    """Variance-targeting Gaussian QMLE GARCH(1,1); best of three Nelder-Mead starts."""
    from scipy.optimize import minimize
    errors = np.asarray(series, dtype=float)
    errors = errors - errors.mean()
    target = float(np.mean(errors * errors))

    def negative_log_likelihood(parameters):
        alpha, beta = parameters
        if alpha <= 0 or beta <= 0 or alpha + beta >= 0.9999:
            return 1e12
        omega = (1 - alpha - beta) * target
        variance = np.empty_like(errors)
        variance[0] = target
        for step in range(1, len(errors)):
            variance[step] = omega + alpha * errors[step - 1] ** 2 + beta * variance[step - 1]
        return 0.5 * float(np.sum(np.log(variance) + errors * errors / variance))

    best = None
    for start in GARCH_STARTS:
        result = minimize(negative_log_likelihood, list(start), method="Nelder-Mead", options=dict(GARCH_OPTIONS))
        if best is None or result.fun < best.fun:
            best = result
    alpha, beta = (float(value) for value in best.x)
    return {"alpha": alpha, "beta": beta, "persistence": alpha + beta,
            "half_life_sessions": math.log(0.5) / math.log(alpha + beta), "unconditional_variance": target,
            "negative_log_likelihood": float(best.fun)}


# ---------------------------------------------------------------- proxy replay (r1 scratch port)
def _add_months(day: date, months: int = 6) -> date:
    index = day.year * 12 + day.month - 1 + months
    year, zero = divmod(index, 12)
    month = zero + 1
    end = calendar.monthrange(year, month)[1]
    month_end = day.day == calendar.monthrange(day.year, day.month)[1]
    return date(year, month, end if month_end else min(day.day, end))


def _fresh_scale(residuals: np.ndarray, decay: float) -> tuple[np.ndarray, float, float]:
    from scipy.signal import lfilter
    squared = np.square(residuals)
    variance = np.empty_like(squared)
    variance[0] = max(squared[0], 1e-16)
    if len(squared) > 1:
        filtered, _ = lfilter([1 - decay], [1, -decay], squared[:-1], axis=0,
                              zi=np.asarray(decay * variance[0]).reshape((1, *squared.shape[1:])))
        variance[1:] = filtered
    fresh = decay * variance[-1] + (1 - decay) * squared[-1]
    return (np.sqrt(np.maximum(fresh, 1e-16)) / np.sqrt(np.maximum(variance, 1e-16)),
            float(fresh), float(variance[-1]))


def _term(fresh_variance: float, long_run: float, phi: float, horizon: int) -> np.ndarray:
    steps = np.arange(1, horizon + 1)
    variance = long_run + phi ** (steps - 1) * (fresh_variance - long_run)
    return np.sqrt(np.maximum(variance, 1e-16) / max(fresh_variance, 1e-16))


def _slow_ewma(squared: np.ndarray, decay: float = SLOW_EWMA) -> float:
    value = squared[0]
    for item in squared[:-1]:
        value = decay * value + (1 - decay) * item
    return float(decay * value + (1 - decay) * squared[-1])


def _replay_select(residuals: np.ndarray, previous, phi: float, replicates: int):
    from ai_fc.timeseries.backtest import sample_crps
    from ai_fc.timeseries_v2.model import _stationary_bootstrap_batch
    count = len(residuals)
    validation_count = min(52, (count - 252) // 21)
    origins = list(range(count - validation_count * 21, count, 21))
    scores: dict[tuple[int, float], np.ndarray] = {}
    for decay in LAMBDAS:
        prepared = {}
        for origin in origins:
            training = residuals[:origin]
            scale, fresh, _ = _fresh_scale(training, decay)
            prepared[origin] = (scale, _term(fresh, float(np.mean(training * training)), phi, 21))
        for block in BLOCKS:
            replicate_scores = []
            for replicate in range(replicates):
                values = []
                for sequence, origin in enumerate(origins):
                    training = residuals[:origin]
                    scale, growth = prepared[origin]
                    rng = np.random.default_rng([SELECTION_SEED, replicate, sequence])
                    indexes = _stationary_bootstrap_batch(rng, rows=len(training), paths=1000, horizon=21, mean_block=block)
                    sample = np.sum(training[indexes] * scale[indexes] * growth[None, :], axis=1)
                    values.append(sample_crps(sample, float(np.sum(residuals[origin:origin + 21]))))
                replicate_scores.append(np.mean(values))
            scores[(block, decay)] = np.array(replicate_scores)
    best = min(scores, key=lambda key: (scores[key].mean(), key))
    incumbent = previous if previous in scores else DEFAULT_SELECTION
    margin = scores[incumbent] - scores[best]
    mc_sd = float(np.std(margin, ddof=1) / math.sqrt(replicates)) if replicates > 1 else 0.0
    chosen = best if (best != incumbent and margin.mean() > mc_sd) else incumbent
    return chosen, best, float(margin.mean()), mc_sd


def proxy_replay(dates: list[str], returns: np.ndarray, *, phi: float, replicates: int = REPLICATES,
                 paths: int = PATHS, step: int = ORIGIN_STEP, first_origin: int = FIRST_ORIGIN_INDEX) -> dict[str, Any]:
    """Univariate Nasdaq proxy replay; returns per-origin quantiles for every variant."""
    from ai_fc.timeseries_v2.model import _stationary_bootstrap_batch
    days = [date.fromisoformat(day) for day in dates]
    rows = []
    previous = None
    last = len(returns) - 1
    origin = first_origin
    while origin < last:
        end = _add_months(days[origin])
        if end > days[-1]:
            break
        horizon = sum(1 for index in range(origin + 1, len(days)) if days[index] <= end)
        training = returns[:origin + 1]
        mean = float(np.mean(training))
        residuals = training - mean
        chosen, best, margin, mc_sd = _replay_select(residuals, previous, phi, replicates)
        previous = chosen
        block, decay = chosen
        scale, fresh, lagged = _fresh_scale(residuals, decay)
        squared = residuals * residuals
        growth = {"B": _term(fresh, float(np.mean(squared)), phi, horizon),
                  "S": _term(fresh, _slow_ewma(squared), phi, horizon),
                  "F": np.ones(horizon)}
        rng = np.random.default_rng([SELECTION_SEED, SIM_STREAM, origin])
        indexes = _stationary_bootstrap_batch(rng, rows=len(residuals), paths=paths, horizon=horizon, mean_block=block)
        base = residuals[indexes] * scale[indexes]
        lagged_scale = scale * math.sqrt(lagged / fresh)
        variants = {name: np.cumsum(mean + base * value[None, :], axis=1) for name, value in growth.items()}
        variants["v1_like"] = np.cumsum(mean + residuals[indexes] * lagged_scale[indexes], axis=1)
        variants["zero_drift_B"] = np.cumsum(base * growth["B"][None, :], axis=1)
        quantiles = {name: np.quantile(value, [0.1, 0.25, 0.5, 0.75, 0.9], axis=0).T for name, value in variants.items()}
        rows.append({"origin": dates[origin], "index": origin, "horizon": horizon, "chosen": chosen, "best": best,
                     "margin": margin, "mc_sd": mc_sd, "fresh_over_lagged_sd": math.sqrt(fresh / lagged),
                     "long_run_over_fresh_variance": float(np.mean(squared)) / fresh,
                     "realized": np.cumsum(returns[origin + 1:origin + 1 + horizon]), "quantiles": quantiles})
        origin += step
    return {"rows": rows, "replicates": replicates, "paths": paths, "step": step, "first_origin_index": first_origin}


def _coverage(rows: list[dict[str, Any]], name: str, lead: int, multiplier: float = 1.0, subset=None) -> tuple[float, float]:
    hit80 = hit50 = count = 0
    for position, row in enumerate(rows):
        if subset is not None and not subset(position):
            continue
        k = min(lead, row["horizon"]) - 1
        quantile = row["quantiles"][name][k]
        median = quantile[2]
        actual = row["realized"][k]
        hit80 += median + multiplier * (quantile[0] - median) <= actual <= median + multiplier * (quantile[4] - median)
        hit50 += median + multiplier * (quantile[1] - median) <= actual <= median + multiplier * (quantile[3] - median)
        count += 1
    return hit80 / count, hit50 / count


def _raw_multipliers(rows, name, subset=None) -> dict[str, float]:
    result = {}
    for lead in ANCHOR_LEADS:
        losses = []
        for multiplier in MULTIPLIER_GRID:
            cover80, cover50 = _coverage(rows, name, lead, multiplier, subset)
            losses.append(((cover80 - .8) ** 2 + (cover50 - .5) ** 2, abs(multiplier - 1), multiplier))
        result[str(lead)] = float(min(losses)[2])
    return result


def summarize_replay(replay: dict[str, Any], *, phi: float) -> dict[str, Any]:
    rows = replay["rows"]
    if not rows:
        raise Daily6mV2ContractError("design replay produced no origins")
    pit_loss = {}
    coverage = {}
    for name in ("v1_like", "F", "S", "B", "zero_drift_B"):
        coverage[name] = {str(lead): [round(value, 6) for value in _coverage(rows, name, lead)] for lead in ANCHOR_LEADS}
    for name in ("F", "S", "B"):
        pit_loss[name] = float(sum((a - .8) ** 2 + (b - .5) ** 2 for a, b in (_coverage(rows, name, lead) for lead in ANCHOR_LEADS)))
    half = len(rows) // 2
    multipliers = {name: {"full": _raw_multipliers(rows, name), "early": _raw_multipliers(rows, name, lambda i: i < half),
                          "late": _raw_multipliers(rows, name, lambda i: i >= half)} for name in ("F", "S", "B")}
    effective = {str(lead): len(rows) * replay["step"] / max(lead, replay["step"]) for lead in ANCHOR_LEADS}
    gate = {}
    for name in ("F", "S", "B"):
        gate[name] = {}
        for lead in ANCHOR_LEADS:
            n_eff = effective[str(lead)]
            cover80, cover50 = _coverage(rows, name, lead)
            fired = abs(cover80 - .8) > 1.645 * math.sqrt(.16 / n_eff) or abs(cover50 - .5) > 1.645 * math.sqrt(.25 / n_eff)
            gate[name][str(lead)] = bool(fired)
    chosen = [tuple(row["chosen"]) for row in rows]
    best = [tuple(row["best"]) for row in rows]
    distribution: dict[str, int] = {}
    for item in chosen:
        key = f"{item[0]}_{item[1]:.2f}"
        distribution[key] = distribution.get(key, 0) + 1
    ratio = np.array([np.mean(row["long_run_over_fresh_variance"] + phi ** (np.arange(1, 127) - 1)
                              * (1 - row["long_run_over_fresh_variance"])) for row in rows])
    fresh = np.array([row["fresh_over_lagged_sd"] for row in rows])
    return {
        "origins": len(rows), "first_origin": rows[0]["origin"], "last_origin": rows[-1]["origin"],
        "horizon_range": [min(row["horizon"] for row in rows), max(row["horizon"] for row in rows)],
        "effective_independent_windows": {key: round(value, 1) for key, value in effective.items()},
        "pit_loss": pit_loss, "coverage80_coverage50": coverage, "raw_grid_multipliers": multipliers,
        "r1_post_hoc_significance_gate_fired": gate,
        "selection": {"selected_switches": sum(a != b for a, b in zip(chosen, chosen[1:])),
                      "argmin_switches": sum(a != b for a, b in zip(best, best[1:])),
                      "kept_incumbent_over_argmin": sum(a != b for a, b in zip(chosen, best)),
                      "chosen_distribution": dict(sorted(distribution.items()))},
        "direction": {
            "B_h126_cumulative_variance_over_flat": {"median": float(np.median(ratio)), "p10": float(np.quantile(ratio, .1)),
                                                      "p90": float(np.quantile(ratio, .9)), "narrowing_share": float(np.mean(ratio < 1))},
            "fresh_over_lagged_sd": {"median": float(np.median(fresh)), "p10": float(np.quantile(fresh, .1)),
                                     "p90": float(np.quantile(fresh, .9)), "max": float(fresh.max())},
        },
    }


# ---------------------------------------------------------------- constants
def compute_design(panel: dict[str, Any], *, replicates: int = REPLICATES, paths: int = PATHS,
                   step: int = ORIGIN_STEP, first_origin: int = FIRST_ORIGIN_INDEX) -> dict[str, Any]:
    dates, changes = panel["dates"], panel["changes"]
    fits = {}
    split = dates.index(HALF_WINDOW_SPLIT) if HALF_WINDOW_SPLIT in dates else len(dates) // 2
    for column, name in enumerate(COLUMNS):
        fit = garch_variance_targeting(changes[:, column])
        fit["early_persistence"] = garch_variance_targeting(changes[:split, column])["persistence"]
        fit["late_persistence"] = garch_variance_targeting(changes[split:, column])["persistence"]
        fits[name] = fit
    phi = fits["nasdaq_return"]["persistence"]
    replay = proxy_replay(dates, changes[:, 0], phi=phi, replicates=replicates, paths=paths, step=step, first_origin=first_origin)
    summary = summarize_replay(replay, phi=phi)
    return {"panel": panel, "fits": fits, "summary": summary, "replay": replay,
            "settings": {"replicates": replicates, "paths": paths, "step": step, "first_origin": first_origin}}


def constants_from_design(design: dict[str, Any]) -> dict[str, Any]:
    panel, fits, summary, settings = design["panel"], design["fits"], design["summary"], design["settings"]
    pit = {"sample_mean_square": round(summary["pit_loss"]["B"], 4), "slow_ewma_0.996": round(summary["pit_loss"]["S"], 4),
           "flat_reference": round(summary["pit_loss"]["F"], 4)}
    registered = min(("sample_mean_square", "slow_ewma_0.996"), key=lambda key: (pit[key], key))
    return {
        "schema_version": 1,
        "constants_id": "daily6m_v2_design_constants_v1",
        "design_window": list(DESIGN_WINDOW),
        "panel": {"returns": len(panel["dates"]), "first_return": panel["dates"][0], "last_return": panel["dates"][-1],
                  "series": dict(SERIES)},
        "persistence_by_column": {name: round(fits[name]["persistence"], 5) for name in COLUMNS},
        "persistence_estimator": {"model": "garch11_variance_targeting_gaussian_qmle", "optimizer": "nelder_mead",
                                  "starts": [list(start) for start in GARCH_STARTS], "xatol": GARCH_OPTIONS["xatol"],
                                  "fatol": GARCH_OPTIONS["fatol"], "maxiter": GARCH_OPTIONS["maxiter"], "round": 5},
        "long_run_rule": {"registered": registered, "candidates": ["sample_mean_square", "slow_ewma_0.996"],
                          "criterion": "min pre-multiplier PIT loss over anchor leads", "pit_loss": pit},
        "lead_width_multiplier": "rejected (design_report_v1.json 에 원시 격자·반창 공시)",
        "proxy": {"model": "nasdaq_univariate_bootstrap_fresh_ewma", "first_origin_index": settings["first_origin"],
                  "origin_step_sessions": settings["step"], "paths": settings["paths"],
                  "sim_seed_key": [SELECTION_SEED, SIM_STREAM, "origin_index"], "drift": "expanding_mean",
                  "origins": summary["origins"],
                  "selection_bootstrap": "sealed_v2_stationary_bootstrap_batch (r1 스크래치 그대로 — 라이브 선택 규칙과 다름, caveat)"},
        "selection": {"seed": SELECTION_SEED, "replicates": REPLICATES, "paths": 1000, "validation_horizon": 21,
                      "origin_rule": "anchored_position_grid_mod_21", "bootstrap": "crn_predrawn_starts_and_uniforms",
                      "hysteresis_mc_sd": 1.0, "default_incumbent": list(DEFAULT_SELECTION)},
    }


def report_from_design(design: dict[str, Any], constants: dict[str, Any]) -> dict[str, Any]:
    fits = {name: {key: (round(value, 8) if isinstance(value, float) else value) for key, value in fit.items()}
            for name, fit in design["fits"].items()}
    summary = json.loads(json.dumps(design["summary"]))
    return {
        "schema_version": 1, "report_id": "daily6m_v2_design_report_v1",
        "role": "disclosure_only_not_a_verdict_basis", "design_window": list(DESIGN_WINDOW),
        "constants_hash": canonical_hash(constants),
        "panel": {**constants["panel"], "post_window_rows_used": 0,
                  "post_window_filter": "observation_time_le_2014-12-31_rows_skipped_after_full_read",
                  "point_in_time": False},
        "garch_fits": fits, "proxy_replay": summary,
        "lead_width_multiplier": {"status": "rejected",
                                  "reason": "raw grid optimum alternates across leads, flips between half windows (h126 1.10 vs 0.75), h126 effective windows 11; r1 significance gate was chosen after results"},
        "v8_b1_precedent": {"contract": "multivariate_timeseries_v8", "grid": "B1_volatility_term_structure",
                            "dev_runs": list(V8_B1_DEV_RUNS), "gfc_p10_p90_coverage": [0.615, 0.551],
                            "direction_vs_this_design": "opposite_unverified"},
        "caveats": [
            "proxy is univariate Nasdaq, not the daily6m VARX (DFM inputs start 2014-05-21)",
            "selection in this replay uses the sealed V2 bootstrap with a moving grid and B term structure in scores — differs from the registered live CRN selection",
            "slow_ewma_0.996 candidate was added after B-anchor over-coverage results were seen",
            "archive reader is latest-revision, not point in time; archive VIX and DGS10-DGS2 differ from live VIXCLS and T10Y2Y",
        ],
        "footnote": "연구 설계 공시 · 판정 근거 아님 · 참고 의견, 매매 신호 아님",
    }


def generate_design_artifacts(root: Path, *, write: bool = False, panel: dict[str, Any] | None = None,
                              **settings: Any) -> dict[str, Any]:
    panel = load_design_panel(root) if panel is None else panel
    design = compute_design(panel, **settings)
    constants = constants_from_design(design)
    report = report_from_design(design, constants)
    if write:
        for relative, value in ((CONSTANTS_RELATIVE, constants), (REPORT_RELATIVE, report)):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return {"constants": constants, "report": report, "constants_hash": canonical_hash(constants),
            "post_window_rows_skipped": panel["post_window_rows_skipped"], "post_window_rows_used": panel["post_window_rows_used"]}


def check_design_constants(root: Path, **settings: Any) -> dict[str, Any]:
    """Recompute φ (5 digits) and PIT losses (4 digits) and require exact equality."""
    stored = json.loads((root / CONSTANTS_RELATIVE).read_text(encoding="utf-8"))
    result = generate_design_artifacts(root, write=False, **settings)
    recomputed = result["constants"]
    differences = sorted(key for key in set(stored) | set(recomputed) if stored.get(key) != recomputed.get(key))
    import numpy
    import scipy
    return {"ok": not differences, "differences": differences, "stored_hash": canonical_hash(stored),
            "recomputed_hash": result["constants_hash"], "persistence_by_column": recomputed["persistence_by_column"],
            "pit_loss": recomputed["long_run_rule"]["pit_loss"], "registered_long_run_rule": recomputed["long_run_rule"]["registered"],
            "post_window_rows_skipped": result["post_window_rows_skipped"], "post_window_rows_used": result["post_window_rows_used"],
            "runtime": {"numpy": numpy.__version__, "scipy": scipy.__version__}}
