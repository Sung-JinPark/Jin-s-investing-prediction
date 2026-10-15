"""Additive representative geometry uses source fixtures and disposable stores."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil

import pytest

from ai_fc.trendlines import contracts as C, engine as E, full_history as F, representative as V, research as R, storage as S
from test_trendlines_critical import capture, original_bytes

REPOSITORY = Path(__file__).resolve().parents[2]
FIRST = datetime(2022, 7, 1, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    for relative in (C.CONTRACT_RELATIVE, C.ASSET_REGISTRY_RELATIVE, C.SOURCE_POLICY_RELATIVE, V.POLICY_RELATIVE):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPOSITORY / relative, target)
    return tmp_path


def rows(count=300, gaps=(), flat=False):
    output = []
    lows = {30, 80, 120, 150, 175, 195, 230, 260, 290}
    highs = {45, 95, 135, 165, 190, 215, 245, 275}
    stamp = (FIRST + timedelta(days=count+1)).isoformat()
    for i in range(count):
        if i in gaps:
            continue
        base = 100.0 if flat else 100+i*.1
        output.append({"session_date": (FIRST+timedelta(days=i)).date().isoformat(), "session_index": i,
                       "open": base+5, "close": base+5, "low": base if i in lows else base+3,
                       "high": base+10 if i in highs else base+8,
                       "bar_id": "research-bar-"+hashlib.sha256(str(i).encode()).hexdigest(),
                       "available_at": stamp, "fetched_at": stamp,
                       "finalized_at": (FIRST+timedelta(days=i+1)).isoformat()})
    return output


def inputs(observations):
    source = {"snapshot_id": "research-snapshot-"+"1"*64, "config": C.default_config(),
              "asset": {"asset_id": "bitcoin", "kind": "crypto", "calendar_id": "24/7", "tick_size": 0.0}}
    full = {"source_snapshot_id": source["snapshot_id"], "bars": observations, "input_hash": C.canonical_hash(observations)}
    return source, full


def test_policy_is_exact_versioned_contract(store):
    assert V.load_policy(store) == V.POLICY
    path = store/V.POLICY_RELATIVE
    path.write_text(path.read_text().replace("observations: 200", "observations: 199"))
    with pytest.raises(ValueError, match="versioned_contract"):
        V.load_policy(store)


@pytest.mark.parametrize("axis", ["linear", "log"])
def test_200_ols_uses_exact_finalized_observations_original_session_gaps(axis):
    observations = rows(gaps=(130, 149, 231))
    source, full = inputs(observations)
    line = V._ols(observations, 200, axis, "regression_200", V._future(observations, source["asset"]))
    sample = observations[-200:]
    assert line["fit"]["n"] == 200
    assert line["fit"]["start_index"] == sample[0]["session_index"]
    assert line["fit"]["missing_sessions"] == 3
    if axis == "linear":
        assert line["slope"] == pytest.approx(.1)
        assert line["intercept"] == pytest.approx(sample[0]["close"])
        assert line["fit"]["rmse"] < 1e-12
    else:
        assert line["slope"] > 0
        assert line["fit"]["residual_axis"] == "natural_log_price"
    assert line["first_anchor"] is line["second_anchor"] is None
    assert line["contacts"] == [] and line["contact_count"] == 0
    assert line["role"] == "direction_only" and line["verified_boundary"] is False


def test_ols_intercept_is_never_shifted_to_last_close_and_constant_r_squared_is_null():
    observations = rows()
    source, _ = inputs(observations)
    future = V._future(observations, source["asset"])
    observations[-1].update(close=observations[-1]["close"]+50, high=observations[-1]["high"]+50)
    line = V._ols(observations, 200, "linear", "regression_200", future)
    assert line["current_price"] != observations[-1]["close"]
    constant = V._ols(rows(flat=True), 200, "linear", "regression_200", future)
    assert constant["fit"]["r_squared"] is None
    assert constant["direction"] == "flat"


def test_three_families_have_verified_pivots_and_no_synthetic_regression_contacts():
    source, full = inputs(rows())
    result = V._calculate(source, full)
    assert result["independent_validation"]["independent_candidate_completeness_and_rank"]
    for axis, view in result["analyses"].items():
        assert [p["slot"] for p in view["representatives"]] == list(V.SLOTS)
        assert all(p["status"] == "ready" for p in view["representatives"])
        current = view["representatives"][1]
        assert current["kind"] == "pivot_structure"
        assert current["structural_state"] == "active"
        assert current["role"] == "support"
        assert current["contact_count"] >= 2 and current["verified_boundary"] is False
        assert current["second_anchor"]["index"]-current["first_anchor"]["index"] >= 10
        major = view["representatives"][2]
        assert major["kind"] == "pivot_structure"
        assert major["major_anchor_ids"]
        assert major["second_anchor"]["index"]-major["first_anchor"]["index"] >= 60
        assert all(point["price"] > 0 for point in major["projections"])


def test_missing_or_unconfirmed_pivots_use_exact_ols_fallback():
    observations = rows()
    for row in observations:
        row["low"] = row["close"]-2
        row["high"] = row["close"]+2
    source, full = inputs(observations)
    result = V._calculate(source, full)
    for view in result["analyses"].values():
        assert [line["kind"] for line in view["representatives"]] == ["regression"]*3
        assert [line["fit"]["n"] for line in view["representatives"]] == [200, 63, 252]
        assert view["representatives"][1]["fallback_reason"] == "no_intact_recent_pivot_structure"
        assert all(line["contact_count"] == 0 for line in view["representatives"])


def test_pivots_wait_for_right_confirmation_and_choose_first_tie():
    observations = rows(80)
    for row in observations:
        row["low"] = 110
    observations[30]["low"] = observations[31]["low"] = 100
    observations[-2]["low"] = 90
    pivots = V._pivots(observations, 3, 3)
    lows = [p for p in pivots if p["side"] == "support"]
    assert [p["index"] for p in lows] == [30]
    assert lows[0]["confirmation_end_index"] == 33
    assert not [p for p in V._pivots([r for r in observations if r["session_index"] != 32], 3, 3) if p["side"] == "support"]


def test_major_broken_or_penetrated_structure_never_flips_role():
    observations = rows()
    source, full = inputs(observations)
    pivots = V._pivots(observations, 10, 10)
    first = next(p for p in pivots if p["index"] == 80 and p["side"] == "support")
    second = next(p for p in pivots if p["index"] == 230 and p["side"] == "support")
    for row in observations[-3:]:
        row.update(open=100, close=100, low=99, high=102)
    atr = E._atr(observations, 14, segmented=True)
    line = V._pivot_line(first, second, pivots, observations, atr, source["asset"], source["config"], "linear", "major_structure", V._future(observations, source["asset"]))
    assert line["structural_state"] == "broken"
    assert line["role"] == "direction_only" and line["origin_role"] == "support"
    assert line["structural_review"]["historical_signals_available"] is False


def test_gaps_reset_two_finalized_close_state_confirmation():
    observations = rows()
    source, _ = inputs(observations)
    pivots = V._pivots(observations, 3, 3)
    first = next(p for p in pivots if p["index"] == 260 and p["side"] == "support")
    second = next(p for p in pivots if p["index"] == 290 and p["side"] == "support")
    for row in observations[-3:]:
        row.update(close=80, low=79, high=81, open=80)
    observations.pop(-2)
    atr = E._atr(observations, 14, segmented=True)
    line = V._pivot_line(first, second, pivots, observations, atr, source["asset"], source["config"], "linear", "current_structure", V._future(observations, source["asset"]))
    assert line["structural_review"]["break_sessions"] == []


def test_independent_oracle_rejects_candidate_omission_rank_and_bad_formula():
    source, full = inputs(rows())
    result = V._calculate(source, full)
    bad = deepcopy(result)
    bad["candidate_audits"]["linear"]["current_structure"]["eligible_line_ids"].pop()
    with pytest.raises(ValueError, match="completeness_or_rank"):
        V._scalar_selection_verify(full["bars"], source["asset"], source["config"], bad, V._scalar_atr(full["bars"]), V.POLICY)
    bad = deepcopy(result)
    bad["analyses"]["linear"]["representatives"][0]["slope"] += .01
    with pytest.raises(ValueError, match="ols_slope"):
        V._scalar_verify(full["bars"], source["asset"], source["config"], bad, V._pivots(full["bars"], 3, 3), V._pivots(full["bars"], 10, 10), V.POLICY)


def test_insufficient_fit_is_hold_without_changing_requested_period():
    observations = rows(120)
    source, full = inputs(observations)
    result = V._calculate(source, full)
    assert result["analyses"]["linear"]["representatives"][0]["status"] == "hold"
    assert result["analyses"]["linear"]["representatives"][0]["requested_observations"] == 200


def test_refresh_is_additive_idempotent_bounded_and_never_legacy_curve_replays(store, monkeypatch):
    source, stamp = capture(store, count=300)
    before = original_bytes(store)
    monkeypatch.setattr(R, "verify", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("legacy replay")))
    monkeypatch.setattr(F, "verify", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("legacy replay")))
    first = V.refresh(store, "bitcoin", now=stamp)
    second = V.refresh(store, "bitcoin", now=stamp)
    assert first["changed"] and not second["changed"]
    assert first["representative_snapshot_id"] == second["representative_snapshot_id"]
    assert before == original_bytes(store)
    assert V.verify(store, now=stamp)["ok"]
    envelope = V.load_detail(store, "bitcoin", now=stamp)
    body = V.decode_envelope(envelope)
    assert body["source_snapshot_id"] == source["snapshot_id"]
    assert body["full_manifest_payload_sha256"] == F.load_manifest(store, "bitcoin", now=stamp)["payload_sha256"]
    assert body["events"] == []
    assert all(body[k] is False for k in ("verified_source", "verified_boundary", "historical_signals_available", "official_forecast_write"))
    assert len(envelope["payload_json"].encode()) <= 256*1024


@pytest.mark.parametrize("target", ["raw", "source", "full", "representative", "export", "pointer"])
def test_corruption_fails_closed_without_replacing_pointer(store, target):
    _, stamp = capture(store, count=260)
    result = V.refresh(store, "bitcoin", now=stamp)
    pointer = store/V.ROOT/"latest.json"
    original_pointer = pointer.read_bytes()
    if target == "raw": path = next((store/R.ROOT/"raw").glob("*"))
    elif target == "source": path = next((store/R.ROOT/"snapshots").glob("*"))
    elif target == "full": path = next((store/F.ROOT/"snapshots").glob("*"))
    elif target == "representative": path = next((store/V.ROOT/"snapshots").glob("*"))
    elif target == "export": path = store/result["detail_path"]
    else: path = pointer
    path.write_bytes(path.read_bytes()+b" ")
    with pytest.raises(ValueError):
        V.load_detail(store, "bitcoin", now=stamp)
    with pytest.raises(ValueError):
        V.refresh(store, "bitcoin", now=stamp)
    assert pointer.read_bytes() == (original_pointer+b" " if target == "pointer" else original_pointer)


def test_source_reparse_blocks_self_consistent_tampered_ohlc(store, monkeypatch):
    _, stamp = capture(store, count=260)
    original_prepare = R._prepare
    def changed(*a, **kw):
        bars, metadata, gaps = original_prepare(*a, **kw)
        bars[-1]["close"] += .01
        return bars, metadata, gaps
    monkeypatch.setattr(R, "_prepare", changed)
    with pytest.raises(ValueError, match="differs_from_original_html"):
        V.refresh(store, "bitcoin", now=stamp)
    assert not (store/V.ROOT/"latest.json").exists()


def test_calendar_projections_and_no_future_ohlc():
    observations = rows()
    source, _ = inputs(observations)
    future = V._future(observations, source["asset"])
    assert len(future) == 30 and future[0]["offset"] == 1 and future[-1]["offset"] == 30
    assert all(set(p) == {"offset", "index", "session"} for p in future)
    asset = {**source["asset"], "kind": "equity", "calendar_id": "XKRX"}
    schedule = C.session_schedule("XKRX", "2026-01-02", "2026-10-14")
    observations = [{"session_date": day, "session_index": i} for i, (day, _, _) in enumerate(schedule)]
    assert len(V._future(observations, asset)) == 21


def test_dominant_cycle_peak_beats_larger_local_prominence_at_same_recent_anchor():
    observations = rows(235)
    for row in observations:
        row.update(open=142.0, close=142.0, low=138.0, high=146.0)
    for i, high in ((80, 169.0), (160, 300.0), (222, 194.0)):
        observations[i]["high"] = high
    observations[222]["low"] = 100.0  # The recent high anchor is also the cycle's confirmed low.
    source, _ = inputs(observations)
    pivots = V._pivots(observations, 10, 10)
    atr = [30.0]*len(observations)
    atr[80], atr[160], atr[222] = 4.0, 30.0, 14.0
    enriched, _ = V._prominent(pivots, observations, atr, V.POLICY)
    local = next(p for p in enriched if p["index"] == 80)
    dominant = next(p for p in enriched if p["index"] == 160)
    assert local["prominence"] > dominant["prominence"]
    for axis in ("linear", "log"):
        line, _ = V._major(observations, atr, source["asset"], source["config"], axis,
                           V._future(observations, source["asset"]), pivots, V.POLICY)
        assert line["first_anchor"]["index"] == 160
        assert line["second_anchor"]["index"] == 222
        assert line["dominant_cycle_extremum_contains"]
        outside_markers = [p for p in line["markers"] if p["index"] == 222]
        assert {p["side"] for p in outside_markers} == {"support", "resistance"}


def test_outside_bar_high_and_low_connections_have_distinct_ids_and_side_binding():
    observations = rows()
    for i, low, high in ((80, 1.0, 1000.0), (160, 2.0, 800.0)):
        observations[i].update(low=low, high=high)
    source, _ = inputs(observations)
    pivots = V._pivots(observations, 10, 10)
    atr = E._atr(observations, 14, segmented=True)
    lines = []
    for side in ("support", "resistance"):
        first = next(p for p in pivots if p["index"] == 80 and p["side"] == side)
        second = next(p for p in pivots if p["index"] == 160 and p["side"] == side)
        lines.append(V._pivot_line(first, second, pivots, observations, atr, source["asset"], source["config"],
                                   "linear", "major_structure", V._future(observations, source["asset"])))
    assert lines[0]["first_anchor"]["bar_id"] == lines[1]["first_anchor"]["bar_id"]
    assert lines[0]["second_anchor"]["bar_id"] == lines[1]["second_anchor"]["bar_id"]
    assert lines[0]["line_id"] != lines[1]["line_id"]


def test_log_constant_price_r_squared_is_undefined_even_for_small_price():
    observations = rows()
    for row in observations:
        row["close"] = 1e-12
    source, _ = inputs(observations)
    line = V._ols(observations, 252, "log", "major_structure", V._future(observations, source["asset"]))
    assert line["fit"]["r_squared"] is None
    assert line["fit"]["rmse"] == 0 and line["slope"] == 0


def test_bounded_replay_cache_skips_only_math_invalidates_functions_and_never_hides_raw_tampering(store, monkeypatch):
    _, stamp = capture(store, count=260)
    V.refresh(store, "bitcoin", now=stamp)
    original = V._calculate
    calls = []
    def tracked(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(V, "_calculate", tracked)
    cache = R.VerifiedReplayCache(max_entries=2)
    with R.use_verified_replay_cache(cache):
        assert V.verify(store, now=stamp)["ok"] and len(calls) == 1
        assert V.verify(store, now=stamp)["ok"] and len(calls) == 1
        assert cache.entry_count == 1
        def replacement(*args, **kwargs):
            return tracked(*args, **kwargs)
        monkeypatch.setattr(V, "_calculate", replacement)
        assert V.verify(store, now=stamp)["ok"] and len(calls) == 2
    assert V.verify(store, now=stamp)["ok"] and len(calls) == 3
    snapshot = next((store/V.ROOT/"snapshots").glob("*.json"))
    original_snapshot = snapshot.read_bytes()
    snapshot.write_bytes(original_snapshot+b" ")
    with R.use_verified_replay_cache(cache):
        assert not V.verify(store, now=stamp)["ok"]
    assert len(calls) == 3
    snapshot.write_bytes(original_snapshot)  # Restore only this disposable corruption fixture.
    raw = next((store/R.ROOT/"raw").glob("*"))
    raw.write_bytes(raw.read_bytes()+b" ")
    with R.use_verified_replay_cache(cache):
        assert not V.verify(store, now=stamp)["ok"]
    assert len(calls) == 3


def test_failed_verification_does_not_populate_replay_cache(store):
    _, stamp = capture(store, count=260)
    result = V.refresh(store, "bitcoin", now=stamp)
    export = store/result["detail_path"]
    export.write_bytes(export.read_bytes()+b" ")
    cache = R.VerifiedReplayCache()
    with R.use_verified_replay_cache(cache):
        assert not V.verify(store, now=stamp)["ok"]
    assert cache.entry_count == 0


def test_get_is_read_only_without_normalization_calculation_or_reparse_and_calendar_binding_fails_closed(store, monkeypatch):
    _, stamp = capture(store, count=260)
    V.refresh(store, "bitcoin", now=stamp)
    def forbidden(*args, **kwargs):
        raise AssertionError("GET attempted normalization, ingestion or arithmetic")
    monkeypatch.setattr(V, "_calculate", forbidden)
    monkeypatch.setattr(F, "_normalize", forbidden)
    monkeypatch.setattr(R, "_prepare", forbidden)
    assert V.decode_envelope(V.load_detail(store, "bitcoin", now=stamp))["reference_close"] > 0
    original = F._read_snapshot
    def changed_coordinate(*args, **kwargs):
        full, source = original(*args, **kwargs)
        full["bars"][50]["session_index"] += 1
        full["input_hash"] = C.canonical_hash(full["bars"])
        return full, source
    monkeypatch.setattr(F, "_read_snapshot", changed_coordinate)
    with pytest.raises(ValueError, match="calendar_coordinate_binding"):
        V.load_detail(store, "bitcoin", now=stamp)


def test_requested_asset_replay_does_not_reparse_other_assets(store, monkeypatch):
    _, stamp = capture(store, count=260)
    result = V.refresh(store, "bitcoin", now=stamp)
    path = store/V.ROOT/"snapshots"/("representative-snapshot-"+"f"*64+".json")
    unrelated = {"asset_id": "soxx"}
    S.atomic_json(path, {**unrelated, "content_hash": C.canonical_hash(unrelated)}, immutable=True)
    original = V._read_snapshot
    def only_requested(root, snapshot_id, *args, **kwargs):
        assert snapshot_id == result["representative_snapshot_id"]
        return original(root, snapshot_id, *args, **kwargs)
    monkeypatch.setattr(V, "_read_snapshot", only_requested)
    assert V.verify(store, asset_id="bitcoin", now=stamp)["ok"]
