"""Recurring V7 research scheduler decisions without side effects."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


STAGES = (
    "COLLECT", "VERIFY_RAW", "PARSE", "RECONCILE", "MATERIALIZE_PIT",
    "MATURE_LABELS", "DATA_QUALITY_GATE", "PLAN_RESEARCH", "TRAIN",
    "NESTED_BACKTEST", "STACK", "CALIBRATE", "HISTORICAL_STRESS",
    "QUALIFICATION", "FREEZE_GENERATION", "PROSPECTIVE_FORECAST",
    "MATURE_PROSPECTIVE_LABELS", "PROSPECTIVE_SCORE", "REVIEW_PROPOSAL",
)


@dataclass(frozen=True)
class GenerationEvidence:
    matured_weekly_origins: int = 0
    independent_resolved_events: int = 0
    approved_code_hypothesis: bool = False
    feature_drift_alert: bool = False
    target_drift_alert: bool = False


@dataclass(frozen=True)
class ScheduleDecision:
    state: str
    reason: str
    create_generation: bool


def generation_input_hash(value: dict[str, Any]) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(body).hexdigest()


def decide_generation(
    evidence: GenerationEvidence,
    *,
    now: datetime,
    last_generation_at: datetime | None,
    input_hash: str,
    prior_input_hashes: set[str],
) -> ScheduleDecision:
    if input_hash in prior_input_hashes:
        return ScheduleDecision("WAIT_DATA", "same_input_hash_duplicate_generation", False)
    trigger = (
        evidence.matured_weekly_origins >= 4
        or evidence.independent_resolved_events >= 5
        or evidence.approved_code_hypothesis
        or evidence.feature_drift_alert
        or evidence.target_drift_alert
    )
    if not trigger:
        return ScheduleDecision("WAIT_DATA", "no_new_generation_evidence", False)
    if last_generation_at is not None and now - last_generation_at < timedelta(days=28):
        return ScheduleDecision("WAIT_DATA", "minimum_generation_interval", False)
    return ScheduleDecision("READY", "preregistered_generation_trigger", True)


def task_blueprint(run_id: str, cycle_id: str, generation_id: str) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    previous: str | None = None
    for index, stage in enumerate(STAGES):
        key = f"{index + 1:02d}-{stage.lower()}"
        tasks.append({
            "run_id": run_id, "cycle_id": cycle_id, "generation_id": generation_id,
            "task_key": key, "stage": stage, "dependency_task_key": previous,
        })
        previous = key
    return tasks
