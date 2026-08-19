from __future__ import annotations

import json
import math
import shutil
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from ai_fc.facts import ObservationFact
from ai_fc.timeseries.artifact import (
    append_correction,
    append_forecast,
    blocked_artifact,
    load_projection,
    verify_latest,
)
from ai_fc.timeseries.backtest import (
    OriginScore,
    diebold_mariano_hac,
    sample_crps,
    summarize_backtest,
)
from ai_fc.timeseries.contracts import load_contract
from ai_fc.timeseries.ledger import (
    append_facts,
    collect_alfred,
    normalize_alfred,
    persist_response,
    read_facts,
)
from ai_fc.timeseries.events import (
    EventFact,
    append_event,
    apply_event_overlay,
    persist_event_response,
    read_events,
)
from ai_fc.timeseries.features import build_release_state_history, fit_dynamic_factor_state
from ai_fc.timeseries.model import (
    deterministic_seed,
    ensemble_weights,
    fit_ridge_varx,
    simulate_correlated_paths,
    select_ridge_varx,
    summarize_paths,
)
from ai_fc.timeseries.workbook import export_timeseries_workbook


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _root(tmp_path: Path) -> Path:
    target = tmp_path / "repo"
    (target / "data/contracts").mkdir(parents=True)
    shutil.copy2(
        REPOSITORY_ROOT / "data/contracts/multivariate_timeseries_v1.yaml",
        target / "data/contracts/multivariate_timeseries_v1.yaml",
    )
    return target


def _fact(*, value: float, vintage_end: str | None = None) -> ObservationFact:
    return ObservationFact(
        source_id="alfred",
        series_id="NASDAQCOM",
        observation_time="2020-01-02",
        value=value,
        available_at="2020-01-03T13:30:00+00:00",
        vintage_start="2020-01-03T13:30:00+00:00",
        vintage_end=vintage_end,
        retrieved_at="2026-08-19T00:00:00+00:00",
        source_revision_id="NASDAQCOM:2020-01-03",
        source_hash="a" * 64,
        parser_version="test-v1",
        timezone="America/New_York",
        calendar_id="US_FED",
    )


def test_timeseries_contract_is_preregistered_and_isolated(tmp_path: Path) -> None:
    contract = load_contract(_root(tmp_path))
    assert contract["model_id"] == "shadow.mf_dfm_ridge_varx_v1"
    assert contract["target"]["horizons_sessions"] == [1, 5, 21, 63]
    assert contract["probability_contract"]["stored_unit"] == "fraction"
    assert contract["probability_contract"]["combine_with_official_forecasts"] is False
    assert contract["probability_contract"]["combine_with_scenario_v5_2"] is False
    assert contract["promotion"]["automatic_champion"] is False


def test_timeseries_workflow_checkpoints_raw_pit_before_model_work() -> None:
    workflow = (REPOSITORY_ROOT / ".github/workflows/timeseries-refresh.yml").read_text(
        encoding="utf-8",
    )
    refresh_position = workflow.index("Append ALFRED raw receipts and PIT observations")
    checkpoint_position = workflow.index("Checkpoint immutable PIT source history")
    fit_position = workflow.index("Refit DFM and expanding/rolling Ridge VARX")
    assert refresh_position < checkpoint_position < fit_position
    assert "git add data/timeseries docs/generated/inventory.generated.md" in workflow
    assert "data: checkpoint ALFRED PIT history" in workflow


def test_raw_first_receipt_redacts_api_key_and_gzip_is_deterministic(tmp_path: Path) -> None:
    root = _root(tmp_path)
    payload = b'{"observations":[]}'
    receipt = persist_response(
        root,
        series_id="NASDAQCOM",
        status=200,
        payload=payload,
        retrieved_at="2026-08-19T00:00:00+00:00",
        request_url="https://api.stlouisfed.org/fred/series/observations?series_id=NASDAQCOM&api_key=SECRET",
    )
    ledger = (root / "data/timeseries/ledgers/raw_receipts.jsonl").read_text(encoding="utf-8")
    assert "SECRET" not in ledger
    assert len(receipt.request_fingerprint) == 64
    raw = root / receipt.raw_path
    first = raw.read_bytes()
    persist_response(
        root,
        series_id="NASDAQCOM",
        status=200,
        payload=payload,
        retrieved_at="2026-08-19T00:00:00+00:00",
        request_url="https://api.stlouisfed.org/fred/series/observations?series_id=NASDAQCOM&api_key=DIFFERENT",
    )
    assert raw.read_bytes() == first


