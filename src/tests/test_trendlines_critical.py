"""Critical selection is additive and strict, including empty actual charts."""

from __future__ import annotations

import hashlib
import json
import shutil
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ai_fc.trendlines import contracts as C, critical as K, engine as E, full_history as F, research as R, storage as S

REPOSITORY = Path(__file__).resolve().parents[2]
FIRST = datetime(2022, 7, 1, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    for relative in (C.CONTRACT_RELATIVE, C.ASSET_REGISTRY_RELATIVE, C.SOURCE_POLICY_RELATIVE, K.POLICY_RELATIVE):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPOSITORY / relative, target)
    return tmp_path


def capture(root, count=120, extra=0.0):
    quotes = {key: [] for key in ("open", "high", "low", "close", "volume")}
    for i in range(count):
        low = 100 + i * .1 + abs(i % 100 - 50) * .6 + extra
        for key, value in zip(quotes, (low + 1, low + 4, low, low + 2, 100)):
            quotes[key].append(value)
    body = {"chart": {"result": [{"meta": {"symbol": "BTC-USD", "currency": "USD", "exchangeTimezoneName": "UTC",
            "dataGranularity": "1d", "instrumentType": "CRYPTOCURRENCY"},
            "timestamp": [int((FIRST + timedelta(days=i)).timestamp()) for i in range(count)],
            "indicators": {"quote": [quotes]}, "events": {}}], "error": None}}
    wrapper = {"status": 200, "statusText": "OK", "headers": {"content-type": "application/json"}, "body": json.dumps(body)}
    raw = ('<html><script type="application/json" data-sveltekit-fetched data-url="https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD?interval=1d">'
           + json.dumps(wrapper) + '</script></html>').encode()
    stamp = (FIRST + timedelta(days=count, hours=1)).isoformat()
    receipt = {"url": "https://finance.yahoo.com/quote/BTC-USD/history/", "retrieved_at": stamp,
               "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "http_status": 200}
    result = R.capture_html(root, "bitcoin", raw, receipt, as_of=stamp)
    F.refresh(root, "bitcoin", now=stamp)
    return result, stamp


def original_bytes(root):
    return {str(path.relative_to(root)): path.read_bytes() for parent in (R.ROOT, F.ROOT, S.ROOT)
            for path in (root / parent).rglob("*") if path.is_file()}


def input_rows(count=150, diagonal=False):
    rows = []
    for i in range(count):
        low = 112.0
        if i in (30, 70, 110):
            low = 100.0 + (i - 30) * .1 if diagonal else 100.0
        high = 125.0 if i in (40, 80, 120) else 121.0
        session = (FIRST + timedelta(days=i)).date().isoformat()
        rows.append({"session_date": session, "session_index": i, "open": 115.0, "high": high, "low": low, "close": 115.0,
                     "bar_id": "research-bar-" + hashlib.sha256(str(i).encode()).hexdigest(),
                     "available_at": "2023-01-01T00:00:00+00:00", "fetched_at": "2023-01-01T00:00:00+00:00",
                     "finalized_at": (FIRST + timedelta(days=i+1)).isoformat()})
    asset = {"asset_id": "bitcoin", "kind": "crypto", "calendar_id": "24/7", "tick_size": 0.0}
    parameters = {"bars": count, "left": 3, "right": 3, "min_anchor_gap": 10, "minimum_bars": 78}
    settings = C.default_config()
    atr = E._atr(rows, 14, segmented=True)
    future = K._future(rows, asset, K.POLICY)
    analysis, _, candidates = E._analyze(rows, asset, settings, "linear", parameters, future, C.canonical_hash(settings), research=True)
    return rows, asset, parameters, settings, atr, future, analysis, candidates


def test_horizontal_three_independent_contacts_selects_only_one_each_role():
    rows, asset, parameters, settings, atr, future, analysis, candidates = input_rows()
    assert candidates == []  # Equal-price pairs were absent from old diagonal transport.
    view, audit = K._view(analysis, candidates, rows, atr, asset, settings, parameters, K.POLICY, future, "linear")
    assert len(view["boundaries"]) == 2
    assert {item["role"] for item in view["boundaries"]} == {"support", "resistance"}
    assert all(item["kind"] == "horizontal_zone" and item["contact_count"] == 3 for item in view["boundaries"])
    assert {item["level"] for item in view["boundaries"]} == {100.0, 125.0}
    assert view["candidate_count"] == len(audit)
    assert all(not item["reasons"] for item in audit)


def test_all_candidates_considered_even_if_old_display_lines_empty():
    rows, asset, parameters, settings, atr, future, analysis, candidates = input_rows(diagonal=True)
    assert any(line["touch_count"] >= 3 for line in candidates)
    analysis["lines"] = []
    view, audit = K._view(analysis, candidates, rows, atr, asset, settings, parameters, K.POLICY, future, "linear")
    assert view["diagonal_candidate_count"] == len(candidates)
    assert {item["boundary_id"] for item in audit if item["kind"] == "diagonal"} == {item["line_id"] for item in candidates}
    assert view["shadow"]["baseline_line_ids"] == []
    assert len(view["boundaries"]) <= 2


def test_pivot_confirmation_windows_are_not_double_counted():
    contacts = [{"index": i, "bar_id": str(i), "confirmation_start_index": i-3, "confirmation_end_index": i+3} for i in (10, 14, 17, 24)]
    independent = K._independent(contacts)
    assert [item["index"] for item in independent] == [10, 17, 24]
    assert K._independent(list(reversed(contacts))) == independent
    assert [item["index"] for item in K._independent(contacts[:2])] == [14]


def test_two_contacts_never_filled_as_a_core_boundary():
    rows, asset, parameters, settings, atr, future, analysis, candidates = input_rows()
    analysis["pivots"] = [pivot for pivot in analysis["pivots"] if pivot["index"] not in (110, 120)]
    view, audit = K._view(analysis, candidates, rows, atr, asset, settings, parameters, K.POLICY, future, "linear")
    assert view["boundaries"] == [] and view["status"] == "no_verified_boundaries"
    assert len(audit) == 2
    assert all("fewer_than_three_independent_confirmed_contacts" in item["reasons"] for item in audit)


def test_distance_requires_both_atr_and_fraction_conditions():
    rows, asset, parameters, settings, atr, future, analysis, candidates = input_rows()
    rows[-1].update(open=135.0, high=140.0, low=130.0, close=135.0)
    view, audit = K._view(analysis, candidates, rows, atr, asset, settings, parameters, K.POLICY, future, "linear")
    support = next(item for item in audit if item["role"] == "support")
    assert "distance_exceeds_twenty_percent" in support["reasons"]
    assert all(item["boundary_id"] != support["boundary_id"] for item in view["boundaries"])
    atr[-1] = 1.0
    _, audit = K._view(analysis, candidates, rows, atr, asset, settings, parameters, K.POLICY, future, "linear")
    assert all("distance_exceeds_four_atr" in item["reasons"] for item in audit)


def test_obsolete_contact_and_wrong_side_never_auto_flip_role():
    rows, asset, parameters, settings, atr, future, analysis, candidates = input_rows(count=250)
    rows[-1].update(open=95.0, high=99.0, low=90.0, close=95.0)
    view, audit = K._view(analysis, candidates, rows, atr, asset, settings, parameters, K.POLICY, future, "linear")
    assert not view["boundaries"]
    support = next(item for item in audit if item["role"] == "support")
    assert "original_role_on_wrong_side_of_final_close" in support["reasons"]
    assert "contact_older_than_63_sessions" in support["reasons"]
    assert all(item["role"] == original["side"] for item in audit for original in analysis["pivots"] if item["role"] == original["side"])


def test_close_break_reclaim_and_missing_session_reset_streak():
    rows, asset, _, settings, atr, _, _, _ = input_rows()
    boundary = {"kind": "horizontal_zone", "level": 100.0, "role": "support"}
    rows[-4]["close"] = rows[-3]["close"] = 80.0
    rows[-2]["close"] = rows[-1]["close"] = 115.0
    state = K._states(boundary, rows, atr, asset, settings, 144)
    assert state["state"] == "reclaimed"
    assert state["break_sessions"] == [rows[-3]["session_date"]]
    assert state["reclaim_sessions"] == [rows[-1]["session_date"]]
    rows[-3]["session_index"] += 1
    rows[-2]["session_index"] += 1
    rows[-1]["session_index"] += 1
    state = K._states(boundary, rows, atr, asset, settings, 144)
    assert state["break_sessions"] == []


def test_atr_unavailable_resets_two_close_confirmation():
    rows, asset, _, settings, atr, _, _, _ = input_rows()
    boundary = {"kind": "horizontal_zone", "level": 100.0, "role": "support"}
    rows[-3]["close"] = rows[-2]["close"] = rows[-1]["close"] = 80.0
    atr[-2] = None
    assert K._states(boundary, rows, atr, asset, settings, 145)["break_sessions"] == []


def test_diagonal_geometry_is_preserved_and_independent_scalar_agrees():
    rows, asset, parameters, settings, atr, future, analysis, candidates = input_rows(diagonal=True)
    view, _ = K._view(analysis, candidates, rows, atr, asset, settings, parameters, K.POLICY, future, "linear")
    originals = {line["line_id"]: line for line in candidates}
    for line in view["boundaries"]:
        if line["kind"] == "diagonal":
            original = originals[line["line_id"]]
            for field in ("slope", "intercept", "coordinate_origin_index", "first_anchor", "second_anchor"):
                assert line[field] == original[field]
            for point in line["projections"]:
                assert K._price(line, point["index"]) == pytest.approx(K._scalar_price(line, point["index"]), rel=1e-10, abs=1e-6)
    result = K._scalar_verify(rows, asset, settings, {"linear": {"test": view}}, atr, future)
    assert result["status"] == "passed" and result["checked_boundaries"] == len(view["boundaries"])


def test_selection_and_audit_are_order_reproducible():
    rows, asset, parameters, settings, atr, future, analysis, candidates = input_rows(diagonal=True)
    first, _ = K._view(analysis, candidates, rows, atr, asset, settings, parameters, K.POLICY, future, "linear")
    second, _ = K._view(analysis, list(reversed(candidates)), rows, atr, asset, settings, parameters, K.POLICY, future, "linear")
    assert first == second
    prices = [item["current_price"] for item in first["boundaries"]]
    if len(prices) > 1:
        assert abs(prices[0] - prices[1]) > .5 * atr[-1]


def test_independent_oracle_rejects_omitted_candidates_and_rank_changes():
    rows, asset, parameters, settings, atr, future, analysis, candidates = input_rows(diagonal=True)
    view, audit = K._view(analysis, candidates, rows, atr, asset, settings, parameters, K.POLICY, future, "linear")
    source = {"asset": asset, "config": settings, "engine_snapshot": {"audit_lines": candidates, "analyses": {"linear": {"63": analysis}}}}
    views, audits = {"linear": {"63": view}}, {"linear": {"63": audit}}
    assert K._scalar_selection_verify(source, {}, views, audits, rows, atr, K.POLICY)["complete_candidate_pools"]
    changed = deepcopy(audits)
    removed = next(item for item in changed["linear"]["63"] if item["kind"] == "diagonal")
    changed["linear"]["63"].remove(removed)
    with pytest.raises(ValueError, match="diagonal_candidate_pool_incomplete"):
        K._scalar_selection_verify(source, {}, views, changed, rows, atr, K.POLICY)
    changed = deepcopy(views)
    changed["linear"]["63"]["boundaries"] = list(reversed(view["boundaries"]))
    if len(view["boundaries"]) == 2:
        with pytest.raises(ValueError, match="selection_rank_differs"):
            K._scalar_selection_verify(source, {}, changed, audits, rows, atr, K.POLICY)


def test_independent_state_oracle_does_not_use_producer_state_machine(monkeypatch):
    rows, asset, parameters, settings, atr, future, analysis, candidates = input_rows(diagonal=True)
    view, _ = K._view(analysis, candidates, rows, atr, asset, settings, parameters, K.POLICY, future, "linear")
    monkeypatch.setattr(K, "_states", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("producer called")))
    assert K._scalar_verify(rows, asset, settings, {"linear": {"63": view}}, atr, future)["status"] == "passed"


