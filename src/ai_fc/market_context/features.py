"""Read-only PIT inputs, exchange sessions, and auditable daily innovations."""

from __future__ import annotations

import math
from bisect import bisect_left
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

from . import contracts as C
from .ledger import OBSERVATIONS, SOURCE_STATUS, digest, read_events, read_jsonl, timestamp, validate_raw

SERIES = ("NASDAQCOM", "VIXCLS", "DGS2", "DGS10", "DCOILWTICO", "DTWEXBGS",
          "CPIAUCSL", "CPILFESL", "PAYEMS", "INDPRO")
INNOVATIONS = {
    "VIXCLS": ("vix_innovation", "risk_financial", "index_points"),
    "DGS2": ("treasury_2y_innovation", "policy_rates", "percentage_points"),
    "DGS10": ("treasury_10y_innovation", "policy_rates", "percentage_points"),
    "DCOILWTICO": ("oil_innovation", "energy", "usd_per_barrel"),
    "DTWEXBGS": ("dollar_innovation", "risk_financial", "index_points"),
    "CPIAUCSL": ("cpi_model_innovation", "inflation", "index_points"),
    "CPILFESL": ("core_cpi_model_innovation", "inflation", "index_points"),
    "PAYEMS": ("payroll_model_innovation", "growth", "thousands_persons"),
    "INDPRO": ("industrial_production_innovation", "growth", "index_points"),
}


def read_market_rows(root: Path, *, as_of: str) -> list[dict[str, Any]]:
    """Native facts and separate captures, never relabeling capture as past availability."""
    cutoff = timestamp(as_of, "as_of")
    rows = read_jsonl(root / OBSERVATIONS)
    native_path = root / "data/timeseries/facts/observations.parquet"
    if native_path.is_file():
        try:
            import pyarrow.parquet as pq
            native_rows = pq.read_table(native_path, filters=[("series_id", "in", list(SERIES))]).to_pylist()
        except ImportError as exc:
            raise C.MarketContextError("native fact reader requires existing pyarrow dependency") from exc
        for native in native_rows:
            if native.get("source_id") != "alfred":
                continue
            status = str(native.get("value_status", "ok"))
            if status not in {"ok", "ValueStatus.OK"}:
                continue
            native = {**native, "source_sha256": native.get("source_hash"), "data_grade": "native_vintage",
                      "historical_pit_eligible": True, "native_store": native_path.relative_to(root).as_posix()}
            rows.append(native)
    eligible: dict[tuple[str, str], dict[str, Any]] = {}
    verified_captures: set[tuple[str, str, str, str]] = set()
    for row in rows:
        if row.get("series_id") not in SERIES:
            continue
        available = timestamp(row["available_at"], "available_at")
        acquired = timestamp(row["retrieved_at"], "retrieved_at")
        vintage = timestamp(row.get("vintage_start", row["available_at"]), "vintage_start")
        if available > cutoff or acquired > cutoff or vintage > cutoff:
            continue
        if row.get("data_grade") == "captured_current_vintage":
            signature = tuple(str(row.get(key)) for key in ("source_id", "source_sha256", "raw_path", "retrieved_at"))
            if signature not in verified_captures:
                validate_raw(root, row)
                verified_captures.add(signature)
        if row.get("vintage_end") and timestamp(row["vintage_end"], "vintage_end") <= cutoff:
            continue
        day = str(row["observation_time"])[:10]
        if day > cutoff.date().isoformat():
            continue
        value = row.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise C.MarketContextError("market source contains a non-finite or invalid value")
        if row["series_id"] in {"NASDAQCOM", "VIXCLS", "DTWEXBGS"} and value <= 0:
            raise C.MarketContextError("registered index level must be positive")
        key = (row["series_id"], day)
        item = {**row, "observation_time": day, "value": float(value)}
        prior = eligible.get(key)
        # The most recently published eligible revision wins; acquisition breaks ties.
        rank = (available, vintage, acquired)
        prior_rank = (timestamp(prior["available_at"]), timestamp(prior.get("vintage_start", prior["available_at"])),
                      timestamp(prior["retrieved_at"])) if prior else None
        if prior is None or rank > prior_rank or (rank == prior_rank and row.get("supersedes") == prior.get("observation_id")):
            eligible[key] = item
    return sorted(eligible.values(), key=lambda row: (row["series_id"], row["observation_time"]))


