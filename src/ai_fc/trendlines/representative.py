"""Three descriptive structures from immutable finalized OHLC, never forecasts.

This additive read model does not weaken the critical-boundary contract, move an
OLS intercept to the last close, manufacture contacts, or issue historical
events. Its bounded replay reparses the pinned original capture and independently
checks its own arithmetic; unrelated historical curve snapshots are not replayed.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path

from . import contracts as C, engine as E, full_history as F, research as R, storage as S

ROOT = Path("data/trendlines_research_representative")
POLICY_RELATIVE = Path("data/contracts/trendlines_representative_v1.yaml")
POLICY_VERSION = "representative_v1"
TRANSPORT_CONTRACT = "trendlines_private_representative_transport_v1"
DETAIL_CONTRACT = "trendlines_private_representative_v1"
SNAPSHOT_PREFIX = "representative-snapshot-"
SNAPSHOT_RE = re.compile(re.escape(SNAPSHOT_PREFIX) + r"[0-9a-f]{64}\Z")
SLOTS = ("regression_200", "current_structure", "major_structure")
POLICY = {
    "schema_version": 1, "contract_id": "trendlines_private_representative_policy_v1",
    "policy_version": POLICY_VERSION, "publication_scope": "private_only",
    "official_forecast_write": False, "verified_boundary": False,
    "regression": {"observations": 200, "method": "ordinary_least_squares",
                   "response": {"linear": "close", "log": "natural_log_close"},
                   "coordinates": "original_calendar_session_index", "close_alignment": "forbidden"},
    "current": {"observations": 63, "left": 3, "right": 3, "minimum_anchor_gap": 10,
                "maximum_anchor_age": 63, "maximum_distance_atr": 4.0, "maximum_distance_fraction": .2,
                "fallback_observations": 63, "rank": ["second_anchor_desc", "first_anchor_desc", "line_id_asc"]},
    "major": {"left": 10, "right": 10, "minimum_anchor_gap": 60, "maximum_second_anchor_age": 252,
              "prominence_window": 756, "top_prominence_per_side": 3,
              "prominence": "minimum_left_right_reversal_divided_by_pivot_atr14",
              "dominant_cycle_extremum": "same_side_extreme_price_in_latest_756_sessions_latest_tie",
              "maximum_distance_atr": 8.0, "maximum_distance_fraction": .5,
              "minimum_current_price_fraction": .5, "maximum_current_price_fraction": 1.5,
              "fallback_observations": 252,
              "rank": ["dominant_cycle_extremum_contains_desc", "second_anchor_desc", "maximum_prominence_desc", "summed_prominence_desc", "line_id_asc"]},
    "role_transition": "no_automatic_flip",
    "contact_independence": "disjoint_pivot_confirmation_windows_latest_first",
    "structural_state": "reconstructed_current_vintage_not_historical_signal",
    "projection_sessions": {"exchange": 21, "crypto": 30},
    "comparison_tolerance": {"absolute": 1e-6, "relative": 1e-10},
}


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _hash(value):
    return {**value, "content_hash": C.canonical_hash(value)}


def _path(root, relative):
    return S.safe_path(Path(root), relative.as_posix())


def load_policy(root):
    policy = C._yaml(Path(root), POLICY_RELATIVE)
    if policy != POLICY:
        raise C.TrendlinesError("representative_policy_not_the_versioned_contract")
    return policy


def _near(actual, expected, reason):
    if actual is None or expected is None:
        if actual is not expected:
            raise C.TrendlinesError("representative_" + reason)
    elif (not C._finite_number(actual) or not C._finite_number(expected)
          or not math.isclose(actual, expected, abs_tol=1e-6, rel_tol=1e-10)):
        raise C.TrendlinesError("representative_" + reason)


def _future(rows, asset, policy=POLICY):
    count = policy["projection_sessions"]["crypto" if asset["kind"] == "crypto" else "exchange"]
    last = rows[-1]
    end = (date.fromisoformat(last["session_date"]) + timedelta(days=120)).isoformat()
    schedule = C.session_schedule(asset["calendar_id"], rows[0]["session_date"], end)
    if schedule[last["session_index"]][0] != last["session_date"]:
        raise C.TrendlinesError("representative_calendar_coordinate_binding_invalid")
    return [{"offset": offset, "index": last["session_index"] + offset,
             "session": schedule[last["session_index"] + offset][0]} for offset in range(1, count + 1)]


def _direction(slope):
    return "rising" if slope > 0 else "falling" if slope < 0 else "flat"


def _geometry(line, rows, future):
    origin = line["display_start_index"]
    first = next(row for row in rows if row["session_index"] == origin)
    endpoints = [{"index": origin, "session": first["session_date"]},
                 {"index": rows[-1]["session_index"], "session": rows[-1]["session_date"]}]
    line["current_price"] = E._value(line, rows[-1]["session_index"])
    line["current_price_status"] = "ready" if line["current_price"] is not None else "unavailable_nonpositive_projection"
    line["points"] = [{**item, "price": E._value(line, item["index"]), "future": False} for item in endpoints]
    line["projections"] = [{**item, "price": E._value(line, item["index"]),
                            "status": "ready" if E._value(line, item["index"]) is not None else "unavailable"}
                           for item in future]
    line["display_end_index"] = future[-1]["index"]
    line["verified_boundary"] = False
    return line


def _ols(rows, count, axis, slot, future, fallback_reason=None):
    if len(rows) < count:
        return {"slot": slot, "axis": axis, "status": "hold", "kind": "regression",
                "verified_boundary": False, "reason_codes": ["insufficient_finalized_observations"],
                "available_observations": len(rows), "requested_observations": count,
                "current_price": None, "current_price_status": "unavailable_insufficient_observations",
                "points": [], "projections": [], "markers": [], "contacts": [], "independent_contacts": [],
                "contact_count": 0, "first_anchor": None, "second_anchor": None,
                "fallback_reason": fallback_reason}
    sample = rows[-count:]
    origin = sample[0]["session_index"]
    x = [row["session_index"] - origin for row in sample]
    y = [math.log(row["close"]) if axis == "log" else row["close"] for row in sample]
    xm = math.fsum(x) / count
    ym = y[0] if all(value == y[0] for value in y) else math.fsum(y) / count
    sxx = math.fsum((value - xm) ** 2 for value in x)
    sxy = math.fsum((a - xm) * (b - ym) for a, b in zip(x, y))
    slope, intercept = sxy / sxx, ym - sxy / sxx * xm
    residuals = [value - (intercept + slope * index) for index, value in zip(x, y)]
    sse = math.fsum(value * value for value in residuals)
    sst = math.fsum((value - ym) ** 2 for value in y)
    ids_hash = C.canonical_hash([row["bar_id"] for row in sample])
    fit = {"n": count, "requested_observations": count, "start_index": origin,
           "end_index": sample[-1]["session_index"], "start_session": sample[0]["session_date"],
           "end_session": sample[-1]["session_date"], "input_bar_ids_hash": ids_hash, "fit_bar_ids_hash": ids_hash,
           "session_span": x[-1] + 1, "missing_sessions": x[-1] + 1 - count,
           "x_mean": xm, "y_mean": ym, "sxx": sxx, "sxy": sxy,
           "r_squared": None if sst == 0 else 1 - sse / sst, "rmse": math.sqrt(sse / count),
           "residual_axis": "natural_log_price" if axis == "log" else "price"}
    identity = {"slot": slot, "axis": axis, "input_bar_ids_hash": ids_hash, "policy": POLICY_VERSION}
    line = {"slot": slot, "axis": axis, "status": "ready", "kind": "regression",
            "line_id": "representative-line-" + C.canonical_hash(identity)[:32], "source_line_id": None,
            "role": "direction_only", "origin_role": None, "geometry_status": "descriptive",
            "direction": _direction(slope), "structural_state": "descriptive", "fit": fit,
            "coordinate_origin_index": origin, "slope": slope, "intercept": intercept,
            "first_anchor": None, "second_anchor": None, "contacts": [], "independent_contacts": [],
            "contact_count": 0, "formation_penetration": None, "latest_touch_age_sessions": None,
            "selection_reason": "ordinary_least_squares_finalized_closes", "fallback_reason": fallback_reason,
            "display_start_index": origin, "markers": [], "structural_review": None,
            "label": "200봉 회귀 추세" if slot == "regression_200" else
                     "현재 방향 대표선 · 63봉 회귀" if slot == "current_structure" else "장기 방향 대표선 · 252봉 회귀"}
    return _geometry(line, rows, future)


def _pivots(rows, left, right):
    values = []
    for side in ("support", "resistance"):
        for pivot in E._pivots(rows, 0, left, right, side, segmented=True):
            item = {key: pivot[key] for key in ("session", "index", "price", "bar_id", "confirmed_at", "confirmation_session", "side")}
            item.update(confirmation_start_index=pivot["index"] - left,
                        confirmation_end_index=pivot["index"] + right)
            values.append(item)
    return sorted(values, key=lambda p: (p["index"], p["side"], p["bar_id"]))


def _independent(contacts):
    selected, before = [], math.inf
    for pivot in sorted(contacts, key=lambda p: (-p["index"], p["bar_id"])):
        if pivot["confirmation_end_index"] < before:
            selected.append(pivot)
            before = pivot["confirmation_start_index"]
    return list(reversed(selected))


def _state(line, rows, atr, asset, settings):
    broken, streak, prior = False, 0, None
    breaks, reclaims, state = [], [], "active"
    for position, row in enumerate(rows):
        if row["session_index"] <= line["activation_index"]:
            continue
        if prior != row["session_index"] - 1:
            streak = 0
        prior = row["session_index"]
        price = E._value(line, prior)
        if price is None:
            return {"state": "projection_invalid", "break_sessions": breaks, "reclaim_sessions": reclaims}
        if atr[position] is None:
            streak, state = 0, "broken" if broken else "active"
            continue
        signed = row["close"] - price if line["origin_role"] == "support" else price - row["close"]
        tolerance = E._epsilon(price, atr[position], asset, settings, "break")
        crosses = signed > tolerance if broken else signed < -tolerance
        streak = streak + 1 if crosses else 0
        if streak >= 2:
            broken, streak = not broken, 0
            (breaks if broken else reclaims).append(row["session_date"])
        state = (("reclaim_pending" if broken else "break_pending") if streak else
                 "broken" if broken else "reclaimed" if reclaims else "active")
    return {"state": state, "break_sessions": breaks, "reclaim_sessions": reclaims}


def _pivot_line(first, second, pivots, rows, atr, asset, settings, axis, slot, future):
    transform = math.log if axis == "log" else float
    span = second["index"] - first["index"]
    identity = {"slot": slot, "axis": axis, "origin_role": first["side"], "first_bar_id": first["bar_id"], "second_bar_id": second["bar_id"],
                "policy_version": POLICY_VERSION}
    line = {"slot": slot, "axis": axis, "status": "ready", "kind": "pivot_structure",
            "line_id": "representative-line-" + C.canonical_hash(identity)[:32], "source_line_id": None,
            "role": first["side"], "origin_role": first["side"], "first_anchor": deepcopy(first), "second_anchor": deepcopy(second),
            "coordinate_origin_index": first["index"], "intercept": transform(first["price"]),
            "slope": (transform(second["price"]) - transform(first["price"])) / span,
            "activation_index": second["confirmation_end_index"], "activation_session": second["confirmation_session"],
            "activation_asof": max(first["confirmed_at"], second["confirmed_at"], key=C.aware_time),
            "parameters": {"left": POLICY["current" if slot == "current_structure" else "major"]["left"],
                           "right": POLICY["current" if slot == "current_structure" else "major"]["right"],
                           "min_anchor_gap": POLICY["current" if slot == "current_structure" else "major"]["minimum_anchor_gap"]},
            "fit": None, "fallback_reason": None, "display_start_index": first["index"]}
    line["direction"] = _direction(line["slope"])
    contacts, penetration = [], 0.0
    formation_valid, reason = True, None
    positions = {row["session_index"]: position for position, row in enumerate(rows)}
    for index in range(first["index"], line["activation_index"] + 1):
        if index not in positions:
            formation_valid, reason = False, "missing_formation_session"
            continue
        position = positions[index]
        price = E._value(line, index)
        if price is None or atr[position] is None:
            formation_valid, reason = False, "formation_price_or_atr_unavailable"
            continue
        adverse = price - rows[position]["low"] if first["side"] == "support" else rows[position]["high"] - price
        penetration = max(penetration, adverse / E._epsilon(price, atr[position], asset, settings, "touch"))
    if penetration > 1 + 1e-10:
        formation_valid, reason = False, "formation_penetration"
    for pivot in pivots:
        if pivot["side"] != first["side"] or pivot["index"] < first["index"]:
            continue
        position = positions[pivot["index"]]
        price = E._value(line, pivot["index"])
        if price is not None and atr[position] is not None and abs(pivot["price"] - price) <= E._epsilon(price, atr[position], asset, settings, "touch"):
            contacts.append(deepcopy(pivot))
    contacts = _independent(contacts)
    state = _state(line, rows, atr, asset, settings)
    line.update(contacts=contacts, independent_contacts=contacts, contact_count=len(contacts),
                geometry_status="three_contact" if len(contacts) >= 3 else "two_anchor",
                formation_penetration=penetration, formation_valid=formation_valid,
                formation_rejection_reason=reason, structural_state=state["state"],
                structural_review={**state, "classification": "reconstructed_current_vintage", "historical_signals_available": False},
                latest_touch_age_sessions=rows[-1]["session_index"] - max((p["index"] for p in contacts), default=second["index"]),
                markers=[deepcopy(first), deepcopy(second)])
    line = _geometry(line, rows, future)
    # A broken or penetrated structural reference never acquires a new role.
    if state["state"] not in {"active", "reclaimed"} or not formation_valid:
        line["role"] = "direction_only"
    line["label"] = ("현재 " if slot == "current_structure" else "장기 주요점 ") + (
        "상승 구조" if line["direction"] == "rising" else "하락 구조" if line["direction"] == "falling" else "수평 구조")
    if line["role"] == "direction_only":
        line["label"] += " · 이탈·침범 구조"
    return line


def _current(rows, atr, asset, settings, axis, future, pivots, policy):
    spec = policy["current"]
    regression = _ols(rows, spec["observations"], axis, "current_structure", future)
    eligible, rejected = [], {}
    def reject(reason):
        rejected[reason] = rejected.get(reason, 0) + 1
    recent = [p for p in pivots if p["index"] >= rows[-1]["session_index"] - spec["maximum_anchor_age"] + 1]
    for offset, first in enumerate(recent):
        for second in recent[offset + 1:]:
            if first["side"] != second["side"] or second["index"] - first["index"] < spec["minimum_anchor_gap"]:
                continue
            if first["confirmation_end_index"] >= second["confirmation_start_index"]:
                continue
            if regression["status"] != "ready" or _direction(second["price"] - first["price"]) != regression["direction"]:
                reject("direction_differs_from_recent_63_ols")
                continue
            line = _pivot_line(first, second, recent, rows, atr, asset, settings, axis, "current_structure", future)
            price = line["current_price"]
            if not line["formation_valid"]:
                reject(line["formation_rejection_reason"])
            elif line["structural_state"] not in {"active", "reclaimed"}:
                reject("original_role_not_reestablished")
            elif price is None or any(p["price"] is None for p in line["projections"]):
                reject("nonpositive_projection")
            elif (first["side"] == "support" and price > rows[-1]["close"]) or (first["side"] == "resistance" and price < rows[-1]["close"]):
                reject("original_role_wrong_side_of_close")
            elif atr[-1] is None or abs(price - rows[-1]["close"]) > spec["maximum_distance_atr"] * atr[-1]:
                reject("distance_exceeds_four_atr_or_atr_unavailable")
            elif abs(price - rows[-1]["close"]) > spec["maximum_distance_fraction"] * rows[-1]["close"]:
                reject("distance_exceeds_twenty_percent")
            else:
                line["selection_reason"] = "recent_independent_confirmed_anchors_matching_63_ols"
                eligible.append(line)
    eligible.sort(key=lambda line: (-line["second_anchor"]["index"], -line["first_anchor"]["index"], line["line_id"]))
    selected = eligible[0] if eligible else regression
    if not eligible:
        selected["fallback_reason"] = "no_intact_recent_pivot_structure"
    return selected, {"eligible_line_ids": [p["line_id"] for p in eligible], "rejection_counts": rejected}


def _prominent(pivots, rows, atr, policy):
    positions = {row["session_index"]: i for i, row in enumerate(rows)}
    enriched = []
    span = policy["major"]["left"]
    for pivot in pivots:
        position = positions[pivot["index"]]
        if atr[position] is None or atr[position] <= 0:
            continue
        column = "high" if pivot["side"] == "support" else "low"
        left = [row[column] for row in rows[position-span:position]]
        right = [row[column] for row in rows[position+1:position+span+1]]
        amplitude = (min(max(left), max(right)) - pivot["price"] if pivot["side"] == "support" else
                     pivot["price"] - max(min(left), min(right)))
        enriched.append({**pivot, "prominence": amplitude / atr[position]})
    major_ids = set()
    for side in ("support", "resistance"):
        recent = [p for p in enriched if p["side"] == side and p["index"] >= rows[-1]["session_index"] - policy["major"]["prominence_window"] + 1]
        recent.sort(key=lambda p: (-p["prominence"], -p["index"], p["bar_id"]))
        major_ids.update((p["bar_id"], p["side"]) for p in recent[:policy["major"]["top_prominence_per_side"]])
    return enriched, major_ids


def _major(rows, atr, asset, settings, axis, future, pivots, policy):
    spec = policy["major"]
    enriched, major_ids = _prominent(pivots, rows, atr, policy)
    dominant = set()
    for side in ("support", "resistance"):
        pool = [p for p in enriched if p["side"] == side and p["index"] >= rows[-1]["session_index"]-spec["prominence_window"]+1]
        if pool:
            extreme = min(pool, key=lambda p: (p["price"] if side == "support" else -p["price"], -p["index"], p["bar_id"]))
            dominant.add((extreme["bar_id"], extreme["side"]))
    eligible, rejected = [], {}
    def reject(reason):
        rejected[reason] = rejected.get(reason, 0) + 1
    for offset, first in enumerate(enriched):
        for second in enriched[offset + 1:]:
            if (first["side"] != second["side"] or second["index"] - first["index"] < spec["minimum_anchor_gap"]
                    or rows[-1]["session_index"] - second["index"] > spec["maximum_second_anchor_age"]
                    or not {(first["bar_id"], first["side"]), (second["bar_id"], second["side"])} & major_ids):
                continue
            line = _pivot_line(first, second, enriched, rows, atr, asset, settings, axis, "major_structure", future)
            price = line["current_price"]
            distance = math.inf if price is None else abs(price - rows[-1]["close"])
            if price is None or any(p["price"] is None for p in line["projections"]):
                reject("nonpositive_projection")
            elif atr[-1] is None or distance > spec["maximum_distance_atr"] * atr[-1]:
                reject("distance_exceeds_eight_atr_or_atr_unavailable")
            elif (distance > spec["maximum_distance_fraction"] * rows[-1]["close"]
                    or not spec["minimum_current_price_fraction"] * rows[-1]["close"] <= price <= spec["maximum_current_price_fraction"] * rows[-1]["close"]):
                reject("distance_exceeds_half_close")
            else:
                if (first["side"] == "support" and price > rows[-1]["close"]) or (first["side"] == "resistance" and price < rows[-1]["close"]):
                    line["role"] = "direction_only"
                    line["label"] += " · 원래 역할 미충족"
                line["major_anchor_ids"] = sorted(p["bar_id"] for p in (first, second) if (p["bar_id"], p["side"]) in major_ids)
                line["dominant_anchor_ids"] = sorted(p["bar_id"] for p in (first, second) if (p["bar_id"], p["side"]) in dominant)
                line["dominant_cycle_extremum_contains"] = bool(line["dominant_anchor_ids"])
                line["selection_reason"] = "recent_major_confirmed_pivot_structure"
                line["maximum_prominence"] = max(first["prominence"], second["prominence"])
                line["summed_prominence"] = first["prominence"] + second["prominence"]
                # Show the captured cycle's confirmed peak/trough as context, not another trendline.
                extrema = []
                for side in ("support", "resistance"):
                    pool = [p for p in enriched if p["side"] == side and p["index"] >= first["index"]]
                    if pool:
                        extrema.append(deepcopy(min(pool, key=lambda p: (p["price"] if side == "support" else -p["price"], -p["index"]))))
                line["markers"] = list({(p["bar_id"], p["side"]): p for p in line["markers"] + extrema}.values())
                eligible.append(line)
    eligible.sort(key=lambda line: (-int(line["dominant_cycle_extremum_contains"]), -line["second_anchor"]["index"], -line["maximum_prominence"], -line["summed_prominence"], line["line_id"]))
    selected = eligible[0] if eligible else _ols(rows, spec["fallback_observations"], axis, "major_structure", future,
                                                "no_realistic_major_pivot_structure")
    return selected, {"eligible_line_ids": [p["line_id"] for p in eligible], "rejection_counts": rejected,
                      "major_pivot_ids": sorted({bar_id for bar_id, _side in major_ids}),
                      "major_pivot_keys": [{"bar_id": bar_id, "side": side} for bar_id, side in sorted(major_ids)],
                      "dominant_pivot_keys": [{"bar_id": bar_id, "side": side} for bar_id, side in sorted(dominant)]}


def _calculate(source, full, policy=POLICY):
    rows, settings, asset = full["bars"], source["config"], source["asset"]
    if full["source_snapshot_id"] != source["snapshot_id"] or C.canonical_hash(rows) != full["input_hash"]:
        raise C.TrendlinesError("representative_full_input_source_binding_invalid")
    atr = E._atr(rows, settings["atr"]["period"], segmented=True)
    future = _future(rows, asset, policy)
    current_pivots, major_pivots = _pivots(rows, 3, 3), _pivots(rows, 10, 10)
    analyses, audits = {}, {}
    for axis in ("linear", "log"):
        current, current_audit = _current(rows, atr, asset, settings, axis, future, current_pivots, policy)
        major, major_audit = _major(rows, atr, asset, settings, axis, future, major_pivots, policy)
        analyses[axis] = {"representatives": [_ols(rows, policy["regression"]["observations"], axis, "regression_200", future), current, major]}
        audits[axis] = {"current_structure": current_audit, "major_structure": major_audit}
    result = {"policy": deepcopy(policy), "policy_sha256": C.canonical_hash(policy), "input_hash": C.canonical_hash(rows),
              "input_bar_ids_hash": C.canonical_hash([row["bar_id"] for row in rows]),
              "reference_close": rows[-1]["close"], "reference_session": rows[-1]["session_date"],
              "reference_index": rows[-1]["session_index"], "atr14": atr[-1], "projection_sessions": future,
              "analyses": analyses, "candidate_audits": audits}
    result["independent_validation"] = _scalar_verify(rows, asset, settings, result, current_pivots, major_pivots, policy)
    return result


def _scalar_value(line, index):
    if line["kind"] == "pivot_structure":
        first, second = line["first_anchor"], line["second_anchor"]
        fraction = (index - first["index"]) / (second["index"] - first["index"])
        value = (first["price"] + (second["price"] - first["price"]) * fraction if line["axis"] == "linear" else
                 math.log(first["price"]) + (math.log(second["price"]) - math.log(first["price"])) * fraction)
    else:
        value = line["intercept"] + line["slope"] * (index - line["coordinate_origin_index"])
    try:
        price = math.exp(value) if line["axis"] == "log" else value
    except OverflowError:
        return None
    return price if math.isfinite(price) and price > 0 else None


def _scalar_pivots(rows, left, right):
    result = []
    for i in range(left, len(rows) - right):
        sample = rows[i-left:i+right+1]
        if [r["session_index"] for r in sample] != list(range(rows[i]["session_index"]-left, rows[i]["session_index"]+right+1)):
            continue
        for side, column in (("support", "low"), ("resistance", "high")):
            value = rows[i][column]
            values = [r[column] for r in sample]
            valid = (value < min(values[:left]) and value <= min(values[left+1:]) if side == "support" else
                     value > max(values[:left]) and value >= max(values[left+1:]))
            if valid:
                known = max(C.aware_time(r[k]) for r in sample for k in ("available_at", "fetched_at"))
                result.append({"session": rows[i]["session_date"], "index": rows[i]["session_index"], "price": value,
                               "bar_id": rows[i]["bar_id"], "confirmed_at": known.isoformat(),
                               "confirmation_session": rows[i+right]["session_date"], "side": side,
                               "confirmation_start_index": rows[i]["session_index"]-left,
                               "confirmation_end_index": rows[i]["session_index"]+right})
    return sorted(result, key=lambda p: (p["index"], p["side"], p["bar_id"]))


def _scalar_atr(rows):
    output, ranges = [None], []
    for i in range(1, len(rows)):
        if rows[i]["session_index"] != rows[i-1]["session_index"] + 1:
            ranges = []
            output.append(None)
            continue
        before, row = rows[i-1], rows[i]
        ranges.append(max(row["high"]-row["low"], abs(row["high"]-before["close"]), abs(row["low"]-before["close"])))
        output.append(math.fsum(ranges[-14:]) / 14 if len(ranges) >= 14 else None)
    return output


def _scalar_state(line, rows, atr, asset, settings):
    mode, consecutive, prior, state = "intact", [], None, "active"
    breaks, reclaims = [], []
    for i, row in enumerate(rows):
        if row["session_index"] <= line["activation_index"]:
            continue
        if prior != row["session_index"]-1:
            consecutive = []
        prior = row["session_index"]
        price = _scalar_value(line, prior)
        if price is None:
            return {"state": "projection_invalid", "break_sessions": breaks, "reclaim_sessions": reclaims}
        if atr[i] is None:
            consecutive, state = [], "broken" if mode == "broken" else "active"
            continue
        buffer = max(asset.get("tick_size", 0.0), settings["break"]["atr_multiple"] * atr[i], settings["break"]["price_fraction"] * price, 1e-12 * price)
        distance = row["close"] - price if line["origin_role"] == "support" else price - row["close"]
        confirms = distance > buffer if mode == "broken" else distance < -buffer
        if not confirms:
            consecutive = []
            state = "broken" if mode == "broken" else "reclaimed" if reclaims else "active"
            continue
        consecutive.append(row["session_date"])
        if len(consecutive) == 1:
            state = "reclaim_pending" if mode == "broken" else "break_pending"
        else:
            if mode == "intact":
                breaks.append(row["session_date"])
                mode, state = "broken", "broken"
            else:
                reclaims.append(row["session_date"])
                mode, state = "intact", "reclaimed"
            consecutive = []
    return {"state": state, "break_sessions": breaks, "reclaim_sessions": reclaims}


def _scalar_verify(rows, asset, settings, result, current_pivots, major_pivots, policy):
    """Independent normal equations, pivots, ATR, anchor interpolation and runs."""
    if current_pivots != _scalar_pivots(rows, 3, 3) or major_pivots != _scalar_pivots(rows, 10, 10):
        raise C.TrendlinesError("representative_scalar_confirmed_pivots")
    atr = _scalar_atr(rows)
    for observed, expected in zip(E._atr(rows, 14, segmented=True), atr):
        _near(observed, expected, "scalar_atr")
    end = (date.fromisoformat(rows[-1]["session_date"])+timedelta(days=120)).isoformat()
    dates = [day for day, _, _ in C.session_schedule(asset["calendar_id"], rows[-1]["session_date"], end)
             if day > rows[-1]["session_date"]]
    count = policy["projection_sessions"]["crypto" if asset["kind"] == "crypto" else "exchange"]
    if result["projection_sessions"] != [{"offset": i, "index": rows[-1]["session_index"]+i, "session": day}
                                         for i, day in enumerate(dates[:count], 1)]:
        raise C.TrendlinesError("representative_scalar_future_calendar")
    checked = 0
    for axis, analysis in result["analyses"].items():
        if [line["slot"] for line in analysis["representatives"]] != list(SLOTS):
            raise C.TrendlinesError("representative_scalar_slots")
        for line in analysis["representatives"]:
            if line["status"] == "hold":
                if len(rows) >= line["requested_observations"]:
                    raise C.TrendlinesError("representative_scalar_unnecessary_hold")
                continue
            if line["kind"] == "regression":
                count = line["fit"]["n"]
                requested = 200 if line["slot"] == "regression_200" else 63 if line["slot"] == "current_structure" else 252
                if count != requested or line["fit"]["requested_observations"] != requested:
                    raise C.TrendlinesError("representative_scalar_ols_window")
                sample = rows[-count:]
                x = [r["session_index"] - sample[0]["session_index"] for r in sample]
                y = [math.log(r["close"]) if axis == "log" else r["close"] for r in sample]
                sx, sy = math.fsum(x), math.fsum(y)
                b = (count * math.fsum(a*v for a, v in zip(x, y)) - sx * sy) / (count * math.fsum(a*a for a in x) - sx*sx)
                a = (sy - b*sx) / count
                _near(line["slope"], b, "scalar_ols_slope")
                _near(line["intercept"], a, "scalar_ols_intercept")
                errors = [v - a - b*t for t, v in zip(x, y)]
                _near(line["fit"]["rmse"], math.sqrt(math.fsum(e*e for e in errors)/count), "scalar_ols_rmse")
                xm = sx/count
                ym = y[0] if all(v == y[0] for v in y) else sy/count
                sst = math.fsum((v-ym)**2 for v in y)
                r_squared = None if sst == 0 else 1-math.fsum(e*e for e in errors)/sst
                for key, expected in (("x_mean", xm), ("y_mean", ym), ("sxx", math.fsum((v-xm)**2 for v in x)),
                                      ("sxy", math.fsum((u-xm)*(v-ym) for u, v in zip(x, y))), ("r_squared", r_squared)):
                    _near(line["fit"][key], expected, "scalar_ols_"+key)
                ids_hash = C.canonical_hash([r["bar_id"] for r in sample])
                if (line["fit"]["input_bar_ids_hash"] != ids_hash or line["fit"]["fit_bar_ids_hash"] != ids_hash
                        or line["coordinate_origin_index"] != sample[0]["session_index"]
                        or line["fit"]["start_index"] != sample[0]["session_index"] or line["fit"]["end_index"] != sample[-1]["session_index"]
                        or line["fit"]["start_session"] != sample[0]["session_date"] or line["fit"]["end_session"] != sample[-1]["session_date"]):
                    raise C.TrendlinesError("representative_scalar_ols_inputs")
                if line["contacts"] or line["contact_count"] or line["first_anchor"] is not None or line["second_anchor"] is not None:
                    raise C.TrendlinesError("representative_regression_fabricated_pivots")
            else:
                pivots = current_pivots if line["slot"] == "current_structure" else major_pivots
                identity = {"slot": line["slot"], "axis": axis, "origin_role": line["origin_role"],
                            "first_bar_id": line["first_anchor"]["bar_id"], "second_bar_id": line["second_anchor"]["bar_id"],
                            "policy_version": POLICY_VERSION}
                if line["line_id"] != "representative-line-"+C.canonical_hash(identity)[:32]:
                    raise C.TrendlinesError("representative_scalar_line_identity")
                for anchor in (line["first_anchor"], line["second_anchor"]):
                    found = next((p for p in pivots if p["bar_id"] == anchor["bar_id"] and p["side"] == anchor["side"]), None)
                    if found is None or any(anchor[k] != value for k, value in found.items()):
                        raise C.TrendlinesError("representative_scalar_anchor_binding")
                marker_keys = [(p["bar_id"], p["side"]) for p in line["markers"]]
                if (len(marker_keys) != len(set(marker_keys)) or
                        any((line[key]["bar_id"], line[key]["side"]) not in marker_keys for key in ("first_anchor", "second_anchor"))):
                    raise C.TrendlinesError("representative_scalar_anchor_marker_missing_or_duplicated")
                for marker in line["markers"]:
                    found = next((p for p in pivots if (p["bar_id"], p["side"]) == (marker["bar_id"], marker["side"])), None)
                    if found is None or any(marker[k] != value for k, value in found.items()):
                        raise C.TrendlinesError("representative_scalar_marker_not_confirmed_pivot")
                state = _scalar_state(line, rows, atr, asset, settings)
                if any(line["structural_review"][k] != value for k, value in state.items()):
                    raise C.TrendlinesError("representative_scalar_state")
                positions = {r["session_index"]: i for i, r in enumerate(rows)}
                admissible = []
                for pivot in pivots:
                    if pivot["side"] != line["origin_role"] or pivot["index"] < line["first_anchor"]["index"]:
                        continue
                    i = positions[pivot["index"]]
                    price = _scalar_value(line, pivot["index"])
                    if price is None or atr[i] is None:
                        continue
                    tolerance = max(asset.get("tick_size", 0.0), settings["touch"]["atr_multiple"]*atr[i], settings["touch"]["price_fraction"]*price, 1e-12*price)
                    if abs(pivot["price"]-price) <= tolerance:
                        admissible.append(pivot)
                independent = []
                for pivot in sorted(admissible, key=lambda p: (-p["index"], p["bar_id"])):
                    if all(pivot["confirmation_end_index"] < other["confirmation_start_index"] for other in independent):
                        independent.append(pivot)
                independent.reverse()
                if ([p["bar_id"] for p in line["contacts"]] != [p["bar_id"] for p in independent]
                        or line["contact_count"] != len(independent)
                        or line["geometry_status"] != ("three_contact" if len(independent) >= 3 else "two_anchor")):
                    raise C.TrendlinesError("representative_scalar_contact_completeness")
            for point in line["points"] + line["projections"]:
                _near(point["price"], _scalar_value(line, point["index"]), "scalar_line_price")
            _near(line["current_price"], _scalar_value(line, rows[-1]["session_index"]), "scalar_current_price")
            checked += 1
    _scalar_selection_verify(rows, asset, settings, result, atr, policy)
    return {"status": "passed", "independent_ols_normal_equations": True, "independent_confirmed_pivots": True,
            "independent_atr_and_state_runs": True, "independent_anchor_interpolation": True,
            "independent_candidate_completeness_and_rank": True,
            "checked_representatives": checked}


def _scalar_selection_verify(rows, asset, settings, result, atr, policy):
    """Enumerate and rank pairs without any producer candidate/selection helpers."""
    positions = {row["session_index"]: i for i, row in enumerate(rows)}
    last, close = rows[-1]["session_index"], rows[-1]["close"]
    def buffer(price, volatility):
        return max(asset.get("tick_size", 0.0), settings["touch"]["atr_multiple"] * volatility,
                   settings["touch"]["price_fraction"] * price, 1e-12 * price)
    for axis in ("linear", "log"):
        for slot in ("current_structure", "major_structure"):
            spec = policy["current" if slot == "current_structure" else "major"]
            pivots = _scalar_pivots(rows, spec["left"], spec["right"])
            top, dominant = set(), set()
            if slot == "current_structure":
                pivots = [p for p in pivots if p["index"] >= last - spec["maximum_anchor_age"] + 1]
                if len(rows) >= 63:
                    sample = rows[-63:]
                    x = [r["session_index"] - sample[0]["session_index"] for r in sample]
                    y = [math.log(r["close"]) if axis == "log" else r["close"] for r in sample]
                    covariance = 63 * math.fsum(a*b for a, b in zip(x, y)) - math.fsum(x)*math.fsum(y)
                    direction = "flat" if all(v == y[0] for v in y) else _direction(covariance)
                else:
                    direction = None
            else:
                scored = []
                for pivot in pivots:
                    i = positions[pivot["index"]]
                    if atr[i] is None or atr[i] <= 0:
                        continue
                    if pivot["side"] == "support":
                        left_turn = max(r["high"] for r in rows[i-10:i]) - pivot["price"]
                        right_turn = max(r["high"] for r in rows[i+1:i+11]) - pivot["price"]
                    else:
                        left_turn = pivot["price"] - min(r["low"] for r in rows[i-10:i])
                        right_turn = pivot["price"] - min(r["low"] for r in rows[i+1:i+11])
                    scored.append({**pivot, "prominence": min(left_turn, right_turn) / atr[i]})
                pivots = scored
                for side in ("support", "resistance"):
                    pool = [p for p in pivots if p["side"] == side and p["index"] >= last-spec["prominence_window"]+1]
                    pool.sort(key=lambda p: (-p["prominence"], -p["index"], p["bar_id"]))
                    top.update((p["bar_id"], p["side"]) for p in pool[:spec["top_prominence_per_side"]])
                    if pool:
                        winner = min(pool, key=lambda p: (p["price"] if side == "support" else -p["price"], -p["index"], p["bar_id"]))
                        dominant.add((winner["bar_id"], winner["side"]))
            admitted = []
            for i in range(len(pivots)):
                for j in range(i+1, len(pivots)):
                    first, second = pivots[i], pivots[j]
                    if first["side"] != second["side"] or second["index"]-first["index"] < spec["minimum_anchor_gap"]:
                        continue
                    if slot == "current_structure":
                        if (first["confirmation_end_index"] >= second["confirmation_start_index"]
                                or _direction(second["price"]-first["price"]) != direction):
                            continue
                    elif last-second["index"] > spec["maximum_second_anchor_age"] or not {(first["bar_id"], first["side"]), (second["bar_id"], second["side"])} & top:
                        continue
                    oracle = {"kind": "pivot_structure", "axis": axis, "first_anchor": first, "second_anchor": second,
                              "origin_role": first["side"], "activation_index": second["confirmation_end_index"]}
                    value = _scalar_value(oracle, last)
                    if value is None or any(_scalar_value(oracle, p["index"]) is None for p in result["projection_sessions"]):
                        continue
                    if atr[-1] is None or abs(value-close) > spec["maximum_distance_atr"]*atr[-1] or abs(value-close) > spec["maximum_distance_fraction"]*close:
                        continue
                    if slot == "current_structure":
                        if (first["side"] == "support" and value > close) or (first["side"] == "resistance" and value < close):
                            continue
                        valid = True
                        for index in range(first["index"], second["confirmation_end_index"]+1):
                            if index not in positions or atr[positions[index]] is None:
                                valid = False
                                break
                            row, volatility = rows[positions[index]], atr[positions[index]]
                            level = _scalar_value(oracle, index)
                            if level is None:
                                valid = False
                                break
                            adverse = level-row["low"] if first["side"] == "support" else row["high"]-level
                            if adverse > buffer(level, volatility)*(1+1e-10):
                                valid = False
                                break
                        if not valid or _scalar_state(oracle, rows, atr, asset, settings)["state"] not in {"active", "reclaimed"}:
                            continue
                    elif not spec["minimum_current_price_fraction"]*close <= value <= spec["maximum_current_price_fraction"]*close:
                        continue
                    identity = {"slot": slot, "axis": axis, "origin_role": first["side"], "first_bar_id": first["bar_id"], "second_bar_id": second["bar_id"], "policy_version": POLICY_VERSION}
                    line_id = "representative-line-" + C.canonical_hash(identity)[:32]
                    rank = ((-second["index"], -first["index"], line_id) if slot == "current_structure" else
                            (-int(bool({(first["bar_id"], first["side"]), (second["bar_id"], second["side"])} & dominant)),
                             -second["index"], -max(first["prominence"], second["prominence"]), -(first["prominence"]+second["prominence"]), line_id))
                    admitted.append((rank, line_id))
            expected = [line_id for _rank, line_id in sorted(admitted)]
            reported = result["candidate_audits"][axis][slot]["eligible_line_ids"]
            if expected != reported:
                raise C.TrendlinesError("representative_scalar_candidate_completeness_or_rank")
            selected = next(p for p in result["analyses"][axis]["representatives"] if p["slot"] == slot)
            if expected:
                if selected.get("line_id") != expected[0] or selected["kind"] != "pivot_structure":
                    raise C.TrendlinesError("representative_scalar_selection_rank")
            elif selected["kind"] != "regression":
                raise C.TrendlinesError("representative_scalar_missing_regression_fallback")


def _bind_full(root, full_id, now=None, *, reparse=False):
    full, source = F._read_snapshot(root, full_id)
    identity = {k: v for k, v in source.items() if k not in {"snapshot_id", "content_hash"}}
    if (source["snapshot_id"] != "research-snapshot-" + C.canonical_hash(identity)
            or source.get("schema_version") != 1 or source.get("contract_id") != "trendlines_research_snapshot_v1"
            or source["config"] != C.load_contract(root) or S.aware_time(source["capture_asof"]) > S.aware_time(now)):
        raise C.TrendlinesError("representative_source_identity_or_cutoff_invalid")
    receipt = F._source_evidence(root, source)
    rows = full["bars"]
    # The engine's pinned input hash covers ALL original calendar coordinates,
    # including the older rows omitted from its compact bars. Readers check it
    # without importing an exchange calendar or validating each day on a GET.
    # Batch/replay independently recheck the complete calendar and original HTML.
    if (not rows or len(rows) > F.MAX_BARS or
            [{k: v for k, v in row.items() if k not in {"session", "session_index"}} for row in rows] != source["bars"]
            or C.canonical_hash(rows) != full["input_hash"]):
        raise C.TrendlinesError("representative_full_bars_differ_from_source")
    if (source["engine_snapshot"]["input_hash"] != full["input_hash"]
            or not all(row["session"] == row["session_date"] and type(row["session_index"]) is int for row in rows)
            or any(a["session_index"] >= b["session_index"] for a, b in zip(rows, rows[1:]))):
        raise C.TrendlinesError("representative_full_calendar_coordinate_binding_invalid")
    manifest_path = _path(root, F.ROOT / "exports" / full_id / "manifest.json")
    manifest = S.read_json(manifest_path)
    if manifest_path.read_bytes() != S.encode(manifest) or manifest != F._exports(full)[0]:
        raise C.TrendlinesError("representative_full_manifest_binding_invalid")
    if reparse:
        calendar = C.session_schedule(source["asset"]["calendar_id"], rows[0]["session_date"], rows[-1]["session_date"])
        coordinates = {day: i for i, (day, _, _) in enumerate(calendar)}
        if any(row["session_index"] != coordinates.get(row["session_date"]) for row in rows):
            raise C.TrendlinesError("representative_full_calendar_coordinate_binding_invalid")
        # F._read_snapshot and _source_evidence just hashed this archive, its
        # receipt and raw original; reuse only this worker's proof for those bytes.
        if not R._source_replayed(root, source, full["source_archive_sha256"]):
            raw = S.safe_path(root, receipt["raw_path"]).read_bytes()
            bars, metadata, gaps = R._prepare(raw, receipt, source["asset"], source["capture_asof"], config=source["config"],
                                              allow_rejected_rows=source["row_validation_policy"]["allow_rejected_rows"])
            if bars != source["bars"] or metadata != source["metadata"] or gaps != source["gaps"]:
                raise C.TrendlinesError("representative_source_differs_from_original_html")
    return source, full, manifest


def _sources(root, asset_id, now=None, *, reparse=False):
    source, source_pointer = F._source(root, asset_id, now)
    if source is None:
        return None, None, None, None
    full_pointer = F._latest(root)["assets"].get(asset_id)
    if full_pointer is None:
        raise C.TrendlinesError("representative_full_snapshot_missing")
    pinned_source, full, manifest = _bind_full(root, full_pointer["snapshot_id"], now, reparse=reparse)
    if pinned_source != source:
        raise C.TrendlinesError("representative_full_snapshot_not_current_source")
    full_path = F.ROOT / "snapshots" / (full["snapshot_id"] + ".json")
    manifest_path = F.ROOT / "exports" / full["snapshot_id"] / "manifest.json"
    if (full_pointer["snapshot_path"] != full_path.as_posix() or full_pointer["manifest_path"] != manifest_path.as_posix()
            or full_pointer["snapshot_sha256"] != _sha(_path(root, full_path).read_bytes())
            or full_pointer["manifest_sha256"] != _sha(_path(root, manifest_path).read_bytes())):
        raise C.TrendlinesError("representative_full_latest_binding_invalid")
    return source, source_pointer, full, manifest


def _strict_shadow(root, asset_id, source):
    """Freeze the existing selection evidence; no critical computation or writes."""
    latest = Path("data/trendlines_research_critical/latest.json")
    path = _path(root, latest)
    if not path.is_file():
        return {"classification": "additive_descriptive_not_critical_promotion", "strict_available": False,
                "strict_selected_ids": {}, "existing_events_unchanged": True}
    pointer = R._checked(path)
    row = pointer["assets"].get(asset_id)
    if row is None:
        return {"classification": "additive_descriptive_not_critical_promotion", "strict_available": False,
                "strict_selected_ids": {}, "existing_events_unchanged": True}
    snapshot_path = S.safe_path(root, row["snapshot_path"])
    snapshot = R._checked(snapshot_path)
    if _sha(snapshot_path.read_bytes()) != row["snapshot_sha256"] or snapshot["asset_id"] != asset_id:
        raise C.TrendlinesError("representative_strict_shadow_binding_invalid")
    return {"classification": "additive_descriptive_not_critical_promotion", "strict_available": True,
            "strict_snapshot_id": snapshot["snapshot_id"], "strict_snapshot_sha256": row["snapshot_sha256"],
            "strict_source_snapshot_id": snapshot["source_snapshot_id"],
            "comparable_inputs": snapshot["source_snapshot_id"] == source["snapshot_id"],
            "strict_selected_ids": {axis: {window: [b["line_id"] for b in view["boundaries"]]
                                          for window, view in views.items()} for axis, views in snapshot["analyses"].items()},
            "existing_events_unchanged": True}


def _verify_shadow(root, shadow, asset_id):
    if not shadow["strict_available"]:
        if shadow["strict_selected_ids"] != {}:
            raise C.TrendlinesError("representative_shadow_without_source")
        return
    sid = shadow["strict_snapshot_id"]
    if not re.fullmatch(r"critical-snapshot-[0-9a-f]{64}", sid):
        raise C.TrendlinesError("representative_shadow_snapshot_id_invalid")
    path = _path(root, Path("data/trendlines_research_critical/snapshots")/(sid+".json"))
    snapshot = R._checked(path)
    selected = {axis: {window: [b["line_id"] for b in view["boundaries"]] for window, view in views.items()}
                for axis, views in snapshot["analyses"].items()}
    if (snapshot["snapshot_id"] != sid or snapshot["asset_id"] != asset_id
            or _sha(path.read_bytes()) != shadow["strict_snapshot_sha256"]
            or selected != shadow["strict_selected_ids"] or snapshot["source_snapshot_id"] != shadow["strict_source_snapshot_id"]):
        raise C.TrendlinesError("representative_shadow_strict_selection_changed")


def _evidence(root, snapshot, source, full):
    """What a successful snapshot check was bound to: each file's digest, instrument and contract."""
    files = {(F.ROOT / "snapshots" / (full["snapshot_id"] + ".json")).as_posix(): _sha(S.encode(full)),
             full["source_snapshot_path"]: full["source_archive_sha256"],
             source["receipt_path"]: source["receipt_sha256"],
             (R.ROOT / "raw" / (source["raw_sha256"] + ".bin")).as_posix(): source["raw_sha256"],
             (F.ROOT / "exports" / full["snapshot_id"] / "manifest.json").as_posix(): _sha(S.encode(F._exports(full)[0])),
             (ROOT / "exports" / snapshot["snapshot_id"] / "detail.json").as_posix(): _sha(S.encode(_export(snapshot)))}
    shadow = snapshot["shadow"]
    if shadow["strict_available"]:
        strict = Path("data/trendlines_research_critical/snapshots") / (shadow["strict_snapshot_id"] + ".json")
        files[strict.as_posix()] = shadow["strict_snapshot_sha256"]
    return {"snapshot_id": snapshot["snapshot_id"], "asset_id": snapshot["asset_id"], "content_hash": snapshot["content_hash"],
            "source_content_hash": source["content_hash"], "source_archive_sha256": snapshot["source_archive_sha256"],
            "raw_sha256": source["raw_sha256"], "receipt_sha256": source["receipt_sha256"],
            "full_content_hash": full["content_hash"], "full_manifest_payload_sha256": snapshot["full_manifest_payload_sha256"],
            "capture_asof": source["capture_asof"], "files": files, "contract": C.canonical_hash(source["config"]),
            "assets": {source["asset_id"]: C.canonical_hash(R.asset_definition(root, source["asset_id"]))}}


