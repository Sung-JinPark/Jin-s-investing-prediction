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


def _pointer(body: dict) -> dict:
    from ai_fc.timeseries_v8.contracts import canonical_hash

    return {**body, "content_hash": canonical_hash(body)}


def _synthetic_forecast(origin: str = "2026-10-16") -> dict:
    grid = [(-0.05 + 0.0005 * i) for i in range(200)]
    p_up = sum(1 for g in grid if g > 0) / len(grid)
    return {
        "origin": origin,
        "grid_levels_count": 200,
        "horizons": {"1": {"quantile_grid": grid, "p_up": p_up}},
    }


def test_verify_latest_pointer_live_as_of_field():
    """운영 포인터는 origin 이 아니라 as_of 를 쓴다 — 2026-10-27 실포인터가 드러낸
    필드명 결함의 회귀 테스트 (hold 상태만으로는 이 경로가 실행되지 않았다)."""
    from ai_fc.mts_research.adapters.v8 import verify_latest_pointer

    forecast = _synthetic_forecast()
    grid = forecast["horizons"]["1"]["quantile_grid"]
    cells = {
        "p10": grid[20], "p25": grid[50], "p50": grid[100],
        "p75": grid[150], "p90": grid[180],
        "probability_up": forecast["horizons"]["1"]["p_up"],
    }
    pointer = _pointer({"as_of": "2026-10-16", "status": "shadow_live", "horizons": {"1": cells}})
    result = verify_latest_pointer(pointer, [forecast])
    assert result["status"] == "PASS"
    assert result["pointer_origin"] == "2026-10-16"

    # 값 하나를 변조하면 MISMATCH — 투영 검사가 실제로 작동한다
    tampered_cells = {**cells, "p50": cells["p50"] + 1e-6}
    tampered = _pointer({"as_of": "2026-10-16", "status": "shadow_live", "horizons": {"1": tampered_cells}})
    bad = verify_latest_pointer(tampered, [forecast])
    assert bad["status"] == "MISMATCH"
    assert any("p50" in issue for issue in bad["issues"])


def test_verify_latest_pointer_hold_and_missing_forecast():
    from ai_fc.mts_research.adapters.v8 import verify_latest_pointer

    hold = _pointer({"status": "shadow_operational_hold"})
    assert verify_latest_pointer(hold, [])["status"] == "HOLD_POINTER"

    live = _pointer({
        "as_of": "2026-10-23", "status": "shadow_live",
        "horizons": {"1": {"p50": 0.0, "probability_up": 0.5}},
    })
    result = verify_latest_pointer(live, [_synthetic_forecast("2026-10-16")])
    assert result["status"] == "MISMATCH"
    assert any("forecast 행 없음" in issue for issue in result["issues"])


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
