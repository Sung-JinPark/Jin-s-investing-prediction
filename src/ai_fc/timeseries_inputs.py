"""Bounded, raw-first source capture and replay, independent of model fitting."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from .official_sources import RequestSpec, alfred_request, alfred_vintage_dates_request
from .timeseries import ledger as N
from .timeseries_daily6m import features as F
from .timeseries_daily6m.contracts import canonical_hash
from .timeseries_daily6m.pipeline import writer_lock
from .timeseries_v2 import market_archive as M

NATIVE_SERIES = ("NASDAQCOM", "VIXCLS", "DGS2", "T10Y2Y", "DTWEXBGS")
MARKET_KINDS = ("market_cboe", "market_treasury", "market_fred_nasdaq", "market_fred_dollar")
STATE_RELATIVE = Path("data/timeseries_inputs/latest.json")
MAX_REPORT_BYTES = 16384
OVERLAP_DAYS = 7
MARKET_LOOKBACK_DAYS = 30
_AUTH_KEYS = {"api_key", "apikey", "key", "token", "access_token", "authorization", "signature"}


class TimeSeriesInputsError(ValueError):
    """A source capture or replay failed its registered integrity boundary."""


def _time(value: str | datetime | None = None) -> datetime:
    result = datetime.now(timezone.utc) if value is None else datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(result, datetime) or result.tzinfo is None or result.utcoffset() is None:
        raise TimeSeriesInputsError("source timestamps must include a timezone")
    return result.astimezone(timezone.utc)


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.is_file() else []


def _public_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode([(k, v) for k, v in parse_qsl(parts.query) if k.lower() not in _AUTH_KEYS]), ""))


def _sha(value: bytes | str) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def _state(root: Path) -> dict[str, Any]:
    path = root / STATE_RELATIVE
    if not path.is_file():
        return {}
    result = json.loads(path.read_text(encoding="utf-8"))
    if result.get("content_hash") != canonical_hash({k: v for k, v in result.items() if k != "content_hash"}):
        raise TimeSeriesInputsError("input state content hash mismatch")
    return result


def _native_table(root: Path) -> list[dict[str, Any]]:
    import pyarrow.parquet as pq
    path = root / "data/timeseries/facts/observations.parquet"
    if not path.is_file():
        return []
    columns = ["source_id", "series_id", "observation_time", "value", "value_status", "available_at", "vintage_start", "vintage_end", "retrieved_at", "source_hash"]
    return pq.read_table(path, columns=columns, filters=[("series_id", "in", list(NATIVE_SERIES)), ("source_id", "=", "alfred")]).to_pylist()


def _native_seed_windows(root: Path, now: datetime) -> tuple[dict[str, str], list[dict[str, Any]]]:
    facts = _native_table(root)
    prior = _state(root).get("native_watermarks", {})
    receipts = _rows(root / "data/timeseries/ledgers/raw_receipts.jsonl")
    valid_receipts = {(r.get("series_id"), r.get("raw_sha256"), r.get("retrieved_at")) for r in receipts if r.get("source_id") == "alfred" and r.get("http_status") == 200}
    windows, failures = {}, []
    for sid in NATIVE_SERIES:
        rows = [r for r in facts if r["series_id"] == sid]
        if not rows:
            failures.append({"source_id": "alfred", "series_id": sid, "stage": "bootstrap", "reason": "existing native series required; use the full timeseries-refresh repair"})
            continue
        latest = prior.get(sid)
        if latest is None:
            candidates = [_time(r["retrieved_at"]) for r in rows if (sid, r["source_hash"], r["retrieved_at"]) in valid_receipts]
            if not candidates:
                failures.append({"source_id": "alfred", "series_id": sid, "stage": "bootstrap", "reason": "successful linked observation receipt required; use the full source repair"})
                continue
            latest = max(candidates)
        latest = _time(latest)
        if latest > now:
            raise TimeSeriesInputsError("native success watermark is after this collection time")
        if (now - latest).days > MARKET_LOOKBACK_DAYS:
            failures.append({"source_id": "alfred", "series_id": sid, "stage": "bootstrap", "reason": "native watermark exceeds bounded repair window; use the full source repair"})
            continue
        windows[sid] = (latest - timedelta(days=OVERLAP_DAYS)).date().isoformat()
    return windows, failures


def _native_parse(payload: bytes, sid: str, captured: datetime) -> list[Any]:
    value = json.loads(payload)
    if not isinstance(value, dict) or value.get("output_type") != 3 or not isinstance(value.get("observations"), list):
        raise TimeSeriesInputsError("native observations require explicit output_type=3")
    count, offset = value.get("count", len(value["observations"])), value.get("offset", 0)
    if type(count) is not int or type(offset) is not int or offset != 0 or count != len(value["observations"]):
        raise TimeSeriesInputsError("native observation response is truncated or paginated")
    for row in value["observations"]:
        if not isinstance(row, dict) or not isinstance(row.get("date"), str):
            raise TimeSeriesInputsError("native observation shape invalid")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["date"]) or date.fromisoformat(row["date"]).isoformat() != row["date"]:
            raise TimeSeriesInputsError("native observation date invalid")
        for name, number in row.items():
            if name == "date":
                continue
            if not re.fullmatch(re.escape(sid) + r"_\d{8}", name) or isinstance(number, bool):
                raise TimeSeriesInputsError("native observation series/vintage coordinate invalid")
    facts = N.normalize_alfred(payload, series_id=sid, retrieved_at=captured.isoformat())
    if any(not math.isfinite(f.value) or (sid in {"NASDAQCOM", "VIXCLS", "DTWEXBGS"} and f.value <= 0) for f in facts):
        raise TimeSeriesInputsError("native observation levels must be finite and price levels positive")
    if any(f.observation_time > F.last_completed_session(captured) for f in facts):
        raise TimeSeriesInputsError("native response contains an uncompleted future observation")
    return facts


def _market_values(kind: str, payload: bytes, sid: str, captured: datetime) -> dict[str, list[tuple[str, float]]]:
    if kind == "market_cboe":
        values = {"VIX": M.parse_cboe_vix_csv(payload)}
    elif kind == "market_treasury":
        rows = M.parse_treasury_xml(payload)
        values = {"DGS2": [(d, a) for d, a, _ in rows], "DGS10": [(d, b) for d, _, b in rows]}
    else:
        from .fred_api import observations_to_csv
        decoded = json.loads(payload)
        if not isinstance(decoded, dict) or not isinstance(decoded.get("observations"), list):
            raise TimeSeriesInputsError("official FRED response lacks observations")
        values = {sid: M.parse_fred_graph_csv(observations_to_csv(payload, sid).encode(), series_id=sid)}
    completed = F.last_completed_session(captured)
    for series, rows in values.items():
        if not rows:
            raise TimeSeriesInputsError("official market response contains no observations")
        for day, number in rows:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or date.fromisoformat(day).isoformat() != day:
                raise TimeSeriesInputsError("market observation date invalid")
            if day > completed or isinstance(number, bool) or not math.isfinite(number) or (series in {"VIX", "NASDAQCOM", "DTWEXBGS"} and number <= 0):
                raise TimeSeriesInputsError("market response contains an invalid or uncompleted close")
    return values


def capture_timeseries_inputs(
    root: Path, *, output_dir: Path | str | None = None, now: str | datetime | None = None,
    api_key: str | None = None, native_fetcher: Callable[[RequestSpec], tuple[int, bytes]] | None = None,
    market_fetcher: Callable | None = None, fred_fetch_text: Callable | None = None,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Capture immutable raw responses without mutating source or model ledgers."""
    root = Path(root)
    tick = clock or (lambda: datetime.now(timezone.utc))
    started = _time(now if now is not None else tick())
    target = Path(output_dir) if output_dir is not None else root / ".tmp/inputs-capture"
    if not target.is_absolute():
        target = root / target
    if target.exists() and any(target.iterdir()):
        raise TimeSeriesInputsError("capture directory is immutable and must be empty")
    target.mkdir(parents=True, exist_ok=True)
    store = target / "raw_store"
    windows, failures = _native_seed_windows(root, started)
    receipts: list[dict[str, Any]] = []
    native_complete: dict[str, str] = {}
    native_observation_complete: dict[str, str] = {}
    market_complete: dict[str, str] = {}

    def record(kind, sid, source_id, url, requested, status, payload, content_type):
        captured = _time(tick())
        if captured < requested:
            raise TimeSeriesInputsError("response completion precedes its request")
        public = _public_url(url)
        if api_key and api_key.encode() in payload:
            raise TimeSeriesInputsError("response unexpectedly contains a runtime credential")
        if kind.startswith("native"):
            receipt = N.persist_response(store, series_id=sid, status=status, payload=payload, retrieved_at=captured.isoformat(), request_url=public)
        else:
            receipt = M.persist_market_raw(store, source_id=source_id, source_uri=public, payload=payload, retrieved_at=captured.isoformat(), http_status=status, content_type=content_type)
        item = {"kind": kind, "series_id": sid, "source_id": source_id, "source_uri": public, "request_sha256": _sha(public),
                "requested_at": requested.isoformat(), "retrieved_at": captured.isoformat(), "http_status": status, "raw_sha256": receipt.raw_sha256,
                "raw_path": "raw_store/" + receipt.raw_path, "byte_count": len(payload), "content_type": content_type, "valid": status == 200}
        receipts.append(item)
        return item, captured

    def failure(source_id, sid, stage, exc):
        failed = next((r["http_status"] for r in reversed(receipts) if r["source_id"] == source_id and r["series_id"] == sid and r["http_status"] != 200), None)
        failures.append({"source_id": source_id, "series_id": sid, "stage": stage, "reason": type(exc).__name__, "http_status": getattr(exc, "status", getattr(exc, "code", failed))})

    for sid, start in windows.items():
        try:
            if not api_key:
                raise TimeSeriesInputsError("runtime FRED key required")
            dates, offset = [], 0
            while True:
                spec = alfred_vintage_dates_request(sid, api_key=api_key, realtime_start=start, realtime_end="9999-12-31", offset=offset)
                requested = _time(tick())
                status, payload = native_fetcher(spec) if native_fetcher else N._fetch_alfred(spec, series_id=sid, endpoint="vintage_dates", timeout_seconds=25, max_attempts=1)
                item, captured = record("native_inventory", sid, "alfred", spec.url, requested, status, payload, "application/json")
                try:
                    value = json.loads(payload)
                    if status != 200 or not isinstance(value.get("vintage_dates"), list):
                        raise TimeSeriesInputsError("vintage inventory request failed")
                    page = value["vintage_dates"]
                    if any(not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or day < start for day in page):
                        raise TimeSeriesInputsError("vintage inventory dates invalid")
                    dates.extend(page)
                    count = value.get("count", len(page))
                    if type(count) is not int or count < offset + len(page) or (not page and count > offset):
                        raise TimeSeriesInputsError("vintage inventory response is incomplete")
                    offset += len(page)
                    if offset >= count:
                        break
                except (ValueError, TypeError, KeyError):
                    item["valid"] = False
                    raise
            dates = sorted(set(dates))
            for index in range(0, len(dates), N.ALFRED_VINTAGE_BATCH_SIZE):
                batch = dates[index:index + N.ALFRED_VINTAGE_BATCH_SIZE]
                spec = alfred_request(sid, api_key=api_key, realtime_start=batch[0], realtime_end=batch[-1], output_type=3)
                requested = _time(tick())
                status, payload = native_fetcher(spec) if native_fetcher else N._fetch_alfred(spec, series_id=sid, endpoint="observations", timeout_seconds=25, max_attempts=1)
                item, captured = record("native_observations", sid, "alfred", spec.url, requested, status, payload, "application/json")
                try:
                    if status != 200:
                        raise TimeSeriesInputsError("native observation request failed")
                    _native_parse(payload, sid, captured)
                except (ValueError, TypeError, KeyError):
                    item["valid"] = False
                    raise
                native_observation_complete[sid] = captured.isoformat()
            native_complete[sid] = captured.isoformat()
        except (OSError, ValueError, RuntimeError, TypeError, KeyError) as exc:
            failure("alfred", sid, "native", exc)

    for kind in MARKET_KINDS:
        sid = "VIX" if kind == "market_cboe" else "DGS2_DGS10" if kind == "market_treasury" else "NASDAQCOM" if kind == "market_fred_nasdaq" else "DTWEXBGS"
        source_id = "cboe_vix_archive" if kind == "market_cboe" else "us_treasury_yield_archive" if kind == "market_treasury" else "fred_api_nasdaqcom_archive" if kind == "market_fred_nasdaq" else "fred_api_h10_broad_goods_services_archive"
        try:
            requested = _time(tick())
            if kind == "market_cboe":
                url = M.MARKET_ARCHIVE_SPECS["VIX"]["url"]
            elif kind == "market_treasury":
                url = M.MARKET_ARCHIVE_SPECS["TREASURY"]["url"].format(year=requested.year)
            else:
                from .fred_api import _request_url
                if not api_key:
                    raise TimeSeriesInputsError("runtime FRED key required")
                url = _request_url(sid, key=api_key, observation_start=(requested.date() - timedelta(days=MARKET_LOOKBACK_DAYS)).isoformat())
            if kind.startswith("market_fred"):
                if fred_fetch_text is None:
                    from .quant.feed import get_with_curl_fallback
                    payload = get_with_curl_fallback(url, timeout=45).encode()
                else:
                    response = fred_fetch_text(url, timeout=45)
                    payload = response.encode() if isinstance(response, str) else response
                status, content_type = 200, "application/json"
            else:
                status, payload, content_type = market_fetcher(url) if market_fetcher else M._fetch(url, timeout=30)
            item, captured = record(kind, sid, source_id, url, requested, status, payload, content_type)
            try:
                if status != 200:
                    raise TimeSeriesInputsError("official market request failed")
                _market_values(kind, payload, sid, captured)
            except (ValueError, TypeError, KeyError):
                item["valid"] = False
                raise
            market_complete[kind] = captured.isoformat()
        except (OSError, ValueError, RuntimeError, TypeError, KeyError) as exc:
            failure(source_id, sid, kind, exc)

    finished = _time(tick())
    body = {"schema_version": 1, "contract_id": "timeseries_inputs_capture_v1", "started_at": started.isoformat(), "completed_at": finished.isoformat(),
            "native_series": list(NATIVE_SERIES), "native_windows": windows, "native_complete": native_complete,
            "native_observation_complete": native_observation_complete, "market_complete": market_complete,
            "receipts": receipts, "source_failures": failures, "status": "partial" if failures and receipts else "failed" if failures else "captured"}
    body["bundle_id"] = "ts-inputs-" + canonical_hash(body)[:24]
    manifest = {**body, "content_hash": canonical_hash(body)}
    raw = _json_bytes(manifest)
    (target / "manifest.json").write_bytes(raw)
    return {"schema_version": 1, "status": body["status"], "bundle_path": str(target.resolve()), "bundle_id": body["bundle_id"], "manifest_sha256": _sha(raw), "source_failures": failures, "receipts": len(receipts), "count": len(receipts)}