def _latest(root):
    path = _path(root, ROOT / "latest.json")
    if not path.is_file():
        return {"assets": {}}
    value = R._checked(path)
    if (value.get("contract_id") != "trendlines_private_representative_latest_v1" or value.get("schema_version") != 1
            or not isinstance(value.get("assets"), dict) or set(value["assets"]) - set(R.SYMBOLS)
            or path.read_bytes() != S.encode(value)):
        raise C.TrendlinesError("representative_latest_contract_invalid")
    return value


def _read_snapshot(root, sid, now=None, *, reparse=False):
    if not isinstance(sid, str) or not SNAPSHOT_RE.fullmatch(sid):
        raise C.TrendlinesError("representative_snapshot_id_invalid")
    path = _path(root, ROOT / "snapshots" / (sid + ".json"))
    value = R._checked(path)
    identity = {k: v for k, v in value.items() if k not in {"snapshot_id", "content_hash"}}
    if (value.get("snapshot_id") != sid or sid != SNAPSHOT_PREFIX + C.canonical_hash(identity)
            or path.read_bytes() != S.encode(value) or value.get("contract_id") != "trendlines_private_representative_snapshot_v1"
            or value.get("policy") != POLICY or value.get("verified_boundary") is not False
            or value.get("verified_source") is not False or value.get("historical_signals_available") is not False
            or value.get("official_forecast_write") is not False or value.get("events") != []):
        raise C.TrendlinesError("representative_snapshot_identity_or_policy_invalid")
    source, full, manifest = _bind_full(root, value["source_full_snapshot_id"], now, reparse=reparse)
    if (value["source_snapshot_id"] != source["snapshot_id"] or value["asset_id"] != source["asset_id"]
            or value["source_content_hash"] != source["content_hash"] or value["source_full_content_hash"] != full["content_hash"]
            or value["source_engine_content_hash"] != source["engine_snapshot"]["content_hash"]
            or value["source_engine_snapshot_id"] != source["engine_snapshot"]["snapshot_id"]
            or value["full_manifest_payload_sha256"] != manifest["payload_sha256"]
            or value["as_of"] != source["capture_asof"] or value["source_snapshot_path"] != full["source_snapshot_path"]
            or value["source_archive_sha256"] != full["source_archive_sha256"]):
        raise C.TrendlinesError("representative_source_snapshot_binding_invalid")
    _verify_shadow(root, value["shadow"], value["asset_id"])
    return value, source, full


