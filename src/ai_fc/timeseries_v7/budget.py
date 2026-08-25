"""Pre-launch V7 resource budgets and durable stop decisions."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping


RESOURCE_LIMITS = {
    "wall_clock_seconds": Decimal(24 * 3600),
    "cpu_seconds": Decimal(500 * 3600),
    "gpu_seconds": Decimal(40 * 3600),
    "experiment_count": Decimal(750),
    "storage_bytes": Decimal(250 * 1024**3),
    "api_cost_usd": Decimal(0),
}


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    state: str
    exhausted_resources: tuple[str, ...]


def preflight_budget(usage: Mapping[str, Decimal | int | float], requested: Mapping[str, Decimal | int | float]) -> BudgetDecision:
    exhausted: list[str] = []
    for resource, limit in RESOURCE_LIMITS.items():
        current = Decimal(str(usage.get(resource, 0)))
        increment = Decimal(str(requested.get(resource, 0)))
        if current < 0 or increment < 0:
            raise ValueError("budget usage and requests must be non-negative")
        if current + increment > limit:
            exhausted.append(resource)
    return BudgetDecision(not exhausted, "READY" if not exhausted else "HOLD_BUDGET", tuple(sorted(exhausted)))


APPEND_BUDGET_SQL = """
INSERT INTO timeseries_v7.budget_ledger
  (run_id,cycle_id,generation_id,task_key,resource_type,amount)
VALUES (%s,%s,%s,%s,%s,%s)
"""


def durable_control_sql(action: str) -> tuple[str, str]:
    normalized = action.upper()
    if normalized == "PAUSE":
        return ("UPDATE timeseries_v7.research_run SET state='wait_data',updated_at=clock_timestamp() WHERE run_id=%s", "wait_data")
    if normalized == "ABORT":
        return ("UPDATE timeseries_v7.research_run SET state='cancelled',updated_at=clock_timestamp() WHERE run_id=%s", "cancelled")
    raise ValueError("action must be PAUSE or ABORT")
