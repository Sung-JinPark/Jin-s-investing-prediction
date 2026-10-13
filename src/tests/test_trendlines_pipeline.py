"""Disposable captured OHLC, append integrity, and publication replay checks."""

from __future__ import annotations

import hashlib
import json
import math
import runpy
import shutil
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml

from ai_fc.trendlines import contracts as C, display as D, pipeline as P, storage as S

REPOSITORY = Path(__file__).resolve().parents[2]
ISSUED = "2026-09-13T01:00:00+00:00"


@pytest.fixture
def store(tmp_path):
    for relative in (C.CONTRACT_RELATIVE, C.ASSET_REGISTRY_RELATIVE, C.SOURCE_POLICY_RELATIVE):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPOSITORY / relative, target)
    return tmp_path


def _enable(root: Path):
    path = root / C.ASSET_REGISTRY_RELATIVE
    registry = yaml.safe_load(path.read_text(encoding="utf-8"))
    asset = registry["assets"]["bitcoin"]
    asset.update({"enabled": True, "source_id": "fixture_exchange"})
    path.write_text(yaml.safe_dump(registry, allow_unicode=True, sort_keys=False), encoding="utf-8")
    policy = {"schema_version": 1, "default_action": "deny", "sources": {"fixture_exchange": {
        "rights_status": "approved_free", "allow_collection": True, "allow_derived_display": True,
        "allow_ohlc": True, "allowed_domains": ["fixture.example"], "allowed_price_bases": [asset["price_basis"]],
        "asset_ids": ["bitcoin"], "calendar_ids": [asset["calendar_id"]], "parser_id": "json_ohlc_v1",
        "adjustment_method": "none", "publication_lag_minutes": 0}}}
    (root / C.SOURCE_POLICY_RELATIVE).write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")
    return asset


def _records():
    rows = []
    start = date(2026, 6, 15)
    for index in range(90):
        day = start + timedelta(days=index)
        value = 100 + index * 0.15 + 3 * math.sin(index * math.pi / 7)
        rows.append({"session_date": day.isoformat(), "open": value - 0.2, "high": value + 1,
                     "low": value - 1, "close": value,
                     "finalized_at": (day + timedelta(days=1)).isoformat() + "T00:15:00+00:00"})
    return rows


def _bundle(root: Path, asset: dict, *, records=None, fetched=ISSUED, directory="capture"):
    destination = root / directory
    destination.mkdir(parents=True, exist_ok=True)
    rows = _records() if records is None else records
    payload = {key: asset[key] for key in ("asset_id", "identity", "symbol", "source_id", "currency", "unit", "price_basis", "calendar_id")}
    payload["bars"] = rows
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=True).encode("utf-8")
    raw_path = destination / "raw.json"
    raw_path.write_bytes(raw)
    receipt = {"source_id": asset["source_id"], "asset_id": asset["asset_id"],
               "source_uri": "https://fixture.example/ohlc", "http_status": 200,
               "media_type": "application/json", "parser_id": "json_ohlc_v1",
               "raw_sha256": hashlib.sha256(raw).hexdigest(), "byte_count": len(raw),
               "fetched_at": fetched, "available_at": fetched}
    body = {"schema_version": 1, "contract_id": P.CAPTURE_ID, "captured_at": fetched,
            "assets": [{"asset_id": asset["asset_id"], "receipt": receipt, "raw_path": "raw.json", "bars": rows}],
            "failures": []}
    S.atomic_json(destination / "manifest.json", {**body, "content_hash": S.digest(body)})
    return destination


def _canonical_bytes(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in (root / S.ROOT).rglob("*") if path.is_file()}


def test_seven_holds_initialize_and_clock_only_rerun_is_byte_stable(store):
    first = P.refresh(store, as_of=ISSUED)
    assert first["changed"] is True and first["publication_allowed"] is True
    assert first["status"] == "hold" and len(first["assets"]) == 7
    assert {row["status"] for row in first["assets"]} == {"hold"}
    assert len(S.read_chain(store, "snapshots")) == 7
    assert S.read_chain(store, "bars") == []
    before = _canonical_bytes(store)
    second = P.refresh(store, as_of="2026-09-14T01:00:00+00:00")
    assert second["changed"] is False and second["publication_allowed"] is True
    assert _canonical_bytes(store) == before
    assert P.verify(store, replay=True)["ok"] is True
    projection = D.load_projection(store, now=ISSUED)
    assert len(projection["details"]) == 7
    assert all(not detail["bars"] for detail in projection["details"].values())