def test_alfred_history_batches_below_json_vintage_limit_and_preserves_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _root(tmp_path)
    vintage_dates = [
        (date(2000, 1, 1) + timedelta(days=index)).isoformat()
        for index in range(2_001)
    ]
    observation_windows: list[tuple[str, str]] = []

    def fake_fetch(spec: object, *, series_id: str, endpoint: str) -> tuple[int, bytes]:
        del series_id
        from urllib.parse import parse_qs, urlparse

        query = parse_qs(urlparse(spec.url).query)  # type: ignore[attr-defined]
        if endpoint == "vintage_dates":
            payload = {
                "count": len(vintage_dates),
                "vintage_dates": vintage_dates,
            }
        else:
            start = query["realtime_start"][0]
            end = query["realtime_end"][0]
            observation_windows.append((start, end))
            payload = {"observations": [{
                "date": "2000-01-03",
                "value": str(len(observation_windows)),
                "realtime_start": start,
                "realtime_end": end,
            }]}
        return 200, json.dumps(payload).encode()

    monkeypatch.setattr("ai_fc.timeseries.ledger._fetch_alfred", fake_fetch)
    result = collect_alfred(
        root,
        api_key="x" * 32,
        series_ids=["NASDAQCOM"],
        retrieved_at="2026-08-19T00:00:00+00:00",
        realtime_start="2000-01-01",
        realtime_end="2006-01-01",
    )

    assert result["series"][0]["vintage_count"] == 2_001
    assert result["series"][0]["batch_count"] == 2
    assert len(observation_windows) == 2
    assert observation_windows[0] == (vintage_dates[0], vintage_dates[1_499])
    assert observation_windows[1] == (vintage_dates[1_500], vintage_dates[-1])
    assert len(result["series"][0]["receipt_ids"]) == 3
    receipt_lines = (
        root / "data/timeseries/ledgers/raw_receipts.jsonl"
    ).read_text(encoding="utf-8").splitlines()
    assert len(receipt_lines) == 3
    assert result["facts"]["appended"] == 2


def test_alfred_vintage_closure_appends_explicit_supersedes(tmp_path: Path) -> None:
    root = _root(tmp_path)
    first = append_facts(root, [_fact(value=100.0)])
    second = append_facts(root, [_fact(value=100.0, vintage_end="2020-02-03T13:30:00+00:00")])
    assert first["appended"] == 1
    assert second["appended"] == 1
    assert second["corrected"] == 1
    rows = [json.loads(line) for line in (
        root / "data/timeseries/ledgers/observations.jsonl"
    ).read_text(encoding="utf-8").splitlines()]
    assert rows[1]["revision_seq"] == 1
    assert rows[1]["supersedes_observation_id"] == rows[0]["observation_id"]
    active = read_facts(root)
    assert len(active) == 1
    assert active[0].vintage_end == "2020-02-03T13:30:00+00:00"


def test_alfred_date_only_vintage_uses_conservative_end_of_day_availability() -> None:
    payload = json.dumps({"observations": [{
        "date": "2020-01-02", "value": "100", "realtime_start": "2020-01-03",
        "realtime_end": "9999-12-31",
    }]}).encode()
    fact = normalize_alfred(
        payload, series_id="NASDAQCOM", retrieved_at="2026-08-19T12:00:00+00:00",
    )[0]
    assert fact.available_at == "2020-01-04T04:59:59+00:00"


def _synthetic_var(seed: int = 7, rows: int = 1200):
    rng = np.random.default_rng(seed)
    endog = np.zeros((rows, 2), dtype=float)
    exog = rng.normal(scale=0.3, size=(rows, 1))
    transition = np.asarray([[0.45, -0.10], [0.12, 0.35]])
    beta = np.asarray([0.18, -0.08])
    covariance = np.asarray([[0.010, 0.006], [0.006, 0.012]])
    for index in range(1, rows):
        endog[index] = transition @ endog[index - 1] + beta * exog[index - 1, 0]
        endog[index] += rng.multivariate_normal(np.zeros(2), covariance)
    return endog, exog, transition, beta


def test_ridge_varx_recovers_synthetic_next_value_and_contributions() -> None:
    endog, exog, transition, beta = _synthetic_var()
    fit = fit_ridge_varx(
        endog,
        exog,
        lag=1,
        alpha=1e-4,
        endog_names=("nasdaq_return", "vix_change"),
        exog_names=("growth_factor",),
    )
    prediction = fit.predict(endog, exog[-1])
    expected = transition @ endog[-1] + beta * exog[-1, 0]
    assert np.max(np.abs(prediction - expected)) < 0.04
    contributions = fit.target_contributions(endog, exog[-1])
    assert abs(sum(contributions.values()) - prediction[0]) < 1e-12


