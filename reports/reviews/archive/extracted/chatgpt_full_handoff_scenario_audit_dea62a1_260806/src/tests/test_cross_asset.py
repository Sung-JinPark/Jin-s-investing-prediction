from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pytest
import yaml

from ai_fc.cross_asset import (
    CrossAssetError,
    append_path_tracking_v2,
    _legacy_forecast_model,
    _dotcom_peak_reference,
    _persist_receipt_bundle,
    _persist_snapshot,
    build_cross_asset,
    refresh_cross_asset,
    upgrade_cross_asset_horizon,
    validate_cross_asset,
)
from ai_fc.quant.feed import YahooDividendResult, YahooPriceSeriesResult
from ai_fc.realty_income import FredSeries


ORIGINAL_2026_07_31_CANONICAL_SHA256 = (
    "16d8cfbb94565268b1b877bad46af2b72206164d7971bfcbdce07c02477ec792"
)
ROOT = Path(__file__).parents[2]


def _macro_assumptions() -> dict:
    return yaml.safe_load(
        (ROOT / "data/contracts/cross_asset_macro_assumptions.yaml")
        .read_text(encoding="utf-8"))


def _realty_sensitivity(*, rate: float = -8.0, credit: float = 0.0) -> dict:
    record = lambda used: {  # noqa: E731
        "measured_effect_per_100bp_pct": used,
        "bootstrap_10_90_pct": [used - 1, used + 1],
        "used_effect_per_100bp_pct": used,
        "status": "eligible" if used else "ci_crosses_zero",
        "observations": 156,
    }
    return {
        "asof": "2026-08-03", "status": "partial",
        "beta_rate": record(rate), "beta_credit": record(credit),
        "dividend_yield_ttm_pct": 5.5, "spread_vs_10y_pp": .8,
        "spread_percentile_since_2000": 62.0,
        "dividend_monitor": {"c4_met": True, "status": "maintained_or_increased"},
    }


