"""Offline retrospective relative-strength models with purged expanding evaluation.

No official forecasts, database writes, application imports, or network calls.
Hyperparameters are fixed before this run, not selected on this evaluation set.
Historical vendor-delivery vintages are unavailable; live promotion is blocked.
"""
from __future__ import annotations
import argparse
import csv
import datetime as dt
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import sqlite3

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import brier_score_loss, log_loss, mean_absolute_error, mean_squared_error
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
AS_OF = "2026-10-12T10:38:50+09:00"
HORIZONS = [21, 57]
SEED = 20261012
INITIAL_ORIGIN = 1386  # 126-session feature burn-in + five years of history.
REFIT_SESSIONS = 63
BOOTSTRAP_REPLICATIONS = 1200


def finite_positive(series: pd.Series, name: str) -> None:
    values = series.to_numpy(dtype=float)
    if not np.all(np.isfinite(values) & (values > 0)):
        raise ValueError(f"Invalid {name}; missing or nonpositive observations are not filled")


def load_prices(folder: Path = ROOT) -> pd.DataFrame:
    series = []
    for symbol in ["SOXX", "IGV", "SPY"]:
        frame = pd.read_csv(folder / "price_inputs" / f"{symbol}_adjusted_history.csv")
        if frame.date.duplicated().any():
            raise ValueError(f"Duplicate dates in {symbol}")
        if frame.date.max() > "2026-10-09":
            raise ValueError("Incomplete/future session")
        finite_positive(frame.adj_close, symbol)
        if not frame.date.is_monotonic_increasing:
            raise ValueError("Input history must already be chronological")
        series.append(frame.set_index("date").adj_close.rename(symbol))
    if not all(series[0].index.equals(item.index) for item in series[1:]):
        raise ValueError("Session mismatch; no forward fill/interpolation permitted")
    return pd.concat(series, axis=1)


def make_features(prices: pd.DataFrame) -> pd.DataFrame:
    logp = np.log(prices)
    returns = logp.diff()
    relative = logp.SOXX - logp.IGV
    x = pd.DataFrame(index=prices.index)
    for lag in [5, 21, 63, 126]:
        x[f"relative_log_momentum_{lag}"] = relative.diff(lag)
    for symbol in ["SOXX", "IGV"]:
        x[f"{symbol}_vol_21"] = returns[symbol].rolling(21).std(ddof=1) * np.sqrt(252)
        x[f"{symbol}_drawdown_126"] = prices[symbol] / prices[symbol].rolling(126).max() - 1
    for lag in [21, 63]:
        x[f"SPY_log_momentum_{lag}"] = logp.SPY.diff(lag)
    x["pair_corr_63"] = returns.SOXX.rolling(63).corr(returns.IGV)
    variance = returns.SPY.rolling(126).var(ddof=1)
    x["beta_difference_126"] = (returns.SOXX.rolling(126).cov(returns.SPY)
                                      - returns.IGV.rolling(126).cov(returns.SPY)) / variance
    return x


def relative_target(prices: pd.DataFrame, horizon: int) -> pd.Series:
    logratio = np.log(prices.SOXX / prices.IGV)
    return logratio.shift(-horizon) - logratio


def purged_training_indices(origin: int, horizon: int, valid: np.ndarray) -> np.ndarray:
    # One-session embargo: latest train label ends at origin - 1, strictly before test start.
    indices = np.flatnonzero(valid & (np.arange(len(valid)) + horizon < origin))
    if len(indices) and not np.all(indices + horizon < origin):
        raise AssertionError("Training label overlaps a test origin")
    return indices


def models():
    return {
        "ridge": make_pipeline(StandardScaler(), Ridge(alpha=10.0)),
        "logistic": make_pipeline(StandardScaler(), LogisticRegression(C=0.1, max_iter=3000, random_state=SEED)),
        "random_forest": RandomForestClassifier(n_estimators=150, max_depth=3,
                                                min_samples_leaf=50, max_features="sqrt",
                                                random_state=SEED, n_jobs=2),
    }


