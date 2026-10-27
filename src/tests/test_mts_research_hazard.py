"""hazard scaffold 테스트 — T22~T27 (합성 전용, 실자료 0)."""

from __future__ import annotations

import numpy as np
import pytest

from ai_fc.mts_research.hazard import (
    HazardFit,
    MtsHazardError,
    SurfaceKey,
    build_person_periods,
    check_probability_surface,
    cumulative_event_probability,
    fit_hazard,
    hazard_curve,
    negative_log_likelihood,
)


def _constant_hazard_cohort(lam: float, n: int, horizon: int, seed: int):
    """상수 λ 기하 사건 시각 코호트 — z 는 정보 없음(0)."""
    rng = np.random.default_rng(seed)
    event = np.zeros(n, dtype=int)
    end = np.full(n, horizon, dtype=int)
    for i in range(n):
        draws = rng.random(horizon)
        hits = np.nonzero(draws < lam)[0]
        if hits.size:
            event[i] = int(hits[0]) + 1
    z = rng.normal(0, 1, (n, 1)) * 0.0  # 무정보 특징
    return event, end, z


def test_f11_zero_event_bin_flagged_and_probability_refused():
    """사건 0 bin 은 비식별로 기록되고 그 bin 을 지나는 확률 산출은 거부된다 (F11).

    무벌점 절편은 사건 0 bin 에서 유한 최적해가 없다(a_b→−∞) — optimizer 가
    '수렴' 을 보고해도 식별이 아니다. estimable 이 그 구분이다.
    """
    rng = np.random.default_rng(11)
    n = 40
    # 사건은 전부 k<=21 (bin 0·1), bin 2(22..63) 는 risk 행만 있고 사건 0
    event = np.where(rng.random(n) < 0.5, rng.integers(1, 22, n), 0)
    end = np.full(n, 63, dtype=int)
    z = rng.normal(0, 1, (n, 2))
    pp = build_person_periods(event_k=event, observed_end_k=end, z=z, horizon=63)
    fit = fit_hazard(pp, ridge=1.0)
    assert 2 in fit.non_identified_bins
    assert fit.estimable is False
    with pytest.raises(MtsHazardError, match="비식별 bin"):
        cumulative_event_probability(fit, z[0], horizons=(63,))
    # 식별된 bin 만 지나는 지평은 허용 — 전부 거부가 아니라 비식별 구간만 거부
    p = cumulative_event_probability(fit, z[0], horizons=(5, 21))
    assert p.shape == (2,)


def test_f11_empty_risk_set_bin_refuses_fabricated_probability():
    """risk-set 행이 없는 bin 은 비식별 — 절편이 초기값(λ=0.5)에 머물러 p 를 날조하던
    경로를 확률 산출 거부로 차단한다 (F11)."""
    rng = np.random.default_rng(12)
    n = 20
    event = np.where(rng.random(n) < 0.5, rng.integers(1, 15, n), 0)
    end = np.full(n, 21, dtype=int)  # bin 2(22..63) 행 자체가 없음
    z = rng.normal(0, 1, (n, 1))
    pp = build_person_periods(event_k=event, observed_end_k=end, z=z, horizon=63)
    fit = fit_hazard(pp, ridge=1.0)
    assert 2 in fit.non_identified_bins
    assert fit.estimable is False
    with pytest.raises(MtsHazardError, match="비식별 bin"):
        cumulative_event_probability(fit, z[0], horizons=(63,))


def test_f11_separation_with_zero_ridge_flagged():
    """완전분리 + ridge=0 은 slope 발산 — estimable=False, 확률 산출 거부 (F11)."""
    n = 30
    z = np.linspace(-1, 1, n).reshape(-1, 1)
    event = np.where(z[:, 0] > 0, 1, 0).astype(int)  # z>0 이면 k=1 사건: 완전분리
    end = np.full(n, 5, dtype=int)
    pp = build_person_periods(
        event_k=event, observed_end_k=end, z=z, horizon=5, bins=((1, 5),),
    )
    diverged = fit_hazard(pp, ridge=0.0)
    assert diverged.slope_divergence is True
    assert diverged.estimable is False
    with pytest.raises(MtsHazardError, match="slope 발산"):
        hazard_curve(diverged, z[0], 5)
    regularized = fit_hazard(pp, ridge=1.0)
    assert regularized.slope_divergence is False
    assert regularized.estimable is True
    assert 0.0 < cumulative_event_probability(regularized, z[0], horizons=(5,))[0] < 1.0


def test_t22_no_rows_after_first_event():
    event = np.array([3, 0])
    end = np.array([5, 5])
    z = np.zeros((2, 1))
    pp = build_person_periods(event_k=event, observed_end_k=end, z=z, horizon=5)
    first = pp.k[pp.origin_index == 0]
    assert list(first) == [1, 2, 3]  # 사건 뒤 행 없음 (T22)
    assert list(pp.d[pp.origin_index == 0]) == [0, 0, 1]
    second = pp.k[pp.origin_index == 1]
    assert list(second) == [1, 2, 3, 4, 5]
    assert pp.d[pp.origin_index == 1].sum() == 0


def test_t23_censoring_boundary():
    """event_k > observed_end_k 입력 거부 + 검열 경계 행 수 일치 (T23)."""
    with pytest.raises(MtsHazardError):
        build_person_periods(
            event_k=np.array([4]), observed_end_k=np.array([3]),
            z=np.zeros((1, 1)), horizon=5,
        )
    pp = build_person_periods(
        event_k=np.array([0]), observed_end_k=np.array([3]),  # 세션 4 부터 관측 누락
        z=np.zeros((1, 1)), horizon=5,
    )
    assert list(pp.k) == [1, 2, 3]  # 누락을 무사건 생존으로 세지 않는다