def test_empty_capture_is_portable_and_does_not_fabricate_prices(store):
    manifest = P.capture(store, out=store / "portable", as_of=ISSUED)
    assert manifest["assets"] == [] and manifest["failures"] == []
    result = P.refresh(store, as_of=ISSUED, capture_bundle=store / "portable")
    assert result["publication_allowed"] is True and result["status"] == "hold"
    assert S.read_chain(store, "raw_receipts") == []


def test_real_fixture_computes_partial_publication_and_replays(store):
    asset = _enable(store)
    result = P.refresh(store, as_of=ISSUED, capture_bundle=_bundle(store, asset))
    assert result["publication_allowed"] is True and result["status"] == "partial"
    assert len(S.read_chain(store, "bars")) == 90
    assert len(S.read_chain(store, "raw_receipts")) == 1
    assert P.verify(store, replay=True)["ok"] is True
    detail = D.load_asset_detail(store, "bitcoin", now=ISSUED)
    assert detail["status"] == "ready" and detail["bars"]
    assert len(S.encode(detail)) <= 256 * 1024


def test_identical_raw_refetch_reuses_original_vintage_and_is_noop(store):
    asset = _enable(store)
    P.refresh(store, as_of=ISSUED, capture_bundle=_bundle(store, asset))
    before = _canonical_bytes(store)
    second = P.refresh(store, as_of="2026-09-13T02:00:00+00:00", capture_bundle=_bundle(
        store, asset, fetched="2026-09-13T02:00:00+00:00", directory="capture2"))
    assert second["changed"] is False
    assert _canonical_bytes(store) == before
    assert len(S.read_chain(store, "bars")) == 90
    assert S.read_chain(store, "raw_receipts")[0]["payload"]["fetched_at"] == ISSUED


def test_correction_appends_explicit_revision_and_preserves_old_archive(store):
    asset = _enable(store)
    P.refresh(store, as_of=ISSUED, capture_bundle=_bundle(store, asset))
    old_pointer = P.latest(store)
    old_archives = {path: body for path, body in _canonical_bytes(store).items() if "/archive/" in path.replace("\\", "/")}
    rows = _records()
    rows[-4]["close"] += 0.5
    result = P.refresh(store, as_of="2026-09-13T02:00:00+00:00", capture_bundle=_bundle(
        store, asset, records=rows, fetched="2026-09-13T02:00:00+00:00", directory="corrected"))
    assert result["changed"] is True and result["publication_allowed"] is True
    stored = [row["payload"] for row in S.read_chain(store, "bars")]
    assert len(stored) == 91
    correction = stored[-1]
    original = next(row for row in stored[:-1] if row["session_date"] == correction["session_date"])
    assert correction["revision_seq"] == 2 and correction["supersedes_bar_id"] == original["bar_id"]
    for path, body in old_archives.items():
        assert (store / path).read_bytes() == body
    assert P.latest(store)["content_hash"] != old_pointer["content_hash"]
    assert P.verify(store, replay=True)["ok"] is True
    detail = D.load_asset_detail(store, "bitcoin", now="2026-09-13T02:00:00+00:00")
    assert detail["status"] == "ready"
    assert next(row for row in detail["bars"] if row["session"] == correction["session_date"])["close"] == correction["close"]
    prior_bars = S.select_bars(stored, asset, ISSUED)
    assert next(row for row in prior_bars if row["session_date"] == correction["session_date"])["bar_id"] == original["bar_id"]