def _export(snapshot):
    excluded = {"content_hash", "policy", "source_snapshot_path", "candidate_audits"}
    body = {k: deepcopy(v) for k, v in snapshot.items() if k not in excluded}
    body.update(contract_id=DETAIL_CONTRACT, rights_status=R.RIGHTS, source_context=R.CONTEXT)
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(raw.encode("utf-8")) > R.MAX_PRIVATE_PAYLOAD_BYTES:
        raise C.TrendlinesError("representative_payload_exceeds_256KiB")
    envelope = {"schema_version": 1, "contract_id": TRANSPORT_CONTRACT, "publication_scope": "private_only",
                "asset_id": body["asset_id"], "snapshot_id": body["snapshot_id"], "payload_json": raw,
                "payload_sha256": _sha(raw.encode("utf-8"))}
    if len(S.encode(envelope)) > R.MAX_PRIVATE_ENVELOPE_BYTES:
        raise C.TrendlinesError("representative_envelope_exceeds_512KiB")
    return envelope


def decode_envelope(envelope, expected_contract=None):
    try:
        if (not isinstance(envelope, dict) or set(envelope) != {"schema_version", "contract_id", "publication_scope", "asset_id", "snapshot_id", "payload_json", "payload_sha256"}
                or type(envelope["schema_version"]) is not int or envelope["schema_version"] != 1
                or envelope["contract_id"] != TRANSPORT_CONTRACT or envelope["publication_scope"] != "private_only"
                or envelope["asset_id"] not in R.SYMBOLS or not SNAPSHOT_RE.fullmatch(envelope["snapshot_id"])
                or len(S.encode(envelope)) > R.MAX_PRIVATE_ENVELOPE_BYTES):
            raise C.TrendlinesError("representative_transport_contract_invalid")
        raw = envelope["payload_json"].encode("utf-8")
        if len(raw) > R.MAX_PRIVATE_PAYLOAD_BYTES or _sha(raw) != envelope["payload_sha256"]:
            raise C.TrendlinesError("representative_transport_payload_binding_invalid")
        def unique(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise C.TrendlinesError("representative_transport_duplicate_key")
                value[key] = item
            return value
        body = json.loads(envelope["payload_json"], object_pairs_hook=unique,
                          parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v)))
        if (body.get("schema_version") != 1 or body.get("contract_id") != DETAIL_CONTRACT
                or (expected_contract is not None and expected_contract != DETAIL_CONTRACT)
                or body.get("asset_id") != envelope["asset_id"] or body.get("snapshot_id") != envelope["snapshot_id"]
                or body.get("policy_version") != POLICY_VERSION or body.get("policy_sha256") != C.canonical_hash(POLICY)
                or body.get("publication_scope") != "private_only" or body.get("rights_status") != R.RIGHTS or body.get("source_context") != R.CONTEXT
                or any(body.get(k) is not False for k in ("verified_source", "official_forecast_write", "verified_boundary", "historical_signals_available"))
                or body.get("events") != [] or set(body["analyses"]) != {"linear", "log"}):
            raise C.TrendlinesError("representative_transport_body_binding_invalid")
        if (not C._finite_number(body["reference_close"]) or body["reference_close"] <= 0
                or type(body["reference_index"]) is not int or body["reference_index"] < 0
                or date.fromisoformat(body["reference_session"]).isoformat() != body["reference_session"]
                or (body["atr14"] is not None and (not C._finite_number(body["atr14"]) or body["atr14"] < 0))
                or not F.SNAPSHOT_RE.fullmatch(body["source_full_snapshot_id"])
                or not re.fullmatch(r"research-snapshot-[0-9a-f]{64}", body["source_snapshot_id"])
                or any(not C.SHA256.fullmatch(body[k]) for k in ("source_archive_sha256", "source_content_hash", "source_engine_content_hash", "source_full_content_hash", "full_manifest_payload_sha256", "input_hash", "input_bar_ids_hash"))):
            raise C.TrendlinesError("representative_transport_reference_invalid")
        cutoff = C.aware_time(body["as_of"])
        future = body["projection_sessions"]
        count = 30 if body["asset_id"] == "bitcoin" else 21
        if (len(future) != count or any(set(p) != {"offset", "index", "session"} or p["offset"] != i
                or p["index"] != body["reference_index"]+i or date.fromisoformat(p["session"]).isoformat() != p["session"]
                for i, p in enumerate(future, 1)) or not all(a["session"] < b["session"] for a, b in zip(future, future[1:]))):
            raise C.TrendlinesError("representative_transport_future_sessions_invalid")
        for axis, view in body["analyses"].items():
            if [p["slot"] for p in view["representatives"]] != list(SLOTS):
                raise C.TrendlinesError("representative_transport_slots_invalid")
            for line in view["representatives"]:
                if line["axis"] != axis or line.get("verified_boundary") is not False:
                    raise C.TrendlinesError("representative_transport_line_flags_invalid")
                if line["status"] == "hold":
                    if not 0 <= line["available_observations"] < line["requested_observations"]:
                        raise C.TrendlinesError("representative_transport_hold_invalid")
                    continue
                if (line["status"] != "ready" or line["kind"] not in {"regression", "pivot_structure"}
                        or line["direction"] != _direction(line["slope"]) or line["role"] not in {"support", "resistance", "direction_only"}
                        or not C._finite_number(line["slope"]) or not C._finite_number(line["intercept"])
                        or line["display_start_index"] != line["coordinate_origin_index"]):
                    raise C.TrendlinesError("representative_transport_geometry_invalid")
                if line["kind"] == "regression":
                    if (line["geometry_status"] != "descriptive" or line["role"] != "direction_only" or line["origin_role"] is not None
                            or line["contact_count"] != 0 or line["contacts"] or line["independent_contacts"]
                            or line["first_anchor"] is not None or line["second_anchor"] is not None or line["markers"]
                            or line["structural_state"] != "descriptive" or line["fit"]["end_index"] != body["reference_index"]):
                        raise C.TrendlinesError("representative_transport_regression_not_pivots")
                else:
                    first, second = line["first_anchor"], line["second_anchor"]
                    if (first["index"] >= second["index"] or first["side"] != second["side"] or line["origin_role"] != first["side"]
                            or first["confirmation_end_index"] >= second["confirmation_start_index"]
                            or line["contact_count"] != len(line["independent_contacts"]) or line["contacts"] != line["independent_contacts"]):
                        raise C.TrendlinesError("representative_transport_pivots_invalid")
                    for anchor in [first, second] + line["contacts"] + line["markers"]:
                        if C.aware_time(anchor["confirmed_at"]) > cutoff or anchor["confirmation_end_index"] > body["reference_index"]:
                            raise C.TrendlinesError("representative_transport_future_pivot")
                    for before, after in zip(line["contacts"], line["contacts"][1:]):
                        if before["confirmation_end_index"] >= after["confirmation_start_index"]:
                            raise C.TrendlinesError("representative_transport_overlapping_contacts")
                    if line["role"] != "direction_only" and (line["structural_state"] not in {"active", "reclaimed"} or not line["formation_valid"]
                            or (line["role"] == "support" and line["current_price"] > body["reference_close"])
                            or (line["role"] == "resistance" and line["current_price"] < body["reference_close"])):
                        raise C.TrendlinesError("representative_transport_false_current_role")
                _near(line["current_price"], _scalar_value(line, body["reference_index"]), "transport_equation")
                if line["current_price_status"] != ("ready" if line["current_price"] is not None else "unavailable_nonpositive_projection"):
                    raise C.TrendlinesError("representative_transport_current_price_status")
                for point in line["points"]:
                    if (type(point["index"]) is not int or not line["display_start_index"] <= point["index"] <= body["reference_index"]
                            or point["future"] is not False or date.fromisoformat(point["session"]).isoformat() != point["session"]):
                        raise C.TrendlinesError("representative_transport_point_invalid")
                    _near(point["price"], _scalar_value(line, point["index"]), "transport_point_equation")
                if len(line["projections"]) != len(future):
                    raise C.TrendlinesError("representative_transport_projection_count")
                for projection, expected in zip(line["projections"], future):
                    if any(projection[k] != value for k, value in expected.items()):
                        raise C.TrendlinesError("representative_transport_projection_date")
                    _near(projection["price"], _scalar_value(line, projection["index"]), "transport_projection_price")
                    if projection["status"] != ("ready" if projection["price"] is not None else "unavailable"):
                        raise C.TrendlinesError("representative_transport_projection_status")
        return body
    except C.TrendlinesError:
        raise
    except (ValueError, KeyError, TypeError, AttributeError, UnicodeError, RecursionError, OverflowError) as exc:
        raise C.TrendlinesError("representative_transport_json_invalid") from exc


