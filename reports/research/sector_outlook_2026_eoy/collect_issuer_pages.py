"""Collect public issuer HTML tables into an isolated research artifact.

No broker API, credentials, database, model, or ledger is accessed.
Re-running collects a new current vintage; it cannot reproduce a past web page.
The frozen issuer_observations.json is the input for reproducible calculations.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
import json
import re
import urllib.request

AS_OF = "2026-10-12T09:16:14+09:00"
ROOT = Path(__file__).resolve().parent
SLUGS = {
    "XLC": "communication-services", "XLY": "consumer-discretionary",
    "XLP": "consumer-staples", "XLE": "energy", "XLF": "financial",
    "XLV": "health-care", "XLI": "industrial", "XLB": "materials",
    "XLRE": "real-estate", "XLK": "technology", "XLU": "utilities",
}

def to_text(html):
    html = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", html, flags=re.S | re.I)
    parser = HTMLParser()
    parts = []
    parser.handle_data = parts.append
    parser.feed(html)
    return re.sub(r"\s+", " ", " ".join(parts)).replace("\ufeff", "")

def find(pattern, text):
    match = re.search(pattern, text)
    return match.group(1).strip() if match else None

def date(s):
    return datetime.strptime(s, "%b %d %Y").date().isoformat() if s else None

def num(s):
    return float(s.replace(",", "")) if s is not None else None

def collect(ticker):
    slug = ("state-street-spdr-sp-500-etf-trust-spy" if ticker == "SPY" else
            f"state-street-{SLUGS[ticker]}-select-sector-spdr-etf-{ticker.lower()}")
    url = "https://www.ssga.com/us/en/intermediary/etfs/" + slug
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            raw = response.read()
        text = to_text(raw.decode("utf-8"))
        market = text.split("Fund Market Price as of ", 1)[1].split("Premium Discount", 1)[0]
        chars = text.split("Fund Characteristics as of ", 1)[1].split("Index Characteristics", 1)[0]
        yields = text.split("Yields as of ", 1)[1].split("Fund Market Price", 1)[0]
        perf = text.split("Fund Performance", 1)[1]
        perf_match = re.search(r"Fund Before Tax NAV\s+(\w{3} \d{2} \d{4})\s+(-?[\d.]+)%\s+(-?[\d.]+)%\s+(-?[\d.]+)%", perf)
        row = {
            "id": "US-ISSUER-" + ticker, "ticker": ticker, "publisher": "State Street Investment Management",
            "url": url, "title": ticker + " issuer fund table", "source_class": "research_reference_proxy",
            "retrieved_at": datetime.now(timezone.utc).isoformat(), "published_at": None,
            "availability_basis": "Dated issuer observations precede cutoff; precise page-publication time not supplied.",
            "pit_certified": False, "raw_html_sha256": sha256(raw).hexdigest(),
            "currency": "USD", "close_date": date(find(r"^(\w{3} \d{2} \d{4})", market)),
            "expense_ratio_annual_fraction": (lambda x: x / 100 if x is not None else None)(num(find(r"most recent prospectus\.\s*([\d.]+)%", text))),
            "expense_ratio_definition": "Issuer published gross annual fund expense ratio; explicit source percent converted to fraction.",
            "close": num(find(r"Closing Price.*?Primary Listing Exchange\.\s*\$([\d,.]+)", market)),
            "valuation_date": date(find(r"^(\w{3} \d{2} \d{4})", chars)),
            "pe_fy1": num(find(r"outliers are included in the calculation\.\s*([\d.]+)", chars)),
            "pe_definition": "Weighted harmonic average current share price / forecasted one-year EPS; includes negative and positive outliers; FY1, not necessarily NTM.",
            "holdings_count": num(find(r"Number of Holdings\s+(\d+)", chars)),
            "distribution_yield_fraction": (lambda x: x / 100 if x is not None else None)(num(find(r"Fund Distribution Yield.*?expressed as a percentage\.\s*([\d.]+)%", yields))),
            "distribution_yield_definition": "Trailing 365-day distributions / NAV; not a promised remaining-year dividend.",
            "performance_date": date(perf_match[1]) if perf_match else None,
            "nav_total_return_1m": float(perf_match[2]) / 100 if perf_match else None,
            "nav_total_return_3m": float(perf_match[3]) / 100 if perf_match else None,
            "nav_total_return_ytd": float(perf_match[4]) / 100 if perf_match else None,
            "performance_definition": "Issuer NAV before-tax total return; QTD at September 30 is the 3-month quarter; dividends reinvested, fees reflected.",
            "source_text_excerpt": "", "error": None,
        }
        if row["close_date"] != "2026-10-09":
            row["price_gap"] = "Issuer page does not provide the last completed US session close (2026-10-09); use only as a dated reference, not a current executable quote."
        else:
            row["price_gap"] = None
        for key in ("close_date", "valuation_date", "performance_date"):
            if row[key] and row[key] > AS_OF[:10]:
                raise ValueError(f"future observation: {key}={row[key]}")
        return row
    except Exception as exc:
        return {"id": "US-ISSUER-" + ticker, "ticker": ticker, "url": url,
                "error": type(exc).__name__ + ": " + str(exc), "source_class": "research_reference_proxy"}

def main():
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(collect, [*SLUGS, "SPY"]))
    payload = {"as_of": AS_OF, "probability_unit": "fraction", "return_unit": "fraction",
               "warning": "Frozen public-page observations, not certified historical PIT vintages or official numerical inputs.",
               "observations": rows}
    (ROOT / "issuer_observations.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for r in rows:
        print(json.dumps({k: r.get(k) for k in ("ticker", "close_date", "close", "pe_fy1", "distribution_yield_fraction", "performance_date", "nav_total_return_1m", "nav_total_return_3m", "nav_total_return_ytd", "error")}, ensure_ascii=False))

if __name__ == "__main__":
    main()
