"""V9 preregistered features from the V1 canonical ALFRED store (read-only).

Point-in-time discipline: every feature value placed at session ``s`` derives
only from vintages whose ``available_at`` is at or before ``s``.  The series
enters as its FIRST public print per observation period (a fixed historical
object — first releases never change), aligned to the actual release date and
forward-filled between releases, so one matrix is PIT-valid for every origin.

Declared, not silent: sessions before the earliest collected vintage
(M2SL: 1996-02-09) carry a neutral 0.0 — that prefix ends a decade before the
design window and is disclosed in the contract and in the transform manifest.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from .contracts import (
    TimeSeriesV9ContractError,
    V1_CANONICAL_FACTS_RELATIVE,
)

TRAILING_Z_SESSIONS = 2520


def first_release_observations(root: Path, series_id: str) -> list[tuple[str, str, float]]:
    """(observation_time, available_at, value) of each period's first public print."""
    import pandas as pd

    path = root / V1_CANONICAL_FACTS_RELATIVE
    if not path.is_file():
        raise TimeSeriesV9ContractError(f"V1 canonical facts parquet missing: {path}")
    frame = pd.read_parquet(path, columns=[
        "series_id", "observation_time", "value", "value_status", "available_at",
    ])
    rows = frame[(frame.series_id == series_id) & (frame.value_status == "ok")]
    if not len(rows):
        raise TimeSeriesV9ContractError(f"no canonical observations for {series_id}")
    first = (
        rows.sort_values("available_at")
        .groupby("observation_time", as_index=False)
        .first()
        .sort_values("observation_time")
    )
    return [
        (str(row.observation_time), str(row.available_at), float(row.value))
        for row in first.itertuples(index=False)
    ]


def release_aligned_log_changes(
    releases: list[tuple[str, str, float]],
) -> list[tuple[str, float]]:
    """(release_date, log_change) of consecutive first prints, ordered by release.

    The change for period m uses m's first print against period m−1's first
    print; both are public by m's release date, so each event is PIT at its
    own timestamp.
    """
    events: list[tuple[str, float]] = []
    for prior, current in zip(releases, releases[1:]):
        if prior[2] <= 0 or current[2] <= 0:
            raise TimeSeriesV9ContractError("first-release level must be positive for log change")
        release_day = current[1][:10]
        events.append((release_day, float(np.log(current[2] / prior[2]))))
    events.sort(key=lambda item: item[0])
    return events


def aligned_raw(
    dates: tuple[str, ...], events: list[tuple[str, float]],
) -> tuple[np.ndarray, np.ndarray]:
    """Forward-fill release events onto the session axis (raw, known-mask)."""
    raw = np.zeros(len(dates), dtype=float)
    known = np.zeros(len(dates), dtype=bool)
    cursor, current, have = 0, 0.0, False
    for index, day in enumerate(dates):
        while cursor < len(events) and events[cursor][0] <= day:
            current, have = events[cursor][1], True
            cursor += 1
        raw[index], known[index] = (current, True) if have else (0.0, False)
    return raw, known


def trailing_z(raw: np.ndarray, known: np.ndarray) -> np.ndarray:
    """Trailing z-score over known sessions only; degenerate windows stay 0."""
    z = np.zeros(len(raw), dtype=float)
    for index in range(len(raw)):
        if not known[index]:
            continue  # declared neutral prefix before the first collected vintage
        start = max(0, index + 1 - TRAILING_Z_SESSIONS)
        window = raw[start:index + 1][known[start:index + 1]]
        spread = float(window.std())
        z[index] = 0.0 if spread == 0.0 else float((raw[index] - window.mean()) / spread)
    return z


def feature_column(
    dates: tuple[str, ...], events: list[tuple[str, float]],
) -> tuple[np.ndarray, dict[str, Any]]:
    """Forward-fill release events onto the session axis, then trailing z-score."""
    raw, known = aligned_raw(dates, events)
    z = trailing_z(raw, known)
    manifest = {
        "alignment": "forward_fill_from_release_date",
        "standardization": f"trailing_z_{TRAILING_Z_SESSIONS}_sessions",
        "neutral_prefix_sessions": int((~known).sum()),
        "first_event_release": events[0][0] if events else None,
        "last_event_release": events[-1][0] if events else None,
    }
    return z, manifest


