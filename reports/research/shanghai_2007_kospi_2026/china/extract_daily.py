"""Transcribe daily closes from public SSE annual tables; no interpolation."""
import csv
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import fitz

ROOT = Path(__file__).resolve().parent
PAGES = {
    2005: {"sse_composite": (2006, 13, 5), "sse_a_share": (2006, 16, 8)},
    2006: {"sse_composite": (2007, 13, 5), "sse_a_share": (2007, 16, 8)},
    2007: {"sse_composite": (2008, 20, 8), "sse_a_share": (2008, 24, 12)},
    2008: {"sse_composite": (2009, 14, 8), "sse_a_share": (2009, 18, 12)},
}
EXPECTED_COUNT = {2005: 242, 2006: 241, 2007: 242, 2008: 246}
EXPECTED_LAST = {
    (2005, "sse_composite"): 1161.06, (2005, "sse_a_share"): 1220.93,
    (2006, "sse_composite"): 2675.47, (2006, "sse_a_share"): 2815.13,
    (2007, "sse_composite"): 5261.56, (2007, "sse_a_share"): 5521.49,
    (2008, "sse_composite"): 1820.81, (2008, "sse_a_share"): 1911.79,
}


def main():
    manifest = json.loads((ROOT / "source_manifest.json").read_text(encoding="utf8"))
    sources = {s["source_id"]: s for s in manifest["sources"]}
    rows = []
    audits = []
    for year, indices in PAGES.items():
        dates_by_index = {}
        for index_id, (book_year, pdf_page, printed_page) in indices.items():
            source_id = f"sse_yearbook_{book_year}"
            source = sources[source_id]
            with fitz.open(ROOT / source["local_path"]) as doc:
                text = doc[pdf_page - 1].get_text()
            (ROOT / f"raw_table_page_{book_year}_{pdf_page}.txt").write_text(text, encoding="utf8")
            assert "Daily Index" in text
            assert ("SSE Composite Index" if index_id == "sse_composite" else "SSE A Share Index") in text
            table = text.split("Dec", 1)[1].split("最高", 1)[0]
            chunks = re.split(r"(?m)^\s*(\d{1,2})\s*$", table)
            assert len(chunks) == 63, (source_id, pdf_page, "Expected 31 daily rows")
            table_rows = []
            omitted_cells = 0
            for j in range(1, len(chunks), 2):
                day = int(chunks[j])
                tokens = re.sub(r"-\s*-\s*-", "---", chunks[j + 1]).split()
                assert len(tokens) == 12, (source_id, pdf_page, day, tokens)
                for month, value in enumerate(tokens, 1):
                    if value == "---":
                        omitted_cells += 1
                        continue
                    assert re.fullmatch(r"\d+\.\d{2}", value), (source_id, pdf_page, day, month, value)
                    observation_date = date(year, month, day)
                    assert observation_date.weekday() < 5, ("Non-weekday observation", observation_date)
                    table_rows.append({"date": observation_date.isoformat(), "index_id": index_id,
                        "index_name": "SSE Composite Index" if index_id == "sse_composite" else "SSE A Share Index",
                        "close": value, "unit": "index_points", "value_origin": "official_numeric_table_transcription",
                        "source_id": source_id, "source_path": source["local_path"],
                        "source_pdf_page_1based": pdf_page, "source_printed_page": printed_page,
                        "source_table": "Daily Index / 每日收盘指数", "source_row_day": day,
                        "source_column_month": month, "source_sha256": source["sha256"]})
            table_rows.sort(key=lambda row: row["date"])
            assert len(table_rows) == EXPECTED_COUNT[year], (year, index_id, len(table_rows))
            assert float(table_rows[-1]["close"]) == EXPECTED_LAST[year, index_id], (year, index_id, table_rows[-1])
            dates_by_index[index_id] = [row["date"] for row in table_rows]
            rows.extend(table_rows)
            audits.append({"year": year, "index_id": index_id, "observations": len(table_rows),
                "omitted_source_dash_cells": omitted_cells, "pdf_page_1based": pdf_page,
                "printed_page": printed_page, "first": table_rows[0], "last": table_rows[-1]})
        assert dates_by_index["sse_composite"] == dates_by_index["sse_a_share"]
    rows.sort(key=lambda r: (r["index_id"], r["date"]))
    assert len({(r["index_id"], r["date"]) for r in rows}) == len(rows)
    output = ROOT / "daily_indices_2005_2008.csv"
    with output.open("w", encoding="utf8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    result = {"schema_version": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "artifact": output.name, "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "row_count": len(rows), "date_start": "2005-01-04", "date_end": "2008-12-31",
        "basis": "Unadjusted official price-index closing levels; no dividends; original index base, not rebased.",
        "units": {"close": "index_points"},
        "method": "Read original PDF text layer; require 31 rows and 12 month cells, retain only original numeric cells; omit source dashes; no filling, interpolation or inferred trading days.",
        "pit_status": "Retrospective yearbook snapshots. Observation date identifies the historical session; exact original publication/available_at timestamps have not been established. Unsuitable as an official point-in-time forecast input without separate availability validation.",
        "checks": ["Every original row has 12 month cells", "All source cells are decimal numbers or explicit dashes", "All numeric cells form valid weekday dates", "Counts 242/241/242/246 for 2005/2006/2007/2008 for each index", "Composite and A Share dates identical per year", "Year-end closes match original annual-summary table", "No duplicate date/index pairs"],
        "table_audits": audits}
    (ROOT / "daily_extraction_audit_2005_2008.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf8")
    print(json.dumps({"path": str(output), "rows": len(rows), "sha256": result["sha256"]}, indent=2))


if __name__ == "__main__":
    main()