@R._audited
def verify(root, *, asset_id=None, replay=True, now=None):
    root = Path(root)
    resolved = str(root.resolve())
    count = 0
    cache = R._ACTIVE_REPLAY_CACHE.get() if replay else None
    functions = (_calculate, _ols, _pivots, _current, _major, _geometry, _pivot_line, _state,
                 _prominent, _independent, _direction, _future, _scalar_verify, _scalar_selection_verify,
                 _scalar_state, _scalar_value, _scalar_atr, _scalar_pivots, R._prepare,
                 E._atr, E._value, E._epsilon, E._pivots, C.session_schedule)
    evidence_functions = functions + (verify, _read_snapshot, _bind_full, _verify_shadow, _export, _evidence, decode_envelope,
                                      F._read_snapshot, F._source_evidence, F._display_metadata, F._exports,
                                      R._checked, R._receipt, R._receipt_of, R._source_replayed, R.asset_definition,
                                      R.research_source_policy)
    pending, decoded = {}, {}
    try:
        policy, pointer, snapshots = load_policy(root), _latest(root), {}
        for path, data, digest in R._audit_reads(sorted(_path(root, ROOT / "snapshots").glob("*.json"))):
            evidence_key = ("representative_evidence", resolved, path.name, digest,
                            tuple(id(f) for f in evidence_functions))
            recalled = cache._recall(evidence_key, evidence_functions) if cache is not None else None
            # Another asset's snapshot is skipped whatever its dependencies hold,
            # so it is identified before they are reread.
            if asset_id is not None and (recalled or R._checked_bytes(data, path.name)).get("asset_id") != asset_id:
                continue
            bound = R._evidence_current(root, recalled)
            if bound is not None and S.aware_time(bound["capture_asof"]) > S.aware_time(now):
                bound = None
            snapshot = source = full = None
            if bound is None:
                snapshot, source, full = _read_snapshot(root, path.stem, now, reparse=replay)
                if S.encode(snapshot) != data:
                    raise C.TrendlinesError("representative_snapshot_identity_or_policy_invalid")
                export_path = _path(root, ROOT / "exports" / snapshot["snapshot_id"] / "detail.json")
                if export_path.read_bytes() != S.encode(_export(snapshot)):
                    raise C.TrendlinesError("representative_export_binding_invalid")
                decode_envelope(S.read_json(export_path))
                bound = _evidence(root, snapshot, source, full)
                if cache is not None:
                    decoded[evidence_key] = (evidence_functions, bound)
            key = ("representative", resolved, bound["content_hash"], digest,
                   bound["source_content_hash"], bound["source_archive_sha256"], bound["raw_sha256"], bound["receipt_sha256"],
                   bound["full_content_hash"], bound["full_manifest_payload_sha256"], C.canonical_hash(policy), tuple(id(f) for f in functions))
            if replay and (cache is None or not cache._contains(key, functions)):
                if source is None:
                    snapshot, source, full = _read_snapshot(root, path.stem, now, reparse=replay)
                    if S.encode(snapshot) != data:
                        raise C.TrendlinesError("representative_snapshot_identity_or_policy_invalid")
                actual = _calculate(source, full, policy)
                if any(snapshot.get(k) != value for k, value in actual.items()):
                    raise C.TrendlinesError("representative_replay_differs")
                pending[key] = functions
            snapshots[bound["snapshot_id"]] = bound
            count += 1
        for asset, row in pointer["assets"].items():
            if asset_id is not None and asset != asset_id:
                continue
            snapshot = snapshots[row["snapshot_id"]]
            sp = ROOT / "snapshots" / (snapshot["snapshot_id"] + ".json")
            ep = ROOT / "exports" / snapshot["snapshot_id"] / "detail.json"
            if (snapshot["asset_id"] != asset or row["snapshot_path"] != sp.as_posix() or row["detail_path"] != ep.as_posix()
                    or row["snapshot_sha256"] != R._audit_digest(_path(root, sp))[0]
                    or row["detail_sha256"] != R._audit_digest(_path(root, ep))[0]):
                raise C.TrendlinesError("representative_latest_snapshot_binding_invalid")
        if cache is not None:
            cache._remember(pending, decoded)
        return {"ok": True, "errors": [], "snapshots": count, "replay": replay}
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        return {"ok": False, "errors": [str(exc)], "snapshots": count, "replay": replay}


