"""User-authorized public HTML research captures, separate from approved sources.

No network access, source approval, official append, missing-candle filling, or
historical availability claim is performed here. A current public vintage is
known only at its recorded capture time, including every retrospective anchor.
"""

from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit
from zoneinfo import ZoneInfo

from . import contracts as C, display as D, engine as E, storage as S

ROOT = Path("data/trendlines_research")
CONTEXT = "user_authorized_public_html_research"
RIGHTS = "uncertified_research_source"
SOURCE = "yahoo_public_history_html"
SYMBOLS = {"sk-hynix": "000660.KS", "soxx": "SOXX", "nasdaq": "^IXIC",
           "sp500": "^GSPC", "bitcoin": "BTC-USD", "dow": "^DJI"}
MAX_RAW_BYTES = 20 * 1024 * 1024
MAX_PRIVATE_PAYLOAD_BYTES = 256 * 1024
MAX_PRIVATE_ENVELOPE_BYTES = 512 * 1024
REJECTABLE_OHLC_ERRORS = {"OHLC must be finite positive numbers; close fallback forbidden", "OHLC containment violation"}


def asset_definition(root: Path, asset_id: str) -> dict[str, Any]:
    """Declare an exact research instrument without enabling official sources."""
    if asset_id not in SYMBOLS:
        raise C.TrendlinesError("research_source_instrument_unavailable")
    asset = deepcopy(C.load_asset_registry(Path(root))[asset_id])
    asset.update({"provider_symbol": SYMBOLS[asset_id], "source_id": SOURCE, "enabled": True,
                  "price_basis": "provider_reported_ohlc_current_vintage", "source_context": CONTEXT,
                  "verified_source": False, "rights_status": RIGHTS})
    return asset


def research_source_policy(asset: dict[str, Any]) -> dict[str, Any]:
    """Explicit research authorization, never a source-rights approval record."""
    return {"schema_version": 1, "default_action": "deny", "sources": {SOURCE: {
        "rights_status": RIGHTS, "source_context": CONTEXT, "adjustment_verified": False,
        "verified_source": False, "asset_ids": [asset["asset_id"]],
        "allowed_price_bases": [asset["price_basis"]], "calendar_ids": [asset["calendar_id"]],
        "allowed_symbols": [asset["provider_symbol"]], "allowed_domains": ["finance.yahoo.com"],
        "parser_id": "yahoo_history_html_v1"}}}


def _hash(value: dict[str, Any]) -> dict[str, Any]:
    body = {key: item for key, item in value.items() if key != "content_hash"}
    return {**body, "content_hash": C.canonical_hash(body)}


def _checked(path: Path) -> dict[str, Any]:
    value = S.read_json(path)
    if value != _hash(value):
        raise C.TrendlinesError("research_artifact_content_hash_mismatch")
    return value


