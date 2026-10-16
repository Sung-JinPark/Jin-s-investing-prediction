"""Receipt-backed, append-only market-context facts with bitemporal reads."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from . import contracts as C

BASE = Path("data/market_context")
EVENTS = BASE / "events.jsonl"
RECEIPTS = BASE / "raw_receipts.jsonl"
OBSERVATIONS = BASE / "market_observations.jsonl"
SOURCE_STATUS = BASE / "source_status.jsonl"
REJECTIONS = BASE / "rejected_observations.jsonl"


def timestamp(value: Any, field: str = "timestamp") -> datetime:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise C.MarketContextError(f"{field} must be an ISO timestamp") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise C.MarketContextError(f"{field} must include a timezone")
    return result.astimezone(timezone.utc)


def digest(row: Any) -> str:
    return hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def incident_group_id(row: dict[str, Any]) -> str:
    """Identify the same disclosed fact independently of syndication URLs."""
    family = str(row.get("family", ""))
    period = row.get("reference_period")
    payload = row.get("fact_payload")
    supplied_hashes = [row[key] for key in ("fact_sha256", "fact_hash", "payload_fact_hash") if row.get(key) is not None]
    if len({str(value) for value in supplied_hashes}) > 1:
        raise C.MarketContextError("conflicting explicit fact hashes")
    supplied = supplied_hashes[0] if supplied_hashes else None
    if supplied is not None and not re.fullmatch(r"[0-9a-f]{64}", str(supplied)):
        raise C.MarketContextError("fact hash must be explicit lowercase SHA256")
    if payload is not None:
        if not isinstance(payload, dict) or not payload:
            raise C.MarketContextError("fact_payload must be a non-empty structured object")
        fact_hash = digest(payload)
        if supplied is not None and supplied != fact_hash:
            raise C.MarketContextError("fact payload/hash mismatch")
        key = {"family": family, "period": period, "fact_sha256": fact_hash}
    elif supplied is not None:
        key = {"family": family, "period": period, "fact_sha256": supplied}
    else:
        mapping, units = row.get("mapping") or {}, row.get("unit_metadata") or {}
        if not isinstance(mapping, dict) or not isinstance(units, dict):
            raise C.MarketContextError("fact mapping and units must be objects")
        metric = row.get("metric") or row.get("series_id") or mapping.get("metric")
        unit = units.get("actual")
        if row.get("actual") is not None and period and metric and unit:
            key = {"family": family, "period": period, "metric": metric,
                   "actual": row["actual"], "actual_unit": unit}
        elif row.get("numerical_eligible") is True or row.get("surprise_z") is not None:
            # A matching headline alone cannot merge independent numeric facts.
            key = {"unstructured_numerical_revision": row.get("revision_id")}
        else:
            title = " ".join(unicodedata.normalize("NFKC", str(row.get("title", ""))).casefold().split())
            # Repeating scheduled-release headlines on different days are
            # independent references unless a structured fact links them.
            stamp = row.get("published_at") or row.get("retrieved_at") or row.get("available_at")
            day = timestamp(stamp).date().isoformat() if stamp else None
            key = {"family": family, "period": period, "reference_title": title or row.get("revision_id"),
                   "publication_or_first_capture_day": day}
    return "mcg-" + digest(key)[:24]


def annotate_incident_groups(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Annotate active PIT revisions without mutating source rows or hiding evidence."""
    groups: dict[str, list[int]] = {}
    annotated = []
    for index, event in enumerate(events):
        value = event.get("surprise_z")
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
            raise C.MarketContextError("surprise_z must be finite before incident grouping")
        group = incident_group_id(event)
        annotated.append({**event, "incident_group_id": group})
        groups.setdefault(group, []).append(index)
    def priority(index: int):
        row = events[index]
        known = [timestamp(row[key]) for key in ("available_at", "retrieved_at") if row.get(key)]
        return (not (row.get("numerical_eligible") is True and row.get("surprise_z") is not None),
                max(known) if known else datetime.max.replace(tzinfo=timezone.utc), str(row.get("revision_id", "")))
    for members in groups.values():
        representative = min(members, key=priority)
        for index in members:
            annotated[index]["incident_group_status"] = "representative" if index == representative else "duplicate"
            if index == representative:
                continue
            row = annotated[index]
            row.setdefault("original_surprise_z", row.get("surprise_z"))
            row.setdefault("original_numerical_eligible", row.get("numerical_eligible"))
            row.update({"duplicate_of_revision_id": events[representative].get("revision_id"),
                        "numerical_eligible": False, "surprise_z": None,
                        "reason": "duplicate_incident_no_additional_shock"})
    return annotated


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise C.MarketContextError(f"invalid JSON in {path.name}:{number}") from exc
        if not isinstance(row, dict):
            raise C.MarketContextError(f"expected object in {path.name}:{number}")
        rows.append(row)
    return rows