def block_bootstrap_interval(values: np.ndarray, block: int, seed: int = SEED) -> list[float]:
    """Circular moving blocks preserve short dependence; CI is for mean score difference."""
    if len(values) < block * 2:
        return [None, None]
    rng = np.random.default_rng(seed)
    blocks = math.ceil(len(values) / block)
    means = np.empty(BOOTSTRAP_REPLICATIONS)
    offsets = np.arange(block)
    for i in range(BOOTSTRAP_REPLICATIONS):
        starts = rng.integers(0, len(values), size=blocks)
        indices = ((starts[:, None] + offsets) % len(values)).ravel()[:len(values)]
        means[i] = values[indices].mean()
    return [float(item) for item in np.quantile(means, [0.025, 0.975])]


def summarize_oos(rows: pd.DataFrame, horizon: int) -> dict:
    y = rows.target_log_ratio.to_numpy()
    label = rows.label.to_numpy(dtype=int)
    baseline_prob = rows.baseline_probability.to_numpy()
    baseline_mean = rows.baseline_mean.to_numpy()
    anchor = rows.iloc[::horizon]
    output = {"daily_origin_count": len(rows), "daily_labels_overlap": True,
              "nonoverlapping_anchor_count": len(anchor),
              "nonoverlapping_anchors_note": "Labels do not overlap; this does not prove full statistical independence.",
              "first_origin": rows.date.iloc[0], "last_matured_origin": rows.date.iloc[-1],
              "outcome_class_1_count": int(label.sum()), "models": {}}
    regression_predictions = {"expanding_mean_baseline": baseline_mean, "ridge": rows.ridge_prediction.to_numpy(),
                              "momentum_63_scaled_baseline": rows.momentum_prediction.to_numpy()}
    baseline_abs_error = np.abs(baseline_mean - y)
    for name, prediction in regression_predictions.items():
        errors = np.abs(prediction - y)
        score_difference = baseline_abs_error - errors
        ci = block_bootstrap_interval(score_difference, horizon)
        anchor_pred = prediction[::horizon]
        output["models"][name] = {"kind": "regression", "target_unit": "log_gross_return_ratio",
            "mae": float(mean_absolute_error(y, prediction)),
            "rmse": float(np.sqrt(mean_squared_error(y, prediction))),
            "direction_accuracy_fraction": float(np.mean((prediction > 0) == label)),
            "anchor_mae": float(mean_absolute_error(anchor.target_log_ratio, anchor_pred)),
            "mean_mae_improvement_vs_expanding_mean": float(score_difference.mean()),
            "mae_improvement_block_bootstrap_95_interval": ci,
            "exploratory_skill_gate": "pass" if ci[0] is not None and ci[0] > 0 else "not_demonstrated"}
    baseline_squared_error = (baseline_prob - label) ** 2
    classifiers = {"expanding_class_frequency_baseline": baseline_prob,
                   "momentum_sign_baseline": (rows.momentum_prediction.to_numpy() > 0).astype(float),
                   "logistic": rows.logistic_probability.to_numpy(),
                   "random_forest": rows.random_forest_probability.to_numpy()}
    for name, probability in classifiers.items():
        if not np.all((probability >= 0) & (probability <= 1)):
            raise ValueError("Probability unit/bounds violation")
        improvement = baseline_squared_error - (probability - label) ** 2
        ci = block_bootstrap_interval(improvement, horizon)
        metric = {"kind": "classifier", "probability_unit": "fraction",
            "brier": float(brier_score_loss(label, probability)),
            "log_loss": float(log_loss(label, probability, labels=[0, 1])),
            "direction_accuracy_fraction": float(np.mean((probability >= .5) == label)),
            "anchor_brier": float(brier_score_loss(anchor.label, probability[::horizon])),
            "mean_brier_improvement_vs_class_frequency": float(improvement.mean()),
            "brier_improvement_block_bootstrap_95_interval": ci,
            "exploratory_skill_gate": "pass" if ci[0] is not None and ci[0] > 0 else "not_demonstrated",
            "calibration_bins": []}
        for low, high in [(0, .4), (.4, .5), (.5, .6), (.6, 1.0000001)]:
            mask = (probability >= low) & (probability < high)
            metric["calibration_bins"].append({"lower_fraction": low, "upper_fraction": min(1, high),
                 "n": int(mask.sum()), "average_probability": float(probability[mask].mean()) if mask.any() else None,
                 "observed_frequency": float(label[mask].mean()) if mask.any() else None})
        output["models"][name] = metric
    return output


