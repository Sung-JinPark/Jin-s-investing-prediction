"""전체 수집 오케스트레이션 — `python -m dualdb ingest [--since YYYY-MM-DD]`."""

from __future__ import annotations

import sqlite3

from . import finra, french, fred, ritter, seeds, shiller, yahoo


def run(conn: sqlite3.Connection, since: str | None = None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    out["seeds"] = seeds.ingest(conn, since)     # 시드 먼저 (entity가 data_gap 기록 대상)
    steps = [("fred", fred.ingest), ("yahoo_indices", yahoo.ingest_indices),
             ("yahoo", yahoo.ingest), ("ritter", ritter.ingest), ("shiller", shiller.ingest),
             ("finra", finra.ingest), ("french", french.ingest)]
    for name, fn in steps:
        try:
            out[name] = fn(conn, since)
        except Exception as exc:  # noqa: BLE001 — 소스 1개 실패가 전체를 막지 않게
            out[name] = {"ERROR": f"{type(exc).__name__}: {exc}"[:200]}
    return out
