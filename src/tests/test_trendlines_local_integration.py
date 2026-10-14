"""Offline integration checks for the local-only automatic chart connection."""

from __future__ import annotations

import hashlib
import json
import runpy
import shutil
from copy import deepcopy
from pathlib import Path

import pytest

from ai_fc.trendlines import contracts as C, research as R, storage as S

REPOSITORY = Path(__file__).resolve().parents[2]
FIXTURE = runpy.run_path(str(REPOSITORY / "src/tests/test_trendlines_research.py"))


@pytest.fixture
def captured(tmp_path):
    for relative in (C.CONTRACT_RELATIVE, C.ASSET_REGISTRY_RELATIVE, C.SOURCE_POLICY_RELATIVE):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPOSITORY / relative, path)
    raw = FIXTURE["public_html"]()
    R.capture_html(tmp_path, "bitcoin", raw, FIXTURE["receipt"](raw), as_of=FIXTURE["FETCHED"])
    return tmp_path


def originals(root):
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in (root / R.ROOT).rglob("*") if path.is_file()}


def test_next_completed_session_changes_read_freshness_without_reissuing_geometry(captured):
    before = originals(captured)
    original = R.load_asset_detail(captured, "bitcoin", now=FIXTURE["FETCHED"])
    assert original["quality"]["stale"] is False
    refreshed = R.load_asset_detail(captured, "bitcoin", now="2024-04-11T00:15:00+00:00")
    assert refreshed["quality"]["stale"] is True
    assert refreshed["quality"]["expected_completed_session"] == "2024-04-10"
    assert refreshed["quality"]["missing_session_dates"] == ["2024-04-10"]
    assert "missing_latest_completed_session" in refreshed["quality"]["reasons"]
    for field in ("as_of", "knowledge_cutoff", "retrieved_at", "receipt_id", "raw_sha256", "snapshot_id",
                  "engine_snapshot_id", "source_snapshot_hash", "observation_through", "bars", "analyses", "events"):
        assert refreshed[field] == original[field], field
    assert refreshed["content_hash"] != original["content_hash"]
    assert originals(captured) == before and R.verify(captured, replay=True)["ok"]


def test_completed_session_buffer_and_intraday_reads_do_not_churn_export(captured):
    first = R.export_private_import(captured, "bitcoin", now="2024-04-11T00:10:00+00:00")
    second = R.export_private_import(captured, "bitcoin", now="2024-04-11T00:14:59+00:00")
    assert first == second
    detail = json.loads(second["payload_json"])
    assert detail["quality"]["stale"] is False
    assert detail["quality"]["expected_completed_session"] == "2024-04-09"
    assert detail["retrieved_at"] == FIXTURE["FETCHED"]


def test_stale_export_reaches_local_browser_contract_without_mutating_archive(captured):
    before = originals(captured)
    envelope = R.export_private_import(captured, "bitcoin", now="2024-04-12T01:00:00+00:00")
    detail = json.loads(envelope["payload_json"])
    assert detail["quality"]["missing_session_dates"] == ["2024-04-10", "2024-04-11"]
    assert detail["quality"]["expected_completed_session"] == "2024-04-11"
    assert detail["quality"]["latest_completed_observation"] == detail["observation_through"] == "2024-04-09"
    assert detail["verified_source"] is False and detail["publication_scope"] == "private_only"
    assert originals(captured) == before


def test_read_before_actual_first_acquisition_remains_ineligible(captured):
    assert R.load_asset_detail(captured, "bitcoin", now="2024-04-10T00:59:59+00:00") is None


