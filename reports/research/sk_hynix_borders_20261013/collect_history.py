"""Capture public history HTML for a retrospective chart; no securities API calls."""
import concurrent.futures
import datetime as dt
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parent
first = int(dt.datetime(2025, 9, 1, tzinfo=dt.timezone.utc).timestamp())
last = int(dt.datetime(2026, 10, 14, tzinfo=dt.timezone.utc).timestamp())
SOURCES = {
    "yahoo": f"https://finance.yahoo.com/quote/000660.KS/history/?period1={first}&period2={last}",
    "stockanalysis": "https://stockanalysis.com/quote/krx/000660/history/",
    "naver_quote": "https://m.stock.naver.com/domestic/stock/000660/total",
    "naver_history": "https://finance.naver.com/item/sise_day.naver?code=000660&page=1",
}

def collect(item):
    name, url = item
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read()
        path = ROOT / f"source_{name}.html"
        path.write_bytes(raw)
        result = {"name": name, "url": url, "path": path.name, "bytes": len(raw),
                  "retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                  "sha256": hashlib.sha256(raw).hexdigest()}
    except Exception as exc:
        result = {"name": name, "url": url, "error": str(exc)}
    print(json.dumps(result, ensure_ascii=True), flush=True)
    return result

if __name__ == "__main__":
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(collect, SOURCES.items()))
    (ROOT / "source_manifest.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