def evaluate(prices: pd.DataFrame, features: pd.DataFrame, horizon: int) -> tuple[dict, pd.DataFrame]:
    target = relative_target(prices, horizon)
    feature_valid = np.isfinite(features.to_numpy()).all(axis=1)
    valid = feature_valid & target.notna().to_numpy()
    x = features.to_numpy(); y = target.to_numpy()
    output_rows = []; folds = []
    for origin in range(INITIAL_ORIGIN, len(prices) - horizon, REFIT_SESSIONS):
        train = purged_training_indices(origin, horizon, valid)
        test = np.arange(origin, min(origin + REFIT_SESSIONS, len(prices) - horizon))
        test = test[valid[test]]
        if not len(test):
            continue
        if len(train) < 1000:
            raise ValueError("Insufficient train observations")
        fits = models()
        fits["ridge"].fit(x[train], y[train])
        label_train = (y[train] > 0).astype(int)
        fits["logistic"].fit(x[train], label_train)
        fits["random_forest"].fit(x[train], label_train)
        regression = fits["ridge"].predict(x[test])
        logistic = fits["logistic"].predict_proba(x[test])[:, 1]
        forest = fits["random_forest"].predict_proba(x[test])[:, 1]
        base_prob = float(label_train.mean()); base_mean = float(y[train].mean())
        for offset, index in enumerate(test):
            output_rows.append({"date": prices.index[index], "horizon_sessions": horizon,
                "label_end_date": prices.index[index + horizon], "target_log_ratio": float(y[index]),
                "label": int(y[index] > 0), "ridge_prediction": float(regression[offset]),
                "logistic_probability": float(logistic[offset]), "random_forest_probability": float(forest[offset]),
                "baseline_probability": base_prob, "baseline_mean": base_mean,
                "momentum_prediction": float(features.relative_log_momentum_63.iloc[index] * horizon / 63),
                "fold_first_origin": prices.index[origin]})
        folds.append({"train_origin_count": len(train), "first_train_origin": prices.index[train[0]],
                      "last_train_origin": prices.index[train[-1]],
                      "last_train_label_end": prices.index[train[-1] + horizon],
                      "first_test_origin": prices.index[test[0]], "last_test_origin": prices.index[test[-1]],
                      "test_origin_count": len(test), "strict_train_label_end_before_test": bool(train[-1] + horizon < test[0])})
    rows = pd.DataFrame(output_rows)
    evaluation = summarize_oos(rows, horizon)
    evaluation["fold_count"] = len(folds); evaluation["folds"] = folds
    latest_origin = len(prices) - 1
    train = purged_training_indices(latest_origin, horizon, valid)
    fits = models()
    fits["ridge"].fit(x[train], y[train]); labels = (y[train] > 0).astype(int)
    fits["logistic"].fit(x[train], labels); fits["random_forest"].fit(x[train], labels)
    prediction = float(fits["ridge"].predict(x[[latest_origin]])[0])
    evaluation["current_exploratory_outputs"] = {
        "origin": prices.index[-1], "training_origin_count": len(train),
        "last_train_label_end": prices.index[train[-1] + horizon],
        "ridge_log_ratio_prediction": prediction, "ridge_gross_return_ratio_minus_one_fraction": float(np.expm1(prediction)),
        "logistic_soxx_outperformance_probability_fraction": float(fits["logistic"].predict_proba(x[[latest_origin]])[0, 1]),
        "random_forest_soxx_outperformance_probability_fraction": float(fits["random_forest"].predict_proba(x[[latest_origin]])[0, 1]),
        "expanding_class_frequency_fraction": float(labels.mean()),
        "expanding_mean_log_ratio": float(y[train].mean()),
        "prospective_usable": False,
        "warning": "Retrospective-vintage model outputs; not a validated year-end winning probability or official forecast."}
    evaluation["current_model_diagnostics"] = {
        "ridge_standardized_feature_coefficients": dict(zip(features.columns, map(float, fits["ridge"][-1].coef_))),
        "ridge_intercept": float(fits["ridge"][-1].intercept_),
        "logistic_standardized_feature_coefficients": dict(zip(features.columns, map(float, fits["logistic"][-1].coef_[0]))),
        "logistic_intercept": float(fits["logistic"][-1].intercept_[0]),
        "random_forest_impurity_feature_importance": dict(zip(features.columns, map(float, fits["random_forest"].feature_importances_))),
        "interpretation_warning": "Coefficients/impurity importance explain this fitted exploratory model; they are not causal effects or independently validated signals."
    }
    evaluation["fixed_reporting_subperiods"] = {}
    for name, start, end in [("2013_2019", "2013-01-01", "2019-12-31"),
                              ("2020_2023", "2020-01-01", "2023-12-31"),
                              ("2024_2026", "2024-01-01", "2026-12-31")]:
        period = rows[(rows.date >= start) & (rows.date <= end)]
        evaluation["fixed_reporting_subperiods"][name] = {
            "n_overlapping_origins": len(period),
            "class_frequency_baseline_brier": float(brier_score_loss(period.label, period.baseline_probability)),
            "logistic_brier": float(brier_score_loss(period.label, period.logistic_probability)),
            "random_forest_brier": float(brier_score_loss(period.label, period.random_forest_probability)),
            "mean_baseline_mae": float(mean_absolute_error(period.target_log_ratio, period.baseline_mean)),
            "ridge_mae": float(mean_absolute_error(period.target_log_ratio, period.ridge_prediction))}
    return evaluation, rows


