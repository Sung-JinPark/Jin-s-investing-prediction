"""rung-3 PB 기준선 도구의 순수 함수 — champion 규칙·PAV·cross-fit 무누수·쌍대 부호 규약."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
rung3 = pytest.importorskip("v13_vol_rung3_pb")


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


def test_paired_model_ci_sign_convention() -> None:
    rng = np.random.default_rng(2)
    n = 300
    x = rng.normal(size=n)
    y = (x + rng.normal(size=n) > 0).astype(float)
    feat = np.column_stack([x])
    me = np.zeros(n, bool); me[:150] = True; ml = ~me
    same = rung3.paired_model_ci(feat, feat, y, me, ml, seed=3, b=50)
    for name in ("early_to_late", "late_to_early"):
        assert same[name]["paired_mean_pb_minus_ewma"] == pytest.approx(0.0)
        assert same[name]["ewma_beats_pb"] is False
    assert same["ewma_beats_pb_both"] is False


def test_family_p_binomial() -> None:
    assert rung3.family_p_binomial(0) == pytest.approx(1.0)
    assert rung3.family_p_binomial(9) == pytest.approx(0.05 ** 9)
    assert 0 < rung3.family_p_binomial(3) < 0.01