def append_unique(path: Path, row: dict[str, Any], id_field: str) -> bool:
    identifier = row.get(id_field)
    if not isinstance(identifier, str) or not identifier:
        raise C.MarketContextError(f"missing {id_field}")
    encoded = json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    for prior in read_jsonl(path):
        if prior.get(id_field) == identifier:
            if prior != row:
                raise C.MarketContextError(f"append-only conflict: {identifier}")
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(encoded + "\n")
    return True


def persist_raw(root: Path, *, source_id: str, url: str, body: bytes,
                retrieved_at: str) -> dict[str, Any]:
    timestamp(retrieved_at, "retrieved_at")
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.username or parts.password or parts.query:
        # Configured sources are public, keyless URLs; never persist query credentials.
        if parts.scheme != "https" or parts.username or parts.password or any(
            name in parts.query.lower() for name in ("api_key", "apikey", "token", "access_key")
        ):
            raise C.MarketContextError("raw source must use a public HTTPS URL without credentials")
    sha = hashlib.sha256(body).hexdigest()
    relative = BASE / "raw" / f"{sha}.bin.gz"
    path = root / relative
    if path.exists():
        if hashlib.sha256(gzip.decompress(path.read_bytes())).hexdigest() != sha:
            raise C.MarketContextError("existing raw artifact hash mismatch")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(body, mtime=0))
    row = {"source_id": source_id, "source_url": url, "retrieved_at": retrieved_at,
           "source_sha256": sha, "raw_path": relative.as_posix(), "byte_count": len(body)}
    row["receipt_id"] = digest(row)
    append_unique(root / RECEIPTS, row, "receipt_id")
    return row


