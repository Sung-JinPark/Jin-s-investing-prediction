"""Disposable synthetic price geometry; never production market data."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from ai_fc.trendlines import contracts as C
from ai_fc.trendlines import engine as E


ROOT = Path(__file__).resolve().parents[2]


def fixture_inputs(count: int = 100, *, break_and_reclaim: bool = False) -> tuple[dict, list[dict], str, dict, dict]:
    """For engine/UI integration tests only, with an explicitly fake provider."""
    asset = deepcopy(C.load_asset_registry(ROOT)["bitcoin"])
    asset.update({"enabled": True, "source_id": "fixture_ohlc", "name": "TEST FIXTURE — not market data"})
    policy = {"sources": {"fixture_ohlc": {"rights_status": "approved_free", "allow_collection": True,
              "allow_derived_display": True, "allow_ohlc": True, "asset_ids": ["bitcoin"],
              "allowed_price_bases": ["published_spot_price"], "calendar_ids": ["24/7"],
              "allowed_domains": ["fixture.invalid"], "parser_id": "json_ohlc_v1", "adjustment_method": "none"}}}
    bars = []
    first = date(2024, 1, 1)
    for index in range(count):
        session = first + timedelta(days=index)
        closed = datetime.combine(session + timedelta(days=1), datetime.min.time(), timezone.utc)
        low = 100.0 + index * 0.1 + abs(index % 20 - 10) * 0.6
        close = low + 2.0
        if break_and_reclaim and index in (94, 95):
            low, close = 100.0 + index * 0.1 - 4.0, 100.0 + index * 0.1 - 3.0
        if break_and_reclaim and index in (96, 97):
            low, close = 100.0 + index * 0.1 + 1.0, 100.0 + index * 0.1 + 3.0
        available = closed + timedelta(minutes=20)
        bars.append({"bar_id": f"fixture-bar-{index:04d}", "asset_id": "bitcoin", "source_id": "fixture_ohlc",
                     "session_date": session.isoformat(), "open": low + 1, "high": max(low + 4, close), "low": low,
                     "close": close, "volume": 100, "currency": "USD", "unit": "USD_per_BTC",
                     "price_basis": "published_spot_price", "calendar_id": "24/7", "available_at": available.isoformat(),
                     "fetched_at": available.isoformat(), "finalized_at": closed.isoformat(), "revision_seq": 1,
                     "supersedes_bar_id": None, "raw_sha256": C.canonical_hash({"fixture": index}), "receipt_id": f"fixture-receipt-{index:04d}"})
    cutoff = (C.aware_time(bars[-1]["available_at"]) + timedelta(minutes=10)).isoformat()
    return asset, bars, cutoff, C.default_config(), policy


def build(inputs: tuple) -> dict:
    asset, bars, cutoff, config, policy = inputs
    return E.build_asset_snapshot(asset, bars, cutoff, config=config, source_policy=policy)


def rehash(snapshot: dict) -> dict:
    body = {key: value for key, value in snapshot.items() if key not in {"snapshot_id", "content_hash"}}
    return E._finish(body)


def test_seven_assets_are_explicit_stable_hold_without_fake_data() -> None:
    config, assets, policy = C.load_contract(ROOT), C.load_asset_registry(ROOT), C.load_source_policy(ROOT)
    assert tuple(assets) == C.ASSET_IDS and policy["sources"] == {}
    for asset in assets.values():
        first = E.build_asset_snapshot(asset, [], "2026-10-13T01:00:00+00:00", config=config, source_policy=policy)
        later = E.build_asset_snapshot(asset, [], "2026-10-14T01:00:00+00:00", config=config, source_policy=policy)
        assert first == later
        assert first["status"] == "hold" and first["reason_codes"] == ["missing_approved_ohlc"]
        assert first["as_of"] is None and not first["bars"] and not first["events"]
        assert E.verify_asset_snapshot(first, [], asset, config=config, source_policy=policy)["ok"]


def test_confirmed_geometry_linear_log_and_independent_replay() -> None:
    inputs = fixture_inputs()
    asset, bars, _cutoff, config, policy = inputs
    snapshot = build(inputs)
    assert snapshot["status"] == "ready"
    assert snapshot["analyses"]["linear"]["252"]["reason_codes"] == ["insufficient_history"]
    assert snapshot["analyses"]["linear"]["63"]["lines"]
    for axis in ("linear", "log"):
        analysis = snapshot["analyses"][axis]["63"]
        assert analysis["projection_sessions"][1]["offset"] == 7
        assert analysis["projection_sessions"][-1]["offset"] == 30
        assert all(line["geometry_status"] == ("confirmed" if line["touch_count"] >= 3 else "candidate") for line in analysis["lines"])
    verified = E.verify_asset_snapshot(snapshot, bars, asset, config=config, source_policy=policy)
    assert verified["ok"], verified
    assert snapshot == build(inputs)


def test_pivot_confirmation_delay_and_first_plateau_not_window_edge() -> None:
    asset, bars, cutoff, config, policy = fixture_inputs(80)
    rows = E._select_rows(bars, asset, cutoff, policy)
    for index, row in enumerate(rows):
        row["session_index"] = index
    bars[71]["low"] = bars[70]["low"]
    rows[71]["low"] = rows[70]["low"]
    pivots = E._pivots(rows, 17, 3, 3, "support")
    assert [p["row_index"] for p in pivots] == [30, 50, 70]
    assert pivots[-1]["confirmation_row_index"] == 73
    assert pivots[-1]["confirmed_at"] == rows[73]["available_at"]
    prefix = E._pivots(rows[:73], 17, 3, 3, "support")
    assert 70 not in [p["row_index"] for p in prefix]
    assert 0 not in [p["row_index"] for p in E._pivots(rows, 0, 3, 3, "support")]


def test_asof_prefix_replay_ignores_future_capture_and_new_revision() -> None:
    asset, bars, _cutoff, config, policy = fixture_inputs(100)
    cutoff = (C.aware_time(bars[79]["available_at"]) + timedelta(minutes=10)).isoformat()
    prefix = E.build_asset_snapshot(asset, bars[:80], cutoff, config=config, source_policy=policy)
    revised = deepcopy(bars[30])
    revised.update({"bar_id": "fixture-future-revision", "revision_seq": 2, "supersedes_bar_id": bars[30]["bar_id"],
                    "available_at": bars[-1]["available_at"], "fetched_at": bars[-1]["available_at"], "close": bars[30]["close"] + 0.5})
    future = E.build_asset_snapshot(asset, bars + [revised], cutoff, config=config, source_policy=policy)
    assert prefix == future


def test_native_available_timestamp_cannot_backdate_a_future_first_capture() -> None:
    asset, bars, cutoff, config, policy = fixture_inputs()
    for row in bars:
        row["fetched_at"] = "2024-04-20T00:00:00+00:00"
    with pytest.raises(C.TrendlinesError, match="future bar"):
        C.validate_bar(bars[0], asset, cutoff, policy)
    snapshot = E.build_asset_snapshot(asset, bars, cutoff, config=config, source_policy=policy)
    assert snapshot["status"] == "hold" and not snapshot["bars"]
    assert snapshot["reason_codes"] == ["missing_approved_ohlc"]
    eligible = fixture_inputs()
    issued = build(eligible)
    replay = E.verify_asset_snapshot(issued, bars, asset, config=config, source_policy=policy)
    assert not replay["ok"]


def test_two_close_break_and_reclaim_preserve_formed_line() -> None:
    asset, bars, cutoff, config, policy = fixture_inputs(break_and_reclaim=True)
    snapshot = E.build_asset_snapshot(asset, bars, cutoff, config=config, source_policy=policy)
    lines = [line for line in snapshot["analyses"]["linear"]["63"]["lines"] if line["side"] == "support" and line["state"] == "reclaimed"]
    assert lines
    events = [event for event in snapshot["events"] if event["line_id"] == lines[0]["line_id"]]
    assert [(event["effective_session"], event["new_state"]) for event in events] == [
        (bars[94]["session_date"], "break_pending"), (bars[95]["session_date"], "broken"),
        (bars[96]["session_date"], "reclaim_pending"), (bars[97]["session_date"], "reclaimed")]
    assert E.verify_asset_snapshot(snapshot, bars, asset, config=config, source_policy=policy)["ok"]


def test_late_bootstrap_never_issues_historical_breaks() -> None:
    asset, bars, cutoff, config, policy = fixture_inputs(break_and_reclaim=True)
    for row in bars:
        row["available_at"] = row["fetched_at"] = cutoff
    snapshot = E.build_asset_snapshot(asset, bars, cutoff, config=config, source_policy=policy)
    assert not snapshot["events"]
    assert all(C.aware_time(line["activation_asof"]) == C.aware_time(cutoff)
               for line in snapshot["analyses"]["linear"]["63"]["lines"])


def test_published_time_before_first_capture_cannot_backdate_line_or_signal() -> None:
    asset, bars, cutoff, config, policy = fixture_inputs(break_and_reclaim=True)
    for row in bars:
        row["fetched_at"] = cutoff
    snapshot = E.build_asset_snapshot(asset, bars, cutoff, config=config, source_policy=policy)
    assert not snapshot["events"]
    assert all(C.aware_time(line["activation_asof"]) == C.aware_time(cutoff) for line in snapshot["audit_lines"])
    assert E.verify_asset_snapshot(snapshot, bars, asset, config=config, source_policy=policy)["ok"]


def test_missing_session_is_not_compressed_or_filled() -> None:
    asset, bars, cutoff, config, policy = fixture_inputs()
    snapshot = E.build_asset_snapshot(asset, bars[:85] + bars[86:], cutoff, config=config, source_policy=policy)
    assert snapshot["status"] == "hold"
    assert "missing_completed_sessions" in snapshot["reason_codes"]
    assert not snapshot["bars"]


@pytest.mark.parametrize("field,value,reason", [("low", 0, "finite positive"), ("high", float("nan"), "finite positive"),
                                              ("close", True, "finite positive"), ("close", 1e10, "containment"),
                                              ("unit", "USD", "identity mismatch"), ("price_basis", "total_return", "identity mismatch")])
def test_rejects_invalid_ohlc_without_normalization(field: str, value: object, reason: str) -> None:
    asset, bars, cutoff, _config, policy = fixture_inputs()
    row = deepcopy(bars[-1]); row[field] = value
    with pytest.raises(C.TrendlinesError, match=reason):
        C.validate_bar(row, asset, cutoff, policy)


def test_close_fallback_naive_time_and_forked_revision_are_rejected() -> None:
    asset, bars, cutoff, config, policy = fixture_inputs()
    malformed = deepcopy(bars[-1]); del malformed["low"]
    with pytest.raises(C.TrendlinesError, match="close fallback forbidden"):
        C.validate_bar(malformed, asset, cutoff, policy)
    with pytest.raises(C.TrendlinesError, match="timezone-aware"):
        E.build_asset_snapshot(asset, bars, "2024-04-10T00:30:00", config=config, source_policy=policy)
    revision = deepcopy(bars[-1]); revision.update({"bar_id": "fork", "revision_seq": 2, "supersedes_bar_id": "missing"})
    with pytest.raises(C.TrendlinesError, match="revision chain"):
        E.build_asset_snapshot(asset, bars + [revision], cutoff, config=config, source_policy=policy)


def test_paid_source_and_dividend_adjustment_cannot_be_approved_by_label() -> None:
    asset, _bars, _cutoff, _config, policy = fixture_inputs()
    source = policy["sources"]["fixture_ohlc"]
    source["rights_status"] = "paid"
    with pytest.raises(C.TrendlinesError, match="not_approved_free"):
        C.validate_source(asset, policy)
    source["rights_status"] = "approved_free"
    asset["price_basis"] = "split_adjusted_price"
    source["allowed_price_bases"] = ["split_adjusted_price"]
    source["adjustment_method"] = "total_return"
    with pytest.raises(C.TrendlinesError, match="split-only"):
        C.validate_source(asset, policy)
    source["adjustment_method"] = "split_only"
    with pytest.raises(C.TrendlinesError, match="vintage"):
        C.validate_source(asset, policy)
    source["adjustment_vintage_guarantee"] = True
    assert C.validate_source(asset, policy) is source


def test_publication_lag_and_dst_early_close_holidays() -> None:
    asset = deepcopy(C.load_asset_registry(ROOT)["nasdaq"])
    # NYSE's 2026 calendar: Nov 27 closes at 13:00 ET; Jul 3 is a full holiday.
    before = C.latest_completed_session(asset, "2026-11-27T18:14:59+00:00")
    after = C.latest_completed_session(asset, "2026-11-27T18:15:00+00:00")
    assert before == "2026-11-25" and after == "2026-11-27"
    assert C.latest_completed_session(asset, "2026-07-02T20:15:00+00:00") == "2026-07-02"
    assert C.latest_completed_session(asset, "2026-07-03T23:00:00+00:00") == "2026-07-02"
    asset["publication_lag_minutes"] = 60
    assert C.latest_completed_session(asset, "2026-11-27T19:14:59+00:00") == "2026-11-25"
    assert C.latest_completed_session(asset, "2026-11-27T19:15:00+00:00") == "2026-11-27"
    asset["publication_lag_minutes"] = 0
    assert C.latest_completed_session(asset, "2026-12-14T21:14:59+00:00") == "2026-12-11"
    with pytest.raises(C.TrendlinesError, match="nonnegative"):
        C.publication_lag({"publication_lag_minutes": -1})


def test_atr_is_true_range_sma_and_invalid_projection_is_not_clipped() -> None:
    rows = [{"high": 10.0, "low": 8.0, "close": 9.0}, {"high": 15.0, "low": 13.0, "close": 14.0},
            {"high": 14.0, "low": 10.0, "close": 12.0}]
    assert E._atr(rows, 2) == [None, None, 5.0]
    line = {"coordinate_origin_index": 0, "intercept": 2.0, "slope": -1.0, "axis": "linear"}
    assert E._value(line, 1) == 1 and E._value(line, 2) is None
    line.update({"axis": "log", "intercept": 1000.0, "slope": 1.0})
    assert E._value(line, 1) is None
    line["intercept"] = -1000.0
    assert E._value(line, 1) is None


@pytest.mark.parametrize("mutation", ["endpoint", "slope", "intercept", "state", "contacts", "border", "rank"])
def test_independent_replay_rejects_rehashed_derived_corruption(mutation: str) -> None:
    asset, bars, cutoff, config, policy = fixture_inputs()
    snapshot = E.build_asset_snapshot(asset, bars, cutoff, config=config, source_policy=policy)
    analysis = snapshot["analyses"]["linear"]["63"]
    line = analysis["lines"][0]
    if mutation == "endpoint": line["points"][-1]["price"] += 10
    elif mutation == "slope": line["slope"] += 1
    elif mutation == "intercept": line["intercept"] += 5
    elif mutation == "state": line["state"] = "broken"
    elif mutation == "contacts": line["touch_count"] += 1
    elif mutation == "rank": line["rank"] = 99
    else:
        side = next(key for key in ("down", "up", "broken") if analysis["borders"][key])
        analysis["borders"][side][0]["price"] += 10
    verified = E.verify_asset_snapshot(rehash(snapshot), bars, asset, config=config, source_policy=policy)
    assert not verified["ok"], mutation


def test_independent_replay_rejects_missing_unselected_candidate_and_its_events() -> None:
    asset, bars, cutoff, config, policy = fixture_inputs(280)
    snapshot = E.build_asset_snapshot(asset, bars, cutoff, config=config, source_policy=policy)
    shown = {line["line_id"] for windows in snapshot["analyses"].values() for analysis in windows.values() for line in analysis["lines"]}
    removed = next(line for line in snapshot["audit_lines"] if line["line_id"] not in shown)
    snapshot["audit_lines"] = [line for line in snapshot["audit_lines"] if line["line_id"] != removed["line_id"]]
    snapshot["events"] = [event for event in snapshot["events"] if event["line_id"] != removed["line_id"]]
    snapshot["analyses"][removed["axis"]][str(removed["window"])]["candidate_count"] -= 1
    verified = E.verify_asset_snapshot(rehash(snapshot), bars, asset, config=config, source_policy=policy)
    assert "candidate admission completeness replay mismatch" in verified["errors"]


def test_independent_replay_checks_event_close_and_issue_time() -> None:
    asset, bars, cutoff, config, policy = fixture_inputs(break_and_reclaim=True)
    snapshot = E.build_asset_snapshot(asset, bars, cutoff, config=config, source_policy=policy)
    event = snapshot["events"][0]
    event["close"] += 10
    event["issued_at"] = "2027-01-01T00:00:00+00:00"
    event["event_id"] = "trend-event-" + C.canonical_hash({key: value for key, value in event.items() if key != "event_id"})[:32]
    for windows in snapshot["analyses"].values():
        for analysis in windows.values():
            for row in analysis["events"]:
                if row["line_id"] == event["line_id"] and row["bar_id"] == event["bar_id"]:
                    row.update(event)
    verified = E.verify_asset_snapshot(rehash(snapshot), bars, asset, config=config, source_policy=policy)
    assert not verified["ok"]
    assert "event issuance time differs from eligible source" in verified["errors"]
    assert "event observation metadata mismatch" in verified["errors"]


@pytest.mark.parametrize("mutation", ["wrong_horizon", "wrong_session", "wrong_calendar_index", "missing_projection",
                                      "missing_point", "future_flag", "nonobject_projection", "nonobject_point", "bool_projection_price"])
def test_independent_replay_binds_extension_horizons_dates_and_complete_points(mutation: str) -> None:
    asset, bars, cutoff, config, policy = fixture_inputs()
    snapshot = E.build_asset_snapshot(asset, bars, cutoff, config=config, source_policy=policy)
    analysis = snapshot["analyses"]["linear"]["63"]
    line = analysis["lines"][0]
    if mutation == "wrong_horizon":
        # Both metadata copies agree and every price still obeys the equation;
        # the user-facing 999-day label remains outside the declared horizons.
        analysis["projection_sessions"][0]["offset"] = 999
        line["projections"][0]["offset"] = 999
    elif mutation == "wrong_session":
        line["projections"][0]["session"] = line["projections"][1]["session"]
    elif mutation == "wrong_calendar_index":
        line["projections"][0]["index"] += 1
        line["projections"][0]["price"] = E._value(line, line["projections"][0]["index"])
    elif mutation == "missing_projection":
        line["projections"].pop()
    elif mutation == "missing_point":
        line["points"].pop()
    elif mutation == "nonobject_projection":
        line["projections"][0] = "invalid projection object"
    elif mutation == "nonobject_point":
        line["points"][-1] = "invalid point object"
    elif mutation == "bool_projection_price":
        line["projections"][0]["price"] = True
    else:
        line["points"][-1]["future"] = False
    result = E.verify_asset_snapshot(rehash(snapshot), bars, asset, config=config, source_policy=policy)
    assert not result["ok"]
    assert any("horizon/calendar" in error for error in result["errors"])


def test_rank_tie_is_deterministic_and_window_warmup_minimum() -> None:
    line = {"touch_count": 3, "latest_touch_index": 20, "anchor_span": 10, "formation_penetration": 0,
            "distance_score": 1, "line_id": "b"}
    other = {**line, "line_id": "a"}
    assert sorted([line, other], key=E._rank) == [other, line]
    assert build(fixture_inputs(77))["status"] == "hold"
    assert build(fixture_inputs(78))["status"] == "ready"


def test_three_year_window_and_no_official_probability_output() -> None:
    inputs = fixture_inputs(780)
    snapshot = build(inputs)
    assert snapshot["analyses"]["linear"]["756"]["status"] == "ready"
    assert len(snapshot["bars"]) == 756
    assert snapshot["official_forecast_write"] is False and snapshot["probability_space"] == "reference_only"
    asset, bars, _cutoff, config, policy = inputs
    assert E.verify_asset_snapshot(snapshot, bars, asset, config=config, source_policy=policy)["ok"]


def test_existing_line_identity_anchor_activation_and_events_are_prefix_preserved() -> None:
    asset, bars, cutoff, config, policy = fixture_inputs(break_and_reclaim=True)
    earlier_cutoff = (C.aware_time(bars[95]["available_at"]) + timedelta(minutes=10)).isoformat()
    earlier = E.build_asset_snapshot(asset, bars[:96], earlier_cutoff, config=config, source_policy=policy)
    later = E.build_asset_snapshot(asset, bars, cutoff, config=config, source_policy=policy, previous_snapshot=earlier)
    old = {line["line_id"]: line for line in earlier["analyses"]["linear"]["63"]["lines"]}
    new = {line["line_id"]: line for line in later["analyses"]["linear"]["63"]["lines"]}
    common = set(old) & set(new)
    assert common
    for line_id in common:
        for field in ("first_anchor", "second_anchor", "slope", "intercept", "activation_asof", "activation_session", "formation_input_hash"):
            assert old[line_id][field] == new[line_id][field]
        old_events = [event for event in earlier["events"] if event["line_id"] == line_id]
        new_events = [event for event in later["events"] if event["line_id"] == line_id]
        assert new_events[:len(old_events)] == old_events
    assert later["selection_changes"]["new_line_ids"] == sorted({line["line_id"] for windows in later["analyses"].values()
                                                                 for analysis in windows.values() for line in analysis["lines"]} -
                                                                {line["line_id"] for windows in earlier["analyses"].values()
                                                                 for analysis in windows.values() for line in analysis["lines"]})
