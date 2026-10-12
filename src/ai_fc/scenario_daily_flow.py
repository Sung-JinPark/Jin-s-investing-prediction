"""Auditable daily display members of the unchanged champion GBM ensemble.

The representative is a member of a dense *feature-space* cluster, not a prediction
of an exact daily trajectory. No historical context, prices, or model estimates
are fetched here. Existing official distribution fields are shadow-reproduced at
their original serialization precision before the display artifact is usable.
"""

from __future__ import annotations

import calendar as calendar_module
import hashlib
import json
import math
from datetime import date
from typing import Any

import numpy as np
from scipy.spatial import cKDTree
from scipy.spatial.distance import cdist

from .scenario import future_trading_days

SCHEMA_VERSION = 1
VERSION = "daily-flow-modal-medoid-v1"
SCENARIOS = ("S1", "S2", "S3")
MIN_CONDITIONAL_PATHS = 200
MIN_ELIGIBLE_NEIGHBORS = 9
# NumPy/libm implementations may differ by an ULP across Windows and Linux.
# These are verification tolerances only: values are never rounded or rewritten.
PRICE_REPLAY_ABS_TOLERANCE = 1e-8
FRACTION_REPLAY_ABS_TOLERANCE = 1e-12
FEATURE_NAMES = tuple(f"log_return_month_{m}" for m in range(1, 7)) + (
    "daily_realized_volatility", "maximum_drawdown", "direction_switch_rate",
)
_QUANTILES = (5, 10, 25, 50, 75, 90, 95)
_DAILY_KEYS = ("p05", "p10", "p25", "p50", "p75", "p90", "p95")
_BAND_KEYS = ("p10", "p25", "p50", "p75", "p90")


class DailyFlowError(ValueError):
    """A daily display cannot satisfy its source, mathematical, or unit contract."""


