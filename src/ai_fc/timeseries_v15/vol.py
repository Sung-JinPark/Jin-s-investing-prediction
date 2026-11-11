"""V15 변동성 팔(A1 fresh_vol · A2 고정 ½·½ λ 혼합) — kernel, 포크 아님(신규).

봉인 V2 `_ewma_scale`(timeseries_v2/model.py)과 같은 lfilter 재귀로 분산을 만든다. A0("v8")
경로는 이 파일을 거치지 않고 봉인 `_ewma_scale` 을 직접 부른다(포크 model.py — 테스트 F5).
미지 mode 는 ValueError 로 fail-closed (None 반환 금지). 참고 의견, 매매 신호 아님.
"""

from __future__ import annotations

import numpy as np

from ai_fc.timeseries_v8.model import _ewma_variance_series

from .arms import MIX_DECAYS, MIX_WEIGHTS


def ewma_variance_matrix(residuals: np.ndarray, decay: float) -> np.ndarray:
    """봉인 `_ewma_scale` 내부의 variance 행렬을 그대로 반환한다(σ²_{t|t−1})."""
    from scipy.signal import lfilter

    squared = np.square(residuals)
    variance = np.empty_like(squared, dtype=float)
    variance[0] = np.maximum(squared[0], 1e-16)
    if len(squared) > 1:
        initial = np.asarray(decay * variance[0], dtype=float).reshape((1, *squared.shape[1:]))
        filtered, _ = lfilter([1.0 - decay], [1.0, -decay], squared[:-1], axis=0, zi=initial)
        variance[1:] = filtered
    return variance


def ewma_scale_arm(residuals: np.ndarray, decay: float, *, mode: str) -> np.ndarray:
    """팔별 innovation scale = sqrt(최신 분산) / sqrt(역사 분산)."""
    sq = np.square(residuals)
    if mode == "fresh":
        # A1: σ²_{T+1|T} = λ σ²_{T|T−1} + (1−λ) e_T² — 원점 당일 잔차를 포함한다.
        var = ewma_variance_matrix(residuals, decay)
        latest_var = decay * var[-1] + (1.0 - decay) * sq[-1]
    elif mode == "lambda_mix":
        # A2: σ² = ½σ²_.94 + ½σ²_.97 (고정, 학습 아님) — 선택된 λ 는 무시한다.
        # 1세션 지연은 A0 그대로 둔다(단일 축).
        var = (MIX_WEIGHTS[0] * ewma_variance_matrix(residuals, MIX_DECAYS[0])
               + MIX_WEIGHTS[1] * ewma_variance_matrix(residuals, MIX_DECAYS[1]))
        latest_var = var[-1]
    else:
        raise ValueError(f"unknown vol_mode {mode!r}")
    return np.sqrt(np.maximum(latest_var, 1e-16)) / np.sqrt(np.maximum(var, 1e-16))


def ewma_variance_series_arm(returns: np.ndarray, decay: float, *, mode: str) -> np.ndarray:
    """FHS 1차원 분산 계열. "v8"·"fresh" 는 봉인 재귀 그대로, "lambda_mix" 는 ½(v.94+v.97)."""
    if mode in ("v8", "fresh"):
        return _ewma_variance_series(returns, decay)
    if mode == "lambda_mix":
        return (MIX_WEIGHTS[0] * _ewma_variance_series(returns, MIX_DECAYS[0])
                + MIX_WEIGHTS[1] * _ewma_variance_series(returns, MIX_DECAYS[1]))
    raise ValueError(f"unknown vol_mode {mode!r}")
