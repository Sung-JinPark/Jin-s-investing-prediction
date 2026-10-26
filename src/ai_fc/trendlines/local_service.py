"""Read-only loopback delivery and scheduled personal research refresh.

HTTP never starts a refresh, executes a command, reads credentials, or serves
vendor originals. A separate, serialized worker runs the explicitly supplied
collector; the public dashboard continues to publish only approved-source data.
"""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
import threading
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import monotonic
from typing import Any, Callable
from urllib.parse import parse_qsl, unquote, urlsplit
from zoneinfo import ZoneInfo

from . import contracts as C, research as R, storage as S, delivery as D

HOST = "127.0.0.1"
PORT = 8878
TRUSTED_ORIGIN = "https://sung-jinpark.github.io"
ASSET_IDS = tuple(R.SYMBOLS)
KST = ZoneInfo("Asia/Seoul")
REFRESH_TIMES = (time(7, 17), time(9, 17), time(16, 17))
STATUS_BUDGET = 16 * 1024
STATIC_ROUTES = {"/": "index.html", "/index.html": "index.html", "/data.json": "data.json",
                 "/assets/trendlines.js": "assets/trendlines.js", "/assets/trendlines.css": "assets/trendlines.css",
                 **{f"/trendlines/{asset_id}.json": f"trendlines/{asset_id}.json" for asset_id in ASSET_IDS}}
_UNSELECTED = object()


class LocalServiceError(ValueError):
    """A local response or request cannot satisfy the private delivery contract."""


