"""Keyless, bounded public-source collection into the separate context archive."""

from __future__ import annotations

import csv
import io
import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from . import contracts as C
from .ledger import (EVENTS, OBSERVATIONS, REJECTIONS, SOURCE_STATUS, append_event, append_unique,
                     digest, persist_raw, read_jsonl, timestamp)


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "AI-Investing-Research/1.0"})
    with urllib.request.urlopen(request, timeout=25) as response:
        return response.read(8 * 1024 * 1024 + 1)


def _text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value)).strip()


def _publication(value: str | None, captured: str) -> str | None:
    if not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            result = parsedate_to_datetime(value)
        except (ValueError, TypeError, OverflowError):
            return None
    # Date-only issuer pages do not establish an intraday release timestamp.
    if result.tzinfo is None:
        return None
    result = result.astimezone(timezone.utc)
    if result > timestamp(captured):
        raise C.MarketContextError("public source contains a future-dated release")
    return result.isoformat()


def _feed_items(body: bytes, base: str) -> list[dict[str, str]]:
    document = ET.fromstring(body)
    items = []
    for entry in document.iter():
        if entry.tag.rsplit("}", 1)[-1] not in {"item", "entry"}:
            continue
        fields: dict[str, str] = {}
        for child in entry:
            key = child.tag.rsplit("}", 1)[-1]
            if key == "link":
                fields["url"] = child.attrib.get("href") or (child.text or "")
            elif key in {"title", "pubDate", "published", "updated"}:
                fields[key] = "".join(child.itertext())
        title = _text(fields.get("title", ""))
        url = urllib.parse.urljoin(base, fields.get("url", ""))
        if title and url.startswith("https://"):
            items.append({"title": title, "url": url,
                          "published": fields.get("pubDate") or fields.get("published")
                          or fields.get("updated", "")})
    return items


class _LinkParser(HTMLParser):
    def __init__(self, base: str, fragments: tuple[str, ...]) -> None:
        super().__init__()
        self.base = base
        self.fragments = fragments
        self.items: list[dict[str, str]] = []
        self.url: str | None = None
        self.label: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            url = urllib.parse.urljoin(self.base, dict(attrs).get("href") or "")
            self.url = url if url.startswith("https://") and urllib.parse.urlsplit(url).netloc == \
                urllib.parse.urlsplit(self.base).netloc and any(fragment in urllib.parse.urlsplit(url).path
                                                                for fragment in self.fragments) else None
            self.label = []

    def handle_data(self, data: str) -> None:
        if self.url:
            self.label.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.url:
            title = _text(" ".join(self.label))
            if len(title) >= 15 and self.url.rstrip("/") != self.base.rstrip("/"):
                self.items.append({"title": title, "url": self.url, "published": ""})
            self.url = None


def _source_list(contract: dict[str, Any]) -> list[dict[str, Any]]:
    sources = contract.get("sources", [])
    if isinstance(sources, dict):
        return [{"id": key, **value} for key, value in sources.items() if isinstance(value, dict)]
    return sources if isinstance(sources, list) else []