def _hash(value: Any) -> str:
    try:
        serialized = json.dumps(value, sort_keys=True, separators=(",", ":"),
                                ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise DailyFlowError("source must be finite JSON data") from exc
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _day(value: Any, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise DailyFlowError(f"{field} must be an ISO calendar date") from exc


def add_calendar_months(asof: date, months: int) -> date:
    """Preserve the day of month, clamping only to a shorter calendar month."""
    year, month0 = divmod(asof.year * 12 + asof.month - 1 + months, 12)
    month = month0 + 1
    return date(year, month, min(asof.day, calendar_module.monthrange(year, month)[1]))


def _number(value: Any, field: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise DailyFlowError(f"{field} must be a finite number")
    if positive and value <= 0:
        raise DailyFlowError(f"{field} must be positive")
    return float(value)


def _integer(value: Any, field: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise DailyFlowError(f"{field} must be an integer >= {minimum}")
    return value


def _source_unit(snapshot: dict[str, Any]) -> tuple[str, str]:
    # This is explicit, preregistered schema metadata, never a magnitude heuristic.
    declared = [container["probability_unit"] for container in (snapshot, snapshot.get("model", {}))
                if isinstance(container, dict) and "probability_unit" in container]
    if declared:
        if any(unit not in ("fraction", "percent") for unit in declared):
            raise DailyFlowError("source probability_unit must be fraction or percent")
        if len(set(declared)) != 1:
            raise DailyFlowError("source probability unit metadata conflicts")
        return declared[0], "source_probability_unit"
    if snapshot.get("schema_version") in (2, 3):
        return "percent", "scenario_daily_flow contract: legacy schema 2/3 paths.*.prob"
    raise DailyFlowError("source probability unit metadata is required")


def _source_inputs(snapshot: dict[str, Any], calendar: dict[str, Any] | None
                   ) -> tuple[dict[str, Any], list[date], dict[str, float]]:
    if not isinstance(snapshot, dict):
        raise DailyFlowError("source snapshot must be an object")
    if snapshot.get("schema_version") not in (2, 3):
        raise DailyFlowError("unsupported champion source schema")
    snapshot_id = snapshot.get("snapshot_id")
    if not isinstance(snapshot_id, str) or not snapshot_id:
        raise DailyFlowError("source snapshot_id is required")
    asof = _day(snapshot.get("asof"), "source asof")
    model = snapshot.get("model")
    if not isinstance(model, dict) or not isinstance(model.get("gbm_parameters"), dict):
        raise DailyFlowError("retained champion GBM parameters are required")
    if not str(snapshot.get("method", "")).startswith("gbm-daily-252d-v2-lookup"):
        raise DailyFlowError("daily_flow only supports the champion GBM source method")
    params = model["gbm_parameters"]
    if _day(params.get("estimation_end"), "estimation_end") != asof:
        raise DailyFlowError("GBM estimation_end must equal source asof")
    if params.get("return_basis") != "daily close-to-close log return":
        raise DailyFlowError("unsupported GBM return basis")
    sigma = _number(params.get("sigma_daily_log_return"), "sigma", positive=True)
    mu = _number(params.get("mu_daily_log_return"), "mu")
    replay = params.get("replay_parameters")
    precision = "retained serialized parameters; no fresh estimation"
    simulation_anchor = _number(snapshot.get("anchor"), "anchor", positive=True)
    simulation_ath = _number(snapshot.get("ath"), "ath", positive=True)
    simulation_corr10 = _number(snapshot.get("corr10"), "corr10", positive=True)
    if replay is not None:
        if not isinstance(replay, dict) or replay.get("schema_version") != 1:
            raise DailyFlowError("unsupported retained GBM replay parameter schema")
        if replay.get("return_basis") != "daily close-to-close log return":
            raise DailyFlowError("unsupported retained replay return basis")
        replay_mu = _number(replay.get("mu_daily_log_return"), "replay mu")
        replay_sigma = _number(replay.get("sigma_daily_log_return"), "replay sigma", positive=True)
        simulation_anchor = _number(replay.get("anchor"), "replay anchor", positive=True)
        simulation_ath = _number(replay.get("ath"), "replay ath", positive=True)
        simulation_corr10 = _number(replay.get("corr10"), "replay corr10", positive=True)
        if (round(replay_mu, 12) != mu or round(replay_sigma, 12) != sigma
                or any(round(raw, 2) != snapshot[key] for key, raw in (
                    ("anchor", simulation_anchor), ("ath", simulation_ath), ("corr10", simulation_corr10)))):
            raise DailyFlowError("retained replay parameters disagree with reported source precision")
        mu, sigma = replay_mu, replay_sigma
        precision = "retained full float replay_parameters schema 1; no fresh estimation"
    n_paths = _integer(model.get("n_paths"), "n_paths", 1)
    horizon = _integer(model.get("horizon_business_days"), "horizon_business_days", 1)
    seed = _integer(model.get("seed"), "seed")
    if horizon != 252:
        raise DailyFlowError("champion daily_flow requires the retained 252-session horizon")
    prices = {key: _number(snapshot.get(key), key, positive=True)
              for key in ("anchor", "ath", "corr10", "reference_price")}
    table = snapshot.get("quantile_table")
    if not isinstance(table, dict) or table.get("status") != "ok":
        raise DailyFlowError("retained daily source quantile table is required")
    raw_days = table.get("trading_days")
    if not isinstance(raw_days, list) or len(raw_days) != horizon:
        raise DailyFlowError("source must retain every future trading-day label")
    days = [_day(value, "trading_days") for value in raw_days]
    if days[0] <= asof or any(b <= a for a, b in zip(days, days[1:])):
        raise DailyFlowError("source trading dates must be strictly increasing after asof")
    if any(day.weekday() >= 5 for day in days):
        raise DailyFlowError("source trading dates contain a weekend")
    if calendar is not None:
        if calendar.get("calendar") != "NYSE" or calendar.get("version") != 1:
            raise DailyFlowError("unsupported registered trading calendar")
        registered = calendar.get("registered_at")
        if registered is not None and _day(str(registered), "calendar registered_at") > asof:
            raise DailyFlowError("calendar vintage was registered after source asof")
        if future_trading_days(asof, horizon, calendar) != days:
            raise DailyFlowError("registered calendar disagrees with retained source dates")
    classification_day = _day(model.get("classification_date"), "classification_date")
    if classification_day not in days:
        raise DailyFlowError("classification_date is outside retained source horizon")
    if classification_day != max(day for day in days if day.year == asof.year):
        raise DailyFlowError("champion classification_date must be the last session of source year")
    unit, unit_basis = _source_unit(snapshot)
    paths = snapshot.get("paths")
    if not isinstance(paths, dict) or set(paths) != set(SCENARIOS):
        raise DailyFlowError("source paths must contain S1/S2/S3")
    probabilities: dict[str, float] = {}
    for key in SCENARIOS:
        value = _number(paths[key].get("prob"), f"{key} probability")
        maximum = 100 if unit == "percent" else 1
        if not 0 <= value <= maximum:
            raise DailyFlowError(f"{key} probability outside declared {unit} unit")
        probabilities[key] = value / maximum
    if not math.isclose(sum(probabilities.values()), 1.0, rel_tol=0, abs_tol=1e-12):
        raise DailyFlowError("source scenario probabilities must sum to one without normalization")
    inputs = {
        "source_snapshot_id": snapshot_id, "asof": asof.isoformat(), **prices,
        "mu_daily_log_return": mu, "sigma_daily_log_return": sigma,
        "n_paths": n_paths, "horizon_business_days": horizon, "seed": seed,
        "classification_date": classification_day.isoformat(),
        "trading_days": raw_days, "source_probability_unit": unit,
        "source_probability_unit_basis": unit_basis,
        "source_parameters_precision": "retained serialized parameters; no fresh estimation",
    }
    inputs["source_parameters_precision"] = precision
    if replay is not None:
        inputs.update({"simulation_anchor": simulation_anchor, "simulation_ath": simulation_ath,
                       "simulation_corr10": simulation_corr10})
    return inputs, days, probabilities


def _ensemble(inputs: dict[str, Any]) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    # Exactly matches quant.mc.gbm_paths, including its mu - sigma**2/2 drift.
    rng = np.random.default_rng(inputs["seed"])
    shocks = rng.standard_normal((inputs["n_paths"], inputs["horizon_business_days"]))
    mu, sigma = inputs["mu_daily_log_return"], inputs["sigma_daily_log_return"]
    future = inputs.get("simulation_anchor", inputs["anchor"]) * np.exp(np.cumsum(mu - sigma ** 2 / 2 + sigma * shocks, axis=1))
    end = inputs["trading_days"].index(inputs["classification_date"])
    classification = future[:, :end + 1]
    s1 = (classification > inputs.get("simulation_ath", inputs["ath"])).any(axis=1)
    s2 = ~s1 & (classification[:, -1] > inputs["reference_price"])
    return future, {"S1": s1, "S2": s2, "S3": ~(s1 | s2)}


def _shadow(snapshot: dict[str, Any], inputs: dict[str, Any], future: np.ndarray,
            masks: dict[str, np.ndarray]) -> dict[str, Any]:
    """Compare every retained numerical champion distribution at exact stored precision."""
    checks: dict[str, dict[str, Any]] = {}

    def compare(name: str, actual: Any, expected: Any) -> None:
        checks[name] = {"passed": actual == expected, "reproduced_sha256": _hash(actual),
                        "source_sha256": _hash(expected)}
        if actual != expected:
            checks[name]["reason"] = "exact serialized reproduction mismatch"

    counts = {key: int(mask.sum()) for key, mask in masks.items()}
    raw = [float(masks[key].mean() * 100) for key in SCENARIOS]
    rounded = [int(round(value)) for value in raw]
    rounded[int(np.argmax(raw))] += 100 - sum(rounded)
    unit = inputs["source_probability_unit"]
    reported = {key: value if unit == "percent" else value / 100
                for key, value in zip(SCENARIOS, rounded)}
    compare("scenario_probabilities", reported,
            {key: snapshot["paths"][key]["prob"] for key in SCENARIOS})
    table = snapshot["quantile_table"]
    compare("scenario_counts", counts, table.get("per_scenario_counts"))
    daily_q = np.percentile(future, _QUANTILES, axis=0)
    serialize_daily = lambda values: [int(round(float(value) / 10) * 10) for value in values]
    compare("daily_quantiles", {key: serialize_daily(values)
            for key, values in zip(_DAILY_KEYS, daily_q)}, table.get("quantiles"))
    medians = {key: np.median(future[mask], axis=0) if mask.any()
               else np.percentile(future, {"S1": 75, "S2": 50, "S3": 25}[key], axis=0)
               for key, mask in masks.items()}
    compare("conditional_medians", {key: serialize_daily(values)
            for key, values in medians.items()}, table.get("per_scenario_p50"))
    for field, threshold in (("prob_above_anchor", inputs.get("simulation_anchor", inputs["anchor"])),
                             ("prob_above_ath", inputs.get("simulation_ath", inputs["ath"]))):
        values = [int(round(float(value) * 100)) for value in (future > threshold).mean(axis=0)]
        compare(field, values, table.get(field))
    week_dates = snapshot.get("week_dates")
    if not isinstance(week_dates, list) or not week_dates or week_dates[0] != inputs["asof"]:
        raise DailyFlowError("source weekly fan dates are required for shadow reproduction")
    try:
        graph_indexes = [inputs["trading_days"].index(value) for value in week_dates[1:]]
    except ValueError as exc:
        raise DailyFlowError("source fan dates must be members of retained trading dates") from exc
    sampled = np.column_stack((np.full(len(future), inputs.get("simulation_anchor", inputs["anchor"])), future[:, graph_indexes]))
    compare("weekly_fan_quantiles", {f"p{q}": [int(round(float(v))) for v in values]
            for q, values in zip(_QUANTILES, np.percentile(sampled, _QUANTILES, axis=0))},
            snapshot.get("fan", {}).get("quantiles"))
    end = inputs["trading_days"].index(inputs["classification_date"])
    terminals = future[:, end]
    compare("year_end_bands", {
        "eoy_median": int(round(float(np.median(terminals)))),
        "eoy_50": [int(round(float(np.percentile(terminals, q)))) for q in (25, 75)],
        "eoy_80": [int(round(float(np.percentile(terminals, q)))) for q in (10, 90)],
    }, snapshot.get("bands"))
    baseline_values = {}
    for key, mask in masks.items():
        values = np.median(sampled[mask], axis=0) if mask.any() else np.percentile(
            sampled, {"S1": 75, "S2": 50, "S3": 25}[key], axis=0)
        values[0] = inputs.get("simulation_anchor", inputs["anchor"])
        baseline_values[key] = [int(round(float(value))) for value in values]
    compare("weekly_baseline_paths", baseline_values,
            {key: snapshot["paths"][key].get("values") for key in SCENARIOS})
    risk = np.maximum.accumulate(future <= inputs.get("simulation_corr10", inputs["corr10"]), axis=1).mean(axis=0)
    levels = ["저"] + ["고" if risk[i] >= .35 else "중" if risk[i] >= .15 else "저"
                      for i in graph_indexes]
    compare("weekly_risk_levels", levels, snapshot.get("risk"))
    # The retained actual sample ids also bind membership beyond aggregate counts.
    sample_checks = {}
    realism = snapshot.get("path_realism", {})
    for key in SCENARIOS:
        for sample in realism.get(key, {}).get("sample_paths", []):
            idx = _integer(sample.get("path_index"), "source sample path_index")
            if idx >= len(future):
                raise DailyFlowError("retained source sample path_index is outside ensemble")
            sample_checks[f"{key}:{idx}"] = bool(masks[key][idx]) and sample.get("values") == [
                int(round(float(value))) for value in sampled[idx]]
    checks["retained_actual_samples"] = {"passed": all(sample_checks.values()),
                                          "members": sample_checks}
    return {"passed": all(check["passed"] for check in checks.values()), "checks": checks,
            "tolerance": "exact_serialized", "fresh_inputs_used": False,
            "parameter_precision": inputs["source_parameters_precision"] if "simulation_anchor" in inputs else "source mu/sigma stored at 12 decimal places",
            "membership_sha256": {key: hashlib.sha256(np.packbits(mask).tobytes()).hexdigest()
                                    for key, mask in masks.items()},
            "membership_note": "source retains counts and selected ids, not full original masks",
            "unchanged_fields": ["probabilities", "fan", "daily_quantiles", "anchor", "thresholds"],
            "source_snapshot_sha256": _hash(snapshot), "input_sha256": _hash(inputs)}


def _standardize(matrix: np.ndarray, names: tuple[str, ...]
                 ) -> tuple[np.ndarray, dict[str, Any]]:
    """Robust scaling with explicit audits; constants supply no density dimension."""
    centers = np.median(matrix, axis=0)
    scales = np.percentile(matrix, 75, axis=0) - np.percentile(matrix, 25, axis=0)
    retained = []
    excluded = []
    fallback = []
    for column, name in enumerate(names):
        if np.ptp(matrix[:, column]) == 0:
            excluded.append(name)
            continue
        if scales[column] == 0:
            scales[column] = float(np.std(matrix[:, column], ddof=0))
            fallback.append(name)
        if not math.isfinite(float(scales[column])) or scales[column] <= 0:
            raise DailyFlowError(f"degenerate scale for {name}")
        retained.append(column)
    standardized = (matrix[:, retained] - centers[retained]) / scales[retained]
    return standardized, {
        "feature_names": list(names), "retained_features": [names[i] for i in retained],
        "excluded_constant_features": excluded, "zero_iqr_std_fallback_features": fallback,
        "centers": {names[i]: float(centers[i]) for i in retained},
        "scales": {names[i]: float(scales[i]) for i in retained},
        "scale_rule": "conditional median/IQR; constant dropped; nonconstant zero-IQR uses population std",
    }


def _features(prices: np.ndarray, month_indexes: list[int]) -> np.ndarray:
    logs = np.log(prices)
    returns = np.diff(logs, axis=1)
    monthly = logs[:, month_indexes] - logs[:, [0]]
    volatility = np.std(returns, axis=1, ddof=1)
    maximum_drawdown = np.max(1 - prices / np.maximum.accumulate(prices, axis=1), axis=1)
    switches = np.mean(returns[:, 1:] * returns[:, :-1] < 0, axis=1)
    return np.column_stack((monthly, volatility, maximum_drawdown, switches))


def _metrics(values: np.ndarray) -> dict[str, float]:
    returns = np.diff(np.log(values))
    return {
        "terminal": float(values[-1]), "log_return": float(np.log(values[-1] / values[0])),
        "daily_realized_volatility": float(np.std(returns, ddof=1)),
        "maximum_drawdown": float(np.max(1 - values / np.maximum.accumulate(values))),
        "direction_switch_rate": float(np.mean(returns[1:] * returns[:-1] < 0)),
    }


def _select_member(prices: np.ndarray, original_ids: np.ndarray, month_indexes: list[int],
                   *, k: int | None = None) -> dict[str, Any]:
    """Exact kNN density center, then eligible actual L1 medoid; no smoothing."""
    n = len(prices)
    if n < MIN_CONDITIONAL_PATHS:
        return {"status": "blocked", "reason": "conditional_sample_below_200", "sample_count": n}
    features = _features(prices, month_indexes)
    standardized, scaling = _standardize(features, FEATURE_NAMES)
    if standardized.shape[1] == 0:
        return {"status": "blocked", "reason": "all_density_features_constant", "scaling": scaling}
    k = math.ceil(math.sqrt(n)) if k is None else k
    if not 1 <= k < n:
        raise DailyFlowError("density k must be between 1 and N-1")
    tree = cKDTree(standardized)
    # Query exact rank k+1 including self; duplicate locations do not change rank.
    distances = tree.query(standardized, k=[k + 1], eps=0, p=2, workers=1)[0][:, 0]
    smallest = float(np.min(distances))
    if not math.isfinite(smallest) or smallest <= 0:
        return {"status": "blocked", "reason": "degenerate_density_radius", "k": k,
                "density_radius": smallest, "scaling": scaling}
    centers = np.flatnonzero(distances == smallest)
    center = int(centers[np.argmin(original_ids[centers])])
    center_distances = np.linalg.norm(standardized - standardized[center], axis=1)
    others = np.flatnonzero(np.arange(n) != center)
    order = np.lexsort((original_ids[others], center_distances[others]))
    cluster = np.r_[center, others[order[:k]]]
    gates = {}
    eligible = np.ones(n, dtype=bool)
    for column, percentiles in ((6, (10, 90)), (7, (5, 95)), (8, (5, 95))):
        lo, hi = np.percentile(features[:, column], percentiles)
        eligible &= (features[:, column] >= lo) & (features[:, column] <= hi)
        gates[FEATURE_NAMES[column]] = {"percentiles": list(percentiles),
                                      "lower": float(lo), "upper": float(hi)}
    candidates = cluster[eligible[cluster]]
    diagnostics = {
        "sample_count": n, "k": k, "feature_dimension": int(standardized.shape[1]),
        "density_radius": smallest, "density_center_path_index": int(original_ids[center]),
        "cluster_member_path_indexes": [int(i) for i in original_ids[cluster]],
        "cluster_size": int(len(cluster)), "eligible_neighbor_count": int(len(candidates)),
        "eligibility_gates": gates, "scaling": scaling,
        "density_rule": "minimum exact kth-other Euclidean radius; ties original path id",
        "cluster_rule": "density center plus k nearest other paths; ties original path id",
        "medoid_rule": "minimum sum daily conditional-IQR-scaled log-price L1 distance to cluster",
    }
    if len(candidates) < MIN_ELIGIBLE_NEIGHBORS:
        return {"status": "blocked", "reason": "eligible_neighbors_below_9", **diagnostics}
    log_prices = np.log(prices)
    scaled_logs, daily_scaling = _standardize(log_prices, tuple(f"day_{i}" for i in range(prices.shape[1])))
    # Scaling is fit on the complete conditional distribution, not selected cluster.
    sums = cdist(scaled_logs[candidates], scaled_logs[cluster], metric="cityblock").sum(axis=1)
    minimum = float(np.min(sums))
    medoid_ties = candidates[sums == minimum]
    chosen = int(medoid_ties[np.argmin(original_ids[medoid_ties])])
    diagnostics.update({
        "member_path_index": int(original_ids[chosen]), "local_member_index": chosen,
        "medoid_distance_sum": minimum, "daily_distance_scaling": daily_scaling,
        "representative_metrics": _metrics(prices[chosen]), "status": "ok",
    })
    return diagnostics


def build_daily_flow(snapshot: dict[str, Any], *, calendar: dict[str, Any] | None = None
                     ) -> dict[str, Any]:
    """Build a deterministic display sidecar; never change a source snapshot or ledger."""
    inputs, trading_days, probabilities = _source_inputs(snapshot, calendar)
    asof = _day(inputs["asof"], "asof")
    calendar_end = add_calendar_months(asof, 6)
    all_days = [asof] + trading_days
    if trading_days[-1] < calendar_end:
        raise DailyFlowError("retained ensemble cannot cover six calendar months")
    month_indexes = [max(i for i, day in enumerate(all_days) if day <= add_calendar_months(asof, m))
                     for m in range(1, 7)]
    default_end_index = month_indexes[-1]
    if default_end_index < 2 or month_indexes[0] < 1:
        raise DailyFlowError("insufficient trading sessions for daily feature computation")
    future, masks = _ensemble(inputs)
    if not np.isfinite(future).all() or (future <= 0).any():
        raise DailyFlowError("reconstructed champion ensemble has nonfinite or nonpositive values")
    full = np.column_stack((np.full(len(future), inputs["anchor"]), future))
    shadow = _shadow(snapshot, inputs, future, masks)
    rows: dict[str, Any] = {}
    for key, mask in masks.items():
        ids = np.flatnonzero(mask)
        conditional = full[mask]
        row: dict[str, Any] = {
            "status": "blocked", "probability": probabilities[key], "probability_unit": "fraction",
            "model_probability": float(mask.mean()), "sample_count": int(len(ids)),
            "member_path_index": None, "values": [], "conditional_bands": {},
        }
        if len(ids):
            quantiles = np.percentile(conditional, (10, 25, 50, 75, 90), axis=0)
            row["conditional_bands"] = {name: values.tolist() for name, values in zip(_BAND_KEYS, quantiles)}
        if not shadow["passed"]:
            row["reason"] = "champion_shadow_reproduction_failed"
            row["selection"] = {"status": "blocked", "reason": row["reason"]}
            rows[key] = row
            continue
        prefix = conditional[:, :default_end_index + 1]
        selected = _select_member(prefix, ids, month_indexes)
        row["selection"] = selected
        row["status"] = selected["status"]
        if selected["status"] == "ok":
            chosen = selected["local_member_index"]
            row["member_path_index"] = selected["member_path_index"]
            row["values"] = conditional[chosen].tolist()
            row["end"] = float(conditional[chosen, default_end_index])
            row["selection"]["month_dates"] = [all_days[i].isoformat() for i in month_indexes]
            sensitivities = {}
            for name, k in (("half_k", max(9, math.ceil(selected["k"] / 2))),
                            ("double_k", min(len(ids) - 1, selected["k"] * 2))):
                alt = _select_member(prefix, ids, month_indexes, k=k)
                sensitivities[name] = {field: alt[field] for field in (
                    "status", "reason", "k", "member_path_index", "representative_metrics",
                    "density_radius", "eligible_neighbor_count") if field in alt}
            row["selection"]["sensitivities"] = sensitivities
            baseline = snapshot.get("structural_forecast", {}).get("paths", {}).get(key)
            if isinstance(baseline, dict):
                baseline = baseline.get("values")
            reference_dates = snapshot.get("structural_forecast", {}).get("dates", snapshot["week_dates"])
            if not isinstance(baseline, list):
                baseline = snapshot["paths"][key]["values"]
                reference_dates = snapshot["week_dates"]
            comparison_indexes = [(i, all_days.index(_day(day, "reference date")))
                                  for i, day in enumerate(reference_dates)
                                  if _day(day, "reference date") in all_days and _day(day, "reference date") <= calendar_end]
            deltas = [float(conditional[chosen, daily_i] - baseline[old_i])
                      for old_i, daily_i in comparison_indexes]
            row["selection"]["display_shadow"] = {
                "basis": "unchanged structural path at shared dated points within six months",
                "reference_dates": [reference_dates[i] for i, _ in comparison_indexes],
                "point_deltas": deltas, "maximum_absolute_delta": max(map(abs, deltas), default=0),
                "old_reference_metrics": _metrics(np.asarray([baseline[i] for i, _ in comparison_indexes], dtype=float))
                    if len(comparison_indexes) > 2 else None,
                "reference_metric_sampling": "weekly; volatility and direction rate not directly comparable to daily",
                "new_daily_metrics": selected["representative_metrics"],
            }
        else:
            row["reason"] = selected["reason"]
        rows[key] = row
    dominant = max(SCENARIOS, key=lambda key: probabilities[key])
    touched = np.maximum.accumulate(future <= inputs.get("simulation_corr10", inputs["corr10"]), axis=1).mean(axis=0)
    cumulative_touch = [0.0] + touched.tolist()
    payload = {
        "schema_version": SCHEMA_VERSION, "version": VERSION,
        "status": "ok" if shadow["passed"] and rows[dominant]["status"] == "ok" else "blocked",
        "source_snapshot_id": inputs["source_snapshot_id"], "source_snapshot_sha256": _hash(snapshot),
        "input_sha256": _hash(inputs), "asof": inputs["asof"], "anchor": inputs["anchor"],
        "calendar_end": calendar_end.isoformat(), "default_end_index": default_end_index,
        "dates": [day.isoformat() for day in all_days], "probability_unit": "fraction",
        "scenarios": rows, "risk": {
            "probability_unit": "fraction", "probability_space": "original_all_gbm_ensemble",
            "direction": "at_or_below", "threshold": inputs["corr10"],
            "cumulative_touch": cumulative_touch,
            "levels": ["고" if value >= .35 else "중" if value >= .15 else "저" for value in cumulative_touch],
            "sampling": "daily discrete first touch, D+1 onward; anchor probability zero",
        }, "shadow": shadow, "provenance": {
            "inputs": inputs, "source_probability_unit": inputs["source_probability_unit"],
            "source_probability_unit_basis": inputs["source_probability_unit_basis"],
            "ensemble": "same champion seed/shape/shock order and GBM drift; stored parameters only",
            "selection_horizon": "six calendar months, last trading session on or before each month boundary",
            "member_path_values": "unrounded actual simulated member; anchor plus retained full 252 sessions",
            "distribution_changed": False, "official_snapshot_changed": False,
            "path_kind": "actual_gbm_member_of_modal_feature_cluster",
            "density_probability_claim": "feature-space modal region; exact trajectory occurrence probability not claimed",
            "display_revision": VERSION, "model_version": snapshot["method"],
            "calendar_basis": "registered NYSE calendar verified" if calendar is not None else "source retained trading dates",
            "limitations": ["GBM normal increments do not model fat tails, event shocks, or volatility clustering",
                            "feature-space modal member is illustrative, not an exact future price forecast",
                            "scenario weights describe the unchanged year-end partition, not this path's probability"],
        },
    }
    if "simulation_corr10" in inputs:
        payload["risk"]["simulation_threshold"] = inputs["simulation_corr10"]
    if payload["status"] == "blocked":
        payload["reason"] = "champion_shadow_reproduction_failed" if not shadow["passed"] else "dominant_scenario_selection_blocked"
    return validate_daily_flow(payload, snapshot)


def validate_daily_flow(payload: dict[str, Any], source_snapshot: dict[str, Any] | None = None
                        ) -> dict[str, Any]:
    """Validate sidecar shape, fractions, source binding, dates and selection gates."""
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION or payload.get("version") != VERSION:
        raise DailyFlowError("unsupported daily_flow schema/version")
    if payload.get("status") not in ("ok", "blocked") or payload.get("probability_unit") != "fraction":
        raise DailyFlowError("daily_flow status and explicit fraction probability unit are required")
    asof = _day(payload.get("asof"), "asof")
    end = _day(payload.get("calendar_end"), "calendar_end")
    if end != add_calendar_months(asof, 6):
        raise DailyFlowError("daily_flow calendar_end must be six calendar months after asof")
    dates = payload.get("dates")
    if not isinstance(dates, list) or len(dates) != 253:
        raise DailyFlowError("daily_flow requires anchor plus 252 daily dates")
    days = [_day(day, "dates") for day in dates]
    if days[0] != asof or any(b <= a for a, b in zip(days, days[1:])):
        raise DailyFlowError("daily_flow dates must start at asof and strictly increase")
    default_end = _integer(payload.get("default_end_index"), "default_end_index", 1)
    if default_end != max(i for i, day in enumerate(days) if day <= end) or days[-1] < end:
        raise DailyFlowError("daily_flow default_end_index does not cover its calendar horizon")
    anchor = _number(payload.get("anchor"), "anchor", positive=True)

    def values(series: Any, field: str, *, probability: bool = False) -> list[float]:
        if not isinstance(series, list) or len(series) != len(days):
            raise DailyFlowError(f"{field} must align with all daily dates")
        parsed = [_number(value, field, positive=not probability) for value in series]
        if probability and any(not 0 <= value <= 1 for value in parsed):
            raise DailyFlowError(f"{field} fraction probabilities must be in [0,1]")
        return parsed

    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, dict) or set(scenarios) != set(SCENARIOS):
        raise DailyFlowError("daily_flow scenarios must be S1/S2/S3")
    probabilities = []
    for key, row in scenarios.items():
        probability = _number(row.get("probability"), f"{key} probability")
        if row.get("probability_unit") != "fraction" or not 0 <= probability <= 1:
            raise DailyFlowError("daily_flow scenario probability must declare fraction in [0,1]")
        probabilities.append(probability)
        if row.get("status") not in ("ok", "blocked"):
            raise DailyFlowError(f"{key} has invalid status")
        bands = row.get("conditional_bands")
        if not isinstance(bands, dict):
            raise DailyFlowError(f"{key} conditional bands must be an object")
        if bands:
            if set(bands) != set(_BAND_KEYS):
                raise DailyFlowError(f"{key} conditional bands must be p10/p25/p50/p75/p90")
            arrays = np.asarray([values(bands[name], f"{key} {name}") for name in _BAND_KEYS])
            if not np.all(arrays[:, 0] == anchor) or np.any(np.diff(arrays, axis=0) < 0):
                raise DailyFlowError(f"{key} conditional bands violate anchor or quantile ordering")
        if row["status"] == "blocked":
            if not row.get("reason") or row.get("values") != [] or row.get("member_path_index") is not None:
                raise DailyFlowError(f"{key} blocked row must retain an auditable reason and no representative")
            continue
        series = values(row.get("values"), f"{key} representative")
        if series[0] != anchor or not bands:
            raise DailyFlowError(f"{key} selected member must start at anchor and have bands")
        _integer(row.get("member_path_index"), f"{key} member_path_index")
        selection = row.get("selection", {})
        if selection.get("status") != "ok" or selection.get("member_path_index") != row["member_path_index"]:
            raise DailyFlowError(f"{key} selection and representative identities disagree")
        if selection.get("sample_count", 0) < MIN_CONDITIONAL_PATHS or selection.get("eligible_neighbor_count", 0) < MIN_ELIGIBLE_NEIGHBORS:
            raise DailyFlowError(f"{key} representative fails sample/eligibility gates")
        metrics = _metrics(np.asarray(series[:default_end + 1]))
        for metric, gate in selection.get("eligibility_gates", {}).items():
            if metric not in metrics or not gate["lower"] <= metrics[metric] <= gate["upper"]:
                raise DailyFlowError(f"{key} selected representative violates {metric} gate")
    if not math.isclose(sum(probabilities), 1.0, rel_tol=0, abs_tol=1e-12):
        raise DailyFlowError("daily_flow scenario probabilities must sum to one without normalization")
    risk = payload.get("risk", {})
    if risk.get("probability_unit") != "fraction" or risk.get("probability_space") != "original_all_gbm_ensemble":
        raise DailyFlowError("risk must declare fraction and original_all_gbm_ensemble")
    touch = values(risk.get("cumulative_touch"), "cumulative_touch", probability=True)
    if touch[0] != 0 or any(b < a for a, b in zip(touch, touch[1:])):
        raise DailyFlowError("daily cumulative first-touch risk must start at zero and be nondecreasing")
    if risk.get("levels") != ["고" if value >= .35 else "중" if value >= .15 else "저" for value in touch]:
        raise DailyFlowError("daily risk labels must match registered fraction thresholds")
    shadow = payload.get("shadow", {})
    checks = shadow.get("checks")
    if (not isinstance(checks, dict) or not checks
            or shadow.get("passed") != all(check.get("passed") is True for check in checks.values())
            or shadow.get("tolerance") != "exact_serialized"):
        raise DailyFlowError("daily_flow shadow checks and status must agree at exact stored precision")
    dominant = max(SCENARIOS, key=lambda key: scenarios[key]["probability"])
    expected_status = "ok" if shadow.get("passed") is True and scenarios[dominant]["status"] == "ok" else "blocked"
    if payload["status"] != expected_status:
        raise DailyFlowError("daily_flow publication status disagrees with shadow and dominant scenario gates")
    if payload["status"] == "blocked" and not payload.get("reason"):
        raise DailyFlowError("blocked daily_flow must provide an auditable reason")
    if source_snapshot is not None:
        if payload.get("source_snapshot_id") != source_snapshot.get("snapshot_id") or payload.get("source_snapshot_sha256") != _hash(source_snapshot):
            raise DailyFlowError("daily_flow source snapshot binding mismatch")
        if payload["asof"] != source_snapshot.get("asof") or anchor != source_snapshot.get("anchor"):
            raise DailyFlowError("daily_flow source date/anchor mismatch")
        if dates[1:] != source_snapshot.get("quantile_table", {}).get("trading_days"):
            raise DailyFlowError("daily_flow date grid must equal the retained champion date grid")
        source_inputs, _, source_probabilities = _source_inputs(source_snapshot, None)
        if payload.get("input_sha256") != _hash(source_inputs):
            raise DailyFlowError("daily_flow input binding mismatch")
        if shadow.get("source_snapshot_sha256") != _hash(source_snapshot) or shadow.get("input_sha256") != _hash(source_inputs):
            raise DailyFlowError("daily_flow shadow source binding mismatch")
        reconstructed, masks = _ensemble(source_inputs)
        expected_shadow = _shadow(source_snapshot, source_inputs, reconstructed, masks)
        if shadow != expected_shadow:
            raise DailyFlowError("daily_flow shadow does not reproduce its source")
        expected_touch = [0.0] + np.maximum.accumulate(reconstructed <= source_inputs.get("simulation_corr10", source_inputs["corr10"]), axis=1).mean(axis=0).tolist()
        if (not np.allclose(touch, expected_touch, rtol=0, atol=FRACTION_REPLAY_ABS_TOLERANCE)
                or risk.get("threshold") != source_inputs["corr10"]):
            raise DailyFlowError("daily_flow risk must use the original complete GBM ensemble")
        if "simulation_corr10" in source_inputs and risk.get("simulation_threshold") != source_inputs["simulation_corr10"]:
            raise DailyFlowError("daily_flow risk simulation threshold must reproduce the source precision")
        for key, row in scenarios.items():
            if row["probability"] != source_probabilities[key] or row.get("model_probability") != float(masks[key].mean()):
                raise DailyFlowError(f"{key} source scenario probability mismatch")
            if row["status"] == "ok":
                member = row["member_path_index"]
                if member >= len(reconstructed) or not masks[key][member]:
                    raise DailyFlowError(f"{key} selected path is not a source conditional member")
                if not np.allclose(row["values"], [anchor] + reconstructed[member].tolist(),
                                   rtol=0, atol=PRICE_REPLAY_ABS_TOLERANCE):
                    raise DailyFlowError(f"{key} values are not the actual unchanged source member")
    return payload
