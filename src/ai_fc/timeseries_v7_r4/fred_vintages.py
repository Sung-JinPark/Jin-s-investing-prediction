"""Durable, idempotent FRED/ALFRED vintage ingestion."""

from __future__ import annotations

import csv
import io
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .integrity import canonical_json, sha256_bytes


@dataclass(frozen=True)
class IngestResult:
    inserted_revisions: int
    cursor: str
    parse_path: Path


class FredVintageIngestor:
    """Persist ALFRED ``output_type=3`` revisions and a committed cursor.

    Raw, receipt, and parsed artifacts are content addressed.  Database rows and
    the cursor share one transaction, so an interrupted attempt is safely
    repeatable and can never publish a cursor ahead of its revisions.
    """

    def __init__(self, output_root: Path, connection: sqlite3.Connection):
        self.output_root = Path(output_root)
        self.connection = connection
        self._create_schema()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS fred_revisions (
              series_id TEXT NOT NULL, observation_date TEXT NOT NULL,
              realtime_start TEXT NOT NULL, realtime_end TEXT NOT NULL,
              value TEXT NOT NULL, raw_sha256 TEXT NOT NULL,
              PRIMARY KEY(series_id, observation_date, realtime_start, realtime_end)
            );
            CREATE TABLE IF NOT EXISTS fred_cursors (
              series_id TEXT PRIMARY KEY, realtime_start TEXT NOT NULL
            );
            """
        )
        self.connection.commit()

    def ingest(self, series_id: str, payload: bytes, *, mode: str,
               retrieved_at: datetime, output_type: int | None = None,
               fail_after: str | None = None) -> IngestResult:
        if mode not in {"full", "incremental"}:
            raise ValueError("mode must be 'full' or 'incremental'")
        if mode == "incremental" and output_type != 3:
            raise ValueError("incremental ALFRED ingestion requires output_type=3")
        raw_hash = sha256_bytes(payload)
        base = self.output_root / "fred_vintages" / series_id
        raw_path = base / "raw" / f"{raw_hash}.csv"
        self._write_once(raw_path, payload)
        self._fail(fail_after, "raw")

        receipt = {"schema_version": 1, "series_id": series_id,
                   "mode": mode, "output_type": 3,
                   "retrieved_at": retrieved_at.isoformat(),
                   "raw_sha256": raw_hash, "raw_bytes": len(payload)}
        receipt_path = base / "receipts" / f"{raw_hash}.json"
        self._write_once(receipt_path, canonical_json(receipt) + b"\n")
        self._fail(fail_after, "receipt")

        rows = self._parse(series_id, payload, raw_hash)
        if not rows:
            raise ValueError("ALFRED payload has no revisions")
        parse_path = base / "parsed" / f"{raw_hash}.jsonl"
        parsed = b"".join(canonical_json(row) + b"\n" for row in rows)
        self._write_once(parse_path, parsed)
        self._fail(fail_after, "parse")

        next_cursor = max(row["realtime_start"] for row in rows)
        before = self.connection.total_changes
        try:
            self.connection.execute("BEGIN")
            self.connection.executemany(
                "INSERT OR IGNORE INTO fred_revisions VALUES(?,?,?,?,?,?)",
                [(r["series_id"], r["date"], r["realtime_start"],
                  r["realtime_end"], r["value"], r["raw_sha256"]) for r in rows],
            )
            inserted = self.connection.total_changes - before
            self._fail(fail_after, "db")
            current = self.cursor(series_id)
            if current is None or next_cursor > current:
                self.connection.execute(
                    "INSERT INTO fred_cursors VALUES(?,?) ON CONFLICT(series_id) "
                    "DO UPDATE SET realtime_start=excluded.realtime_start",
                    (series_id, next_cursor),
                )
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise
        return IngestResult(inserted, self.cursor(series_id) or next_cursor, parse_path)

    def cursor(self, series_id: str) -> str | None:
        row = self.connection.execute(
            "SELECT realtime_start FROM fred_cursors WHERE series_id=?", (series_id,)
        ).fetchone()
        return None if row is None else str(row[0])

    def revision_count(self, series_id: str) -> int:
        return int(self.connection.execute(
            "SELECT count(*) FROM fred_revisions WHERE series_id=?", (series_id,)
        ).fetchone()[0])

    def reconcile(self, parse_path: Path) -> dict[str, Any]:
        expected = [json.loads(line) for line in Path(parse_path).read_text(encoding="utf-8").splitlines()]
        missing = []
        for row in expected:
            found = self.connection.execute(
                "SELECT 1 FROM fred_revisions WHERE series_id=? AND observation_date=? "
                "AND realtime_start=? AND realtime_end=?",
                (row["series_id"], row["date"], row["realtime_start"], row["realtime_end"]),
            ).fetchone()
            if found is None:
                missing.append(row)
        return {"expected_count": len(expected), "missing_count": len(missing),
                "missing_revisions": missing, "pass": not missing}

    @staticmethod
    def _parse(series_id: str, payload: bytes, raw_hash: str) -> list[dict[str, str]]:
        reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
        required = {"realtime_start", "realtime_end", "date", "value"}
        if not required.issubset(reader.fieldnames or ()):
            raise ValueError("output_type=3 payload is missing revision columns")
        return [{"series_id": series_id, "date": row["date"],
                 "realtime_start": row["realtime_start"],
                 "realtime_end": row["realtime_end"], "value": row["value"],
                 "raw_sha256": raw_hash} for row in reader if row["value"] not in {"", "."}]

    @staticmethod
    def _write_once(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(content)

    @staticmethod
    def _fail(requested: str | None, stage: str) -> None:
        if requested == stage:
            raise RuntimeError(f"injected failure after {stage}")
