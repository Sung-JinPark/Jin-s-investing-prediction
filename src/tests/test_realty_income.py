from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from ai_fc.realty_income import (
    RealtyIncomeError,
    append_dividends,
    build_dividend_crosscheck,
    build_dividend_monitor,
    load_event_registry,
    load_dividend_reference,
    significance_gate,
    fetch_hy_event_history,
    validate_macro_assumptions,
)


def test_hy_event_history_merges_pinned_legacy_capture() -> None:
    primary = "DATE,BAMLH0A0HYM2\n2026-08-01,3.0\n"
    legacy = "date,BAMLH0A0HYM2\n2000-01-03,5.0\n2001-01-03,7.0\n"
    def fetch(url: str, **_kwargs) -> str:
        return legacy if "raw.githubusercontent.com" in url else primary
    result = fetch_hy_event_history(fetch_text=fetch)
    assert result.dates[0] == date(2000, 1, 3)
    assert result.receipt["history_status"] == "legacy_public_fred_capture_plus_current"
    assert result.receipt["redistribution_policy"] == "derived_event_diagnostics_only"


def _macro() -> dict:
    return yaml.safe_load(
        """
probability_space: scenario_conditional
required_months: [0, 3, 6, 12]
realty_income_price_carry_pct: 0
scenarios:
  deleveraging: {delta_10y_bp: {0: 0, 3: -30, 6: -60, 12: -80}, delta_hy_bp: {0: 0, 3: 250, 6: 300, 12: 150}}
  easing_rotation: {delta_10y_bp: {0: 0, 3: -60, 6: -120, 12: -150}, delta_hy_bp: {0: 0, 3: 100, 6: 0, 12: -50}}
  soft_landing: {delta_10y_bp: {0: 0, 3: 0, 6: 10, 12: 20}, delta_hy_bp: {0: 0, 3: 0, 6: 0, 12: 0}}
  rates_stay_high: {delta_10y_bp: {0: 0, 3: 20, 6: 30, 12: 40}, delta_hy_bp: {0: 0, 3: 150, 6: 200, 12: 200}}
"""
    )


def _dividend(day: str, amount: float) -> dict:
    return {
        "ex_date": day, "amount": amount,
        "declared_at": "2026-08-04T00:00:00Z",
        "available_at": "2026-08-04T00:00:00Z",
        "source": "test", "source_url": "mock://dividend",
        "source_fingerprint": "same", "revision_vintage": "captured_current",
        "availability_semantics": "first_repository_capture_not_corporate_declaration",
    }


def test_macro_contract_rejects_missing_key_month() -> None:
    payload = _macro()
    payload["scenarios"]["deleveraging"]["delta_10y_bp"].pop(6)
    with pytest.raises(RealtyIncomeError, match="M0/M3/M6/M12"):
        validate_macro_assumptions(payload)


def test_significance_gate_zeros_crossing_or_short_beta() -> None:
    assert significance_gate(-8, -12, -4, 156) == (-8.0, "eligible")
    assert significance_gate(-8, -12, 1, 156) == (0.0, "ci_crosses_zero")
    used, status = significance_gate(-8, -12, -4, 155)
    assert used == 0
    assert status == "insufficient_sample_155_of_156"


def test_significance_gate_requires_two_consecutive_sample_failures() -> None:
    eligible = {
        "used_effect_per_100bp_pct": -8.0,
        "gate_hysteresis": {"consecutive_sample_failures": 0},
    }
    used, status = significance_gate(-7.5, -11, -3, 155, eligible)
    assert (used, status) == (-8.0, "hysteresis_hold_1_of_2")
    first_failure = {
        "used_effect_per_100bp_pct": used,
        "gate_hysteresis": {"consecutive_sample_failures": 1},
    }
    used, status = significance_gate(-7.0, -10, -2, 155, first_failure)
    assert used == 0
    assert status == "insufficient_sample_155_of_156"


def test_hysteresis_does_not_delay_ci_failure() -> None:
    previous = {
        "used_effect_per_100bp_pct": -8.0,
        "gate_hysteresis": {"consecutive_sample_failures": 0},
    }
    assert significance_gate(-7, -10, 2, 156, previous) == (
        0.0, "ci_crosses_zero")


def test_dividend_csv_is_append_only_and_detects_revision(tmp_path) -> None:
    path, changed = append_dividends(
        tmp_path, [_dividend("2026-06-01", .26), _dividend("2026-07-01", .26)])
    original = path.read_bytes()
    _, changed_again = append_dividends(
        tmp_path, [_dividend("2026-06-01", .26), _dividend("2026-07-01", .26)])
    assert changed is True and changed_again is False
    assert path.read_bytes() == original
    with pytest.raises(RealtyIncomeError, match="conflict"):
        append_dividends(tmp_path, [_dividend("2026-07-01", .25)])


def test_dividend_monitor_marks_maintenance_without_probability() -> None:
    rows = [_dividend(f"2026-{month:02d}-01", .25 + (month >= 6) * .01)
            for month in range(1, 9)]
    monitor = build_dividend_monitor(rows, asof=date(2026, 8, 4))
    assert monitor["c4_met"] is True
    assert monitor["cuts_last_12_events"] == 0
    assert "probability" not in monitor


def test_official_dividend_crosscheck_confirms_direction_not_exact_basis() -> None:
    root = Path(__file__).parents[2]
    reference = load_dividend_reference(root)
    rows = []
    for year, amount in zip(range(2001, 2006), (1.09, 1.12, 1.14, 1.21, 1.31)):
        rows.append(_dividend(f"{year}-12-01", amount))
    audit = build_dividend_crosscheck(rows, reference)
    assert audit["status"] == "direction_confirmed"
    assert audit["basis"]["exact_total_equality_asserted"] is False
    assert audit["annual"][-1]["official_paid_per_share"] == 1.346


def test_event_registry_is_fixed_to_six_preregistered_events(tmp_path) -> None:
    path = tmp_path / "data/rate_events/registry.yaml"
    path.parent.mkdir(parents=True)
    source = Path(__file__).parents[2] / "data/rate_events/registry.yaml"
    path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    payload = load_event_registry(tmp_path)
    assert len(payload["events"]) == 6
    assert payload["events"][4]["event_id"] == "acute_crisis_2020"
