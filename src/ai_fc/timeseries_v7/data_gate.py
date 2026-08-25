"""Data quality and drift decisions before any training task."""

from __future__ import annotations


def decide_data_gate(*, pit_pass: bool, receipt_pass: bool, freshness_pass: bool, missingness_rate: float, missingness_max: float, new_evidence: bool, drift_alert: bool) -> dict[str, object]:
    if not pit_pass or not receipt_pass or not freshness_pass or missingness_rate > missingness_max:
        return {"state": "BLOCKED_INVALID_SNAPSHOT", "train_allowed": False, "drift_alert": drift_alert}
    if not new_evidence:
        return {"state": "WAIT_DATA", "train_allowed": False, "drift_alert": drift_alert}
    return {"state": "READY", "train_allowed": True, "drift_alert": drift_alert}
