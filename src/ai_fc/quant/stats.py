"""통계 도구 — Pearson/Spearman/Sharpe/Hurst/DTW/Power law (v3 §6~8)."""

from __future__ import annotations

import numpy as np
from scipy import stats as sps


def overlap_series(a: dict[int, float], b: dict[int, float]) -> tuple[np.ndarray, np.ndarray]:
    keys = sorted(set(a) & set(b))
    return (np.array([a[k] for k in keys]), np.array([b[k] for k in keys]))


def pearson(a: dict[int, float], b: dict[int, float]) -> tuple[float, float]:
    x, y = overlap_series(a, b)
    r, p = sps.pearsonr(x, y)
    return float(r), float(p)


def spearman(a: dict[int, float], b: dict[int, float]) -> tuple[float, float]:
    x, y = overlap_series(a, b)
    rho, p = sps.spearmanr(x, y)
    return float(rho), float(p)


def sharpe_annualized(monthly_closes: list[float]) -> tuple[float, float, float]:
    """(연환산 수익률, 연환산 변동성, Sharpe). R_f=0 가정 (v3 §6.3)."""
    arr = np.asarray(monthly_closes, dtype=float)
    rets = np.diff(np.log(arr))
    mu_a = float(np.mean(rets) * 12)
    sigma_a = float(np.std(rets, ddof=1) * np.sqrt(12))
    return np.expm1(mu_a), sigma_a, (mu_a / sigma_a if sigma_a > 0 else float("nan"))


def hurst_rs(closes: list[float]) -> float:
    """R/S 방법 Hurst 지수 (로그수익률 기준)."""
    rets = np.diff(np.log(np.asarray(closes, dtype=float)))
    n = len(rets)
    sizes = [s for s in (8, 12, 16, 24, 32, 48, 64) if s <= n // 2]
    if len(sizes) < 3:
        raise ValueError("시계열이 너무 짧음")
    log_n, log_rs = [], []
    for s in sizes:
        rs_vals = []
        for start in range(0, n - s + 1, s):
            chunk = rets[start:start + s]
            dev = np.cumsum(chunk - chunk.mean())
            r = dev.max() - dev.min()
            sd = chunk.std(ddof=1)
            if sd > 0:
                rs_vals.append(r / sd)
        if rs_vals:
            log_n.append(np.log(s))
            log_rs.append(np.log(np.mean(rs_vals)))
    slope, *_ = sps.linregress(log_n, log_rs)
    return float(slope)


def dtw_distance(a: np.ndarray, b: np.ndarray) -> float:
    """O(n²) DTW (z-score 정규화)."""
    x = (a - a.mean()) / a.std(ddof=1)
    y = (b - b.mean()) / b.std(ddof=1)
    n, m = len(x), len(y)
    D = np.full((n + 1, m + 1), np.inf)
    D[0, 0] = 0.0
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = abs(x[i - 1] - y[j - 1])
            D[i, j] = cost + min(D[i - 1, j], D[i, j - 1], D[i - 1, j - 1])
    return float(D[n, m] / (n + m))


def best_shift(ai: dict[int, float], dotcom: dict[int, float],
               max_shift: int = 12) -> tuple[int, float]:
    """유클리드 거리를 최소화하는 시프트 (양수 = AI가 닷컴을 k개월 앞당김)."""
    best_k, best_d = 0, float("inf")
    for k in range(-max_shift, max_shift + 1):
        shifted = {m + k: v for m, v in ai.items()}
        x, y = overlap_series(shifted, dotcom)
        if len(x) < 24:
            continue
        xz = (x - x.mean()) / x.std(ddof=1)
        yz = (y - y.mean()) / y.std(ddof=1)
        d = float(np.sqrt(np.mean((xz - yz) ** 2)))
        if d < best_d:
            best_k, best_d = k, d
    return best_k, best_d


def power_law_beta(closes: list[float]) -> float:
    """log(P) = α + β·log(t) 적합 기울기 (v3 §8.2)."""
    p = np.asarray(closes, dtype=float)
    t = np.arange(1, len(p) + 1, dtype=float)
    slope, *_ = sps.linregress(np.log(t), np.log(p))
    return float(slope)
