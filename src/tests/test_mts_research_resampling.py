"""공동 재표집·검정 테스트 — T41~T44 + 크기(size) 합성 null 검사."""

from __future__ import annotations

import numpy as np
import pytest

from ai_fc.mts_research.resampling import (
    LossPanel,
    MtsResamplingError,
    centered_paired_bootstrap_test,
    eligible_paired_mean,
    holm_adjust,
    joint_block_resample,
    skill_ratio,
    stationary_block_indices,
)


def _panel(n=60, *, sparse_eligibility=False, seed=1, shift=0.0):
    """합성 LossPanel — 모델 2(cand, base) × 셀 1."""
    rng = np.random.default_rng(seed)
    base = np.abs(rng.normal(1.0, 0.2, n))
    cand = base + rng.normal(shift, 0.05, n)
    losses = np.stack([cand, base], axis=1)[:, :, None]  # (n, 2, 1)
    eligibility = np.ones((n, 1), dtype=bool)
    if sparse_eligibility:
        eligibility[:, 0] = False
        eligibility[:: 7, 0] = True  # 드문 eligible 날짜 + 긴 gap (V14 모사)
    reason = np.zeros((n, 2, 1), dtype=int)
    origins = tuple(f"2026-01-{i:02d}" if i <= 31 else f"2026-02-{i-31:02d}" for i in range(1, n + 1))
    return LossPanel(
        origin_grid=origins, models=("cand", "base"), cells=("cell",),
        losses=losses, eligibility=eligibility, missing_reason=reason,
    )


def test_t41_original_grid_and_mask_resampled_together():
    """희소 eligibility 라도 원 grid 전체를 재표집하고 mask 를 같은 인덱스로 끌고 간다 (T41)."""
    panel = _panel(sparse_eligibility=True)
    replicates = joint_block_resample(panel, mean_block=5, replications=20, seed=42)
    assert replicates.indices.shape == (20, 60)
    for index_vector in replicates.indices:
        aggregate = eligible_paired_mean(
            panel, candidate="cand", baseline="base", cell="cell", index_vector=index_vector
        )
        # replicate 의 paired 수 == 인덱스된 mask 의 합 (mask 공동 적용 증거)
        assert aggregate.n_paired == int(panel.eligibility[index_vector, 0].sum())


def test_t42_same_indices_across_slices():
    """모든 모델·셀 슬라이스가 같은 인덱스 벡터를 쓴다 — ReplicateSet 은 panel 에 묶인다 (T42)."""
    panel = _panel()
    replicates = joint_block_resample(panel, mean_block=5, replications=5, seed=7)
    other = _panel(n=30)
    with pytest.raises(MtsResamplingError):
        centered_paired_bootstrap_test(
            other, replicates, candidate="cand", baseline="base", cell="cell"
        )  # 다른 panel 의 replicate 재사용 금지


def test_t43_degenerate_and_not_identifiable():
    """상수 손실차·전퇴화 replicate·0 분모 skill — 가짜 p/skill 없이 명확한 상태 (T43)."""
    # 전부 ineligible → UNTESTABLE
    panel = _panel()
    empty = LossPanel(
        origin_grid=panel.origin_grid, models=panel.models, cells=panel.cells,
        losses=panel.losses, eligibility=np.zeros_like(panel.eligibility),
        missing_reason=panel.missing_reason,
    )
    replicates = joint_block_resample(empty, mean_block=5, replications=10, seed=3)
    result = centered_paired_bootstrap_test(
        empty, replicates, candidate="cand", baseline="base", cell="cell"
    )
    assert result.status == "UNTESTABLE" and result.p_raw is None
    # skill 분모 0
    assert skill_ratio(1.0, 0.0)["status"] == "NOT_IDENTIFIABLE"
    assert skill_ratio(0.8, 1.0)["skill"] == pytest.approx(0.2)


