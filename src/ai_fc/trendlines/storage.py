"""Immutable market bars and receipts, without network or credential access."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

ROOT = Path("data/trendlines")
LEDGERS = ("raw_receipts", "bars", "snapshots", "events")
HASH_RE = re.compile(r"[0-9a-f]{64}")
SECRET_KEYS = {"api_key", "apikey", "api-key", "key", "token", "access_token", "accesstoken",
               "api_token", "secret", "client_secret", "password", "registrationkey", "user_id", "userid"}


class TrendlinesStorageError(ValueError):
    """A proposed append or a stored lineage cannot be trusted."""


def encode(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(encode(value)).hexdigest()


def aware_time(value: str | datetime | None = None) -> datetime:
    try:
        stamp = value or datetime.now(timezone.utc)
        parsed = stamp if isinstance(stamp, datetime) else datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except (TypeError, ValueError, AttributeError) as exc:
        raise TrendlinesStorageError("as_of must be an ISO-8601 timestamp with timezone") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TrendlinesStorageError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def safe_path(parent: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise TrendlinesStorageError("artifact path must be relative")
    target = (parent / relative).resolve()
    if parent.resolve() not in target.parents:
        raise TrendlinesStorageError("artifact path escapes its root")
    return target


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TrendlinesStorageError("invalid JSON artifact: " + path.name) from exc
    if not isinstance(value, dict):
        raise TrendlinesStorageError("JSON artifact must be an object: " + path.name)
    return value


def atomic_json(path: Path, value: dict[str, Any], *, immutable: bool = False) -> None:
    body = encode(value)
    if immutable and path.is_file():
        if path.read_bytes() != body:
            raise TrendlinesStorageError("immutable artifact collision: " + path.name)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix="." + path.name, suffix=".tmp", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(body)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        if immutable and path.is_file():
            if path.read_bytes() != body:
                raise TrendlinesStorageError("immutable artifact collision: " + path.name)
        else:
            os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def writer_lock(root: Path):
    """OS-backed serialization; a crash releases the lock without deleting history."""
    path = root / "outputs/trendlines/.writer.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise TrendlinesStorageError("another trendlines publisher owns the writer lock") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def read_chain(root: Path, name: str) -> list[dict[str, Any]]:
    if name not in LEDGERS:
        raise TrendlinesStorageError("unknown trendlines ledger")
    path = root / ROOT / "ledgers" / (name + ".jsonl")
    if not path.is_file():
        return []
    previous = None
    identities: set[str] = set()
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            row = json.loads(line)
            body = {key: value for key, value in row.items() if key != "chain_hash"}
            identity = row["record_id"]
            if (row["previous_hash"] != previous or row["chain_hash"] != digest(body)
                    or not HASH_RE.fullmatch(identity) or identity in identities):
                raise ValueError("invalid ledger identity or hash chain")
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise TrendlinesStorageError(f"{name} ledger rejected at line {number}") from exc
        previous = row["chain_hash"]
        identities.add(identity)
        rows.append(row)
    return rows


def append_chain(root: Path, name: str, records: list[dict[str, Any]]) -> bool:
    """Validate the complete pending segment before its single fsynced append."""
    existing = read_chain(root, name)
    known = {row["record_id"]: row["payload"] for row in existing}
    previous = existing[-1]["chain_hash"] if existing else None
    pending = []
    for record in records:
        identity, payload = record["record_id"], record["payload"]
        if not HASH_RE.fullmatch(identity):
            raise TrendlinesStorageError("record identity must be SHA256")
        if identity in known:
            if known[identity] != payload:
                raise TrendlinesStorageError("conflicting immutable ledger record")
            continue
        body = {"record_id": identity, "payload": payload, "previous_hash": previous}
        row = {**body, "chain_hash": digest(body)}
        previous = row["chain_hash"]
        pending.append(encode(row))
        known[identity] = payload
    if not pending:
        return False
    path = root / ROOT / "ledgers" / (name + ".jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write(b"".join(pending))
        handle.flush()
        os.fsync(handle.fileno())
    return True


def policy_rule(policy: dict[str, Any], asset: dict[str, Any]) -> dict[str, Any]:
    source_id = asset.get("source_id")
    rule = (policy.get("sources") or {}).get(source_id)
    if (asset.get("enabled") is not True or not isinstance(rule, dict)
            or rule.get("rights_status") != "approved_free"
            or any(rule.get(key) is not True for key in ("allow_collection", "allow_derived_display", "allow_ohlc"))
            or asset["asset_id"] not in (rule.get("asset_ids") or [])
            or asset.get("price_basis") not in (rule.get("allowed_price_bases") or [])
            or asset.get("calendar_id") not in (rule.get("calendar_ids") or [])
            or rule.get("parser_id") != "json_ohlc_v1"):
        raise TrendlinesStorageError("missing_approved_ohlc")
    return rule


def validate_source_uri(receipt: dict[str, Any], asset: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    rule = policy_rule(policy, asset)
    parsed = urlsplit(receipt["source_uri"])
    host = (parsed.hostname or "").lower()
    if (parsed.scheme != "https" or not host or parsed.username or parsed.password or parsed.fragment
            or {key.lower() for key, _ in parse_qsl(parsed.query)} & SECRET_KEYS
            or not any(host == domain or host.endswith("." + domain)
                       for domain in rule.get("allowed_domains") or [])):
        raise TrendlinesStorageError("receipt URI is not an approved secret-free source")
    if receipt.get("source_id") != asset["source_id"] or receipt.get("asset_id") != asset["asset_id"]:
        raise TrendlinesStorageError("receipt instrument/source mismatch")
    return rule


def validate_receipt(receipt: dict[str, Any], raw: bytes, asset: dict[str, Any],
                     policy: dict[str, Any], cutoff: str) -> dict[str, Any]:
    required = {"source_id", "asset_id", "source_uri", "http_status", "media_type", "parser_id",
                "raw_sha256", "byte_count", "fetched_at", "available_at"}
    if not required <= receipt.keys():
        raise TrendlinesStorageError("receipt metadata incomplete")
    rule = validate_source_uri(receipt, asset, policy)
    if (receipt["source_id"] != asset["source_id"] or receipt["asset_id"] != asset["asset_id"]
            or receipt["http_status"] != 200 or receipt["media_type"] != "application/json"
            or receipt["parser_id"] != rule["parser_id"]
            or receipt["byte_count"] != len(raw)
            or receipt["raw_sha256"] != hashlib.sha256(raw).hexdigest()):
        raise TrendlinesStorageError("receipt/source/raw binding mismatch")
    fetched = aware_time(receipt["fetched_at"])
    available = aware_time(receipt["available_at"])
    # This connector has captured vintages only. A publication date cannot be
    # invented to make a newly downloaded historical bar eligible in the past.
    if available != fetched or fetched > aware_time(cutoff):
        raise TrendlinesStorageError("receipt captured vintage is after cutoff or backdated")
    body = {key: receipt[key] for key in sorted(required)}
    body["raw_path"] = (ROOT / "raw" / (receipt["raw_sha256"] + ".json")).as_posix()
    identity = digest(body)
    if receipt.get("receipt_id") not in (None, identity):
        raise TrendlinesStorageError("receipt identity mismatch")
    return {**body, "receipt_id": identity}


def parse_raw(raw: bytes, asset: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        envelope = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise TrendlinesStorageError("raw JSON OHLC payload is invalid") from exc
    if not isinstance(envelope, dict):
        raise TrendlinesStorageError("raw JSON OHLC payload must be an object")
    for key in ("asset_id", "identity", "symbol", "source_id", "currency", "unit", "price_basis", "calendar_id"):
        if key not in envelope:
            raise TrendlinesStorageError("raw instrument metadata incomplete: " + key)
        if envelope.get(key) != asset.get(key):
            raise TrendlinesStorageError("raw asset definition mismatch: " + key)
    records = envelope.get("bars")
    if not isinstance(records, list) or not records:
        raise TrendlinesStorageError("raw OHLC bars must be a nonempty array")
    sessions = []
    for row in records:
        if (not isinstance(row, dict) or not {"session_date", "open", "high", "low", "close", "finalized_at"} <= row.keys()
                or any(isinstance(row[key], bool) or not isinstance(row[key], (int, float))
                       for key in ("open", "high", "low", "close"))):
            raise TrendlinesStorageError("raw bar requires explicit numeric OHLC and finalization")
        sessions.append(row["session_date"])
    if sessions != sorted(set(sessions)):
        raise TrendlinesStorageError("raw OHLC sessions must be sorted and unique")
    return records


def bar_identity(bar: dict[str, Any]) -> str:
    return digest({key: value for key, value in bar.items() if key not in {"bar_id", "session", "session_index"}})


def validate_bar_chain(bars: list[dict[str, Any]]) -> None:
    latest: dict[tuple[str, str, str], dict[str, Any]] = {}
    for bar in bars:
        if bar.get("bar_id") != bar_identity(bar):
            raise TrendlinesStorageError("bar content identity mismatch")
        key = (bar["asset_id"], bar["source_id"], bar["session_date"])
        prior = latest.get(key)
        if prior is None:
            if bar.get("revision_seq") != 1 or bar.get("supersedes_bar_id") is not None:
                raise TrendlinesStorageError("first bar revision must be one without supersedes")
        elif (bar.get("revision_seq") != prior["revision_seq"] + 1
              or bar.get("supersedes_bar_id") != prior["bar_id"]
              or aware_time(bar["available_at"]) < aware_time(prior["available_at"])):
            raise TrendlinesStorageError("bar revision must supersede the latest eligible revision")
        latest[key] = bar


def select_bars(bars: list[dict[str, Any]], asset: dict[str, Any], cutoff: str) -> list[dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    stamp = aware_time(cutoff)
    for bar in bars:
        if (bar["asset_id"] == asset["asset_id"] and bar["source_id"] == asset.get("source_id")
                and aware_time(bar["available_at"]) <= stamp and aware_time(bar["fetched_at"]) <= stamp):
            selected[bar["session_date"]] = bar
    return [selected[session] for session in sorted(selected)]
