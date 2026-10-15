"""Raw-first, captured-forward sources for the independent daily research track.

This module never writes the native, V2, V8, forecast, or resolution stores.
An observed capture time is availability; a historical date is never availability.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import math
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlsplit
from zoneinfo import ZoneInfo

STORE = Path("data/timeseries_daily6m")
RECEIPTS = STORE / "source_receipts.jsonl"
OBSERVATIONS = STORE / "source_observations.jsonl"
SCHEMA = "daily6m_sources_v1"
MAX_BYTES = 8_000_000
MAX_REPORT_BYTES = 16_384
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
NASDAQ_INFO = "https://api.nasdaq.com/api/quote/COMP/info?assetclass=index"
NASDAQ_HISTORY = "https://api.nasdaq.com/api/quote/COMP/historical"
CBOE_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
CBOE_RESPONSE_URL = "https://cdn-api.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
TREASURY_URL = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value={year}"
SOURCE_SERIES = {"nasdaq_comp_official": "NASDAQCOM", "cboe_vix_archive": "VIX", "us_treasury_yield_archive": "DGS2"}
NATIVE_SOURCE_SERIES = frozenset({"NASDAQCOM", "VIXCLS", "DGS2"})


class Daily6mSourcesError(ValueError):
    """A public source, immutable bundle, or append boundary failed validation."""


class Daily6mSourcePending(Daily6mSourcesError):
    """A valid official source has not published a completed target close yet."""


def _time(value: str | datetime | None = None) -> datetime:
    stamp = datetime.now(timezone.utc) if value is None else datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(stamp, datetime) or stamp.tzinfo is None or stamp.utcoffset() is None:
        raise Daily6mSourcesError("source timestamps require an explicit timezone")
    return stamp.astimezone(timezone.utc)


def _day(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) or date.fromisoformat(value).isoformat() != value:
        raise Daily6mSourcesError("invalid source observation date")
    return value


def _hash(value: Any) -> str:
    raw = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.is_file() else []


def _contained(base: Path, value: str) -> Path:
    if not isinstance(value, str) or Path(value).is_absolute():
        raise Daily6mSourcesError("raw locator must be relative")
    result = (base / value).resolve()
    if not result.is_relative_to(base.resolve()):
        raise Daily6mSourcesError("raw locator escapes its registered store")
    return result


def _payload(path: Path) -> bytes:
    if path.stat().st_size > MAX_BYTES:
        raise Daily6mSourcesError("compressed source exceeds size bound")
    with gzip.open(path, "rb") as handle:
        raw = handle.read(MAX_BYTES + 1)
    if not raw or len(raw) > MAX_BYTES:
        raise Daily6mSourcesError("source is empty or exceeds size bound")
    raw.decode("utf-8-sig", errors="strict")
    return raw


def _calendar(start: str, end: str):
    import exchange_calendars as xcals
    return xcals.get_calendar("XNAS", start=(date.fromisoformat(start) - timedelta(days=10)).isoformat(), end=(date.fromisoformat(end) + timedelta(days=10)).isoformat())


def last_completed_session(as_of: str | datetime) -> str:
    stamp = _time(as_of)
    start = (stamp.date() - timedelta(days=20)).isoformat()
    cal = _calendar(start, stamp.date().isoformat())
    completed = [s.date().isoformat() for s in cal.sessions_in_range(start, stamp.date().isoformat()) if cal.session_close(s).timestamp() + 900 <= stamp.timestamp()]
    if not completed:
        raise Daily6mSourcesError("no completed XNAS session")
    return completed[-1]


def _sessions(start: str, end: str) -> list[str]:
    if start > end:
        return []
    return [s.date().isoformat() for s in _calendar(start, end).sessions_in_range(start, end)]


def treasury_closed_session(day: str) -> bool:
    """Treasury's federal holidays can differ from the XNAS equity calendar."""
    from pandas.tseries.holiday import USFederalHolidayCalendar
    _day(day)
    return bool(len(USFederalHolidayCalendar().holidays(start=day, end=day)))


