"""Disposable public-HTML research captures; no live network or durable writes."""

from __future__ import annotations

import hashlib
import json
import shutil
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ai_fc.trendlines import contracts as C, display as D, pipeline as P, research as R, storage as S

REPOSITORY = Path(__file__).resolve().parents[2]
FIRST = datetime(2024, 1, 1, tzinfo=timezone.utc)
FETCHED = "2024-04-10T01:00:00+00:00"


@pytest.fixture
def store(tmp_path):
    for relative in (C.CONTRACT_RELATIVE, C.ASSET_REGISTRY_RELATIVE, C.SOURCE_POLICY_RELATIVE):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPOSITORY / relative, path)
    return tmp_path


def public_html(*, gap=False, invalid=False, symbol="BTC-USD", currency="USD", intraday=False, invalid_volume=False):
    stamps, quote = [], {key: [] for key in ("open", "high", "low", "close", "volume")}
    for index in range(100):
        day = FIRST + timedelta(days=index)
        stamps.append(int(day.timestamp()))
        low = 100 + 0.1 * index + abs(index % 20 - 10) * 0.6
        values = {"open": low + 1, "high": low + 4, "low": low, "close": low + 2, "volume": 100}
        if gap and index == 90:
            values = {key: None for key in values}
        if invalid and index == 95:
            values["high"] = 1
        if invalid_volume and index == 95:
            values["volume"] = -1
        for key in quote:
            quote[key].append(values[key])
    payload = {"chart": {"result": [{"meta": {"symbol": symbol, "currency": currency,
                "exchangeTimezoneName": "UTC", "dataGranularity": "1d", "instrumentType": "CRYPTOCURRENCY"},
                "timestamp": stamps, "indicators": {"quote": [quote]}, "events": {}}], "error": None}}
    if intraday:
        payload["chart"]["result"][0]["meta"].update({"regularMarketTime": stamps[-1] + 18 * 3600,
                                                     "regularMarketPrice": 123.45})
    wrapper = {"status": 200, "statusText": "OK", "headers": {"content-type": "application/json"},
               "body": json.dumps(payload)}
    return ('<!doctype html><html><script type="application/json" data-sveltekit-fetched '
            'data-url="https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD?interval=1d">'
            + json.dumps(wrapper) + '</script></html>').encode()


def receipt(raw, fetched=FETCHED):
    return {"url": "https://finance.yahoo.com/quote/BTC-USD/history/?period1=1704067200&period2=1712707200",
            "retrieved_at": fetched, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "http_status": 200}


def all_bytes(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in (root / R.ROOT).rglob("*") if path.is_file()}


def test_exact_html_research_capture_replays_without_approving_official_source(store):
    official_before = {str(path.relative_to(store)): path.read_bytes()
                       for path in (store / S.ROOT).rglob("*") if path.is_file()}
    raw = public_html()
    result = R.capture_html(store, "bitcoin", raw, receipt(raw), as_of=FETCHED)
    assert result["changed"] and result["status"] == "unverified_display"
    assert R.verify(store, replay=True)["ok"]
    detail = R.load_asset_detail(store, "bitcoin", now=FETCHED)
    assert detail["status"] == "unverified_display" and detail["verified_source"] is False
    assert detail["official_forecast_write"] is False and detail["publication_class"] == "research_source"
    assert detail["source_context"] == R.CONTEXT and detail["rights_status"] == R.RIGHTS
    assert detail["source_identity"]["rights_status"] == R.RIGHTS
    assert len(detail["bars"]) == 100 and not detail["events"]
    archive = S.read_json(store / detail["research_archive_path"])
    assert all(bar["available_at"] == FETCHED == bar["fetched_at"] for bar in archive["bars"])
    assert not archive["engine_snapshot"]["guards"].get("approved_free_ohlc", False)
    assert (store / archive["receipt_path"]).is_file()
    saved_receipt = S.read_json(store / archive["receipt_path"])
    assert (store / saved_receipt["raw_path"]).read_bytes() == raw
    assert not C.load_source_policy(store)["sources"]
    assert all(not asset["enabled"] for asset in C.load_asset_registry(store).values())
    assert official_before == {str(path.relative_to(store)): path.read_bytes()
                               for path in (store / S.ROOT).rglob("*") if path.is_file()}