def _strict_json(value: bytes | str):
    def reject_constant(_value):
        raise LocalServiceError("nonfinite_json")
    try:
        return json.loads(value, parse_constant=reject_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise LocalServiceError("invalid_json") from exc


def _finite(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def validate_envelope(raw: bytes, asset_id: str, *, now: datetime) -> dict[str, Any]:
    """Check the exact import string, qualification, identity and visible OHLC."""
    if asset_id not in ASSET_IDS or not 0 < len(raw) <= R.MAX_PRIVATE_ENVELOPE_BYTES:
        raise LocalServiceError("invalid_private_envelope_size_or_asset")
    envelope = _strict_json(raw)
    if (not isinstance(envelope, dict) or type(envelope.get("schema_version")) is not int
            or (envelope["schema_version"], envelope.get("contract_id")) not in {
                (1, "trendlines_private_import_v1"), (2, "trendlines_private_import_v2")}
            or envelope.get("publication_scope") != "private_only" or envelope.get("asset_id") != asset_id
            or not isinstance(envelope.get("payload_json"), str)):
        raise LocalServiceError("invalid_private_envelope_contract")
    # V2 validates the packed wire SHA before expansion and separately checks
    # the original canonical display SHA. The server still returns raw bytes.
    detail = R.decode_private_import(envelope)
    if not isinstance(detail, dict) or "content_hash" in detail:
        raise LocalServiceError("invalid_private_detail")
    expected = {"asset_id": asset_id, "snapshot_id": envelope.get("snapshot_id"),
                "contract_id": "trendlines_research_display_v1", "status": "unverified_display",
                "publication_scope": "private_only", "publication_class": "research_source", "source_context": R.CONTEXT}
    if any(detail.get(key) != value for key, value in expected.items()):
        raise LocalServiceError("private_detail_identity_or_scope_mismatch")
    for key, prefix in (("snapshot_id", "research-snapshot-"), ("receipt_id", "research-receipt-")):
        if not isinstance(detail.get(key), str) or not re.fullmatch(prefix + "[a-f0-9]{64}", detail[key]):
            raise LocalServiceError("private_evidence_identity_invalid")
    if any(not isinstance(detail.get(key), str) or not C.SHA256.fullmatch(detail[key])
           for key in ("raw_sha256", "research_archive_sha256", "source_snapshot_hash")):
        raise LocalServiceError("private_evidence_hash_invalid")
    if (detail.get("verified_source") is not False or detail.get("official_forecast_write") is not False
            or detail.get("numbers_visible") is not True or detail.get("adjustment_verified") is not False
            or detail.get("historical_signals_available") is not False
            or detail.get("guards", {}).get("approved_free_ohlc") is not False):
        raise LocalServiceError("private_detail_cannot_claim_approval")
    asset = detail.get("asset")
    if not isinstance(asset, dict) or asset.get("asset_id") != asset_id:
        raise LocalServiceError("private_asset_identity_mismatch")
    C.validate_research_source(asset, R.research_source_policy(asset))
    if asset.get("verified_source") is not False or asset.get("rights_status") != R.RIGHTS:
        raise LocalServiceError("private_asset_cannot_claim_approval")
    url = urlsplit(detail.get("source_url", ""))
    if (url.scheme != "https" or url.hostname != "finance.yahoo.com" or url.username or url.password or url.fragment
            or url.port not in (None, 443) or unquote(url.path) != "/quote/" + asset["provider_symbol"] + "/history/"
            or any(key.lower() in S.SECRET_KEYS for key, _value in parse_qsl(url.query, keep_blank_values=True))):
        raise LocalServiceError("private_source_url_invalid")
    source = detail.get("source_identity") or {}
    if (source.get("source_id") != R.SOURCE or source.get("rights_status") != R.RIGHTS
            or source.get("price_basis") != asset["price_basis"] or source.get("provider_symbol") != asset["provider_symbol"]
            or source.get("calendar_id") != asset["calendar_id"] or source.get("verified_source") is not False):
        raise LocalServiceError("private_source_identity_mismatch")
    cutoff, fetched = C.aware_time(detail.get("as_of")), C.aware_time(detail.get("retrieved_at"))
    if cutoff != C.aware_time(detail.get("knowledge_cutoff")) or fetched > cutoff or cutoff > C.aware_time(now):
        raise LocalServiceError("private_capture_timestamp_invalid")
    bars = detail.get("bars")
    if not isinstance(bars, list) or not 2 <= len(bars) <= 756:
        raise LocalServiceError("private_candles_missing_or_excessive")
    previous = None
    for bar in bars:
        if not isinstance(bar, dict) or not all(_finite(bar.get(key)) and bar[key] > 0 for key in ("open", "high", "low", "close")):
            raise LocalServiceError("private_ohlc_invalid")
        if not bar["low"] <= min(bar["open"], bar["close"]) <= max(bar["open"], bar["close"]) <= bar["high"]:
            raise LocalServiceError("private_ohlc_containment_invalid")
        session, index = bar.get("session"), bar.get("session_index")
        if (not isinstance(session, str) or len(session) != 10 or type(index) is not int
                or previous is not None and (session <= previous[0] or index <= previous[1])):
            raise LocalServiceError("private_candle_order_invalid")
        try:
            if date.fromisoformat(session).isoformat() != session:
                raise ValueError("noncanonical date")
        except ValueError as exc:
            raise LocalServiceError("private_candle_date_invalid") from exc
        previous = session, index
    if detail.get("observation_through") != bars[-1]["session"]:
        raise LocalServiceError("private_observation_binding_invalid")
    return detail


def _atomic_bytes(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".local-", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class LocalTrendlinesService:
    """One scheduler, one worker, and fixed read-only personal cache responses."""

    def __init__(self, root: Path, *, refresh_asset: Callable[[str], dict],
                 build_preview: Callable[[], Any] | None = None, clock: Callable[[], datetime] | None = None,
                 assets: tuple[str, ...] = ASSET_IDS, startup_refresh: bool = True):
        self.root = Path(root).resolve()
        self.preview_root = self.root / "site"
        self.refresh_asset = refresh_asset
        self.build_preview = build_preview
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        if not assets or len(set(assets)) != len(assets) or any(asset_id not in ASSET_IDS for asset_id in assets):
            raise LocalServiceError("refresh_assets_must_be_exact_registered_instruments")
        if not isinstance(startup_refresh, bool):
            raise LocalServiceError("startup_refresh_requires_explicit_boolean")
        self.assets = tuple(assets)
        self.startup_refresh = startup_refresh
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._scheduler = None
        self._worker = None
        self._running = False
        self._startup_claimed = False
        self._claimed_slot = None
        self._pending = False
        self._preview_error = False
        self._assets = {asset_id: {"last_attempt": None, "last_success": None, "error": None, "full_error": None, "critical_error": None, "representative_error": None,
                                   "refreshing": False} for asset_id in ASSET_IDS}
        self._load_state()

    def _now(self):
        return C.aware_time(self.clock())

    def _path(self, relative: str) -> Path:
        if self.root.resolve() != self.root:
            raise LocalServiceError("private_root_redirected")
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise LocalServiceError("private_cache_path_redirected")
        return path

    def _load_state(self):
        try:
            raw = self._path("local-service-state.json").read_bytes()
            if len(raw) > STATUS_BUDGET:
                return
            state = _strict_json(raw)
            if state.get("contract_id") != "trendlines_local_worker_state_v1":
                return
            for asset_id in ASSET_IDS:
                row = state.get("assets", {}).get(asset_id, {})
                for key in ("last_attempt", "last_success"):
                    stamp = row.get(key)
                    if stamp is not None and C.aware_time(stamp) <= self._now():
                        self._assets[asset_id][key] = stamp
                if row.get("error") == "refresh_failed":
                    self._assets[asset_id]["error"] = "refresh_failed"
                if row.get("full_error") == "full_refresh_failed":
                    self._assets[asset_id]["full_error"] = "full_refresh_failed"
                if row.get("critical_error") == "critical_refresh_failed":
                    self._assets[asset_id]["critical_error"] = "critical_refresh_failed"
                if row.get("representative_error") == "representative_refresh_failed":
                    self._assets[asset_id]["representative_error"] = "representative_refresh_failed"
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return

    def _save_state(self):
        with self._lock:
            state = {"schema_version": 1, "contract_id": "trendlines_local_worker_state_v1",
                     "assets": {asset_id: {key: row[key] for key in ("last_attempt", "last_success", "error", "full_error", "critical_error", "representative_error")}
                                for asset_id, row in self._assets.items()}}
        raw = S.encode(state)
        if len(raw) > STATUS_BUDGET:
            raise LocalServiceError("local_state_budget_exceeded")
        _atomic_bytes(self._path("local-service-state.json"), raw)

    def read_asset_envelope(self, asset_id: str) -> bytes:
        return self._read_asset_detail(asset_id)[0]

    def read_full_manifest(self, asset_id: str) -> bytes:
        """Read a supplemental series pinned to the visible current capture."""
        from . import full_history as F
        selected = D.load_selected(self.root, asset_id, now=self._now())
        _raw, current = self._read_asset_detail(asset_id, selected=selected)
        envelope = D.read_envelope(self.root,selected,'full',now=self._now()) if selected else F.load_manifest(self.root, asset_id, now=self._now())
        if envelope is None:
            raise FileNotFoundError("private_full_history_missing")
        body = F.decode_envelope(envelope, expected_contract="trendlines_private_full_manifest_v1")
        if body.get("source_snapshot_id") != current["snapshot_id"] or body.get("as_of") != current["as_of"]:
            raise LocalServiceError("private_full_history_capture_mismatch")
        return S.encode(envelope)

    def read_full_chunk(self, asset_id: str, snapshot_id: str, chunk_index: int) -> bytes:
        """Immutable chunk reads never select another capture or start work."""
        from . import full_history as F
        envelope = F.load_chunk(self.root, asset_id, snapshot_id, chunk_index, now=self._now())
        body = F.decode_envelope(envelope, expected_contract="trendlines_private_full_bars_v1")
        if body.get("asset_id") != asset_id or body.get("snapshot_id") != snapshot_id or body.get("chunk_index") != chunk_index:
            raise LocalServiceError("private_full_history_chunk_mismatch")
        return S.encode(envelope)

    def read_critical_detail(self, asset_id: str) -> bytes:
        """Serve a verified selection without collecting or calculating on GET."""
        from . import critical as K, full_history as F
        selected = D.load_selected(self.root, asset_id, now=self._now())
        _raw, current = self._read_asset_detail(asset_id, selected=selected)
        envelope = D.read_envelope(self.root,selected,'critical',now=self._now()) if selected else K.load_detail(self.root, asset_id, now=self._now())
        if envelope is None:
            raise FileNotFoundError("private_critical_missing")
        body = K.decode_envelope(envelope)
        full_envelope = D.read_envelope(self.root,selected,'full',now=self._now()) if selected else F.load_manifest(self.root, asset_id, now=self._now())
        if full_envelope is None:
            raise FileNotFoundError("private_critical_full_source_missing")
        full = F.decode_envelope(full_envelope, expected_contract="trendlines_private_full_manifest_v1")
        if (body.get("asset_id") != asset_id or body.get("source_snapshot_id") != current["snapshot_id"]
                or body.get("source_full_snapshot_id") != full["snapshot_id"]
                or full.get("source_snapshot_id") != current["snapshot_id"]
                or body.get("as_of") != current["as_of"] or full.get("as_of") != current["as_of"]
                or body.get("source_engine_content_hash") != current["source_snapshot_hash"]
                or body.get("reference_session") != current["bars"][-1]["session"]
                or body.get("reference_index") != current["bars"][-1]["session_index"]
                or body.get("reference_close") != current["bars"][-1]["close"]):
            raise LocalServiceError("private_critical_capture_mismatch")
        return S.encode(envelope)

    def _read_asset_detail(self, asset_id: str, *, selected=_UNSELECTED) -> tuple[bytes, dict[str, Any]]:
        if asset_id not in ASSET_IDS:
            raise LocalServiceError("private_asset_not_registered")
        if selected is _UNSELECTED:
            selected = D.load_selected(self.root, asset_id, now=self._now())
        if selected is not None:
            raw = S.encode(selected['ohlc'])
        else:
            path = self._path(asset_id + ".trendlines.json")
            with path.open("rb") as handle:
                raw = handle.read(R.MAX_PRIVATE_ENVELOPE_BYTES + 1)
        detail = validate_envelope(raw, asset_id, now=self._now())
        return raw, detail

    def read_representative_detail(self, asset_id: str) -> bytes:
        """Deliver three frozen descriptive overlays pinned to the visible OHLC."""
        from . import representative as V, full_history as F
        selected = D.load_selected(self.root, asset_id, now=self._now())
        _raw, current = self._read_asset_detail(asset_id, selected=selected)
        envelope = D.read_envelope(self.root,selected,'representative',now=self._now()) if selected else V.load_detail(self.root, asset_id, now=self._now(), source_snapshot_id=current["snapshot_id"])
        if envelope is None:
            raise FileNotFoundError("private_representative_missing")
        body = V.decode_envelope(envelope)
        full_envelope = D.read_envelope(self.root,selected,'full',now=self._now()) if selected else F.load_manifest(self.root, asset_id, now=self._now())
        if full_envelope is None:
            raise FileNotFoundError("private_representative_full_source_missing")
        full = F.decode_envelope(full_envelope, expected_contract="trendlines_private_full_manifest_v1")
        if (body.get("asset_id") != asset_id or body.get("source_snapshot_id") != current["snapshot_id"]
                or body.get("source_full_snapshot_id") != full["snapshot_id"]
                or full.get("source_snapshot_id") != current["snapshot_id"]
                or body.get("as_of") != current["as_of"] or full.get("as_of") != current["as_of"]
                or body.get("source_engine_content_hash") != current["source_snapshot_hash"]
                or body.get("full_manifest_payload_sha256") != full_envelope["payload_sha256"]
                or body.get("reference_session") != current["observation_through"]
                or body.get("reference_index") != current["bars"][-1]["session_index"]
                or body.get("reference_close") != current["bars"][-1]["close"]):
            raise LocalServiceError("private_representative_capture_mismatch")
        if (body.get("source_archive_sha256") != current.get("research_archive_sha256")
                or body.get("source_engine_snapshot_id") != current.get("engine_snapshot_id")):
            raise LocalServiceError("private_representative_original_binding_mismatch")
        return S.encode(envelope)

    def read_long_boundaries_detail(self, asset_id: str) -> bytes:
        """Read only the separately verified supplement; never collect on GET."""
        from . import long_boundaries as B
        selected = D.load_selected(self.root, asset_id, now=self._now())
        _raw, current = self._read_asset_detail(asset_id, selected=selected)
        envelope = D.read_envelope(self.root,selected,'long_boundaries',now=self._now()) if selected else B.load_detail(self.root, asset_id, now=self._now(), source_snapshot_id=current["snapshot_id"])
        if envelope is None:
            raise FileNotFoundError("private_long_boundaries_missing")
        body = B.decode_envelope(envelope)
        if (body["asset_id"] != asset_id or body["source_snapshot_id"] != current["snapshot_id"]
                or body["as_of"] != current["as_of"] or body["reference_close"] != current["bars"][-1]["close"]
                or body["reference_session"] != current["observation_through"]
                or body["reference_index"] != current["bars"][-1]["session_index"]
                or body["source_archive_sha256"] != current.get("research_archive_sha256")
                or body["source_engine_snapshot_id"] != current.get("engine_snapshot_id")
                or body["source_engine_content_hash"] != current.get("source_snapshot_hash")):
            raise LocalServiceError("private_long_boundaries_capture_mismatch")
        return S.encode(envelope)

    def _slots(self, now):
        local = now.astimezone(KST)
        return [datetime.combine(local.date() + timedelta(days=offset), at, KST)
                for offset in (-1, 0, 1) for at in REFRESH_TIMES]

    def next_refresh(self):
        now = self._now()
        return min(slot for slot in self._slots(now) if slot > now).isoformat()

    def start(self, *, scheduler: bool = True):
        # Calendar construction must happen before a browser's short request
        # deadline. This is a read-only warmup, never a history replay/collect.
        self.status()
        with self._lock:
            if self._running:
                return
            if self._worker is not None and self._worker.is_alive():
                raise LocalServiceError("worker_still_stopping")
            self._stop.clear()
            self._running = True
            self._startup_claimed = False
            self._pending = False
            if not self.startup_refresh:
                now = self._now()
                self._startup_claimed = True
                self._claimed_slot = max(slot for slot in self._slots(now) if slot <= now)
        self.tick()
        if scheduler:
            self._scheduler = threading.Thread(target=self._schedule_loop, name="trendlines-local-scheduler", daemon=True)
            self._scheduler.start()

    def _schedule_loop(self):
        while not self._stop.wait(1):
            self.tick()

    def tick(self) -> bool:
        """Called by the autonomous scheduler; never by an HTTP handler."""
        now = self._now()
        latest_slot = max(slot for slot in self._slots(now) if slot <= now)
        with self._lock:
            if not self._running:
                return False
            due = not self._startup_claimed or self._claimed_slot is None or latest_slot > self._claimed_slot
            if not due:
                return False
            self._startup_claimed = True
            self._claimed_slot = latest_slot
            self._pending = True
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._work_loop, name="trendlines-local-worker", daemon=True)
                self._worker.start()
            return True

    def _work_loop(self):
        try:
            while not self._stop.is_set():
                with self._lock:
                    if not self._pending:
                        return
                    self._pending = False
                for asset_id in self._refresh_order():
                    if self._stop.is_set():
                        return
                    prior = None
                    try:
                        prior = self.read_asset_envelope(asset_id)
                    except (OSError, ValueError, TypeError, KeyError):
                        pass
                    with self._lock:
                        self._assets[asset_id].update({"last_attempt": self._now().isoformat(), "refreshing": True})
                    try:
                        report = self.refresh_asset(asset_id)
                        if (not isinstance(report, dict) or report.get("publication_scope") != "private_only"
                                or report.get("public_prices_published") is not False
                                or report.get("independent_replay", {}).get("ok") is not True):
                            raise LocalServiceError("refresh_report_not_verified_private")
                        if 'delivery_committed' in report and report['delivery_committed'] is not True:
                            raise LocalServiceError('refresh_did_not_commit_complete_chart')
                        scope = report["independent_replay"].get("replay_scope")
                        if scope is not None and (not isinstance(scope, dict) or scope.get("kind") != "asset"
                                or scope.get("asset_id") != asset_id
                                or report["independent_replay"].get("replay") is not True
                                or scope.get("store_integrity") != "all_originals_receipts_contracts_and_revision_links"):
                            raise LocalServiceError("refresh_report_replay_scope_mismatch")
                        self.read_asset_envelope(asset_id)
                        with self._lock:
                            self._assets[asset_id].update({"last_success": self._now().isoformat(), "error": None,
                                "full_error": "full_refresh_failed" if report.get("full_history", {}).get("status") == "unavailable" else None,
                                "critical_error": "critical_refresh_failed" if report.get("critical", {}).get("status") == "unavailable" else None,
                                "representative_error": "representative_refresh_failed" if report.get("representative", {}).get("status") == "unavailable" else None})
                    except Exception:
                        # Only this replaceable delivery file can be restored.
                        # Immutable source/archive history is never altered.
                        try:
                            path = self._path(asset_id + ".trendlines.json")
                            if prior is not None:
                                _atomic_bytes(path, prior)
                            else:
                                path.unlink(missing_ok=True)
                        except (OSError, ValueError):
                            pass
                        with self._lock:
                            self._assets[asset_id]["error"] = "refresh_failed"
                    finally:
                        with self._lock:
                            self._assets[asset_id]["refreshing"] = False
                        try:
                            self._save_state()
                        except (OSError, ValueError):
                            pass
                if self.build_preview is not None:
                    try:
                        self.build_preview()
                        self._preview_error = False
                    except Exception:
                        self._preview_error = True
        finally:
            with self._lock:
                self._worker = None
                if self._pending and self._running and not self._stop.is_set():
                    self._worker = threading.Thread(target=self._work_loop, name="trendlines-local-worker", daemon=True)
                    self._worker.start()

    def _refresh_order(self):
        """Recover stale assets first, oldest successful refresh first; stable ties."""
        rows = {row["asset_id"]: row for row in self.status()["assets"]}
        def rank(asset_id):
            row = rows[asset_id]
            success = C.aware_time(row["last_success"]).timestamp() if row["last_success"] else float("-inf")
            return (not row["stale"], success)
        return tuple(sorted(self.assets, key=rank))

    def stop(self, *, timeout: float = 5):
        deadline = monotonic() + min(5, max(0, timeout))
        self._stop.set()
        with self._lock:
            self._running = False
            self._pending = False
            threads = self._scheduler, self._worker
        for thread in threads:
            if thread is not None and thread is not threading.current_thread():
                thread.join(max(0, deadline - monotonic()))

    def wait_idle(self, timeout: float = 5) -> bool:
        deadline = monotonic() + max(0, timeout)
        while True:
            with self._lock:
                worker, pending = self._worker, self._pending
            if worker is None and not pending:
                return True
            remaining = deadline - monotonic()
            if remaining <= 0:
                return False
            if worker is not None:
                worker.join(remaining)
            else:
                self._stop.wait(min(.01, remaining))

    def status(self) -> dict[str, Any]:
        now, next_due = self._now(), self.next_refresh()
        with self._lock:
            state = deepcopy(self._assets)
            running, working = self._running, self._worker is not None
        rows = []
        for asset_id in ASSET_IDS:
            row = state[asset_id]
            detail = None
            failure = None
            try:
                _raw, detail = self._read_asset_detail(asset_id)
            except FileNotFoundError:
                failure = "private_capture_missing"
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                failure = "private_capture_invalid"
            stale = True
            if detail is not None:
                expected = C.latest_completed_session(detail["asset"], now,
                                                       buffer_minutes=C.default_config()["settlement_buffer_minutes"])
                stale = detail["observation_through"] != expected or row["error"] is not None
                failure = row["error"] or ("latest_completed_session_missing" if stale else None)
            status = "missing" if detail is None else "stale" if stale else "ready"
            if row["refreshing"]:
                status = "refreshing"
            rows.append({"asset_id": asset_id, "status": status, "last_success": row["last_success"],
                         "last_attempt": row["last_attempt"], "source_asof": detail.get("as_of") if detail else None,
                         "observation_through": detail.get("observation_through") if detail else None,
                         "stale": stale, "reason": failure, "error": row["error"], "full_error": row["full_error"],
                         "critical_error": row["critical_error"], "representative_error": row["representative_error"], "next_refresh_kst": next_due})
        rows.append({"asset_id": "mag7", "status": "hold", "last_success": None, "last_attempt": None,
                     "source_asof": None, "observation_through": None, "stale": False,
                     "reason": "source_instrument_unavailable", "error": None, "next_refresh_kst": next_due})
        body = {"schema_version": 1, "contract_id": "trendlines_local_status_v1", "publication_scope": "private_only",
                "running": running, "refresh_in_progress": working, "next_refresh_kst": next_due,
                "preview_error": self._preview_error, "assets": rows}
        if len(S.encode(body)) > STATUS_BUDGET:
            raise LocalServiceError("local_status_budget_exceeded")
        return body

    def static_response(self, route: str) -> tuple[bytes, str]:
        relative = STATIC_ROUTES.get(route)
        if relative is None:
            raise FileNotFoundError("static_route_not_registered")
        path = self._path("site/" + relative)
        if not path.is_relative_to(self.preview_root):
            raise LocalServiceError("private_preview_path_redirected")
        maximum = 8 * 1024 * 1024 if relative == "index.html" else 2 * 1024 * 1024
        with path.open("rb") as handle:
            raw = handle.read(maximum + 1)
        if len(raw) > maximum:
            raise LocalServiceError("private_preview_budget_exceeded")
        media = "text/html" if relative.endswith(".html") else "text/javascript" if relative.endswith(".js") else "text/css" if relative.endswith(".css") else "application/json"
        return raw, media


def make_http_server(service: LocalTrendlinesService, *, host: str = HOST, port: int = PORT):
    if host != HOST:
        raise LocalServiceError("local_service_must_bind_exact_loopback")

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, _format, *_args):
            pass

        def _allowed(self):
            hosts = self.headers.get_all("Host", [])
            origins = self.headers.get_all("Origin", [])
            if hosts != [self.server.expected_host] or len(origins) > 1 or self.client_address[0] != HOST:
                return False
            return not origins or origins[0] in (TRUSTED_ORIGIN, self.server.local_origin)

        def _reply(self, status, body: bytes, media="application/json"):
            try:
                self.send_response(status)
                self.send_header("Content-Type", media + "; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                origin = self.headers.get("Origin")
                if self._allowed() and origin in (TRUSTED_ORIGIN, self.server.local_origin):
                    self.send_header("Access-Control-Allow-Origin", origin)
                    self.send_header("Access-Control-Allow-Private-Network", "true")
                    self.send_header("Vary", "Origin")
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)
                return True
            except OSError:
                # The client may cancel at its deadline. Never write a second
                # error response into the disconnected socket.
                self.close_connection = True
                return False

        def _error(self, code):
            self._reply(code, S.encode({"error": "local_private_request_rejected"}))

        def _route(self):
            if not self.path.startswith("/") or "?" in self.path or "#" in self.path or "%" in self.path:
                return None
            if self.path in STATIC_ROUTES or self.path == "/api/private-trendlines/status":
                return self.path
            if self.path in {"/api/private-trendlines/" + asset_id for asset_id in ASSET_IDS}:
                return self.path
            if self.path in {"/api/private-trendlines/" + asset_id + "/critical" for asset_id in ASSET_IDS}:
                return self.path
            if self.path in {"/api/private-trendlines/" + asset_id + "/representative" for asset_id in ASSET_IDS}:
                return self.path
            if self.path in {"/api/private-trendlines/" + asset_id + "/long-boundaries" for asset_id in ASSET_IDS}:
                return self.path
            prefix = "/api/private-trendlines/(" + "|".join(ASSET_IDS) + ")/full"
            if re.fullmatch(prefix, self.path) or re.fullmatch(prefix + r"/research-full-snapshot-[a-f0-9]{64}/bars/(?:0|[1-7])", self.path):
                return self.path
            return None

        def do_GET(self):
            if not self._allowed():
                return self._error(403)
            route = self._route()
            if route is None:
                return self._error(404)
            try:
                if route == "/api/private-trendlines/status":
                    return self._reply(200, S.encode(service.status()))
                if route.endswith("/critical"):
                    return self._reply(200, service.read_critical_detail(route.split("/")[3]))
                if route.endswith("/representative"):
                    return self._reply(200, service.read_representative_detail(route.split("/")[3]))
                if route.endswith("/long-boundaries"):
                    return self._reply(200, service.read_long_boundaries_detail(route.split("/")[3]))
                if route.endswith("/full"):
                    return self._reply(200, service.read_full_manifest(route.split("/")[3]))
                if "/full/" in route:
                    parts = route.split("/")
                    return self._reply(200, service.read_full_chunk(parts[3], parts[5], int(parts[7])))
                if route.startswith("/api/private-trendlines/"):
                    return self._reply(200, service.read_asset_envelope(route.rsplit("/", 1)[-1]))
                raw, media = service.static_response(route)
                return self._reply(200, raw, media)
            except FileNotFoundError:
                return self._error(404)
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                return self._error(503)

        def do_OPTIONS(self):
            if (not self._allowed() or self._route() is None
                    or self.headers.get("Access-Control-Request-Method") != "GET"
                    or any(key.strip().lower() not in {"accept"} for key in
                           self.headers.get("Access-Control-Request-Headers", "").split(",") if key.strip())):
                return self._error(403)
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            origin = self.headers.get("Origin")
            if origin in (TRUSTED_ORIGIN, self.server.local_origin):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Private-Network", "true")
                self.send_header("Access-Control-Allow-Methods", "GET")
                self.send_header("Access-Control-Allow-Headers", "Accept")
                self.send_header("Vary", "Origin")
            self.end_headers()

        def do_POST(self):
            self.close_connection = True
            self._error(405)

        do_PUT = do_POST
        do_PATCH = do_POST
        do_DELETE = do_POST
        do_HEAD = do_POST

    server = ThreadingHTTPServer((HOST, port), Handler)
    server.daemon_threads = True
    server.expected_host = HOST + ":" + str(server.server_address[1])
    server.local_origin = "http://" + server.expected_host
    return server