@pytest.mark.parametrize("attack", ["raw", "declared", "close_only", "nan", "containment", "source", "backdated"])
def test_bad_capture_isolated_and_never_enters_bar_ledger(store, attack):
    asset = _enable(store)
    rows = _records()
    if attack == "close_only":
        del rows[0]["low"]
    elif attack == "nan":
        rows[0]["high"] = float("nan")
    elif attack == "containment":
        rows[0]["high"] = rows[0]["close"] - 2
    if attack == "nan":
        with pytest.raises(ValueError):
            _bundle(store, asset, records=rows)
        assert S.read_chain(store, "bars") == []
        return
    bundle = _bundle(store, asset, records=rows)
    manifest = S.read_json(bundle / "manifest.json")
    if attack == "raw":
        (bundle / "raw.json").write_bytes(b"changed raw")
    elif attack == "declared":
        manifest["assets"][0]["bars"][0]["close"] += 0.1
    elif attack == "source":
        manifest["assets"][0]["receipt"]["source_uri"] = "https://unapproved.example/ohlc?api_key=hidden"
    elif attack == "backdated":
        manifest["assets"][0]["receipt"]["available_at"] = "2026-06-15T01:00:00+00:00"
    # A manifest can have a valid transport hash and still fail the source/raw gate.
    manifest["content_hash"] = P._body_hash(manifest)
    if attack != "nan":
        S.atomic_json(bundle / "manifest.json", manifest)
    else:
        # JSON nonfinite values are rejected at the earliest encoding boundary.
        with pytest.raises(ValueError):
            P._body_hash(manifest)
        return
    result = P.refresh(store, as_of=ISSUED, capture_bundle=bundle)
    assert S.read_chain(store, "bars") == []
    assert S.read_chain(store, "raw_receipts") == []
    assert result["status"] == "hold" and result["capture_failures"]
    assert P.verify(store, replay=True)["ok"] is True


def test_bad_manifest_hash_blocks_without_changing_valid_publication(store):
    P.refresh(store, as_of=ISSUED)
    before = _canonical_bytes(store)
    manifest = P.capture(store, out=store / "capture", as_of=ISSUED)
    path = Path(manifest["manifest_path"])
    changed = S.read_json(path)
    changed["captured_at"] = "2026-09-14T01:00:00+00:00"
    S.atomic_json(path, changed)
    result = P.refresh(store, as_of=ISSUED, capture_bundle=path)
    assert result["publication_allowed"] is False and result["changed"] is False
    assert _canonical_bytes(store) == before


@pytest.mark.parametrize("attack", ["raw", "archive", "ledger", "truncate", "pointer"])
def test_stored_tamper_replay_fails_closed(store, attack):
    asset = _enable(store)
    P.refresh(store, as_of=ISSUED, capture_bundle=_bundle(store, asset))
    if attack == "raw":
        next((store / S.ROOT / "raw").glob("*.json")).write_bytes(b"invalid")
    elif attack == "archive":
        next((store / S.ROOT / "archive" / "bitcoin").glob("*.json")).write_bytes(b"{}")
    elif attack == "ledger":
        path = store / S.ROOT / "ledgers/bars.jsonl"
        path.write_bytes(path.read_bytes().replace(b'"close":', b'"close":0,"old_close":', 1))
    elif attack == "truncate":
        path = store / S.ROOT / "ledgers/snapshots.jsonl"
        path.write_bytes(b"")
    else:
        pointer = P.latest(store)
        pointer["assets"][0]["status"] = "ready"
        pointer["content_hash"] = P._body_hash(pointer)
        S.atomic_json(store / P.LATEST, pointer)
    assert P.verify(store, replay=True)["ok"] is False
    result = P.refresh(store, as_of=ISSUED)
    assert result["publication_allowed"] is False and result["changed"] is False
    detail = D.load_asset_detail(store, "bitcoin", now=ISSUED)
    assert detail["status"] == "hold" and detail["bars"] == []


def test_permission_revocation_hides_prices_and_can_publish_new_hold(store):
    asset = _enable(store)
    P.refresh(store, as_of=ISSUED, capture_bundle=_bundle(store, asset))
    policy = C.load_source_policy(store)
    policy["sources"]["fixture_exchange"]["allow_derived_display"] = False
    (store / C.SOURCE_POLICY_RELATIVE).write_text(yaml.safe_dump(policy), encoding="utf-8")
    assert D.load_asset_detail(store, "bitcoin", now=ISSUED)["status"] == "hold"
    result = P.refresh(store, as_of=ISSUED)
    assert result["publication_allowed"] is True and result["status"] == "hold"
    assert len(S.read_chain(store, "bars")) == 90
    assert P.verify(store, replay=True)["ok"] is True


def test_old_approved_snapshot_is_explicitly_stale_on_later_session(store):
    asset = _enable(store)
    P.refresh(store, as_of=ISSUED, capture_bundle=_bundle(store, asset))
    detail = D.load_asset_detail(store, "bitcoin", now="2026-09-14T01:00:00+00:00")
    assert detail["status"] == "stale" and detail["bars"]
    assert detail["observation_through"] == "2026-09-12"
    assert "latest_completed_session_missing" in detail["reason_codes"]