def _months(start_year: int, start_month: int, count: int) -> list[date]:
    out = []
    for offset in range(count):
        total = start_year * 12 + start_month - 1 + offset
        out.append(date(total // 12, total % 12 + 1, 1))
    return out


def _price_path(count: int, drift: float, wave: float) -> list[float]:
    returns = drift + wave * np.sin(np.arange(count - 1) / 9)
    return [100.0, *list(100 * np.exp(np.cumsum(returns)))]


def _fixture(*, history_count: int = 61) -> dict:
    history_dates = _months(2001, 3, history_count)
    current_dates = [date(2020, 1, 1) + timedelta(days=index) for index in range(320)]
    nasdaq = _price_path(320, 0.0004, 0.009)
    bitcoin = _price_path(320, 0.0007, 0.016)
    realty = _price_path(320, 0.00025, 0.004)
    history_nasdaq = list(np.linspace(100, 89.3 if history_count == 62 else 72, 61))
    history_o_price = list(np.linspace(100, 173.8 if history_count == 62 else 180, 61))
    history_o_adjusted = list(np.linspace(100, 240.9 if history_count == 62 else 245, 61))
    return build_cross_asset(
        history_dates=history_dates,
        history_nasdaq=history_nasdaq + ([999] if history_count == 62 else []),
        history_o_price=history_o_price + ([999] if history_count == 62 else []),
        history_o_adjusted=history_o_adjusted + ([999] if history_count == 62 else []),
        current_dates=current_dates,
        current_nasdaq=nasdaq,
        current_bitcoin=bitcoin,
        current_o_adjusted=realty,
        anchors={"nasdaq": 25000, "bitcoin": 65000, "realty_income": 60},
        macro_assumptions=_macro_assumptions(),
        realty_sensitivity=_realty_sensitivity(),
        generated_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
    )


def _legacy_v2(model: dict) -> dict:
    legacy = deepcopy(model)
    legacy["schema_version"] = 2
    legacy["probability_space"] = "scenario_conditional"
    forecast = _legacy_forecast_model(
        model["forecast"]["beta_audit"],
        model["forecast"]["realty_income_sensitivity"],
        _macro_assumptions(),
    )
    forecast["horizon_months"] = 12
    forecast["labels"] = forecast["labels"][:13]
    forecast.pop("shock_origin", None)
    forecast.pop("source_snapshot_id", None)
    scenarios = {}
    for scenario_id, row in forecast["scenarios"].items():
        item = dict(row)
        item.pop("phase_notes", None)
        item["paths"] = {key: values[:13] for key, values in row["paths"].items()}
        item["paths_band"] = {
            key: {bound: values[:13] for bound, values in band.items()}
            for key, band in row["paths_band"].items()
        }
        item["beta_regime_by_month"] = row["beta_regime_by_month"][:13]
        item["realty_income_attribution"] = {
            key: values[:13] for key, values in row["realty_income_attribution"].items()
        }
        item["macro_assumptions"] = {
            **row["macro_assumptions"],
            "delta_10y_bp": row["macro_assumptions"]["delta_10y_bp"][:13],
            "delta_hy_bp": row["macro_assumptions"]["delta_hy_bp"][:13],
        }
        scenarios[scenario_id] = item
    forecast["scenarios"] = scenarios
    legacy["forecast"] = forecast
    return legacy


def test_cross_asset_keeps_observed_history_and_btc_counterfactual_separate() -> None:
    model = _fixture()
    assert model["probability_space"] == "reference_only"
    assert model["history"]["bitcoin"]["status"] == "not_available"
    assert model["history"]["summary"]["nasdaq_price_pct"] == pytest.approx(-28.0)
    assert model["history"]["summary"]["realty_income_total_return_pct"] == pytest.approx(145.0)
    assert model["forecast"]["weights"]["status"] == "not_applicable"
    assert model["schema_version"] == 4
    assert model["forecast"]["model_kind"] == "historical_counterfactual"
    assert model["forecast"]["horizon_months"] == 60
    assert model["forecast"]["labels"] == model["history"]["labels"]
    assert model["forecast"]["labels"][-1] == "2006-03"
    assert model["forecast"]["elapsed_labels"][-1] == "M+60"
    assert model["forecast"]["shock_origin"]["calendar_date_status"] == "observed_history"
    assert set(model["forecast"]["scenarios"]) == {
        "btc_low_beta", "btc_regime_center", "btc_high_beta", "btc_full_beta"
    }
    assert all(
        len(path) == 61
        for scenario in model["forecast"]["scenarios"].values()
        for path in scenario["paths"].values()
    )
    assert all(
        scenario["synthetic_assets"] == ["bitcoin"]
        for scenario in model["forecast"]["scenarios"].values()
    )


def test_historical_counterfactual_never_starts_a_live_path_ledger(tmp_path: Path) -> None:
    model = _fixture()
    _, persisted, _ = _persist_snapshot(tmp_path, model, force=False)
    day = date.fromisoformat(persisted["asof"])
    prices = {
        asset: YahooPriceSeriesResult(
            [day], [persisted["anchors"][asset]], [persisted["anchors"][asset]], {}, {})
        for asset in ("nasdaq", "bitcoin", "realty_income")
    }
    assert not append_path_tracking_v2(tmp_path, persisted, prices)
    assert not (tmp_path / "data/cross_asset/path_tracking_v2.csv").exists()
    assert all(
        len(bound) == 61
        for scenario in model["forecast"]["scenarios"].values()
        for asset in scenario["paths_band"].values()
        for bound in asset.values()
    )


def test_committed_2026_07_31_original_archive_is_byte_immutable() -> None:
    archive = (
        Path(__file__).parents[2]
        / "data"
        / "cross_asset"
        / "archive"
        / "2026-07-31.json"
    )
    # Git stores this text archive with LF. A pre-existing Windows worktree may
    # retain CRLF bytes even though the committed blob is identical, so hash the
    # canonical repository representation on every platform.
    canonical = archive.read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(canonical).hexdigest() == ORIGINAL_2026_07_31_CANONICAL_SHA256


def test_history_is_exactly_2001_03_to_2006_03_and_excludes_next_bar() -> None:
    model = _fixture(history_count=62)
    assert len(model["history"]["labels"]) == 61
    assert model["history"]["labels"][0] == "2001-03"
    assert model["history"]["labels"][-1] == "2006-03"
    assert model["history"]["period"] == "2001-03 to 2006-03"
    assert model["history"]["summary"]["nasdaq_price_pct"] == pytest.approx(-10.7)
    assert model["history"]["summary"]["realty_income_price_pct"] == pytest.approx(73.8)
    assert model["history"]["summary"]["realty_income_total_return_pct"] == pytest.approx(140.9)
    assert model["history"]["summary"]["realty_income_dividend_effect_pp"] == pytest.approx(67.1)


def test_validator_rejects_period_label_mismatch() -> None:
    model = _fixture()
    model["history"]["period"] = "2001-03 to 2006-04"
    with pytest.raises(CrossAssetError, match="period endpoints"):
        validate_cross_asset(model)


def test_btc_case_beta_rules_come_from_audited_center_and_bootstrap_bounds() -> None:
    model = _fixture()
    audit = model["forecast"]["beta_audit"]["bitcoin"]
    cases = model["forecast"]["scenarios"]
    assert cases["btc_low_beta"]["downside_beta"] == audit["downside_5y"]["bootstrap_10_90"][0]
    assert cases["btc_low_beta"]["upside_beta"] == audit["full_252d"]["bootstrap_10_90"][0]
    assert cases["btc_regime_center"]["downside_beta"] == audit["downside_5y"]["used"]
    assert cases["btc_regime_center"]["upside_beta"] == audit["full_252d"]["used"]
    assert cases["btc_high_beta"]["downside_beta"] == audit["downside_5y"]["bootstrap_10_90"][1]
    assert cases["btc_high_beta"]["upside_beta"] == audit["full_252d"]["bootstrap_10_90"][1]


def test_observed_assets_are_byte_equal_across_all_btc_cases() -> None:
    model = _fixture()
    history = model["history"]["series"]
    for case in model["forecast"]["scenarios"].values():
        assert case["paths"]["nasdaq"] == history["nasdaq_price"]
        assert case["paths"]["realty_income"] == history["realty_income_price"]
        assert case["paths"]["realty_income_total_return"] == history[
            "realty_income_total_return"]


def test_btc_center_path_compounds_observed_nasdaq_monthly_log_returns() -> None:
    model = _fixture()
    case = model["forecast"]["scenarios"]["btc_regime_center"]
    nasdaq = model["history"]["series"]["nasdaq_price"]
    expected_raw = [100.0]
    for previous, current in zip(nasdaq[:-1], nasdaq[1:], strict=True):
        market_return = np.log(current / previous)
        beta = case["downside_beta"] if market_return < 0 else case["upside_beta"]
        expected_raw.append(expected_raw[-1] * np.exp(beta * market_return))
    assert case["paths"]["bitcoin"] == [round(value, 1) for value in expected_raw]


def test_five_year_paths_keep_observed_anchor_and_no_btc_history_claim() -> None:
    model = _fixture()
    for case in model["forecast"]["scenarios"].values():
        assert all(path[0] == 100 for path in case["paths"].values())
        assert case["status"] == "counterfactual_not_observed"
        assert "probability" in case["band_semantics"]
    contract = model["forecast"]["counterfactual_contract"]
    assert contract["bitcoin_history_status"] == "not_available_before_2009"
    assert contract["probability_interpretation"] == "none"
    assert model["forecast"]["realty_income_sensitivity"]["used_numerically"] is False


def test_horizon_upgrade_reuses_audited_v2_inputs_and_appends_revision(tmp_path: Path) -> None:
    legacy = _legacy_v2(_fixture())
    _, stored, _ = _persist_snapshot(tmp_path, legacy, force=False)
    contract = tmp_path / "data/contracts/cross_asset_macro_assumptions.yaml"
    contract.parent.mkdir(parents=True)
    contract.write_text(
        (ROOT / "data/contracts/cross_asset_macro_assumptions.yaml").read_text(
            encoding="utf-8"), encoding="utf-8")
    ledger = tmp_path / "calibration/corrections.csv"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        "correction_id,target_table,target_key,status\n"
        f"CORR-HORIZON,cross_asset_snapshots,{stored['asof']},approved\n",
        encoding="utf-8")

    _, upgraded, changed = upgrade_cross_asset_horizon(
        tmp_path, generated_at=datetime(2026, 8, 5, tzinfo=timezone.utc))

    assert changed is True
    assert upgraded["schema_version"] == 3
    assert upgraded["forecast"]["source_snapshot_id"] == stored["snapshot_id"]
    assert upgraded["forecast"]["horizon_months"] == 60
    assert upgraded["revision"] == 2
    assert upgraded["correction_id"] == "CORR-HORIZON"


def test_realty_income_uses_observed_price_and_total_return_not_current_sensitivity() -> None:
    model = _fixture()
    scenarios = model["forecast"]["scenarios"]
    for case in scenarios.values():
        assert case["paths"]["realty_income"] == model["history"]["series"][
            "realty_income_price"]
        assert case["paths"]["realty_income_total_return"] == model["history"][
            "series"]["realty_income_total_return"]
    assert model["forecast"]["realty_income_sensitivity"]["used_numerically"] is False


def test_counterfactual_does_not_consume_generic_future_macro_assumptions() -> None:
    assumptions = _macro_assumptions()
    assumptions["scenarios"]["deleveraging"]["delta_10y_bp"].pop(6)
    baseline = _fixture()
    rebuilt = build_cross_asset(
        history_dates=[date.fromisoformat(label + "-01") for label in baseline["history"]["labels"]],
        history_nasdaq=baseline["history"]["series"]["nasdaq_price"],
        history_o_price=baseline["history"]["series"]["realty_income_price"],
        history_o_adjusted=baseline["history"]["series"]["realty_income_total_return"],
        current_dates=[date(2020, 1, 1) + timedelta(days=i) for i in range(320)],
        current_nasdaq=_price_path(320, .0004, .009),
        current_bitcoin=_price_path(320, .0007, .016),
        current_o_adjusted=_price_path(320, .00025, .004),
        anchors={"nasdaq": 1, "bitcoin": 1, "realty_income": 1},
        macro_assumptions=assumptions,
        realty_sensitivity=_realty_sensitivity(),
    )
    assert "macro_assumptions_version" not in rebuilt["forecast"]


def test_cross_asset_validator_rejects_path_length_drift() -> None:
    model = _fixture()
    model["forecast"]["scenarios"]["btc_regime_center"]["paths"]["bitcoin"].pop()
    with pytest.raises(CrossAssetError, match="length"):
        validate_cross_asset(model)


def test_same_asof_archive_is_noop_or_rejected_without_overwrite(tmp_path) -> None:
    model = _fixture()
    model["receipts"] = [{"response_sha256": "same", "fetched_at": "2026-08-03T00:00:00Z"}]
    _, persisted, _ = _persist_snapshot(tmp_path, model, force=False)
    archive = tmp_path / "data" / "cross_asset" / "archive" / f"{persisted['asof']}.json"
    before = archive.read_bytes()

    rerun = _fixture()
    rerun["generated_at"] = "2026-08-03T01:23:45+00:00"
    rerun["receipts"] = [{"response_sha256": "volatile", "fetched_at": "2026-08-03T01:23:45Z"}]
    latest, _, _ = _persist_snapshot(tmp_path, rerun, force=True)
    assert latest == tmp_path / "data" / "cross_asset" / "cross_asset_latest.json"
    assert archive.read_bytes() == before

    changed = _fixture()
    changed["history"]["summary"]["nasdaq_price_pct"] = -999.0
    with pytest.raises(CrossAssetError, match="approved"):
        _persist_snapshot(tmp_path, changed, force=True)
    assert archive.read_bytes() == before


def test_approved_correction_creates_revision_without_overwriting_original(tmp_path) -> None:
    model = _fixture()
    _, persisted, _ = _persist_snapshot(tmp_path, model, force=False)
    original = tmp_path / "data" / "cross_asset" / "archive" / f"{persisted['asof']}.json"
    original_bytes = original.read_bytes()
    ledger = tmp_path / "calibration" / "corrections.csv"
    ledger.parent.mkdir(parents=True)
    ledger.write_text(
        "correction_id,target_table,target_key,field_name,old_value,new_value,status,"
        "reason,evidence_uri,created_at,approved_at,reviewer\n"
        f"CORR-TEST,cross_asset_snapshots,{persisted['asof']},summary,old,new,"
        "approved,test,,2026-08-03,2026-08-03,tester\n",
        encoding="utf-8",
    )
    changed = _fixture()
    changed["history"]["summary"]["nasdaq_price_pct"] = -27.9
    _, revision, _ = _persist_snapshot(tmp_path, changed, force=True)
    corrected = original.with_name(f"{persisted['asof']}_CORR-TEST.json")
    assert original.read_bytes() == original_bytes
    assert corrected.exists()
    assert revision["revision"] == 2
    assert revision["correction_id"] == "CORR-TEST"


def test_refresh_excludes_intraday_us_market_bar(monkeypatch, tmp_path) -> None:
    monthly = _months(2000, 3, 74)
    daily = []
    cursor = date(2025, 7, 1)
    while cursor <= date(2026, 8, 3):
        if cursor.weekday() < 5:
            daily.append(cursor)
        cursor += timedelta(days=1)

    fetch_count = 0

    def fake_detail(symbol, start, end, interval):
        nonlocal fetch_count
        fetch_count += 1
        dates = monthly if interval == "1mo" else daily
        values = list(np.linspace(100, 160, len(dates)))
        return YahooPriceSeriesResult(
            dates=dates,
            closes=values,
            adjusted=values,
            receipt={
                "request_url": f"mock://{symbol}/{interval}",
                "response_sha256": f"raw-response-{fetch_count}",
                "fetched_at": f"2026-08-03T15:00:{fetch_count:02d}Z",
            },
            data_quality={"status": "ok", "dropped_rows": 0},
        )

    monkeypatch.setattr("ai_fc.cross_asset.feed.yahoo_price_series_detail", fake_detail)
    monkeypatch.setattr(
        "ai_fc.cross_asset.feed.yahoo_dividends",
        lambda *_args, **_kwargs: YahooDividendResult(
            [], [], {"request_url": "mock://dividends", "response_sha256": "div",
                     "fetched_at": "2026-08-03T15:00:00Z"}),
    )
    monkeypatch.setattr(
        "ai_fc.cross_asset.realty_income.load_macro_assumptions",
        lambda _root: _macro_assumptions())
    monkeypatch.setattr(
        "ai_fc.cross_asset.realty_income.load_event_registry",
        lambda _root: {"registry_version": "test", "events": []})
    monkeypatch.setattr(
        "ai_fc.cross_asset.realty_income.load_dividend_reference",
        lambda _root: {"annual": {}, "source_url": "mock://dividend-reference"})
    monkeypatch.setattr(
        "ai_fc.cross_asset.realty_income.fetch_fred_series",
        lambda series_id, _start: FredSeries(
            series_id, daily, list(np.linspace(3, 4, len(daily))),
            {"request_url": f"mock://{series_id}", "response_sha256": series_id,
             "fetched_at": "2026-08-03T15:00:00Z"}))
    monkeypatch.setattr(
        "ai_fc.cross_asset.realty_income.dividend_rows", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        "ai_fc.cross_asset.realty_income.build_rate_sensitivity",
        lambda **_kwargs: _realty_sensitivity())
    monkeypatch.setattr(
        "ai_fc.cross_asset.realty_income.build_event_study",
        lambda **_kwargs: {"status": "partial", "events": []})
    monkeypatch.setattr(
        "ai_fc.cross_asset.realty_income.build_history_preview",
        lambda *_args, **_kwargs: {"status": "ok", "labels": [], "series": {}})
    monkeypatch.setattr(
        "ai_fc.cross_asset.realty_income.append_dividends",
        lambda *_args, **_kwargs: (tmp_path / "dividends.csv", False))
    monkeypatch.setattr(
        "ai_fc.cross_asset.realty_income.persist_derived",
        lambda *_args, **_kwargs: (tmp_path / "derived.json", False))
    _, payload, _ = refresh_cross_asset(
        tmp_path,
        asof=date(2026, 8, 3),
        now=datetime(2026, 8, 3, 15, 0, tzinfo=ZoneInfo("America/New_York")),
    )
    assert payload["asof"] == "2026-07-31"
    receipts = list((tmp_path / "data" / "cross_asset" / "receipts").glob("*.json"))
    assert len(receipts) == 1

    _, rerun, changed = refresh_cross_asset(
        tmp_path,
        asof=date(2026, 8, 3),
        now=datetime(2026, 8, 3, 15, 30, tzinfo=ZoneInfo("America/New_York")),
    )
    assert rerun["asof"] == payload["asof"]
    assert changed is False
    assert len(list((tmp_path / "data" / "cross_asset" / "receipts").glob("*.json"))) == 1

    fresh_root = tmp_path / "fresh_then_lagging"
    _, fresh, _ = refresh_cross_asset(
        fresh_root,
        asof=date(2026, 8, 4),
        now=datetime(2026, 8, 4, 10, 0, tzinfo=ZoneInfo("America/New_York")),
    )
    assert fresh["asof"] == "2026-08-03"
    fresh_receipts = fresh_root / "data" / "cross_asset" / "receipts"
    assert len(list(fresh_receipts.glob("*.json"))) == 1

    daily[:] = [day for day in daily if day <= date(2026, 7, 31)]
    _, retained, changed = refresh_cross_asset(
        fresh_root,
        asof=date(2026, 8, 4),
        now=datetime(2026, 8, 4, 10, 30, tzinfo=ZoneInfo("America/New_York")),
    )
    assert retained["asof"] == "2026-08-03"
    assert changed is False
    assert len(list(fresh_receipts.glob("*.json"))) == 1


def test_dotcom_peak_reference_returns_measured_drawdown() -> None:
    rows = [date(2000, 3, 1), date(2006, 3, 1)]
    result = YahooPriceSeriesResult(
        dates=rows, closes=[100.0, 48.2], adjusted=[100.0, 48.2],
        receipt={}, data_quality={"status": "ok"},
    )
    reference = _dotcom_peak_reference(result)
    assert reference["status"] == "ok"
    assert reference["nasdaq_price_pct"] == -51.8


def test_content_addressed_receipt_keeps_first_capture_time(tmp_path) -> None:
    def result(fetched_at: str) -> YahooPriceSeriesResult:
        return YahooPriceSeriesResult(
            dates=[date(2026, 7, 31)], closes=[100.0], adjusted=[100.0],
            receipt={
                "request_url": "mock://same", "response_sha256": "same-body",
                "fetched_at": fetched_at,
            }, data_quality={"status": "ok"},
        )

    first = _persist_receipt_bundle(tmp_path, "2026-07-31", [result("2026-08-03T00:00:00Z")])
    original = first.read_text(encoding="utf-8")
    second = _persist_receipt_bundle(tmp_path, "2026-07-31", [result("2026-08-04T00:00:00Z")])
    assert first == second
    assert second.read_text(encoding="utf-8") == original
