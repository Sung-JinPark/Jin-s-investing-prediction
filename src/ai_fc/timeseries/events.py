"""Receipt-backed event inputs and a separately calibrated path overlay.

Consensus and market-implied rate probabilities are permitted research inputs,
but they never enter the registered VARX coefficient matrix without the separate
60-event ablation gate.  Below that threshold, an expanding historical event
regression may only reweight already simulated core paths.
"""

from __future__ import annotations

import hashlib
import gzip
import json
import math
import os
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import LEDGER_RELATIVE, canonical_hash, load_contract


EVENT_LEDGER = "events.jsonl"
EVENT_RECEIPT_LEDGER = "event_raw_receipts.jsonl"


class EventFact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    event_id: str
    event_type: str
    source_id: str
    scheduled_at: str
    available_at: str
    retrieved_at: str
    receipt_id: str
    supporting_receipt_ids: tuple[str, ...] = ()
    raw_sha256: str = Field(min_length=64, max_length=64)
    consensus: float | None = None
    model_nowcast: float | None = None
    policy_relief: float | None = None
    actual: float | None = None
    outcome_return_5d: float | None = None
    unit: str
    revision_seq: int = 0
    supersedes: str | None = None

    @model_validator(mode="after")
    def validate_information_time(self) -> "EventFact":
        scheduled = datetime.fromisoformat(self.scheduled_at)
        available = datetime.fromisoformat(self.available_at)
        retrieved = datetime.fromisoformat(self.retrieved_at)
        if retrieved < available:
            raise ValueError("event receipt cannot be retrieved before it is available")
        if self.actual is not None and available < scheduled:
            raise ValueError("future event actual cannot be available before release")
        if self.outcome_return_5d is not None and self.actual is None:
            raise ValueError("realized event return requires a released actual")
        if self.consensus is not None and self.model_nowcast is None:
            raise ValueError("consensus overlay requires a same-vintage model nowcast")
        return self

    def signal(self) -> tuple[float, float]:
        gap = 0.0
        if self.consensus is not None and self.model_nowcast is not None:
            gap = float(self.model_nowcast - self.consensus)
        return gap, float(self.policy_relief or 0.0)


class EventRawReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    receipt_id: str
    source_id: str
    series_id: str
    retrieved_at: str
    available_at: str
    raw_sha256: str = Field(min_length=64, max_length=64)
    raw_path: str
    request_fingerprint: str = Field(min_length=64, max_length=64)
    http_status: int
    byte_count: int


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _append_unique(path: Path, row: dict[str, Any], *, id_field: str) -> bool:
    prior = {str(item[id_field]): item for item in _read_jsonl(path)}
    identifier = str(row[id_field])
    if identifier in prior:
        if prior[identifier] != row:
            raise ValueError(f"append-only event receipt conflict: {identifier}")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    return True


def _request_fingerprint(url: str) -> str:
    split = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(split.query, keep_blank_values=True)
    secret_names = {"api_key", "apikey", "key", "token", "access_token"}
    clean_query = [
        (key, "REDACTED" if key.lower() in secret_names else value)
        for key, value in query
    ]
    clean = urllib.parse.urlunsplit((
        split.scheme, split.netloc, split.path, urllib.parse.urlencode(clean_query), "",
    ))
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()


