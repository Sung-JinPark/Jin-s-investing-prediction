"""mts_research 테스트 공유 빌더 — 합성 데이터는 전부 tmp_path 아래에만 만든다.

실제 원장은 절대 변경하지 않는다. 실계약 yaml 은 tmp 루트로 **복사**해 읽기만 한다.
"""

from __future__ import annotations

import json
import shutil
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

REAL_CONTRACTS = [
    "data/contracts/multivariate_timeseries_v8.yaml",
    "data/contracts/multivariate_timeseries_v13_vol.yaml",
    "data/contracts/multivariate_timeseries_v14_conditional.yaml",
    "data/contracts/timeseries_daily6m_v1.yaml",
]
DRAFT_CONTRACT = "data/mts_research/contracts/mts_research_v1.draft.yaml"


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def research_root(tmp_path: Path) -> Path:
    """실계약 사본 + 초안 계약을 갖춘 합성 저장소 루트."""
    root = tmp_path / "repo"
    for relative in REAL_CONTRACTS + [DRAFT_CONTRACT]:
        source = ROOT / relative
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    (root / "data/mts_research/ledgers").mkdir(parents=True, exist_ok=True)
    return root


def load_draft(root: Path):
    from ai_fc.mts_research.contracts import DRAFT_CONTRACT_RELATIVE, load_research_contract

    return load_research_contract(root / DRAFT_CONTRACT_RELATIVE, root)


def make_spec(**overrides: Any):
    from ai_fc.mts_research.records import ForecastSpec

    body: dict[str, Any] = {
        "target_spec_hash": "t" * 16,
        "instrument_id": "VIX",
        "horizon_sessions": 21,
        "origin_session": date(2026, 10, 20),
        "information_cutoff_at": utc(2026, 10, 20, 21, 30),
        "input_snapshot_id": "mts-snap-" + "a" * 24,
        "calendar_hash": "c" * 16,
        "eligibility_rule_hash": "e" * 16,
        "forecast_kind": "event_probability",
    }
    body.update(overrides)
    return ForecastSpec(**body)


def make_ready_draft(**overrides: Any):
    from ai_fc.mts_research.records import ForecastDraft

    body: dict[str, Any] = {
        "model_id": "mts_research.synthetic",
        "spec": make_spec(),
        "state_id": "state-1",
        "calibration_state_id": None,
        "prediction_status": "READY",
        "payload_ref": "experiments/exp-1/run-1/payload.json",
        "payload_hash": "p" * 16,
        "capabilities": ("event_probability",),
        "reason_codes": (),
    }
    body.update(overrides)
    return ForecastDraft(**body)


def make_event(series_id: str, obs_date: str, value: float, *,
               available_at, first_seen=None, recorded=None,
               grade: str = "captured_forward", revision_seq: int = 1,
               revision_id: str | None = None, supersedes: str | None = None,
               batch: str | None = "batch-1", precision: str | None = None):
    """합성 AvailabilityEvent 빌더."""
    from ai_fc.mts_research.availability import AvailabilityEvent

    first = first_seen or available_at
    return AvailabilityEvent(
        series_id=series_id,
        observation_period_start=obs_date,
        observation_period_end=obs_date,
        value=value,
        unit="level",
        source_published_at=None,
        provider_available_at=None,
        first_seen_at=first,
        recorded_at=recorded or first,
        availability_lower_bound=None,
        availability_upper_bound=available_at,
        availability_precision=precision or {
            "native_pit": "date",
            "reconstructed_market_archive": "inferred",
            "captured_forward": "captured_only",
        }.get(grade, "captured_only"),
        availability_policy_id="synthetic_v1",
        data_grade=grade,
        revision_id=revision_id or f"{series_id}:{obs_date}:r{revision_seq}",
        supersedes_id=supersedes,
        revision_seq=revision_seq,
        raw_sha256=None,
        receipt_id=batch,
        source_id="synthetic",
        ingestion_batch_id=batch,
        instrument_id=None,
    )


def synthetic_checkpoint(*, now=None):
    from ai_fc.mts_research.availability import LedgerCheckpoint

    return LedgerCheckpoint(
        checkpoint_id="ckpt-synthetic",
        ledger_path="synthetic.jsonl",
        row_count=0,
        content_sha256="0" * 64,
        created_at=now or utc(2026, 10, 26),
    )


def synthetic_calendar_ref():
    from ai_fc.mts_research.sessions import CalendarRef

    return CalendarRef(
        calendar_id="observation_grid",
        calendar_hash="synthetic-grid-hash",
        library_version=None,
        window_start="2026-01-01",
        window_end="2026-12-31",
    )


def build_synthetic_snapshot(events, *, cutoff, replay_mode="operational_replay",
                             kind="input", completed_batches=None,
                             transform_code_hash="tc1", environment_lock="env1"):
    from ai_fc.mts_research.snapshots import build_snapshot

    return build_snapshot(
        cutoff=cutoff,
        replay_mode=replay_mode,
        events=events,
        checkpoint=synthetic_checkpoint(),
        calendar=synthetic_calendar_ref(),
        source_specs_hash="ss1",
        availability_policy_hash="ap1",
        transform_code_hash=transform_code_hash,
        environment_lock=environment_lock,
        kind=kind,
        completed_batches=completed_batches,
    )


def write_approval_receipt(root: Path, *, receipt_id: str, windows: list[str],
                           series: list[str], purposes: list[str]) -> dict[str, Any]:
    from ai_fc.mts_research import artifacts
    from ai_fc.mts_research.contracts import APPROVALS_LEDGER_RELATIVE

    body = {
        "receipt_id": receipt_id,
        "decision_id": "SYN-TEST",
        "approved_at": "2026-10-26T00:00:00+00:00",
        "approver_role": "owner",
        "approval_text": f"{receipt_id} 승인",
        "approval_scope": {"windows": windows, "series": series, "purposes": purposes},
    }
    return artifacts.append_event(root, APPROVALS_LEDGER_RELATIVE, body)
