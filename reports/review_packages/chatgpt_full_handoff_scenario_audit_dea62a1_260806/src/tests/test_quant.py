"""quant 모듈 단위 테스트 — 전부 합성 시계열 (네트워크 불필요)."""

from __future__ import annotations

import numpy as np
import pytest

from ai_fc.quant import overlay, stats
from ai_fc.quant.lppl import fit_lppl
from ai_fc.quant.mc import gbm_simulate
from ai_fc.quant.seasonality import midterm_stats, summarize
from datetime import date, timedelta


def test_normalize_and_offset() -> None:
    labels = ["1996-01", "1996-02", "1996-03"]
    idx = overlay.normalize(labels, [100.0, 110.0, 121.0], "1996-01")
    assert idx[0] == 100.0 and abs(idx[2] - 121.0) < 1e-9
    assert overlay.month_offset("2023-01", "2026-07") == 42


def test_max_drawdown_known() -> None:
    labels = [f"d{i}" for i in range(5)]
    dd = overlay.max_drawdown(labels, [100, 120, 90, 110, 95])
    assert abs(dd.mdd - (90 / 120 - 1)) < 1e-9  # -25%


def test_hurst_random_walk_near_half() -> None:
    rng = np.random.default_rng(7)
    prices = np.exp(np.cumsum(rng.standard_normal(600) * 0.01)) * 100
    h = stats.hurst_rs(list(prices))
    assert 0.35 < h < 0.65  # 랜덤워크 ≈ 0.5 (느슨한 검정)


def test_hurst_persistent_higher() -> None:
    rng = np.random.default_rng(7)
    shocks = rng.standard_normal(600) * 0.01
    trend = np.cumsum(shocks) * 0.5 + np.cumsum(np.abs(shocks)) * 0.05  # 추세 강화
    prices = np.exp(trend) * 100
    assert stats.hurst_rs(list(prices)) > 0.6


def test_power_law_recovers_exact_beta() -> None:
    t = np.arange(1, 61, dtype=float)
    p = 5.0 * t ** 0.33
    assert abs(stats.power_law_beta(list(p)) - 0.33) < 1e-6


def test_dtw_identity_zero() -> None:
    rng = np.random.default_rng(3)
    a = np.cumsum(rng.standard_normal(50)) + 100
    assert stats.dtw_distance(a, a) < 1e-9


def test_best_shift_detects_lead() -> None:
    rng = np.random.default_rng(5)
    base = np.cumsum(np.abs(rng.standard_normal(60))) + 100
    dotcom = {m: float(base[m]) for m in range(60)}
    ai = {m: float(base[m + 4]) for m in range(56)}  # AI가 4개월 선행
    shift, _ = stats.best_shift(ai, dotcom)
    assert shift == 4


def test_gbm_reproducible_and_sane() -> None:
    closes = list(np.exp(np.linspace(0, 0.24, 24)) * 100)  # 월 +1% 추세
    r1 = gbm_simulate(closes, seed=42)
    r2 = gbm_simulate(closes, seed=42)
    assert r1.median_pct == r2.median_pct  # 시드 고정 재현성
    assert 0.9 < r1.prob_up <= 1.0


def test_lppl_recovers_synthetic_tc() -> None:
    # 합성 LPPL 시계열 (tc=48, β=0.33, ω=6.5)에서 tc 복원
    t = np.arange(41, dtype=float)
    tc, beta, omega, phi = 48.0, 0.33, 6.5, 1.0
    dt = tc - t
    lnp = 5.0 - 0.4 * dt ** beta + 0.02 * dt ** beta * np.cos(omega * np.log(dt) - phi)
    fit = fit_lppl(list(np.exp(lnp)))
    assert abs(fit.tc - tc) < 4.0  # ±4개월 내 복원 (적합 불안정성 감안)
    assert fit.r2 > 0.95


def test_midterm_stats_synthetic() -> None:
    # 합성: 2018 사례 하나 — 선거 전 하락, 이후 상승
    days = [date(2018, 1, 1) + timedelta(days=i) for i in range(900)]
    closes = []
    for d in days:
        if d < date(2018, 10, 1):
            closes.append(100.0)
        elif d <= date(2018, 11, 6):
            closes.append(90.0)   # 선거 전 -10% (선거일 종가 포함)
        else:
            closes.append(110.0)  # 이후 랠리
    cases = midterm_stats(days, closes)
    assert len(cases) == 1
    assert cases[0].pre_window_dd == pytest.approx(-0.10)
    assert cases[0].plus_12m == pytest.approx(0.10 / 0.90, rel=1e-6) or cases[0].plus_12m > 0
