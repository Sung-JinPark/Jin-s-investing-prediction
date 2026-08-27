from __future__ import annotations

import numpy as np
import pytest

from ai_fc.timeseries_v7_r5.event_multiplier import (
    event_flags,
    event_multiplier_samples,
    parse_bls_schedule,
    parse_fomc_schedule,
)


def test_official_schedule_parsers_extract_only_registered_event_kinds() -> None:
    bls = b"<tr>Friday, January 09, 2015 08:30 AM Employment Situation for December</tr>" \
          b"<tr>Friday, January 16, 2015 08:30 AM Consumer Price Index for December</tr>"
    fed = b"<h5>January 27-28 Meeting - 2015</h5><h5>March 4 Conference Call - 2015</h5>"
    assert [(row["kind"], row["date"]) for row in parse_bls_schedule(bls, 2015)] == [
        ("nfp", "2015-01-09"), ("cpi", "2015-01-16")]
    assert [(row["kind"], row["date"]) for row in parse_fomc_schedule(fed, 2015)] == [
        ("fomc", "2015-01-28")]


def test_event_window_is_strictly_after_origin_and_through_label_end() -> None:
    events = [{"kind": "fomc", "date": "2020-01-03"},
              {"kind": "cpi", "date": "2020-01-02"},
              {"kind": "nfp", "date": "2020-01-10"}]
    assert event_flags(events, origin="2020-01-02", label_end="2020-01-03") == (1, 0, 0)


def test_zero_gamma_is_exact_e0_and_positive_gamma_expands() -> None:
    e0 = np.asarray([-1.0, 0.0, 1.0], dtype=np.float64)
    nested = event_multiplier_samples(e0, flags=(1, 1, 1), gammas=(0.0, 0.0, 0.0))
    expanded = event_multiplier_samples(e0, flags=(1, 0, 0), gammas=(3.0, 0.0, 0.0))
    assert np.array_equal(nested, e0)
    assert np.std(expanded, ddof=1) == pytest.approx(2 * np.std(e0, ddof=1))