def _receipt(raw: bytes, receipt: dict[str, Any], asset: dict[str, Any], as_of: str) -> dict[str, Any]:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_RAW_BYTES:
        raise C.TrendlinesError("research_raw_size_or_type_invalid")
    if not isinstance(receipt, dict):
        raise C.TrendlinesError("research_receipt_required")
    url = receipt.get("url", receipt.get("source_uri"))
    if not isinstance(url, str):
        raise C.TrendlinesError("research_source_url_required")
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.hostname != "finance.yahoo.com" or parts.username
            or parts.password or parts.fragment or parts.port not in (None, 443)
            or unquote(parts.path) != "/quote/" + asset["provider_symbol"] + "/history/"):
        raise C.TrendlinesError("research_source_url_identity_or_safety_violation")
    if any(key.lower() in S.SECRET_KEYS for key, _value in parse_qsl(parts.query, keep_blank_values=True)):
        raise C.TrendlinesError("research_source_url_credential_rejected")
    sha = hashlib.sha256(raw).hexdigest()
    stated_sha = receipt.get("sha256", receipt.get("raw_sha256"))
    stated_length = receipt.get("bytes", receipt.get("byte_count"))
    if stated_sha != sha or isinstance(stated_length, bool) or stated_length != len(raw):
        raise C.TrendlinesError("research_raw_receipt_sha_or_length_mismatch")
    fetched = S.aware_time(receipt.get("retrieved_at", receipt.get("fetched_at"))).isoformat()
    if not receipt.get("retrieved_at", receipt.get("fetched_at")) or S.aware_time(fetched) > S.aware_time(as_of):
        raise C.TrendlinesError("research_receipt_unknown_or_future_acquisition")
    if S.aware_time(receipt.get("available_at", fetched)) != S.aware_time(fetched):
        raise C.TrendlinesError("research_receipt_backdated_availability")
    status = receipt.get("http_status")
    if status is not None and (isinstance(status, bool) or status != 200):
        raise C.TrendlinesError("research_transport_failure")
    body = {"schema_version": 1, "contract_id": "trendlines_research_receipt_v1",
            "asset_id": asset["asset_id"], "identity": asset["identity"], "symbol": asset["provider_symbol"],
            "source_id": SOURCE, "source_context": CONTEXT, "rights_status": RIGHTS,
            "verified_source": False, "official_forecast_write": False,
            "url": url, "raw_sha256": sha, "byte_count": len(raw), "fetched_at": fetched,
            "available_at": fetched, "http_status": status, "media_type": "text/html",
            "parser_id": "yahoo_history_html_v1", "raw_path": (ROOT / "raw" / (sha + ".bin")).as_posix()}
    body["receipt_id"] = "research-receipt-" + C.canonical_hash(body)
    return _hash(body)


def _write_raw(root: Path, receipt: dict[str, Any], raw: bytes) -> None:
    path = S.safe_path(root, receipt["raw_path"])
    if path.is_file():
        if path.read_bytes() != raw:
            raise C.TrendlinesError("research_immutable_raw_collision")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def _row_policy(allow_rejected_rows: bool) -> dict[str, Any]:
    if not isinstance(allow_rejected_rows, bool):
        raise C.TrendlinesError("research_rejected_row_policy_requires_explicit_boolean")
    return {"allow_rejected_rows": allow_rejected_rows,
            "purpose": "private_user_research_chart" if allow_rejected_rows else "strict_research_ohlc",
            "allowed_errors": sorted(REJECTABLE_OHLC_ERRORS) if allow_rejected_rows else [],
            "correction_or_fill_allowed": False}


