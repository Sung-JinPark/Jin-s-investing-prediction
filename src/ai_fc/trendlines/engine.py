"""Deterministic, confirmed-pivot OHLC geometry with auditable issuance times.

This module performs no I/O or collection. Source approval and atomic bars are
required before numbers are produced. Two anchors form a candidate, not a
forecast; a third confirmed pivot is only a geometric contact.
"""

from __future__ import annotations

import math
from copy import deepcopy
from datetime import date, timedelta
from functools import lru_cache
from typing import Any

from . import contracts as C


def _finish(body: dict[str, Any]) -> dict[str, Any]:
    body["snapshot_id"] = "trendlines-" + body["asset_id"] + "-" + C.canonical_hash(body)[:24]
    body["content_hash"] = C.canonical_hash(body)
    return body


def _empty_analysis(reasons: list[str], spec: dict[str, Any], axis: str) -> dict[str, Any]:
    return {"status": "hold", "reason_codes": reasons, "axis": axis, "window": spec["bars"],
            "minimum_bars": spec["minimum_bars"], "lines": [], "borders": {"down": [], "up": [], "broken": []},
            "events": [], "pivots": [], "projection_sessions": [], "candidate_count": 0, "rejection_counts": {}}


def hold_snapshot(asset: dict[str, Any], reasons: list[str], *, config: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = deepcopy(config or C.default_config())
    C.validate_config(settings)
    return _finish({
        "schema_version": 1, "contract_id": "trendlines_display_v1", "engine_version": C.ENGINE_VERSION,
        "asset_id": asset["asset_id"], "asset": deepcopy(asset), "status": "hold", "reason_codes": sorted(set(reasons)),
        "numbers_visible": False, "publication_class": "research_reference_proxy", "probability_space": "reference_only",
        "official_forecast_write": False, "as_of": None, "knowledge_cutoff": None, "observation_through": None,
        "source_identity": {"source_id": asset.get("source_id"), "rights_status": "unapproved",
                            "price_basis": asset["price_basis"], "calendar_id": asset["calendar_id"]},
        "input_hash": None, "config_sha256": C.canonical_hash(settings), "bars": [], "events": [], "audit_lines": [],
        "analyses": {axis: {key: _empty_analysis(sorted(set(reasons)), spec, axis) for key, spec in settings["windows"].items()}
                     for axis in settings["axes"]},
    })


def _select_rows(bars: list[dict[str, Any]], asset: dict[str, Any], cutoff: str,
                 source_policy: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if not isinstance(bars, list):
        raise C.TrendlinesError("bars must be an array")
    by_id: dict[str, dict[str, Any]] = {}
    eligible: dict[str, list[dict[str, Any]]] = {}
    known = C.aware_time(cutoff)
    for row in bars:
        if not isinstance(row, dict) or not isinstance(row.get("bar_id"), str):
            raise C.TrendlinesError("bar identity missing")
        if row["bar_id"] in by_id:
            raise C.TrendlinesError("duplicate bar_id")
        by_id[row["bar_id"]] = row
        if C.aware_time(row.get("available_at")) <= known and C.aware_time(row.get("fetched_at")) <= known:
            eligible.setdefault(str(row.get("session_date")), []).append(row)
    selected = []
    for day, revisions in sorted(eligible.items()):
        sequence: dict[int, dict[str, Any]] = {}
        for row in revisions:
            seq = row.get("revision_seq")
            if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1 or seq in sequence:
                raise C.TrendlinesError("duplicate or invalid session revision")
            sequence[seq] = row
        for seq, row in sequence.items():
            if seq == 1:
                if row.get("supersedes_bar_id") is not None:
                    raise C.TrendlinesError("first revision has supersedes")
            else:
                prior = by_id.get(row.get("supersedes_bar_id"))
                if (prior is None or prior.get("revision_seq") != seq - 1 or prior.get("session_date") != day
                        or prior.get("asset_id") != row.get("asset_id") or prior.get("source_id") != row.get("source_id")
                        or C.aware_time(prior["available_at"]) > C.aware_time(row["available_at"])
                        or C.aware_time(prior["fetched_at"]) > C.aware_time(row["fetched_at"])):
                    raise C.TrendlinesError("broken or forked bar revision chain")
        current = sequence[max(sequence)]
        C.validate_bar(current, asset, cutoff, source_policy)
        selected.append(deepcopy(current))
    return selected


def _atr(rows: list[dict[str, Any]], period: int, *, segmented: bool = False) -> list[float | None]:
    ranges: list[float] = []
    result: list[float | None] = [None]
    for index in range(1, len(rows)):
        row, prior = rows[index], rows[index - 1]
        if segmented and row["session_index"] - prior["session_index"] != 1:
            ranges.clear()
            result.append(None)
            continue
        ranges.append(max(row["high"] - row["low"], abs(row["high"] - prior["close"]), abs(row["low"] - prior["close"])))
        result.append(math.fsum(ranges[-period:]) / period if len(ranges) >= period else None)
    return result


def _contiguous(rows: list[dict[str, Any]], first: int, last: int) -> bool:
    return all(b["session_index"] - a["session_index"] == 1
               for a, b in zip(rows[first:last], rows[first + 1:last + 1]))


def _pivots(rows: list[dict[str, Any]], start: int, left: int, right: int, side: str,
            *, segmented: bool = False) -> list[dict[str, Any]]:
    column = "low" if side == "support" else "high"
    output = []
    for index in range(max(start, left), len(rows) - right):
        if segmented and not _contiguous(rows, index - left, index + right):
            continue
        value = rows[index][column]
        lhs = [row[column] for row in rows[index - left:index]]
        rhs = [row[column] for row in rows[index + 1:index + right + 1]]
        valid = all(value < item for item in lhs) and all(value <= item for item in rhs) if side == "support" else (
            all(value > item for item in lhs) and all(value >= item for item in rhs))
        if valid:
            confirmation = index + right
            known = max(C.aware_time(row[field]) for row in rows[index - left:confirmation + 1]
                        for field in ("available_at", "fetched_at"))
            output.append({"session": rows[index]["session_date"], "index": rows[index]["session_index"], "row_index": index,
                           "price": value, "bar_id": rows[index]["bar_id"], "confirmation_row_index": confirmation,
                           "confirmation_session": rows[confirmation]["session_date"], "confirmed_at": known.isoformat(), "side": side})
    return output


def _value(line: dict[str, Any], index: int) -> float | None:
    displacement = index - line["coordinate_origin_index"]
    transformed = line["intercept"] + line["slope"] * displacement
    try:
        value = transformed if line["axis"] == "linear" else math.exp(transformed)
    except OverflowError:
        return None
    return value if math.isfinite(value) and value > 0 else None


def _epsilon(value: float, atr: float, asset: dict[str, Any], settings: dict[str, Any], block: str) -> float:
    tick = asset.get("tick_size", 0.0)
    if isinstance(tick, bool) or not isinstance(tick, (int, float)) or not math.isfinite(tick) or tick < 0:
        raise C.TrendlinesError("invalid explicit tick_size")
    return max(tick, settings[block]["atr_multiple"] * atr, settings[block]["price_fraction"] * value, 1e-12 * value)


def _formation(rows: list[dict[str, Any]], first: dict[str, Any], second: dict[str, Any],
               *, retrospective: bool = False) -> tuple[int, str]:
    """Late bootstrap/backfill receipts move activation forward, never backward."""
    start = first["row_index"]
    activation = second["confirmation_row_index"]
    known = max(C.aware_time(first["confirmed_at"]), C.aware_time(second["confirmed_at"]))
    if retrospective:
        known = max([known, *(C.aware_time(row[field]) for row in rows[start:activation + 1]
                             for field in ("available_at", "fetched_at"))])
        return activation, known.isoformat()
    while True:
        known = max([known, *(C.aware_time(row[field]) for row in rows[start:activation + 1]
                             for field in ("available_at", "fetched_at"))])
        completed = [i for i, row in enumerate(rows) if C.aware_time(row["finalized_at"]) <= known]
        expanded = max(activation, completed[-1] if completed else activation)
        if expanded == activation:
            return activation, known.isoformat()
        activation = expanded


def _event(line: dict[str, Any], row: dict[str, Any], previous: str, current: str, epsilon: float,
           line_value: float, axis: str, window: int) -> dict[str, Any]:
    event = {"line_id": line["line_id"], "axis": axis, "window": window, "effective_session": row["session_date"],
             "issued_at": max(C.aware_time(row["available_at"]), C.aware_time(row["fetched_at"]),
                              C.aware_time(line["activation_asof"])).isoformat(),
             "bar_id": row["bar_id"], "close": row["close"], "line_price": line_value, "buffer": epsilon,
             "prev_state": previous, "new_state": current}
    event["event_id"] = "trend-event-" + C.canonical_hash(event)[:32]
    return event


def _states(line: dict[str, Any], rows: list[dict[str, Any]], atr: list[float | None], activation: int,
            asset: dict[str, Any], settings: dict[str, Any]) -> tuple[str, list[dict[str, Any]], int | None]:
    state, broken, run, last_break = "active", False, 0, None
    events = []
    for index in range(activation + 1, len(rows)):
        row = rows[index]
        price = _value(line, row["session_index"])
        if price is None:
            return "projection_invalid", events, last_break
        epsilon = _epsilon(price, float(atr[index]), asset, settings, "break")
        if not broken:
            crossing = row["close"] < price - epsilon if line["side"] == "support" else row["close"] > price + epsilon
            if crossing:
                run += 1
                next_state = "broken" if run >= 2 else "break_pending"
                if run >= 2:
                    broken, run, last_break = True, 0, row["session_index"]
            else:
                run = 0
                next_state = "reclaimed" if state == "reclaimed" else "active"
        else:
            crossing = row["close"] > price + epsilon if line["side"] == "support" else row["close"] < price - epsilon
            if crossing:
                run += 1
                next_state = "reclaimed" if run >= 2 else "reclaim_pending"
                if run >= 2:
                    broken, run = False, 0
            else:
                run = 0
                next_state = "broken"
        if state != next_state:
            events.append(_event(line, row, state, next_state, epsilon, price, line["axis"], line["window"]))
        state = next_state
    return state, events, last_break


def _make_line(first: dict[str, Any], second: dict[str, Any], pivots: list[dict[str, Any]], rows: list[dict[str, Any]],
               atr: list[float | None], asset: dict[str, Any], settings: dict[str, Any], axis: str, spec: dict[str, Any],
               config_hash: str, *, research: bool = False) -> tuple[dict[str, Any] | None, str | None]:
    gap = second["index"] - first["index"]
    if gap < spec["min_anchor_gap"]:
        return None, "anchor_gap"
    if first["price"] == second["price"]:
        return None, "horizontal_pair"
    transform = math.log if axis == "log" else float
    activation, known = _formation(rows, first, second, retrospective=research)
    if research and not _contiguous(rows, max(0, first["row_index"] - spec["left"]), activation):
        return None, "missing_formation_sessions"
    formation_hash = C.canonical_hash([row["bar_id"] for row in rows[first["row_index"]:activation + 1]])
    identity = {"asset_id": asset["asset_id"], "axis": axis, "window": spec["bars"], "side": first["side"],
                "first_bar_id": first["bar_id"], "second_bar_id": second["bar_id"], "config_sha256": config_hash,
                "formation_input_hash": formation_hash}
    line = {"line_id": "trend-line-" + C.canonical_hash(identity)[:32], "axis": axis, "window": spec["bars"],
            "side": first["side"], "direction": "rising" if second["price"] > first["price"] else "falling",
            "first_anchor": {key: first[key] for key in ("session", "index", "price", "bar_id", "confirmed_at", "confirmation_session")},
            "second_anchor": {key: second[key] for key in ("session", "index", "price", "bar_id", "confirmed_at", "confirmation_session")},
            "coordinate_origin_index": first["index"], "intercept": transform(first["price"]),
            "slope": (transform(second["price"]) - transform(first["price"])) / gap,
            "activation_asof": known, "activation_session": rows[activation]["session_date"],
            "formation_input_hash": formation_hash}
    penetration = 0.0
    for index in range(first["row_index"], activation + 1):
        price = _value(line, rows[index]["session_index"])
        if price is None or atr[index] is None:
            return None, "invalid_formation_projection"
        tolerance = _epsilon(price, float(atr[index]), asset, settings, "touch")
        adverse = price - rows[index]["low"] if line["side"] == "support" else rows[index]["high"] - price
        penetration = max(penetration, adverse / tolerance)
        if adverse > tolerance:
            return None, "formation_penetration"
    contacts = []
    for pivot in pivots:
        if pivot["index"] < first["index"]:
            continue
        if research and (atr[pivot["row_index"]] is None or not _contiguous(rows, first["row_index"], pivot["row_index"])):
            continue
        price = _value(line, pivot["index"])
        if price is not None and abs(pivot["price"] - price) <= _epsilon(price, float(atr[pivot["row_index"]]), asset, settings, "touch"):
            contacts.append({key: pivot[key] for key in ("session", "index", "price", "bar_id", "confirmed_at")})
    line.update({"contacts": contacts, "touch_count": len(contacts), "geometry_status": "confirmed" if len(contacts) >= 3 else "candidate",
                 "anchor_span": gap, "latest_touch_index": max(item["index"] for item in contacts), "formation_penetration": penetration})
    state, events, last_break = (("research_reference", [], None) if research else
                                _states(line, rows, atr, activation, asset, settings))
    current = _value(line, rows[-1]["session_index"])
    distance = None if current is None or atr[-1] is None else abs(current - rows[-1]["close"]) / _epsilon(
        current, float(atr[-1]), asset, settings, "touch")
    line.update({"state": state, "current_price": current, "distance_score": distance, "last_break_index": last_break, "events": events})
    return line, None


def _rank(line: dict[str, Any]) -> tuple:
    return (-line["touch_count"], -line["latest_touch_index"], -line["anchor_span"], line["formation_penetration"],
            float("inf") if line["distance_score"] is None else line["distance_score"], line["line_id"])


def _project(line: dict[str, Any], rows: list[dict[str, Any]], projections: list[dict[str, Any]]) -> dict[str, Any]:
    result = {key: value for key, value in line.items() if key != "events"}
    result["points"] = []
    indexes = {line["first_anchor"]["index"], line["second_anchor"]["index"], rows[-1]["session_index"]}
    for row in rows:
        if row["session_index"] not in indexes:
            continue
        price = _value(line, row["session_index"])
        if price is None:
            break
        result["points"].append({"session": row["session_date"], "index": row["session_index"], "price": price, "future": False})
    result["projections"] = []
    for row in projections:
        price = _value(line, row["index"])
        result["projections"].append({**row, "price": price, "status": "ready" if price is not None else "unavailable"})
        if price is not None:
            result["points"].append({"session": row["session"], "index": row["index"], "price": price, "future": True})
    return result


def _border(line: dict[str, Any]) -> dict[str, Any]:
    return {"line_id": line["line_id"], "price": line["current_price"], "state": line["state"],
            "geometry_status": line["geometry_status"], "touch_count": line["touch_count"],
            "side": line["side"], "direction": line["direction"]}


def _analyze(rows: list[dict[str, Any]], asset: dict[str, Any], settings: dict[str, Any], axis: str, spec: dict[str, Any],
             projections: list[dict[str, Any]], config_hash: str, *, research: bool = False
             ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    if len(rows) < spec["minimum_bars"]:
        return _empty_analysis(["insufficient_history"], spec, axis), [], []
    required = rows[-spec["minimum_bars"]:]
    if not research and any(b["session_index"] - a["session_index"] != 1 for a, b in zip(required, required[1:])):
        return _empty_analysis(["missing_completed_sessions"], spec, axis), [], []
    atr = _atr(rows, settings["atr"]["period"], segmented=research)
    start = len(rows) - spec["bars"]
    # ATR is not computed across a gap, even if a gap preceded this window.
    if not research and any(row is None for row in atr[start:]):
        return _empty_analysis(["missing_atr_warmup"], spec, axis), [], []
    all_lines, all_pivots, rejected = [], [], {}
    for side in ("support", "resistance"):
        pivots = _pivots(rows, start, spec["left"], spec["right"], side, segmented=research)
        all_pivots.extend(pivots)
        for offset, first in enumerate(pivots):
            for second in pivots[offset + 1:]:
                line, reason = _make_line(first, second, pivots, rows, atr, asset, settings, axis, spec, config_hash, research=research)
                if line is None:
                    rejected[reason] = rejected.get(reason, 0) + 1
                else:
                    all_lines.append(line)
    selected, recent_broken = [], []
    for side in ("support", "resistance"):
        eligible_states = {"research_reference"} if research else {"active", "break_pending", "reclaimed"}
        candidates = sorted((line for line in all_lines if line["side"] == side and line["state"] in eligible_states), key=_rank)
        for rank, line in enumerate(candidates[:settings["max_selected_per_side"]], 1):
            selected.append({**line, "rank": rank})
        broken = sorted((line for line in all_lines if line["side"] == side and line["state"] in {"broken", "reclaim_pending"}
                         and line["current_price"] is not None), key=lambda item: (-(item["last_break_index"] or 0), *_rank(item)))
        for rank, line in enumerate(broken[:settings["max_recent_broken_per_side"]], 1):
            recent_broken.append({**line, "rank": rank})
    close = rows[-1]["close"]
    active = [line for line in all_lines if line["state"] in eligible_states and line["current_price"] is not None]
    down = sorted((line for line in active if line["current_price"] <= close), key=lambda item: (-item["current_price"], *_rank(item)))[:3]
    up = sorted((line for line in active if line["current_price"] > close), key=lambda item: (item["current_price"], *_rank(item)))[:3]
    # Every displayed border must have its corresponding actual line in the chart.
    chosen = {line["line_id"]: line for line in selected + recent_broken}
    for line in down + up:
        chosen.setdefault(line["line_id"], {**line, "rank": None})
    events = [event for line in all_lines for event in line["events"]]
    shown_events = [event for event in events if event["line_id"] in chosen]
    analysis = {"status": "ready", "reason_codes": [], "axis": axis, "window": spec["bars"], "minimum_bars": spec["minimum_bars"],
                "lines": [_project(line, rows, projections) for line in chosen.values()],
                "borders": {"down": [_border(line) for line in down], "up": [_border(line) for line in up],
                            "broken": [_border(line) for line in recent_broken]},
                "events": shown_events, "pivots": [{key: value for key, value in pivot.items() if "row_index" not in key} for pivot in all_pivots],
                "projection_sessions": projections, "candidate_count": len(all_lines), "rejection_counts": rejected}
    return analysis, events, [{key: value for key, value in line.items() if key != "events"} for line in all_lines]


def build_asset_snapshot(asset: dict[str, Any], bars: list[dict[str, Any]], knowledge_cutoff: str, *,
                         config: dict[str, Any] | None = None, source_policy: dict[str, Any] | None = None,
                         previous_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    return _build_asset_snapshot(asset, bars, knowledge_cutoff, config=config, source_policy=source_policy,
                                 previous_snapshot=previous_snapshot, research=False)


def build_research_asset_snapshot(asset: dict[str, Any], bars: list[dict[str, Any]], knowledge_cutoff: str, *,
                                  config: dict[str, Any] | None = None, source_policy: dict[str, Any] | None = None,
                                  previous_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    """Current-vintage public HTML geometry, explicitly outside approved data.

    Historical candles may describe geometric contacts. They cannot issue
    historical break/reclaim signals or be used as a point-in-time backtest.
    """
    C.validate_research_source(asset, source_policy)
    return _build_asset_snapshot(asset, bars, knowledge_cutoff, config=config, source_policy=source_policy,
                                 previous_snapshot=previous_snapshot, research=True)


def _completed(asset: dict[str, Any], cutoff: str, settings: dict[str, Any], source_policy: dict[str, Any] | None,
               *, research: bool) -> str | None:
    calendar_asset = deepcopy(asset)
    if research:
        source = C.validate_research_source(asset, source_policy)
        calendar_asset["publication_lag_minutes"] = C.publication_lag(asset, source)
    return C.latest_completed_session(calendar_asset, cutoff, buffer_minutes=settings["settlement_buffer_minutes"],
                                      source_policy=None if research else source_policy)


def _research_metadata(asset: dict[str, Any], rows: list[dict[str, Any]], expected: str | None,
                       schedule: tuple) -> dict[str, Any]:
    observed = {row["session_date"] for row in rows}
    missing = [day for day, _opened, _closed in schedule if expected is not None and day <= expected and day not in observed]
    stale = bool(rows and rows[-1]["session_date"] != expected)
    return {"source_context": C.RESEARCH_SOURCE_CONTEXT, "verified_source": False, "adjustment_verified": False,
            "research_bootstrap": True, "historical_signals_available": False,
            "quality": {"expected_completed_session": expected, "latest_completed_observation": rows[-1]["session_date"] if rows else None,
                        "missing_session_dates": missing, "stale": stale,
                        "reasons": (["missing_latest_completed_session"] if stale else []) + (["missing_completed_sessions"] if missing else []),
                        "gap_policy": "segmented_geometry_no_synthetic_bars"}}


def _research_hold(asset: dict[str, Any], reasons: list[str], settings: dict[str, Any]) -> dict[str, Any]:
    original = hold_snapshot(asset, reasons, config=settings)
    body = {key: value for key, value in original.items() if key not in {"snapshot_id", "content_hash"}}
    body["publication_class"] = "research_source"
    body.update(_research_metadata(asset, [], None, ()))
    body["source_identity"].update({"rights_status": "uncertified_research_source", "source_context": C.RESEARCH_SOURCE_CONTEXT,
                                    "verified_source": False, "adjustment_verified": False, "provider_symbol": asset["provider_symbol"]})
    return _finish(body)


def _build_asset_snapshot(asset: dict[str, Any], bars: list[dict[str, Any]], knowledge_cutoff: str, *,
                          config: dict[str, Any] | None, source_policy: dict[str, Any] | None,
                          previous_snapshot: dict[str, Any] | None, research: bool) -> dict[str, Any]:
    settings = deepcopy(config or C.default_config())
    C.validate_config(settings)
    if not research and (asset.get("enabled") is not True or not asset.get("source_id")):
        return hold_snapshot(asset, [asset.get("hold_reason") or "missing_approved_ohlc"], config=settings)
    source = C.validate_research_source(asset, source_policy) if research else C.validate_source(asset, source_policy)
    cutoff = C.aware_time(knowledge_cutoff).isoformat()
    rows = _select_rows(bars, asset, cutoff, None if research else source_policy)
    if not rows:
        return (_research_hold(asset, ["missing_research_ohlc"], settings) if research else
                hold_snapshot(asset, ["missing_approved_ohlc"], config=settings))
    if research and any(C.aware_time(row["available_at"]) != C.aware_time(row["fetched_at"]) for row in rows):
        raise C.TrendlinesError("research current-vintage availability must equal actual first capture")
    expected = _completed(asset, cutoff, settings, source_policy, research=research)
    if not research and rows[-1]["session_date"] != expected:
        return hold_snapshot(asset, ["missing_latest_completed_session"], config=settings)
    first_day, last_day = rows[0]["session_date"], rows[-1]["session_date"]
    future_end = max((date.fromisoformat(last_day) + timedelta(days=120)).isoformat(), expected or last_day)
    schedule = C.session_schedule(asset["calendar_id"], first_day, future_end)
    coordinates = {day: index for index, (day, _opened, _closed) in enumerate(schedule)}
    for row in rows:
        row.update({"session": row["session_date"], "session_index": coordinates[row["session_date"]]})
    if research and any(expected is None or row["session_date"] > expected for row in rows):
        raise C.TrendlinesError("research candle is not past completed-session buffer")
    last_index = rows[-1]["session_index"]
    offsets = settings["projections"]["crypto" if asset.get("kind") == "crypto" else "exchange"]
    future = [{"offset": offset, "session": schedule[last_index + offset][0], "index": last_index + offset} for offset in offsets]
    config_hash = C.canonical_hash(settings)
    analyses, events, audit_lines = {}, [], []
    for axis in settings["axes"]:
        analyses[axis] = {}
        for key, spec in settings["windows"].items():
            analyses[axis][key], issued, candidate_manifest = _analyze(rows, asset, settings, axis, spec, future, config_hash, research=research)
            events.extend(issued)
            audit_lines.extend(candidate_manifest)
    if not research and not any(analysis["status"] == "ready" for windows in analyses.values() for analysis in windows.values()):
        reasons = [reason for windows in analyses.values() for analysis in windows.values() for reason in analysis["reason_codes"]]
        return hold_snapshot(asset, reasons, config=settings)
    body = {"schema_version": 1, "contract_id": "trendlines_display_v1", "engine_version": C.ENGINE_VERSION,
            "asset_id": asset["asset_id"], "asset": deepcopy(asset), "status": "unverified_display" if research else "ready", "reason_codes": [], "numbers_visible": True,
            "publication_class": "research_source" if research else "research_reference_proxy", "probability_space": "reference_only", "official_forecast_write": False,
            "as_of": cutoff, "knowledge_cutoff": cutoff, "observation_through": last_day,
            "source_identity": {"source_id": asset["source_id"], "rights_status": source["rights_status"],
                                "price_basis": asset["price_basis"], "calendar_id": asset["calendar_id"]},
            "input_hash": C.canonical_hash(rows), "input_bar_ids": [row["bar_id"] for row in rows], "config_sha256": config_hash,
            "bars": rows[-max(spec["bars"] for spec in settings["windows"].values()):], "analyses": analyses,
            "audit_lines": audit_lines,
            "events": sorted(events, key=lambda event: (event["issued_at"], event["line_id"], event["effective_session"], event["event_id"])),
            "guards": {"approved_free_ohlc": not research, "atomic_ohlc": True, "pit": True, "calendar": True,
                       "no_official_append": True, "no_manual_anchor_inheritance": True}}
    if research:
        body.update(_research_metadata(asset, rows, expected, schedule))
        body["source_identity"].update({"source_context": C.RESEARCH_SOURCE_CONTEXT, "verified_source": False,
                                        "adjustment_verified": False, "provider_symbol": asset["provider_symbol"]})
    if previous_snapshot:
        previous_ids = {line["line_id"] for windows in previous_snapshot.get("analyses", {}).values()
                        for analysis in windows.values() for line in analysis.get("lines", [])}
        body["selection_changes"] = {"new_line_ids": sorted({line["line_id"] for windows in analyses.values()
                                                               for analysis in windows.values() for line in analysis["lines"]} - previous_ids)}
    return _finish(body)


def verify_asset_snapshot(snapshot: dict[str, Any], bars: list[dict[str, Any]], asset: dict[str, Any],
                          config: dict[str, Any] | None = None, source_policy: dict[str, Any] | None = None,
                          replay: bool = True) -> dict[str, Any]:
    return _verify_asset_snapshot(snapshot, bars, asset, config=config, source_policy=source_policy, replay=replay, research=False)


def verify_research_asset_snapshot(snapshot: dict[str, Any], bars: list[dict[str, Any]], asset: dict[str, Any],
                                   config: dict[str, Any] | None = None, source_policy: dict[str, Any] | None = None,
                                   replay: bool = True) -> dict[str, Any]:
    return _verify_asset_snapshot(snapshot, bars, asset, config=config, source_policy=source_policy, replay=replay, research=True)


def _verify_asset_snapshot(snapshot: dict[str, Any], bars: list[dict[str, Any]], asset: dict[str, Any], *,
                           config: dict[str, Any] | None, source_policy: dict[str, Any] | None, replay: bool,
                           research: bool) -> dict[str, Any]:
    """Independent scalar replay of published geometry, contacts and states.

    The oracle intentionally does not call _atr, _pivots, _value or _states.
    It checks all published endpoints and event histories from the frozen bars,
    including issuance eligibility. Input/store/raw hash validation is separate.
    """
    errors: list[str] = []
    try:
        settings = deepcopy(config or C.default_config())
        C.validate_config(settings)
        body = {key: value for key, value in snapshot.items() if key != "content_hash"}
        if snapshot.get("content_hash") != C.canonical_hash(body):
            raise C.TrendlinesError("snapshot content hash mismatch")
        identity_body = {key: value for key, value in body.items() if key != "snapshot_id"}
        if snapshot.get("snapshot_id") != "trendlines-" + asset["asset_id"] + "-" + C.canonical_hash(identity_body)[:24]:
            raise C.TrendlinesError("snapshot identity mismatch")
        if snapshot.get("asset_id") != asset["asset_id"] or snapshot.get("official_forecast_write") is not False:
            raise C.TrendlinesError("snapshot identity or official write gate mismatch")
        if (snapshot.get("schema_version") != 1 or snapshot.get("contract_id") != "trendlines_display_v1"
                or snapshot.get("engine_version") != C.ENGINE_VERSION or snapshot.get("publication_class") != ("research_source" if research else "research_reference_proxy")
                or snapshot.get("probability_space") != "reference_only" or snapshot.get("asset") != asset):
            raise C.TrendlinesError("snapshot semantic contract mismatch")
        if set(snapshot.get("analyses", {})) != set(settings["axes"]) or any(
            set(windows) != set(settings["windows"]) for windows in snapshot["analyses"].values()):
            raise C.TrendlinesError("snapshot axes/windows missing or unsupported")
        if snapshot.get("config_sha256") != C.canonical_hash(settings):
            raise C.TrendlinesError("snapshot config mismatch")
        if research:
            C.validate_research_source(asset, source_policy)
            if any(snapshot.get(key) is not expected for key, expected in (
                    ("verified_source", False), ("adjustment_verified", False), ("historical_signals_available", False), ("research_bootstrap", True))):
                raise C.TrendlinesError("research provenance or historical signal gate mismatch")
            if snapshot.get("source_context") != C.RESEARCH_SOURCE_CONTEXT or snapshot.get("events"):
                raise C.TrendlinesError("research context mismatch or historical signals issued")
        if snapshot.get("status") == "hold":
            if research:
                expected_hold = _research_hold(asset, snapshot.get("reason_codes", []), settings)
                if snapshot != expected_hold:
                    raise C.TrendlinesError("research HOLD provenance/metadata mismatch")
            if snapshot.get("bars") or snapshot.get("events") or snapshot.get("audit_lines") or snapshot.get("numbers_visible") is not False:
                raise C.TrendlinesError("HOLD contains numbers")
            for windows in snapshot.get("analyses", {}).values():
                for analysis in windows.values():
                    if analysis.get("lines") or any(analysis.get("borders", {}).values()) or analysis.get("events") or analysis.get("pivots"):
                        raise C.TrendlinesError("HOLD analysis contains numbers")
            if snapshot.get("as_of") is not None or snapshot.get("knowledge_cutoff") is not None:
                raise C.TrendlinesError("HOLD is backdated or timestamp-only")
            return {"ok": True, "errors": [], "replay": "hold_no_numeric_input"}
        if snapshot.get("status") != ("unverified_display" if research else "ready") or snapshot.get("numbers_visible") is not True:
            raise C.TrendlinesError("unsupported snapshot state")
        if not research:
            C.validate_source(asset, source_policy)
        expected_source = {"source_id": asset["source_id"], "rights_status": "uncertified_research_source" if research else "approved_free",
                           "price_basis": asset["price_basis"], "calendar_id": asset["calendar_id"]}
        if research:
            expected_source.update({"source_context": C.RESEARCH_SOURCE_CONTEXT, "verified_source": False,
                                    "adjustment_verified": False, "provider_symbol": asset["provider_symbol"]})
        if snapshot.get("source_identity") != expected_source:
            raise C.TrendlinesError("snapshot source identity mismatch")
        cutoff = snapshot["knowledge_cutoff"]
        rows = _select_rows(bars, asset, cutoff, None if research else source_policy)
        if research and any(C.aware_time(row["available_at"]) != C.aware_time(row["fetched_at"]) for row in rows):
            raise C.TrendlinesError("research current-vintage availability must equal actual first capture")
        expected = _completed(asset, cutoff, settings, source_policy, research=research)
        schedule = C.session_schedule(asset["calendar_id"], rows[0]["session_date"],
                                      max((date.fromisoformat(rows[-1]["session_date"]) + timedelta(days=120)).isoformat(),
                                          expected or rows[-1]["session_date"]))
        coordinates = {day: index for index, (day, _opened, _closed) in enumerate(schedule)}
        for row in rows:
            row.update({"session": row["session_date"], "session_index": coordinates[row["session_date"]]})
        if C.canonical_hash(rows) != snapshot.get("input_hash") or [row["bar_id"] for row in rows] != snapshot.get("input_bar_ids"):
            raise C.TrendlinesError("snapshot input hash/identity mismatch")
        if snapshot.get("bars") != rows[-max(spec["bars"] for spec in settings["windows"].values()):]:
            raise C.TrendlinesError("snapshot candles differ from frozen inputs")
        if snapshot.get("as_of") != cutoff or snapshot.get("observation_through") != rows[-1]["session_date"]:
            raise C.TrendlinesError("snapshot time mismatch")
        expected = _completed(asset, cutoff, settings, source_policy, research=research)
        if not research and rows[-1]["session_date"] != expected:
            raise C.TrendlinesError("snapshot lacks latest completed session")
        if research:
            if any(expected is None or row["session_date"] > expected for row in rows):
                raise C.TrendlinesError("research candle is not past completed-session buffer")
            metadata = _research_metadata(asset, rows, expected, schedule)
            if any(snapshot.get(key) != value for key, value in metadata.items()):
                raise C.TrendlinesError("research quality/current-vintage metadata mismatch")
            if snapshot.get("guards") != {"approved_free_ohlc": False, "atomic_ohlc": True, "pit": True, "calendar": True,
                                           "no_official_append": True, "no_manual_anchor_inheritance": True}:
                raise C.TrendlinesError("research approval/write guards mismatch")
        if not replay:
            return {"ok": True, "errors": [], "replay": "metadata_only"}
        if not isinstance(snapshot.get("audit_lines"), list):
            raise C.TrendlinesError("candidate audit manifest missing")
        if len({line["line_id"] for line in snapshot["audit_lines"]}) != len(snapshot["audit_lines"]):
            raise C.TrendlinesError("duplicate candidate line identity")
        if len({event["event_id"] for event in snapshot["events"]}) != len(snapshot["events"]):
            raise C.TrendlinesError("duplicate event identity")
        audit_ids = {line["line_id"] for line in snapshot["audit_lines"]}
        if any(event["line_id"] not in audit_ids for event in snapshot["events"]):
            raise C.TrendlinesError("event missing candidate audit lineage")
        lookup = {row["bar_id"]: (index, row) for index, row in enumerate(rows)}
        absolute, relative = settings["comparison_tolerance"]["absolute"], settings["comparison_tolerance"]["relative"]

        def equal(a: float, b: float) -> bool:
            return math.isclose(a, b, rel_tol=relative, abs_tol=absolute)

        @lru_cache(maxsize=None)
        def scalar_atr(index: int) -> float | None:
            period = settings["atr"]["period"]
            if research and (index < period or any(rows[position]["session_index"] - rows[position - 1]["session_index"] != 1
                                                   for position in range(index - period + 1, index + 1))):
                return None
            terms = []
            for position in range(index - period + 1, index + 1):
                high, low = rows[position]["high"], rows[position]["low"]
                previous = rows[position - 1]["close"]
                terms.append(max(high, previous) - min(low, previous))
            return sum(terms) / period

        def scalar_eps(price: float, index: int, block: str) -> float:
            atr = scalar_atr(index)
            if atr is None:
                raise C.TrendlinesError("research ATR crossed a missing session")
            return max(asset.get("tick_size", 0.0), settings[block]["atr_multiple"] * atr,
                       settings[block]["price_fraction"] * price, 1e-12 * price)

        last_index = rows[-1]["session_index"]
        offsets = settings["projections"]["crypto" if asset.get("kind") == "crypto" else "exchange"]
        expected_future = [{"offset": offset, "session": schedule[last_index + offset][0], "index": last_index + offset}
                           for offset in offsets]
        for axis, windows in snapshot["analyses"].items():
            for key, analysis in windows.items():
                spec = settings["windows"][key]
                if analysis["status"] == "hold":
                    if analysis["lines"] or analysis["events"] or any(analysis["borders"].values()) or analysis.get("projection_sessions"):
                        errors.append("held range has numbers")
                    if len(rows) >= spec["minimum_bars"] and (research or all(
                        b["session_index"] - a["session_index"] == 1
                        for a, b in zip(rows[-spec["minimum_bars"]:], rows[-spec["minimum_bars"] + 1:]))):
                        errors.append("eligible range was hidden by HOLD")
                    continue
                reported_future = analysis.get("projection_sessions")
                if (reported_future != expected_future or any(type(item.get(field)) is not int for item in reported_future or []
                                                              for field in ("offset", "index"))):
                    errors.append("projection session horizon/calendar replay mismatch")
                pivot_oracle = {}
                expected_pivot_records = []
                for side, column in (("support", "low"), ("resistance", "high")):
                    pivots = []
                    for index in range(max(len(rows) - spec["bars"], spec["left"]), len(rows) - spec["right"]):
                        segment = rows[index - spec["left"]:index + spec["right"] + 1]
                        if research and any(b["session_index"] - a["session_index"] != 1 for a, b in zip(segment, segment[1:])):
                            continue
                        values = [row[column] for row in segment]
                        extreme = min(values) if side == "support" else max(values)
                        if rows[index][column] == extreme and values.index(extreme) == spec["left"]:
                            pivots.append(index)
                            confirmed = max(C.aware_time(item[field]) for item in segment for field in ("available_at", "fetched_at"))
                            expected_pivot_records.append({"session": rows[index]["session_date"], "index": rows[index]["session_index"],
                                                           "price": rows[index][column], "bar_id": rows[index]["bar_id"],
                                                           "confirmation_session": rows[index + spec["right"]]["session_date"],
                                                           "confirmed_at": confirmed.isoformat(), "side": side})
                    pivot_oracle[side] = pivots
                reported_pivots = {(pivot["side"], pivot["bar_id"]) for pivot in analysis["pivots"]}
                expected_pivots = {(side, rows[index]["bar_id"]) for side, indices in pivot_oracle.items() for index in indices}
                if reported_pivots != expected_pivots:
                    errors.append("pivot replay mismatch")
                if analysis["pivots"] != expected_pivot_records:
                    errors.append("pivot price/confirmation metadata replay mismatch")
                candidates = [line for line in snapshot["audit_lines"] if line["axis"] == axis and line["window"] == spec["bars"]]
                if len(candidates) != analysis["candidate_count"]:
                    errors.append("candidate manifest count mismatch")
                candidate_lookup = {line["line_id"]: line for line in candidates}
                # Enumerate independently, so dropping an inconvenient candidate
                # and its events cannot make the artifact pass replay.
                expected_candidate_ids = set()
                expected_formations = {}
                for side, indices in pivot_oracle.items():
                    column = "low" if side == "support" else "high"
                    for offset, ia in enumerate(indices):
                        for ib in indices[offset + 1:]:
                            a, b = rows[ia], rows[ib]
                            span = b["session_index"] - a["session_index"]
                            if span < spec["min_anchor_gap"] or a[column] == b[column]:
                                continue
                            activation = ib + spec["right"]
                            known = max(C.aware_time(item[field]) for index in (ia, ib)
                                        for item in rows[index - spec["left"]:index + spec["right"] + 1]
                                        for field in ("available_at", "fetched_at"))
                            while True:
                                known = max([known, *(C.aware_time(item[field]) for item in rows[ia:activation + 1]
                                                     for field in ("available_at", "fetched_at"))])
                                if research:
                                    break
                                end = max(activation, max((index for index, item in enumerate(rows)
                                                          if C.aware_time(item["finalized_at"]) <= known), default=activation))
                                if end == activation:
                                    break
                                activation = end
                            admitted = not research or all(
                                rows[position]["session_index"] - rows[position - 1]["session_index"] == 1
                                for position in range(max(0, ia - spec["left"]) + 1, activation + 1))
                            if research and any(scalar_atr(index) is None for index in range(ia, activation + 1)):
                                admitted = False
                            if not admitted:
                                continue
                            for index in range(ia, activation + 1):
                                weight = (rows[index]["session_index"] - a["session_index"]) / span
                                try:
                                    price = (a[column] * (1 - weight) + b[column] * weight if axis == "linear" else
                                             math.exp(math.log(a[column]) * (1 - weight) + math.log(b[column]) * weight))
                                except OverflowError:
                                    admitted = False
                                    break
                                if not math.isfinite(price) or price <= 0:
                                    admitted = False
                                    break
                                adverse = price - rows[index]["low"] if side == "support" else rows[index]["high"] - price
                                if adverse > scalar_eps(price, index, "touch"):
                                    admitted = False
                                    break
                            if admitted:
                                formation_hash = C.canonical_hash([item["bar_id"] for item in rows[ia:activation + 1]])
                                identity = {"asset_id": asset["asset_id"], "axis": axis, "window": spec["bars"], "side": side,
                                            "first_bar_id": a["bar_id"], "second_bar_id": b["bar_id"],
                                            "config_sha256": snapshot["config_sha256"], "formation_input_hash": formation_hash}
                                candidate_id = "trend-line-" + C.canonical_hash(identity)[:32]
                                expected_candidate_ids.add(candidate_id)
                                expected_formations[candidate_id] = (activation, known)
                if set(candidate_lookup) != expected_candidate_ids:
                    errors.append("candidate admission completeness replay mismatch")
                for shown in analysis["lines"]:
                    base = candidate_lookup.get(shown["line_id"])
                    if base is None or any(shown.get(key) != value for key, value in base.items()):
                        errors.append("displayed line differs from audit candidate")
                for line in candidates:
                    first, second = line["first_anchor"], line["second_anchor"]
                    ia, a = lookup[first["bar_id"]]
                    ib, b = lookup[second["bar_id"]]
                    column = "low" if line["side"] == "support" else "high"
                    if ia not in pivot_oracle[line["side"]] or ib not in pivot_oracle[line["side"]]:
                        errors.append("line anchor is not confirmed pivot")
                    if first["price"] != a[column] or second["price"] != b[column]:
                        errors.append("line anchor price mismatch")
                    if line["direction"] != ("rising" if b[column] > a[column] else "falling"):
                        errors.append("line direction replay mismatch")
                    for anchor, row, index in ((first, a, ia), (second, b, ib)):
                        known = max(C.aware_time(item[field]) for item in rows[index - spec["left"]:index + spec["right"] + 1]
                                    for field in ("available_at", "fetched_at"))
                        if (anchor["session"] != row["session_date"] or anchor["index"] != row["session_index"]
                                or C.aware_time(anchor["confirmed_at"]) != known
                                or anchor["confirmation_session"] != rows[index + spec["right"]]["session_date"]):
                            errors.append("anchor confirmation replay mismatch")
                    span = b["session_index"] - a["session_index"]
                    if span < spec["min_anchor_gap"]:
                        errors.append("line anchor gap mismatch")

                    def oracle(index: int) -> float | None:
                        ratio = (index - a["session_index"]) / span
                        try:
                            price = (a[column] + (b[column] - a[column]) * ratio if axis == "linear"
                                     else math.exp((1 - ratio) * math.log(a[column]) + ratio * math.log(b[column])))
                        except OverflowError:
                            return None
                        return price if math.isfinite(price) and price > 0 else None

                    slope = ((b[column] - a[column]) / span if axis == "linear" else (math.log(b[column]) - math.log(a[column])) / span)
                    expected_intercept = a[column] if axis == "linear" else math.log(a[column])
                    if (not equal(slope, line["slope"]) or not equal(expected_intercept, line["intercept"])
                            or line["coordinate_origin_index"] != a["session_index"] or line["axis"] != axis or line["window"] != spec["bars"]):
                        errors.append("line slope/origin replay mismatch")
                    shown = next((item for item in analysis["lines"] if item["line_id"] == line["line_id"]), None)
                    if shown is not None:
                        # Checking a line equation alone permits a correct price
                        # to be attached to a wrong horizon/date, or its required
                        # future segment to disappear. Bind the complete geometry
                        # to the declared exchange/crypto session tuples.
                        projections = shown.get("projections")
                        if not isinstance(projections, list) or len(projections) != len(expected_future):
                            errors.append("line projection horizon/calendar binding mismatch")
                        else:
                            for projection, expected in zip(projections, expected_future):
                                if not isinstance(projection, dict):
                                    errors.append("line projection horizon/calendar binding mismatch")
                                    continue
                                price = oracle(expected["index"])
                                if (any(projection.get(field) != value for field, value in expected.items())
                                        or any(type(projection.get(field)) is not int for field in ("offset", "index"))
                                        or projection.get("status") != ("ready" if price is not None else "unavailable")
                                        or (price is None and projection.get("price") is not None)
                                        or (price is not None and (not C._finite_number(projection.get("price"))
                                                                  or not equal(price, projection["price"])))):
                                    errors.append("line projection horizon/calendar binding mismatch")
                        expected_points = []
                        for row in rows:
                            if row["session_index"] in {a["session_index"], b["session_index"], last_index}:
                                price = oracle(row["session_index"])
                                if price is None:
                                    break
                                expected_points.append({"session": row["session_date"], "index": row["session_index"],
                                                        "price": price, "future": False})
                        for future in expected_future:
                            price = oracle(future["index"])
                            if price is not None:
                                expected_points.append({"session": future["session"], "index": future["index"], "price": price, "future": True})
                        points = shown.get("points")
                        if not isinstance(points, list) or len(points) != len(expected_points):
                            errors.append("line point horizon/calendar binding mismatch")
                        else:
                            for point, expected in zip(points, expected_points):
                                if not isinstance(point, dict):
                                    errors.append("line point horizon/calendar binding mismatch")
                                    continue
                                if (any(point.get(field) != expected[field] for field in ("session", "index", "future"))
                                        or type(point.get("index")) is not int or type(point.get("future")) is not bool
                                        or not C._finite_number(point.get("price")) or not equal(point["price"], expected["price"])):
                                    errors.append("line point horizon/calendar binding mismatch")
                    for point in shown.get("points", []) if shown else []:
                        price = oracle(point["index"])
                        if price is None or not equal(price, point["price"]) or coordinates.get(point["session"]) != point["index"]:
                            errors.append("line endpoint replay mismatch")
                    current = oracle(rows[-1]["session_index"])
                    if (current is None) != (line["current_price"] is None) or (
                        current is not None and not equal(current, line["current_price"])):
                        errors.append("current border replay mismatch")
                    for projection in shown.get("projections", []) if shown else []:
                        expected_price = oracle(projection["index"])
                        if expected_price is None:
                            if projection["price"] is not None or projection["status"] != "unavailable":
                                errors.append("invalid extension was silently clipped")
                        elif projection["price"] is None or not equal(expected_price, projection["price"]):
                            errors.append("future extension replay mismatch")
                    contacts = []
                    for index in pivot_oracle[line["side"]]:
                        if index >= ia:
                            if research and (scalar_atr(index) is None or any(
                                    rows[position]["session_index"] - rows[position - 1]["session_index"] != 1
                                    for position in range(ia + 1, index + 1))):
                                continue
                            price = oracle(rows[index]["session_index"])
                            if price is not None and abs(rows[index][column] - price) <= scalar_eps(price, index, "touch"):
                                contacts.append(rows[index]["bar_id"])
                    if contacts != [pivot["bar_id"] for pivot in line["contacts"]] or len(contacts) != line["touch_count"]:
                        errors.append("contact replay mismatch")
                    expected_contacts = [{field: pivot[field] for field in ("session", "index", "price", "bar_id", "confirmed_at")}
                                         for pivot in expected_pivot_records if pivot["side"] == line["side"] and pivot["bar_id"] in contacts]
                    if line["contacts"] != expected_contacts:
                        errors.append("contact price/confirmation metadata replay mismatch")
                    confirmed = "confirmed" if len(contacts) >= 3 else "candidate"
                    if line["geometry_status"] != confirmed:
                        errors.append("two-anchor line promoted to confirmed geometry")
                    activation = next(i for i, row in enumerate(rows) if row["session_date"] == line["activation_session"])
                    if activation < ib + spec["right"] or C.aware_time(line["activation_asof"]) < C.aware_time(second["confirmed_at"]):
                        errors.append("line activated before pivot confirmation")
                    expected_formation = expected_formations.get(line["line_id"])
                    if expected_formation is None or (activation, C.aware_time(line["activation_asof"])) != expected_formation:
                        errors.append("line activation availability replay mismatch")
                    formation_hash = C.canonical_hash([row["bar_id"] for row in rows[ia:activation + 1]])
                    identity = {"asset_id": asset["asset_id"], "axis": axis, "window": spec["bars"], "side": line["side"],
                                "first_bar_id": a["bar_id"], "second_bar_id": b["bar_id"], "config_sha256": snapshot["config_sha256"],
                                "formation_input_hash": formation_hash}
                    if line["formation_input_hash"] != formation_hash or line["line_id"] != "trend-line-" + C.canonical_hash(identity)[:32]:
                        errors.append("line formation identity mismatch")
                    max_penetration = 0.0
                    for index in range(ia, activation + 1):
                        price = oracle(rows[index]["session_index"])
                        adverse = price - rows[index]["low"] if line["side"] == "support" else rows[index]["high"] - price
                        epsilon = scalar_eps(price, index, "touch")
                        max_penetration = max(max_penetration, adverse / epsilon)
                        if adverse > epsilon:
                            errors.append("formation penetration replay mismatch")
                    if not equal(line["formation_penetration"], max_penetration) or line["anchor_span"] != span:
                        errors.append("candidate rank geometry mismatch")
                    last_touch = max(lookup[bar_id][1]["session_index"] for bar_id in contacts)
                    distance = None if current is None or scalar_atr(len(rows) - 1) is None else abs(
                        current - rows[-1]["close"]) / scalar_eps(current, len(rows) - 1, "touch")
                    if line["latest_touch_index"] != last_touch or (distance is None) != (line["distance_score"] is None) or (
                        distance is not None and not equal(distance, line["distance_score"])):
                        errors.append("candidate rank contact/distance mismatch")
                    state, is_broken, count, last_break = "research_reference" if research else "active", False, 0, None
                    expected_events = []
                    for index in range(activation + 1, len(rows)):
                        if research:
                            break
                        price = oracle(rows[index]["session_index"])
                        if price is None:
                            state = "projection_invalid"
                            break
                        buffer = scalar_eps(price, index, "break")
                        signed = rows[index]["close"] - price
                        if line["side"] == "resistance":
                            signed = -signed
                        condition = signed > buffer if is_broken else signed < -buffer
                        if condition:
                            count += 1
                            next_state = ("reclaimed" if is_broken else "broken") if count == 2 else (
                                "reclaim_pending" if is_broken else "break_pending")
                            if count == 2:
                                if not is_broken:
                                    last_break = rows[index]["session_index"]
                                is_broken, count = not is_broken, 0
                        else:
                            count = 0
                            next_state = "broken" if is_broken else ("reclaimed" if state == "reclaimed" else "active")
                        if next_state != state:
                            expected_events.append((rows[index]["bar_id"], state, next_state, price, buffer))
                        state = next_state
                    actual_events = [event for event in snapshot["events"] if event["line_id"] == line["line_id"]]
                    if state != line["state"] or last_break != line["last_break_index"] or len(actual_events) != len(expected_events):
                        errors.append("line state replay mismatch")
                    for actual, expected_event in zip(actual_events, expected_events):
                        bar_id, prev, new, price, buffer = expected_event
                        if (actual["bar_id"], actual["prev_state"], actual["new_state"]) != (bar_id, prev, new):
                            errors.append("event transition replay mismatch")
                        if not equal(actual["line_price"], price) or not equal(actual["buffer"], buffer):
                            errors.append("event arithmetic replay mismatch")
                        source_row = lookup[bar_id][1]
                        expected_issue = max(C.aware_time(source_row["available_at"]), C.aware_time(source_row["fetched_at"]),
                                             C.aware_time(line["activation_asof"]))
                        if C.aware_time(actual["issued_at"]) != expected_issue or C.aware_time(actual["issued_at"]) > C.aware_time(cutoff):
                            errors.append("event issuance time differs from eligible source")
                        if (actual["effective_session"] != source_row["session_date"] or actual["close"] != source_row["close"]
                                or actual["axis"] != axis or actual["window"] != spec["bars"]):
                            errors.append("event observation metadata mismatch")
                        if actual["event_id"] != "trend-event-" + C.canonical_hash({key: value for key, value in actual.items() if key != "event_id"})[:32]:
                            errors.append("event identity mismatch")
                displayed = {line["line_id"]: line for line in analysis["lines"]}
                selected_event_ids = {event["event_id"] for event in snapshot["events"] if event["line_id"] in displayed}
                if {event["event_id"] for event in analysis["events"]} != selected_event_ids:
                    errors.append("display event selection differs from audit history")
                def rank_oracle(item: dict[str, Any]) -> tuple:
                    return (-item["touch_count"], -item["latest_touch_index"], -item["anchor_span"], item["formation_penetration"],
                            float("inf") if item["distance_score"] is None else item["distance_score"], item["line_id"])
                expected_selected = set()
                expected_broken = []
                for side in ("support", "resistance"):
                    eligible_states = {"research_reference"} if research else {"active", "break_pending", "reclaimed"}
                    active_candidates = sorted((line for line in candidates if line["side"] == side and line["state"] in eligible_states), key=rank_oracle)
                    for rank, line in enumerate(active_candidates[:settings["max_selected_per_side"]], 1):
                        expected_selected.add(line["line_id"])
                        if displayed.get(line["line_id"], {}).get("rank") != rank:
                            errors.append("primary line rank replay mismatch")
                    broken_candidates = sorted((line for line in candidates if line["side"] == side and line["state"] in {"broken", "reclaim_pending"}
                                                and line["current_price"] is not None), key=lambda item: (-(item["last_break_index"] or 0), *rank_oracle(item)))
                    for rank, line in enumerate(broken_candidates[:settings["max_recent_broken_per_side"]], 1):
                        expected_selected.add(line["line_id"])
                        expected_broken.append(line)
                        if displayed.get(line["line_id"], {}).get("rank") != rank:
                            errors.append("broken line rank replay mismatch")
                active_candidates = [line for line in candidates if line["state"] in eligible_states and line["current_price"] is not None]
                close = rows[-1]["close"]
                expected_down = sorted((line for line in active_candidates if line["current_price"] <= close), key=lambda item: (-item["current_price"], *rank_oracle(item)))[:3]
                expected_up = sorted((line for line in active_candidates if line["current_price"] > close), key=lambda item: (item["current_price"], *rank_oracle(item)))[:3]
                expected_selected.update(line["line_id"] for line in expected_down + expected_up)
                if set(displayed) != expected_selected:
                    errors.append("displayed candidate selection replay mismatch")
                for side, expected_levels in (("down", expected_down), ("up", expected_up), ("broken", expected_broken)):
                    if [line["line_id"] for line in analysis["borders"][side]] != [line["line_id"] for line in expected_levels]:
                        errors.append("nearest border ordering replay mismatch")
                for side in ("down", "up", "broken"):
                    for border in analysis["borders"][side]:
                        if border["line_id"] not in displayed or not equal(border["price"], displayed[border["line_id"]]["current_price"]):
                            errors.append("border lacks corresponding verified line")
                        elif border != {"line_id": displayed[border["line_id"]]["line_id"], "price": displayed[border["line_id"]]["current_price"],
                                        **{field: displayed[border["line_id"]][field] for field in ("state", "geometry_status", "touch_count", "side", "direction")}}:
                            errors.append("border state/geometry metadata replay mismatch")
    except (C.TrendlinesError, ValueError, KeyError, TypeError, IndexError, ArithmeticError) as exc:
        errors.append(str(exc))
    return {"ok": not errors, "errors": sorted(set(errors)), "replay": "independent_scalar_geometry_and_states" if replay else "metadata_only"}


independent_replay = verify_asset_snapshot
