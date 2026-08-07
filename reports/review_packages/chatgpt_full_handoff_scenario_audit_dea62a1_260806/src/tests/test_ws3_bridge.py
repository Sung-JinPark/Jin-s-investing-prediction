"""WS3: 브라운 브리지 보정 — 수식 스팟값 · 단조성(보정 ≥ raw) · 기터치=1 · GBM 일간 ≥ 주간."""

from __future__ import annotations

import math

import numpy as np

from ai_fc.ml.chronos_fc import bridge_touch_prob
from ai_fc.quant import mc


def test_bridge_spot_value() -> None:
    """단일 경로·단일 쌍 — p = exp(−2·d0·d1/σ²) 수식 직접 검증 (하향 배리어)."""
    b = 100.0
    d0, d1, sigma = 0.10, 0.05, 0.08
    path = np.array([[b * math.exp(d0), b * math.exp(d1)]])
    expected = math.exp(-2 * d0 * d1 / sigma ** 2)
    got = bridge_touch_prob(path, b, "below", sigma_w=sigma)
    assert abs(got - expected) < 1e-9

    # 상향 배리어 부호 대칭
    path_up = np.array([[b * math.exp(-d0), b * math.exp(-d1)]])
    got_up = bridge_touch_prob(path_up, b, "above", sigma_w=sigma)
    assert abs(got_up - expected) < 1e-9


def test_bridge_already_touched_is_one() -> None:
    """관측점 자체가 배리어를 넘은 경로는 확률 1."""
    paths = np.array([[110.0, 95.0, 112.0],     # 95 < 100 터치
                      [120.0, 118.0, 125.0]])   # 미터치
    p = bridge_touch_prob(paths, 100.0, "below", sigma_w=0.05)
    assert p >= 0.5  # 터치 경로가 정확히 1로 계수됨
    p_all = bridge_touch_prob(np.array([[110.0, 95.0, 112.0]]), 100.0, "below",
                              sigma_w=0.05)
    assert p_all == 1.0


def test_bridge_monotonic_vs_raw() -> None:
    """보정 ≥ raw — 브리지 항은 확률 질량을 더할 뿐이다 (전 방향·윈도우)."""
    rng = np.random.default_rng(7)
    start = 100.0
    paths = start * np.exp(np.cumsum(rng.normal(0, 0.03, (500, 20)), axis=1))
    for direction, thr in (("below", 92.0), ("above", 108.0)):
        for step_range in (None, (3, 15)):
            raw = mc.barrier_prob(paths, thr, direction, step_range)
            corrected = bridge_touch_prob(paths, thr, direction, step_range)
            assert corrected >= raw - 1e-12, (direction, step_range)
            assert corrected <= 1.0


def test_gbm_daily_geq_weekly() -> None:
    """GBM 일간 스텝 전환 후 터치 확률 ≥ 주간 (동일 원천 시계열, 통계 허용오차)."""
    rng = np.random.default_rng(42)
    daily = list(100.0 * np.exp(np.cumsum(rng.normal(0.0002, 0.012, 500))))
    weekly = daily[::5]
    horizon_w, horizon_d = 12, 60
    pw = mc.gbm_paths(weekly, lookback=52, horizon=horizon_w, seed=1)
    pd = mc.gbm_paths(daily, lookback=252, horizon=horizon_d, seed=1)
    thr = daily[-1] * 0.94
    raw_w = mc.barrier_prob(pw, thr, "below")
    raw_d = mc.barrier_prob(pd, thr, "below")
    assert raw_d >= raw_w - 0.02  # 관측 밀도 증가 → 터치 확률 증가 (허용오차 2%p)