def test_future_calendar_has_every_offset_and_no_future_ohlc():
    rows, asset, *_ = input_rows()
    future = K._future(rows, asset, K.POLICY)
    assert len(future) == 30
    assert [item["offset"] for item in future] == list(range(1, 31))
    assert all(set(item) == {"offset", "index", "session"} for item in future)
    asset.update(kind="equity", calendar_id="XKRX")
    schedule = C.session_schedule("XKRX", "2026-01-02", "2026-10-14")
    exchange_rows = [{"session_date": day, "session_index": i} for i, (day, _, _) in enumerate(schedule)]
    future = K._future(exchange_rows, asset, K.POLICY)
    assert len(future) == 21 and all(date.weekday() < 5 for date in [datetime.fromisoformat(p["session"]) for p in future])


def test_refresh_preserves_originals_is_idempotent_and_transport_binds_source(store):
    source, stamp = capture(store)
    before = original_bytes(store)
    with R.use_verified_replay_cache(R.VerifiedReplayCache()):
        result = K.refresh(store, "bitcoin", now=stamp)
        second = K.refresh(store, "bitcoin", now=stamp)
        assert K.verify(store, now=stamp)["ok"]
    assert result["changed"] and not second["changed"]
    assert result["critical_snapshot_id"] == second["critical_snapshot_id"]
    assert original_bytes(store) == before
    envelope = K.load_detail(store, "bitcoin", now=stamp)
    body = K.decode_envelope(envelope)
    assert body["source_snapshot_id"] == source["snapshot_id"]
    assert body["full_manifest_payload_sha256"] == F.load_manifest(store, "bitcoin", now=stamp)["payload_sha256"]
    assert body["official_forecast_write"] is body["verified_source"] is body["historical_signals_available"] is False
    assert set(body["analyses"]) == {"linear", "log"}
    assert all(set(windows) == {"63", "252", "756", "full"} for windows in body["analyses"].values())
    assert len(envelope["payload_json"].encode()) <= 256 * 1024
    assert not list((store / S.ROOT).rglob("*.jsonl"))


