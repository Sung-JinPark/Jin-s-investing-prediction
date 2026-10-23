"""User-authorized public HTML research captures, separate from approved sources.

No network access, source approval, official append, missing-candle filling, or
historical availability claim is performed here. A current public vintage is
known only at its recorded capture time, including every retrospective anchor.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
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
           "sp500": "^GSPC", "bitcoin": "BTC-USD", "dow": "^DJI",
           "kospi": "^KS11", "samsung": "005930.KS", "nvidia": "NVDA", "micron": "MU"}
MAX_RAW_BYTES = 20 * 1024 * 1024
MAX_PRIVATE_PAYLOAD_BYTES = 256 * 1024
MAX_PRIVATE_ENVELOPE_BYTES = 512 * 1024
PRIVATE_BAR_COLUMNS = ("session", "session_index", "open", "high", "low", "close", "bar_id")
PRIVATE_BAR_ID_PREFIX = "research-bar-"
REJECTABLE_OHLC_ERRORS = {"OHLC must be finite positive numbers; close fallback forbidden", "OHLC containment violation"}
_ACTIVE_REPLAY_CACHE: ContextVar[VerifiedReplayCache | None] = ContextVar("private_verified_replay_cache", default=None)
_ACTIVE_REPLAY_ASSET: ContextVar[str | None] = ContextVar("private_replay_asset", default=None)


@contextmanager
def use_asset_replay_scope(asset_id: str):
    """Private refresh isolation: all evidence checks, this asset's arithmetic.

    The default audit outside this context still replays the entire store.
    Metadata-only checks never populate numerical replay proofs.
    """
    if asset_id not in SYMBOLS:
        raise C.TrendlinesError("private_replay_asset_not_registered")
    _check_replay_asset(asset_id)
    token = _ACTIVE_REPLAY_ASSET.set(asset_id)
    try:
        yield
    finally:
        _ACTIVE_REPLAY_ASSET.reset(token)


def _check_replay_asset(asset_id):
    scope = _ACTIVE_REPLAY_ASSET.get()
    if scope is not None and scope != asset_id:
        raise C.TrendlinesError("private_refresh_replay_asset_mismatch")


def _replay_includes(asset_id):
    return _ACTIVE_REPLAY_ASSET.get() in (None, asset_id)


def _scope_report(report):
    scope = _ACTIVE_REPLAY_ASSET.get()
    if scope is not None:
        return {**report, "replay_scope": {"kind": "asset", "asset_id": scope,
                "store_integrity": "all_originals_receipts_contracts_and_revision_links"}}
    return report


# Successful audits an entry may go unused before a full store may replace it.
# A worker refresh runs about 13 audits, so ten assets use every live entry
# within about 130; this leaves about 16 cycles for a slow or failing asset.
REPLAY_CACHE_IDLE_AUDITS = 2048


class VerifiedReplayCache:
    """Bounded, process-local proofs populated only by a successful full audit.

    There is no persisted proof, caller-supplied verified flag, or preloaded
    entry API. Scoped metadata proofs use a distinct namespace and can never
    satisfy a numerical replay. Each hit still requires fresh raw and receipt hashes,
    current identity checks, revision chains and latest bindings.

    A separate evidence memo holds the bindings decoded from archive bytes whose
    canonical form a successful audit checked. It is keyed by the SHA256 of the
    exact bytes read and hashed in each later audit, so changed bytes are decoded
    and checked again; it never stands in for hashing a file.

    Each store holds at most ``max_entries``. A full store does not evict by
    recency: every worker pass walks the whole store, and each asset's own
    proofs are used once per ten-asset cycle, so LRU dropped exactly the entries
    the next refresh needed. It keeps what it holds and replaces only an entry
    no successful audit has used in REPLAY_CACHE_IDLE_AUDITS audits; otherwise
    the new entry is not kept and is checked in full again next time.
    """

    __slots__ = ("__limit", "__entries", "__evidence", "__audits", "__shared", "__lock")

    def __init__(self, *, max_entries: int = 262144):
        if type(max_entries) is not int or not 1 <= max_entries <= 1048576:
            raise C.TrendlinesError("private_replay_cache_capacity_invalid")
        self.__limit = max_entries
        self.__entries = OrderedDict()
        self.__evidence = OrderedDict()
        self.__audits = 0
        self.__shared = {}
        self.__lock = threading.Lock()

    @property
    def max_entries(self) -> int:
        return self.__limit

    @property
    def entry_count(self) -> int:
        with self.__lock:
            return len(self.__entries)

    @property
    def evidence_count(self) -> int:
        with self.__lock:
            return len(self.__evidence)

    @staticmethod
    def _same(prior, functions) -> bool:
        return len(prior) == len(functions) and all(a is b for a, b in zip(prior, functions))

    def _contains(self, key, functions) -> bool:
        with self.__lock:
            prior = self.__entries.get(key)
            if prior is None or not self._same(prior[0], functions):
                return False
            prior[-1] = self.__audits
            self.__entries.move_to_end(key)
            return True

    def _recall(self, key, functions):
        with self.__lock:
            prior = self.__evidence.get(key)
            if prior is None or not self._same(prior[0], functions):
                return None
            prior[-1] = self.__audits
            self.__evidence.move_to_end(key)
            return deepcopy(prior[1])

    def _remember(self, keys, evidence=None) -> None:
        # Retain function objects as well as their IDs, so object-ID reuse cannot
        # revive a proof for a different validator after a monkeypatch or reload.
        with self.__lock:
            self.__audits += 1
            for key, functions in keys.items():
                # A full replay of the same bytes subsumes the metadata-only check.
                self.__entries.pop(("research_metadata", *key), None)
                if self.__room(self.__entries, key):
                    self.__entries[self.__compact(key)] = [functions, self.__audits]
                    self.__entries.move_to_end(key)
            for key, (functions, value) in (evidence or {}).items():
                if self.__room(self.__evidence, key):
                    self.__evidence[self.__compact(key)] = [functions, deepcopy(value), self.__audits]
                    self.__evidence.move_to_end(key)

    def __room(self, store, key) -> bool:
        if key in store or len(store) < self.__limit:
            return True
        oldest = next(iter(store))
        if store[oldest][-1] > self.__audits - REPLAY_CACHE_IDLE_AUDITS:
            return False
        del store[oldest]
        return True

    def __compact(self, key):
        # Keys repeat the tuple of checking-function IDs; hold one equal copy.
        if len(self.__shared) > 256:
            self.__shared.clear()
        return tuple(self.__shared.setdefault(part, part) if type(part) is tuple else part for part in key)


@contextmanager
def use_verified_replay_cache(cache: VerifiedReplayCache):
    """Opt a private refresh worker into this cache for its current context only."""
    if type(cache) is not VerifiedReplayCache:
        raise C.TrendlinesError("private_replay_cache_instance_required")
    token = _ACTIVE_REPLAY_CACHE.set(cache)
    try:
        yield
    finally:
        _ACTIVE_REPLAY_CACHE.reset(token)


def _replay_functions():
    from .research_html import parse_yahoo_history

    return (verify, _prepare, _replay_includes, _checked_bytes, _archive_identity, _archive_bindings,
            asset_definition, research_source_policy, _row_policy, E.verify_research_asset_snapshot, parse_yahoo_history,
            C.validate_bar, C.validate_config, C.validate_research_source, C.session_schedule,
            C.latest_completed_session, C._finite_number, C.canonical_hash)


def _source_replayed(root: Path, archive: dict[str, Any], archive_sha256: str) -> bool:
    """Whether this worker's successful audit already reparsed exactly this archive.

    The caller must have just hashed the archive, receipt and raw files to the
    digests used here. Outside an opted-in worker there is never a proof.
    """
    cache = _ACTIVE_REPLAY_CACHE.get()
    if cache is None:
        return False
    functions = _replay_functions()
    key = (str(Path(root).resolve()), archive["content_hash"], archive_sha256, archive["receipt_sha256"],
           archive["receipt_sha256"], archive["raw_sha256"], C.ENGINE_VERSION, tuple(id(f) for f in functions))
    return cache._contains(key, functions) or cache._contains(("research_metadata", *key), functions)


def _evidence_recall(root: Path, key, functions) -> dict[str, Any] | None:
    """Bindings from a successful audit, only while every file they name hashes the same.

    Each recalled file is read and hashed again now, and each instrument is
    compared with today's registry. Any difference returns None, so the caller
    repeats its complete check and reports that check's own error.
    """
    cache = _ACTIVE_REPLAY_CACHE.get()
    bound = cache._recall(key, functions) if cache is not None else None
    if bound is None:
        return None
    try:
        if any(hashlib.sha256(S.safe_path(Path(root), relative).read_bytes()).hexdigest() != digest
               for relative, digest in bound["files"].items()):
            return None
        if any(C.canonical_hash(asset_definition(root, asset_id)) != digest for asset_id, digest in bound["assets"].items()):
            return None
        if "contract" in bound and C.canonical_hash(C.load_contract(Path(root))) != bound["contract"]:
            return None
    except (OSError, ValueError):
        return None
    return bound


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


def _checked_bytes(data: bytes, name: str) -> dict[str, Any]:
    """_checked() of bytes already read once, so a hash and its decode agree."""
    try:
        value = json.loads(data.decode("utf-8"))
    except ValueError as exc:
        raise S.TrendlinesStorageError("invalid JSON artifact: " + name) from exc
    if not isinstance(value, dict):
        raise S.TrendlinesStorageError("JSON artifact must be an object: " + name)
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
    _check_replay_asset(asset_id)
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


def _archive_identity(archive: dict[str, Any], asset: dict[str, Any], name: str) -> None:
    identity = {key: item for key, item in archive.items() if key not in {"snapshot_id", "content_hash"}}
    if (archive["snapshot_id"] != "research-snapshot-" + C.canonical_hash(identity) or name != archive["snapshot_id"] + ".json"
            or archive.get("contract_id") != "trendlines_research_snapshot_v1" or archive.get("schema_version") != 1
            or archive.get("asset") != asset or archive.get("source_context") != CONTEXT
            or archive.get("rights_status") != RIGHTS or archive.get("verified_source") is not False
            or archive.get("official_forecast_write") is not False
            or archive.get("publication_scope", "private_only") != "private_only"
            or archive.get("source_policy") != research_source_policy(asset)
            or archive.get("row_validation_policy") != _row_policy(
                archive.get("row_validation_policy", {}).get("allow_rejected_rows"))):
        raise C.TrendlinesError("research_snapshot_identity_or_contract_invalid")
    if archive["engine_snapshot"].get("knowledge_cutoff") != archive["capture_asof"]:
        raise C.TrendlinesError("research_snapshot_cutoff_binding_invalid")


def _archive_bindings(archive: dict[str, Any]) -> dict[str, Any]:
    """The fields later cross-checks read, plus the identity they were checked against."""
    return {**{key: archive[key] for key in ("snapshot_id", "asset_id", "receipt_id", "receipt_path", "receipt_sha256",
                                             "raw_sha256", "capture_asof", "content_hash")},
            "supersedes_snapshot_id": archive.get("supersedes_snapshot_id"),
            "asset_sha256": C.canonical_hash(archive["asset"])}


def verify(root: Path, *, replay: bool = True) -> dict[str, Any]:
    """Reparse immutable HTML and replay every research archive, never official DBs."""
    root = Path(root)
    resolved = str(root.resolve())
    errors, snapshots = [], {}
    cache = _ACTIVE_REPLAY_CACHE.get() if replay is True else None
    pending, decoded = OrderedDict(), OrderedDict()
    functions = _replay_functions() if cache is not None else ()
    try:
        pointer = _latest(root)
        for path in sorted((root / ROOT / "raw").glob("*.bin")):
            if path.stem != hashlib.sha256(path.read_bytes()).hexdigest():
                raise C.TrendlinesError("research_original_raw_sha_mismatch")
        receipts, receipt_file_hashes = {}, {}
        for path in sorted((root / ROOT / "receipts").glob("*.json")):
            data = path.read_bytes()
            receipt = _checked_bytes(data, path.name)
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
            if cache is not None:
                receipt_file_hashes[receipt["receipt_id"]] = hashlib.sha256(data).hexdigest()
        for path in sorted((root / ROOT / "snapshots").glob("*.json")):
            data = path.read_bytes()
            file_sha = hashlib.sha256(data).hexdigest()
            evidence_key = ("research_archive", resolved, file_sha, CONTEXT, RIGHTS,
                            tuple(id(function) for function in functions)) if cache is not None else None
            bindings = cache._recall(evidence_key, functions) if cache is not None else None
            archive = None
            if bindings is None:
                archive = _checked_bytes(data, path.name)
                asset = asset_definition(root, archive["asset_id"])
                _archive_identity(archive, asset, path.name)
                bindings = _archive_bindings(archive)
                if cache is not None:
                    decoded[evidence_key] = (functions, bindings)
            else:
                # Identical bytes passed the canonical checks above in a successful
                # audit; the registry and file name are still today's.
                asset = asset_definition(root, bindings["asset_id"])
                if C.canonical_hash(asset) != bindings["asset_sha256"] or path.name != bindings["snapshot_id"] + ".json":
                    raise C.TrendlinesError("research_snapshot_identity_or_contract_invalid")
            sid = bindings["snapshot_id"]
            receipt = receipts[bindings["receipt_id"]]
            expected_receipt_path = ROOT / "receipts" / (receipt["receipt_id"] + ".json")
            if (bindings["receipt_path"] != expected_receipt_path.as_posix()
                    or bindings["receipt_sha256"] != hashlib.sha256(S.encode(receipt)).hexdigest()
                    or bindings["raw_sha256"] != receipt["raw_sha256"] or receipt["asset_id"] != bindings["asset_id"]):
                raise C.TrendlinesError("research_snapshot_receipt_binding_invalid")
            # The receipt loop above hashed this original during this audit.
            key = (resolved, bindings["content_hash"], file_sha,
                   bindings["receipt_sha256"], receipt_file_hashes[bindings["receipt_id"]], receipt["raw_sha256"], C.ENGINE_VERSION,
                   tuple(id(function) for function in functions)) if cache is not None else None
            numeric_replay = replay and _replay_includes(bindings["asset_id"])
            metadata_key = (("research_metadata", *key) if cache is not None and not numeric_replay
                            and _ACTIVE_REPLAY_ASSET.get() is not None else None)
            full_hit = cache is not None and cache._contains(key, functions)
            metadata_hit = metadata_key is not None and cache._contains(metadata_key, functions)
            if not full_hit and not metadata_hit:
                raw = S.safe_path(root, receipt["raw_path"]).read_bytes()
                if hashlib.sha256(raw).hexdigest() != receipt["raw_sha256"]:
                    raise C.TrendlinesError("research_original_raw_sha_mismatch")
                archive = archive or _checked_bytes(data, path.name)
                bars, meta, gaps = _prepare(raw, receipt, asset, archive["capture_asof"], config=archive["config"],
                                            allow_rejected_rows=archive["row_validation_policy"]["allow_rejected_rows"])
                if bars != archive["bars"] or meta != archive["metadata"] or gaps != archive["gaps"]:
                    raise C.TrendlinesError("research_snapshot_differs_from_original_html")
                checked = E.verify_research_asset_snapshot(archive["engine_snapshot"], bars, asset,
                                                          config=archive["config"], source_policy=archive["source_policy"], replay=numeric_replay)
                if checked["ok"] is not True:
                    raise C.TrendlinesError("research_numeric_replay_failed: " + "; ".join(checked["errors"]))
                if cache is not None and (numeric_replay or metadata_key is not None):
                    pending[key if numeric_replay else metadata_key] = functions
                    while len(pending) > cache.max_entries:
                        pending.popitem(last=False)
            # All hashes, originals and numerical checks above still run. Only the
            # small bindings are kept after this archive is checked; retaining
            # every OHLC/candidate graph exhausts long-running workers.
            snapshots[sid] = bindings
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
    if not errors and cache is not None:
        cache._remember(pending, decoded)
    return _scope_report({"ok": not errors, "errors": errors, "snapshots": len(snapshots), "replay": replay})


def load_asset_detail(root: Path, asset_id: str, *, now: str | datetime | None = None) -> dict[str, Any] | None:
    """Fail closed on any corrupted research evidence; disclose qualification."""
    _check_replay_asset(asset_id)
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
    current = S.aware_time(now)
    if S.aware_time(archive["capture_asof"]) > current:
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
    # Freshness describes this read, not the frozen geometry's issuance time.
    # Reusing a capture must not leave yesterday's missing close marked fresh.
    calendar_asset = deepcopy(archive["asset"])
    source = archive["source_policy"]["sources"][calendar_asset["source_id"]]
    calendar_asset["publication_lag_minutes"] = C.publication_lag(calendar_asset, source)
    expected = C.latest_completed_session(calendar_asset, current,
                                         buffer_minutes=archive["config"]["settlement_buffer_minutes"])
    quality = deepcopy(detail["quality"])
    missing = set(quality["missing_session_dates"])
    if expected is not None and expected >= detail["observation_through"]:
        missing.update(day for day, _opened, _closed in C.session_schedule(
            calendar_asset["calendar_id"], detail["observation_through"], expected)
                       if day > detail["observation_through"])
    stale = detail["observation_through"] != expected
    other_reasons = [reason for reason in quality["reasons"]
                     if reason not in {"missing_latest_completed_session", "missing_completed_sessions"}]
    quality.update({"expected_completed_session": expected, "stale": stale,
                    "missing_session_dates": sorted(missing),
                    "reasons": (["missing_latest_completed_session"] if stale else [])
                               + (["missing_completed_sessions"] if missing else []) + other_reasons})
    detail["quality"] = quality
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


def decode_private_import(envelope: dict[str, Any]) -> dict[str, Any]:
    """Verify the exact wire bytes and losslessly restore a V1 or V2 body.

    This is a transport check, not source approval or an archive replay. Callers
    retain their identity, source qualification, OHLC and point-in-time gates.
    The returned body excludes its hash, just as the original V1 payload did.
    """
    try:
        version = envelope.get("schema_version") if isinstance(envelope, dict) else None
        if (type(version) is not int or version not in (1, 2)
                or envelope.get("contract_id") != f"trendlines_private_import_v{version}"
                or envelope.get("publication_scope") != "private_only"
                or envelope.get("asset_id") not in SYMBOLS
                or not isinstance(envelope.get("payload_json"), str)):
            raise C.TrendlinesError("private_research_envelope_contract_invalid")
        if len(S.encode(envelope)) > MAX_PRIVATE_ENVELOPE_BYTES:
            raise C.TrendlinesError("private_research_envelope_exceeds_512KiB")
        encoded = envelope["payload_json"].encode("utf-8")
        if not 0 < len(encoded) <= MAX_PRIVATE_PAYLOAD_BYTES:
            raise C.TrendlinesError("private_research_payload_exceeds_256KiB")
        if hashlib.sha256(encoded).hexdigest() != envelope.get("payload_sha256"):
            raise C.TrendlinesError("private_research_payload_hash_binding_invalid")

        def reject_constant(_value):
            raise C.TrendlinesError("private_research_nonfinite_json")

        def unique_object(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise C.TrendlinesError("private_research_duplicate_json_key")
                value[key] = item
            return value

        body = json.loads(encoded, parse_constant=reject_constant, object_pairs_hook=unique_object)
        if (not isinstance(body, dict) or "content_hash" in body
                or body.get("asset_id") != envelope["asset_id"]
                or body.get("snapshot_id") != envelope.get("snapshot_id")):
            raise C.TrendlinesError("private_research_detail_binding_invalid")
        if version == 1:
            if "bars_packed" in body or "original_detail_sha256" in body or "original_detail_sha256" in envelope:
                raise C.TrendlinesError("private_research_v1_packed_fields_forbidden")
            original_hash = envelope["payload_sha256"]
        else:
            original_hash = envelope.get("original_detail_sha256")
            if (not isinstance(original_hash, str) or not C.SHA256.fullmatch(original_hash)
                    or body.get("original_detail_sha256") != original_hash or "bars" in body):
                raise C.TrendlinesError("private_research_original_detail_hash_binding_invalid")
            packed = body.get("bars_packed")
            if (not isinstance(packed, dict)
                    or set(packed) not in ({"columns", "rows"}, {"columns", "rows", "bar_id_prefix"})
                    or packed.get("columns") != list(PRIVATE_BAR_COLUMNS)
                    or not isinstance(packed.get("rows"), list) or not 2 <= len(packed["rows"]) <= 756
                    or any(not isinstance(row, list) or len(row) != len(PRIVATE_BAR_COLUMNS)
                           for row in packed["rows"])):
                raise C.TrendlinesError("private_research_packed_bars_contract_invalid")
            has_prefix = "bar_id_prefix" in packed
            if has_prefix and (packed["bar_id_prefix"] != PRIVATE_BAR_ID_PREFIX
                               or any(not isinstance(row[-1], str) or not C.SHA256.fullmatch(row[-1])
                                      for row in packed["rows"])):
                raise C.TrendlinesError("private_research_packed_bar_identity_invalid")
            body = {key: item for key, item in body.items()
                    if key not in {"bars_packed", "original_detail_sha256"}}
            body["bars"] = [dict(zip(PRIVATE_BAR_COLUMNS, row)) for row in packed["rows"]]
            if has_prefix:
                for bar in body["bars"]:
                    bar["bar_id"] = PRIVATE_BAR_ID_PREFIX + bar["bar_id"]
        if C.canonical_hash(body) != original_hash:
            raise C.TrendlinesError("private_research_original_detail_hash_binding_invalid")
        return body
    except C.TrendlinesError:
        raise
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
        raise C.TrendlinesError("private_research_import_json_invalid") from exc


def export_private_import(root: Path, asset_id: str, now: str | datetime | None = None) -> dict[str, Any]:
    """An exact locally imported payload; no source prices are publicly exported.

    Hash the supplied UTF-8 JSON string before parsing it in the browser. This
    preserves Python's explicit floating point representation and avoids
    claiming that JSON.stringify is the Python canonical encoding.
    """
    _check_replay_asset(asset_id)
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
    envelope = {"schema_version": 1, "contract_id": "trendlines_private_import_v1",
                "publication_scope": "private_only", "asset_id": asset_id, "snapshot_id": detail["snapshot_id"],
                "payload_json": payload, "payload_sha256": digest}
    if len(encoded) > MAX_PRIVATE_PAYLOAD_BYTES:
        bars = body.get("bars")
        if (not isinstance(bars, list) or not 2 <= len(bars) <= 756
                or any(not isinstance(bar, dict) or set(bar) != set(PRIVATE_BAR_COLUMNS) for bar in bars)
                or "bars_packed" in body or "original_detail_sha256" in body):
            raise C.TrendlinesError("private_research_packed_bars_contract_invalid")
        if any(not isinstance(bar["bar_id"], str) or not bar["bar_id"].startswith(PRIVATE_BAR_ID_PREFIX)
               or not C.SHA256.fullmatch(bar["bar_id"][len(PRIVATE_BAR_ID_PREFIX):]) for bar in bars):
            raise C.TrendlinesError("private_research_packed_bar_identity_invalid")
        packed_body = {key: item for key, item in body.items() if key != "bars"}
        packed_body.update({"original_detail_sha256": digest,
                            "bars_packed": {"columns": list(PRIVATE_BAR_COLUMNS),
                                            "bar_id_prefix": PRIVATE_BAR_ID_PREFIX,
                                            "rows": [[bar[key] for key in PRIVATE_BAR_COLUMNS[:-1]]
                                                     + [bar["bar_id"][len(PRIVATE_BAR_ID_PREFIX):]] for bar in bars]}})
        packed_payload = json.dumps(packed_body, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False)
        packed_bytes = packed_payload.encode("utf-8")
        if len(packed_bytes) > MAX_PRIVATE_PAYLOAD_BYTES:
            raise C.TrendlinesError("private_research_payload_exceeds_256KiB")
        envelope.update({"schema_version": 2, "contract_id": "trendlines_private_import_v2",
                         "original_detail_sha256": digest, "payload_json": packed_payload,
                         "payload_sha256": hashlib.sha256(packed_bytes).hexdigest()})
    if len(S.encode(envelope)) > MAX_PRIVATE_ENVELOPE_BYTES:
        raise C.TrendlinesError("private_research_envelope_exceeds_512KiB")
    return envelope
