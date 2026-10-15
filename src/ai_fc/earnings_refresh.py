"""Immutable public earnings capture and replay into the display-only ledger."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlsplit
from zoneinfo import ZoneInfo

from . import event_consensus as E
from .event_calendar import load_events

RAW_RELATIVE = Path("data/calendar/earnings_raw")
SCHEMA_VERSION = 1
CONTRACT_ID = "earnings_capture_v1"
MAX_REPORT_BYTES = 16384
_AUTH = {"api_key", "apikey", "token", "access_token", "authorization", "key", "signature"}
NASDAQ_SOURCE_IDS = {"issuer_ir", "nvidia_ir", "micron_ir", "asml_ir", "tsmc_ir"}
MAX_TEXT_BYTES = 8_000_000
TEXT_HEADERS = {"User-Agent": E.USER_AGENT, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8", "Accept-Encoding": "identity"}


class EarningsRefreshError(E.ConsensusError):
    """Capture/replay failed a source, temporal, or append-only boundary."""


def _time(value: Any = None) -> datetime:
    return E._aware(datetime.now(timezone.utc) if value is None else value)


def _bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _event(event: dict[str, Any]) -> dict[str, Any]:
    result = {k: event.get(k, "") for k in ("event_id", "kind", "date", "time_et", "status", "ticker", "title", "source_id", "source_url", "available_at", "registered_at")}
    target = E.expected_period(event)
    if target:
        result.update(fiscal_year=target.year, fiscal_quarter=(target.month - 1) // 3 + 1, period_end=target.isoformat())
    result["scheduled_at"] = datetime.fromisoformat(f"{event['date']}T{event.get('time_et') or '00:00'}").replace(tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc).isoformat()
    return result


def _nearby_events(root: Path, now: datetime) -> list[dict[str, Any]]:
    selected = []
    for raw in load_events(root):
        if raw.get("kind") != "earnings" or not raw.get("ticker"):
            continue
        event = _event(raw)
        if any(event.get(k) and _time(event[k]) > now for k in ("available_at", "registered_at")):
            continue
        scheduled = _time(event["scheduled_at"])
        before, after = (timedelta(days=1), timedelta(days=3)) if event["status"] == "confirmed" else (timedelta(days=7), timedelta(days=7))
        if scheduled - before <= now <= scheduled + after:
            selected.append(event)
    return selected


def _supported(event: dict[str, Any]) -> bool:
    return event["source_id"] in NASDAQ_SOURCE_IDS and bool(re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", event["ticker"]))


def _events(root: Path, now: datetime) -> list[dict[str, Any]]:
    return [event for event in _nearby_events(root, now) if _supported(event)]


def _unsupported(root: Path, now: datetime) -> list[dict[str, Any]]:
    return [{"event_id": event["event_id"], "ticker": event["ticker"], "reason": "no_registered_keyless_earnings_adapter"}
            for event in _nearby_events(root, now) if not _supported(event)]


def _url(event: dict[str, Any], kind: str, url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.port not in (None, 443) or parts.username or parts.password or parts.fragment or any(k.lower() in _AUTH for k, _ in parse_qsl(parts.query)):
        raise EarningsRefreshError("earnings source URL must be public HTTPS without credentials")
    if kind == "nasdaq":
        if url not in {E.EPS_SURPRISE_URL.format(ticker=event["ticker"]), E.EPS_FORECAST_URL.format(ticker=event["ticker"])}:
            raise EarningsRefreshError("unregistered Nasdaq earnings endpoint")
    else:
        allowed = {"ASML": {"investor.asml.com", "www.investor.asml.com", "www.asml.com", "asml.com", "live.euronext.com"}, "TSM": {"investor.tsmc.com", "pr.tsmc.com"}}
        if parts.hostname not in allowed.get(event["ticker"], set()):
            raise EarningsRefreshError("unregistered official issuer host")


def _fetch_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": E.USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=15) as response:
        body = response.read()
    return {"body": body, "captured_at": datetime.now(timezone.utc).isoformat(), "source_url": url}


def _text_url(url: str, *, requested: str | None = None) -> None:
    parts = urlsplit(url)
    if (parts.scheme != "https" or not parts.hostname or parts.port not in (None, 443)
            or parts.username or parts.password or parts.fragment
            or any(k.lower() in _AUTH for k, _ in parse_qsl(parts.query))):
        raise EarningsRefreshError("earnings text transport requires public HTTPS")
    if requested is not None and parts.hostname != urlsplit(requested).hostname:
        raise EarningsRefreshError("earnings text redirect changed its source host")


class _TextRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 3
    max_repeats = 3

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _text_url(newurl, requested=req.full_url)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _text_decode(payload: bytes) -> str:
    if not isinstance(payload, bytes) or not payload or len(payload) > MAX_TEXT_BYTES:
        raise EarningsRefreshError("earnings HTML is empty or exceeds eight million bytes")
    try:
        result = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise EarningsRefreshError("earnings HTML is not valid UTF-8") from exc
    if not result.strip():
        raise EarningsRefreshError("earnings HTML is empty")
    return result


def _fetch_text(url: str) -> str:
    """Try each URL independently; a failed host never disables another host."""
    _text_url(url)
    request = urllib.request.Request(url, headers=TEXT_HEADERS)
    try:
        opener = urllib.request.build_opener(_TextRedirect())
        with opener.open(request, timeout=20) as response:
            status = getattr(response, "status", None)
            if status is None:
                status = response.getcode()
            if status != 200:
                raise EarningsRefreshError("earnings HTML response is not HTTP 200")
            _text_url(response.geturl(), requested=url)
            payload = response.read(MAX_TEXT_BYTES + 1)
    except (OSError, urllib.error.URLError) as exc:
        # This fallback changes the transport, never the URL or source policy.
        command = ["curl", "--silent", "--show-error", "--fail", "--location", "--max-redirs", "3",
                   "--proto", "=https", "--proto-redir", "=https", "--connect-timeout", "10",
                   "--max-time", "20", "--retry", "1", "--retry-delay", "1", "--retry-max-time", "30",
                   "--max-filesize", str(MAX_TEXT_BYTES)]
        for key, value in TEXT_HEADERS.items():
            command.extend(["--header", f"{key}: {value}"])
        # A seekable output lets curl discard an interrupted attempt on retry;
        # stdout would concatenate partial and complete response bodies.
        with tempfile.TemporaryDirectory(prefix="earnings-html-") as scratch:
            output = Path(scratch) / "response.html"
            command.extend(["--output", str(output), "--write-out", "%{http_code}\n%{url_effective}", url])
            try:
                result = subprocess.run(command, capture_output=True, timeout=45, check=False)
            except (OSError, subprocess.SubprocessError) as fallback:
                raise EarningsRefreshError("earnings HTTPS transports were unavailable") from fallback
            if result.returncode != 0:
                raise EarningsRefreshError(f"earnings HTTPS curl failed ({result.returncode})") from exc
            if not isinstance(result.stdout, bytes):
                raise EarningsRefreshError("earnings curl response metadata must be bytes")
            try:
                status, effective = result.stdout.rsplit(b"\n", 1)
                final_url = effective.decode("utf-8", errors="strict")
            except (ValueError, UnicodeDecodeError) as malformed:
                raise EarningsRefreshError("earnings curl response metadata is malformed") from malformed
            if status != b"200":
                raise EarningsRefreshError("earnings HTML response is not HTTP 200")
            _text_url(final_url, requested=url)
            try:
                with output.open("rb") as handle:
                    payload = handle.read(MAX_TEXT_BYTES + 1)
            except OSError as missing:
                raise EarningsRefreshError("earnings curl response body is unavailable") from missing
    return _text_decode(payload)


def _response(value: Any, *, kind: str, url: str, tick: Callable[[], datetime]) -> tuple[bytes, datetime]:
    if isinstance(value, dict) and ("body" in value or "text" in value):
        if value.get("source_url", url) != url or value.get("status", value.get("http_status", 200)) != 200:
            raise EarningsRefreshError("source response identity/status mismatch")
        body = value.get("body", value.get("text"))
        captured = _time(value.get("captured_at", tick()))
    else:
        body, captured = value, _time(tick())
    if isinstance(body, bytes):
        payload = body
    elif isinstance(body, str):
        payload = body.encode()
    elif kind == "nasdaq" and isinstance(body, dict):
        payload = _bytes(body)
    else:
        raise EarningsRefreshError("source response body has an invalid type")
    if not payload:
        raise EarningsRefreshError("empty earnings response")
    return payload, captured


def _nasdaq(event: dict[str, Any], fetch: Callable[[str], dict[str, Any]], cutoff: datetime | Callable[[], datetime]) -> list[dict[str, Any]]:
    def checked(url):
        value = fetch(url)
        if not isinstance(value, dict):
            raise EarningsRefreshError("Nasdaq earnings response must be a JSON object")
        status, data = value.get("status"), value.get("data")
        if status and (not isinstance(status, dict) or status.get("rCode") not in (None, 200)):
            raise EarningsRefreshError("Nasdaq earnings response reports a failure")
        if data is not None:
            table = "earningsSurpriseTable" if "earnings-surprise" in url else "quarterlyForecast"
            if (not isinstance(data, dict) or (data.get(table) is not None and not isinstance(data[table], dict))):
                raise EarningsRefreshError("Nasdaq earnings table shape invalid")
            rows = (data.get(table) or {}).get("rows")
            if rows is not None and (not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows)):
                raise EarningsRefreshError("Nasdaq earnings rows shape invalid")
        return value
    url = E.EPS_SURPRISE_URL.format(ticker=event["ticker"])
    surprise = checked(url)
    return E.earnings_rows(event, lambda source: surprise if source == url else checked(source), as_of=cutoff() if callable(cutoff) else cutoff)


def _official(event: dict[str, Any], fetch: Callable[[str], Any], cutoff: datetime | None) -> dict[str, Any]:
    if event["ticker"] not in {"ASML", "TSM"}:
        return {"candidates": [], "errors": []}
    from .earnings_official import discover_issuer_release
    value = discover_issuer_release(event, fetch_text=fetch, now=cutoff)
    return value


def _attach(rows: list[dict[str, Any]], receipts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    if not receipts:
        raise EarningsRefreshError("earnings rows lack source receipts")
    stamp = max(_time(r["captured_at"]) for r in receipts).isoformat()
    sources = [{k: r[k] for k in ("source_url", "source_hash", "captured_at", "kind", "raw_path")} for r in receipts]
    return [{**row, "captured_at": stamp, "available_at": stamp, "source_receipts": sources,
             "source_hash": row.get("source_hash") or receipts[-1]["source_hash"]} for row in rows]


def _validate_rows(event: dict[str, Any], rows: list[dict[str, Any]], cutoff: datetime) -> None:
    for row in rows:
        if row.get("event_id") != event["event_id"] or row.get("metric") not in {"eps", "eps_reported", "eps_reported_adr", "revenue_reported", "gross_margin_reported"}:
            raise EarningsRefreshError("earnings candidate identity mismatch")
        stamp = _time(row["captured_at"])
        if stamp > cutoff or _time(row["available_at"]) != stamp or (row.get("published_at") and _time(row["published_at"]) > stamp):
            raise EarningsRefreshError("earnings candidate uses future availability/publication")
        if row["metric"] == "eps":
            if row.get("currency") != "USD" or row.get("unit") != "currency_per_share" or not E._period_matches(event, row.get("period_end")):
                raise EarningsRefreshError("Nasdaq earnings period/currency mismatch")
        else:
            target = E.expected_period(event)
            if (not target or row.get("fiscal_year") != target.year or row.get("fiscal_quarter") != (target.month - 1) // 3 + 1
                    or row.get("comparison_allowed") is not False or row.get("consensus") is not None):
                raise EarningsRefreshError("official earnings quarter/comparison mismatch")
            value = row.get("actual_value")
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise EarningsRefreshError("official actual must be finite numeric data")
            if row["metric"] == "gross_margin_reported":
                if row.get("unit") != "percent" or row.get("currency") is not None or not 0 <= value <= 100:
                    raise EarningsRefreshError("official margin unit/range mismatch")
            elif row["metric"] == "revenue_reported":
                if row.get("unit") != "million_currency" or row.get("currency") != "EUR" or event["ticker"] != "ASML":
                    raise EarningsRefreshError("official revenue unit/currency mismatch")
            else:
                if event["ticker"] == "ASML" and (row.get("currency") != "EUR" or row.get("share_basis") != "ordinary_share"):
                    raise EarningsRefreshError("ASML official currency/share basis mismatch")
                if event["ticker"] == "TSM" and (row.get("currency"), row.get("share_basis"), row.get("unit")) not in {("TWD", "ordinary_share", "currency_per_share"), ("USD", "ADR_unit", "currency_per_adr")}:
                    raise EarningsRefreshError("TSMC official currency/share basis mismatch")
                if row.get("eps_basis") not in {"basic", "diluted"} or row.get("unit") not in {"currency_per_share", "currency_per_adr"}:
                    raise EarningsRefreshError("official EPS basis/unit missing")
        if not row.get("source_receipts") or not any(r["source_hash"] == row.get("source_hash") for r in row["source_receipts"]):
            raise EarningsRefreshError("earnings source hash is not pinned to a captured receipt")


def capture_earnings(root: Path, *, output_dir: Path | str, now: datetime | str | None = None,
                     fetch_json: Callable[[str], Any] | None = None, fetch_text: Callable[[str], Any] | None = None,
                     clock: Callable[[], datetime] | None = None) -> dict[str, Any]:
    """Capture only nearby registered earnings; never mutate canonical source data."""
    root = Path(root)
    tick = clock or (lambda: datetime.now(timezone.utc))
    start = _time(now if now is not None else tick())
    target = Path(output_dir)
    if not target.is_absolute():
        target = root / target
    if target.exists() and any(target.iterdir()):
        raise EarningsRefreshError("earnings capture directory is immutable and must be empty")
    target.mkdir(parents=True, exist_ok=True)
    events, receipts, failures, candidates, statuses, diagnostics = _events(root, start), [], [], [], [], []
    for event in events:
        for kind in ("nasdaq", "official"):
            if kind == "official" and event["ticker"] not in {"ASML", "TSM"}:
                continue
            event_receipts = []
            def fetch(url, *, _kind=kind):
                _url(event, _kind, url)
                requested = _time(tick())
                payload, captured = _response((fetch_json or _fetch_json)(url) if _kind == "nasdaq" else (fetch_text or _fetch_text)(url), kind=_kind, url=url, tick=tick)
                if not start <= requested <= captured:
                    raise EarningsRefreshError("source completion precedes capture/request")
                digest = _sha(payload)
                relative = f"raw/{digest}.{'json' if _kind == 'nasdaq' else 'html'}.gz"
                raw = target / relative
                raw.parent.mkdir(parents=True, exist_ok=True)
                if not raw.exists():
                    raw.write_bytes(gzip.compress(payload, mtime=0))
                receipt = {"event_id": event["event_id"], "kind": _kind, "http_status": 200, "source_url": url, "source_hash": digest,
                           "raw_path": relative, "byte_count": len(payload), "requested_at": requested.isoformat(), "captured_at": captured.isoformat()}
                receipts.append(receipt)
                event_receipts.append(receipt)
                text = payload.decode("utf-8")
                return json.loads(text) if _kind == "nasdaq" else {"text": text, "source_url": url, "source_hash": digest, "captured_at": captured.isoformat()}
            try:
                result = _official(event, fetch, None) if kind == "official" else None
                rows = result["candidates"] if result else _nasdaq(event, fetch, lambda: _time(tick()))
                errors = result.get("errors", []) if result else []
                attempts = result.get("attempt_failures", []) if result else []
                usable = bool(result and result.get("status") in {"released", "pending"}
                              and (rows or result.get("usable_discovery_receipts", 0) > 0))
                for error in errors:
                    audit = {"event_id": event["event_id"], "ticker": event["ticker"], "kind": kind, "reason": error.get("error_type", "OfficialEarningsError")}
                    failures.append(audit)
                for error in attempts:
                    audit = {"event_id": event["event_id"], "ticker": event["ticker"], "kind": kind, "reason": error.get("error_type", "OfficialEarningsError")}
                    (diagnostics if usable else failures).append(audit)
                rows = _attach(rows, event_receipts)
                _validate_rows(event, rows, max([_time(r["captured_at"]) for r in event_receipts] or [start]))
                candidates.extend(rows)
                statuses.append({"event_id": event["event_id"], "kind": kind, "status": "reported" if any(r.get("actual") is not None for r in rows) else "failed" if errors or (attempts and not usable) else "pending"})
            except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
                failures.append({"event_id": event["event_id"], "ticker": event["ticker"], "kind": kind, "reason": type(exc).__name__})
                statuses.append({"event_id": event["event_id"], "kind": kind, "status": "failed"})
    end = max([_time(tick()), start, *[_time(r["captured_at"]) for r in receipts]])
    latest = E._ledger_latest(E._read_ledger(root / E.LEDGER_RELATIVE))
    hint = any(E.semantic_change(latest.get((r["event_id"], r["metric"])), r) for r in candidates)
    unsupported = _unsupported(root, start)
    body = {"schema_version": SCHEMA_VERSION, "contract_id": CONTRACT_ID, "started_at": start.isoformat(), "completed_at": end.isoformat(),
            "events": events, "receipts": receipts, "candidates": candidates, "source_failures": failures, "event_status": statuses, "attempt_failures": diagnostics,
            "unsupported_events": unsupported}
    body["bundle_id"] = "earnings-" + E.canonical_hash(body)[:24]
    manifest = {**body, "content_hash": E.canonical_hash(body)}
    (target / "manifest.json").write_bytes(_bytes(manifest))
    return {"schema_version": SCHEMA_VERSION, "bundle_path": str(target.resolve()), "bundle_id": body["bundle_id"],
            "status": "partial" if failures else "captured", "events": len(events), "receipts": len(receipts), "rows_seen": len(candidates),
            "pending": sum(s["status"] == "pending" for s in statuses), "source_failures": failures, "failures": failures, "attempt_failures": diagnostics, "changed_hint": hint,
            "unsupported_events": unsupported}


def _load_bundle(root: Path, bundle: Path, now: datetime) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, bytes]]:
    base = bundle.resolve()
    manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    body = {k: v for k, v in manifest.items() if k != "content_hash"}
    seed = {k: v for k, v in body.items() if k != "bundle_id"}
    if (manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("contract_id") != CONTRACT_ID
            or manifest.get("content_hash") != E.canonical_hash(body)
            or manifest.get("bundle_id") != "earnings-" + E.canonical_hash(seed)[:24]):
        raise EarningsRefreshError("earnings bundle contract/hash mismatch")
    start, end = _time(manifest["started_at"]), _time(manifest["completed_at"])
    if not start <= end <= now:
        raise EarningsRefreshError("earnings capture completion is after apply cutoff")
    registered = {event["event_id"]: event for event in _events(root, start)}
    if manifest.get("unsupported_events") != _unsupported(root, start):
        raise EarningsRefreshError("unsupported earnings scope audit differs from registered sources")
    events = manifest["events"]
    if len({event["event_id"] for event in events}) != len(events) or any(registered.get(event["event_id"]) != event for event in events):
        raise EarningsRefreshError("earnings event registration/window changed")
    if set(registered) != {event["event_id"] for event in events}:
        raise EarningsRefreshError("earnings bundle omits a nearby registered event")
    by_id = {event["event_id"]: event for event in events}
    if len(manifest["receipts"]) > 128 or len(manifest["source_failures"]) > 128:
        raise EarningsRefreshError("earnings bundle source report is unbounded")
    payloads = {}
    seen = set()
    for receipt in manifest["receipts"]:
        event = by_id.get(receipt["event_id"])
        if event is None or receipt.get("kind") not in {"nasdaq", "official"} or receipt.get("http_status") != 200:
            raise EarningsRefreshError("earnings receipt event/source mismatch")
        _url(event, receipt["kind"], receipt["source_url"])
        key = (receipt["event_id"], receipt["kind"], receipt["source_url"])
        if key in seen:
            raise EarningsRefreshError("duplicate earnings source response")
        seen.add(key)
        if not start <= _time(receipt["requested_at"]) <= _time(receipt["captured_at"]) <= end:
            raise EarningsRefreshError("earnings source capture clock is outside request bounds")
        path = (base / receipt["raw_path"]).resolve()
        if not path.is_relative_to((base / "raw").resolve()) or path.suffix != ".gz":
            raise EarningsRefreshError("earnings raw path escaped its immutable container")
        payload = gzip.decompress(path.read_bytes())
        digest = receipt["source_hash"]
        if not re.fullmatch(r"[a-f0-9]{64}", digest) or _sha(payload) != digest or len(payload) != receipt["byte_count"] or len(payload) > 8_000_000:
            raise EarningsRefreshError("earnings raw hash/byte count mismatch")
        payloads[receipt["raw_path"]] = payload
    for failure in manifest["source_failures"] + manifest.get("attempt_failures", []):
        if (failure.get("event_id") not in by_id or failure.get("ticker") != by_id[failure["event_id"]]["ticker"]
                or failure.get("kind") not in {"nasdaq", "official"} or not isinstance(failure.get("reason"), str) or len(failure["reason"]) > 128):
            raise EarningsRefreshError("earnings source failure metadata invalid")
    statuses = manifest["event_status"]
    expected_sources = {(e["event_id"], kind) for e in events for kind in ("nasdaq", "official") if kind == "nasdaq" or e["ticker"] in {"ASML", "TSM"}}
    if len(statuses) != len(expected_sources) or {(s["event_id"], s["kind"]) for s in statuses} != expected_sources:
        raise EarningsRefreshError("earnings bundle silently omits a source status")
    replayed = []
    for event in events:
        for status in [s for s in statuses if s["event_id"] == event["event_id"]]:
            kind = status["kind"]
            source_receipts = [r for r in manifest["receipts"] if r["event_id"] == event["event_id"] and r["kind"] == kind]
            if status["status"] not in {"pending", "reported", "failed"}:
                raise EarningsRefreshError("invalid earnings release status")
            failures = [f for f in manifest["source_failures"] if f["event_id"] == event["event_id"] and f["kind"] == kind]
            diagnostics = [f for f in manifest.get("attempt_failures", []) if f["event_id"] == event["event_id"] and f["kind"] == kind]
            if status["status"] == "failed" and not failures:
                raise EarningsRefreshError("failed source lacks explicit audit metadata")
            consumed = set()
            def fetch(url, *, _kind=kind):
                receipt = next((r for r in source_receipts if r["source_url"] == url), None)
                if receipt is None:
                    raise EarningsRefreshError("earnings replay requested an uncaptured source")
                consumed.add(url)
                text = payloads[receipt["raw_path"]].decode("utf-8")
                return json.loads(text) if _kind == "nasdaq" else {"text": text, "source_url": url, "captured_at": receipt["captured_at"]}
            if kind == "official":
                official = _official(event, fetch, end)
                if official.get("errors") and not failures:
                    raise EarningsRefreshError("official earnings replay failed without captured failure")
                rows = official["candidates"]
                replay_status = {"released": "reported", "pending": "pending", "failed": "failed"}.get(official.get("status"))
                if replay_status != status["status"]:
                    raise EarningsRefreshError("official discovery status differs from immutable-source replay")
            else:
                try:
                    rows = _nasdaq(event, fetch, end)
                except (ValueError, RuntimeError, KeyError, TypeError) as exc:
                    if not failures or status["status"] != "failed":
                        raise EarningsRefreshError("Nasdaq replay failure lacks matching captured audit status") from exc
                    rows = []
                else:
                    if failures or status["status"] == "failed":
                        raise EarningsRefreshError("claimed Nasdaq failure contradicts successful raw-source replay")
            if not (failures or diagnostics) and consumed != {r["source_url"] for r in source_receipts}:
                raise EarningsRefreshError("earnings source receipts are not used by the registered parser")
            rows = _attach(rows, source_receipts)
            _validate_rows(event, rows, end)
            reported = any(row.get("actual") is not None for row in rows)
            if reported != (status["status"] == "reported"):
                raise EarningsRefreshError("earnings release decision differs from captured raw sources")
            replayed.extend(rows)
    if E.canonical_hash(replayed) != E.canonical_hash(manifest["candidates"]):
        raise EarningsRefreshError("earnings candidates differ from immutable-source replay")
    return manifest, replayed, payloads


def apply_earnings(root: Path, *, bundle_dir: Path | str, now: datetime | str | None = None) -> dict[str, Any]:
    """Revalidate all sources before any append; stale captures never roll back actuals."""
    root, bundle = Path(root), Path(bundle_dir)
    if not bundle.is_absolute():
        bundle = root / bundle
    manifest, rows, payloads = _load_bundle(root, bundle, _time(now))
    canonical_rows = []
    locators = {}
    for row in rows:
        sources = []
        for receipt in row["source_receipts"]:
            suffix = "json" if receipt["kind"] == "nasdaq" else "html"
            relative = (RAW_RELATIVE / f"{receipt['source_hash']}.{suffix}.gz").as_posix()
            locators[relative] = payloads[receipt["raw_path"]]
            sources.append({**receipt, "raw_path": relative})
        canonical_rows.append({**row, "source_receipts": sources})
    def persist(records):
        needed = {r["raw_path"] for row in records for r in row["source_receipts"]}
        for relative in needed:
            path = root / relative
            if path.exists() and gzip.decompress(path.read_bytes()) != locators[relative]:
                raise EarningsRefreshError("append-only earnings raw artifact conflict")
        for relative in sorted(needed):
            path, payload = root / relative, locators[relative]
            if path.exists():
                if gzip.decompress(path.read_bytes()) != payload:
                    raise EarningsRefreshError("append-only earnings raw artifact conflict")
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + ".tmp")
            temporary.write_bytes(gzip.compress(payload, mtime=0))
            os.replace(temporary, path)
    failures = manifest["source_failures"]
    report = {"schema_version": SCHEMA_VERSION, "bundle_id": manifest["bundle_id"], "status": "partial" if failures else "ready",
              "changed": False, "appended": 0, "events": len(manifest["events"]),
              "pending": sum(s["status"] == "pending" for s in manifest["event_status"]), "source_failures": failures, "failures": failures,
              "attempt_failures": manifest.get("attempt_failures", []), "unsupported_events": manifest["unsupported_events"], "stale_ignored": 0}
    if len(_bytes(report)) > MAX_REPORT_BYTES - 256:
        raise EarningsRefreshError("earnings report exceeds bounded output contract")
    result = E.append_consensus_rows(root, canonical_rows, before_append=persist)
    report.update(changed=result["changed"], appended=result["appended"], stale_ignored=result["stale_ignored"])
    return report