def _calendar(as_of: str, start: str, horizon: int):
    try:
        import exchange_calendars as xcals
    except ImportError as exc:
        raise C.MarketContextError("XNAS session calculations require existing exchange_calendars") from exc
    cutoff = timestamp(as_of)
    end = (cutoff.date() + timedelta(days=max(600, horizon * 2 + 30))).isoformat()
    calendar = xcals.get_calendar("XNAS", start=(datetime.fromisoformat(start).date() - timedelta(days=10)).isoformat(),
                                 end=(datetime.fromisoformat(end).date() + timedelta(days=10)).isoformat())
    labels = calendar.sessions_in_range(start, end)
    days = [label.date().isoformat() for label in labels]
    closes = [calendar.session_close(label).to_pydatetime().astimezone(timezone.utc) for label in labels]
    return calendar, days, closes


def _innovation_events(rows: list[dict[str, Any]], *, as_of: str | None = None) -> list[dict[str, Any]]:
    events = []
    for series, (family, axis, unit) in INNOVATIONS.items():
        values = sorted((row for row in rows if row["series_id"] == series),
                        key=lambda row: (row["observation_time"], row["retrieved_at"]))
        if len(values) < 33:
            continue
        known_times = [max(timestamp(row["available_at"]), timestamp(row["retrieved_at"])) for row in values]
        earliest_knowledge = min(known_times)
        latest_versions = {row["observation_time"]: index for index, row in enumerate(values)}
        latest_period = max(latest_versions)
        for period, index in sorted(latest_versions.items()):
            latest = values[index]
            available = known_times[index]
            # First-batch history cannot produce pre-acquisition expectations.
            if available == earliest_knowledge and period != latest_period:
                continue
            prior_versions: dict[str, tuple[datetime, dict[str, Any]]] = {}
            for candidate, known in zip(values, known_times):
                if candidate["observation_time"] >= period or known >= available:
                    continue
                previous = prior_versions.get(candidate["observation_time"])
                if previous is None or known >= previous[0]:
                    prior_versions[candidate["observation_time"]] = (known, candidate)
            selected = [prior_versions[day] for day in sorted(prior_versions)[-61:]]
            prior = [row for _, row in selected]
            enough = len(prior) >= 32
            expected_available = max((known for known, _ in selected), default=None)
            differences = np.diff([row["value"] for row in prior]) if enough else np.asarray([])
            expectation = float(prior[-1]["value"] + differences.mean()) if enough else None
            scale = float(differences.std(ddof=1)) if enough else None
            eligible = bool(enough and scale is not None and scale > 0)
            if not eligible and period != latest_period:
                continue
            reason = "ready_model_innovation" if eligible else (
                "prior_snapshot_not_captured_before_actual" if not enough else "zero_historical_innovation_scale")
            incident = {"family": family, "period": latest["observation_time"]}
            identity = {**incident, "actual": latest["value"], "source_sha256": latest.get("source_sha256"),
                        "first_acquired_at": latest["retrieved_at"]}
            revision = "mci-r-" + str(latest.get("observation_id") or digest(identity))[:24]
            previous = "mci-r-" + str(latest["supersedes"])[:24] if latest.get("supersedes") else None
            events.append({"event_id": "mci-" + digest(incident)[:24], "revision_id": revision,
                       "supersedes": previous, "family": family, "axis": axis, "kind": "model_innovation", "metric": series,
                       "title": f"{series} {latest['observation_time']} model innovation",
                       "reference_period": latest["observation_time"], "published_at": latest["available_at"],
                       "published_at_basis": "conservative_availability_bound_not_verified_source_publication",
                       "available_at": available.isoformat(), "retrieved_at": latest["retrieved_at"],
                       "source_id": latest["source_id"], "source_url": f"https://fred.stlouisfed.org/series/{series}",
                       "source_sha256": latest.get("source_sha256"), "raw_path": latest.get("raw_path"),
                       "native_store": latest.get("native_store"), "dedupe_key": digest(identity),
                       "actual": latest["value"], "expectation": expectation, "standardization_scale": scale if scale and scale > 0 else None,
                       "unit_metadata": {"actual": unit, "expectation": unit}, "expectation_kind": "model_innovation",
                       "expectation_available_at": expected_available.isoformat() if expected_available else None,
                       "scale_as_of": expected_available.isoformat() if expected_available else None,
                       "scale_sample_count": len(differences), "surprise_z": (latest["value"] - expectation) / scale if eligible else None,
                       "numerical_eligible": eligible, "reason": reason,
                       "data_grade": latest["data_grade"], "historical_pit_eligible": False,
                       "computed_at": as_of or available.isoformat(),
                       "expectation_information_cutoff": expected_available.isoformat() if expected_available else None,
                       "expectation_is_stored_preannouncement_consensus": False,
                       "expectation_method": "prior_60_available_level_differences_mean_and_sample_sd"})
    return events


