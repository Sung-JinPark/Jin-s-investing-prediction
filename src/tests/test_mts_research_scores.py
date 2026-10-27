"""채점기 테스트 — T33~T37 + 동결 채점기와의 교차 인증."""

from __future__ import annotations

import math

import numpy as np
import pytest

from ai_fc.mts_research.scores import (
    GridMismatch,
    MtsScoreError,
    SampleMeta,
    assert_simultaneous,
    brier,
    brier_skill_denominator_guard,
    crps_weighted_empirical,
    energy_score,
    fair_adjustment_allowed,
    interval_score,
    log_loss,
    pointwise_coverage,
    qlike,
    simultaneous_coverage,
    variogram_score,
    wis,
)


def _brute_force_crps(x: np.ndarray, w: np.ndarray, y: float) -> float:
    term1 = float(np.sum(w * np.abs(x - y)))
    term2 = 0.5 * float(np.sum(w[:, None] * w[None, :] * np.abs(x[:, None] - x[None, :])))
    return term1 - term2


def test_t33_crps_single_point_reduces_to_abs_error():
    assert crps_weighted_empirical([3.0], None, 1.0) == pytest.approx(2.0)
    assert crps_weighted_empirical([3.0, 3.0], None, 1.0) == pytest.approx(2.0)


def test_t33_crps_matches_frozen_scorer_and_brute_force():
    """동결 sample_crps(균일 가중)와 1e-12, O(M²) 전수와 1e-12 일치 (T33)."""
    from ai_fc.timeseries.backtest import sample_crps

    rng = np.random.default_rng(20261026)
    for _ in range(20):
        x = rng.normal(0, 1, rng.integers(2, 200))
        y = float(rng.normal())
        ours = crps_weighted_empirical(x, None, y)
        frozen = sample_crps(x, y)
        assert ours == pytest.approx(frozen, abs=1e-12)
    for _ in range(10):
        n = int(rng.integers(2, 40))
        x = rng.normal(0, 2, n)
        w = rng.random(n)
        w = w / w.sum()
        y = float(rng.normal())
        assert crps_weighted_empirical(x, w, y) == pytest.approx(
            _brute_force_crps(x, w, y), abs=1e-12
        )


def test_t33_crps_translation_and_scale():
    rng = np.random.default_rng(5)
    x = rng.normal(0, 1, 60)
    y = 0.3
    base = crps_weighted_empirical(x, None, y)
    assert crps_weighted_empirical(x + 2.5, None, y + 2.5) == pytest.approx(base, abs=1e-12)
    assert crps_weighted_empirical(3.0 * x, None, 3.0 * y) == pytest.approx(3.0 * base, abs=1e-12)


def test_t34_wis_grid_mismatch_rejected():
    quantiles = {0.1: -1.6, 0.5: 0.0, 0.9: 1.6}
    value = wis(quantiles, 0.5, alpha_grid=[0.2])
    # K=1 손계산: (0.5·|y−m| + (α/2)·IS) / 1.5
    expected = (0.5 * 0.5 + 0.1 * interval_score(-1.6, 1.6, 0.5, alpha=0.2)) / 1.5
    assert value == pytest.approx(expected, abs=1e-12)
    with pytest.raises(GridMismatch):
        wis({0.25: -0.6, 0.5: 0.0, 0.75: 0.6}, 0.5, alpha_grid=[0.2])  # 다른 격자
    with pytest.raises(GridMismatch):
        wis({0.1: -1.6, 0.9: 1.6}, 0.5, alpha_grid=[0.2])  # 중앙값 누락


def test_interval_score_penalty_direction():
    inside = interval_score(-1.0, 1.0, 0.0, alpha=0.2)
    below = interval_score(-1.0, 1.0, -2.0, alpha=0.2)
    above = interval_score(-1.0, 1.0, 2.0, alpha=0.2)
    assert inside == pytest.approx(2.0)
    assert below == pytest.approx(2.0 + 10.0) and above == pytest.approx(2.0 + 10.0)


def test_t35_fair_adjustment_refused():
    fair_adjustment_allowed(SampleMeta(iid=True, weighted=False, deterministic_grid=False))
    for meta in (
        SampleMeta(iid=False, weighted=False, deterministic_grid=False),
        SampleMeta(iid=True, weighted=True, deterministic_grid=False),
        SampleMeta(iid=True, weighted=False, deterministic_grid=True),
    ):
        with pytest.raises(MtsScoreError):
            fair_adjustment_allowed(meta)