def _validate_uri(item: dict[str, Any]) -> None:
    url = item["source_uri"]
    parts = urlsplit(url)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    if parts.scheme != "https" or parts.username or parts.password or parts.fragment or parts.port not in (None, 443) or any(k.lower() in _AUTH_KEYS for k, _ in pairs) or len(dict(pairs)) != len(pairs):
        raise TimeSeriesInputsError("capture request URI contains credentials or an invalid origin")
    if item.get("request_sha256") != _sha(url):
        raise TimeSeriesInputsError("capture request SHA256 mismatch")
    kind, sid = item["kind"], item["series_id"]
    query = dict(pairs)
    if kind.startswith("native"):
        allowed = {"series_id", "file_type", "realtime_start", "realtime_end", "limit", "offset"} if kind == "native_inventory" else {"series_id", "file_type", "realtime_start", "realtime_end", "output_type"}
        endpoint = "vintagedates" if kind == "native_inventory" else "observations"
        if sid not in NATIVE_SERIES or item["source_id"] != "alfred" or parts.netloc != "api.stlouisfed.org" or parts.path != "/fred/series/" + endpoint or set(query) != allowed or query["series_id"] != sid or query["file_type"] != "json":
            raise TimeSeriesInputsError("native capture source/series/request mismatch")
        if kind == "native_inventory" and (query["realtime_end"] != "9999-12-31" or int(query["limit"]) != 10000 or int(query["offset"]) < 0):
            raise TimeSeriesInputsError("native inventory bounds mismatch")
        if kind == "native_observations" and query["output_type"] != "3":
            raise TimeSeriesInputsError("native capture output_type mismatch")
    elif kind == "market_cboe":
        if url != M.MARKET_ARCHIVE_SPECS["VIX"]["url"] or sid != "VIX" or item["source_id"] != "cboe_vix_archive":
            raise TimeSeriesInputsError("CBOE capture source mismatch")
    elif kind == "market_treasury":
        expected = M.MARKET_ARCHIVE_SPECS["TREASURY"]["url"].format(year=_time(item["requested_at"]).year)
        if url != expected or sid != "DGS2_DGS10" or item["source_id"] != "us_treasury_yield_archive":
            raise TimeSeriesInputsError("Treasury capture source/year mismatch")
    elif kind in {"market_fred_nasdaq", "market_fred_dollar"}:
        expected_sid, source = ("NASDAQCOM", "fred_api_nasdaqcom_archive") if kind == "market_fred_nasdaq" else ("DTWEXBGS", "fred_api_h10_broad_goods_services_archive")
        expected_start = (_time(item["requested_at"]).date() - timedelta(days=MARKET_LOOKBACK_DAYS)).isoformat()
        if sid != expected_sid or item["source_id"] != source or parts.netloc != "api.stlouisfed.org" or parts.path != "/fred/series/observations" or query != {"series_id": sid, "file_type": "json", "observation_start": expected_start}:
            raise TimeSeriesInputsError("official FRED market source/lookback mismatch")
    else:
        raise TimeSeriesInputsError("unregistered capture kind")