def test_path_escape_and_unknown_asset_are_rejected(store):
    with pytest.raises(S.TrendlinesStorageError, match="escapes"):
        S.safe_path(store, "../unrelated.json")
    with pytest.raises(C.TrendlinesError, match="unregistered"):
        D.load_asset_detail(store, "synthetic-mag7")


def test_two_publishers_cannot_hold_same_os_lock(store):
    with S.writer_lock(store):
        with pytest.raises(S.TrendlinesStorageError, match="another"):
            with S.writer_lock(store):
                pass


def test_wrong_instrument_identity_cannot_be_relabelled_as_a_registered_asset(store):
    asset = _enable(store)
    bundle = _bundle(store, asset)
    manifest = S.read_json(bundle / "manifest.json")
    raw = json.loads((bundle / "raw.json").read_bytes())
    raw["identity"] = "MAGS_ETF_IS_NOT_THE_SOLACTIVE_MAG7_PR_INDEX"
    body = json.dumps(raw, sort_keys=True).encode()
    (bundle / "raw.json").write_bytes(body)
    manifest["assets"][0]["receipt"].update({"raw_sha256": hashlib.sha256(body).hexdigest(), "byte_count": len(body)})
    manifest["content_hash"] = P._body_hash(manifest)
    S.atomic_json(bundle / "manifest.json", manifest)
    result = P.refresh(store, as_of=ISSUED, capture_bundle=bundle)
    assert "identity" in result["capture_failures"]["bitcoin"]
    assert S.read_chain(store, "bars") == []


@pytest.mark.parametrize("uri", ["https://fixture.example/ohlc?API_KEY=hidden",
                                  "https://fixture.example/ohlc?ToKeN=hidden",
                                  "https://user:secret@fixture.example/ohlc",
                                  "https://fixture.example.evil.test/ohlc"])
def test_secret_and_suffix_confusion_uris_are_rejected_before_raw_storage(store, uri):
    asset = _enable(store)
    bundle = _bundle(store, asset)
    manifest = S.read_json(bundle / "manifest.json")
    manifest["assets"][0]["receipt"]["source_uri"] = uri
    manifest["content_hash"] = P._body_hash(manifest)
    S.atomic_json(bundle / "manifest.json", manifest)
    result = P.refresh(store, as_of=ISSUED, capture_bundle=bundle)
    assert result["capture_failures"]
    assert not (store / S.ROOT / "raw").exists()


def test_approved_source_subdomain_is_accepted(store):
    asset = _enable(store)
    bundle = _bundle(store, asset)
    manifest = S.read_json(bundle / "manifest.json")
    manifest["assets"][0]["receipt"]["source_uri"] = "https://data.fixture.example/ohlc"
    manifest["content_hash"] = P._body_hash(manifest)
    S.atomic_json(bundle / "manifest.json", manifest)
    assert P.refresh(store, as_of=ISSUED, capture_bundle=bundle)["status"] == "partial"


def _inbox(root, asset, records):
    bundle = _bundle(root, asset, records=records, directory="data/trendlines/inbox/connector")
    manifest = S.read_json(bundle / "manifest.json")
    manifest["assets"][0]["raw_path"] = "connector/raw.json"
    manifest["content_hash"] = P._body_hash(manifest)
    S.atomic_json(bundle.parent / "connector.json", manifest)
    return bundle


def test_approved_invalid_raw_is_preserved_before_numeric_validation(store):
    asset = _enable(store)
    records = _records()
    records[-1]["high"] = records[-1]["close"] - 3
    original = _inbox(store, asset, records)
    before = (original / "raw.json").read_bytes()
    result = P.capture(store, out=store / "portable", as_of=ISSUED)
    assert result["assets"] == [] and len(result["failures"]) == 1
    failure = result["failures"][0]
    assert failure["raw_sha256"] == hashlib.sha256(before).hexdigest()
    assert (store / "portable" / failure["raw_path"]).read_bytes() == before
    assert (original / "raw.json").read_bytes() == before
    assert S.read_chain(store, "raw_receipts") == []
    assert "containment" in failure["reason"]


def test_unapproved_capture_does_not_preserve_raw_in_public_capture(store):
    asset = C.load_asset_registry(store)["bitcoin"]
    _inbox(store, asset, _records())
    result = P.capture(store, out=store / "portable", as_of=ISSUED)
    assert result["failures"] and "raw_path" not in result["failures"][0]
    assert not (store / "portable/raw").exists()


