"""Immutable current-vintage critical boundaries, separate from source geometry.

Every verified candidate is assessed; a price drawing is never promoted to an
approved feed, historical signal or investment probability. Existing diagonal
equations and IDs are preserved. Source archives and event ledgers are read only.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from statistics import median
from typing import Any

from . import contracts as C, engine as E, full_history as F, research as R, storage as S

ROOT = Path("data/trendlines_research_critical")
POLICY_RELATIVE = Path("data/contracts/trendlines_critical_v1.yaml")
POLICY_VERSION = "critical_v1"
TRANSPORT_CONTRACT = "trendlines_private_critical_transport_v1"
DETAIL_CONTRACT = "trendlines_private_critical_v1"
SNAPSHOT_PREFIX = "critical-snapshot-"
SNAPSHOT_RE = re.compile(re.escape(SNAPSHOT_PREFIX) + r"[0-9a-f]{64}\Z")
POLICY = {
    "schema_version": 1, "contract_id": "trendlines_private_critical_policy_v1",
    "policy_version": POLICY_VERSION, "publication_scope": "private_only", "official_forecast_write": False,
    "minimum_independent_contacts": 3, "maximum_distance_atr": 4.0, "maximum_distance_fraction": .2,
    "maximum_contact_age_sessions": 63, "duplicate_distance_atr": .5, "maximum_per_role": 1,
    "contact_independence": "disjoint_pivot_confirmation_windows",
    "independent_contact_tie_break": "latest_session_desc",
    "horizontal_center": "median_independent_pivot_prices",
    "horizontal_membership": "existing_per_pivot_touch_tolerance", "role_transition": "no_automatic_flip",
    "structural_state": "reconstructed_current_vintage_not_historical_signal",
    "rank_order": ["distance_asc", "latest_contact_desc", "independent_contacts_desc", "contact_error_asc", "boundary_id_asc"],
    "projection_sessions": {"exchange": 21, "crypto": 30}, "default_context_bars": 10,
    "empty_context_bars": 252, "comparison_tolerance": {"absolute": 1e-6, "relative": 1e-10},
}


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _hash(body):
    return {**body, "content_hash": C.canonical_hash(body)}


def _path(root, relative):
    return S.safe_path(Path(root), relative.as_posix())


def load_policy(root):
    value = C._yaml(Path(root), POLICY_RELATIVE)
    if value != POLICY:
        raise C.TrendlinesError("critical_policy_not_the_versioned_contract")
    return value


def _price(boundary, index):
    if boundary["kind"] == "horizontal_zone":
        return boundary["level"]
    return E._value(boundary, index)


def _scalar_price(boundary, index):
    if boundary["kind"] == "horizontal_zone":
        return boundary["level"]
    return F._scalar_price(boundary, index)


def _contact(pivot, rows, parameters):
    by_index = {row["session_index"]: row for row in rows}
    start, end = pivot["index"] - parameters["left"], pivot["index"] + parameters["right"]
    if any(index not in by_index for index in range(start, end + 1)):
        raise C.TrendlinesError("critical_pivot_confirmation_has_missing_session")
    if (by_index[pivot["index"]]["bar_id"] != pivot["bar_id"] or
            by_index[end]["session_date"] != pivot["confirmation_session"]):
        raise C.TrendlinesError("critical_pivot_source_binding_invalid")
    return {**{key: pivot[key] for key in ("session", "index", "price", "bar_id", "confirmed_at", "confirmation_session")},
            "confirmation_start_index": start, "confirmation_end_index": end}


def _independent(contacts):
    """Latest-first maximizes equal-width count and preserves recent contacts."""
    selected, start = [], math.inf
    for item in sorted(contacts, key=lambda item: (-item["index"], item["bar_id"])):
        if item["confirmation_end_index"] < start:
            selected.append(item)
            start = item["confirmation_start_index"]
    return list(reversed(selected))


def _states(boundary, rows, atr, asset, settings, activation_index, value=_price):
    """Current structural check only; no backdated operational events are issued."""
    broken, run, state, last = False, 0, "active", None
    breaks, reclaims = [], []
    for i, row in enumerate(rows):
        if row["session_index"] <= activation_index:
            continue
        if last is None or row["session_index"] != last + 1:
            run = 0
        last = row["session_index"]
        level = value(boundary, last)
        if level is None:
            return {"state": "projection_invalid", "break_sessions": breaks, "reclaim_sessions": reclaims}
        if atr[i] is None:
            run = 0
            state = "broken" if broken else "active"
            continue
        tolerance = E._epsilon(level, atr[i], asset, settings, "break")
        adverse = row["close"] < level - tolerance if boundary["role"] == "support" else row["close"] > level + tolerance
        favorable = row["close"] > level + tolerance if boundary["role"] == "support" else row["close"] < level - tolerance
        crossed = favorable if broken else adverse
        run = run + 1 if crossed else 0
        if run >= 2:
            broken = not broken
            (breaks if broken else reclaims).append(row["session_date"])
            run = 0
            state = "broken" if broken else "reclaimed"
        elif crossed:
            state = "reclaim_pending" if broken else "break_pending"
        else:
            state = "broken" if broken else ("reclaimed" if reclaims else "active")
    return {"state": state, "break_sessions": breaks, "reclaim_sessions": reclaims}


def _scalar_states(boundary, rows, atr, asset, settings):
    """Separate run parser; neither the production state machine nor epsilon."""
    mode, streak, prior = "intact", [], None
    broken_dates, reclaimed_dates = [], []
    result = "active"
    for position, row in enumerate(rows):
        if row["session_index"] <= boundary["activation_index"]:
            continue
        level = _scalar_price(boundary, row["session_index"])
        if level is None:
            return {"state": "projection_invalid", "break_sessions": broken_dates, "reclaim_sessions": reclaimed_dates}
        if prior != row["session_index"] - 1:
            streak = []
        prior = row["session_index"]
        if atr[position] is None:
            streak = []
            result = "broken" if mode == "broken" else "active"
            continue
        buffer = max(asset.get("tick_size", 0.0), settings["break"]["atr_multiple"] * atr[position],
                     settings["break"]["price_fraction"] * level, 1e-12 * level)
        distance = row["close"] - level
        signed = distance if boundary["role"] == "support" else -distance
        confirms = signed > buffer if mode == "broken" else signed < -buffer
        if not confirms:
            streak = []
            result = "broken" if mode == "broken" else ("reclaimed" if reclaimed_dates else "active")
            continue
        streak.append(row["session_date"])
        if len(streak) < 2:
            result = "reclaim_pending" if mode == "broken" else "break_pending"
            continue
        if mode == "intact":
            broken_dates.append(streak[-1])
            mode, result = "broken", "broken"
        else:
            reclaimed_dates.append(streak[-1])
            mode, result = "intact", "reclaimed"
        streak = []
    return {"state": result, "break_sessions": broken_dates, "reclaim_sessions": reclaimed_dates}


def _finish(boundary, contacts, rows, atr, asset, settings, parameters, policy, future):
    contacts = _independent(contacts)
    boundary["independent_contacts"] = contacts
    boundary["contacts"] = contacts
    boundary["contact_count"] = boundary["touch_count"] = len(contacts)
    boundary["latest_touch_index"] = max((item["index"] for item in contacts), default=-1)
    latest = rows[-1]
    price = _price(boundary, latest["session_index"])
    boundary["current_price"] = price
    by_index = {row["session_index"]: i for i, row in enumerate(rows)}
    errors = []
    for item in contacts:
        i = by_index[item["index"]]
        level = _price(boundary, item["index"])
        if level is None or atr[i] is None:
            raise C.TrendlinesError("critical_contact_price_or_atr_unavailable")
        error = abs(item["price"] - level) / E._epsilon(level, atr[i], asset, settings, "touch")
        if error > 1 + 1e-10:
            raise C.TrendlinesError("critical_contact_outside_tolerance")
        errors.append(error)
    boundary["contact_error"] = math.fsum(errors) / len(errors) if errors else 0.0
    state = _states(boundary, rows, atr, asset, settings, boundary["activation_index"])
    boundary["structural_state"] = state["state"]
    boundary["structural_review"] = {**state, "classification": "reconstructed_current_vintage", "historical_signals_available": False}
    boundary["geometry_status"] = "confirmed" if len(contacts) >= policy["minimum_independent_contacts"] else "candidate"
    boundary["state"] = "research_reference"
    boundary["distance"] = None if price is None else abs(price - latest["close"])
    reasons = []
    if len(contacts) < policy["minimum_independent_contacts"]:
        reasons.append("fewer_than_three_independent_confirmed_contacts")
    if latest["session_index"] - boundary["latest_touch_index"] > policy["maximum_contact_age_sessions"]:
        reasons.append("contact_older_than_63_sessions")
    if price is None:
        reasons.append("nonpositive_or_invalid_current_projection")
    else:
        if (boundary["role"] == "support" and price > latest["close"]) or (boundary["role"] == "resistance" and price < latest["close"]):
            reasons.append("original_role_on_wrong_side_of_final_close")
        if atr[-1] is None:
            reasons.append("latest_contiguous_atr14_unavailable")
        elif boundary["distance"] > policy["maximum_distance_atr"] * atr[-1]:
            reasons.append("distance_exceeds_four_atr")
        if boundary["distance"] > policy["maximum_distance_fraction"] * latest["close"]:
            reasons.append("distance_exceeds_twenty_percent")
    if state["state"] in {"broken", "reclaim_pending", "projection_invalid"}:
        reasons.append("original_role_not_reestablished")
    boundary["points"] = []
    first = boundary["first_anchor"]["index"]
    for row in rows:
        index = row["session_index"]
        if index in {first, boundary["second_anchor"]["index"], latest["session_index"]}:
            value = _price(boundary, index)
            if value is not None:
                boundary["points"].append({"session": row["session_date"], "index": index, "price": value, "future": False})
    boundary["projections"] = []
    # Only positive extension values are represented. No synthetic OHLC is made.
    for session in future:
        value = _price(boundary, session["index"])
        boundary["projections"].append({**session, "price": value, "status": "ready" if value is not None else "unavailable"})
        if value is not None and session["offset"] in {1, len(future)}:
            boundary["points"].append({**session, "price": value, "future": True})
    return boundary, reasons


def _diagonals(candidates, pivots, rows, atr, asset, settings, parameters, policy, future, axis):
    indexes = {row["session_index"]: i for i, row in enumerate(rows)}
    output = []
    for original in candidates:
        if original["axis"] != axis or original["window"] != parameters["bars"]:
            continue
        line = deepcopy(original)
        line.update({"kind": "diagonal", "boundary_id": line["line_id"], "role": line["side"]})
        line["activation_index"] = next(row["session_index"] for row in rows if row["session_date"] == line["activation_session"])
        contacts = []
        original_ids = {item["bar_id"] for item in original["contacts"]}
        for pivot in pivots:
            if pivot["side"] != line["role"] or pivot["bar_id"] not in original_ids:
                continue
            i = indexes[pivot["index"]]
            if atr[i] is None:
                raise C.TrendlinesError("critical_original_contact_atr_missing")
            contacts.append(_contact(pivot, rows, parameters))
        if {item["bar_id"] for item in contacts} != original_ids:
            raise C.TrendlinesError("critical_candidate_contacts_not_in_confirmed_pivots")
        output.append(_finish(line, contacts, rows, atr, asset, settings, parameters, policy, future))
    return output


def _zone_groups(pivots, rows, atr, asset, settings, parameters):
    """Enumerate tolerance-interval memberships, then fix median memberships.

    Testing interval endpoints and intervening cells avoids selecting an
    arbitrary clustering width or missing groups between pivot-price seeds.
    """
    positions = {row["session_index"]: i for i, row in enumerate(rows)}
    contacts = [_contact(p, rows, parameters) for p in pivots if atr[positions[p["index"]]] is not None]
    edges = set()
    fraction = settings["touch"]["price_fraction"]
    for item in contacts:
        floor = max(asset.get("tick_size", 0.0), settings["touch"]["atr_multiple"] * atr[positions[item["index"]]])
        edges.update((max(0.0, min(item["price"] - floor, item["price"] / (1 + fraction))),
                      max(item["price"] + floor, item["price"] / (1 - fraction))))
    ordered = sorted(edges)
    seeds = ordered + [(a + b) / 2 for a, b in zip(ordered, ordered[1:])]
    groups = {}
    for seed in seeds:
        seen = set()
        while True:
            members = [item for item in contacts if abs(item["price"] - seed) <= E._epsilon(
                seed, atr[positions[item["index"]]], asset, settings, "touch") + 1e-10]
            independent = _independent(members)
            ids = tuple(item["bar_id"] for item in independent)
            if not independent or ids in seen:
                break
            seen.add(ids)
            center = float(median(item["price"] for item in independent))
            updated = [item for item in contacts if abs(item["price"] - center) <= E._epsilon(
                center, atr[positions[item["index"]]], asset, settings, "touch") + 1e-10]
            if tuple(item["bar_id"] for item in _independent(updated)) == ids:
                groups[ids] = (center, independent)
                break
            seed = center
    return [groups[key] for key in sorted(groups)]


def _zones(pivots, rows, atr, asset, settings, parameters, policy, future, axis):
    output = []
    positions = {row["session_index"]: i for i, row in enumerate(rows)}
    for role in ("support", "resistance"):
        for center, contacts in _zone_groups([p for p in pivots if p["side"] == role], rows, atr, asset, settings, parameters):
            if len(contacts) < 2:
                continue
            first, second = contacts[0], contacts[1]
            activation = contacts[min(2, len(contacts) - 1)]["confirmation_end_index"]
            identity = {"asset_id": asset["asset_id"], "axis": axis, "window": parameters["bars"], "role": role,
                        "policy_version": policy["policy_version"], "contact_bar_ids": [p["bar_id"] for p in contacts], "level": center}
            sid = "critical-zone-" + C.canonical_hash(identity)[:32]
            boundary = {"line_id": sid, "boundary_id": sid, "kind": "horizontal_zone", "role": role, "side": role,
                        "axis": axis, "window": parameters["bars"], "direction": "horizontal", "level": center, "center": center,
                        "zone_low": min(p["price"] for p in contacts), "zone_high": max(p["price"] for p in contacts),
                        "first_anchor": first, "second_anchor": second, "coordinate_origin_index": first["index"],
                        "slope": 0.0, "intercept": math.log(center) if axis == "log" else center,
                        "activation_index": activation, "activation_session": next(r["session_date"] for r in rows if r["session_index"] == activation),
                        "activation_asof": max(p["confirmed_at"] for p in contacts[:3]), "anchor_span": second["index"] - first["index"]}
            formed = True
            for row in rows:
                index = row["session_index"]
                if not first["index"] <= index <= activation:
                    continue
                volatility = atr[positions[index]]
                if volatility is None:
                    formed = False
                    break
                tolerance = E._epsilon(center, volatility, asset, settings, "touch")
                adverse = center - row["low"] if role == "support" else row["high"] - center
                if adverse > tolerance:
                    formed = False
                    break
            complete = all(index in positions for index in range(first["index"], activation + 1))
            boundary, reasons = _finish(boundary, contacts, rows, atr, asset, settings, parameters, policy, future)
            if not complete:
                reasons.append("horizontal_missing_formation_sessions")
            if not formed:
                reasons.append("horizontal_formation_penetration")
            output.append((boundary, reasons))
    return output


def _rank(boundary):
    return (math.inf if boundary["distance"] is None else boundary["distance"], -boundary["latest_touch_index"],
            -boundary["contact_count"], boundary["contact_error"], boundary["boundary_id"])


def _view(analysis, candidates, rows, atr, asset, settings, parameters, policy, future, axis):
    pivots = analysis["pivots"]
    evaluated = _diagonals(candidates, pivots, rows, atr, asset, settings, parameters, policy, future, axis)
    evaluated += _zones(pivots, rows, atr, asset, settings, parameters, policy, future, axis)
    eligible = sorted((boundary for boundary, reasons in evaluated if not reasons), key=_rank)
    representatives, selected = [], []
    outcomes = {boundary["boundary_id"]: list(reasons) for boundary, reasons in evaluated}
    for boundary in eligible:
        overlap = next((item for item in representatives if abs(item["current_price"] - boundary["current_price"]) <= policy["duplicate_distance_atr"] * atr[-1]), None)
        if overlap:
            outcomes[boundary["boundary_id"]] = ["overlaps_nearer_representative_within_half_atr"]
            continue
        representatives.append(boundary)
        if any(item["role"] == boundary["role"] for item in selected):
            outcomes[boundary["boundary_id"]] = ["one_boundary_per_role_display_limit"]
        else:
            selected.append(boundary)
    counts = {}
    audit = []
    for boundary, _reasons in evaluated:
        reasons = outcomes[boundary["boundary_id"]]
        for reason in reasons:
            counts[reason] = counts.get(reason, 0) + 1
        audit.append({"boundary_id": boundary["boundary_id"], "line_id": boundary["line_id"], "kind": boundary["kind"],
                      "role": boundary["role"], "current_price": boundary["current_price"], "contact_count": boundary["contact_count"],
                      "latest_touch_index": boundary["latest_touch_index"], "contact_error": boundary["contact_error"],
                      "structural_review": boundary["structural_review"], "reasons": reasons,
                      "independent_contacts": boundary["independent_contacts"]})
    baseline_ids = sorted(line["line_id"] for line in analysis["lines"])
    selected_ids = sorted(line["boundary_id"] for line in selected)
    # Explicitly record every old displayed diagonal and its exact rejection.
    by_id = {item["boundary_id"]: item for item in audit}
    examples = [by_id[line_id] for line_id in baseline_ids if line_id in by_id and by_id[line_id]["reasons"]]
    examples.sort(key=lambda item: (math.inf if item["current_price"] is None else abs(item["current_price"] - rows[-1]["close"]), item["boundary_id"]))
    examples = [{key: item[key] for key in ("boundary_id", "kind", "role", "current_price", "contact_count", "latest_touch_index", "reasons")} for item in examples]
    view = {"status": "ready" if selected else "no_verified_boundaries", "axis": axis, "window": parameters["bars"],
            "parameters": deepcopy(parameters), "boundaries": selected, "candidate_count": len(evaluated),
            "diagonal_candidate_count": sum(item["kind"] == "diagonal" for item, _ in evaluated),
            "horizontal_candidate_count": sum(item["kind"] == "horizontal_zone" for item, _ in evaluated),
            "eligible_count": len(eligible), "rejection_counts": counts, "rejection_examples": examples,
            "projection_sessions": future, "shadow": {"classification": "display_selection_not_model_promotion",
                "baseline_line_ids": baseline_ids, "selected_boundary_ids": selected_ids,
                "removed_line_ids": sorted(set(baseline_ids) - set(selected_ids)),
                "added_boundary_ids": sorted(set(selected_ids) - set(baseline_ids)),
                "same_input_hash": C.canonical_hash(rows), "source_geometry_unchanged": True,
                "probability_and_official_ledgers_unchanged": True}}
    return view, audit


def _future(rows, asset, policy):
    count = policy["projection_sessions"]["crypto" if asset["kind"] == "crypto" else "exchange"]
    last = rows[-1]
    end = (date.fromisoformat(last["session_date"]) + timedelta(days=120)).isoformat()
    schedule = C.session_schedule(asset["calendar_id"], rows[0]["session_date"], end)
    if schedule[last["session_index"]][0] != last["session_date"]:
        raise C.TrendlinesError("critical_calendar_coordinate_binding_invalid")
    return [{"offset": offset, "index": last["session_index"] + offset, "session": schedule[last["session_index"] + offset][0]}
            for offset in range(1, count + 1)]


def _calculate(source, full, policy):
    rows = full["bars"]
    settings, asset = source["config"], source["asset"]
    if (full["source_snapshot_id"] != source["snapshot_id"] or C.canonical_hash(rows) != full["input_hash"]):
        raise C.TrendlinesError("critical_full_input_source_binding_invalid")
    atr = E._atr(rows, settings["atr"]["period"], segmented=True)
    future = _future(rows, asset, policy)
    analyses, audits = {}, {}
    for axis in ("linear", "log"):
        analyses[axis], audits[axis] = {}, {}
        for window in ("63", "252", "756", "full"):
            if window == "full":
                analysis, candidates, parameters = full["analyses"][axis]["full"], full["audit_lines"], full["full_config"]["parameters"]
            else:
                analysis, candidates, parameters = source["engine_snapshot"]["analyses"][axis][window], source["engine_snapshot"]["audit_lines"], settings["windows"][window]
            analyses[axis][window], audits[axis][window] = _view(analysis, candidates, rows, atr, asset, settings, parameters, policy, future, axis)
    validation = _scalar_verify(rows, asset, settings, analyses, atr, future)
    validation.update(_scalar_selection_verify(source, full, analyses, audits, rows, atr, policy))
    return {"policy": deepcopy(policy), "policy_sha256": C.canonical_hash(policy), "input_hash": C.canonical_hash(rows),
            "reference_close": rows[-1]["close"], "reference_session": rows[-1]["session_date"],
            "reference_index": rows[-1]["session_index"], "atr14": atr[-1], "projection_sessions": future,
            "analyses": analyses, "candidate_audits": audits,
            "independent_validation": validation}


def _scalar_verify(rows, asset, settings, analyses, actual_atr, future):
    """Independent arithmetic and disjoint-window oracle for selected boundaries."""
    ranges, expected_atr = [], [None]
    for previous, row in zip(rows, rows[1:]):
        if row["session_index"] != previous["session_index"] + 1:
            ranges = []
            expected_atr.append(None)
        else:
            ranges.append(max(row["high"] - row["low"], abs(row["high"] - previous["close"]), abs(row["low"] - previous["close"])))
            expected_atr.append(math.fsum(ranges[-14:]) / 14 if len(ranges) >= 14 else None)
    for actual, expected in zip(actual_atr, expected_atr):
        F._near(actual, expected, "critical_atr")
    checked, contacts_checked = 0, 0
    by_index = {row["session_index"]: i for i, row in enumerate(rows)}
    for axis, windows in analyses.items():
        for view in windows.values():
            roles = []
            for boundary in view["boundaries"]:
                checked += 1
                roles.append(boundary["role"])
                if boundary["axis"] != axis or boundary["contact_count"] < 3:
                    raise C.TrendlinesError("critical_scalar_axis_or_contact_count")
                contacts = boundary["independent_contacts"]
                for previous, current in zip(contacts, contacts[1:]):
                    if previous["confirmation_end_index"] >= current["confirmation_start_index"]:
                        raise C.TrendlinesError("critical_scalar_overlapping_contact_windows")
                for contact in contacts:
                    contacts_checked += 1
                    row = rows[by_index[contact["index"]]]
                    if row["bar_id"] != contact["bar_id"] or row["session_date"] != contact["session"]:
                        raise C.TrendlinesError("critical_scalar_contact_source_binding")
                    column = "low" if boundary["role"] == "support" else "high"
                    F._near(contact["price"], row[column], "critical_contact_price")
                    i = by_index[contact["index"]]
                    before, after = view["parameters"]["left"], view["parameters"]["right"]
                    price = row[column]
                    valid = (all(price < item[column] for item in rows[i-before:i]) and all(price <= item[column] for item in rows[i+1:i+after+1])
                             if boundary["role"] == "support" else
                             all(price > item[column] for item in rows[i-before:i]) and all(price >= item[column] for item in rows[i+1:i+after+1]))
                    if not valid:
                        raise C.TrendlinesError("critical_scalar_contact_not_confirmed_pivot")
                if boundary["kind"] == "horizontal_zone":
                    F._near(boundary["level"], median(p["price"] for p in contacts), "critical_zone_median")
                for point in boundary["points"] + boundary["projections"]:
                    F._near(point["price"], _scalar_price(boundary, point["index"]), "critical_equation")
                F._near(boundary["current_price"], _scalar_price(boundary, rows[-1]["session_index"]), "critical_current_price")
                if _scalar_states(boundary, rows, expected_atr, asset, settings) != {
                        key: boundary["structural_review"][key] for key in ("state", "break_sessions", "reclaim_sessions")}:
                    raise C.TrendlinesError("critical_scalar_structural_state")
            if len(roles) > 2 or len(roles) != len(set(roles)):
                raise C.TrendlinesError("critical_scalar_more_than_one_per_role")
    if [item["offset"] for item in future] != list(range(1, len(future) + 1)):
        raise C.TrendlinesError("critical_scalar_future_offsets")
    return {"status": "passed", "checked_boundaries": checked, "checked_contacts": contacts_checked,
            "atr14_simple_mean": True, "price_tolerance": {"absolute": 1e-6, "relative": 1e-10}}


def _scalar_zone_memberships(pivots, rows, atr, asset, settings, parameters):
    """Independent median-seed enumeration for complete horizontal candidates.

    A median is a member price or the midpoint of two member prices. Enumerate
    those values directly, rather than the producer's tolerance interval cells.
    """
    positions = {row["session_index"]: i for i, row in enumerate(rows)}
    usable = sorted((pivot for pivot in pivots if atr[positions[pivot["index"]]] is not None),
                    key=lambda pivot: (-pivot["index"], pivot["bar_id"]))
    centers = {float(p["price"]) for p in usable}
    centers.update((a["price"] + b["price"]) / 2 for i, a in enumerate(usable) for b in usable[i+1:])
    groups = {}
    for center in centers:
        member, previous_start = [], math.inf
        for pivot in usable:
            buffer = max(asset.get("tick_size", 0.0), settings["touch"]["atr_multiple"] * atr[positions[pivot["index"]]],
                         settings["touch"]["price_fraction"] * center, 1e-12 * center)
            if abs(pivot["price"] - center) > buffer + 1e-10:
                continue
            start, stop = pivot["index"] - parameters["left"], pivot["index"] + parameters["right"]
            if stop < previous_start:
                member.append(pivot)
                previous_start = start
        if len(member) < 2:
            continue
        price_list = sorted(p["price"] for p in member)
        n = len(price_list)
        actual_median = price_list[n//2] if n % 2 else (price_list[n//2-1] + price_list[n//2]) / 2
        if actual_median == center:
            groups[tuple(p["bar_id"] for p in reversed(member))] = center
    return groups


def _scalar_selection_verify(source, full, analyses, audits, rows, atr, policy):
    diagonal_count, horizontal_count = 0, 0
    exclusion = {"overlaps_nearer_representative_within_half_atr", "one_boundary_per_role_display_limit"}
    for axis, windows in analyses.items():
        for window, view in windows.items():
            audit = audits[axis][window]
            originals = full["audit_lines"] if window == "full" else source["engine_snapshot"]["audit_lines"]
            expected = {line["line_id"] for line in originals if line["axis"] == axis and line["window"] == view["parameters"]["bars"]}
            actual = [item["line_id"] for item in audit if item["kind"] == "diagonal"]
            if len(actual) != len(set(actual)) or set(actual) != expected:
                raise C.TrendlinesError("critical_scalar_diagonal_candidate_pool_incomplete")
            diagonal_count += len(actual)
            analysis = full["analyses"][axis]["full"] if window == "full" else source["engine_snapshot"]["analyses"][axis][window]
            for role in ("support", "resistance"):
                expected_groups = _scalar_zone_memberships([p for p in analysis["pivots"] if p["side"] == role],
                                                          rows, atr, source["asset"], source["config"], view["parameters"])
                actual_groups = {tuple(p["bar_id"] for p in item["independent_contacts"]): item for item in audit
                                 if item["kind"] == "horizontal_zone" and item["role"] == role}
                if set(actual_groups) != set(expected_groups):
                    raise C.TrendlinesError("critical_scalar_horizontal_candidate_pool_incomplete")
                for ids, center in expected_groups.items():
                    F._near(actual_groups[ids]["current_price"], center, "critical_horizontal_median")
                horizontal_count += len(actual_groups)
            eligible = [item for item in audit if not set(item["reasons"]) - exclusion]
            # Deliberately spell out the scalar rank; do not call _rank.
            eligible.sort(key=lambda item: (abs(item["current_price"] - rows[-1]["close"]), -item["latest_touch_index"],
                                          -item["contact_count"], item["contact_error"], item["boundary_id"]))
            centers, roles, expected_ids = [], set(), []
            for item in eligible:
                if any(abs(item["current_price"] - prior) <= .5 * atr[-1] for prior in centers):
                    if item["reasons"] != ["overlaps_nearer_representative_within_half_atr"]:
                        raise C.TrendlinesError("critical_scalar_duplicate_representative")
                    continue
                centers.append(item["current_price"])
                if item["role"] in roles:
                    if item["reasons"] != ["one_boundary_per_role_display_limit"]:
                        raise C.TrendlinesError("critical_scalar_role_display_limit")
                    continue
                roles.add(item["role"])
                expected_ids.append(item["boundary_id"])
                if item["reasons"]:
                    raise C.TrendlinesError("critical_scalar_selected_candidate_rejected")
            if [line["boundary_id"] for line in view["boundaries"]] != expected_ids:
                raise C.TrendlinesError("critical_scalar_selection_rank_differs")
            if view["candidate_count"] != len(audit):
                raise C.TrendlinesError("critical_scalar_audit_count_differs")
    return {"checked_diagonal_candidates": diagonal_count, "checked_horizontal_candidates": horizontal_count,
            "complete_candidate_pools": True, "independent_rank_and_overlap_check": True}


def _latest(root):
    path = _path(root, ROOT / "latest.json")
    if not path.is_file():
        return {"assets": {}}
    pointer = R._checked(path)
    if (pointer.get("contract_id") != "trendlines_private_critical_latest_v1" or pointer.get("schema_version") != 1
            or not isinstance(pointer.get("assets"), dict) or set(pointer["assets"]) - set(R.SYMBOLS)
            or path.read_bytes() != S.encode(pointer)):
        raise C.TrendlinesError("critical_latest_contract_invalid")
    return pointer


def _sources(root, asset_id, now=None):
    source, pointer = F._source(root, asset_id, now)
    if source is None:
        return None, None, None, None
    full_pointer = F._latest(root)["assets"].get(asset_id)
    if full_pointer is None:
        raise C.TrendlinesError("critical_verified_full_snapshot_missing")
    full, pinned_source = F._read_snapshot(root, full_pointer["snapshot_id"])
    if pinned_source != source:
        raise C.TrendlinesError("critical_full_snapshot_not_current_source")
    return source, pointer, full, full_pointer


def _read_snapshot(root, sid, now=None):
    if not isinstance(sid, str) or not SNAPSHOT_RE.fullmatch(sid):
        raise C.TrendlinesError("critical_snapshot_id_invalid")
    path = _path(root, ROOT / "snapshots" / (sid + ".json"))
    snapshot = R._checked(path)
    identity = {key: value for key, value in snapshot.items() if key not in {"content_hash", "snapshot_id"}}
    if (snapshot.get("snapshot_id") != sid or sid != SNAPSHOT_PREFIX + C.canonical_hash(identity)
            or path.read_bytes() != S.encode(snapshot) or snapshot.get("contract_id") != "trendlines_private_critical_snapshot_v1"
            or snapshot.get("publication_scope") != "private_only" or snapshot.get("official_forecast_write") is not False
            or snapshot.get("policy") != POLICY or snapshot.get("verified_source") is not False
            or snapshot.get("historical_signals_available") is not False):
        raise C.TrendlinesError("critical_snapshot_identity_or_policy_invalid")
    full, source = F._read_snapshot(root, snapshot["source_full_snapshot_id"])
    source_path = S.safe_path(root, snapshot["source_snapshot_path"])
    if (source["snapshot_id"] != snapshot["source_snapshot_id"] or source["asset_id"] != snapshot["asset_id"]
            or _sha(source_path.read_bytes()) != snapshot["source_archive_sha256"]
            or full["content_hash"] != snapshot["source_full_content_hash"]
            or source["engine_snapshot"]["content_hash"] != snapshot["source_engine_content_hash"]
            or S.aware_time(source["capture_asof"]) > S.aware_time(now)):
        raise C.TrendlinesError("critical_source_binding_or_cutoff_invalid")
    manifest = _path(root, F.ROOT / "exports" / full["snapshot_id"] / "manifest.json")
    manifest_envelope = S.read_json(manifest)
    if (manifest_envelope != F._exports(full)[0] or manifest_envelope["payload_sha256"] != snapshot["full_manifest_payload_sha256"]):
        raise C.TrendlinesError("critical_full_manifest_binding_invalid")
    return snapshot, source, full


def _export(snapshot):
    body = {key: deepcopy(snapshot[key]) for key in ("asset_id", "snapshot_id", "source_snapshot_id", "source_full_snapshot_id",
        "source_engine_content_hash", "source_full_content_hash", "full_manifest_payload_sha256", "as_of", "policy_version",
        "policy_sha256", "reference_close", "reference_session", "reference_index", "atr14", "projection_sessions", "analyses",
        "independent_validation", "historical_signals_available", "official_forecast_write", "verified_source")}
    body.update({"schema_version": 1, "contract_id": DETAIL_CONTRACT, "publication_scope": "private_only",
                 "rights_status": R.RIGHTS, "source_context": R.CONTEXT})
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(raw.encode("utf-8")) > R.MAX_PRIVATE_PAYLOAD_BYTES:
        raise C.TrendlinesError("critical_payload_exceeds_256KiB")
    envelope = {"schema_version": 1, "contract_id": TRANSPORT_CONTRACT, "publication_scope": "private_only",
                "asset_id": body["asset_id"], "snapshot_id": body["snapshot_id"], "payload_json": raw,
                "payload_sha256": _sha(raw.encode("utf-8"))}
    if len(S.encode(envelope)) > R.MAX_PRIVATE_ENVELOPE_BYTES:
        raise C.TrendlinesError("critical_envelope_exceeds_512KiB")
    return envelope


def decode_envelope(envelope, expected_contract=None):
    try:
        if (not isinstance(envelope, dict) or set(envelope) != {"schema_version", "contract_id", "publication_scope", "asset_id", "snapshot_id", "payload_json", "payload_sha256"}
                or type(envelope["schema_version"]) is not int or envelope["schema_version"] != 1
                or envelope["contract_id"] != TRANSPORT_CONTRACT or envelope["publication_scope"] != "private_only"
                or envelope["asset_id"] not in R.SYMBOLS or not SNAPSHOT_RE.fullmatch(envelope["snapshot_id"])
                or not isinstance(envelope["payload_json"], str) or len(S.encode(envelope)) > R.MAX_PRIVATE_ENVELOPE_BYTES):
            raise C.TrendlinesError("critical_transport_contract_invalid")
        raw = envelope["payload_json"].encode("utf-8")
        if len(raw) > R.MAX_PRIVATE_PAYLOAD_BYTES or _sha(raw) != envelope["payload_sha256"]:
            raise C.TrendlinesError("critical_transport_payload_binding_invalid")
        def unique(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise C.TrendlinesError("critical_transport_duplicate_key")
                value[key] = item
            return value
        body = json.loads(envelope["payload_json"], object_pairs_hook=unique,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        if (body.get("contract_id") != DETAIL_CONTRACT or (expected_contract is not None and expected_contract != DETAIL_CONTRACT)
                or type(body.get("schema_version")) is not int or body.get("schema_version") != 1 or body.get("publication_scope") != "private_only"
                or body.get("asset_id") != envelope["asset_id"] or body.get("snapshot_id") != envelope["snapshot_id"]
                or body.get("policy_version") != POLICY_VERSION or body.get("official_forecast_write") is not False
                or body.get("verified_source") is not False or body.get("historical_signals_available") is not False):
            raise C.TrendlinesError("critical_transport_body_binding_invalid")
        if (body.get("policy_sha256") != C.canonical_hash(POLICY)
                or not C._finite_number(body.get("reference_close")) or body["reference_close"] <= 0
                or type(body.get("reference_index")) is not int or body["reference_index"] < 0
                or date.fromisoformat(body["reference_session"]).isoformat() != body["reference_session"]
                or (body.get("atr14") is not None and (not C._finite_number(body["atr14"]) or body["atr14"] < 0))
                or not F.SNAPSHOT_RE.fullmatch(body["source_full_snapshot_id"])
                or not re.fullmatch(r"research-snapshot-[0-9a-f]{64}", body["source_snapshot_id"])
                or any(not C.SHA256.fullmatch(body[key]) for key in ("source_engine_content_hash", "source_full_content_hash", "full_manifest_payload_sha256"))
                or set(body.get("analyses", {})) != {"linear", "log"}
                or any(set(windows) != {"63", "252", "756", "full"} for windows in body["analyses"].values())):
            raise C.TrendlinesError("critical_transport_reference_or_source_invalid")
        cutoff = C.aware_time(body["as_of"])
        future = body["projection_sessions"]
        count = 30 if body["asset_id"] == "bitcoin" else 21
        if (len(future) != count or any(set(item) != {"offset", "index", "session"} or
                item["offset"] != offset or item["index"] != body["reference_index"] + offset or
                date.fromisoformat(item["session"]).isoformat() != item["session"]
                for offset, item in enumerate(future, 1)) or
                not all(a["session"] < b["session"] for a, b in zip(future, future[1:]))):
            raise C.TrendlinesError("critical_transport_future_session_map_invalid")
        for axis, windows in body["analyses"].items():
            for view in windows.values():
                boundaries = view["boundaries"]
                if len(boundaries) > 2 or len({item["role"] for item in boundaries}) != len(boundaries):
                    raise C.TrendlinesError("critical_transport_role_display_limit")
                for item in boundaries:
                    if (item["axis"] != axis or item["kind"] not in {"diagonal", "horizontal_zone"}
                            or item["role"] not in {"support", "resistance"}
                            or item["contact_count"] != len(item["independent_contacts"]) or item["contact_count"] < 3
                            or item["structural_state"] in {"broken", "reclaim_pending", "projection_invalid"}
                            or item["latest_touch_index"] != max(p["index"] for p in item["independent_contacts"])
                            or body["reference_index"] - item["latest_touch_index"] > 63
                            or body["atr14"] is None or abs(item["current_price"] - body["reference_close"]) > 4 * body["atr14"]
                            or abs(item["current_price"] - body["reference_close"]) > .2 * body["reference_close"]
                            or (item["role"] == "support" and item["current_price"] > body["reference_close"])
                            or (item["role"] == "resistance" and item["current_price"] < body["reference_close"])):
                        raise C.TrendlinesError("critical_transport_boundary_policy_invalid")
                    for contact in item["independent_contacts"]:
                        if C.aware_time(contact["confirmed_at"]) > cutoff or contact["confirmation_end_index"] > body["reference_index"]:
                            raise C.TrendlinesError("critical_transport_future_contact")
                    for before, after in zip(item["independent_contacts"], item["independent_contacts"][1:]):
                        if before["confirmation_end_index"] >= after["confirmation_start_index"]:
                            raise C.TrendlinesError("critical_transport_overlapping_contact_windows")
                    F._near(item["current_price"], _scalar_price(item, body["reference_index"]), "critical_transport_equation")
        return body
    except C.TrendlinesError:
        raise
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, AttributeError) as exc:
        raise C.TrendlinesError("critical_transport_json_invalid") from exc


def verify(root, *, asset_id=None, replay=True, now=None):
    root = Path(root)
    audit = F.verify(root, replay=replay, now=now)
    if not audit["ok"]:
        return {"ok": False, "errors": audit["errors"], "snapshots": 0, "replay": replay}
    cache = R._ACTIVE_REPLAY_CACHE.get() if replay else None
    functions = (_calculate, _view, _diagonals, _zones, _zone_groups, _finish, _independent, _contact, _states, _scalar_states,
                 _scalar_selection_verify, _scalar_zone_memberships,
                 _rank, _future, _scalar_verify, _scalar_price, E._value, E._atr, E._epsilon, F._scalar_price, C.session_schedule)
    pending, snapshots = {}, {}
    try:
        policy = load_policy(root)
        pointer = _latest(root)
        for path in sorted(_path(root, ROOT / "snapshots").glob("*.json")):
            # An unrelated asset's newer capture is not an input to this
            # asset's PIT replay. Check that evidence against wall-clock time.
            scoped_asset = R._checked(path)["asset_id"]
            cutoff = now if R._replay_includes(scoped_asset) else None
            snapshot, source, full = _read_snapshot(root, path.stem, cutoff)
            if snapshot["asset_id"] != scoped_asset:
                raise C.TrendlinesError("critical_snapshot_changed_during_scope_check")
            key = ("critical", str(root.resolve()), snapshot["content_hash"], _sha(path.read_bytes()), snapshot["source_archive_sha256"],
                   snapshot["source_full_content_hash"], tuple(id(f) for f in functions))
            if replay and R._replay_includes(snapshot["asset_id"]) and (cache is None or not cache._contains(key, functions)):
                computation = _calculate(source, full, policy)
                if any(snapshot.get(field) != value for field, value in computation.items()):
                    raise C.TrendlinesError("critical_replay_differs_from_verified_candidates")
                pending[key] = functions
            export_path = _path(root, ROOT / "exports" / snapshot["snapshot_id"] / "detail.json")
            if export_path.read_bytes() != S.encode(_export(snapshot)):
                raise C.TrendlinesError("critical_export_binding_invalid")
            snapshots[snapshot["snapshot_id"]] = {field: snapshot[field] for field in ("snapshot_id", "asset_id")}
        for asset, row in pointer["assets"].items():
            snapshot = snapshots[row["snapshot_id"]]
            expected_path = ROOT / "snapshots" / (snapshot["snapshot_id"] + ".json")
            expected_export = ROOT / "exports" / snapshot["snapshot_id"] / "detail.json"
            if (snapshot["asset_id"] != asset or row["snapshot_path"] != expected_path.as_posix()
                    or row["detail_path"] != expected_export.as_posix()
                    or row["snapshot_sha256"] != _sha(_path(root, expected_path).read_bytes())
                    or row["detail_sha256"] != _sha(_path(root, expected_export).read_bytes())):
                raise C.TrendlinesError("critical_latest_snapshot_binding_invalid")
        if cache is not None:
            cache._remember(pending)
        return R._scope_report({"ok": True, "errors": [], "snapshots": len(snapshots), "replay": replay})
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {"ok": False, "errors": [str(exc)], "snapshots": len(snapshots), "replay": replay}


def refresh(root, asset_id, now=None):
    R._check_replay_asset(asset_id)
    root = Path(root)
    with S.writer_lock(root):
        audit = verify(root, replay=True, now=now)
        if not audit["ok"]:
            raise C.TrendlinesError("critical_existing_integrity_failed: " + "; ".join(audit["errors"]))
        policy = load_policy(root)
        source, source_pointer, full, _full_pointer = _sources(root, asset_id, now)
        if source is None:
            return {"changed": False, "asset_id": asset_id, "status": "hold", "reason_codes": ["missing_research_ohlc"]}
        pointer = _latest(root)
        prior = pointer["assets"].get(asset_id)
        if prior:
            previous, _source, _full = _read_snapshot(root, prior["snapshot_id"], now)
            if previous["source_snapshot_id"] == source["snapshot_id"] and previous["source_full_snapshot_id"] == full["snapshot_id"]:
                return {"changed": False, "asset_id": asset_id, "status": "ready", "critical_snapshot_id": previous["snapshot_id"],
                        "detail_path": prior["detail_path"], "selected_counts": {axis: {window: len(view["boundaries"]) for window, view in views.items()} for axis, views in previous["analyses"].items()}}
        computation = _calculate(source, full, policy)
        manifest = F._exports(full)[0]
        body = {"schema_version": 1, "contract_id": "trendlines_private_critical_snapshot_v1", "asset_id": asset_id,
                "publication_scope": "private_only", "official_forecast_write": False, "verified_source": False,
                "historical_signals_available": False, "policy_version": POLICY_VERSION, "as_of": source["capture_asof"],
                "source_snapshot_id": source["snapshot_id"], "source_snapshot_path": source_pointer["snapshot_path"],
                "source_archive_sha256": source_pointer["snapshot_sha256"], "source_full_snapshot_id": full["snapshot_id"],
                "source_full_content_hash": full["content_hash"], "source_engine_content_hash": source["engine_snapshot"]["content_hash"],
                "full_manifest_payload_sha256": manifest["payload_sha256"], **computation}
        body["snapshot_id"] = SNAPSHOT_PREFIX + C.canonical_hash(body)
        snapshot = _hash(body)
        envelope = _export(snapshot)
        decode_envelope(envelope)
        # All source evidence and current pointer bindings are rechecked directly
        # before publication. No caller-provided "verified" flag can bypass this.
        current_source, current_pointer, current_full, _ = _sources(root, asset_id, now)
        if current_source != source or current_pointer != source_pointer or current_full != full:
            raise C.TrendlinesError("critical_source_changed_during_shadow")
        source_audit = R.verify(root, replay=True)
        if not source_audit["ok"]:
            raise C.TrendlinesError("critical_source_integrity_failed_before_publication")
        snapshot_path = ROOT / "snapshots" / (snapshot["snapshot_id"] + ".json")
        export_path = ROOT / "exports" / snapshot["snapshot_id"] / "detail.json"
        S.atomic_json(_path(root, export_path), envelope, immutable=True)
        S.atomic_json(_path(root, snapshot_path), snapshot, immutable=True)
        final_source, final_pointer, final_full, _ = _sources(root, asset_id, now)
        if final_source != source or final_pointer != source_pointer or final_full != full:
            raise C.TrendlinesError("critical_source_changed_before_pointer_exchange")
        assets = deepcopy(pointer["assets"])
        assets[asset_id] = {"snapshot_id": snapshot["snapshot_id"], "snapshot_path": snapshot_path.as_posix(),
                            "snapshot_sha256": _sha(S.encode(snapshot)), "detail_path": export_path.as_posix(),
                            "detail_sha256": _sha(S.encode(envelope))}
        S.atomic_json(_path(root, ROOT / "latest.json"), _hash({"schema_version": 1,
                      "contract_id": "trendlines_private_critical_latest_v1", "assets": assets}))
        return {"changed": True, "asset_id": asset_id, "status": "ready", "critical_snapshot_id": snapshot["snapshot_id"],
                "source_snapshot_id": source["snapshot_id"], "detail_path": export_path.as_posix(),
                "selected_counts": {axis: {window: len(view["boundaries"]) for window, view in views.items()} for axis, views in snapshot["analyses"].items()},
                "validation": snapshot["independent_validation"]}


def load_detail(root, asset_id, now=None):
    """Cheap immutable source-proof read; collection and calculation stay in batch."""
    root = Path(root)
    if asset_id not in R.SYMBOLS:
        raise C.TrendlinesError("critical_asset_has_no_research_source")
    load_policy(root)
    row = _latest(root)["assets"].get(asset_id)
    if row is None:
        return None
    snapshot, source, full = _read_snapshot(root, row["snapshot_id"], now)
    latest_source, _pointer, latest_full, _ = _sources(root, asset_id, now)
    if latest_source != source or latest_full != full:
        raise C.TrendlinesError("critical_snapshot_is_not_current_source")
    path = S.safe_path(root, row["detail_path"])
    expected = ROOT / "exports" / snapshot["snapshot_id"] / "detail.json"
    envelope = S.read_json(path)
    if (row["detail_path"] != expected.as_posix() or envelope != _export(snapshot)
            or _sha(path.read_bytes()) != row["detail_sha256"]
            or row["snapshot_sha256"] != _sha(_path(root, ROOT / "snapshots" / (snapshot["snapshot_id"] + ".json")).read_bytes())):
        raise C.TrendlinesError("critical_export_latest_binding_invalid")
    decode_envelope(envelope)
    return envelope
