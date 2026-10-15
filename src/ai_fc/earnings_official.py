"""Read-only, point-in-time adapters for explicitly reported ASML/TSMC results.

Company-reported EPS is a separate metric from Nasdaq's USD consensus.  This
module never converts currencies or share units and never writes a ledger.
"""

from __future__ import annotations

import hashlib
import html
import math
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import parse_qsl, urljoin, urlparse
from zoneinfo import ZoneInfo


class OfficialEarningsError(ValueError):
    """An official result could not be identified without guessing its meaning."""


_HOSTS = {
    "ASML": {"investor.asml.com", "www.investor.asml.com", "www.asml.com", "live.euronext.com"},
    "TSM": {"investor.tsmc.com", "pr.tsmc.com"},
}
_QUARTERS = {"first": 1, "second": 2, "third": 3, "fourth": 4}
_MONTHS = {name: index for index, name in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"), 1)}
_MAX_FETCHES = 6


def _clean(value: str) -> str:
    return " ".join(html.unescape(value).replace("\xa0", " ").split())


def _utc(value: datetime | str) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise OfficialEarningsError("invalid source timestamp") from exc
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise OfficialEarningsError("source timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


def _identity(event: dict[str, Any]) -> tuple[str, int, int]:
    ticker = str(event.get("ticker", "")).upper()
    if ticker not in _HOSTS:
        raise OfficialEarningsError("official adapter supports ASML/TSM only")
    if not event.get("event_id") or event.get("kind", "earnings") != "earnings":
        raise OfficialEarningsError("registered earnings event required")
    year, quarter = event.get("fiscal_year"), event.get("fiscal_quarter")
    if year is None or quarter is None:
        match = re.search(r"(?:^|_)(20\d{2})_q([1-4])(?:_|$)", str(event["event_id"]), re.I)
        if not match:
            raise OfficialEarningsError("explicit fiscal year and quarter required")
        year, quarter = match.groups()
    try:
        year, quarter = int(year), int(quarter)
    except (TypeError, ValueError) as exc:
        raise OfficialEarningsError("invalid fiscal year/quarter") from exc
    if not 2000 <= year <= 2100 or quarter not in (1, 2, 3, 4):
        raise OfficialEarningsError("invalid fiscal year/quarter")
    return ticker, year, quarter


def _url(ticker: str, value: str) -> str:
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise OfficialEarningsError("invalid issuer source port") from exc
    if (parsed.scheme != "https" or parsed.hostname not in _HOSTS[ticker]
            or parsed.username or parsed.password or port not in (None, 443)
            or any(key.lower() in {"key", "api_key", "apikey", "token", "access_token"}
                   for key, _ in parse_qsl(parsed.query))):
        raise OfficialEarningsError("unapproved issuer source URL")
    return value


def official_urls(event: dict[str, Any]) -> list[str]:
    """Finite discovery roots; fiscal identity is checked again in each release."""
    ticker, year, quarter = _identity(event)
    if ticker == "ASML":
        # Euronext carries the issuer's original full release and is available
        # when the issuer IR site's transport is blocked. It is attributed as
        # issuer-distributed Euronext, never relabelled as an ASML-hosted page.
        return ["https://live.euronext.com/en/listview/company-press-release/058805",
                "https://investor.asml.com/quarterly-results"]
    return [f"https://investor.tsmc.com/english/quarterly-results/{year}/q{quarter}",
            "https://pr.tsmc.com/english"]


class _Document(HTMLParser):
    """Keep semantic cells/links, including empty spacer cells in ASML tables."""

    def __init__(self, text: str):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.headings: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.node_links: list[tuple[str, str]] = []
        self.isins: set[str] = set()
        self.tables: list[list[list[str]]] = []
        self.published: list[str] = []
        self._skip = 0
        self._heading: list[str] | None = None
        self._link: tuple[str, list[str]] | None = None
        self._link_node: str | None = None
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self.feed(text)
        self.close()
        self.text = _clean(" ".join(self.parts))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs = dict(attrs)
        if tag in {"script", "style"}:
            self._skip += 1
        if self._skip:
            return
        if tag in {"h1", "title"}:
            self._heading = []
        if tag == "a":
            self._link = (attrs.get("href") or "", [])
            self._link_node = attrs.get("data-node-nid")
        if attrs.get("data-isin"):
            self.isins.update(item.strip() for item in attrs["data-isin"].split(","))
        if tag == "table" and self._table is None:
            self._table = []
        if tag == "tr" and self._table is not None:
            self._row = []
        if tag in {"th", "td"} and self._row is not None:
            self._cell = []
        if tag in {"br", "p", "div"}:
            self.handle_data(" ")
        if tag == "meta" and (attrs.get("property") or attrs.get("name") or "").lower() in {
                "article:published_time", "datepublished", "date", "dcterms.created"}:
            self.published.append(attrs.get("content") or "")
        if tag == "time" and attrs.get("datetime"):
            self.published.append(attrs["datetime"] or "")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip:
            self._skip -= 1
            return
        if self._skip:
            return
        if tag in {"h1", "title"} and self._heading is not None:
            self.headings.append(_clean(" ".join(self._heading)))
            self._heading = None
        if tag == "a" and self._link is not None:
            self.links.append((self._link[0], _clean(" ".join(self._link[1]))))
            if self._link_node and self._link_node.isdigit():
                self.node_links.append((self._link_node, _clean(" ".join(self._link[1]))))
            self._link = None
            self._link_node = None
        if tag in {"th", "td"} and self._cell is not None and self._row is not None:
            self._row.append(_clean(" ".join(self._cell)))
            self._cell = None
        if tag == "tr" and self._row is not None and self._table is not None:
            self._table.append(self._row)
            self._row = None
        if tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None

    def handle_data(self, value: str) -> None:
        if self._skip:
            return
        self.parts.append(value)
        for target in (self._heading, self._cell):
            if target is not None:
                target.append(value)
        if self._link is not None:
            self._link[1].append(value)


def _number(text: str) -> float:
    text = _clean(text)
    if not re.fullmatch(r"-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", text):
        raise OfficialEarningsError(f"invalid reported numeric value: {text!r}")
    value = float(text.replace(",", ""))
    if not math.isfinite(value):
        raise OfficialEarningsError("nonfinite reported numeric value")
    return value


def _publication(doc: _Document) -> tuple[str | None, str | None]:
    for value in doc.published:
        try:
            parsed = _utc(value)
        except OfficialEarningsError:
            continue  # A date or naive local clock is not a documented UTC instant.
        return _iso(parsed), parsed.date().isoformat()
    # This is an explicit source offset (CEST/CET), not an inferred timezone
    # from an earnings call or from a local clock without a zone.
    match = re.search(r"\b(\d{1,2})\s+([A-Za-z]{3})\s+(20\d{2})\s+(\d{2}:\d{2})\s+(CEST|CET)\b", doc.text)
    if match:
        parsed = datetime.strptime(" ".join(match.groups()[:4]), "%d %b %Y %H:%M")
        parsed = parsed.replace(tzinfo=timezone(timedelta(hours=2 if match[5] == "CEST" else 1)))
        return _iso(parsed), parsed.date().isoformat()
    match = re.search(r"(?:Press release\s*[-–]\s*|Issued on:\s*)([A-Za-z]+\s+\d{1,2},?\s+20\d{2}|20\d{2}/\d{2}/\d{2})", doc.text, re.I)
    if match:
        for pattern in ("%B %d, %Y", "%B %d %Y", "%Y/%m/%d"):
            try:
                return None, datetime.strptime(match[1], pattern).date().isoformat()
            except ValueError:
                pass
    return None, None


def _deduplicate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        previous = result.get(row["metric"])
        if previous and (previous["actual_value"], previous["unit"], previous["share_basis"]) != (
                row["actual_value"], row["unit"], row["share_basis"]):
            raise OfficialEarningsError("conflicting reported metric in the same release")
        result.setdefault(row["metric"], row)
    return list(result.values())


def parse_official(event: dict[str, Any], raw_text: str, *, source_url: str,
                   captured_at: datetime | str, as_of: datetime | str | None = None) -> list[dict[str, Any]]:
    """Parse actual results only. Guidance/index pages return an empty list.

    Availability is the response completion clock, even when publication is
    earlier. A supplied cutoff cannot backdate the captured source.
    """
    ticker, year, quarter = _identity(event)
    _url(ticker, source_url)
    capture = _utc(captured_at)
    cutoff = _utc(as_of) if as_of is not None else capture
    if capture > cutoff:
        raise OfficialEarningsError("source captured after as_of")
    if not isinstance(raw_text, str) or not raw_text.strip() or len(raw_text) > 8_000_000:
        raise OfficialEarningsError("empty or oversized official HTML")
    doc = _Document(raw_text)
    published_at, published_date = _publication(doc)
    rows: list[dict[str, Any]] = []
    period_end: str | None = None

    def row(metric: str, label: str, value: float, actual: str, unit: str,
            currency: str | None, share_basis: str, eps_basis: str | None = None) -> None:
        rows.append({
            "event_id": str(event["event_id"]), "metric": metric, "label": label,
            "actual": actual, "actual_value": value, "consensus": None, "previous": None,
            "period": f"Q{quarter} {year}", "fiscal_year": year, "fiscal_quarter": quarter,
            "period_end": period_end, "unit": unit, "currency": currency,
            "share_basis": share_basis, "eps_basis": eps_basis,
            "accounting_basis": "US_GAAP" if ticker == "ASML" else "TIFRS",
            "comparison_allowed": False,
            "source": ("ASML issuer-distributed Euronext" if urlparse(source_url).hostname == "live.euronext.com"
                       else f"{ticker} official IR"),
            "source_url": source_url, "source_hash": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
            "published_at": published_at, "published_date": published_date,
            "captured_at": _iso(capture), "available_at": _iso(capture),
            "note": "회사 발표 원단위. 통화·주당 단위 변환 및 USD 컨센서스 비교를 하지 않습니다.",
        })

    headline = " ".join(doc.headings)
    if ticker == "ASML":
        # An archive/index may mention every period; require a result headline.
        if not re.search(r"ASML\s+reports\b", headline, re.I):
            return []
        periods = re.findall(r"\bQ([1-4])\s*[- ]?\s*(20\d{2})\b", headline, re.I)
        if set(periods) != {(str(quarter), str(year))}:
            raise OfficialEarningsError("ASML release fiscal period does not match event")
        if urlparse(source_url).hostname == "live.euronext.com" and (
                "NL0010273215" not in doc.isins or not re.search(r"ASML\s+HOLDING\s+N\.?\s*V\.?", doc.text, re.I)):
            raise OfficialEarningsError("Euronext release ASML issuer/ISIN not verified")
        if not re.search(r"(?:US\s*GAAP|U\.S\.\s*GAAP)", doc.text, re.I):
            raise OfficialEarningsError("ASML accounting basis not explicitly US GAAP")
        end = re.search(r"(?:quarter|months)\s+ended\s+([A-Za-z]+)\s+(\d{1,2}),?\s+(20\d{2})", doc.text, re.I)
        if end and end[1].lower() in _MONTHS:
            end_date = datetime(int(end[3]), _MONTHS[end[1].lower()], int(end[2])).date()
            if end_date.year != year or (end_date.month - 1) // 3 + 1 != quarter:
                raise OfficialEarningsError("ASML fiscal end does not match event")
            period_end = end_date.isoformat()
        for table in doc.tables:
            columns = [(index, cell) for cells in table for index, cell in enumerate(cells)
                       if re.fullmatch(fr"Q{quarter}\s+{year}", cell, re.I)]
            if len(columns) != 1:
                continue
            index = columns[0][0]
            for cells in table:
                if not cells or not cells[0]:
                    continue
                label = cells[0].lower()
                if not any(part in label for part in ("eps", "total net sales", "gross margin")):
                    continue
                if len(cells) <= index:
                    raise OfficialEarningsError("ASML financial table missing target-period cell")
                if "eps" in label:
                    if not re.fullmatch(r"eps\s*\(basic;?\s*in\s+euros\)", label, re.I):
                        continue
                    value = _number(cells[index])
                    row("eps_reported", "기본 EPS (EUR/보통주)", value, f"EUR {value:.2f}",
                        "currency_per_share", "EUR", "ordinary_share", "basic")
                elif label == "total net sales":
                    if not re.search(r"millions of euros", " ".join(" ".join(x) for x in table), re.I):
                        raise OfficialEarningsError("ASML revenue unit not explicitly million EUR")
                    value = _number(cells[index])
                    row("revenue_reported", "매출 (백만 EUR)", value, f"EUR {value:,.0f}M",
                        "million_currency", "EUR", "not_applicable")
                elif re.fullmatch(r"gross margin\s*\(%\)", label):
                    value = _number(cells[index])
                    if not 0 <= value <= 100:
                        raise OfficialEarningsError("gross margin percent out of bounds")
                    row("gross_margin_reported", "매출총이익률 (%)", value, f"{value:g}%",
                        "percent", None, "not_applicable")
        if not any(item["metric"] == "eps_reported" for item in rows):
            raise OfficialEarningsError("ASML basic EUR EPS missing or malformed")
    else:
        if not re.search(r"TSMC\s+Reports\s+(?:First|Second|Third|Fourth)\s+Quarter\s+EPS", headline, re.I):
            return []  # In particular, the 3Q guidance table is not an actual.
        heading_quarters = re.findall(r"TSMC\s+Reports\s+(First|Second|Third|Fourth)\s+Quarter\s+EPS", headline, re.I)
        if {_QUARTERS[word.lower()] for word in heading_quarters} != {quarter}:
            raise OfficialEarningsError("TSMC result headline quarter does not match event")
        pattern = (r"diluted\s+earnings\s+per\s+share\s+(?:of\s+)?NT\$\s*([\d,.]+)"
                   r"(?:\s*\(\s*US\$\s*([\d,.]+)\s+per\s+ADR\s+unit\s*\))?"
                   r"\s+for\s+the\s+(first|second|third|fourth)\s+quarter\s+ended\s+"
                   r"([A-Za-z]+)\s+(\d{1,2}),?\s+(20\d{2})")
        matches = list(re.finditer(pattern, doc.text, re.I))
        matches = [m for m in matches if _QUARTERS[m[3].lower()] == quarter and int(m[6]) == year]
        if not matches:
            raise OfficialEarningsError("TSMC actual EPS fiscal period missing or mismatched")
        if not re.search(r"\bTIFRS\b", doc.text):
            raise OfficialEarningsError("TSMC accounting basis not explicitly TIFRS")
        for match in matches:
            if match[4].lower() not in _MONTHS:
                raise OfficialEarningsError("invalid TSMC fiscal period end")
            end = datetime(int(match[6]), _MONTHS[match[4].lower()], int(match[5])).date()
            if (end.month - 1) // 3 + 1 != quarter:
                raise OfficialEarningsError("TSMC quarter-end month does not match event")
            period_end = end.isoformat()
            value = _number(match[1])
            row("eps_reported", "희석 EPS (TWD/보통주)", value, f"TWD {value:.2f}",
                "currency_per_share", "TWD", "ordinary_share", "diluted")
            if match[2] is not None:
                value = _number(match[2])
                row("eps_reported_adr", "희석 EPS (USD/ADR)", value, f"USD {value:.2f}",
                    "currency_per_adr", "USD", "ADR_unit", "diluted")

    if published_at is not None and _utc(published_at) > min(cutoff, capture):
        raise OfficialEarningsError("official publication is after capture/as_of")
    if published_at is None and published_date is not None:
        issuer_zone = ZoneInfo("Europe/Amsterdam" if ticker == "ASML" else "Asia/Taipei")
        # A date-only release cannot establish a publication instant, but a
        # future date in the issuer's local calendar is still not an actual.
        if published_date > min(capture, cutoff).astimezone(issuer_zone).date().isoformat():
            raise OfficialEarningsError("official publication date is after capture/as_of")
    return _deduplicate(rows)


def _release_links(event: dict[str, Any], text: str, base: str) -> list[str]:
    ticker, year, quarter = _identity(event)
    doc = _Document(text)
    words = next(word for word, value in _QUARTERS.items() if value == quarter)
    result: list[str] = []
    if ticker == "ASML" and urlparse(base).hostname == "live.euronext.com":
        for node, label in doc.node_links:
            if re.search(fr"ASML\s+reports\b.*\bQ{quarter}\s+{year}\b", label, re.I):
                result.append(f"https://live.euronext.com/ajax/node/company-press-release/{node}")
    for href, label in doc.links:
        url = urljoin(base, href)
        try:
            _url(ticker, url)
        except OfficialEarningsError:
            continue
        if ticker == "ASML":
            relevant = (re.search(fr"\bq{quarter}[- /]?{year}\b", f"{url} {label}", re.I)
                        and re.search(r"reports|press.release|news-release|financial.results", f"{url} {label}", re.I))
        else:
            relevant = (urlparse(url).hostname == "pr.tsmc.com"
                        and re.search(r"/english/news/\d+(?:$|[?#])", url)
                        and re.search(fr"Reports\s+{words}\s+Quarter\s+EPS", label, re.I))
        if relevant and url not in result:
            result.append(url)
    return result[:3]


def discover_issuer_release(event: dict[str, Any], *, fetch_text: Callable[[str], Any],
                            now: datetime | None = None) -> dict[str, Any]:
    """Fetch a bounded set of issuer HTML sources, retaining raw source receipts.

    ``fetch_text`` may return text or ``{text, captured_at, source_url?}``. Plain
    text is timestamped *after* the response; fixture/replay clocks must be
    provided explicitly. Passing ``now`` establishes a cutoff, never a capture
    clock. The caller owns persistence and can replay with an offline callback.
    """
    ticker, _, _ = _identity(event)
    cutoff = _utc(now) if now is not None else None
    queue = official_urls(event)
    visited: set[str] = set()
    receipts: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    attempt_failures: list[dict[str, str]] = []
    while queue and len(visited) < _MAX_FETCHES:
        requested = queue.pop(0)
        if requested in visited:
            continue
        visited.add(requested)
        try:
            response = fetch_text(requested)
            completed = datetime.now(timezone.utc)
            if isinstance(response, str):
                text, captured, source = response, completed, requested
            elif isinstance(response, dict):
                text = response.get("text", response.get("raw_text"))
                captured = _utc(response.get("captured_at", completed))
                source = response.get("source_url", requested)
            else:
                raise OfficialEarningsError("official fetch must return text or structured text receipt")
            _url(ticker, source)
            if not isinstance(text, str):
                raise OfficialEarningsError("official response text missing")
            receipt = {"source_url": source, "request_url": requested, "raw_text": text,
                       "source_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                       "captured_at": _iso(captured)}
            receipts.append(receipt)
            rows = parse_official(event, text, source_url=source, captured_at=captured,
                                  as_of=cutoff if cutoff is not None else completed)
            candidates.extend(rows)
            if rows:
                break
            queue[0:0] = [link for link in _release_links(event, text, source) if link not in visited]
        except Exception as exc:  # A failed issuer fetch is explicit, never an invented actual.
            failure = {"source_url": requested, "reason": str(exc), "error_type": type(exc).__name__}
            if isinstance(exc, OfficialEarningsError):
                errors.append(failure)
            else:
                attempt_failures.append(failure)
    candidates = _deduplicate(candidates)
    if errors:
        candidates = []  # A parse-integrity failure cannot be hidden by another source.
    return {"status": "failed" if errors else ("released" if candidates else (
                "failed" if attempt_failures else "pending")),
            "candidates": candidates, "receipts": receipts, "errors": errors,
            "attempt_failures": attempt_failures}
