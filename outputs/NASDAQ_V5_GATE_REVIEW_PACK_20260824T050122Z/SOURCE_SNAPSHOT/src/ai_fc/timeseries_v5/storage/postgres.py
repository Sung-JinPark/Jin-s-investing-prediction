"""Neon/PostgreSQL control-plane migration adapter."""

from __future__ import annotations
from pathlib import Path
from typing import Any
import json


class PostgresControlPlane:
    def __init__(self, dsn: str):
        if not dsn or "postgres" not in dsn: raise ValueError("valid PostgreSQL DSN required")
        self.dsn = dsn
    def _connect(self):
        try: import psycopg  # type: ignore
        except ImportError as exc: raise RuntimeError("install ai-fc[timeseries-v5] for PostgreSQL") from exc
        return psycopg.connect(self.dsn)
    def migrate(self, root: Path) -> None:
        sql = (root / "migrations/timeseries_v5/0001_control_plane.sql").read_text(encoding="utf-8")
        with self._connect() as connection:
            with connection.cursor() as cursor: cursor.execute(sql)
    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params); return [] if cursor.description is None else list(cursor.fetchall())

    def rows(self, ledger: str) -> list[dict[str, Any]]:
        if not ledger.replace("_", "").replace("-", "").isalnum(): raise ValueError("invalid ledger name")
        rows = self.execute("SELECT payload FROM research_append_ledger WHERE ledger_name=%s ORDER BY appended_at, identity_value", (ledger,))
        return [dict(row[0]) if isinstance(row[0], dict) else json.loads(row[0]) for row in rows]

    def append(self, ledger: str, row: dict[str, Any], *, identity: str) -> bool:
        if identity not in row: raise ValueError(f"identity missing: {identity}")
        prior = self.execute("SELECT payload FROM research_append_ledger WHERE ledger_name=%s AND identity_value=%s", (ledger, str(row[identity])))
        if prior:
            value = dict(prior[0][0]) if isinstance(prior[0][0], dict) else json.loads(prior[0][0])
            if value != row: raise ValueError(f"append-only identity collision: {ledger}/{row[identity]}")
            return False
        self.execute("INSERT INTO research_append_ledger (ledger_name, identity_value, payload) VALUES (%s,%s,%s::jsonb)", (ledger, str(row[identity]), json.dumps(row, ensure_ascii=False, sort_keys=True)))
        return True

    def append_many(self, ledger: str, rows: list[dict[str, Any]], *, identity: str) -> int:
        """Managed-store compatibility; uniqueness is enforced by PostgreSQL."""
        return sum(int(self.append(ledger, row, identity=identity)) for row in rows)

    def append_bundle(self, batches: list[tuple[str, list[dict[str, Any]], str]]) -> int:
        """Write all fact/link batches in one PostgreSQL transaction."""
        appended = 0
        with self._connect() as connection:
            with connection.cursor() as cursor:
                for ledger, rows, identity in batches:
                    for row in rows:
                        if identity not in row: raise ValueError(f"identity missing: {identity}")
                        cursor.execute("SELECT payload FROM research_append_ledger WHERE ledger_name=%s AND identity_value=%s", (ledger, str(row[identity])))
                        prior = cursor.fetchone()
                        if prior:
                            value = dict(prior[0]) if isinstance(prior[0], dict) else json.loads(prior[0])
                            if value != row: raise ValueError(f"append-only identity collision: {ledger}/{row[identity]}")
                            continue
                        cursor.execute("INSERT INTO research_append_ledger (ledger_name, identity_value, payload) VALUES (%s,%s,%s::jsonb)", (ledger, str(row[identity]), json.dumps(row, ensure_ascii=False, sort_keys=True)))
                        appended += 1
        return appended