def test_bad_new_capture_preserves_last_good_as_stale_without_recomputing_prices(store):
    asset = _enable(store)
    P.refresh(store, as_of=ISSUED, capture_bundle=_bundle(store, asset))
    previous = D.load_asset_detail(store, "bitcoin", now=ISSUED)
    bad = _bundle(store, asset, fetched="2026-09-13T02:00:00+00:00", directory="bad_new")
    (bad / "raw.json").write_bytes(b"bad payload")
    result = P.refresh(store, as_of="2026-09-13T02:00:00+00:00", capture_bundle=bad)
    assert result["publication_allowed"] is True
    assert next(row for row in result["assets"] if row["asset_id"] == "bitcoin")["status"] == "stale"
    detail = D.load_asset_detail(store, "bitcoin", now="2026-09-13T02:00:00+00:00")
    assert detail["status"] == "stale" and detail["bars"] == previous["bars"]
    assert P.verify(store, replay=True)["ok"] is True
    policy = C.load_source_policy(store)
    policy["sources"]["fixture_exchange"]["allow_derived_display"] = False
    (store / C.SOURCE_POLICY_RELATIVE).write_text(yaml.safe_dump(policy), encoding="utf-8")
    hidden = D.load_asset_detail(store, "bitcoin", now=ISSUED)
    assert hidden["status"] == "hold" and hidden["bars"] == []


def test_failed_candidate_replay_leaves_canonical_store_untouched(store, monkeypatch):
    asset = _enable(store)
    before = _canonical_bytes(store)
    monkeypatch.setattr(P.E, "verify_asset_snapshot", lambda *args, **kwargs: {"ok": False, "errors": ["injected replay mismatch"]})
    with pytest.raises(S.TrendlinesStorageError, match="candidate replay failed"):
        P.refresh(store, as_of=ISSUED, capture_bundle=_bundle(store, asset))
    assert _canonical_bytes(store) == before
    assert not (store / P.LATEST).exists()


@pytest.mark.parametrize("crash_boundary", ["archive", "latest"])
def test_crash_recovers_intact_append_history_without_overwriting_orphan_archive(store, monkeypatch, crash_boundary):
    asset = _enable(store)
    bundle = _bundle(store, asset)
    atomic = S.atomic_json
    crashed = False

    def interrupt(path, value, **kwargs):
        nonlocal crashed
        atomic(path, value, **kwargs)
        boundary = "/archive/" in path.as_posix() if crash_boundary == "archive" else path == store / P.LATEST
        if boundary and not crashed:
            crashed = True
            raise OSError("injected process failure after atomic artifact write")

    monkeypatch.setattr(S, "atomic_json", interrupt)
    with pytest.raises(OSError, match="injected"):
        P.refresh(store, as_of=ISSUED, capture_bundle=bundle)
    preserved = {path: body for path, body in _canonical_bytes(store).items() if "/archive/" in path.replace("\\", "/")}
    monkeypatch.setattr(S, "atomic_json", atomic)
    resumed = P.refresh(store, as_of="2026-09-13T02:00:00+00:00", capture_bundle=bundle)
    assert resumed["publication_allowed"] is True
    for path, body in preserved.items():
        assert (store / path).read_bytes() == body
    assert len(S.read_chain(store, "bars")) == 90
    assert len(S.read_chain(store, "snapshots")) == 7
    assert P.verify(store, replay=True)["ok"] is True


def test_reenabling_same_valid_result_is_new_snapshot_revision_not_pointer_rollback(store):
    asset = _enable(store)
    P.refresh(store, as_of=ISSUED, capture_bundle=_bundle(store, asset))
    original = next(row for row in P.latest(store)["assets"] if row["asset_id"] == "bitcoin")["snapshot_id"]
    policy_path = store / C.SOURCE_POLICY_RELATIVE
    policy = C.load_source_policy(store)
    policy["sources"]["fixture_exchange"]["allow_derived_display"] = False
    policy_path.write_text(yaml.safe_dump(policy), encoding="utf-8")
    P.refresh(store, as_of=ISSUED)
    withheld = next(row for row in P.latest(store)["assets"] if row["asset_id"] == "bitcoin")["snapshot_id"]
    policy["sources"]["fixture_exchange"]["allow_derived_display"] = True
    policy_path.write_text(yaml.safe_dump(policy), encoding="utf-8")
    P.refresh(store, as_of=ISSUED)
    resumed = next(row for row in P.latest(store)["assets"] if row["asset_id"] == "bitcoin")
    assert resumed["status"] == "ready" and resumed["snapshot_id"] != original
    envelope = P._archive(store, resumed)
    assert envelope["supersedes_snapshot_id"] == withheld
    assert P.verify(store, replay=True)["ok"] is True


