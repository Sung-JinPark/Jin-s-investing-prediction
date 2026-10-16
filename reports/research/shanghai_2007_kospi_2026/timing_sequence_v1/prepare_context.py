"""Archive public historical context and price chronology without production writes."""
from datetime import datetime, timezone
import csv
import hashlib
import json
from pathlib import Path
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parent
STUDY = ROOT.parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    baseline = ROOT / "original_study_before.json"
    if not baseline.exists():
        files = {p.relative_to(STUDY).as_posix(): sha(p) for p in STUDY.rglob("*")
                 if p.is_file() and ROOT not in p.parents and "__pycache__" not in p.parts}
        baseline.write_text(json.dumps({"captured_at_utc": datetime.now(timezone.utc).isoformat(),
                            "sha256": files}, indent=2) + "\n", encoding="utf-8")
    out = ROOT / "context"
    out.mkdir(exist_ok=True)
    sources = [
        ("FED-20080122", "https://www.federalreserve.gov/newsevents/pressreleases/monetary20080122b.htm",
         "2008-01-22", "html"),
        ("BIS-200803", "https://www.bis.org/publ/qtrpdf/r_qt0803.pdf", "2008-03", "pdf"),
        ("BIS-200803-OVERVIEW", "https://www.bis.org/publications/qr/r-qt0803a.pdf", "2008-03-03", "pdf"),
        ("IMF-REO-200804", "https://www.elibrary.imf.org/display/book/9781589067103/C1.xml", "2008-04", "html"),
    ]
    records = []
    for source_id, url, published, extension in sources:
        path = out / f"{source_id}.{extension}"
        previous = None
        manifest = out / "source_manifest.json"
        if manifest.exists():
            previous = next((r for r in json.loads(manifest.read_text(encoding="utf-8"))["sources"]
                             if r["source_id"] == source_id and r.get("sha256") == (sha(path) if path.exists() else None)), None)
        if previous:
            if source_id == "BIS-200803" and previous.get("content_type", "").startswith("text/html"):
                previous.update(status="saved_redirect_index_html", received_format="HTML despite requested PDF URL",
                                role="Index-page response only; do not treat as the article PDF")
            records.append(previous)
            continue
        record = {"source_id": source_id, "url": url, "published_date_or_month": published,
                  "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                  "historical_role": "contemporaneous assessment or release, read only at/after its publication",
                  "original_collection_vintage_certified": False}
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=40) as response:
                body = response.read()
                record.update(http_status=response.status, resolved_url=response.url,
                              content_type=response.headers.get("Content-Type"))
            path.write_bytes(body)
            record.update(local_path=path.name, sha256=sha(path), bytes=len(body), status="saved")
            record["received_format"] = "PDF" if body.startswith(b"%PDF-") else "HTML or other"
            if extension == "pdf" and not body.startswith(b"%PDF-"):
                record.update(status="saved_redirect_index_html", role="Non-PDF response retained, not article PDF")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
            record.update(status="failed", error=str(error))
        records.append(record)
    (out / "source_manifest.json").write_text(json.dumps({"sources": records}, ensure_ascii=False,
                                              indent=2) + "\n", encoding="utf-8")

    rows = list(csv.DictReader((STUDY / "prices/prices.csv").open(encoding="utf-8")))
    result = []
    selected = {
        "SSE_COMPOSITE": ["2007-10-16", "2007-10-31", "2007-11-28", "2007-12-28",
                          "2008-01-14", "2008-01-22", "2008-02-22", "2008-03-18",
                          "2008-04-18", "2008-04-30", "2008-05-05", "2008-06-02"],
        "KOSPI": ["2026-06-22", "2026-05-28", "2026-07-15", "2026-07-16", "2026-07-30",
                  "2026-08-27", "2026-09-23", "2026-10-08", "2026-10-14", "2026-10-15"],
    }
    for symbol, dates in selected.items():
        series = [r for r in rows if r["symbol"] == symbol]
        peak_date = dates[0]
        peak = float(next(r["close"] for r in series if r["date"] == peak_date))
        peak_index = next(i for i, r in enumerate(series) if r["date"] == peak_date)
        for date in dates:
            matching = [(i, r) for i, r in enumerate(series) if r["date"] == date]
            if not matching:
                raise ValueError(f"Requested date has no actual close: {symbol}/{date}")
            index, row = matching[0]
            result.append({"symbol": symbol, "date": date, "close_index_points": float(row["close"]),
                           "peak_reference_date": peak_date, "peak_reference_close": peak,
                           "return_from_observed_peak_fraction": float(row["close"])/peak-1,
                           "peak_reference_is_future_to_observation": date < peak_date,
                           "actual_return_intervals_from_peak": index-peak_index,
                           "source_id": row["source_id"], "source_path": row["source_path"],
                           "source_pdf_page_1based": row["source_pdf_page_1based"]})
    price_result = {"as_of": "2026-10-16T09:00:00+09:00", "price_cutoff": "2026-10-15",
                    "source_csv_relative_to_study": "prices/prices.csv", "source_sha256": sha(STUDY / "prices/prices.csv"),
                    "return_unit": "fraction", "rows": result,
                    "role": "descriptive chronology, not forecasting features or trading instructions"}
    (ROOT / "price_chronology.json").write_text(json.dumps(price_result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (ROOT / "price_chronology.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(result[0]))
        writer.writeheader()
        writer.writerows(result)
    print(json.dumps({"sources": [{"id": r["source_id"], "status": r["status"]} for r in records],
                      "price_observations": len(result)}))


if __name__ == "__main__":
    main()
