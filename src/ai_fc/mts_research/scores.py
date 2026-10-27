"""부록 A 채점기 — 발행된 분포 객체 자체를 채점한다.

- CRPS(A.2): 정렬 O(M log M) + 누적합. weighted empirical distribution 자체의
  점수이며, 잠재 연속 생성분포 점수의 무편향 추정이라는 별도 주장을 하지 않는다.
- iid fair-CRPS 보정은 조건이 확인된 경우에만 — deterministic grid·가중·의존 표본에
  자동 적용하지 않는다 (T35).
- WIS(A.3): 모델 간 α 격자·weight 고정 — 다른 격자의 WIS 를 같은 score ID 로
  보고하지 않는다 (T34).
- QLIKE(A.4), Energy/Variogram(A.5 — Euclidean 고정, scale/weight 는 개발 단계 고정).
- coverage 는 pointwise 와 simultaneous 를 별개 타입으로 둔다 (T37).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Mapping, Sequence

import numpy as np


class MtsScoreError(RuntimeError):
    """채점 계약 위반 — fail-closed."""


class GridMismatch(MtsScoreError):
    """등록된 분위수 격자와 다른 격자 (T34)."""


# ---------------------------------------------------------------------------
# A.1 Brier / log loss
# ---------------------------------------------------------------------------


def brier(p: float, y: int) -> float:
    if not 0.0 <= p <= 1.0:
        raise MtsScoreError(f"확률은 fraction [0,1]: {p}")
    if y not in (0, 1):
        raise MtsScoreError(f"사건 라벨은 0/1: {y}")
    return (p - y) ** 2


def log_loss(p: float, y: int, *, clip_epsilon: float | None = None) -> float:
    """log loss — clipping 은 epsilon·적용 위치를 명시하고 원확률은 보존한다 (A.1)."""
    if not 0.0 <= p <= 1.0:
        raise MtsScoreError(f"확률은 fraction [0,1]: {p}")
    if y not in (0, 1):
        raise MtsScoreError(f"사건 라벨은 0/1: {y}")
    effective = p
    if clip_epsilon is not None:
        if not 0.0 < clip_epsilon < 0.5:
            raise MtsScoreError("clip epsilon 은 (0, 0.5)")
        effective = min(max(p, clip_epsilon), 1.0 - clip_epsilon)
    if effective in (0.0, 1.0):
        return 0.0 if effective == y else math.inf
    return -(y * math.log(effective) + (1 - y) * math.log(1.0 - effective))


def brier_skill_denominator_guard(baseline_total: float) -> None:
    """BSS 분모 0 이면 skill 을 정의하지 않는다 (A.1) — NOT_IDENTIFIABLE."""
    if baseline_total <= 0.0:
        raise MtsScoreError("baseline Brier 합이 0 — skill NOT_IDENTIFIABLE (A.1)")


# ---------------------------------------------------------------------------
# A.2 weighted empirical CRPS — O(M log M)
# ---------------------------------------------------------------------------


def crps_weighted_empirical(
    atoms: Sequence[float], weights: Sequence[float] | None, y: float
) -> float:
    values = np.asarray(atoms, dtype=float)
    if values.ndim != 1 or values.size == 0 or not np.isfinite(values).all():
        raise MtsScoreError("지지점은 유한한 비어 있지 않은 1차원")
    if not math.isfinite(y):
        raise MtsScoreError("실현값이 유한하지 않다")
    if weights is None:
        w = np.full(values.size, 1.0 / values.size)
    else:
        w = np.asarray(weights, dtype=float)
        if w.shape != values.shape or (w < 0).any() or not np.isfinite(w).all():
            raise MtsScoreError("weight 는 비음수 유한, 모양 일치")
        total = float(w.sum())
        if total <= 0 or abs(total - 1.0) > 1e-9:
            raise MtsScoreError(f"weight 합 1 위반: {total}")
    order = np.argsort(values, kind="stable")
    x = values[order]
    ws = w[order]
    term1 = float(np.sum(ws * np.abs(x - y)))
    cumulative_w = np.concatenate([[0.0], np.cumsum(ws)[:-1]])   # W_{m-1}
    cumulative_s = np.concatenate([[0.0], np.cumsum(ws * x)[:-1]])  # S_{m-1}
    pair_half = float(np.sum(ws * (x * cumulative_w - cumulative_s)))
    return term1 - pair_half


@dataclass(frozen=True)
class SampleMeta:
    """fair-CRPS 보정 적용 가능성 판정 입력 (T35)."""

    iid: bool
    weighted: bool
    deterministic_grid: bool


def fair_adjustment_allowed(meta: SampleMeta) -> None:
    """iid 비가중 무작위 표본이 아닌데 fair 보정을 요청하면 거부한다 (T35, A.2)."""
    if not meta.iid:
        raise MtsScoreError("의존/재정렬 표본에 iid fair-CRPS 보정 자동 적용 금지 (T35)")
    if meta.weighted:
        raise MtsScoreError("가중 표본에 iid fair-CRPS 보정 자동 적용 금지 (T35)")
    if meta.deterministic_grid:
        raise MtsScoreError("deterministic quantile grid 에 fair-CRPS 보정 금지 (T35)")


# ---------------------------------------------------------------------------
# A.3 WIS
# ---------------------------------------------------------------------------


def interval_score(lower: float, upper: float, y: float, *, alpha: float) -> float:
    if not 0.0 < alpha < 1.0:
        raise MtsScoreError("alpha 는 (0,1)")
    if lower > upper:
        raise MtsScoreError("구간 역전")
    score = upper - lower
    if y < lower:
        score += (2.0 / alpha) * (lower - y)
    elif y > upper:
        score += (2.0 / alpha) * (y - upper)
    return score


def wis(
    quantiles: Mapping[float, float],
    y: float,
    *,
    alpha_grid: Sequence[float],
) -> float:
    """일반 WIS (A.3) — 등록된 α 격자와 입력 격자가 정확히 맞아야 한다 (T34).

    요구 격자: 중앙값 0.5 + 각 α 의 (α/2, 1−α/2).
    """
    required: set[float] = {0.5}
    for alpha in alpha_grid:
        if not 0.0 < alpha < 1.0:
            raise MtsScoreError("alpha 는 (0,1)")
        required.add(round(alpha / 2.0, 12))
        required.add(round(1.0 - alpha / 2.0, 12))
    provided = {round(float(q), 12) for q in quantiles}
    if provided != required:
        raise GridMismatch(
            f"분위수 격자 불일치 — 비교 전 공통 격자 요구 (T34): 필요 {sorted(required)}, 제공 {sorted(provided)}"
        )
    median = float(quantiles[0.5]) if 0.5 in quantiles else float(
        next(v for q, v in quantiles.items() if round(float(q), 12) == 0.5)
    )
    total = 0.5 * abs(y - median)
    for alpha in alpha_grid:
        lower = next(v for q, v in quantiles.items() if round(float(q), 12) == round(alpha / 2.0, 12))
        upper = next(
            v for q, v in quantiles.items() if round(float(q), 12) == round(1.0 - alpha / 2.0, 12)
        )
        total += (alpha / 2.0) * interval_score(float(lower), float(upper), y, alpha=alpha)
    return total / (len(alpha_grid) + 0.5)


# ---------------------------------------------------------------------------
# A.4 QLIKE
# ---------------------------------------------------------------------------


def qlike(variance_forecast: float, realized_proxy: float) -> float:
    if not variance_forecast > 0.0 or not math.isfinite(variance_forecast):
        raise MtsScoreError("분산 예측은 양의 유한값 (A.4)")
    if realized_proxy < 0.0 or not math.isfinite(realized_proxy):
        raise MtsScoreError("실현 proxy 는 비음수 유한값")
    return math.log(variance_forecast) + realized_proxy / variance_forecast


# ---------------------------------------------------------------------------
# A.5 Energy score / Variogram score
# ---------------------------------------------------------------------------


def _weights_or_uniform(count: int, weights: Sequence[float] | None) -> np.ndarray:
    if weights is None:
        return np.full(count, 1.0 / count)
    w = np.asarray(weights, dtype=float)
    if w.shape != (count,) or (w < 0).any() or abs(float(w.sum()) - 1.0) > 1e-9:
        raise MtsScoreError("weight 는 비음수·합 1·모양 일치")
    return w


def energy_score(
    samples: np.ndarray, weights: Sequence[float] | None, y: np.ndarray, *, chunk: int = 512
) -> float:
    """weighted empirical Energy score (A.5) — 거리는 Euclidean 으로 고정."""
    x = np.asarray(samples, dtype=float)
    target = np.asarray(y, dtype=float)
    if x.ndim != 2 or target.ndim != 1 or x.shape[1] != target.shape[0]:
        raise MtsScoreError("samples (M,d), y (d,) 모양 필요")
    if not np.isfinite(x).all() or not np.isfinite(target).all():
        raise MtsScoreError("NaN/inf 금지")
    w = _weights_or_uniform(x.shape[0], weights)
    term1 = float(np.sum(w * np.linalg.norm(x - target[None, :], axis=1)))
    term2 = 0.0
    m = x.shape[0]
    for start in range(0, m, chunk):
        block = x[start : start + chunk]
        wb = w[start : start + chunk]
        distances = np.linalg.norm(block[:, None, :] - x[None, :, :], axis=2)
        term2 += float(wb @ distances @ w)
    return term1 - 0.5 * term2


def variogram_score(
    samples: np.ndarray,
    weights: Sequence[float] | None,
    y: np.ndarray,
    *,
    p: float = 0.5,
    pair_weights: np.ndarray | None = None,
) -> float:
    """Variogram score (A.5) — p>0, 비음수 a_ij 를 명시한다."""
    if not p > 0:
        raise MtsScoreError("p > 0 (A.5)")
    x = np.asarray(samples, dtype=float)
    target = np.asarray(y, dtype=float)
    if x.ndim != 2 or target.ndim != 1 or x.shape[1] != target.shape[0]:
        raise MtsScoreError("samples (M,d), y (d,) 모양 필요")
    d = target.shape[0]
    w = _weights_or_uniform(x.shape[0], weights)
    if pair_weights is None:
        a = np.ones((d, d))
    else:
        a = np.asarray(pair_weights, dtype=float)
        if a.shape != (d, d) or (a < 0).any():
            raise MtsScoreError("pair weight 는 (d,d) 비음수")
    total = 0.0
    for i in range(d):
        for j in range(i + 1, d):
            observed = abs(target[i] - target[j]) ** p
            expected = float(np.sum(w * np.abs(x[:, i] - x[:, j]) ** p))
            total += a[i, j] * (observed - expected) ** 2
    return total


# ---------------------------------------------------------------------------
# T37 — coverage 의 종류를 타입으로 구분
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CoverageReport:
    kind: Literal["pointwise", "simultaneous"]
    hit_rate: float
    n: int


def pointwise_coverage(y_paths: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> CoverageReport:
    """각 날짜의 구간 적중 비율 — 경로 전체 동시 coverage 가 아니다 (T37)."""
    y = np.asarray(y_paths, dtype=float)
    hits = (y >= np.asarray(lower)) & (y <= np.asarray(upper))
    return CoverageReport(kind="pointwise", hit_rate=float(hits.mean()), n=int(hits.size))


def simultaneous_coverage(y_paths: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> CoverageReport:
    """경로 전체가 동시에 띠 안에 있는 비율 (T37)."""
    y = np.asarray(y_paths, dtype=float)
    if y.ndim != 2:
        raise MtsScoreError("simultaneous coverage 는 (paths, steps) 입력")
    inside = ((y >= np.asarray(lower)[None, :]) & (y <= np.asarray(upper)[None, :])).all(axis=1)
    return CoverageReport(kind="simultaneous", hit_rate=float(inside.mean()), n=int(inside.size))


def assert_simultaneous(report: CoverageReport) -> CoverageReport:
    """pointwise 결과를 simultaneous 로 표시하는 것을 차단한다 (T37)."""
    if report.kind != "simultaneous":
        raise MtsScoreError("pointwise coverage 를 simultaneous 로 표시할 수 없다 (T37)")
    return report