def _validate_bundle(bundle_dir: Path, now: datetime) -> tuple[dict[str, Any], list[tuple[dict[str, Any], bytes, Any]]]:
    base = bundle_dir.resolve()
    manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    body = {k: v for k, v in manifest.items() if k != "content_hash"}
    seed = {k: v for k, v in body.items() if k != "bundle_id"}
    if manifest.get("content_hash") != canonical_hash(body) or manifest.get("bundle_id") != "ts-inputs-" + canonical_hash(seed)[:24]:
        raise TimeSeriesInputsError("immutable capture manifest identity/hash mismatch")
    if manifest.get("schema_version") != 1 or manifest.get("contract_id") != "timeseries_inputs_capture_v1" or manifest.get("native_series") != list(NATIVE_SERIES):
        raise TimeSeriesInputsError("capture contract or native roster mismatch")
    start, end = _time(manifest["started_at"]), _time(manifest["completed_at"])
    if start > end or end > now:
        raise TimeSeriesInputsError("capture completion is after replay time or before capture start")
    if not isinstance(manifest.get("source_failures"), list) or len(manifest["source_failures"]) > len(NATIVE_SERIES) + len(MARKET_KINDS):
        raise TimeSeriesInputsError("capture source failure report invalid or unbounded")
    allowed_sources = {"alfred", "cboe_vix_archive", "us_treasury_yield_archive", "fred_api_nasdaqcom_archive", "fred_api_h10_broad_goods_services_archive"}
    for failure in manifest["source_failures"]:
        if (not isinstance(failure, dict) or set(failure) - {"source_id", "series_id", "stage", "reason", "http_status"}
                or any(not isinstance(failure.get(k), str) or len(failure[k]) > 128 for k in ("source_id", "series_id", "stage", "reason"))
                or failure["source_id"] not in allowed_sources or failure["series_id"] not in {*NATIVE_SERIES, "VIX", "DGS2_DGS10"}
                or failure["stage"] not in {*MARKET_KINDS, "native", "bootstrap"}):
            raise TimeSeriesInputsError("capture source failure metadata invalid")
    for sid, window in manifest["native_windows"].items():
        if sid not in NATIVE_SERIES or date.fromisoformat(window) < start.date() - timedelta(days=MARKET_LOOKBACK_DAYS + OVERLAP_DAYS):
            raise TimeSeriesInputsError("native capture must use a bounded initialized source window")
    loaded = []
    for item in manifest["receipts"]:
        _validate_uri(item)
        requested, captured = _time(item["requested_at"]), _time(item["retrieved_at"])
        if not start <= requested <= captured <= end:
            raise TimeSeriesInputsError("receipt actual completion time is outside capture bounds")
        path = (base / item["raw_path"]).resolve()
        if not path.is_relative_to((base / "raw_store").resolve()) or path.suffix != ".gz":
            raise TimeSeriesInputsError("capture raw path escaped its container")
        payload = gzip.decompress(path.read_bytes())
        if not re.fullmatch(r"[0-9a-f]{64}", str(item["raw_sha256"])) or _sha(payload) != item["raw_sha256"] or len(payload) != item["byte_count"]:
            raise TimeSeriesInputsError("capture raw SHA256 or byte count mismatch")
        if type(item.get("valid")) is not bool or type(item.get("http_status")) is not int:
            raise TimeSeriesInputsError("capture status must be explicit")
        if item["valid"] and item["http_status"] != 200:
            raise TimeSeriesInputsError("failed HTTP capture cannot be valid")
        if not item["valid"]:
            if not manifest["source_failures"]:
                raise TimeSeriesInputsError("invalid response lacks an explicit source failure")
            loaded.append((item, payload, None))
            continue
        if item["kind"] == "native_observations":
            parsed = _native_parse(payload, item["series_id"], captured)
            query = dict(parse_qsl(urlsplit(item["source_uri"]).query))
            if any(not query["realtime_start"] <= _time(f.vintage_start).astimezone(ZoneInfo("America/New_York")).date().isoformat() <= query["realtime_end"] for f in parsed):
                raise TimeSeriesInputsError("native response vintage is outside its requested range")
        elif item["kind"] == "native_inventory":
            parsed = json.loads(payload)
            if not isinstance(parsed.get("vintage_dates"), list):
                raise TimeSeriesInputsError("native inventory capture invalid")
        else:
            parsed = _market_values(item["kind"], payload, item["series_id"], captured)
        loaded.append((item, payload, parsed))
    complete = set(manifest["native_complete"]) == set(NATIVE_SERIES) and set(manifest["market_complete"]) == set(MARKET_KINDS)
    if not manifest["source_failures"] and not complete:
        raise TimeSeriesInputsError("capture silently omits a required source")
    for sid, stamp in manifest["native_complete"].items():
        entries = [i for i, _, _ in loaded if i["series_id"] == sid and i["kind"].startswith("native")]
        if not entries or not all(i["valid"] for i in entries) or _time(stamp) != max(_time(i["retrieved_at"]) for i in entries):
            raise TimeSeriesInputsError("native success watermark does not cover successful responses")
        inventory = [(i, p) for i, _, p in loaded if i["kind"] == "native_inventory" and i["series_id"] == sid]
        dates, offset = [], 0
        for item, page in inventory:
            query = dict(parse_qsl(urlsplit(item["source_uri"]).query))
            if query["realtime_start"] != manifest["native_windows"][sid] or int(query["offset"]) != offset:
                raise TimeSeriesInputsError("native inventory pagination/window mismatch")
            dates.extend(page["vintage_dates"])
            offset += len(page["vintage_dates"])
        if not inventory or offset < int(inventory[-1][1].get("count", offset)):
            raise TimeSeriesInputsError("native inventory coverage incomplete")
        dates = sorted(set(dates))
        expected_batches = [(dates[n], dates[min(n + N.ALFRED_VINTAGE_BATCH_SIZE, len(dates)) - 1]) for n in range(0, len(dates), N.ALFRED_VINTAGE_BATCH_SIZE)]
        observations = [i for i in entries if i["kind"] == "native_observations"]
        actual_batches = [(dict(parse_qsl(urlsplit(i["source_uri"]).query))["realtime_start"], dict(parse_qsl(urlsplit(i["source_uri"]).query))["realtime_end"]) for i in observations]
        if actual_batches != expected_batches:
            raise TimeSeriesInputsError("native observation coverage omits an inventoried vintage")
    for sid, stamp in manifest.get("native_observation_complete", {}).items():
        entries = [i for i, _, _ in loaded if i["kind"] == "native_observations" and i["series_id"] == sid]
        if sid not in manifest["native_complete"] or not entries or not all(i["valid"] for i in entries) or _time(stamp) != max(_time(i["retrieved_at"]) for i in entries):
            raise TimeSeriesInputsError("native observation success timestamp invalid")
    for kind, stamp in manifest["market_complete"].items():
        entries = [i for i, _, _ in loaded if i["kind"] == kind]
        if len(entries) != 1 or not entries[0]["valid"] or stamp != entries[0]["retrieved_at"]:
            raise TimeSeriesInputsError("market source completion mismatch")
    return manifest, loaded


