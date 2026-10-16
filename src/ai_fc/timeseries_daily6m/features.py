"""Explicit-vintage inputs for the independent daily six-month research model."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import numpy as np

from ai_fc.timeseries_v2.contracts import frozen_hash as v2_contract_hash, load_contract_v2, require_dfm_runtime
from ai_fc.timeseries_v2.dfm_cache import read_dfm_manifest

from .contracts import canonical_hash

SERIES = ("NASDAQCOM", "VIXCLS", "DGS2", "T10Y2Y", "DTWEXB", "DTWEXBGS")
ENDOG_NAMES = ("nasdaq_return", "vix_change", "dgs2_change_bps", "curve_change_bps", "dollar_change")
EXOG_NAMES = ("growth_factor", "inflation_factor", "dfm_age_since_release")
FX_BRIDGE = "2019-01-02"


class Daily6mFeatureError(ValueError):
    """A required source or temporal input contract failed closed."""


def aware_time(value: str | datetime | None = None) -> datetime:
    current = datetime.now(timezone.utc) if value is None else (datetime.fromisoformat(value) if isinstance(value, str) else value)
    if current.tzinfo is None or current.utcoffset() is None:
        raise Daily6mFeatureError("as_of must include an explicit timezone")
    return current.astimezone(timezone.utc)


@dataclass(frozen=True)
class Daily6mFeatureBundle:
    dates: tuple[str, ...]
    endogenous: np.ndarray
    exogenous: np.ndarray
    endogenous_names: tuple[str, ...]
    exogenous_names: tuple[str, ...]
    anchor: dict[str, Any]
    history: dict[str, list[Any]]
    lineage: dict[str, Any]
    issues: tuple[str, ...]
    freshness: tuple[dict[str, Any], ...]
    origin_age_sessions: int
    issuance_exogenous: np.ndarray | None = None
    issuance_factor_lineage: dict[str, Any] | None = None


def read_native_frame(root: Path, *, as_of: str | datetime) -> pd.DataFrame:
    """Read only registered native ALFRED facts, without materializing all macro rows."""
    import pyarrow.parquet as pq
    path = root / "data/timeseries/facts/observations.parquet"
    if not path.is_file():
        raise Daily6mFeatureError("native ALFRED facts are missing")
    columns = ["source_id", "series_id", "observation_time", "value", "value_status", "available_at", "vintage_start", "vintage_end", "retrieved_at", "source_hash"]
    frame = pq.read_table(path, columns=columns, filters=[("series_id", "in", list(SERIES))]).to_pandas()
    return eligible_frame(frame, as_of=as_of)


def eligible_frame(rows: pd.DataFrame | Iterable[dict[str, Any]], *, as_of: str | datetime) -> pd.DataFrame:
    import pandas as pd
    cutoff = aware_time(as_of)
    frame = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(list(rows))
    required = {"series_id", "observation_time", "value", "available_at", "vintage_start", "retrieved_at", "source_id", "source_hash"}
    if not required.issubset(frame.columns):
        raise Daily6mFeatureError("source rows lack explicit availability/vintage metadata")
    frame = frame[frame["series_id"].isin(SERIES)].copy()
    if (frame["source_id"] != "alfred").any():
        raise Daily6mFeatureError("registered market inputs require native ALFRED source metadata")
    if not frame["source_hash"].map(lambda value: isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None).all():
        raise Daily6mFeatureError("native market source SHA256 is missing or invalid")
    for key in ("available_at", "vintage_start"):
        for value in frame[key].unique():
            aware_time(str(value))
        frame[key + "_utc"] = pd.to_datetime(frame[key], utc=True, errors="raise")
    valid = (frame["available_at_utc"] <= cutoff) & (frame["vintage_start_utc"] <= cutoff)
    if "vintage_end" in frame:
        end = pd.to_datetime(frame["vintage_end"], utc=True, errors="raise")
        valid &= end.isna() | (end > cutoff)
    frame = frame[valid].copy()
    for value in frame["retrieved_at"].unique():
        aware_time(str(value))
    frame["retrieved_at_utc"] = pd.to_datetime(frame["retrieved_at"], utc=True, errors="raise")
    if (frame["retrieved_at_utc"] > cutoff).any():
        raise Daily6mFeatureError("native source was captured after requested issuance; source publication and capture are distinct")
    if "value_status" in frame:
        frame = frame[frame["value_status"].astype(str).isin(["ok", "ValueStatus.OK"])].copy()
    if frame["value"].map(lambda value: isinstance(value, (bool, np.bool_))).any():
        raise Daily6mFeatureError("market levels cannot be boolean")
    values = pd.to_numeric(frame["value"], errors="raise")
    if not np.isfinite(values).all():
        raise Daily6mFeatureError("native market values must be finite")
    positive = frame["series_id"].isin(["NASDAQCOM", "VIXCLS", "DTWEXB", "DTWEXBGS"])
    if (values[positive] <= 0).any():
        raise Daily6mFeatureError("index and volatility levels must be positive")
    frame["value"] = values
    frame["day"] = frame["observation_time"].astype(str).str[:10]
    if (frame["day"] > last_completed_session(cutoff)).any():
        raise Daily6mFeatureError("market observation is after the last completed exchange session")
    return frame.sort_values(["series_id", "day", "vintage_start_utc", "available_at_utc"]).drop_duplicates(["series_id", "day"], keep="last")


def last_completed_session(now: str | datetime) -> str:
    import exchange_calendars as xcals
    import pandas as pd
    current = aware_time(now)
    start = (pd.Timestamp(current.date()) - pd.Timedelta(days=14)).date().isoformat()
    calendar = xcals.get_calendar("XNAS", start=(pd.Timestamp(start) - pd.Timedelta(days=7)).date().isoformat(), end=(pd.Timestamp(current.date()) + pd.Timedelta(days=7)).date().isoformat())
    labels = calendar.sessions_in_range(start, current.date().isoformat())
    complete = [label for label in labels if calendar.session_close(label).to_pydatetime().astimezone(timezone.utc).timestamp() + 900 <= current.timestamp()]
    if not complete:
        raise Daily6mFeatureError("no completed XNAS session before issuance")
    return complete[-1].date().isoformat()


def source_freshness(frame: pd.DataFrame, as_of: str | datetime) -> tuple[dict[str, Any], ...]:
    cutoff = aware_time(as_of)
    reports = []
    for group, alternatives, limit in (("NASDAQCOM", ("NASDAQCOM",), 48), ("VIX", ("VIXCLS",), 48), ("DGS2", ("DGS2",), 48), ("curve", ("T10Y2Y",), 48), ("dollar", ("DTWEXBGS", "DTWEXB"), 216)):
        selected = frame[frame["series_id"].isin(alternatives)]
        if selected.empty:
            reports.append({"group": group, "status": "missing", "limit_hours": limit, "observation_time": None, "age_hours": None})
            continue
        row = selected.sort_values(["day", "available_at_utc"]).iloc[-1]
        observed = datetime.combine(datetime.fromisoformat(str(row["day"])).date(), time(23, 59, 59), tzinfo=timezone.utc)
        age = max(0.0, (cutoff - observed).total_seconds() / 3600)
        reports.append({"group": group, "series_id": str(row["series_id"]), "observation_time": str(row["day"]), "available_at": str(row["available_at"]), "age_hours": round(age, 6), "limit_hours": limit, "status": "fresh" if age <= limit else "stale"})
    return tuple(reports)


def origin_age(origin_session: str, now: str | datetime) -> int:
    import exchange_calendars as xcals
    import pandas as pd
    current = aware_time(now)
    end = current.date().isoformat()
    calendar = xcals.get_calendar("XNAS", start=(pd.Timestamp(origin_session) - pd.Timedelta(days=7)).date().isoformat(), end=(pd.Timestamp(end) + pd.Timedelta(days=7)).date().isoformat())
    labels = calendar.sessions_in_range(origin_session, end)
    return sum(str(label.date()) > origin_session and calendar.session_close(label).to_pydatetime().astimezone(timezone.utc).timestamp() + 900 <= current.timestamp() for label in labels)


def _factor_entries(root: Path) -> list[dict[str, Any]]:
    expected = v2_contract_hash(load_contract_v2(root))
    return sorted((row for row in read_dfm_manifest(root) if row.get("contract_hash") == expected), key=lambda row: (str(row["cutoff"]), str(row.get("manifest_id", ""))))


def _factors(root: Path, days: list[str], *, entries: list[dict[str, Any]] | None = None, as_of: datetime) -> tuple[np.ndarray, list[dict[str, Any]]]:
    entries = _factor_entries(root) if entries is None else sorted(entries, key=lambda row: str(row["cutoff"]))
    output, lineage = [], []
    cursor, current = 0, None
    for day in days:
        session_cutoff = min(datetime.combine(datetime.fromisoformat(day).date(), time(23, 59, 59), tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc), as_of)
        while cursor < len(entries) and aware_time(entries[cursor]["cutoff"]) <= session_cutoff:
            entry = entries[cursor]
            current = None
            if entry.get("status", "ready") == "ready":
                if any(not isinstance(entry.get(key), str) or re.fullmatch(r"[0-9a-f]{64}", entry[key]) is None for key in ("input_hash", "content_hash")):
                    raise Daily6mFeatureError("DFM input/content SHA256 provenance is missing or invalid")
                if "factors" in entry:
                    current = entry
                else:
                    path = root / str(entry["path"])
                    if not path.resolve().is_relative_to((root / "data/timeseries_v2/dfm_cache").resolve()):
                        raise Daily6mFeatureError("DFM cache locator is outside its registered store")
                    value = json.loads(path.read_text(encoding="utf-8"))
                    body = {key: item for key, item in value.items() if key != "content_hash"}
                    if value.get("content_hash") != canonical_hash(body) or value.get("content_hash") != entry.get("content_hash"):
                        raise Daily6mFeatureError("DFM cache content hash mismatch")
                    if aware_time(value["cutoff"]) > session_cutoff:
                        raise Daily6mFeatureError("DFM cache cutoff is later than its feature session")
                    if value.get("input_hash") != entry.get("input_hash") or value.get("data_grade") != "native_pit" or value.get("parameter_estimation") != "origin_specific_native_pit":
                        raise Daily6mFeatureError("DFM native input provenance mismatch")
                    require_dfm_runtime(value.get("runtime"))
                    materialized = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                    if materialized > as_of:
                        raise Daily6mFeatureError("DFM cache was materialized after requested issuance; historical availability is not recorded")
                    value = {**value, "cache_materialized_at": materialized.isoformat(), "cache_availability_basis": "local_artifact_materialization_metadata_not_origin_cutoff"}
                    current = value
            cursor += 1
        if current is None:
            output.append([math.nan] * 3)
            continue
        if not current.get("cache_materialized_at") or aware_time(current["cache_materialized_at"]) > as_of:
            raise Daily6mFeatureError("DFM factor materialization availability is missing or after issuance")
        factors = current["factors"]
        factor_cutoff = aware_time(current["cutoff"])
        output.append([float(factors["growth_factor"]), float(factors["inflation_factor"]), float((session_cutoff - factor_cutoff).days)])
        lineage.append({"session": day, "cache_id": current.get("cache_id"), "cutoff": current["cutoff"], "input_hash": current.get("input_hash"), "content_hash": current.get("content_hash"), "cache_materialized_at": current.get("cache_materialized_at"), "cache_availability_basis": current.get("cache_availability_basis", "explicit_test_factor_fixture"), "carried": factor_cutoff.date().isoformat() != day})
    return np.asarray(output, dtype=float), lineage


def build_bundle(root: Path, *, as_of: str | datetime, rows: Iterable[dict[str, Any]] | pd.DataFrame | None = None, factor_entries: list[dict[str, Any]] | None = None) -> Daily6mFeatureBundle:
    """Construct C1 logical inputs with explicit carries and strict daily price/VIX gaps."""
    import exchange_calendars as xcals
    import pandas as pd
    cutoff = aware_time(as_of)
    frame = read_native_frame(root, as_of=cutoff) if rows is None else eligible_frame(rows, as_of=cutoff)
    freshness = source_freshness(frame, cutoff)
    issues = ["required source " + row["group"] + " " + row["status"] for row in freshness if row["status"] != "fresh"]
    series = {sid: frame[frame["series_id"] == sid].set_index("day") for sid in SERIES}
    if any(series[sid].empty for sid in ("NASDAQCOM", "VIXCLS", "DGS2", "T10Y2Y")) or (series["DTWEXB"].empty and series["DTWEXBGS"].empty):
        raise Daily6mFeatureError("required native market series missing")
    nasdaq = series["NASDAQCOM"]
    end = str(nasdaq.index.max())
    if end != last_completed_session(cutoff):
        issues.append("new forecast anchor is not the latest completed exchange session")
    start = max(str(series[sid].index.min()) for sid in ("NASDAQCOM", "VIXCLS", "DGS2", "T10Y2Y"))
    calendar = xcals.get_calendar("XNAS", start=(pd.Timestamp(start) - pd.Timedelta(days=7)).date().isoformat(), end=(pd.Timestamp(end) + pd.Timedelta(days=7)).date().isoformat())
    days = [label.date().isoformat() for label in calendar.sessions_in_range(start, end)]
    levels, provenance = [], []
    for day in days:
        selected = {}
        for sid in ("NASDAQCOM", "VIXCLS", "DGS2", "T10Y2Y"):
            choices = series[sid].loc[series[sid].index <= day]
            if sid in ("NASDAQCOM", "VIXCLS"):
                if day not in series[sid].index:
                    issues.append("daily gap " + sid + " " + day)
                    selected[sid] = None
                    continue
                selected[sid] = series[sid].loc[day]
            else:
                selected[sid] = choices.iloc[-1] if not choices.empty else None
        fx_sid = "DTWEXBGS" if day >= FX_BRIDGE else "DTWEXB"
        fx = series[fx_sid].loc[series[fx_sid].index <= day]
        selected[fx_sid] = fx.iloc[-1] if not fx.empty else None
        if any(row is None for row in selected.values()):
            levels.append([math.nan] * 5)
            continue
        levels.append([float(selected[sid]["value"]) for sid in ("NASDAQCOM", "VIXCLS", "DGS2", "T10Y2Y")] + [float(selected[fx_sid]["value"])])
        for sid, row in selected.items():
            provenance.append({"session": day, "series_id": sid, "source_id": str(row["source_id"]), "observation_time": str(row["observation_time"]), "available_at": row["available_at_utc"].isoformat(), "vintage_start": row["vintage_start_utc"].isoformat(), "retrieved_at": row["retrieved_at_utc"].isoformat(), "source_hash": str(row["source_hash"]), "carried": str(row.name) != day})
    data = np.asarray(levels, dtype=float)
    changes = np.column_stack((np.diff(np.log(data[:, 0])), np.diff(np.log(data[:, 1])), np.diff(data[:, 2]) * 100, np.diff(data[:, 3]) * 100, np.diff(np.log(data[:, 4])))) if len(data) > 1 else np.empty((0, 5))
    for index, day in enumerate(days[1:]):
        if day >= FX_BRIDGE > days[index]:
            previous = series["DTWEXBGS"].loc[series["DTWEXBGS"].index < day]
            if previous.empty:
                issues.append("FX bridge lacks registered predecessor")
                changes[index, 4] = math.nan
            else:
                changes[index, 4] = math.log(data[index + 1, 4] / float(previous.iloc[-1]["value"]))
                row = previous.iloc[-1]
                provenance.append({"session": day, "series_id": "DTWEXBGS", "role": "registered_fx_bridge_previous_observation", "source_id": str(row["source_id"]), "observation_time": str(row["observation_time"]), "available_at": row["available_at_utc"].isoformat(), "vintage_start": row["vintage_start_utc"].isoformat(), "retrieved_at": row["retrieved_at_utc"].isoformat(), "source_hash": str(row["source_hash"]), "carried": True})
    entries = _factor_entries(root) if factor_entries is None else factor_entries
    exog, factor_lineage = _factors(root, days[1:], entries=entries, as_of=cutoff)
    # Forecast state is independent of historical training rows: a release
    # known at issuance can update the projected factor without rewriting
    # the origin-specific historical feature matrix.
    known_entries = [row for row in entries if aware_time(row["cutoff"]) <= cutoff]
    issue_day = cutoff.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    current_exog, current_lineage = _factors(root, [issue_day], entries=known_entries[-1:], as_of=cutoff)
    if not np.isfinite(current_exog).all():
        issues.append("latest ready DFM state at issuance is unavailable")
    issuance_lineage = {**current_lineage[0], "purpose": "forecast_latest_known_factor_state"} if current_lineage else None
    if issuance_lineage:
        factor_lineage.append(issuance_lineage)
    complete = np.isfinite(changes).all(axis=1) & np.isfinite(exog).all(axis=1)
    first = int(np.flatnonzero(complete)[0]) if complete.any() else len(changes)
    if not complete[first:].all():
        issues.append("internal complete-session feature gap")
    kept_days = days[1:][first:]
    endogenous, exogenous = changes[first:], exog[first:]
    if len(kept_days) < 800:
        issues.append("insufficient complete native sessions: " + str(len(kept_days)) + "/800")
    last = nasdaq.loc[end]
    anchor = {"series_id": "NASDAQCOM", "date": end, "value": float(last["value"]), "available_at": str(last["available_at"])}
    age = origin_age(end, cutoff)
    if age >= 10:
        issues.append("forecast origin age reaches 10 completed sessions")
    history_rows = nasdaq.sort_index().tail(63)
    lineage = {"source": "native_alfred_vintages", "market_rows": provenance, "factor_rows": factor_lineage, "mapping": {"vix_change": "VIXCLS", "curve_change_bps": "T10Y2Y", "dollar_bridge": FX_BRIDGE}, "carry_policy": "price_and_vix_exact_session; yield_curve_fx_known_levels; factors_latest_ready_cutoff", "historical_pit_validation": "not_established", "available_at_max": str(frame["available_at_utc"].max().isoformat()), "retrieved_at_max": str(frame["retrieved_at_utc"].max().isoformat()), "initial_unavailable_sessions": first, "reconstruction_used": False}
    return Daily6mFeatureBundle(tuple(kept_days), endogenous, exogenous, ENDOG_NAMES, EXOG_NAMES, anchor, {"dates": list(history_rows.index), "index": [float(value) for value in history_rows["value"]]}, lineage, tuple(dict.fromkeys(issues)), freshness, age, current_exog[0], issuance_lineage)