def test_full_candidate_pool_replay_has_independent_horizontal_and_rank_oracles(store):
    _, stamp = capture(store, count=850)
    result = K.refresh(store, "bitcoin", now=stamp)
    assert result["validation"]["complete_candidate_pools"]
    assert result["validation"]["checked_diagonal_candidates"] > 0
    assert result["validation"]["independent_rank_and_overlap_check"]
    assert K.verify(store, now=stamp)["ok"]


@pytest.mark.parametrize("target", ["raw", "source", "full", "critical", "export", "pointer"])
def test_corruption_fails_closed_without_replacing_previous_pointer(store, target):
    _, stamp = capture(store)
    result = K.refresh(store, "bitcoin", now=stamp)
    pointer = store / K.ROOT / "latest.json"
    previous = pointer.read_bytes()
    if target == "raw": path = next((store / R.ROOT / "raw").glob("*"))
    elif target == "source": path = next((store / R.ROOT / "snapshots").glob("*"))
    elif target == "full": path = next((store / F.ROOT / "snapshots").glob("*"))
    elif target == "critical": path = next((store / K.ROOT / "snapshots").glob("*"))
    elif target == "export": path = store / result["detail_path"]
    else: path = pointer
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        K.load_detail(store, "bitcoin", now=stamp)
    assert not K.verify(store, now=stamp)["ok"]
    with pytest.raises(ValueError):
        K.refresh(store, "bitcoin", now=stamp)
    if target != "pointer":
        assert pointer.read_bytes() == previous


