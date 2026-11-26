"""Append-only official/estimated market event calendar for the static dashboard.

The automatic lane is intentionally schedule-only: it records when a release is
due, never the released value.  Official dates supersede rule-derived estimates
by appending a revision; previously registered rows remain byte-for-byte intact.
"""

from __future__ import annotations

import csv
import html
import re
from calendar import month_name
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import yaml


EVENTS_PATH = Path("data/calendar/events.csv")
SOURCES_PATH = Path("data/contracts/calendar_sources.yaml")
EVENT_FIELDS = [
    "event_id", "kind", "date", "time_et", "status", "ticker", "title",
    "source_id", "source_url", "available_at", "registered_at", "supersedes",
    "superseded_by",
]
KINDS = {
    "fomc", "cpi", "nfp", "gdp", "earnings", "pce",
    "consumer_confidence", "manufacturing_pmi", "services_pmi", "other",
}
STATUSES = {"confirmed", "estimated"}
AUTO_KINDS = {
    "gdp", "pce", "consumer_confidence", "manufacturing_pmi", "services_pmi",
}
BEA_PCE_ICS_URL = "https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics"
BEA_SCHEDULE_URL = "https://www.bea.gov/news/schedule"
CONSUMER_CONFIDENCE_URL = "https://www.conference-board.org/topics/consumer-confidence/"
ISM_CALENDAR_URL = (
    "https://www.ismworld.org/supply-management-news-and-reports/"
    "reports/rob-report-calendar/"
)
_MONTHS = {name.lower(): index for index, name in enumerate(month_name) if name}
_SEMANTIC_FIELDS = (
    "kind", "date", "time_et", "status", "ticker", "title", "source_id",
    "source_url",
)
_FetchText = Callable[[str], str]


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
        kinds = source.get("kinds")
        if not isinstance(kinds, list) or not kinds or not set(kinds) <= KINDS:
            raise CalendarError(f"calendar source {source_id} has invalid kinds")
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


def _fetch_text(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "ai-investing-calendar/1.0 (public release schedules only)",
            "Accept": "text/html,text/calendar,text/plain;q=0.9,*/*;q=0.8",
        },
    )
    with urlopen(request, timeout=30) as response:  # noqa: S310 - allowlisted HTTPS contracts
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="strict")