def test_audit_releases_checked_archive_bodies_but_still_checks_old_evidence(store, monkeypatch):
    import gc
    import weakref

    for index in range(5):
        fetched = f"2024-04-{10+index:02d}T01:00:00+00:00"
        raw = public_html() + f"<!-- capture {index} -->".encode()
        R.capture_html(store, "bitcoin", raw, receipt(raw, fetched), as_of=fetched)
    before = all_bytes(store)
    original_checked = R._checked
    living, peak = 0, 0

    class TrackedArchive(dict):
        pass

    def released():
        nonlocal living
        living -= 1

    def checked(path):
        nonlocal living, peak
        value = original_checked(path)
        if value.get("contract_id") == "trendlines_research_snapshot_v1":
            gc.collect()
            value = TrackedArchive(value)
            living += 1
            peak = max(peak, living)
            weakref.finalize(value, released)
        return value

    monkeypatch.setattr(R, "_checked", checked)
    audit = R.verify(store, replay=True)
    assert audit["ok"] and audit["snapshots"] == 5
    assert peak <= 2, "checked historical bodies must not accumulate in the revision index"
    assert before == all_bytes(store)
    # Releasing a parsed body must not skip old raw evidence or revision checks.
    raw_path = next((store / R.ROOT / "raw").glob("*.bin"))
    raw_path.write_bytes(b"controlled corruption of retained source")
    assert not R.verify(store, replay=True)["ok"]


def test_refetch_identical_html_preserves_first_acquisition_and_is_noop(store):
    raw = public_html()
    first = R.capture_html(store, "bitcoin", raw, receipt(raw), as_of=FETCHED)
    before = all_bytes(store)
    second = R.capture_html(store, "bitcoin", raw, receipt(raw, "2024-04-11T01:00:00+00:00"),
                            as_of="2024-04-11T01:00:00+00:00")
    assert not second["changed"] and first["snapshot_id"] == second["snapshot_id"]
    assert before == all_bytes(store)
    assert R.load_asset_detail(store, "bitcoin", now="2024-04-11T02:00:00+00:00")["retrieved_at"] == FETCHED


def test_null_rows_are_auditable_calendar_gaps_without_secondary_fill(store):
    raw = public_html(gap=True)
    R.capture_html(store, "bitcoin", raw, receipt(raw), as_of=FETCHED)
    detail = R.load_asset_detail(store, "bitcoin", now=FETCHED)
    assert len(detail["bars"]) == 99
    assert detail["gaps"] == [{"session": "2024-03-31", "session_index": 90, "reason": "source_null_ohlc_no_fill"}]
    assert not any(bar["session"] == "2024-03-31" for bar in detail["bars"])
    assert detail["bars"][90]["session_index"] == 91


def test_invalid_price_keeps_html_and_receipt_but_does_not_publish(store):
    raw = public_html(invalid=True)
    with pytest.raises(ValueError, match="containment"):
        R.capture_html(store, "bitcoin", raw, receipt(raw), as_of=FETCHED)
    receipts = list((store / R.ROOT / "receipts").glob("*.json"))
    assert len(receipts) == 1
    preserved = S.read_json(receipts[0])
    assert (store / preserved["raw_path"]).read_bytes() == raw
    assert len(list((store / R.ROOT / "failures").glob("*.json"))) == 1
    assert not (store / R.ROOT / "latest.json").exists()
    assert R.verify(store)["ok"] and R.load_asset_detail(store, "bitcoin", now=FETCHED) is None


@pytest.mark.parametrize("attack", ["hash", "future", "backdated", "credentials", "identity", "userinfo"])
def test_invalid_receipt_never_registers_permanent_research_raw(store, attack):
    raw = public_html()
    note = receipt(raw)
    if attack == "hash": note["sha256"] = "0" * 64
    if attack == "future": note["retrieved_at"] = "2024-04-11T01:00:00+00:00"
    if attack == "backdated": note["available_at"] = "2024-04-09T00:00:00+00:00"
    if attack == "credentials": note["url"] += "&API_KEY=secret"
    if attack == "identity": note["url"] = "https://finance.yahoo.com/quote/MAGS/history/"
    if attack == "userinfo": note["url"] = "https://user@finance.yahoo.com/quote/BTC-USD/history/"
    with pytest.raises(ValueError):
        R.capture_html(store, "bitcoin", raw, note, as_of=FETCHED)
    assert not list((store / R.ROOT).rglob("*.bin"))