@pytest.fixture(scope="module")
def transport(tmp_path_factory):
    root = tmp_path_factory.mktemp("private-packed-transport")
    for relative in (C.CONTRACT_RELATIVE, C.ASSET_REGISTRY_RELATIVE, C.SOURCE_POLICY_RELATIVE):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPOSITORY / relative, path)
    raw = FIXTURE["public_html"](gap=True)
    R.capture_html(root, "bitcoin", raw, FIXTURE["receipt"](raw), as_of=FIXTURE["FETCHED"])
    detail = R.load_asset_detail(root, "bitcoin", now=FIXTURE["FETCHED"])
    before = originals(root)
    v1 = R.export_private_import(root, "bitcoin", now=FIXTURE["FETCHED"])
    # Exercise the oversize branch with an actual replayed disposable capture.
    # The real 256 KiB limit remains in force when either envelope is decoded.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(R, "MAX_PRIVATE_PAYLOAD_BYTES", len(v1["payload_json"].encode()) - 1)
        v2 = R.export_private_import(root, "bitcoin", now=FIXTURE["FETCHED"])
    assert originals(root) == before
    return root, detail, v1, v2, before


def test_v1_private_import_preserves_existing_body_and_hash(transport):
    _root, detail, v1, _v2, _before = transport
    assert v1["schema_version"] == 1 and v1["contract_id"] == "trendlines_private_import_v1"
    assert {**R.decode_private_import(v1), "content_hash": v1["payload_sha256"]} == detail


def test_v2_packed_bars_restore_exact_detail_without_price_or_archive_changes(transport):
    root, detail, v1, v2, before = transport
    packed = json.loads(v2["payload_json"])
    assert v2["schema_version"] == 2 and v2["contract_id"] == "trendlines_private_import_v2"
    assert "bars" not in packed and "content_hash" not in packed
    assert packed["bars_packed"]["columns"] == list(R.PRIVATE_BAR_COLUMNS)
    assert packed["bars_packed"]["bar_id_prefix"] == R.PRIVATE_BAR_ID_PREFIX
    assert packed["bars_packed"]["rows"] == [[bar[key] for key in R.PRIVATE_BAR_COLUMNS[:-1]]
                                           + [bar["bar_id"][len(R.PRIVATE_BAR_ID_PREFIX):]] for bar in detail["bars"]]
    restored = R.decode_private_import(v2)
    assert {**restored, "content_hash": v2["original_detail_sha256"]} == detail
    assert C.canonical_hash(restored) == detail["content_hash"] == packed["original_detail_sha256"]
    assert v2["payload_sha256"] == hashlib.sha256(v2["payload_json"].encode("utf-8")).hexdigest()
    assert v2["payload_sha256"] != v2["original_detail_sha256"]
    assert len(v2["payload_json"].encode()) < len(v1["payload_json"].encode())
    assert len(v2["payload_json"].encode()) <= R.MAX_PRIVATE_PAYLOAD_BYTES
    assert len(S.encode(v2)) <= R.MAX_PRIVATE_ENVELOPE_BYTES
    # Preserve gap ordinals and Python's numeric representation, not just values.
    assert restored["gaps"] == detail["gaps"] and restored["bars"][90]["session_index"] == 91
    for expected, actual in zip(detail["bars"], restored["bars"]):
        assert all(type(actual[key]) is type(expected[key]) for key in R.PRIVATE_BAR_COLUMNS)
    assert originals(root) == before


@pytest.mark.parametrize("attack", ["wire_hash", "outside_original", "both_original", "ohlc", "column_order",
                                   "row_width", "extra_packed_key", "shadow_bars", "duplicate_json_key",
                                   "boolean_version", "prefix", "id_suffix", "id_type"])
