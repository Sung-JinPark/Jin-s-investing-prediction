"""Export a frozen read-only macro/market history for V5.2 scenario clustering.

The local dualdb database is never mutated.  The raw capture preserves each
row's source and ingestion vintage; the normalized file keeps only the fields
used by the deterministic scenario-cluster engine.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "dualdb" / "db" / "dualdb.sqlite"
RAW_RELATIVE = Path(
    "data/raw/market/dualdb_macro_cluster_daily_19900102_20260804.json"
)
NORMALIZED_RELATIVE = Path(
    "data/normalized/market/dualdb_macro_cluster_daily_19900102_20260804.json"
)
SERIES = ("NASDAQCOM", "DFF", "DGS2", "DGS10", "T10Y2Y", "VIXCLS", "NFCI")
WINDOW_START = "1990-01-02"
WINDOW_END = "2026-08-04"
AVAILABLE_AT = "2026-08-06T09:15:52+09:00"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> None:
    if not DB_PATH.is_file():
        raise SystemExit(f"missing read-only source database: {DB_PATH}")
    database_sha256 = _sha256(DB_PATH)
    placeholders = ",".join("?" for _ in SERIES)
    uri = f"file:{DB_PATH.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        rows = connection.execute(
            f"""SELECT series_id, date, value, source, ingested_at
                FROM macro_daily
                WHERE series_id IN ({placeholders})
                  AND date BETWEEN ? AND ? AND value IS NOT NULL
                ORDER BY series_id, date""",
            (*SERIES, WINDOW_START, WINDOW_END),
        ).fetchall()
    observed = {row[0] for row in rows}
    if observed != set(SERIES):
        raise SystemExit(f"missing required macro series: {set(SERIES) - observed}")
    if any(not isinstance(row[2], (int, float)) for row in rows):
        raise SystemExit("non-numeric macro value")
    if any(row[4] > "2026-08-06T09:15:52" for row in rows):
        raise SystemExit("macro source contains a future ingestion vintage")

    raw = {
        "schema_version": 1,
        "dataset_id": "DUALDB_MACRO_CLUSTER_DAILY_RAW_19900102_20260804",
        "available_at": AVAILABLE_AT,
        "source_database_path": "dualdb/db/dualdb.sqlite",
        "source_database_sha256": database_sha256,
        "source_table": "macro_daily",
        "series": list(SERIES),
        "window_start": WINDOW_START,
        "window_end": WINDOW_END,
        "row_count": len(rows),
        "rows": [
            {
                "series_id": row[0], "date": row[1], "value": float(row[2]),
                "source": row[3], "ingested_at": row[4],
            }
            for row in rows
        ],
    }
    raw_path = ROOT / RAW_RELATIVE
    _write(raw_path, raw)
    raw_hash = _sha256(raw_path)
    normalized_rows: dict[str, list[dict[str, float | str]]] = {
        series: [] for series in SERIES
    }
    for series, session, value, _source, _ingested_at in rows:
        normalized_rows[series].append({"date": session, "value": float(value)})
    normalized = {
        "schema_version": 1,
        "dataset_id": "DUALDB_MACRO_CLUSTER_DAILY_NORMALIZED_19900102_20260804",
        "available_at": AVAILABLE_AT,
        "value_units": {
            "NASDAQCOM": "index_points", "DFF": "percentage_points",
            "DGS2": "percentage_points", "DGS10": "percentage_points",
            "T10Y2Y": "percentage_points", "VIXCLS": "index_points",
            "NFCI": "z_score",
        },
        "missing_value_policy": "asof_backward_join_without_future_values",
        "raw_source_path": RAW_RELATIVE.as_posix(),
        "raw_sha256": raw_hash,
        "series": normalized_rows,
    }
    normalized_path = ROOT / NORMALIZED_RELATIVE
    _write(normalized_path, normalized)
    print(RAW_RELATIVE.as_posix(), raw_hash, len(rows))
    print(NORMALIZED_RELATIVE.as_posix(), _sha256(normalized_path))


if __name__ == "__main__":
    main()