@pytest.mark.parametrize("attack", ["raw", "receipt", "snapshot", "latest", "path"])
def test_tampered_research_artifacts_block_numerical_display(store, attack):
    raw = public_html()
    R.capture_html(store, "bitcoin", raw, receipt(raw), as_of=FETCHED)
    pointer = S.read_json(store / R.ROOT / "latest.json")
    ref = pointer["assets"]["bitcoin"]
    archive = S.read_json(store / ref["snapshot_path"])
    saved_receipt = S.read_json(store / archive["receipt_path"])
    if attack == "raw": (store / saved_receipt["raw_path"]).write_bytes(raw + b" ")
    if attack == "receipt":
        saved_receipt["available_at"] = "2000-01-01T00:00:00+00:00"
        S.atomic_json(store / archive["receipt_path"], R._hash(saved_receipt))
    if attack == "snapshot":
        archive["bars"][0]["close"] += 1
        S.atomic_json(store / ref["snapshot_path"], R._hash(archive))
    if attack == "latest":
        pointer["assets"]["bitcoin"]["snapshot_sha256"] = "0" * 64
        S.atomic_json(store / R.ROOT / "latest.json", R._hash(pointer))
    if attack == "path":
        pointer["assets"]["bitcoin"]["snapshot_path"] = "../escape.json"
        S.atomic_json(store / R.ROOT / "latest.json", R._hash(pointer))
    assert not R.verify(store, replay=True)["ok"]
    assert R.load_asset_detail(store, "bitcoin", now=FETCHED) is None


def test_research_projection_preserves_official_hold_and_does_not_override_ready(store):
    P.refresh(store, as_of=FETCHED)
    official = D.load_projection(store, now=FETCHED)
    raw = public_html()
    R.capture_html(store, "bitcoin", raw, receipt(raw), as_of=FETCHED)
    assert R.attach_projection(store, official, now=FETCHED) == official
    merged = R.attach_projection(store, official, now=FETCHED, allow_private_research=True)
    selected = next(row for row in merged["assets"] if row["asset_id"] == "bitcoin")
    assert selected["status"] == "unverified_display" and selected["official_snapshot_status"] == "hold"
    assert selected["numbers_visible"] is True and selected["content_hash"] == merged["details"]["bitcoin"]["content_hash"]
    assert official["details"]["bitcoin"]["status"] == "hold" and not official["details"]["bitcoin"]["bars"]
    ready = deepcopy(official)
    next(row for row in ready["assets"] if row["asset_id"] == "bitcoin")["status"] = "ready"
    assert R.attach_projection(store, ready, now=FETCHED, allow_private_research=True)["details"]["bitcoin"] == ready["details"]["bitcoin"]


def test_unknown_mag7_equivalent_cannot_be_replaced_by_yahoo_etf(store):
    raw = public_html()
    with pytest.raises(ValueError, match="instrument_unavailable"):
        R.capture_html(store, "mag7", raw, receipt(raw), as_of=FETCHED)
    assert not (store / R.ROOT).exists()


def test_capture_cutoff_before_first_acquisition_never_displays_numbers(store):
    raw = public_html()
    R.capture_html(store, "bitcoin", raw, receipt(raw), as_of=FETCHED)
    assert R.load_asset_detail(store, "bitcoin", now="2024-04-10T00:59:59+00:00") is None


def test_provider_watermark_prevents_partial_candle_becoming_final_after_fetch(store):
    raw = public_html(intraday=True)
    R.capture_html(store, "bitcoin", raw, receipt(raw), as_of=FETCHED)
    detail = R.load_asset_detail(store, "bitcoin", now=FETCHED)
    assert len(detail["bars"]) == 99 and detail["observation_through"] == "2024-04-08"
    assert detail["gaps"] == [{"session": "2024-04-09", "session_index": 99,
                               "reason": "unfinished_session_not_a_final_candle"}]
    assert detail["intraday_quote"]["price"] == 123.45
    assert detail["intraday_quote"]["session_index"] == 99
    assert detail["intraday_quote"]["observed_at"] == "2024-04-09T18:00:00+00:00"
    assert detail["intraday_quote"]["status"] == "intraday_snapshot_not_final_close"
    assert detail["quality"]["stale"]
    assert not detail["historical_signals_available"] and not detail["adjustment_verified"]