def test_t24_future_covariates_rejected():
    with pytest.raises(MtsHazardError):
        build_person_periods(
            event_k=np.array([0, 0]), observed_end_k=np.array([5, 5]),
            z=np.zeros((2, 5, 1)), horizon=5,  # (n, H, p) — 시간축 covariate
        )
    # 적합 후에도 z_row 는 원점 특징 하나
    event, end, z = _constant_hazard_cohort(0.1, 100, 21, seed=1)
    pp = build_person_periods(event_k=event, observed_end_k=end, z=z, horizon=21)
    fit = fit_hazard(pp, ridge=1.0)
    with pytest.raises(MtsHazardError):
        hazard_curve(fit, np.zeros(5), 21)  # 특징 차원 불일치


def test_t25_constant_hazard_closed_form():
    """상수 λ: p(h)=1-(1-λ)^h 수치 일치 + 참 λ 의 NLL 폐형 일치 (T25)."""
    lam = 0.08
    event, end, z = _constant_hazard_cohort(lam, 4000, 63, seed=20261026)
    pp = build_person_periods(event_k=event, observed_end_k=end, z=z, horizon=63)
    fit = fit_hazard(pp, ridge=1.0)
    assert fit.converged
    p = cumulative_event_probability(fit, np.zeros(1), horizons=(5, 21, 63))
    expected = 1.0 - (1.0 - lam) ** np.array([5, 21, 63])
    assert np.allclose(p, expected, atol=0.03)  # 표본 오차 내 (등록 허용오차)
    # 참 λ 에서의 NLL 폐형: -Σ[d logλ + (1-d) log(1-λ)]
    import math

    truth_intercepts = np.full(3, math.log(lam / (1 - lam)))
    closed = -(
        pp.d.sum() * math.log(lam) + (len(pp.d) - pp.d.sum()) * math.log(1 - lam)
    )
    computed = negative_log_likelihood(
        pp, truth_intercepts, np.zeros(1), mu=fit.scaler_mu, sd=fit.scaler_sd, ridge=0.0
    )
    assert computed == pytest.approx(closed, rel=1e-9)
    assert fit.no_iid_ci is True  # naive Hessian CI 금지 플래그 (§9.5)


def test_t26_horizon_monotone_and_range():
    """p(5)<=p(21)<=p(63) 기계 보장 — log1p/expm1 경로 (T26)."""
    event, end, z = _constant_hazard_cohort(0.05, 500, 63, seed=3)
    pp = build_person_periods(event_k=event, observed_end_k=end, z=z, horizon=63)
    fit = fit_hazard(pp, ridge=1.0)
    p = cumulative_event_probability(fit, np.zeros(1), horizons=(5, 21, 63))
    assert 0.0 <= p[0] <= p[1] <= p[2] <= 1.0
    surface = SurfaceKey(
        origin_session="2026-10-20", information_cutoff_at="2026-10-20T21:15:00+00:00",
        eligibility_rule_hash="e1", observation_field="official_close", within_horizon=True,
    )
    check_probability_surface(p, horizons=(5, 21, 63), surface=surface)
    with pytest.raises(MtsHazardError):
        check_probability_surface(
            np.array([0.5, 0.3, 0.6]), horizons=(5, 21, 63), surface=surface
        )  # 단조 위반 탐지


def test_t27_cross_surface_projection_refused():
    """다른 cutoff/조건부 표면 간 projection 결합 거부 (T27)."""
    unconditional = SurfaceKey(
        origin_session="2026-10-20", information_cutoff_at="2026-10-20T21:15:00+00:00",
        eligibility_rule_hash="none", observation_field="official_close", within_horizon=True,
    )
    conditional = SurfaceKey(
        origin_session="2026-10-20", information_cutoff_at="2026-10-20T21:15:00+00:00",
        eligibility_rule_hash="v14_vix_calm", observation_field="official_close",
        within_horizon=True,
    )
    p = np.array([0.1, 0.2, 0.3])
    check_probability_surface(
        p, horizons=(5, 21, 63), surface=unconditional, other_surface=unconditional
    )
    with pytest.raises(MtsHazardError):
        check_probability_surface(
            p, horizons=(5, 21, 63), surface=unconditional, other_surface=conditional
        )


def test_informative_feature_recovered():
    """z 가 hazard 를 올리는 합성 세계에서 β>0 방향을 복원한다 (scaffold 건전성)."""
    rng = np.random.default_rng(9)
    n, horizon = 3000, 21
    z = rng.normal(0, 1, (n, 1))
    beta_true = 0.9
    base = -2.5
    event = np.zeros(n, dtype=int)
    end = np.full(n, horizon, dtype=int)
    for i in range(n):
        lam = 1 / (1 + np.exp(-(base + beta_true * z[i, 0])))
        draws = rng.random(horizon)
        hits = np.nonzero(draws < lam)[0]
        if hits.size:
            event[i] = int(hits[0]) + 1
    pp = build_person_periods(event_k=event, observed_end_k=end, z=z, horizon=horizon)
    fit = fit_hazard(pp, ridge=1.0)
    assert fit.converged and fit.beta[0] > 0.3
