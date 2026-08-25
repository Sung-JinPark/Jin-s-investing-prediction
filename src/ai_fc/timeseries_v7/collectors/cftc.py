"""CFTC report snapshots counted by independent publication."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class CftcSnapshot:
    report_date: date
    published_at: datetime
    contract_code: str
    rows: tuple[dict[str, float], ...]

    @property
    def independent_id(self) -> str:
        return f"{self.report_date.isoformat()}@{self.published_at.isoformat()}"


def independent_snapshot_count(values: list[CftcSnapshot]) -> int:
    return len({value.independent_id for value in values})