def _unfold_ics(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _ics_unescape(value: str) -> str:
    return (
        value.replace("\\n", "\n").replace("\\N", "\n")
        .replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")
    )


def _parse_ics_datetime(value: str) -> datetime:
    raw = value.strip()
    if re.fullmatch(r"\d{8}T\d{6}Z", raw):
        return datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    if re.fullmatch(r"\d{8}T\d{6}", raw):
        return datetime.strptime(raw, "%Y%m%dT%H%M%S").replace(
            tzinfo=ZoneInfo("America/New_York")
        )
    if re.fullmatch(r"\d{8}", raw):
        return datetime.strptime(raw, "%Y%m%d").replace(
            tzinfo=ZoneInfo("America/New_York")
        )
    raise CalendarError(f"unsupported calendar DTSTART: {value!r}")


def _period_parts(summary: str, fallback: date) -> tuple[str, str]:
    """Return a stable PCE occurrence key and a readable reference-period label."""
    tail = summary.split(",", 1)[1].strip() if "," in summary else ""
    year_match = re.search(r"\b(20\d{2})\b", tail)
    month_matches = list(re.finditer(
        r"\b(" + "|".join(re.escape(name) for name in month_name[1:]) + r")\b",
        tail,
        flags=re.IGNORECASE,
    ))
    if year_match and month_matches:
        year = int(year_match.group(1))
        months = [_MONTHS[match.group(1).lower()] for match in month_matches]
        suffix = "_".join(f"{month:02d}" for month in months)
        label = "·".join(f"{year}년 {month}월" for month in months)
        return f"pce_{year}_{suffix}", label
    return f"pce_release_{fallback:%Y_%m_%d}", tail or fallback.isoformat()


def parse_bea_pce_schedule(text: str) -> list[dict[str, str]]:
    """Parse BEA's public schedule subscription and retain PIO/PCE releases."""
    components: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in _unfold_ics(text):
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            if current is not None:
                components.append(current)
            current = None
            continue
        if current is None or ":" not in line:
            continue
        name, value = line.split(":", 1)
        current[name.split(";", 1)[0]] = _ics_unescape(value)

    events: list[dict[str, str]] = []
    eastern = ZoneInfo("America/New_York")
    for component in components:
        summary = component.get("SUMMARY", "")
        if not summary.startswith("Personal Income and Outlays"):
            continue
        if not component.get("DTSTART"):
            raise CalendarError("BEA PCE schedule event is missing DTSTART")
        release = _parse_ics_datetime(component["DTSTART"]).astimezone(eastern)
        event_id, period_label = _period_parts(summary, release.date())
        events.append({
            "event_id": event_id,
            "kind": "pce",
            "date": release.date().isoformat(),
            "time_et": release.strftime("%H:%M"),
            "status": "confirmed",
            "ticker": "",
            "title": f"PCE 물가지수·개인소득·지출 ({period_label})",
            "source_id": "bea_pce",
            "source_url": BEA_SCHEDULE_URL,
        })
    return events


def _gdp_period_parts(summary: str) -> tuple[int, int, int] | None:
    quarter = re.search(r"\b([1-4])(?:st|nd|rd|th)\s+Quarter\b", summary)
    year = re.search(r"\b(20\d{2})\b", summary)
    if not quarter or not year:
        return None
    lowered = summary.lower()
    if "advance estimate" in lowered or "initial estimate" in lowered:
        revision = 1
    elif "second estimate" in lowered:
        revision = 2
    elif "third estimate" in lowered or "updated estimate" in lowered:
        revision = 3
    else:
        return None
    return int(year.group(1)), int(quarter.group(1)), revision


def parse_bea_gdp_schedule(text: str) -> list[dict[str, str]]:
    """Parse national GDP advance/second/third releases from BEA's ICS feed."""
    components: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in _unfold_ics(text):
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            if current is not None:
                components.append(current)
            current = None
            continue
        if current is not None and ":" in line:
            name, value = line.split(":", 1)
            current[name.split(";", 1)[0]] = _ics_unescape(value)

    eastern = ZoneInfo("America/New_York")
    labels = {1: "속보", 2: "2차", 3: "3차"}
    events: list[dict[str, str]] = []
    for component in components:
        summary = component.get("SUMMARY", "")
        # Exclude state/county GDP series: only the national headline release is
        # in scope for this calendar.
        if not (summary.startswith("Gross Domestic Product") or summary.startswith("GDP (")):
            continue
        parts = _gdp_period_parts(summary)
        if parts is None or not component.get("DTSTART"):
            continue
        year, quarter, revision = parts
        release = _parse_ics_datetime(component["DTSTART"]).astimezone(eastern)
        events.append({
            "event_id": f"gdp_{year}_q{quarter}_{revision}",
            "kind": "gdp",
            "date": release.date().isoformat(),
            "time_et": release.strftime("%H:%M"),
            "status": "confirmed",
            "ticker": "",
            "title": f"GDP {quarter}분기 {labels[revision]} 추정",
            "source_id": "bea_gdp",
            "source_url": BEA_SCHEDULE_URL,
        })
    return events


def _html_text(text: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", html.unescape(text))
    return re.sub(r"\s+", " ", without_tags).strip()


def parse_consumer_confidence_next_release(text: str) -> date | None:
    """Read the exact next date stated on the Conference Board's latest release."""
    plain = _html_text(text)
    updated = re.search(
        r"Updated:\s*[A-Za-z]+,\s*([A-Za-z]+)\s+(\d{1,2}),\s*(20\d{2})",
        plain,
        flags=re.IGNORECASE,
    )
    next_release = re.search(
        r"next release is\s+[A-Za-z]+,\s*([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?"
        r"(?:,?\s*(20\d{2}))?\s+at\s+10\s*(?:a\.?m\.?|AM)\s+ET",
        plain,
        flags=re.IGNORECASE,
    )
    if not updated or not next_release:
        return None
    updated_day = date(
        int(updated.group(3)), _MONTHS[updated.group(1).lower()], int(updated.group(2))
    )
    month = _MONTHS[next_release.group(1).lower()]
    explicit_year = next_release.group(3)
    year = int(explicit_year) if explicit_year else updated_day.year
    if explicit_year is None and month < updated_day.month:
        year += 1
    parsed = date(year, month, int(next_release.group(2)))
    if parsed.weekday() != 1 or not timedelta(0) <= parsed - updated_day <= timedelta(days=62):
        raise CalendarError("Conference Board next-release date failed sanity checks")
    return parsed


class _TableRowParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.lower() == "tr":
            self._row = []
        elif tag.lower() in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None
        elif lowered == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def parse_ism_schedule(text: str) -> dict[tuple[str, int, int], date]:
    """Parse explicit Manufacturing/Services dates from the official ISM table."""
    parser = _TableRowParser()
    parser.feed(text)
    out: dict[tuple[str, int, int], date] = {}
    for row in parser.rows:
        if len(row) < 3:
            continue
        label = re.fullmatch(r"([A-Za-z]+)\s+(20\d{2})", row[0])
        if not label or label.group(1).lower() not in _MONTHS:
            continue
        month = _MONTHS[label.group(1).lower()]
        year = int(label.group(2))
        for kind, raw in zip(("manufacturing_pmi", "services_pmi"), row[1:3]):
            day_match = re.search(r"\b(\d{1,2})\b", raw)
            if day_match:
                out[(kind, year, month)] = date(year, month, int(day_match.group(1)))
    return out


def _month_starts(first: date, last: date) -> list[date]:
    cursor = first.replace(day=1)
    out = []
    while cursor <= last:
        out.append(cursor)
        cursor = (
            date(cursor.year + 1, 1, 1)
            if cursor.month == 12 else date(cursor.year, cursor.month + 1, 1)
        )
    return out


def _last_tuesday(year: int, month: int) -> date:
    following = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    final_day = following - timedelta(days=1)
    return final_day - timedelta(days=(final_day.weekday() - 1) % 7)


def _ism_rule_date(root: Path, year: int, month: int, ordinal: int) -> date:
    from .scenario import future_trading_days, load_calendar_contract

    month_start = date(year, month, 1)
    sessions = future_trading_days(
        month_start - timedelta(days=1), ordinal, load_calendar_contract(root)
    )
    if len(sessions) < ordinal or sessions[ordinal - 1].month != month:
        raise CalendarError(f"could not derive ISM business day for {year}-{month:02d}")
    return sessions[ordinal - 1]


def _previous_month(day: date) -> tuple[int, int]:
    previous = day.replace(day=1) - timedelta(days=1)
    return previous.year, previous.month


def _auto_event(
    *, event_id: str, kind: str, day: date, time_et: str, status: str,
    title: str, source_id: str, source_url: str, registered_at: str,
) -> dict[str, str]:
    return {
        "event_id": event_id,
        "kind": kind,
        "date": day.isoformat(),
        "time_et": time_et,
        "status": status,
        "ticker": "",
        "title": title,
        "source_id": source_id,
        "source_url": source_url,
        "available_at": registered_at,
        "registered_at": registered_at,
        "supersedes": "",
        "superseded_by": "",
    }


def _consumer_confidence_candidates(
    start: date, end: date, exact_next: date | None, registered_at: str,
) -> list[dict[str, str]]:
    out = []
    for month_start in _month_starts(start, end):
        release = _last_tuesday(month_start.year, month_start.month)
        if release < start or release > end:
            continue
        if exact_next and exact_next.year == release.year and exact_next.month == release.month:
            release = exact_next
            status = "confirmed"
        else:
            status = "estimated"
        out.append(_auto_event(
            event_id=f"consumer_confidence_{release:%Y_%m}",
            kind="consumer_confidence",
            day=release,
            time_et="10:00",
            status=status,
            title=f"미국 소비자신뢰지수 ({release.year}년 {release.month}월)",
            source_id="conference_board_consumer_confidence",
            source_url=CONSUMER_CONFIDENCE_URL,
            registered_at=registered_at,
        ))
    return out


def _ism_candidates(
    root: Path, start: date, end: date,
    explicit: dict[tuple[str, int, int], date],
    confirmed_through: date | None, registered_at: str,
) -> list[dict[str, str]]:
    out = []
    specs = (
        ("manufacturing_pmi", "ISM 제조업 PMI", 1, 2),
        ("services_pmi", "ISM 서비스업 PMI", 3, 4),
    )
    for month_start in _month_starts(start, end):
        for kind, label, regular_ordinal, january_ordinal in specs:
            ordinal = january_ordinal if month_start.month == 1 else regular_ordinal
            rule_day = _ism_rule_date(root, month_start.year, month_start.month, ordinal)
            published = explicit.get((kind, month_start.year, month_start.month))
            release = published or rule_day
            if release < start or release > end:
                continue
            is_published = published is not None or (
                confirmed_through is not None and release <= confirmed_through
            )
            period_year, period_month = _previous_month(release)
            out.append(_auto_event(
                event_id=f"{kind}_{period_year}_{period_month:02d}",
                kind=kind,
                day=release,
                time_et="10:00",
                status="confirmed" if is_published else "estimated",
                title=f"{label} ({period_year}년 {period_month}월)",
                source_id="ism_pmi",
                source_url=ISM_CALENDAR_URL,
                registered_at=registered_at,
            ))
    return out


def _base_event_id(event_id: str) -> str:
    return re.sub(r"_r\d+$", "", event_id)


def _same_schedule(left: dict[str, str], right: dict[str, str]) -> bool:
    return all(left.get(field, "") == right.get(field, "") for field in _SEMANTIC_FIELDS)


def _next_revision_id(base_id: str, rows: list[dict[str, str]]) -> str:
    highest = 1
    pattern = re.compile(rf"^{re.escape(base_id)}_r(\d+)$")
    for row in rows:
        if row["event_id"] == base_id:
            highest = max(highest, 1)
        elif match := pattern.fullmatch(row["event_id"]):
            highest = max(highest, int(match.group(1)))
    return f"{base_id}_r{highest + 1}"


def _confirmed_through(contract: dict[str, Any], source_id: str) -> date | None:
    source = next(source for source in contract["sources"] if source["id"] == source_id)
    raw = source.get("confirmed_through")
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw))
    except ValueError as exc:
        raise CalendarError(f"invalid confirmed_through for {source_id}") from exc


