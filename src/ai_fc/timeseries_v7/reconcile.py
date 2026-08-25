"""Deterministic lineage reconciliation and partition identity."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .lineage import ReceiptOutcome, reconcile_receipts
from .revisions import ObservationRevision, validate_revision_chain


def reconcile(receipts: list[str], outcomes: list[ReceiptOutcome], revision_groups: list[list[ObservationRevision]], partition_rows: list[dict[str, Any]]) -> dict[str, object]:
    receipt_report = reconcile_receipts(receipts, outcomes)
    broken = []
    for index, chain in enumerate(revision_groups):
        try: validate_revision_chain(chain)
        except ValueError as exc: broken.append({"chain": index, "error": str(exc)})
    body = b"\n".join(json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() for row in sorted(partition_rows, key=lambda row: json.dumps(row, sort_keys=True)))
    if body: body += b"\n"
    return {"receipt": receipt_report, "broken_revision_chains": broken, "partition_logical_sha256": hashlib.sha256(body).hexdigest(), "pass": receipt_report["pass"] and not broken}
