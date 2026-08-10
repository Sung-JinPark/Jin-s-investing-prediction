"""P1.7-S2: GBM 경로·배리어 확률 테스트 — 합성 데이터만 (백테스트 금지)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from ai_fc.ml.runner import _window_steps
from ai_fc.quant.mc import barrier_prob, gbm_paths


def _synthetic_closes(n_rets: int = 300, seed: int = 7) -> list[float]:
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0, 0.02, n_rets)
    prices = 100.0 * np.exp(np.cumsum(rets))
    return [100.0] + [float(p) for p in prices]


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def test_barrier_vs_reflection_principle() -> None:
    """무드리프트 GBM의 상방 배리어 터치 확률 ≈ 반사원리 해석해 2·N(−b/σ√T).

    주간 이산 관측은 연속 터치를 소폭 과소추정 — 허용오차에 반영.
    """
    closes = _synthetic_closes()
    horizon, n = 100, 40000
    paths = gbm_paths(closes, lookback=len(closes) - 1, horizon=horizon, n=n, seed=1)

    arr = np.asarray(closes)
    rets = np.diff(np.log(arr))
    mu, sigma = float(rets.mean()), float(rets.std(ddof=1))
    s0 = float(arr[-1])
    threshold = s0 * 1.15
    b = math.log(threshold / s0)
    drift = mu - sigma ** 2 / 2
    t = float(horizon)
    # 드리프트 있는 브라운 운동의 배리어 터치 해석해
    analytic = (_norm_cdf((drift * t - b) / (sigma * math.sqrt(t)))
                + math.exp(2 * drift * b / sigma ** 2)
                * _norm_cdf((-b - drift * t) / (sigma * math.sqrt(t))))
    mc_touch = barrier_prob(paths, threshold, "above")
    assert mc_touch == pytest.approx(analytic, abs=0.04)
    assert mc_touch <= analytic + 0.01  # 이산 관측은 연속해를 넘지 않아야 함


def test_touch_geq_terminal_invariant() -> None:
    """불변식: 경로 터치 확률 ≥ 종점 상회 확률."""
    closes = _synthetic_closes(seed=11)
    paths = gbm_paths(closes, lookback=100, horizon=30, n=5000, seed=2)
    thr = float(closes[-1]) * 1.05
    touch = barrier_prob(paths, thr, "above")
    terminal = float((paths[:, -1] >= thr).mean())
    assert touch >= terminal
    # below 방향도 동일
    thr_dn = float(closes[-1]) * 0.95
    assert barrier_prob(paths, thr_dn, "below") >= float((paths[:, -1] <= thr_dn).mean())


def test_step_range_partial_window() -> None:
    closes = _synthetic_closes(seed=3)
    paths = gbm_paths(closes, lookback=100, horizon=20, n=3000, seed=4)
    thr = float(closes[-1]) * 1.03
    full = barrier_prob(paths, thr, "above")
    assert barrier_prob(paths, thr, "above", (0, 19)) == pytest.approx(full)
    sub = barrier_prob(paths, thr, "above", (5, 10))
    assert 0.0 <= sub <= full
    assert barrier_prob(paths, thr, "above", (15, 3)) == 0.0  # 역전 구간 → 0


def test_seed_reproducibility() -> None:
    closes = _synthetic_closes(seed=5)
    a = gbm_paths(closes, lookback=50, horizon=10, n=500, seed=42)
    b = gbm_paths(closes, lookback=50, horizon=10, n=500, seed=42)
    assert np.array_equal(a, b)


def test_window_steps() -> None:
    from datetime import date

    asof = date(2099, 7, 15)
    assert _window_steps(asof, None, 25) is None
    s = _window_steps(asof, ("2099-08-01", "2099-10-31"), 25)
    assert s == (2, 16)  # 17일//7=2, ceil(108/7)=16
    # 윈도우가 지평을 넘으면 클램프
    s2 = _window_steps(asof, ("2099-08-01", "2100-06-30"), 25)
    assert s2 == (2, 24)