def test_public_projection_preserves_all_plot_and_contact_values_without_mutating_archive():
    inputs = runpy.run_path(str(REPOSITORY / "src/tests/test_trendlines_engine.py"))["fixture_inputs"](100)
    asset, bars, cutoff, config, policy = inputs
    snapshot = P.E.build_asset_snapshot(asset, bars, cutoff, config=config, source_policy=policy)
    original = deepcopy(snapshot)
    detail = D.compact_snapshot(snapshot)
    assert snapshot == original and D.compact_snapshot(detail) == detail
    assert detail["source_snapshot_hash"] == snapshot["content_hash"]
    assert detail["input_hash"] == snapshot["input_hash"]
    assert detail["content_hash"] == C.canonical_hash({key: value for key, value in detail.items() if key != "content_hash"})
    assert detail["input_bar_count"] == len(snapshot["input_bar_ids"])
    assert detail["visible_bar_count"] == len(snapshot["bars"])
    assert "audit_lines" not in detail and detail["events"] == []
    for axis, windows in snapshot["analyses"].items():
        for period, analysis in windows.items():
            projected = detail["analyses"][axis][period]
            assert projected["borders"] == analysis["borders"]
            assert len(projected["events"]) == len(analysis["events"])
            assert len(projected["lines"]) == len(analysis["lines"])
            for old_line, public_line in zip(analysis["lines"], projected["lines"]):
                for key in ("line_id", "side", "slope", "intercept", "points", "projections", "first_anchor", "second_anchor"):
                    assert public_line[key] == old_line[key]
                assert public_line["contacts"] == [{key: row[key] for key in ("session", "index", "price")}
                                                   for row in old_line["contacts"]]


def test_full_780_krx_engine_fixture_fits_public_sidecar_budget_without_trimming_plot_data():
    from ai_fc import dashboard
    asset = deepcopy(C.load_asset_registry(REPOSITORY)["sk-hynix"])
    asset.update(enabled=True, source_id="fixture_krx")
    policy = {"sources": {"fixture_krx": {"rights_status": "approved_free", "allow_collection": True,
              "allow_derived_display": True, "allow_ohlc": True, "asset_ids": ["sk-hynix"],
              "allowed_price_bases": [asset["price_basis"]], "calendar_ids": [asset["calendar_id"]],
              "allowed_domains": ["fixture.invalid"], "parser_id": "json_ohlc_v1", "adjustment_method": "split_only",
              "adjustment_vintage_guarantee": True}}}
    bars = []
    for index, (session, _opened, closed) in enumerate(C.session_schedule("XKRX", "2023-01-02", "2026-10-12")[:780]):
        available = (closed + timedelta(minutes=20)).isoformat()
        low = 800000 + index * 800 + abs(index % 26 - 13) * 6000
        bars.append({"open": low + 10000, "high": low + 40000, "low": low, "close": low + 20000,
                     "bar_id": "fixture-krx-bar-" + str(index), "session_date": session,
                     **{key: asset[key] for key in ("asset_id", "source_id", "currency", "unit", "price_basis", "calendar_id")},
                     "available_at": available, "fetched_at": available, "finalized_at": closed.isoformat(),
                     "revision_seq": 1, "supersedes_bar_id": None, "receipt_id": "fixture-receipt-" + str(index),
                     "raw_sha256": C.canonical_hash({"fixture": index})})
    cutoff = (C.aware_time(bars[-1]["available_at"]) + timedelta(minutes=10)).isoformat()
    snapshot = P.E.build_asset_snapshot(asset, bars, cutoff, source_policy=policy)
    assert snapshot["status"] == "ready"
    assert P.E.verify_asset_snapshot(snapshot, bars, asset, source_policy=policy)["ok"] is True
    detail = D.compact_snapshot(snapshot)
    payload = {"schema_version": 1, "contract_id": "trendlines_asset_route_v1", "data": {"trendlines": detail}}
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    assert len(raw) <= dashboard.TRENDLINES_ASSET_BUDGET_BYTES
    assert len(detail["bars"]) == 756
    assert sum(len(row["lines"]) for windows in detail["analyses"].values() for row in windows.values()) == sum(
        len(row["lines"]) for windows in snapshot["analyses"].values() for row in windows.values())