def _prepare(raw: bytes, receipt: dict[str, Any], asset: dict[str, Any], cutoff: str, *, config=None,
             allow_rejected_rows: bool = False):
    from .research_html import parse_yahoo_history

    rows, meta = parse_yahoo_history(raw, asset)
    if (meta.get("symbol") != asset["provider_symbol"] or meta.get("currency") != asset["currency"]
            or meta.get("dataGranularity") != "1d"):
        raise C.TrendlinesError("research_html_instrument_currency_or_interval_mismatch")
    if not isinstance(rows, list) or not rows:
        raise C.TrendlinesError("research_html_daily_rows_missing")
    sessions = [row.get("date") for row in rows]
    if sessions != sorted(set(sessions)):
        raise C.TrendlinesError("research_html_session_order_or_duplicate")
    schedule = C.session_schedule(asset["calendar_id"], sessions[0], sessions[-1])
    by_day = {day: (index, closed) for index, (day, _opened, closed) in enumerate(schedule)}
    quote = meta.get("quote") or {}
    if quote.get("price") is not None and (not C._finite_number(quote["price"]) or quote["price"] <= 0):
        raise C.TrendlinesError("research_provider_quote_price_invalid")
    observed = S.aware_time(quote["observed_at"]) if quote.get("observed_at") else None
    if observed is not None and (observed > S.aware_time(receipt["fetched_at"])
                                 or quote.get("symbol") != asset["provider_symbol"]
                                 or quote.get("currency") != asset["currency"]):
        raise C.TrendlinesError("research_provider_quote_time_or_identity_invalid")
    observed_day = observed.astimezone(ZoneInfo(asset["timezone"])).date().isoformat() if observed else None
    captured_day = S.aware_time(receipt["fetched_at"]).astimezone(ZoneInfo(asset["timezone"])).date().isoformat()
    buffer = (config or C.default_config())["settlement_buffer_minutes"]
    bars, gaps = [], []
    for row in rows:
        day = row["date"]
        if day not in by_day:
            raise C.TrendlinesError("research_html_nontrading_session")
        index, closed = by_day[day]
        source_finality_unknown = day == captured_day and (observed is None or observed_day != day)
        if (source_finality_unknown or closed + timedelta(minutes=buffer) > S.aware_time(receipt["fetched_at"])
                or (observed_day == day and observed is not None and observed < closed)):
            gaps.append({"session": day, "session_index": index,
                         "reason": "source_current_session_finality_unverified" if source_finality_unknown else
                         "unfinished_session_not_a_final_candle"})
            continue
        prices = [row.get(field) for field in ("open", "high", "low", "close")]
        if any(value is None for value in prices):
            gaps.append({"session": day, "session_index": index, "reason": "source_null_ohlc_no_fill"})
            continue
        bar = {"asset_id": asset["asset_id"], "source_id": SOURCE, "session_date": day,
               "currency": asset["currency"], "unit": asset["unit"], "price_basis": asset["price_basis"],
               "calendar_id": asset["calendar_id"], "available_at": receipt["fetched_at"],
               "fetched_at": receipt["fetched_at"], "finalized_at": closed.isoformat(),
               "revision_seq": 1, "supersedes_bar_id": None, "raw_sha256": receipt["raw_sha256"],
               "receipt_id": receipt["receipt_id"], **{field: row[field] for field in ("open", "high", "low", "close")}}
        if row.get("volume") is not None:
            bar["volume"] = row["volume"]
        bar["bar_id"] = "research-bar-" + C.canonical_hash(bar)
        try:
            C.validate_bar(bar, asset, cutoff)
        except C.TrendlinesError as exc:
            if not allow_rejected_rows or str(exc) not in REJECTABLE_OHLC_ERRORS:
                raise
            gaps.append({"session": day, "session_index": index, "reason": "source_invalid_ohlc_no_fill",
                         "validation_error": str(exc), "original_row": deepcopy(row)})
            continue
        bars.append(bar)
    supplied = set(sessions)
    gaps.extend({"session": day, "session_index": index, "reason": "source_session_missing_no_fill"}
                for day, (index, closed) in by_day.items()
                if day not in supplied and closed <= S.aware_time(receipt["fetched_at"]))
    if not bars:
        raise C.TrendlinesError("research_no_valid_finalized_ohlc")
    origin = by_day[bars[0]["session_date"]][0]
    for gap in gaps:
        gap["session_index"] -= origin
    return bars, meta, sorted(gaps, key=lambda item: item["session"])


def _latest(root: Path) -> dict[str, Any] | None:
    path = root / ROOT / "latest.json"
    if not path.is_file():
        return None
    value = _checked(path)
    if (value.get("contract_id") != "trendlines_research_latest_v1" or value.get("schema_version") != 1
            or not isinstance(value.get("assets"), dict) or set(value["assets"]) - set(SYMBOLS)):
        raise C.TrendlinesError("research_latest_contract_invalid")
    return value


