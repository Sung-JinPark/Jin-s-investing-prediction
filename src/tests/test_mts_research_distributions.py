"""확률 객체 테스트 — T28~T32 + randomized PIT·identity 보정(T30)."""

from __future__ import annotations

import numpy as np
import pytest

from ai_fc.mts_research.distributions import (
    MtsDistributionError,
    QuantileGridForecast,
    UnsupportedCapability,
    WeightedEmpiricalDistribution,
    mixture_cdf,
    quantile_average,
    randomized_pit,
)


def test_t28_cdf_quantile_pup_same_object():
    """CDF 단조·범위·우연속 + quantile 단조 + p_up 이 같은 객체에서 (T28)."""
    dist = WeightedEmpiricalDistribution([-2.0, -1.0, 0.0, 1.0, 3.0])
    xs = np.linspace(-3, 4, 71)
    cdf_values = [dist.cdf(x) for x in xs]
    assert all(b >= a for a, b in zip(cdf_values, cdf_values[1:]))  # 단조
    assert cdf_values[0] == 0.0 and cdf_values[-1] == 1.0
    assert dist.cdf(1.0) == pytest.approx(0.8)  # 우연속: 원자 포함
    qs = [dist.quantile(q) for q in np.linspace(0.01, 0.99, 25)]
    assert all(b >= a for a, b in zip(qs, qs[1:]))
    assert dist.p_above(0.0, boundary=">") == pytest.approx(1.0 - dist.cdf(0.0))
    lower, upper = dist.interval(0.1, 0.9)
    assert lower <= dist.quantile(0.5) <= upper


def test_t29_point_mass_boundary_and_generalized_inverse():
    """점질량·경계 — `>=` 는 좌극한, quantile 은 일반화 역함수 (T29)."""
    dist = WeightedEmpiricalDistribution([0.0, 0.0, 1.0, 2.0], [0.25, 0.25, 0.25, 0.25])
    assert dist.point_mass(0.0) == pytest.approx(0.5)
    assert dist.p_above(0.0, boundary=">") == pytest.approx(0.5)
    assert dist.p_above(0.0, boundary=">=") == pytest.approx(1.0)  # 좌극한 경유
    assert dist.quantile(0.5) == 0.0   # inf{x: F(x)>=0.5}
    assert dist.quantile(0.5000001) == 1.0
    assert dist.quantile(0.0) == 0.0 and dist.quantile(1.0) == 2.0
    with pytest.raises(MtsDistributionError):
        dist.p_above(0.0, boundary="above")  # boundary 명시 강제


def test_t30_identity_pit_transform_preserves_distribution():
    """균일 PIT 이력의 V8 재보정은 레벨을 보존한다 — identity 앵커 (T30)."""
    from ai_fc.timeseries_v8.model import recalibration_levels

    levels = np.linspace(0.025, 0.975, 39)
    uniform_history = np.linspace(0.0, 1.0, 2001)
    for shrinkage in (0.0, 0.5, 1.0):
        out = recalibration_levels(uniform_history, target_levels=levels, shrinkage=shrinkage)
        assert np.allclose(out, levels, atol=1e-3)
    # s=1 은 구조적으로 항등 — 임의 이력에서도
    skewed = np.clip(np.linspace(0, 1, 500) ** 2, 0, 1)
    assert np.allclose(
        recalibration_levels(skewed, target_levels=levels, shrinkage=1.0), levels, atol=1e-12
    )


def test_t31_quantile_grid_refuses_cdf_and_crps():
    grid = QuantileGridForecast([0.1, 0.5, 0.9], [-1.0, 0.0, 1.0])
    assert grid.quantile(0.5) == 0.0
    with pytest.raises(UnsupportedCapability):
        grid.cdf(0.0)
    with pytest.raises(UnsupportedCapability):
        grid.crps(0.0)
    with pytest.raises(UnsupportedCapability):
        grid.quantile(0.25)  # 격자 밖 — 보간 정책 없음
    with pytest.raises(MtsDistributionError):
        QuantileGridForecast([0.1, 0.5, 0.9], [1.0, 0.0, -1.0])  # crossing 거부


def test_t32_mixture_cdf_differs_from_quantile_average():
    """두 점질량 분포의 반반 혼합: CDF 혼합 중앙값 ≠ 분위수 평균 (T32)."""
    a = WeightedEmpiricalDistribution([-10.0])
    b = WeightedEmpiricalDistribution([10.0])
    mixed = mixture_cdf([a, b], [0.5, 0.5])
    assert mixed.quantile(0.5) == -10.0  # 일반화 역함수: 질량 절반이 -10 에
    assert mixed.cdf(0.0) == pytest.approx(0.5)

    grid_a = QuantileGridForecast([0.5], [-10.0])
    grid_b = QuantileGridForecast([0.5], [10.0])
    averaged = quantile_average([grid_a, grid_b], [0.5, 0.5])
    assert averaged.quantile(0.5) == 0.0  # 분위수 평균 — 전혀 다른 객체
    with pytest.raises(MtsDistributionError):
        quantile_average([grid_a, QuantileGridForecast([0.4], [0.0])], [0.5, 0.5])


def test_randomized_pit_atoms():
    """원자 질량 위 randomized PIT — v 고정 stream (부록 A.6)."""
    dist = WeightedEmpiricalDistribution([0.0, 1.0], [0.5, 0.5])
    assert randomized_pit(dist, 0.0, v=0.0) == pytest.approx(0.0)
    assert randomized_pit(dist, 0.0, v=1.0) == pytest.approx(0.5)
    assert randomized_pit(dist, 0.5, v=0.3) == pytest.approx(0.5)  # 질량 없는 점
    with pytest.raises(MtsDistributionError):
        randomized_pit(dist, 0.0, v=1.5)


def test_weight_validation():
    with pytest.raises(MtsDistributionError):
        WeightedEmpiricalDistribution([0.0, 1.0], [0.6, 0.6])
    with pytest.raises(MtsDistributionError):
        WeightedEmpiricalDistribution([0.0, np.inf])
    with pytest.raises(MtsDistributionError):
        WeightedEmpiricalDistribution([0.0, 1.0], [-0.1, 1.1])
