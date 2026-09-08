"""V13-VOL 수치 계층 — numpy 만. tools/v13_vol_run.py 의 수식을 1:1 로 재현한다 (패리티 테스트 대상).

- build_panel  : VIX∩NASDAQCOM 일간 패널, rv21 = log(NASDAQCOM).diff().rolling(21).std(ddof=1)·sqrt(252) (pandas 동일 — 앞 21행 NaN)
- ewma         : 시드 x[0], 비유한 carry-forward. 라이브에서는 전체 이력에 연속 실행한다 (재시작 금지)
- logit_fit    : zscore(ddof=0, sd<1e-9→1.0) + 절편, Newton 200회(l2=1e-3), clip [1e-6, 1−1e-6]
- labels_*     : vix >= K(strict forward window) · rv > theta(비유한만)
- delta_method_se / block_bootstrap_cov : 80% 대역 = 계수 불확실성(델타법) — 보정 대역이 아니다
- pav / pav_apply : h63 파생층 isotonic step map
"""

from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np

from .contracts import BLOCK_LENGTH, BOOTSTRAP_REPLICATES, EWMA_ALPHA

PROB_CLIP = (1e-6, 1 - 1e-6)


# ── 패널 ─────────────────────────────────────────────────────────────────────
def _series(observations: Iterable[Any], series_id: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for obs in observations:
        row = obs.model_dump(mode="json") if hasattr(obs, "model_dump") else obs
        if row["series_id"] == series_id:
            out[str(row["observation_time"])[:10]] = float(row["value"])
    return out


def rolling_std_ddof1(x: np.ndarray, window: int) -> np.ndarray:
    """pandas Series.rolling(window).std() 재현 — 창에 NaN 이 있으면 NaN, ddof=1."""
    n = len(x)
    out = np.full(n, np.nan)
    for i in range(window - 1, n):
        seg = x[i - window + 1:i + 1]
        if np.isfinite(seg).all():
            out[i] = float(np.std(seg, ddof=1))
    return out


def build_panel(observations: Iterable[Any], *, start: str, end: str | None = None) -> dict[str, np.ndarray]:
    """관측 → {'dates','vix','ndx','rv21'}. 날짜는 VIX·NASDAQCOM 교집합, [start, end] 절단(문자열 비교)."""
    observations = list(observations)
    vix = _series(observations, "VIX")
    ndx = _series(observations, "NASDAQCOM")
    dates = sorted(d for d in vix if d in ndx and d >= start and (end is None or d <= end))
    if not dates:
        return {"dates": np.array([], dtype=object), "vix": np.array([]), "ndx": np.array([]), "rv21": np.array([])}
    v = np.array([vix[d] for d in dates], float)
    q = np.array([ndx[d] for d in dates], float)
    r = np.concatenate([[np.nan], np.diff(np.log(q))])
    rv21 = rolling_std_ddof1(r, 21) * math.sqrt(252)
    return {"dates": np.array(dates, dtype=object), "vix": v, "ndx": q, "rv21": rv21}


# ── 피처 ─────────────────────────────────────────────────────────────────────
def ewma(x: np.ndarray, alpha: float = EWMA_ALPHA) -> np.ndarray:
    out = np.empty(len(x))
    m = x[0] if len(x) and np.isfinite(x[0]) else 0.0
    for i, v in enumerate(x):
        if np.isfinite(v):
            m = alpha * v + (1 - alpha) * m
        out[i] = m
    return out


def fill_rv_nan(rv: np.ndarray, median: float) -> np.ndarray:
    """동결 상수(설계창 중앙값)로 NaN 채움 — 라이브에서 재계산하지 않는다."""
    return np.where(np.isfinite(rv), rv, float(median))


def feature_matrix(model: str, level: np.ndarray, smooth: np.ndarray | None) -> np.ndarray:
    """ewma_logit=[x_t, EWMA21(x_t)] · persistence_pb=[x_t]."""
    if model == "ewma_logit":
        if smooth is None:
            raise ValueError("ewma_logit needs the EWMA column")
        return np.column_stack([level, smooth])
    if model == "persistence_pb":
        return np.asarray(level, float).reshape(-1, 1)
    raise ValueError(f"unknown model {model!r}")


def feature_names(model: str, target: str) -> list[str]:
    base = "vix_close" if target == "vix_touch" else "rv21_ann"
    if model == "ewma_logit":
        return [base, f"{base}_ewma21"]
    if model == "persistence_pb":
        return [base]
    raise ValueError(f"unknown model {model!r}")


# ── 라벨 ─────────────────────────────────────────────────────────────────────
def labels_vix(vix: np.ndarray, K: float, h: int) -> np.ndarray:
    n = len(vix); y = np.full(n, np.nan)
    for i in range(n - h):
        y[i] = 1.0 if (vix[i + 1:i + 1 + h] >= K).any() else 0.0
    return y


def labels_rv(rv: np.ndarray, theta: float, h: int) -> np.ndarray:
    n = len(rv); y = np.full(n, np.nan)
    for i in range(n - h):
        w = rv[i + 1:i + 1 + h]
        if np.isfinite(w).any():
            y[i] = 1.0 if (w[np.isfinite(w)] > theta).any() else 0.0
    return y


# ── 로짓 ─────────────────────────────────────────────────────────────────────
def standardize_params(X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mu = X.mean(0); sd = X.std(0).copy(); sd[sd < 1e-9] = 1.0
    return mu, sd


def _design(X: np.ndarray, mu: np.ndarray, sd: np.ndarray) -> np.ndarray:
    return np.column_stack([np.ones(len(X)), (X - mu) / sd])


def logit_fit(X: np.ndarray, y: np.ndarray, *, iters: int = 200, l2: float = 1e-3,
              tol: float | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """tools/v13_vol_run._logit_fit 동일 (tol=None → 정확히 iters 회). tol 지정 시 조기 수렴 정지(부트스트랩 전용)."""
    mu, sd = standardize_params(X)
    Xs = _design(X, mu, sd)
    beta = np.zeros(Xs.shape[1])
    n = len(y)
    for _ in range(iters):
        p = 1 / (1 + np.exp(-Xs @ beta)); p = np.clip(p, *PROB_CLIP)
        g = Xs.T @ (p - y) / n + l2 * beta
        W = p * (1 - p)
        H = (Xs * W[:, None]).T @ Xs / n + l2 * np.eye(Xs.shape[1])
        step = np.linalg.solve(H, g)
        beta = beta - step
        if tol is not None and float(np.abs(step).max()) < tol:
            break
    return beta, mu, sd


def logit_predict(beta: np.ndarray, mu: np.ndarray, sd: np.ndarray, X: np.ndarray) -> np.ndarray:
    return np.clip(1 / (1 + np.exp(-_design(X, mu, sd) @ beta)), *PROB_CLIP)


def delta_method_se(beta: np.ndarray, cov_beta: np.ndarray, mu: np.ndarray, sd: np.ndarray,
                    x_row: np.ndarray) -> tuple[float, float]:
    """(p, se_p) — se_p = p(1−p)·sqrt(zᵀ Cov(β) z), z = [1, (x−μ)/σ]."""
    z = np.concatenate([[1.0], (np.asarray(x_row, float) - mu) / sd])
    eta = float(z @ beta)
    p = float(np.clip(1 / (1 + math.exp(-eta)), *PROB_CLIP))
    var_eta = float(z @ np.asarray(cov_beta, float) @ z)
    return p, p * (1 - p) * math.sqrt(max(var_eta, 0.0))


def block_bootstrap_cov(X: np.ndarray, y: np.ndarray, *, seed: int, block: int = BLOCK_LENGTH,
                        b: int = BOOTSTRAP_REPLICATES) -> np.ndarray:
    """정지 블록(기하 길이, 순환) 재표집 → 재적합 β 의 표본 공분산 (ddof=1). tools.block_boot_ci 와 같은 재표집 규칙."""
    rng = np.random.default_rng(seed); n = len(y)
    betas = []
    for _ in range(b):
        idx: list[np.ndarray] = []; total = 0
        while total < n:
            s = int(rng.integers(0, n)); L = int(rng.geometric(1.0 / block))
            idx.append((s + np.arange(L)) % n); total += L
        take = np.concatenate(idx)[:n]
        beta, _, _ = logit_fit(X[take], y[take], tol=1e-9)
        betas.append(beta)
    return np.cov(np.asarray(betas).T, ddof=1)


# ── isotonic (h63 파생층) ─────────────────────────────────────────────────────
def pav(p: np.ndarray, y: np.ndarray, w: np.ndarray | None = None) -> dict[str, list[float]]:
    p = np.asarray(p, float); y = np.asarray(y, float)
    w = np.ones(len(p)) if w is None else np.asarray(w, float)
    order = np.argsort(p, kind="stable"); p, y, w = p[order], y[order], w[order]
    blocks: list[list[float]] = []
    for pi, yi, wi in zip(p, y, w):
        blocks.append([yi * wi, wi, pi])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            b2 = blocks.pop(); b1 = blocks.pop()
            blocks.append([b1[0] + b2[0], b1[1] + b2[1], max(b1[2], b2[2])])
    return {"p_max": [float(b[2]) for b in blocks], "value": [float(b[0] / b[1]) for b in blocks]}


def pav_apply(pmap: dict[str, list[float]], p: np.ndarray | float) -> np.ndarray:
    arr = np.atleast_1d(np.asarray(p, float))
    pmax = np.asarray(pmap["p_max"], float); val = np.asarray(pmap["value"], float)
    k = np.clip(np.searchsorted(pmax, arr, side="left"), 0, len(val) - 1)
    return np.clip(val[k], *PROB_CLIP)