def persist_event_response(
    root: Path,
    *,
    source_id: str,
    series_id: str,
    payload: bytes,
    http_status: int,
    retrieved_at: str,
    available_at: str,
    request_url: str,
) -> EventRawReceipt:
    digest = hashlib.sha256(payload).hexdigest()
    raw_path = root / "data/timeseries/raw/events" / f"{digest}.bin.gz"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    if not raw_path.is_file():
        temporary = raw_path.with_suffix(".tmp")
        with temporary.open("wb") as raw_handle:
            with gzip.GzipFile(filename="", fileobj=raw_handle, mode="wb", compresslevel=9, mtime=0) as handle:
                handle.write(payload)
        os.replace(temporary, raw_path)
    body = {
        "schema_version": 1,
        "source_id": source_id,
        "series_id": series_id,
        "retrieved_at": retrieved_at,
        "available_at": available_at,
        "raw_sha256": digest,
        "raw_path": raw_path.relative_to(root).as_posix(),
        "request_fingerprint": _request_fingerprint(request_url),
        "http_status": int(http_status),
        "byte_count": len(payload),
    }
    receipt = EventRawReceipt(receipt_id=canonical_hash(body), **body)
    _append_unique(
        root / LEDGER_RELATIVE / EVENT_RECEIPT_LEDGER,
        receipt.model_dump(mode="json"), id_field="receipt_id",
    )
    return receipt


def append_event(root: Path, fact: EventFact) -> bool:
    """Append an event revision; correction must explicitly supersede the tip."""
    path = root / LEDGER_RELATIVE / EVENT_LEDGER
    contract = load_contract(root)
    authority = contract["sources"]["authority"]
    allowed_sources = set(authority["official_pit"]) | set(authority["research_numeric_with_receipt"])
    receipts = {
        str(row["receipt_id"]): row
        for row in _read_jsonl(root / LEDGER_RELATIVE / EVENT_RECEIPT_LEDGER)
    }
    receipt = receipts.get(fact.receipt_id)
    if receipt is None:
        raise ValueError("event fact requires a persisted raw receipt")
    if fact.source_id not in allowed_sources:
        raise ValueError("event numerical source is not registered")
    for field in ("source_id", "raw_sha256", "retrieved_at", "available_at"):
        if str(receipt.get(field)) != str(getattr(fact, field)):
            raise ValueError(f"event fact/receipt mismatch: {field}")
    supporting = [receipts.get(identifier) for identifier in fact.supporting_receipt_ids]
    if any(row is None for row in supporting):
        raise ValueError("event fact supporting receipt is missing")
    evidence_sources = {str(receipt["source_id"]), *[str(row["source_id"]) for row in supporting if row]}
    if not evidence_sources.issubset(allowed_sources):
        raise ValueError("event supporting source is not registered")
    if any(datetime.fromisoformat(str(row["available_at"])) > datetime.fromisoformat(fact.available_at)
           for row in supporting if row):
        raise ValueError("event fact cannot predate supporting evidence")
    if fact.consensus is not None and "market_consensus" not in evidence_sources:
        raise ValueError("consensus input requires a market_consensus receipt")
    if fact.policy_relief is not None and "market_implied_rate_distribution" not in evidence_sources:
        raise ValueError("policy relief input requires a rate-distribution receipt")
    rows = _read_jsonl(path)
    identities = {str(row["event_id"]): row for row in rows}
    if fact.event_id in identities:
        if identities[fact.event_id] != fact.model_dump(mode="json"):
            raise ValueError(f"append-only event conflict: {fact.event_id}")
        return False
    same_release = [
        row for row in rows
        if row["event_type"] == fact.event_type and row["scheduled_at"] == fact.scheduled_at
    ]
    if same_release:
        tip = max(same_release, key=lambda row: int(row["revision_seq"]))
        if fact.revision_seq != int(tip["revision_seq"]) + 1 or fact.supersedes != tip["event_id"]:
            raise ValueError("event correction requires next revision_seq and explicit supersedes")
    elif fact.revision_seq != 0 or fact.supersedes is not None:
        raise ValueError("first event revision must start at zero without supersedes")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(
            fact.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ) + "\n")
    return True