def capture_html(root: Path, asset_id: str, raw: bytes, receipt: dict[str, Any], *,
                 as_of: str | datetime | None = None, allow_rejected_rows: bool = False) -> dict[str, Any]:
    """Preserve original bytes first, then replay exact finalized research OHLC."""
    root = Path(root)
    row_policy = _row_policy(allow_rejected_rows)
    cutoff = S.aware_time(as_of).isoformat()
    asset = asset_definition(root, asset_id)
    context = _receipt(raw, receipt, asset, cutoff)
    with S.writer_lock(root):
        audit = verify(root, replay=True)
        if not audit["ok"]:
            raise C.TrendlinesError("research_existing_integrity_failed: " + "; ".join(audit["errors"]))
        pointer = _latest(root)
        prior = (pointer or {}).get("assets", {}).get(asset_id)
        if prior:
            previous = _checked(S.safe_path(root, prior["snapshot_path"]))
            old_receipt = _checked(S.safe_path(root, previous["receipt_path"]))
            if (old_receipt["raw_sha256"] == context["raw_sha256"] and old_receipt["url"] == context["url"]
                    and previous["asset"] == asset and previous["config"] == C.load_contract(root)
                    and previous.get("row_validation_policy") == row_policy
                    and previous.get("publication_scope") == "private_only"):
                return {"changed": False, "asset_id": asset_id, "status": "unverified_display",
                        "snapshot_id": previous["snapshot_id"], "receipt_id": old_receipt["receipt_id"]}
        _write_raw(root, context, raw)
        receipt_path = ROOT / "receipts" / (context["receipt_id"] + ".json")
        S.atomic_json(root / receipt_path, context, immutable=True)
        try:
            if prior and (S.aware_time(cutoff) < S.aware_time(previous["capture_asof"])
                          or S.aware_time(context["fetched_at"]) < S.aware_time(old_receipt["fetched_at"])):
                raise C.TrendlinesError("research_capture_revision_cannot_backdate")
            config = C.load_contract(root)
            bars, meta, gaps = _prepare(raw, context, asset, cutoff, config=config,
                                        allow_rejected_rows=allow_rejected_rows)
            policy = research_source_policy(asset)
            snapshot = E.build_research_asset_snapshot(asset, bars, cutoff, config=config, source_policy=policy)
            checked = E.verify_research_asset_snapshot(snapshot, bars, asset, config=config, source_policy=policy, replay=True)
            if checked["ok"] is not True:
                raise C.TrendlinesError("research_numeric_replay_failed: " + "; ".join(checked["errors"]))
            if snapshot.get("numbers_visible") is not True:
                raise C.TrendlinesError("research_insufficient_ohlc_for_geometry")
            body = {"schema_version": 1, "contract_id": "trendlines_research_snapshot_v1",
                    "asset_id": asset_id, "asset": asset, "config": config, "source_policy": policy, "capture_asof": cutoff,
                    "row_validation_policy": row_policy,
                    "source_context": CONTEXT, "rights_status": RIGHTS, "verified_source": False,
                    "publication_scope": "private_only",
                    "official_forecast_write": False, "receipt_path": receipt_path.as_posix(),
                    "receipt_sha256": hashlib.sha256(S.encode(context)).hexdigest(), "receipt_id": context["receipt_id"],
                    "raw_sha256": context["raw_sha256"], "bars": bars, "metadata": meta, "gaps": gaps,
                    "supersedes_snapshot_id": prior["snapshot_id"] if prior else None, "engine_snapshot": snapshot}
            body["snapshot_id"] = "research-snapshot-" + C.canonical_hash(body)
            body = _hash(body)
            snapshot_path = ROOT / "snapshots" / (body["snapshot_id"] + ".json")
            S.atomic_json(root / snapshot_path, body, immutable=True)
            assets = deepcopy((pointer or {}).get("assets", {}))
            assets[asset_id] = {"snapshot_id": body["snapshot_id"], "snapshot_path": snapshot_path.as_posix(),
                                "snapshot_sha256": hashlib.sha256(S.encode(body)).hexdigest()}
            S.atomic_json(root / ROOT / "latest.json", _hash({"schema_version": 1,
                          "contract_id": "trendlines_research_latest_v1", "assets": assets}))
            return {"changed": True, "asset_id": asset_id, "status": "unverified_display",
                    "snapshot_id": body["snapshot_id"], "receipt_id": context["receipt_id"],
                    "bars": len(bars), "gaps": gaps, "observation_through": snapshot["observation_through"]}
        except (ValueError, KeyError, TypeError, OSError) as exc:
            failure = {"schema_version": 1, "contract_id": "trendlines_research_capture_failure_v1",
                       "receipt_id": context["receipt_id"], "receipt_path": receipt_path.as_posix(),
                       "raw_sha256": context["raw_sha256"], "reason": str(exc), "numeric_input_allowed": False}
            S.atomic_json(root / ROOT / "failures" / (C.canonical_hash(failure) + ".json"), _hash(failure), immutable=True)
            raise


