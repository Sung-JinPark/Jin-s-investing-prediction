"""rung-4 매크로 블록 — 정렬·지연 로직의 미래 정보 누수 검사.

이 트랙에서 새로 생긴 유일한 위험은 저빈도·지연 발행 계열을 패널에 맞추는 과정이다. 지연이 잘못되면
'아직 공표되지 않은 값'을 원점에서 쓰게 되고, 그건 곧 가짜 스킬이다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
rung4 = pytest.importorskip("v13_vol_rung4_macro")


def test_align_forward_fills_only_from_the_past() -> None:
    dates = ["2010-01-04", "2010-01-05", "2010-01-06", "2010-01-07"]
    values = {"2010-01-05": 2.0, "2010-01-07": 4.0}
    out = rung4._align(dates, values, lag_sessions=0)
    assert np.isnan(out[0]), "첫 관측 이전은 채우지 않는다"
    assert out[1] == 2.0 and out[2] == 2.0, "직전 값으로 전방 채움"
    assert out[3] == 4.0
    # 미래 값이 과거 칸에 새지 않는다
    assert not np.any(out[:1] == 4.0)


def test_align_lag_shifts_strictly_backwards() -> None:
    dates = [f"2010-01-{d:02d}" for d in range(4, 12)]
    values = {d: float(i) for i, d in enumerate(dates)}
    out = rung4._align(dates, values, lag_sessions=3)
    assert np.isnan(out[:3]).all(), "지연만큼 앞은 비어 있어야 한다"
    # 지연 후 각 칸은 3세션 전 값이다 — 절대 당일이나 미래가 아니다
    for i in range(3, len(dates)):
        assert out[i] == float(i - 3)


def test_lagged_series_cannot_see_a_future_jump() -> None:
    """미래에 급등이 생겨도 지연 이전 칸은 영향을 받지 않아야 한다."""
    dates = [f"2010-02-{d:02d}" for d in range(1, 21)]
    base = {d: 1.0 for d in dates}
    spike_at = 5
    spike = dict(base); spike[dates[spike_at]] = 99.0
    a = rung4._align(dates, base, lag_sessions=10)
    b = rung4._align(dates, spike, lag_sessions=10)
    # 급등은 지연 10세션 뒤(index 15)부터만 보여야 한다
    assert np.allclose(a[:spike_at + 10], b[:spike_at + 10], equal_nan=True), "지연 이전 칸이 바뀌면 누수다"
    assert b[spike_at + 10] == 99.0 and a[spike_at + 10] == 1.0, "지연만큼 지난 뒤에는 반영돼야 한다"


def test_contract_registers_the_blocks_before_results() -> None:
    import yaml
    contract = yaml.safe_load((ROOT / "data/contracts/multivariate_timeseries_v13_vol.yaml").read_text(encoding="utf-8"))
    spec = contract["rung4_macro_blocks"]
    assert spec["prereg_commit"], "결과 전 커밋 해시가 기입돼야 한다"
    assert spec["backtest_windows_opened"] == 0
    blocks = spec["blocks"]
    assert blocks["F1_term_spread"]["pit_grade"] == "archive_verified" and blocks["F1_term_spread"]["lag_sessions"] == 0
    for name in ("F2_dollar", "F3_ebp"):
        assert blocks[name]["pit_grade"] == "assumed_lag"
        assert blocks[name]["lag_sessions"] > 0, "PIT 증거가 없는 계열은 보수 지연이 필수"
    assert "홀드아웃 결과로 셀을 고르지 않는다" in spec["cells"]


def test_result_artifact_matches_the_ledger_row() -> None:
    import hashlib
    import json
    out = ROOT / "data/timeseries_v13/vol/ladder_rung4_macro.json"
    if not out.is_file():
        pytest.skip("rung-4 미실행")
    payload = json.loads(out.read_text(encoding="utf-8"))
    from ai_fc.timeseries_v13.contracts import canonical_hash
    body = {k: v for k, v in payload.items() if k != "content_hash"}
    assert canonical_hash(body) == payload["content_hash"]
    rows = [json.loads(line) for line in
            (ROOT / "data/timeseries_v13/ledgers/vol_experiments.jsonl").read_text(encoding="utf-8").splitlines() if line]
    row = next(r for r in rows if r["experiment_label"] == "V13VOL_rung4_macro")
    assert row["results_sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()
    assert row["k_obs_adopted"] == payload["k_obs_adopted"]
    assert row["backtest_windows_opened"] == 0
    # 예산 회계가 원장 행 수와 맞는다
    import yaml
    contract = yaml.safe_load((ROOT / "data/contracts/multivariate_timeseries_v13_vol.yaml").read_text(encoding="utf-8"))
    assert contract["development_protocol"]["evaluations_spent"] == len(rows)
