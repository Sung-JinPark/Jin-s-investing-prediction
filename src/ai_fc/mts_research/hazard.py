"""§9.4~9.6 이산시간 hazard scaffold — **합성 테스트 전용** (W5).

실측 V14 개발 실험은 V14-D11 결정·예산·실험 등록 조건이 충족될 때만 실행한다.
이 모듈은 어떤 실자료도 읽지 않는다.

구조 (§9.4): logit(λ_{t,k}) = a_{b(k)} + β z_t
- z_t: 원점에 알려진 특징만 (미래 VIX/RV teacher forcing 금지 — T24).
- b(k): 시간 basis — 제안 초기 구간 [1..5], [6..21], [22..63].
- 적합: bin 절편은 무벌점, 공유 slope 에만 ridge — 자체 Newton-IRLS
  (저장소 전례: timeseries_v13/features.py::logit_fit; sklearn 은 이 벌점 구조를
  표현하지 못한다). 수렴 실패 시 scipy L-BFGS-B fallback — 플래그로 기록, 조용한
  대체 없음.
- p(h) = 1 − Π(1−λ_k): log1p/expm1 경로로 p(5) <= p(21) <= p(63) 기계 보장 (T25·T26).
- 중첩 원점의 person-period 합은 composite 목적 — naive iid Hessian CI 금지
  (`no_iid_ci` 플래그, §9.5). 계수 대역은 등록된 block 절차로만.
- clip 정책 3종(학습/log score/표시)은 별개 상수다 (§9.5).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from ..timeseries_v8.contracts import canonical_hash

DEFAULT_TIME_BINS: tuple[tuple[int, int], ...] = ((1, 5), (6, 21), (22, 63))

# clip 정책 — 학습·채점·표시를 하나의 epsilon 으로 뭉개지 않는다 (§9.5)
TRAIN_HAZARD_CLIP = 1e-10       # 우도 수치 안정 전용
LOG_SCORE_CLIP = 1e-6           # 채점용 — 원확률은 보존
DISPLAY_ROUND_DIGITS = 6        # 표시 반올림


class MtsHazardError(RuntimeError):
    """hazard 계약 위반 — fail-closed."""


@dataclass(frozen=True)
class SurfaceKey:
    """확률 표면의 좌표 — 다른 표면 간 제약 결합을 막는 축 (T27, §9.6)."""

    origin_session: str
    information_cutoff_at: str
    eligibility_rule_hash: str
    observation_field: str
    within_horizon: bool

    def hash(self) -> str:
        return canonical_hash(self.__dict__)


@dataclass(frozen=True)
class PersonPeriods:
    origin_index: np.ndarray  # (R,)
    k: np.ndarray             # (R,) 1-based 미래 세션
    bin_index: np.ndarray     # (R,)
    z: np.ndarray             # (R, p) — 원점 특징 브로드캐스트
    d: np.ndarray             # (R,) {0,1}
    n_origins: int
    horizon: int
    bins: tuple[tuple[int, int], ...]


def _bin_of(k: int, bins: Sequence[tuple[int, int]]) -> int:
    for index, (low, high) in enumerate(bins):
        if low <= k <= high:
            return index
    raise MtsHazardError(f"k={k} 가 어느 bin 에도 없다")


def build_person_periods(
    *,
    event_k: np.ndarray,
    observed_end_k: np.ndarray,
    z: np.ndarray,
    horizon: int,
    bins: tuple[tuple[int, int], ...] = DEFAULT_TIME_BINS,
) -> PersonPeriods:
    """원점별 (사건 k, 관측 종료 k, 특징) → person-period 행 (§9.5).

    - ``event_k[i]`` ∈ {0(미관측), 1..}: **fit cutoff 까지 실제로 본** 첫 사건의 k.
      잠재 T 를 아는 것으로 가정하지 않는다 (T23).
    - ``observed_end_k[i]``: 원점 i 이후 **연속 완전 관측**된 마지막 미래 세션 —
      데이터 누락을 무사건 생존으로 해석하지 않는다.
    - 행은 k = 1 .. min(event_k or ∞, observed_end_k, horizon); 사건 뒤 행 금지 (T22).
    - z 는 (n_origins, p) 원점 특징만 — 시간축을 가진 covariate 거부 (T24).
    """
    event = np.asarray(event_k, dtype=int)
    end = np.asarray(observed_end_k, dtype=int)
    features = np.asarray(z, dtype=float)
    if features.ndim != 2:
        raise MtsHazardError(
            "origin-only feature 계약 위반: z 는 (n_origins, p) — "
            "시간축/미래값 covariate 금지 (T24)"
        )
    n = features.shape[0]
    if event.shape != (n,) or end.shape != (n,):
        raise MtsHazardError("event_k/observed_end_k 모양 불일치")
    if (end < 0).any() or (end > horizon).any():
        raise MtsHazardError("observed_end_k 는 [0, horizon]")
    if (event < 0).any():
        raise MtsHazardError("event_k 는 0(미관측) 또는 1 이상")
    observed_event = event > 0
    if (event[observed_event] > end[observed_event]).any():
        raise MtsHazardError(
            "event_k > observed_end_k — 보지 못한 사건을 입력할 수 없다 (T23)"
        )
    if not np.isfinite(features).all():
        raise MtsHazardError("특징에 NaN/inf 금지")

    origin_rows: list[int] = []
    k_rows: list[int] = []
    d_rows: list[int] = []
    for i in range(n):
        last = min(int(event[i]) if event[i] > 0 else horizon, int(end[i]), horizon)
        for k in range(1, last + 1):
            origin_rows.append(i)
            k_rows.append(k)
            d_rows.append(1 if (event[i] > 0 and k == event[i]) else 0)
    if not origin_rows:
        raise MtsHazardError("person-period 행이 없다")
    origin_arr = np.asarray(origin_rows, dtype=int)
    k_arr = np.asarray(k_rows, dtype=int)
    return PersonPeriods(
        origin_index=origin_arr,
        k=k_arr,
        bin_index=np.asarray([_bin_of(int(k), bins) for k in k_arr], dtype=int),
        z=features[origin_arr],
        d=np.asarray(d_rows, dtype=int),
        n_origins=n,
        horizon=horizon,
        bins=tuple(tuple(b) for b in bins),
    )


@dataclass(frozen=True)
class HazardFit:
    bins: tuple[tuple[int, int], ...]
    intercepts: np.ndarray
    beta: np.ndarray
    ridge: float
    scaler_mu: np.ndarray
    scaler_sd: np.ndarray
    converged: bool
    fallback_used: bool
    nll: float
    n_origins: int
    n_person_periods: int
    no_iid_ci: bool = True  # §9.5 — naive Hessian CI 금지 플래그
    # 외부 리뷰 F11 (2026-10-27): optimizer 의 '수렴' 과 통계적 '식별가능' 은 다른 판정이다.
    # 사건 0 bin 의 무벌점 절편은 유한 최적해가 없고(a_b→−∞), 전건 bin 은 반대 방향 발산.
    non_identified_bins: tuple[int, ...] = ()
    slope_divergence: bool = False

    @property
    def estimable(self) -> bool:
        """전 bin 식별 + slope 비발산 — converged 와 별개의 판정 (F11)."""
        return not self.non_identified_bins and not self.slope_divergence


def _design(pp: PersonPeriods, mu: np.ndarray, sd: np.ndarray) -> np.ndarray:
    n_bins = len(pp.bins)
    one_hot = np.zeros((len(pp.k), n_bins))
    one_hot[np.arange(len(pp.k)), pp.bin_index] = 1.0
    standardized = (pp.z - mu) / sd
    return np.hstack([one_hot, standardized])


def negative_log_likelihood(
    pp: PersonPeriods, intercepts: np.ndarray, beta: np.ndarray,
    *, mu: np.ndarray, sd: np.ndarray, ridge: float,
) -> float:
    """§9.5 우도 (ridge 는 slope 블록만). log1p 경로로 안정 계산."""
    eta = intercepts[pp.bin_index] + ((pp.z - mu) / sd) @ beta
    # -log(1+e^{-eta})·d - log(1+e^{eta})·(1-d) 의 안정형
    nll = float(np.sum(np.logaddexp(0.0, eta) - pp.d * eta))
    return nll + 0.5 * ridge * float(beta @ beta)


def fit_hazard(
    pp: PersonPeriods, *, ridge: float, max_iter: int = 200, tol: float = 1e-10
) -> HazardFit:
    """penalized Newton-IRLS — scaler 는 학습 자료(원점 특징)에서만 적합한다."""
    if ridge < 0:
        raise MtsHazardError("ridge >= 0")
    # scaler: 원점당 1회 (person-period 반복 가중 왜곡 방지)
    unique_origins = np.unique(pp.origin_index)
    origin_features = np.stack([pp.z[pp.origin_index == i][0] for i in unique_origins])
    mu = origin_features.mean(axis=0)
    sd = origin_features.std(axis=0).copy()
    sd[sd < 1e-9] = 1.0

    n_bins = len(pp.bins)
    # F11 — bin별 risk-set·사건 수 사전 점검: 행 0 bin(절편 정의 불능)·사건 0 bin(절편
    # a_b→−∞ 발산)·전건 bin(반대 방향 발산)은 전부 '비식별' 로 기록한다. 적합 자체는
    # 식별된 bin 들을 위해 진행하되, 비식별 bin 을 지나는 확률 산출은 거부된다.
    bin_rows = np.bincount(pp.bin_index, minlength=n_bins)
    bin_events = np.bincount(pp.bin_index, weights=pp.d.astype(float), minlength=n_bins)
    non_identified = tuple(
        i for i in range(n_bins)
        if bin_rows[i] == 0 or bin_events[i] == 0 or bin_events[i] == bin_rows[i]
    )

    design = _design(pp, mu, sd)
    n_params = design.shape[1]
    theta = np.zeros(n_params)
    penalty = np.zeros(n_params)
    penalty[n_bins:] = ridge  # slope 블록만 벌점

    converged = False
    for _ in range(max_iter):
        eta = design @ theta
        probability = 1.0 / (1.0 + np.exp(-np.clip(eta, -35, 35)))
        probability = np.clip(probability, TRAIN_HAZARD_CLIP, 1 - TRAIN_HAZARD_CLIP)
        gradient = design.T @ (probability - pp.d) + penalty * theta
        weights = probability * (1 - probability)
        hessian = (design * weights[:, None]).T @ design + np.diag(penalty)
        try:
            step = np.linalg.solve(hessian, gradient)
        except np.linalg.LinAlgError:
            break
        theta = theta - step
        if float(np.max(np.abs(step))) < tol:
            converged = True
            break

    fallback = False
    if not converged:
        from scipy.optimize import minimize

        def objective(vector: np.ndarray) -> float:
            return negative_log_likelihood(
                pp, vector[:n_bins], vector[n_bins:], mu=mu, sd=sd, ridge=ridge
            )

        result = minimize(objective, theta, method="L-BFGS-B")
        theta = result.x
        converged = bool(result.success)
        fallback = True  # 조용한 대체 없음 — 기록 (§9.4)

    intercepts = theta[:n_bins]
    beta = theta[n_bins:]
    # F11 — 표준화 특징에서 |β| 가 선형 예측자 clip 경계(35)를 넘으면 사실상 분리:
    # ridge=0 이면 유한 최적해가 없을 수 있고, optimizer 종료가 식별을 만들지 않는다.
    slope_divergence = bool(beta.size and float(np.max(np.abs(beta))) > 35.0)
    return HazardFit(
        bins=pp.bins,
        intercepts=intercepts,
        beta=beta,
        ridge=ridge,
        scaler_mu=mu,
        scaler_sd=sd,
        converged=converged,
        fallback_used=fallback,
        nll=negative_log_likelihood(pp, intercepts, beta, mu=mu, sd=sd, ridge=0.0),
        n_origins=pp.n_origins,
        n_person_periods=len(pp.k),
        non_identified_bins=non_identified,
        slope_divergence=slope_divergence,
    )


def _assert_identified_through(fit: HazardFit, horizon: int) -> None:
    """F11 — 요청 지평이 비식별 bin 을 지나면 확률 산출을 거부한다 (조용한 날조 차단)."""
    if fit.slope_divergence:
        raise MtsHazardError(
            "slope 발산(사실상 분리) 적합 — 확률 산출 거부. 등록된 ridge/HOLD 정책으로만 (F11)"
        )
    touched = {_bin_of(k, fit.bins) for k in range(1, horizon + 1)}
    bad = sorted(touched & set(fit.non_identified_bins))
    if bad:
        raise MtsHazardError(
            f"비식별 bin {bad} (사건 0 또는 전건) 을 지나는 지평 {horizon} — "
            "λ 추정치가 정의되지 않아 확률을 내지 않는다 (F11). "
            "허용 fallback(HOLD·baseline·bin 통합)은 등록된 정책으로만"
        )


def hazard_curve(fit: HazardFit, z_row: np.ndarray, horizon: int) -> np.ndarray:
    """λ_k, k=1..horizon — 원점 특징 하나의 hazard 곡선."""
    _assert_identified_through(fit, horizon)
    z_row = np.asarray(z_row, dtype=float)
    if z_row.ndim != 1 or z_row.shape[0] != fit.beta.shape[0]:
        raise MtsHazardError("z_row 모양 불일치 — 원점 특징만 (T24)")
    standardized = (z_row - fit.scaler_mu) / fit.scaler_sd
    curve = np.empty(horizon)
    for k in range(1, horizon + 1):
        eta = fit.intercepts[_bin_of(k, fit.bins)] + float(standardized @ fit.beta)
        curve[k - 1] = 1.0 / (1.0 + np.exp(-eta))
    return curve


def cumulative_event_probability(
    fit: HazardFit, z_row: np.ndarray, horizons: Sequence[int] = (5, 21, 63)
) -> np.ndarray:
    """p(h) = 1 − Π_{k<=h}(1−λ_k) — log1p/expm1 경로, 지평 단조 기계 보장 (T25·T26)."""
    max_h = max(horizons)
    curve = hazard_curve(fit, z_row, max_h)
    log_survival = np.cumsum(np.log1p(-np.clip(curve, 0.0, 1 - 1e-15)))
    out = np.array([-np.expm1(log_survival[h - 1]) for h in horizons])
    return out


def check_probability_surface(
    probabilities: np.ndarray,
    *,
    horizons: Sequence[int],
    surface: SurfaceKey,
    other_surface: SurfaceKey | None = None,
) -> None:
    """T26 — 범위·지평 단조; T27 — 다른 표면과의 제약 결합 거부."""
    p = np.asarray(probabilities, dtype=float)
    if p.shape != (len(horizons),):
        raise MtsHazardError("확률/지평 모양 불일치")
    if (p < 0).any() or (p > 1).any() or not np.isfinite(p).all():
        raise MtsHazardError("확률 범위 [0,1] 위반 (T26)")
    order = np.argsort(np.asarray(horizons))
    if (np.diff(p[order]) < -1e-12).any():
        raise MtsHazardError("같은 사건의 지평 단조성 위반: p(h1) > p(h2), h1<h2 (T26)")
    if other_surface is not None and other_surface.hash() != surface.hash():
        raise MtsHazardError(
            "다른 origin/cutoff/eligibility/판정 기준 표면 간 제약 투영 금지 (T27) — "
            "예: V13 무조건부 vs V14 평온 조건부"
        )
