"""W1·W3 공통 상태 시계열 — 내생 변동성 상태 (trailing-only, PIT 안전).

primary  = v_now / v̄ : EWMA(λ=.97) 분산 ÷ 직전 2520세션 제곱수익 평균
sensitivity = RV63 / RV504 : 63세션 제곱평균 ÷ 504세션 제곱평균
기준선 창이 미완성인 초기 구간(1996~2004류)은 s≡1 — 계약이 선언한 중립 워밍업이며
침묵 정규화가 아니다. 모든 값은 자기 시점까지의 데이터만 쓴다(trailing).
"""

from __future__ import annotations

import numpy as np

from .model_fork import _ewma_variance_series

PRIMARY_LAMBDA = 0.97
BASELINE_SESSIONS = 2520
RV_SHORT = 63
RV_LONG = 504


def _trailing_mean_square(returns: np.ndarray, window: int) -> tuple[np.ndarray, np.ndarray]:
    """Trailing mean of squared returns and a completeness mask."""
    squared = np.square(np.asarray(returns, dtype=float))
    cumulative = np.concatenate(([0.0], np.cumsum(squared)))
    index = np.arange(1, len(squared) + 1)
    start = np.maximum(0, index - window)
    sums = cumulative[index] - cumulative[start]
    counts = index - start
    complete = counts >= window
    means = sums / np.maximum(counts, 1)
    return means, complete


def build_state_series(returns: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(primary, sensitivity) state arrays aligned to the return index."""
    returns = np.asarray(returns, dtype=float)
    if returns.ndim != 1 or len(returns) < RV_LONG + 1:
        raise ValueError("state series requires a one-dimensional return history")
    v_now = _ewma_variance_series(returns, PRIMARY_LAMBDA)
    v_bar, baseline_complete = _trailing_mean_square(returns, BASELINE_SESSIONS)
    primary = np.ones(len(returns), dtype=float)
    valid = baseline_complete & (v_bar > 1e-16)
    primary[valid] = v_now[valid] / v_bar[valid]

    rv_short, short_complete = _trailing_mean_square(returns, RV_SHORT)
    rv_long, long_complete = _trailing_mean_square(returns, RV_LONG)
    sensitivity = np.ones(len(returns), dtype=float)
    valid_alt = short_complete & long_complete & (rv_long > 1e-16)
    sensitivity[valid_alt] = rv_short[valid_alt] / rv_long[valid_alt]
    return primary, sensitivity