def _append_market_csv(root: Path, source: dict[str, Any], body: bytes,
                       receipt: dict[str, Any]) -> dict[str, int]:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8-sig")))
    series = str(source.get("series_id", "NASDAQCOM"))
    if not reader.fieldnames or series not in reader.fieldnames:
        raise C.MarketContextError("market CSV schema missing registered series")
    date_column = "observation_date" if "observation_date" in reader.fieldnames else "DATE"
    if date_column not in reader.fieldnames:
        raise C.MarketContextError("market CSV schema missing observation date")
    latest = {(item["series_id"], item["observation_time"]): item
              for item in read_jsonl(root / OBSERVATIONS)}
    pending = []
    parsed = []
    seen_dates: set[str] = set()
    for record in reader:
        if record[series] in {"", "."}:
            continue
        day = datetime.strptime(record[date_column], "%Y-%m-%d").date().isoformat()
        value = float(record[series])
        if not math.isfinite(value) or (series == "NASDAQCOM" and value <= 0):
            raise C.MarketContextError("market observation must be finite and index positive")
        if day > timestamp(receipt["retrieved_at"]).date().isoformat():
            raise C.MarketContextError("market CSV contains a future observation")
        if day in seen_dates:
            raise C.MarketContextError("market CSV contains a duplicate observation date")
        seen_dates.add(day)
        parsed.append((day, value))
    maximum = int(source.get("maximum_captured_observations", 3000))
    if maximum < 253:
        raise C.MarketContextError("captured market window must retain at least 253 observations")
    session_closes = {}
    provisional_excluded = 0
    rejected_count = rejections_appended = 0
    eligible = sorted(parsed)
    if series == "NASDAQCOM" and parsed:
        from .features import _calendar
        calendar, days, closes = _calendar(receipt["retrieved_at"], min(day for day, _ in parsed), 252)
        session_closes = dict(zip(days, closes))
        eligible = []
        for day, value in sorted(parsed):
            if day in session_closes:
                eligible.append((day, value))
                continue
            rejection = {"source_id": source["id"], "series_id": series, "observation_time": day,
                         "value": value, "unit": "index_points", "status": "rejected",
                         "reason": "non_session_index_observation", "calendar_requested": "XNAS",
                         "calendar_resolved": calendar.name, "source_url": receipt["source_url"],
                         "retrieved_at": receipt["retrieved_at"], "source_sha256": receipt["source_sha256"],
                         "raw_path": receipt["raw_path"], "policy": "reject_row_with_raw_link_and_reason"}
            rejection["rejection_id"] = digest(rejection)
            rejections_appended += append_unique(root / REJECTIONS, rejection, "rejection_id")
            rejected_count += 1
    selected = eligible[-maximum:]
    for day, value in selected:
        close = session_closes.get(day) if series == "NASDAQCOM" else None
        if series == "NASDAQCOM":
            if close > timestamp(receipt["retrieved_at"]):
                provisional_excluded += 1
                continue
        row = {"series_id": series, "observation_time": day, "value": value,
               "available_at": receipt["retrieved_at"], "retrieved_at": receipt["retrieved_at"],
               "source_id": source["id"], "source_sha256": receipt["source_sha256"],
               "raw_path": receipt["raw_path"], "data_grade": "captured_current_vintage",
               "historical_pit_eligible": False}
        if close:
            row.update({"session_close": close.isoformat(), "final_close_capture": True})
        # Persist only changed values; repeated snapshots never duplicate observations.
        prior = latest.get((series, day))
        recertify = bool(prior and close and timestamp(prior["retrieved_at"]) < close)
        if prior and prior["value"] == value and not recertify:
            continue
        row["supersedes"] = prior["observation_id"] if prior else None
        row["observation_id"] = digest(row)
        pending.append(row)
        latest[(series, day)] = row
    if pending:
        path = root / OBSERVATIONS
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            for row in pending:
                handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")
    return {"appended": len(pending), "parsed_observations": len(parsed),
            "eligible_observations": len(eligible), "rejected_observations": rejected_count,
            "rejections_appended": rejections_appended,
            "selected_observations": len(selected), "excluded_by_declared_window": len(eligible) - len(selected),
            "provisional_excluded": provisional_excluded, "window_limit": maximum}


def _freeze_innovations(root: Path, source_id: str, captured: str) -> int:
    """Freeze the original prior-only scale before later source revisions exist."""
    from .features import _innovation_events
    # Keep old revisions: a prior month revised in today's release was not
    # known when forming the strictly pre-capture expectation for that release.
    rows = [row for row in read_jsonl(root / OBSERVATIONS)
            if row["source_id"] == source_id and timestamp(row["retrieved_at"]) <= timestamp(captured)]
    known = read_jsonl(root / EVENTS)
    revisions = {row["revision_id"] for row in known}
    count = 0
    candidates = _innovation_events(rows, as_of=captured)
    latest_periods: dict[str, str] = {}
    for candidate in candidates:
        latest_periods[candidate["family"]] = max(latest_periods.get(candidate["family"], ""), candidate["reference_period"])
    for candidate in candidates:
        if not candidate["numerical_eligible"] or candidate["revision_id"] in revisions:
            continue
        previous = [row for row in known if row["event_id"] == candidate["event_id"]]
        # One historical revision batch is not dozens of independent releases.
        # Previously frozen incidents may still receive explicit corrections.
        if not previous and candidate["reference_period"] != latest_periods[candidate["family"]]:
            continue
        candidate["source_observation_supersedes"] = candidate.get("supersedes")
        candidate["supersedes"] = previous[-1]["revision_id"] if previous else None
        if previous:
            candidate["correction_available_at"] = candidate["available_at"]
            candidate["published_at"] = previous[0]["published_at"]
        count += append_event(root, candidate)
        known.append(candidate)
        revisions.add(candidate["revision_id"])
    return count