def test_correlated_bootstrap_is_deterministic_and_quantiles_are_monotone() -> None:
    endog, exog, _, _ = _synthetic_var(rows=700)
    fit = fit_ridge_varx(
        endog,
        exog,
        lag=1,
        alpha=0.01,
        endog_names=("nasdaq_return", "vix_change"),
        exog_names=("growth_factor",),
    )
    kwargs = dict(
        fits=(fit, fit),
        weights=(0.5, 0.5),
        endog_history=endog,
        exog_last=exog[-1],
        anchor=100.0,
        path_count=500,
        horizon=63,
        block_length=10,
        ewma_lambda=0.97,
        seed=deterministic_seed("shadow.mf_dfm_ridge_varx_v1", 1, "2026-08-19"),
    )
    left = simulate_correlated_paths(**kwargs)
    right = simulate_correlated_paths(**kwargs)
    assert left["path_hash"] == right["path_hash"]
    assert np.array_equal(left["index_paths"], right["index_paths"])
    # Resampling vector rows preserves contemporaneous residual dependence.
    correlation = np.corrcoef(fit.residuals.T)[0, 1]
    innovations = left["innovations"].reshape(-1, 2)
    simulated_correlation = np.corrcoef(innovations.T)[0, 1]
    assert np.isfinite(correlation)
    assert abs(simulated_correlation - correlation) < 0.08
    summary = summarize_paths(left["index_paths"], anchor=100.0)
    for row in summary["horizons"].values():
        values = [row["quantiles"][key] for key in ("p10", "p25", "p50", "p75", "p90")]
        assert values == sorted(values)
        assert 0 <= row["probability_up"] <= 1
        assert 0 <= row["first_touch_minus_10"] <= 1


def test_ensemble_weight_bounds_and_history_fallback() -> None:
    assert ensemble_weights([], []) == (0.5, 0.5, "insufficient_52_origin_history")
    left, right, rule = ensemble_weights([0.1] * 52, [10.0] * 52)
    assert (left, right, rule) == (0.75, 0.25, "inverse_crps_52_origin")


def test_blocked_artifact_hides_numbers_and_replays(tmp_path: Path) -> None:
    root = _root(tmp_path)
    payload = blocked_artifact(
        root,
        as_of="2026-08-19",
        knowledge_cutoff="2026-08-19T12:00:00+00:00",
        reasons=["offline gate pending"],
    )
    path = append_forecast(root, payload)
    assert path.is_file()
    verified = verify_latest(root)
    assert verified["ok"] is True
    assert verified["customer_numbers_visible"] is False
    projection = load_projection(root)
    assert projection["status"] == "validation_pending"
    assert projection["horizons"] == {}
    assert projection["path"] == {}


def test_forecast_correction_is_append_only(tmp_path: Path) -> None:
    root = _root(tmp_path)
    row = {
        "correction_id": "c" * 64,
        "supersedes": "old",
        "replacement": "new",
        "reason": "parser correction",
        "corrected_at": "2026-08-19T12:00:00+00:00",
    }
    assert append_correction(root, row) is True
    assert append_correction(root, row) is False


def test_backtest_gate_hides_small_samples() -> None:
    samples = np.asarray([-0.02, 0.00, 0.01, 0.03])
    assert sample_crps(samples, 0.01) >= 0
    rows = [
        OriginScore(
            date=f"2020-01-{index + 1:02d}",
            horizon=horizon,
            actual_log_return=0.01,
            model_crps=0.01,
            baseline_crps={"random_walk": 0.011},
            median=0.01,
            p10=-0.02,
            p25=-0.005,
            p75=0.02,
            p90=0.04,
            direction_correct=True,
            first_touch_actual=False,
            first_touch_probability=0.1,
            expanding_crps=0.01,
            rolling_crps=0.01,
        )
        for index in range(10) for horizon in (1, 5, 21, 63)
    ]
    summary = summarize_backtest(rows)
    assert summary["status"] == "hold"
    assert summary["gate_pass"] is False
    assert any("250" in reason for reason in summary["reasons"])


def _event(
    identifier: str,
    *,
    scheduled: str,
    available: str,
    actual: float | None = None,
    outcome: float | None = None,
    gap: float = 0.0,
    relief: float = 0.0,
) -> EventFact:
    return EventFact(
        event_id=identifier,
        event_type="employment",
        source_id="market_consensus",
        scheduled_at=scheduled,
        available_at=available,
        retrieved_at=available,
        receipt_id=f"receipt-{identifier}",
        raw_sha256="b" * 64,
        consensus=0.0,
        model_nowcast=gap,
        policy_relief=relief,
        actual=actual,
        outcome_return_5d=outcome,
        unit="fraction",
    )