@pytest.mark.parametrize("attack", ["record_id", "payload_id", "snapshot_asset", "invented_transition"])
def test_event_with_valid_hash_chain_cannot_forge_snapshot_identity_or_transition(store, attack):
    # The cold snapshots intentionally contain no transitions. This attack
    # recomputes a valid chain and pointer, so cryptographic framing alone cannot
    # detect that the event was never independently derived by the engine.
    P.refresh(store, as_of=ISSUED)
    pointer = P.latest(store)
    referenced = pointer["assets"][0]
    asset_id = "soxx" if attack == "snapshot_asset" else referenced["asset_id"]
    event = {"event_id": "invented-event", "line_id": "invented-line", "close": 999999,
             "new_state": "reclaimed", "issued_at": ISSUED, "effective_session": "2026-09-12"}
    expected = S.digest({"asset_id": asset_id, "event": event})
    payload = {"event_id": "0" * 64 if attack == "payload_id" else expected,
               "asset_id": asset_id, "snapshot_id": referenced["snapshot_id"], "event": event}
    identity = "0" * 64 if attack == "record_id" else expected
    S.append_chain(store, "events", [{"record_id": identity, "payload": payload}])
    pointer["ledger_heads"]["events"] = S.read_chain(store, "events")[-1]["chain_hash"]
    pointer["content_hash"] = P._body_hash(pointer)
    S.atomic_json(store / P.LATEST, pointer)
    audit = P.verify(store, replay=True)
    assert audit["ok"] is False
    reason = audit["errors"][0]
    if attack in {"record_id", "payload_id"}:
        assert "event content identity" in reason
    elif attack == "snapshot_asset":
        assert "event asset" in reason
    else:
        assert "replayed snapshot transition" in reason
    assert P.refresh(store, as_of=ISSUED)["publication_allowed"] is False


def test_genuine_captured_break_and_reclaim_events_match_frozen_snapshot(store):
    asset = _enable(store)
    rows = _records()
    initial_capture = (date.fromisoformat(rows[77]["session_date"]) + timedelta(days=1)).isoformat() + "T01:00:00+00:00"
    first = P.refresh(store, as_of=initial_capture, capture_bundle=_bundle(
        store, asset, records=rows[:78], fetched=initial_capture, directory="initial78"))
    assert first["status"] == "partial"
    for index in (86, 87):
        for key in ("open", "high", "low", "close"):
            rows[index][key] -= 10
    P.refresh(store, as_of=ISSUED, capture_bundle=_bundle(store, asset, records=rows, directory="break_reclaim"))
    events = S.read_chain(store, "events")
    assert events, "the fixture must exercise real derived transitions"
    snapshot_records = {row["record_id"]: row["payload"] for row in S.read_chain(store, "snapshots")}
    for row in events:
        payload = row["payload"]
        assert row["record_id"] == payload["event_id"] == S.digest({"asset_id": payload["asset_id"], "event": payload["event"]})
        snapshot = P._archive(store, snapshot_records[payload["snapshot_id"]])["snapshot"]
        assert payload["asset_id"] == snapshot["asset_id"] and payload["event"] in snapshot["events"]
    assert P.verify(store, replay=True)["ok"] is True


def _invalid_approved_capture(root, *, portable=False):
    asset = _enable(root)
    records = _records()
    records[-1]["high"] = records[-1]["close"] - 3
    if portable:
        _inbox(root, asset, records)
        directory = root / "portable_rejected"
        P.capture(root, out=directory, as_of=ISSUED)
    else:
        directory = _bundle(root, asset, records=records, directory="bad_prices")
    return asset, directory