def verify(root: Path, *, replay: bool = True) -> dict[str, Any]:
    """Reparse immutable HTML and replay every research archive, never official DBs."""
    root = Path(root)
    errors, snapshots = [], {}
    try:
        pointer = _latest(root)
        for path in sorted((root / ROOT / "raw").glob("*.bin")):
            if path.stem != hashlib.sha256(path.read_bytes()).hexdigest():
                raise C.TrendlinesError("research_original_raw_sha_mismatch")
        receipts = {}
        for path in sorted((root / ROOT / "receipts").glob("*.json")):
            receipt = _checked(path)
            asset = asset_definition(root, receipt["asset_id"])
            raw_path = ROOT / "raw" / (receipt["raw_sha256"] + ".bin")
            if receipt.get("raw_path") != raw_path.as_posix():
                raise C.TrendlinesError("research_raw_path_binding_invalid")
            raw = S.safe_path(root, receipt["raw_path"]).read_bytes()
            rebuilt = _receipt(raw, {"url": receipt["url"], "retrieved_at": receipt["fetched_at"],
                                    "sha256": receipt["raw_sha256"], "bytes": receipt["byte_count"],
                                    "http_status": receipt["http_status"]}, asset, receipt["fetched_at"])
            if receipt != rebuilt or path.name != receipt["receipt_id"] + ".json":
                raise C.TrendlinesError("research_receipt_binding_invalid")
            receipts[receipt["receipt_id"]] = receipt
        for path in sorted((root / ROOT / "snapshots").glob("*.json")):
            archive = _checked(path)
            sid = archive["snapshot_id"]
            identity = {key: item for key, item in archive.items() if key not in {"snapshot_id", "content_hash"}}
            asset = asset_definition(root, archive["asset_id"])
            if (sid != "research-snapshot-" + C.canonical_hash(identity) or path.name != sid + ".json"
                    or archive.get("contract_id") != "trendlines_research_snapshot_v1" or archive.get("schema_version") != 1
                    or archive.get("asset") != asset or archive.get("source_context") != CONTEXT
                    or archive.get("rights_status") != RIGHTS or archive.get("verified_source") is not False
                    or archive.get("official_forecast_write") is not False
                    or archive.get("publication_scope", "private_only") != "private_only"
                    or archive.get("source_policy") != research_source_policy(asset)
                    or archive.get("row_validation_policy") != _row_policy(
                        archive.get("row_validation_policy", {}).get("allow_rejected_rows"))):
                raise C.TrendlinesError("research_snapshot_identity_or_contract_invalid")
            receipt = receipts[archive["receipt_id"]]
            expected_receipt_path = ROOT / "receipts" / (receipt["receipt_id"] + ".json")
            if (archive["receipt_path"] != expected_receipt_path.as_posix()
                    or archive["receipt_sha256"] != hashlib.sha256(S.encode(receipt)).hexdigest()
                    or archive["raw_sha256"] != receipt["raw_sha256"] or receipt["asset_id"] != archive["asset_id"]):
                raise C.TrendlinesError("research_snapshot_receipt_binding_invalid")
            raw = S.safe_path(root, receipt["raw_path"]).read_bytes()
            bars, meta, gaps = _prepare(raw, receipt, asset, archive["capture_asof"], config=archive["config"],
                                        allow_rejected_rows=archive["row_validation_policy"]["allow_rejected_rows"])
            if bars != archive["bars"] or meta != archive["metadata"] or gaps != archive["gaps"]:
                raise C.TrendlinesError("research_snapshot_differs_from_original_html")
            if archive["engine_snapshot"].get("knowledge_cutoff") != archive["capture_asof"]:
                raise C.TrendlinesError("research_snapshot_cutoff_binding_invalid")
            checked = E.verify_research_asset_snapshot(archive["engine_snapshot"], bars, asset,
                                                      config=archive["config"], source_policy=archive["source_policy"], replay=replay)
            if checked["ok"] is not True:
                raise C.TrendlinesError("research_numeric_replay_failed: " + "; ".join(checked["errors"]))
            snapshots[sid] = archive
        for sid, archive in snapshots.items():
            prior = archive.get("supersedes_snapshot_id")
            if prior is not None and (prior not in snapshots or snapshots[prior]["asset_id"] != archive["asset_id"]
                                      or S.aware_time(snapshots[prior]["capture_asof"]) > S.aware_time(archive["capture_asof"])
                                      or S.aware_time(receipts[snapshots[prior]["receipt_id"]]["fetched_at"])
                                      > S.aware_time(receipts[archive["receipt_id"]]["fetched_at"])):
                raise C.TrendlinesError("research_snapshot_revision_binding_invalid")
        for asset_id, row in (pointer or {}).get("assets", {}).items():
            expected = ROOT / "snapshots" / (row["snapshot_id"] + ".json")
            if (row["snapshot_path"] != expected.as_posix() or row["snapshot_id"] not in snapshots
                    or snapshots[row["snapshot_id"]]["asset_id"] != asset_id
                    or row["snapshot_sha256"] != hashlib.sha256((root / expected).read_bytes()).hexdigest()):
                raise C.TrendlinesError("research_latest_snapshot_binding_invalid")
        for path in sorted((root / ROOT / "failures").glob("*.json")):
            failure = _checked(path)
            identity = {key: item for key, item in failure.items() if key != "content_hash"}
            receipt = receipts[failure["receipt_id"]]
            if (path.stem != C.canonical_hash(identity) or failure.get("numeric_input_allowed") is not False
                    or failure.get("schema_version") != 1
                    or failure.get("contract_id") != "trendlines_research_capture_failure_v1"
                    or not isinstance(failure.get("reason"), str) or not failure["reason"]
                    or failure.get("raw_sha256") != receipt["raw_sha256"]
                    or failure.get("receipt_path") != (ROOT / "receipts" / (receipt["receipt_id"] + ".json")).as_posix()):
                raise C.TrendlinesError("research_failure_receipt_binding_invalid")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(str(exc))
    return {"ok": not errors, "errors": errors, "snapshots": len(snapshots), "replay": replay}


