"""Verified live-source overlays, isolated from immutable native observations."""

from __future__ import annotations

import math
import re
from numbers import Real
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from .contracts import Daily6mContractError


REGISTERED_SOURCES = {
    "nasdaq_comp_official": ("NASDAQCOM", "NASDAQCOM", "index"),
    "cboe_vix_archive": ("VIX", "VIXCLS", "index"),
    "us_treasury_yield_archive": ("DGS2", "DGS2", "percent"),
}
SOURCE_METADATA = (
    "raw_sha256", "receipt_id", "receipt_raw_path", "receipt_source_uri", "receipt_http_status",
    "receipt_response_uri", "receipt_response_uri_recorded",
    "receipt_verified", "observation_id", "source_unit", "logical_mapping",
    "native_overlap_verified", "native_overlap_count", "native_overlap_max_abs_delta",
    "native_prefix_end", "bridge_origin", "bridge_sessions", "bridge_required_sessions", "bridge_verified",
)


def _stamp(value: Any) -> datetime:
    try:
        stamp = datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise Daily6mContractError("captured tail timestamp is malformed") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise Daily6mContractError("captured tail timestamp must be timezone-aware")
    return stamp


def _sessions(start: str, end: str) -> list[str]:
    import exchange_calendars as xcals
    import pandas as pd
    first, last = datetime.fromisoformat(start).date(), datetime.fromisoformat(end).date()
    if first > last:
        raise Daily6mContractError("captured tail source prefix is after origin")
    cal = xcals.get_calendar("XNAS", start=first - timedelta(days=7), end=last + timedelta(days=7))
    return [day.date().isoformat() for day in cal.sessions_in_range(pd.Timestamp(first), pd.Timestamp(last))
            if day.date().isoformat() > start]


def _treasury_closed(day: str) -> bool:
    from ai_fc.daily6m_sources import treasury_closed_session
    return treasury_closed_session(day)


def _source_uri(source: str, uri: str) -> bool:
    if source == "cboe_vix_archive":
        return uri == "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
    if source == "us_treasury_yield_archive":
        return bool(re.fullmatch(r"https://home\.treasury\.gov/resource-center/data-chart-center/interest-rates/pages/xml\?data=daily_treasury_yield_curve&field_tdr_date_value=20\d{2}", uri))
    return uri == "https://api.nasdaq.com/api/quote/COMP/info?assetclass=index"


def validate_tail_lineage_rows(rows: Iterable[dict[str, Any]], origin: str) -> None:
    """Structural guard shared by the numerical and append/replay boundaries.

    Raw bytes/overlap are independently replayed by the source-store reader;
    the linked proof coordinates travel with every model input row.
    """
    tails = [row for row in rows if row.get("source_id") != "alfred"
             or row.get("data_grade") == "captured_forward"]
    point_counts: dict[str, int] = {}
    treasury: list[dict[str, Any]] = []
    for row in tails:
        source = row.get("source_id")
        registered = REGISTERED_SOURCES.get(source)
        if registered is None:
            raise Daily6mContractError("unregistered captured tail source")
        _, logical, unit = registered
        raw_hash = row.get("raw_sha256")
        if (row.get("series_id") != logical or row.get("data_grade") != "captured_forward"
                or row.get("receipt_verified") is not True or row.get("receipt_http_status") != 200
                or not row.get("receipt_id") or not row.get("receipt_raw_path")
                or not _source_uri(source, str(row.get("receipt_source_uri", "")))
                or row.get("source_unit") != unit
                or not isinstance(raw_hash, str) or re.fullmatch(r"[0-9a-f]{64}", raw_hash) is None
                or row.get("source_hash") != raw_hash
                or _stamp(row.get("available_at")) != _stamp(row.get("retrieved_at"))
                or _stamp(row.get("vintage_start")) != _stamp(row.get("retrieved_at"))):
            raise Daily6mContractError("captured tail source/receipt/unit/actual-capture linkage invalid")
        observed, session = str(row.get("observation_time", ""))[:10], str(row.get("session", ""))[:10]
        if logical in {"NASDAQCOM", "VIXCLS"}:
            if observed != origin or session != origin:
                raise Daily6mContractError("captured price/VIX tail is latest completed origin only")
            if row.get("native_prefix_end") and _sessions(str(row["native_prefix_end"]), origin) != [origin]:
                raise Daily6mContractError("captured price/VIX tail cannot fill an interior session gap")
            point_counts[logical] = point_counts.get(logical, 0) + 1
            if point_counts[logical] > 1:
                raise Daily6mContractError("captured price/VIX tail may contain only one origin session")
        else:
            treasury.append(row)
            prefix = str(row.get("native_prefix_end", ""))
            if not prefix or not prefix < observed <= session <= origin or row.get("bridge_origin") != origin:
                raise Daily6mContractError("captured Treasury tail is outside native-prefix/current-origin bridge")
            sessions = _sessions(prefix, origin)
            required = [day for day in sessions if not _treasury_closed(day)]
            if (not 1 <= len(sessions) <= 5 or row.get("bridge_sessions") != sessions
                    or row.get("bridge_required_sessions") != required or row.get("bridge_verified") is not True
                    or observed not in required
                    or any(not _treasury_closed(day) for day in _sessions(observed, session))):
                raise Daily6mContractError("captured Treasury bridge is incomplete or exceeds five XNAS sessions")
        if logical != "VIXCLS" and (
                row.get("native_overlap_verified") is not True
                or isinstance(row.get("native_overlap_count"), bool)
                or not isinstance(row.get("native_overlap_count"), Real)
                or not math.isfinite(row["native_overlap_count"])
                or int(row["native_overlap_count"]) != row["native_overlap_count"]
                or row["native_overlap_count"] < 5
                or row.get("native_overlap_max_abs_delta") != 0.0):
            raise Daily6mContractError("captured tail lacks exact registered native-source overlap")
    if treasury:
        expected = treasury[0]["bridge_required_sessions"]
        if (any(row["bridge_required_sessions"] != expected for row in treasury)
                or sorted({str(row["observation_time"])[:10] for row in treasury}) != expected):
            raise Daily6mContractError("captured Treasury bridge omits a required source observation")


