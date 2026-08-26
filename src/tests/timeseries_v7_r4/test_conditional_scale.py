import pytest

from ai_fc.timeseries_v7_r4.conditional_scale import (
    ScaleCase,
    fit_conditional_scale,
)


def _case(case_id, state, central, actual, width):
    return ScaleCase(case_id, "calibration", state, central, actual, width)


def test_scale_varies_by_ex_ante_state_and_intervals_are_nested():
    rows = []
    for index in range(40):
        state = "normal" if index < 20 else "stress"
        shock = (1 if index % 2 else -1) * (.01 if state == "normal" else .04)
        rows.append(_case(str(index), state, .002, .002 + shock, .04))

    fitted = fit_conditional_scale(rows)
    normal = fitted.states["normal"]
    stress = fitted.states["stress"]

    assert stress.volatility_scale > normal.volatility_scale
    assert normal.central_scale == pytest.approx(stress.central_scale)
    assert normal.half_width_50 <= normal.half_width_80 <= normal.half_width_90
    assert stress.half_width_50 <= stress.half_width_80 <= stress.half_width_90


def test_fit_fails_closed_on_role_state_width_and_duplicate_identity():
    valid = _case("a", "normal", 0.0, .01, .02)
    with pytest.raises(ValueError, match="calibration role"):
        fit_conditional_scale([ScaleCase("x", "evaluation", "normal", 0, 0, .1)])
    with pytest.raises(ValueError, match="ex-ante state"):
        fit_conditional_scale([ScaleCase("x", "calibration", "", 0, 0, .1)])
    with pytest.raises(ValueError, match="positive"):
        fit_conditional_scale([ScaleCase("x", "calibration", "normal", 0, 0, 0)])
    with pytest.raises(ValueError, match="unique"):
        fit_conditional_scale([valid, valid])