def test_v2_private_import_rejects_tampering_even_with_rehashed_wire(transport, attack):
    root, _detail, _v1, template, before = transport
    envelope = deepcopy(template)
    body = json.loads(envelope["payload_json"])
    if attack == "wire_hash":
        envelope["payload_json"] += " "
    elif attack == "outside_original":
        envelope["original_detail_sha256"] = "0" * 64
    elif attack == "boolean_version":
        envelope["schema_version"] = True
    else:
        if attack == "both_original":
            body["original_detail_sha256"] = envelope["original_detail_sha256"] = "0" * 64
        elif attack == "ohlc":
            body["bars_packed"]["rows"][0][5] += 0.125
        elif attack == "column_order":
            body["bars_packed"]["columns"][2:4] = ["high", "open"]
        elif attack == "row_width":
            body["bars_packed"]["rows"][0].pop()
        elif attack == "extra_packed_key":
            body["bars_packed"]["adjustment"] = "split_only"
        elif attack == "shadow_bars":
            body["bars"] = []
        elif attack == "prefix":
            body["bars_packed"]["bar_id_prefix"] = "approved-bar-"
        elif attack == "id_suffix":
            body["bars_packed"]["rows"][0][-1] = "research-bar-" + "0" * 64
        elif attack == "id_type":
            body["bars_packed"]["rows"][0][-1] = 123
        envelope["payload_json"] = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if attack == "duplicate_json_key":
            envelope["payload_json"] = envelope["payload_json"].replace(
                '"bars_packed":', '"bars_packed":null,"bars_packed":', 1)
        envelope["payload_sha256"] = hashlib.sha256(envelope["payload_json"].encode()).hexdigest()
    with pytest.raises(C.TrendlinesError):
        R.decode_private_import(envelope)
    assert originals(root) == before


def test_original_v2_full_bar_ids_remain_backward_compatible(transport):
    _root, detail, _v1, template, _before = transport
    envelope = deepcopy(template)
    body = json.loads(envelope["payload_json"])
    prefix = body["bars_packed"].pop("bar_id_prefix")
    for row in body["bars_packed"]["rows"]:
        row[-1] = prefix + row[-1]
    envelope["payload_json"] = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    envelope["payload_sha256"] = hashlib.sha256(envelope["payload_json"].encode()).hexdigest()
    assert {**R.decode_private_import(envelope), "content_hash": envelope["original_detail_sha256"]} == detail


def test_export_refuses_noncanonical_bar_identity_before_prefix_extraction(transport, monkeypatch):
    root, template, _v1, _v2, before = transport
    detail = deepcopy(template)
    detail["bars"][0]["bar_id"] = "other-provider-id"
    detail = R._hash(detail)
    monkeypatch.setattr(R, "load_asset_detail", lambda *_args, **_kwargs: detail)
    monkeypatch.setattr(R, "MAX_PRIVATE_PAYLOAD_BYTES", 1)
    with pytest.raises(C.TrendlinesError, match="packed_bar_identity_invalid"):
        R.export_private_import(root, "bitcoin", now=FIXTURE["FETCHED"])
    assert originals(root) == before


def test_v2_decode_retains_both_size_limits(transport, monkeypatch):
    _root, _detail, _v1, v2, _before = transport
    monkeypatch.setattr(R, "MAX_PRIVATE_PAYLOAD_BYTES", len(v2["payload_json"].encode()) - 1)
    with pytest.raises(C.TrendlinesError, match="256KiB"):
        R.decode_private_import(v2)
    monkeypatch.setattr(R, "MAX_PRIVATE_PAYLOAD_BYTES", 256 * 1024)
    monkeypatch.setattr(R, "MAX_PRIVATE_ENVELOPE_BYTES", len(S.encode(v2)) - 1)
    with pytest.raises(C.TrendlinesError, match="512KiB"):
        R.decode_private_import(v2)


def test_export_refuses_to_drop_unrecognized_candle_fields(transport, monkeypatch):
    root, template, _v1, _v2, before = transport
    detail = deepcopy(template)
    detail["bars"][0]["unexpected_metadata"] = "must_not_be_lost"
    detail = R._hash(detail)
    monkeypatch.setattr(R, "load_asset_detail", lambda *_args, **_kwargs: detail)
    monkeypatch.setattr(R, "MAX_PRIVATE_PAYLOAD_BYTES", 1)
    with pytest.raises(C.TrendlinesError, match="packed_bars_contract_invalid"):
        R.export_private_import(root, "bitcoin", now=FIXTURE["FETCHED"])
    assert originals(root) == before
