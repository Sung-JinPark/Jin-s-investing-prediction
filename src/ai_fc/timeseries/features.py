"""Point-in-time feature construction for the NASDAQ time-series shadow model."""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass
from datetime import datetime, time, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import numpy as np

from ai_fc.facts import ObservationFact, as_of_rows


DAILY_ENDOGENOUS = (
    "nasdaq_return",
    "vix_change",
    "dgs2_change_bps",
    "curve_change_bps",
    "hy_oas_change_bps",
    "dollar_change",
)


@dataclass(frozen=True)
class FeatureBundle:
    dates: tuple[str, ...]
    endogenous: np.ndarray
    endogenous_names: tuple[str, ...]
    exogenous: np.ndarray
    exogenous_names: tuple[str, ...]
    source_available_at: dict[str, str]
    missing_required: tuple[str, ...]
    transform_manifest: dict[str, str]


def _deps():
    try:
        import pandas as pd  # type: ignore
        from statsmodels.tsa.statespace.dynamic_factor_mq import DynamicFactorMQ  # type: ignore
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("install ai-fc[timeseries] for time-series fitting") from exc
    return pd, DynamicFactorMQ


def _series_as_of(
    facts: Iterable[ObservationFact], series_id: str, knowledge_cutoff: str,
):
    pd, _ = _deps()
    rows = as_of_rows(facts, series_id=series_id, as_of=knowledge_cutoff)
    if not rows:
        return pd.Series(dtype=float), []
    values = pd.Series(
        [float(row.value) for row in rows],
        index=pd.to_datetime([row.observation_time[:10] for row in rows]),
        name=series_id,
        dtype=float,
    )
    return values[~values.index.duplicated(keep="last")].sort_index(), rows


def _log_change(values):
    safe = values.where(values > 0)
    return np.log(safe).diff()


def build_daily_market_frame(
    facts: Iterable[ObservationFact], *, knowledge_cutoff: str,
):
    """Create the six-dimensional daily endogenous vector from PIT rows only."""
    pd, _ = _deps()
    facts = list(facts)
    raw: dict[str, Any] = {}
    row_map: dict[str, list[ObservationFact]] = {}
    required = ("NASDAQCOM", "VIXCLS", "DGS2", "T10Y2Y", "BAMLH0A0HYM2", "DTWEXBGS")
    requested = (*required, "DTWEXB")
    for series_id in requested:
        raw[series_id], row_map[series_id] = _series_as_of(facts, series_id, knowledge_cutoff)
    if raw["NASDAQCOM"].empty:
        return pd.DataFrame(columns=DAILY_ENDOGENOUS), row_map
    frame = pd.DataFrame(index=raw["NASDAQCOM"].index)
    frame["nasdaq_return"] = _log_change(raw["NASDAQCOM"]).reindex(frame.index)
    frame["vix_change"] = _log_change(raw["VIXCLS"]).reindex(frame.index)
    frame["dgs2_change_bps"] = raw["DGS2"].diff().mul(100).reindex(frame.index)
    frame["curve_change_bps"] = raw["T10Y2Y"].diff().mul(100).reindex(frame.index)
    frame["hy_oas_change_bps"] = raw["BAMLH0A0HYM2"].diff().mul(100).reindex(frame.index)
    current_dollar = _log_change(raw["DTWEXBGS"]).reindex(frame.index)
    predecessor_dollar = _log_change(raw["DTWEXB"]).reindex(frame.index)
    overlap = int((current_dollar.notna() & predecessor_dollar.notna()).sum())
    if not raw["DTWEXB"].empty and overlap < 252:
        raise RuntimeError("registered DTWEXB/DTWEXBGS bridge lacks 252 overlap sessions")
    frame["dollar_change"] = current_dollar.combine_first(predecessor_dollar)
    # Market observations are never filled across missing source dates. A session is
    # usable only when every endogenous coordinate is actually observed.
    return frame.dropna(how="any"), row_map


def _macro_transform(series_id: str, values):
    if series_id in {"PAYEMS", "INDPRO", "RSAFS", "HOUST", "M2SL", "GDPC1"}:
        return _log_change(values)
    if series_id in {"CPIAUCSL", "CPILFESL", "PCEPI", "PCEPILFE"}:
        return _log_change(values)
    return values.astype(float)


