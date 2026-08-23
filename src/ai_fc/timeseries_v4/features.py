"""Point-in-time V4 feature view built from the isolated source ledger.

The view is deliberately availability aligned.  A source value is attached to
the first US market session whose close is not earlier than ``available_at``;
no observation date is used as a substitute for release availability.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from ai_fc.timeseries_v3.pipeline import load_v3_frame

from .source_store import read_v4_observations


CORE_MARKET_SERIES = (
    "VIX9D", "VIX3M", "VVIX", "SKEW", "NASDAQ100",
    "US_EQ_TOTAL_NOTIONAL", "US_EQ_TAPE_C_NOTIONAL_SHARE",
    "US_EQ_OFF_EXCHANGE_NOTIONAL_SHARE", "US_EQ_TOTAL_TRADES",
)


def _deps():
    try:
        import pandas as pd  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("install ai-fc[timeseries,pit] for V4") from exc
    return pd


def _available_session_day(value: str):
    pd = _deps()
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    return timestamp.tz_convert("America/New_York").tz_localize(None).normalize()


def _asof_series(rows: list[dict[str, Any]], index, *, name: str):
    pd = _deps()
    if not rows:
        return pd.Series(np.nan, index=index, name=name, dtype=float)
    source = pd.DataFrame(rows)
    source["available_session"] = source["available_at"].map(_available_session_day)
    source = source.sort_values(["available_session", "revision_seq", "observation_id"])
    source = source.drop_duplicates("available_session", keep="last")
    left = pd.DataFrame({"session": pd.DatetimeIndex(index)}).sort_values("session")
    joined = pd.merge_asof(
        left, source[["available_session", "value"]], left_on="session",
        right_on="available_session", direction="backward", allow_exact_matches=True,
    )
    return pd.Series(joined["value"].to_numpy(dtype=float), index=left["session"], name=name).reindex(index)


def _market_close_series(rows: list[dict[str, Any]], index, *, name: str):
    """Market closes become known at their explicit availability timestamp."""
    return _asof_series(rows, index, name=name)


def _dimensions(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return {str(key): str(item) for key, item in value.items()}
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return {str(key): str(item) for key, item in parsed.items()}
    return {}


def build_v4_feature_frame(root: Path):
    """Return the V3 PIT frame augmented by every usable V4 source block.

    Sparse captured-forward inputs are retained as columns and accompanied by
    availability flags.  The model layer decides whether the preregistered
    60-observation minimum permits a coefficient; this function never silently
    fills a future event value.
    """
    pd = _deps()
    base, engineered, returns, index_values = load_v3_frame(root)
    sessions = pd.DatetimeIndex(base.index).tz_localize(None)
    facts = [row.model_dump(mode="json") for row in read_v4_observations(root)]
    by_series: dict[str, list[dict[str, Any]]] = {}
    for row in facts:
        row["dimensions"] = _dimensions(row.get("dimensions"))
        by_series.setdefault(str(row["series_id"]), []).append(row)

    output = engineered.copy()
    raw: dict[str, Any] = {}
    for series_id in CORE_MARKET_SERIES:
        raw[series_id] = _market_close_series(by_series.get(series_id, []), sessions, name=series_id)

    positive = lambda series: series.where(series > 0)
    output["log_vix9d_vix3m"] = np.log(positive(raw["VIX9D"]) / positive(raw["VIX3M"]))
    output["log_vix_vix3m"] = output["vix_level"] - np.log(positive(raw["VIX3M"]))
    output["log_vvix_change_5d"] = np.log(positive(raw["VVIX"])).diff(5)
    output["skew_level"] = raw["SKEW"]
    output["skew_change_5d"] = raw["SKEW"].diff(5)
    nasdaq_return_21 = base["nasdaq_return"].rolling(21).sum()
    output["nasdaq100_to_composite_relative_strength_21d"] = (
        np.log(positive(raw["NASDAQ100"])).diff(21) - nasdaq_return_21
    )
    output["tape_c_notional_share"] = raw["US_EQ_TAPE_C_NOTIONAL_SHARE"]
    output["off_exchange_notional_share"] = raw["US_EQ_OFF_EXCHANGE_NOTIONAL_SHARE"]
    output["log_total_notional_change_21d"] = np.log(positive(raw["US_EQ_TOTAL_NOTIONAL"])).diff(21)
    output["log_total_trades_change_21d"] = np.log(positive(raw["US_EQ_TOTAL_TRADES"])).diff(21)

    # Cleveland monthly nowcasts can contain overlapping target panels.  Keep
    # the panel whose target month equals the as-of month; otherwise do not
    # manufacture a value from another target period.
    cleveland_map = {
        "CLEVELAND_CPI_NOWCAST": "cleveland_cpi_nowcast",
        "CLEVELAND_CORE_CPI_NOWCAST": "cleveland_core_cpi_nowcast",
        "CLEVELAND_PCE_NOWCAST": "cleveland_pce_nowcast",
        "CLEVELAND_CORE_PCE_NOWCAST": "cleveland_core_pce_nowcast",
    }
    for series_id, column in cleveland_map.items():
        selected: list[dict[str, Any]] = []
        for row in by_series.get(series_id, []):
            dimensions = row["dimensions"]
            if dimensions.get("frequency") != "month":
                continue
            day = pd.Timestamp(row["observation_time"])
            target = dimensions.get("target_period", "")
            if target == f"{day.year}-{day.month}":
                selected.append(row)
        output[column] = _asof_series(selected, sessions, name=column)

    spf_map = {
        "SPF_EMP_MEAN_EMP1": "spf_employment_mean",
        "SPF_EMP_DISPERSION_EMP_D1_T": "spf_employment_dispersion",
        "SPF_CPI_MEAN_CPI1": "spf_cpi_mean",
        "SPF_CPI_DISPERSION_CPI_D1_T": "spf_cpi_dispersion",
        "SPF_UNEMP_MEAN_UNEMP1": "spf_unemployment_mean",
        "SPF_UNEMP_DISPERSION_UNEMP_D1_T": "spf_unemployment_dispersion",
        "SPF_RECESS_MEAN_RECESS2": "spf_recession_probability",
    }
    for series_id, column in spf_map.items():
        output[column] = _asof_series(by_series.get(series_id, []), sessions, name=column)

    # Captured-forward event inputs stay sparse.  A one-off snapshot is visible
    # for audit and overlay decisions but cannot become a backfilled history.
    event_map = {
        "FED_RATE_PATH_ENTROPY": "fed_rate_path_entropy",
        "FED_RATE_EXPECTED_TARGET_MIDPOINT": "fed_rate_expected_target_midpoint",
        "NFP_CONSENSUS": "nfp_consensus",
        "BLS_NFP_ACTUAL": "nfp_actual",
    }
    for series_id, column in event_map.items():
        rows = by_series.get(series_id, [])
        output[column] = _asof_series(rows, sessions, name=column) if rows else np.nan
        output[f"{column}_history_count"] = float(len(rows))

    output = output.replace([np.inf, -np.inf], np.nan)
    metadata = {
        "source_observations": len(facts),
        "source_series": len(by_series),
        "feature_columns": list(output.columns),
        "core_market_start": {
            name: (None if raw[name].first_valid_index() is None else raw[name].first_valid_index().date().isoformat())
            for name in CORE_MARKET_SERIES
        },
        "event_history_counts": {
            column: len(by_series.get(series_id, [])) for series_id, column in event_map.items()
        },
    }
    return base, output, returns, index_values, metadata
