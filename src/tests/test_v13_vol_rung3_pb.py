"""rung-3 PB 기준선 도구의 순수 함수 — champion 규칙·PAV·cross-fit 무누수·쌍대 부호 규약."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import v13_vol_rung3_pb as rung3  # noqa: E402  — ImportError 는 스킵이 아니라 실패여야 한다


def test_pb_feature_is_single_column() -> None:
    feat = rung3.pb_features([1.0, 2.0, 3.0])
    assert feat.shape == (3, 1)


def _cell(*, ewma_both, nc_inc, pb_adopted, nc_pb):
    return {"ewma_vs_pb": {"ewma_beats_pb_both": ewma_both},
            "neg_control_increment_pass_rate": nc_inc,
            "pb_vs_clim": {"adopted": pb_adopted},
            "neg_control_pb_pass_rate": nc_pb}


def test_champion_rule_three_branches() -> None:
    assert rung3.champion_rule(_cell(ewma_both=True, nc_inc=0.05, pb_adopted=True, nc_pb=0.0)) == "ewma_logit"
    # 증분 귀무 누수(>0.10) → EWMA 탈락 → PB 가 기후 통과면 PB
    assert rung3.champion_rule(_cell(ewma_both=True, nc_inc=0.20, pb_adopted=True, nc_pb=0.02)) == "persistence_pb"
    assert rung3.champion_rule(_cell(ewma_both=False, nc_inc=None, pb_adopted=True, nc_pb=0.02)) == "persistence_pb"
    # PB 도 기후를 못 이기거나 귀무 누수 → hold
    assert rung3.champion_rule(_cell(ewma_both=False, nc_inc=None, pb_adopted=False, nc_pb=None)) == "hold"
    assert rung3.champion_rule(_cell(ewma_both=False, nc_inc=None, pb_adopted=True, nc_pb=0.30)) == "hold"
    # 귀무 미실행(None) 은 통과가 아니다 — fail-closed
    assert rung3.champion_rule(_cell(ewma_both=True, nc_inc=None, pb_adopted=True, nc_pb=None)) == "hold"


def test_finalist_id_is_null_when_all_hold_and_stable_otherwise() -> None:
    assert rung3.finalist_id({"a": "hold", "b": "hold"}) is None
    one = rung3.finalist_id({"a": "ewma_logit", "b": "hold"})
    two = rung3.finalist_id({"b": "hold", "a": "ewma_logit"})
    assert one == two and one.startswith("V13VOL_champion_") and len(one) == len("V13VOL_champion_") + 12
    assert rung3.finalist_id({"a": "persistence_pb"}) != one


def test_pav_matches_hand_computed_case_and_is_monotone() -> None:
    pmap = rung3.pav([0.1, 0.2, 0.3, 0.4], [0, 1, 0, 1])
    # 블록: {0.1}→0 · {0.2,0.3}→0.5 · {0.4}→1
    assert pmap["value"] == [0.0, 0.5, 1.0]
    assert pmap["p_max"] == [0.1, 0.3, 0.4]
    applied = rung3.apply_pav(pmap, [0.05, 0.1, 0.25, 0.3, 0.35, 0.9])
    assert np.all(np.diff(applied) >= 0)
    assert applied[0] == pytest.approx(1e-6) and applied[-1] == pytest.approx(1 - 1e-6)
    rng = np.random.default_rng(0)
    p = rng.uniform(size=200); y = (rng.uniform(size=200) < p).astype(float)
    values = rung3.pav(p, y)["value"]
    assert np.all(np.diff(values) >= 0)


def test_cross_fit_isotonic_is_leak_free_with_embargo() -> None:
    rng = np.random.default_rng(1)
    n = 400; h = 21
    x = rng.normal(size=n)
    feat = np.column_stack([x, x + rng.normal(scale=0.1, size=n)])
    y = (x + rng.normal(size=n) > 0).astype(float)
    fit_mask = np.zeros(n, bool); fit_mask[50:350] = True
    out = rung3.cross_fit_isotonic(feat, y, fit_mask, h, k=5)
    assert len(out["folds"]) == 5
    for fold in out["folds"]:
        assert fold["train_gap_ok"] is True
        # 학습 인덱스가 fold ± embargo 와 겹치지 않는다
        assert fold["train_min"] < fold["start"] - h or fold["train_min"] > fold["end"] + h
    assert np.isfinite(out["oof_p"]).all()
    assert np.all(np.diff(out["map"]["value"]) >= 0)


def test_paired_model_ci_sign_convention_detects_the_better_model() -> None:
    # a=PB 역할(정보 없는 잡음 피처), b=EWMA 역할(정보 피처): d = BS_a − BS_b > 0 ⇒ ewma_beats_pb True.
    # 같은 피처를 양쪽에 넣으면 부호 뒤바뀜을 못 잡으므로(검토 지적) 서로 다른 피처로 검정한다.
    rng = np.random.default_rng(2)
    n = 400
    x = rng.normal(size=n)
    y = (2.0 * x + 0.3 * rng.normal(size=n) > 0).astype(float)
    noise = np.column_stack([rng.normal(size=n)])
    signal = np.column_stack([x])
    me = np.zeros(n, bool); me[:200] = True; ml = ~me
    out = rung3.paired_model_ci(noise, signal, y, me, ml, seed=3, b=200)
    for name in ("early_to_late", "late_to_early"):
        assert out[name]["paired_mean_pb_minus_ewma"] > 0
        assert out[name]["ewma_beats_pb"] is True and out[name]["ewma_significantly_worse"] is False
    assert out["ewma_beats_pb_both"] is True
    # 뒤집으면 부호도 뒤집힌다
    flipped = rung3.paired_model_ci(signal, noise, y, me, ml, seed=3, b=200)
    assert flipped["ewma_beats_pb_both"] is False
    assert flipped["early_to_late"]["ewma_significantly_worse"] is True
    same = rung3.paired_model_ci(signal, signal, y, me, ml, seed=3, b=50)
    assert same["early_to_late"]["paired_mean_pb_minus_ewma"] == pytest.approx(0.0)


def test_family_p_binomial() -> None:
    assert rung3.family_p_binomial(0) == pytest.approx(1.0)
    assert rung3.family_p_binomial(9) == pytest.approx(0.05 ** 9)
    assert 0 < rung3.family_p_binomial(3) < 0.01
