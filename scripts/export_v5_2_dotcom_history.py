"""Export the frozen point-in-time Nasdaq dotcom history for Scenario V5.2.

The local dualdb database is opened read-only.  This exporter creates a raw
capture plus a compact normalized manifest; it never changes dualdb or any
official forecast, ledger, snapshot, or archive.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "dualdb" / "db" / "dualdb.sqlite"
RAW_RELATIVE = Path(
    "data/raw/market/dualdb_ixic_dotcom_daily_19950103_20041231.json"
)
NORMALIZED_RELATIVE = Path(
    "data/normalized/market/dualdb_ixic_dotcom_daily_19950103_20041231.json"
)
WINDOW_START = "1995-01-03"
WINDOW_END = "2004-12-31"
AVAILABLE_AT = "2026-07-30T16:33:42+09:00"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> None:
    if not DB_PATH.is_file():
        raise SystemExit(f"missing read-only source database: {DB_PATH}")
    database_sha256 = _sha256(DB_PATH)
    uri = f"file:{DB_PATH.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        rows = connection.execute(
            """SELECT date, close, source, ingested_at
               FROM price_daily
               WHERE series = '^IXIC' AND date BETWEEN ? AND ?
               ORDER BY date""",
            (WINDOW_START, WINDOW_END),
        ).fetchall()
    if len(rows) != 2519 or rows[0][0] != WINDOW_START or rows[-1][0] != WINDOW_END:
        raise SystemExit("unexpected dotcom source coverage")
    if any(not isinstance(row[1], (int, float)) or float(row[1]) <= 0 for row in rows):
        raise SystemExit("invalid dotcom close")
    if {row[2] for row in rows} != {"fred-close+yahoo-ohlcv"}:
        raise SystemExit("unexpected dotcom source provenance")
    if {row[3] for row in rows} != {"2026-07-30T16:33:42"}:
        raise SystemExit("unexpected dotcom ingestion vintage")

    raw = {
        "schema_version": 1,
        "dataset_id": "DUALDB_IXIC_DOTCOM_DAILY_RAW_19950103_20041231",
        "series": "^IXIC",
        "window_start": WINDOW_START,
        "window_end": WINDOW_END,
        "available_at": AVAILABLE_AT,
        "source_database_path": "dualdb/db/dualdb.sqlite",
        "source_database_sha256": database_sha256,
        "source_table": "price_daily",
        "source_query_contract": (
            "series='^IXIC'; date between 1995-01-03 and 2004-12-31; order by date"
        ),
        "row_count": len(rows),
        "rows": [
            {
                "date": row[0],
                "close": float(row[1]),
                "source": row[2],
                "ingested_at": row[3],
            }
            for row in rows
        ],
    }
    raw_path = ROOT / RAW_RELATIVE
    _write(raw_path, raw)
    raw_sha256 = _sha256(raw_path)
    normalized = {
        "schema_version": 1,
        "dataset_id": "DUALDB_IXIC_DOTCOM_DAILY_NORMALIZED_19950103_20041231",
        "series": "^IXIC",
        "available_at": AVAILABLE_AT,
        "probability_unit": "fraction",
        "level_unit": "index_points",
        "return_method": "close_to_close_log_return",
        "raw_source_path": RAW_RELATIVE.as_posix(),
        "raw_sha256": raw_sha256,
        "row_count": len(rows),
        "first_session": rows[0][0],
        "last_session": rows[-1][0],
        "generator_role": "dotcom_episode_base_and_local_residual_pool",
        "rows": [{"date": row[0], "close": float(row[1])} for row in rows],
    }
    _write(ROOT / NORMALIZED_RELATIVE, normalized)
    print(RAW_RELATIVE.as_posix(), raw_sha256)
    print(NORMALIZED_RELATIVE.as_posix(), _sha256(ROOT / NORMALIZED_RELATIVE))


if __name__ == "__main__":
    main()
