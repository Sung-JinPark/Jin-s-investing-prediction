# V15 포크(최소 복사·패치) — 원본 src/ai_fc/timeseries_v2/features.py 를 그대로 복사하고 표시된 지점만 바꿨다.
# 정확한 diff 는 data/timeseries_v15/prereg/fork_patch_v1.json 에 고정돼 있다(테스트 F1).
# 원본은 봉인 커널이라 0바이트 변경. 참고 의견, 매매 신호 아님.
"""V2 candidate feature matrices with explicit availability and data grades."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, time, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import numpy as np

from ai_fc.facts import ObservationFact

from ai_fc.timeseries_v2.contracts import frozen_hash  # V15 패치: 봉인 절대 import
from ai_fc.timeseries_v2.contracts import PARQUET_RELATIVE
from ai_fc.timeseries_v2.dfm_cache import load_factor_states_for_sessions, macro_release_cutoffs, read_dfm_manifest
from ai_fc.timeseries_v2.market_archive import MarketObservationV2, read_market_observations
from ai_fc.timeseries_v15.calendar import CALENDAR_START as _XNAS_CALENDAR_START  # V15 패치
from ai_fc.timeseries_v15.calendar import session_table as _xnas_session_table  # V15 패치
from ai_fc.timeseries_v15.contracts import TimeSeriesV15DataError  # V15 패치


CORE_ENDOGENOUS = (
    "nasdaq_return", "vix_change", "dgs2_change_bps", "curve_change_bps", "dollar_change",
)


@dataclass(frozen=True)
class CandidateFeatureBundle:
    candidate_id: str
    status: str
    dates: tuple[str, ...]
    endogenous: np.ndarray
    endogenous_names: tuple[str, ...]
    exogenous: np.ndarray
    exogenous_names: tuple[str, ...]
    data_grades: tuple[str, ...]
    missing_features: tuple[str, ...]
    dfm_cache_ids: tuple[str, ...]
    transform_manifest: dict[str, str]
    dfm_cache_complete: bool


def export_candidate_parquet(root, bundle: CandidateFeatureBundle) -> dict[str, Any]:
    """Write a derived candidate matrix with explicit columns and dates."""
    import hashlib
    import json
    import os

    pd = _deps()
    frame = pd.DataFrame(
        np.column_stack((bundle.endogenous, bundle.exogenous)),
        index=pd.to_datetime(bundle.dates),
        columns=[*bundle.endogenous_names, *bundle.exogenous_names],
    )
    frame.index.name = "session_date"
    target = root / PARQUET_RELATIVE / f"features_{bundle.candidate_id}.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp.parquet")
    frame.to_parquet(temporary, engine="pyarrow", compression="zstd")
    os.replace(temporary, target)
    manifest = {
        "schema_version": 2, "candidate_id": bundle.candidate_id,
        "path": target.relative_to(root).as_posix(), "rows": len(frame),
        "columns": list(frame.columns), "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "data_grades": list(bundle.data_grades), "status": bundle.status,
    }
    manifest_path = target.with_suffix(".manifest.json")
    temporary_manifest = manifest_path.with_suffix(".tmp")
    temporary_manifest.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary_manifest, manifest_path)
    return manifest


def _deps():
    try:
        import pandas as pd  # type: ignore
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("install ai-fc[timeseries] for V2 feature construction") from exc
    return pd


def _log_change(values):
    return np.log(values.where(values > 0)).diff()


def _latest_market_rows(rows: Iterable[MarketObservationV2]) -> dict[tuple[str, str], MarketObservationV2]:
    latest: dict[tuple[str, str], MarketObservationV2] = {}
    for row in rows:
        key = (row.series_id, row.observation_time)
        if key not in latest or row.revision_seq > latest[key].revision_seq:
            latest[key] = row
    return latest


def _xnas_sessions(start, knowledge_cutoff: str):
    """V15 패치: XNAS 세션(kernel 안 calendar 복사본) [min(1995-01-01, start), cutoff 날짜]."""
    first = min(_XNAS_CALENDAR_START, start.date())
    last = datetime.fromisoformat(knowledge_cutoff).date()
    return [datetime.fromisoformat(row.session) for row in _xnas_session_table(first, last)]


def build_core_market_frame(
    root, *, knowledge_cutoff: str, frame_mode: str = "v8", provenance: dict | None = None,
):
    pd = _deps()
    rows = read_market_observations(root, knowledge_cutoff=knowledge_cutoff)
    latest = _latest_market_rows(rows)
    series: dict[str, Any] = {}
    for series_id in ("NASDAQCOM", "VIX", "DGS2", "DGS10", "DTWEXB", "DTWEXBGS"):
        selected = [row for (sid, _), row in latest.items() if sid == series_id]
        series[series_id] = pd.Series(
            [row.value for row in selected],
            index=pd.to_datetime([row.observation_time for row in selected]),
            dtype=float,
            name=series_id,
        ).sort_index()
    if series["NASDAQCOM"].empty:
        return pd.DataFrame(columns=CORE_ENDOGENOUS), rows
    if frame_mode == "v8":  # 원본 문자 그대로 (A0·A1·A2 경로)
        index = series["NASDAQCOM"].index
        frame = pd.DataFrame(index=index)
        frame["nasdaq_return"] = _log_change(series["NASDAQCOM"]).reindex(index)
        frame["vix_change"] = _log_change(series["VIX"]).reindex(index)
        frame["dgs2_change_bps"] = series["DGS2"].diff().mul(100).reindex(index)
        curve = series["DGS10"] - series["DGS2"]
        frame["curve_change_bps"] = curve.diff().mul(100).reindex(index)
        current = _log_change(series["DTWEXBGS"]).reindex(index)
        predecessor = _log_change(series["DTWEXB"]).reindex(index)
        frame["dollar_change"] = current.combine_first(predecessor)
        return frame.dropna(how="any"), rows
    # V15 패치 (frame_mode): XNAS 세션을 DatetimeIndex 로 정규화한다(date 목록이어도 isin 이 비지 않게).
    sessions = pd.DatetimeIndex(_xnas_sessions(series["NASDAQCOM"].index.min(), knowledge_cutoff))
    if frame_mode == "vix_align":  # A4 (D6): VIX 를 XNAS 세션 행으로 거른 뒤 차분 — 행 집합은 A0 와 동일
        index = series["NASDAQCOM"].index
        frame = pd.DataFrame(index=index)
        frame["nasdaq_return"] = _log_change(series["NASDAQCOM"]).reindex(index)
        vix_x = series["VIX"][series["VIX"].index.isin(sessions)]
        frame["vix_change"] = _log_change(vix_x).reindex(index)
        frame["dgs2_change_bps"] = series["DGS2"].diff().mul(100).reindex(index)
        curve = series["DGS10"] - series["DGS2"]
        frame["curve_change_bps"] = curve.diff().mul(100).reindex(index)
        current = _log_change(series["DTWEXBGS"]).reindex(index)
        predecessor = _log_change(series["DTWEXB"]).reindex(index)
        frame["dollar_change"] = current.combine_first(predecessor)
        return frame.dropna(how="any"), rows
    if frame_mode == "xnas_label":  # A3 (D1·D3) — dropna(how=any) 금지
        nas = series["NASDAQCOM"]
        non_xnas = nas.index[~nas.index.isin(sessions)]
        nas_x = nas[nas.index.isin(sessions)]
        index = nas_x.index
        inner = sessions[(sessions >= index.min()) & (sessions <= index.max())]
        gaps = inner[~inner.isin(index)]
        if len(gaps):
            raise TimeSeriesV15DataError(
                f"NASDAQCOM XNAS gap: {[day.date().isoformat() for day in gaps[:5]]}"
            )

        def asof(values):
            return values.reindex(values.index.union(index)).sort_index().ffill().reindex(index)

        frame = pd.DataFrame(index=index)
        frame["nasdaq_return"] = _log_change(nas_x)
        frame["vix_change"] = _log_change(series["VIX"]).reindex(index)
        frame["dgs2_change_bps"] = asof(series["DGS2"]).diff().mul(100)
        frame["curve_change_bps"] = asof(series["DGS10"] - series["DGS2"]).diff().mul(100)
        current = _log_change(asof(series["DTWEXBGS"]))
        predecessor = _log_change(asof(series["DTWEXB"]))
        frame["dollar_change"] = current.combine_first(predecessor)
        complete_rows = frame.notna().all(axis=1)
        if not complete_rows.any():
            return pd.DataFrame(columns=CORE_ENDOGENOUS), rows
        first_complete = complete_rows.idxmax()
        frame = frame.loc[first_complete:]
        residual_nan = frame.index[frame.isna().any(axis=1)]
        if provenance is not None:
            observed = {name: series[name].index for name in ("DGS2", "DGS10", "DTWEXBGS")}
            carried: dict[str, list[str]] = {}
            for name, observed_index in observed.items():
                for day in frame.index[~frame.index.isin(observed_index)]:
                    carried.setdefault(day.date().isoformat(), []).append(name)
            provenance.update({
                "frame_mode": frame_mode,
                "non_xnas_rows_ignored": [day.date().isoformat() for day in non_xnas],
                "carried_sessions": {day: carried[day] for day in sorted(carried)},
                "dropped_sessions": [
                    [day.date().isoformat(), "vix_or_nasdaq_missing"] for day in residual_nan
                ],
            })
        return frame.drop(index=residual_nan), rows
    if frame_mode == "v8_dollar_tail_asof":  # A5 — 원본과 같되 DTWEXBGS 꼬리만 as-of 캐리
        index = series["NASDAQCOM"].index
        frame = pd.DataFrame(index=index)
        frame["nasdaq_return"] = _log_change(series["NASDAQCOM"]).reindex(index)
        frame["vix_change"] = _log_change(series["VIX"]).reindex(index)
        frame["dgs2_change_bps"] = series["DGS2"].diff().mul(100).reindex(index)
        curve = series["DGS10"] - series["DGS2"]
        frame["curve_change_bps"] = curve.diff().mul(100).reindex(index)
        current = _log_change(series["DTWEXBGS"]).reindex(index)
        last_obs = series["DTWEXBGS"].index.max()
        tail = index > last_obs
        current[tail] = 0.0  # 원점 주 달러 미발표 → 0 변화
        predecessor = _log_change(series["DTWEXB"]).reindex(index)
        frame["dollar_change"] = current.combine_first(predecessor)
        if provenance is not None:
            provenance.update({
                "frame_mode": frame_mode,
                "dollar_last_obs_asof": last_obs.date().isoformat(),
                "dollar_tail_asof": [day.date().isoformat() for day in index[tail]],
            })
        return frame.dropna(how="any"), rows
    raise ValueError(f"unknown frame_mode {frame_mode!r}")


def _session_cutoff(day: str) -> str:
    local = datetime.combine(
        datetime.fromisoformat(day).date(), time(23, 59, 59),
        tzinfo=ZoneInfo("America/New_York"),
    )
    return local.astimezone(timezone.utc).isoformat(timespec="seconds")


def _release_features(
    facts: list[ObservationFact], *, session_cutoffs: list[str], series_ids: tuple[str, ...],
) -> tuple[dict[str, list[float]], list[str]]:
    output: dict[str, list[float]] = {}
    missing: list[str] = []
    for series_id in series_ids:
        events = sorted(
            (row for row in facts if row.series_id == series_id),
            key=lambda row: (row.available_at, row.observation_time),
        )
        event_index = 0
        known: dict[str, ObservationFact] = {}
        levels: list[float] = []
        changes: list[float] = []
        ages: list[float] = []
        for cutoff in session_cutoffs:
            while event_index < len(events) and events[event_index].available_at <= cutoff:
                event = events[event_index]
                known[event.observation_time] = event
                event_index += 1
            ordered_periods = sorted(known)
            latest = known[ordered_periods[-1]] if ordered_periods else None
            prior = known[ordered_periods[-2]] if len(ordered_periods) >= 2 else None
            value = None if latest is None else float(latest.value)
            available = None if latest is None else latest.available_at
            change: float | None = None
            if latest is not None and prior is not None:
                previous = float(prior.value)
                if series_id in {"M2SL"} and value is not None and value > 0 and previous > 0:
                    change = math.log(value / previous)
                elif value is not None:
                    change = value - previous
            levels.append(math.nan if value is None else value)
            changes.append(math.nan if change is None else change)
            if available is None:
                ages.append(math.nan)
            else:
                ages.append(float((datetime.fromisoformat(cutoff) - datetime.fromisoformat(available)).days))
        if all(math.isnan(value) for value in levels):
            missing.append(series_id)
            continue
        if series_id in {"NFCI", "DFF"}:
            output[f"{series_id.lower()}_level"] = levels
            output[f"{series_id.lower()}_change"] = changes
        elif series_id == "M2SL":
            output["m2_log_growth"] = changes
        else:
            output[f"{series_id.lower()}_change"] = changes
        output[f"{series_id.lower()}_age_since_release"] = ages
    return output, missing


def _captured_market_release_features(
    rows: list[MarketObservationV2], *, session_cutoffs: list[str], series_id: str,
) -> tuple[dict[str, list[float]], list[str]]:
    events = sorted(
        (row for row in rows if row.series_id == series_id),
        key=lambda row: (row.available_at, row.observation_time, row.revision_seq),
    )
    if not events:
        return {}, [series_id]
    event_index = 0
    known: dict[str, MarketObservationV2] = {}
    levels: list[float] = []
    changes: list[float] = []
    ages: list[float] = []
    for cutoff in session_cutoffs:
        while event_index < len(events) and events[event_index].available_at <= cutoff:
            event = events[event_index]
            known[event.observation_time] = event
            event_index += 1
        periods = sorted(known)
        latest = known[periods[-1]] if periods else None
        prior = known[periods[-2]] if len(periods) >= 2 else None
        levels.append(math.nan if latest is None else float(latest.value))
        changes.append(
            math.nan if latest is None or prior is None
            else float(latest.value) - float(prior.value)
        )
        ages.append(
            math.nan if latest is None
            else float((datetime.fromisoformat(cutoff) - datetime.fromisoformat(latest.available_at)).days)
        )
    prefix = series_id.lower()
    return {
        f"{prefix}_level": levels,
        f"{prefix}_change": changes,
        f"{prefix}_age_since_release": ages,
    }, []


def assemble_candidate_bundle(
    root, *, contract: dict[str, Any], macro_facts: list[ObservationFact],
    candidate_id: str, knowledge_cutoff: str,
    frame_mode: str = "v8", provenance: dict | None = None,  # V15 패치
) -> CandidateFeatureBundle:
    pd = _deps()
    if candidate_id not in contract["model"]["candidates"]:
        raise ValueError(f"unknown frozen candidate {candidate_id}")
    market, market_rows = build_core_market_frame(
        root, knowledge_cutoff=knowledge_cutoff, frame_mode=frame_mode, provenance=provenance,
    )  # V15 패치
    dates = [item.date().isoformat() for item in market.index]
    cutoffs = [_session_cutoff(day) for day in dates]
    factor_rows = load_factor_states_for_sessions(
        root, session_cutoffs=cutoffs, contract_hash=frozen_hash(contract),
    )
    factor_frame = pd.DataFrame(
        {
            "growth_factor": [row["growth_factor"] for row in factor_rows],
            "inflation_factor": [row["inflation_factor"] for row in factor_rows],
            "dfm_age_since_release": [row["age_since_release_days"] for row in factor_rows],
        },
        index=market.index,
    )
    missing: list[str] = []
    cache_ids = tuple(sorted({str(row["cache_id"]) for row in factor_rows if row["cache_id"]}))
    if factor_frame[["growth_factor", "inflation_factor"]].isna().all().any():
        missing.extend(["growth_factor", "inflation_factor"])
    evaluation_start = str(contract["evaluation"]["outer_start"])
    expected_cutoffs = set(macro_release_cutoffs(
        macro_facts, start=evaluation_start, end=knowledge_cutoff,
    ))
    ready_cutoffs = {
        str(row["cutoff"]) for row in read_dfm_manifest(root)
        if row.get("contract_hash") == frozen_hash(contract) and row.get("status") == "ready"
    }
    ready_before_evaluation = any(cutoff[:10] < evaluation_start for cutoff in ready_cutoffs)
    dfm_cache_complete = (
        bool(expected_cutoffs)
        and ready_before_evaluation
        and expected_cutoffs.issubset(ready_cutoffs)
    )
    if not dfm_cache_complete:
        missing.append("dfm_origin_cache_incomplete")
    optional: dict[str, list[float]] = {}
    if candidate_id == "C2":
        optional, optional_missing = _release_features(
            macro_facts, session_cutoffs=cutoffs, series_ids=("NFCI", "DFF"),
        )
        missing.extend(optional_missing)
    elif candidate_id == "C3":
        optional, optional_missing = _release_features(
            macro_facts, session_cutoffs=cutoffs,
            series_ids=("M2SL", "WALCL", "WTREGEN", "RRPONTSYD"),
        )
        missing.extend(optional_missing)
    elif candidate_id == "C4":
        optional, optional_missing = _captured_market_release_features(
            market_rows, session_cutoffs=cutoffs, series_id="FED_EBP",
        )
        if optional_missing:
            missing.append("FED_EBP_or_CMDI")
    exogenous = factor_frame
    if optional:
        exogenous = exogenous.join(pd.DataFrame(optional, index=market.index))
    # C5 is a post-selection overlay.  It inherits the selected core matrix and
    # cannot be assembled before the development selection is sealed.
    if candidate_id == "C5":
        missing.append("selected_core_not_bound")
    aligned = market.join(exogenous)
    required = ["growth_factor", "inflation_factor"] + [
        column for column in exogenous.columns
        if not column.endswith("_age_since_release") and column != "dfm_age_since_release"
    ][2:]
    start_positions: list[int] = []
    for column in required:
        valid = np.flatnonzero(aligned[column].notna().to_numpy())
        if valid.size:
            start_positions.append(int(valid[0]))
        elif column not in missing:
            missing.append(column)
    start = max(start_positions, default=len(aligned))
    usable = aligned.iloc[start:]
    core_columns = list(CORE_ENDOGENOUS)
    exog_columns = list(exogenous.columns)
    if not usable.empty:
        complete = usable[core_columns + exog_columns].notna().all(axis=1)
        usable = usable.loc[complete]
    if len(usable) < 800:
        missing.append("insufficient_complete_sessions")
    status = "ready" if not missing else "candidate_unavailable"
    used_market_series = {"NASDAQCOM", "VIX", "DGS2", "DGS10", "DTWEXB", "DTWEXBGS"}
    if candidate_id == "C4":
        used_market_series.add("FED_EBP")
    grades = tuple(sorted({
        row.data_grade for row in market_rows if row.series_id in used_market_series
    }))
    manifest = {
        "core": "reconstructed official market archive; daily transforms without filling",
        "growth_factor": "origin-specific DynamicFactorMQ cache, native ALFRED PIT",
        "inflation_factor": "origin-specific DynamicFactorMQ cache, native ALFRED PIT",
    }
    return CandidateFeatureBundle(
        candidate_id=candidate_id,
        status=status,
        dates=tuple(item.date().isoformat() for item in usable.index),
        endogenous=usable[core_columns].to_numpy(dtype=float),
        endogenous_names=CORE_ENDOGENOUS,
        exogenous=usable[exog_columns].to_numpy(dtype=float),
        exogenous_names=tuple(exog_columns),
        data_grades=grades,
        missing_features=tuple(sorted(set(missing))),
        dfm_cache_ids=cache_ids,
        transform_manifest=manifest,
        dfm_cache_complete=dfm_cache_complete,
    )