@pytest.mark.parametrize("portable", [False, True])
def test_rejected_approved_prices_preserve_permanent_raw_receipt_and_policy_after_artifact_removal(store, portable):
    _, directory = _invalid_approved_capture(store, portable=portable)
    result = P.refresh(store, as_of=ISSUED, capture_bundle=directory)
    assert result["status"] == "hold" and result["publication_allowed"] is True
    rows = S.read_chain(store, "rejections")
    assert len(rows) == 1
    record = rows[0]["payload"]
    metadata = S.read_json(store / record["metadata_path"])
    raw = (store / record["raw_path"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == metadata["raw_sha256"]
    assert metadata["receipt"]["raw_path"] == record["raw_path"]
    assert metadata["receipt"]["fetched_at"] == ISSUED
    assert metadata["source_policy_hash"] == S.digest(metadata["source_policy"])
    assert metadata["numeric_input_allowed"] is False and "containment" in metadata["reason"]
    assert S.read_chain(store, "bars") == S.read_chain(store, "events") == S.read_chain(store, "raw_receipts") == []
    assert all(P._archive(store, row)["snapshot"]["bars"] == [] for row in P.latest(store)["assets"])
    # Remove only disposable fixture inputs; the permanent evidence must still
    # be verifiable after the Actions artifact and connector inbox expire.
    assert store.resolve() in directory.resolve().parents
    shutil.rmtree(directory)
    inbox = store / S.ROOT / "inbox"
    if inbox.exists():
        assert store.resolve() in inbox.resolve().parents
        shutil.rmtree(inbox)
    assert P.verify(store, replay=True)["ok"] is True


def test_rejected_refetch_is_idempotent_and_preserves_original_receipt_clock(store):
    asset, directory = _invalid_approved_capture(store)
    P.refresh(store, as_of=ISSUED, capture_bundle=directory)
    before = _canonical_bytes(store)
    records = _records()
    records[-1]["high"] = records[-1]["close"] - 3
    fetched = "2026-09-13T02:00:00+00:00"
    second = _bundle(store, asset, records=records, fetched=fetched, directory="bad_refetch")
    result = P.refresh(store, as_of=fetched, capture_bundle=second)
    assert result["changed"] is False and _canonical_bytes(store) == before
    record = S.read_chain(store, "rejections")[0]["payload"]
    assert S.read_json(store / record["metadata_path"])["receipt"]["fetched_at"] == ISSUED


@pytest.mark.parametrize("attack", ["raw", "receipt", "policy", "ledger", "missing_raw", "truncated_ledger"])
def test_permanent_rejection_tamper_blocks_replay_and_publication(store, attack):
    _, directory = _invalid_approved_capture(store)
    P.refresh(store, as_of=ISSUED, capture_bundle=directory)
    record = S.read_chain(store, "rejections")[0]["payload"]
    if attack == "raw":
        (store / record["raw_path"]).write_bytes(b"tampered")
    elif attack == "missing_raw":
        (store / record["raw_path"]).unlink()
    elif attack in {"receipt", "policy"}:
        metadata = S.read_json(store / record["metadata_path"])
        if attack == "receipt":
            metadata["receipt"]["source_uri"] = "https://unapproved.example/ohlc"
        else:
            metadata["source_policy"]["sources"]["fixture_exchange"]["allow_collection"] = False
        S.atomic_json(store / record["metadata_path"], metadata)
    else:
        path = store / S.ROOT / "ledgers/rejections.jsonl"
        path.write_bytes(b"" if attack == "truncated_ledger" else path.read_bytes().replace(b'"reason":', b'"old_reason":', 1))
    assert P.verify(store, replay=True)["ok"] is False
    assert P.refresh(store, as_of=ISSUED)["publication_allowed"] is False


@pytest.mark.parametrize("attack", ["permission", "uri", "hash", "late_receipt", "backdated_receipt"])
def test_bad_authorization_or_receipt_cannot_register_permanent_rejection_raw(store, attack):
    asset, directory = _invalid_approved_capture(store)
    manifest = S.read_json(directory / "manifest.json")
    receipt = manifest["assets"][0]["receipt"]
    if attack == "permission":
        policy = C.load_source_policy(store)
        policy["sources"]["fixture_exchange"]["allow_collection"] = False
        (store / C.SOURCE_POLICY_RELATIVE).write_text(yaml.safe_dump(policy), encoding="utf-8")
    elif attack == "uri":
        receipt["source_uri"] = "https://fixture.example/ohlc?API_KEY=hidden"
    elif attack == "hash":
        receipt["raw_sha256"] = "0" * 64
    elif attack == "late_receipt":
        receipt["fetched_at"] = receipt["available_at"] = "2026-09-14T01:00:00+00:00"
    else:
        receipt["available_at"] = "2026-06-15T01:00:00+00:00"
    manifest["content_hash"] = P._body_hash(manifest)
    S.atomic_json(directory / "manifest.json", manifest)
    result = P.refresh(store, as_of=ISSUED, capture_bundle=directory)
    assert result["capture_failures"]
    assert S.read_chain(store, "rejections") == []
    assert not (store / S.ROOT / "quarantine/raw").exists()
