from datetime import date, timedelta

from ai_fc.timeseries_v7_r4.full_analog_trajectories import sample_analog_trajectories


def test_samples_unique_spaced_actual_paths_using_only_origin_available_prices():
    start = date(2020, 1, 1)
    rows = []
    price = 100.0
    for index in range(260):
        session = (start + timedelta(days=index)).isoformat()
        price *= 1.0 + ((index % 9) - 4) / 1000.0
        rows.append({"origin_session": session, "price": price, "pit_pass": True,
                     "origin_cutoff_at": session + "T23:59:00+00:00",
                     "max_available_at": session + "T20:00:00+00:00"})

    report = sample_analog_trajectories(rows, rows[-1]["origin_session"],
                                        trajectory_length=63, minimum_spacing_sessions=63)

    assert report["trajectory_count"] == 4
    assert report["duplicate_count"] == 0
    assert report["actual_contiguous_returns"] is True
    assert report["endpoint_interpolation_used"] is False
    assert all(len(item["returns"]) == 63 for item in report["trajectories"])
    assert all(item["end_session"] < rows[-1]["origin_session"]
               for item in report["trajectories"])
    starts = [item["start_index"] for item in report["trajectories"]]
    assert all(right - left >= 63 for left, right in zip(starts, starts[1:]))
    assert isinstance(report["maximum_drawdown"], float)
    assert 0.0 <= report["first_touch_rate"] <= 1.0
    assert 0.0 <= report["recovery_rate"] <= 1.0
