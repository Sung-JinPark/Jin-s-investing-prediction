"""V15 최소 포크 — 패치 재현·A0 비트 동일·grid 연산 일치·잔차 정렬·vol fail-closed·frame 동일·달력 복사 정합
(spec_U3 §8 F1~F7). 합성 walk-forward 는 모듈 fixture 로 1회만 계산한다. 쓰기 0. 참고 의견, 매매 신호 아님.
"""

from __future__ import annotations

import ast
import difflib
import hashlib
import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

import ai_fc.timeseries_v15.backtest as fork_backtest
from ai_fc.timeseries_v8.backtest import walk_forward_dev_backtest_v8
from ai_fc.timeseries_v8.model import DistributionConfigV8
from ai_fc.timeseries_v15.arms import ARMS
from v15_coherence_fixtures import ROOT, REAL_CUTOFF, Obs, synthetic_market, weekday_sessions

FROZEN_LIKE = DistributionConfigV8(
    blend_weight_by_horizon={1: 1.0, 5: 1.0, 21: 0.75, 63: 0.75},
    pit_recalibration_shrinkage=0.5, fhs_horizons=(21, 63),
)
SESSIONS = 1100


def test_f1_fork_patch_manifest_reproduces_byte_for_byte() -> None:
    manifest = json.loads((ROOT / "data/timeseries_v15/prereg/fork_patch_v1.json").read_text(encoding="utf-8"))
    assert [entry["target"] for entry in manifest["files"]] == [
        "src/ai_fc/timeseries_v15/model.py", "src/ai_fc/timeseries_v15/backtest.py",
        "src/ai_fc/timeseries_v15/features.py"]
    for entry in manifest["files"]:
        original = (ROOT / entry["source"]).read_bytes()
        forked = (ROOT / entry["target"]).read_bytes()
        assert hashlib.sha256(original).hexdigest() == entry["source_sha256"], entry["source"]
        assert hashlib.sha256(forked).hexdigest() == entry["target_sha256"], entry["target"]
        diff = "".join(difflib.unified_diff(
            original.decode("utf-8").splitlines(keepends=True), forked.decode("utf-8").splitlines(keepends=True),
            fromfile=entry["source"], tofile=entry["target"]))
        assert diff == entry["unified_diff"]
        assert b"\r" not in forked


def _memoized(function):
    """입력 바이트가 정확히 같을 때만 결과를 재사용한다(결정론 함수 — 다른 입력이면 새로 계산).

    봉인 선택 함수(ridge·분포 모수)는 원점당 ~1.2초라 두 번째 walk-forward 의 같은 입력 호출만 줄인다.
    포크가 다른 입력을 넘기면 캐시가 빗나가 새로 계산되므로 비트 동일 판정의 의미는 그대로다."""
    cache: dict = {}

    def key_of(value):
        if isinstance(value, np.ndarray):
            return ("nd", value.shape, str(value.dtype), hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest())
        if isinstance(value, (list, tuple)):
            return tuple(key_of(item) for item in value)
        return repr(value)

    def wrapper(*args, **kwargs):
        key = (key_of(args), tuple(sorted((name, key_of(value)) for name, value in kwargs.items())))
        if key not in cache:
            cache[key] = function(*args, **kwargs)
        return cache[key]

    return wrapper


@pytest.fixture(scope="module")
def paired_walk_forward():
    import ai_fc.timeseries_v8.backtest as sealed_backtest

    dates = weekday_sessions(SESSIONS)
    endog, exog = synthetic_market(SESSIONS, seed=11)
    common = dict(
        dates=dates, endog=endog, exog=exog, endog_names=("a", "b", "c", "d", "e"), exog_names=("x", "y"),
        model_id="shadow.mf_dfm_varx_calibrated_v8", model_version=8, config=FROZEN_LIKE,
        outer_start=dates[820], outer_end=dates[1022], path_count=64,
        collect_cramer_audit=False, pit_min_matured=2, emit_forecast=True,
    )
    calls = {"fhs": 0}
    original = fork_backtest.fhs_horizon_samples

    def counting(*args, **kwargs):
        calls["fhs"] += 1
        return original(*args, **kwargs)

    patched = {name: _memoized(getattr(sealed_backtest, name))
               for name in ("select_ridge_varx_v2", "select_distribution_parameters_v2")}
    saved = {(module, name): getattr(module, name)
             for module in (sealed_backtest, fork_backtest) for name in patched}
    try:
        for module in (sealed_backtest, fork_backtest):
            for name, wrapper in patched.items():
                setattr(module, name, wrapper)
        sealed_scores, sealed_summary = walk_forward_dev_backtest_v8(**common)
        fork_backtest.fhs_horizon_samples = counting
        fork_scores, fork_summary = fork_backtest.walk_forward_v15(**common, arm=ARMS["A0"])
    finally:
        fork_backtest.fhs_horizon_samples = original
        for (module, name), value in saved.items():
            setattr(module, name, value)
    return sealed_scores, sealed_summary, fork_scores, fork_summary, calls


