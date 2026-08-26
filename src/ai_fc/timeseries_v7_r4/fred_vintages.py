"""PostgreSQL-authoritative, idempotent FRED/ALFRED vintage ingestion."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg

from .integrity import canonical_json, sha256_bytes


@dataclass(frozen=True)
class IngestResult:
    inserted_revisions: int
    cursor: str
    parse_path: Path


class FredVintageIngestor:
    """Persist ALFRED ``output_type=3`` revisions before advancing its cursor."""

    def __init__(self, output_root: Path, database_url: str):
        if not database_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("R4 FRED ingestion requires a PostgreSQL database URL")
        self.output_root = Path(output_root)
        self.database_url = database_url

    def _connect(self):
        return psycopg.connect(self.database_url)

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

        receipt = {
            "schema_version": 1, "series_id": series_id, "mode": mode,
            "output_type": 3, "retrieved_at": retrieved_at.isoformat(),
            "raw_sha256": raw_hash, "raw_bytes": len(payload),
        }
        self._write_once(base / "receipts" / f"{raw_hash}.json",
                         canonical_json(receipt) + b"\n")
        self._fail(fail_after, "receipt")

        rows = self._parse(series_id, payload, raw_hash)
        if not rows:
            raise ValueError("ALFRED payload has no revisions")
        parse_path = base / "parsed" / f"{raw_hash}.jsonl"
        self._write_once(parse_path, b"".join(canonical_json(row) + b"\n" for row in rows))
        self._fail(fail_after, "parse")

        next_cursor = max(row["realtime_start"] for row in rows)
        inserted = 0
        with self._connect() as connection:
            for row in rows:
                created = connection.execute(
                    "INSERT INTO timeseries_v7_r4.fred_revisions "
                    "(series_id,observation_date,realtime_start,realtime_end,available_at,"
                    "value,raw_sha256,retrieved_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT DO NOTHING RETURNING 1",
                    (row["series_id"], row["date"], row["realtime_start"],
                     row["realtime_end"], row["available_at"], row["value"],
                     row["raw_sha256"], retrieved_at),
                ).fetchone()
                inserted += int(created is not None)
            self._fail(fail_after, "db")
            connection.execute(
                "INSERT INTO timeseries_v7_r4.fred_cursors(series_id,realtime_start) "
                "VALUES (%s,%s) ON CONFLICT(series_id) DO UPDATE SET "
                "realtime_start=GREATEST(timeseries_v7_r4.fred_cursors.realtime_start,"
                "excluded.realtime_start), committed_at=CASE WHEN "
                "excluded.realtime_start>timeseries_v7_r4.fred_cursors.realtime_start "
                "THEN now() ELSE timeseries_v7_r4.fred_cursors.committed_at END",
                (series_id, next_cursor),
            )
        committed_cursor = self.cursor(series_id)
        if committed_cursor is None:  # defensive: the transaction must publish both
            raise RuntimeError("revision commit completed without a cursor")
        return IngestResult(inserted, committed_cursor, parse_path)

    def cursor(self, series_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT realtime_start::text FROM timeseries_v7_r4.fred_cursors "
                "WHERE series_id=%s", (series_id,),
            ).fetchone()
        return None if row is None else str(row[0])

    def revision_count(self, series_id: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT count(*) FROM timeseries_v7_r4.fred_revisions WHERE series_id=%s",
                (series_id,),
            ).fetchone()
        return int(row[0])

    def reconcile(self, parse_path: Path) -> dict[str, Any]:
        expected = [json.loads(line) for line in
                    Path(parse_path).read_text(encoding="utf-8").splitlines()]
        missing = []
        with self._connect() as connection:
            for row in expected:
                found = connection.execute(
                    "SELECT 1 FROM timeseries_v7_r4.fred_revisions "
                    "WHERE series_id=%s AND observation_date=%s AND realtime_start=%s "
                    "AND realtime_end=%s",
                    (row["series_id"], row["date"], row["realtime_start"],
                     row["realtime_end"]),
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
        return [
            {"series_id": series_id, "date": row["date"],
             "realtime_start": row["realtime_start"],
             "realtime_end": row["realtime_end"],
             "available_at": row["realtime_start"], "value": row["value"],
             "raw_sha256": raw_hash}
            for row in reader if row["value"] not in {"", "."}
        ]

    @staticmethod
    def _write_once(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(content)

    @staticmethod
    def _fail(requested: str | None, stage: str) -> None:
        if requested == stage:
            raise RuntimeError(f"injected failure after {stage}")
