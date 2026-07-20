"""DB 연결·재구축. 스키마는 schema.sql이 유일 원천 (CREATE IF NOT EXISTS 멱등)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from . import config


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    schema = (config.ROOT / "schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema)
    return conn


def rebuild(conn: sqlite3.Connection) -> None:
    """raw 계층 재적재를 위한 초기화 — 원본 파일(data/raw)은 건드리지 않는다."""
    tables = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    for t in tables:
        conn.execute(f"DELETE FROM {t}")
    conn.commit()