def max_drawdown(prices: pd.Series) -> float:
    return float((prices / prices.cummax() - 1).min())


def descriptive(prices: pd.DataFrame) -> dict:
    returns = np.log(prices).diff().dropna()
    windows = {}
    for horizon in [21, 57, 126, 252, 756]:
        ret = returns.iloc[-horizon:]
        endpoints = prices.iloc[-horizon-1:]
        entry = {"observation_sessions": horizon, "from_close": endpoints.index[0], "to_close": endpoints.index[-1],
                 "pair_correlation": float(ret.SOXX.corr(ret.IGV)), "sectors": {}}
        variance = ret.SPY.var(ddof=1)
        for symbol in ["SOXX", "IGV", "SPY"]:
            entry["sectors"][symbol] = {"adjusted_total_return_fraction": float(endpoints[symbol].iloc[-1] / endpoints[symbol].iloc[0] - 1),
                "realized_annualized_log_return_volatility_fraction": float(ret[symbol].std(ddof=1) * np.sqrt(252)),
                "market_beta_OLS": float(ret[symbol].cov(ret.SPY) / variance),
                "maximum_drawdown_fraction": max_drawdown(endpoints[symbol])}
        entry["relative_gross_return_ratio_minus_one_fraction"] = float((endpoints.SOXX.iloc[-1] / endpoints.SOXX.iloc[0])
                                                                      / (endpoints.IGV.iloc[-1] / endpoints.IGV.iloc[0]) - 1)
        windows[str(horizon)] = entry
    yearstart = prices.index[prices.index < "2026-01-01"][-1]
    ytd = prices.loc[yearstart:]
    return {"kind": "retrospective descriptive statistics, not forward risk limits", "probability_unit": "fraction",
            "return_convention": "Vendor adjusted close, before tax, no transaction costs, no extra annual fee subtraction",
            "windows": windows, "ytd": {symbol: float(ytd[symbol].iloc[-1] / ytd[symbol].iloc[0] - 1) for symbol in prices.columns},
            "full_history_max_drawdown": {symbol: max_drawdown(prices[symbol]) for symbol in prices.columns},
            "latest_close_validation": {"expected_SOXX": 559.40, "observed_SOXX": float(prices.SOXX.iloc[-1]),
                                         "expected_IGV": 112.67, "observed_IGV": float(prices.IGV.iloc[-1]),
                                         "both_match_to_cent": bool(abs(prices.SOXX.iloc[-1]-559.40)<.005 and abs(prices.IGV.iloc[-1]-112.67)<.005)}}


def inventory() -> dict:
    database_path = REPO / "dualdb/db/dualdb.sqlite"
    before = hashlib.sha256(database_path.read_bytes()).hexdigest()
    connection = sqlite3.connect(database_path.as_uri() + "?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON"); connection.row_factory = sqlite3.Row
    series = [dict(row) for row in connection.execute(
        "SELECT series,COUNT(*) AS n,MIN(date) AS first_date,MAX(date) AS last_date,MAX(ingested_at) AS latest_ingested_at FROM price_daily GROUP BY series ORDER BY series")]
    columns = [row["name"] for row in connection.execute("PRAGMA table_info(price_daily)")]
    connection.close()
    after = hashlib.sha256(database_path.read_bytes()).hexdigest()
    if before != after:
        raise AssertionError("Database changed during read-only inventory")
    manifest = json.loads((ROOT / "price_history_manifest.json").read_text(encoding="utf-8"))
    return {"research_as_of": AS_OF, "database": "dualdb/db/dualdb.sqlite", "sqlite_mode": "ro",
            "query_only": True, "sha256_before": before, "sha256_after": after, "unchanged": True,
            "columns": columns, "series": series, "internal_pair_missing": ["SOXX", "IGV"],
            "internal_available_at_missing": "available_at" not in columns,
            "external_histories": manifest["histories"],
            "original_vintage_gate": "blocked", "gate_reason": "No original historical available_at or adjustment vintages; public HTML collected after study cutoff.",
            "retrospective_research_allowed": True}


