from pathlib import Path

import pytest

from ai_fc.timeseries_v7_r6.outer_guard import OuterAccessBlocked, R5OuterDenylist


ROOT = Path(__file__).resolve().parents[3]


def test_r5_outer_path_is_blocked_before_open() -> None:
    guard = R5OuterDenylist.load(ROOT)
    denied = Path("outputs/timeseries_v7_r5/R5-G4/outer_score_matrix.parquet")
    with pytest.raises(OuterAccessBlocked, match="BLOCKED_PROTECTED_SCOPE"):
        guard.guarded_read_bytes(denied, role="calibration")


@pytest.mark.parametrize("role", ["outer", "R5_OUTER", "outer_evaluation"])
def test_every_outer_role_is_blocked(role: str) -> None:
    guard = R5OuterDenylist.load(ROOT)
    with pytest.raises(OuterAccessBlocked, match="BLOCKED_PROTECTED_SCOPE"):
        guard.assert_role_allowed(role)


def test_calibration_role_and_non_outer_path_remain_allowed(tmp_path: Path) -> None:
    guard = R5OuterDenylist.load(ROOT)
    sample = tmp_path / "calibration.json"
    sample.write_text("{}", encoding="utf-8")
    assert guard.guarded_read_bytes(sample, role="calibration") == b"{}"