def assert_pit(
    dates: tuple[str, ...], events: list[tuple[str, float]],
) -> int:
    """Return 0 iff no event used at a session postdates that session."""
    violations = 0
    cursor = -1
    for day in dates:
        advanced = cursor
        for index in range(cursor + 1, len(events)):
            if events[index][0] <= day:
                advanced = index
            else:
                break
        cursor = advanced
        if cursor >= 0 and events[cursor][0] > day:
            violations += 1
    return violations


def correlation_rejection(
    candidate: np.ndarray, exog: np.ndarray, exog_names: tuple[str, ...],
    *, limit: float = 0.85,
) -> dict[str, Any]:
    """|ρ| against every existing exogenous column; fail closed above the limit."""
    worst_name, worst_rho = None, 0.0
    spread = float(candidate.std())
    if spread == 0.0:
        raise TimeSeriesV9ContractError("candidate feature is constant — rejected")
    for column in range(exog.shape[1]):
        series = exog[:, column]
        if float(series.std()) == 0.0:
            continue
        rho = float(np.corrcoef(candidate, series)[0, 1])
        if abs(rho) > abs(worst_rho):
            worst_name, worst_rho = exog_names[column], rho
    verdict = {"max_abs_correlation": abs(worst_rho), "against": worst_name,
               "limit": limit, "rejected": abs(worst_rho) > limit}
    if verdict["rejected"]:
        raise TimeSeriesV9ContractError(
            f"feature rejected: |rho|={abs(worst_rho):.3f} vs {worst_name} exceeds {limit}"
        )
    return verdict


def build_first_release_feature(
    root: Path, dates: tuple[str, ...], *, series_id: str, feature_id: str,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Generic registered-feature builder: first prints → log change → trailing z."""
    releases = first_release_observations(root, series_id)
    events = release_aligned_log_changes(releases)
    if assert_pit(dates, events) != 0:
        raise TimeSeriesV9ContractError(f"{series_id} feature failed the PIT assertion")
    column, manifest = feature_column(dates, events)
    manifest["series_id"] = series_id
    manifest["feature_id"] = feature_id
    manifest["release_events"] = len(events)
    return column, manifest


def build_m2sl_feature(
    root: Path, dates: tuple[str, ...],
) -> tuple[np.ndarray, dict[str, Any]]:
    """F1_m2sl_liquidity — 월간 M2 (V9_E1에서 무효익 판정, 기준 기록 유지)."""
    return build_first_release_feature(
        root, dates, series_id="M2SL", feature_id="F1_m2sl_liquidity")


def build_totci_feature(
    root: Path, dates: tuple[str, ...],
) -> tuple[np.ndarray, dict[str, Any]]:
    """F2_totci_credit — 주간 C&I 대출 (H.8, ALFRED vintage 1996-12+)."""
    return build_first_release_feature(
        root, dates, series_id="TOTCI", feature_id="F2_totci_credit")


def build_totll_feature(
    root: Path, dates: tuple[str, ...],
) -> tuple[np.ndarray, dict[str, Any]]:
    """F3_totll_credit — 주간 은행 총여신 (H.8, ALFRED vintage 1996-12+)."""
    return build_first_release_feature(
        root, dates, series_id="TOTLL", feature_id="F3_totll_credit")


def build_wrmfns_feature(
    root: Path, dates: tuple[str, ...],
) -> tuple[np.ndarray, dict[str, Any]]:
    """F4_wrmfns_mmf — 주간 소매 MMF (H.6, ALFRED vintage 2002-10+)."""
    return build_first_release_feature(
        root, dates, series_id="WRMFNS", feature_id="F4_wrmfns_mmf")
