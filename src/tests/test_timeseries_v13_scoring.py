"""V13 판정 기계 라이브러리 — 부트스트랩·쌍대 Brier·건전 귀무·Murphy·국면 가드.

핵심 회귀: 사건 수 가드는 통과하는데 국면 가드는 실패하는 표본을 정확히 구분해야 한다
(설계창 실측에서 vix30 계열 후반창이 정확히 그 모양이었다).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

from ai_fc.timeseries_v13 import scoring as S

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))


def test_block_boot_ci_matches_the_rung1_reference_rule() -> None:
    tools = pytest.importorskip("v13_vol_run")
    rng = np.random.default_rng(3)
    d = rng.normal(loc=0.002, scale=0.01, size=400)
    mean, lo, hi, se = tools.block_boot_ci(d, seed=S.BOOTSTRAP_SEED, b=300)
    out = S.block_boot_ci(d, seed=S.BOOTSTRAP_SEED, b=300)
    assert out["mean"] == pytest.approx(mean)
    assert out["ci90"] == pytest.approx([lo, hi])
    assert out["se"] == pytest.approx(se)
    assert out["mde"] == pytest.approx(1.645 * se)
    empty = S.block_boot_ci(np.array([]))
    assert empty["n"] == 0 and np.isnan(empty["mean"])


def test_paired_brier_ci_sign_and_two_sided_decisions() -> None:
    rng = np.random.default_rng(5)
    y = (rng.uniform(size=600) < 0.4).astype(float)
    good = np.where(y == 1, 0.75, 0.25)          # 정보 있는 예측
    base = np.full(600, 0.4)                      # 기후
    out = S.paired_brier_ci(base, good, y, b=200)
    assert out["mean"] > 0 and out["lower_gt_zero"] is True and out["upper_ge_zero"] is True
    flipped = S.paired_brier_ci(good, base, y, b=200)
    assert flipped["mean"] < 0 and flipped["lower_gt_zero"] is False
    assert flipped["upper_ge_zero"] is False, "유의 열위는 비열화(upper>=0)를 통과하면 안 된다"
    same = S.paired_brier_ci(base, base, y, b=100)
    assert same["mean"] == pytest.approx(0.0) and same["upper_ge_zero"] is True


def test_brier_skill_score_is_zero_for_climatology() -> None:
    y = np.array([1.0, 0.0, 1.0, 0.0])
    assert S.brier_skill_score(np.full(4, 0.5), y, 0.5) == pytest.approx(0.0)
    assert S.brier_skill_score(y, y, 0.5) == pytest.approx(1.0)


def test_y_block_null_permutes_blocks_and_preserves_the_label_multiset() -> None:
    y = np.array([1.0] * 13 + [0.0] * 13 + [1.0] * 13 + [0.0] * 13)
    perms = list(S.y_block_permutations(y, draws=8, seed=1))
    assert len(perms) == 8
    for p in perms:
        assert len(p) == len(y)
        assert sorted(p.tolist()) == sorted(y.tolist()), "라벨 다중집합 보존"
    assert any(not np.array_equal(p, y) for p in perms), "적어도 한 번은 순서가 바뀌어야 한다"
    rate = S.y_block_null_pass_rate(y, lambda _p: False, draws=10, seed=1)
    assert rate == 0.0
    rate = S.y_block_null_pass_rate(y, lambda _p: True, draws=10, seed=1)
    assert rate == 1.0


def test_murphy_reliability_decomposition_reconstructs_brier() -> None:
    rng = np.random.default_rng(7)
    p = rng.uniform(0.05, 0.95, size=800)
    y = (rng.uniform(size=800) < p).astype(float)
    out = S.murphy_reliability(p, y)
    brier = float(((p - y) ** 2).mean())
    assert out["brier_check"] == pytest.approx(brier, abs=0.02)
    assert 0.0 <= out["reliability"] < 0.05, "잘 보정된 표본은 신뢰도 오차가 작다"
    assert out["curve"] and all(0 <= b["obs"] <= 1 for b in out["curve"])


def test_family_p_binomial_bounds() -> None:
    assert S.family_p_binomial(0, 9) == pytest.approx(1.0)
    assert S.family_p_binomial(9, 9) == pytest.approx(0.05 ** 9)
    assert 0 < S.family_p_binomial(3, 9) < 0.01


def test_episode_runs_counts_regimes_not_days() -> None:
    # 사건 100일이 한 덩어리면 국면은 1개다 — 이것이 설계창 vix30 계열의 실제 모양이었다.
    y = np.array([0.0] * 50 + [1.0] * 100 + [0.0] * 50)
    assert S.episode_runs(y) == {"event_runs": 1, "non_event_runs": 2}
    scattered = np.array([0.0, 1.0] * 50)
    assert S.episode_runs(scattered)["event_runs"] == 50
    with_nan = np.array([1.0, np.nan, 1.0, 0.0])
    assert S.episode_runs(with_nan) == {"event_runs": 1, "non_event_runs": 1}, "NaN 은 구간을 끊지 않는다"


def test_degeneracy_report_separates_count_pass_from_episode_fail() -> None:
    # 사건 100·비사건 100 → 사건 수 가드 통과, 국면 2개 → 국면 가드 실패
    single_regime = np.array([0.0] * 100 + [1.0] * 100)
    report = S.degeneracy_report(single_regime, min_events=20, min_episodes=5)
    assert report["events"] == 100 and report["non_events"] == 100
    assert report["counts_ok"] is True
    assert report["episodes_ok"] is False
    assert report["verdict"] == "episode_thin"
    # 사건 3개 → 채점 자체가 불가능
    starved = np.array([1.0] * 3 + [0.0] * 200)
    assert S.degeneracy_report(starved, min_events=20, min_episodes=5)["verdict"] == "untestable_by_construction"
    # 국면이 흩어져 있으면 통과
    healthy = np.tile(np.array([1.0] * 10 + [0.0] * 10), 8)
    ok = S.degeneracy_report(healthy, min_events=20, min_episodes=5)
    assert ok["verdict"] == "ok" and ok["counts_ok"] and ok["episodes_ok"]


def test_episode_spans_reports_regime_boundaries() -> None:
    dates = np.array([f"2011-0{m}-01" for m in range(1, 10)], dtype=object)
    y = np.array([0.0, 1.0, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0])
    spans = S.episode_spans(dates, y, 1.0)
    assert [(s["start"], s["end"], s["n"]) for s in spans] == [
        ("2011-02-01", "2011-03-01", 2), ("2011-06-01", "2011-06-01", 1)]
