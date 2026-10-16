"""Download public Yahoo history HTML; never invoke a broker or securities API.

The rendered page's embedded public chart JSON is extracted offline. History is
currently revised, not an archived point-in-time vintage. That limitation is
retained explicitly and blocks prospective claims.
"""
from __future__ import annotations
import concurrent.futures
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import urllib.request

ROOT = Path(__file__).resolve().parent
AS_OF = "2026-10-12T10:38:50+09:00"
LAST_SESSION = "2026-10-09"


def parse_public_html(raw: str, symbol: str) -> dict:
    candidates = []
    for script in re.findall(r"<script[^>]*>(.*?)</script>", raw, re.S):
        if "adjclose" not in script:
            continue
        try:
            wrapper = json.loads(script)
            body = json.loads(wrapper["body"])
            result = body["chart"]["result"][0]
        except (KeyError, ValueError, TypeError, IndexError):
            continue
        if result["meta"]["symbol"] == symbol and "adjclose" in result["indicators"]:
            candidates.append(result)
    if len(candidates) != 1:
        raise ValueError(f"Expected one public daily adjusted series: {symbol}, found {len(candidates)}")
    return candidates[0]


def collect(symbol: str) -> dict:
    period1 = int(dt.datetime(2008, 1, 1, tzinfo=dt.timezone.utc).timestamp())
    period2 = int(dt.datetime(2026, 10, 10, tzinfo=dt.timezone.utc).timestamp())
    url = f"https://finance.yahoo.com/quote/{symbol}/history/?period1={period1}&period2={period2}"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=40) as response:
        raw = response.read()
    retrieved = dt.datetime.now(dt.timezone.utc).isoformat()
    html_path = ROOT / "source_html" / f"{symbol}_history.html"
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_bytes(raw)
    result = parse_public_html(raw.decode("utf-8"), symbol)
    quote = result["indicators"]["quote"][0]
    adjusted = result["indicators"]["adjclose"][0]["adjclose"]
    rows = []
    for i, timestamp in enumerate(result["timestamp"]):
        observation_date = dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).date().isoformat()
        if observation_date > LAST_SESSION:
            raise ValueError("Future or incomplete session in history")
        values = {field: quote[field][i] for field in ["open", "high", "low", "close", "volume"]}
        rows.append({"date": observation_date, "symbol": symbol, **values,
                     "adj_close": adjusted[i], "available_at": "", "vintage": "retrieved_current_history",
                     "source_id": f"YAHOO_HISTORY_{symbol}", "retrieved_at": retrieved})
    csv_path = ROOT / "price_inputs" / f"{symbol}_adjusted_history.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    events_path = ROOT / "price_inputs" / f"{symbol}_events.json"
    events_path.write_text(json.dumps(result.get("events", {}), ensure_ascii=False, indent=2), encoding="utf-8")
    return {"symbol": symbol, "url": url, "retrieved_at": retrieved, "rows": len(rows),
            "first_session": rows[0]["date"], "last_session": rows[-1]["date"],
            "last_close": rows[-1]["close"], "last_adj_close": rows[-1]["adj_close"],
            "adjustment_definition": "Yahoo history page: adjusted close includes splits and dividend/capital-gain distributions",
            "available_at": None, "historical_original_vintage_verified": False,
            "as_of_eligibility": "retrospective research only; archived delivery timestamp unavailable",
            "source_html": str(html_path.relative_to(ROOT)).replace("\\", "/"),
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "csv": str(csv_path.relative_to(ROOT)).replace("\\", "/"),
            "csv_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
            "dividend_event_count": len(result.get("events", {}).get("dividends", {})),
            "split_event_count": len(result.get("events", {}).get("splits", {}))}


if __name__ == "__main__":
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        histories = list(executor.map(collect, ["SOXX", "IGV", "SPY"]))
    output = {"research_as_of": AS_OF, "histories": histories,
              "canonical_probability_unit": "fraction", "original_vintage_gate": "blocked"}
    (ROOT / "price_history_manifest.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
