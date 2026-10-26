"""snapshot 계층 테스트 — T06·T07·T09·T14 + manifest 불변성."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_fc.mts_research.snapshots import (
    MtsSnapshotError,
    OutcomeSnapshot,
    assert_input_snapshot,
    persist_manifest,
    resolve_latest_visible_revision_per_period,
    select_heads,
)
from mts_research_fixtures import build_synthetic_snapshot, make_event, utc


def _history_events():
    """3개 관측 기간 × 정정 포함 — 이력 보존 검사용."""
    rows = []
    for day, value in (("2026-10-15", 15.0), ("2026-10-16", 16.0), ("2026-10-17", 17.0)):
        rows.append(make_event("VIX", day, value, available_at=utc(2026, 10, int(day[-2:]), 21)))
    rows.append(make_event("VIX", "2026-10-16", 16.5, available_at=utc(2026, 10, 18, 21),
                           revision_seq=2, supersedes=rows[1].revision_id))
    return rows


def test_t06_full_period_history_preserved():
    """기간별 최신 가용판의 **전체 이력**이 보존된다 — head 한 행 축약 금지 (T06)."""
    snap = build_synthetic_snapshot(_history_events(), cutoff=utc(2026, 10, 20))
    periods = [(e.observation_period_end, e.value) for e in snap.history]
    assert periods == [("2026-10-15", 15.0), ("2026-10-16", 16.5), ("2026-10-17", 17.0)]
    head = snap.manifest.series_heads["VIX"]
    assert head.observation_period_end == "2026-10-17" and head.value == 17.0


def test_t07_incomplete_batch_excluded():
    """완료 marker 없는 batch 의 이벤트는 snapshot 에서 제외된다 (T07)."""
    events = [
        make_event("VIX", "2026-10-15", 15.0, available_at=utc(2026, 10, 15, 21), batch="b1"),
        make_event("VIX", "2026-10-16", 16.0, available_at=utc(2026, 10, 16, 21), batch="b2"),
    ]
    snap = build_synthetic_snapshot(events, cutoff=utc(2026, 10, 20), completed_batches={"b1"})
    assert [e.observation_period_end for e in snap.history] == ["2026-10-15"]


def test_t09_cache_key_changes_with_code_policy_lock():
    """동일 데이터라도 code/lock hash 가 바뀌면 snapshot_id 가 바뀐다 (T09)."""
    events = _history_events()
    base = build_synthetic_snapshot(events, cutoff=utc(2026, 10, 20))
    same = build_synthetic_snapshot(events, cutoff=utc(2026, 10, 20))
    assert base.manifest.snapshot_id == same.manifest.snapshot_id  # 결정적
    code_changed = build_synthetic_snapshot(events, cutoff=utc(2026, 10, 20),
                                            transform_code_hash="tc2")
    lock_changed = build_synthetic_snapshot(events, cutoff=utc(2026, 10, 20),
                                            environment_lock="env2")
    assert code_changed.manifest.snapshot_id != base.manifest.snapshot_id
    assert lock_changed.manifest.snapshot_id != base.manifest.snapshot_id


def test_t14_outcome_snapshot_rejected_by_feature_guard():
    """outcome snapshot 을 feature 경로에 전달하면 타입 검사가 거부한다 (T14)."""
    events = _history_events()
    outcome = build_synthetic_snapshot(events, cutoff=utc(2026, 10, 20), kind="outcome")
    assert isinstance(outcome, OutcomeSnapshot)
    with pytest.raises(MtsSnapshotError):
        assert_input_snapshot(outcome)
    input_snap = build_synthetic_snapshot(events, cutoff=utc(2026, 10, 20), kind="input")
    assert assert_input_snapshot(input_snap) is input_snap


def test_input_outcome_ids_differ():
    events = _history_events()
    a = build_synthetic_snapshot(events, cutoff=utc(2026, 10, 20), kind="input")
    b = build_synthetic_snapshot(events, cutoff=utc(2026, 10, 20), kind="outcome")
    assert a.manifest.snapshot_id != b.manifest.snapshot_id


def test_deterministic_revision_tiebreak():
    """같은 상계·같은 seq 라면 revision_id 로 결정적 tie-break."""
    at = utc(2026, 10, 15, 21)
    a = make_event("VIX", "2026-10-15", 1.0, available_at=at, revision_id="VIX:2026-10-15:a")
    b = make_event("VIX", "2026-10-15", 2.0, available_at=at, revision_id="VIX:2026-10-15:b")
    chosen = resolve_latest_visible_revision_per_period([a, b])
    chosen_swapped = resolve_latest_visible_revision_per_period([b, a])
    assert chosen == chosen_swapped and chosen[0].revision_id.endswith(":b")


def test_heads_age_axes():
    """age_since_observation 과 age_since_publication 은 별개 축 (§6.5)."""
    snap = build_synthetic_snapshot(_history_events(), cutoff=utc(2026, 10, 20))
    head = snap.manifest.series_heads["VIX"]
    assert head.age_since_observation_days == pytest.approx(3.0)
    assert head.age_since_publication_days is None  # legacy — 공개 증거 없음, 승격 금지


def test_manifest_persist_immutable(tmp_path: Path):
    root = tmp_path / "repo"
    (root / "data/mts_research").mkdir(parents=True)
    snap = build_synthetic_snapshot(_history_events(), cutoff=utc(2026, 10, 20))
    path1 = persist_manifest(root, snap)
    path2 = persist_manifest(root, snap)  # 동일 내용 재기록은 no-op
    assert path1 == path2 and path1.is_file()