def test_changed_source_requires_new_selection_and_keeps_old_snapshots(store):
    _, stamp = capture(store)
    first = K.refresh(store, "bitcoin", now=stamp)
    capture(store, count=121, extra=.5)
    with pytest.raises(ValueError, match="not_current_source"):
        K.load_detail(store, "bitcoin")
    second = K.refresh(store, "bitcoin")
    assert second["critical_snapshot_id"] != first["critical_snapshot_id"]
    assert len(list((store / K.ROOT / "snapshots").glob("*.json"))) == 2
    assert K.verify(store)["ok"]


def test_no_future_capture_read_and_no_mag7_substitute(store):
    _, stamp = capture(store)
    K.refresh(store, "bitcoin", now=stamp)
    with pytest.raises(ValueError, match="cutoff"):
        K.load_detail(store, "bitcoin", now=FIRST.isoformat())
    with pytest.raises(ValueError, match="no_research_source"):
        K.load_detail(store, "mag7")


def test_locked_versioned_policy_rejects_silent_parameter_change(store):
    path = store / K.POLICY_RELATIVE
    path.write_text(path.read_text().replace("minimum_independent_contacts: 3", "minimum_independent_contacts: 2"))
    with pytest.raises(ValueError, match="versioned_contract"):
        K.load_policy(store)