def test_t44_holm_direction_units_and_family_preservation():
    """one-sided 방향·δ 단위·Holm 손계산 일치 + 검정불능도 family 에 남는다 (T44)."""
    panel_better = _panel(shift=-0.3, seed=11)   # 후보가 명확히 개선
    panel_null = _panel(shift=0.0, seed=12)
    replicates_b = joint_block_resample(panel_better, mean_block=5, replications=499, seed=99)
    replicates_n = joint_block_resample(panel_null, mean_block=5, replications=499, seed=99)
    improved = centered_paired_bootstrap_test(
        panel_better, replicates_b, candidate="cand", baseline="base", cell="cell"
    )
    null = centered_paired_bootstrap_test(
        panel_null, replicates_n, candidate="cand", baseline="base", cell="cell"
    )
    assert improved.status == "OK" and improved.p_raw < 0.05
    assert null.status == "OK" and null.p_raw > 0.05
    # δ 는 손실 단위: 개선 폭(0.3)보다 큰 δ 를 요구하면 유의성이 사라진다
    strict = centered_paired_bootstrap_test(
        panel_better, replicates_b, candidate="cand", baseline="base", cell="cell", delta=0.5
    )
    assert strict.p_raw > improved.p_raw

    untestable = centered_paired_bootstrap_test(
        LossPanel(
            origin_grid=panel_null.origin_grid, models=panel_null.models,
            cells=panel_null.cells, losses=panel_null.losses,
            eligibility=np.zeros_like(panel_null.eligibility),
            missing_reason=panel_null.missing_reason,
        ),
        joint_block_resample(
            LossPanel(
                origin_grid=panel_null.origin_grid, models=panel_null.models,
                cells=panel_null.cells, losses=panel_null.losses,
                eligibility=np.zeros_like(panel_null.eligibility),
                missing_reason=panel_null.missing_reason,
            ), mean_block=5, replications=10, seed=1,
        ),
        candidate="cand", baseline="base", cell="cell",
    )
    family = holm_adjust([improved, null, untestable], family_id="syn", alpha=0.05)
    assert family.family_size == 3  # 검정불능 제거로 family 를 줄이지 않는다
    # Holm 손계산: p 정렬 후 (m-rank)·p 의 running max
    p = [r.p_raw if r.p_raw is not None else 1.0 for r in (improved, null, untestable)]
    order = sorted(range(3), key=lambda i: p[i])
    expected = {}
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (3 - rank) * p[i]))
        expected[i] = running
    assert list(family.adjusted_p) == [expected[0], expected[1], expected[2]]
    assert family.rejected[2] is False  # untestable 은 기각 불가


def test_size_under_dependent_null():
    """블록 의존 null 에서 좌측꼬리 기각률이 명목 수준을 크게 넘지 않는다 (§19.2 — MC 불확실성 보고)."""
    rng = np.random.default_rng(2026)
    rejections = 0
    trials = 60
    for t in range(trials):
        n = 80
        innovations = rng.normal(0, 1, n)
        ar = np.zeros(n)
        for i in range(1, n):
            ar[i] = 0.5 * ar[i - 1] + innovations[i]  # 의존 손실차, 평균 0
        base = np.abs(rng.normal(1.0, 0.1, n)) + 1.0
        cand = base + 0.05 * ar
        losses = np.stack([cand, base], axis=1)[:, :, None]
        panel = LossPanel(
            origin_grid=tuple(f"d{i:03d}" for i in range(n)),
            models=("cand", "base"), cells=("cell",),
            losses=losses, eligibility=np.ones((n, 1), dtype=bool),
            missing_reason=np.zeros((n, 2, 1), dtype=int),
        )
        replicates = joint_block_resample(panel, mean_block=8, replications=199, seed=t)
        result = centered_paired_bootstrap_test(
            panel, replicates, candidate="cand", baseline="base", cell="cell"
        )
        if result.p_raw is not None and result.p_raw <= 0.05:
            rejections += 1
    rate = rejections / trials
    # 명목 5% — MC 오차(60회) 감안 상한 15%: 근사 유효성의 보수적 확인이지 보장은 아니다
    assert rate <= 0.15, f"귀무 기각률 {rate}"


def test_block_indices_contract():
    rng = np.random.default_rng(0)
    indices = stationary_block_indices(50, mean_block=5, rng=rng)
    assert indices.shape == (50,) and indices.min() >= 0 and indices.max() < 50
    with pytest.raises(MtsResamplingError):
        stationary_block_indices(0, mean_block=5, rng=rng)


def test_panel_missing_reason_contract():
    n = 4
    losses = np.ones((n, 2, 1))
    losses[1, 0, 0] = np.nan
    reason = np.zeros((n, 2, 1), dtype=int)
    with pytest.raises(MtsResamplingError):
        LossPanel(
            origin_grid=("a", "b", "c", "d"), models=("x", "y"), cells=("c1",),
            losses=losses, eligibility=np.ones((n, 1), dtype=bool), missing_reason=reason,
        )  # NaN 에 OK 사유 — 거부
