"""Official earnings adapters retain fiscal identity, units, and capture clocks."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest

from ai_fc import earnings_official as official


CAPTURE = datetime(2026, 10, 15, 0, 20, tzinfo=timezone.utc)
ASML_URL = "https://investor.asml.com/news-releases/news-release-details/q3-2026-results"
EURONEXT_URL = "https://live.euronext.com/ajax/node/company-press-release/12916206"
TSM_URL = "https://pr.tsmc.com/english/news/3333"


def event(ticker="ASML", year=2026, quarter=3):
    return {"event_id": f"{ticker.lower()}_{year}_q{quarter}", "kind": "earnings",
            "ticker": ticker, "fiscal_year": year, "fiscal_quarter": quarter,
            "date": "2026-10-14" if ticker == "ASML" else "2026-10-15"}


def asml_html(eps="12.95", *, quarter=3, year=2026, extra="", euronext=False):
    identity = ('<div data-isin="NL0010273215, NL0010273215">Issuer ASML HOLDING N.V.</div>'
                '<p>14 Oct 2026 07:00 CEST</p>') if euronext else ""
    return f"""<html><head><title>ASML reports net sales in Q{quarter} {year}</title></head>
    <body>{identity}<h1>ASML reports net sales in Q{quarter} {year}</h1>
    <p>Press release - October 14, 2026</p>
    <p>The quarter and nine months ended September 27, 2026. US GAAP Financial Reporting.</p>
    <table><tr><td>(Figures in millions of euros unless otherwise indicated)</td>
    <td>Q2 2026</td><td>&nbsp;</td><td>Q{quarter} {year}</td></tr>
    <tr><td>Total net sales</td><td>9,326</td><td></td><td><b>11,662</b></td></tr>
    <tr><td>Gross margin (%)</td><td>54.0</td><td></td><td>57.5</td></tr>
    <tr><td>EPS (basic; in euros)</td><td>7.59</td><td>&nbsp;</td><td>{eps}</td></tr>
    <tr><td>Diluted net income per ordinary share</td><td>7.58</td><td></td><td>12.93</td></tr>
    </table>{extra}</body></html>"""


def tsm_html(*, quarter="third", year=2026, month="September", day=30, adr=True):
    adr_text = " (US$4.31 per ADR unit)" if adr else ""
    return f"""<html><head><script>Not an actual: EPS 999</script></head>
    <h1>TSMC Reports {quarter.title()} Quarter EPS of NT$27.25</h1>
    <p>Issued on: <time datetime="2026-10-15T00:00:00Z">2026/10/15</time></p>
    <p>TSMC today announced consolidated revenue and diluted earnings per share of
    NT$27.25{adr_text} for the {quarter} quarter ended {month} {day}, {year}.</p>
    <p>All figures were prepared in accordance with TIFRS on a consolidated basis.</p></html>"""


def parse(text, *, ticker="ASML", url=None, **kwargs):
    return official.parse_official(event(ticker), text, source_url=url or (
        ASML_URL if ticker == "ASML" else TSM_URL), captured_at=CAPTURE, **kwargs)


def test_asml_spacer_columns_basic_eur_and_fiscal_end():
    text = asml_html()
    rows = {r["metric"]: r for r in parse(text)}
    eps = rows["eps_reported"]
    assert eps["actual_value"] == 12.95 and eps["actual"] == "EUR 12.95"
    assert eps["eps_basis"] == "basic" and eps["currency"] == "EUR"
    assert eps["share_basis"] == "ordinary_share" and eps["accounting_basis"] == "US_GAAP"
    assert eps["consensus"] is None and eps["comparison_allowed"] is False
    assert eps["period_end"] == "2026-09-27" and eps["fiscal_quarter"] == 3
    assert eps["available_at"] == eps["captured_at"] == "2026-10-15T00:20:00Z"
    assert eps["published_at"] is None and eps["published_date"] == "2026-10-14"
    assert eps["source_hash"] == hashlib.sha256(text.encode()).hexdigest()
    assert rows["revenue_reported"]["actual_value"] == 11662
    assert rows["revenue_reported"]["unit"] == "million_currency"
    assert rows["gross_margin_reported"]["actual_value"] == 57.5
    assert len(rows) == 3


def test_euronext_issuer_identity_and_explicit_cest_publication():
    rows = parse(asml_html(euronext=True), url=EURONEXT_URL)
    assert rows[0]["source"] == "ASML issuer-distributed Euronext"
    assert rows[0]["published_at"] == "2026-10-14T05:00:00Z"
    for bad in (asml_html(euronext=True).replace("NL0010273215", "XX0000000000"),
                asml_html(euronext=True).replace("ASML HOLDING N.V.", "OTHER COMPANY")):
        with pytest.raises(official.OfficialEarningsError, match="issuer/ISIN"):
            parse(bad, url=EURONEXT_URL)


@pytest.mark.parametrize("value", ["NaN", "12.95-13.0", "EUR 12.95", "12.95abc", ""])
def test_malformed_eps_rejected(value):
    with pytest.raises(official.OfficialEarningsError, match="numeric"):
        parse(asml_html(value))


@pytest.mark.parametrize("change", [
    lambda s: s.replace("Q3 2026", "Q2 2026"),
    lambda s: s.replace("Q3 2026", "Q3 2025"),
    lambda s: s.replace("US GAAP", "IFRS"),
    lambda s: s.replace("in euros", "in dollars"),
    lambda s: s.replace("millions of euros", "billions of euros"),
    lambda s: s.replace("September 27, 2026", "June 30, 2026"),
])
def test_asml_wrong_period_units_accounting_rejected(change):
    with pytest.raises(official.OfficialEarningsError):
        parse(change(asml_html()))


def test_future_capture_and_publication_are_not_backdated():
    with pytest.raises(official.OfficialEarningsError, match="captured after"):
        parse(asml_html(), as_of=datetime(2026, 10, 14, tzinfo=timezone.utc))
    future = '<meta property="article:published_time" content="2026-10-16T05:00:00Z">'
    with pytest.raises(official.OfficialEarningsError, match="publication"):
        parse(asml_html(extra=future))
    with pytest.raises(official.OfficialEarningsError, match="publication date"):
        parse(asml_html().replace("Press release - October 14, 2026", "Press release - October 16, 2026"))


def test_conflicting_release_headings_are_rejected():
    with pytest.raises(official.OfficialEarningsError, match="period"):
        parse(asml_html().replace("<h1>ASML reports net sales in Q3 2026", "<h1>ASML reports net sales in Q2 2026"))


def test_tsm_guidance_page_has_no_actual_for_current_quarter():
    text = """<h1>Financial Results - 2026Q3</h1><p>Third Quarter 2026 Earnings Conference
    will be held on October 15, 2026 at 14:00 Taiwan time.</p>
    <table><tr><th></th><th colspan="2">2Q26</th><th>3Q26</th></tr>
    <tr><th></th><th>Actual</th><th>Guidance</th><th>Guidance</th></tr>
    <tr><td>Net Revenue (US$ billion)</td><td>40.20</td><td>39.0-40.2</td>
    <td>44.6-45.8</td></tr></table>"""
    assert parse(text, ticker="TSM", url="https://investor.tsmc.com/english/quarterly-results/2026/q3") == []


def test_tsm_explicit_common_and_adr_units_are_separate_metrics():
    rows = {r["metric"]: r for r in parse(tsm_html(), ticker="TSM")}
    assert rows["eps_reported"]["actual"] == "TWD 27.25"
    assert rows["eps_reported"]["share_basis"] == "ordinary_share"
    assert rows["eps_reported"]["eps_basis"] == "diluted"
    assert rows["eps_reported"]["accounting_basis"] == "TIFRS"
    assert rows["eps_reported_adr"]["actual"] == "USD 4.31"
    assert rows["eps_reported_adr"]["share_basis"] == "ADR_unit"
    assert all(r["comparison_allowed"] is False and r["consensus"] is None for r in rows.values())
    assert rows["eps_reported"]["period_end"] == "2026-09-30"
    assert len(parse(tsm_html(adr=False), ticker="TSM")) == 1


@pytest.mark.parametrize("text", [tsm_html(quarter="second", month="June"),
                                      tsm_html(year=2025), tsm_html(month="June"),
                                      tsm_html().replace("TIFRS", "US GAAP")])
def test_tsm_prior_actual_or_wrong_basis_cannot_be_current_actual(text):
    with pytest.raises(official.OfficialEarningsError):
        parse(text, ticker="TSM")


def test_duplicate_whitespace_deduplicates_and_conflicting_values_fail():
    text = asml_html()
    table = text[text.index("<table>"):text.index("</table>") + 8]
    rows = parse(text.replace("</body>", table + "</body>"))
    assert len(rows) == 3
    assert [r["actual"] for r in parse(text.replace("<b>", "<b>\n\t "))] == [r["actual"] for r in rows]
    with pytest.raises(official.OfficialEarningsError, match="conflicting"):
        parse(text.replace("</body>", table.replace("12.95", "99.99") + "</body>"))


def test_discovery_euronext_node_chain_preserves_exact_receipts():
    roots = official.official_urls(event())
    listing = ('<a href="" data-node-nid="12916206">ASML reports €11.7 billion '
               'total net sales in Q3 2026</a><a href="https://evil.example/q3-2026-results">'
               'ASML reports Q3 2026</a>')
    pages = {roots[0]: listing, EURONEXT_URL: asml_html(euronext=True)}
    calls = []
    def fetch(url):
        calls.append(url)
        return {"text": pages[url], "captured_at": CAPTURE, "source_url": url}
    result = official.discover_issuer_release(event(), fetch_text=fetch, now=CAPTURE)
    assert result["status"] == "released" and len(result["candidates"]) == 3
    assert calls == [roots[0], EURONEXT_URL]
    assert result["receipts"][0]["raw_text"] == listing
    assert result["receipts"][1]["source_hash"] == hashlib.sha256(pages[EURONEXT_URL].encode()).hexdigest()
    assert result["errors"] == []


def test_discovery_transport_fallback_is_diagnostic_and_parse_integrity_is_fatal():
    root1, root2 = official.official_urls(event())
    def fetch(url):
        if url == root1:
            raise RuntimeError("HTTP 403")
        if url == root2:
            return {"text": '<a href="/news-releases/news-release-details/q3-2026-results">ASML reports Q3 2026</a>',
                    "captured_at": CAPTURE}
        return {"text": asml_html(), "captured_at": CAPTURE}
    result = official.discover_issuer_release(event(), fetch_text=fetch, now=CAPTURE)
    assert result["status"] == "released" and len(result["attempt_failures"]) == 1
    assert result["errors"] == []
    broken = official.discover_issuer_release(event(), fetch_text=lambda _url: {
        "text": asml_html("NaN"), "captured_at": CAPTURE}, now=CAPTURE)
    assert broken["status"] == "failed" and broken["candidates"] == []
    assert broken["errors"]


def test_tsm_pending_discovery_does_not_fetch_prior_quarter_article():
    calls = []
    def fetch(url):
        calls.append(url)
        return {"text": '<h1>Financial Results 2026Q3</h1><a href="https://pr.tsmc.com/english/news/3326">'
                        'TSMC Reports Second Quarter EPS of NT$27.25</a>', "captured_at": CAPTURE}
    result = official.discover_issuer_release(event("TSM"), fetch_text=fetch, now=CAPTURE)
    assert result["status"] == "pending" and result["candidates"] == []
    assert calls == official.official_urls(event("TSM"))


def test_tsm_new_actual_release_can_be_discovered_from_official_press_index():
    quarter, press_index = official.official_urls(event("TSM"))
    pages = {quarter: "<h1>Financial Results 2026Q3</h1><p>Guidance</p>",
             press_index: '<a href="/english/news/3333">TSMC Reports Third Quarter EPS of NT$27.25</a>',
             TSM_URL: tsm_html()}
    calls = []
    def fetch(url):
        calls.append(url)
        return {"text": pages[url], "captured_at": CAPTURE}
    result = official.discover_issuer_release(event("TSM"), fetch_text=fetch, now=CAPTURE)
    assert result["status"] == "released" and len(result["candidates"]) == 2
    assert calls == [quarter, press_index, TSM_URL]


@pytest.mark.parametrize("url", ["http://investor.asml.com/a", "https://evil.example/a",
                                     "https://user:pass@investor.asml.com/a",
                                     "https://investor.asml.com/a?api_key=sensitive"])
def test_unapproved_source_urls_are_rejected(url):
    with pytest.raises(official.OfficialEarningsError, match="source URL"):
        parse(asml_html(), url=url)


def test_unsupported_or_unidentified_event_is_rejected():
    with pytest.raises(official.OfficialEarningsError, match="ASML/TSM"):
        official.official_urls(event("MSFT"))
    with pytest.raises(official.OfficialEarningsError, match="fiscal"):
        official.official_urls({"event_id": "asml_unknown", "ticker": "ASML"})
