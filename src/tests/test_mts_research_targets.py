"""표적 계약 테스트 — T17·T18·T19·T20 + 실제 V13 추정식과의 수치 일치."""

from __future__ import annotations

import math

import numpy as np
import pytest

from ai_fc.mts_research.targets import (
    EligibilityRule,
    EventTargetSpec,
    MtsTargetError,
    decompose_rv21,
    evaluate_event_target,
    known_variance_contribution,
    log_returns,
    rv21_annualized,
)
from mts_research_fixtures import synthetic_calendar_ref


def _vix_spec(h: int = 5, *, eligibility: EligibilityRule | None = None) -> EventTargetSpec:
    return EventTargetSpec(
        target_id=f"syn_vix25_h{h}",
        instrument_id="VIX",
        observation_field="official_close",
        boundary=">=",
        threshold=25.0,
        horizon_sessions=h,
        eligibility=eligibility,
        label_revision_policy_id="first_available_v1",
        calendar=synthetic_calendar_ref(),
        unit="level",
    )


def _rv_spec(h: int = 5) -> EventTargetSpec:
    return EventTargetSpec(
        target_id=f"syn_rv_h{h}",
        instrument_id="NASDAQCOM",
        observation_field="official_close",
        boundary=">",
        threshold=0.1694,
        horizon_sessions=h,
        label_revision_policy_id="first_available_v1",
        calendar=synthetic_calendar_ref(),
        unit="annualized_vol",
    )


def test_t19_equality_boundary_contracts():
    """임계와 정확히 같은 값: VIX `>=` 양성 / RV `>` 음성 (T19)."""
    vix = evaluate_event_target(
        _vix_spec(3), origin_session="2026-10-20", future_values=[20.0, 25.0, 20.0]
    )
    assert vix.status == "OBSERVED_1" and vix.first_touch_k == 2
    rv = evaluate_event_target(
        _rv_spec(3), origin_session="2026-10-20", future_values=[0.10, 0.1694, 0.12]
    )
    assert rv.status == "OBSERVED_0" and rv.first_touch_k is None


def test_t17_missing_sessions_unresolved_not_zero():
    """누락 세션 때문에 사건을 배제할 수 없으면 UNRESOLVED — 0 금지 (T17)."""
    row = evaluate_event_target(
        _vix_spec(3), origin_session="2026-10-20", future_values=[20.0, None, 21.0]
    )
    assert row.status == "UNRESOLVED" and row.sessions_missing == 1
    # 관측된 구간에서 이미 돌파했다면 누락과 무관하게 양성
    touched = evaluate_event_target(
        _vix_spec(3), origin_session="2026-10-20", future_values=[26.0, None, None]
    )
    assert touched.status == "OBSERVED_1" and touched.first_touch_k == 1


def test_t18_not_eligible_blocks_probability_zero():
    """eligibility 밖 원점은 NOT_ELIGIBLE — 확률 0 발행 경로가 없다 (T18)."""
    rule = EligibilityRule(rule_id="v14_vix_calm", field="vix_close", boundary="<", threshold=20.0)
    row = evaluate_event_target(
        _vix_spec(3, eligibility=rule),
        origin_session="2026-10-20",
        future_values=[26.0, 27.0, 28.0],
        eligibility_value=21.0,  # VIX_t=21 — calm 아님 (strict <)
    )
    assert row.status == "NOT_ELIGIBLE" and row.first_touch_k is None
    boundary = evaluate_event_target(
        _vix_spec(3, eligibility=rule),
        origin_session="2026-10-20",
        future_values=[26.0, 27.0, 28.0],
        eligibility_value=20.0,  # 정확히 20 — strict < 라 여전히 부적격 (V14 계약)
    )
    assert boundary.status == "NOT_ELIGIBLE"
    eligible = evaluate_event_target(
        _vix_spec(3, eligibility=rule),
        origin_session="2026-10-20",
        future_values=[26.0, 27.0, 28.0],
        eligibility_value=19.9,
    )
    assert eligible.status == "OBSERVED_1"


def test_partial_window_rejected():
    with pytest.raises(MtsTargetError):
        evaluate_event_target(_vix_spec(5), origin_session="2026-10-20",
                              future_values=[20.0, 21.0])


def test_rv21_matches_frozen_v13_estimator():
    """mts rv21 이 실제 V13 구현(rolling_std_ddof1 × sqrt252)과 수치 일치한다."""
    from ai_fc.timeseries_v13.features import rolling_std_ddof1

    rng = np.random.default_rng(20261026)
    prices = 1000.0 * np.exp(np.cumsum(rng.normal(0, 0.01, 120)))
    ours = rv21_annualized(prices)
    r = log_returns(prices)
    theirs = rolling_std_ddof1(r, 21) * math.sqrt(252)
    assert np.allclose(ours[21:], theirs[21:], rtol=0, atol=1e-12, equal_nan=True)
    assert np.isnan(ours[:21]).all()


def test_t20_decomposition_recombines_exactly():
    """known/future (합·제곱합·n) 분해 재결합이 실제 추정식과 기계 오차 내 일치 (T20)."""
    rng = np.random.default_rng(7)
    prices = 1000.0 * np.exp(np.cumsum(rng.normal(0, 0.012, 200)))
    r = log_returns(prices)
    rv = rv21_annualized(prices)
    t = 100
    for k in (1, 5, 10, 20, 21):
        decomposition = decompose_rv21(r, t, k)
        assert decomposition.n_known == max(21 - k, 0)
        assert decomposition.n_future == min(k, 21)
        assert decomposition.recombine_ann() == pytest.approx(rv[t + k], abs=1e-12)
    # k=21 이면 알려진 부분이 없다
    assert decompose_rv21(r, t, 21).n_known == 0
    share = known_variance_contribution(r, t, 1)
    assert 0.0 < share < 1.0 and share > known_variance_contribution(r, t, 20)


def test_decomposition_rejects_nan_window():
    r = np.full(60, 0.01)
    r[30] = np.nan
    with pytest.raises(MtsTargetError):
        decompose_rv21(r, 25, 10)  # 창에 NaN — 추정식과 동일하게 거부
