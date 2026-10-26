"""T49 — 동결 V8/PB adapter 의 golden 동일성 (실자료 read-only).

전수 replay 는 baseline_identity.json 생성 경로가 수행한다. 스위트에서는 실행 시간을
위해 PB 는 부분 행, V8 tier-1 은 전 행(수 초)을 검사한다. 어떤 원장·동결 파일도
변경하지 않는다 — 사후 git status 로 확인되는 read-only 경로만 쓴다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

HAS_V13 = (ROOT / "data/timeseries_v13/ledgers/vol_live.jsonl").is_file()
HAS_V8 = (ROOT / "data/timeseries_v8/ledgers/shadow_forecasts.jsonl").is_file()


@pytest.mark.skipif(not HAS_V13, reason="V13 원장 없음")
def test_t49_pb_live_rows_replay_subset():
    from ai_fc.mts_research.adapters.pb import replay_vol_live_rows

    result = replay_vol_live_rows(ROOT, max_rows=6)
    assert result["failures"] == []
    # 재계산 가능한 행(핀 sha)은 전부 PASS, 구 sha 행은 hash-only 로 정직하게 분류
    assert result["pass"] + result["hash_only_old_sha"] == result["rows"]
    assert result["pass"] >= 1


@pytest.mark.skipif(not HAS_V13, reason="V13 원장 없음")
def test_t49_pb_resolutions_replay_subset():
    from ai_fc.mts_research.adapters.pb import replay_vol_resolutions

    result = replay_vol_resolutions(ROOT, max_rows=30)
    assert result["failures"] == []
    assert result["pass"] == result["rows"]


@pytest.mark.skipif(not HAS_V8, reason="V8 원장 없음")
def test_t49_v8_tier1_full_replay():
    from ai_fc.mts_research.adapters.v8 import tier1_replay

    report = tier1_replay(ROOT)
    assert report["chain_errors"] == []
    assert report["forecast_pass"] == report["forecast_rows"] > 0
    assert report["resolution_pass"] == report["resolution_rows"] > 0
    assert all(r["status"] == "PASS" for r in report["sealed"])
    assert report["pointer"]["status"] in ("PASS", "HOLD_POINTER", "NOT_APPLICABLE")
    assert report["ok"] is True
    # grid-skip 행은 '보정 항등식' 으로만 통과한다 — 라벨의 grid-종속성 공시 (감사 사실)
    for row in report["resolution_results"]:
        if row["status"] == "PASS_WITH_GRID_SKIP":
            assert any("GRID_SKIP" in note for note in row["notes"])


@pytest.mark.skipif(not HAS_V8, reason="V8 원장 없음")
def test_t49_identity_is_read_only():
    """identity replay 는 동결 원장을 변경하지 않는다 (보호 전제)."""
    import hashlib

    targets = [
        ROOT / "data/timeseries_v8/ledgers/shadow_forecasts.jsonl",
        ROOT / "data/timeseries_v13/vol/champion_coefficients.json",
    ]
    before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in targets]
    from ai_fc.mts_research.adapters.v8 import tier1_replay

    tier1_replay(ROOT)
    after = [hashlib.sha256(p.read_bytes()).hexdigest() for p in targets]
    assert before == after
