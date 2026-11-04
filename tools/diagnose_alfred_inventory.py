"""Read-only paired ALFRED inventory probes. Credentials never enter the report."""
import hashlib
import json
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone
import urllib.error
import urllib.parse
import urllib.request


def probe(series, start, end, key):
    params = {"series_id": series, "realtime_start": start, "realtime_end": end,
              "file_type": "json", "limit": 10000, "offset": 0, "api_key": key}
    url = "https://api.stlouisfed.org/fred/series/vintagedates?" + urllib.parse.urlencode(params)
    result = {"series": series, "start": start, "end": end,
              "retrieved_at": datetime.now(timezone.utc).isoformat()}
    try:
        with urllib.request.urlopen(url, timeout=45) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    except (urllib.error.URLError, TimeoutError):
        return {**result, "status": "network_failure"}
    # Redact defensively even if the provider echoes the request in an error.
    safe = raw.replace(key.encode(), b"REDACTED")
    result.update(status=status, raw_sha256=hashlib.sha256(raw).hexdigest(),
                  response=json.loads(safe))
    return result


def main():
    key = os.environ.get("FRED_API_KEY", "")
    if not key:
        raise SystemExit("Existing FRED workflow secret is required")
    root = Path(__file__).resolve().parents[1]
    receipts = [json.loads(l) for l in (root / "data/timeseries/ledgers/raw_receipts.jsonl").read_text(encoding="utf-8").splitlines() if l]
    now = datetime.now(timezone.utc)
    prior = max(datetime.fromisoformat(r["retrieved_at"]) for r in receipts)
    start = (min(prior, now) - timedelta(days=7)).date().isoformat()
    results = []
    for series in ("M2SL", "WRMFNS", "CPIAUCSL", "NASDAQCOM"):
        for first, last in ((start, "9999-12-31"), (start, now.date().isoformat()),
                            ((now - timedelta(days=366)).date().isoformat(), "9999-12-31")):
            results.append(probe(series, first, last, key))
    report = {"checked_at": now.isoformat(), "original_incremental_start": start,
              "source_or_model_writes": False, "probes": results}
    output = root / ".tmp/alfred-diagnostics.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