def refresh(root, asset_id, now=None):
    R._check_replay_asset(asset_id)
    root = Path(root)
    with S.writer_lock(root):
        audit = verify(root, asset_id=asset_id, replay=True, now=now)
        if not audit["ok"]:
            raise C.TrendlinesError("representative_existing_integrity_failed: " + "; ".join(audit["errors"]))
        policy = load_policy(root)
        source, source_pointer, full, manifest = _sources(root, asset_id, now, reparse=True)
        if source is None:
            return {"changed": False, "asset_id": asset_id, "status": "hold", "reason_codes": ["missing_research_ohlc"]}
        pointer = _latest(root)
        prior = pointer["assets"].get(asset_id)
        if prior:
            previous, _, _ = _read_snapshot(root, prior["snapshot_id"], now)
            if previous["source_snapshot_id"] == source["snapshot_id"] and previous["source_full_snapshot_id"] == full["snapshot_id"]:
                return {"changed": False, "asset_id": asset_id, "status": "ready", "representative_snapshot_id": previous["snapshot_id"], "detail_path": prior["detail_path"]}
        computation = _calculate(source, full, policy)
        body = {"schema_version": 1, "contract_id": "trendlines_private_representative_snapshot_v1", "asset_id": asset_id,
                "publication_scope": "private_only", "official_forecast_write": False, "verified_source": False,
                "verified_boundary": False, "historical_signals_available": False, "events": [], "policy_version": POLICY_VERSION,
                "as_of": source["capture_asof"], "source_snapshot_id": source["snapshot_id"],
                "source_snapshot_path": source_pointer["snapshot_path"], "source_archive_sha256": source_pointer["snapshot_sha256"],
                "source_content_hash": source["content_hash"], "source_full_snapshot_id": full["snapshot_id"],
                "source_full_content_hash": full["content_hash"], "source_engine_content_hash": source["engine_snapshot"]["content_hash"],
                "source_engine_snapshot_id": source["engine_snapshot"]["snapshot_id"], "full_manifest_payload_sha256": manifest["payload_sha256"],
                "shadow": _strict_shadow(root, asset_id, source), **computation}
        body["snapshot_id"] = SNAPSHOT_PREFIX + C.canonical_hash(body)
        snapshot = _hash(body)
        envelope = _export(snapshot)
        decode_envelope(envelope)
        current_source, current_pointer, current_full, _ = _sources(root, asset_id, now, reparse=True)
        if current_source != source or current_pointer != source_pointer or current_full != full:
            raise C.TrendlinesError("representative_source_changed_during_calculation")
        snapshot_path = ROOT / "snapshots" / (snapshot["snapshot_id"] + ".json")
        export_path = ROOT / "exports" / snapshot["snapshot_id"] / "detail.json"
        S.atomic_json(_path(root, export_path), envelope, immutable=True)
        S.atomic_json(_path(root, snapshot_path), snapshot, immutable=True)
        final_source, final_pointer, final_full, _ = _sources(root, asset_id, now)
        if final_source != source or final_pointer != source_pointer or final_full != full:
            raise C.TrendlinesError("representative_source_changed_before_pointer_exchange")
        assets = deepcopy(pointer["assets"])
        assets[asset_id] = {"snapshot_id": snapshot["snapshot_id"], "snapshot_path": snapshot_path.as_posix(),
                            "snapshot_sha256": _sha(S.encode(snapshot)), "detail_path": export_path.as_posix(), "detail_sha256": _sha(S.encode(envelope))}
        S.atomic_json(_path(root, ROOT / "latest.json"), _hash({"schema_version": 1,
                      "contract_id": "trendlines_private_representative_latest_v1", "assets": assets}))
        return {"changed": True, "asset_id": asset_id, "status": "ready", "representative_snapshot_id": snapshot["snapshot_id"],
                "source_snapshot_id": source["snapshot_id"], "detail_path": export_path.as_posix(), "validation": snapshot["independent_validation"]}