def load_asset_detail(root: Path, asset_id: str, *, now: str | datetime | None = None) -> dict[str, Any] | None:
    """Fail closed on any corrupted research evidence; disclose qualification."""
    if asset_id not in C.ASSET_IDS:
        raise C.TrendlinesError("unregistered trendlines research asset")
    audit = verify(root, replay=True)
    if not audit["ok"]:
        return None
    return _load_verified_detail(Path(root), asset_id, now=now)


def _load_verified_detail(root: Path, asset_id: str, *, now=None) -> dict[str, Any] | None:
    row = (_latest(Path(root)) or {}).get("assets", {}).get(asset_id)
    if not row:
        return None
    archive = _checked(S.safe_path(Path(root), row["snapshot_path"]))
    if S.aware_time(archive["capture_asof"]) > S.aware_time(now):
        return None
    receipt = _checked(S.safe_path(Path(root), archive["receipt_path"]))
    detail = D.compact_snapshot(archive["engine_snapshot"])
    detail.update({"contract_id": "trendlines_research_display_v1", "status": "unverified_display",
                   "publication_class": "research_source", "verified_source": False, "source_context": CONTEXT,
                   "publication_scope": "private_only",
                   "rights_status": RIGHTS, "numbers_visible": True, "official_forecast_write": False,
                   "engine_snapshot_id": detail["snapshot_id"], "snapshot_id": archive["snapshot_id"],
                   "source_url": receipt["url"], "retrieved_at": receipt["fetched_at"],
                   "receipt_id": receipt["receipt_id"], "raw_sha256": receipt["raw_sha256"],
                   "research_archive_path": row["snapshot_path"], "research_archive_sha256": row["snapshot_sha256"],
                   "gaps": archive["gaps"], "audit_evidence": "immutable_research_html_receipts_and_replayed_archives",
                   "row_validation_policy": archive["row_validation_policy"],
                   "rejected_rows": [gap for gap in archive["gaps"] if gap["reason"] == "source_invalid_ohlc_no_fill"],
                   "limitations": ["uncertified_public_source_not_an_approved_price_feed",
                                    "current_capture_vintage_not_historical_publication_receipts",
                                    "displayed_ohlc_without_split_adjustment_vintage_guarantee",
                                    "missing_and_unfinished_candles_are_never_filled"]})
    quote = archive["metadata"].get("quote") or {}
    if quote.get("observed_at") and C._finite_number(quote.get("price")) and quote["price"] > 0:
        stamp = S.aware_time(quote["observed_at"])
        local = stamp.astimezone(ZoneInfo(archive["asset"]["timezone"]))
        sessions = C.session_schedule(archive["asset"]["calendar_id"], archive["bars"][0]["session_date"],
                                      local.date().isoformat())
        positions = {day: index for index, (day, _opened, _closed) in enumerate(sessions)}
        final = archive["bars"][-1]
        identical_final_close = (local.date().isoformat() == final["session_date"]
                                 and stamp >= S.aware_time(final["finalized_at"])
                                 and quote["price"] == final["close"])
        if not identical_final_close:
            detail["intraday_quote"] = {"date": local.date().isoformat(), "time": local.strftime("%H:%M:%S"),
                                        "observed_at": stamp.isoformat(), "price": quote["price"],
                                        "session_index": positions.get(local.date().isoformat()),
                                        "source_url": receipt["url"], "retrieved_at": receipt["fetched_at"],
                                        "status": "intraday_snapshot_not_final_close", "currency": quote["currency"]}
    return _hash(detail)