def eligibility_signature(root: Path, *, now: str | datetime | None = None) -> dict[str, Any]:
    """Compact signatures of eligible source vintages and gate state, without clock ages."""
    current = _time(now)
    expected = F.last_completed_session(current)
    selected: dict[tuple[str, str], dict[str, Any]] = {}
    errors = []
    for row in _native_table(Path(root)):
        try:
            available, vintage, captured = (_time(row[k]) for k in ("available_at", "vintage_start", "retrieved_at"))
            if captured > current:
                errors.append("native capture is after current cutoff: " + row["series_id"])
                continue
            if available > current or vintage > current or row["observation_time"] > expected or row["value_status"] != "ok":
                continue
            if row.get("vintage_end") is not None and _time(row["vintage_end"]) <= current:
                continue
            number = row["value"]
            if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number):
                raise TimeSeriesInputsError("native eligible level invalid")
            key = (row["series_id"], row["observation_time"])
            prior = selected.get(key)
            if prior is None or (vintage, available) > (_time(prior["vintage_start"]), _time(prior["available_at"])):
                selected[key] = row
        except (TypeError, ValueError, KeyError):
            errors.append("native source metadata invalid")
    native, cohort = {}, {}
    for sid in NATIVE_SERIES:
        rows = [r for r in selected.values() if r["series_id"] == sid]
        if not rows:
            native[sid] = None
            cohort[sid] = None
            continue
        latest = max(rows, key=lambda r: r["observation_time"])
        coordinates = ("series_id", "observation_time", "value", "available_at", "vintage_start", "source_hash")
        native[sid] = {k: latest[k] for k in coordinates}
        newest = max(_time(r["available_at"]) for r in rows)
        cohort[sid] = {"available_at": newest.isoformat(), "digest": canonical_hash(sorted([{k: r[k] for k in coordinates} for r in rows if _time(r["available_at"]) == newest], key=lambda r: r["observation_time"]))}
    market = {}
    for row in M.read_market_observations(Path(root), knowledge_cutoff=current.isoformat()):
        if row.series_id in {"NASDAQCOM", "VIX", "DGS2", "DGS10", "DTWEXBGS"}:
            old = market.get(row.series_id)
            if old is None or row.observation_time > old["observation_time"]:
                market[row.series_id] = {"observation_time": row.observation_time, "value": row.value, "available_at": row.available_at, "data_grade": row.data_grade, "source_id": row.source_id}
    statuses = []
    for sid in NATIVE_SERIES:
        row = native[sid]
        age = (current - _time(row["observation_time"] + "T23:59:59+00:00")).total_seconds() / 3600 if row else None
        statuses.append({"series_id": sid, "status": "missing" if row is None else "stale" if age > (216 if sid == "DTWEXBGS" else 48) else "fresh"})
    iso = datetime.fromisoformat(expected).date().isocalendar()
    week = f"{iso.year}-W{iso.week:02d}"
    material = {"expected_session": expected, "native": native, "native_publication_cohorts": cohort, "market": market, "source_status": statuses,
                "iso_week": week, "errors": sorted(set(errors))}
    return {"schema_version": 1, "as_of": current.isoformat(), "status": "hold" if errors or any(r["status"] != "fresh" for r in statuses) else "ready", "eligibility_hash": canonical_hash(material), **material}


