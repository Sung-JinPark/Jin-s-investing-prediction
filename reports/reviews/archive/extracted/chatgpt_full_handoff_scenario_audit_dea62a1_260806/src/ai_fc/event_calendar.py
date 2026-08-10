"""Append-only official/estimated market event calendar for the static dashboard."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml


EVENTS_PATH = Path("data/calendar/events.csv")
SOURCES_PATH = Path("data/contracts/calendar_sources.yaml")
EVENT_FIELDS = [
    "event_id", "kind", "date", "time_et", "status", "ticker", "title",
    "source_id", "source_url", "available_at", "registered_at", "supersedes",
    "superseded_by",
]
KINDS = {"fomc", "cpi", "nfp", "gdp", "earnings", "other"}
STATUSES = {"confirmed", "estimated"}


class CalendarError(ValueError):
    """Raised when the append-only calendar contract is violated."""


def load_source_contract(root: Path) -> dict[str, Any]:
    path = root / SOURCES_PATH
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise CalendarError(f"calendar source contract unavailable: {exc}") from exc
    sources = payload.get("sources")
    if not isinstance(sources, list) or len(sources) < 3:
        raise CalendarError("calendar_sources requires at least three D0 sources")
    seen: set[str] = set()
    for source in sources:
        source_id = str(source.get("id") or "")
        if not source_id or source_id in seen:
            raise CalendarError("calendar source ids must be non-empty and unique")
        if source.get("official") is not True or source.get("access") != "free":
            raise CalendarError(f"calendar source {source_id} must be official and free")
        url = str(source.get("url") or "")
        if urlparse(url).scheme != "https":
            raise CalendarError(f"calendar source {source_id} must use https")
        seen.add(source_id)
    return payload


def _read_rows(root: Path) -> list[dict[str, str]]:
    path = root / EVENTS_PATH
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != EVENT_FIELDS:
            raise CalendarError("calendar events schema drift")
        return list(reader)


def _validate_rows(rows: list[dict[str, str]], source_ids: set[str]) -> None:
    seen: dict[str, dict[str, str]] = {}
    superseded: dict[str, str] = {}
    for row in rows:
        event_id = row.get("event_id", "")
        if not event_id or event_id in seen:
            raise CalendarError("calendar event_id must be non-empty and unique")
        if row.get("kind") not in KINDS or row.get("status") not in STATUSES:
            raise CalendarError(f"invalid calendar kind/status: {event_id}")
        try:
            date.fromisoformat(row.get("date", ""))
        except ValueError as exc:
            raise CalendarError(f"invalid calendar date: {event_id}") from exc
        if row.get("source_id") not in source_ids:
            raise CalendarError(f"unregistered calendar source: {event_id}")
        if urlparse(row.get("source_url", "")).scheme != "https":
            raise CalendarError(f"calendar source_url must use https: {event_id}")
        supersedes = row.get("supersedes", "")
        if supersedes:
            if supersedes not in seen or supersedes in superseded:
                raise CalendarError(f"invalid supersedes chain: {event_id}")
            superseded[supersedes] = event_id
        if row.get("superseded_by"):
            raise CalendarError(
                "stored superseded_by must stay blank; append a row with supersedes instead"
            )
        seen[event_id] = row


def load_events(root: Path) -> list[dict[str, str]]:
    """Return active rows, deriving superseded_by without rewriting old CSV rows."""
    contract = load_source_contract(root)
    source_ids = {str(source["id"]) for source in contract["sources"]}
    rows = _read_rows(root)
    _validate_rows(rows, source_ids)
    superseded = {
        row["supersedes"]: row["event_id"] for row in rows if row.get("supersedes")
    }
    active = []
    for row in rows:
        if row["event_id"] in superseded:
            continue
        item = dict(row)
        item["superseded_by"] = superseded.get(row["event_id"], "")
        active.append(item)
    return sorted(active, key=lambda item: (item["date"], item["kind"], item["event_id"]))


def append_event(root: Path, event: dict[str, Any]) -> bool:
    """Append a new event or correction; existing bytes are never edited."""
    contract = load_source_contract(root)
    source_ids = {str(source["id"]) for source in contract["sources"]}
    rows = _read_rows(root)
    normalized = {field: str(event.get(field, "")) for field in EVENT_FIELDS}
    if normalized["event_id"] in {row["event_id"] for row in rows}:
        existing = next(row for row in rows if row["event_id"] == normalized["event_id"])
        if existing != normalized:
            raise CalendarError(f"append-only calendar conflict: {normalized['event_id']}")
        return False
    _validate_rows(rows + [normalized], source_ids)
    path = root / EVENTS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=EVENT_FIELDS, lineterminator="\n")
        if path.stat().st_size == 0:
            writer.writeheader()
        writer.writerow(normalized)
    return True