def test_event_actual_is_prohibited_before_release() -> None:
    with pytest.raises(ValueError, match="future event actual"):
        _event(
            "bad", scheduled="2026-09-01T12:30:00+00:00",
            available="2026-08-31T12:00:00+00:00", actual=0.1,
        )


def test_event_ledger_is_pit_and_overlay_does_not_change_varx_coefficients(tmp_path: Path) -> None:
    root = _root(tmp_path)
    history = []
    for index in range(12):
        event = _event(
            f"e{index}",
            scheduled=f"2025-{index + 1:02d}-02T13:30:00+00:00",
            available=f"2025-{index + 1:02d}-02T13:30:00+00:00",
            actual=float(index), outcome=(index - 5.0) / 1000.0,
            gap=(index - 5.0) / 10.0, relief=index / 100.0,
        )
        receipt = persist_event_response(
            root, source_id=event.source_id, series_id=event.event_type,
            payload=f"event-{index}".encode(), http_status=200,
            retrieved_at=event.retrieved_at, available_at=event.available_at,
            request_url=f"https://consensus.example/events/{index}?api_key=SECRET",
        )
        rate_receipt = persist_event_response(
            root, source_id="market_implied_rate_distribution", series_id="fed_rate_probability",
            payload=f"rates-{index}".encode(), http_status=200,
            retrieved_at=event.retrieved_at, available_at=event.available_at,
            request_url=f"https://rates.example/distribution/{index}?token=SECRET",
        )
        event = event.model_copy(update={
            "receipt_id": receipt.receipt_id, "raw_sha256": receipt.raw_sha256,
            "supporting_receipt_ids": (rate_receipt.receipt_id,),
        })
        assert append_event(root, event) is True
        history.append(event)
    future = _event(
        "future", scheduled="2026-09-04T12:30:00+00:00",
        available="2026-08-19T12:00:00+00:00", gap=0.6, relief=0.1,
    )
    receipt = persist_event_response(
        root, source_id=future.source_id, series_id=future.event_type,
        payload=b"future-event", http_status=200,
        retrieved_at=future.retrieved_at, available_at=future.available_at,
        request_url="https://consensus.example/events/future?token=SECRET",
    )
    rate_receipt = persist_event_response(
        root, source_id="market_implied_rate_distribution", series_id="fed_rate_probability",
        payload=b"future-rates", http_status=200,
        retrieved_at=future.retrieved_at, available_at=future.available_at,
        request_url="https://rates.example/distribution/future?api_key=SECRET",
    )
    future = future.model_copy(update={
        "receipt_id": receipt.receipt_id, "raw_sha256": receipt.raw_sha256,
        "supporting_receipt_ids": (rate_receipt.receipt_id,),
    })
    append_event(root, future)
    receipt_text = (root / "data/timeseries/ledgers/event_raw_receipts.jsonl").read_text(encoding="utf-8")
    assert "SECRET" not in receipt_text
    known = read_events(root, knowledge_cutoff="2026-08-19T12:00:00+00:00")
    paths = 100.0 * np.exp(np.linspace(-0.03, 0.03, 1200)[:, None] * np.arange(1, 64)[None, :] / 5)
    result, metadata = apply_event_overlay(
        paths, anchor=100.0, events=known, current_event=future,
        contract=load_contract(root), seed=7,
    )
    assert result.shape == paths.shape
    assert metadata["status"] == "applied_path_reweighting_only"
    assert metadata["core_coefficients_modified"] is False
    assert metadata["historical_event_count"] == 12


def test_diebold_mariano_uses_serial_dependence_hac() -> None:
    losses = np.sin(np.arange(80) / 6.0) * 0.01 - 0.002
    result = diebold_mariano_hac(losses, horizon=21)
    assert result["observations"] == 80
    assert result["hac_lags"] == 5
    assert result["statistic"] is not None
    assert 0 <= float(result["p_value"]) <= 1


def _series_fact(
    series_id: str, *, observation: str, available: str, value: float,
) -> ObservationFact:
    return ObservationFact(
        source_id="alfred",
        series_id=series_id,
        observation_time=observation,
        value=value,
        available_at=available,
        vintage_start=available,
        retrieved_at="2026-08-20T00:00:00+00:00",
        source_revision_id=f"{series_id}:{available}",
        source_hash="c" * 64,
        parser_version="test-v1",
        timezone="America/New_York",
        calendar_id="US_FED",
    )


