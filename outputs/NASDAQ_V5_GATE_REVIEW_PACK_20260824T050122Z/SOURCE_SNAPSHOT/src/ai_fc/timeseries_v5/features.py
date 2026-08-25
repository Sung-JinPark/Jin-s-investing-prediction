"""Leakage-resistant V5 research frame and direct cumulative targets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from ai_fc.timeseries_v3.pipeline import direct_targets_from_returns, load_v3_frame

from .identifiers import content_hash
from .market_calendar import session_records


SAFE_BASE_FEATURES = (
    "trend_21", "trend_63", "trend_126", "drawdown_21", "drawdown_63", "drawdown_252",
    "realized_vol_5", "realized_vol_21", "realized_vol_63", "downside_semivariance_21",
    "vix_level", "vix_change", "vol_of_vol_21", "dgs2_change_bps", "curve_change_bps", "dollar_change",
)

V4_RECONSTRUCTED_SERIES = (
    "VIX9D", "VIX3M", "VVIX", "SKEW", "US_EQ_OFF_EXCHANGE_NOTIONAL_SHARE",
    "US_EQ_TAPE_C_NOTIONAL_SHARE", "US_EQ_TOTAL_NOTIONAL", "US_EQ_TOTAL_TRADES",
)

V5_PUBLIC_FEATURE_SOURCES = {
    "ofr_fsi", "nyfed_cmdi", "treasury_yield_curve", "treasury_real_yield_curve",
    "cftc_tff", "finra_otc", "philadelphia_spf", "cboe_vix", "cboe_vix9d",
    "cboe_vix3m", "cboe_vvix", "cboe_skew", "fed_ebp", "chicago_fed_nfci",
    "fed_h41_walcl", "fred_tga", "nyfed_rrp", "fed_fama_french",
}


def _jump_variation(values: np.ndarray, window: int = 21) -> np.ndarray:
    output = np.full(len(values), np.nan)
    for index in range(window - 1, len(values)):
        sample = values[index - window + 1:index + 1]; realized = float(np.sum(sample**2)); bipower = float(np.pi / 2 * np.sum(np.abs(sample[1:] * sample[:-1])))
        output[index] = max(0.0, realized - bipower)
    return output


def _active_partition(root: Path, source_id: str):
    pd = __import__("pandas")
    path = root / f"outputs/timeseries_v5/private_store/parquet/observations/source_id={source_id}/observations.parquet"
    if not path.is_file(): return pd.DataFrame(columns=["series_id", "available_at", "value", "revision_seq", "observation_key", "dimensions"])
    rows = pd.read_parquet(path)
    if rows.empty: return rows
    return rows.sort_values(["observation_key", "revision_seq"]).drop_duplicates("observation_key", keep="last")


def _align_available(rows, sessions, *, aggregate: str = "last"):
    """Map observations to the first XNAS close at or after available_at."""
    pd = __import__("pandas")
    if rows.empty: return pd.Series(dtype=float), pd.Series(dtype=float)
    closes = np.asarray([pd.Timestamp(row["close_at"]).value for row in sessions], dtype=np.int64)
    dates = [pd.Timestamp(row["session_date"]) for row in sessions]
    selected = rows.copy(); available = pd.to_datetime(selected["available_at"], utc=True)
    # Pandas 3 may retain microsecond dtype here while ``Timestamp.value`` is
    # always nanoseconds.  Convert element-wise so both sides of searchsorted
    # use the same unit and an observation one second after close cannot leak
    # into that completed session.
    available_ns = available.map(lambda value: pd.Timestamp(value).value).to_numpy(dtype=np.int64)
    positions = np.searchsorted(closes, available_ns, side="left")
    valid = positions < len(dates); selected = selected.loc[valid].copy(); positions = positions[valid]
    selected["eligible_session"] = [dates[index] for index in positions]; selected["available_sort"] = available_ns[valid]
    if aggregate == "sum": values = selected.groupby("eligible_session", sort=True)["value"].sum()
    else: values = selected.sort_values(["eligible_session", "available_sort", "revision_seq"]).groupby("eligible_session", sort=True)["value"].last()
    session_index = pd.DatetimeIndex(dates); values = values.reindex(session_index).ffill()
    update_positions = np.where(values.index.isin(selected["eligible_session"].unique()), np.arange(len(values)), np.nan)
    last_update = pd.Series(update_positions, index=values.index).ffill(); age = pd.Series(np.arange(len(values)), index=values.index) - last_update
    return values, age


def _append_v5_public_features(root: Path, frame, sessions) -> tuple[list[str], dict[str, list[str]]]:
    used: list[str] = []; blocks: dict[str, list[str]] = {"core_public": [], "challenger_stress": [], "challenger_positioning": [], "challenger_expectations": [], "challenger_liquidity": [], "challenger_academic": []}

    def add(name: str, values, age, block: str) -> None:
        frame[name] = values.reindex(frame.index)
        frame[f"{name}_age_sessions"] = age.reindex(frame.index)
        used.append(name); blocks[block].extend([name, f"{name}_age_sessions"])

    cboe: dict[str, tuple[Any, Any]] = {}
    for source_id, series_id, name in (
        ("cboe_vix", "VIX", "core_cboe_vix"),
        ("cboe_vix9d", "VIX9D", "core_cboe_vix9d"),
        ("cboe_vix3m", "VIX3M", "core_cboe_vix3m"),
        ("cboe_vvix", "VVIX", "core_cboe_vvix"),
        ("cboe_skew", "SKEW", "core_cboe_skew"),
    ):
        rows = _active_partition(root, source_id)
        values, age = _align_available(rows.loc[rows["series_id"] == series_id], sessions)
        if not values.empty:
            cboe[name] = (values, age)
            transformed = np.log(values.where(values > 0)) if name != "core_cboe_skew" else values
            add(f"{name}_log_level" if name != "core_cboe_skew" else name, transformed, age, "core_public")
    if {"core_cboe_vix9d", "core_cboe_vix3m"} <= set(cboe):
        values = np.log(cboe["core_cboe_vix9d"][0].where(cboe["core_cboe_vix9d"][0] > 0) / cboe["core_cboe_vix3m"][0].where(cboe["core_cboe_vix3m"][0] > 0))
        age = np.maximum(cboe["core_cboe_vix9d"][1], cboe["core_cboe_vix3m"][1])
        add("core_cboe_vix_term_log_slope", values, age, "core_public")

    treasury = _active_partition(root, "treasury_yield_curve")
    treasury_series = {}
    for series_id, name in (("TREASURY_BC_2YEAR", "core_treasury_2y"), ("TREASURY_BC_10YEAR", "core_treasury_10y")):
        values, age = _align_available(treasury.loc[treasury["series_id"] == series_id], sessions)
        if not values.empty: treasury_series[name] = values; add(name, values, age, "core_public")
    if {"core_treasury_2y", "core_treasury_10y"} <= set(treasury_series):
        frame["core_treasury_10y2y"] = treasury_series["core_treasury_10y"] - treasury_series["core_treasury_2y"]
        frame["core_treasury_2y_change_bps"] = treasury_series["core_treasury_2y"].diff() * 100.0
        blocks["core_public"].extend(["core_treasury_10y2y", "core_treasury_2y_change_bps"])

    real = _active_partition(root, "treasury_real_yield_curve")
    values, age = _align_available(real.loc[real["series_id"] == "TREASURY_TC_10YEAR"], sessions)
    if not values.empty: add("core_treasury_real_10y", values, age, "core_public")

    ofr = _active_partition(root, "ofr_fsi")
    for series_id, suffix in (("OFR_FSI", "fsi"), ("VOLATILITY", "volatility"), ("FUNDING", "funding")):
        values, age = _align_available(ofr.loc[ofr["series_id"] == series_id], sessions)
        if not values.empty: add(f"challenger_ofr_{suffix}", values, age, "challenger_stress")

    cmdi = _active_partition(root, "nyfed_cmdi")
    for series_id, suffix in (("SHEET1_MARKET_CMDI", "market"), ("SHEET1_HY_CMDI", "hy")):
        values, age = _align_available(cmdi.loc[cmdi["series_id"] == series_id], sessions)
        if not values.empty: add(f"challenger_cmdi_{suffix}", values, age, "challenger_stress")

    for source_id, series_id, name in (
        ("fed_ebp", "EBP", "challenger_fed_ebp"),
        ("fed_ebp", "GZ_SPREAD", "challenger_fed_gz_spread"),
        ("chicago_fed_nfci", "NFCI", "challenger_nfci"),
    ):
        rows = _active_partition(root, source_id)
        values, age = _align_available(rows.loc[rows["series_id"] == series_id], sessions)
        if not values.empty: add(name, values, age, "challenger_stress")

    cftc = _active_partition(root, "cftc_tff")
    if not cftc.empty:
        cftc = cftc.loc[cftc["dimensions"].map(lambda value: "NASDAQ" in str((value or {}).get("Market_and_Exchange_Names", "")).upper())]
        aligned: dict[str, Any] = {}; aligned_age: dict[str, Any] = {}
        for series_id in ("ASSET_MGR_POSITIONS_LONG_ALL", "ASSET_MGR_POSITIONS_SHORT_ALL", "LEV_MONEY_POSITIONS_LONG_ALL", "LEV_MONEY_POSITIONS_SHORT_ALL", "OPEN_INTEREST_ALL"):
            aligned[series_id], aligned_age[series_id] = _align_available(cftc.loc[cftc["series_id"] == series_id], sessions, aggregate="sum")
        if all(not aligned[name].empty for name in aligned):
            denominator = aligned["OPEN_INTEREST_ALL"].where(aligned["OPEN_INTEREST_ALL"] > 0)
            asset = (aligned["ASSET_MGR_POSITIONS_LONG_ALL"] - aligned["ASSET_MGR_POSITIONS_SHORT_ALL"]) / denominator
            leveraged = (aligned["LEV_MONEY_POSITIONS_LONG_ALL"] - aligned["LEV_MONEY_POSITIONS_SHORT_ALL"]) / denominator
            age = aligned_age["OPEN_INTEREST_ALL"]
            add("challenger_cftc_asset_manager_net", asset, age, "challenger_positioning")
            add("challenger_cftc_leveraged_net", leveraged, age, "challenger_positioning")

    finra = _active_partition(root, "finra_otc")
    if not finra.empty:
        finra = finra.loc[~finra["dimensions"].map(lambda value: any(key in (value or {}) for key in ("initialPublishedDate", "lastUpdateDate")))]
        for series_id, suffix in (("FINRA_OTC_TOTALNOTIONALSUM", "notional"), ("FINRA_OTC_TOTALWEEKLYTRADECOUNT", "trades")):
            values, age = _align_available(finra.loc[finra["series_id"] == series_id], sessions, aggregate="sum")
            if not values.empty:
                transformed = np.log(values.where(values > 0)).diff()
                add(f"challenger_finra_{suffix}_log_change", transformed, age, "challenger_positioning")

    spf = _active_partition(root, "philadelphia_spf")
    for series_id, suffix in (("UNEMP_UNEMP1", "unemployment"), ("CPI_CPI1", "cpi"), ("RGDP_RGDP1", "growth")):
        values, age = _align_available(spf.loc[spf["series_id"] == series_id], sessions)
        if not values.empty: add(f"challenger_spf_{suffix}", values, age, "challenger_expectations")

    for source_id, series_id, name in (
        ("fed_h41_walcl", "WALCL", "challenger_walcl_log_change"),
        ("fred_tga", "WTREGEN", "challenger_tga_log_change"),
        ("nyfed_rrp", "RRPONTSYD", "challenger_rrp_log1p_change"),
    ):
        rows = _active_partition(root, source_id)
        values, age = _align_available(rows.loc[rows["series_id"] == series_id], sessions)
        if not values.empty:
            transformed = np.log1p(values.where(values >= 0)).diff() if series_id == "RRPONTSYD" else np.log(values.where(values > 0)).diff()
            add(name, transformed, age, "challenger_liquidity")

    factors = _active_partition(root, "fed_fama_french")
    for series_id, suffix in (("FF_MKT_RF", "market"), ("FF_SMB", "size"), ("FF_HML", "value")):
        values, age = _align_available(factors.loc[factors["series_id"] == series_id], sessions)
        if not values.empty: add(f"challenger_ff_{suffix}_return", values, age, "challenger_academic")
    return used, blocks


def load_research_frame(root: Path):
    """Build only ex-ante market features from immutable V2/V3 research views.

    V2/V3 are read-only.  Current-vintage macro levels and one-off event values
    are intentionally excluded from the first V5 bundle.
    """
    pd = __import__("pandas")
    base, engineered, returns, index_values = load_v3_frame(root)
    missing = [name for name in SAFE_BASE_FEATURES if name not in engineered.columns]
    if missing: raise ValueError(f"V5 safe feature inputs missing: {missing}")
    frame = engineered.loc[:, list(SAFE_BASE_FEATURES)].copy()
    frame["core_growth_factor"] = base["growth_factor"]
    frame["core_inflation_factor"] = base["inflation_factor"]
    frame["core_dfm_age_sessions"] = base["dfm_age_since_release"]
    frame["core_dfm_available"] = (base[["growth_factor", "inflation_factor"]].notna().all(axis=1)).astype(float)
    frame["momentum_5d"] = base["nasdaq_return"].rolling(5).sum()
    frame["momentum_21d"] = base["nasdaq_return"].rolling(21).sum()
    frame["momentum_63d"] = base["nasdaq_return"].rolling(63).sum()
    frame["realized_volatility_21d"] = frame["realized_vol_21"]
    frame["realized_volatility_63d"] = frame["realized_vol_63"]
    frame["downside_semivariance_21d"] = frame["downside_semivariance_21"]
    frame["jump_variation_21d"] = _jump_variation(np.asarray(returns, dtype=float), 21)
    frame["term_spread_change_5d"] = frame["curve_change_bps"].rolling(5).sum()
    frame["dollar_change_5d"] = frame["dollar_change"].rolling(5).sum()
    frame["vix_inversion"] = (frame["vix_change"].rolling(5).sum() > 0).astype(float)
    v4_path = root / "data/timeseries_v4/parquet/observations.parquet"
    reconstructed_used: list[str] = []
    if v4_path.is_file():
        archive = pd.read_parquet(v4_path)
        archive = archive.loc[archive["series_id"].isin(V4_RECONSTRUCTED_SERIES)].sort_values(["series_id", "observation_time", "revision_seq"]).drop_duplicates(["series_id", "observation_time"], keep="last")
        if not archive.empty:
            archive["observation_time"] = pd.to_datetime(archive["observation_time"])
            wide = archive.pivot(index="observation_time", columns="series_id", values="value").reindex(frame.index).ffill(limit=5)
            for series in V4_RECONSTRUCTED_SERIES:
                if series in wide:
                    reconstructed_used.append(series)
            if "VIX9D" in wide and "VIX3M" in wide:
                frame["vix_term_log_slope"] = np.log(wide["VIX9D"].where(wide["VIX9D"] > 0) / wide["VIX3M"].where(wide["VIX3M"] > 0))
            if "VVIX" in wide: frame["vvix_log_level"] = np.log(wide["VVIX"].where(wide["VVIX"] > 0))
            if "SKEW" in wide: frame["skew_level"] = wide["SKEW"]
            if "US_EQ_OFF_EXCHANGE_NOTIONAL_SHARE" in wide: frame["off_exchange_share"] = wide["US_EQ_OFF_EXCHANGE_NOTIONAL_SHARE"]
            if "US_EQ_TAPE_C_NOTIONAL_SHARE" in wide: frame["tape_c_share"] = wide["US_EQ_TAPE_C_NOTIONAL_SHARE"]
            if "US_EQ_TOTAL_NOTIONAL" in wide: frame["market_notional_log_change"] = np.log(wide["US_EQ_TOTAL_NOTIONAL"].where(wide["US_EQ_TOTAL_NOTIONAL"] > 0)).diff()
            if "US_EQ_TOTAL_TRADES" in wide: frame["market_trade_log_change"] = np.log(wide["US_EQ_TOTAL_TRADES"].where(wide["US_EQ_TOTAL_TRADES"] > 0)).diff()
    sessions = session_records(frame.index[0].date().isoformat(), frame.index[-1].date().isoformat())
    v5_used, feature_blocks = _append_v5_public_features(root, frame, sessions)
    feature_blocks["core_public"] = [
        "core_growth_factor", "core_inflation_factor", "core_dfm_age_sessions", "core_dfm_available",
        *feature_blocks["core_public"],
    ]
    frame = frame.replace([np.inf, -np.inf], np.nan)
    original_columns = list(frame.columns)
    for name in original_columns:
        if frame[name].isna().any(): frame[f"{name}__missing"] = frame[name].isna().astype(float)
    targets = direct_targets_from_returns(np.asarray(returns, dtype=float))
    parquet_manifest = root / "data/timeseries_v5/manifests/parquet_latest.json"
    metadata = {"data_grade": "reconstructed_market_archive", "evaluation_label": "research_pseudo_oos", "macro_current_vintage_used": False, "event_backfill_used": False, "v4_reconstructed_challenger_series": reconstructed_used, "v5_public_sources_used": v5_used, "feature_blocks": feature_blocks, "missing_indicators": [name for name in frame.columns if name.endswith("__missing")], "feature_names": list(frame.columns), "input_hash": content_hash({"dates": [item.date().isoformat() for item in frame.index], "columns": list(frame.columns), "shape": frame.shape, "parquet_manifest": json.loads(parquet_manifest.read_text(encoding="utf-8")).get("content_hash") if parquet_manifest.is_file() else None})}
    return base, frame, targets, np.asarray(index_values, dtype=float), metadata


def feature_snapshot(frame, *, origin_index: int, lookback: int = 2520) -> dict[str, Any]:
    history = frame.iloc[max(0, origin_index - lookback):origin_index]
    current = frame.iloc[origin_index]; medians = history.median(skipna=True); q1 = history.quantile(0.25); q3 = history.quantile(0.75); scale = (q3 - q1).replace(0, 1.0)
    values = {name: (None if not np.isfinite(float(current[name])) else float(current[name])) for name in frame.columns}
    standardized = {name: (None if values[name] is None or not np.isfinite(float(medians[name])) else float((values[name] - medians[name]) / scale[name])) for name in frame.columns}
    core = {"origin": frame.index[origin_index].date().isoformat(), "values": values, "standardized": standardized, "training_start": None if history.empty else history.index[0].date().isoformat(), "training_end": None if history.empty else history.index[-1].date().isoformat()}
    return {**core, "snapshot_id": f"feature-{content_hash(core)[:24]}", "content_hash": content_hash(core)}
