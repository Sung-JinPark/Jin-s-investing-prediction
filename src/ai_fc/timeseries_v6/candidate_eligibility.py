"""Fail-closed eligibility for preregistered V6 candidates E8-E10."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def evaluate_deferred_candidates(root: Path) -> dict[str, Any]:
    events = _jsonl(root / "data/timeseries_v6/events/resolved_events.jsonl")
    independent_events = {
        row.get("independent_event_id")
        for row in events
        if row.get("resolved") is True
        and row.get("pre_event_snapshot_receipt_id")
        and row.get("independent_event_id")
    }
    e8_eligible = len(independent_events) >= 60
    market_license = root / "data/timeseries_v6/licenses/market_implied_physical_calibration.json"
    market_history = root / "data/timeseries_v6/events/market_implied_history.parquet"
    e9_eligible = market_license.is_file() and market_history.is_file()
    checkpoint_receipt = root / "data/timeseries_v6/licenses/foundation_checkpoint.json"
    foundation_license = root / "data/timeseries_v6/licenses/foundation_model_license.json"
    e10_eligible = checkpoint_receipt.is_file() and foundation_license.is_file()
    candidates = {
        "E8": {
            "eligible": e8_eligible,
            "weight": 0.0,
            "resolved_independent_event_count": len(independent_events),
            "minimum_required": 60,
            "reason": None if e8_eligible else "minimum_resolved_independent_events_not_met",
        },
        "E9": {
            "eligible": e9_eligible,
            "weight": 0.0,
            "license_receipt_present": market_license.is_file(),
            "history_present": market_history.is_file(),
            "reason": None if e9_eligible else "licensed_physical_calibration_history_unavailable",
        },
        "E10": {
            "eligible": e10_eligible,
            "weight": 0.0,
            "checkpoint_receipt_present": checkpoint_receipt.is_file(),
            "license_receipt_present": foundation_license.is_file(),
            "reason": None if e10_eligible else "checkpoint_or_license_receipt_unavailable",
        },
    }
    canonical = json.dumps(candidates, sort_keys=True, separators=(",", ":")).encode()
    return {
        "schema_version": 1,
        "candidates": candidates,
        "all_ineligible_zero_weight": all(not row["eligible"] and row["weight"] == 0.0 for row in candidates.values()),
        "content_hash": hashlib.sha256(canonical).hexdigest(),
    }
