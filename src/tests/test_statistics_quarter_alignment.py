"""Quarter-end stocks must pair with their own quarter's final price month."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
import json

import pytest

from ai_fc import statistics_lab as lab


def _points(values: dict[str, float]) -> list[dict]:
    return [{"date": observed, "value": value} for observed, value in sorted(values.items())]


def test_quarter_end_stock_uses_march_and_june_instead_of_january_and_april() -> None:
    prices = _points({"2026-01-01": 100, "2026-02-01": 200, "2026-03-01": 300,
                      "2026-04-01": 400, "2026-05-01": 500, "2026-06-01": 800})
    balances = _points({"2026-01-01": 10, "2026-04-01": 20})
    original = deepcopy((prices, balances))
    assert lab._quarter_end_ratio(prices, balances, as_of=date(2026, 6, 30)) == [
        {"date": "2026-03-01", "value": 30},
        {"date": "2026-06-01", "value": 40},
    ]
    assert (prices, balances) == original


@pytest.mark.parametrize("quarter_start,price_month,quarter_end", [
    ("1995-01-01", "1995-03-01", date(1995, 3, 31)),
    ("2026-04-01", "2026-06-01", date(2026, 6, 30)),
    ("2026-07-01", "2026-09-01", date(2026, 9, 30)),
    ("2026-10-01", "2026-12-01", date(2026, 12, 31)),
])
def test_each_native_quarter_maps_to_its_end_month(quarter_start, price_month, quarter_end) -> None:
    result = lab._quarter_end_ratio(_points({price_month: 21}), _points({quarter_start: 7}),
                                   as_of=quarter_end)
    assert result == [{"date": price_month, "value": 3}]


def test_missing_quarter_end_price_has_no_previous_month_or_next_quarter_fallback() -> None:
    prices = _points({"2026-03-01": 100, "2026-04-01": 999,
                      "2026-05-01": 888, "2026-07-01": 777})
    balances = _points({"2026-01-01": 10, "2026-04-01": 20})
    audit = {}
    result = lab._quarter_end_ratio(prices, balances, as_of=date(2026, 7, 31), audit=audit)
    assert result == [{"date": "2026-03-01", "value": 10}]
    assert audit["missing_price_months"] == ["2026-06-01"]


def test_quarters_outside_price_history_are_audited_without_extending_history() -> None:
    audit = {}
    result = lab._quarter_end_ratio(
        _points({"1995-03-01": 100, "1995-06-01": 200}),
        _points({"1994-10-01": 10, "1995-01-01": 10, "1995-04-01": 20, "1995-07-01": 30}),
        as_of=date(1995, 12, 31), audit=audit,
    )
    assert result == [{"date": "1995-03-01", "value": 10},
                      {"date": "1995-06-01", "value": 10}]
    assert audit["missing_price_months"] == []
    assert audit["outside_price_coverage"] == 2


@pytest.mark.parametrize("as_of,expected_dates", [
    (date(2026, 6, 29), ["2026-03-01"]),
    (date(2026, 6, 30), ["2026-03-01", "2026-06-01"]),
])
def test_partial_current_quarter_cannot_use_future_quarter_end(as_of, expected_dates) -> None:
    result = lab._quarter_end_ratio(
        _points({"2026-03-01": 100, "2026-06-01": 200}),
        _points({"2026-01-01": 10, "2026-04-01": 20}), as_of=as_of,
    )
    assert [row["date"] for row in result] == expected_dates


def test_december_price_does_not_make_q4_complete_before_year_end() -> None:
    prices, balances = _points({"2026-12-01": 100}), _points({"2026-10-01": 20})
    assert lab._quarter_end_ratio(prices, balances, as_of=date(2026, 12, 30)) == []
    assert lab._quarter_end_ratio(prices, balances, as_of=date(2027, 1, 1)) == [
        {"date": "2026-12-01", "value": 5},
    ]


def test_quarter_join_keeps_the_registered_monthly_price_aggregation() -> None:
    daily = _points({"2026-03-27": 50, "2026-03-31": 90,
                     "2026-06-26": 120, "2026-06-29": 150})
    prices = lab._monthly(daily, "last")
    assert lab._quarter_end_ratio(prices, _points({"2026-01-01": 10, "2026-04-01": 30}),
                                  as_of=date(2026, 6, 30)) == [
        {"date": "2026-03-01", "value": 9},
        {"date": "2026-06-01", "value": 5},
    ]


@pytest.mark.parametrize("invalid_date", ["2026-02-01", "2026-04-02", "not-a-date"])
def test_noncanonical_quarter_balance_labels_are_rejected(invalid_date) -> None:
    with pytest.raises(lab.StatisticsLabError):
        lab._quarter_end_ratio(_points({"2026-06-01": 100}),
                               [{"date": invalid_date, "value": 20}], as_of=date(2026, 6, 30))


@pytest.mark.parametrize("side", ["price", "balance"])
@pytest.mark.parametrize("invalid_value", [0, -1, float("nan"), float("inf")])
def test_nonpositive_and_nonfinite_input_is_rejected_without_clipping(side, invalid_value) -> None:
    prices = _points({"2026-06-01": invalid_value if side == "price" else 100})
    balances = _points({"2026-04-01": invalid_value if side == "balance" else 20})
    with pytest.raises(lab.StatisticsLabError):
        lab._quarter_end_ratio(prices, balances, as_of=date(2026, 6, 30))


@pytest.mark.parametrize("side", ["price", "balance"])
def test_duplicate_input_months_are_rejected(side) -> None:
    prices, balances = _points({"2026-06-01": 100}), _points({"2026-04-01": 20})
    duplicated = prices if side == "price" else balances
    duplicated.append(dict(duplicated[0]))
    with pytest.raises(lab.StatisticsLabError):
        lab._quarter_end_ratio(prices, balances, as_of=date(2026, 6, 30))


def test_monthly_ratios_continue_to_use_each_matching_month() -> None:
    prices = _points({"2026-01-01": 100, "2026-02-01": 120, "2026-03-01": 150,
                      "2026-04-01": 180, "2026-05-01": 210, "2026-06-01": 240})
    money = _points({row["date"]: 10 for row in prices})
    result = lab._ratio(prices, money)
    assert [row["date"] for row in result] == [row["date"] for row in prices]
    assert [row["value"] for row in result] == [10, 12, 15, 18, 21, 24]


@pytest.fixture(scope="module")
def quarter_payload():
    from test_statistics_lab import _payload_inputs

    rows, receipts = _payload_inputs()
    # Keep unrelated source inputs intact. Replace the relevant quarters with
    # hand-computable prices and stocks, in BOTH comparison eras.
    replacements = {
        "NASDAQCOM": {"1995-01-01": 13, "1995-03-01": 300, "1995-04-01": 17, "1995-06-01": 800,
                      "2023-01-01": 11, "2023-03-01": 200, "2023-04-01": 19, "2023-06-01": 1500},
        "SPASTT01USM661N": {"1995-01-01": 7, "1995-03-01": 60, "1995-04-01": 11, "1995-06-01": 180,
                            "2023-01-01": 13, "2023-03-01": 100, "2023-04-01": 17, "2023-06-01": 300},
        "DABSHNO": {"1995-01-01": 10, "1995-04-01": 20,
                    "2023-01-01": 20, "2023-04-01": 50},
        "GFDEBTN": {"1995-01-01": 30, "1995-04-01": 60,
                    "2023-01-01": 25, "2023-04-01": 50},
    }
    for sid, values in replacements.items():
        for row in rows[sid]:
            if row["date"] in values:
                row["value"] = values[row["date"]]
    # The legacy shared fixture contains monthly federal-debt points. This
    # fixture explicitly supplies the registered quarterly stock observations.
    rows["GFDEBTN"] = [row for row in rows["GFDEBTN"] if int(row["date"][5:7]) in {1, 4, 7, 10}]
    original = deepcopy(rows)
    payload = lab.build_statistics_lab(rows, generated_at="2026-12-31T00:00:00+00:00", receipts=receipts)
    assert rows == original
    return payload, rows


@pytest.mark.parametrize("chart_id,era,expected_q2", [
    ("nasdaq_per_household_liquid_assets", "dotcom", 400 / 3),
    ("nasdaq_per_household_liquid_assets", "current", 300),
    ("spx_per_federal_debt", "dotcom", 150),
    ("spx_per_federal_debt", "current", 150),
])
def test_builder_aligns_both_eras_and_rebases_the_first_complete_quarter(quarter_payload, chart_id, era, expected_q2) -> None:
    payload, _ = quarter_payload
    chart = next(row for row in payload["charts"] if row["id"] == chart_id)
    series = next(row for row in chart["series"] if row["era"] == era)
    year = 1995 if era == "dotcom" else 2023
    q1, q2 = series["points"][:2]
    assert (q1["date"], q1["period"], q1["value"]) == (f"{year}-03-01", 2, 100)
    assert (q2["date"], q2["period"]) == (f"{year}-06-01", 5)
    assert q2["value"] == pytest.approx(expected_q2)


def test_full_history_uses_same_corrected_pairing_and_first_complete_quarter_base(quarter_payload) -> None:
    payload, _ = quarter_payload
    chart = next(row for row in payload["charts"] if row["id"] == "spx_per_federal_debt_full_history")
    points = next(row for row in chart["series"] if row["era"] == "current")["points"]
    assert points[:2] == [
        {"date": "1995-03-01", "period": 0, "value": 100},
        {"date": "1995-06-01", "period": 3, "value": 150},
    ]


def test_builder_does_not_convert_monthly_m2_ratio_to_a_quarterly_path(quarter_payload) -> None:
    payload, rows = quarter_payload
    chart = next(row for row in payload["charts"] if row["id"] == "nasdaq_per_m2")
    current = next(row for row in chart["series"] if row["era"] == "current")["points"]
    assert [row["date"] for row in current[:6]] == [f"2023-{month:02d}-01" for month in range(1, 7)]
    m2 = {row["date"]: row["value"] for row in rows["M2SL"]}
    assert current[0]["value"] == 100
    assert current[2]["value"] == pytest.approx((200 / m2["2023-03-01"]) / (11 / m2["2023-01-01"]) * 100)


@pytest.mark.parametrize("chart_id,price_measure", [
    ("nasdaq_per_household_liquid_assets", "last_trading_close_of_quarter_end_month"),
    ("spx_per_federal_debt", "quarter_end_month_average"),
    ("spx_per_federal_debt_full_history", "quarter_end_month_average"),
])
def test_chart_exposes_which_price_measure_and_join_audit_was_used(quarter_payload, chart_id, price_measure) -> None:
    payload, _ = quarter_payload
    chart = next(row for row in payload["charts"] if row["id"] == chart_id)
    alignment = chart["ratio_alignment"]
    assert alignment["method"] == "quarter_end_month_to_quarter_end_stock_v1"
    assert alignment["derived_date"] == "quarter_end_month_start"
    assert alignment["completed_quarters_only"] is True
    assert alignment["price_measure"] == price_measure
    assert alignment["missing_price_months"] == []


@pytest.mark.parametrize("price_sid", ["NASDAQCOM", "SPASTT01USM661N"])
def test_builder_rejects_an_internal_missing_price_month_instead_of_hiding_a_quarter(quarter_payload, price_sid) -> None:
    from test_statistics_lab import _payload_inputs

    _, source_rows = quarter_payload
    _, receipts = _payload_inputs()
    rows = deepcopy(source_rows)
    rows[price_sid] = [row for row in rows[price_sid] if row["date"] != "2023-06-01"]
    with pytest.raises(lab.StatisticsLabError, match="missing exact quarter-end price months"):
        lab.build_statistics_lab(rows, generated_at="2026-12-31T00:00:00+00:00", receipts=receipts)


@pytest.mark.parametrize("corrupt_alignment", [
    {"missing_price_months": ["2023-06-01"]},
    {"completed_quarters_only": False},
    {"derived_date": "quarter_start_label"},
])
def test_read_model_validator_rejects_corrupt_quarter_join_metadata(quarter_payload, corrupt_alignment) -> None:
    payload, _ = quarter_payload
    bad = deepcopy(payload)
    chart = next(row for row in bad["charts"] if row["id"] == "nasdaq_per_household_liquid_assets")
    chart["ratio_alignment"].update(corrupt_alignment)
    with pytest.raises(lab.StatisticsLabError, match="quarter-end ratio alignment"):
        lab.validate_statistics_lab(bad)


def test_read_model_validator_rejects_a_quarter_start_used_as_the_derived_price_date(quarter_payload) -> None:
    payload, _ = quarter_payload
    bad = deepcopy(payload)
    chart = next(row for row in bad["charts"] if row["id"] == "nasdaq_per_household_liquid_assets")
    chart["series"][0]["points"][0]["date"] = "1995-01-01"
    with pytest.raises(lab.StatisticsLabError, match="quarter-end ratio observation date"):
        lab.validate_statistics_lab(bad)


def test_read_model_validator_rejects_quarter_end_prices_before_the_quarter_is_complete(quarter_payload) -> None:
    payload, _ = quarter_payload
    bad = deepcopy(payload)
    bad["generated_at"] = "2026-12-30T23:59:59+00:00"
    with pytest.raises(lab.StatisticsLabError, match="quarter-end ratio observation date"):
        lab.validate_statistics_lab(bad)


def test_dashboard_projection_preserves_corrected_quarter_coordinates_without_point_dates(quarter_payload, tmp_path) -> None:
    payload, _ = quarter_payload
    latest = tmp_path / "data/statistics/dotcom_statistics_latest.json"
    latest.parent.mkdir(parents=True)
    latest.write_text(json.dumps(payload), encoding="utf-8")
    projected = lab.statistics_dashboard_projection(tmp_path)
    lab.validate_statistics_lab(projected, projected=True)
    chart_ids = {"nasdaq_per_household_liquid_assets", "spx_per_federal_debt",
                 "spx_per_federal_debt_full_history"}
    for chart_id in chart_ids:
        raw_chart = next(row for row in payload["charts"] if row["id"] == chart_id)
        view_chart = next(row for row in projected["charts"] if row["id"] == chart_id)
        assert view_chart["ratio_alignment"] == raw_chart["ratio_alignment"]
        for raw_series, view_series in zip(raw_chart["series"], view_chart["series"], strict=True):
            assert view_series["label"] == raw_series["label"]
            assert view_series["latest_date"] == raw_series["points"][-1]["date"]
            coordinates = {point["period"]: point["value"] for point in raw_series["points"]}
            for point in view_series["points"]:
                assert "date" not in point
                assert point["value"] == coordinates[point["period"]]
            for endpoint in (0, -1):
                assert view_series["points"][endpoint] == {
                    "period": raw_series["points"][endpoint]["period"],
                    "value": raw_series["points"][endpoint]["value"],
                }

    # Compact coordinates intentionally omit dates; the join audit must still
    # be validated rather than bypassed together with full-source date checks.
    invalid = deepcopy(projected)
    chart = next(row for row in invalid["charts"] if row["id"] == "spx_per_federal_debt")
    chart["ratio_alignment"]["missing_price_months"] = ["2023-06-01"]
    with pytest.raises(lab.StatisticsLabError, match="quarter-end ratio alignment"):
        lab.validate_statistics_lab(invalid, projected=True)
