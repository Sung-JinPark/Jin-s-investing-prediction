"""LPPL (Log-Periodic Power Law) 적합 — Sornette 버블 임계점 모델 (v3 §8.1).

ln(p(t)) = A + B·(tc−t)^β + C·(tc−t)^β·cos(ω·ln(tc−t) − φ)

비선형 파라미터(tc, β, ω, φ)는 differential_evolution으로 탐색하고,
선형 파라미터(A, B, C)는 각 후보에서 최소자승으로 풀어낸다 (표준 2단계 적합).
v3 절차대로 닷컴 M+0~40 백캘리브레이션으로 편향(실제 M+50 대비)을 함께 보고한다.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import differential_evolution


@dataclass
class LpplFit:
    tc: float          # 정점 시점 (M+ 단위)
    beta: float
    omega: float
    phi: float
    r2: float
    converged: bool


def _design(t: np.ndarray, tc: float, beta: float, omega: float, phi: float) -> np.ndarray:
    dt = np.maximum(tc - t, 1e-9)
    f = dt ** beta
    g = f * np.cos(omega * np.log(dt) - phi)
    return np.column_stack([np.ones_like(t), f, g])


def fit_lppl(closes: list[float], seed: int = 42) -> LpplFit:
    p = np.log(np.asarray(closes, dtype=float))
    t = np.arange(len(p), dtype=float)
    n = len(p)

    def sse(params: np.ndarray) -> float:
        tc, beta, omega, phi = params
        X = _design(t, tc, beta, omega, phi)
        coef, *_ = np.linalg.lstsq(X, p, rcond=None)
        resid = p - X @ coef
        return float(resid @ resid)

    bounds = [(n + 0.5, n + 36.0),   # tc: 미래 0.5~36개월
              (0.1, 0.9),            # β
              (4.0, 25.0),           # ω
              (0.0, 2 * np.pi)]      # φ
    result = differential_evolution(sse, bounds, seed=seed, maxiter=400,
                                    tol=1e-10, polish=True)
    tc, beta, omega, phi = result.x
    X = _design(t, tc, beta, omega, phi)
    coef, *_ = np.linalg.lstsq(X, p, rcond=None)
    pred = X @ coef
    ss_res = float(np.sum((p - pred) ** 2))
    ss_tot = float(np.sum((p - p.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return LpplFit(float(tc), float(beta), float(omega), float(phi), r2,
                   bool(result.success))


def backcalibrate_dotcom(dotcom_closes: list[float], fit_upto: int = 41,
                         actual_peak_m: int = 50) -> tuple[LpplFit, float]:
    """닷컴 M+0~(fit_upto-1)로 적합 → 예측 tc와 실제 정점(M+50)의 편향(개월)."""
    fit = fit_lppl(dotcom_closes[:fit_upto])
    bias = fit.tc - actual_peak_m  # 음수 = 모델이 일찍 예측
    return fit, float(bias)
