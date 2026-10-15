"""Separate numerical oracle and adversarial input checks for representative fits.

No test collects, refreshes or opens a durable database/source store.
"""
from __future__ import annotations

import hashlib
import math
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from ai_fc.trendlines import contracts as C, representative as V

REPOSITORY = Path(__file__).resolve().parents[2]
KNOWN = "2026-10-15T00:00:00+00:00"


def rows_for(values, *, gaps=False, offset=0):
    result = []
    for i, value in enumerate(values):
        index = i + (i >= len(values)//3 if gaps else 0) + (i >= 2*len(values)//3 if gaps else 0)
        result.append({"session_index": index + offset,
            "session_date": (date(2022, 7, 1) + timedelta(days=index)).isoformat(),
            "open": value, "high": value * 1.02, "low": value * .98, "close": value,
            "bar_id": "research-bar-" + hashlib.sha256(str((i, value)).encode()).hexdigest(),
            "available_at": KNOWN, "fetched_at": KNOWN})
    return result


def future_for(rows, count=30):
    end = date.fromisoformat(rows[-1]["session_date"])
    return [{"index": rows[-1]["session_index"] + i, "offset": i,
             "session": (end + timedelta(days=i)).isoformat()} for i in range(1, count+1)]


def normal_equations(rows, axis):
    """70-digit absolute-coordinate normal equations, independent of V's fit."""
    with localcontext() as context:
        context.prec = 70
        x = [Decimal(row["session_index"]) for row in rows]
        y = [Decimal(str(row["close"])) for row in rows]
        if axis == "log":
            y = [value.ln() for value in y]
        n = Decimal(len(x)); sx, sy = sum(x), sum(y)
        slope = (n*sum(a*b for a, b in zip(x, y))-sx*sy)/(n*sum(a*a for a in x)-sx*sx)
        intercept = (sy-slope*sx)/n
        return slope, intercept


def evaluate(line, index):
    value = line["intercept"] + line["slope"]*(index-line["coordinate_origin_index"])
    result = math.exp(value) if line["axis"] == "log" else value
    return result if math.isfinite(result) and result > 0 else None


def source_for(rows):
    source = {"snapshot_id": "research-snapshot-" + "a"*64,
        "config": C.default_config(), "asset": deepcopy(C.load_asset_registry(REPOSITORY)["bitcoin"])}
    full = {"source_snapshot_id": source["snapshot_id"], "bars": rows, "input_hash": C.canonical_hash(rows)}
    return source, full


@pytest.mark.parametrize("axis", ["linear", "log"])
@pytest.mark.parametrize("count", [63, 200, 252])
def test_fit_matches_high_precision_normal_equations_with_real_calendar_gaps(axis, count):
    rows = rows_for([100 + i*.2 + 3*math.sin(i/13) for i in range(count+10)], gaps=True)
    sample = rows[-count:]
    line = V._ols(rows, count, axis, "regression_200", future_for(rows))
    slope, absolute_intercept = normal_equations(sample, axis)
    for index in [sample[0]["session_index"], sample[-1]["session_index"], rows[-1]["session_index"]+30]:
        exact = absolute_intercept + slope*Decimal(index)
        expected = float(exact.exp() if axis == "log" else exact)
        assert evaluate(line, index) == pytest.approx(expected, rel=1e-10, abs=1e-6)
    assert line["fit"]["n"] == count
    assert line["fit"]["session_span"] == sample[-1]["session_index"]-sample[0]["session_index"]+1
    assert line["fit"]["missing_sessions"] == line["fit"]["session_span"]-count > 0
    assert line["fit"]["input_bar_ids_hash"] == C.canonical_hash([r["bar_id"] for r in sample])
    assert line["first_anchor"] is None and line["second_anchor"] is None
    assert line["contact_count"] == 0 and line["contacts"] == []
    assert line["verified_boundary"] is False and line["role"] == "direction_only"


@pytest.mark.parametrize("axis", ["linear", "log"])
def test_translating_calendar_origin_does_not_move_fit_or_create_a_last_close_anchor(axis):
    values = [100 + i*.3 + 4*math.sin(i/9) for i in range(200)]
    ordinary, shifted = rows_for(values), rows_for(values, offset=10**9)
    left = V._ols(ordinary, 200, axis, "regression_200", future_for(ordinary))
    right = V._ols(shifted, 200, axis, "regression_200", future_for(shifted))
    assert left["slope"] == right["slope"] and left["intercept"] == right["intercept"]
    assert left["current_price"] == right["current_price"]
    assert abs(left["current_price"]-values[-1]) > .1


@pytest.mark.parametrize("count", [63, 252])
def test_constant_log_response_has_undefined_r_squared_not_false_zero_fit_quality(count):
    rows = rows_for([1e-12]*count)
    line = V._ols(rows, count, "log", "current_structure", future_for(rows))
    assert line["slope"] == 0
    assert line["fit"]["r_squared"] is None
    assert line["current_price"] == pytest.approx(1e-12, rel=1e-10, abs=0)


def test_positive_ohlc_can_make_only_the_200_linear_current_value_unavailable():
    rows = rows_for([1000. if 600 <= i < 650 else 100. for i in range(800)])
    source, full = source_for(rows)
    before = C.canonical_hash((source, full))
    result = V._calculate(source, full)
    by_slot = {line["slot"]: line for line in result["analyses"]["linear"]["representatives"]}
    bad = by_slot["regression_200"]
    assert bad["status"] == "ready" and bad["current_price"] is None
    assert bad["current_price_status"] == "unavailable_nonpositive_projection"
    assert bad["slope"] == pytest.approx(-5.062626565664142)
    assert bad["intercept"] == pytest.approx(828.7313432835822)
    assert all(p["price"] is None and p["status"] == "unavailable" for p in bad["projections"])
    assert by_slot["current_structure"]["current_price"] == 100.
    assert by_slot["major_structure"]["current_price"] == pytest.approx(71.06154714850368)
    assert all(line["current_price"] > 0 for line in result["analyses"]["log"]["representatives"])
    assert C.canonical_hash((source, full)) == before


def test_large_atr_cannot_let_a_near_zero_major_pivot_line_replace_a_realistic_structure():
    rows = rows_for([100.]*800)
    for row in rows:
        row["high"], row["low"] = 190., 10.
    for index in (100, 300, 600):
        rows[index]["low"] = 1.
    source, full = source_for(rows)
    result = V._calculate(source, full)
    for view in result["analyses"].values():
        major = next(line for line in view["representatives"] if line["slot"] == "major_structure")
        assert major["kind"] == "regression" and major["current_price"] == pytest.approx(100.)
        assert major["verified_boundary"] is False


def test_two_observed_pivot_ties_are_not_two_independent_confirmed_peaks():
    rows = rows_for([100 + i*.01 for i in range(80)])
    rows[30]["low"] = rows[31]["low"] = 80.
    rows[78]["low"] = 70.  # Last two observations cannot confirm a right-3 pivot.
    lows = [p for p in V._pivots(rows, 3, 3) if p["side"] == "support"]
    assert [p["index"] for p in lows] == [30]
    assert lows[0]["confirmation_end_index"] == 33


@pytest.mark.parametrize("axis", ["linear", "log"])
def test_outside_bars_on_both_sides_have_distinct_current_structure_identities(axis):
    rows = rows_for([100+i*.1 for i in range(800)])
    for index in (740, 760):
        rows[index]["high"] = rows[index]["close"]+10
        rows[index]["low"] = rows[index]["close"]-10
    source, full = source_for(rows)
    result = V._calculate(source, full)
    ids = result["candidate_audits"][axis]["current_structure"]["eligible_line_ids"]
    assert len(ids) >= 2
    assert len(ids) == len(set(ids))
    assert result["independent_validation"]["status"] == "passed"