def _native_source_rows(root: Path) -> list[dict[str, Any]]:
    """Read the three immutable source series without parsing unrelated chunks.

    The native manifest already partitions by series. Preserve every revision
    of a selected series and the native reader's containment/hash/count guards;
    an issuance cutoff is applied only after reading its complete history.
    """
    from .timeseries import ledger as native_ledger
    ledger = root / native_ledger.LEDGER_RELATIVE
    rows = []
    legacy = ledger / native_ledger.OBSERVATIONS_NAME
    if legacy.is_file():
        with legacy.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    row = json.loads(line)
                    if row.get("series_id") in NATIVE_SOURCE_SERIES:
                        rows.append(row)
    manifest = ledger / native_ledger.OBSERVATION_MANIFEST_NAME
    if manifest.is_file():
        chunk_root = (root / native_ledger.FACTS_RELATIVE / native_ledger.OBSERVATION_CHUNKS_DIRECTORY).resolve()
        with manifest.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                item = json.loads(line)
                if item.get("series_id") not in NATIVE_SOURCE_SERIES:
                    continue
                path = (root / str(item["chunk_path"])).resolve()
                if not path.is_relative_to(chunk_root):
                    raise Daily6mSourcesError("selected native chunk escapes its registered root")
                if not path.is_file():
                    raise Daily6mSourcesError("selected native chunk is missing")
                body = gzip.decompress(path.read_bytes())
                digest = _hash(body)
                if digest != item["content_sha256"] or digest != item["chunk_id"]:
                    raise Daily6mSourcesError("selected native chunk hash mismatch")
                chunk_rows = [json.loads(value) for value in body.decode("utf-8").splitlines() if value]
                if type(item["row_count"]) is not int or len(chunk_rows) != item["row_count"]:
                    raise Daily6mSourcesError("selected native chunk row count mismatch")
                if any(row.get("series_id") != item["series_id"] for row in chunk_rows):
                    raise Daily6mSourcesError("selected native chunk series metadata mismatch")
                rows.extend(chunk_rows)
    return rows


def _native_at(root: Path, as_of: datetime) -> dict[str, dict[str, dict[str, Any]]]:
    from .timeseries import ledger as native_ledger
    ledger = root / native_ledger.LEDGER_RELATIVE
    if any((ledger / name).exists() for name in (native_ledger.OBSERVATIONS_NAME, native_ledger.OBSERVATION_MANIFEST_NAME)):
        # The Parquet view selects today's latest same-vintage correction. Its
        # earlier captured revision remains in immutable chunks, and is required
        # to replay an older source receipt without later revision leakage.
        records = _native_source_rows(root)
    else:
        import pyarrow.parquet as pq
        path = root / "data/timeseries/facts/observations.parquet"
        if not path.is_file():
            raise Daily6mSourcesError("existing native ALFRED baseline is required")
        columns = ["source_id", "series_id", "observation_time", "value", "value_status", "available_at", "vintage_start", "vintage_end", "retrieved_at", "source_hash"]
        records = pq.read_table(path, columns=columns, filters=[("source_id", "=", "alfred"), ("series_id", "in", ["NASDAQCOM", "VIXCLS", "DGS2"])]).to_pylist()
    result: dict[str, dict[str, dict[str, Any]]] = {sid: {} for sid in ("NASDAQCOM", "VIXCLS", "DGS2")}
    revisions = {}
    for row in records:
        if row["source_id"] != "alfred" or row["series_id"] not in result:
            continue
        if max(_time(row[k]) for k in ("available_at", "vintage_start", "retrieved_at")) > as_of:
            continue
        key = (row["series_id"], row["observation_time"], row["vintage_start"])
        prior = revisions.get(key)
        if prior is None or row.get("revision_seq", 0) > prior.get("revision_seq", 0):
            revisions[key] = row
    for row in revisions.values():
        # A correction to missing or to a closed vintage retires that numeric
        # revision before filtering; it must not resurrect an earlier value.
        if row["value_status"] != "ok" or (row.get("vintage_end") and _time(row["vintage_end"]) <= as_of):
            continue
        day = _day(str(row["observation_time"]))
        number = row["value"]
        if isinstance(number, bool) or not math.isfinite(number) or (row["series_id"] in {"NASDAQCOM", "VIXCLS"} and number <= 0) or not re.fullmatch(r"[a-f0-9]{64}", row.get("source_hash") or ""):
            raise Daily6mSourcesError("native baseline has invalid value or source hash")
        prior = result[row["series_id"]].get(day)
        if prior is None or (_time(row["vintage_start"]), _time(row["retrieved_at"]), row.get("revision_seq", 0)) > (_time(prior["vintage_start"]), _time(prior["retrieved_at"]), prior.get("revision_seq", 0)):
            result[row["series_id"]][day] = row
    if not result["NASDAQCOM"] or not result["DGS2"]:
        raise Daily6mSourcesError("eligible native Nasdaq and Treasury baselines are required")
    return result


