"""V15 팔 수식 단위 + 실데이터 오라클(as_of 고정) — spec_U3 §8 A1~A5.

실아카이브 프레임은 모드별로 1회만 조립한다(모듈 fixture). 어떤 팔의 점수도 계산하지 않는다(오라클은 입력 값뿐).
쓰기 0, 네트워크 0. 참고 의견, 매매 신호 아님.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
import pytest

import ai_fc.timeseries_v15.features as fork_features
import ai_fc.timeseries_v15.model as fork_model
from ai_fc.timeseries_v8.model import _ewma_variance_series
from ai_fc.timeseries_v15 import vol
from ai_fc.timeseries_v15.arms import DOLLAR_INDEX, apply_issuance_tail
from ai_fc.timeseries_v15.contracts import TimeSeriesV15DataError
from v15_coherence_fixtures import ROOT, REAL_CUTOFF, Obs, weekday_sessions

_FRAMES: dict = {}


def real_frame(mode: str, cutoff: str = REAL_CUTOFF):
    key = (mode, cutoff)
    if key not in _FRAMES:
        provenance: dict = {}
        frame, _ = fork_features.build_core_market_frame(ROOT, knowledge_cutoff=cutoff, frame_mode=mode,
                                                         provenance=provenance)
        _FRAMES[key] = (frame, provenance)
    return _FRAMES[key]


# ── A1 fresh_vol ─────────────────────────────────────────────────────────────


def test_a1_1_fresh_latest_variance_hand_computed() -> None:
    residuals = np.array([[0.01, -0.02], [0.03, 0.01], [-0.02, 0.04]])
    lam = 0.94
    sq = residuals ** 2
    var = np.empty_like(sq)
    var[0] = sq[0]
    var[1] = lam * var[0] + (1 - lam) * sq[0]
    var[2] = lam * var[1] + (1 - lam) * sq[1]
    latest = lam * var[2] + (1 - lam) * sq[2]
    expected = np.sqrt(latest) / np.sqrt(var)
    assert np.max(np.abs(vol.ewma_scale_arm(residuals, lam, mode="fresh") - expected)) <= 1e-12
    returns = np.random.default_rng(1).normal(0.0003, 0.012, size=900)
    v8 = fork_model.fhs_horizon_samples(returns, horizon=21, ewma_lambda=0.97, vol_mode="v8")
    fresh = fork_model.fhs_horizon_samples(returns, horizon=21, ewma_lambda=0.97, vol_mode="fresh")
    series = _ewma_variance_series(returns, 0.97)
    v_now_fresh = 0.97 * series[-1] + 0.03 * returns[-1] ** 2
    center = float(np.mean(returns)) * 21
    ratio = (fresh - center) / (v8 - center)
    assert np.max(np.abs(ratio - math.sqrt(v_now_fresh / series[-1]))) <= 1e-10


def test_a1_2_random_consumption_is_identical_across_vol_modes(monkeypatch) -> None:
    from ai_fc.timeseries_v2.model import select_ridge_varx_v2

    rng = np.random.default_rng(2)
    endog = rng.normal(0, 0.01, size=(500, 5))
    exog = rng.normal(0, 1, size=(500, 2))
    fit = select_ridge_varx_v2(endog, exog, endog_names=tuple("abcde"), exog_names=("x", "y"))
    recorded: dict[str, list] = {"v8": [], "fresh": []}
    original = fork_model._stationary_bootstrap_batch
    mode_holder = {"mode": "v8"}

    def spy(generator, **kwargs):
        value = original(generator, **kwargs)
        recorded[mode_holder["mode"]].append(value.copy())
        return value

    monkeypatch.setattr(fork_model, "_stationary_bootstrap_batch", spy)
    outputs = {}
    for mode in ("v8", "fresh"):
        mode_holder["mode"] = mode
        outputs[mode] = fork_model.simulate_calibrated_paths_v8(
            (fit, fit), weights=(0.5, 0.5), endog_history=endog, exog_last=exog[-1], anchor=1.0,
            path_count=200, horizon=21, block_length=10, ewma_lambda=0.97, seed=99, vol_mode=mode)
    assert np.array_equal(outputs["v8"]["assignments"], outputs["fresh"]["assignments"])
    assert len(recorded["v8"]) == len(recorded["fresh"]) == 2
    for left, right in zip(recorded["v8"], recorded["fresh"]):
        assert np.array_equal(left, right)
    assert not np.array_equal(outputs["v8"]["log_returns"], outputs["fresh"]["log_returns"])


def test_a2_1_lambda_mix_is_fixed_half_and_ignores_selected_lambda() -> None:
    residuals = np.random.default_rng(3).normal(0, 0.01, size=(400, 5))
    mixed = 0.5 * vol.ewma_variance_matrix(residuals, 0.94) + 0.5 * vol.ewma_variance_matrix(residuals, 0.97)
    expected = np.sqrt(np.maximum(mixed[-1], 1e-16)) / np.sqrt(np.maximum(mixed, 1e-16))
    assert np.array_equal(vol.ewma_scale_arm(residuals, 0.94, mode="lambda_mix"), expected)
    assert np.array_equal(vol.ewma_scale_arm(residuals, 0.94, mode="lambda_mix"),
                          vol.ewma_scale_arm(residuals, 0.97, mode="lambda_mix"))
    returns = residuals[:, 0]
    assert np.array_equal(vol.ewma_variance_series_arm(returns, 0.94, mode="lambda_mix"),
                          vol.ewma_variance_series_arm(returns, 0.97, mode="lambda_mix"))
    assert np.array_equal(vol.ewma_variance_series_arm(returns, 0.94, mode="lambda_mix"),
                          0.5 * _ewma_variance_series(returns, 0.94) + 0.5 * _ewma_variance_series(returns, 0.97))


# ── A3 xnas_label (실데이터 오라클) ──────────────────────────────────────────


def test_a3_1_real_oracle_2026_10_12() -> None:
    from ai_fc.timeseries_v2.market_archive import read_market_observations

    frame, provenance = real_frame("xnas_label")
    day = pd.Timestamp("2026-10-12")
    assert day in frame.index
    assert abs(frame.loc[day, "nasdaq_return"] - (-0.004404527952707)) <= 1e-12
    assert frame.loc[day, "dgs2_change_bps"] == 0.0
    assert {"DGS2", "DGS10", "DTWEXBGS"} <= set(provenance["carried_sessions"]["2026-10-12"])
    values = {(r.series_id, r.observation_time[:10]): r.value
              for r in read_market_observations(ROOT, knowledge_cutoff=REAL_CUTOFF) if r.series_id == "DGS2"}
    expected = (values[("DGS2", "2026-10-13")] - values[("DGS2", "2026-10-09")]) * 100
    assert abs(frame.loc[pd.Timestamp("2026-10-13"), "dgs2_change_bps"] - expected) <= 1e-9


def test_a3_2_non_xnas_nasdaq_rows_are_reported_not_used() -> None:
    frame, provenance = real_frame("xnas_label")
    assert "2019-04-19" in provenance["non_xnas_rows_ignored"]
    assert pd.Timestamp("2019-04-19") not in frame.index


def _synthetic_rows(missing_nasdaq: str | None = None) -> list[Obs]:
    rows = []
    days = pd.bdate_range("2021-03-01", "2021-04-30")
    for index, day in enumerate(days):
        text = day.date().isoformat()
        if text == "2021-04-02":  # 성금요일 — XNAS 휴장(국채는 개장)
            rows.append(Obs("DGS2", text, 0.2 + index * 1e-3))
            continue
        for series, base in (("NASDAQCOM", 13000.0), ("VIX", 20.0), ("DGS2", 0.2), ("DGS10", 1.5), ("DTWEXBGS", 112.0)):
            if series == "NASDAQCOM" and text == missing_nasdaq:
                continue
            rows.append(Obs(series, text, base * (1.0 + 0.001 * math.sin(index + len(series)))))
    return rows


def test_a3_3_internal_xnas_gap_fails_closed(monkeypatch) -> None:
    rows = _synthetic_rows(missing_nasdaq="2021-03-17")
    monkeypatch.setattr(fork_features, "read_market_observations", lambda root, knowledge_cutoff=None: rows)
    with pytest.raises(TimeSeriesV15DataError):
        fork_features.build_core_market_frame(ROOT, knowledge_cutoff="2021-05-01T00:00:00+00:00",
                                              frame_mode="xnas_label")


def test_a3_4_date_list_sessions_are_normalized(monkeypatch) -> None:
    rows = _synthetic_rows()
    monkeypatch.setattr(fork_features, "read_market_observations", lambda root, knowledge_cutoff=None: rows)
    reference, _ = fork_features.build_core_market_frame(ROOT, knowledge_cutoff="2021-05-01T00:00:00+00:00",
                                                         frame_mode="xnas_label")
    original = fork_features._xnas_sessions

    def as_dates(start, cutoff):
        return [value.date() for value in original(start, cutoff)]

    monkeypatch.setattr(fork_features, "_xnas_sessions", as_dates)
    frame, _ = fork_features.build_core_market_frame(ROOT, knowledge_cutoff="2021-05-01T00:00:00+00:00",
                                                     frame_mode="xnas_label")
    assert len(frame) > 30
    pd.testing.assert_frame_equal(frame, reference, check_exact=True)
    assert pd.Timestamp("2021-04-02") not in frame.index


# ── A4 vix_align (실데이터 오라클) ───────────────────────────────────────────


def test_a4_1_real_oracle_2026_01_20() -> None:
    a4, _ = real_frame("vix_align")
    a0, _ = real_frame("v8")
    day = pd.Timestamp("2026-01-20")
    assert abs(a4.loc[day, "vix_change"] - 0.23642196262014) <= 1e-12
    assert abs(a0.loc[day, "vix_change"] - 0.06423990967863) <= 1e-12
    assert abs((a4.loc[day, "vix_change"] - a0.loc[day, "vix_change"]) - 0.17218205294152) <= 1e-12


def test_a4_2_row_set_equals_a0() -> None:
    a4, _ = real_frame("vix_align")
    a0, _ = real_frame("v8")
    assert a4.index.equals(a0.index)
    assert a4.drop(columns="vix_change").equals(a0.drop(columns="vix_change"))


# ── A5 issuance ──────────────────────────────────────────────────────────────


def test_a5_1_issuance_tail_zeroes_only_origin_week_dollar() -> None:
    dates = weekday_sessions(20, start="2026-10-12")  # 2026-10-12(월) … 2026-11-06(금)
    endog = np.random.default_rng(5).normal(0, 0.01, size=(20, 5))
    original = endog.copy()
    out = apply_issuance_tail(endog, dates)
    week = [i for i, d in enumerate(dates) if date.fromisoformat(d).isocalendar()[:2] == (2026, 45)]
    assert len(week) == 5 and dates[week[0]] == "2026-11-02"
    assert np.all(out[week, DOLLAR_INDEX] == 0.0)
    mask = np.ones_like(out, dtype=bool)
    mask[week, DOLLAR_INDEX] = False
    assert np.array_equal(out[mask], original[mask])
    assert np.array_equal(endog, original)


def test_a5_2_real_tail_asof_matches_structural_week() -> None:
    frame, provenance = real_frame("v8_dollar_tail_asof", "2026-11-09T13:00:00+00:00")
    last = frame.index[-1].date().isoformat()
    assert last == "2026-11-06"
    assert provenance["dollar_tail_asof"] == ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"]
    assert provenance["dollar_last_obs_asof"] == "2026-10-30"
    week = date.fromisoformat(last).isocalendar()[:2]
    structural = [d.date().isoformat() for d in frame.index if d.date().isocalendar()[:2] == week]
    assert structural == provenance["dollar_tail_asof"]
    assert np.all(frame.loc[pd.Timestamp("2026-11-02"):, "dollar_change"].to_numpy() == 0.0)


def test_a5_3_issuance_deadline_is_next_open_minus_300s() -> None:
    from datetime import timedelta

    from ai_fc.timeseries_v15.calendar import open_utc, session_offset

    nxt = session_offset(date(2026, 11, 6), 1)
    assert nxt == date(2026, 11, 9)
    assert open_utc(nxt) == datetime(2026, 11, 9, 14, 30, tzinfo=timezone.utc)
    assert open_utc(nxt) - timedelta(seconds=300) == datetime(2026, 11, 9, 14, 25, tzinfo=timezone.utc)
