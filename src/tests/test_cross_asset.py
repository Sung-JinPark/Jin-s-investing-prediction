from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pytest
import yaml

from ai_fc.cross_asset import (
    CrossAssetError,
    append_path_tracking_v2,
    _dotcom_peak_reference,
    _persist_receipt_bundle,
    _persist_snapshot,
    build_cross_asset,
    refresh_cross_asset,
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
    history_dates = _months(2000, 12, history_count)
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


def test_cross_asset_keeps_history_and_conditional_paths_separate() -> None:
    model = _fixture()
    assert model["probability_space"] == "scenario_conditional"
    assert model["history"]["bitcoin"]["status"] == "not_available"
    assert model["history"]["summary"]["nasdaq_price_pct"] == pytest.approx(-28.0)
    assert model["history"]["summary"]["realty_income_total_return_pct"] == pytest.approx(145.0)
    assert model["forecast"]["weights"]["status"] == "not_estimated"
    assert set(model["forecast"]["scenarios"]) == {
        "deleveraging", "easing_rotation", "soft_landing", "rates_stay_high"
    }
    assert all(
        len(path) == 13
        for scenario in model["forecast"]["scenarios"].values()
        for path in scenario["paths"].values()
    )


def test_path_tracking_v2_appends_three_assets_once(tmp_path: Path) -> None:
    model = _fixture()
    _, persisted, _ = _persist_snapshot(tmp_path, model, force=False)
    day = date.fromisoformat(persisted["asof"])
    prices = {
        asset: YahooPriceSeriesResult(
            [day], [persisted["anchors"][asset]], [persisted["anchors"][asset]], {}, {})
        for asset in ("nasdaq", "bitcoin", "realty_income")
    }
    assert append_path_tracking_v2(tmp_path, persisted, prices)
    assert not append_path_tracking_v2(tmp_path, persisted, prices)
    rows = (tmp_path / "data/cross_asset/path_tracking_v2.csv").read_text(
        encoding="utf-8").splitlines()
    assert len(rows) == 4
    assert "origin_snapshot_id" in rows[0]
    assert all(
        len(bound) == 13
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


def test_history_explicitly_excludes_2006_01_partial_bar() -> None:
    model = _fixture(history_count=62)
    assert model["history"]["labels"][-1] == "2005-12"
    assert model["history"]["period"] == "2000-12 to 2005-12"
    assert model["history"]["summary"]["nasdaq_price_pct"] == pytest.approx(-10.7)
    assert model["history"]["summary"]["realty_income_price_pct"] == pytest.approx(73.8)
    assert model["history"]["summary"]["realty_income_total_return_pct"] == pytest.approx(140.9)
    assert model["history"]["summary"]["realty_income_dividend_effect_pp"] == pytest.approx(67.1)


def test_validator_rejects_period_label_mismatch() -> None:
    model = _fixture()
    model["history"]["period"] = "2000-12 to 2006-01"
    with pytest.raises(CrossAssetError, match="period endpoints"):
        validate_cross_asset(model)


def test_beta_regime_is_selected_by_nasdaq_path_level() -> None:
    model = _fixture()
    soft = model["forecast"]["scenarios"]["soft_landing"]
    deleveraging = model["forecast"]["scenarios"]["deleveraging"]
    assert soft["beta_regime_by_month"][6] == "full_252d"
    assert deleveraging["beta_regime_by_month"][6] == "downside_5y"
    btc_full = model["forecast"]["beta_audit"]["bitcoin"]["full_252d"]
    assert btc_full["used"] == btc_full["measured"]
    assert not btc_full["lower_clipped"]


def test_easing_rotation_allows_divergence_after_initial_shock() -> None:
    paths = _fixture()["forecast"]["scenarios"]["easing_rotation"]["paths"]
    assert paths["bitcoin"][3] < 100
    assert paths["bitcoin"][-1] > paths["nasdaq"][-1]
    assert paths["realty_income"][-1] > 100


def test_realty_income_v2_keeps_initial_deleveraging_and_adds_refutation_path() -> None:
    scenarios = _fixture()["forecast"]["scenarios"]
    deleveraging = scenarios["deleveraging"]["paths"]["realty_income"]
    rates_high = scenarios["rates_stay_high"]["paths"]["realty_income"]
    easing = scenarios["easing_rotation"]["paths"]["realty_income"]
    assert min(deleveraging[:4]) < 100
    assert rates_high[-1] < easing[-1]
    assert scenarios["rates_stay_high"]["macro_assumptions"]["delta_10y_bp"][-1] == 40


def test_cross_asset_requires_preregistered_macro_assumptions() -> None:
    assumptions = _macro_assumptions()
    assumptions["scenarios"]["deleveraging"]["delta_10y_bp"].pop(6)
    with pytest.raises((CrossAssetError, KeyError)):
        model = _fixture()
        build_cross_asset(
            history_dates=[date.fromisoformat(label + "-01") for label in model["history"]["labels"]],
            history_nasdaq=model["history"]["series"]["nasdaq_price"],
            history_o_price=model["history"]["series"]["realty_income_price"],
            history_o_adjusted=model["history"]["series"]["realty_income_total_return"],
            current_dates=[date(2020, 1, 1) + timedelta(days=i) for i in range(320)],
            current_nasdaq=_price_path(320, .0004, .009),
            current_bitcoin=_price_path(320, .0007, .016),
            current_o_adjusted=_price_path(320, .00025, .004),
            anchors={"nasdaq": 1, "bitcoin": 1, "realty_income": 1},
            macro_assumptions=assumptions,
            realty_sensitivity=_realty_sensitivity(),
        )


def test_cross_asset_validator_rejects_path_length_drift() -> None:
    model = _fixture()
    model["forecast"]["scenarios"]["soft_landing"]["paths"]["bitcoin"].pop()
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
    monthly = _months(2000, 3, 71)
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


def test_dotcom_peak_reference_returns_measured_drawdown() -> None:
    rows = [date(2000, 3, 1), date(2005, 12, 1)]
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