def _monthly_panel(
    facts: list[ObservationFact], series_ids: tuple[str, ...], knowledge_cutoff: str,
):
    pd, _ = _deps()
    columns: dict[str, Any] = {}
    rows_by_series: dict[str, list[ObservationFact]] = {}
    for series_id in series_ids:
        values, rows = _series_as_of(facts, series_id, knowledge_cutoff)
        rows_by_series[series_id] = rows
        if values.empty:
            continue
        transformed = _macro_transform(series_id, values)
        transformed.index = transformed.index.to_period("M")
        columns[series_id] = transformed.groupby(level=0).last()
    if not columns:
        return pd.DataFrame(), rows_by_series
    panel = pd.concat(columns, axis=1).sort_index()
    return panel, rows_by_series


def fit_dynamic_factor_state(
    facts: Iterable[ObservationFact], *, knowledge_cutoff: str,
) -> dict[str, Any]:
    """Fit preregistered one-factor growth and inflation DynamicFactorMQ states.

    Each call sees one ALFRED vintage only. Backtests must call this function again
    at every outer origin; a factor fitted at a later origin is never backfilled.
    """
    pd, DynamicFactorMQ = _deps()
    facts = list(facts)
    groups = {
        "growth_factor": ("PAYEMS", "UNRATE", "INDPRO", "RSAFS", "HOUST", "GDPC1"),
        "inflation_factor": ("CPIAUCSL", "CPILFESL", "PCEPI", "PCEPILFE"),
    }
    output: dict[str, Any] = {
        "knowledge_cutoff": knowledge_cutoff,
        "states": {},
        "available_at": {},
        "missing": [],
        "converged": {},
        "fit_warnings": {},
    }
    output["history"] = {}
    for factor_name, series_ids in groups.items():
        panel, rows = _monthly_panel(facts, series_ids, knowledge_cutoff)
        missing = [series_id for series_id in series_ids if not rows.get(series_id)]
        if missing:
            output["missing"].extend(missing)
        usable = panel.dropna(axis=1, how="all")
        if usable.shape[1] < 2 or usable.dropna(how="all").shape[0] < 36:
            output["states"][factor_name] = None
            output["converged"][factor_name] = False
            continue
        usable = usable.replace([np.inf, -np.inf], np.nan)
        # DynamicFactorMQ retains the ragged edge; only columns that are entirely
        # absent are removed. Standardization is internal to the training vintage.
        quarterly = None
        if factor_name == "growth_factor" and "GDPC1" in usable:
            quarterly = usable[["GDPC1"]].copy()
            quarterly.index = quarterly.index.asfreq("Q")
            quarterly = quarterly.groupby(level=0).last().dropna(how="all")
            usable = usable.drop(columns=["GDPC1"])
        model = DynamicFactorMQ(
            usable,
            endog_quarterly=quarterly,
            factors=1,
            factor_orders=1,
            idiosyncratic_ar1=True,
            standardize=True,
        )
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = model.fit_em(maxiter=300, tolerance=1e-6, disp=False)
        factor = result.factors.filtered.iloc[:, 0].dropna()
        output["states"][factor_name] = None if factor.empty else float(factor.iloc[-1])
        first_release_by_coordinate: dict[tuple[str, str], str] = {}
        cutoff = datetime.fromisoformat(knowledge_cutoff)
        for row in facts:
            if row.series_id not in series_ids or datetime.fromisoformat(row.available_at) > cutoff:
                continue
            period = str(pd.Period(row.observation_time[:7], freq="M"))
            coordinate = (row.series_id, period)
            prior = first_release_by_coordinate.get(coordinate)
            if prior is None or row.available_at < prior:
                first_release_by_coordinate[coordinate] = row.available_at
        release_by_period: dict[str, str] = {}
        for (_, period), available_at in first_release_by_coordinate.items():
            prior = release_by_period.get(period)
            if prior is None or available_at > prior:
                release_by_period[period] = available_at
        output["history"][factor_name] = [
            {
                "period": str(period),
                "available_at": release_by_period[str(period)],
                "value": float(value),
            }
            for period, value in factor.items()
            if str(period) in release_by_period
        ]
        warning_text = [str(item.message) for item in caught]
        convergence_failures = [
            message for message in warning_text
            if "without achieving convergence" in message or "Log-likelihood decreased" in message
        ]
        output["converged"][factor_name] = not convergence_failures
        output["fit_warnings"][factor_name] = warning_text
        latest_availability = max(
            datetime.fromisoformat(row.available_at)
            for series_id in series_ids for row in rows.get(series_id, [])
        )
        output["available_at"][factor_name] = latest_availability.astimezone(timezone.utc).isoformat()
    output["missing"] = sorted(set(output["missing"]))
    return output