def apply_timeseries_inputs(root: Path, *, bundle_dir: Path | str, now: str | datetime | None = None) -> dict[str, Any]:
    """Validate every capture before replay into the latest serialized source store."""
    root, bundle = Path(root), Path(bundle_dir)
    if not bundle.is_absolute():
        bundle = root / bundle
    current = _time(now)
    with writer_lock(root):
        manifest, loaded = _validate_bundle(bundle, current)
        prior_state = _state(root)
        if prior_state.get("capture_completed_at") and _time(manifest["completed_at"]) < _time(prior_state["capture_completed_at"]):
            return {"schema_version": 1, "status": "hold", "bundle_id": manifest["bundle_id"], "changed": False, "semantic_changed": False,
                    "eligibility_changed": False, "publication_allowed": False, "source_failures": [{"stage": "apply", "reason": "stale capture ignored; newer applied source check preserved"}],
                    "native": {"appended": 0, "corrected": 0}, "market": {"appended": 0}, "state_path": STATE_RELATIVE.as_posix(), "state_changed": False, "stale_ignored": True}
        before = eligibility_signature(root, now=current)
        existing_native = {f.key: f for f in N.read_facts(root)}
        existing_market = {(r.series_id, r.observation_time): r for r in M.read_market_observations(root)}
        pending, market_work = [], []
        needed_native = set()
        for item, payload, parsed in loaded:
            if not item["valid"]:
                continue
            if item["kind"] == "native_observations":
                for fact in parsed:
                    old = existing_native.get(fact.key)
                    if old is not None and _time(old.retrieved_at) > _time(fact.retrieved_at) and (old.value != fact.value or old.value_status != fact.value_status):
                        raise TimeSeriesInputsError("older native capture cannot supersede a newer correction")
                    if old is None or old.value != fact.value or old.value_status != fact.value_status:
                        pending.append(fact)
                        needed_native.add(item["raw_sha256"])
            elif item["kind"] != "native_inventory":
                changed_values = {}
                for sid, values in parsed.items():
                    changed_values[sid] = []
                    for day, number in values:
                        old = existing_market.get((sid, day))
                        if old is not None and _time(old.vintage_start) > _time(item["retrieved_at"]) and old.value != number:
                            raise TimeSeriesInputsError("older market capture cannot supersede a newer correction")
                        if old is None or old.value != number:
                            changed_values[sid].append((day, number))
                if any(changed_values.values()):
                    market_work.append((item, payload, changed_values))
        # All source/receipt/path/clock/revision guards precede these mutations.
        for item, payload, _ in loaded:
            if item["kind"] == "native_observations" and item["raw_sha256"] in needed_native:
                N.persist_response(root, series_id=item["series_id"], status=200, payload=payload, retrieved_at=item["retrieved_at"], request_url=item["source_uri"])
        native_result = N.append_facts(root, N._close_vintage_intervals(root, pending)) if pending else {"appended": 0, "corrected": 0}
        market_appended = 0
        for item, payload, values in market_work:
            receipt = M.persist_market_raw(root, source_id=item["source_id"], source_uri=item["source_uri"], payload=payload, retrieved_at=item["retrieved_at"], content_type=item["content_type"])
            for sid, rows in values.items():
                unit = "percentage_point" if sid in {"DGS2", "DGS10"} else "index"
                outcome = M._append_observations(root, source_id=item["source_id"], series_id=sid, unit=unit, values=rows, receipt=receipt,
                                                 available_at=M._market_available_at, data_grade="captured_forward")
                market_appended += outcome["appended"]
        if market_appended:
            M.export_market_parquet(root)
        signature = eligibility_signature(root, now=current)
        failures = list(manifest["source_failures"])
        failures.extend({"source_id": "stored_native", "series_id": "critical", "stage": "eligibility", "reason": reason} for reason in signature["errors"])
        publication_allowed = not failures
        semantic_changed = native_result["appended"] > 0 or market_appended > 0
        old_eligibility = prior_state.get("eligibility_hash", before["eligibility_hash"])
        eligibility_changed = signature["eligibility_hash"] != old_eligibility or prior_state.get("publication_allowed") is not publication_allowed
        changed = semantic_changed or eligibility_changed
        watermarks = dict(prior_state.get("native_watermarks", {}))
        for sid, stamp in manifest.get("native_observation_complete", {}).items():
            if sid not in watermarks or _time(stamp) > _time(watermarks[sid]):
                watermarks[sid] = stamp
        body = {"schema_version": 1, "contract_id": "timeseries_inputs_refresh_v1", "checked_at": current.isoformat(), "capture_completed_at": manifest["completed_at"],
                "bundle_id": manifest["bundle_id"], "status": "ready" if publication_allowed else "hold", "publication_allowed": publication_allowed,
                "source_failures": failures, "native_watermarks": watermarks, "eligibility_hash": signature["eligibility_hash"],
                "expected_session": signature["expected_session"], "source_status": signature["source_status"], "eligibility_status": signature["status"],
                "eligible_native_latest": signature["native"], "changed": changed, "semantic_changed": semantic_changed, "eligibility_changed": eligibility_changed}
        state = {**body, "content_hash": canonical_hash(body)}
        raw = _json_bytes(state)
        if len(raw) > MAX_REPORT_BYTES:
            raise TimeSeriesInputsError("bounded source status exceeds 16KiB")
        path = root / STATE_RELATIVE
        state_changed = not path.is_file() or path.read_bytes() != raw
        if state_changed:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(raw)
            os.replace(temporary, path)
        return {"schema_version": 1, "status": state["status"], "bundle_id": manifest["bundle_id"], "changed": changed, "semantic_changed": semantic_changed,
                "eligibility_changed": eligibility_changed, "publication_allowed": publication_allowed, "source_failures": failures,
                "native": {"appended": native_result["appended"], "corrected": native_result["corrected"]}, "market": {"appended": market_appended},
                "state_path": STATE_RELATIVE.as_posix(), "state_changed": state_changed, "eligibility_hash": signature["eligibility_hash"]}