def test_release_after_market_close_enters_only_next_completed_session() -> None:
    facts = [_series_fact(
        "NFCI", observation="2026-08-19", value=-0.2,
        available="2026-08-19T21:30:00+00:00",
    )]
    frame, _ = build_release_state_history(
        facts,
        session_dates=("2026-08-19", "2026-08-20"),
        knowledge_cutoff="2026-08-20T22:00:00+00:00",
    )
    assert np.isnan(frame.loc["2026-08-19", "NFCI_level"])
    assert frame.loc["2026-08-20", "NFCI_level"] == -0.2
    assert frame.loc["2026-08-20", "NFCI_age_days"] > 0


def test_inner_selection_cannot_see_rows_after_outer_training_end() -> None:
    endog, exog, _, _ = _synthetic_var(rows=900)
    kwargs = dict(
        endog_names=("nasdaq_return", "vix_change"),
        exog_names=("growth_factor",),
        lag_candidates=(1, 2), alpha_candidates=(0.01, 1.0), train_end=800,
    )
    first = select_ridge_varx(endog, exog, **kwargs)
    altered = endog.copy()
    altered[800:] = 1_000.0
    second = select_ridge_varx(altered, exog, **kwargs)
    assert first.lag == second.lag and first.alpha == second.alpha
    assert np.array_equal(first.coefficients, second.coefficients)


def test_log_return_paths_restore_index_exactly() -> None:
    returns = np.asarray([0.01, -0.02, 0.03])
    restored = 100.0 * np.exp(np.cumsum(returns))
    assert np.allclose(np.diff(np.log(np.r_[100.0, restored])), returns, atol=1e-15)


def test_workbook_jsonl_parquet_reconciliation(tmp_path: Path) -> None:
    root = _root(tmp_path)
    append_facts(root, [_fact(value=100.0)])
    path, summary = export_timeseries_workbook(root)
    assert path.is_file()
    assert summary["observations"] == 1
    assert summary["active_observations"] == 1
    assert summary["parquet_rows"] == 1
    assert summary["sheets"] == 8
    assert len(summary["sha256"]) == 64
    _, replay = export_timeseries_workbook(root)
    assert replay["sha256"] == summary["sha256"]


def test_dynamic_factor_mq_consumes_monthly_and_quarterly_ragged_edge() -> None:
    facts: list[ObservationFact] = []
    monthly = (
        "PAYEMS", "UNRATE", "INDPRO", "RSAFS", "HOUST",
        "CPIAUCSL", "CPILFESL", "PCEPI", "PCEPILFE",
    )
    for index in range(48):
        year, month = 2020 + index // 12, index % 12 + 1
        next_year, next_month = year + int(month == 12), 1 if month == 12 else month + 1
        observed = f"{year:04d}-{month:02d}-01"
        available = f"{next_year:04d}-{next_month:02d}-05T13:30:00+00:00"
        for offset, series_id in enumerate(monthly):
            facts.append(_series_fact(
                series_id, observation=observed, available=available,
                value=100.0 + offset + index * 0.2 + math.sin(index / 4.0),
            ))
        if month in (1, 4, 7, 10):
            facts.append(_series_fact(
                "GDPC1", observation=observed, available=available,
                value=20_000.0 + index * 12.0,
            ))
    result = fit_dynamic_factor_state(
        facts, knowledge_cutoff="2026-08-19T12:00:00+00:00",
    )
    assert result["states"]["growth_factor"] is not None
    assert result["states"]["inflation_factor"] is not None
    assert result["history"]["growth_factor"]
    assert result["history"]["inflation_factor"]


def test_later_vintage_cannot_mutate_earlier_release_feature_bytes() -> None:
    earlier = _series_fact(
        "NFCI", observation="2026-07-01", available="2026-07-03T14:00:00+00:00", value=-0.1,
    )
    later = _series_fact(
        "NFCI", observation="2026-08-01", available="2026-08-07T14:00:00+00:00", value=0.2,
    )
    kwargs = {
        "session_dates": ("2026-07-06", "2026-07-07"),
        "knowledge_cutoff": "2026-07-07T22:00:00+00:00",
    }
    before, manifest_before = build_release_state_history([earlier], **kwargs)
    after, manifest_after = build_release_state_history([earlier, later], **kwargs)
    assert before.to_json(double_precision=15) == after.to_json(double_precision=15)
    assert manifest_before == manifest_after