def load_inputs(root: Path, *, as_of: str) -> dict[str, Any]:
    contract = C.load_contract(root)
    cutoff = timestamp(as_of)
    spec = contract.get("input", {})
    horizon = int(spec.get("horizon_sessions", 252))
    rows = read_market_rows(root, as_of=as_of)
    index_rows = [row for row in rows if row["series_id"] == "NASDAQCOM"]
    start = index_rows[0]["observation_time"] if index_rows else (cutoff.date() - timedelta(days=550)).isoformat()
    calendar, days, close_times = _calendar(as_of, start, horizon)
    import exchange_calendars as xcals
    completed = [day for day, close in zip(days, close_times) if close <= cutoff]
    completed_set = set(completed)
    session_closes = dict(zip(days, close_times))
    index_rows = [row for row in index_rows if row["observation_time"] in completed_set
                  and timestamp(row["retrieved_at"]) >= session_closes[row["observation_time"]]]
    reasons = []
    minimum = int(spec.get("minimum_history_sessions", 253))
    if len(index_rows) < minimum:
        reasons.append(f"insufficient_index_history:{len(index_rows)}<{minimum}")
    anchor_date = index_rows[-1]["observation_time"] if index_rows else None
    anchor = float(index_rows[-1]["value"]) if index_rows else None
    anchor_age = completed.index(completed[-1]) - completed.index(anchor_date) if anchor_date and completed else None
    if anchor_age is None or anchor_age > int(spec.get("market_max_age_sessions", 0)):
        reasons.append("stale_or_missing_index_anchor")
    if anchor_date:
        available_days = {row["observation_time"] for row in index_rows}
        expected = completed[max(0, completed.index(anchor_date) - minimum + 1):completed.index(anchor_date) + 1]
        gaps = [day for day in expected if day not in available_days]
        if gaps:
            reasons.append("index_session_gaps:" + ",".join(gaps[:10]))
    future = [day for day in days if anchor_date and day > anchor_date][:horizon]
    if len(future) != horizon:
        reasons.append("insufficient_future_exchange_sessions")
    events = read_events(root, as_of=as_of)
    persisted_incidents = {event["event_id"] for event in events}
    # Receipt-backed, frozen surprises take precedence over a later re-derivation.
    derived = _innovation_events(rows, as_of=cutoff.isoformat())
    latest_periods: dict[str, str] = {}
    for event in derived:
        latest_periods[event["family"]] = max(latest_periods.get(event["family"], ""), event["reference_period"])
    for event in derived:
        if event["event_id"] in persisted_incidents or event["reference_period"] != latest_periods[event["family"]]:
            continue
        if event.get("data_grade") == "captured_current_vintage" and event["numerical_eligible"]:
            event = {**event, "numerical_eligible": False, "reason": "innovation_not_frozen_at_capture"}
        events.append(event)
    for event in events:
        # A close contains the information only when the source was acquired by that close.
        known = max(timestamp(event["available_at"]), timestamp(event["retrieved_at"]))
        position = bisect_left(close_times, known)
        event["effective_session"] = days[position] if position < len(days) else None
    latest_status: dict[str, dict[str, Any]] = {}
    for status in read_jsonl(root / SOURCE_STATUS):
        if timestamp(status["retrieved_at"]) <= cutoff:
            latest_status[status["source_id"]] = status
    history = {"dates": [row["observation_time"] for row in index_rows], "index": [row["value"] for row in index_rows]}
    lineage = {"as_of": cutoff.isoformat(), "native_store_read_only": True,
               "historical_pit_validation": "not_established", "current_csv_history_is_pit_training": False,
               "calendar": {"requested": "XNAS", "resolved": calendar.name, "session_count": len(days),
                            "library_version": xcals.__version__, "calendar_dates_sha256": digest(days),
                            "completed_dates_sha256": digest(completed), "history_dates_sha256": digest(history["dates"]),
                            "future_dates_sha256": digest(future),
                            "effective_session_rule": "first_exchange_close_at_or_after_available_and_acquired"},
               "anchor_source": index_rows[-1] if index_rows else None,
               "market_row_count": len(rows), "market_rows_sha256": digest(rows),
               "available_at_max": max((timestamp(row["available_at"]) for row in rows), default=None).isoformat() if rows else None,
               "retrieved_at_max": max((timestamp(row["retrieved_at"]) for row in rows), default=None).isoformat() if rows else None,
               "innovation_history_policy": "all_frozen_forward_innovations; new_incident_latest_period_only; historical_revisions_reference_only"}
    return {"as_of": cutoff.isoformat(), "dates": history["dates"], "closes": history["index"],
            "anchor_date": anchor_date, "anchor": anchor, "events": events, "session_dates": completed,
            "future_dates": future, "history": history, "lineage": lineage,
            "gate": {"pass": not reasons, "reasons": reasons}, "market_features": rows,
            "source_statuses": list(latest_status.values()), "anchor_age_sessions": anchor_age}