def run() -> dict:
    prices = load_prices(); features = make_features(prices)
    results = {}; all_rows = []
    for horizon in HORIZONS:
        print(f"Evaluating h={horizon} sessions...", flush=True)
        results[str(horizon)], rows = evaluate(prices, features, horizon)
        all_rows.append(rows)
    pd.concat(all_rows, ignore_index=True).to_csv(ROOT / "ml_oos_predictions.csv", index=False)
    features.to_csv(ROOT / "ml_feature_matrix.csv", index_label="date")
    import exchange_calendars as xcals
    calendar = xcals.get_calendar("XNYS")
    sessions = calendar.sessions_in_range("2026-10-12", "2026-12-31")
    if len(sessions) != 57:
        raise ValueError(f"Unexpected residual horizon: {len(sessions)}")
    result = {"research_as_of": AS_OF, "price_as_of": prices.index[-1],
              "target_market_close": "2026-12-31", "remaining_sessions": len(sessions),
              "remaining_session_dates": [str(item.date()) for item in sessions],
              "canonical_probability_unit": "fraction", "ml_status": "retrospective_computed",
              "prospective_forecast_gate": "blocked", "official_model_changes": 0,
              "reason": "Current revised history lacks original delivery/adjustment vintages; do not advertise outputs as calibrated live winning probabilities.",
              "training_panel_rows": len(prices), "history_start": prices.index[0], "history_end": prices.index[-1],
              "target_definition": "y_t,h = log(SOXX_adjusted[t+h]/SOXX_adjusted[t]) - log(IGV_adjusted[t+h]/IGV_adjusted[t]); label=1 iff y>0",
              "target_interpretation": "expm1(y) is the ratio of gross total returns minus one, not arithmetic percentage-point return difference",
              "feature_names": list(features), "feature_count": len(features.columns),
              "method": {"initial_origin_index": INITIAL_ORIGIN, "refit_sessions": REFIT_SESSIONS,
                         "train": "expanding", "embargo_sessions": 1,
                         "label_gate": "train_origin + horizon < first_test_origin",
                         "scaler": "fit on each train fold only", "random_split": False,
                         "hyperparameter_search": False, "hyperparameters_fixed_before_this_run": True,
                         "preregistered_before_historical_outcomes": False,
                         "scope": "Retrospective model comparison, not tradable P&L or prospective validation",
                         "ridge_alpha": 10.0, "logistic_C": .1, "random_forest": {"trees":150,"max_depth":3,"min_leaf":50},
                         "bootstrap_replications": BOOTSTRAP_REPLICATIONS, "bootstrap_block_sessions": "equal to label horizon",
                         "bootstrap_caveat": "Overlapping labels handled in moving blocks; regime changes and model selection uncertainty are not fully covered.",
                         "seed": SEED},
              "descriptive_stats": descriptive(prices), "horizons": results,
              "package_versions": {name: importlib.metadata.version(name) for name in ["numpy", "pandas", "scikit-learn", "exchange-calendars"]}}
    result["method_sources"] = [
        {"title":"Ridge official documentation", "url":"https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html", "role":"algorithm reference, not forecast evidence"},
        {"title":"LogisticRegression official documentation", "url":"https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html", "role":"algorithm reference, not forecast evidence"},
        {"title":"RandomForestClassifier official documentation", "url":"https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.RandomForestClassifier.html", "role":"algorithm reference, not forecast evidence"},
        {"title":"TimeSeriesSplit official documentation", "url":"https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html", "role":"chronological evaluation reference; implemented custom maturity purge goes beyond ordinary fixed gap"}]
    (ROOT / "data_inventory.json").write_text(json.dumps(inventory(), ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "quantitative_ml.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return result


if __name__ == "__main__":
    run()
