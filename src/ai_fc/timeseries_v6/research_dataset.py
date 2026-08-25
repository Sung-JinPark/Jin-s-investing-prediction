"""PIT feature matrix and direct labels from the immutable V6 public archive."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

import exchange_calendars as xcals
import numpy as np
import pandas as pd
import pyarrow.parquet as pq


class ResearchDatasetError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResearchDataset:
    origins: tuple[str, ...]
    feature_names: tuple[str, ...]
    features: np.ndarray
    labels: dict[int, np.ndarray]
    anchors: np.ndarray
    origin_cutoffs: tuple[str, ...]
    max_input_available_at: tuple[str, ...]
    feature_series_ids: tuple[str, ...]
    feature_data_grades: tuple[str, ...]
    provenance_rate: float
    content_hash: str


def _load_partitions(root: Path, manifest: dict) -> dict[str, pd.DataFrame]:
    output: dict[str, pd.DataFrame] = {}
    for partition in manifest["partitions"]:
        path = root / partition["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != partition["sha256"]:
            raise ResearchDatasetError(f"partition hash mismatch: {partition['series_id']}")
        # Read the exact immutable file, not a Hive-partition dataset inferred
        # from source_id=/series_id= directory names.
        frame = pq.ParquetFile(path).read().to_pandas()
        required = {"observation_version_id", "series_id", "observation_time", "available_at", "value_numeric"}
        if not required <= set(frame):
            raise ResearchDatasetError(f"partition lacks version provenance: {partition['series_id']}")
        frame["observation_time"] = pd.to_datetime(frame["observation_time"], utc=True)
        frame["available_at"] = pd.to_datetime(frame["available_at"], utc=True)
        output[partition["series_id"]] = frame.sort_values(["available_at", "observation_time", "observation_version_id"])
    return output


def _asof_series(frame: pd.DataFrame, cutoffs: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    left = pd.DataFrame({"cutoff": cutoffs.astype("datetime64[ns, UTC]")}).sort_values("cutoff")
    right = frame[["available_at", "value_numeric", "observation_version_id"]].sort_values("available_at")
    right = right.assign(available_at=right["available_at"].astype("datetime64[ns, UTC]"))
    joined = pd.merge_asof(left, right, left_on="cutoff", right_on="available_at", direction="backward", allow_exact_matches=True)
    return joined["value_numeric"].to_numpy(float), joined["available_at"].to_numpy(), joined["observation_version_id"].fillna("").to_numpy(str)


def _changes(values: np.ndarray, lag: int, *, logarithmic: bool = False) -> np.ndarray:
    series = pd.Series(values)
    return (np.log(series.clip(lower=1e-8)).diff(lag) if logarithmic else series.diff(lag)).to_numpy(float)


def build_research_dataset(root: Path, manifest_path: Path) -> ResearchDataset:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    frames = _load_partitions(root, manifest)
    if "NASDAQCOM" not in frames:
        raise ResearchDatasetError("NASDAQCOM target archive is required")
    calendar = xcals.get_calendar("XNAS", start="1995-01-01", end="2027-12-31")
    session_labels = calendar.sessions_in_range("1996-01-01", "2026-08-21")
    sessions = pd.DatetimeIndex(session_labels)
    cutoff_values = [calendar.session_close(label) + pd.Timedelta(minutes=15) for label in session_labels]
    cutoffs = pd.DatetimeIndex(cutoff_values)
    available_values: dict[str, np.ndarray] = {}
    available_times: dict[str, np.ndarray] = {}
    version_values: dict[str, np.ndarray] = {}
    for series_id, frame in frames.items():
        values, times, versions = _asof_series(frame, cutoffs)
        available_values[series_id] = values
        available_times[series_id] = times
        version_values[series_id] = versions
    target_frame = frames["NASDAQCOM"].copy()
    target_frame["session"] = target_frame["observation_time"].dt.strftime("%Y-%m-%d")
    price_map = dict(zip(target_frame["session"], target_frame["value_numeric"], strict=False))
    closes = np.asarray([float(price_map.get(str(label.date()), np.nan)) for label in session_labels])
    if not np.isfinite(closes).all():
        missing = [str(session_labels[index].date()) for index in np.where(~np.isfinite(closes))[0][:20]]
        raise ResearchDatasetError(f"NASDAQCOM is missing completed XNAS sessions; silent forward fill is prohibited: {missing}")
    close_series = closes
    returns = _changes(close_series, 1, logarithmic=True)
    features: dict[str, np.ndarray] = {
        "momentum_1": returns,
        "momentum_5": _changes(close_series, 5, logarithmic=True),
        "momentum_21": _changes(close_series, 21, logarithmic=True),
        "momentum_63": _changes(close_series, 63, logarithmic=True),
    }
    feature_series: dict[str, str] = {name: "NASDAQCOM" for name in features}
    for window in (5, 21, 63):
        features[f"realized_vol_{window}"] = pd.Series(returns).rolling(window).std().to_numpy(float) * math.sqrt(252)
        feature_series[f"realized_vol_{window}"] = "NASDAQCOM"
    features["downside_semivariance_21"] = pd.Series(np.minimum(returns, 0) ** 2).rolling(21).mean().to_numpy(float)
    feature_series["downside_semivariance_21"] = "NASDAQCOM"
    if "VIX" in available_values:
        features["vix_log_level"] = np.log(np.maximum(available_values["VIX"], 1e-8))
        features["vix_log_change_5"] = _changes(available_values["VIX"], 5, logarithmic=True)
        feature_series.update({"vix_log_level": "VIX", "vix_log_change_5": "VIX"})
    for series_id in ("VIX9D", "VIX3M", "VVIX", "SKEW"):
        if series_id in available_values:
            values = np.maximum(available_values[series_id], 1e-8)
            features[f"{series_id.lower()}_log_level"] = np.log(values)
            features[f"{series_id.lower()}_log_change_5"] = _changes(values, 5, logarithmic=True)
            feature_series.update({f"{series_id.lower()}_log_level": series_id, f"{series_id.lower()}_log_change_5": series_id})
    if "VIX" in available_values and "VIX9D" in available_values:
        features["vix9d_vix_log_slope"] = np.log(np.maximum(available_values["VIX9D"], 1e-8) / np.maximum(available_values["VIX"], 1e-8))
        feature_series["vix9d_vix_log_slope"] = "VIX9D"
    if "VIX" in available_values and "VIX3M" in available_values:
        features["vix3m_vix_log_slope"] = np.log(np.maximum(available_values["VIX3M"], 1e-8) / np.maximum(available_values["VIX"], 1e-8))
        feature_series["vix3m_vix_log_slope"] = "VIX3M"
    for series_id in ("DGS2", "T10Y2Y", "NFCI", "DFF"):
        if series_id in available_values:
            features[f"{series_id.lower()}_level"] = available_values[series_id]
            features[f"{series_id.lower()}_change_5"] = _changes(available_values[series_id], 5)
            feature_series.update({f"{series_id.lower()}_level": series_id, f"{series_id.lower()}_change_5": series_id})
    for series_id in ("OFR_FSI", "EBP", "CMDI", "CFTC_NASDAQ_LEV_NET_PCT_OI"):
        if series_id in available_values:
            features[f"{series_id.lower()}_level"] = available_values[series_id]
            features[f"{series_id.lower()}_change_5"] = _changes(available_values[series_id], 5)
            feature_series.update({f"{series_id.lower()}_level": series_id, f"{series_id.lower()}_change_5": series_id})
    if "DTWEXBGS" in available_values:
        features["dollar_log_change_5"] = _changes(available_values["DTWEXBGS"], 5, logarithmic=True)
        features["dollar_log_change_21"] = _changes(available_values["DTWEXBGS"], 21, logarithmic=True)
        feature_series.update({"dollar_log_change_5": "DTWEXBGS", "dollar_log_change_21": "DTWEXBGS"})
    for series_id in ("WALCL", "WTREGEN", "RRPONTSYD", "M2SL", "PAYEMS", "INDPRO", "CPIAUCSL"):
        if series_id in available_values:
            values = available_values[series_id]
            features[f"{series_id.lower()}_log_change_21"] = _changes(values, 21, logarithmic=True)
            feature_series[f"{series_id.lower()}_log_change_21"] = series_id
    if "UNRATE" in available_values:
        features["unrate_level"] = available_values["UNRATE"]
        features["unrate_change_21"] = _changes(available_values["UNRATE"], 21)
        feature_series.update({"unrate_level": "UNRATE", "unrate_change_21": "UNRATE"})
    # Missing archive history is not silently hidden.  Every feature that can
    # be absent receives an explicit, preregistered-style indicator before the
    # training-only median fill in RobustScaler.
    for name, values in tuple(features.items()):
        if np.any(~np.isfinite(values)) and feature_series[name] != "NASDAQCOM":
            indicator_name = f"{name}__missing"
            features[indicator_name] = (~np.isfinite(values)).astype(float)
            feature_series[indicator_name] = feature_series[name]
    feature_names = tuple(features)
    matrix = np.column_stack([features[name] for name in feature_names])
    week_groups = pd.Series(np.arange(len(sessions)), index=sessions).groupby(sessions.to_period("W-FRI")).last().to_numpy(int)
    selected = week_groups[(week_groups >= 63) & (week_groups + 63 < len(sessions))]
    origins = tuple(str(session_labels[index].date()) for index in selected)
    matrix = matrix[selected]
    anchors = close_series[selected]
    labels = {horizon: np.log(close_series[selected + horizon] / close_series[selected]) for horizon in (1, 5, 21, 63)}
    max_times: list[str] = []
    linked = 0; possible = 0
    for index in selected:
        times = []
        for series_id in available_times:
            value = available_times[series_id][index]
            version = version_values[series_id][index]
            if not pd.isna(value):
                possible += 1
                if version:
                    linked += 1; times.append(pd.Timestamp(value))
        max_times.append(max(times).isoformat() if times else "")
    grade_by_series = {partition["series_id"]: partition["data_grade"] for partition in manifest["partitions"]}
    feature_series_ids = tuple(feature_series[name] for name in feature_names)
    feature_data_grades = tuple(grade_by_series[series_id] for series_id in feature_series_ids)
    origin_cutoffs = tuple(pd.Timestamp(cutoffs[index]).isoformat() for index in selected)
    core = {"origins": origins, "origin_cutoffs": origin_cutoffs, "feature_names": feature_names, "feature_series_ids": feature_series_ids, "feature_data_grades": feature_data_grades, "labels": {str(k): hashlib.sha256(v.tobytes()).hexdigest() for k, v in labels.items()}, "matrix_sha256": hashlib.sha256(matrix.tobytes()).hexdigest(), "manifest_hash": manifest["content_hash"]}
    digest = hashlib.sha256(json.dumps(core, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return ResearchDataset(origins, feature_names, matrix, labels, anchors, origin_cutoffs, tuple(max_times), feature_series_ids, feature_data_grades, linked / possible if possible else 0.0, digest)
