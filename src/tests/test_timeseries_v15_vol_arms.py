"""V15-VOL 팔 수식·설계창 재현 오라클 (명세 U5 §8.2). 설계창 2007-2014 만 읽는다 — 저장소 쓰기 0."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

from ai_fc.timeseries_v13 import features as F
from ai_fc.timeseries_v15_vol import arms as A
from ai_fc.timeseries_v15_vol import contracts as C
from ai_fc.timeseries_v15_vol import design_fit as D
from v15_vol_fixtures import ROOT, protected_hashes

sys.path.insert(0, str(ROOT / "tools"))
import v13_vol_rung3_pb as rung3  # noqa: E402  — ImportError 는 스킵이 아니라 실패여야 한다

CONSTANTS = json.loads((ROOT / C.CONSTANTS_RELATIVE).read_text(encoding="utf-8"))
TOL = 1e-9


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(C.ARMING_ENV, raising=False)
    before = protected_hashes()
    yield
    assert protected_hashes() == before


@pytest.fixture(scope="module")
def design() -> dict:
    cutoff = CONSTANTS["provenance"]["knowledge_cutoff"]
    panel = D.design_panel(ROOT, knowledge_cutoff=cutoff)
    frozen, _ = D.load_parent_frozen(ROOT)
    return {"panel": panel, "frozen": frozen, "cutoff": cutoff}


def test_r1_identity_and_monotone() -> None:
    for p in (1e-6, 0.01, 0.5, 0.99):
        assert abs(A.r1_platt(p, 0.0, 1.0) - p) < 1e-12
    grid = np.linspace(0.001, 0.999, 50)
    values = [A.r1_platt(p, 0.2, 1.3) for p in grid]
    assert all(b > a for a, b in zip(values, values[1:]))


def test_r2_lambda5_cases() -> None:
    tail = CONSTANTS["R2"]["jump_tail"]
    n_calm = CONSTANTS["R2"]["n_calm"]
    assert n_calm == 1108 and len(tail) == 11 and tail == sorted(tail)
    assert A.r2_lambda5(20.0, 25, tail, n_calm, calm=False) == 0.0
    # need > max tail → k=0 → λ1 = 0.5/(n+1)
    lam = A.r2_lambda5(10.0, 30, tail, n_calm, calm=True)
    assert abs(lam - (1 - (1 - 0.5 / (n_calm + 1)) ** 5)) < 1e-15
    assert abs(A.r2_lambda5(16.61, 25, tail, n_calm, calm=True) - 0.006744579688804819) < 1e-12
    need = math.log(25 / 19.92)
    assert sum(1 for j in tail if j >= need) == 10


def test_r2_jump_and_r3_mix_bounds() -> None:
    for p in (0.0, 0.1, 0.9):
        assert A.r2_jump(p, 0.0) == p
        assert A.r2_jump(p, 0.05) >= p
    for p, c in ((0.1, 0.6), (0.7, 0.2)):
        v = A.r3_regime_mix(p, c)
        assert min(p, c) <= v <= max(p, c)


def test_log_score_clip() -> None:
    assert A.log_score(0.0, 1.0) == pytest.approx(math.log(1e-6))
    assert A.log_score(1.0, 0.0) == pytest.approx(math.log(1e-6))
    assert A.brier(0.3, 1.0) == pytest.approx(0.49)


def test_is_calm_rules() -> None:
    vix = {"name": "vix25_h5", "target": "vix_touch", "K": 25, "h": 5}
    rv = {"name": "rv_h5", "target": "rv_exceedance", "theta": 0.1694, "h": 5}
    assert A.is_calm(vix, {"vix_close": 19.99}) and not A.is_calm(vix, {"vix_close": 20.0})
    assert A.is_calm(rv, {"rv21_ann": 0.1694}) and not A.is_calm(rv, {"rv21_ann": 0.16942071054680877})


def _assert_close(expected, actual, path="") -> None:
    if isinstance(expected, dict):
        assert set(expected) == set(actual), path
        for key in expected:
            _assert_close(expected[key], actual[key], f"{path}.{key}")
    elif isinstance(expected, list):
        assert len(expected) == len(actual), path
        for i, (e, a) in enumerate(zip(expected, actual)):
            _assert_close(e, a, f"{path}[{i}]")
    elif isinstance(expected, float) and not isinstance(expected, bool):
        assert abs(expected - float(actual)) <= TOL, (path, expected, actual)
    else:
        assert expected == actual, (path, expected, actual)


def test_design_window_oracle_reproduces_frozen_constants() -> None:
    body = D.build_constants(ROOT, knowledge_cutoff=CONSTANTS["provenance"]["knowledge_cutoff"])
    frozen = {k: v for k, v in CONSTANTS.items() if k not in ("provenance", "content_hash")}
    _assert_close(frozen, json.loads(json.dumps(body)))


def test_spec_table_values() -> None:
    table = {  # 명세 §3.3 r2 표(소수 6자리) — a0, b0, n_oof, cond calm, cond stress
        "vix25_h5": (0.205624, 1.323215, 2004, 0.009964, 0.670718),
        "vix25_h21": (-0.024410, 1.060221, 1972, 0.114469, 0.789123),
        "vix30_h63": (-0.247715, 0.721968, 1888, 0.161932, 0.696089),
        "rv_h5": (0.013422, 1.569393, 1988, 0.124117, 0.976048),
        "rv_h63": (-0.042231, 1.085015, 1888, 0.753927, 0.993976),
    }
    for cell, (a0, b0, n, calm, stress) in table.items():
        r1 = CONSTANTS["R1"]["cells"][cell]
        r3 = CONSTANTS["R3"]["cells"][cell]
        assert abs(r1["a0"] - a0) <= 1e-6 and abs(r1["b0"] - b0) <= 1e-6 and r1["n_oof"] == n
        assert abs(r3["calm"] - calm) <= 1e-6 and abs(r3["stress"] - stress) <= 1e-6
    assert CONSTANTS["R2"]["max_calm_jump_date"] == "2007-02-27"
    assert abs(CONSTANTS["R2"]["max_calm_jump"] - 0.496008) < 1e-6


def test_design_panel_refuses_post_2014(monkeypatch) -> None:
    original = F.build_panel

    def leaky(observations, *, start, end=None):
        panel = original(observations, start=start, end=end)
        panel["dates"] = np.append(panel["dates"], "2015-01-02")
        return panel

    monkeypatch.setattr(F, "build_panel", leaky)
    with pytest.raises(D.DesignWindowError):
        D.design_panel(ROOT, knowledge_cutoff=CONSTANTS["provenance"]["knowledge_cutoff"])


def test_oof_embargo_zero_equals_rung3_dir_preds(design) -> None:
    panel, frozen = design["panel"], design["frozen"]
    early = np.array([str(d) for d in panel["dates"]]) < D.SPLIT
    for spec in C.cell_specs():
        x, y, _ = D._cell_xy(spec, panel, frozen)
        oof, flag = D.pb_oof_cross_transfer(x, y, early, embargo=0)
        m = np.isfinite(y)
        me, ml = early & m, ~early & m
        feat = x.reshape(-1, 1)
        assert np.max(np.abs(oof[ml] - rung3._dir_preds(feat, y, me, ml))) < 1e-12
        assert np.max(np.abs(oof[me] - rung3._dir_preds(feat, y, ml, me))) < 1e-12
        h = spec["h"]
        oof_h, flag_h = D.pb_oof_cross_transfer(x, y, early, embargo=h)
        split = int(np.argmax(~early))
        assert np.all(flag_h[split - h:split] == -1) and np.all(np.isnan(oof_h[split - h:split]))
        assert int(np.isfinite(oof_h).sum()) == CONSTANTS["R1"]["cells"][spec["name"]]["n_oof"]


def test_stratified_platt_recovers_and_differs_from_pooled() -> None:
    rng = np.random.default_rng(20261111)
    n = 4000
    direction = (np.arange(n) >= n // 2).astype(int)
    z = np.where(direction == 0, rng.normal(-2.0, 1.0, n), rng.normal(1.0, 1.0, n))
    intercept = np.where(direction == 0, -1.0, 1.0)
    prob = 1 / (1 + np.exp(-(intercept + 1.5 * z)))
    y = (rng.random(n) < prob).astype(float)
    X = np.column_stack([(direction == 0).astype(float), (direction == 1).astype(float), z])
    coef, converged, _ = D.newton_logit(X, y, (0.0, 0.0, 1.0))
    assert converged
    assert abs(coef[0] + 1.0) < 0.1 and abs(coef[1] - 1.0) < 0.1 and abs(coef[2] - 1.5) < 0.1
    pooled, ok, _ = D.newton_logit(np.column_stack([np.ones(n), z]), y, (0.0, 1.0))
    assert ok and abs(pooled[1] - coef[2]) > 0.1          # Simpson — pooled 기울기는 층화와 다르다


def test_design_convergence_flags() -> None:
    cells = CONSTANTS["R1"]["cells"]
    assert all(cells[c]["converged"] is True for c in C.CELL_ORDER)
    assert cells["vix30_h63"]["by_direction"]["l2e"]["converged"] is False
    assert cells["vix30_h63"]["by_direction"]["l2e"]["b"] == "non_convergent"


def test_ridge_slope_ratio_oracle(design) -> None:
    for spec in C.cell_specs():
        ratio = D.ridge_slope_ratio(spec, design["panel"], design["frozen"])
        assert abs(ratio - CONSTANTS["R1"]["cells"][spec["name"]]["ridge_slope_ratio"]) <= TOL
    assert round(CONSTANTS["R1"]["cells"]["vix25_h5"]["ridge_slope_ratio"], 4) == 1.2966
    assert round(CONSTANTS["R1"]["cells"]["rv_h5"]["ridge_slope_ratio"], 4) == 1.6149