def test_failed_capture_preserves_previous_research_snapshot_and_new_invalid_original(store):
    raw = public_html()
    R.capture_html(store, "bitcoin", raw, receipt(raw), as_of=FETCHED)
    pointer_before = (store / R.ROOT / "latest.json").read_bytes()
    initial_id = R.load_asset_detail(store, "bitcoin", now=FETCHED)["snapshot_id"]
    invalid = public_html(invalid=True)
    with pytest.raises(ValueError, match="containment"):
        R.capture_html(store, "bitcoin", invalid, receipt(invalid), as_of=FETCHED)
    assert (store / R.ROOT / "latest.json").read_bytes() == pointer_before
    assert len(list((store / R.ROOT / "raw").glob("*.bin"))) == 2
    assert R.verify(store, replay=True)["ok"]
    assert R.load_asset_detail(store, "bitcoin", now=FETCHED)["snapshot_id"] == initial_id


@pytest.mark.parametrize("field", ["symbol", "currency"])
def test_embedded_instrument_mismatch_keeps_original_but_never_publishes(store, field):
    raw = public_html(**({"symbol": "MAGS"} if field == "symbol" else {"currency": "KRW"}))
    with pytest.raises(ValueError, match="identity|currency"):
        R.capture_html(store, "bitcoin", raw, receipt(raw), as_of=FETCHED)
    assert len(list((store / R.ROOT / "raw").glob("*.bin"))) == 1
    assert not (store / R.ROOT / "latest.json").exists()
    assert R.verify(store, replay=True)["ok"]


def test_backdated_revision_preserves_evidence_and_cannot_replace_later_capture(store):
    raw = public_html()
    R.capture_html(store, "bitcoin", raw, receipt(raw), as_of=FETCHED)
    pointer = (store / R.ROOT / "latest.json").read_bytes()
    earlier_raw = public_html(gap=True)
    before = "2024-04-10T00:45:00+00:00"
    with pytest.raises(ValueError, match="cannot_backdate"):
        R.capture_html(store, "bitcoin", earlier_raw, receipt(earlier_raw, before), as_of=before)
    assert (store / R.ROOT / "latest.json").read_bytes() == pointer
    assert len(list((store / R.ROOT / "receipts").glob("*.json"))) == 2
    assert R.verify(store, replay=True)["ok"]


def test_equity_today_without_source_watermark_remains_a_gap_even_after_clock_close(store):
    asset = R.asset_definition(store, "sk-hynix")
    sessions = C.session_schedule("XKRX", "2024-01-01", "2024-04-09")
    timestamps = [int(opened.timestamp()) for _day, opened, _closed in sessions]
    prices = {field: [100.0 + index + offset for index in range(len(sessions))]
              for field, offset in (("open", 1), ("high", 4), ("low", 0), ("close", 2))}
    payload = {"chart": {"error": None, "result": [{"meta": {"symbol": asset["provider_symbol"],
        "currency": "KRW", "exchangeTimezoneName": "Asia/Seoul", "dataGranularity": "1d"},
        "timestamp": timestamps, "indicators": {"quote": [prices]}}]}}
    wrapper = {"status": 200, "body": json.dumps(payload)}
    raw = ('<script type="application/json" data-sveltekit-fetched data-url="https://query1.finance.yahoo.com/v8/finance/chart/000660.KS?interval=1d">'
           + json.dumps(wrapper) + '</script>').encode()
    stamp = "2024-04-09T08:00:00+00:00"
    note = {**receipt(raw, stamp), "url": "https://finance.yahoo.com/quote/000660.KS/history/"}
    result = R.capture_html(store, "sk-hynix", raw, note, as_of=stamp)
    assert result["observation_through"] == "2024-04-08"
    assert result["gaps"][-1]["reason"] == "source_current_session_finality_unverified"
    assert result["gaps"][-1]["session"] == "2024-04-09"
    assert R.verify(store, replay=True)["ok"]


