import pytest

from ai_fc.timeseries_v7_r4.cross_fit_calibration import (
    CalibrationCase,
    fit_cross_fit_calibrator,
    one_sided_hit_rates,
)


def _case(name, samples, outcome, role="calibration"):
    return CalibrationCase(name, role, tuple(samples), outcome)


def test_fit_uses_only_calibration_role_and_fits_all_four_components():
    cases = [
        _case("a", (-3, -1, 0, 1, 2), -2),
        _case("b", (-2, -1, 0, 2, 4), 3),
        _case("c", (-4, -2, 0, 1, 3), 0.5),
    ]
    fitted = fit_cross_fit_calibrator(cases)
    assert fitted.fitted_case_ids == ("a", "b", "c")
    assert fitted.central_scale > 0
    assert fitted.negative_tail_scale > 0
    assert fitted.positive_tail_scale > 0

    with pytest.raises(ValueError, match="calibration role"):
        fit_cross_fit_calibrator(cases + [_case("future", (-1, 0, 1), 99, "outer")])
    with pytest.raises(ValueError, match="calibration role"):
        fit_cross_fit_calibrator(cases + [_case("future", (-1, 0, 1), 99, "prospective")])


def test_calibrated_quantiles_are_monotone_and_hits_are_one_sided():
    cases = [
        _case("a", (-4, -2, 0, 1, 2), -3),
        _case("b", (-2, -1, 0, 2, 5), 4),
        _case("c", (-3, -1, 0, 1, 3), 0),
    ]
    fitted = fit_cross_fit_calibrator(cases)
    quantiles = fitted.calibrate_quantiles((-3, -1, 0, 2, 4))
    assert quantiles == tuple(sorted(quantiles))
    assert one_sided_hit_rates(outcomes=(-2, 0, 3), lower=(-1, -1, 2), upper=(1, 1, 2)) == (1 / 3, 1 / 3)


def test_case_validation_rejects_nonfinite_and_unsorted_samples():
    with pytest.raises(ValueError):
        fit_cross_fit_calibrator([_case("bad", (0, -1, 1), 0)])
    with pytest.raises(ValueError):
        fit_cross_fit_calibrator([_case("bad", (-1, 0, float("nan")), 0)])
