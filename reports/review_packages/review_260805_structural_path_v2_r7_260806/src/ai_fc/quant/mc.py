"""GBM Monte Carlo (v3 §8.3). 정규분포 가정 — fat tail 미포착 한계는 산출물에 명시."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class McResult:
    mu_monthly: float
    sigma_monthly: float
    mean_pct: float      # horizon 후 평균 변화율
    median_pct: float
    ci95_lo_pct: float
    ci95_hi_pct: float
    prob_up: float


def gbm_simulate(closes: list[float], lookback: int = 12, horizon: int = 6,
                 n: int = 10000, seed: int = 42) -> McResult:
    arr = np.asarray(closes, dtype=float)
    rets = np.diff(np.log(arr))[-lookback:]
    mu, sigma = float(rets.mean()), float(rets.std(ddof=1))
    rng = np.random.default_rng(seed)
    shocks = rng.standard_normal((n, horizon))
    paths = np.exp(np.cumsum(mu - sigma ** 2 / 2 + sigma * shocks, axis=1))
    final = paths[:, -1]
    return McResult(
        mu_monthly=mu, sigma_monthly=sigma,
        mean_pct=float(final.mean() - 1),
        median_pct=float(np.median(final) - 1),
        ci95_lo_pct=float(np.percentile(final, 2.5) - 1),
        ci95_hi_pct=float(np.percentile(final, 97.5) - 1),
        prob_up=float((final > 1).mean()),
    )


def gbm_paths(closes: list[float], lookback: int = 52, horizon: int = 25,
              n: int = 10000, seed: int = 42) -> np.ndarray:
    """절대가격 경로 (n, horizon) — 배리어(경로 터치) 확률용. 기본 주간 파라미터.

    gbm_simulate와 같은 GBM이지만 종점이 아니라 경로 전체를 반환한다.
    """
    arr = np.asarray(closes, dtype=float)
    rets = np.diff(np.log(arr))[-lookback:]
    mu, sigma = float(rets.mean()), float(rets.std(ddof=1))
    rng = np.random.default_rng(seed)
    shocks = rng.standard_normal((n, horizon))
    ratio = np.exp(np.cumsum(mu - sigma ** 2 / 2 + sigma * shocks, axis=1))
    return float(arr[-1]) * ratio


def barrier_prob(paths: np.ndarray, threshold: float, direction: str,
                 step_range: tuple[int, int] | None = None) -> float:
    """경로 중 임계값을 1회라도 터치할 확률 (절대가격 경로 입력).

    direction: 'above' | 'below'. step_range: (시작, 끝) 스텝 인덱스 폐구간 —
    부분 판정 윈도우(예: F2의 8~10월)용, None이면 전체 지평.
    Chronos-T5 샘플 경로에도 그대로 재사용 가능 (모델 불문 순수 함수).
    """
    if step_range is not None:
        s0 = max(0, step_range[0])
        s1 = min(paths.shape[1] - 1, step_range[1])
        if s0 > s1:
            return 0.0
        window = paths[:, s0:s1 + 1]
    else:
        window = paths
    if direction == "above":
        return float((window >= threshold).any(axis=1).mean())
    return float((window <= threshold).any(axis=1).mean())