def load_detail(root, asset_id, now=None, *, source_snapshot_id=None):
    """Read a verified export, optionally pinned to the delivered OHLC cohort.

    Pending raw captures do not replace an already delivered cohort. The
    unpinned path remains strict for refresh/promotion callers.
    """
    root = Path(root)
    if asset_id not in R.SYMBOLS:
        raise C.TrendlinesError("representative_asset_has_no_research_source")
    load_policy(root)
    pointer = _latest(root)["assets"].get(asset_id)
    if pointer is None:
        return None
    snapshot, source, full = _read_snapshot(root, pointer["snapshot_id"], now)
    if source_snapshot_id is None:
        current_source, _, current_full, _ = _sources(root, asset_id, now)
        if current_source != source or current_full != full:
            raise C.TrendlinesError("representative_snapshot_is_not_current_source")
    else:
        # _read_snapshot above verifies the immutable source, original bytes,
        # full series and arithmetic. Still require the selected full manifest
        # to agree; this is not a fallback to an arbitrary historical line.
        manifest = F.load_manifest(root, asset_id, now=now)
        if (source["snapshot_id"] != source_snapshot_id or manifest is None
                or manifest["snapshot_id"] != full["snapshot_id"]
                or manifest["payload_sha256"] != snapshot["full_manifest_payload_sha256"]):
            raise C.TrendlinesError("representative_snapshot_is_not_served_cohort")
    sp = ROOT / "snapshots" / (snapshot["snapshot_id"] + ".json")
    ep = ROOT / "exports" / snapshot["snapshot_id"] / "detail.json"
    path = S.safe_path(root, pointer["detail_path"])
    envelope = S.read_json(path)
    if (pointer["snapshot_path"] != sp.as_posix() or pointer["detail_path"] != ep.as_posix()
            or pointer["snapshot_sha256"] != _sha(_path(root, sp).read_bytes()) or pointer["detail_sha256"] != _sha(path.read_bytes())
            or envelope != _export(snapshot)):
        raise C.TrendlinesError("representative_export_latest_binding_invalid")
    decode_envelope(envelope)
    return envelope
