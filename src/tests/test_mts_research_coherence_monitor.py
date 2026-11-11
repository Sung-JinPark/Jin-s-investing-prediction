"""일일 정합성 감시기 C1~C12 (2026-11-11 설계 P2) — 단위·재생 오라클·원장 멱등.

실제 저장소 데이터는 읽기만 한다. 원장·derived 쓰기는 tmp_path 사본에서만 한다.
재생 오라클은 고정 원점 집합(2026-10-02~2026-11-09)으로 묶어 데이터가 늘어도 깨지지 않게 한다.
재생 경보 수는 표본 내 서술이며 검증된 성능이 아니다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from ai_fc.mts_research.audits import coherence as C
from ai_fc.mts_research.monitor_thresholds import (
    PINNED_THRESHOLD_HASH,
    THRESHOLDS_RELATIVE,
    load_pinned_thresholds,
)

ROOT = Path(__file__).resolve().parents[2]
COMPUTED_AT = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
PREREG = ROOT / "docs/research/mts_upgrade/coherence_monitor_prereg_20261111.md"

# 2026-10-02~11-09 일일 표시 원점 15개 (대체되지 않은 행) — 재생 오라클의 고정 집합
DISPLAY_ORIGINS = [date.fromisoformat(d) for d in (
    "2026-10-02", "2026-10-09", "2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16",
    "2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-11-04",
    "2026-11-05", "2026-11-06", "2026-11-09",
)]
COMMON_SHADOW_ORIGINS = [date.fromisoformat(d) for d in (
    "2026-10-02", "2026-10-09", "2026-10-16", "2026-10-23", "2026-11-06")]
SEALED_FILES = [
    "src/ai_fc/timeseries_v2/model.py",
    "src/ai_fc/timeseries_v2/features.py",
    "src/ai_fc/timeseries_v2/pipeline.py",
    "src/ai_fc/timeseries_v8/model.py",
    "src/ai_fc/timeseries_v8/pipeline.py",
    "src/ai_fc/daily6m_sources.py",
]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _jsonl(relative: str) -> list[dict]:
    return [json.loads(line) for line in (ROOT / relative).read_text(encoding="utf-8").splitlines()
            if line.strip()]


@pytest.fixture(scope="module")
def real_inputs():
    return C.load_monitor_inputs(ROOT)


@pytest.fixture(scope="module")
def thresholds():
    payload, status = load_pinned_thresholds(ROOT)
    assert status == "ok"
    return payload


@pytest.fixture(scope="module")
def replay(real_inputs, thresholds):
    """10-02~11-09 XNAS 세션 전부의 감시 행 (읽기 전용 계산)."""
    cal = C.xnas_calendar_for(date(2026, 10, 2))
    return {
        day: C.build_monitor_row(ROOT, day, thresholds=thresholds, threshold_status="ok",
                                 inputs=real_inputs, computed_at=COMPUTED_AT)
        for day in cal.between(date(2026, 10, 1), date(2026, 11, 9))
    }


# ---------------------------------------------------------------------------
# §3.0 봉인 무접촉 — V8·V2·daily6m model_code_hash 가 마지막 기록값과 같다
# ---------------------------------------------------------------------------


def test_sealed_model_code_hashes_unchanged():
    from ai_fc.timeseries_daily6m.contracts import model_code_hash as d6_hash
    from ai_fc.timeseries_v2.contracts import model_code_hash as v2_hash
    from ai_fc.timeseries_v8.contracts import model_code_hash as v8_hash

    assert v8_hash(ROOT) == _jsonl("data/timeseries_v8/ledgers/shadow_forecasts.jsonl")[-1]["model_code_hash"]
    corrections = _jsonl("data/timeseries_v2/ledgers/sealed_evaluation_corrections.jsonl")
    assert v2_hash(ROOT) == corrections[-1]["replacement_model_code_hash"]
    last_run = _jsonl("data/timeseries_daily6m/ledgers/forecasts.jsonl")[-1]["run_path"]
    recorded = json.loads((ROOT / last_run).read_text(encoding="utf-8"))["model_code_hash"]
    assert d6_hash(ROOT) == recorded


# ---------------------------------------------------------------------------
# P0 임계 해시
# ---------------------------------------------------------------------------


def test_threshold_hash_pinned():
    from ai_fc.timeseries_v8.contracts import canonical_hash

    payload = json.loads((ROOT / THRESHOLDS_RELATIVE).read_text(encoding="utf-8"))
    assert canonical_hash(payload) == PINNED_THRESHOLD_HASH
    documented = re.findall(r"`([0-9a-f]{64})`", PREREG.read_text(encoding="utf-8"))
    assert PINNED_THRESHOLD_HASH in documented
    loaded, status = load_pinned_thresholds(ROOT)
    assert status == "ok" and loaded == payload


# ---------------------------------------------------------------------------
# 순수 함수 단위
# ---------------------------------------------------------------------------


def test_c1_unit_formula():
    r_t = -0.0568
    v_used = r_t * r_t / 32.26
    value = C.c1_vol_staleness(0.97, v_used, r_t)
    assert value == pytest.approx(math.sqrt(0.97 + 0.03 * 32.26), rel=1e-12)
    assert value == pytest.approx(1.392, abs=1e-3)
    with pytest.raises(C.MtsCoherenceError):
        C.c1_vol_staleness(0.97, 0.0, r_t)


def test_ewma_variance_used_matches_sealed_recursion_and_sealed_lag_is_pinned():
    """봉인 _ewma_scale 은 마지막 잔차 변경에 불변이다 — 기지 1세션 지연을 고정하는 회귀."""
    from ai_fc.timeseries_v2.model import _ewma_scale
    from ai_fc.timeseries_v8.model import _ewma_variance_series

    rng = np.random.default_rng(7)
    returns = rng.normal(0.0, 0.01, 400)
    assert C.ewma_variance_used(returns, 0.97) == pytest.approx(
        float(_ewma_variance_series(returns, 0.97)[-1]), rel=1e-12)
    shocked = returns.copy()
    shocked[-1] = -0.0568
    base = _ewma_scale(returns.reshape(-1, 1), 0.97)
    after = _ewma_scale(shocked.reshape(-1, 1), 0.97)
    assert np.allclose(base, after)  # 원점일 충격이 상태에 들어가지 않는다 (봉인 — 수정 금지)
    assert C.ewma_variance_used(shocked, 0.97) == C.ewma_variance_used(returns, 0.97)


def test_c3a_returns_none_below_min_sessions():
    assert C.c3a_level_rank([0.1] * 19, [0.2] * 19, min_n=20) is None
    result = C.c3a_level_rank(list(range(20)), list(range(20)), min_n=20)
    assert result["rho"] == pytest.approx(1.0) and result["n"] == 20


def test_c3b_flags_only_large_sign_discord():
    pair = C.ConsecutivePair(date(2026, 11, 5), date(2026, 11, 6), 0.05, 0.08, 0.9, 0.7)
    result = C.c3b_delta_discord([pair], 1.0)
    assert result["pairs"][0]["sign_discord"] and result["flag"]
    calm = C.ConsecutivePair(date(2026, 11, 5), date(2026, 11, 6), 0.05, 0.08, 0.30, 0.25)
    assert not C.c3b_delta_discord([calm], 1.0)["flag"]
    with pytest.raises(C.MtsCoherenceError):
        C.c3b_delta_discord([C.ConsecutivePair(date(2026, 1, 1), date(2026, 1, 2), 0.0, 0.1, 0.2, 0.3)])


def test_c4_fixed_seed_is_deterministic():
    first = C.c4_rv_bound(0.5, 0.20)
    assert first == C.c4_rv_bound(0.5, 0.20)
    from scipy.stats import chi2

    analytic = float(chi2.sf(20 * (C.RV_THETA / 0.20) ** 2, 20))
    assert first["p_v8_terminal_bound"] == pytest.approx(analytic, abs=0.01)


def test_c5_epsilon_regression_on_two_step_boundary():
    shadow = {"origin": "2026-11-06", "horizons": {
        "1": {"p_up": 0.53}, "5": {"p_up": 0.55},
        "21": {"quantile_grid": [0.0] * 200}, "63": {"quantile_grid": [0.0] * 200}}}
    from ai_fc.timeseries_v8.contracts import canonical_hash

    grid_hash = canonical_hash([0.0] * 200)
    display = {"origin": "2026-11-06", "display_id": "d", "horizons": {
        "1": {"p_up": 0.52}, "5": {"p_up": 0.55},
        "21": {"quantile_grid_sha256": grid_hash}, "63": {"quantile_grid_sha256": grid_hash}}}
    result = C.c5_shadow_display_identity(shadow, display)
    assert result["h1_abs_delta_p_up"] == pytest.approx(0.01)
    assert not result["step_flag"] and not result["hash_flag"]
    display["horizons"]["1"]["p_up"] = 0.515
    assert C.c5_shadow_display_identity(shadow, display)["step_flag"]


def test_c7_tolerance_and_provisional_correction():
    day = date(2026, 10, 6)
    result = C.c7_input_identity(
        {"NASDAQCOM:archive": {day: 27599.89},
         "NASDAQCOM:market_quotes_close": {day: 27599.79},
         "NASDAQCOM:market_quotes_next_previous_close": {day: 27599.89},
         "NASDAQCOM:daily6m_anchor": {day: 27599.894}},
        0.005,
        provisional=frozenset({"NASDAQCOM:market_quotes_close"}),
        confirms={"NASDAQCOM:market_quotes_close": "NASDAQCOM:market_quotes_next_previous_close"},
    )
    assert not result["flag"] and result["provisional_mismatch_count"] == 1
    states = {row["source"]: row.get("state") for row in result["comparisons"]}
    assert states["market_quotes_close"] == "provisional_corrected"


# ---------------------------------------------------------------------------
# 재생 오라클 (실제 저장소, 고정 원점 집합)
# ---------------------------------------------------------------------------


def test_replay_rows_have_no_computation_error(replay):
    """_run_indicator 는 코드 결함도 null 로 닫는다 — 재생 전 행에서 조용한 null 이 없는지 확인."""
    for day, row in replay.items():
        for key in C.INDICATOR_KEYS:
            reason = str(row[key]["null_reason"] or "")
            assert not reason.startswith("computation_error"), (day, key, reason)


def test_replay_c1_flags_on_display_rows(replay):
    rows = [replay[d] for d in DISPLAY_ORIGINS]
    assert all(row["C1"]["surface"] == "v8_daily_display" for row in rows)
    flagged = {date.fromisoformat(row["as_of"]) for row in rows if row["C1"]["flag"]}
    assert flagged == {date(2026, 10, 14), date(2026, 10, 16), date(2026, 10, 22), date(2026, 11, 5)}
    assert replay[date(2026, 11, 5)]["C1"]["value"] == pytest.approx(1.287, abs=1e-3)
    assert replay[date(2026, 10, 20)]["C1"]["flag"] is False
    assert all(row["C1"]["proxy"] for row in rows)


def test_replay_c2_band_exit_only_on_shock_day(replay):
    rows = [replay[d] for d in DISPLAY_ORIGINS]
    flagged = {row["as_of"] for row in rows if row["C2"]["flag"]}
    assert flagged == {"2026-11-05"}
    assert replay[date(2026, 11, 5)]["C2"]["value"] == pytest.approx(0.594, abs=5e-4)


def test_replay_c5_grid_identity_26_of_26(replay):
    matches = checks = 0
    for origin in COMMON_SHADOW_ORIGINS:
        c5 = replay[origin]["C5"]
        rows = [row for row in c5["rows"]]
        matches += c5["grid_hash_matches"]
        checks += c5["grid_hash_checks"]
        assert c5["flag"] is False
        assert len(rows) >= 1
    assert (matches, checks) == (26, 26)
    effective = next(r for r in replay[date(2026, 11, 6)]["C5"]["rows"] if r["effective"])
    assert effective["h1_abs_delta_p_up"] == pytest.approx(0.010000000000000009, abs=1e-15)
    assert effective["h1_step_flag"] is False


def test_replay_c6_lambda_switch_and_same_day_disagreement(replay):
    rows = [replay[d]["C6"] for d in DISPLAY_ORIGINS]
    transitions = [row for row in rows if row["switch"] is not None]
    assert (sum(row["switch"] for row in transitions), len(transitions)) == (6, 14)
    same_day = [row for row in rows if row["disagree"] is not None]
    assert (sum(row["disagree"] for row in same_day), len(same_day)) == (6, 10)


def test_replay_c3b_consecutive_only(replay):
    assert replay[date(2026, 11, 6)]["C3b"]["flag"] is True
    assert replay[date(2026, 11, 9)]["C3b"]["flag"] is True
    assert replay[date(2026, 11, 5)]["C3b"]["flag"] is False  # 같은 방향 (concord)
    # 11-04 직전 세션(11-03)에는 V8 행이 없다 — 10-23→11-04 같은 비연속 쌍은 평가하지 않는다
    assert replay[date(2026, 11, 4)]["C3b"]["null_reason"] == "no_consecutive_pair"
    assert all(replay[d]["C3a"]["null_reason"] == "insufficient_sessions" for d in DISPLAY_ORIGINS)


def test_c3a_refuses_mixed_tail_sources(real_inputs, thresholds, monkeypatch):
    """C3a 도 C3b 처럼 표시(정규근사)·섀도(격자 보간) 꼬리를 한 순위열에 섞지 않는다."""
    as_of = date(2026, 11, 9)
    cal = C.xnas_calendar_for(as_of)
    day = C._Day(as_of=as_of, cal=cal, inputs=real_inputs, coh=thresholds["coherence"],
                 reference_at=COMPUTED_AT)
    monkeypatch.setattr(C, "c3a_level_rank", lambda tail, v25, min_n: {"rho": 0.5, "n": len(tail)})
    result = C._m_c3a(day)
    assert result["tail_sources"] == ["v8_daily_display", "v8_weekly_shadow"]
    assert result["null_reason"] == "mixed_v8_surfaces" and result["value"] is None


def test_replay_c4_no_rv_bound_violation(replay):
    slacks = [replay[d]["C4"]["value"] for d in DISPLAY_ORIGINS if replay[d]["C4"]["value"] is not None]
    assert len(slacks) == 14  # 10-16 은 V13 행이 없다
    assert min(slacks) > -0.05
    assert replay[date(2026, 11, 9)]["C4"]["value"] == pytest.approx(0.027, abs=0.01)


def test_replay_c7_detects_cent_mismatch_and_corrects_after_hours(replay):
    c7 = replay[date(2026, 10, 29)]["C7"]
    assert c7["flag"] is True
    hits = {(row["source"], row["value"], row["reference"]) for row in c7["comparisons"]
            if row["mismatch"] and not row["provisional"]}
    assert ("daily6m_source_observations", 26184.73, 26184.72) in hits
    after_hours = replay[date(2026, 10, 6)]["C7"]
    assert after_hours["flag"] is False
    quote = next(row for row in after_hours["comparisons"] if row["source"] == "market_quotes_close")
    assert quote["state"] == "provisional_corrected"


def test_c9_vix_offsession_oracle(real_inputs):
    vix = real_inputs.data["archive_index"]["latest"]["VIX"]
    cal = C.xnas_calendar_for(date(2026, 1, 20))
    result = C.c9_vix_offsession(date(2026, 1, 20), vix, cal)
    exposure = next(item for item in result["exposures"] if item["session"] == "2026-01-20")
    assert exposure["offsession_row"] == "2026-01-19"
    assert exposure["used"] == pytest.approx(0.064, abs=5e-4)
    assert exposure["correct"] == pytest.approx(0.236, abs=5e-4)
    later = C.c9_vix_offsession(date(2026, 11, 9), vix, C.xnas_calendar_for(date(2026, 11, 9)))
    assert later["flag"] is False
    assert later["offsession_rows_since_2014"] == 33
    assert later["next_exposure_projected"]["exposed_session"] == "2026-11-27"
    assert later["next_exposure_projected"]["closure_type"] == "Thanksgiving"


def test_c9_projection_skips_closure_types_without_vix_rows(real_inputs):
    """성탄·신정은 패턴 창(2022-05~)에서 VIX 행이 한 번도 없었다 — 노출로 투영하지 않는다."""
    vix = real_inputs.data["archive_index"]["latest"]["VIX"]
    origin = date(2026, 11, 27)
    cal = C.xnas_calendar_for(origin)
    projected = C.project_vix_exposure(origin, vix, cal, C.weekday_closure_names(cal))
    skipped = {item["closure"]: item for item in projected["skipped_closures"]}
    assert set(skipped) == {"2026-12-25", "2027-01-01"}
    assert all(item["vix_rows_observed"] == 0 for item in skipped.values())
    assert projected["closure"] == "2027-01-18" and projected["exposed_session"] == "2027-01-19"


def test_replay_c10_records_h63_divergence(replay):
    c10 = replay[date(2026, 11, 6)]["C10"]
    assert c10["flag"] is True and c10["no_arithmetic_combination"] is True and c10["screen_badge"] is None
    assert c10["value"] == pytest.approx(0.70 - 0.562, abs=0.01)
    horizons = c10["horizons"]
    assert horizons["1"]["target_session_v8"] == horizons["1"]["target_session_d6"] == "2026-11-09"
    assert horizons["1"]["target_sessions_differ"] is False
    # 11-11 은 국채 휴장 — V8 grid 의 h5 는 한 세션 뒤로 밀린다
    assert (horizons["5"]["target_session_v8"], horizons["5"]["target_session_d6"]) == ("2026-11-16", "2026-11-13")
    assert horizons["63"]["target_sessions_differ"] is True
    assert "XNAS" in c10["horizon_basis"]


def test_replay_c11_confirmed_and_projected_drops(replay):
    horizons = {item["h"]: item for item in replay[date(2026, 10, 2)]["C11"]["horizons"]}
    assert horizons[21]["dropped_sessions_confirmed"] == ["2026-10-12"]
    assert horizons[1]["exposed"] is False
    late = {item["h"]: item for item in replay[date(2026, 11, 9)]["C11"]["horizons"]}
    assert late[5]["dropped_sessions_projected"] == ["2026-11-11"]


def test_replay_c12_fed_ebp_silent_stall(replay):
    states = {row["series_id"]: row["state"] for row in replay[date(2026, 11, 9)]["C12"]["series"]}
    assert states["FED_EBP"] == "silent_stall"
    assert states["NASDAQCOM"] == "ok" and states["VIX"] == "ok"
    # 새 원본 바이트(2026-10-07 수집분) 전에는 정체가 아니다 — 같은 바이트 반복 수집은 증거가 아님
    early = {row["series_id"]: row["state"] for row in replay[date(2026, 10, 2)]["C12"]["series"]}
    assert early["FED_EBP"] == "stale_source"
    assert replay[date(2026, 10, 2)]["C12"]["flag"] is False


def test_rows_carry_disclosure_fields(replay):
    row = replay[date(2026, 11, 9)]
    assert row["display_only"] and row["scoring_excluded"] and row["notice"] == "참고 의견, 매매 신호 아님"
    assert row["coherence_id"] == "coh-2026-11-09-v1"
    assert row["retrospective"] is True and row["computed_at"] == COMPUTED_AT.isoformat()
    assert row["n_dates"] == 1 and row["single_episode"] is True and row["no_arithmetic_combination"]
    for key in C.INDICATOR_KEYS:
        assert {"value", "threshold", "flag", "n", "null_reason", "proxy"} <= set(row[key])


def test_acceptance_as_of_2026_11_10_all_indicators_null_or_value(real_inputs, thresholds):
    row = C.build_monitor_row(ROOT, date(2026, 11, 10), thresholds=thresholds, threshold_status="ok",
                              inputs=real_inputs, computed_at=COMPUTED_AT)
    for key in C.INDICATOR_KEYS:
        assert (row[key]["value"] is None) == (row[key]["null_reason"] is not None)
        assert not str(row[key]["null_reason"] or "").startswith("computation_error")
    assert "FED_EBP" in row["C12"]["stalled_series"]


# ---------------------------------------------------------------------------
# tmp 사본: 결측·해시 불일치·원장 멱등
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def base_copy(tmp_path_factory):
    root = tmp_path_factory.mktemp("coh") / "repo"
    for relative in list(C.INPUT_FILES.values()) + [THRESHOLDS_RELATIVE]:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    forecasts = [json.loads(line) for line in (ROOT / C.D6_FORECASTS_RELATIVE).read_text(
        encoding="utf-8").splitlines() if line.strip()]
    run = next(row["run_path"] for row in forecasts if row["origin_session"] == "2026-11-06")
    (root / run).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / run, root / run)
    return root


def _copy(base: Path, tmp_path: Path) -> Path:
    target = tmp_path / "repo"
    shutil.copytree(base, target)
    return target


def _args(**overrides) -> argparse.Namespace:
    body = {"as_of": "2026-11-06", "append": False, "report": None, "kind": None,
            "now": "2026-11-11T12:00:00+00:00"}
    body.update(overrides)
    return argparse.Namespace(**body)


def test_missing_input_nulls_only_dependent_indicators(base_copy, tmp_path, thresholds):
    root = _copy(base_copy, tmp_path)
    (root / C.V13_LIVE_RELATIVE).unlink()
    row = C.build_monitor_row(root, date(2026, 11, 6), thresholds=thresholds, threshold_status="ok",
                              computed_at=COMPUTED_AT)
    for key in ("C3a", "C3b", "C4"):
        assert row[key]["value"] is None and row[key]["null_reason"].startswith("input_missing")
    for key in ("C1", "C2", "C5", "C6", "C9", "C10", "C11", "C12"):
        assert row[key]["null_reason"] is None, key


def test_threshold_hash_mismatch_nulls_everything(base_copy, tmp_path):
    from ai_fc.mts_research.audits.coherence import run_monitor_cli

    root = _copy(base_copy, tmp_path)
    path = root / THRESHOLDS_RELATIVE
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["coherence"]["C1_vol_staleness_max"] = 1.2
    path.write_text(json.dumps(payload), encoding="utf-8")
    code, out = run_monitor_cli(root, _args(append=True))
    assert code == 2 and out["status"] == "threshold_hash_mismatch" and out["appended"] == 0
    assert all(out["row"][key]["value"] is None for key in C.INDICATOR_KEYS)
    assert not (root / C.MONITOR_LEDGER_RELATIVE).exists()


def test_append_is_idempotent_and_chain_verifies(base_copy, tmp_path):
    from ai_fc.mts_research.artifacts import read_chain

    root = _copy(base_copy, tmp_path)
    sealed_before = {name: _sha(ROOT / name) for name in SEALED_FILES}
    code, dry = C.run_monitor_cli(root, _args())
    assert code == 0 and dry["appended"] == 0 and dry["status"] == "dry_run"
    assert not (root / C.MONITOR_LEDGER_RELATIVE).exists()
    code, first = C.run_monitor_cli(root, _args(append=True))
    assert code == 0 and first["appended"] == 1
    code, again = C.run_monitor_cli(root, _args(append=True, now="2026-11-12T00:00:00+00:00"))
    assert code == 0 and again["appended"] == 0 and again["already_recorded"]
    assert again["recomputed_matches_ledger"] is True
    rows = read_chain(root, C.MONITOR_LEDGER_RELATIVE)
    assert [row["coherence_id"] for row in rows] == ["coh-2026-11-06-v1"]
    assert rows[0]["retrospective"] is True and rows[0]["computed_at"] == "2026-11-11T12:00:00+00:00"
    derived = json.loads((root / C.MONITOR_DERIVED_RELATIVE).read_text(encoding="utf-8"))
    assert derived["n_dates"] == 1 and derived["display_only"] and derived["indicator_summary"]["C10"]["n_flagged"] == 1
    assert "검증된 성능" in derived["in_sample_note"]
    assert {name: _sha(ROOT / name) for name in SEALED_FILES} == sealed_before


def test_live_row_rerun_with_later_now_matches_ledger(base_copy, tmp_path, thresholds):
    """다음 개장 전에 계산한 비소급 행 — 나중에 재실행해도 원래 computed_at 으로 재계산해 일치."""
    root = _copy(base_copy, tmp_path)
    live_now, later_now = "2026-11-07T00:00:00+00:00", "2026-11-12T20:00:00+00:00"
    code, first = C.run_monitor_cli(root, _args(append=True, now=live_now))
    assert code == 0 and first["appended"] == 1 and first["retrospective"] is False
    assert first["row"]["reference_at"] == live_now
    # 벽시계로 다시 계산하면 reference_at 이 달라져 해시가 바뀐다 — 비교는 원래 시각으로 해야 한다
    naive = C.build_monitor_row(root, date(2026, 11, 6), thresholds=thresholds, threshold_status="ok",
                                computed_at=datetime(2026, 11, 12, 20, 0, tzinfo=timezone.utc))
    assert naive["result_hash"] != first["row"]["result_hash"]
    for now in (later_now, "2026-11-09T14:00:00+00:00"):
        code, again = C.run_monitor_cli(root, _args(append=True, now=now))
        assert code == 0 and again["appended"] == 0 and again["already_recorded"]
        assert again["recomputed_matches_ledger"] is True
        assert again["recomputed_with_computed_at"] == live_now


def test_append_refuses_as_of_without_archive_close(base_copy, tmp_path):
    """아카이브 마지막 세션 다음 날(종가 미도착)은 dry-run 만 되고 append 는 0행."""
    root = _copy(base_copy, tmp_path)
    inputs = C.load_monitor_inputs(root)
    pending = C.xnas_calendar_for(C.default_as_of(inputs)).following(C.default_as_of(inputs))
    code, dry = C.run_monitor_cli(root, _args(as_of=pending.isoformat(), now="2026-12-31T00:00:00+00:00"))
    assert code == 0 and dry["status"] == "dry_run" and not all(dry["archive_closes_present"].values())
    code, out = C.run_monitor_cli(root, _args(as_of=pending.isoformat(), append=True,
                                              now="2026-12-31T00:00:00+00:00"))
    assert code == 4 and out["status"] == "pending_archive" and out["appended"] == 0
    assert not (root / C.MONITOR_LEDGER_RELATIVE).exists()


def test_cli_rejects_non_session_as_of(base_copy, tmp_path):
    root = _copy(base_copy, tmp_path)
    code, out = C.run_monitor_cli(root, _args(as_of="2026-11-08"))
    assert code == 4 and out["status"] == "precondition_failed"


def test_default_as_of_is_last_archive_session(real_inputs):
    latest = real_inputs.data["archive_index"]["latest"]
    expected = min(max(latest["NASDAQCOM"]), max(latest["VIX"]))
    got = C.default_as_of(real_inputs)
    assert got <= expected and got >= date(2026, 11, 9)
