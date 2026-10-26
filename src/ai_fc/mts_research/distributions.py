"""§9.1 단일 확률 객체 — capability 가 확인된 연산만 노출한다.

- 분위수·상승확률·구간은 같은 분포 객체에서 파생한다 (T28).
- ``>=`` 사건에는 좌극한 CDF 가 필요하다 — 경험분포의 원자 질량과 boundary 를
  명시적으로 다룬다 (T29).
- 분위수 격자만 가진 후보에 tail 가정을 숨겨 full CDF 를 만들어 주지 않는다 (T31).
- CDF 혼합과 분위수 평균은 다른 연산이다 (T32).
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

from ..timeseries_v8.contracts import canonical_hash


class MtsDistributionError(RuntimeError):
    """확률 객체 불변조건 위반 — fail-closed."""


class UnsupportedCapability(MtsDistributionError):
    """해당 객체가 지원하지 않는 연산 요청 — capability 가장 금지 (T31)."""


class WeightedEmpiricalDistribution:
    """유한 지지점 + 비음수 weight 의 경험분포 (§9.1 MarginalDistribution)."""

    capabilities = ("cdf", "cdf_left", "quantile", "p_above", "crps")

    def __init__(self, atoms: Sequence[float], weights: Sequence[float] | None = None):
        values = np.asarray(atoms, dtype=float)
        if values.ndim != 1 or values.size == 0:
            raise MtsDistributionError("지지점은 비어 있지 않은 1차원이어야 한다")
        if not np.isfinite(values).all():
            raise MtsDistributionError("지지점에 NaN/inf 금지")
        if weights is None:
            w = np.full(values.size, 1.0 / values.size)
        else:
            w = np.asarray(weights, dtype=float)
            if w.shape != values.shape:
                raise MtsDistributionError("weight 모양 불일치")
            if not np.isfinite(w).all() or (w < 0).any():
                raise MtsDistributionError("weight 는 비음수 유한값")
            total = float(w.sum())
            if total <= 0 or abs(total - 1.0) > 1e-9:
                raise MtsDistributionError(f"weight 합이 1 이 아니다: {total}")
        order = np.argsort(values, kind="stable")
        self.atoms = values[order]
        self.weights = w[order]
        self._cum = np.cumsum(self.weights)

    def distribution_id(self) -> str:
        return "dist-" + canonical_hash({
            "atoms": [float(v) for v in self.atoms],
            "weights": [float(v) for v in self.weights],
        })[:24]

    def cdf(self, x: float) -> float:
        """F(x) = P(X <= x) — 우연속."""
        index = np.searchsorted(self.atoms, x, side="right")
        return float(self._cum[index - 1]) if index > 0 else 0.0

    def cdf_left(self, x: float) -> float:
        """F(x-) = P(X < x) — `>=` 사건의 좌극한 (T29)."""
        index = np.searchsorted(self.atoms, x, side="left")
        return float(self._cum[index - 1]) if index > 0 else 0.0

    def point_mass(self, x: float) -> float:
        return self.cdf(x) - self.cdf_left(x)

    def quantile(self, q: float) -> float:
        """일반화 역함수 Q(q) = inf{x : F(x) >= q} (§9.1)."""
        if not 0.0 <= q <= 1.0:
            raise MtsDistributionError("q 는 [0,1]")
        if q == 0.0:
            return float(self.atoms[0])
        index = int(np.searchsorted(self._cum, q - 1e-15, side="left"))
        index = min(index, len(self.atoms) - 1)
        return float(self.atoms[index])

    def p_above(self, threshold: float, *, boundary: str = ">") -> float:
        """P(X > t) 또는 P(X >= t) — boundary 명시 필수 (T29)."""
        if boundary == ">":
            return 1.0 - self.cdf(threshold)
        if boundary == ">=":
            return 1.0 - self.cdf_left(threshold)
        raise MtsDistributionError(f"boundary 는 '>' 또는 '>=': {boundary}")

    def interval(self, lower_q: float, upper_q: float) -> tuple[float, float]:
        if not lower_q < upper_q:
            raise MtsDistributionError("lower_q < upper_q")
        return (self.quantile(lower_q), self.quantile(upper_q))


class QuantileGridForecast:
    """분위수 격자만 제공하는 후보 — tail 을 모른다 (§9.1, T31).

    등록된 tail policy 없이는 cdf/CRPS capability 를 주장하지 않는다.
    """

    capabilities = ("quantile_grid",)

    def __init__(self, levels: Sequence[float], values: Sequence[float]):
        lv = np.asarray(levels, dtype=float)
        xs = np.asarray(values, dtype=float)
        if lv.shape != xs.shape or lv.ndim != 1 or lv.size == 0:
            raise MtsDistributionError("levels/values 모양 불일치")
        if (np.diff(lv) <= 0).any() or (lv <= 0).any() or (lv >= 1).any():
            raise MtsDistributionError("levels 는 (0,1) 의 순증가")
        if (np.diff(xs) < 0).any():
            raise MtsDistributionError("quantile crossing — 값이 비감소여야 한다")
        self.levels = lv
        self.values = xs

    def quantile(self, q: float) -> float:
        matches = np.nonzero(np.isclose(self.levels, q, atol=1e-12))[0]
        if matches.size == 0:
            raise UnsupportedCapability(
                f"격자에 없는 분위수 {q} — 격자 사이 보간 정책은 계약에 없다 (T31)"
            )
        return float(self.values[matches[0]])

    def cdf(self, x: float) -> float:
        raise UnsupportedCapability("quantile-grid 출력에는 full CDF capability 가 없다 (T31)")

    def crps(self, y: float) -> float:
        raise UnsupportedCapability(
            "미정 꼬리를 가진 quantile grid 의 CRPS 를 full-CDF CRPS 로 부를 수 없다 (T31) — WIS 를 쓴다"
        )


def mixture_cdf(
    components: Sequence[WeightedEmpiricalDistribution], weights: Sequence[float]
) -> WeightedEmpiricalDistribution:
    """w·F1 + (1-w)·F2 — CDF 혼합 (T32). 분위수 평균이 아니다."""
    w = np.asarray(weights, dtype=float)
    if len(components) != len(w) or len(components) == 0:
        raise MtsDistributionError("성분/가중 불일치")
    if (w < 0).any() or abs(float(w.sum()) - 1.0) > 1e-9:
        raise MtsDistributionError("혼합 가중은 비음수·합 1")
    atoms = np.concatenate([c.atoms for c in components])
    mixed = np.concatenate([c.weights * wi for c, wi in zip(components, w)])
    return WeightedEmpiricalDistribution(atoms, mixed)


def quantile_average(
    grids: Sequence[QuantileGridForecast], weights: Sequence[float]
) -> QuantileGridForecast:
    """w·Q1 + (1-w)·Q2 — 분위수 평균 (별개 연산, T32)."""
    w = np.asarray(weights, dtype=float)
    if len(grids) != len(w) or len(grids) == 0:
        raise MtsDistributionError("성분/가중 불일치")
    base = grids[0].levels
    for grid in grids[1:]:
        if not np.allclose(grid.levels, base, atol=1e-12):
            raise MtsDistributionError("분위수 평균은 동일 격자에서만 (T34 연계)")
    values = np.zeros_like(base)
    for grid, wi in zip(grids, w):
        values = values + wi * grid.values
    return QuantileGridForecast(base, values)


def randomized_pit(
    distribution: WeightedEmpiricalDistribution, y: float, *, v: float
) -> float:
    """원자 질량이 있는 분포의 randomized PIT (부록 A.6).

    u = F(y-) + v·[F(y) - F(y-)], v ~ U(0,1) 은 고정 난수 stream 에서 온다.
    """
    if not 0.0 <= v <= 1.0:
        raise MtsDistributionError("v 는 [0,1] uniform draw")
    left = distribution.cdf_left(y)
    return left + v * (distribution.cdf(y) - left)
