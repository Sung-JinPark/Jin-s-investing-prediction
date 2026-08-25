"""Receipt terminal-outcome completeness checks."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable


TERMINAL_OUTCOMES = {
    "parsed_new", "parsed_revision", "unchanged", "empty_valid",
    "quarantined", "parser_failure", "license_blocked",
}


@dataclass(frozen=True)
class ReceiptOutcome:
    receipt_id: str
    outcome: str
    observation_count: int

    def __post_init__(self) -> None:
        if self.outcome not in TERMINAL_OUTCOMES:
            raise ValueError("unknown receipt terminal outcome")
        if self.observation_count < 0:
            raise ValueError("observation_count must be non-negative")
        if self.outcome in {"unchanged", "empty_valid", "quarantined", "parser_failure", "license_blocked"} and self.observation_count != 0:
            raise ValueError("non-parsed outcome cannot claim observations")


def reconcile_receipts(receipt_ids: Iterable[str], outcomes: Iterable[ReceiptOutcome]) -> dict[str, object]:
    receipts = list(receipt_ids)
    rows = list(outcomes)
    counts = Counter(row.receipt_id for row in rows)
    receipt_set = set(receipts)
    orphan = sorted(receipt_id for receipt_id in receipt_set if counts[receipt_id] == 0)
    duplicate = sorted(receipt_id for receipt_id, count in counts.items() if count != 1)
    unknown = sorted(set(counts) - receipt_set)
    return {
        "receipt_count": len(receipts), "terminal_outcome_count": len(rows),
        "orphan_receipts": orphan, "duplicate_outcomes": duplicate,
        "unknown_receipts": unknown, "pass": not orphan and not duplicate and not unknown,
    }
