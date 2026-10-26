"""라벨 성숙 테스트 — T11·T15·T16·T48(상태)·T59."""

from __future__ import annotations

import pytest

from ai_fc.mts_research.maturity import (
    LabelEvent,
    MtsMaturityError,
    assert_prospective_issue,
    latest_label_state,
    matured_view,
    resolutions_available_before,
)
from mts_research_fixtures import utc


def _event(event_id: str, *, status: str, origin: str = "2026-10-01",
           observed: float | None = None, available=None, recorded=None,
           supersedes: str | None = None, early=None, revision: str | None = None,
           anchor: str | None = "anchor-r1") -> LabelEvent:
    if status in ("MATURE", "RESTATED") and revision is None:
        revision = f"{event_id}-rev"
    return LabelEvent(
        label_event_id=event_id,
        target_spec_hash="target-1",
        origin_session=origin,
        status=status,  # type: ignore[arg-type]
        observed_value=observed,
        first_touch_session=None,
        early_event_observed_at=early,
        label_available_at=available,
        label_revision_id=revision,
        recorded_at=recorded or utc(2026, 10, 25),
        outcome_snapshot_id=None,
        anchor_revision_id=anchor,
        supersedes_label_event_id=supersedes,
    )


def test_t16_early_positive_excluded_until_mature():
    """조기 양성은 early_event_observed_at 메타로만 남고 성숙 전 집계에서 제외 (T16)."""
    pending = _event("e1", status="PENDING", early=utc(2026, 10, 5))
    view = matured_view([pending], as_of=utc(2026, 10, 26))
    assert view == {}
    mature = _event("e2", status="MATURE", origin="2026-09-01", observed=1.0,
                    available=utc(2026, 10, 10), recorded=utc(2026, 10, 10))
    view = matured_view([pending, mature], as_of=utc(2026, 10, 26))
    assert list(view) == [("target-1", "2026-09-01")]


def test_t16_pending_cannot_carry_observed_value():
    with pytest.raises(MtsMaturityError):
        _event("e1", status="PENDING", observed=1.0)


def test_maturity_requires_label_available_at():
    mature = _event("e1", status="MATURE", observed=1.0, available=utc(2026, 11, 1),
                    recorded=utc(2026, 10, 25))
    assert matured_view([mature], as_of=utc(2026, 10, 26)) == {}  # 아직 미성숙
    assert len(matured_view([mature], as_of=utc(2026, 11, 2),
                            recorded_cutoff=utc(2026, 11, 2))) == 1


def test_t59_operational_replay_excludes_late_recorded():
    """원천상 과거 가용이지만 늦게 기록된 해소는 당시 checkpoint 밖 (T59)."""
    late = _event("e1", status="MATURE", observed=0.0,
                  available=utc(2026, 9, 1),      # 원천 가용은 9/1
                  recorded=utc(2026, 10, 20))     # 우리 기록은 10/20
    cutoff = utc(2026, 10, 1)
    operational = resolutions_available_before(
        [late], cutoff=cutoff, replay_mode="operational_replay", recorded_cutoff=cutoff
    )
    assert operational == []
    historical = resolutions_available_before(
        [late], cutoff=cutoff, replay_mode="historical_information_set_reconstruction"
    )
    assert len(historical) == 1


def test_t48_restatement_preserves_original():
    """정정은 RESTATED 새 이벤트 — 원판은 체인에 남고 최신 상태만 바뀐다 (T48 상태측)."""
    original = _event("e1", status="MATURE", observed=1.0,
                      available=utc(2026, 10, 10), recorded=utc(2026, 10, 10),
                      revision="rev-1")
    restated = _event("e2", status="RESTATED", observed=0.0,
                      available=utc(2026, 10, 20), recorded=utc(2026, 10, 20),
                      revision="rev-2", supersedes="e1")
    state = latest_label_state([original, restated])
    chosen = state[("target-1", "2026-10-01")]
    assert chosen.label_event_id == "e2" and chosen.observed_value == 0.0
    assert chosen.anchor_revision_id == "anchor-r1"  # 발행 anchor 판은 보존 (T11)
    assert chosen.label_revision_id == "rev-2"       # terminal 판은 별도 (T11)


def test_t48_restated_requires_reference_and_same_key():
    with pytest.raises(MtsMaturityError):
        _event("e2", status="RESTATED", observed=0.0, available=utc(2026, 10, 20))
    original = _event("e1", status="MATURE", observed=1.0, available=utc(2026, 10, 10))
    stranger = _event("e2", status="RESTATED", origin="2026-05-05", observed=0.0,
                      available=utc(2026, 10, 20), supersedes="e1")
    with pytest.raises(MtsMaturityError):
        latest_label_state([original, stranger])  # 다른 (target, origin) 참조 금지


def test_duplicate_terminal_without_supersedes_rejected():
    a = _event("e1", status="MATURE", observed=1.0, available=utc(2026, 10, 10))
    b = _event("e2", status="MATURE", observed=0.0, available=utc(2026, 10, 11))
    with pytest.raises(MtsMaturityError):
        latest_label_state([a, b])


def test_t15_backdated_prospective_rejected():
    """첫 대상 세션 가용 시각 이후의 발행은 prospective 로 등록 불가 (T15)."""
    first_available = utc(2026, 10, 21, 20, 15)
    assert_prospective_issue(
        issued_at=utc(2026, 10, 20, 22), first_target_available_at=first_available
    )
    with pytest.raises(MtsMaturityError):
        assert_prospective_issue(
            issued_at=utc(2026, 10, 21, 20, 15), first_target_available_at=first_available
        )
    with pytest.raises(MtsMaturityError):
        assert_prospective_issue(
            issued_at=utc(2026, 10, 22), first_target_available_at=first_available
        )
