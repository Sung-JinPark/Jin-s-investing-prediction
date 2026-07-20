"""P1.7-S5: 옵션 내재 디지털 확률 테스트 — Black-Scholes 합성 체인 (네트워크 불필요)."""

from __future__ import annotations

import math
from datetime import date

import pytest

from ai_fc.market.options_bl import (
    OptionChain, _norm_cdf, nearest_expiry, prob_above, proxy_strike, RISK_FREE,
)

ASOF = date(2099, 6, 15)
EXPIRY = date(2099, 12, 18)
SPOT = 500.0
SIGMA = 0.25


def _bs_chain(sigma: float = SIGMA, strikes: range = range(400, 610, 10)) -> OptionChain:
    """플랫 IV 합성 체인 — prob_above가 정확히 N(d2)를 재현해야 한다."""
    chain = OptionChain(symbol="TEST", spot=SPOT)
    for k in strikes:
        chain.call_ivs[(EXPIRY, float(k))] = sigma
    return chain


def _analytic_n_d2(strike: float, sigma: float = SIGMA) -> float:
    t = (EXPIRY - ASOF).days / 365.0
    d2 = ((math.log(SPOT / strike) + (RISK_FREE - 0.5 * sigma ** 2) * t)
          / (sigma * math.sqrt(t)))
    return _norm_cdf(d2)


def test_prob_above_matches_analytic() -> None:
    chain = _bs_chain()
    for k in (450.0, 500.0, 550.0):
        r = prob_above(chain, EXPIRY, k, asof=ASOF)
        assert r is not None
        assert r.prob_above == pytest.approx(_analytic_n_d2(k), abs=1e-9)
        assert r.detail["measure"] == "risk-neutral"


def test_prob_monotone_decreasing_in_strike() -> None:
    chain = _bs_chain()
    probs = [prob_above(chain, EXPIRY, float(k), asof=ASOF).prob_above
             for k in range(420, 600, 20)]
    assert probs == sorted(probs, reverse=True)


def test_smile_interpolation() -> None:
    """스마일(행사가별 IV 상이) — 보간된 IV가 이웃 사이 값이어야 한다."""
    chain = OptionChain(symbol="TEST", spot=SPOT)
    chain.call_ivs[(EXPIRY, 480.0)] = 0.30
    chain.call_ivs[(EXPIRY, 520.0)] = 0.20
    r = prob_above(chain, EXPIRY, 500.0, asof=ASOF)
    assert r is not None and 0.20 < r.iv < 0.30
    assert r.iv == pytest.approx(0.25, abs=1e-9)  # 중간점 선형 보간


def test_sparse_or_missing_data_returns_none() -> None:
    empty = OptionChain(symbol="TEST", spot=SPOT)
    assert prob_above(empty, EXPIRY, 500.0, asof=ASOF) is None
    single = OptionChain(symbol="TEST", spot=SPOT)
    single.call_ivs[(EXPIRY, 500.0)] = 0.25  # 점 1개 — 보간 불가
    assert prob_above(single, EXPIRY, 500.0, asof=ASOF) is None


def test_nearest_expiry() -> None:
    chain = _bs_chain()
    chain.call_ivs[(date(2099, 9, 18), 500.0)] = 0.25
    assert nearest_expiry(chain, date(2099, 8, 1)) == date(2099, 9, 18)
    assert nearest_expiry(chain, date(2099, 10, 1)) == EXPIRY
    assert nearest_expiry(chain, date(2100, 6, 1)) == EXPIRY  # 이후 만기 없으면 마지막


def test_proxy_strike_ratio() -> None:
    # ^IXIC 26,206.89 / 현물 26,107 → QQQ 500 기준 등가 행사가
    k = proxy_strike(26206.89, 26107.0, 500.0)
    assert k == pytest.approx(500.0 * 26206.89 / 26107.0)