def collect_context(root: Path, *, as_of: str | None = None, fetcher=None) -> dict[str, Any]:
    contract = C.load_contract(root)
    requested = timestamp(as_of, "as_of") if as_of else datetime.now(timezone.utc)
    fetch = fetcher or _fetch
    statuses = []
    total_events = total_observations = 0
    for source in _source_list(contract):
        if source.get("enabled", True) is not True:
            continue
        source_id = str(source.get("id") or source.get("source_id") or "")
        source = {**source, "id": source_id}
        url = str(source.get("url") or source.get("endpoint") or "")
        started = datetime.now(timezone.utc).isoformat()
        status = {"source_id": source_id, "retrieved_at": started, "requested_as_of": requested.isoformat(),
                  "events_appended": 0, "observations_appended": 0}
        try:
            if not source_id or not url.startswith("https://"):
                raise C.MarketContextError("enabled source requires id and HTTPS URL")
            body = fetch(url)
            if not isinstance(body, bytes) or len(body) > 8 * 1024 * 1024:
                raise C.MarketContextError("source must return bytes within 8 MiB limit")
            captured = datetime.now(timezone.utc).isoformat()
            receipt = persist_raw(root, source_id=source_id, url=url, body=body, retrieved_at=captured)
            status["retrieved_at"] = captured
            status["receipt_id"] = receipt["receipt_id"]
            format_name = source.get("format", source.get("parser", "rss"))
            if format_name in {"fred_csv", "csv"}:
                window = contract.get("input", {}).get("maximum_captured_observations_per_series", 3000)
                selection = _append_market_csv(root, {**source, "maximum_captured_observations": window}, body, receipt)
                status["observations_appended"] = selection["appended"]
                status["capture_window"] = selection
                status["events_appended"] = _freeze_innovations(root, source_id, captured)
                status["new_innovation_incidents_latest_period_only"] = True
            else:
                if format_name in {"rss", "atom", "rss_atom"}:
                    items = _feed_items(body, url)
                elif format_name == "html_links":
                    parser = _LinkParser(url, tuple(source.get("link_path_fragments", ["/news/", "/newsroom/", "/press-release/"])))
                    parser.feed(body.decode("utf-8", errors="replace"))
                    items = parser.items
                else:
                    raise C.MarketContextError(f"unsupported public parser: {format_name}")
                known = read_jsonl(root / EVENTS)
                keys = {item["dedupe_key"] for item in known}
                for item in items[:int(source.get("max_items", 30))]:
                    terms = source.get("topic_terms", [])
                    if terms and not any(str(term).lower() in item["title"].lower() for term in terms):
                        continue
                    parsed_url = urllib.parse.urlsplit(item["url"])
                    canonical_url = urllib.parse.urlunsplit((parsed_url.scheme, parsed_url.netloc,
                                                            parsed_url.path.rstrip("/"), "", ""))
                    # URL+title is immutable content identity, independently of changing feed bytes.
                    dedupe = digest({"url": canonical_url, "title": item["title"]})
                    if dedupe in keys:
                        continue
                    event_id = "mce-" + digest({"url": canonical_url})[:24]
                    previous = [row for row in known if row["event_id"] == event_id]
                    published = _publication(item["published"], captured)
                    if published and (timestamp(captured) - timestamp(published)).days > int(source.get("max_age_days", 90)):
                        continue
                    row = {"event_id": event_id, "revision_id": "mcr-" + dedupe[:24],
                           "supersedes": previous[-1]["revision_id"] if previous else None,
                           "family": source.get("family", "macro_release"),
                           "axis": source.get("axis", "growth"), "kind": source.get("kind", "official_news"),
                           "title": item["title"], "reference_period": None,
                           "published_at": published, "available_at": published or captured, "retrieved_at": captured,
                           "publication_time_status": "verified_feed_timestamp" if published else "unknown",
                           "source_id": source_id, "source_url": canonical_url,
                           "source_sha256": receipt["source_sha256"], "raw_path": receipt["raw_path"],
                           "dedupe_key": dedupe, "actual": None, "expectation": None,
                           "standardization_scale": None, "unit_metadata": {"actual": None, "expectation": None},
                           "expectation_kind": "none", "expectation_available_at": None,
                           "scale_as_of": None, "scale_sample_count": 0, "surprise_z": None,
                           "numerical_eligible": False, "reason": "reference_only_no_validated_surprise_mapping" if published
                           else "reference_only_unknown_publication_time_first_captured_now"}
                    status["events_appended"] += append_event(root, row)
                    known.append(row)
                    keys.add(dedupe)
                status["items_parsed"] = len(items)
                if not items:
                    raise C.MarketContextError("source parsed no auditable items")
            status["status"] = "quality_degraded" if status.get("capture_window", {}).get("rejected_observations") else "ok"
            if status["status"] == "quality_degraded":
                status["reason"] = "non-session index rows rejected with raw evidence; valid sessions retained"
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, ET.ParseError) as exc:
            status["status"] = "failed"
            status["reason"] = f"{type(exc).__name__}: {exc}"[:500]
        status["status_id"] = digest(status)
        append_unique(root / SOURCE_STATUS, status, "status_id")
        statuses.append(status)
        total_events += status["events_appended"]
        total_observations += status["observations_appended"]
    failed = [row for row in statuses if row["status"] != "ok"]
    finished = max([datetime.now(timezone.utc), *[timestamp(row["retrieved_at"]) for row in statuses]])
    return {"requested_as_of": requested.isoformat(), "as_of": finished.isoformat(),
            "completed_at": finished.isoformat(), "status": "degraded" if failed else "ok",
            "counts": {"events_appended": total_events, "observations_appended": total_observations,
                       "sources": len(statuses), "failed_sources": sum(row["status"] == "failed" for row in statuses),
                       "quality_degraded_sources": sum(row["status"] == "quality_degraded" for row in statuses)}, "sources": statuses}