def test_t36_energy_score_scalar_equals_crps_and_discriminates_dependence():
    """스칼라 ES ≡ CRPS; 사전 고정 반복 추첨에서 의존구조 구분 — 단일 실현 우위를
    요구하지 않고 평균 점수 분리를 검사한다 (T36)."""
    rng = np.random.default_rng(11)
    x = rng.normal(0, 1, 80)
    y = 0.4
    es = energy_score(x[:, None], None, np.array([y]))
    assert es == pytest.approx(crps_weighted_empirical(x, None, y), abs=1e-12)

    # 같은 Gaussian 주변분포, 다른 의존구조: comonotone vs 독립
    d = 5
    repeats = 40
    seeds = range(1000, 1000 + repeats)
    es_comonotone, es_independent = [], []
    for seed in seeds:
        gen = np.random.default_rng(seed)
        y_vec = gen.standard_normal(d)  # 실제 세계: 독립 성분
        z = gen.standard_normal(400)
        comonotone = np.repeat(z[:, None], d, axis=1)      # 완전 동행 경로
        independent = gen.standard_normal((400, d))        # 독립 경로
        es_comonotone.append(energy_score(comonotone, None, y_vec))
        es_independent.append(energy_score(independent, None, y_vec))
    assert np.mean(es_independent) < np.mean(es_comonotone)  # 맞는 의존구조가 평균 우위


def test_t36_variogram_detects_dependence_location_blind():
    """Variogram 은 차이 기반 — 공통 위치 이동에 불변, 의존 오류에 반응 (A.5)."""
    rng = np.random.default_rng(23)
    d = 4
    y_vec = rng.standard_normal(d)
    independent = rng.standard_normal((500, d))
    comonotone = np.repeat(rng.standard_normal(500)[:, None], d, axis=1)
    vs_ind = variogram_score(independent, None, y_vec)
    vs_com = variogram_score(comonotone, None, y_vec)
    assert vs_ind < vs_com  # 독립 실제 세계에서 comonotone 경로가 벌점
    shifted = variogram_score(independent + 7.0, None, y_vec + 7.0)
    assert shifted == pytest.approx(vs_ind, abs=1e-9)
    with pytest.raises(MtsScoreError):
        variogram_score(independent, None, y_vec, p=0.0)


def test_t37_pointwise_not_promotable_to_simultaneous():
    rng = np.random.default_rng(3)
    paths = rng.standard_normal((200, 10))
    lower, upper = np.full(10, -1.3), np.full(10, 1.3)
    pointwise = pointwise_coverage(paths, lower, upper)
    simultaneous = simultaneous_coverage(paths, lower, upper)
    assert simultaneous.hit_rate < pointwise.hit_rate  # 동시 띠가 더 어렵다
    assert assert_simultaneous(simultaneous) is simultaneous
    with pytest.raises(MtsScoreError):
        assert_simultaneous(pointwise)


def test_brier_logloss_qlike_contracts():
    assert brier(0.7, 1) == pytest.approx(0.09)
    with pytest.raises(MtsScoreError):
        brier(1.2, 1)
    assert log_loss(0.5, 1) == pytest.approx(math.log(2))
    assert log_loss(0.0, 0) == 0.0 and math.isinf(log_loss(0.0, 1))
    clipped = log_loss(0.0, 1, clip_epsilon=1e-6)
    assert math.isfinite(clipped)
    # QLIKE 는 v_hat=v 에서 최소
    v = 0.04
    base = qlike(v, v)
    assert qlike(v * 1.5, v) > base and qlike(v * 0.5, v) > base
    with pytest.raises(MtsScoreError):
        qlike(0.0, 1.0)
    with pytest.raises(MtsScoreError):
        brier_skill_denominator_guard(0.0)


def test_f13_wis_rejects_rounding_collapsed_grid():
    """round(q,12) 동치에서 붕괴하는 중복 키·중복 alpha 는 거부한다 (F13)."""
    from ai_fc.mts_research.scores import GridMismatch, wis

    collapsed = {0.05: 10.0, 0.05 + 1e-13: 12.0, 0.5: 20.0, 0.95: 30.0}
    with pytest.raises(GridMismatch):
        wis(collapsed, 15.0, alpha_grid=[0.1])
    clean = {0.05: 10.0, 0.5: 20.0, 0.95: 30.0}
    with pytest.raises(GridMismatch):
        wis(clean, 15.0, alpha_grid=[0.1, 0.1 + 1e-13])
    assert wis(clean, 15.0, alpha_grid=[0.1]) > 0.0


def test_f13_variogram_uniform_bias_blind_is_documented_limit():
    """variogram 은 균일 bias(X+c·1)에 불변 — 단독 사용 금지의 실측 근거 (F13)."""
    from ai_fc.mts_research.scores import variogram_score

    rng = np.random.default_rng(0)
    samples = rng.normal(0.0, 1.0, (64, 3))
    target = np.array([0.1, -0.2, 0.3])
    unbiased = variogram_score(samples, None, target)
    biased = variogram_score(samples + 5.0, None, target)
    assert abs(unbiased - biased) < 1e-9