def build_realtime_factor_history(
    facts: Iterable[ObservationFact], *, knowledge_cutoff: str,
) -> dict[str, Any]:
    """Build a release-aligned filtered history from one training-cutoff DFM fit.

    This is suitable for the current shadow fit. An offline publication backtest
    still requires origin-specific parameter re-estimation and therefore keeps a
    separate HOLD gate until that expensive evaluation is complete.
    """
    facts = list(facts)
    try:
        fitted = fit_dynamic_factor_state(facts, knowledge_cutoff=knowledge_cutoff)
    except (RuntimeError, ValueError, np.linalg.LinAlgError) as exc:
        return {
            "knowledge_cutoff": knowledge_cutoff,
            "parameter_estimation_mode": "single_training_cutoff_filtered_history",
            "origin_specific_parameter_pit": False,
            "states": [],
            "failures": [{"available_at": knowledge_cutoff, "reason": str(exc)}],
            "fit_count": 0,
            "release_count": 0,
        }
    events: dict[str, dict[str, float]] = {}
    for factor_name in ("growth_factor", "inflation_factor"):
        for row in fitted["history"].get(factor_name, []):
            events.setdefault(str(row["available_at"]), {})[factor_name] = float(row["value"])
    states: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    if not all(fitted["converged"].get(name, False)
               for name in ("growth_factor", "inflation_factor")):
        failures.append({
            "available_at": knowledge_cutoff,
            "reason": "DynamicFactorMQ convergence gate failed",
        })
    current: dict[str, float] = {}
    for release_time in sorted(events):
        current.update(events[release_time])
        growth = current.get("growth_factor")
        inflation = current.get("inflation_factor")
        if growth is None or inflation is None:
            continue
        states.append({
            "available_at": release_time,
            "growth_factor": float(growth),
            "inflation_factor": float(inflation),
        })
    return {
        "knowledge_cutoff": knowledge_cutoff,
        "parameter_estimation_mode": "single_training_cutoff_filtered_history",
        "origin_specific_parameter_pit": False,
        "states": states,
        "failures": failures,
        "fit_count": int(not failures),
        "release_count": len(events),
    }


def _session_close_utc(day: datetime) -> datetime:
    local = datetime.combine(day.date(), time(16, 0), tzinfo=ZoneInfo("America/New_York"))
    return local.astimezone(timezone.utc)


def build_release_state_history(
    facts: Iterable[ObservationFact], *, session_dates: Iterable[str], knowledge_cutoff: str,
):
    """Build release-age variables without backdating economic observations.

    Macro levels enter only from ``available_at`` onward. The expensive DynamicFactorMQ
    refits are intentionally performed by the rolling-origin pipeline and cached as run
    artifacts; this history exposes reproducible release states and ages to VARX.
    """
    pd, _ = _deps()
    cutoff = datetime.fromisoformat(knowledge_cutoff)
    dates = pd.to_datetime(list(session_dates))
    session_closes = [_session_close_utc(day.to_pydatetime()) for day in dates]
    frame = pd.DataFrame(index=dates)
    manifest: dict[str, str] = {}
    macro_series = ("NFCI", "M2SL", "WALCL", "WTREGEN", "RRPONTSYD", "DFF")
    for series_id in macro_series:
        eligible = sorted(
            (
                datetime.fromisoformat(fact.available_at),
                fact.observation_time,
                float(fact.value),
            )
            for fact in facts
            if fact.series_id == series_id
            and fact.value is not None
            and datetime.fromisoformat(fact.available_at) <= cutoff
        )
        by_release: dict[datetime, tuple[str, float]] = {}
        for release_time, observation_time, value in eligible:
            prior = by_release.get(release_time)
            if prior is None or observation_time >= prior[0]:
                by_release[release_time] = (observation_time, value)
        releases = [(release_time.astimezone(timezone.utc), item[1]) for release_time, item in sorted(by_release.items())]
        if not releases:
            continue
        pointer = 0
        current_value = math.nan
        current_release: datetime | None = None
        state_values: list[float] = []
        state_releases: list[datetime | None] = []
        for session_close in session_closes:
            while pointer < len(releases) and releases[pointer][0] <= session_close:
                current_release, current_value = releases[pointer]
                pointer += 1
            state_values.append(current_value)
            state_releases.append(current_release)
        state = pd.Series(state_values, index=dates, dtype=float)
        age = [
            math.nan if release is None else float((close - release).total_seconds() / 86_400.0)
            for close, release in zip(session_closes, state_releases, strict=True)
        ]
        if series_id in {"PAYEMS", "INDPRO", "RSAFS", "HOUST", "M2SL"}:
            state = _log_change(state)
            manifest[series_id] = "release_state_log_change"
        elif series_id in {"CPIAUCSL", "CPILFESL", "PCEPI", "PCEPILFE"}:
            frame[f"{series_id}_yoy"] = _log_change(state).rolling(12).sum()
            frame[f"{series_id}_3m_ann"] = _log_change(state).rolling(3).sum().mul(4)
            frame[f"{series_id}_age_days"] = age
            manifest[series_id] = "release_state_yoy_and_3m_annualized_log_change"
            continue
        elif series_id in {"UNRATE", "NFCI"}:
            frame[f"{series_id}_level"] = state
            frame[f"{series_id}_change"] = state.diff()
            frame[f"{series_id}_age_days"] = age
            manifest[series_id] = "release_state_level_and_first_difference"
            continue
        else:
            state = state.diff()
            manifest[series_id] = "release_state_first_difference"
        frame[series_id] = state
        frame[f"{series_id}_age_days"] = age
    return frame, manifest