def test_f2_a0_is_bit_identical_to_sealed_v8_with_b4_and_fhs_active(paired_walk_forward) -> None:
    sealed_scores, sealed_summary, fork_scores, fork_summary, calls = paired_walk_forward
    assert sealed_summary["origin_count_window"] >= 40
    assert fork_scores == sealed_scores  # OriginScore 전 필드 정확 일치
    assert sum(sealed_summary["pit_recalibrated_origins"].values()) > 0
    assert sealed_summary["pit_recalibrated_origins"] == fork_summary["pit_recalibrated_origins"]
    assert calls["fhs"] >= 2 * sealed_summary["origin_count_window"]  # h21·h63 FHS 실활성
    left, right = sealed_summary["shadow_forecast"], fork_summary["shadow_forecast"]
    for key in ("1", "5", "21", "63"):
        for field in ("quantile_grid", "baseline_quantile_grid"):
            assert np.array_equal(np.asarray(left["horizons"][key][field]), np.asarray(right["horizons"][key][field]))
        assert left["horizons"][key]["recalibrated"] == right["horizons"][key]["recalibrated"]
    assert left["ensemble_weights"] == right["ensemble_weights"]
    assert (left["block_length"], left["ewma_lambda"]) == (right["block_length"], right["ewma_lambda"])
    assert right["arm"] == "A0" and isinstance(right["seed"], int)


def test_f3_grid_200_equals_final_session_grid(monkeypatch) -> None:
    dates = weekday_sessions(900)
    endog, exog = synthetic_market(900, seed=5)
    rng = np.random.default_rng(3)
    pit_history = {h: [(index, float(rng.uniform())) for index in range(0, 400, 5)] for h in (1, 5, 21, 63)}
    recorded: list[tuple] = []
    original_mix = fork_backtest.mixture_quantile_function
    original_recal = fork_backtest.recalibration_levels
    state: dict = {}

    def spy_recal(pits, *, target_levels, shrinkage):
        state["pits"], state["shrinkage"] = np.array(pits), shrinkage
        return original_recal(pits, target_levels=target_levels, shrinkage=shrinkage)

    def spy_mix(samples, historical, *, weight, levels):
        recorded.append((np.array(samples), np.array(historical), weight, state.pop("pits", None),
                         state.pop("shrinkage", None)))
        return original_mix(samples, historical, weight=weight, levels=levels)

    monkeypatch.setattr(fork_backtest, "mixture_quantile_function", spy_mix)
    monkeypatch.setattr(fork_backtest, "recalibration_levels", spy_recal)
    forecast = fork_backtest._final_session_forecast(
        dates=dates, endog=endog, exog=exog, endog_names=("a", "b", "c", "d", "e"), exog_names=("x", "y"),
        model_id="m", model_version=8, config=FROZEN_LIKE, path_count=64,
        expanding_history=[0.01, 0.02], rolling_history=[0.015, 0.018], pit_history=pit_history,
        pit_min_matured=2,
    )
    monkeypatch.setattr(fork_backtest, "mixture_quantile_function", original_mix)
    monkeypatch.setattr(fork_backtest, "recalibration_levels", original_recal)
    assert len(recorded) == 4
    for key, (samples, historical, weight, pits, shrinkage) in zip(("1", "5", "21", "63"), recorded):
        active = pits is not None
        grid = fork_backtest._grid_200(samples, historical, weight=weight,
                                       matured_pits=list(pits) if active else [], shrinkage=shrinkage, active=active)
        assert np.array_equal(grid, np.asarray(forecast["horizons"][key]["quantile_grid"]))
    assert any(forecast["horizons"][k]["recalibrated"] for k in forecast["horizons"])


def test_f4_varx_residual_last_row_is_origin_residual() -> None:
    from ai_fc.timeseries_v2.model import select_ridge_varx_v2

    endog, exog = synthetic_market(700, seed=9)
    origin = 600
    fit = select_ridge_varx_v2(endog[:origin + 1], exog[:origin + 1],
                               endog_names=("a", "b", "c", "d", "e"), exog_names=("x", "y"))
    assert len(fit.residuals) == fit.train_end - fit.train_start - fit.lag
    expected = endog[origin] - fit.predict(endog[:origin], exog[origin - 1])
    assert np.max(np.abs(fit.residuals[-1] - expected)) <= 1e-12