def refresh_calendar(
    root: Path,
    *,
    as_of: date | None = None,
    horizon_days: int = 400,
    now: datetime | None = None,
    fetch_text: _FetchText | None = None,
) -> dict[str, Any]:
    """Append a rolling calendar from official schedules and disclosed rules."""
    if horizon_days < 31 or horizon_days > 730:
        raise CalendarError("calendar horizon_days must be between 31 and 730")
    contract = load_source_contract(root)
    source_ids = {str(source["id"]) for source in contract["sources"]}
    required_sources = {
        "bea_pce", "conference_board_consumer_confidence", "ism_pmi",
    }
    missing = required_sources - source_ids
    if missing:
        raise CalendarError(f"automatic calendar sources are unregistered: {sorted(missing)}")

    today = as_of or datetime.now(ZoneInfo("America/New_York")).date()
    end = today + timedelta(days=horizon_days)
    registered = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    registered_at = registered.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    fetch = fetch_text or _fetch_text
    failures: list[str] = []
    warnings: list[str] = []
    candidates: list[dict[str, str]] = []
    source_counts: dict[str, int] = {}

    try:
        bea_schedule = fetch(BEA_PCE_ICS_URL)
        pce = parse_bea_pce_schedule(bea_schedule)
        pce = [event for event in pce if today <= date.fromisoformat(event["date"]) <= end]
        if not pce:
            raise CalendarError("official BEA subscription returned no future PCE releases")
        pce_candidates = [
            _auto_event(
                event_id=event["event_id"], kind=event["kind"],
                day=date.fromisoformat(event["date"]), time_et=event["time_et"],
                status=event["status"], title=event["title"],
                source_id=event["source_id"], source_url=event["source_url"],
                registered_at=registered_at,
            )
            for event in pce
        ]
        candidates.extend(pce_candidates)
        source_counts["bea_pce"] = len(pce_candidates)
    except (CalendarError, OSError, UnicodeError) as exc:
        failures.append(f"bea_pce: {exc}")
        source_counts["bea_pce"] = 0

    try:
        gdp = parse_bea_gdp_schedule(bea_schedule)
        gdp = [event for event in gdp if today <= date.fromisoformat(event["date"]) <= end]
        if not gdp:
            raise CalendarError("official BEA subscription returned no future GDP releases")
        gdp_candidates = [
            _auto_event(
                event_id=event["event_id"], kind=event["kind"],
                day=date.fromisoformat(event["date"]), time_et=event["time_et"],
                status=event["status"], title=event["title"],
                source_id=event["source_id"], source_url=event["source_url"],
                registered_at=registered_at,
            )
            for event in gdp
        ]
        candidates.extend(gdp_candidates)
        source_counts["bea_gdp"] = len(gdp_candidates)
    except (CalendarError, OSError, UnicodeError, UnboundLocalError) as exc:
        failures.append(f"bea_gdp: {exc}")
        source_counts["bea_gdp"] = 0

    exact_confidence: date | None = None
    try:
        exact_confidence = parse_consumer_confidence_next_release(
            fetch(CONSUMER_CONFIDENCE_URL)
        )
        if exact_confidence is None:
            raise CalendarError("official page did not expose its exact next release")
    except (CalendarError, OSError, UnicodeError) as exc:
        failures.append(f"conference_board_consumer_confidence: {exc}")
    confidence = _consumer_confidence_candidates(
        today, end, exact_confidence, registered_at
    )
    candidates.extend(confidence)
    source_counts["conference_board_consumer_confidence"] = len(confidence)

    explicit_ism: dict[tuple[str, int, int], date] = {}
    try:
        explicit_ism = parse_ism_schedule(fetch(ISM_CALENDAR_URL))
        if not explicit_ism:
            warnings.append(
                "ism_pmi: explicit table unavailable; used ISM cadence and NYSE closures"
            )
    except (OSError, UnicodeError) as exc:
        warnings.append(f"ism_pmi: {exc}; used ISM cadence and NYSE closures")
    ism = _ism_candidates(
        root, today, end, explicit_ism,
        _confirmed_through(contract, "ism_pmi"), registered_at,
    )
    candidates.extend(ism)
    source_counts["ism_pmi"] = len(ism)

    candidate_bases = [_base_event_id(event["event_id"]) for event in candidates]
    if len(candidate_bases) != len(set(candidate_bases)):
        raise CalendarError("automatic calendar produced duplicate logical events")

    rows = _read_rows(root)
    active = load_events(root)
    active_by_base = {
        _base_event_id(row["event_id"]): row
        for row in active if row["kind"] in AUTO_KINDS
    }
    appended: list[str] = []
    corrected: list[str] = []
    unchanged = 0
    for candidate in sorted(candidates, key=lambda row: (row["date"], row["kind"])):
        base_id = _base_event_id(candidate["event_id"])
        current = active_by_base.get(base_id)
        if current and _same_schedule(current, candidate):
            unchanged += 1
            continue
        if current:
            candidate["event_id"] = _next_revision_id(base_id, rows)
            candidate["supersedes"] = current["event_id"]
            corrected.append(candidate["event_id"])
        if append_event(root, candidate):
            appended.append(candidate["event_id"])
            normalized = {field: str(candidate.get(field, "")) for field in EVENT_FIELDS}
            rows.append(normalized)
            active_by_base[base_id] = normalized

    return {
        "as_of": today.isoformat(),
        "horizon_end": end.isoformat(),
        "registered_at": registered_at,
        "source_counts": source_counts,
        "appended": appended,
        "corrected": corrected,
        "unchanged": unchanged,
        "failures": failures,
        "warnings": warnings,
    }