def attach_projection(root: Path, official_projection: dict[str, Any], *,
                      now: str | datetime | None = None, allow_private_research: bool = False) -> dict[str, Any]:
    """Attach reviewed research display while retaining the official HOLD state."""
    merged = deepcopy(official_projection)
    if allow_private_research is not True:
        return merged
    if verify(root, replay=True)["ok"] is not True:
        return merged
    for summary in merged.get("assets", []):
        if summary["status"] != "hold":
            continue
        detail = _load_verified_detail(Path(root), summary["asset_id"], now=now)
        if detail is None:
            continue
        official = merged["details"][summary["asset_id"]]
        detail["official_snapshot_status"] = official["status"]
        detail["official_snapshot_id"] = official.get("snapshot_id")
        detail = _hash(detail)
        summary.update({"official_snapshot_status": summary["status"], "official_snapshot_id": summary.get("snapshot_id"),
                        "status": "unverified_display", "snapshot_id": detail["snapshot_id"],
                        "content_hash": detail["content_hash"], "as_of": detail["as_of"],
                        "last_session": detail["observation_through"], "reason_codes": ["uncertified_research_source"],
                        "publication_class": "research_source", "verified_source": False,
                        "publication_scope": "private_only",
                        "numbers_visible": True, "source_context": CONTEXT, "rights_status": RIGHTS})
        merged["details"][summary["asset_id"]] = detail
    if any(row["status"] == "unverified_display" for row in merged.get("assets", [])):
        merged["status"] = "partial"
        clocks = [row["as_of"] for row in merged["assets"] if row.get("as_of")]
        if merged.get("generated_at"):
            clocks.append(merged["generated_at"])
        merged["generated_at"] = max(clocks, key=S.aware_time) if clocks else None
    return _hash(merged)


def export_private_import(root: Path, asset_id: str, now: str | datetime | None = None) -> dict[str, Any]:
    """An exact locally imported payload; no source prices are publicly exported.

    Hash the supplied UTF-8 JSON string before parsing it in the browser. This
    preserves Python's explicit floating point representation and avoids
    claiming that JSON.stringify is the Python canonical encoding.
    """
    detail = load_asset_detail(root, asset_id, now=now)
    if detail is None:
        raise C.TrendlinesError("private_research_import_requires_verified_evidence")
    if detail.get("publication_scope") != "private_only":
        raise C.TrendlinesError("private_research_import_scope_required")
    body = {key: item for key, item in detail.items() if key != "content_hash"}
    payload = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    encoded = payload.encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    if digest != detail["content_hash"]:
        raise C.TrendlinesError("private_research_payload_hash_binding_invalid")
    if len(encoded) > MAX_PRIVATE_PAYLOAD_BYTES:
        raise C.TrendlinesError("private_research_payload_exceeds_256KiB")
    envelope = {"schema_version": 1, "contract_id": "trendlines_private_import_v1",
                "publication_scope": "private_only", "asset_id": asset_id, "snapshot_id": detail["snapshot_id"],
                "payload_json": payload, "payload_sha256": digest}
    if len(S.encode(envelope)) > MAX_PRIVATE_ENVELOPE_BYTES:
        raise C.TrendlinesError("private_research_envelope_exceeds_512KiB")
    return envelope