def test_f5_vol_paths_are_fail_closed_and_match_sealed_recursion() -> None:
    from ai_fc.timeseries_v2.model import _ewma_scale
    from ai_fc.timeseries_v15 import vol

    tree = ast.parse((ROOT / "src/ai_fc/timeseries_v15/vol.py").read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "ewma_scale_arm")
    constants = {node.value for node in ast.walk(function) if isinstance(node, ast.Constant)}
    assert "v8" not in constants  # A0 경로는 봉인 _ewma_scale 직접 호출
    fork_model = (ROOT / "src/ai_fc/timeseries_v15/model.py").read_text(encoding="utf-8")
    assert "scales = (_ewma_scale(residuals, ewma_lambda) if vol_mode == \"v8\"" in fork_model
    rng = np.random.default_rng(21)
    for trial in range(5):
        residuals = rng.normal(0, 0.01 * (trial + 1), size=(300, 5))
        decay = (0.94, 0.97)[trial % 2]
        variance = vol.ewma_variance_matrix(residuals, decay)
        rebuilt = np.sqrt(np.maximum(variance[-1], 1e-16)) / np.sqrt(np.maximum(variance, 1e-16))
        assert np.array_equal(rebuilt, _ewma_scale(residuals, decay))
    with pytest.raises(ValueError):
        vol.ewma_scale_arm(residuals, 0.97, mode="v9")
    with pytest.raises(ValueError):
        vol.ewma_variance_series_arm(residuals[:, 0], 0.97, mode="bogus")


def _synthetic_archive() -> list[Obs]:
    rows = []
    rng = np.random.default_rng(4)
    days = pd.bdate_range("2020-01-02", "2020-06-30")
    levels = {"NASDAQCOM": 9000.0, "VIX": 15.0, "DGS2": 1.5, "DGS10": 1.8, "DTWEXBGS": 115.0}
    for day in days:
        for series in levels:
            if series in ("DGS2", "DGS10") and day.strftime("%m-%d") == "02-17":
                continue
            levels[series] *= float(np.exp(rng.normal(0, 0.01)))
            rows.append(Obs(series, day.date().isoformat(), levels[series]))
    return rows


def test_f6_fork_frame_v8_mode_equals_sealed(monkeypatch) -> None:
    import ai_fc.timeseries_v2.features as sealed_features
    import ai_fc.timeseries_v15.features as fork_features

    rows = _synthetic_archive()
    monkeypatch.setattr(sealed_features, "read_market_observations", lambda root, knowledge_cutoff=None: rows)
    monkeypatch.setattr(fork_features, "read_market_observations", lambda root, knowledge_cutoff=None: rows)
    left, _ = sealed_features.build_core_market_frame(ROOT, knowledge_cutoff="2020-07-01T00:00:00+00:00")
    right, _ = fork_features.build_core_market_frame(ROOT, knowledge_cutoff="2020-07-01T00:00:00+00:00")
    pd.testing.assert_frame_equal(left, right, check_exact=True)
    monkeypatch.undo()
    left, _ = sealed_features.build_core_market_frame(ROOT, knowledge_cutoff=REAL_CUTOFF)
    right, _ = fork_features.build_core_market_frame(ROOT, knowledge_cutoff=REAL_CUTOFF, frame_mode="v8")
    pd.testing.assert_frame_equal(left, right, check_exact=True)
    assert len(right) > 7000


def test_f7_calendar_copy_matches_research_sessions() -> None:
    from ai_fc.mts_research import sessions as research
    from ai_fc.timeseries_v15 import calendar as copy_

    start, end = date(1995, 1, 1), date(2027, 12, 31)
    left = research.session_table(start, end)
    right = copy_.session_table(start, end)
    assert [(r.session, r.open_utc, r.close_utc, r.early_close) for r in left] == [
        (r.session, r.open_utc, r.close_utc, r.early_close) for r in right]
    for origin in (date(2001, 9, 10), date(2019, 4, 18), date(2026, 11, 6), date(2026, 12, 24)):
        assert research.future_sessions(origin, 63) == copy_.future_sessions(origin, 63)
        for k in (1, 5, 21, 63):
            assert research.session_offset(origin, k) == copy_.session_offset(origin, k)
    assert copy_.sessions_between(date(2026, 11, 2), date(2026, 11, 6)) == [
        date(2026, 11, d) for d in (2, 3, 4, 5, 6)]