def test_explicit_private_rejected_row_policy_preserves_source_prices_without_correction(store):
    from ai_fc.trendlines.research_html import parse_yahoo_history

    raw = public_html(invalid=True)
    result = R.capture_html(store, "bitcoin", raw, receipt(raw), as_of=FETCHED, allow_rejected_rows=True)
    detail = R.load_asset_detail(store, "bitcoin", now=FETCHED)
    source_rows, _meta = parse_yahoo_history(raw, R.asset_definition(store, "bitcoin"))
    rejected = source_rows[95]
    assert result["bars"] == 99 and len(detail["rejected_rows"]) == 1
    assert detail["rejected_rows"] == [{"session": rejected["date"], "session_index": 95,
        "reason": "source_invalid_ohlc_no_fill", "validation_error": "OHLC containment violation", "original_row": rejected}]
    assert detail["row_validation_policy"]["allow_rejected_rows"] is True
    assert detail["row_validation_policy"]["purpose"] == "private_user_research_chart"
    assert detail["row_validation_policy"]["correction_or_fill_allowed"] is False
    original = {row["date"]: row for row in source_rows}
    for candle in detail["bars"]:
        assert candle["session"] != rejected["date"]
        assert all(candle[field] == original[candle["session"]][field] for field in ("open", "high", "low", "close"))
    assert R.verify(store, replay=True)["ok"]


def test_strict_failure_can_be_retried_with_explicit_policy_without_rewriting_original(store):
    raw = public_html(invalid=True)
    with pytest.raises(ValueError, match="containment"):
        R.capture_html(store, "bitcoin", raw, receipt(raw), as_of=FETCHED)
    original = all_bytes(store)
    result = R.capture_html(store, "bitcoin", raw, receipt(raw), as_of=FETCHED, allow_rejected_rows=True)
    assert result["changed"] and result["bars"] == 99
    assert all((store / path).read_bytes() == body for path, body in original.items())
    assert R.verify(store, replay=True)["ok"]


def test_private_rejected_row_opt_in_never_bypasses_volume_or_temporal_validation(store):
    raw = public_html(invalid_volume=True)
    with pytest.raises(ValueError, match="invalid volume"):
        R.capture_html(store, "bitcoin", raw, receipt(raw), as_of=FETCHED, allow_rejected_rows=True)
    assert not (store / R.ROOT / "latest.json").exists()
    assert R.verify(store, replay=True)["ok"]


@pytest.mark.parametrize("attack", ["original_row", "policy_flag", "permitted_error"])
def test_reparse_binds_rejected_original_and_policy_even_after_resigning_all_local_hashes(store, attack):
    raw = public_html(invalid=True)
    R.capture_html(store, "bitcoin", raw, receipt(raw), as_of=FETCHED, allow_rejected_rows=True)
    pointer_path = store / R.ROOT / "latest.json"
    pointer = S.read_json(pointer_path)
    ref = pointer["assets"]["bitcoin"]
    old_path = store / ref["snapshot_path"]
    archive = S.read_json(old_path)
    if attack == "original_row": archive["gaps"][0]["original_row"]["high"] = 12345
    if attack == "policy_flag": archive["row_validation_policy"] = R._row_policy(False)
    if attack == "permitted_error": archive["row_validation_policy"]["allowed_errors"].append("invalid volume")
    identity = {key: item for key, item in archive.items() if key not in {"snapshot_id", "content_hash"}}
    archive["snapshot_id"] = "research-snapshot-" + C.canonical_hash(identity)
    archive = R._hash(archive)
    new_relative = R.ROOT / "snapshots" / (archive["snapshot_id"] + ".json")
    S.atomic_json(store / new_relative, archive)
    old_path.unlink()
    pointer["assets"]["bitcoin"] = {"snapshot_id": archive["snapshot_id"], "snapshot_path": new_relative.as_posix(),
                                    "snapshot_sha256": hashlib.sha256(S.encode(archive)).hexdigest()}
    S.atomic_json(pointer_path, R._hash(pointer))
    report = R.verify(store, replay=True)
    assert not report["ok"]
    if attack == "original_row": assert "differs_from_original_html" in report["errors"][0]
    if attack == "policy_flag": assert "containment" in report["errors"][0]
    if attack == "permitted_error": assert "contract_invalid" in report["errors"][0]
    assert R.load_asset_detail(store, "bitcoin", now=FETCHED) is None