def _number(value: Any, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise Daily6mSourcesError("boolean source value")
    result = float(str(value).replace(",", ""))
    if not math.isfinite(result) or (positive and result <= 0):
        raise Daily6mSourcesError("nonfinite or nonpositive source value")
    return result


def _nasdaq_json(raw: bytes) -> dict[str, Any]:
    value = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(value, dict) or not isinstance(value.get("status"), dict) or value["status"].get("rCode") != 200 or not isinstance(value.get("data"), dict) or value["data"].get("symbol") != "COMP":
        raise Daily6mSourcesError("Nasdaq response is not successful COMP JSON")
    return value["data"]


def _history(raw: bytes) -> dict[str, float]:
    data = _nasdaq_json(raw)
    table = data.get("tradesTable") or {}
    if not isinstance(table, dict) or not isinstance(table.get("headers"), dict) or table["headers"].get("close") != "Close/Last" or not isinstance(table.get("rows"), list) or not table["rows"]:
        raise Daily6mSourcesError("Nasdaq historical close table is missing")
    if type(data.get("totalRecords")) is not int or data["totalRecords"] != len(table["rows"]):
        raise Daily6mSourcesError("Nasdaq historical response is truncated")
    result = {}
    for row in table["rows"]:
        if not isinstance(row, dict):
            raise Daily6mSourcesError("Nasdaq historical row is not an object")
        day = datetime.strptime(row["date"], "%m/%d/%Y").date().isoformat()
        if day in result:
            raise Daily6mSourcesError("duplicate Nasdaq historical session")
        result[day] = _number(row["close"], positive=True)
    return result


def _source_values(source_id: str, raw: bytes, *, captured: datetime, native: dict, historical: bytes | None = None) -> tuple[list[tuple[str, float]], dict[str, Any]]:
    from .timeseries_v2.market_archive import parse_cboe_vix_csv, parse_treasury_xml
    completed = last_completed_session(captured)
    if source_id == "nasdaq_comp_official":
        data = _nasdaq_json(raw)
        primary = data.get("primaryData") or {}
        if not isinstance(primary, dict) or data.get("assetClass") not in {"INDEX", "index"} or data.get("exchange") != "Index" or data.get("marketStatus") not in {"Closed", "After-Hours", "Open", "Pre-Market"} or type(primary.get("isRealTime")) is not bool:
            raise Daily6mSourcesError("Nasdaq COMP must be a closed, non-realtime index")
        session = datetime.strptime(primary.get("lastTradeTimestamp", ""), "%b %d, %Y").date().isoformat()
        value = _number(primary.get("lastSalePrice"), positive=True)
        stats = data.get("keyStats")
        if not isinstance(stats, dict) or not isinstance(stats.get("previousclose"), dict):
            raise Daily6mSourcesError("Nasdaq previous close field is missing")
        prior = _number(stats["previousclose"].get("value"), positive=True)
        today = captured.astimezone(ZoneInfo("America/New_York")).date().isoformat()
        if session > today or session not in _sessions(session, session):
            raise Daily6mSourcesError("Nasdaq quote has an invalid future or nonexchange date")
        if historical is None:
            raise Daily6mSourcesError("Nasdaq historical identity receipt is required")
        history = _history(historical)
        if any(day > completed for day in history):
            raise Daily6mSourcesError("Nasdaq history contains an uncompleted session")
        overlap = sorted(set(history) & set(native["NASDAQCOM"]))[-20:]
        if len(overlap) < 5 or any(Decimal(str(history[d])) != Decimal(str(native["NASDAQCOM"][d]["value"])) for d in overlap):
            raise Daily6mSourcesError("Nasdaq history requires at least five exact native overlaps")
        if data["marketStatus"] in {"Open", "Pre-Market"}:
            raise Daily6mSourcePending("Nasdaq current market state has no final completed-session quote")
        if primary["isRealTime"] is not False:
            raise Daily6mSourcesError("Nasdaq closed index quote is unexpectedly realtime")
        if session != completed:
            raise Daily6mSourcePending("Nasdaq info has not published the latest completed XNAS session")
        previous = _sessions((date.fromisoformat(completed) - timedelta(days=14)).isoformat(), completed)[-2]
        if previous not in native["NASDAQCOM"]:
            raise Daily6mSourcesError("native previous-session close is missing")
        if Decimal(str(prior)) != Decimal(str(native["NASDAQCOM"][previous]["value"])):
            raise Daily6mSourcesError("Nasdaq previous close differs from native previous session")
        if "netChange" in primary and abs((Decimal(str(value)) - Decimal(str(prior))) - Decimal(str(_number(primary["netChange"])))) > Decimal("0.000001"):
            raise Daily6mSourcesError("Nasdaq close and net change disagree")
        if max(native["NASDAQCOM"]) not in {previous, completed}:
            raise Daily6mSourcesError("Nasdaq tail cannot bridge an older native gap")
        if completed in native["NASDAQCOM"] and Decimal(str(value)) != Decimal(str(native["NASDAQCOM"][completed]["value"])):
            raise Daily6mSourcesError("Nasdaq current native close and official close disagree")
        return [(completed, value)], {"historical_overlap_count": len(overlap), "previous_session": previous, "previous_native_close": prior}
    if source_id == "cboe_vix_archive":
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        if not reader.fieldnames or not {"DATE", "CLOSE"}.issubset({s.upper() for s in reader.fieldnames}):
            raise Daily6mSourcesError("CBOE DATE/CLOSE CSV schema missing")
        rows = parse_cboe_vix_csv(raw)
        sid = "VIXCLS"
    elif source_id == "us_treasury_yield_archive":
        rows = [(day, two) for day, two, _ in parse_treasury_xml(raw)]
        sid = "DGS2"
    else:
        raise Daily6mSourcesError("unregistered captured source")
    values = {}
    for day, value in rows:
        _day(day)
        number = _number(value, positive=source_id == "cboe_vix_archive")
        if day in values or day > completed:
            raise Daily6mSourcesError("source has duplicate or uncompleted session")
        values[day] = number
    if not values:
        raise Daily6mSourcesError("official archive has no typed observations")
    overlap = sorted(set(values) & set(native[sid]))[-20:]
    if (source_id == "us_treasury_yield_archive" and len(overlap) < 5) or any(Decimal(str(values[d])) != Decimal(str(native[sid][d]["value"])) for d in overlap):
        raise Daily6mSourcesError("official archive differs from its native series overlap")
    if source_id == "cboe_vix_archive":
        if completed not in values:
            raise Daily6mSourcePending("official CBOE latest completed close is not published")
        return [(completed, values[completed])], {"native_overlap_count": len(overlap)}
    end = max(native[sid])
    sessions = _sessions(end, completed)
    bridge = [day for day in sessions if day > end]
    if len(bridge) > 5:
        raise Daily6mSourcesError("Treasury bridge exceeds five XNAS sessions")
    expected = [day for day in bridge if not treasury_closed_session(day)]
    missing = [day for day in expected if day not in values]
    if any(day < max(values) for day in missing):
        raise Daily6mSourcesError("Treasury published bridge has an unexplained missing session")
    if missing:
        raise Daily6mSourcePending("Treasury latest completed bridge quotes are not published")
    if any(day in values for day in bridge if treasury_closed_session(day)):
        raise Daily6mSourcesError("Treasury archive has a value on a registered federal closure")
    return [(day, values[day]) for day in expected], {"native_overlap_count": len(overlap), "native_end": end, "bridge_sessions": bridge, "closed_sessions": [d for d in bridge if treasury_closed_session(d)]}


def _urls(stamp: datetime) -> dict[str, tuple[str, str]]:
    return {
        "nasdaq_history": ("nasdaq_comp_official", NASDAQ_HISTORY + "?" + urlencode({"assetclass": "index", "fromdate": (stamp.date() - timedelta(days=30)).isoformat(), "todate": stamp.date().isoformat(), "limit": 100})),
        "nasdaq_info": ("nasdaq_comp_official", NASDAQ_INFO),
        "cboe": ("cboe_vix_archive", CBOE_URL),
        "treasury": ("us_treasury_yield_archive", TREASURY_URL.format(year=stamp.year)),
    }


def _check_uri(kind: str, uri: str, stamp: datetime) -> None:
    if uri not in {_urls(stamp)[kind][1], _urls(stamp - timedelta(days=1))[kind][1]}:
        raise Daily6mSourcesError("source URI differs from its registered credential-free request")
    parts = urlsplit(uri)
    if parts.scheme != "https" or parts.username or parts.password or parts.fragment or any(k.lower() in {"key", "api_key", "token", "authorization"} for k in parse_qs(parts.query)):
        raise Daily6mSourcesError("source URI is not public HTTPS")


class _Redirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 3
    max_repeats = 2

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old, new = urlsplit(req.full_url), urlsplit(newurl)
        registered_cboe = req.full_url == CBOE_URL and newurl == CBOE_RESPONSE_URL and code == 307
        if new.scheme != "https" or (new.hostname != old.hostname and not registered_cboe) or new.username or new.password or new.port not in {None, 443} or new.fragment:
            raise Daily6mSourcesError("source redirect leaves its official HTTPS host")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _response_uri(request_uri: str, response_uri: str) -> None:
    if response_uri != request_uri and (request_uri, response_uri) != (CBOE_URL, CBOE_RESPONSE_URL):
        raise Daily6mSourcesError("source response URI differs from its exact registered redirect")


def _fetch(url: str) -> tuple[int, bytes, str, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json,text/csv,application/xml,text/xml", "Accept-Encoding": "identity"})
    with urllib.request.build_opener(_Redirect()).open(req, timeout=20) as response:
        _response_uri(url, response.url)
        return response.status, response.read(MAX_BYTES + 1), response.headers.get("Content-Type", ""), response.url


def _receipt(kind: str, source: str, uri: str, raw: bytes, stamp: datetime, requested: datetime, status: int, content_type: str, response_uri: str | None = None) -> dict[str, Any]:
    response_uri = uri if response_uri is None else response_uri
    _response_uri(uri, response_uri)
    seed = {"kind": kind, "source_id": source, "source_uri": uri, "response_uri": response_uri, "retrieved_at": stamp.isoformat(), "requested_at": requested.isoformat(), "http_status": status, "raw_sha256": _hash(raw), "byte_count": len(raw), "content_type": content_type}
    return {**seed, "receipt_id": "daily6m-receipt-" + _hash(seed)[:32], "raw_path": str(STORE / "raw" / source / (_hash(raw) + ".gz")).replace("\\", "/")}


def _verify_receipt(receipt: dict, raw: bytes, *, allow_legacy: bool = False) -> None:
    expected = _receipt(receipt["kind"], receipt["source_id"], receipt["source_uri"], raw, _time(receipt["retrieved_at"]), _time(receipt["requested_at"]), receipt["http_status"], receipt["content_type"], receipt.get("response_uri", receipt["source_uri"]))
    if "response_uri" not in receipt:
        if not allow_legacy:
            raise Daily6mSourcesError("new source receipts require the actual response URI")
        # Existing direct-host receipts predate the explicit redirect field.
        # Preserve their identity bytes; do not invent an observed final URI.
        expected.pop("response_uri")
        seed = {k: v for k, v in expected.items() if k not in {"receipt_id", "raw_path"}}
        expected["receipt_id"] = "daily6m-receipt-" + _hash(seed)[:32]
    if receipt != expected:
        raise Daily6mSourcesError("receipt identity, size, or raw hash mismatch")


def _candidate(source: str, day: str, value: float, receipt: dict, validation: dict, dependencies: list[str]) -> dict:
    return {"source_id": source, "series_id": SOURCE_SERIES[source], "observation_time": day, "value": value, "unit": "percent" if source == "us_treasury_yield_archive" else "index", "data_grade": "captured_forward", "available_at": receipt["retrieved_at"], "vintage_start": receipt["retrieved_at"], "vintage_end": None, "raw_sha256": receipt["raw_sha256"], "receipt_id": receipt["receipt_id"], "validation_receipt_ids": dependencies, "validation": validation}


def _replay(root: Path, manifest: dict, payloads: dict[str, bytes]) -> tuple[list[dict], list[dict], list[dict]]:
    receipts = {r["kind"]: r for r in manifest["receipts"]}
    candidates, failures, pending = [], [], []
    for kind in ("nasdaq_info", "cboe", "treasury"):
        if kind not in receipts:
            failures.append({"kind": kind, "reason": "missing_response"})
            continue
        receipt = receipts[kind]
        try:
            if receipt["http_status"] != 200:
                raise Daily6mSourcesError("source HTTP status is not 200")
            captured = _time(receipt["retrieved_at"])
            native = _native_at(root, captured)
            history = receipts.get("nasdaq_history")
            if kind == "nasdaq_info" and (history is None or history["http_status"] != 200):
                raise Daily6mSourcesError("successful Nasdaq history response is required")
            if kind == "nasdaq_info" and _time(history["retrieved_at"]) > captured:
                raise Daily6mSourcesError("Nasdaq historical identity capture is after the primary close capture")
            values, validation = _source_values(receipt["source_id"], payloads[receipt["receipt_id"]], captured=captured, native=native, historical=payloads[history["receipt_id"]] if kind == "nasdaq_info" else None)
            dependencies = [history["receipt_id"]] if kind == "nasdaq_info" else []
            candidates.extend(_candidate(receipt["source_id"], day, value, receipt, validation, dependencies) for day, value in values)
        except Daily6mSourcePending as exc:
            pending.append({"kind": kind, "reason": str(exc)[:240]})
        except (ValueError, TypeError, KeyError, OSError, RuntimeError, ET.ParseError, csv.Error) as exc:
            failures.append({"kind": kind, "reason": str(exc)[:240]})
    return candidates, failures, pending


def _report(value: dict) -> dict:
    if len(_json(value)) > MAX_REPORT_BYTES:
        raise Daily6mSourcesError("source report exceeds its bounded size")
    return value


def capture_daily6m_sources(root: Path, *, output_dir: Path | str, now: str | datetime | None = None, clock: Callable[[], datetime] | None = None, fetcher: Callable | None = None) -> dict:
    """Capture four public responses in an immutable, credential-free bundle."""
    root = Path(root)
    tick = clock or (lambda: datetime.now(timezone.utc))
    started = _time(now if now is not None else tick())
    target = Path(output_dir)
    if not target.is_absolute():
        target = root / target
    if target.resolve().is_relative_to((root / STORE).resolve()):
        raise Daily6mSourcesError("capture output must be outside the canonical research source store")
    if target.exists() and any(target.iterdir()):
        raise Daily6mSourcesError("capture directory must be empty")
    target.mkdir(parents=True, exist_ok=True)
    receipts, payloads, transport = [], {}, []
    for kind, (source, uri) in _urls(started).items():
        requested = _time(tick())
        try:
            response = (fetcher or _fetch)(uri)
            status, raw = response[:2]
            content_type = response[2] if len(response) > 2 else "application/json" if kind.startswith("nasdaq") else "text/csv" if kind == "cboe" else "application/xml"
            captured = _time(tick())
            if captured < requested or requested < started or not isinstance(raw, bytes) or not raw or len(raw) > MAX_BYTES:
                raise Daily6mSourcesError("invalid response payload size or completion clock")
            raw.decode("utf-8-sig", errors="strict")
            receipt = _receipt(kind, source, uri, raw, captured, requested, status, content_type, response[3] if len(response) > 3 else uri)
            path = _contained(target, receipt["raw_path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            compressed = gzip.compress(raw, mtime=0)
            if path.exists() and _payload(path) != raw:
                raise Daily6mSourcesError("immutable raw content collision")
            if not path.exists():
                path.write_bytes(compressed)
            receipts.append(receipt)
            payloads[receipt["receipt_id"]] = raw
        except (ValueError, TypeError, KeyError, OSError, RuntimeError) as exc:
            transport.append({"kind": kind, "reason": type(exc).__name__ + ": " + str(exc)[:180]})
    completed = _time(tick())
    if completed < started or any(_time(r["retrieved_at"]) > completed for r in receipts):
        raise Daily6mSourcesError("capture completion clock is inconsistent")
    manifest = {"schema_version": SCHEMA, "started_at": started.isoformat(), "completed_at": completed.isoformat(), "receipts": receipts, "transport_failures": transport}
    candidates, failures, pending = _replay(root, manifest, payloads)
    manifest.update(candidates=candidates, source_failures=failures, source_pending=pending)
    manifest["bundle_id"] = "daily6m-source-bundle-" + _hash(manifest)[:32]
    manifest["content_hash"] = _hash(manifest)
    (target / "manifest.json").write_bytes(_json(manifest))
    active = {(r["source_id"], r["series_id"], r["observation_time"]): r for r in _rows(root / OBSERVATIONS)}
    changed = any((prior := active.get((r["source_id"], r["series_id"], r["observation_time"]))) is None or (prior["value"], prior["unit"]) != (r["value"], r["unit"]) for r in candidates)
    report = _report({"status": "partial" if failures else "captured", "changed": changed, "appended": 0, "bundle_id": manifest["bundle_id"], "completed_at": completed.isoformat(), "receipts": len(receipts), "observations": len(candidates), "source_failures": failures, "source_pending": pending, "transport_failures": transport})
    (target / "report.json").write_bytes(_json(report))
    return report


def _validate_bundle(root: Path, target: Path, now: datetime) -> tuple[dict, list[dict], dict[str, bytes]]:
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SCHEMA or manifest.get("content_hash") != _hash({k: v for k, v in manifest.items() if k != "content_hash"}):
        raise Daily6mSourcesError("immutable bundle schema or content hash mismatch")
    if manifest.get("bundle_id") != "daily6m-source-bundle-" + _hash({k: v for k, v in manifest.items() if k not in {"content_hash", "bundle_id"}})[:32]:
        raise Daily6mSourcesError("immutable bundle identity mismatch")
    started, completed = _time(manifest["started_at"]), _time(manifest["completed_at"])
    if not started <= completed <= now:
        raise Daily6mSourcesError("bundle completion is after apply time")
    receipts, payloads, seen = manifest["receipts"], {}, set()
    if not isinstance(receipts, list) or len(receipts) > 4:
        raise Daily6mSourcesError("bundle has an invalid receipt roster")
    for receipt in receipts:
        kind = receipt["kind"]
        if kind in seen or kind not in _urls(started) or receipt["source_id"] != _urls(started)[kind][0]:
            raise Daily6mSourcesError("bundle has duplicate or unregistered receipts")
        seen.add(kind)
        _check_uri(kind, receipt["source_uri"], started)
        requested, captured = _time(receipt["requested_at"]), _time(receipt["retrieved_at"])
        if not started <= requested <= captured <= completed:
            raise Daily6mSourcesError("receipt has an impossible request/completion time")
        path = _contained(target, receipt["raw_path"])
        registered = target / STORE / "raw" / receipt["source_id"]
        if path.parent.resolve() != registered.resolve() or path.name != receipt["raw_sha256"] + ".gz":
            raise Daily6mSourcesError("raw path differs from its registered source/hash")
        raw = _payload(path)
        _verify_receipt(receipt, raw)
        payloads[receipt["receipt_id"]] = raw
    candidates, failures, pending = _replay(root, manifest, payloads)
    if candidates != manifest.get("candidates") or failures != manifest.get("source_failures") or pending != manifest.get("source_pending"):
        raise Daily6mSourcesError("bundle decisions differ from independent raw replay")
    return manifest, candidates, payloads


def _append(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _revision(candidate: dict, prior: dict | None) -> dict:
    body = {**candidate, "revision_seq": 1 if prior is None else prior["revision_seq"] + 1, "supersedes": None if prior is None else prior["observation_id"]}
    return {"observation_id": "daily6m-observation-" + _hash(body)[:32], **body}


def apply_daily6m_sources(root: Path, *, bundle_dir: Path | str, now: str | datetime | None = None) -> dict:
    """Replay against this checkout, then append valid changed source observations."""
    from .timeseries_daily6m.pipeline import writer_lock
    root = Path(root)
    target = Path(bundle_dir)
    if not target.is_absolute():
        target = root / target
    cutoff = _time(now)
    with writer_lock(root):
        manifest, candidates, payloads = _validate_bundle(root, target, cutoff)
        # Validate existing history before any durable source-store write.
        load_verified_source_observations(root, as_of=cutoff)
        old = _rows(root / OBSERVATIONS)
        latest = {}
        for row in old:
            latest[(row["source_id"], row["series_id"], row["observation_time"])] = row
        pending, stale, unchanged = [], 0, 0
        for candidate in candidates:
            key = (candidate["source_id"], candidate["series_id"], candidate["observation_time"])
            prior = latest.get(key)
            if prior and _time(prior["available_at"]) > _time(candidate["available_at"]):
                stale += 1
                continue
            if prior and prior["value"] == candidate["value"] and prior["unit"] == candidate["unit"]:
                unchanged += 1
                continue
            if prior and _time(prior["available_at"]) == _time(candidate["available_at"]):
                raise Daily6mSourcesError("conflicting source revisions have the same completion time")
            row = _revision(candidate, prior)
            pending.append(row)
            latest[key] = row
        needed = {r for row in pending for r in [row["receipt_id"], *row["validation_receipt_ids"]]}
        existing_receipts = {r["receipt_id"]: r for r in _rows(root / RECEIPTS)}
        receipts = [r for r in manifest["receipts"] if r["receipt_id"] in needed and r["receipt_id"] not in existing_receipts]
        # Preflight every destination before appending either ledger.
        for receipt in receipts:
            path = _contained(root, receipt["raw_path"])
            if path.exists() and _payload(path) != payloads[receipt["receipt_id"]]:
                raise Daily6mSourcesError("canonical raw content collision")
        for receipt in receipts:
            path = _contained(root, receipt["raw_path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_bytes(gzip.compress(payloads[receipt["receipt_id"]], mtime=0))
        _append(root / RECEIPTS, receipts)
        _append(root / OBSERVATIONS, pending)
        return _report({"status": "partial" if manifest["source_failures"] else "applied", "changed": bool(pending), "appended": len(pending), "unchanged": unchanged, "stale_ignored": stale, "bundle_id": manifest["bundle_id"], "completed_at": manifest["completed_at"], "receipts": len(receipts), "observations": len(candidates), "source_failures": manifest["source_failures"], "source_pending": manifest["source_pending"], "transport_failures": manifest["transport_failures"]})


def load_verified_source_observations(root: Path, *, as_of: str | datetime) -> list[dict]:
    """Read immutable observations with verified source bytes and receipt metadata."""
    root, cutoff = Path(root), _time(as_of)
    receipts = _rows(root / RECEIPTS)
    by_id, payloads = {}, {}
    for receipt in receipts:
        if receipt["receipt_id"] in by_id:
            raise Daily6mSourcesError("duplicate source receipt ID")
        captured = _time(receipt["retrieved_at"])
        kind = receipt["kind"]
        _check_uri(kind, receipt["source_uri"], _time(receipt["requested_at"]))
        if receipt["source_id"] != _urls(captured)[kind][0] or receipt["http_status"] != 200:
            raise Daily6mSourcesError("invalid durable source receipt")
        path = _contained(root, receipt["raw_path"])
        if path.parent != (root / STORE / "raw" / receipt["source_id"]).resolve() or path.name != receipt["raw_sha256"] + ".gz":
            raise Daily6mSourcesError("durable raw source locator mismatch")
        raw = _payload(path)
        _verify_receipt(receipt, raw, allow_legacy=True)
        by_id[receipt["receipt_id"]], payloads[receipt["receipt_id"]] = receipt, raw
    latest, output, replayed = {}, [], {}
    for row in _rows(root / OBSERVATIONS):
        body = {k: v for k, v in row.items() if k != "observation_id"}
        if row["observation_id"] != "daily6m-observation-" + _hash(body)[:32]:
            raise Daily6mSourcesError("source observation identity mismatch")
        receipt = by_id.get(row["receipt_id"])
        if receipt is None or row["source_id"] != receipt["source_id"] or row["raw_sha256"] != receipt["raw_sha256"] or row["data_grade"] != "captured_forward" or row["vintage_end"] is not None or any(_time(row[k]) != _time(receipt["retrieved_at"]) for k in ("available_at", "vintage_start")):
            raise Daily6mSourcesError("observation and actual capture receipt disagree")
        key = (row["source_id"], row["series_id"], row["observation_time"])
        prior = latest.get(key)
        if row["revision_seq"] != (1 if prior is None else prior["revision_seq"] + 1) or row["supersedes"] != (None if prior is None else prior["observation_id"]) or (prior and _time(row["available_at"]) <= _time(prior["available_at"])):
            raise Daily6mSourcesError("source revision does not supersede the active earlier revision")
        latest[key] = row
        rid = receipt["receipt_id"]
        if rid not in replayed:
            deps = row["validation_receipt_ids"]
            history = by_id.get(deps[0]) if len(deps) == 1 else None
            if (receipt["kind"] == "nasdaq_info") != (history is not None) or (history is not None and (history["kind"] != "nasdaq_history" or _time(history["retrieved_at"]) > _time(receipt["retrieved_at"]))):
                raise Daily6mSourcesError("Nasdaq historical identity receipt linkage is invalid")
            values, validation = _source_values(row["source_id"], payloads[rid], captured=_time(receipt["retrieved_at"]), native=_native_at(root, _time(receipt["retrieved_at"])), historical=payloads[history["receipt_id"]] if history else None)
            replayed[rid] = [_candidate(row["source_id"], day, value, receipt, validation, deps) for day, value in values]
        candidate = {k: v for k, v in row.items() if k not in {"observation_id", "revision_seq", "supersedes"}}
        if candidate not in replayed[rid]:
            raise Daily6mSourcesError("stored observation differs from its immutable official raw payload")
        if _time(receipt["retrieved_at"]) <= cutoff:
            count = row["validation"].get("historical_overlap_count", row["validation"].get("native_overlap_count", 0))
            output.append({**row, "retrieved_at": receipt["retrieved_at"], "receipt_raw_path": receipt["raw_path"], "receipt_source_uri": receipt["source_uri"], "receipt_response_uri": receipt.get("response_uri"), "receipt_response_uri_recorded": "response_uri" in receipt, "receipt_verified": True, "receipt_http_status": receipt["http_status"], "source_unit": row["unit"], "native_overlap_verified": True, "native_overlap_count": count, "native_overlap_max_abs_delta": 0.0})
    return output
