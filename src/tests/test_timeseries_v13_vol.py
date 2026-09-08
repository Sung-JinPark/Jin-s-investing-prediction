"""V13-VOL 수치 계층 패리티 — numpy 패키지가 설계 러너(tools/v13_vol_run.py, pandas)와 같은 수를 낸다.

동결 계수 artifact 가 핀되어 있으면 계약·파일·content_hash·finalist 3자 대조도 실제 repo 에서 검사한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import yaml

from ai_fc.timeseries_v13 import contracts as C
from ai_fc.timeseries_v13 import features as F

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))


def _contract() -> dict:
    return yaml.safe_load((ROOT / C.CONTRACT_RELATIVE).read_text(encoding="utf-8"))


@pytest.mark.skipif(not (ROOT / "data/timeseries_v2").exists(), reason="market archive not present")
def test_features_match_pandas_design_panel() -> None:
    pytest.importorskip("pandas")
    R = pytest.importorskip("v13_vol_run")
    from ai_fc.timeseries_v2.market_archive import read_market_observations

    idx, vix, ndx, rv = R.load_panel()
    panel = F.build_panel(read_market_observations(ROOT), start=C.DESIGN_WINDOW[0], end=C.DESIGN_WINDOW[1])
    assert list(panel["dates"]) == [str(d)[:10] for d in idx]
    assert np.array_equal(panel["vix"], vix) and np.array_equal(panel["ndx"], ndx)
    nan_ref = np.isnan(rv); nan_new = np.isnan(panel["rv21"])
    assert np.array_equal(nan_ref, nan_new) and int(nan_new.sum()) == 21
    assert np.allclose(panel["rv21"][~nan_new], rv[~nan_ref], atol=1e-10, rtol=0)
    # 설계 러너와 같은 EWMA / NaN 채움 / 라벨
    assert np.allclose(F.ewma(vix), R._ewma(vix, 2 / 22), atol=0, rtol=0)
    median = float(np.nanmedian(rv[np.isfinite(rv)]))
    assert median == pytest.approx(0.1694207105468098)
    assert np.array_equal(F.fill_rv_nan(rv, median), np.where(np.isfinite(rv), rv, median))
    for K in (25, 30):
        for h in (5, 21, 63):
            assert np.array_equal(F.labels_vix(vix, K, h), R.labels_vix(vix, K, h), equal_nan=True)
    for h in (5, 21, 63):
        assert np.array_equal(F.labels_rv(rv, C.THETA_RV, h), R.labels_rv(rv, h), equal_nan=True)


def test_logit_fit_matches_tools_reference_on_synthetic_data() -> None:
    R = pytest.importorskip("v13_vol_run")
    rng = np.random.default_rng(7)
    X = np.column_stack([rng.normal(size=500), rng.normal(size=500)])
    y = ((X[:, 0] + 0.5 * X[:, 1] + rng.normal(size=500)) > 0).astype(float)
    b0, mu0, sd0 = R._logit_fit(X, y)
    b1, mu1, sd1 = F.logit_fit(X, y)
    assert np.allclose(b0, b1, atol=1e-12) and np.array_equal(mu0, mu1) and np.array_equal(sd0, sd1)
    assert np.allclose(R._logit_pred(b0, mu0, sd0, X), F.logit_predict(b1, mu1, sd1, X), atol=1e-12)
    # 조기 정지 적합은 같은 고정점에 수렴한다 (부트스트랩 전용 경로)
    b2, _, _ = F.logit_fit(X, y, tol=1e-9)
    assert np.allclose(b1, b2, atol=1e-7)


def test_ewma_runs_over_full_history_without_restart() -> None:
    rng = np.random.default_rng(3)
    x = np.abs(rng.normal(size=300)) + 10
    full = F.ewma(x)
    restarted = F.ewma(x[200:])
    # 재시작(시드 x[200]) 은 연속 실행과 다르다 — 라이브는 전체 이력에 연속 실행해야 한다
    assert not np.allclose(full[200:205], restarted[:5])
    assert np.allclose(full[295:], restarted[95:], atol=1e-3)  # 충분히 지나면 수렴


def test_rv_nan_fill_uses_frozen_median_not_recomputed() -> None:
    rv = np.array([np.nan, np.nan, 0.2, 0.4])
    filled = F.fill_rv_nan(rv, 0.1694207105468098)
    assert filled[0] == pytest.approx(0.1694207105468098) and filled[2] == 0.2
    assert F.fill_rv_nan(rv, 0.1694207105468098)[1] != np.nanmedian(rv)


def test_delta_band_is_inside_unit_interval() -> None:
    beta = np.array([-0.3, 1.2, 0.4]); mu = np.array([20.0, 20.0]); sd = np.array([8.0, 7.0])
    cov = np.array([[0.01, 0.001, 0.0], [0.001, 0.02, 0.002], [0.0, 0.002, 0.03]])
    p, se = F.delta_method_se(beta, cov, mu, sd, np.array([35.0, 28.0]))
    assert 0 < p < 1 and se > 0
    lo, hi = max(0.0, p - C.Z80 * se), min(1.0, p + C.Z80 * se)
    assert 0 <= lo <= p <= hi <= 1


def test_block_bootstrap_cov_is_symmetric_psd() -> None:
    rng = np.random.default_rng(5)
    X = np.column_stack([rng.normal(size=200)])
    y = ((X[:, 0] + rng.normal(size=200)) > 0).astype(float)
    cov = F.block_bootstrap_cov(X, y, seed=1, b=40)
    assert cov.shape == (2, 2) and np.allclose(cov, cov.T)
    assert np.all(np.linalg.eigvalsh(cov) >= -1e-12)


def test_pav_apply_is_monotone_and_clipped() -> None:
    pmap = F.pav([0.1, 0.2, 0.3, 0.4], [0, 1, 0, 1])
    assert pmap["value"] == [0.0, 0.5, 1.0]
    applied = F.pav_apply(pmap, np.array([0.0, 0.25, 0.9]))
    assert np.all(np.diff(applied) >= 0) and applied[0] == pytest.approx(1e-6)


def test_feature_matrix_shapes_and_names() -> None:
    level = np.array([1.0, 2.0]); smooth = np.array([1.0, 1.5])
    assert F.feature_matrix("ewma_logit", level, smooth).shape == (2, 2)
    assert F.feature_matrix("persistence_pb", level, None).shape == (2, 1)
    assert F.feature_names("ewma_logit", "vix_touch") == ["vix_close", "vix_close_ewma21"]
    assert F.feature_names("persistence_pb", "rv_exceedance") == ["rv21_ann"]
    with pytest.raises(ValueError):
        F.feature_matrix("garch", level, smooth)


def test_cell_specs_match_contract_targets() -> None:
    specs = C.cell_specs()
    targets = _contract()["targets"]
    assert [s["name"] for s in specs] == list(C.CELL_ORDER)
    assert sorted({s["K"] for s in specs if s["target"] == "vix_touch"}) == targets["vix_touch"]["K"]
    assert sorted({s["h"] for s in specs}) == targets["vix_touch"]["horizons"]
    assert all(s["theta"] == targets["rv_exceedance"]["theta"] for s in specs if s["target"] == "rv_exceedance")


def test_frozen_coefficients_pin_matches_contract_when_pinned() -> None:
    frozen = _contract()["frozen_coefficients"]
    if frozen["sha256"] is None:
        with pytest.raises(C.TimeSeriesV13VolError, match="not pinned"):
            C.load_frozen_coefficients(ROOT, expected_sha256=None, expected_content_hash=None,
                                       expected_finalist_id=None)
        pytest.skip("coefficients not frozen yet (Phase C pending)")
    payload = C.load_frozen_coefficients(ROOT, expected_sha256=frozen["sha256"],
                                         expected_content_hash=frozen["content_hash"],
                                         expected_finalist_id=frozen["finalist_id"])
    assert payload["reconciliation"]["pass"] is True
    champion = _contract()["gates"]["champion"]
    assert payload["finalist_id"] == champion["finalist_id"]
    for name, cell in payload["cells"].items():
        assert champion["cells"][name] == cell["model"]
        assert len(cell["beta"]) == 1 + len(cell["feature_names"])
        assert len(cell["mu"]) == len(cell["sd"]) == len(cell["feature_names"])
    with pytest.raises(C.TimeSeriesV13VolError, match="finalist"):
        C.load_frozen_coefficients(ROOT, expected_sha256=frozen["sha256"],
                                   expected_content_hash=frozen["content_hash"],
                                   expected_finalist_id="V13VOL_champion_000000000000")