def select_live_tails(native: Any, observations: list[dict[str, Any]], *,
                      as_of: str | datetime, completed: str) -> list[dict[str, Any]]:
    """Select current point tails and a complete bounded Treasury source bridge."""
    cutoff = _stamp(as_of)
    chosen: list[dict[str, Any]] = []
    for source, (raw_series, logical, unit) in REGISTERED_SOURCES.items():
        rows = native[native["series_id"] == logical]
        if rows.empty:
            # A live tail cannot bootstrap historical model coverage.
            continue
        prefix = str(rows["day"].max())
        if prefix == completed:
            continue  # Eligible native values always win without numerical changes.
        candidates = [row for row in observations if row.get("source_id") == source
                      and row.get("series_id") == raw_series
                      and prefix < str(row.get("observation_time", "")) <= completed]
        if logical in {"NASDAQCOM", "VIXCLS"}:
            candidates = [row for row in candidates if row["observation_time"] == completed]
        if not candidates:
            continue
        if logical in {"NASDAQCOM", "VIXCLS"} and _sessions(prefix, completed) != [completed]:
            raise Daily6mContractError("captured price/VIX tail cannot fill an interior session gap")
        latest: dict[str, dict[str, Any]] = {}
        for row in candidates:
            if row.get("data_grade") != "captured_forward" or row.get("source_unit", row.get("unit")) != unit:
                raise Daily6mContractError("captured source grade/unit differs from registered input")
            if any(_stamp(row.get(key)) > cutoff for key in ("available_at", "vintage_start", "retrieved_at")):
                raise Daily6mContractError("captured source is after current issuance")
            day = str(row["observation_time"])
            if day not in latest or int(row["revision_seq"]) > int(latest[day]["revision_seq"]):
                latest[day] = row
        bridge: dict[str, Any] = {"native_prefix_end": prefix, "bridge_origin": completed}
        if logical == "DGS2":
            sessions = _sessions(prefix, completed)
            required = [day for day in sessions if not _treasury_closed(day)]
            if len(sessions) > 5 or sorted(latest) != required:
                raise Daily6mContractError("captured Treasury bridge missing required quotes or exceeds five XNAS sessions")
            bridge = {"native_prefix_end": prefix, "bridge_origin": completed,
                      "bridge_sessions": sessions, "bridge_required_sessions": required, "bridge_verified": True}
        for day, row in sorted(latest.items()):
            chosen.append({**row, **bridge, "series_id": logical, "value_status": "ok",
                           "source_hash": row["raw_sha256"], "source_unit": unit,
                           "logical_mapping": raw_series + "_to_" + logical})
    validate_tail_lineage_rows([{**row, "session": row["observation_time"]} for row in chosen], completed)
    return chosen


def overlay_live_tails(root: Path, native: Any, *, as_of: str | datetime, completed: str) -> Any:
    """Read only the independent research source store; never change native facts."""
    store = Path(root) / "data/timeseries_daily6m"
    if not any((store / name).exists() for name in ("source_receipts.jsonl", "source_observations.jsonl")):
        return native
    import pandas as pd
    from ai_fc.daily6m_sources import load_verified_source_observations
    observations = load_verified_source_observations(root, as_of=as_of)
    tails = select_live_tails(native, observations, as_of=as_of, completed=completed)
    return pd.concat([native, pd.DataFrame(tails)], ignore_index=True) if tails else native