def test_private_import_pins_exact_python_json_string_before_browser_parse(store):
    raw = public_html()
    R.capture_html(store, "bitcoin", raw, receipt(raw), as_of=FETCHED)
    detail = R.load_asset_detail(store, "bitcoin", now=FETCHED)
    envelope = R.export_private_import(store, "bitcoin", now=FETCHED)
    assert envelope["contract_id"] == "trendlines_private_import_v1"
    assert envelope["publication_scope"] == "private_only"
    assert len(envelope["payload_json"].encode()) <= R.MAX_PRIVATE_PAYLOAD_BYTES
    assert len(S.encode(envelope)) <= R.MAX_PRIVATE_ENVELOPE_BYTES
    assert envelope["payload_sha256"] == detail["content_hash"] == hashlib.sha256(envelope["payload_json"].encode()).hexdigest()
    parsed = json.loads(envelope["payload_json"])
    assert "content_hash" not in parsed
    assert {**parsed, "content_hash": envelope["payload_sha256"]} == detail
    assert parsed["bars"] == detail["bars"] and parsed["analyses"] == detail["analyses"]


def test_private_import_fails_budget_without_truncating_any_candle_or_line(store, monkeypatch):
    raw = public_html()
    R.capture_html(store, "bitcoin", raw, receipt(raw), as_of=FETCHED)
    before = all_bytes(store)
    monkeypatch.setattr(R, "MAX_PRIVATE_PAYLOAD_BYTES", 10)
    with pytest.raises(ValueError, match="256KiB"):
        R.export_private_import(store, "bitcoin", now=FETCHED)
    assert all_bytes(store) == before
    monkeypatch.setattr(R, "MAX_PRIVATE_PAYLOAD_BYTES", 256 * 1024)
    monkeypatch.setattr(R, "MAX_PRIVATE_ENVELOPE_BYTES", 10)
    with pytest.raises(ValueError, match="512KiB"):
        R.export_private_import(store, "bitcoin", now=FETCHED)
    assert all_bytes(store) == before


@pytest.mark.parametrize("same_price", [True, False])
def test_final_equity_close_omits_only_identical_completed_quote_without_mutating_archive(store, same_price):
    asset = R.asset_definition(store, "sk-hynix")
    sessions = C.session_schedule("XKRX", "2024-01-01", "2024-04-09")
    timestamps = [int(opened.timestamp()) for _day, opened, _closed in sessions]
    prices = {field: [100.0 + index + offset for index in range(len(sessions))]
              for field, offset in (("open", 1), ("high", 4), ("low", 0), ("close", 2))}
    quote_price = prices["close"][-1] + (0 if same_price else 1)
    meta = {"symbol": asset["provider_symbol"], "currency": "KRW", "exchangeTimezoneName": "Asia/Seoul",
            "dataGranularity": "1d", "regularMarketTime": int(sessions[-1][2].timestamp()) + 1,
            "regularMarketPrice": quote_price}
    payload = {"chart": {"error": None, "result": [{"meta": meta, "timestamp": timestamps,
                                                     "indicators": {"quote": [prices]}}]}}
    wrapper = {"status": 200, "body": json.dumps(payload)}
    raw = ('<script type="application/json" data-sveltekit-fetched data-url="https://query1.finance.yahoo.com/v8/finance/chart/000660.KS?interval=1d">'
           + json.dumps(wrapper) + '</script>').encode()
    fetched = "2024-04-09T08:00:00+00:00"
    note = {**receipt(raw, fetched), "url": "https://finance.yahoo.com/quote/000660.KS/history/"}
    R.capture_html(store, "sk-hynix", raw, note, as_of=fetched)
    before = all_bytes(store)
    detail = R.load_asset_detail(store, "sk-hynix", now=fetched)
    assert detail["retrieved_at"] == fetched
    assert detail["observation_through"] == "2024-04-09"
    assert detail["bars"][-1]["session"] == "2024-04-09"
    assert detail["bars"][-1]["close"] == prices["close"][-1]
    assert len(detail["bars"]) == len(sessions) and not detail["quality"]["stale"]
    if same_price:
        assert "intraday_quote" not in detail
    else:
        assert detail["intraday_quote"]["price"] == quote_price
    archive = S.read_json(store / detail["research_archive_path"])
    assert archive["metadata"]["quote"]["price"] == quote_price
    assert all_bytes(store) == before
    assert R.verify(store, replay=True)["ok"]
