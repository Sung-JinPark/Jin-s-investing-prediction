"""Append-only bitemporal fact store with optional Parquet/DuckDB acceleration."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .data_contracts import ValueStatus


class ObservationFact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    series_id: str
    observation_time: str
    value: float | None
    value_status: ValueStatus = ValueStatus.OK
    available_at: str
    vintage_start: str
    vintage_end: str | None = None
    retrieved_at: str
    source_revision_id: str | None = None
    source_hash: str = Field(min_length=32)
    parser_version: str
    timezone: str
    market_session: str | None = None
    calendar_id: str

    @model_validator(mode="after")
    def temporal_contract(self) -> "ObservationFact":
        available = datetime.fromisoformat(self.available_at)
        vintage_start = datetime.fromisoformat(self.vintage_start)
        if vintage_start < available:
            raise ValueError("vintage_start cannot precede available_at")
        if self.vintage_end and datetime.fromisoformat(self.vintage_end) <= vintage_start:
            raise ValueError("vintage_end must be later than vintage_start")
        if self.value_status is ValueStatus.OK and self.value is None:
            raise ValueError("ok facts require a numeric value")
        return self

    @property
    def key(self) -> tuple[str, str, str, str]:
        return self.source_id, self.series_id, self.observation_time, self.vintage_start


def as_of_rows(
    facts: Iterable[ObservationFact], *, series_id: str, as_of: str,
    as_of_market_date: str | None = None,
) -> list[ObservationFact]:
    """Return the revision that was knowable at ``as_of`` for each observation."""
    cutoff = datetime.fromisoformat(as_of)
    market_cutoff = as_of_market_date or as_of[:10]
    eligible = [
        fact for fact in facts
        if fact.series_id == series_id
        and fact.observation_time[:10] <= market_cutoff
        and datetime.fromisoformat(fact.available_at) <= cutoff
        and datetime.fromisoformat(fact.vintage_start) <= cutoff
        and (fact.vintage_end is None or datetime.fromisoformat(fact.vintage_end) > cutoff)
    ]
    by_observation: dict[str, ObservationFact] = {}
    for fact in sorted(eligible, key=lambda item: item.vintage_start):
        by_observation[fact.observation_time] = fact
    return [by_observation[key] for key in sorted(by_observation)]


def assert_no_leakage(facts: Iterable[ObservationFact], *, as_of: str) -> None:
    cutoff = datetime.fromisoformat(as_of)
    leaked = [fact.key for fact in facts if datetime.fromisoformat(fact.available_at) > cutoff]
    if leaked:
        raise AssertionError(f"point-in-time leakage detected: {leaked[:5]}")


class ParquetFactStore:
    """Annual Hive-partitioned Parquet facts queried by an in-memory DuckDB connection."""

    def __init__(self, root: Path) -> None:
        self.root = root / "data" / "facts"

    @staticmethod
    def _deps():
        try:
            import duckdb  # type: ignore
            import pyarrow as pa  # type: ignore
            import pyarrow.parquet as pq  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("install ai-fc[pit] for Parquet/DuckDB fact storage") from exc
        return duckdb, pa, pq

    def append(self, facts: Iterable[ObservationFact]) -> list[Path]:
        _, pa, pq = self._deps()
        grouped: dict[tuple[str, str], list[dict]] = {}
        for fact in facts:
            grouped.setdefault(
                (fact.source_id, fact.observation_time[:4]), []
            ).append(fact.model_dump(mode="json"))
        written: list[Path] = []
        for (source_id, year), rows in grouped.items():
            rows.sort(key=lambda row: (row["series_id"], row["observation_time"], row["vintage_start"]))
            digest = hashlib.sha256(
                json.dumps(rows, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()[:20]
            target = self.root / f"source_id={source_id}" / f"year={year}" / f"part-{digest}.parquet"
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                pq.write_table(pa.Table.from_pylist(rows), target, compression="zstd")
            written.append(target)
        return written

    def as_of(
        self, *, series_id: str, as_of: str, as_of_market_date: str | None = None
    ) -> list[dict]:
        duckdb, _, _ = self._deps()
        if not self.root.exists() or not next(self.root.rglob("*.parquet"), None):
            return []
        glob = (self.root / "**" / "*.parquet").as_posix()
        market_cutoff = as_of_market_date or as_of[:10]
        conn = duckdb.connect(":memory:")
        result = conn.execute(
            """SELECT * EXCLUDE (rn) FROM (
                 SELECT *, row_number() OVER (
                   PARTITION BY source_id,series_id,observation_time
                   ORDER BY vintage_start DESC) AS rn
                 FROM read_parquet(?, hive_partitioning=true, union_by_name=true)
                 WHERE series_id=? AND observation_time<=? AND available_at<=?
                   AND vintage_start<=? AND (vintage_end IS NULL OR vintage_end>?))
               WHERE rn=1 ORDER BY observation_time""",
            [glob, series_id, market_cutoff, as_of, as_of, as_of],
        )
        columns = [col[0] for col in result.description]
        rows = [dict(zip(columns, row)) for row in result.fetchall()]
        conn.close()
        return rows
