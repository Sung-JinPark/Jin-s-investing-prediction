"""V15-VOL 팔·기준선·점수 — 순수 함수(numpy·표준 라이브러리만). 상수는 동결 아티팩트에서만 온다.

R1  p1 = clip(σ(a0_c + b0_c·logit p_PB))
R2  (vix25_h5·vix30_h5) λ1 = (#{j ∈ tail : j ≥ ln(K/x_t)} + ½)/(n_calm + 1),  λ5 = 1 − (1 − λ1)^5 (평온일 때만, 아니면 0),
    p2 = 1 − (1 − p_PB)(1 − λ5)
R3  p3 = ½·p_PB + ½·c_c(state_t)
점수: brier = (p − y)²,  log_score = y·ln p + (1 − y)·ln(1 − p) (p clip 1e-6, 클수록 좋음)
"""

from __future__ import annotations

import math
from bisect import bisect_left
from typing import Any, Sequence

from .contracts import CALM_VIX_BELOW, PROB_CLIP, R2_CELLS, THETA_RV


def _clip(p: float) -> float:
    return min(max(float(p), PROB_CLIP[0]), PROB_CLIP[1])


def logit(p: float) -> float:
    q = _clip(p)
    return math.log(q / (1.0 - q))


def sigmoid(z: float) -> float:
    z = float(z)
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def is_calm(cell_spec: dict[str, Any], inputs: dict[str, Any]) -> bool:
    """운영 문턱 상태: vix 셀 VIX_t < 20 (엄격), rv 셀 RV21_t ≤ θ (NaN 채움값 0.169421 > θ → stress)."""
    if cell_spec["target"] == "vix_touch":
        return float(inputs["vix_close"]) < CALM_VIX_BELOW
    return float(inputs["rv21_ann"]) <= THETA_RV


def r1_platt(p: float, a0: float, b0: float) -> float:
    return _clip(sigmoid(float(a0) + float(b0) * logit(p)))


def r2_lambda5(x: float, K: float, jump_tail: Sequence[float], n_calm: int, calm: bool, horizon: int = 5) -> float:
    """평온 1일 점프 해저드의 h 복리 — 비평온이면 0. jump_tail 은 오름차순."""
    if not calm:
        return 0.0
    need = math.log(float(K) / float(x))
    k = len(jump_tail) - bisect_left(list(jump_tail), need)
    lam1 = (k + 0.5) / (int(n_calm) + 1)
    return 1.0 - (1.0 - lam1) ** int(horizon)


def r2_jump(p: float, lam5: float) -> float:
    """1 − (1 − p)(1 − λ5) 를 p + (1 − p)·λ5 로 계산한다(대수적으로 같고 λ5=0 이면 정확히 p)."""
    p = float(p)
    return p + (1.0 - p) * float(lam5)


def r3_regime_mix(p: float, cond_rate: float) -> float:
    return 0.5 * float(p) + 0.5 * float(cond_rate)


def cell_columns(cell_spec: dict[str, Any], inputs: dict[str, Any], p_pb: float, constants: dict[str, Any],
                 *, clim: float) -> dict[str, Any]:
    """한 셀의 섀도 열 — {p_pb, p_r1, p_r2(R2 셀만), p_r3, clim, cond, calm}. 반올림은 호출부가 한다."""
    name = cell_spec["name"]
    calm = is_calm(cell_spec, inputs)
    r1 = constants["R1"]["cells"][name]
    rates = constants["R3"]["cells"][name]
    cond = float(rates["calm"] if calm else rates["stress"])
    out: dict[str, Any] = {
        "calm": bool(calm),
        "p_pb": float(p_pb),
        "p_r1": r1_platt(p_pb, r1["a0"], r1["b0"]),
    }
    if name in R2_CELLS:
        r2 = constants["R2"]
        lam5 = r2_lambda5(float(inputs["vix_close"]), cell_spec["K"], r2["jump_tail"], r2["n_calm"], calm,
                          horizon=int(r2["horizon"]))
        out["p_r2"] = r2_jump(p_pb, lam5)
    out["p_r3"] = r3_regime_mix(p_pb, cond)
    out["clim"] = float(clim)
    out["cond"] = cond
    return out


def brier(p: float, y: float) -> float:
    return (float(p) - float(y)) ** 2


def log_score(p: float, y: float) -> float:
    q = _clip(p)
    y = float(y)
    return y * math.log(q) + (1.0 - y) * math.log(1.0 - q)
