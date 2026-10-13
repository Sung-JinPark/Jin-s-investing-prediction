"""Captured-only trendline publication and deterministic archive replay."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from . import contracts as C, engine as E, storage as S

LATEST = S.ROOT / "latest.json"
CAPTURE_ID = "trendlines_capture_v1"


def _policies(root: Path):
    return C.load_contract(root), C.load_asset_registry(root), C.load_source_policy(root)


def _body_hash(value: dict[str, Any]) -> str:
    return S.digest({key: item for key, item in value.items() if key != "content_hash"})


def _semantic(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _semantic(item) for key, item in value.items()
                if key not in {"as_of", "knowledge_cutoff", "generated_at", "content_hash", "snapshot_id"}}
    if isinstance(value, list):
        return [_semantic(item) for item in value]
    return value


def _asset_summary(snapshot: dict[str, Any], asset: dict[str, Any], *, snapshot_id: str,
                   archive_path: str, archive_sha256: str, publication_status: str | None = None,
                   publication_reasons: list[str] | None = None) -> dict[str, Any]:
    return {"asset_id": asset["asset_id"], "label": asset["name"],
            "currency": asset["currency"], "price_unit": asset["unit"],
            "status": publication_status or snapshot["status"],
            "reason_codes": publication_reasons if publication_reasons is not None else (snapshot.get("reason_codes") or []),
            "snapshot_id": snapshot_id, "as_of": snapshot.get("as_of"),
            "last_session": snapshot.get("observation_through"),
            "content_hash": snapshot.get("content_hash") or S.digest(snapshot),
            "archive_path": archive_path, "archive_sha256": archive_sha256}


def latest(root: Path) -> dict[str, Any] | None:
    path = root / LATEST
    if not path.is_file():
        return None
    pointer = S.read_json(path)
    if (pointer.get("schema_version") != 1 or pointer.get("contract_id") != "trendlines_publication_v1"
            or pointer.get("content_hash") != _body_hash(pointer)):
        raise S.TrendlinesStorageError("trendlines latest pointer identity mismatch")
    return pointer


def _read_bundle(bundle: Path | dict[str, Any]) -> tuple[dict[str, Any], Path]:
    if isinstance(bundle, dict):
        base = Path(bundle.get("bundle_root", ".")).resolve()
        manifest = {key: value for key, value in bundle.items() if key not in {"bundle_root", "manifest_path"}}
    else:
        path = Path(bundle)
        path = path / "manifest.json" if path.is_dir() else path
        base, manifest = path.parent.resolve(), S.read_json(path)
    if (manifest.get("schema_version") != 1 or manifest.get("contract_id") != CAPTURE_ID
            or manifest.get("content_hash") != _body_hash(manifest)
            or not isinstance(manifest.get("assets"), list)
            or not isinstance(manifest.get("failures", []), list)):
        raise S.TrendlinesStorageError("capture manifest schema or hash mismatch")
    return manifest, base


def _entry(entry: dict[str, Any], base: Path, assets: dict[str, dict[str, Any]],
           policy: dict[str, Any], cutoff: str):
    asset_id = entry.get("asset_id")
    if asset_id not in assets:
        raise S.TrendlinesStorageError("capture contains an unregistered asset")
    asset = assets[asset_id]
    path = S.safe_path(base, entry["raw_path"])
    raw = path.read_bytes()
    receipt = S.validate_receipt(entry["receipt"], raw, asset, policy, cutoff)
    records = S.parse_raw(raw, asset)
    if entry.get("bars", records) != records:
        raise S.TrendlinesStorageError("capture OHLC arrays differ from exact raw bytes")
    return asset, receipt, records, raw


def _rejected_entry(root: Path, entry: dict[str, Any], base: Path, assets: dict[str, dict[str, Any]],
                    policy: dict[str, Any], cutoff: str, reason: str):
    """Only authorized, hash-bound, eligible source responses can enter quarantine."""
    try:
        asset = assets[entry["asset_id"]]
        if asset.get("enabled") is not True:
            return None
        C.validate_source(asset, policy)
        raw = S.safe_path(base, entry["raw_path"]).read_bytes()
        return S.prepare_rejection(root, raw=raw, receipt=entry["receipt"], asset=asset,
                                   policy=policy, cutoff=cutoff, reason=reason)
    except (OSError, ValueError, KeyError, TypeError):
        # Missing authorization, unsafe URI, bad receipt hashes and late capture
        # are audit reasons only; their bytes never become permanent source data.
        return None


def capture(root: Path, out: Path, as_of: str | datetime | None = None) -> dict[str, Any]:
    """Copy approved local connector bundles; this module never calls a market API."""
    _, assets, policy = _policies(root)
    stamp = S.aware_time(as_of).isoformat(timespec="seconds")
    out = Path(out)
    manifest_path = out if out.suffix == ".json" else out / "manifest.json"
    directory = manifest_path.parent
    entries, failures = [], []
    seen: set[str] = set()
    for inbox in sorted((root / S.ROOT / "inbox").glob("*.json")):
        manifest, base = _read_bundle(inbox)
        for entry in manifest["assets"]:
            asset_id = entry.get("asset_id")
            if asset_id in seen:
                raise S.TrendlinesStorageError("duplicate connector capture for an asset")
            seen.add(asset_id)
            preserved = {}
            try:
                if asset_id not in assets:
                    raise S.TrendlinesStorageError("capture contains an unregistered asset")
                S.validate_source_uri(entry["receipt"], assets[asset_id], policy)
                raw_first = S.safe_path(base, entry["raw_path"]).read_bytes()
                actual_hash = hashlib.sha256(raw_first).hexdigest()
                relative = Path("raw") / (actual_hash + ".json")
                target = directory / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.is_file() and target.read_bytes() != raw_first:
                    raise S.TrendlinesStorageError("capture raw artifact collision")
                if not target.exists():
                    with target.open("xb") as handle:
                        handle.write(raw_first)
                preserved = {"raw_sha256": actual_hash, "raw_path": relative.as_posix()}
                validated_receipt = S.validate_receipt(entry["receipt"], raw_first, assets[asset_id], policy, stamp)
                preserved.update({"receipt": validated_receipt, "source_policy": policy,
                                  "source_policy_hash": S.digest(policy), "asset_definition": assets[asset_id]})
                asset, receipt, records, raw = _entry(entry, base, assets, policy, stamp)
                # Only explicit finalized OHLC survives capture. The write boundary
                # repeats these gates using the publisher's current registry.
                for record in records:
                    bar = _normalized_bar(record, asset, receipt, None)
                    C.validate_bar(bar, asset, stamp, source_policy=policy)
                relative = Path("raw") / (receipt["raw_sha256"] + ".json")
                target = directory / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.is_file() and target.read_bytes() != raw:
                    raise S.TrendlinesStorageError("capture raw artifact collision")
                if not target.exists():
                    with target.open("xb") as handle:
                        handle.write(raw)
                entries.append({"asset_id": asset_id, "receipt": receipt,
                                "raw_path": relative.as_posix(), "bars": records})
            except (OSError, ValueError, KeyError, TypeError) as exc:
                failures.append({"asset_id": asset_id, "reason": str(exc), **preserved})
    body = {"schema_version": 1, "contract_id": CAPTURE_ID, "captured_at": stamp,
            "assets": entries, "failures": failures}
    manifest = {**body, "content_hash": S.digest(body)}
    S.atomic_json(manifest_path, manifest)
    return {**manifest, "manifest_path": str(manifest_path.resolve()), "bundle_root": str(directory.resolve())}


def _normalized_bar(record: dict[str, Any], asset: dict[str, Any],
                    receipt: dict[str, Any], prior: dict[str, Any] | None) -> dict[str, Any]:
    bar = {key: record[key] for key in ("session_date", "open", "high", "low", "close", "finalized_at")}
    if "volume" in record:
        bar["volume"] = record["volume"]
    bar.update({key: asset[key] for key in ("asset_id", "source_id", "currency", "unit", "price_basis", "calendar_id")})
    bar.update({"available_at": receipt["available_at"], "fetched_at": receipt["fetched_at"],
                "raw_sha256": receipt["raw_sha256"], "receipt_id": receipt["receipt_id"],
                "revision_seq": 1 if prior is None else prior["revision_seq"] + 1,
                "supersedes_bar_id": None if prior is None else prior["bar_id"]})
    return {**bar, "bar_id": S.bar_identity(bar)}


def _same_bar(prior: dict[str, Any], candidate: dict[str, Any]) -> bool:
    keys = ("asset_id", "source_id", "session_date", "currency", "unit", "price_basis",
            "calendar_id", "open", "high", "low", "close", "volume", "finalized_at")
    return all(prior.get(key) == candidate.get(key) for key in keys)


def _reuse_receipt(candidate: dict[str, Any], receipts: list[dict[str, Any]]) -> dict[str, Any]:
    ignored = {"receipt_id", "available_at", "fetched_at"}
    for receipt in receipts:
        if {key: value for key, value in receipt.items() if key not in ignored} == {
            key: value for key, value in candidate.items() if key not in ignored
        }:
            return receipt
    return candidate


def _archive(root: Path, summary: dict[str, Any]) -> dict[str, Any]:
    path = S.safe_path(root, summary["archive_path"])
    if S.ROOT / "archive" not in path.relative_to(root.resolve()).parents:
        raise S.TrendlinesStorageError("snapshot path is outside trendlines archive")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != summary["archive_sha256"]:
        raise S.TrendlinesStorageError("immutable snapshot bytes changed")
    envelope = S.read_json(path)
    if envelope.get("content_hash") != _body_hash(envelope) or envelope.get("snapshot_id") != summary["snapshot_id"]:
        raise S.TrendlinesStorageError("snapshot archive identity mismatch")
    return envelope


def verify(root: Path, replay: bool = True) -> dict[str, Any]:
    """Audit receipts, complete revision chains, every archive, and the public pointer."""
    errors = []
    asset_results = []
    try:
        _policies(root)
        chains = {name: S.read_chain(root, name) for name in S.LEDGERS}
        S.verify_rejections(root, chains["rejections"])
        receipts = {row["record_id"]: row["payload"] for row in chains["raw_receipts"]}
        raw_payloads = {}
        for receipt_id, receipt in receipts.items():
            if (receipt_id != receipt.get("receipt_id")
                    or receipt_id != S.digest({key: value for key, value in receipt.items() if key != "receipt_id"})
                    or receipt.get("raw_path") != (S.ROOT / "raw" / (receipt["raw_sha256"] + ".json")).as_posix()):
                raise S.TrendlinesStorageError("stored receipt identity mismatch")
            raw = S.safe_path(root, receipt["raw_path"]).read_bytes()
            if len(raw) != receipt["byte_count"] or hashlib.sha256(raw).hexdigest() != receipt["raw_sha256"]:
                raise S.TrendlinesStorageError("stored raw hash or length mismatch")
            raw_payloads[receipt_id] = raw
        bars = [row["payload"] for row in chains["bars"]]
        S.validate_bar_chain(bars)
        by_id = {bar["bar_id"]: bar for bar in bars}
        raw_records: dict[str, list[dict[str, Any]]] = {}
        for bar in bars:
            receipt = receipts.get(bar["receipt_id"])
            if receipt is None or receipt.get("receipt_id") != bar["receipt_id"]:
                raise S.TrendlinesStorageError("bar references a missing immutable receipt")
            if (receipt["raw_sha256"] != bar["raw_sha256"] or receipt["source_id"] != bar["source_id"]
                    or receipt["asset_id"] != bar["asset_id"] or receipt["fetched_at"] != bar["fetched_at"]
                    or receipt["available_at"] != bar["available_at"]):
                raise S.TrendlinesStorageError("stored bar/receipt lineage mismatch")
            if receipt["receipt_id"] not in raw_records:
                raw = raw_payloads[receipt["receipt_id"]]
                envelope = json.loads(raw)
                raw_records[receipt["receipt_id"]] = envelope["bars"]
            matching = [row for row in raw_records[receipt["receipt_id"]] if row["session_date"] == bar["session_date"]]
            if (len(matching) != 1 or any(matching[0].get(key) != bar.get(key)
                                         for key in ("open", "high", "low", "close", "volume", "finalized_at"))):
                raise S.TrendlinesStorageError("stored OHLC differs from immutable source bytes")
        known_snapshots = {}
        snapshot_event_bindings = {}
        latest_snapshot_by_asset = {}
        for row in chains["snapshots"]:
            record = row["payload"]
            envelope = _archive(root, record)
            if record["snapshot_id"] != row["record_id"]:
                raise S.TrendlinesStorageError("snapshot ledger identity mismatch")
            prior_id = latest_snapshot_by_asset.get(record["asset_id"])
            if envelope.get("supersedes_snapshot_id") != prior_id:
                raise S.TrendlinesStorageError("snapshot revision must supersede the preceding asset snapshot")
            latest_snapshot_by_asset[record["asset_id"]] = row["record_id"]
            if (record["status"] != envelope.get("publication_status", envelope["snapshot"]["status"])
                    or record["content_hash"] != envelope["snapshot"]["content_hash"]
                    or record["as_of"] != envelope["snapshot"].get("as_of")
                    or record["last_session"] != envelope["snapshot"].get("observation_through")):
                raise S.TrendlinesStorageError("snapshot publication metadata mismatch")
            inputs = [by_id[key] for key in envelope["bar_ids"]]
            context = envelope["build_context"]
            for bar in inputs:
                receipt = receipts[bar["receipt_id"]]
                S.validate_receipt(receipt, raw_payloads[bar["receipt_id"]], context["asset"],
                                   context["source_policy"], envelope["snapshot"]["as_of"])
                S.parse_raw(raw_payloads[bar["receipt_id"]], context["asset"])
            result = E.verify_asset_snapshot(envelope["snapshot"], inputs, context["asset"],
                                             config=context["config"], source_policy=context["source_policy"], replay=replay)
            if result.get("ok") is not True:
                raise S.TrendlinesStorageError("snapshot replay rejected: " + str(result.get("errors")))
            known_snapshots[row["record_id"]] = record
            snapshot_event_bindings[row["record_id"]] = {
                "asset_id": envelope["snapshot"]["asset_id"], "events": envelope["snapshot"].get("events", []),
            }
        pointer = latest(root)
        if pointer is not None:
            _, registry, _ = _policies(root)
            if {row["asset_id"] for row in pointer["assets"]} != set(registry):
                raise S.TrendlinesStorageError("publication must contain exactly seven registered assets")
            for name, expected in pointer["ledger_heads"].items():
                if name not in chains or (expected is not None and expected not in {row["chain_hash"] for row in chains[name]}):
                    raise S.TrendlinesStorageError("published ledger history was truncated or replaced")
            for summary in pointer["assets"]:
                record = known_snapshots.get(summary["snapshot_id"])
                if record is None or any(record.get(key) != summary.get(key) for key in (
                        "asset_id", "archive_path", "archive_sha256", "content_hash", "status", "as_of", "last_session")):
                    raise S.TrendlinesStorageError("published summary differs from registered snapshot")
                envelope = _archive(root, summary)
                asset_results.append({"asset_id": summary["asset_id"], "status": summary["status"], "ok": True})
        for row in chains["events"]:
            event_record = row["payload"]
            snapshot_binding = snapshot_event_bindings.get(event_record["snapshot_id"])
            if snapshot_binding is None:
                raise S.TrendlinesStorageError("event references an unknown snapshot")
            expected_id = S.digest({"asset_id": event_record["asset_id"], "event": event_record["event"]})
            if row["record_id"] != expected_id or event_record.get("event_id") != expected_id:
                raise S.TrendlinesStorageError("event content identity mismatch")
            if event_record["asset_id"] != snapshot_binding["asset_id"]:
                raise S.TrendlinesStorageError("event asset differs from its immutable snapshot")
            if event_record["event"] not in snapshot_binding["events"]:
                raise S.TrendlinesStorageError("event is not an independently replayed snapshot transition")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        errors.append(str(exc))
    return {"ok": not errors, "errors": errors, "assets": asset_results}


def refresh(root: Path, as_of: str | datetime | None = None,
            capture_bundle: Path | dict[str, Any] | None = None) -> dict[str, Any]:
    """Publish only current-policy, replayable OHLC; preserve every previous revision."""
    stamp = S.aware_time(as_of).isoformat(timespec="seconds")
    with S.writer_lock(root):
        audit = verify(root, replay=True)
        if audit["ok"] is not True:
            return {"changed": False, "publication_allowed": False, "status": "blocked",
                    "assets": audit["assets"], "errors": audit["errors"]}
        try:
            config, registry, policy = _policies(root)
            previous = latest(root)
            incoming, failures, prepared_rejections = [], {}, []
            if capture_bundle is not None:
                manifest, base = _read_bundle(capture_bundle)
                if S.aware_time(manifest["captured_at"]) > S.aware_time(stamp):
                    raise S.TrendlinesStorageError("capture is after publication cutoff")
                seen = set()
                for entry in manifest["assets"]:
                    if entry.get("asset_id") in seen:
                        raise S.TrendlinesStorageError("duplicate asset in capture manifest")
                    seen.add(entry.get("asset_id"))
                    try:
                        incoming.append(_entry(entry, base, registry, policy, stamp))
                    except (OSError, ValueError, KeyError, TypeError) as exc:
                        failures[entry.get("asset_id")] = str(exc)
                        rejected = _rejected_entry(root, entry, base, registry, policy, stamp, str(exc))
                        if rejected is not None:
                            prepared_rejections.append(rejected)
                for failure in manifest.get("failures", []):
                    failures[failure["asset_id"]] = failure["reason"]
                    rejected = _rejected_entry(root, failure, base, registry, policy, stamp, failure["reason"])
                    if rejected is not None:
                        prepared_rejections.append(rejected)
            if any(asset_id not in registry for asset_id in failures):
                raise S.TrendlinesStorageError("capture failure targets an unregistered asset")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return {"changed": False, "publication_allowed": False, "status": "blocked",
                    "assets": [], "errors": [str(exc)]}
        receipts = [row["payload"] for row in S.read_chain(root, "raw_receipts")]
        stored_bars = [row["payload"] for row in S.read_chain(root, "bars")]
        pending_receipts, pending_bars, raw_blobs = [], [], []
        for asset, candidate_receipt, records, raw in incoming:
            asset_id = asset["asset_id"]
            try:
                receipt = _reuse_receipt(candidate_receipt, receipts + pending_receipts)
                current = {(bar["asset_id"], bar["source_id"], bar["session_date"]): bar
                           for bar in stored_bars + pending_bars}
                candidates = []
                for record in records:
                    prior = current.get((asset_id, asset["source_id"], record["session_date"]))
                    bar = _normalized_bar(record, asset, receipt, prior)
                    C.validate_bar(bar, asset, stamp, source_policy=policy)
                    if prior is None or not _same_bar(prior, bar):
                        candidates.append(bar)
                S.validate_bar_chain(stored_bars + pending_bars + candidates)
                pending_bars.extend(candidates)
                if receipt not in receipts + pending_receipts:
                    pending_receipts.append(receipt)
                    raw_blobs.append((root / receipt["raw_path"], raw))
            except (ValueError, KeyError, TypeError) as exc:
                failures[asset_id] = str(exc)
                try:
                    C.validate_source(asset, policy)
                    prepared_rejections.append(S.prepare_rejection(root, raw=raw, receipt=candidate_receipt,
                                                                   asset=asset, policy=policy, cutoff=stamp, reason=str(exc)))
                except (ValueError, KeyError, TypeError):
                    pass
        all_bars = stored_bars + pending_bars
        old_summaries = {row["asset_id"]: row for row in (previous or {}).get("assets", [])}
        summaries, archives, snapshot_records, event_records = [], [], [], []
        known_events = {row["record_id"] for row in S.read_chain(root, "events")}
        known_snapshots = {row["record_id"]: row["payload"] for row in S.read_chain(root, "snapshots")}
        for asset_id, asset in registry.items():
            # The engine chooses the latest eligible revision itself and needs
            # its ancestors to independently verify every supersedes edge.
            bars = [bar for bar in all_bars if bar["asset_id"] == asset_id
                    and bar["source_id"] == asset.get("source_id")
                    and S.aware_time(bar["available_at"]) <= S.aware_time(stamp)
                    and S.aware_time(bar["fetched_at"]) <= S.aware_time(stamp)]
            previous_summary = old_summaries.get(asset_id)
            prior_envelope = _archive(root, previous_summary) if previous_summary else None
            try:
                build_asset = asset if asset_id not in failures else {**asset, "enabled": False, "hold_reason": "capture_rejected"}
                snapshot = E.build_asset_snapshot(build_asset, bars, stamp, config=config, source_policy=policy)
            except (ValueError, KeyError, TypeError) as exc:
                failures[asset_id] = str(exc)
                snapshot = E.build_asset_snapshot({**asset, "enabled": False, "hold_reason": "capture_rejected"}, [],
                                                  stamp, config=config, source_policy=policy)
            context = {"asset": asset, "config": config, "source_policy": policy}
            publication_status, publication_reasons = snapshot["status"], snapshot.get("reason_codes") or []
            stale_tail = snapshot["status"] == "hold" and "missing_latest_completed_session" in snapshot.get("reason_codes", [])
            if asset_id in failures or stale_tail:
                retain_prior = False
                if prior_envelope and prior_envelope["snapshot"]["status"] == "ready":
                    try:
                        S.policy_rule(policy, asset)
                        old_asset = prior_envelope["build_context"]["asset"]
                        retain_prior = all(old_asset.get(key) == asset.get(key) for key in (
                            "asset_id", "source_id", "currency", "unit", "calendar_id", "price_basis", "identity"))
                    except ValueError:
                        pass
                if retain_prior:
                    snapshot = prior_envelope["snapshot"]
                    context = prior_envelope["build_context"]
                    bars = [bar for bar in all_bars if bar["bar_id"] in prior_envelope["bar_ids"]]
                    publication_status, publication_reasons = "stale", [
                        "capture_rejected_last_good_preserved" if asset_id in failures else "latest_completed_session_missing"]
                else:
                    context = {"asset": {**asset, "enabled": False, "hold_reason": "capture_rejected"},
                               "config": config, "source_policy": policy}
                    snapshot = E.build_asset_snapshot(context["asset"], [], stamp, config=config, source_policy=policy)
                    bars = []
                    publication_status, publication_reasons = "hold", ["capture_rejected"]
            body = {"schema_version": 1, "snapshot": snapshot,
                    "bar_ids": [bar["bar_id"] for bar in bars] if snapshot["status"] == "ready" else [],
                    "build_context": context,
                    "publication_status": publication_status, "publication_reason_codes": publication_reasons}
            semantic_hash = S.digest(_semantic(body))
            if prior_envelope and S.digest(_semantic({key: prior_envelope[key] for key in body})) == semantic_hash:
                summaries.append(previous_summary)
                continue
            # Selecting a former result after a later revision is itself a new
            # assertion with an explicit supersedes edge, not a pointer rollback.
            identity = S.digest({"semantic_hash": semantic_hash,
                                 "supersedes_snapshot_id": previous_summary["snapshot_id"] if previous_summary else None})
            archive_path = (S.ROOT / "archive" / asset_id / (identity + ".json")).as_posix()
            archive_body = {**body, "snapshot_id": identity,
                            "supersedes_snapshot_id": previous_summary["snapshot_id"] if previous_summary else None}
            envelope = {**archive_body, "content_hash": S.digest(archive_body)}
            if identity in known_snapshots:
                existing = _archive(root, known_snapshots[identity])
                if _semantic(existing["snapshot"]) != _semantic(snapshot):
                    raise S.TrendlinesStorageError("snapshot semantic identity collision")
                summaries.append(known_snapshots[identity])
                continue
            path = root / archive_path
            if path.is_file():
                # Recover an intact orphan archive from a crash before its
                # journal append. Preserve its original issuance bytes/time.
                orphan = S.read_json(path)
                if (orphan.get("content_hash") != _body_hash(orphan)
                        or orphan.get("snapshot_id") != identity
                        or orphan.get("supersedes_snapshot_id") != archive_body["supersedes_snapshot_id"]
                        or S.digest(_semantic({key: orphan[key] for key in body})) != semantic_hash):
                    raise S.TrendlinesStorageError("unregistered immutable snapshot collision")
                envelope = orphan
                snapshot = orphan["snapshot"]
            summary = _asset_summary(snapshot, asset, snapshot_id=identity, archive_path=archive_path,
                                     archive_sha256=hashlib.sha256(S.encode(envelope)).hexdigest(),
                                     publication_status=publication_status, publication_reasons=publication_reasons)
            summaries.append(summary)
            archives.append((root / archive_path, envelope))
            snapshot_records.append({"record_id": identity, "payload": summary})
            for event in snapshot.get("events", []):
                event_id = S.digest({"asset_id": asset_id, "event": event})
                if event_id not in known_events:
                    known_events.add(event_id)
                    event_records.append({"record_id": event_id, "payload": {
                        "event_id": event_id, "asset_id": asset_id, "snapshot_id": identity, "event": event}})
        # Last reliable boundary: re-read policy and revalidate every proposed bar
        # and output immediately before any canonical append.
        current_config, current_registry, current_policy = _policies(root)
        if (current_config, current_registry, current_policy) != (config, registry, policy):
            raise S.TrendlinesStorageError("trendline contract changed before append")
        for bar in pending_bars:
            C.validate_bar(bar, registry[bar["asset_id"]], stamp, source_policy=policy)
        for _, envelope in archives:
            result = E.verify_asset_snapshot(envelope["snapshot"],
                                             [bar for bar in all_bars if bar["bar_id"] in envelope["bar_ids"]],
                                             envelope["build_context"]["asset"], config=envelope["build_context"]["config"],
                                             source_policy=envelope["build_context"]["source_policy"], replay=True)
            if result.get("ok") is not True:
                raise S.TrendlinesStorageError("candidate replay failed: " + str(result.get("errors")))
        for path, raw in raw_blobs:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.read_bytes() != raw:
                raise S.TrendlinesStorageError("immutable raw content collision")
            if not path.exists():
                with path.open("xb") as handle:
                    handle.write(raw)
        changed = S.persist_rejections(root, prepared_rejections)
        changed = S.append_chain(root, "raw_receipts", [{"record_id": row["receipt_id"], "payload": row} for row in pending_receipts]) or changed
        changed = S.append_chain(root, "bars", [{"record_id": row["bar_id"], "payload": row} for row in pending_bars]) or changed
        for path, envelope in archives:
            S.atomic_json(path, envelope, immutable=True)
        changed = S.append_chain(root, "snapshots", snapshot_records) or changed
        changed = S.append_chain(root, "events", event_records) or changed
        heads = {name: (rows[-1]["chain_hash"] if rows else None)
                 for name in S.LEDGERS for rows in [S.read_chain(root, name)]}
        status = "ready" if all(row["status"] == "ready" for row in summaries) else (
            "partial" if any(row["status"] in {"ready", "stale"} for row in summaries) else "hold")
        pointer_body = {"schema_version": 1, "contract_id": "trendlines_publication_v1",
                        "status": status, "assets": summaries, "ledger_heads": heads,
                        "contract_hash": S.digest(config), "registry_hash": S.digest(registry),
                        "source_policy_hash": S.digest(policy)}
        if previous and {key: value for key, value in previous.items() if key not in {"generated_at", "content_hash"}} == pointer_body:
            return {"changed": changed, "publication_allowed": True, "status": status,
                    "assets": deepcopy(summaries), "content_hash": previous["content_hash"], "capture_failures": failures}
        pointer_body["generated_at"] = stamp
        pointer = {**pointer_body, "content_hash": S.digest(pointer_body)}
        S.atomic_json(root / LATEST, pointer)
        return {"changed": True, "publication_allowed": True, "status": status,
                "assets": deepcopy(summaries), "content_hash": pointer["content_hash"], "capture_failures": failures}