def validate_raw(root: Path, row: dict[str, Any], *, receipts: list[dict[str, Any]] | None = None) -> None:
    sha = str(row.get("source_sha256", ""))
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise C.MarketContextError("source_sha256 must be lowercase SHA256")
    relative = Path(str(row.get("raw_path", "")))
    path = (root / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(root.resolve()) or not path.is_file():
        raise C.MarketContextError("raw artifact missing or outside repository")
    try:
        body = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
    except (OSError, EOFError) as exc:
        raise C.MarketContextError("raw artifact unreadable") from exc
    if hashlib.sha256(body).hexdigest() != sha:
        raise C.MarketContextError("raw artifact hash mismatch")
    receipts = read_jsonl(root / RECEIPTS) if receipts is None else receipts
    if not any(all(receipt.get(key) == row.get(key) for key in
                   ("source_id", "source_sha256", "raw_path", "retrieved_at")) for receipt in receipts):
        raise C.MarketContextError("event requires its persisted acquisition receipt")


def _source_ids(root: Path) -> set[str]:
    configured = C.load_contract(root).get("sources", [])
    return set(configured) if isinstance(configured, dict) else {
        str(source.get("id") or source.get("source_id")) for source in configured
        if isinstance(source, dict)
    }


def _validate_event(root: Path, row: dict[str, Any], *, verify_evidence: bool = True,
                    source_ids: set[str] | None = None) -> None:
    required = {"event_id", "revision_id", "family", "axis", "kind", "title", "published_at",
                "available_at", "retrieved_at", "source_id", "source_url", "source_sha256",
                "raw_path", "dedupe_key", "unit_metadata", "expectation_kind", "numerical_eligible", "reason"}
    if required - row.keys():
        raise C.MarketContextError("missing event fields: " + ", ".join(sorted(required - row.keys())))
    for field in ("event_id", "revision_id", "dedupe_key", "source_id", "family"):
        if not isinstance(row[field], str) or not row[field].strip():
            raise C.MarketContextError(f"{field} must be non-empty")
    if row["axis"] not in C.AXES:
        raise C.MarketContextError("unknown context axis")
    source_ids = _source_ids(root) if source_ids is None else source_ids
    if row["source_id"] not in source_ids:
        raise C.MarketContextError("event source is not registered")
    published = timestamp(row["published_at"], "published_at") if row["published_at"] is not None else None
    available, retrieved = (timestamp(row[key], key) for key in ("available_at", "retrieved_at"))
    if (published is not None and published > available) or available > retrieved:
        raise C.MarketContextError("event requires published_at <= available_at <= retrieved_at")
    if published is None and (row.get("numerical_eligible") is not False or row.get("publication_time_status") != "unknown"):
        raise C.MarketContextError("unknown publication time requires a reference-only event and explicit status")
    if not str(row["source_url"]).startswith("https://"):
        raise C.MarketContextError("event source_url must use HTTPS")
    if not isinstance(row["numerical_eligible"], bool):
        raise C.MarketContextError("numerical_eligible must be boolean")
    units = row["unit_metadata"]
    if not isinstance(units, dict) or not {"actual", "expectation"}.issubset(units):
        raise C.MarketContextError("explicit actual and expectation unit metadata required")
    if row["expectation_kind"] not in {"market_consensus", "model_innovation", "none"}:
        raise C.MarketContextError("unknown expectation_kind")
    for field in ("actual", "expectation", "standardization_scale", "surprise_z"):
        value = row.get(field)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                  or not math.isfinite(value)):
            raise C.MarketContextError(f"{field} must be a finite number or null")
    incident_group_id(row)
    if row["numerical_eligible"]:
        structured_fact = any(row.get(key) for key in ("fact_payload", "fact_sha256", "fact_hash", "payload_fact_hash"))
        mapping = row.get("mapping") or {}
        metric = row.get("metric") or row.get("series_id") or (mapping.get("metric") if isinstance(mapping, dict) else None)
        period = row.get("reference_period")
        if not structured_fact and not (isinstance(metric, str) and metric.strip()
                                        and isinstance(period, str) and period.strip()):
            raise C.MarketContextError("numerical event requires structured fact identity or explicit metric and reference_period")
        if row["expectation_kind"] == "none" or any(row.get(key) is None for key in
                   ("actual", "expectation", "standardization_scale", "surprise_z")):
            raise C.MarketContextError("numerical event requires an auditable surprise")
        if not units["actual"] or units["actual"] != units["expectation"]:
            raise C.MarketContextError("actual and expectation units must explicitly match")
        scale = row["standardization_scale"]
        if scale <= 0:
            raise C.MarketContextError("standardization_scale must be positive")
        expectation_time = timestamp(row.get("expectation_available_at"), "expectation_available_at")
        scale_time = timestamp(row.get("scale_as_of"), "scale_as_of")
        if expectation_time >= available or scale_time >= available:
            raise C.MarketContextError("expectation and scale must predate the released actual")
        if row["expectation_kind"] == "market_consensus" and expectation_time >= published:
            raise C.MarketContextError("market consensus must be captured before the published release")
        count = row.get("scale_sample_count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 2:
            raise C.MarketContextError("scale requires at least two prior samples")
        expected_z = (row["actual"] - row["expectation"]) / scale
        if not math.isclose(row["surprise_z"], expected_z, abs_tol=1e-10, rel_tol=1e-10):
            raise C.MarketContextError("surprise_z does not reconcile")
    if verify_evidence:
        validate_raw(root, row)


def append_event(root: Path, row: dict[str, Any]) -> bool:
    _validate_event(root, row)
    existing = read_jsonl(root / EVENTS)
    by_revision = {prior["revision_id"]: prior for prior in existing}
    if row["revision_id"] in by_revision:
        return append_unique(root / EVENTS, row, "revision_id")
    same_event = [prior for prior in existing if prior["event_id"] == row["event_id"]]
    supersedes = row.get("supersedes")
    if same_event:
        superseded = {prior.get("supersedes") for prior in same_event}
        tips = [prior for prior in same_event if prior["revision_id"] not in superseded]
        if len(tips) != 1 or supersedes != tips[0]["revision_id"]:
            raise C.MarketContextError("correction must explicitly supersede the active event revision")
        if timestamp(row["retrieved_at"]) < timestamp(tips[0]["retrieved_at"]) or \
                timestamp(row["available_at"]) < timestamp(tips[0]["available_at"]):
            raise C.MarketContextError("correction cannot precede its prior revision")
    elif supersedes:
        raise C.MarketContextError("first event revision cannot supersede another incident")
    if any(prior["dedupe_key"] == row["dedupe_key"] and prior["event_id"] != row["event_id"]
           for prior in existing):
        return False
    if any(prior["event_id"] != row["event_id"] and incident_group_id(prior) == incident_group_id(row)
           for prior in existing):
        return False
    return append_unique(root / EVENTS, row, "revision_id")


def read_events(root: Path, *, as_of: str) -> list[dict[str, Any]]:
    cutoff = timestamp(as_of, "as_of")
    rows = [row for row in read_jsonl(root / EVENTS)
            if timestamp(row["available_at"]) <= cutoff and timestamp(row["retrieved_at"]) <= cutoff]
    # Filter first: a correction learned tomorrow must not erase today's revision.
    selected: dict[str, dict[str, Any]] = {}
    seen: dict[str, dict[str, Any]] = {}
    source_ids = _source_ids(root)
    verified: set[tuple[str, str, str, str]] = set()
    receipts = read_jsonl(root / RECEIPTS)
    for row in rows:
        _validate_event(root, row, verify_evidence=False, source_ids=source_ids)
        signature = tuple(str(row.get(key)) for key in ("source_id", "source_sha256", "raw_path", "retrieved_at"))
        if signature not in verified:
            validate_raw(root, row, receipts=receipts)
            verified.add(signature)
        revision = row["revision_id"]
        if revision in seen:
            raise C.MarketContextError("duplicate event revision in ledger")
        supersedes = row.get("supersedes")
        prior = selected.get(row["event_id"])
        if supersedes and (prior is None or supersedes != prior["revision_id"]):
            raise C.MarketContextError("invalid eligible correction chain")
        if prior and not supersedes:
            raise C.MarketContextError("event revision requires supersedes")
        seen[revision] = row
        selected[row["event_id"]] = row
    return annotate_incident_groups(sorted(selected.values(), key=lambda row: (row["available_at"], row["event_id"])))


def verify_store(root: Path) -> dict[str, Any]:
    """Verify every revision and raw receipt, including facts never forecast yet."""
    counts: dict[str, int] = {}
    try:
        sources = _source_ids(root)
        receipts, events, observations, statuses, rejected = (read_jsonl(root / path) for path in
                                                    (RECEIPTS, EVENTS, OBSERVATIONS, SOURCE_STATUS, REJECTIONS))
        counts = {"raw_receipts": len(receipts), "events": len(events),
                  "market_observations": len(observations), "source_statuses": len(statuses),
                  "rejected_observations": len(rejected)}
        seen_receipts: set[str] = set()
        verified: set[tuple[str, str, str, str]] = set()
        for receipt in receipts:
            identifier = receipt.get("receipt_id")
            if identifier in seen_receipts or identifier != digest({key: value for key, value in receipt.items() if key != "receipt_id"}):
                raise C.MarketContextError("raw receipt identity conflict")
            seen_receipts.add(identifier)
            timestamp(receipt["retrieved_at"])
            if receipt["source_id"] not in sources:
                raise C.MarketContextError("unregistered raw receipt source")
            validate_raw(root, receipt, receipts=receipts)
            verified.add(tuple(str(receipt.get(key)) for key in ("source_id", "source_sha256", "raw_path", "retrieved_at")))
        event_tips: dict[str, dict[str, Any]] = {}
        seen_revisions: set[str] = set()
        for row in events:
            _validate_event(root, row, verify_evidence=False, source_ids=sources)
            signature = tuple(str(row.get(key)) for key in ("source_id", "source_sha256", "raw_path", "retrieved_at"))
            if signature not in verified:
                raise C.MarketContextError("event acquisition receipt is missing")
            prior = event_tips.get(row["event_id"])
            if row["revision_id"] in seen_revisions or row.get("supersedes") != (prior["revision_id"] if prior else None):
                raise C.MarketContextError("invalid complete event revision chain")
            if prior and (timestamp(row["retrieved_at"]) < timestamp(prior["retrieved_at"]) or
                          timestamp(row["available_at"]) < timestamp(prior["available_at"])):
                raise C.MarketContextError("event revision time reversal")
            event_tips[row["event_id"]] = row
            seen_revisions.add(row["revision_id"])
        observation_tips: dict[tuple[str, str, str], dict[str, Any]] = {}
        seen_observations: set[str] = set()
        for row in observations:
            identifier = row.get("observation_id")
            if identifier in seen_observations or identifier != digest({key: value for key, value in row.items() if key != "observation_id"}):
                raise C.MarketContextError("market observation identity conflict")
            seen_observations.add(identifier)
            signature = tuple(str(row.get(key)) for key in ("source_id", "source_sha256", "raw_path", "retrieved_at"))
            if signature not in verified:
                raise C.MarketContextError("market observation receipt is missing")
            datetime.strptime(row["observation_time"], "%Y-%m-%d")
            value = row["value"]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise C.MarketContextError("invalid market observation value")
            if row["series_id"] == "NASDAQCOM" and value <= 0:
                raise C.MarketContextError("invalid index level")
            if timestamp(row["available_at"]) > timestamp(row["retrieved_at"]):
                raise C.MarketContextError("market observation time reversal")
            if row.get("historical_pit_eligible") is not False or row.get("data_grade") != "captured_current_vintage":
                raise C.MarketContextError("captured history cannot claim historical PIT status")
            key = (row["source_id"], row["series_id"], row["observation_time"])
            prior = observation_tips.get(key)
            if row.get("supersedes") != (prior["observation_id"] if prior else None):
                raise C.MarketContextError("invalid market observation supersedes chain")
            if prior and timestamp(row["retrieved_at"]) < timestamp(prior["retrieved_at"]):
                raise C.MarketContextError("market observation correction predates prior capture")
            observation_tips[key] = row
        latest_status: dict[str, dict[str, Any]] = {}
        rejection_ids = set()
        for row in rejected:
            identifier = row.get("rejection_id")
            if identifier in rejection_ids or identifier != digest({key: value for key, value in row.items() if key != "rejection_id"}):
                raise C.MarketContextError("rejected observation identity conflict")
            rejection_ids.add(identifier)
            signature = tuple(str(row.get(key)) for key in ("source_id", "source_sha256", "raw_path", "retrieved_at"))
            if signature not in verified or row.get("status") != "rejected" or not row.get("reason"):
                raise C.MarketContextError("rejected observation lacks auditable evidence or reason")
            datetime.strptime(row["observation_time"], "%Y-%m-%d")
        for row in statuses:
            if row.get("status_id") != digest({key: value for key, value in row.items() if key != "status_id"}):
                raise C.MarketContextError("source status identity conflict")
            latest_status[row["source_id"]] = row
        failures = [row for row in latest_status.values() if row.get("status") != "ok"]
        return {"ok": True, "counts": counts, "errors": [], "source_failures": failures}
    except (C.MarketContextError, OSError, KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "counts": counts, "errors": [str(exc)], "source_failures": []}