def read_events(root: Path, *, knowledge_cutoff: str) -> list[EventFact]:
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    cutoff = datetime.fromisoformat(knowledge_cutoff)
    for row in _read_jsonl(root / LEDGER_RELATIVE / EVENT_LEDGER):
        if datetime.fromisoformat(str(row["available_at"])) > cutoff:
            continue
        key = (str(row["event_type"]), str(row["scheduled_at"]))
        prior = latest.get(key)
        if prior is None or int(row["revision_seq"]) > int(prior["revision_seq"]):
            if prior is not None and row.get("supersedes") != prior.get("event_id"):
                raise ValueError(f"branched event correction: {key}")
            latest[key] = row
    return [
        EventFact.model_validate(row)
        for row in sorted(latest.values(), key=lambda row: (row["scheduled_at"], row["event_type"]))
    ]


def event_fact_id(payload: dict[str, Any]) -> str:
    return f"tse-{canonical_hash(payload)[:24]}"


def _systematic_resample(weights: np.ndarray, *, count: int, seed: int) -> np.ndarray:
    cumulative = np.cumsum(weights / np.sum(weights))
    rng = np.random.default_rng(seed)
    points = (rng.random() + np.arange(count)) / count
    return np.searchsorted(cumulative, points, side="right")


def apply_event_overlay(
    index_paths: np.ndarray,
    *,
    anchor: float,
    events: list[EventFact],
    current_event: EventFact | None,
    contract: dict[str, Any],
    seed: int,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Reweight core paths using only past event outcomes and current known signals."""
    spec = contract["event_overlay"]
    minimum = int(spec["minimum_pit_observations_for_overlay"])
    coefficient_minimum = int(spec["minimum_pit_observations_for_varx"])
    history = [event for event in events if event.outcome_return_5d is not None]
    common = {
        "historical_event_count": len(history),
        "minimum_for_overlay": minimum,
        "minimum_for_varx": coefficient_minimum,
        "varx_status": (
            "eligible_pending_ablation" if len(history) >= coefficient_minimum
            else "blocked_insufficient_pit_history"
        ),
        "core_coefficients_modified": False,
    }
    if current_event is None:
        return index_paths, {**common, "status": "not_applied_no_current_event"}
    if current_event.actual is not None:
        return index_paths, {**common, "status": "not_applied_event_already_released"}
    if len(history) < minimum:
        return index_paths, {**common, "status": "not_applied_insufficient_pit_history"}
    x = np.asarray([[1.0, *event.signal()] for event in history], dtype=float)
    y = np.asarray([float(event.outcome_return_5d) for event in history], dtype=float)
    alpha = float(spec["ridge_alpha"])
    penalty = np.eye(x.shape[1]) * alpha
    penalty[0, 0] = 0.0
    beta = np.linalg.solve(x.T @ x + penalty, x.T @ y)
    target = float(np.asarray([1.0, *current_event.signal()]) @ beta)
    sigma = float(np.std(y, ddof=1)) if len(y) > 1 else 0.0
    cap = float(spec["maximum_absolute_shift_sigma"]) * sigma
    target = float(np.clip(target, -cap, cap)) if cap > 0 else 0.0
    session = min(int(spec["target_path_sessions"]), index_paths.shape[1]) - 1
    realized = np.log(index_paths[:, session] / float(anchor))
    bandwidth = max(float(np.std(realized, ddof=1)), 1e-8)
    log_weights = -0.5 * np.square((realized - target) / bandwidth)
    weights = np.exp(log_weights - float(np.max(log_weights)))
    digest = hashlib.sha256(
        f"{seed}|{current_event.event_id}|{len(history)}".encode("utf-8")
    ).digest()
    overlay_seed = int.from_bytes(digest[:8], "big")
    indices = _systematic_resample(weights, count=len(index_paths), seed=overlay_seed)
    return index_paths[indices].copy(), {
        **common,
        "status": "applied_path_reweighting_only",
        "current_event_id": current_event.event_id,
        "target_5d_log_return": target,
        "calibration": spec["calibration"],
        "effective_path_fraction": float(np.square(np.sum(weights)) / np.sum(np.square(weights)) / len(weights)),
        "overlay_seed": overlay_seed,
    }
