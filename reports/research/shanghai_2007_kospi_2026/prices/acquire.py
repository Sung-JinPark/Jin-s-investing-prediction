"""Download public, unauthenticated historical HTML/CSV documents only.

This is a reproducible acquisition helper, not needed for offline analytics.
No broker endpoint, credential, live quote API, or dependency is used.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import html
import io
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
AS_OF = "2026-10-16T09:00:00+09:00"


def download(source_id: str, url: str, suffix: str = ".html") -> tuple[bytes, dict]:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=45) as response:
        payload = response.read()
        status = response.status
        final_url = response.url
    path = RAW / (source_id + suffix)
    path.write_bytes(payload)
    return payload, {
        "source_id": source_id, "url": url, "final_url": final_url,
        "http_status": status, "retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "raw_file": path.relative_to(ROOT).as_posix(),
        "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload),
        "access_method": "unauthenticated_static_historical_document",
    }


def yahoo_rows(payload: bytes, symbol: str, currency: str, source_id: str) -> list[dict]:
    text = payload.decode("utf8")
    rows = []
    for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>", text, re.S):
        cells = [html.unescape(re.sub(r"<[^>]+>", "", td)).strip()
                 for td in re.findall(r"<td\b[^>]*>(.*?)</td>", tr, re.S)]
        if len(cells) != 7:
            continue
        try:
            date = dt.datetime.strptime(cells[0], "%b %d, %Y").date().isoformat()
            numbers = [float(c.replace(",", "")) for c in cells[1:6]]
        except ValueError:
            continue
        rows.append(dict(date=date, open=numbers[0], high=numbers[1], low=numbers[2],
                         close=numbers[3], adjusted_close=numbers[4], symbol=symbol,
                         currency=currency, source_id=source_id,
                         price_type="unadjusted_index_close"))
    rows.sort(key=lambda r: r["date"])
    if len({r["date"] for r in rows}) != len(rows):
        raise ValueError(f"Duplicate dates: {source_id}")
    return rows


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    all_rows, sources, failures = [], [], []
    jobs = [
        ("yahoo_sse_composite_2005_2008", "000001.SS", "SSE_COMPOSITE", "CNY", "2005-01-01", "2009-01-01"),
        ("yahoo_sse_a_2005_2008", "000002.SS", "SSE_A", "CNY", "2005-01-01", "2009-01-01"),
        ("yahoo_kospi_2024_2026", "^KS11", "KOSPI", "KRW", "2024-10-01", "2026-10-16"),
        ("yahoo_msci_world_2005_2008", "^990100-USD-STRD", "MSCI_WORLD", "USD", "2005-01-01", "2009-01-01"),
        ("yahoo_msci_world_2024_2026", "^990100-USD-STRD", "MSCI_WORLD", "USD", "2024-10-01", "2026-10-16"),
    ]
    for source_id, ticker, symbol, currency, start, end in jobs:
        params = dict(period1=int(dt.datetime.fromisoformat(start).replace(tzinfo=dt.timezone.utc).timestamp()),
                      period2=int(dt.datetime.fromisoformat(end).replace(tzinfo=dt.timezone.utc).timestamp()), frequency="1d")
        url = "https://finance.yahoo.com/quote/" + urllib.parse.quote(ticker, safe="") + "/history/?" + urllib.parse.urlencode(params)
        try:
            payload, meta = download(source_id, url)
            meta.update(provider="Yahoo Finance", provider_ticker=ticker, symbol=symbol, currency=currency,
                        requested_start=start, requested_end_exclusive=end,
                        title=html.unescape(re.findall(r"<title>(.*?)</title>", payload.decode("utf8"), re.S)[0]))
            rows = yahoo_rows(payload, symbol, currency, source_id)
            if not rows:
                raise ValueError("No historical daily rows in public HTML")
            meta.update(row_count=len(rows), first_observation=rows[0]["date"], last_observation=rows[-1]["date"],
                        unit="index_points", adjustment="close; not dividend total return",
                        available_at_policy="historical_market_close_date; original publication timestamps not supplied")
            sources.append(meta)
            all_rows.extend(rows)
            print(source_id, len(rows), rows[0]["date"], rows[-1]["date"], rows[-1]["close"], flush=True)
        except Exception as exc:
            failures.append(dict(source_id=source_id, url=url, error=f"{type(exc).__name__}: {exc}"))
            print(source_id, "UNAVAILABLE", type(exc).__name__, str(exc), flush=True)
    for symbol, fred_id, currency in [("KRW_PER_USD", "DEXKOUS", "KRW/USD"), ("CNY_PER_USD", "DEXCHUS", "CNY/USD")]:
        for start, end in [("2005-01-01", "2008-12-31"), ("2024-10-01", "2026-10-15")]:
            source_id = f"fred_{fred_id.lower()}_{start[:4]}_{end[:4]}"
            url = f"https://fred.stlouisfed.org/graph.csv?id={fred_id}&cosd={start}&coed={end}"
            try:
                payload, meta = download(source_id, url, ".csv")
                fx = []
                for row in csv.DictReader(io.StringIO(payload.decode("utf8-sig"))):
                    date = row.get("observation_date", row.get("DATE"))
                    value = row.get(fred_id, "")
                    if date and value not in ("", "."):
                        fx.append(dict(date=date, close=float(value), symbol=symbol, currency=currency,
                                       source_id=source_id, price_type="reference_fx_local_currency_per_usd"))
                if not fx:
                    raise ValueError("No FX observations")
                meta.update(provider="Federal Reserve via FRED", provider_ticker=fred_id, symbol=symbol,
                            currency=currency, unit="local_currency_per_usd", row_count=len(fx),
                            first_observation=fx[0]["date"], last_observation=fx[-1]["date"],
                            missing_policy="FRED dot observations retained in raw CSV, omitted from canonical observations",
                            time_basis="New York noon buying rate; not synchronous with Asian equity close",
                            available_at_policy="retrieved historical vintage; original release timestamp unavailable")
                all_rows.extend(fx); sources.append(meta)
                print(source_id, len(fx), fx[0]["date"], fx[-1]["date"], flush=True)
            except Exception as exc:
                failures.append(dict(source_id=source_id, url=url, error=f"{type(exc).__name__}: {exc}"))
                print(source_id, "UNAVAILABLE", type(exc).__name__, str(exc), flush=True)
    fields = ["date", "symbol", "currency", "close", "open", "high", "low", "adjusted_close", "source_id", "price_type"]
    with (ROOT / "prices.csv").open("w", newline="", encoding="utf8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader(); writer.writerows(sorted(all_rows, key=lambda r: (r["symbol"], r["date"])))
    manifest = dict(schema_version=1, as_of=AS_OF, cutoff_date="2026-10-15", research_only=True,
                    sources=sources, failed_acquisitions=failures,
                    policies=dict(no_interpolation=True, no_live_broker_or_quote_api=True, credentials_used=False,
                                  original_publication_timestamps_available=False,
                                  vintage_warning="Retrospectively retrieved public history; not a point-in-time forecast input."))
    (ROOT / "source_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf8")


if __name__ == "__main__":
    main()
