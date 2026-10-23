"""Free seven-indicator display feed; independent of the headline-index ledger.

The publisher explicitly documents this unauthenticated endpoint and permits reuse
at https://feargreedflow.com/data. Preserve the response before parsing; keep every
successful revision. A failed/stale feed must never expose the September seed as
the current seven readings. This module is not a forecast input.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ENDPOINT = "https://feargreedflow.com/api/fear-greed"
SOURCE = "feargreedflow_seven_indicators"
BASE = Path("data/fear_greed/components")
MAX_AGE = timedelta(hours=96)  # includes a US holiday weekend; always display timestamp
KEYS = (
    "market_momentum_sp500", "stock_price_strength", "stock_price_breadth",
    "put_call_options", "market_volatility_vix", "junk_bond_demand", "safe_haven_demand",
)
META = (
    ("주가 모멘텀", "S&P 500 지수", "S&P 500 과 125일 이동평균의 거리"),
    ("주가 강도", "신고가−신저가 (%)", "52주 신고가 종목이 신저가보다 얼마나 많은가"),
    ("주가 폭", "McClellan 거래량", "오르는 종목과 내리는 종목의 거래량"),
    ("풋/콜 비율", "5일 평균", "풋 거래가 콜보다 많으면 공포"),
    ("시장 변동성", "VIX", "VIX 와 50일 이동평균의 거리"),
    ("정크본드 수요", "스프레드 (%p)", "위험 채권에 요구하는 금리 차이"),
    ("안전자산 선호", "주식−채권 수익률차 (%p)", "최근 20일 주식과 채권 수익률 차이"),
)


class ComponentsError(ValueError):
    pass


def _bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ComponentsError("non-finite or non-numeric source value")
    return float(value)


def _timestamp(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError("timezone missing")
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ComponentsError("source timestamp invalid") from exc


def _series(dates: Any, values: Any, cutoff: datetime) -> tuple[dict[str, float], int]:
    if not isinstance(dates, list) or not isinstance(values, list) or not dates or len(dates) != len(values):
        raise ComponentsError("source date/value lengths invalid")
    rows: dict[str, float] = {}
    previous = ""
    duplicates = 0
    for day, value in zip(dates, values):
        try:
            if not isinstance(day, str) or datetime.strptime(day, "%Y-%m-%d").strftime("%Y-%m-%d") != day:
                raise ValueError("date")
        except ValueError as exc:
            raise ComponentsError("source date invalid") from exc
        if day < previous or day > cutoff.date().isoformat():
            raise ComponentsError("unordered or future source date")
        duplicates += int(day in rows)
        # The documented feed can end with a same-session live update. Preserve
        # both in raw; explicitly select its last occurrence in this read model.
        rows[day] = _number(value)
        previous = day
    return rows, duplicates


def normalize(raw: bytes, *, now: datetime) -> dict[str, Any]:
    try:
        source = json.loads(raw)
        asof = _timestamp(source["asOf"])
        if asof > now + timedelta(minutes=5) or now - asof > MAX_AGE:
            raise ComponentsError("headline source timestamp stale or future")
        headline, duplicates = _series(source["dates"], source["values"], asof)
        if any(not 0 <= v <= 100 for v in headline.values()):
            raise ComponentsError("headline outside 0–100")
        result = {}
        for key, (label, unit, hint) in zip(KEYS, META):
            component = source["indicators"][key]
            score = _number(component["score"])
            if not 0 <= score <= 100:
                raise ComponentsError(f"{key}: score outside 0–100")
            rating = str(component["rating"]).replace(" ", "_")
            if rating not in {"extreme_fear", "fear", "neutral", "greed", "extreme_greed"}:
                raise ComponentsError(f"{key}: rating invalid")
            stamp = datetime.fromtimestamp(_number(component["asOf"]) / 1000, timezone.utc)
            if stamp > now + timedelta(minutes=5) or now - stamp > MAX_AGE:
                raise ComponentsError(f"{key}: timestamp stale or future")
            rows, count = _series(component["dates"], component["values"], stamp)
            if list(rows)[-1] != stamp.date().isoformat():
                raise ComponentsError(f"{key}: score and raw-series dates differ")
            dates = list(rows)[-260:]
            result[key] = {"label": label, "unit": unit, "hint": hint,
                           "score": score, "rating": rating, "observed_at": stamp.isoformat(),
                           "observed_date": dates[-1], "dates": dates,
                           "series": [rows[d] for d in dates], "duplicate_session_updates": count}
        return {"schema_version": 1, "source": SOURCE, "source_url": ENDPOINT,
                "source_as_of": asof.isoformat(), "components": result,
                "components_observed_through": min(c["observed_date"] for c in result.values()),
                "headline_at_source": list(headline.values())[-1],
                "duplicate_session_policy": "last_source_occurrence",
                "headline_duplicate_session_updates": duplicates,
                "display_only": True, "model_use": False,
                "license_url": "https://feargreedflow.com/data"}
    except (KeyError, TypeError, json.JSONDecodeError, OverflowError, OSError) as exc:
        raise ComponentsError("seven-indicator source schema invalid") from exc


def _immutable(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ComponentsError("immutable component file collision")
        return
    with path.open("xb") as handle:
        handle.write(raw)


def _atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_bytes(_bytes(value))
    os.replace(temporary, path)


def refresh(root: Path, *, now: datetime | None = None, raw: bytes | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    directory = root / BASE
    try:
        if raw is None:
            for attempt in range(3):
                try:
                    request = urllib.request.Request(ENDPOINT, headers={
                        "User-Agent": "JinsInvestingResearch/1.0", "Accept": "application/json"})
                    with urllib.request.urlopen(request, timeout=25) as response:
                        if response.status != 200:
                            raise ComponentsError("component HTTP status invalid")
                        raw = response.read(2_000_001)
                    break
                except (OSError, TimeoutError):
                    if attempt == 2:
                        raise
                    time.sleep(attempt + 1)
        if len(raw) > 2_000_000:
            raise ComponentsError("component response exceeds byte budget")
        raw_sha = _sha(raw)
        raw_path = directory / "raw" / f"{raw_sha}.json.gz"
        # gzip headers may differ between Windows and Linux. Identity is the
        # uncompressed response, so preserve existing gzip bytes on every replay.
        if raw_path.exists():
            if gzip.decompress(raw_path.read_bytes()) != raw:
                raise ComponentsError("immutable raw response collision")
        else:
            _immutable(raw_path, gzip.compress(raw, mtime=0))
        receipt_path = directory / "receipts" / f"{raw_sha}.json"
        if not receipt_path.exists():
            _immutable(receipt_path, _bytes({
                "source": SOURCE, "source_url": ENDPOINT, "raw_sha256": raw_sha,
                "bytes": len(raw), "available_at": now.isoformat(), "http_status": 200}))
        available_at = json.loads(receipt_path.read_bytes())["available_at"]
        payload = normalize(raw, now=now)
        old_path = directory / "latest.json"
        old = json.loads(old_path.read_bytes()) if old_path.exists() else {}
        if old:
            old_snapshot = old.get("snapshot_id", "")
            if not isinstance(old_snapshot, str) or len(old_snapshot) != 64 or any(c not in "0123456789abcdef" for c in old_snapshot):
                raise ComponentsError("existing component pointer invalid")
            previous = json.loads((directory / "snapshots" / f"{old_snapshot}.json").read_bytes())
            projection(root, now=_timestamp(previous["available_at"]), check_attempt=False, strict=True)
            if _timestamp(payload["source_as_of"]) < _timestamp(previous["source_as_of"]):
                raise ComponentsError("component source timestamp regressed")
            if now < _timestamp(previous["available_at"]):
                raise ComponentsError("component acquisition clock regressed")
        # Identical source bytes do not append another observation/revision.
        if old.get("raw_sha256") == raw_sha:
            projection(root, now=now, check_attempt=False, strict=True)
            status_path = directory / "status.json"
            status = json.loads(status_path.read_bytes()) if status_path.exists() else {}
            if status.get("status") != "ok" or status.get("snapshot_id") != old["snapshot_id"]:
                _atomic(status_path, {"status": "ok", "checked_at": now.isoformat(),
                                     "snapshot_id": old["snapshot_id"]})
            return old
        payload.update(raw_sha256=raw_sha, available_at=now.isoformat(), raw_first_acquired_at=available_at,
                       revision=old.get("revision", 0) + 1, supersedes=old.get("snapshot_id"))
        body = _bytes(payload)
        snapshot = _sha(body)
        _immutable(directory / "snapshots" / f"{snapshot}.json", body)
        pointer = {"snapshot_id": snapshot, "sha256": snapshot, "raw_sha256": raw_sha,
                   "revision": payload["revision"], "source_as_of": payload["source_as_of"]}
        _atomic(old_path, pointer)
        _atomic(directory / "status.json", {"status": "ok", "checked_at": now.isoformat(),
                                            "snapshot_id": snapshot})
        return pointer
    except Exception as exc:
        _atomic(directory / "status.json", {"status": "failed", "checked_at": now.isoformat(),
                                            "reason": f"{type(exc).__name__}: {exc}"[:240]})
        raise


def projection(root: Path, *, now: datetime | None = None, check_attempt: bool = True,
               strict: bool = False) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    directory = root / BASE
    absent = {"status": "unavailable", "components": {}, "components_refresh_policy": "automatic",
              "source": SOURCE, "source_url": ENDPOINT}
    try:
        pointer = json.loads((directory / "latest.json").read_bytes())
        snapshot = pointer["snapshot_id"]
        if not isinstance(snapshot, str) or len(snapshot) != 64 or any(c not in "0123456789abcdef" for c in snapshot):
            raise ComponentsError("invalid snapshot ID")
        body = (directory / "snapshots" / f"{snapshot}.json").read_bytes()
        if _sha(body) != snapshot or pointer["sha256"] != snapshot:
            raise ComponentsError("component snapshot hash mismatch")
        raw_sha = pointer["raw_sha256"]
        if not isinstance(raw_sha, str) or len(raw_sha) != 64 or any(c not in "0123456789abcdef" for c in raw_sha):
            raise ComponentsError("invalid raw ID")
        raw = gzip.decompress((directory / "raw" / f"{raw_sha}.json.gz").read_bytes())
        receipt = json.loads((directory / "receipts" / f"{raw_sha}.json").read_bytes())
        if _sha(raw) != raw_sha or receipt["raw_sha256"] != raw_sha or receipt["bytes"] != len(raw):
            raise ComponentsError("component raw receipt mismatch")
        payload = json.loads(body)
        normalized = normalize(raw, now=now)
        if payload["raw_sha256"] != raw_sha or payload.get("raw_first_acquired_at", payload["available_at"]) != receipt["available_at"]:
            raise ComponentsError("component provenance mismatch")
        if _timestamp(receipt["available_at"]) > _timestamp(payload["available_at"]):
            raise ComponentsError("component revision predates raw acquisition")
        if pointer["source_as_of"] != payload["source_as_of"]:
            raise ComponentsError("component pointer source timestamp mismatch")
        if receipt.get("source") != SOURCE or receipt.get("source_url") != ENDPOINT or receipt.get("http_status") != 200:
            raise ComponentsError("component source receipt mismatch")
        if _timestamp(payload["available_at"]) > now:
            raise ComponentsError("component capture was not yet available")
        revision, supersedes = payload.get("revision"), payload.get("supersedes")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1 or pointer["revision"] != revision:
            raise ComponentsError("component revision invalid")
        if revision == 1:
            if supersedes is not None:
                raise ComponentsError("initial component revision has a predecessor")
        else:
            if not isinstance(supersedes, str) or len(supersedes) != 64 or any(c not in "0123456789abcdef" for c in supersedes):
                raise ComponentsError("component predecessor invalid")
            previous_body = (directory / "snapshots" / f"{supersedes}.json").read_bytes()
            previous = json.loads(previous_body)
            if _sha(previous_body) != supersedes or previous["revision"] != revision - 1:
                raise ComponentsError("component revision chain mismatch")
            if _timestamp(previous["available_at"]) > _timestamp(payload["available_at"]):
                raise ComponentsError("component revision acquisition order invalid")
        if any(payload[k] != value for k, value in normalized.items()):
            raise ComponentsError("component raw-to-read-model mismatch")
        if check_attempt:
            attempt = json.loads((directory / "status.json").read_bytes())
            if attempt["status"] != "ok" or attempt["snapshot_id"] != snapshot:
                raise ComponentsError("latest collection failed; retained snapshot is not current")
        return {**payload, "components": normalized["components"], "snapshot_id": snapshot, "status": "live",
                "components_refresh_policy": "automatic", "license_status": "publisher_free_api"}
    except (OSError, ValueError, KeyError, TypeError, EOFError) as exc:
        if strict:
            raise
        return {**absent, "reason": str(exc)[:240]}