def assemble_feature_bundle(
    facts: Iterable[ObservationFact], *, knowledge_cutoff: str,
    factor_history: dict[str, Any] | None = None,
) -> FeatureBundle:
    facts = list(facts)
    daily, row_map = build_daily_market_frame(facts, knowledge_cutoff=knowledge_cutoff)
    required = set(("NASDAQCOM", "VIXCLS", "DGS2", "T10Y2Y", "BAMLH0A0HYM2", "DTWEXBGS"))
    missing = sorted(series for series in required if not row_map.get(series))
    if daily.empty:
        return FeatureBundle((), np.empty((0, 6)), DAILY_ENDOGENOUS, np.empty((0, 0)), (), {}, tuple(missing), {})
    exogenous, transform_manifest = build_release_state_history(
        facts,
        session_dates=[item.date().isoformat() for item in daily.index],
        knowledge_cutoff=knowledge_cutoff,
    )
    if factor_history:
        pd, _ = _deps()
        states = factor_history.get("states") or []
        if states:
            ordered = sorted(states, key=lambda row: row["available_at"])
            pointer = 0
            current: dict[str, Any] | None = None
            aligned_states: list[dict[str, float]] = []
            for session_day in exogenous.index:
                close = _session_close_utc(session_day.to_pydatetime())
                while pointer < len(ordered) and datetime.fromisoformat(ordered[pointer]["available_at"]) <= close:
                    current = ordered[pointer]
                    pointer += 1
                aligned_states.append({
                    "growth_factor": math.nan if current is None else float(current["growth_factor"]),
                    "inflation_factor": math.nan if current is None else float(current["inflation_factor"]),
                })
            state_frame = pd.DataFrame(aligned_states, index=exogenous.index)
            exogenous = exogenous.join(state_frame, how="left")
            transform_manifest["growth_factor"] = "DynamicFactorMQ filtered state available at release time"
            transform_manifest["inflation_factor"] = "DynamicFactorMQ filtered state available at release time"
    aligned = daily.join(exogenous, how="left")
    # Optional macro features may be missing, but a feature is never silently dropped:
    # its absence is recorded. Fully observed registered columns are admitted.
    complete_from: dict[str, int] = {}
    for column in exogenous.columns:
        valid = np.flatnonzero(aligned[column].notna().to_numpy())
        if valid.size:
            complete_from[column] = int(valid[0])
        else:
            missing.append(f"feature:{column}")
    exog_names = tuple(sorted(complete_from))
    start = max(complete_from.values(), default=0)
    if exog_names:
        usable_mask = aligned.loc[:, exog_names].iloc[start:].notna().all(axis=1)
        if not usable_mask.all():
            first_bad = usable_mask.index[~usable_mask][0]
            raise RuntimeError(f"registered feature has an interior missing value at {first_bad}")
    daily = daily.iloc[start:]
    aligned = aligned.iloc[start:]
    source_available_at = {
        series_id: max(row.available_at for row in rows)
        for series_id, rows in row_map.items() if rows
    }
    return FeatureBundle(
        dates=tuple(item.date().isoformat() for item in daily.index),
        endogenous=daily.to_numpy(dtype=float),
        endogenous_names=DAILY_ENDOGENOUS,
        exogenous=(aligned.loc[:, exog_names].to_numpy(dtype=float)
                   if exog_names else np.empty((len(aligned), 0))),
        exogenous_names=exog_names,
        source_available_at=source_available_at,
        missing_required=tuple(sorted(set(missing))),
        transform_manifest=transform_manifest,
    )