@pytest.mark.parametrize("attack", ["payload", "source_class", "historical", "duplicate", "nan"])
def test_transport_tampering_rejected(store, attack):
    _, stamp = capture(store)
    K.refresh(store, "bitcoin", now=stamp)
    envelope = K.load_detail(store, "bitcoin", now=stamp)
    body = json.loads(envelope["payload_json"])
    if attack == "payload": envelope["payload_json"] += " "
    else:
        if attack == "source_class": body["verified_source"] = True
        elif attack == "historical": body["historical_signals_available"] = True
        elif attack == "nan": body["atr14"] = float("nan")
        text = json.dumps(body, separators=(",", ":"))
        if attack == "duplicate": text = text[:-1] + ',"schema_version":1}'
        envelope["payload_json"] = text
        envelope["payload_sha256"] = hashlib.sha256(text.encode()).hexdigest()
    with pytest.raises(ValueError):
        K.decode_envelope(envelope)


def test_replay_detects_scalar_equation_change(store, monkeypatch):
    _, stamp = capture(store)
    K.refresh(store, "bitcoin", now=stamp)
    original = K._calculate
    def changed(*args):
        result = original(*args)
        result["reference_close"] += 1
        return result
    monkeypatch.setattr(K, "_calculate", changed)
    assert not K.verify(store, now=stamp)["ok"]


def test_writer_collision_keeps_existing_pointer(store):
    _, stamp = capture(store)
    K.refresh(store, "bitcoin", now=stamp)
    pointer = store / K.ROOT / "latest.json"
    before = pointer.read_bytes()
    with S.writer_lock(store):
        with pytest.raises(ValueError, match="publisher"):
            K.refresh(store, "bitcoin", now=stamp)
    assert pointer.read_bytes() == before


def test_failed_export_leaves_no_incomplete_snapshot_or_pointer(store, monkeypatch):
    _, stamp = capture(store)
    atomic = S.atomic_json
    def fail_export(path, value, **kwargs):
        if path.name == "detail.json":
            raise OSError("fixture_export_failure")
        return atomic(path, value, **kwargs)
    monkeypatch.setattr(S, "atomic_json", fail_export)
    with pytest.raises(OSError, match="fixture_export_failure"):
        K.refresh(store, "bitcoin", now=stamp)
    assert not (store / K.ROOT / "latest.json").exists()
    assert not list((store / K.ROOT / "snapshots").glob("*.json"))
    assert K.verify(store, now=stamp)["ok"]
